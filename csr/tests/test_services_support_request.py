"""
Unit Tests for CSR Support Request Service — Phase CSR-2.5
==========================================================
Tests Expression of Interest (EOI) creation, verification gating, duplicate
prevention, NGO acceptance workflows, automatic partnership formation, and tenant isolation.
"""

from decimal import Decimal
from django.test import TestCase

from users.models import User
from ngo.models import NGOProfile
from csr.models import (
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CompanyProfile,
    CompanyVerificationStatus,
    CSRSupportType,
    CSRPartnership,
    CSRPartnershipStatus,
)
from csr.services.support_request_service import (
    create_support_request,
    get_support_request,
    list_inbox_for_ngo,
    list_outbox_for_company,
    withdraw_support_request,
    accept_support_request,
    reject_support_request,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
    CSRPermissionError,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
)


class SupportRequestServiceTests(TestCase):
    """Tests for CSR support request lifecycle service."""

    def setUp(self):
        self.company_user_a = make_user(email="comp_a@example.com", role=User.Role.COMPANY)
        self.company_a = make_company_profile(
            user=self.company_user_a,
            company_name="Apex Corp",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        self.company_user_b = make_user(email="comp_b@example.com", role=User.Role.COMPANY)
        self.company_b = make_company_profile(
            user=self.company_user_b,
            company_name="Beta Corp",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        self.unverified_company_user = make_user(email="unver@example.com", role=User.Role.COMPANY)
        self.unverified_company = make_company_profile(
            user=self.unverified_company_user,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )

        self.ngo_user_a = make_user(email="ngo_a@example.com", role=User.Role.NGO)
        self.ngo_a = make_ngo_profile(user=self.ngo_user_a)

        self.ngo_user_b = make_user(email="ngo_b@example.com", role=User.Role.NGO)
        self.ngo_b = make_ngo_profile(user=self.ngo_user_b)

        self.requirement_a = make_csr_requirement(
            ngo=self.ngo_a,
            status=CSRRequirementStatus.OPEN_FOR_CSR,
            total_estimated_budget=Decimal('500000.00'),
            required_csr_funding=Decimal('400000.00'),
            committed_funding=Decimal('0.00'),
        )

    def _sample_eoi_data(self, **kwargs):
        defaults = {
            'spoc_name': 'Ramesh Kumar',
            'spoc_email': 'ramesh@apex.com',
            'spoc_phone': '+919876543210',
            'proposed_funding': Decimal('200000.00'),
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'message': 'We are pleased to express interest in funding your digital classroom initiative.',
        }
        defaults.update(kwargs)
        return defaults

    def test_create_support_request_success(self):
        """Verified corporate user can create an EOI for an OPEN_FOR_CSR requirement."""
        data = self._sample_eoi_data()
        req = create_support_request(self.company_user_a, self.requirement_a.id, data)
        self.assertEqual(req.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        self.assertEqual(req.company, self.company_a)
        self.assertEqual(req.company_name_snapshot, "Apex Corp")
        self.assertEqual(req.proposed_funding, Decimal('200000.00'))

    def test_create_support_request_unverified_company_rejected(self):
        """Unverified company cannot create support requests (raises CSRPermissionError)."""
        data = self._sample_eoi_data()
        with self.assertRaises(CSRPermissionError):
            create_support_request(self.unverified_company_user, self.requirement_a.id, data)

    def test_create_support_request_non_open_requirement_rejected(self):
        """Cannot create support request for requirement in DRAFT or PENDING_REVIEW."""
        draft_req = make_csr_requirement(ngo=self.ngo_a, status=CSRRequirementStatus.DRAFT)
        with self.assertRaises(CSRStateError):
            create_support_request(self.company_user_a, draft_req.id, self._sample_eoi_data())

    def test_create_support_request_duplicate_active_rejected(self):
        """Duplicate active EOI for same (company, requirement) is rejected (raises CSRConflictError)."""
        create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())
        with self.assertRaises(CSRConflictError):
            create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())

    def test_withdraw_support_request_lifecycle(self):
        """Company can withdraw pending request with reason; non-pending cannot be withdrawn."""
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())

        # Empty reason rejected
        with self.assertRaises(CSRValidationError):
            withdraw_support_request(self.company_user_a, eoi.id, reason="")

        # Withdraws successfully
        withdrawn = withdraw_support_request(self.company_user_a, eoi.id, reason="Budget reallocation")
        self.assertEqual(withdrawn.status, CSRSupportRequestStatus.WITHDRAWN)
        self.assertEqual(withdrawn.withdrawal_reason, "Budget reallocation")

        # Company B attempting to withdraw Company A request -> CSRNotFoundError
        eoi_2 = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())
        with self.assertRaises(CSRNotFoundError):
            withdraw_support_request(self.company_user_b, eoi_2.id, reason="Malicious withdrawal")

    def test_accept_support_request_creates_partnership_and_updates_funding(self):
        """NGO acceptance transitions EOI to ACCEPTED, forms CSRPartnership, and increments committed funding."""
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data(proposed_funding=Decimal('400000.00')))

        result = accept_support_request(self.ngo_user_a, eoi.id)
        accepted_eoi = result['support_request']
        partnership = result['partnership']

        self.assertEqual(accepted_eoi.status, CSRSupportRequestStatus.ACCEPTED)
        self.assertIsNotNone(partnership)
        self.assertEqual(partnership.company, self.company_a)
        self.assertEqual(partnership.ngo, self.ngo_a)
        self.assertEqual(partnership.status, CSRPartnershipStatus.PENDING_MOU)

        # Requirement committed funding updated and status moved to PARTNERED (since 400k == 400k)
        self.requirement_a.refresh_from_db()
        self.assertEqual(self.requirement_a.committed_funding, Decimal('400000.00'))
        self.assertEqual(self.requirement_a.status, CSRRequirementStatus.PARTNERED)

    def test_accept_support_request_idempotency(self):
        """Re-accepting an already ACCEPTED request returns existing partnership without duplicate funding."""
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data(proposed_funding=Decimal('200000.00')))
        result_1 = accept_support_request(self.ngo_user_a, eoi.id)

        # Second accept call
        result_2 = accept_support_request(self.ngo_user_a, eoi.id)
        self.assertEqual(result_1['partnership'].id, result_2['partnership'].id)

        # Ensure committed funding did NOT double
        self.requirement_a.refresh_from_db()
        self.assertEqual(self.requirement_a.committed_funding, Decimal('200000.00'))

    def test_reject_support_request_lifecycle(self):
        """NGO rejection transitions EOI to REJECTED with mandatory reason."""
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())

        with self.assertRaises(CSRValidationError):
            reject_support_request(self.ngo_user_a, eoi.id, reason="")

        rejected = reject_support_request(self.ngo_user_a, eoi.id, reason="Scope mismatch")
        self.assertEqual(rejected.status, CSRSupportRequestStatus.REJECTED)
        self.assertEqual(rejected.rejection_reason, "Scope mismatch")

    def test_cross_ngo_acceptance_denied(self):
        """NGO B cannot accept or reject NGO A's support requests."""
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())

        with self.assertRaises(CSRNotFoundError):
            accept_support_request(self.ngo_user_b, eoi.id)

        with self.assertRaises(CSRNotFoundError):
            reject_support_request(self.ngo_user_b, eoi.id, reason="Malicious reject")

    def test_list_inbox_denies_unapproved_ngo(self):
        """list_inbox_for_ngo raises CSROwnershipError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.DRAFT, is_active=False)
        with self.assertRaises(CSROwnershipError):
            list_inbox_for_ngo(unapproved_user)

    def test_accept_support_request_denies_unapproved_ngo(self):
        """accept_support_request raises CSROwnershipError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.REJECTED, is_active=False)
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())
        with self.assertRaises(CSROwnershipError):
            accept_support_request(unapproved_user, eoi.id)

    def test_reject_support_request_denies_unapproved_ngo(self):
        """reject_support_request raises CSROwnershipError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.SUSPENDED, is_active=False)
        eoi = create_support_request(self.company_user_a, self.requirement_a.id, self._sample_eoi_data())
        with self.assertRaises(CSROwnershipError):
            reject_support_request(unapproved_user, eoi.id, reason="Reason")

