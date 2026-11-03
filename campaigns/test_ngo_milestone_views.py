"""
HTTP View Tests for NGO Campaign Milestone & Distribution Proof APIs.

Phase 5.2.3 — Integration, Security, and Cross-NGO IDOR Test Suite.
Endpoints tested:
1. GET/POST   /api/v1/ngo/campaigns/<uuid:campaign_id>/milestones/
2. GET        /api/v1/ngo/campaigns/milestones/<uuid:pk>/
3. PUT/PATCH  /api/v1/ngo/campaigns/milestones/<uuid:pk>/
4. POST       /api/v1/ngo/campaigns/milestones/<uuid:pk>/proofs/
5. GET        /api/v1/ngo/campaigns/distribution-proofs/

Covers:
- Authentication & Role checks (Unauthenticated, Inactive, Pending, Suspended, Donor, Company)
- Campaign ownership & Cross-NGO IDOR prevention
- Milestone CRUD lifecycle & verified milestone immutability
- Multipart distribution proof upload (Valid images, corrupt, oversized, bad extensions)
- GPS & Beneficiary validation
- Mass assignment defense (forged submitted_by, forged status, campaign reassignment)
- Proof list multi-tenant isolation & query parameter filtering
- Regression test on existing Campaign APIs
"""

import datetime
from decimal import Decimal
import io
import os
import shutil

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignMilestone, DistributionProof
from ngo.models import NGOProfile

User = get_user_model()
TEMP_MEDIA_ROOT = '/tmp/daangives_api_test_media'


def create_in_memory_image(name='evidence.jpg', size=(300, 300), color='blue', format='JPEG'):
    file_obj = io.BytesIO()
    image = Image.new('RGB', size, color)
    image.save(file_obj, format=format)
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type=f'image/{format.lower()}')


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class NGOCampaignMilestoneAPITests(APITestCase):
    """
    Comprehensive API integration and IDOR test suite for Phase 5.2.3.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if os.path.exists(TEMP_MEDIA_ROOT):
            shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=90)

        # 1. Primary Approved NGO User & Profile (NGO A)
        self.ngo_user_a = User.objects.create_user(
            email='ngo_a@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Lead NGO A',
            is_active=True,
        )
        self.ngo_profile_a = NGOProfile.objects.create(
            user=self.ngo_user_a,
            legal_name='Aarav Healthcare Trust',
            display_name='Aarav Trust',
            category='HEALTHCARE',
            description='Healthcare delivery in rural belts.',
            year_established=2014,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # 2. Secondary Approved NGO User & Profile (NGO B - for IDOR attacks)
        self.ngo_user_b = User.objects.create_user(
            email='ngo_b@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Lead NGO B',
            is_active=True,
        )
        self.ngo_profile_b = NGOProfile.objects.create(
            user=self.ngo_user_b,
            legal_name='Bhavya Education Society',
            display_name='Bhavya Society',
            category='EDUCATION',
            description='Tribal school education projects.',
            year_established=2016,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # 3. Pending Verification NGO User
        self.pending_ngo_user = User.objects.create_user(
            email='pending_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Pending Lead',
            is_active=True,
        )
        self.pending_ngo_profile = NGOProfile.objects.create(
            user=self.pending_ngo_user,
            legal_name='Pending Verification Trust',
            display_name='Pending Trust',
            category='EDUCATION',
            description='Pending trust project documentation for rural schools.',
            year_established=2021,
            status=NGOProfile.Status.SUBMITTED,
            is_active=True,
        )

        # 4. Inactive NGO User
        self.inactive_ngo_user = User.objects.create_user(
            email='inactive_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Inactive Lead',
            is_active=False,
        )

        # 5. Rejected NGO User
        self.rejected_ngo_user = User.objects.create_user(
            email='rejected_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Rejected Lead',
            is_active=True,
        )
        self.rejected_ngo_profile = NGOProfile.objects.create(
            user=self.rejected_ngo_user,
            legal_name='Rejected Foundation',
            display_name='Rejected Found',
            category='EDUCATION',
            description='Rejected foundation documentation for educational trust.',
            year_established=2020,
            status=NGOProfile.Status.REJECTED,
            is_active=True,
        )

        # 6. Suspended NGO User
        self.suspended_ngo_user = User.objects.create_user(
            email='suspended_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Suspended Lead',
            is_active=True,
        )
        self.suspended_ngo_profile = NGOProfile.objects.create(
            user=self.suspended_ngo_user,
            legal_name='Suspended Foundation',
            display_name='Suspended Found',
            category='EDUCATION',
            description='Suspended foundation due to compliance check failure.',
            year_established=2019,
            status=NGOProfile.Status.SUSPENDED,
            is_active=True,
        )

        # 7. Non-NGO Users
        self.user_without_profile = User.objects.create_user(
            email='no_profile@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='No Profile User',
            is_active=True,
        )
        self.donor_user = User.objects.create_user(
            email='donor_user@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Donor Individual',
            is_active=True,
        )
        self.company_user = User.objects.create_user(
            email='company_user@example.com',
            password='TestPassword123!',
            role='COMPANY',
            full_name='CSR Corporate Lead',
            is_active=True,
        )

        # 8. Campaigns
        # Campaign A (belongs to NGO A)
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Rural Mobile Clinics 2026',
            short_description='Mobile clinics for 25 remote hamlets',
            description='Detailed initiative for delivering healthcare services to underserved communities.',
            slug='rural-mobile-clinics-2026',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('400000.00'),
            raised_amount=Decimal('200000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # Campaign B (belongs to NGO B)
        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title='Digital Libraries 2026',
            short_description='Digital classrooms for tribal students',
            description='Setting up 10 computer centers with solar power and internet connectivity.',
            slug='digital-libraries-2026',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('300000.00'),
            raised_amount=Decimal('150000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 9. Milestones
        # Milestone A1 on Campaign A
        self.milestone_a1 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Procure Diagnostic Equipment',
            description='ECG, blood analyzers, and BP kits.',
            target_amount=Decimal('120000.00'),
            target_completion_date=self.today + datetime.timedelta(days=15),
            status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        )

        # Milestone A2 on Campaign A (Pending)
        self.milestone_a2 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=2,
            title='Field Staff Training',
            description='Orientation workshops for 10 community health workers.',
            target_amount=Decimal('50000.00'),
            target_completion_date=self.today + datetime.timedelta(days=30),
            status=CampaignMilestone.MilestoneStatus.PENDING,
        )

        # Milestone B1 on Campaign B
        self.milestone_b1 = CampaignMilestone.objects.create(
            campaign=self.campaign_b,
            sequence_number=1,
            title='Procure 40 Laptops',
            description='Purchase 40 educational laptops.',
            target_amount=Decimal('100000.00'),
            target_completion_date=self.today + datetime.timedelta(days=20),
            status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        )

        # 10. Existing Proofs
        photo_a = create_in_memory_image(name='proof_a1.jpg')
        self.proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a1,
            photo=photo_a,
            caption='ECG and analyzer delivery at primary center.',
            latitude=Decimal('28.613900'),
            longitude=Decimal('77.209000'),
            location_name='North Primary Health Center',
            beneficiary_count=200,
            beneficiary_type='HEALTHCARE_PATIENTS',
            spent_amount=Decimal('45000.00'),
            expense_breakdown={'analyzers': 45000},
            distribution_date=self.today,
            status=DistributionProof.Status.SUBMITTED,
            submitted_by=self.ngo_user_a,
            submitted_at=timezone.now(),
        )

        photo_b = create_in_memory_image(name='proof_b1.jpg')
        self.proof_b1 = DistributionProof.objects.create(
            milestone=self.milestone_b1,
            photo=photo_b,
            caption='Laptop delivery in block A.',
            latitude=Decimal('22.572600'),
            longitude=Decimal('88.363900'),
            location_name='Tribal Community School',
            beneficiary_count=80,
            beneficiary_type='CHILDREN_EDUCATION',
            spent_amount=Decimal('38000.00'),
            expense_breakdown={'laptops': 38000},
            distribution_date=self.today,
            status=DistributionProof.Status.SUBMITTED,
            submitted_by=self.ngo_user_b,
            submitted_at=timezone.now(),
        )

    # ============================================================
    # 1. AUTHENTICATION TESTS (401 Unauthorized)
    # ============================================================

    def test_unauthenticated_milestone_list_denied(self):
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_milestone_create_denied(self):
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.post(url, {'title': 'New Milestone'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_milestone_detail_denied(self):
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_milestone_update_denied(self):
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        response = self.client.patch(url, {'title': 'Hacked Title'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_proof_upload_denied(self):
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_proof_list_denied(self):
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ============================================================
    # 2. NGO STATUS & ROLE TESTS (403 Forbidden)
    # ============================================================

    def test_approved_active_ngo_allowed(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inactive_ngo_denied(self):
        self.client.force_authenticate(user=self.inactive_ngo_user)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_pending_ngo_denied(self):
        self.client.force_authenticate(user=self.pending_ngo_user)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejected_ngo_denied(self):
        self.client.force_authenticate(user=self.rejected_ngo_user)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_suspended_ngo_denied(self):
        self.client.force_authenticate(user=self.suspended_ngo_user)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_without_ngo_profile_denied(self):
        self.client.force_authenticate(user=self.user_without_profile)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_donor_role_denied(self):
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_role_denied(self):
        self.client.force_authenticate(user=self.company_user)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ============================================================
    # 3. CAMPAIGN OWNERSHIP & IDOR TESTS
    # ============================================================

    def test_own_campaign_milestones_list_success(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Handle paginated or direct list
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 2)
        titles = [m['title'] for m in results]
        self.assertIn('Procure Diagnostic Equipment', titles)
        self.assertIn('Field Staff Training', titles)

    def test_own_campaign_milestone_create_success(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_a.id})
        payload = {
            'sequence_number': 3,
            'title': 'Deploy Mobile Vans to Sector C',
            'description': 'Deploy 2 fully equipped mobile clinics to Sector C villages.',
            'target_amount': '80000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=45)),
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['sequence_number'], 3)
        self.assertEqual(response.data['status'], 'PENDING')
        self.assertEqual(str(response.data['campaign']), str(self.campaign_a.id))

    def test_foreign_campaign_milestones_list_denied(self):
        """NGO A must receive 404 when querying Campaign B's milestones (IDOR defense)."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_b.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_foreign_campaign_milestone_create_denied(self):
        """NGO A cannot inject milestones into Campaign B."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestones_list_create', kwargs={'campaign_id': self.campaign_b.id})
        payload = {
            'sequence_number': 2,
            'title': 'IDOR Injected Milestone',
            'description': 'Malicious cross-NGO milestone creation attempt.',
            'target_amount': '50000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=20)),
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ============================================================
    # 4. MILESTONE DETAIL & UPDATE TESTS
    # ============================================================

    def test_own_milestone_detail_success(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.milestone_a1.id))
        self.assertEqual(response.data['title'], 'Procure Diagnostic Equipment')
        self.assertEqual(response.data['proofs_count'], 1)

    def test_foreign_milestone_detail_denied(self):
        """NGO A cannot retrieve Milestone B1 (belongs to Campaign B / NGO B)."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_b1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_own_milestone_update_patch_success(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        payload = {
            'title': 'Procure Advanced Diagnostic Equipment',
            'target_amount': '135000.00',
        }
        response = self.client.patch(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Procure Advanced Diagnostic Equipment')
        self.assertEqual(Decimal(response.data['target_amount']), Decimal('135000.00'))

    def test_own_milestone_update_put_success(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        payload = {
            'sequence_number': 1,
            'title': 'Procure Full Clinic Equipment Set',
            'description': 'Complete set of analyzers and diagnostic units for 3 vans.',
            'target_amount': '140000.00',
            'target_completion_date': str(self.today + datetime.timedelta(days=20)),
        }
        response = self.client.put(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Procure Full Clinic Equipment Set')

    def test_foreign_milestone_update_denied(self):
        """NGO A cannot update Milestone B1."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_b1.id})
        response = self.client.patch(url, {'title': 'Hacked Title'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.milestone_b1.refresh_from_db()
        self.assertEqual(self.milestone_b1.title, 'Procure 40 Laptops')

    def test_invalid_uuid_handling(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = '/api/v1/ngo/campaigns/milestones/not-a-valid-uuid/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_verified_milestone_update_denied(self):
        """Once VERIFIED, a milestone is sealed; PUT/PATCH returns 400."""
        self.milestone_a1.status = CampaignMilestone.MilestoneStatus.VERIFIED
        self.milestone_a1.save(update_fields=['status'])

        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        response = self.client.patch(url, {'title': 'Attempted Sealed Update'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sealed', str(response.data).lower())

    def test_campaign_reassignment_blocked(self):
        """Passing another campaign ID in milestone update payload is ignored/blocked."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_detail', kwargs={'pk': self.milestone_a1.id})
        payload = {
            'campaign': str(self.campaign_b.id),
            'title': 'Campaign Reassignment Test',
        }
        response = self.client.patch(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.milestone_a1.refresh_from_db()
        self.assertEqual(self.milestone_a1.campaign_id, self.campaign_a.id)

    # ============================================================
    # 5. DISTRIBUTION PROOF MULTIPART UPLOAD TESTS
    # ============================================================

    def test_valid_proof_multipart_upload_success(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        photo = create_in_memory_image(name='upload_evidence.jpg')
        payload = {
            'photo': photo,
            'caption': 'Medical kits delivered to Primary Health Center 4.',
            'latitude': '28.613900',
            'longitude': '77.209000',
            'location_name': 'PHC 4, Rural Sonitpur',
            'beneficiary_count': '350',
            'beneficiary_type': 'HEALTHCARE_PATIENTS',
            'beneficiary_notes': 'Primary checkup completed for 350 rural elders.',
            'spent_amount': '32000.00',
            'expense_breakdown': '{"ecg_units": 20000, "analyzer_reagents": 12000}',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'SUBMITTED')
        self.assertEqual(response.data['caption'], 'Medical kits delivered to Primary Health Center 4.')
        self.assertEqual(str(response.data['submitted_by']), str(self.ngo_user_a.id))
        self.assertIsNotNone(response.data['photo_url'])
        self.assertIsNone(response.data['reviewed_by'])

    def test_foreign_milestone_proof_upload_denied(self):
        """NGO A cannot upload proof for Milestone B1 (belongs to Campaign B)."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_b1.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'Cross-NGO upload attack',
            'spent_amount': '1000.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_valid_gps_accepted(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'GPS Boundary Acceptance Test',
            'latitude': '89.999999',
            'longitude': '179.999999',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_invalid_gps_rejected(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'Invalid Latitude Test',
            'latitude': '95.000000',  # Out of range (>90)
            'longitude': '77.209000',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('latitude', str(response.data).lower())

    def test_invalid_image_extension_rejected(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        fake_file = SimpleUploadedFile('document.txt', b'Hello world text', content_type='text/plain')
        payload = {
            'photo': fake_file,
            'caption': 'Invalid file upload',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_image_rejected(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        large_bytes = b'0' * (6 * 1024 * 1024)  # 6 MB (> 5 MB)
        large_file = SimpleUploadedFile('large.jpg', large_bytes, content_type='image/jpeg')
        payload = {
            'photo': large_file,
            'caption': 'Oversized file upload',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_corrupted_image_rejected(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        corrupt_file = SimpleUploadedFile('corrupt.jpg', b'\xFF\xD8\xFFFakeCorruptedBytes', content_type='image/jpeg')
        payload = {
            'photo': corrupt_file,
            'caption': 'Corrupted image upload',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_forged_submitted_by_blocked(self):
        """Passing another user ID in submitted_by is ignored; server enforces request.user."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'Spoofing submitted_by test',
            'submitted_by': str(self.ngo_user_b.id),  # Malicious attempt
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data['submitted_by']), str(self.ngo_user_a.id))

    def test_forged_status_blocked(self):
        """Passing status='VERIFIED' in proof upload is ignored; status is forced to SUBMITTED."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'Status escalation test',
            'status': 'VERIFIED',  # Malicious attempt
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'SUBMITTED')

    def test_premature_proof_upload_pending_milestone_rejected(self):
        """Proof cannot be uploaded for milestone_a2 which is still in PENDING status."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a2.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'Premature proof attempt',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('in_progress' in str(response.data).lower() or 'pending' in str(response.data).lower())

    def test_late_proof_upload_verified_milestone_rejected(self):
        """Proof cannot be uploaded for a milestone already sealed in VERIFIED status."""
        self.milestone_a1.status = CampaignMilestone.MilestoneStatus.VERIFIED
        self.milestone_a1.save(update_fields=['status'])

        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_milestone_proof_upload', kwargs={'pk': self.milestone_a1.id})
        photo = create_in_memory_image()
        payload = {
            'photo': photo,
            'caption': 'Late proof attempt',
            'spent_amount': '500.00',
            'distribution_date': str(self.today),
        }
        response = self.client.post(url, payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('verified', str(response.data).lower())

    # ============================================================
    # 6. DISTRIBUTION PROOF LIST & MULTI-TENANT ISOLATION TESTS
    # ============================================================

    def test_proof_list_ngo_a_scoping(self):
        """NGO A sees only Proof A1 in the proof list."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.proof_a1.id))
        self.assertEqual(results[0]['caption'], 'ECG and analyzer delivery at primary center.')

    def test_proof_list_ngo_b_scoping(self):
        """NGO B sees only Proof B1 in the proof list."""
        self.client.force_authenticate(user=self.ngo_user_b)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.proof_b1.id))
        self.assertEqual(results[0]['caption'], 'Laptop delivery in block A.')

    def test_proof_list_no_cross_tenant_leakage(self):
        """Ensures that no matter what parameters are passed, NGO A never sees Proof B1."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"{reverse('ngo_distribution_proof_list')}?campaign={self.campaign_b.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 0, 'Cross-tenant query parameter must return empty set.')

    def test_proof_list_filtering_by_status_and_milestone(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        # Filter by SUBMITTED
        url = f"{reverse('ngo_distribution_proof_list')}?status=SUBMITTED&milestone={self.milestone_a1.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 1)

        # Filter by VERIFIED (should be empty for NGO A)
        url2 = f"{reverse('ngo_distribution_proof_list')}?status=VERIFIED"
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        results2 = response2.data['results'] if 'results' in response2.data else response2.data
        self.assertEqual(len(results2), 0)

    def test_proof_list_ngo_without_profile_returns_403_with_detail(self):
        """User with role NGO but missing NGOProfile receives 403 'NGO Profile does not exist.'."""
        self.client.force_authenticate(user=self.user_without_profile)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'NGO Profile does not exist.')

    def test_proof_list_pending_submitted_ngo_returns_403(self):
        """NGO user with SUBMITTED status receives 403 explaining only approved NGOs can manage."""
        self.client.force_authenticate(user=self.pending_ngo_user)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Only approved NGOs can manage campaigns', response.data['detail'])
        self.assertIn('SUBMITTED', response.data['detail'])

    def test_proof_list_draft_ngo_returns_403(self):
        """NGO user with DRAFT profile receives 403 explaining current status is DRAFT."""
        draft_user = User.objects.create_user(
            email='draft_ngo@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Draft Lead',
            is_active=True,
        )
        NGOProfile.objects.create(
            user=draft_user,
            legal_name='Draft NGO Foundation',
            display_name='Draft NGO',
            category='EDUCATION',
            description='Draft documentation.',
            year_established=2022,
            status=NGOProfile.Status.DRAFT,
            is_active=True,
        )
        self.client.force_authenticate(user=draft_user)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Only approved NGOs can manage campaigns', response.data['detail'])
        self.assertIn('DRAFT', response.data['detail'])

    def test_proof_list_donor_role_forbidden(self):
        """Donor role is forbidden from accessing NGO distribution proofs."""
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_proof_list_company_role_forbidden(self):
        """Company role is forbidden from accessing NGO distribution proofs."""
        self.client.force_authenticate(user=self.company_user)
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_proof_list_unauthenticated_returns_401(self):
        """Unauthenticated request to proof list returns 401."""
        url = reverse('ngo_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ============================================================
    # 7. REGRESSION ON EXISTING CAMPAIGN ENDPOINTS
    # ============================================================

    def test_existing_campaign_list_create_unaffected(self):
        """Verify GET /api/v1/ngo/campaigns/ remains functional."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_list_create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.campaign_a.id))

    def test_existing_campaign_submit_review_unaffected(self):
        """Verify POST /api/v1/ngo/campaigns/<id>/submit-review/ remains functional."""
        draft_campaign = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Draft Appeal for Clean Water',
            short_description='Water filters for school compounds',
            description='Installation of commercial RO water filtration units in 10 schools.',
            slug='draft-appeal-clean-water',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('100000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('ngo_campaign_submit_review', kwargs={'pk': draft_campaign.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        draft_campaign.refresh_from_db()
        self.assertEqual(draft_campaign.status, Campaign.Status.PENDING_REVIEW)
