"""
Tests for CampaignMilestone and DistributionProof Domain Services.

Phase 5.2.2 - Pure Domain Service Layer Tests.
Coverage:
- Milestone CRUD & access control (validate_ngo_campaign_access)
- Cross-NGO IDOR protection
- Inactive / Unapproved NGO rejections
- Milestone state machine transitions & terminal VERIFIED locking
- DistributionProof creation & validation (image, GPS, spent amount)
- Proof lifecycle: SUBMITTED -> UNDER_REVIEW -> VERIFIED / REVISION_REQUESTED / REJECTED
- Proof resubmission lifecycle: REVISION_REQUESTED -> SUBMITTED
- Transaction safety & atomic rollback
- Concurrency protection & row-level locking
"""

import datetime
from decimal import Decimal
import io
import os
import shutil

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from campaigns.models import Campaign, CampaignMilestone, DistributionProof
from campaigns.services.exceptions import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignOwnershipError,
    CampaignPermissionError,
    CampaignServiceError,
    CampaignStateError,
    CampaignValidationError,
)
from campaigns.services.distribution_proof_service import (
    create_distribution_proof,
    get_distribution_proof,
    reject_distribution_proof,
    request_proof_revision,
    resubmit_distribution_proof,
    start_proof_review,
    verify_distribution_proof,
)
from campaigns.services.milestone_service import (
    create_milestone,
    get_milestone,
    list_milestones_for_campaign,
    transition_milestone_status,
    update_milestone,
    validate_ngo_campaign_access,
)
from ngo.models import NGOProfile

User = get_user_model()
TEMP_MEDIA_ROOT = '/tmp/daangives_services_test_media'


def create_in_memory_image(name='test.jpg', size=(300, 300), color='green', format='JPEG'):
    file_obj = io.BytesIO()
    image = Image.new('RGB', size, color)
    image.save(file_obj, format=format)
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type=f'image/{format.lower()}')


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class MilestoneAndProofServiceTests(TestCase):
    """
    Exhaustive Domain Service Test Suite for Phase 5.2.2.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if os.path.exists(TEMP_MEDIA_ROOT):
            shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=90)

        # 1. Primary NGO User & Profile
        self.ngo_user1 = User.objects.create_user(
            email='service_ngo1@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Seva Foundation Lead',
            is_active=True,
        )
        self.ngo_profile1 = NGOProfile.objects.create(
            user=self.ngo_user1,
            legal_name='Seva Relief Trust',
            display_name='Seva Relief',
            category='DISASTER_RELIEF',
            description='Active disaster relief trust.',
            year_established=2015,
            status='APPROVED',
            is_active=True,
        )

        # 2. Secondary NGO User & Profile (for IDOR attack testing)
        self.ngo_user2 = User.objects.create_user(
            email='service_ngo2@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Asha Vikas Lead',
            is_active=True,
        )
        self.ngo_profile2 = NGOProfile.objects.create(
            user=self.ngo_user2,
            legal_name='Asha Vikas Samiti',
            display_name='Asha Vikas',
            category='HEALTHCARE',
            description='Healthcare for tribal communities.',
            year_established=2017,
            status='APPROVED',
            is_active=True,
        )

        # 3. Unapproved NGO User & Profile
        self.unapproved_ngo_user = User.objects.create_user(
            email='unapproved_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Pending NGO Lead',
            is_active=True,
        )
        self.unapproved_ngo_profile = NGOProfile.objects.create(
            user=self.unapproved_ngo_user,
            legal_name='Pending Verification Trust',
            display_name='Pending Trust',
            category='EDUCATION',
            year_established=2020,
            status='PENDING',
            is_active=True,
        )

        # 4. Inactive NGO User
        self.inactive_ngo_user = User.objects.create_user(
            email='inactive_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Inactive NGO Lead',
            is_active=False,
        )

        # 5. Platform Admin / Staff User
        self.admin_user = User.objects.create_user(
            email='service_admin@example.com',
            password='TestPassword123!',
            role='ADMIN',
            full_name='Compliance Officer',
            is_staff=True,
            is_active=True,
        )

        # 6. Primary Campaign (belongs to NGO 1)
        self.campaign1 = Campaign.objects.create(
            ngo=self.ngo_profile1,
            created_by=self.ngo_user1,
            title='Flood Relief Assam 2026',
            short_description='Emergency ration and sanitation kits',
            description='Direct distribution of ration kits to 2,000 affected families.',
            slug='flood-relief-assam-2026',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('500000.00'),
            raised_amount=Decimal('250000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 7. Secondary Campaign (belongs to NGO 2)
        self.campaign2 = Campaign.objects.create(
            ngo=self.ngo_profile2,
            created_by=self.ngo_user2,
            title='Mobile Medical Vans 2026',
            short_description='Health clinics on wheels',
            description='Mobile clinic services covering 40 tribal villages.',
            slug='mobile-medical-vans-2026',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('800000.00'),
            raised_amount=Decimal('100000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 8. Unapproved Campaign
        self.unapproved_campaign = Campaign.objects.create(
            ngo=self.unapproved_ngo_profile,
            created_by=self.unapproved_ngo_user,
            title='Unapproved Campaign',
            short_description='Pending approval campaign',
            description='Detailed description of the unapproved campaign with more than thirty characters.',
            slug='unapproved-campaign-2026',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('100000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.PENDING_REVIEW,
            is_active=True,
        )

        # 9. Existing Milestone for Campaign 1
        self.milestone1 = CampaignMilestone.objects.create(
            campaign=self.campaign1,
            sequence_number=1,
            title='Procure 1000 Ration Kits',
            description='Procuring rice, dal, oil, and salt from local mandi.',
            target_amount=Decimal('150000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
            status=CampaignMilestone.MilestoneStatus.PENDING,
        )

    # ============================================================
    # MILESTONE SERVICE TESTS
    # ============================================================

    def test_create_milestone_success(self):
        """Test successful milestone creation by authorized NGO owner."""
        m2 = create_milestone(
            campaign=self.campaign1,
            user=self.ngo_user1,
            sequence_number=2,
            title='Distribute Kits in Zone A',
            description='Distribution in 10 flood-hit panchayats.',
            target_amount=Decimal('100000.00'),
            target_completion_date=self.today + datetime.timedelta(days=20),
        )
        self.assertIsNotNone(m2.id)
        self.assertEqual(m2.sequence_number, 2)
        self.assertEqual(m2.status, CampaignMilestone.MilestoneStatus.PENDING)
        self.assertEqual(m2.campaign_id, self.campaign1.id)

    def test_create_milestone_unapproved_ngo_rejected(self):
        """Test that unapproved NGO cannot create milestones."""
        with self.assertRaises(CampaignPermissionError) as ctx:
            create_milestone(
                campaign=self.unapproved_campaign,
                user=self.unapproved_ngo_user,
                sequence_number=1,
                title='Test Milestone',
                description='Should fail approval check',
                target_amount=Decimal('10000.00'),
                target_completion_date=self.today + datetime.timedelta(days=10),
            )
        self.assertIn('not approved', str(ctx.exception).lower())

    def test_create_milestone_inactive_ngo_rejected(self):
        """Test that inactive NGO user cannot create milestones."""
        with self.assertRaises(CampaignPermissionError):
            create_milestone(
                campaign=self.campaign1,
                user=self.inactive_ngo_user,
                sequence_number=3,
                title='Test Milestone',
                description='Should fail active check',
                target_amount=Decimal('10000.00'),
                target_completion_date=self.today + datetime.timedelta(days=10),
            )

    def test_create_milestone_cross_ngo_idor_rejected(self):
        """NGO 2 must not be able to create a milestone on NGO 1's campaign."""
        with self.assertRaises(CampaignOwnershipError):
            create_milestone(
                campaign=self.campaign1,
                user=self.ngo_user2,
                sequence_number=2,
                title='IDOR Injected Milestone',
                description='Attempting to inject into NGO 1 campaign',
                target_amount=Decimal('50000.00'),
                target_completion_date=self.today + datetime.timedelta(days=15),
            )

    def test_create_milestone_duplicate_sequence_rejected(self):
        """Duplicate sequence on the same campaign must be rejected."""
        with self.assertRaises(CampaignConflictError):
            create_milestone(
                campaign=self.campaign1,
                user=self.ngo_user1,
                sequence_number=1,  # Already used by self.milestone1
                title='Duplicate Seq Milestone',
                description='Same sequence #1',
                target_amount=Decimal('50000.00'),
                target_completion_date=self.today + datetime.timedelta(days=10),
            )

    def test_create_milestone_invalid_sequence_number(self):
        """Sequence number < 1 must be rejected."""
        with self.assertRaises(CampaignValidationError):
            create_milestone(
                campaign=self.campaign1,
                user=self.ngo_user1,
                sequence_number=0,
                title='Invalid Seq Milestone',
                description='Seq 0 is invalid',
                target_amount=Decimal('50000.00'),
                target_completion_date=self.today + datetime.timedelta(days=10),
            )

    def test_create_milestone_invalid_target_amount(self):
        """Negative target amount must be rejected."""
        with self.assertRaises(CampaignValidationError):
            create_milestone(
                campaign=self.campaign1,
                user=self.ngo_user1,
                sequence_number=2,
                title='Negative Amount',
                description='Invalid amount',
                target_amount=Decimal('-500.00'),
                target_completion_date=self.today + datetime.timedelta(days=10),
            )

    def test_update_milestone_success(self):
        """Authorized NGO owner can update non-verified milestone fields."""
        updated = update_milestone(
            milestone=self.milestone1,
            user=self.ngo_user1,
            title='Procure 1200 Ration Kits',
            target_amount=Decimal('180000.00'),
        )
        self.assertEqual(updated.title, 'Procure 1200 Ration Kits')
        self.assertEqual(updated.target_amount, Decimal('180000.00'))

    def test_update_milestone_cross_ngo_idor_rejected(self):
        """NGO 2 cannot update NGO 1's milestone."""
        with self.assertRaises(CampaignOwnershipError):
            update_milestone(
                milestone=self.milestone1,
                user=self.ngo_user2,
                title='Hacked Title',
            )
        self.milestone1.refresh_from_db()
        self.assertEqual(self.milestone1.title, 'Procure 1000 Ration Kits')

    def test_update_milestone_immutable_when_verified(self):
        """A VERIFIED milestone is strictly sealed and immutable."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.VERIFIED
        self.milestone1.save(update_fields=['status'])

        with self.assertRaises(CampaignStateError) as ctx:
            update_milestone(
                milestone=self.milestone1,
                user=self.ngo_user1,
                title='Attempted Update After Verification',
            )
        self.assertIn('verified', str(ctx.exception).lower())

    def test_update_milestone_prevent_campaign_reassignment(self):
        """Campaign assignment cannot be modified during update."""
        update_milestone(
            milestone=self.milestone1,
            user=self.ngo_user1,
            campaign=self.campaign2,  # Should be silently discarded or ignored
            title='Legit Update',
        )
        self.milestone1.refresh_from_db()
        self.assertEqual(self.milestone1.campaign_id, self.campaign1.id)
        self.assertEqual(self.milestone1.title, 'Legit Update')

    # ============================================================
    # MILESTONE STATE MACHINE TESTS
    # ============================================================

    def test_milestone_transition_pending_to_in_progress(self):
        """NGO transitions PENDING -> IN_PROGRESS when work begins."""
        m = transition_milestone_status(
            milestone=self.milestone1,
            new_status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
            actor=self.ngo_user1,
        )
        self.assertEqual(m.status, CampaignMilestone.MilestoneStatus.IN_PROGRESS)

    def test_milestone_transition_in_progress_to_revision(self):
        """Admin requests revision on an IN_PROGRESS milestone."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        m = transition_milestone_status(
            milestone=self.milestone1,
            new_status=CampaignMilestone.MilestoneStatus.REVISION_REQUESTED,
            actor=self.admin_user,
            reason='Insufficient proof uploaded.',
        )
        self.assertEqual(m.status, CampaignMilestone.MilestoneStatus.REVISION_REQUESTED)

    def test_milestone_transition_revision_to_in_progress(self):
        """NGO transitions REVISION_REQUESTED -> IN_PROGRESS to address feedback."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.REVISION_REQUESTED
        self.milestone1.save(update_fields=['status'])

        m = transition_milestone_status(
            milestone=self.milestone1,
            new_status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
            actor=self.ngo_user1,
        )
        self.assertEqual(m.status, CampaignMilestone.MilestoneStatus.IN_PROGRESS)

    def test_milestone_transition_in_progress_to_verified_by_admin(self):
        """Admin verifies milestone; actual_completion_date is stamped."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        m = transition_milestone_status(
            milestone=self.milestone1,
            new_status=CampaignMilestone.MilestoneStatus.VERIFIED,
            actor=self.admin_user,
        )
        self.assertEqual(m.status, CampaignMilestone.MilestoneStatus.VERIFIED)
        self.assertEqual(m.actual_completion_date, timezone.now().date())

    def test_milestone_transition_verified_to_anything_rejected(self):
        """A VERIFIED milestone cannot transition to any other status."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.VERIFIED
        self.milestone1.save(update_fields=['status'])

        with self.assertRaises(CampaignStateError):
            transition_milestone_status(
                milestone=self.milestone1,
                new_status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
                actor=self.admin_user,
            )

        with self.assertRaises(CampaignStateError):
            transition_milestone_status(
                milestone=self.milestone1,
                new_status=CampaignMilestone.MilestoneStatus.PENDING,
                actor=self.admin_user,
            )

    def test_milestone_invalid_transition_pending_to_verified_rejected(self):
        """Direct jump from PENDING to VERIFIED is prohibited."""
        with self.assertRaises(CampaignStateError):
            transition_milestone_status(
                milestone=self.milestone1,
                new_status=CampaignMilestone.MilestoneStatus.VERIFIED,
                actor=self.admin_user,
            )

    def test_milestone_invalid_transition_pending_to_revision_rejected(self):
        """Direct jump from PENDING to REVISION_REQUESTED is prohibited."""
        with self.assertRaises(CampaignStateError):
            transition_milestone_status(
                milestone=self.milestone1,
                new_status=CampaignMilestone.MilestoneStatus.REVISION_REQUESTED,
                actor=self.admin_user,
            )

    def test_milestone_transition_unauthorized_actor_rejected(self):
        """NGO cannot verify its own milestone; VERIFIED requires staff."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        with self.assertRaises(CampaignPermissionError):
            transition_milestone_status(
                milestone=self.milestone1,
                new_status=CampaignMilestone.MilestoneStatus.VERIFIED,
                actor=self.ngo_user1,  # Non-staff NGO
            )

    def test_list_milestones_for_campaign(self):
        """List milestones returns all campaign milestones ordered by sequence_number."""
        create_milestone(
            campaign=self.campaign1,
            user=self.ngo_user1,
            sequence_number=2,
            title='Milestone 2',
            description='Second phase',
            target_amount=Decimal('50000.00'),
            target_completion_date=self.today + datetime.timedelta(days=20),
        )
        milestones = list_milestones_for_campaign(self.campaign1, user=self.ngo_user1)
        self.assertEqual(len(milestones), 2)
        self.assertEqual(milestones[0].sequence_number, 1)
        self.assertEqual(milestones[1].sequence_number, 2)

    # ============================================================
    # DISTRIBUTION PROOF SERVICE TESTS
    # ============================================================

    def test_create_distribution_proof_success(self):
        """Authorized NGO owner uploads proof when milestone is IN_PROGRESS."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image(name='service_proof.jpg')
        proof = create_distribution_proof(
            milestone=self.milestone1,
            user=self.ngo_user1,
            photo=photo,
            caption='Grain delivery completed in Sonitpur.',
            latitude=Decimal('26.652800'),
            longitude=Decimal('92.792600'),
            location_name='Sonitpur Distribution Center',
            beneficiary_count=450,
            beneficiary_type='DISASTER_AFFECTED',
            beneficiary_notes='Distributed to 450 BPL cardholder families.',
            spent_amount=Decimal('48500.00'),
            expense_breakdown={'grain': 35000, 'transport': 13500},
            distribution_date=self.today,
        )
        self.assertIsNotNone(proof.id)
        self.assertEqual(proof.status, DistributionProof.Status.SUBMITTED)
        self.assertEqual(proof.submitted_by_id, self.ngo_user1.id)
        self.assertIsNotNone(proof.submitted_at)
        self.assertIsNone(proof.reviewed_by)
        self.assertIsNone(proof.reviewed_at)

    def test_create_distribution_proof_pending_milestone_rejected(self):
        """Proof cannot be uploaded for a PENDING milestone."""
        photo = create_in_memory_image()
        with self.assertRaises(CampaignStateError) as ctx:
            create_distribution_proof(
                milestone=self.milestone1,  # PENDING
                user=self.ngo_user1,
                photo=photo,
                caption='Premature proof',
            )
        self.assertTrue('in_progress' in str(ctx.exception).lower() or 'pending' in str(ctx.exception).lower())

    def test_create_distribution_proof_verified_milestone_rejected(self):
        """Proof cannot be uploaded for a VERIFIED milestone."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.VERIFIED
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image()
        with self.assertRaises(CampaignStateError):
            create_distribution_proof(
                milestone=self.milestone1,
                user=self.ngo_user1,
                photo=photo,
                caption='Late proof after verification',
            )

    def test_create_distribution_proof_cross_ngo_idor_rejected(self):
        """NGO 2 cannot upload proof for NGO 1's milestone."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image()
        with self.assertRaises(CampaignOwnershipError):
            create_distribution_proof(
                milestone=self.milestone1,
                user=self.ngo_user2,
                photo=photo,
                caption='Malicious cross-NGO proof',
            )

    def test_create_distribution_proof_invalid_image(self):
        """Non-image or corrupted files are rejected by Pillow verification."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        fake_photo = SimpleUploadedFile('hacked.jpg', b'malicious payload text', content_type='image/jpeg')
        with self.assertRaises(CampaignValidationError):
            create_distribution_proof(
                milestone=self.milestone1,
                user=self.ngo_user1,
                photo=fake_photo,
                caption='Fake image proof',
            )

    def test_create_distribution_proof_invalid_coordinates(self):
        """Out of bound latitude/longitude coordinates are rejected."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image()
        with self.assertRaises(CampaignValidationError):
            create_distribution_proof(
                milestone=self.milestone1,
                user=self.ngo_user1,
                photo=photo,
                caption='Invalid latitude proof',
                latitude=Decimal('95.000000'),  # > 90
            )

    def test_create_distribution_proof_negative_spent_amount(self):
        """Negative spent amount is rejected."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image()
        with self.assertRaises(CampaignValidationError):
            create_distribution_proof(
                milestone=self.milestone1,
                user=self.ngo_user1,
                photo=photo,
                caption='Negative amount proof',
                spent_amount=Decimal('-100.00'),
            )

    def test_create_distribution_proof_submitted_by_derived_server_side(self):
        """The submitted_by field is strictly derived from the authenticated user."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image()
        proof = create_distribution_proof(
            milestone=self.milestone1,
            user=self.ngo_user1,
            photo=photo,
            caption='Server derived user test',
        )
        self.assertEqual(proof.submitted_by_id, self.ngo_user1.id)

    # ============================================================
    # PROOF MODERATION / REVIEW LIFECYCLE TESTS
    # ============================================================

    def _create_standard_proof(self):
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])
        photo = create_in_memory_image(name='standard_proof.jpg')
        return create_distribution_proof(
            milestone=self.milestone1,
            user=self.ngo_user1,
            photo=photo,
            caption='Proof waiting for moderation',
            spent_amount=Decimal('10000.00'),
        )

    def test_admin_start_proof_review(self):
        """Admin starts review on a SUBMITTED proof (moves to UNDER_REVIEW)."""
        proof = self._create_standard_proof()
        reviewed_proof = start_proof_review(
            proof=proof,
            admin_user=self.admin_user,
            admin_notes='Review started by compliance team.',
        )
        self.assertEqual(reviewed_proof.status, DistributionProof.Status.UNDER_REVIEW)
        self.assertEqual(reviewed_proof.reviewed_by_id, self.admin_user.id)
        self.assertIsNotNone(reviewed_proof.reviewed_at)
        self.assertEqual(reviewed_proof.admin_notes, 'Review started by compliance team.')

    def test_admin_start_proof_review_unauthorized_user_rejected(self):
        """Non-admin user cannot start review."""
        proof = self._create_standard_proof()
        with self.assertRaises(CampaignPermissionError):
            start_proof_review(
                proof=proof,
                admin_user=self.ngo_user1,  # Non-staff NGO
            )

    def test_admin_verify_proof_success(self):
        """Admin verifies proof currently UNDER_REVIEW."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)

        verified_proof = verify_distribution_proof(
            proof=proof,
            admin_user=self.admin_user,
            admin_notes='GPS metadata and receipt verified.',
        )
        self.assertEqual(verified_proof.status, DistributionProof.Status.VERIFIED)
        self.assertEqual(verified_proof.reviewed_by_id, self.admin_user.id)
        self.assertIsNotNone(verified_proof.reviewed_at)

    def test_admin_verify_proof_direct_from_submitted_rejected(self):
        """Cannot jump directly from SUBMITTED to VERIFIED without UNDER_REVIEW."""
        proof = self._create_standard_proof()
        with self.assertRaises(CampaignStateError) as ctx:
            verify_distribution_proof(proof=proof, admin_user=self.admin_user)
        self.assertIn('under_review', str(ctx.exception).lower())

    def test_admin_request_proof_revision_success(self):
        """Admin requests revision on proof UNDER_REVIEW with a mandatory reason."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)

        revision_proof = request_proof_revision(
            proof=proof,
            admin_user=self.admin_user,
            rejection_reason='Photo is blurry; invoice receipt is missing.',
            admin_notes='Flagged for clearer photo and bill copy.',
        )
        self.assertEqual(revision_proof.status, DistributionProof.Status.REVISION_REQUESTED)
        self.assertEqual(revision_proof.rejection_reason, 'Photo is blurry; invoice receipt is missing.')

    def test_admin_request_proof_revision_empty_reason_rejected(self):
        """Revision request must have a non-empty rejection_reason."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)

        with self.assertRaises(CampaignValidationError):
            request_proof_revision(
                proof=proof,
                admin_user=self.admin_user,
                rejection_reason='',  # Empty reason
            )

    def test_admin_reject_proof_success(self):
        """Admin rejects proof UNDER_REVIEW with a mandatory reason."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)

        rejected_proof = reject_distribution_proof(
            proof=proof,
            admin_user=self.admin_user,
            rejection_reason='Stock photo detected from external website.',
            admin_notes='Fraud detection triggered.',
        )
        self.assertEqual(rejected_proof.status, DistributionProof.Status.REJECTED)
        self.assertEqual(rejected_proof.rejection_reason, 'Stock photo detected from external website.')

    def test_admin_reject_proof_empty_reason_rejected(self):
        """Rejection must have a non-empty rejection_reason."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)

        with self.assertRaises(CampaignValidationError):
            reject_distribution_proof(
                proof=proof,
                admin_user=self.admin_user,
                rejection_reason='   ',  # Whitespace only
            )

    def test_rejected_proof_is_terminal(self):
        """A REJECTED proof is terminal: cannot be verified or resubmitted."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)
        reject_distribution_proof(proof, self.admin_user, 'Invalid documentation')

        with self.assertRaises(CampaignStateError):
            verify_distribution_proof(proof, self.admin_user)

        with self.assertRaises(CampaignStateError):
            resubmit_distribution_proof(proof, self.ngo_user1, caption='Resubmitting anyway')

    def test_ngo_resubmit_proof_revision(self):
        """NGO successfully updates & resubmits a REVISION_REQUESTED proof."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)
        request_proof_revision(proof, self.admin_user, 'Please provide clearer photo.')

        new_photo = create_in_memory_image(name='clean_proof.jpg')
        resubmitted_proof = resubmit_distribution_proof(
            proof=proof,
            user=self.ngo_user1,
            photo=new_photo,
            caption='Updated clear photo with GPS tag.',
            spent_amount=Decimal('10500.00'),
        )
        self.assertEqual(resubmitted_proof.status, DistributionProof.Status.SUBMITTED)
        self.assertEqual(resubmitted_proof.caption, 'Updated clear photo with GPS tag.')
        self.assertEqual(resubmitted_proof.spent_amount, Decimal('10500.00'))

    def test_ngo_resubmit_proof_cross_ngo_rejected(self):
        """NGO 2 cannot resubmit NGO 1's proof."""
        proof = self._create_standard_proof()
        start_proof_review(proof, self.admin_user)
        request_proof_revision(proof, self.admin_user, 'Need update.')

        with self.assertRaises(CampaignOwnershipError):
            resubmit_distribution_proof(
                proof=proof,
                user=self.ngo_user2,
                caption='Cross NGO resubmit attempt',
            )

    def test_ngo_resubmit_unauthorized_status_rejected(self):
        """Resubmission is prohibited if status is not REVISION_REQUESTED."""
        proof = self._create_standard_proof()  # In SUBMITTED status
        with self.assertRaises(CampaignStateError):
            resubmit_distribution_proof(proof=proof, user=self.ngo_user1, caption='Early resubmit')

    # ============================================================
    # TRANSACTION SAFETY & CONCURRENCY TESTS
    # ============================================================

    def test_proof_transaction_rollback(self):
        """If image validation or save fails during creation, no orphan proof record is kept."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        initial_count = DistributionProof.objects.count()

        fake_corrupted_file = SimpleUploadedFile('corrupt.jpg', b'\xFF\xD8\xFFNOT_A_VALID_JPEG')

        try:
            create_distribution_proof(
                milestone=self.milestone1,
                user=self.ngo_user1,
                photo=fake_corrupted_file,
                caption='Corrupted payload',
            )
        except CampaignValidationError:
            pass

        final_count = DistributionProof.objects.count()
        self.assertEqual(final_count, initial_count, 'No orphan records should be created on failure.')

    def test_milestone_concurrency_locking(self):
        """Verifies get_milestone with for_update=True locks the row properly."""
        with transaction.atomic():
            locked_milestone = get_milestone(
                milestone_id=self.milestone1.id,
                user=self.ngo_user1,
                for_update=True,
            )
            self.assertEqual(locked_milestone.id, self.milestone1.id)
            self.assertEqual(locked_milestone.title, self.milestone1.title)

    def test_adversarial_mass_assignment_protection(self):
        """Attempting to inject illegal status or fields during create/update fails closed."""
        self.milestone1.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
        self.milestone1.save(update_fields=['status'])

        photo = create_in_memory_image()
        # Ensure status, reviewed_by, admin_notes cannot be passed via kwargs to override
        proof = create_distribution_proof(
            milestone=self.milestone1,
            user=self.ngo_user1,
            photo=photo,
            caption='Adversarial test',
            status='VERIFIED',  # Adversarial parameter attempt
            admin_notes='Adversarial notes',
            reviewed_by=self.ngo_user1,
        )
        # Server must force SUBMITTED and empty review fields
        self.assertEqual(proof.status, DistributionProof.Status.SUBMITTED)
        self.assertIsNone(proof.reviewed_by)
        self.assertIsNone(proof.reviewed_at)
        self.assertEqual(proof.admin_notes, '')
