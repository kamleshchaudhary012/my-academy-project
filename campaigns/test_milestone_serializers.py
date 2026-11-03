import io
import os
import shutil
import tempfile
import uuid
import datetime
from decimal import Decimal
from PIL import Image

from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from ngo.models import NGOProfile
from csr.models import BeneficiaryDemographic
from campaigns.models import Campaign, CampaignMilestone, DistributionProof
from campaigns.milestone_serializers import (
    CampaignMilestoneSerializer,
    DistributionProofSerializer,
    DistributionProofCreateSerializer,
    DistributionProofPublicSerializer,
)

User = get_user_model()
TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix='daan_ser_media_')


def create_in_memory_image(format='JPEG', size=(200, 200), color=(100, 150, 200), name='proof.jpg'):
    """Helper to generate in-memory images for upload testing."""
    buf = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    content_type = 'image/jpeg' if format.upper() == 'JPEG' else f'image/{format.lower()}'
    return SimpleUploadedFile(name, buf.read(), content_type=content_type)


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class MilestoneAndProofSerializerTests(TestCase):
    """
    Exhaustive Serializer & Validation Test Suite for Phase 5.2.2.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if os.path.exists(TEMP_MEDIA_ROOT):
            shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        # 1. Users
        self.ngo_user = User.objects.create_user(
            email='ser_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Serializer NGO Lead',
            is_active=True,
        )
        self.admin_user = User.objects.create_user(
            email='ser_admin@example.com',
            password='TestPassword123!',
            role='ADMIN',
            full_name='Platform Admin',
            is_staff=True,
            is_active=True,
        )

        # 2. NGO Profile
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Bright Future Foundation',
            display_name='Bright Future',
            category='EDUCATION',
            description='NGO for education and child nutrition.',
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )

        # 3. Campaign
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=60)
        self.campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='School Meals Drive 2026',
            short_description='Mid-day meals for 5 schools',
            description='Providing balanced nutrition and drinking water to rural school children.',
            slug='school-meals-drive-2026',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('150000.00'),
            raised_amount=Decimal('80000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 4. Campaign Milestone
        self.milestone = CampaignMilestone.objects.create(
            campaign=self.campaign,
            sequence_number=1,
            title='Procure Grains and Pulses',
            description='Bulk procurement of food grains from agricultural cooperative.',
            target_amount=Decimal('50000.00'),
            target_completion_date=self.today + datetime.timedelta(days=15),
            status=CampaignMilestone.MilestoneStatus.PENDING,
        )

    # 1. Valid milestone serialization
    def test_valid_milestone_serialization(self):
        serializer = CampaignMilestoneSerializer(instance=self.milestone)
        data = serializer.data
        self.assertEqual(data['id'], str(self.milestone.id))
        self.assertEqual(data['title'], 'Procure Grains and Pulses')
        self.assertEqual(data['campaign_title'], self.campaign.title)
        self.assertEqual(data['status'], 'PENDING')
        self.assertEqual(Decimal(data['target_amount']), Decimal('50000.00'))

    # 2. Valid milestone creation through serializer
    def test_valid_milestone_creation(self):
        payload = {
            'campaign': str(self.campaign.id),
            'sequence_number': 2,
            'title': 'School Kitchen Utensils',
            'description=': 'Procure cooking pots and serving trays.',
            'description': 'Procure cooking pots and serving trays for 5 schools.',
            'target_amount': '25000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=25)),
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        milestone = serializer.save()
        self.assertEqual(milestone.sequence_number, 2)
        self.assertEqual(milestone.status, CampaignMilestone.MilestoneStatus.PENDING)

    # 3. Read-only ID cannot be overridden
    def test_milestone_read_only_id(self):
        fake_id = str(uuid.uuid4())
        payload = {
            'id': fake_id,
            'campaign': str(self.campaign.id),
            'sequence_number': 3,
            'title': 'Storage Facility Setup',
            'description': 'Rent and prepare hygienic grain storage room.',
            'target_amount': '15000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=10)),
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        milestone = serializer.save()
        self.assertNotEqual(str(milestone.id), fake_id)

    # 4. Read-only timestamps
    def test_milestone_read_only_timestamps(self):
        serializer = CampaignMilestoneSerializer(instance=self.milestone)
        self.assertIn('created_at', serializer.data)
        self.assertIn('updated_at', serializer.data)

    # 5. Status mass-assignment blocked
    def test_milestone_status_mass_assignment_blocked(self):
        payload = {
            'campaign': str(self.campaign.id),
            'sequence_number': 4,
            'title': 'Attempted Verified Status Injection',
            'description': 'Malicious attempt to set status to VERIFIED on creation.',
            'target_amount': '10000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=10)),
            'status': 'VERIFIED',
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        milestone = serializer.save()
        # Must default to PENDING; client status payload stripped
        self.assertEqual(milestone.status, CampaignMilestone.MilestoneStatus.PENDING)

    # 6. Actual completion date mass-assignment blocked
    def test_milestone_actual_completion_date_read_only(self):
        payload = {
            'campaign': str(self.campaign.id),
            'sequence_number': 5,
            'title': 'Fake Completion Date Injection',
            'description': 'Attempt to mark deliverable complete via client input.',
            'target_amount': '10000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=10)),
            'actual_completion_date': str(self.today),
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        milestone = serializer.save()
        self.assertIsNone(milestone.actual_completion_date)

    # 7. Invalid sequence (< 1) rejected
    def test_milestone_invalid_sequence_rejected(self):
        payload = {
            'campaign': str(self.campaign.id),
            'sequence_number': 0,
            'title': 'Zero Sequence',
            'description': 'Invalid sequence number test.',
            'target_amount': '5000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=5)),
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('sequence_number', serializer.errors)

    # 8. Invalid target amount (< 0) rejected
    def test_milestone_negative_target_amount_rejected(self):
        payload = {
            'campaign': str(self.campaign.id),
            'sequence_number': 6,
            'title': 'Negative Budget',
            'description': 'Invalid negative target amount test.',
            'target_amount': '-1000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=5)),
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('target_amount', serializer.errors)

    # 9. Duplicate sequence on same campaign rejected in serializer
    def test_milestone_duplicate_sequence_rejected(self):
        payload = {
            'campaign': str(self.campaign.id),
            'sequence_number': 1,  # Milestone 1 already exists
            'title': 'Duplicate Sequence Milestone',
            'description': 'Should be rejected because seq #1 already exists.',
            'target_amount': '5000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=5)),
        }
        serializer = CampaignMilestoneSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertTrue(
            'non_field_errors' in serializer.errors or 'sequence_number' in serializer.errors
        )

    # 10. Valid distribution proof serialization
    def test_valid_proof_serialization(self):
        photo = create_in_memory_image(name='photo1.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Delivery of 100 grain sacks at school center.',
            latitude=Decimal('28.613900'),
            longitude=Decimal('77.209000'),
            location_name='Rampur Primary School',
            beneficiary_count=150,
            beneficiary_type=BeneficiaryDemographic.CHILDREN_EDUCATION,
            beneficiary_notes='Direct distribution witnessed by school headmaster.',
            spent_amount=Decimal('35000.00'),
            expense_breakdown={'items': [{'name': 'Grains (100 sacks)', 'cost': 35000}]},
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        serializer = DistributionProofSerializer(instance=proof)
        data = serializer.data
        self.assertEqual(data['id'], str(proof.id))
        self.assertEqual(data['milestone_title'], self.milestone.title)
        self.assertEqual(data['campaign_title'], self.campaign.title)
        self.assertEqual(data['beneficiary_count'], 150)
        self.assertEqual(data['beneficiary_type_display'], 'Children & Primary Education')
        self.assertEqual(Decimal(data['spent_amount']), Decimal('35000.00'))
        self.assertTrue(data['photo_url'].startswith('/media/distribution_proofs/'))

    # 11. Valid proof creation through DistributionProofCreateSerializer
    def test_valid_proof_creation_serializer(self):
        photo = create_in_memory_image(name='create_test.jpg')
        payload = {
            'photo': photo,
            'caption': 'Volunteers serving meals at Village Ward 3.',
            'latitude': '26.846700',
            'longitude': '80.946200',
            'location_name': 'Ward 3 Community Center',
            'beneficiary_count': 80,
            'beneficiary_type': 'CHILDREN_EDUCATION',
            'beneficiary_notes=': 'All 80 children received meals.',
            'beneficiary_notes': 'All 80 children received meals.',
            'spent_amount': '12500.00',
            'expense_breakdown': {'groceries': 10000, 'fuel': 2500},
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # Note: milestone and submitted_by are passed by the service/view, not client payload
        proof = serializer.save(milestone=self.milestone, submitted_by=self.ngo_user)
        self.assertEqual(proof.status, DistributionProof.Status.SUBMITTED)
        self.assertEqual(proof.beneficiary_count, 80)
        self.assertEqual(proof.spent_amount, Decimal('12500.00'))

    # 12. submitted_by mass-assignment blocked
    def test_proof_submitted_by_mass_assignment_blocked(self):
        other_user = User.objects.create_user(
            email='intruder@example.com',
            password='TestPassword123!',
            role='NGO',
        )
        photo = create_in_memory_image(name='tamper_user.jpg')
        payload = {
            'milestone': str(self.milestone.id),
            'photo': photo,
            'caption': 'Attempting to impersonate other submitter',
            'distribution_date': str(self.today),
            'submitted_by': str(other_user.id),
        }
        serializer = DistributionProofSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # Service assigns submitted_by server-side
        proof = serializer.save(submitted_by=self.ngo_user)
        self.assertEqual(proof.submitted_by, self.ngo_user)
        self.assertNotEqual(proof.submitted_by, other_user)

    # 13. reviewed_by mass-assignment blocked
    def test_proof_reviewed_by_mass_assignment_blocked(self):
        photo = create_in_memory_image(name='tamper_reviewer.jpg')
        payload = {
            'milestone': str(self.milestone.id),
            'photo': photo,
            'caption': 'Attempting to inject reviewer ID',
            'distribution_date': str(self.today),
            'reviewed_by': str(self.admin_user.id),
            'reviewed_at': str(timezone.now()),
        }
        serializer = DistributionProofSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        proof = serializer.save(submitted_by=self.ngo_user)
        self.assertIsNone(proof.reviewed_by)
        self.assertIsNone(proof.reviewed_at)

    # 14. admin_notes mass-assignment blocked
    def test_proof_admin_notes_mass_assignment_blocked(self):
        photo = create_in_memory_image(name='tamper_notes.jpg')
        payload = {
            'milestone': str(self.milestone.id),
            'photo': photo,
            'caption': 'Attempting to inject fake admin note',
            'distribution_date': str(self.today),
            'admin_notes': 'Fake admin verified without inspection.',
        }
        serializer = DistributionProofSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        proof = serializer.save(submitted_by=self.ngo_user)
        self.assertEqual(proof.admin_notes, '')

    # 15. status mass-assignment blocked
    def test_proof_status_mass_assignment_blocked(self):
        photo = create_in_memory_image(name='tamper_status.jpg')
        payload = {
            'milestone': str(self.milestone.id),
            'photo': photo,
            'caption': 'Attempting to escalate status to VERIFIED',
            'distribution_date': str(self.today),
            'status': 'VERIFIED',
        }
        serializer = DistributionProofSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        proof = serializer.save(submitted_by=self.ngo_user)
        self.assertEqual(proof.status, DistributionProof.Status.SUBMITTED)

    # 16. Invalid latitude (< -90 or > 90) rejected
    def test_proof_invalid_latitude_rejected(self):
        photo = create_in_memory_image(name='bad_lat.jpg')
        payload = {
            'photo': photo,
            'caption': 'Invalid latitude test',
            'latitude': '95.500000',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('latitude', serializer.errors)

    # 17. Invalid longitude (< -180 or > 180) rejected
    def test_proof_invalid_longitude_rejected(self):
        photo = create_in_memory_image(name='bad_lng.jpg')
        payload = {
            'photo': photo,
            'caption': 'Invalid longitude test',
            'longitude': '-185.000000',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('longitude', serializer.errors)

    # 18. Valid GPS boundary values
    def test_proof_valid_gps_boundaries(self):
        photo = create_in_memory_image(name='boundary_gps.jpg')
        payload = {
            'photo': photo,
            'caption': 'Boundary GPS test',
            'latitude': '90.000000',
            'longitude': '180.000000',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    # 19. Nullable GPS coordinates permitted
    def test_proof_nullable_gps(self):
        photo = create_in_memory_image(name='null_gps.jpg')
        payload = {
            'photo': photo,
            'caption': 'Distribution without GPS',
            'latitude': None,
            'longitude': None,
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    # 20. Invalid beneficiary count (< 0) rejected
    def test_proof_invalid_beneficiary_count_rejected(self):
        photo = create_in_memory_image(name='bad_bcount.jpg')
        payload = {
            'photo': photo,
            'caption': 'Negative beneficiary count',
            'beneficiary_count': -5,
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('beneficiary_count', serializer.errors)

    # 21. Invalid beneficiary type choice rejected
    def test_proof_invalid_beneficiary_type_rejected(self):
        photo = create_in_memory_image(name='bad_btype.jpg')
        payload = {
            'photo': photo,
            'caption': 'Invalid demographic choice',
            'beneficiary_type': 'ALIENS_AND_MARTIANS',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('beneficiary_type', serializer.errors)

    # 22. Invalid spent amount (< 0) rejected
    def test_proof_invalid_spent_amount_rejected(self):
        photo = create_in_memory_image(name='bad_spent.jpg')
        payload = {
            'photo': photo,
            'caption': 'Negative spent amount',
            'spent_amount': '-500.00',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('spent_amount', serializer.errors)

    # 23. Invalid image extension (.txt renamed) rejected
    def test_proof_invalid_image_extension_rejected(self):
        fake_txt = SimpleUploadedFile('report.txt', b'Just a text file', content_type='text/plain')
        payload = {
            'photo': fake_txt,
            'caption': 'Text file test',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('photo', serializer.errors)

    # 24. Oversized image (> 5MB) rejected
    def test_proof_oversized_image_rejected(self):
        big_data = b'x' * (5 * 1024 * 1024 + 2048)
        big_file = SimpleUploadedFile('huge.jpg', big_data, content_type='image/jpeg')
        payload = {
            'photo': big_file,
            'caption': 'Oversized image test',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('photo', serializer.errors)

    # 25. Corrupted image bytes rejected
    def test_proof_corrupted_image_rejected(self):
        corrupt_file = SimpleUploadedFile('corrupt.jpg', b'\xff\xd8\xffCORRUPTBYTES', content_type='image/jpeg')
        payload = {
            'photo': corrupt_file,
            'caption': 'Corrupted image test',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('photo', serializer.errors)

    # 26. Valid PNG and WebP images accepted
    def test_proof_valid_png_and_webp_accepted(self):
        png = create_in_memory_image(format='PNG', name='valid.png')
        p1 = DistributionProofCreateSerializer(data={'photo': png, 'caption': 'PNG test', 'distribution_date': str(self.today)})
        self.assertTrue(p1.is_valid(), p1.errors)

        webp = create_in_memory_image(format='WEBP', name='valid.webp')
        p2 = DistributionProofCreateSerializer(data={'photo': webp, 'caption': 'WebP test', 'distribution_date': str(self.today)})
        self.assertTrue(p2.is_valid(), p2.errors)

    # 27. Expense breakdown must be JSON dictionary
    def test_proof_expense_breakdown_dict_enforced(self):
        photo = create_in_memory_image(name='exp_test.jpg')
        payload = {
            'photo': photo,
            'caption': 'Invalid expense breakdown type',
            'expense_breakdown': 'Not a dict',
            'distribution_date': str(self.today),
        }
        serializer = DistributionProofCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('expense_breakdown', serializer.errors)

    # 28. No filesystem path leakage in photo_url
    def test_proof_no_filesystem_path_leakage(self):
        photo = create_in_memory_image(name='secret_path.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Checking URL safety',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        serializer = DistributionProofSerializer(instance=proof)
        photo_url = serializer.data['photo_url']
        self.assertFalse(photo_url.startswith('/Users/'))
        self.assertFalse(photo_url.startswith('/var/'))
        self.assertTrue(photo_url.startswith('/media/distribution_proofs/'))

    # 29. Public serializer strictly excludes private admin notes and internal metadata
    def test_public_serializer_excludes_internal_fields(self):
        photo = create_in_memory_image(name='public_view.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Verified public field activity',
            beneficiary_count=200,
            beneficiary_type=BeneficiaryDemographic.CHILDREN_EDUCATION,
            spent_amount=Decimal('45000.00'),
            distribution_date=self.today,
            status=DistributionProof.Status.VERIFIED,
            submitted_by=self.ngo_user,
            reviewed_by=self.admin_user,
            reviewed_at=timezone.now(),
            admin_notes='SECRET INTERNAL AUDIT NOTE: GPS matched school boundary within 20m.',
            rejection_reason='N/A',
        )
        serializer = DistributionProofPublicSerializer(instance=proof)
        data = serializer.data
        self.assertNotIn('admin_notes', data)
        self.assertNotIn('rejection_reason', data)
        self.assertNotIn('submitted_by', data)
        self.assertNotIn('reviewed_by', data)
        self.assertEqual(data['beneficiary_count'], 200)
        self.assertEqual(data['status'], 'VERIFIED')

    # 30. Verified spent amount calculation on Milestone serializer
    def test_milestone_verified_spent_amount_aggregation(self):
        # Proof 1: VERIFIED, ₹15,000
        photo1 = create_in_memory_image(name='p1.jpg')
        DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo1,
            caption='Verified batch 1',
            spent_amount=Decimal('15000.00'),
            distribution_date=self.today,
            status=DistributionProof.Status.VERIFIED,
            submitted_by=self.ngo_user,
        )

        # Proof 2: VERIFIED, ₹20,000
        photo2 = create_in_memory_image(name='p2.jpg')
        DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo2,
            caption='Verified batch 2',
            spent_amount=Decimal('20000.00'),
            distribution_date=self.today,
            status=DistributionProof.Status.VERIFIED,
            submitted_by=self.ngo_user,
        )

        # Proof 3: SUBMITTED (unverified), ₹10,000 (must NOT be counted in verified_spent_amount)
        photo3 = create_in_memory_image(name='p3.jpg')
        DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo3,
            caption='Unverified batch 3',
            spent_amount=Decimal('10000.00'),
            status=DistributionProof.Status.SUBMITTED,
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )

        serializer = CampaignMilestoneSerializer(instance=self.milestone)
        # Sum of verified proofs only: 15,000 + 20,000 = 35,000
        self.assertEqual(Decimal(serializer.data['verified_spent_amount']), Decimal('35000.00'))
        self.assertEqual(serializer.data['proofs_count'], 3)
