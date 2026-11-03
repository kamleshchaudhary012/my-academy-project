"""
Unit Tests for CSR Verification Service — Phase CSR-2.5
=======================================================
Tests administrative moderation workflows for corporate profiles and
CSR requirements, including approvals, rejections, suspensions, and change requests.
"""

from decimal import Decimal
from django.test import TestCase

from users.models import User
from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.services.verification_service import (
    approve_company,
    reject_company,
    suspend_company,
    request_company_changes,
    approve_requirement,
    reject_requirement,
    suspend_requirement,
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
)


class VerificationServiceTests(TestCase):
    """Tests for administrative verification workflows and security boundaries."""

    def setUp(self):
        self.admin_user = make_user(email="admin@example.com", role=User.Role.ADMIN)
        self.non_admin_user = make_user(email="nonadmin@example.com", role=User.Role.COMPANY)
        self.inactive_admin = make_user(email="inactive_admin@example.com", role=User.Role.ADMIN, is_active=False)

        self.company_user = make_user(email="comp@example.com", role=User.Role.COMPANY)
        self.company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )

        self.ngo_user = make_user(email="ngo@example.com", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user)
        self.requirement = make_csr_requirement(
            ngo=self.ngo,
            status=CSRRequirementStatus.PENDING_REVIEW,
        )

    def test_non_admin_users_denied_verification_actions(self):
        """Non-admin and inactive admin users cannot execute moderation actions."""
        with self.assertRaises(CSROwnershipError):
            approve_company(self.non_admin_user, self.company.id)
        with self.assertRaises(CSROwnershipError):
            approve_company(self.inactive_admin, self.company.id)
        with self.assertRaises(CSROwnershipError):
            approve_requirement(self.non_admin_user, self.requirement.id)

    def test_approve_company_success_and_idempotency(self):
        """Admin approves company profile, setting status to APPROVED and recording audit history."""
        approved = approve_company(self.admin_user, self.company.id, review_notes="All MCA credentials validated.")
        self.assertEqual(approved.verification_status, CompanyVerificationStatus.APPROVED)
        self.assertEqual(approved.verified_by, self.admin_user)
        self.assertIsNotNone(approved.verified_at)

        # Audit ledger record written
        history = CSRVerificationHistory.objects.filter(entity_id=self.company.id, entity_type=CSRAuditEntityType.COMPANY)
        self.assertTrue(history.exists())
        self.assertEqual(history.first().new_status, CompanyVerificationStatus.APPROVED)

        # Repeat call is idempotent
        repeat = approve_company(self.admin_user, self.company.id)
        self.assertEqual(repeat.verification_status, CompanyVerificationStatus.APPROVED)

    def test_reject_company_requires_reason(self):
        """Admin rejecting company requires non-empty reason and sets status to REJECTED."""
        with self.assertRaises(CSRValidationError):
            reject_company(self.admin_user, self.company.id, reason="")

        rejected = reject_company(self.admin_user, self.company.id, reason="Invalid CIN number")
        self.assertEqual(rejected.verification_status, CompanyVerificationStatus.REJECTED)
        self.assertEqual(rejected.rejection_reason, "Invalid CIN number")

    def test_suspend_company(self):
        """Admin can suspend an approved company."""
        approve_company(self.admin_user, self.company.id)
        suspended = suspend_company(self.admin_user, self.company.id, reason="Compliance breach")
        self.assertEqual(suspended.verification_status, CompanyVerificationStatus.SUSPENDED)
        self.assertEqual(suspended.suspension_reason, "Compliance breach")

    def test_request_company_changes(self):
        """Admin requests changes moving company from PENDING_VERIFICATION back to DRAFT."""
        changed = request_company_changes(self.admin_user, self.company.id, notes="Please re-upload PAN with higher resolution.")
        self.assertEqual(changed.verification_status, CompanyVerificationStatus.DRAFT)
        self.assertEqual(changed.rejection_reason, "Please re-upload PAN with higher resolution.")

    def test_approve_requirement_success_and_idempotency(self):
        """Admin approves proposal, moving to OPEN_FOR_CSR by default."""
        approved = approve_requirement(self.admin_user, self.requirement.id, publish_open_for_csr=True)
        self.assertEqual(approved.status, CSRRequirementStatus.OPEN_FOR_CSR)
        self.assertEqual(approved.reviewed_by, self.admin_user)
        self.assertIsNotNone(approved.reviewed_at)

        # Audit ledger recorded
        history = CSRVerificationHistory.objects.filter(entity_id=self.requirement.id, entity_type=CSRAuditEntityType.REQUIREMENT)
        self.assertTrue(history.exists())

        # Repeat call is idempotent
        repeat = approve_requirement(self.admin_user, self.requirement.id)
        self.assertEqual(repeat.status, CSRRequirementStatus.OPEN_FOR_CSR)

    def test_reject_and_suspend_requirement(self):
        """Reject and suspend requirements with mandatory reasons."""
        with self.assertRaises(CSRValidationError):
            reject_requirement(self.admin_user, self.requirement.id, reason="")

        rejected = reject_requirement(self.admin_user, self.requirement.id, reason="Budget unrealistic")
        self.assertEqual(rejected.status, CSRRequirementStatus.REJECTED)

        # Suspended requirement
        approved_req = make_csr_requirement(ngo=self.ngo, status=CSRRequirementStatus.OPEN_FOR_CSR)
        suspended = suspend_requirement(self.admin_user, approved_req.id, reason="Investigation pending")
        self.assertEqual(suspended.status, CSRRequirementStatus.SUSPENDED)
