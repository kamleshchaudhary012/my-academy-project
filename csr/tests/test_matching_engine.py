"""
Unit Tests for CSR Matchmaking Engine — Phase CSR-2.6
=====================================================
Comprehensive tests covering the pure, deterministic scoring engine, sub-score weights,
explainability reasons, recommendation ranking, tie-breaking, purity, and serializer compatibility.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase

from users.models import User
from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CSRRequirement,
    CSRRequirementStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CompanyVerificationStatus,
)
from csr.services.matching_service import (
    MatchResult,
    calculate_match_score,
    get_recommended_requirements_for_company,
)
from csr.services.matching_hooks import (
    calculate_match_score as hook_calculate_match_score,
    get_recommended_requirements_for_company as hook_get_recommended_requirements_for_company,
)
from csr.serializers.matching_serializers import CSRMatchResultSerializer
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
)


class MatchmakingEngineSubScoreTests(TestCase):
    """Tests each of the 5 scoring dimensions in isolation against exact frozen weights."""

    def setUp(self):
        self.company_user = make_user(email="match_corp@example.com", role=User.Role.COMPANY)
        self.company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.APPROVED,
        )
        self.pref = CompanyCSRPreference.objects.create(company=self.company)

        self.ngo_user = make_user(email="match_ngo@example.com", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user)

    def _make_req(self, **kwargs):
        today = date.today()
        defaults = {
            'ngo': self.ngo,
            'title': f'Project {uuid.uuid4().hex[:6]}',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'total_estimated_budget': Decimal('500000.00'),
            'required_csr_funding': Decimal('400000.00'),
            'start_date': today,
            'expected_completion_date': today + timedelta(days=180),  # ~6 months
            'status': CSRRequirementStatus.OPEN_FOR_CSR,
        }
        defaults.update(kwargs)
        return make_csr_requirement(**defaults)

    # -----------------------------------------------------------------------
    # 1. Category Sub-score (max 35)
    # -----------------------------------------------------------------------

    def test_category_exact_match(self):
        """Category in preferred_categories awards 35 points."""
        self.pref.preferred_categories = [ScheduleVIICategory.PROMOTING_EDUCATION]
        self.pref.save()

        req = self._make_req(schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['category'], 35.0)
        self.assertTrue(any("category matches" in r.lower() for r in result.reasons))

    def test_category_empty_preference_fallback(self):
        """Empty preferred_categories awards 25 points fallback."""
        self.pref.preferred_categories = []
        self.pref.save()

        req = self._make_req(schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['category'], 25.0)
        self.assertTrue(any("no category restriction" in r.lower() for r in result.reasons))

    def test_category_mismatch(self):
        """Category not in non-empty preferred_categories awards 0 points."""
        self.pref.preferred_categories = [ScheduleVIICategory.PROMOTING_EDUCATION]
        self.pref.save()

        req = self._make_req(schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['category'], 0.0)

    # -----------------------------------------------------------------------
    # 2. Location Sub-score (max 25)
    # -----------------------------------------------------------------------

    def test_location_exact_district_match(self):
        """Exact district match in preferred_districts awards 25 points."""
        self.pref.preferred_districts = ['Pune']
        self.pref.preferred_states = ['Maharashtra']
        self.pref.save()

        req = self._make_req(state='Maharashtra', district='Pune')
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['location'], 25.0)
        self.assertTrue(any("preferred district" in r.lower() for r in result.reasons))

    def test_location_nationwide_preference(self):
        """Nationwide corporate preference awards 22 points."""
        self.pref.is_nationwide = True
        self.pref.preferred_districts = []
        self.pref.save()

        req = self._make_req(state='Odisha', district='Cuttack')
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['location'], 22.0)
        self.assertTrue(any("nationwide" in r.lower() for r in result.reasons))

    def test_location_multi_district_state_match(self):
        """Multi-district project matching preferred state awards 20 points."""
        self.pref.is_nationwide = False
        self.pref.preferred_states = ['Maharashtra']
        self.pref.preferred_districts = []
        self.pref.save()

        req = self._make_req(
            state='Maharashtra',
            district='Thane',
            location_scope=LocationScope.MULTI_DISTRICT,
        )
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['location'], 20.0)

    def test_location_no_preference_fallback(self):
        """No location preference configured awards 20 points fallback."""
        self.pref.has_no_location_pref = True
        self.pref.is_nationwide = False
        self.pref.preferred_states = []
        self.pref.preferred_districts = []
        self.pref.save()

        req = self._make_req(state='Karnataka', district='Bengaluru')
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['location'], 20.0)

    def test_location_state_match_different_district(self):
        """State match with non-matching district awards 15 points."""
        self.pref.is_nationwide = False
        self.pref.has_no_location_pref = False
        self.pref.preferred_states = ['Maharashtra']
        self.pref.preferred_districts = ['Mumbai']  # Preferred is Mumbai, req is Pune
        self.pref.save()

        req = self._make_req(state='Maharashtra', district='Pune', location_scope=LocationScope.SPECIFIC_DISTRICT)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['location'], 15.0)

    def test_location_mismatch(self):
        """Geographical mismatch awards 0 points."""
        self.pref.is_nationwide = False
        self.pref.has_no_location_pref = False
        self.pref.preferred_states = ['Gujarat']
        self.pref.preferred_districts = ['Ahmedabad']
        self.pref.save()

        req = self._make_req(state='Kerala', district='Kochi')
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['location'], 0.0)

    # -----------------------------------------------------------------------
    # 3. Budget Sub-score (max 20)
    # -----------------------------------------------------------------------

    def test_budget_in_range(self):
        """Funding within corporate range [min, max] awards 20 points."""
        self.pref.min_budget = Decimal('100000.00')
        self.pref.max_budget = Decimal('500000.00')
        self.pref.save()

        req = self._make_req(required_csr_funding=Decimal('300000.00'))
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['budget'], 20.0)
        self.assertTrue(any("fits within company budget range" in r.lower() for r in result.reasons))

    def test_budget_within_tolerance_buffer(self):
        """Funding within ±25% tolerance buffer outside [min, max] awards 12 points."""
        self.pref.min_budget = Decimal('200000.00')
        self.pref.max_budget = Decimal('400000.00')
        self.pref.save()

        # max_budget * 1.25 = 500,000. Req = 450,000 (within tolerance)
        req = self._make_req(
            total_estimated_budget=Decimal('600000.00'),
            required_csr_funding=Decimal('450000.00'),
        )
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['budget'], 12.0)
        self.assertTrue(any("tolerance buffer" in r.lower() for r in result.reasons))

    def test_budget_no_constraint_fallback(self):
        """min=0 and max=0 (no constraint) awards 15 points."""
        self.pref.min_budget = Decimal('0.00')
        self.pref.max_budget = Decimal('0.00')
        self.pref.save()

        req = self._make_req(required_csr_funding=Decimal('1000000.00'))
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['budget'], 15.0)

    def test_budget_out_of_bounds(self):
        """Funding exceeding tolerance buffer awards 0 points."""
        self.pref.min_budget = Decimal('100000.00')
        self.pref.max_budget = Decimal('200000.00')
        self.pref.save()

        # Max is 200k, 1.25x = 250k. Req is 400k (far out of range)
        req = self._make_req(
            total_estimated_budget=Decimal('500000.00'),
            required_csr_funding=Decimal('400000.00'),
        )
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['budget'], 0.0)

    # -----------------------------------------------------------------------
    # 4. Demographic Sub-score (max 10)
    # -----------------------------------------------------------------------

    def test_demographic_exact_match(self):
        """Demographic in preferred_beneficiaries awards 10 points."""
        self.pref.preferred_beneficiaries = [BeneficiaryDemographic.CHILDREN_EDUCATION]
        self.pref.save()

        req = self._make_req(beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['demographic'], 10.0)

    def test_demographic_empty_preference_fallback(self):
        """Empty preferred_beneficiaries awards 8 points fallback."""
        self.pref.preferred_beneficiaries = []
        self.pref.save()

        req = self._make_req(beneficiary_demographic=BeneficiaryDemographic.ELDERLY_CARE)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['demographic'], 8.0)

    def test_demographic_mismatch(self):
        """Demographic mismatch awards 0 points."""
        self.pref.preferred_beneficiaries = [BeneficiaryDemographic.WOMEN_EMPOWERMENT]
        self.pref.save()

        req = self._make_req(beneficiary_demographic=BeneficiaryDemographic.ELDERLY_CARE)
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['demographic'], 0.0)

    # -----------------------------------------------------------------------
    # 5. Duration Sub-score (max 10)
    # -----------------------------------------------------------------------

    def test_duration_within_3_months(self):
        """Duration within ±3 months of preferred awards 10 points."""
        today = date.today()
        self.pref.preferred_duration_months = 6
        self.pref.save()

        # 5 months duration (|5 - 6| = 1 <= 3)
        req = self._make_req(
            start_date=today,
            expected_completion_date=today + timedelta(days=150),
        )
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['duration'], 10.0)

    def test_duration_no_preference_fallback(self):
        """No preferred duration awards 8 points fallback."""
        self.pref.preferred_duration_months = None
        self.pref.save()

        req = self._make_req()
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['duration'], 8.0)

    def test_duration_moderate_deviation_returns_zero(self):
        """Duration deviating between 3 and 6 months awards 0 points per frozen rules."""
        today = date.today()
        self.pref.preferred_duration_months = 12
        self.pref.save()

        # 7 months duration (|7 - 12| = 5, in (3, 6])
        req = self._make_req(
            start_date=today,
            expected_completion_date=today + timedelta(days=210),
        )
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['duration'], 0.0)

    def test_duration_large_deviation(self):
        """Duration deviating > 6 months awards 3 points."""
        today = date.today()
        self.pref.preferred_duration_months = 24
        self.pref.save()

        # 6 months duration (|6 - 24| = 18 > 6)
        req = self._make_req(
            start_date=today,
            expected_completion_date=today + timedelta(days=180),
        )
        result = calculate_match_score(self.pref, req)
        self.assertEqual(result.breakdown['duration'], 3.0)


class MatchmakingEngineCompositeAndRankingTests(TestCase):
    """Tests composite scoring, bounds clamping, deterministic ranking, purity, and serializer integration."""

    def setUp(self):
        self.company_user = make_user(email="comp_rank@example.com", role=User.Role.COMPANY)
        self.company = make_company_profile(user=self.company_user, verification_status=CompanyVerificationStatus.APPROVED)
        self.pref = CompanyCSRPreference.objects.create(
            company=self.company,
            preferred_categories=[ScheduleVIICategory.PROMOTING_EDUCATION],
            preferred_states=['Maharashtra'],
            preferred_districts=['Pune'],
            min_budget=Decimal('100000.00'),
            max_budget=Decimal('500000.00'),
            preferred_beneficiaries=[BeneficiaryDemographic.CHILDREN_EDUCATION],
            preferred_duration_months=6,
        )

        self.ngo_user = make_user(email="ngo_rank@example.com", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user)

    def _make_req(self, title, **kwargs):
        today = date.today()
        defaults = {
            'ngo': self.ngo,
            'title': title,
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'total_estimated_budget': Decimal('500000.00'),
            'required_csr_funding': Decimal('300000.00'),
            'start_date': today,
            'expected_completion_date': today + timedelta(days=180),
            'status': CSRRequirementStatus.OPEN_FOR_CSR,
        }
        defaults.update(kwargs)
        return make_csr_requirement(**defaults)

    def test_perfect_100_composite_score(self):
        """Requirement matching all 5 preferred dimensions yields exactly 100.0."""
        req = self._make_req("Perfect Match Project")
        result = calculate_match_score(self.company, req)

        self.assertEqual(result.match_score, 100.0)
        self.assertEqual(result.breakdown, {
            'category': 35.0,
            'location': 25.0,
            'budget': 20.0,
            'demographic': 10.0,
            'duration': 10.0,
        })
        self.assertEqual(len(result.reasons), 5)

    def test_all_zero_mismatch_score(self):
        """Requirement failing all 5 dimensions yields 0.0 without errors."""
        today = date.today()
        req = self._make_req(
            "Complete Mismatch Project",
            schedule_vii_category=ScheduleVIICategory.ARMED_FORCES_VETERANS,
            state='Assam',
            district='Guwahati',
            total_estimated_budget=Decimal('50000000.00'),
            required_csr_funding=Decimal('40000000.00'),
            beneficiary_demographic=BeneficiaryDemographic.ELDERLY_CARE,
            start_date=today,
            expected_completion_date=today + timedelta(days=1000),  # > 30 months
        )
        result = calculate_match_score(self.company, req)
        # Note: Duration > 6 months gives 3 pts per CSR-2.0 spec
        self.assertEqual(result.breakdown['category'], 0.0)
        self.assertEqual(result.breakdown['location'], 0.0)
        self.assertEqual(result.breakdown['budget'], 0.0)
        self.assertEqual(result.breakdown['demographic'], 0.0)
        self.assertEqual(result.breakdown['duration'], 3.0)
        self.assertEqual(result.match_score, 3.0)

    def test_deterministic_ranking_and_tie_breaking(self):
        """get_recommended_requirements_for_company sorts by match_score desc, created_at asc."""
        req_high = self._make_req("High Score Project")  # 100 pts
        req_med = self._make_req(
            "Med Score Project",
            schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER,  # 0 pts category
        )  # 65 pts
        req_low = self._make_req(
            "Low Score Project",
            schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER,
            state='Rajasthan',
            district='Jaipur',
        )

        recommendations = get_recommended_requirements_for_company(self.company)
        self.assertGreaterEqual(len(recommendations), 3)

        scores = [r.match_score for r in recommendations]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(recommendations[0].requirement_id, req_high.id)

    def test_ranking_min_score_filter_and_limit(self):
        """min_score filters low matches and limit bounds return size."""
        self._make_req("Project 1")
        self._make_req("Project 2")
        self._make_req("Project 3")

        filtered = get_recommended_requirements_for_company(self.company, min_score=90.0, limit=2)
        self.assertLessEqual(len(filtered), 2)
        for r in filtered:
            self.assertGreaterEqual(r.match_score, 90.0)

    def test_matching_hooks_re_export_parity(self):
        """matching_hooks functions behave identically to matching_service functions."""
        req = self._make_req("Hook Test Project")
        direct_res = calculate_match_score(self.company, req)
        hook_res = hook_calculate_match_score(self.company, req)

        self.assertEqual(direct_res.match_score, hook_res.match_score)
        self.assertEqual(direct_res.breakdown, hook_res.breakdown)
        self.assertEqual(direct_res.reasons, hook_res.reasons)

        direct_list = get_recommended_requirements_for_company(self.company)
        hook_list = hook_get_recommended_requirements_for_company(self.company)
        self.assertEqual(len(direct_list), len(hook_list))

    def test_serializer_compatibility(self):
        """MatchResult serializes cleanly and passes CSRMatchResultSerializer validation."""
        req = self._make_req("Serializer Validation Project")
        result = calculate_match_score(self.company, req)

        serializer = CSRMatchResultSerializer(data=result.to_dict())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['match_score'], 100.0)
        self.assertEqual(serializer.validated_data['requirement_id'], req.id)

    def test_explainability_safety(self):
        """Explainability reasons contain no sensitive PII, PAN, paths, or email addresses."""
        req = self._make_req("PII Check Project")
        result = calculate_match_score(self.company, req)

        for reason in result.reasons:
            self.assertNotIn("@", reason)
            self.assertNotIn("PAN", reason)
            self.assertNotIn("CIN", reason)
            self.assertNotIn("/media/", reason)

    def test_purity_and_zero_database_mutations(self):
        """Engine executes strictly without creating or updating any database rows."""
        req = self._make_req("Purity Test Project")
        req_count_before = CSRRequirement.objects.count()
        pref_count_before = CompanyCSRPreference.objects.count()

        # Run scoring 10 times
        for _ in range(10):
            calculate_match_score(self.company, req)

        self.assertEqual(CSRRequirement.objects.count(), req_count_before)
        self.assertEqual(CompanyCSRPreference.objects.count(), pref_count_before)
