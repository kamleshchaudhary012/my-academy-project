"""
Unit Tests for CSR Transactional Guarantees & Concurrency — Phase CSR-2.5
========================================================================
Tests database transaction atomicity, mid-flow failure rollbacks, concurrency
idempotency, and absolute isolation from financial payment pipelines.
"""

from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.db import transaction

from users.models import User
from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRPartnership,
    CSRPartnershipStatus,
    PartnershipMilestone,
    MilestoneStatus,
    CSRVerificationHistory,
)
from campaigns.models import MonetaryDonation, PaymentTransaction
from csr.services.support_request_service import accept_support_request
from csr.services.partnership_service import (
    create_partnership_from_request,
    record_off_platform_disbursement,
)
from csr.services.verification_service import approve_company
from csr.services.exceptions import CSRValidationError
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
)


class TransactionalAndConcurrencyServiceTests(TestCase):
    """Tests for transactional rollbacks, row locking, and financial pipeline isolation."""

    def setUp(self):
        self.company_user = make_user(email="comp_tx@example.com", role=User.Role.COMPANY)
        self.company = make_company_profile(
            user=self.company_user,
            company_name="Titan CSR Corp",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        self.ngo_user = make_user(email="ngo_tx@example.com", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user)

        self.admin_user = make_user(email="admin_tx@example.com", role=User.Role.ADMIN)

        self.requirement = make_csr_requirement(
            ngo=self.ngo,
            status=CSRRequirementStatus.OPEN_FOR_CSR,
            total_estimated_budget=Decimal('500000.00'),
            required_csr_funding=Decimal('400000.00'),
            committed_funding=Decimal('0.00'),
        )

        self.support_request = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
            proposed_funding=Decimal('250000.00'),
        )

    def test_mid_flow_failure_rollback_on_accept_support_request(self):
        """Simulated exception during partnership creation completely rolls back EOI acceptance and funding commit."""
        initial_committed = self.requirement.committed_funding

        # Patch create_partnership_from_request to raise an unexpected runtime error
        with patch('csr.services.support_request_service.create_partnership_from_request', side_effect=RuntimeError("Simulated crash mid-flow")):
            with self.assertRaises(RuntimeError):
                accept_support_request(self.ngo_user, self.support_request.id)

        # Verify DB state is pristine and completely rolled back
        self.support_request.refresh_from_db()
        self.assertEqual(self.support_request.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        self.assertIsNone(self.support_request.reviewed_by)

        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.committed_funding, initial_committed)

        # Ensure NO partnership was created
        self.assertFalse(CSRPartnership.objects.filter(support_request=self.support_request).exists())

    def test_concurrency_idempotency_on_accept_support_request(self):
        """Sequential or concurrent acceptance calls safely return the existing partnership without duplicate funding."""
        result_1 = accept_support_request(self.ngo_user, self.support_request.id)
        pt_1 = result_1['partnership']

        # Second accept call
        result_2 = accept_support_request(self.ngo_user, self.support_request.id)
        pt_2 = result_2['partnership']

        self.assertEqual(pt_1.id, pt_2.id)
        self.assertEqual(CSRPartnership.objects.filter(support_request=self.support_request).count(), 1)

        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.committed_funding, Decimal('250000.00'))

    def test_concurrency_idempotency_on_approve_company(self):
        """Repeat approval calls on company profile remain idempotent without corrupting audit status."""
        company_pending = make_company_profile(verification_status=CompanyVerificationStatus.PENDING_VERIFICATION)

        app_1 = approve_company(self.admin_user, company_pending.id)
        app_2 = approve_company(self.admin_user, company_pending.id)

        self.assertEqual(app_1.id, app_2.id)
        self.assertEqual(app_1.verification_status, CompanyVerificationStatus.APPROVED)

    def test_disbursement_recording_zero_payment_pipeline_side_effects(self):
        """Recording off-platform disbursements does NOT create or mutate MonetaryDonation or PaymentTransaction."""
        partnership = make_csr_partnership(
            company=self.company,
            ngo=self.ngo,
            requirement=self.requirement,
            support_request=self.support_request,
            status=CSRPartnershipStatus.ACTIVE,
        )

        initial_donations_count = MonetaryDonation.objects.count()
        initial_tx_count = PaymentTransaction.objects.count()

        # Record ₹50,000 disbursement
        updated = record_off_platform_disbursement(
            self.company_user,
            partnership.id,
            disbursed_amount=Decimal('50000.00'),
            notes="Bank transfer NEFT-12345",
        )

        self.assertEqual(updated.disbursed_amount_reported, Decimal('50000.00'))

        # Absolute verification that donation and payment tables remain 100% untouched
        self.assertEqual(MonetaryDonation.objects.count(), initial_donations_count)
        self.assertEqual(PaymentTransaction.objects.count(), initial_tx_count)
