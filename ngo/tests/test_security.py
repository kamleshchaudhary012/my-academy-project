"""
DaanGives NGO Model Tests — Security, IDOR & Immutability
=========================================================
Test modules:
  - TestNGOOwnership (3 tests)
  - TestHistoryImmutability (8 tests)
  - TestSecurityAndIDOR (7 tests)
Total: 18 tests
"""

from django.test import TestCase
from django.db import IntegrityError
from django.core.exceptions import PermissionDenied

from ngo.models import (
    NGOProfile,
    NGODocument,
    NGOVerification,
    NGOVerificationHistory,
    ImmutableRecordError,
)
from ngo.services.verification_service import (
    change_ngo_verification_status,
    reopen_ngo_application,
    ResubmissionLimitError,
)
from ngo.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_admin_user,
)


class TestNGOOwnership(TestCase):
    """B. Enforce one profile per user."""

    def test_b1_one_user_one_profile(self):
        """One user cannot create two NGOProfile records."""
        user = make_user(role='NGO')
        make_ngo_profile(user=user)
        with self.assertRaises(IntegrityError):
            # Bypass make_ngo_profile to attempt direct duplicate
            NGOProfile.objects.create(
                user=user,
                legal_name='Second NGO',
                display_name='Second NGO',
                category='EDUCATION',
                description='B' * 50,
                year_established=2015,
                official_email='other@testngo.org',
                official_phone='+911234567891',
            )

    def test_b2_different_users_can_have_separate_profiles(self):
        """Two different users can each have one NGO profile."""
        user1 = make_user(email='ngo1@test.com', role='NGO')
        user2 = make_user(email='ngo2@test.com', role='NGO')
        p1 = make_ngo_profile(user=user1)
        p2 = make_ngo_profile(user=user2)
        self.assertNotEqual(p1.pk, p2.pk)

    def test_b3_ngo_profile_owned_by_correct_user(self):
        """NGOProfile.user points to the correct user."""
        user = make_user(role='NGO')
        profile = make_ngo_profile(user=user)
        self.assertEqual(profile.user, user)
        # OneToOne reverse works
        self.assertEqual(user.ngo_profile, profile)


class TestHistoryImmutability(TestCase):
    """H. Verify NGOVerificationHistory cannot be mutated."""

    def setUp(self):
        self.ngo = make_ngo_profile()
        self.record = NGOVerificationHistory.objects.create(
            ngo=self.ngo,
            actor_type='SYSTEM',
            previous_status='PENDING',
            new_status='SUBMITTED',
            reason='Test',
        )

    def test_h1_existing_save_rejected(self):
        """Calling .save() on existing history raises ImmutableRecordError."""
        with self.assertRaises(ImmutableRecordError):
            self.record.reason = 'Modified'
            self.record.save()

    def test_h2_instance_delete_rejected(self):
        """Calling .delete() on a history instance raises ImmutableRecordError."""
        with self.assertRaises(ImmutableRecordError):
            self.record.delete()

    def test_h3_queryset_update_rejected(self):
        """QuerySet.update() raises ImmutableRecordError."""
        with self.assertRaises(ImmutableRecordError):
            NGOVerificationHistory.objects.filter(pk=self.record.pk).update(reason='Modified')

    def test_h4_queryset_delete_rejected(self):
        """QuerySet.delete() raises ImmutableRecordError."""
        with self.assertRaises(ImmutableRecordError):
            NGOVerificationHistory.objects.filter(pk=self.record.pk).delete()

    def test_h5_bulk_update_rejected(self):
        """Manager.bulk_update() raises ImmutableRecordError."""
        with self.assertRaises(ImmutableRecordError):
            NGOVerificationHistory.objects.bulk_update([self.record], ['reason'])

    def test_h6_new_record_creation_succeeds(self):
        """objects.create() on a NEW record is allowed."""
        new_record = NGOVerificationHistory.objects.create(
            ngo=self.ngo,
            actor_type='ADMIN',
            previous_status='SUBMITTED',
            new_status='UNDER_REVIEW',
        )
        self.assertIsNotNone(new_record.pk)

    def test_h7_history_record_persists_after_creation(self):
        """History record can be read after creation."""
        fetched = NGOVerificationHistory.objects.get(pk=self.record.pk)
        self.assertEqual(fetched.previous_status, 'PENDING')
        self.assertEqual(fetched.new_status, 'SUBMITTED')

    def test_h8_service_creates_history_record(self):
        """change_ngo_verification_status() creates exactly one history record."""
        ngo_user = make_user(role='NGO')
        ngo = make_ngo_profile(user=ngo_user)
        before = ngo.history.count()
        change_ngo_verification_status(ngo, 'SUBMITTED', ngo_user)
        self.assertEqual(ngo.history.count(), before + 1)
        latest = ngo.history.first()
        self.assertEqual(latest.previous_status, 'DRAFT')
        self.assertEqual(latest.new_status, 'SUBMITTED')
        self.assertEqual(latest.actor_type, 'NGO')


class TestSecurityAndIDOR(TestCase):
    """J. Object ownership and cross-NGO access prevention at model/service level."""

    def setUp(self):
        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.admin_user = make_admin_user()
        self.ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.ngo_b = make_ngo_profile(user=self.ngo_user_b)

    def test_j1_ngo_a_cannot_submit_ngo_b_profile(self):
        """NGO A user cannot submit NGO B's profile via service."""
        with self.assertRaises(PermissionDenied):
            # ngo_user_a is trying to submit ngo_b
            change_ngo_verification_status(self.ngo_b, 'SUBMITTED', self.ngo_user_a)

    def test_j2_ngo_b_profile_belongs_to_correct_user(self):
        """NGO B profile's user is ngo_user_b, not ngo_user_a."""
        self.assertEqual(self.ngo_b.user, self.ngo_user_b)
        self.assertNotEqual(self.ngo_b.user, self.ngo_user_a)

    def test_j3_document_ngo_association(self):
        """Documents are correctly associated with their NGO."""
        doc = NGODocument.objects.create(
            ngo=self.ngo_a,
            uploaded_by=self.ngo_user_a,
            document_type=NGODocument.DocumentType.TRUST_DEED,
            file='fake/a/trust.pdf',
            original_filename='trust.pdf',
            file_size_bytes=100,
            mime_type='application/pdf',
        )
        # Ownership check at model level
        self.assertEqual(doc.ngo.user, self.ngo_user_a)
        self.assertNotEqual(doc.ngo.user, self.ngo_user_b)

    def test_j4_ngo_b_document_not_visible_through_ngo_a_queryset(self):
        """NGO A can only see its own documents (when filtered by ngo=self.ngo_a)."""
        NGODocument.objects.create(
            ngo=self.ngo_b,
            uploaded_by=self.ngo_user_b,
            document_type=NGODocument.DocumentType.PAN_CARD,
            file='fake/b/pan.pdf',
            original_filename='pan.pdf',
            file_size_bytes=200,
            mime_type='application/pdf',
        )
        # Correctly filtered query returns only NGO A's docs
        ngo_a_docs = NGODocument.objects.filter(ngo=self.ngo_a)
        self.assertEqual(ngo_a_docs.count(), 0)
        # Ensure NGO B's document exists but is not in NGO A's queryset
        all_docs = NGODocument.objects.all()
        self.assertEqual(all_docs.count(), 1)

    def test_j5_admin_can_submit_transitions(self):
        """Admin can perform admin-authorized transitions on any NGO."""
        change_ngo_verification_status(self.ngo_a, 'SUBMITTED', self.ngo_user_a)
        # Admin moves NGO A to UNDER_REVIEW
        change_ngo_verification_status(self.ngo_a, 'UNDER_REVIEW', self.admin_user)
        self.ngo_a.refresh_from_db()
        self.assertEqual(self.ngo_a.status, 'UNDER_REVIEW')

    def test_j6_resubmission_limit_enforced(self):
        """After 3 resubmission cycles, further resubmission is blocked."""
        ngo_user = make_user(role='NGO')
        ngo = make_ngo_profile(user=ngo_user)

        # Set resubmission_count to limit directly for test speed
        NGOVerification.objects.filter(ngo=ngo).update(
            resubmission_count=3,
            resubmission_limit=3,
            admin_reopened=False,
        )
        # Also set status to CORRECTION_REQUIRED
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED')
        NGOVerification.objects.filter(ngo=ngo).update(status='CORRECTION_REQUIRED')
        ngo.refresh_from_db()

        with self.assertRaises(ResubmissionLimitError):
            change_ngo_verification_status(ngo, 'SUBMITTED', ngo_user)

    def test_j7_admin_reopen_allows_resubmission(self):
        """After admin reopen, NGO can resubmit again."""
        ngo_user = make_user(role='NGO')
        ngo = make_ngo_profile(user=ngo_user)

        # Force to limit
        NGOVerification.objects.filter(ngo=ngo).update(
            resubmission_count=3,
            resubmission_limit=3,
            admin_reopened=False,
            status='CORRECTION_REQUIRED',
        )
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED')
        ngo.refresh_from_db()

        # Admin reopens
        reopen_ngo_application(ngo, self.admin_user, additional_cycles=3)
        ngo.refresh_from_db()

        # Now NGO can resubmit
        change_ngo_verification_status(ngo, 'SUBMITTED', ngo_user)
        ngo.refresh_from_db()
        self.assertEqual(ngo.status, 'SUBMITTED')
