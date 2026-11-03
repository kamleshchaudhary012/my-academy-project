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
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from ngo.models import NGOProfile
from csr.models import BeneficiaryDemographic
from campaigns.models import Campaign, CampaignMilestone, DistributionProof

User = get_user_model()

# Create a temporary directory for media files during tests
TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix='daan_test_media_')


def create_in_memory_image(format='JPEG', size=(200, 200), color=(100, 150, 200), name='proof_photo.jpg'):
    """Helper to generate valid in-memory images for upload testing."""
    buf = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(buf, format=format)
    buf.seek(0)
    content_type = f'image/{format.lower()}'
    if format.upper() == 'JPEG':
        content_type = 'image/jpeg'
    return SimpleUploadedFile(name, buf.read(), content_type=content_type)


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class DistributionProofModelTests(TestCase):
    """
    Exhaustive Model-Level Unit Tests for DistributionProof (Phase 5.2.1).
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Clean up temporary media directory completely
        if os.path.exists(TEMP_MEDIA_ROOT):
            shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        # 1. Users
        self.ngo_user = User.objects.create_user(
            email='proof_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Distribution NGO Lead',
            is_active=True,
        )
        self.admin_user = User.objects.create_user(
            email='proof_admin@example.com',
            password='TestPassword123!',
            role='ADMIN',
            full_name='Platform Admin',
            is_staff=True,
            is_active=True,
        )

        # 2. NGO Profile
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Rural Education and Health Trust',
            display_name='Rural Trust',
            category='EDUCATION',
            description='NGO working in rural education and relief.',
            year_established=2017,
            status='APPROVED',
            is_active=True,
        )

        # 3. Campaign
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=90)
        self.campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Rural Winter Clothing and Blankets Distribution',
            short_description='Distributing 500 blankets to rural families',
            description='Community-driven blanket drive providing essential warmth during winter.',
            slug='rural-winter-clothing-proof-test',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('100000.00'),
            raised_amount=Decimal('50000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 4. Campaign Milestone
        self.milestone = CampaignMilestone.objects.create(
            campaign=self.campaign,
            sequence_number=1,
            title='Procurement and Field Distribution of 250 Blankets',
            description='Purchase 250 heavy fleece blankets and distribute at Camp 1.',
            target_amount=Decimal('50000.00'),
            target_completion_date=self.today + datetime.timedelta(days=15),
            status=CampaignMilestone.MilestoneStatus.PENDING,
        )

    # 16. Create valid proof
    def test_create_valid_distribution_proof(self):
        photo = create_in_memory_image(name='distribution_proof_1.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Field volunteer team distributing blankets to families in Village Camp A.',
            latitude=Decimal('28.613939'),
            longitude=Decimal('77.209021'),
            location_name='Village Rampur, District Meerut',
            beneficiary_count=120,
            beneficiary_type=BeneficiaryDemographic.RURAL_COMMUNITIES,
            beneficiary_notes='Blankets handed directly to heads of households with signed receipt logs.',
            spent_amount=Decimal('24500.00'),
            expense_breakdown={'items': [{'name': 'Fleece Blankets (120 units)', 'cost': 21600}, {'name': 'Transport van', 'cost': 2900}]},
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertIsNotNone(proof.pk)
        self.assertEqual(proof.milestone, self.milestone)
        self.assertEqual(proof.beneficiary_count, 120)
        self.assertEqual(proof.spent_amount, Decimal('24500.00'))
        self.assertEqual(proof.status, DistributionProof.Status.SUBMITTED)

    # 17. UUID primary key generation
    def test_uuid_generation(self):
        photo = create_in_memory_image(name='uuid_test.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Delivery verification',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertIsInstance(proof.id, uuid.UUID)

    # 18. Default status is SUBMITTED
    def test_default_status_is_submitted(self):
        photo = create_in_memory_image(name='status_test.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Proof awaiting review',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertEqual(proof.status, DistributionProof.Status.SUBMITTED)

    # 19. Default beneficiary_count is 0
    def test_default_beneficiary_count(self):
        photo = create_in_memory_image(name='beneficiary_default.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Inspection before distribution',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertEqual(proof.beneficiary_count, 0)

    # 20. Beneficiary count validation (negative rejected)
    def test_negative_beneficiary_count_rejected(self):
        photo = create_in_memory_image(name='neg_beneficiary.jpg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=photo,
            caption='Negative beneficiary test',
            beneficiary_count=-10,
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError):
            proof.full_clean()

    # 21. Spent amount zero allowed
    def test_spent_amount_zero_allowed(self):
        photo = create_in_memory_image(name='zero_spent.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Volunteer distribution without external logistics fee',
            spent_amount=Decimal('0.00'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertEqual(proof.spent_amount, Decimal('0.00'))
        proof.full_clean()

    # 22. Negative spent amount rejected
    def test_negative_spent_amount_rejected(self):
        photo = create_in_memory_image(name='neg_spent.jpg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=photo,
            caption='Negative expense test',
            spent_amount=Decimal('-150.00'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError):
            proof.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                proof.save()

    # 23. GPS valid boundary values
    def test_gps_valid_boundary_values(self):
        photo = create_in_memory_image(name='boundary_gps.jpg')
        # Equator & Prime Meridian
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Equator testing',
            latitude=Decimal('0.000000'),
            longitude=Decimal('0.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        proof.full_clean()
        self.assertEqual(proof.latitude, Decimal('0.000000'))
        self.assertEqual(proof.longitude, Decimal('0.000000'))

    # 24. Latitude -90 and +90 accepted
    def test_latitude_extremes_accepted(self):
        photo1 = create_in_memory_image(name='north_pole.jpg')
        p_north = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo1,
            caption='North Pole latitude',
            latitude=Decimal('90.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        p_north.full_clean()

        photo2 = create_in_memory_image(name='south_pole.jpg')
        p_south = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo2,
            caption='South Pole latitude',
            latitude=Decimal('-90.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        p_south.full_clean()

    # 25. Longitude -180 and +180 accepted
    def test_longitude_extremes_accepted(self):
        photo1 = create_in_memory_image(name='date_line_east.jpg')
        p_east = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo1,
            caption='East antimeridian',
            longitude=Decimal('180.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        p_east.full_clean()

        photo2 = create_in_memory_image(name='date_line_west.jpg')
        p_west = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo2,
            caption='West antimeridian',
            longitude=Decimal('-180.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        p_west.full_clean()

    # 26. Invalid latitude rejected (> 90 or < -90)
    def test_invalid_latitude_rejected(self):
        photo = create_in_memory_image(name='invalid_lat.jpg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=photo,
            caption='Invalid latitude 95.0',
            latitude=Decimal('95.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError):
            proof.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                proof.save()

    # 27. Invalid longitude rejected (> 180 or < -180)
    def test_invalid_longitude_rejected(self):
        photo = create_in_memory_image(name='invalid_lng.jpg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=photo,
            caption='Invalid longitude 185.0',
            longitude=Decimal('185.000000'),
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError):
            proof.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                proof.save()

    # 28. Nullable GPS behavior (both lat and long can be null)
    def test_nullable_gps_allowed(self):
        photo = create_in_memory_image(name='no_gps.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Proof without GPS coordinates',
            latitude=None,
            longitude=None,
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        proof.full_clean()
        self.assertIsNone(proof.latitude)
        self.assertIsNone(proof.longitude)

    # 29. Beneficiary demographic choices
    def test_beneficiary_demographic_choices(self):
        for choice_key in BeneficiaryDemographic.values:
            photo = create_in_memory_image(name=f'{choice_key}.jpg')
            proof = DistributionProof(
                milestone=self.milestone,
                photo=photo,
                caption=f'Test for {choice_key}',
                beneficiary_type=choice_key,
                distribution_date=self.today,
                submitted_by=self.ngo_user,
            )
            proof.full_clean()

    # 30. Expense breakdown default is dict
    def test_expense_breakdown_default(self):
        photo = create_in_memory_image(name='breakdown_default.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Default breakdown test',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertEqual(proof.expense_breakdown, {})

    # 31. JSON default isolation across instances
    def test_json_default_isolation(self):
        photo1 = create_in_memory_image(name='json_iso_1.jpg')
        p1 = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo1,
            caption='Instance 1',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        p1.expense_breakdown['test_key'] = 'value_1'
        p1.save()

        photo2 = create_in_memory_image(name='json_iso_2.jpg')
        p2 = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo2,
            caption='Instance 2',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertNotIn('test_key', p2.expense_breakdown)

    # 32. distribution_date is required
    def test_distribution_date_required(self):
        photo = create_in_memory_image(name='missing_date.jpg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=photo,
            caption='Missing date test',
            distribution_date=None,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError):
            proof.full_clean()

    # 33. submitted_by on_delete is PROTECT
    def test_submitted_by_protect_prevents_user_deletion(self):
        photo = create_in_memory_image(name='protect_test.jpg')
        DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Proof submitted by NGO user',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(models.ProtectedError):
            self.ngo_user.delete()

    # 34. reviewed_by nullable
    def test_reviewed_by_nullable(self):
        photo = create_in_memory_image(name='unreviewed.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Unreviewed proof',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
            reviewed_by=None,
            reviewed_at=None,
        )
        self.assertIsNone(proof.reviewed_by)
        self.assertIsNone(proof.reviewed_at)

    # 35. reviewed_by on_delete is SET_NULL
    def test_reviewed_by_set_null_on_admin_deletion(self):
        photo = create_in_memory_image(name='reviewed_proof.jpg')
        temp_admin = User.objects.create_user(
            email='temp_admin_review@example.com',
            password='TestPassword123!',
            role='ADMIN',
            is_staff=True,
        )
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Verified by temp admin',
            status=DistributionProof.Status.VERIFIED,
            distribution_date=self.today,
            submitted_by=self.ngo_user,
            reviewed_by=temp_admin,
            reviewed_at=timezone.now(),
        )
        self.assertEqual(proof.reviewed_by, temp_admin)

        # Delete temp_admin
        temp_admin.delete()
        proof.refresh_from_db()
        self.assertIsNone(proof.reviewed_by)
        self.assertEqual(proof.status, DistributionProof.Status.VERIFIED)

    # 36. milestone CASCADE deletion deletes proofs
    def test_milestone_cascade_deletes_proofs(self):
        photo = create_in_memory_image(name='cascade_test.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Will be deleted when milestone is deleted',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        proof_id = proof.id
        self.assertTrue(DistributionProof.objects.filter(id=proof_id).exists())

        # Delete milestone
        self.milestone.delete()
        self.assertFalse(DistributionProof.objects.filter(id=proof_id).exists())

    # 37. Image extension validation
    def test_image_extension_validation(self):
        # Valid PNG
        png_photo = create_in_memory_image(format='PNG', name='valid.png')
        proof_png = DistributionProof(
            milestone=self.milestone,
            photo=png_photo,
            caption='Valid PNG',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        proof_png.full_clean()

        # Valid WebP
        webp_photo = create_in_memory_image(format='WEBP', name='valid.webp')
        proof_webp = DistributionProof(
            milestone=self.milestone,
            photo=webp_photo,
            caption='Valid WebP',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        proof_webp.full_clean()

        # Invalid .txt
        fake_txt = SimpleUploadedFile('invalid.txt', b'This is a text file', content_type='text/plain')
        proof_txt = DistributionProof(
            milestone=self.milestone,
            photo=fake_txt,
            caption='Invalid text file',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            proof_txt.full_clean()
        self.assertIn('photo', ctx.exception.message_dict)

    # 38. Image size validation (> 5 MB rejected)
    def test_image_size_validation_oversized_rejected(self):
        # 5MB + 1KB
        oversized_data = b'x' * (5 * 1024 * 1024 + 1024)
        oversized_file = SimpleUploadedFile('oversized.jpg', oversized_data, content_type='image/jpeg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=oversized_file,
            caption='Oversized file',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            proof.full_clean()
        self.assertIn('photo', ctx.exception.message_dict)

    # 39. Pillow invalid image validation (corrupted bytes with .jpg extension)
    def test_corrupted_image_content_rejected(self):
        corrupted_file = SimpleUploadedFile('corrupt.jpg', b'\xff\xd8\xffnotarealjpgfile', content_type='image/jpeg')
        proof = DistributionProof(
            milestone=self.milestone,
            photo=corrupted_file,
            caption='Corrupt image file',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            proof.full_clean()
        self.assertIn('photo', ctx.exception.message_dict)

    # 40. Upload path isolation and randomization
    def test_upload_path_randomization(self):
        photo = create_in_memory_image(name='original_filename_123.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Randomized upload path test',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        self.assertTrue(proof.photo.name.startswith(f'distribution_proofs/{self.campaign.id}/'))
        self.assertNotIn('original_filename_123', proof.photo.name)
        self.assertTrue(proof.photo.name.endswith('.jpg'))

    # 41. String representation
    def test_string_representation(self):
        photo = create_in_memory_image(name='str_test.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='String repr test',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        expected = f'Proof for {self.milestone.title} (SUBMITTED) — {self.today}'
        self.assertEqual(str(proof), expected)

    # 42. All review status choices valid
    def test_all_proof_status_choices_valid(self):
        photo = create_in_memory_image(name='status_choices.jpg')
        proof = DistributionProof.objects.create(
            milestone=self.milestone,
            photo=photo,
            caption='Status choices test',
            distribution_date=self.today,
            submitted_by=self.ngo_user,
        )
        for st in [
            DistributionProof.Status.SUBMITTED,
            DistributionProof.Status.UNDER_REVIEW,
            DistributionProof.Status.VERIFIED,
            DistributionProof.Status.REVISION_REQUESTED,
            DistributionProof.Status.REJECTED,
        ]:
            proof.status = st
            proof.save()
            proof.refresh_from_db()
            self.assertEqual(proof.status, st)
