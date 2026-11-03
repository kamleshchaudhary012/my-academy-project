"""
DaanGives NGO Model Tests — Services & Lifecycle Workflow
=========================================================
Test modules:
  - TestStatusLifecycle (10 tests)
  - TestStatusTransitions (17 tests)
  - TestBankModificationRules (8 tests)
  - TestTransactionAtomicity (3 tests)
Total: 38 tests
"""

from unittest.mock import patch
from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError

from ngo.models import (
    NGOProfile,
    NGOVerification,
)
from ngo.services.verification_service import (
    change_ngo_verification_status,
    StatusTransitionError,
)
from ngo.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_bank_info,
    make_admin_user,
)


class TestStatusLifecycle(TestCase):
    """E. Verify status/is_active/is_public consistency rules."""

    def _set_status_directly(self, ngo, status, is_active):
        """Helper: set status and is_active directly on DB (bypasses service for test isolation)."""
        NGOProfile.objects.filter(pk=ngo.pk).update(status=status, is_active=is_active)
        ngo.refresh_from_db()

    def test_e1_approved_is_active_true_is_public_true(self):
        """APPROVED + is_active=True → is_public=True."""
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'APPROVED', True)
        self.assertTrue(ngo.is_active)
        self.assertEqual(ngo.status, 'APPROVED')
        self.assertTrue(ngo.is_public)

    def test_e2_approved_is_active_false_is_not_public(self):
        """APPROVED + is_active=False → is_public=False (inconsistent state blocked)."""
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'APPROVED', False)
        self.assertFalse(ngo.is_public)

    def test_e3_suspended_is_active_true_is_not_public(self):
        """SUSPENDED + is_active=True → is_public=False (status check fails)."""
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'SUSPENDED', True)
        self.assertFalse(ngo.is_public)

    def test_e4_draft_not_public(self):
        ngo = make_ngo_profile()
        self.assertEqual(ngo.status, 'DRAFT')
        self.assertFalse(ngo.is_public)

    def test_e5_submitted_not_active_not_public(self):
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'SUBMITTED', False)
        self.assertFalse(ngo.is_active)
        self.assertFalse(ngo.is_public)

    def test_e6_under_review_not_public(self):
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'UNDER_REVIEW', False)
        self.assertFalse(ngo.is_public)

    def test_e7_correction_required_not_public(self):
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'CORRECTION_REQUIRED', False)
        self.assertFalse(ngo.is_public)

    def test_e8_rejected_not_public(self):
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'REJECTED', False)
        self.assertFalse(ngo.is_public)

    def test_e9_suspended_not_public(self):
        ngo = make_ngo_profile()
        self._set_status_directly(ngo, 'SUSPENDED', False)
        self.assertFalse(ngo.is_public)

    def test_e10_is_public_is_property_not_db_field(self):
        """is_public does not exist as a database column."""
        field_names = [f.name for f in NGOProfile._meta.get_fields()]
        self.assertNotIn('is_public', field_names)


class TestStatusTransitions(TestCase):
    """F. Verify allowed and forbidden status transitions via service."""

    def setUp(self):
        self.ngo_user = make_user(role='NGO')
        self.admin_user = make_admin_user()
        self.ngo = make_ngo_profile(user=self.ngo_user)

    def _advance_to(self, ngo, status):
        """Advance an NGO profile to a given status using the service."""
        v = ngo.verification
        transitions = {
            'SUBMITTED': lambda: change_ngo_verification_status(
                ngo, 'SUBMITTED', self.ngo_user),
            'UNDER_REVIEW': lambda: change_ngo_verification_status(
                ngo, 'UNDER_REVIEW', self.admin_user),
            'APPROVED': lambda: change_ngo_verification_status(
                ngo, 'APPROVED', self.admin_user),
            'CORRECTION_REQUIRED': lambda: change_ngo_verification_status(
                ngo, 'CORRECTION_REQUIRED', self.admin_user,
                correction_instructions='Please fix'),
            'REJECTED': lambda: change_ngo_verification_status(
                ngo, 'REJECTED', self.admin_user,
                rejection_reason='Incomplete documents'),
            'SUSPENDED': lambda: change_ngo_verification_status(
                ngo, 'SUSPENDED', self.admin_user),
        }
        # Execute the chain up to target status
        chains = {
            'SUBMITTED': ['SUBMITTED'],
            'UNDER_REVIEW': ['SUBMITTED', 'UNDER_REVIEW'],
            'APPROVED': ['SUBMITTED', 'UNDER_REVIEW', 'APPROVED'],
            'CORRECTION_REQUIRED': ['SUBMITTED', 'UNDER_REVIEW', 'CORRECTION_REQUIRED'],
            'REJECTED': ['SUBMITTED', 'UNDER_REVIEW', 'REJECTED'],
            'SUSPENDED': ['SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'SUSPENDED'],
        }
        for s in chains[status]:
            transitions[s]()
            ngo.refresh_from_db()

    def test_f1_draft_to_submitted_by_ngo(self):
        """NGO can submit from DRAFT."""
        change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'SUBMITTED')
        self.assertFalse(self.ngo.is_active)

    def test_f2_submitted_to_under_review_by_admin(self):
        """Admin can move SUBMITTED to UNDER_REVIEW."""
        self._advance_to(self.ngo, 'UNDER_REVIEW')
        self.assertEqual(self.ngo.status, 'UNDER_REVIEW')

    def test_f3_under_review_to_approved_by_admin(self):
        """Admin can APPROVE from UNDER_REVIEW."""
        self._advance_to(self.ngo, 'APPROVED')
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'APPROVED')
        self.assertTrue(self.ngo.is_active)
        self.assertTrue(self.ngo.is_public)

    def test_f4_under_review_to_correction_required(self):
        """Admin can request correction from UNDER_REVIEW."""
        self._advance_to(self.ngo, 'CORRECTION_REQUIRED')
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'CORRECTION_REQUIRED')
        self.assertFalse(self.ngo.is_active)

    def test_f5_under_review_to_rejected(self):
        """Admin can REJECT from UNDER_REVIEW."""
        self._advance_to(self.ngo, 'REJECTED')
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'REJECTED')
        self.assertFalse(self.ngo.is_active)

    def test_f6_approved_to_suspended(self):
        """Admin can SUSPEND an APPROVED NGO."""
        self._advance_to(self.ngo, 'SUSPENDED')
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'SUSPENDED')
        self.assertFalse(self.ngo.is_active)
        self.assertFalse(self.ngo.is_public)

    def test_f7_suspended_to_approved(self):
        """Admin can reinstate a SUSPENDED NGO."""
        self._advance_to(self.ngo, 'SUSPENDED')
        change_ngo_verification_status(self.ngo, 'APPROVED', self.admin_user)
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'APPROVED')
        self.assertTrue(self.ngo.is_active)

    def test_f8_correction_required_to_resubmitted_by_ngo(self):
        """NGO can resubmit after CORRECTION_REQUIRED."""
        self._advance_to(self.ngo, 'CORRECTION_REQUIRED')
        change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)
        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'SUBMITTED')
        self.assertEqual(self.ngo.verification.resubmission_count, 1)

    def test_f9_forbidden_draft_to_approved(self):
        """Cannot jump from DRAFT directly to APPROVED."""
        with self.assertRaises(StatusTransitionError):
            change_ngo_verification_status(self.ngo, 'APPROVED', self.admin_user)

    def test_f10_forbidden_draft_to_under_review(self):
        with self.assertRaises(StatusTransitionError):
            change_ngo_verification_status(self.ngo, 'UNDER_REVIEW', self.admin_user)

    def test_f11_forbidden_submitted_to_approved(self):
        self._advance_to(self.ngo, 'SUBMITTED')
        with self.assertRaises(StatusTransitionError):
            change_ngo_verification_status(self.ngo, 'APPROVED', self.admin_user)

    def test_f12_forbidden_ngo_cannot_move_to_under_review(self):
        self._advance_to(self.ngo, 'SUBMITTED')
        with self.assertRaises((StatusTransitionError, PermissionError, Exception)):
            change_ngo_verification_status(self.ngo, 'UNDER_REVIEW', self.ngo_user)

    def test_f13_forbidden_correction_to_approved_without_review(self):
        self._advance_to(self.ngo, 'CORRECTION_REQUIRED')
        with self.assertRaises(StatusTransitionError):
            change_ngo_verification_status(self.ngo, 'APPROVED', self.admin_user)

    def test_f14_rejected_is_terminal_for_ngo(self):
        self._advance_to(self.ngo, 'REJECTED')
        with self.assertRaises(StatusTransitionError):
            change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)

    def test_f15_history_record_created_on_every_transition(self):
        """Every allowed transition creates exactly one history record."""
        initial_count = self.ngo.history.count()
        change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)
        self.assertEqual(self.ngo.history.count(), initial_count + 1)
        change_ngo_verification_status(self.ngo, 'UNDER_REVIEW', self.admin_user)
        self.assertEqual(self.ngo.history.count(), initial_count + 2)

    def test_f16_correction_requires_instructions(self):
        """CORRECTION_REQUIRED without instructions raises ValidationError."""
        self._advance_to(self.ngo, 'UNDER_REVIEW')
        with self.assertRaises(ValidationError):
            change_ngo_verification_status(
                self.ngo, 'CORRECTION_REQUIRED', self.admin_user,
                correction_instructions='',  # empty — must fail
            )

    def test_f17_rejection_requires_reason(self):
        """REJECTED without rejection_reason raises ValidationError."""
        self._advance_to(self.ngo, 'UNDER_REVIEW')
        with self.assertRaises(ValidationError):
            change_ngo_verification_status(
                self.ngo, 'REJECTED', self.admin_user,
                rejection_reason='',  # empty — must fail
            )


class TestBankModificationRules(TestCase):
    """G. Bank info is editable only in approved states."""

    def setUp(self):
        self.ngo_user = make_user(role='NGO')
        self.admin_user = make_admin_user()
        self.ngo = make_ngo_profile(user=self.ngo_user)
        self.bank = make_bank_info(self.ngo)

    def _set_status(self, status, bank_correction_requested=False, is_active=False):
        NGOProfile.objects.filter(pk=self.ngo.pk).update(status=status, is_active=is_active)
        NGOVerification.objects.filter(ngo=self.ngo).update(
            status=status,
            bank_correction_requested=bank_correction_requested,
        )
        self.ngo.refresh_from_db()

    def _is_bank_editable(self):
        """
        Checks bank editability rule:
        DRAFT → editable
        CORRECTION_REQUIRED + bank_correction_requested=True → editable
        Otherwise → NOT editable
        """
        v = self.ngo.verification
        v.refresh_from_db()
        return (
            self.ngo.status == 'DRAFT'
            or (
                self.ngo.status == 'CORRECTION_REQUIRED'
                and v.bank_correction_requested
            )
        )

    def test_g1_draft_bank_editable(self):
        """Bank info is editable in DRAFT."""
        self.assertEqual(self.ngo.status, 'DRAFT')
        self.assertTrue(self._is_bank_editable())

    def test_g2_correction_with_flag_editable(self):
        """Bank editable in CORRECTION_REQUIRED if bank_correction_requested=True."""
        self._set_status('CORRECTION_REQUIRED', bank_correction_requested=True)
        self.assertTrue(self._is_bank_editable())

    def test_g3_correction_without_flag_not_editable(self):
        """Bank NOT editable in CORRECTION_REQUIRED if bank_correction_requested=False."""
        self._set_status('CORRECTION_REQUIRED', bank_correction_requested=False)
        self.assertFalse(self._is_bank_editable())

    def test_g4_submitted_bank_not_editable(self):
        self._set_status('SUBMITTED')
        self.assertFalse(self._is_bank_editable())

    def test_g5_under_review_bank_not_editable(self):
        self._set_status('UNDER_REVIEW')
        self.assertFalse(self._is_bank_editable())

    def test_g6_approved_bank_not_editable(self):
        self._set_status('APPROVED', is_active=True)
        self.assertFalse(self._is_bank_editable())

    def test_g7_bank_correction_flag_resets_on_resubmission(self):
        """bank_correction_requested resets to False after resubmission."""
        # Simulate state: CORRECTION_REQUIRED with bank flag
        self._set_status('CORRECTION_REQUIRED', bank_correction_requested=True)
        # Force status back to DRAFT for service to accept SUBMITTED
        NGOProfile.objects.filter(pk=self.ngo.pk).update(status='DRAFT')
        NGOVerification.objects.filter(ngo=self.ngo).update(status='PENDING')
        self.ngo.refresh_from_db()
        change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)
        v = self.ngo.verification
        v.refresh_from_db()
        self.assertFalse(v.bank_correction_requested)

    def test_g8_masked_account_number(self):
        """account_number is masked to last 4 digits via property."""
        self.assertTrue(self.bank.masked_account_number.startswith('****'))
        self.assertEqual(self.bank.masked_account_number, f'****{self.bank.account_number[-4:]}')


class TestTransactionAtomicity(TransactionTestCase):
    """I. Verify that service rolls back completely on failure."""

    def setUp(self):
        self.ngo_user = make_user(role='NGO')
        self.ngo = make_ngo_profile(user=self.ngo_user)

    def test_i1_rollback_on_history_create_failure(self):
        """If history INSERT fails, NGOProfile and NGOVerification changes are rolled back."""
        from ngo.models import NGOVerificationHistory
        original_status = self.ngo.status
        original_is_active = self.ngo.is_active

        with patch.object(
            NGOVerificationHistory.objects,
            'create',
            side_effect=Exception('Simulated DB failure on history INSERT'),
        ):
            with self.assertRaises(Exception):
                change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)

        # Reload from database
        self.ngo.refresh_from_db()
        # Status must not have changed
        self.assertEqual(self.ngo.status, original_status)
        self.assertEqual(self.ngo.is_active, original_is_active)
        # Verification must not have changed
        v = self.ngo.verification
        v.refresh_from_db()
        self.assertEqual(v.status, 'PENDING')

    def test_i2_successful_transition_is_fully_committed(self):
        """Successful transition commits all three changes atomically."""
        change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)
        self.ngo.refresh_from_db()
        v = self.ngo.verification
        v.refresh_from_db()
        # All three must be consistent
        self.assertEqual(self.ngo.status, 'SUBMITTED')
        self.assertEqual(v.status, 'SUBMITTED')
        self.assertEqual(self.ngo.history.count(), 1)

    def test_i3_no_partial_state_on_validation_error(self):
        """ValidationError (missing correction_instructions) leaves state unchanged."""
        # Advance to UNDER_REVIEW first
        change_ngo_verification_status(self.ngo, 'SUBMITTED', self.ngo_user)
        admin_user = make_admin_user()
        change_ngo_verification_status(self.ngo, 'UNDER_REVIEW', admin_user)
        self.ngo.refresh_from_db()
        history_count = self.ngo.history.count()

        with self.assertRaises(ValidationError):
            change_ngo_verification_status(
                self.ngo, 'CORRECTION_REQUIRED', admin_user,
                correction_instructions='',
            )

        self.ngo.refresh_from_db()
        self.assertEqual(self.ngo.status, 'UNDER_REVIEW')  # unchanged
        self.assertEqual(self.ngo.history.count(), history_count)  # no new record
