"""
CSR Matching Hooks
==================
Re-exports matchmaking engine services for compatibility with platform service hooks.
"""

from typing import Optional, List, Dict, Any, Union
from django.db.models import QuerySet

from csr.models import CSRRequirement
from csr.services.matching_service import (
    MatchResult,
    calculate_match_score as _calculate_match_score,
    get_recommended_requirements_for_company as _get_recommended_requirements_for_company,
)


def calculate_match_score(company_profile, requirement: CSRRequirement) -> MatchResult:
    """
    Calculate deterministic match score between a corporate profile and a requirement.
    """
    return _calculate_match_score(company_profile, requirement)


def get_recommended_requirements_for_company(
    company_profile,
    requirements: Optional[Union[QuerySet, List[CSRRequirement]]] = None,
    *,
    limit: Optional[int] = 10,
    min_score: float = 0.0,
) -> List[MatchResult]:
    """
    Fetch prioritized, ranked matched CSR requirements for a company.
    """
    return _get_recommended_requirements_for_company(
        company_profile,
        requirements=requirements,
        limit=limit,
        min_score=min_score,
    )
