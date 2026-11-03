"""
Unit Tests for CSRRequirement Model
===================================
Tests CSRRequirement creation, constraints, relationships, file paths, and status options.
"""

import shutil
import tempfile
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from ngo.models import NGOProfile
from csr.models import (
    CSRRequirement,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CSRRequirementStatus,
    requirement_proposal_doc_path,
    requirement_budget_doc_path,
    requirement_impact_doc_path,
)
from csr.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_csr_requirement,
    make_dummy_uploaded_file,
)

User = get_user_model()


class CSRRequirementModelTests(TestCase):
    """Test suite for CSRRequirement model behavior and rules."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.ngo = make_ngo_profile()
        self.creator = self.ngo.user

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_create_valid_csr_requirement(self):
        """Creates a valid CSRRequirement and verifies all field mappings."""
        today = date.today()
        req = CSRRequirement.objects.create(
            ngo=self.ngo,
            created_by=self.creator,
            title='Rural Solar Electrification',
            slug='rural-solar-electrification-2026',
            schedule_vii_category=ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY,
            state='Rajasthan',
            district='Jodhpur',
            location_scope=LocationScope.MULTI_DISTRICT,
            additional_districts=['Barmer', 'Jaisalmer'],
            beneficiary_demographic=BeneficiaryDemographic.RURAL_COMMUNITIES,
            target_beneficiary_count=1200,
            summary='Deploying solar microgrids in 5 remote villages.',
            detailed_description='Comprehensive 12-month solar installation and maintenance project.',
            expected_outcomes='Clean electricity access for 1200 rural households.',
            total_estimated_budget=Decimal('2500000.00'),
            required_csr_funding=Decimal('2000000.00'),
            committed_funding=Decimal('500000.00'),
            start_date=today,
            expected_completion_date=today + timedelta(days=365),
            status=CSRRequirementStatus.DRAFT,
        )
        self.assertIsInstance(req.id, uuid.UUID)
        self.assertEqual(req.ngo, self.ngo)
        self.assertEqual(req.created_by, self.creator)
        self.assertEqual(req.slug, 'rural-solar-electrification-2026')
        self.assertEqual(req.status, CSRRequirementStatus.DRAFT)
        self.assertEqual(len(req.additional_districts), 2)
        self.assertEqual(req.total_estimated_budget, Decimal('2500000.00'))
        self.assertEqual(req.required_csr_funding, Decimal('2000000.00'))
        self.assertEqual(req.committed_funding, Decimal('500000.00'))
        self.assertIsNotNone(req.created_at)
        self.assertIsNotNone(req.updated_at)
        self.assertEqual(str(req), f"Rural Solar Electrification ({CSRRequirementStatus.DRAFT})")

    def test_slug_uniqueness_enforced_at_db(self):
        """Duplicate slugs must raise IntegrityError at database level."""
        shared_slug = 'unique-project-slug'
        make_csr_requirement(ngo=self.ngo, slug=shared_slug)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_requirement(ngo=self.ngo, slug=shared_slug)

    def test_additional_districts_callable_default_independent(self):
        """Proves additional_districts default list is independent per instance."""
        req1 = make_csr_requirement(ngo=self.ngo)
        req2 = make_csr_requirement(ngo=self.ngo)

        self.assertEqual(req1.additional_districts, [])
        self.assertEqual(req2.additional_districts, [])

        req1.additional_districts.append('Nagpur')
        req1.save()

        req2.refresh_from_db()
        self.assertEqual(req2.additional_districts, [])

    def test_open_for_csr_and_status_choices(self):
        """CSRRequirement supports all 9 frozen status choices including OPEN_FOR_CSR."""
        req = make_csr_requirement(ngo=self.ngo)
        for status in CSRRequirementStatus.values:
            req.status = status
            req.save()
            req.refresh_from_db()
            self.assertEqual(req.status, status)
        self.assertEqual(CSRRequirementStatus.OPEN_FOR_CSR, 'OPEN_FOR_CSR')

    def test_reviewed_by_set_null_on_admin_deletion(self):
        """Deleting reviewing admin user sets reviewed_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        req = make_csr_requirement(
            ngo=self.ngo,
            status=CSRRequirementStatus.APPROVED,
            reviewed_by=admin_user,
        )
        self.assertEqual(req.reviewed_by, admin_user)
        admin_user.delete()
        req.refresh_from_db()
        self.assertIsNone(req.reviewed_by)

    def test_filefield_upload_paths_isolated(self):
        """Upload paths for proposal, budget, and impact assessment are generated correctly."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            req = make_csr_requirement(ngo=self.ngo)
            prop_file = make_dummy_uploaded_file(name='proposal.pdf')
            budget_file = make_dummy_uploaded_file(name='budget.pdf')
            impact_file = make_dummy_uploaded_file(name='impact.pdf')

            req.proposal_document = prop_file
            req.detailed_budget_document = budget_file
            req.impact_assessment_report = impact_file
            req.save()

            self.assertTrue(req.proposal_document.name.startswith(f'csr_docs/proposals/{req.id}/'))
            self.assertTrue(req.detailed_budget_document.name.startswith(f'csr_docs/budgets/{req.id}/'))
            self.assertTrue(req.impact_assessment_report.name.startswith(f'csr_docs/impact/{req.id}/'))

            # Test path functions directly
            self.assertTrue(requirement_proposal_doc_path(req, 'p.pdf').startswith(f'csr_docs/proposals/{req.id}/'))
            self.assertTrue(requirement_budget_doc_path(req, 'b.pdf').startswith(f'csr_docs/budgets/{req.id}/'))
            self.assertTrue(requirement_impact_doc_path(req, 'i.pdf').startswith(f'csr_docs/impact/{req.id}/'))

    def test_full_clean_minimum_budget_validations(self):
        """full_clean() rejects budgets below minimum thresholds."""
        today = date.today()
        req = CSRRequirement(
            ngo=self.ngo,
            created_by=self.creator,
            title='Low Budget Project',
            slug='low-budget-proj',
            schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
            state='Maharashtra',
            district='Pune',
            beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION,
            summary='Summary text',
            detailed_description='Detailed text',
            expected_outcomes='Outcomes',
            total_estimated_budget=Decimal('9999.00'),  # Minimum is 10000.00
            required_csr_funding=Decimal('9999.00'),    # Minimum is 10000.00
            committed_funding=Decimal('-1.00'),        # Minimum is 0.00
            start_date=today,
            expected_completion_date=today + timedelta(days=30),
        )
        with self.assertRaises(ValidationError) as ctx:
            req.full_clean()
        self.assertIn('total_estimated_budget', ctx.exception.message_dict)
        self.assertIn('required_csr_funding', ctx.exception.message_dict)
        self.assertIn('committed_funding', ctx.exception.message_dict)
