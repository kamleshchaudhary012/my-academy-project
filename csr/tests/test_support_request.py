"""
Unit Tests for CSRSupportRequest Model
======================================
Tests CSRSupportRequest creation, partial uniqueness constraint for pending requests,
status lifecycle choices, and relationship protections.
"""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from csr.models import (
    CSRSupportRequest,
    CSRSupportType,
    CSRSupportRequestStatus,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_csr_requirement,
    make_csr_support_request,
)

User = get_user_model()


class CSRSupportRequestModelTests(TestCase):
    """Test suite for CSRSupportRequest model behavior and partial unique constraint."""

    def setUp(self):
        self.company = make_company_profile()
        self.requirement = make_csr_requirement()

    def test_create_valid_support_request(self):
        """Creates a valid CSRSupportRequest and checks attributes."""
        req = CSRSupportRequest.objects.create(
            company=self.company,
            requirement=self.requirement,
            company_name_snapshot=self.company.company_name,
            spoc_name='Ananya Verma',
            spoc_email='ananya@company.com',
            spoc_phone='+919876543210',
            proposed_funding=Decimal('350000.00'),
            support_type=CSRSupportType.FINANCIAL_GRANT,
            message='Our CSR committee has approved this co-funding proposal.',
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )
        self.assertIsInstance(req.id, uuid.UUID)
        self.assertEqual(req.company, self.company)
        self.assertEqual(req.requirement, self.requirement)
        self.assertEqual(req.proposed_funding, Decimal('350000.00'))
        self.assertEqual(req.support_type, CSRSupportType.FINANCIAL_GRANT)
        self.assertEqual(req.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        self.assertIsNotNone(req.created_at)
        self.assertIsNotNone(req.updated_at)
        self.assertEqual(str(req), f"Support Request from {self.company.company_name} ({CSRSupportRequestStatus.PENDING_NGO_REVIEW})")

    def test_partial_uniqueness_prevents_simultaneous_pending_requests(self):
        """
        CRITICAL TEST: Database constraint unique_pending_csr_support_request
        MUST prevent a second simultaneous PENDING_NGO_REVIEW request from the same company for the same requirement.
        """
        # First pending request succeeds
        make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        # Second simultaneous pending request for same (company, requirement) MUST fail at DB level
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_support_request(
                    company=self.company,
                    requirement=self.requirement,
                    status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
                )

    def test_partial_uniqueness_allows_new_pending_after_prior_request_resolved(self):
        """
        CRITICAL TEST: When previous request is moved to REJECTED, ACCEPTED, or WITHDRAWN,
        a new PENDING_NGO_REVIEW request for the same (company, requirement) is permitted.
        """
        first_request = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        # Transition the first request to REJECTED
        first_request.status = CSRSupportRequestStatus.REJECTED
        first_request.rejection_reason = 'Scope mismatch with CSR focus area.'
        first_request.save()

        # Now creating a new PENDING_NGO_REVIEW request MUST SUCCEED
        second_request = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )
        self.assertIsNotNone(second_request.id)
        self.assertEqual(second_request.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)

        # Transition second request to WITHDRAWN
        second_request.status = CSRSupportRequestStatus.WITHDRAWN
        second_request.withdrawal_reason = 'Internal reprioritization.'
        second_request.save()

        # A third PENDING_NGO_REVIEW request can also be created
        third_request = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )
        self.assertIsNotNone(third_request.id)
        self.assertEqual(third_request.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)

    def test_different_companies_can_have_pending_requests_for_same_requirement(self):
        """Multiple distinct companies can simultaneously have pending requests for the same requirement."""
        company2 = make_company_profile()
        req1 = make_csr_support_request(company=self.company, requirement=self.requirement)
        req2 = make_csr_support_request(company=company2, requirement=self.requirement)
        self.assertEqual(req1.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        self.assertEqual(req2.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)

    def test_same_company_can_have_pending_requests_for_different_requirements(self):
        """A single company can simultaneously have pending requests for different requirements."""
        requirement2 = make_csr_requirement()
        req1 = make_csr_support_request(company=self.company, requirement=self.requirement)
        req2 = make_csr_support_request(company=self.company, requirement=requirement2)
        self.assertEqual(req1.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        self.assertEqual(req2.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)

    def test_reviewed_by_set_null_on_user_deletion(self):
        """Deleting reviewing user sets reviewed_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        req = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.ACCEPTED,
            reviewed_by=admin_user,
        )
        self.assertEqual(req.reviewed_by, admin_user)
        admin_user.delete()
        req.refresh_from_db()
        self.assertIsNone(req.reviewed_by)

    def test_full_clean_minimum_funding(self):
        """full_clean() enforces proposed_funding >= 1000.00."""
        req = CSRSupportRequest(
            company=self.company,
            requirement=self.requirement,
            company_name_snapshot=self.company.company_name,
            spoc_name='Jane',
            spoc_email='jane@company.com',
            proposed_funding=Decimal('999.00'),  # Minimum is 1000.00
            message='Message',
        )
        with self.assertRaises(ValidationError) as ctx:
            req.full_clean()
        self.assertIn('proposed_funding', ctx.exception.message_dict)
