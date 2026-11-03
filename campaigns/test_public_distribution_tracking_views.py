"""
HTTP View Tests for Public and Donor Verified Distribution Proof Tracking APIs.

Phase 5.2.5 — Transparency & Field Evidence Verification Tracking.
Endpoints tested:
1. GET /api/v1/public/campaigns/<slug:slug>/tracking/
2. GET /api/v1/public/campaigns/<uuid:campaign_id>/distribution-proofs/
3. GET /api/v1/public/campaigns/distribution-proofs/<uuid:pk>/

Covers:
- AllowAny open public access (Anonymous visitors allowed)
- Authenticated Donor access to the same public tracking endpoints
- Authenticated NGO, Company, and Admin access (no role blocks on public endpoints)
- VERIFIED-only queryset filtering (SUBMITTED, UNDER_REVIEW, REVISION_REQUESTED, REJECTED strictly hidden)
- 404 Not Found response for unverified proof detail lookup (never 403, no status leakage)
- Administrative metadata protection (admin_notes, rejection_reason, submitted_by, reviewed_by never leaked)
- Cross-campaign IDOR protection (campaign proof list only returns proofs for that campaign)
- Cross-NGO appeal isolation
- Inactive, draft, and unapproved campaign protection (returns 404)
- Correct serialization via DistributionProofPublicSerializer and CampaignMilestonePublicSerializer
- Milestone progress and verified expenditure calculations
- Zero financial side effects (read-only verification)
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
TEMP_MEDIA_ROOT = '/tmp/daangives_public_tracking_test_media'


def create_in_memory_image(name='evidence.jpg', size=(300, 300), color='blue', format='JPEG'):
    file_obj = io.BytesIO()
    image = Image.new('RGB', size, color)
    image.save(file_obj, format=format)
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type=f'image/{format.lower()}')


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class PublicDistributionTrackingAPITests(APITestCase):
    """
    Comprehensive test suite for Phase 5.2.5 Public and Donor Tracking APIs.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if os.path.exists(TEMP_MEDIA_ROOT):
            shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=90)

        # 1. Platform Admin User
        self.admin_user = User.objects.create_user(
            email='admin@daangives.org',
            password='AdminPassword123!',
            role='ADMIN',
            full_name='Platform Admin',
            is_active=True,
            is_staff=True,
        )

        # 2. NGO User A & Approved Profile A
        self.ngo_user_a = User.objects.create_user(
            email='ngo_alpha@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Alpha Officer',
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

        # 3. NGO User B & Approved Profile B
        self.ngo_user_b = User.objects.create_user(
            email='ngo_beta@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Beta Officer',
            is_active=True,
        )
        self.ngo_profile_b = NGOProfile.objects.create(
            user=self.ngo_user_b,
            legal_name='Beta Clean Energy Trust',
            display_name='Beta Energy',
            category='ENVIRONMENT',
            description='Solar electrification for off-grid rural communities.',
            year_established=2018,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # 4. Donor User
        self.donor_user = User.objects.create_user(
            email='donor_rohit@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Rohit Sharma',
            is_active=True,
        )

        # 5. Corporate Representative
        self.company_user = User.objects.create_user(
            email='csr_rep@tata.com',
            password='TestPassword123!',
            role='COMPANY',
            full_name='Tata CSR Lead',
            is_active=True,
        )

        # 6. Active Public Campaign A (belonging to NGO A)
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Rural Mobile Health Clinic Appeal',
            slug='rural-mobile-health-clinic-appeal',
            category='HEALTHCARE',
            campaign_type='MONETARY',
            short_description='Providing fully equipped mobile medical clinics.',
            description='Extended medical reach to 50 remote tribal villages in Maharashtra.',
            target_amount=Decimal('500000.00'),
            raised_amount=Decimal('350000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 7. Milestones for Campaign A
        self.milestone_a1 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Procure Clinic Vans and Diagnostic Kits',
            description='Purchase 2 specialized utility vehicles and portable ECG machines.',
            target_amount=Decimal('250000.00'),
            target_completion_date=self.today + datetime.timedelta(days=30),
            status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        )
        self.milestone_a2 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=2,
            title='Doctor Deployment and First 20 Village Camps',
            description='Conduct initial outreach screening for 1,000 tribal residents.',
            target_amount=Decimal('250000.00'),
            target_completion_date=self.today + datetime.timedelta(days=60),
            status=CampaignMilestone.MilestoneStatus.PENDING,
        )

        # 8. Active Public Campaign B (belonging to NGO B)
        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title='Solar Microgrid Electrification Drive',
            slug='solar-microgrid-electrification-drive',
            category='ENVIRONMENT',
            campaign_type='MONETARY',
            short_description='Community solar lighting installations.',
            description='Install solar panels and storage units in un-electrified hamlet.',
            target_amount=Decimal('300000.00'),
            raised_amount=Decimal('150000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.milestone_b1 = CampaignMilestone.objects.create(
            campaign=self.campaign_b,
            sequence_number=1,
            title='Procure 50 Solar Panels',
            description='Purchase high-efficiency PV modules and inverters.',
            target_amount=Decimal('150000.00'),
            target_completion_date=self.today + datetime.timedelta(days=20),
            status=CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        )

        # 9. Draft / Unpublished Campaign (belonging to NGO A)
        self.draft_campaign = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Unpublished Internal Draft Campaign',
            slug='unpublished-internal-draft-campaign',
            category='HEALTHCARE',
            campaign_type='MONETARY',
            short_description='Internal draft appeal not yet reviewed by admin.',
            description='Private draft details for internal review and not yet approved by platform admin.',
            target_amount=Decimal('100000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        self.draft_milestone = CampaignMilestone.objects.create(
            campaign=self.draft_campaign,
            sequence_number=1,
            title='Draft Milestone 1',
            description='Private draft milestone.',
            target_amount=Decimal('50000.00'),
            target_completion_date=self.today + datetime.timedelta(days=30),
            status=CampaignMilestone.MilestoneStatus.PENDING,
        )

        # 10. Distribution Proofs for Campaign A, Milestone A1 in various states
        self.verified_proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a1,
            photo=create_in_memory_image(name='van_procurement_verified.jpg'),
            caption='Delivery receipt and handover of 2 Mahindra Bolero clinic vans at Nashik.',
            latitude=Decimal('19.997453'),
            longitude=Decimal('73.789802'),
            location_name='Nashik District Collectorate, Maharashtra',
            beneficiary_count=250,
            beneficiary_type='GENERAL_RURAL',
            beneficiary_notes='Local healthcare committee members present for inspection.',
            spent_amount=Decimal('185000.00'),
            expense_breakdown={'vehicle_purchase': 160000, 'chassis_retrofitting': 25000},
            distribution_date=self.today - datetime.timedelta(days=2),
            status=DistributionProof.Status.VERIFIED,
            submitted_by=self.ngo_user_a,
            submitted_at=timezone.now() - datetime.timedelta(days=3),
            reviewed_by=self.admin_user,
            reviewed_at=timezone.now() - datetime.timedelta(days=1),
            admin_notes='Verified against RTO registration and GST invoice.',
            rejection_reason='',
        )

        self.submitted_proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a1,
            photo=create_in_memory_image(name='medical_supplies_submitted.jpg'),
            caption='Initial shipment of stethoscope and diagnostic toolkits.',
            latitude=Decimal('19.997453'),
            longitude=Decimal('73.789802'),
            location_name='Nashik Warehouse',
            beneficiary_count=50,
            beneficiary_type='GENERAL_RURAL',
            spent_amount=Decimal('25000.00'),
            expense_breakdown={'stethoscopes': 10000, 'bp_monitors': 15000},
            distribution_date=self.today - datetime.timedelta(days=1),
            status=DistributionProof.Status.SUBMITTED,
            submitted_by=self.ngo_user_a,
            submitted_at=timezone.now() - datetime.timedelta(hours=10),
            admin_notes='',
            rejection_reason='',
        )

        self.under_review_proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a1,
            photo=create_in_memory_image(name='testing_kits_under_review.jpg'),
            caption='Rapid testing diagnostic kits under inspection.',
            distribution_date=self.today - datetime.timedelta(days=1),
            spent_amount=Decimal('15000.00'),
            status=DistributionProof.Status.UNDER_REVIEW,
            submitted_by=self.ngo_user_a,
            reviewed_by=self.admin_user,
            admin_notes='Verification in progress with supplier invoice.',
        )

        self.revision_requested_proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a1,
            photo=create_in_memory_image(name='blurry_receipt.jpg'),
            caption='Blurry receipt submission.',
            distribution_date=self.today - datetime.timedelta(days=1),
            spent_amount=Decimal('5000.00'),
            status=DistributionProof.Status.REVISION_REQUESTED,
            submitted_by=self.ngo_user_a,
            reviewed_by=self.admin_user,
            admin_notes='Blurry photo.',
            rejection_reason='Please upload high-resolution GST invoice.',
        )

        self.rejected_proof_a1 = DistributionProof.objects.create(
            milestone=self.milestone_a1,
            photo=create_in_memory_image(name='invalid_claim.jpg'),
            caption='Non-compliant expense claim.',
            distribution_date=self.today - datetime.timedelta(days=1),
            spent_amount=Decimal('12000.00'),
            status=DistributionProof.Status.REJECTED,
            submitted_by=self.ngo_user_a,
            reviewed_by=self.admin_user,
            admin_notes='Expense outside campaign scope.',
            rejection_reason='Ineligible administrative expenditure.',
        )

        # 11. Verified Distribution Proof for Campaign B
        self.verified_proof_b1 = DistributionProof.objects.create(
            milestone=self.milestone_b1,
            photo=create_in_memory_image(name='solar_panels_batch1.jpg'),
            caption='Delivery of 50 monocrystalline solar modules at village site.',
            latitude=Decimal('20.904221'),
            longitude=Decimal('74.774889'),
            location_name='Dhule Village Square, Maharashtra',
            beneficiary_count=120,
            beneficiary_type='GENERAL_RURAL',
            spent_amount=Decimal('140000.00'),
            expense_breakdown={'panels': 110000, 'cables_and_stands': 30000},
            distribution_date=self.today - datetime.timedelta(days=5),
            status=DistributionProof.Status.VERIFIED,
            submitted_by=self.ngo_user_b,
            submitted_at=timezone.now() - datetime.timedelta(days=6),
            reviewed_by=self.admin_user,
            reviewed_at=timezone.now() - datetime.timedelta(days=4),
            admin_notes='Verified with transit waybill and serial numbers.',
        )

    # =========================================================================
    # A. PUBLIC ACCESS (ANONYMOUS USERS)
    # =========================================================================

    def test_anonymous_access_campaign_tracking(self):
        """Anonymous public visitor can retrieve campaign tracking overview."""
        url = reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('campaign', response.data)
        self.assertIn('milestones', response.data)
        self.assertIn('verified_distribution_proofs', response.data)
        self.assertIn('total_verified_spent', response.data)
        self.assertEqual(response.data['campaign']['slug'], self.campaign_a.slug)

    def test_anonymous_access_verified_proof_list(self):
        """Anonymous public visitor can retrieve campaign-scoped verified proofs."""
        url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)

    def test_anonymous_access_verified_proof_detail(self):
        """Anonymous public visitor can retrieve single verified proof detail."""
        url = reverse('public_distribution_proof_detail', kwargs={'pk': self.verified_proof_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data['id']), str(self.verified_proof_a1.id))
        self.assertEqual(response.data['status'], 'VERIFIED')

    # =========================================================================
    # B. AUTHENTICATED DONOR ACCESS
    # =========================================================================

    def test_donor_access_campaign_tracking(self):
        """Authenticated donor accesses same public campaign tracking overview."""
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['campaign']['id'], str(self.campaign_a.id))

    def test_donor_access_verified_proof_list(self):
        """Authenticated donor accesses same public verified proof list."""
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)

    def test_donor_access_verified_proof_detail(self):
        """Authenticated donor accesses same public verified proof detail."""
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('public_distribution_proof_detail', kwargs={'pk': self.verified_proof_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data['id']), str(self.verified_proof_a1.id))

    # =========================================================================
    # C. OTHER AUTHENTICATED ROLES (AllowAny Access)
    # =========================================================================

    def test_all_roles_can_access_public_tracking_endpoints(self):
        """Verify NGO, Company, and Admin users can access public tracking APIs without role blocks."""
        tracking_url = reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug})
        list_url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        detail_url = reverse('public_distribution_proof_detail', kwargs={'pk': self.verified_proof_a1.id})

        for user in [self.ngo_user_a, self.ngo_user_b, self.company_user, self.admin_user]:
            self.client.force_authenticate(user=user)
            res_tracking = self.client.get(tracking_url)
            self.assertEqual(res_tracking.status_code, status.HTTP_200_OK, f"Failed for {user.role}")
            res_list = self.client.get(list_url)
            self.assertEqual(res_list.status_code, status.HTTP_200_OK, f"Failed for {user.role}")
            res_detail = self.client.get(detail_url)
            self.assertEqual(res_detail.status_code, status.HTTP_200_OK, f"Failed for {user.role}")

    # =========================================================================
    # D. VERIFIED PROOF LIST FILTERING (Strict Status Enforcement)
    # =========================================================================

    def test_public_proof_list_only_returns_verified_proofs(self):
        """
        Proof list must return ONLY VERIFIED proofs.
        SUBMITTED, UNDER_REVIEW, REVISION_REQUESTED, and REJECTED must be excluded.
        """
        url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = [item['id'] for item in response.data['results']]
        # Verified proof must be present
        self.assertIn(str(self.verified_proof_a1.id), returned_ids)
        # All other statuses must be absent
        self.assertNotIn(str(self.submitted_proof_a1.id), returned_ids)
        self.assertNotIn(str(self.under_review_proof_a1.id), returned_ids)
        self.assertNotIn(str(self.revision_requested_proof_a1.id), returned_ids)
        self.assertNotIn(str(self.rejected_proof_a1.id), returned_ids)

        for item in response.data['results']:
            self.assertEqual(item['status'], 'VERIFIED')

    def test_public_proof_list_milestone_filter(self):
        """Milestone query parameter filters proofs to requested milestone."""
        url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(f"{url}?milestone={self.milestone_a1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        # Milestone with no verified proofs returns empty results
        response_empty = self.client.get(f"{url}?milestone={self.milestone_a2.id}")
        self.assertEqual(response_empty.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_empty.data['results']), 0)

    def test_public_proof_list_slug_route_compatibility(self):
        """Verify the slug-based route works identically for public proof listing."""
        url = reverse('public_campaign_distribution_proof_list_slug', kwargs={'slug': self.campaign_a.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], str(self.verified_proof_a1.id))

    # =========================================================================
    # E. UNVERIFIED PROOF DETAIL ACCESS PROTECTION (404 NOT FOUND)
    # =========================================================================

    def test_unverified_proof_detail_returns_404_all_states(self):
        """
        Unverified proofs must return 404 NOT FOUND to public/donor callers.
        Never 403, and never revealing that the proof exists or its state.
        """
        unverified_proofs = [
            self.submitted_proof_a1,
            self.under_review_proof_a1,
            self.revision_requested_proof_a1,
            self.rejected_proof_a1,
        ]

        for proof in unverified_proofs:
            url = reverse('public_distribution_proof_detail', kwargs={'pk': proof.id})
            # Anonymous call
            res_anon = self.client.get(url)
            self.assertEqual(
                res_anon.status_code,
                status.HTTP_404_NOT_FOUND,
                f"Proof in {proof.status} leaked via 200/403 for anonymous"
            )
            # Authenticated Donor call
            self.client.force_authenticate(user=self.donor_user)
            res_donor = self.client.get(url)
            self.assertEqual(
                res_donor.status_code,
                status.HTTP_404_NOT_FOUND,
                f"Proof in {proof.status} leaked via 200/403 for donor"
            )
            self.client.force_authenticate(user=None)

    # =========================================================================
    # F. VERIFIED PROOF DETAIL (200 OK with Correct Public Serializer)
    # =========================================================================

    def test_verified_proof_detail_success(self):
        """Verified proof returns 200 OK and accurate public fields."""
        url = reverse('public_distribution_proof_detail', kwargs={'pk': self.verified_proof_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data['id']), str(self.verified_proof_a1.id))
        self.assertEqual(response.data['caption'], self.verified_proof_a1.caption)
        self.assertEqual(response.data['location_name'], self.verified_proof_a1.location_name)
        self.assertEqual(response.data['beneficiary_count'], self.verified_proof_a1.beneficiary_count)
        self.assertEqual(response.data['beneficiary_type'], 'GENERAL_RURAL')
        self.assertEqual(response.data['spent_amount'], '185000.00')
        self.assertEqual(response.data['status'], 'VERIFIED')
        self.assertIsNotNone(response.data['reviewed_at'])
        self.assertIsNotNone(response.data['photo_url'])

    # =========================================================================
    # G. PRIVATE FIELD LEAKAGE AUDIT
    # =========================================================================

    def test_private_fields_not_leaked_in_proof_detail(self):
        """Ensure admin_notes, rejection_reason, submitted_by, reviewed_by never appear in proof detail."""
        url = reverse('public_distribution_proof_detail', kwargs={'pk': self.verified_proof_a1.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        forbidden_fields = ['admin_notes', 'rejection_reason', 'submitted_by', 'reviewed_by']
        for field in forbidden_fields:
            self.assertNotIn(field, response.data, f"Private field '{field}' leaked in proof detail!")

    def test_private_fields_not_leaked_in_proof_list(self):
        """Ensure administrative fields never appear in proof list responses."""
        url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        forbidden_fields = ['admin_notes', 'rejection_reason', 'submitted_by', 'reviewed_by']
        for item in response.data['results']:
            for field in forbidden_fields:
                self.assertNotIn(field, item, f"Private field '{field}' leaked in proof list item!")

    def test_private_fields_not_leaked_in_campaign_tracking(self):
        """Ensure administrative and unverified fields never appear in campaign tracking overview."""
        url = reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        forbidden_fields = ['admin_notes', 'rejection_reason', 'submitted_by', 'reviewed_by']
        for proof in response.data['verified_distribution_proofs']:
            for field in forbidden_fields:
                self.assertNotIn(field, proof, f"Private field '{field}' leaked in tracking proofs!")

        for milestone in response.data['milestones']:
            for proof in milestone.get('proofs', []):
                for field in forbidden_fields:
                    self.assertNotIn(field, proof, f"Private field '{field}' leaked in milestone proofs!")

    # =========================================================================
    # H. CROSS-CAMPAIGN IDOR PROTECTION
    # =========================================================================

    def test_cross_campaign_proof_list_isolation(self):
        """Querying Campaign A must return Proof A only, never Proof B from Campaign B."""
        url_a = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id})
        res_a = self.client.get(url_a)
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)

        ids_a = [p['id'] for p in res_a.data['results']]
        self.assertIn(str(self.verified_proof_a1.id), ids_a)
        self.assertNotIn(str(self.verified_proof_b1.id), ids_a)

        url_b = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_b.id})
        res_b = self.client.get(url_b)
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)

        ids_b = [p['id'] for p in res_b.data['results']]
        self.assertIn(str(self.verified_proof_b1.id), ids_b)
        self.assertNotIn(str(self.verified_proof_a1.id), ids_b)

    # =========================================================================
    # I. CROSS-NGO ISOLATION
    # =========================================================================

    def test_cross_ngo_isolation_in_tracking(self):
        """Public tracking for Campaign A must expose only NGO A data, never NGO B data."""
        url_a = reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug})
        response = self.client.get(url_a)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # NGO info belongs to Alpha
        self.assertEqual(response.data['campaign']['ngo_slug'], self.ngo_profile_a.slug)
        self.assertEqual(response.data['campaign']['ngo_name'], self.ngo_profile_a.display_name)

        # Milestones belong to Campaign A
        milestone_ids = [m['id'] for m in response.data['milestones']]
        self.assertIn(str(self.milestone_a1.id), milestone_ids)
        self.assertNotIn(str(self.milestone_b1.id), milestone_ids)

        # Proofs belong to Campaign A
        proof_ids = [p['id'] for p in response.data['verified_distribution_proofs']]
        self.assertIn(str(self.verified_proof_a1.id), proof_ids)
        self.assertNotIn(str(self.verified_proof_b1.id), proof_ids)

    # =========================================================================
    # J. NONEXISTENT & INACTIVE CAMPAIGN PROTECTION
    # =========================================================================

    def test_nonexistent_campaign_slug_returns_404(self):
        """Invalid campaign slug returns 404 Not Found."""
        url = reverse('public_campaign_tracking', kwargs={'slug': 'nonexistent-campaign-slug-404'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_draft_campaign_tracking_returns_404(self):
        """Unpublished/draft campaign tracking overview returns 404 Not Found."""
        url = reverse('public_campaign_tracking', kwargs={'slug': self.draft_campaign.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_draft_campaign_proof_list_returns_404(self):
        """Proof list for unpublished/draft campaign returns 404 Not Found."""
        url = reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.draft_campaign.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_proof_belonging_to_draft_campaign_detail_returns_404(self):
        """A verified proof belonging to a draft campaign must not be publicly visible."""
        draft_verified_proof = DistributionProof.objects.create(
            milestone=self.draft_milestone,
            photo=create_in_memory_image(name='draft_verified.jpg'),
            caption='Proof on draft campaign.',
            distribution_date=self.today,
            spent_amount=Decimal('5000.00'),
            status=DistributionProof.Status.VERIFIED,
            submitted_by=self.ngo_user_a,
            reviewed_by=self.admin_user,
        )
        url = reverse('public_distribution_proof_detail', kwargs={'pk': draft_verified_proof.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # K & L. NONEXISTENT & MALFORMED PROOF UUID
    # =========================================================================

    def test_nonexistent_proof_uuid_returns_404(self):
        """Random nonexistent UUID returns 404 Not Found."""
        random_uuid = uuid.uuid4()
        url = reverse('public_distribution_proof_detail', kwargs={'pk': random_uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_proof_uuid_returns_404(self):
        """Malformed UUID string fails at URL resolution with 404."""
        response = self.client.get('/api/v1/public/campaigns/distribution-proofs/not-a-valid-uuid/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # M. UNVERIFIED PROOF EXISTENCE LEAKAGE PROTECTION
    # =========================================================================

    def test_unverified_proof_existence_leakage_protection(self):
        """Attempting to access an existing submitted proof must return 404, exactly identical to a non-existent UUID."""
        url_existing_unverified = reverse('public_distribution_proof_detail', kwargs={'pk': self.submitted_proof_a1.id})
        url_nonexistent = reverse('public_distribution_proof_detail', kwargs={'pk': uuid.uuid4()})

        res_unverified = self.client.get(url_existing_unverified)
        res_nonexistent = self.client.get(url_nonexistent)

        self.assertEqual(res_unverified.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_nonexistent.status_code, status.HTTP_404_NOT_FOUND)
        # Verify no difference in response status (no 403 or descriptive status leak)
        self.assertNotIn('SUBMITTED', str(res_unverified.data))
        self.assertNotIn('status', str(res_unverified.data))

    # =========================================================================
    # N. CAMPAIGN TRACKING CONTENT & FINANCIAL AGGREGATION
    # =========================================================================

    def test_campaign_tracking_overview_calculations(self):
        """Verify accurate calculation of verified spent amounts and counts."""
        url = reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Milestone 1 has 1 verified proof of ₹185,000.00
        m1_data = next(m for m in response.data['milestones'] if m['id'] == str(self.milestone_a1.id))
        self.assertEqual(m1_data['verified_spent_amount'], '185000.00')
        self.assertEqual(m1_data['verified_proofs_count'], 1)
        self.assertEqual(len(m1_data['proofs']), 1)
        self.assertEqual(m1_data['proofs'][0]['id'], str(self.verified_proof_a1.id))

        # Milestone 2 has 0 verified proofs
        m2_data = next(m for m in response.data['milestones'] if m['id'] == str(self.milestone_a2.id))
        self.assertEqual(m2_data['verified_spent_amount'], '0.00')
        self.assertEqual(m2_data['verified_proofs_count'], 0)
        self.assertEqual(len(m2_data['proofs']), 0)

        # Campaign overall verified spent amount
        self.assertEqual(response.data['total_verified_spent'], '185000.00')

    # =========================================================================
    # O. FINANCIAL INTEGRITY & ZERO SIDE-EFFECTS
    # =========================================================================

    def test_read_tracking_has_no_financial_side_effects(self):
        """Calling tracking endpoints must never modify campaign raised amount or financial tables."""
        initial_raised = self.campaign_a.raised_amount

        # Invoke all 3 tracking endpoints
        self.client.get(reverse('public_campaign_tracking', kwargs={'slug': self.campaign_a.slug}))
        self.client.get(reverse('public_campaign_distribution_proof_list', kwargs={'campaign_id': self.campaign_a.id}))
        self.client.get(reverse('public_distribution_proof_detail', kwargs={'pk': self.verified_proof_a1.id}))

        self.campaign_a.refresh_from_db()
        self.assertEqual(self.campaign_a.raised_amount, initial_raised)
