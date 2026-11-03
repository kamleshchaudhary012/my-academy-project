"""
CSR Matchmaking Engine Service — Phase CSR-2.6
==============================================
Pure, deterministic, and explainable algorithmic scoring engine that ranks
CSRRequirements against corporate CompanyCSRPreference configurations.

Mathematical Formula (CSR-2.0 Section 11):
  Total Score = S_cat (35%) + S_loc (25%) + S_bud (20%) + S_dem (10%) + S_dur (10%)
  Where Total Score in [0.0, 100.0].
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, List, Dict, Any, Union, Tuple
from django.db.models import QuerySet

from csr.models import (
    CSRRequirement,
    CSRRequirementStatus,
    CompanyCSRPreference,
    CompanyProfile,
    LocationScope,
)


@dataclass
class MatchResult:
    """
    Data Transfer Object representing a deterministic matchmaking calculation result.
    Fully compatible with CSRMatchResultSerializer.
    """
    requirement_id: Union[uuid.UUID, str]
    match_score: float
    breakdown: Dict[str, float]
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            'requirement_id': str(self.requirement_id),
            'match_score': self.match_score,
            'breakdown': self.breakdown,
            'reasons': self.reasons,
        }

    def __getitem__(self, item: str) -> Any:
        return self.to_dict()[item]

    def get(self, item: str, default: Any = None) -> Any:
        return self.to_dict().get(item, default)


def _resolve_preference(preference_or_company: Any) -> Optional[CompanyCSRPreference]:
    """Extract or resolve CompanyCSRPreference from various entity types."""
    if preference_or_company is None:
        return None
    if isinstance(preference_or_company, CompanyCSRPreference):
        return preference_or_company
    if isinstance(preference_or_company, CompanyProfile):
        return getattr(preference_or_company, 'csr_preferences', None)
    if hasattr(preference_or_company, 'company_profile'):
        company = getattr(preference_or_company, 'company_profile', None)
        return getattr(company, 'csr_preferences', None) if company else None
    return None


def _calculate_project_duration_months(requirement: CSRRequirement) -> int:
    """Calculate project duration in months from start and expected completion dates."""
    start_d = getattr(requirement, 'start_date', None)
    end_d = getattr(requirement, 'expected_completion_date', None)
    if not start_d or not end_d:
        return 1

    month_diff = (end_d.year - start_d.year) * 12 + (end_d.month - start_d.month)
    if end_d.day < start_d.day:
        month_diff = max(0, month_diff - 1)

    # If within same month, round based on days
    days = (end_d - start_d).days
    approx_months = max(1, round(days / 30.4375))
    return approx_months if approx_months > 0 else max(1, month_diff)


# ===========================================================================
# Sub-score Calculators
# ===========================================================================

def _score_category(preference: Optional[CompanyCSRPreference], requirement: CSRRequirement) -> Tuple[float, Optional[str]]:
    """
    Category Sub-score (max 35 pts):
      - In preferred_categories: 35 pts
      - preferred_categories empty: 25 pts
      - Mismatch: 0 pts
    """
    category = getattr(requirement, 'schedule_vii_category', '')
    preferred = getattr(preference, 'preferred_categories', []) if preference else []

    if not preferred:
        return 25.0, "Company has no category restriction configured."

    if category in preferred:
        readable_cat = category.replace('_', ' ').title()
        return 35.0, f"Schedule VII category matches '{readable_cat}'."

    return 0.0, None


def _score_location(preference: Optional[CompanyCSRPreference], requirement: CSRRequirement) -> Tuple[float, Optional[str]]:
    """
    Location Sub-score (max 25 pts) in priority order:
      1. Exact District Match: 25 pts
      2. Corporate Nationwide preference (is_nationwide=True): 22 pts
      3. State Match / Multi-District scope: 20 pts
      4. Corporate No Location Preference (has_no_location_pref=True or unconfigured): 20 pts
      5. State match but different district: 15 pts
      6. Mismatch: 0 pts
    """
    if not preference:
        return 20.0, "Company has no location restriction configured."

    is_nationwide = getattr(preference, 'is_nationwide', False)
    has_no_pref = getattr(preference, 'has_no_location_pref', False)
    pref_states = [s.strip().lower() for s in (getattr(preference, 'preferred_states', []) or [])]
    pref_districts = [d.strip().lower() for d in (getattr(preference, 'preferred_districts', []) or [])]

    req_state = (getattr(requirement, 'state', '') or '').strip().lower()
    req_district = (getattr(requirement, 'district', '') or '').strip().lower()
    req_scope = getattr(requirement, 'location_scope', LocationScope.SPECIFIC_DISTRICT)
    additional_districts = [d.strip().lower() for d in (getattr(requirement, 'additional_districts', []) or [])]

    # 1. Exact District Match (primary or additional districts)
    all_req_districts = [req_district] + additional_districts
    district_match = any(d in pref_districts for d in all_req_districts if d)
    if pref_districts and district_match:
        matched_dist = getattr(requirement, 'district', '').title()
        return 25.0, f"Requirement located in preferred district: {matched_dist}."

    # 2. Nationwide preference
    if is_nationwide:
        return 22.0, "Company has nationwide location scope preference."

    # 3. State Match with multi-district or exact state list match
    state_matched = req_state in pref_states if pref_states else False
    if state_matched and req_scope == LocationScope.MULTI_DISTRICT:
        return 20.0, f"Multi-district project in preferred state: {getattr(requirement, 'state', '').title()}."

    # 4. No Location Preference configured
    if has_no_pref or (not pref_states and not pref_districts):
        return 20.0, "Company has no location restriction configured."

    # 5. State match with different district
    if state_matched:
        return 15.0, f"State matches preferred state: {getattr(requirement, 'state', '').title()}."

    # 6. Complete mismatch
    return 0.0, None


def _score_budget(preference: Optional[CompanyCSRPreference], requirement: CSRRequirement) -> Tuple[float, Optional[str]]:
    """
    Budget Sub-score (max 20 pts):
      Let R = required_csr_funding, minB = min_budget, maxB = max_budget
      - minB == 0 and maxB == 0: 15 pts
      - minB <= R <= maxB: 20 pts
      - within ±25% tolerance buffer: 12 pts
      - out of bounds: 0 pts
    """
    req_funding = getattr(requirement, 'required_csr_funding', None)
    if req_funding is None:
        return 0.0, None

    r = Decimal(str(req_funding))
    min_b = getattr(preference, 'min_budget', Decimal('0.00')) if preference else Decimal('0.00')
    max_b = getattr(preference, 'max_budget', Decimal('0.00')) if preference else Decimal('0.00')

    min_b = Decimal(str(min_b)) if min_b is not None else Decimal('0.00')
    max_b = Decimal(str(max_b)) if max_b is not None else Decimal('0.00')

    # 1. No budget constraint configured
    if min_b <= Decimal('0.00') and max_b <= Decimal('0.00'):
        return 15.0, "Company has no budget constraint configured."

    # 2. In range
    in_range = False
    if min_b > 0 and max_b > 0:
        in_range = (min_b <= r <= max_b)
    elif min_b > 0:
        in_range = (r >= min_b)
    elif max_b > 0:
        in_range = (r <= max_b)

    if in_range:
        return 20.0, f"Required funding of ₹{r:,.2f} fits within company budget range."

    # 3. Within ±25% tolerance buffer
    in_tolerance = False
    if min_b > 0 and max_b > 0:
        lower_bound = min_b * Decimal('0.75')
        upper_bound = max_b * Decimal('1.25')
        in_tolerance = (lower_bound <= r <= upper_bound)
    elif min_b > 0:
        in_tolerance = (r >= min_b * Decimal('0.75'))
    elif max_b > 0:
        in_tolerance = (r <= max_b * Decimal('1.25'))

    if in_tolerance:
        return 12.0, f"Required funding of ₹{r:,.2f} is within ±25% budget tolerance buffer."

    # 4. Out of bounds
    return 0.0, None


def _score_demographic(preference: Optional[CompanyCSRPreference], requirement: CSRRequirement) -> Tuple[float, Optional[str]]:
    """
    Beneficiary Demographic Sub-score (max 10 pts):
      - In preferred_beneficiaries: 10 pts
      - preferred_beneficiaries empty: 8 pts
      - Mismatch: 0 pts
    """
    demographic = getattr(requirement, 'beneficiary_demographic', '')
    preferred = getattr(preference, 'preferred_beneficiaries', []) if preference else []

    if not preferred:
        return 8.0, "Company has no beneficiary demographic restriction configured."

    if demographic in preferred:
        readable_dem = demographic.replace('_', ' ').title()
        return 10.0, f"Target demographic matches '{readable_dem}'."

    return 0.0, None


def _score_duration(preference: Optional[CompanyCSRPreference], requirement: CSRRequirement) -> Tuple[float, Optional[str]]:
    """
    Project Duration Sub-score (max 10 pts):
      Let D = duration_in_months, P = preferred_duration_months
      - No preferred duration: 8 pts
      - |D - P| <= 3 months: 10 pts
      - |D - P| > 6 months (large deviation): 3 pts
      - All other cases (e.g., 3 < |D - P| <= 6): 0 pts
    """
    pref_duration = getattr(preference, 'preferred_duration_months', None) if preference else None

    if pref_duration is None or pref_duration == 0:
        return 8.0, "Company has no project duration restriction configured."

    d = _calculate_project_duration_months(requirement)
    p = int(pref_duration)
    diff = abs(d - p)

    if diff <= 3:
        return 10.0, f"Project duration of ~{d} months is within ±3 months of preferred {p} months."
    elif diff > 6:
        return 3.0, f"Project duration of ~{d} months deviates by >6 months from preferred {p} months."
    else:
        return 0.0, None


# ===========================================================================
# Public Matchmaking Functions
# ===========================================================================

def calculate_match_score(
    company_or_preference: Any,
    requirement: CSRRequirement,
) -> MatchResult:
    """
    Calculate deterministic, explainable matchmaking score (0.0 to 100.0) between
    a company's CSR preference and a CSR requirement proposal.
    Pure functional calculation: Zero database mutations.
    """
    preference = _resolve_preference(company_or_preference)

    s_cat, reason_cat = _score_category(preference, requirement)
    s_loc, reason_loc = _score_location(preference, requirement)
    s_bud, reason_budget = _score_budget(preference, requirement)
    s_dem, reason_dem = _score_demographic(preference, requirement)
    s_dur, reason_dur = _score_duration(preference, requirement)

    breakdown = {
        'category': round(float(s_cat), 2),
        'location': round(float(s_loc), 2),
        'budget': round(float(s_bud), 2),
        'demographic': round(float(s_dem), 2),
        'duration': round(float(s_dur), 2),
    }

    raw_total = sum(breakdown.values())
    total_score = max(0.0, min(100.0, round(float(raw_total), 2)))

    # Collect explainability reasons for non-zero scores
    reasons: List[str] = []
    for r in [reason_cat, reason_loc, reason_budget, reason_dem, reason_dur]:
        if r:
            reasons.append(r)

    req_id = getattr(requirement, 'id', None) or uuid.uuid4()

    return MatchResult(
        requirement_id=req_id,
        match_score=total_score,
        breakdown=breakdown,
        reasons=reasons,
    )


def get_recommended_requirements_for_company(
    company_or_preference: Any,
    requirements: Optional[Union[QuerySet, List[CSRRequirement]]] = None,
    *,
    limit: Optional[int] = 10,
    min_score: float = 0.0,
) -> List[MatchResult]:
    """
    Compute compatibility scores for a set of requirements and return prioritized,
    ranked recommendations filtered by min_score.
    
    Ranking order:
      1. match_score descending
      2. requirement.created_at ascending (deterministic tiebreak)
    """
    if requirements is None:
        requirements = CSRRequirement.objects.filter(status=CSRRequirementStatus.OPEN_FOR_CSR)

    results: List[Tuple[MatchResult, Any]] = []

    for req in requirements:
        result = calculate_match_score(company_or_preference, req)
        if result.match_score >= min_score:
            created_at = getattr(req, 'created_at', None)
            results.append((result, created_at))

    # Deterministic sort: match_score desc, created_at asc (or requirement_id string)
    results.sort(
        key=lambda item: (-item[0].match_score, item[1] if item[1] is not None else str(item[0].requirement_id))
    )

    ranked_results = [item[0] for item in results]

    if limit is not None and limit > 0:
        ranked_results = ranked_results[:limit]

    return ranked_results
