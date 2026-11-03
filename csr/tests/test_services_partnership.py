"""
Unit Tests for CSR Partnership Service — Phase CSR-2.5
======================================================
Tests bilateral partnership formation, MoU activation, lifecycle status transitions,
participant access gating, and informational off-platform disbursement tracking.
"""

from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from users.models import User
from ngo.models import NGOProfile
from csr.models import (
    CSRPartnership,
    CSRPartnershipStatus,
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CompanyVerificationStatus,
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.services.partnership_service import (
    create_partnership_from_request,
    get_partnership,
    list_partnerships_for_user,
    activate_partnership,
    pause_partnership,
    resume_partnership,
    complete_partnership,
    cancel_partnership,
    record_off_platform_disbursement,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
)


class PartnershipServiceTests(TestCase):
    """Tests for bilateral CSR partnership lifecycle service."""

    def setUp(self):
        self.company_user_a = make_user(email="comp_a@example.com", role=User.Role.COMPANY)
        self.company_a = make_company_profile(user=self.company_user_a, company_name="Alpha Tech", verification_status=CompanyVerificationStatus.APPROVED)

        self.company_user_b = make_user(email="comp_b@example.com", role=User.Role.COMPANY)
        self.company_b = make_company_profile(user=self.company_user_b, company_name="Beta Retail", verification_status=CompanyVerificationStatus.APPROVED)

        self.ngo_user_a = make_user(email="ngo_a@example.com", role=User.Role.NGO)
        self.ngo_a = make_ngo_profile(user=self.ngo_user_a)

        self.ngo_user_b = make_user(email="ngo_b@example.com", role=User.Role.NGO)
        self.ngo_b = make_ngo_profile(user=self.ngo_user_b)

        self.admin_user = make_user(email="admin@example.com", role=User.Role.ADMIN)
        self.donor_user = make_user(email="donor@example.com", role=User.Role.DONOR)

        self.requirement_a = make_csr_requirement(ngo=self.ngo_a, status=CSRRequirementStatus.OPEN_FOR_CSR)
        self.support_request_a = make_csr_support_request(
            company=self.company_a,
            requirement=self.requirement_a,
            status=CSRSupportRequestStatus.ACCEPTED,
            proposed_funding=Decimal('300000.00'),
        )

    def test_create_partnership_from_request_success(self):
        """Creates bilateral partnership with valid code and PENDING_MOU status."""
        partnership = create_partnership_from_request(self.support_request_a)
        self.assertEqual(partnership.status, CSRPartnershipStatus.PENDING_MOU)
        self.assertEqual(partnership.company, self.company_a)
        self.assertEqual(partnership.ngo, self.ngo_a)
        self.assertEqual(partnership.agreed_funding_amount, Decimal('300000.00'))
        self.assertTrue(partnership.partnership_code.startswith("CSR-PT-"))

    def test_create_partnership_idempotency(self):
        """Multiple calls for the same support request return existing partnership."""
        pt1 = create_partnership_from_request(self.support_request_a)
        pt2 = create_partnership_from_request(self.support_request_a)
        self.assertEqual(pt1.id, pt2.id)

    def test_participant_access_scoping(self):
        """Corporate partner, NGO partner, and Admin can view; third-parties cannot."""
        partnership = create_partnership_from_request(self.support_request_a)

        # Authorized participants
        self.assertEqual(get_partnership(self.company_user_a, partnership.id).id, partnership.id)
        self.assertEqual(get_partnership(self.ngo_user_a, partnership.id).id, partnership.id)
        self.assertEqual(get_partnership(self.admin_user, partnership.id).id, partnership.id)

        # Unauthorized entities
        with self.assertRaises(CSRNotFoundError):
            get_partnership(self.company_user_b, partnership.id)
        with self.assertRaises(CSRNotFoundError):
            get_partnership(self.ngo_user_b, partnership.id)
        with self.assertRaises(CSRNotFoundError):
            get_partnership(self.donor_user, partnership.id)

    def test_activate_partnership_lifecycle(self):
        """Activating with MoU transitions PENDING_MOU -> ACTIVE and sets requirement to IN_EXECUTION."""
        partnership = create_partnership_from_request(self.support_request_a)
        mou_doc = SimpleUploadedFile("mou.pdf", b"%PDF-1.4 bilateral agreement", content_type="application/pdf")

        activated = activate_partnership(self.ngo_user_a, partnership.id, mou_file=mou_doc)
        self.assertEqual(activated.status, CSRPartnershipStatus.ACTIVE)
        self.assertTrue(bool(activated.signed_mou_document))

        # Check requirement status moved to IN_EXECUTION
        self.requirement_a.refresh_from_db()
        self.assertEqual(self.requirement_a.status, CSRRequirementStatus.IN_EXECUTION)

    def test_pause_and_resume_partnership(self):
        """Pause moves ACTIVE -> PAUSED; Resume moves PAUSED -> ACTIVE."""
        partnership = create_partnership_from_request(self.support_request_a)
        activate_partnership(self.company_user_a, partnership.id)

        paused = pause_partnership(self.ngo_user_a, partnership.id, reason="Awaiting site permissions")
        self.assertEqual(paused.status, CSRPartnershipStatus.PAUSED)

        resumed = resume_partnership(self.company_user_a, partnership.id)
        self.assertEqual(resumed.status, CSRPartnershipStatus.ACTIVE)

    def test_complete_partnership(self):
        """Completing partnership transitions ACTIVE -> COMPLETED and timestamps record."""
        partnership = create_partnership_from_request(self.support_request_a)
        activate_partnership(self.company_user_a, partnership.id)

        completed = complete_partnership(self.ngo_user_a, partnership.id)
        self.assertEqual(completed.status, CSRPartnershipStatus.COMPLETED)
        self.assertIsNotNone(completed.actual_completion_date)
        self.assertIsNotNone(completed.completed_at)

    def test_cancel_partnership_requires_reason(self):
        """Cancelling partnership transitions to CANCELLED and requires reason."""
        partnership = create_partnership_from_request(self.support_request_a)

        with self.assertRaises(CSRValidationError):
            cancel_partnership(self.company_user_a, partnership.id, reason="")

        cancelled = cancel_partnership(self.company_user_a, partnership.id, reason="Strategic withdrawal")
        self.assertEqual(cancelled.status, CSRPartnershipStatus.CANCELLED)

        # Terminal state cannot be cancelled again
        with self.assertRaises(CSRStateError):
            cancel_partnership(self.company_user_a, partnership.id, reason="Again")

    def test_record_off_platform_disbursement(self):
        """Informational off-platform disbursement increases reported total without payment mutations."""
        partnership = create_partnership_from_request(self.support_request_a)
        activate_partnership(self.company_user_a, partnership.id)

        # Record tranche 1 (₹1,00,000)
        updated = record_off_platform_disbursement(
            self.company_user_a,
            partnership.id,
            disbursed_amount=Decimal('100000.00'),
            notes="Tranche 1 RTGS UTR# 987654321",
        )
        self.assertEqual(updated.disbursed_amount_reported, Decimal('100000.00'))

        # Record tranche 2 (₹1,50,000)
        updated_2 = record_off_platform_disbursement(
            self.ngo_user_a,
            partnership.id,
            disbursed_amount=Decimal('150000.00'),
            notes="Tranche 2 received",
        )
        self.assertEqual(updated_2.disbursed_amount_reported, Decimal('250000.00'))

        # Audit history verifies disbursement entries
        history = CSRVerificationHistory.objects.filter(entity_id=partnership.id, entity_type=CSRAuditEntityType.PARTNERSHIP)
        self.assertTrue(history.exists())

    def test_list_partnerships_denies_unapproved_ngo(self):
        """list_partnerships_for_user raises CSROwnershipError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.DRAFT, is_active=False)
        with self.assertRaises(CSROwnershipError):
            list_partnerships_for_user(unapproved_user)

    def test_get_partnership_denies_unapproved_ngo(self):
        """get_partnership raises CSRNotFoundError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.DRAFT, is_active=False)
        partnership = create_partnership_from_request(self.support_request_a)
        with self.assertRaises(CSRNotFoundError):
            get_partnership(unapproved_user, partnership.id)

