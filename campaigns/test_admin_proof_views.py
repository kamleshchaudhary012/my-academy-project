"""
HTTP View Tests for Admin Distribution Proof Moderation APIs.

Phase 5.2.4 — Administrative Moderation Queue & Evidence Decision Engine.
Endpoints tested:
1. GET   /api/v1/admin/campaigns/distribution-proofs/
2. GET   /api/v1/admin/campaigns/distribution-proofs/<uuid:pk>/
3. POST  /api/v1/admin/campaigns/distribution-proofs/<uuid:pk>/start-review/
4. POST  /api/v1/admin/campaigns/distribution-proofs/<uuid:pk>/verify/
5. POST  /api/v1/admin/campaigns/distribution-proofs/<uuid:pk>/request-changes/
6. POST  /api/v1/admin/campaigns/distribution-proofs/<uuid:pk>/reject/

Covers:
- Authentication enforcement (Unauthenticated -> 401)
- Role-Based Access Control (Admin allowed, NGO/Donor/Company/Inactive -> 403)
- List, Search, Status, and Campaign filtering
- Detail view inspection with administrative fields
- State machine lifecycle transitions & row-locking delegation:
    SUBMITTED -> UNDER_REVIEW -> (VERIFIED | REVISION_REQUESTED | REJECTED)
- Rejection reason enforcement (missing/blank -> 400)
- Terminal state locking (VERIFIED and REJECTED proofs cannot be re-moderated)
- Cross-NGO global administrative scope
- Non-admin tenant isolation (NGO cannot access admin moderation URLs)
"""

import datetime
from decimal import Decimal
import io
import os
import shutil
import uuid

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
TEMP_MEDIA_ROOT = '/tmp/daangives_admin_proof_test_media'


def create_in_memory_image(name='evidence.jpg', size=(300, 300), color='green', format='JPEG'):
    file_obj = io.BytesIO()
    image = Image.new('RGB', size, color)
    image.save(file_obj, format=format)
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type=f'image/{format.lower()}')


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class AdminDistributionProofAPITests(APITestCase):
    """
    Comprehensive integration and security test suite for Phase 5.2.4 Admin Moderation APIs.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if os.path.exists(TEMP_MEDIA_ROOT):
            shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=90)

        # 1. Platform Administrator User
        self.admin_user = User.objects.create_user(
            email='platform_admin@daangives.org',
            password='AdminPassword123!',
            role='ADMIN',
            full_name='Chief Moderator',
            is_active=True,
            is_staff=True,
        )

        # 2. Inactive Admin User
        self.inactive_admin = User.objects.create_user(
            email='inactive_admin@daangives.org',
            password='AdminPassword123!',
            role='ADMIN',
            full_name='Inactive Moderator',
            is_active=False,
            is_staff=True,
        )

        # 3. NGO User & Profile A
        self.ngo_user_a = User.objects.create_user(
            email='ngo_alpha@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Lead NGO Alpha',
            is_active=True,
        )
        self.ngo_profile_a = NGOProfile.objects.create(
            user=self.ngo_user_a,
            legal_name='Alpha Rural Development Trust',
            display_name='Alpha Trust',
            category='HEALTHCARE',
            description='Healthcare infrastructure and medical camp delivery in rural belts.',
            year_established=2015,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # 4. NGO User & Profile B
        self.ngo_user_b = User.objects.create_user(
            email='ngo_beta@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Lead NGO Beta',
            is_active=True,
        )
        self.ngo_profile_b = NGOProfile.objects.create(
            user=self.ngo_user_b,
            legal_name='Beta Clean Energy Initiative',
            display_name='Beta Initiative',
            category='ENVIRONMENT',
            description='Community solar lighting and environmental education initiatives.',
            year_established=2018,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # 5. Non-admin users: Donor and Company
        self.donor_user = User.objects.create_user(
            email='donor_user@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Generous Donor',
            is_active=True,
        )
        self.company_user = User.objects.create_user(
            email='csr_rep@example.com',
            password='TestPassword123!',
            role='COMPANY',
            full_name='CSR Officer',
            is_active=True,
        )

        # 6. Campaign & Milestones for NGO A
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Primary Health Clinic Expansion Drive',
            short_description='Expanding primary clinics in remote villages.',
            description='Detailed medical campaign specification for rural clinic upgrades.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('500000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.milestone_a = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Diagnostic Equipment Delivery',
            description='Procurement and delivery of analyzers to rural health clinic.',
            target_amount=Decimal('150000.00'),
            target_completion_date=self.today + datetime.timedelta(days=30),
            status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        )

        # 7. Campaign & Milestones for NGO B
        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title='Solar Micro-Grid Installation',
            short_description='Solar power installation for 5 tribal schools.',
            description='Installing solar micro-grids across remote educational facilities.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('350000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.milestone_b = CampaignMilestone.objects.create(
            campaign=self.campaign_b,
            sequence_number=1,
            title='Procurement of Solar Panels',
            description='Ordering and dispatch of solar arrays and battery units.',
            target_amount=Decimal('120000.00'),
            target_completion_date=self.today + datetime.timedelta(days=25),
            status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        )

        # 8. Test Proofs
        # Proof A1: SUBMITTED
        self.proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a,
            photo=create_in_memory_image(name='proof_a1.jpg', color='blue'),
            caption='Batch 1 blood analyzers delivered to Primary Health Center 1.',
            location_name='Navsari Village Clinic',
            latitude=Decimal('20.946700'),
            longitude=Decimal('72.952000'),
            beneficiary_count=120,
            beneficiary_type='RURAL_POPULATION',
            spent_amount=Decimal('45000.00'),
            expense_breakdown={'analyzers': 40000, 'logistics': 5000},
            distribution_date=self.today,
            status=DistributionProof.Status.SUBMITTED,
            submitted_by=self.ngo_user_a,
            submitted_at=timezone.now(),
        )

        # Proof A2: UNDER_REVIEW
        self.proof_a2 = DistributionProof.objects.create(
            milestone=self.milestone_a,
            photo=create_in_memory_image(name='proof_a2.jpg', color='cyan'),
            caption='Batch 2 diagnostic kits handed to village health officer.',
            location_name='Valsad Health Center',
            latitude=Decimal('20.610000'),
            longitude=Decimal('72.930000'),
            beneficiary_count=85,
            beneficiary_type='WOMEN',
            spent_amount=Decimal('35000.00'),
            expense_breakdown={'kits': 32000, 'freight': 3000},
            distribution_date=self.today,
            status=DistributionProof.Status.UNDER_REVIEW,
            submitted_by=self.ngo_user_a,
            submitted_at=timezone.now() - datetime.timedelta(days=1),
            reviewed_by=self.admin_user,
            reviewed_at=timezone.now(),
            admin_notes='Review commenced.',
        )

        # Proof B1: SUBMITTED (NGO B)
        self.proof_b1 = DistributionProof.objects.create(
            milestone=self.milestone_b,
            photo=create_in_memory_image(name='proof_b1.jpg', color='yellow'),
            caption='First 15 solar panels installed on tribal school rooftop.',
            location_name='Ahwa Tribal High School',
            latitude=Decimal('20.758000'),
            longitude=Decimal('73.687000'),
            beneficiary_count=210,
            beneficiary_type='CHILDREN',
            spent_amount=Decimal('80000.00'),
            expense_breakdown={'panels': 70000, 'inverters': 10000},
            distribution_date=self.today,
            status=DistributionProof.Status.SUBMITTED,
            submitted_by=self.ngo_user_b,
            submitted_at=timezone.now(),
        )

    # =========================================================================
    # A. AUTHENTICATION TESTS (401 Unauthorized for anonymous callers)
    # =========================================================================

    def test_anonymous_proof_list_denied(self):
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_proof_detail_denied(self):
        url = reverse('admin_distribution_proof_detail', kwargs={'pk': self.proof_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_start_review_denied(self):
        url = reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_a1.id})
        response = self.client.post(url, {'admin_notes': 'test'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_verify_denied(self):
        url = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_request_changes_denied(self):
        url = reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {'rejection_reason': 'Need receipt'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_reject_denied(self):
        url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {'rejection_reason': 'Fraudulent'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # =========================================================================
    # B. ROLE-BASED ACCESS CONTROL (RBAC) TESTS
    # =========================================================================

    def test_admin_allowed_access(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ngo_role_denied_admin_endpoints(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_donor_role_denied_admin_endpoints(self):
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_role_denied_admin_endpoints(self):
        self.client.force_authenticate(user=self.company_user)
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_admin_denied(self):
        self.client.force_authenticate(user=self.inactive_admin)
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # =========================================================================
    # C. ADMIN PROOF LIST & FILTERING TESTS
    # =========================================================================

    def test_admin_list_proofs_global_visibility(self):
        """Admin sees proofs across all NGOs (A and B)."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data['results'] if 'results' in response.data else response.data
        proof_ids = [item['id'] for item in results]
        self.assertIn(str(self.proof_a1.id), proof_ids)
        self.assertIn(str(self.proof_a2.id), proof_ids)
        self.assertIn(str(self.proof_b1.id), proof_ids)

    def test_admin_list_filter_by_status(self):
        """Filter proofs by status=UNDER_REVIEW."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_list') + '?status=UNDER_REVIEW'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data['results'] if 'results' in response.data else response.data
        self.assertTrue(all(item['status'] == 'UNDER_REVIEW' for item in results))
        proof_ids = [item['id'] for item in results]
        self.assertIn(str(self.proof_a2.id), proof_ids)
        self.assertNotIn(str(self.proof_a1.id), proof_ids)

    def test_admin_list_filter_by_campaign(self):
        """Filter proofs by campaign UUID."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_list') + f'?campaign={self.campaign_b.id}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.proof_b1.id))

    def test_admin_list_search_filter(self):
        """Search across caption and location_name."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_list') + '?search=rooftop'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.proof_b1.id))

    # =========================================================================
    # D. ADMIN PROOF DETAIL TESTS
    # =========================================================================

    def test_admin_detail_proof_success(self):
        """Admin retrieves full proof detail including administrative fields."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_detail', kwargs={'pk': self.proof_a2.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.proof_a2.id))
        self.assertEqual(response.data['status'], 'UNDER_REVIEW')
        self.assertEqual(response.data['admin_notes'], 'Review commenced.')
        self.assertEqual(str(response.data['reviewed_by']), str(self.admin_user.id))
        self.assertIsNotNone(response.data['reviewed_at'])

    def test_admin_detail_nonexistent_uuid_404(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_detail', kwargs={'pk': uuid.uuid4()})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # E. START REVIEW TESTS (SUBMITTED -> UNDER_REVIEW)
    # =========================================================================

    def test_start_review_success(self):
        """Admin transitions proof from SUBMITTED to UNDER_REVIEW."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_a1.id})
        payload = {'admin_notes': 'Commencing verification of medical kits.'}
        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'UNDER_REVIEW')
        self.assertEqual(response.data['admin_notes'], 'Commencing verification of medical kits.')
        self.assertEqual(str(response.data['reviewed_by']), str(self.admin_user.id))
        self.assertIsNotNone(response.data['reviewed_at'])

        self.proof_a1.refresh_from_db()
        self.assertEqual(self.proof_a1.status, DistributionProof.Status.UNDER_REVIEW)

    def test_start_review_on_under_review_fails(self):
        """Cannot start review on a proof that is already UNDER_REVIEW."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # =========================================================================
    # F. VERIFY TESTS (UNDER_REVIEW -> VERIFIED)
    # =========================================================================

    def test_verify_proof_success(self):
        """Admin approves and verifies a proof in UNDER_REVIEW status."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a2.id})
        payload = {'admin_notes': 'GPS geotag confirmed authentic. Receipt ledger audited.'}
        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'VERIFIED')
        self.assertEqual(response.data['admin_notes'], 'GPS geotag confirmed authentic. Receipt ledger audited.')
        self.assertEqual(str(response.data['reviewed_by']), str(self.admin_user.id))
        self.assertIsNotNone(response.data['reviewed_at'])

        self.proof_a2.refresh_from_db()
        self.assertEqual(self.proof_a2.status, DistributionProof.Status.VERIFIED)

    def test_verify_directly_from_submitted_fails(self):
        """Direct verification of SUBMITTED proof without UNDER_REVIEW is rejected."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a1.id})
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('under_review', response.data['detail'].lower())

    # =========================================================================
    # G. REQUEST CHANGES TESTS (UNDER_REVIEW -> REVISION_REQUESTED)
    # =========================================================================

    def test_request_changes_success(self):
        """Admin requests revisions from NGO with mandatory reason."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a2.id})
        payload = {
            'rejection_reason': 'Photo is blurry. Please provide a legible photo of the serial number.',
            'admin_notes': 'Notified NGO coordinator via platform.',
        }
        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'REVISION_REQUESTED')
        self.assertEqual(response.data['rejection_reason'], 'Photo is blurry. Please provide a legible photo of the serial number.')
        self.assertEqual(response.data['admin_notes'], 'Notified NGO coordinator via platform.')

        self.proof_a2.refresh_from_db()
        self.assertEqual(self.proof_a2.status, DistributionProof.Status.REVISION_REQUESTED)

        # Parent milestone synchronized to REVISION_REQUESTED
        self.milestone_a.refresh_from_db()
        self.assertEqual(self.milestone_a.status, CampaignMilestone.MilestoneStatus.REVISION_REQUESTED)

    def test_request_changes_missing_reason_fails(self):
        """Missing rejection_reason returns 400 Bad Request."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {'admin_notes': 'note only'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_changes_blank_reason_fails(self):
        """Blank rejection_reason returns 400 Bad Request."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {'rejection_reason': '   '}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_changes_on_submitted_fails(self):
        """Request changes on SUBMITTED proof without review returns 400."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a1.id})
        response = self.client.post(url, {'rejection_reason': 'Fix image'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # =========================================================================
    # H. REJECT TESTS (UNDER_REVIEW -> REJECTED)
    # =========================================================================

    def test_reject_proof_success(self):
        """Admin formally rejects an illegitimate or duplicate proof."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id})
        payload = {
            'rejection_reason': 'Evidence belongs to an unrelated medical mission conducted in 2024.',
            'admin_notes': 'Duplicate EXIF signature verified with external database.',
        }
        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'REJECTED')
        self.assertEqual(response.data['rejection_reason'], 'Evidence belongs to an unrelated medical mission conducted in 2024.')
        self.assertEqual(response.data['admin_notes'], 'Duplicate EXIF signature verified with external database.')

        self.proof_a2.refresh_from_db()
        self.assertEqual(self.proof_a2.status, DistributionProof.Status.REJECTED)

    def test_reject_missing_reason_fails(self):
        """Missing rejection_reason returns 400 Bad Request."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_blank_reason_fails(self):
        """Blank rejection_reason returns 400 Bad Request."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id})
        response = self.client.post(url, {'rejection_reason': '   '}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_on_submitted_fails(self):
        """Rejecting a SUBMITTED proof directly without review returns 400."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a1.id})
        response = self.client.post(url, {'rejection_reason': 'Rejected'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # =========================================================================
    # I. TERMINAL STATE PROTECTION TESTS
    # =========================================================================

    def test_verified_proof_is_terminal(self):
        """Once VERIFIED, a proof cannot be transitioned or modified."""
        self.client.force_authenticate(user=self.admin_user)
        # 1. Move proof_a2 to VERIFIED
        verify_url = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(verify_url, {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 2. Attempt start-review -> 400
        start_url = reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(start_url, {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Attempt request-changes -> 400
        req_url = reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(req_url, {'rejection_reason': 'Try changing'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 4. Attempt reject -> 400
        rej_url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(rej_url, {'rejection_reason': 'Try rejecting'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejected_proof_is_terminal(self):
        """Once REJECTED, a proof cannot be transitioned or modified."""
        self.client.force_authenticate(user=self.admin_user)
        # 1. Reject proof_a2
        rej_url = reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(rej_url, {'rejection_reason': 'Permanently rejected'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 2. Attempt verify -> 400
        verify_url = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(verify_url, {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Attempt start-review -> 400
        start_url = reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_a2.id})
        res = self.client.post(start_url, {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # =========================================================================
    # J. CROSS-NGO GLOBAL ADMIN ACCESS
    # =========================================================================

    def test_cross_ngo_admin_access(self):
        """Admin can moderate proofs from NGO A and NGO B with global authority."""
        self.client.force_authenticate(user=self.admin_user)

        # Moderate NGO A proof
        verify_url = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a2.id})
        res_a = self.client.post(verify_url, {}, format='json')
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)

        # Moderate NGO B proof (first start review, then verify)
        start_url_b = reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_b1.id})
        res_b1 = self.client.post(start_url_b, {}, format='json')
        self.assertEqual(res_b1.status_code, status.HTTP_200_OK)

        verify_url_b = reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_b1.id})
        res_b2 = self.client.post(verify_url_b, {'admin_notes': 'Solar installation verified.'}, format='json')
        self.assertEqual(res_b2.status_code, status.HTTP_200_OK)

        self.proof_a2.refresh_from_db()
        self.proof_b1.refresh_from_db()
        self.assertEqual(self.proof_a2.status, DistributionProof.Status.VERIFIED)
        self.assertEqual(self.proof_b1.status, DistributionProof.Status.VERIFIED)

    # =========================================================================
    # K. NON-ADMIN TENANT ISOLATION
    # =========================================================================

    def test_ngo_cannot_use_admin_urls_for_own_proof(self):
        """Owning NGO cannot access Admin moderation URLs for its own proof."""
        self.client.force_authenticate(user=self.ngo_user_a)

        # 1. List
        res = self.client.get(reverse('admin_distribution_proof_list'))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Detail
        res = self.client.get(reverse('admin_distribution_proof_detail', kwargs={'pk': self.proof_a1.id}))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Start review
        res = self.client.post(reverse('admin_distribution_proof_start_review', kwargs={'pk': self.proof_a1.id}), {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Verify
        res = self.client.post(reverse('admin_distribution_proof_verify', kwargs={'pk': self.proof_a2.id}), {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 5. Request changes
        res = self.client.post(reverse('admin_distribution_proof_request_changes', kwargs={'pk': self.proof_a2.id}), {'rejection_reason': 'test'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 6. Reject
        res = self.client.post(reverse('admin_distribution_proof_reject', kwargs={'pk': self.proof_a2.id}), {'rejection_reason': 'test'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
