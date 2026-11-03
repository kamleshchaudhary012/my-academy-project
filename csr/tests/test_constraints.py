"""
Unit Tests for CSR Database Constraints (18 Constraints)
========================================================
Directly verifies database-level enforcement of all 18 frozen constraints:
- 6 inline uniqueness rules
- 10 check constraints
- 2 Meta unique constraints
All tests assert IntegrityError within isolated transaction.atomic() blocks.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
    CSRSupportRequestStatus,
    ScheduleVIICategory,
    BeneficiaryDemographic,
)
from csr.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_company_profile,
    make_company_preference,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_partnership_milestone,
    generate_valid_cin,
    generate_valid_pan,
)

User = get_user_model()


class CSRDatabaseConstraintTests(TestCase):
    """Test suite directly proving PostgreSQL enforcement of all 18 frozen database constraints."""

    def setUp(self):
        self.ngo = make_ngo_profile()
        self.creator = self.ngo.user
        self.company = make_company_profile()

    # =======================================================================
    # 6 Inline Uniqueness Constraints
    # =======================================================================

    def test_constraint_01_company_cin_uniqueness(self):
        """1. CompanyProfile.cin_number uniqueness constraint."""
        cin = generate_valid_cin()
        make_company_profile(cin_number=cin)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_company_profile(cin_number=cin)

    def test_constraint_02_company_user_onetoone(self):
        """2. CompanyProfile.user OneToOne uniqueness constraint."""
        user = make_user(role=User.Role.COMPANY)
        make_company_profile(user=user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_company_profile(user=user)

    def test_constraint_03_preference_company_onetoone(self):
        """3. CompanyCSRPreference.company OneToOne uniqueness constraint."""
        make_company_preference(company=self.company)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_company_preference(company=self.company)

    def test_constraint_04_requirement_slug_uniqueness(self):
        """4. CSRRequirement.slug uniqueness constraint."""
        slug = f"unique-slug-{uuid.uuid4().hex[:8]}"
        make_csr_requirement(ngo=self.ngo, slug=slug)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_requirement(ngo=self.ngo, slug=slug)

    def test_constraint_05_partnership_code_uniqueness(self):
        """5. CSRPartnership.partnership_code uniqueness constraint."""
        code = f"CSR-CODE-{uuid.uuid4().hex[:8].upper()}"
        make_csr_partnership(partnership_code=code)
        sr2 = make_csr_support_request(status=CSRSupportRequestStatus.ACCEPTED)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_partnership(support_request=sr2, partnership_code=code)

    def test_constraint_06_partnership_support_request_onetoone(self):
        """6. CSRPartnership.support_request OneToOne uniqueness constraint."""
        sr = make_csr_support_request(status=CSRSupportRequestStatus.ACCEPTED)
        make_csr_partnership(support_request=sr)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_partnership(support_request=sr)

    # =======================================================================
    # 10 Check Constraints
    # =======================================================================

    def test_constraint_07_requirement_dates_valid(self):
        """7. check_csr_requirement_dates_valid: expected_completion_date >= start_date."""
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRRequirement.objects.create(
                    ngo=self.ngo,
                    created_by=self.creator,
                    title='Invalid Dates Req',
                    slug=f'inv-dates-{uuid.uuid4().hex[:8]}',
                    schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
                    state='Maharashtra',
                    district='Pune',
                    beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION,
                    summary='Summary',
                    detailed_description='Description',
                    expected_outcomes='Outcomes',
                    total_estimated_budget=Decimal('50000.00'),
                    required_csr_funding=Decimal('50000.00'),
                    committed_funding=Decimal('0.00'),
                    start_date=today,
                    expected_completion_date=today - timedelta(days=1),  # Violation
                )

    def test_constraint_08_requirement_budget_positive(self):
        """8. check_csr_requirement_budget_positive: total_estimated_budget >= 10000.00."""
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRRequirement.objects.create(
                    ngo=self.ngo,
                    created_by=self.creator,
                    title='Low Total Budget Req',
                    slug=f'low-budget-{uuid.uuid4().hex[:8]}',
                    schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
                    state='Maharashtra',
                    district='Pune',
                    beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION,
                    summary='Summary',
                    detailed_description='Description',
                    expected_outcomes='Outcomes',
                    total_estimated_budget=Decimal('9999.99'),  # Violation (< 10000)
                    required_csr_funding=Decimal('10000.00'),
                    committed_funding=Decimal('0.00'),
                    start_date=today,
                    expected_completion_date=today + timedelta(days=30),
                )

    def test_constraint_09_requirement_required_funding_positive(self):
        """9. check_csr_required_funding_positive: required_csr_funding >= 10000.00."""
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRRequirement.objects.create(
                    ngo=self.ngo,
                    created_by=self.creator,
                    title='Low Req Funding',
                    slug=f'low-req-fund-{uuid.uuid4().hex[:8]}',
                    schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
                    state='Maharashtra',
                    district='Pune',
                    beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION,
                    summary='Summary',
                    detailed_description='Description',
                    expected_outcomes='Outcomes',
                    total_estimated_budget=Decimal('20000.00'),
                    required_csr_funding=Decimal('9999.00'),  # Violation (< 10000)
                    committed_funding=Decimal('0.00'),
                    start_date=today,
                    expected_completion_date=today + timedelta(days=30),
                )

    def test_constraint_10_requirement_committed_funding_non_negative(self):
        """10. check_csr_committed_funding_non_negative: committed_funding >= 0.00."""
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRRequirement.objects.create(
                    ngo=self.ngo,
                    created_by=self.creator,
                    title='Neg Committed Funding',
                    slug=f'neg-commit-{uuid.uuid4().hex[:8]}',
                    schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
                    state='Maharashtra',
                    district='Pune',
                    beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION,
                    summary='Summary',
                    detailed_description='Description',
                    expected_outcomes='Outcomes',
                    total_estimated_budget=Decimal('50000.00'),
                    required_csr_funding=Decimal('50000.00'),
                    committed_funding=Decimal('-0.01'),  # Violation (< 0)
                    start_date=today,
                    expected_completion_date=today + timedelta(days=30),
                )

    def test_constraint_11_support_request_proposed_funding_positive(self):
        """11. check_csr_proposed_funding_positive: proposed_funding >= 1000.00."""
        req = make_csr_requirement(ngo=self.ngo)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRSupportRequest.objects.create(
                    company=self.company,
                    requirement=req,
                    company_name_snapshot=self.company.company_name,
                    spoc_name='Jane',
                    spoc_email='jane@company.com',
                    proposed_funding=Decimal('999.99'),  # Violation (< 1000)
                    message='Funding offer',
                )

    def test_constraint_12_partnership_dates_valid(self):
        """12. check_csr_partnership_dates_valid: target_completion_date >= execution_start_date."""
        req = make_csr_requirement(ngo=self.ngo)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRPartnership.objects.create(
                    company=self.company,
                    ngo=self.ngo,
                    requirement=req,
                    support_request=sr,
                    partnership_code=f'CSR-PART-{uuid.uuid4().hex[:8].upper()}',
                    agreed_funding_amount=Decimal('50000.00'),
                    disbursed_amount_reported=Decimal('0.00'),
                    execution_start_date=today,
                    target_completion_date=today - timedelta(days=1),  # Violation
                )

    def test_constraint_13_partnership_agreed_funding_positive(self):
        """13. check_csr_agreed_funding_positive: agreed_funding_amount >= 1000.00."""
        req = make_csr_requirement(ngo=self.ngo)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRPartnership.objects.create(
                    company=self.company,
                    ngo=self.ngo,
                    requirement=req,
                    support_request=sr,
                    partnership_code=f'CSR-PART-{uuid.uuid4().hex[:8].upper()}',
                    agreed_funding_amount=Decimal('999.99'),  # Violation (< 1000)
                    disbursed_amount_reported=Decimal('0.00'),
                    execution_start_date=today,
                    target_completion_date=today + timedelta(days=90),
                )

    def test_constraint_14_partnership_disbursed_funding_non_negative(self):
        """14. check_csr_disbursed_funding_non_negative: disbursed_amount_reported >= 0.00."""
        req = make_csr_requirement(ngo=self.ngo)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CSRPartnership.objects.create(
                    company=self.company,
                    ngo=self.ngo,
                    requirement=req,
                    support_request=sr,
                    partnership_code=f'CSR-PART-{uuid.uuid4().hex[:8].upper()}',
                    agreed_funding_amount=Decimal('50000.00'),
                    disbursed_amount_reported=Decimal('-0.01'),  # Violation (< 0)
                    execution_start_date=today,
                    target_completion_date=today + timedelta(days=90),
                )

    def test_constraint_15_milestone_sequence_positive(self):
        """15. check_csr_milestone_sequence_positive: sequence_number >= 1."""
        partnership = make_csr_partnership()
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PartnershipMilestone.objects.create(
                    partnership=partnership,
                    sequence_number=0,  # Violation (< 1)
                    title='Zero Seq Milestone',
                    description='Description',
                    target_completion_date=today + timedelta(days=30),
                )

    def test_constraint_16_milestone_completion_pct(self):
        """16. check_csr_milestone_completion_pct: completion_percentage <= 100."""
        partnership = make_csr_partnership()
        today = date.today()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PartnershipMilestone.objects.create(
                    partnership=partnership,
                    sequence_number=1,
                    title='Over 100 Pct Milestone',
                    description='Description',
                    target_completion_date=today + timedelta(days=30),
                    completion_percentage=101,  # Violation (> 100)
                )

    # =======================================================================
    # 2 Meta UniqueConstraints
    # =======================================================================

    def test_constraint_17_unique_partnership_milestone_sequence(self):
        """17. unique_partnership_milestone_sequence: unique (partnership, sequence_number)."""
        partnership = make_csr_partnership()
        make_partnership_milestone(partnership=partnership, sequence_number=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_partnership_milestone(partnership=partnership, sequence_number=1)

    def test_constraint_18_unique_pending_csr_support_request(self):
        """18. unique_pending_csr_support_request: unique (company, requirement) where status='PENDING_NGO_REVIEW'."""
        req = make_csr_requirement(ngo=self.ngo)
        make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.PENDING_NGO_REVIEW)
