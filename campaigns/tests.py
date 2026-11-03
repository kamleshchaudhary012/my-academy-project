import datetime
import uuid
import json
import hmac
import hashlib
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from ngo.models import NGOProfile, NGOLegalInfo, NGOAddress
from campaigns.models import (
    Campaign,
    MonetaryDonation,
    PaymentTransaction,
    GatewayWebhookEvent,
    TaxReceiptRecord,
)
from campaigns.tax_receipt_service import (
    TaxReceiptService,
    get_financial_year,
    parse_financial_year,
    amount_to_words_inr,
)

User = get_user_model()


class CampaignComprehensiveAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Users
        self.approved_ngo_user = User.objects.create_user(
            email='approved_ngo@example.com',
            password='Password123!',
            full_name='Approved NGO User',
            role=User.Role.NGO,
        )
        self.draft_ngo_user = User.objects.create_user(
            email='draft_ngo@example.com',
            password='Password123!',
            full_name='Draft NGO User',
            role=User.Role.NGO,
        )
        self.suspended_ngo_user = User.objects.create_user(
            email='suspended_ngo@example.com',
            password='Password123!',
            full_name='Suspended NGO User',
            role=User.Role.NGO,
        )
        self.donor_user = User.objects.create_user(
            email='donor@example.com',
            password='Password123!',
            full_name='Donor User',
            role=User.Role.DONOR,
        )
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            password='Password123!',
            full_name='Admin User',
            role=User.Role.ADMIN,
        )

        # NGO Profiles
        self.approved_ngo = NGOProfile.objects.create(
            user=self.approved_ngo_user,
            legal_name='Approved Foundation',
            display_name='Approved Foundation',
            category=NGOProfile.Category.EDUCATION,
            description='A fully verified and approved non-profit organization.',
            year_established=2015,
            official_email='info@approved.org',
            official_phone='+919876543210',
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        self.draft_ngo = NGOProfile.objects.create(
            user=self.draft_ngo_user,
            legal_name='Draft Non-Profit',
            display_name='Draft Non-Profit',
            category=NGOProfile.Category.HEALTHCARE,
            description='Unverified draft NGO application.',
            year_established=2020,
            official_email='info@draft.org',
            official_phone='+919876543211',
            status=NGOProfile.Status.DRAFT,
            is_active=False,
        )

        self.suspended_ngo = NGOProfile.objects.create(
            user=self.suspended_ngo_user,
            legal_name='Suspended Non-Profit',
            display_name='Suspended Non-Profit',
            category=NGOProfile.Category.DISASTER_RELIEF,
            description='Suspended NGO application.',
            year_established=2018,
            official_email='info@suspended.org',
            official_phone='+919876543212',
            status=NGOProfile.Status.SUSPENDED,
            is_active=False,
        )

        self.today = datetime.date.today()
        self.future_date = self.today + datetime.timedelta(days=30)

    # 1. NGO authentication required
    def test_unauthenticated_user_cannot_create_campaign(self):
        self.client.force_authenticate(user=None)
        res = self.client.post('/api/v1/ngo/campaigns/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    # 2. Donor cannot create campaign
    def test_donor_cannot_create_campaign(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {
            'title': 'Donor Campaign Attempt',
            'short_description': 'Donor attempt',
            'description': 'Donor user trying to create a campaign.',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 3. Admin permission remains protected
    def test_admin_cannot_create_ngo_campaign(self):
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            'title': 'Admin Campaign Attempt',
            'short_description': 'Admin attempt',
            'description': 'Admin user trying to create an NGO campaign.',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 4. Approved NGO can create campaign
    def test_approved_ngo_can_create_campaign(self):
        self.client.force_authenticate(user=self.approved_ngo_user)
        payload = {
            'title': 'School Supplies Appeal',
            'category': 'EDUCATION',
            'campaign_type': 'MONETARY',
            'short_description': 'Help 500 children get school supplies.',
            'description': 'Comprehensive appeal to provide textbooks, bags, and stationery.',
            'target_amount': '50000.00',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
            'status': 'ACTIVE',
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Campaign.objects.count(), 1)
        c = Campaign.objects.first()
        self.assertEqual(c.ngo, self.approved_ngo)
        self.assertEqual(c.title, 'School Supplies Appeal')

    # 5. Unapproved NGO cannot create campaign
    def test_unapproved_ngo_cannot_create_campaign(self):
        self.client.force_authenticate(user=self.draft_ngo_user)
        payload = {
            'title': 'Draft NGO Campaign',
            'category': 'HEALTHCARE',
            'short_description': 'Draft campaign attempt.',
            'description': 'Attempting to create a campaign from a draft unverified NGO.',
            'target_amount': '10000.00',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 6. Suspended NGO cannot create campaign
    def test_suspended_ngo_cannot_create_campaign(self):
        self.client.force_authenticate(user=self.suspended_ngo_user)
        payload = {
            'title': 'Suspended NGO Campaign',
            'category': 'DISASTER_RELIEF',
            'short_description': 'Suspended campaign attempt.',
            'description': 'Attempting to create a campaign from a suspended NGO.',
            'target_amount': '10000.00',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 7. NGO can list own campaigns
    def test_ngo_can_list_own_campaigns(self):
        Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Campaign 1',
            short_description='Summary 1',
            description='Detailed description for Campaign 1 for testing list.',
            start_date=self.today,
            end_date=self.future_date,
        )
        self.client.force_authenticate(user=self.approved_ngo_user)
        res = self.client.get('/api/v1/ngo/campaigns/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get('results') if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)

    # 8. NGO cannot access or modify another NGO's campaign
    def test_ngo_cannot_access_or_modify_another_ngo_campaign(self):
        c = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Approved NGO Campaign',
            short_description='Summary',
            description='Detailed campaign description for approved NGO.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.ACTIVE,
        )

        user2 = User.objects.create_user(
            email='ngo2@example.com',
            password='Password123!',
            role=User.Role.NGO,
        )
        NGOProfile.objects.create(
            user=user2,
            legal_name='NGO Two',
            display_name='NGO Two',
            year_established=2018,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        self.client.force_authenticate(user=user2)
        res_get = self.client.get(f'/api/v1/ngo/campaigns/{c.id}/')
        self.assertEqual(res_get.status_code, status.HTTP_404_NOT_FOUND)

        res_patch = self.client.patch(f'/api/v1/ngo/campaigns/{c.id}/', {'title': 'Hacked Title'}, format='json')
        self.assertEqual(res_patch.status_code, status.HTTP_404_NOT_FOUND)

    # 9. Invalid dates validation (end_date < start_date)
    def test_invalid_dates_validation(self):
        self.client.force_authenticate(user=self.approved_ngo_user)
        payload = {
            'title': 'Invalid Dates Campaign',
            'short_description': 'Invalid dates summary',
            'description': 'Detailed campaign description with invalid dates.',
            'start_date': str(self.today),
            'end_date': str(self.today - datetime.timedelta(days=5)),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('end_date', res.data)

    # 10. Invalid target amount validation
    def test_negative_target_amount_validation(self):
        self.client.force_authenticate(user=self.approved_ngo_user)
        payload = {
            'title': 'Negative Goal Campaign',
            'short_description': 'Negative goal summary',
            'description': 'Detailed campaign description with negative goal.',
            'target_amount': '-500.00',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 11. Client cannot set raised_amount
    def test_client_cannot_control_raised_amount(self):
        self.client.force_authenticate(user=self.approved_ngo_user)
        payload = {
            'title': 'Fake Raised Amount Campaign',
            'short_description': 'Fake raised summary',
            'description': 'Detailed campaign description trying to set raised amount.',
            'target_amount': '100000.00',
            'raised_amount': '999999.00',
            'start_date': str(self.today),
            'end_date': str(self.future_date),
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        c = Campaign.objects.get(id=res.data['id'])
        self.assertEqual(c.raised_amount, 0.00)

    # 12. Public API exposes only active campaigns of approved NGOs
    def test_public_campaign_visibility_rules(self):
        c_active = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Public Active Campaign',
            short_description='Public summary',
            description='Public campaign description for discovery test.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        c_draft = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Draft Private Campaign',
            short_description='Draft summary',
            description='Draft campaign description for discovery test.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )

        self.client.force_authenticate(user=None)
        res = self.client.get('/api/v1/public/campaigns/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get('results') if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['slug'], c_active.slug)

        # Detail view
        res_detail = self.client.get(f'/api/v1/public/campaigns/{c_active.slug}/')
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)

        # Draft returns 404
        res_draft = self.client.get(f'/api/v1/public/campaigns/{c_draft.slug}/')
        self.assertEqual(res_draft.status_code, status.HTTP_404_NOT_FOUND)

    # 13. Suspended NGO campaigns disappear from public API
    def test_suspended_ngo_campaign_disappears_from_public_api(self):
        c_suspended_ngo = Campaign.objects.create(
            ngo=self.suspended_ngo,
            created_by=self.suspended_ngo_user,
            title='Suspended NGO Active Campaign',
            short_description='Suspended summary',
            description='Active campaign under a suspended NGO.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.client.force_authenticate(user=None)
        res = self.client.get(f'/api/v1/public/campaigns/{c_suspended_ngo.slug}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 14. Active campaign cancellation / delete behavior
    def test_active_campaign_cancellation_semantics(self):
        c = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Active Campaign To Cancel',
            short_description='Active summary',
            description='Detailed description for active campaign cancellation test.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.client.force_authenticate(user=self.approved_ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{c.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

        c.refresh_from_db()
        self.assertEqual(c.status, Campaign.Status.CANCELLED)
        self.assertFalse(c.is_active)

    # 15. Draft campaign permanent deletion semantics
    def test_draft_campaign_deletion_semantics(self):
        c_draft = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Draft Campaign To Delete',
            short_description='Draft summary',
            description='Detailed description for draft campaign deletion test.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )

        self.client.force_authenticate(user=self.approved_ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{c_draft.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Campaign.objects.filter(id=c_draft.id).exists())

    # 16. Completed campaign deletion rejection
    def test_completed_campaign_deletion_rejected(self):
        c_completed = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Completed Campaign To Delete',
            short_description='Completed summary',
            description='Detailed description for completed campaign deletion test.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.COMPLETED,
            is_active=True,
        )

        self.client.force_authenticate(user=self.approved_ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{c_completed.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 17. Cancelled campaign deletion rejection
    def test_cancelled_campaign_deletion_rejected(self):
        c_cancelled = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.approved_ngo_user,
            title='Cancelled Campaign To Delete',
            short_description='Cancelled summary',
            description='Detailed description for cancelled campaign deletion test.',
            start_date=self.today,
            end_date=self.future_date,
            status=Campaign.Status.CANCELLED,
            is_active=False,
        )

        self.client.force_authenticate(user=self.approved_ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{c_cancelled.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

class Phase411CampaignModerationAPITests(TestCase):
    def setUp(self):
        from campaigns.models import Campaign, CampaignReviewHistory
        self.client = APIClient()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            email='admin_mod@example.com',
            password='AdminPassword123!',
            full_name='Platform Admin',
        )

        # Approved NGO
        self.ngo_user = User.objects.create_user(
            email='ngo_mod@example.com',
            password='Password123!',
            full_name='NGO Mod User',
            role=User.Role.NGO,
        )
        self.ngo = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Youth Relief Foundation',
            display_name='Youth Relief Foundation',
            category=NGOProfile.Category.EDUCATION,
            year_established=2018,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # Other NGO
        self.other_ngo_user = User.objects.create_user(
            email='other_ngo_mod@example.com',
            password='Password123!',
            full_name='Other NGO Mod User',
            role=User.Role.NGO,
        )
        self.other_ngo = NGOProfile.objects.create(
            user=self.other_ngo_user,
            legal_name='Other Relief Org',
            display_name='Other Relief Org',
            category=NGOProfile.Category.HEALTHCARE,
            year_established=2020,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

    # 1. Approved NGO creates campaign -> always DRAFT (client cannot force ACTIVE)
    def test_ngo_creation_forces_draft(self):
        self.client.force_authenticate(user=self.ngo_user)
        payload = {
            'title': 'School Supplies Appeal 2026',
            'category': 'EDUCATION',
            'campaign_type': 'MONETARY',
            'short_description': 'Providing books and bags for needy children.',
            'description': 'Comprehensive educational drive description for rural families.',
            'target_amount': '50000.00',
            'start_date': str(self.today),
            'end_date': str(self.future),
            'status': 'ACTIVE',
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['status'], 'DRAFT')

    # 2. DRAFT campaign is NOT public
    def test_draft_campaign_not_public(self):
        from campaigns.models import Campaign
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Draft Drive',
            short_description='Draft short summary',
            description='Detailed draft description text.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000.00,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get('results', res.data) if isinstance(res.data, dict) else res.data
        slugs = [c['slug'] for c in results]
        self.assertNotIn(campaign.slug, slugs)

    # 3. NGO submits campaign for review -> PENDING_REVIEW
    def test_ngo_submit_review_success(self):
        from campaigns.models import Campaign
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Classroom Supplies Drive',
            short_description='Drive description',
            description='Detailed description text for classroom supplies appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000.00,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
        )
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.post(f'/api/v1/ngo/campaigns/{campaign.id}/submit-review/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'PENDING_REVIEW')

    # 4. Non-admin cannot access admin moderation queue
    def test_non_admin_cannot_access_moderation(self):
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.get('/api/v1/admin/campaigns/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 5. Admin approves campaign -> ACTIVE and creates audit history
    def test_admin_approve_campaign(self):
        from campaigns.models import Campaign, CampaignReviewHistory
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Approved Appeal',
            short_description='Drive description',
            description='Detailed description text for approved appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000.00,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.PENDING_REVIEW,
        )

        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(f'/api/v1/admin/campaigns/{campaign.id}/approve/', {'note': 'Verified authentic appeal.'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, 'ACTIVE')

        history = CampaignReviewHistory.objects.filter(campaign=campaign).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.new_status, 'ACTIVE')



class Phase412CampaignCancelledAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # Users
        self.ngo_user = User.objects.create_user(
            email='ngo_cancel_owner@example.com',
            password='Password123!',
            full_name='NGO Cancel Owner',
            role=User.Role.NGO,
        )
        self.other_ngo_user = User.objects.create_user(
            email='ngo_cancel_other@example.com',
            password='Password123!',
            full_name='NGO Cancel Other',
            role=User.Role.NGO,
        )
        self.donor = User.objects.create_user(
            email='donor_cancel_test@example.com',
            password='Password123!',
            full_name='Donor Cancel Test',
            role=User.Role.DONOR,
        )

        # NGO Profile
        self.ngo = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Cancel Test Trust',
            display_name='Cancel Test Trust',
            category=NGOProfile.Category.EDUCATION,
            year_established=2010,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        self.other_ngo = NGOProfile.objects.create(
            user=self.other_ngo_user,
            legal_name='Other Cancel Trust',
            display_name='Other Cancel Trust',
            category=NGOProfile.Category.EDUCATION,
            year_established=2012,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

    # 1. ACTIVE campaign cancellation sets status=CANCELLED, is_active=False, row preserved
    def test_active_campaign_cancellation(self):
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Active Drive to Cancel',
            short_description='Drive desc',
            description='Detailed text for active drive to cancel appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{campaign.id}/')
        self.assertIn(res.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.CANCELLED)
        self.assertFalse(campaign.is_active)
        self.assertTrue(Campaign.objects.filter(id=campaign.id).exists())

    # 2. PENDING_REVIEW campaign cancellation sets status=CANCELLED, is_active=False
    def test_pending_review_campaign_cancellation(self):
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Pending Review Drive to Cancel',
            short_description='Drive desc',
            description='Detailed text for pending review drive appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.PENDING_REVIEW,
            is_active=True,
        )
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{campaign.id}/')
        self.assertIn(res.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.Status.CANCELLED)
        self.assertFalse(campaign.is_active)

    # 3. COMPLETED campaign cancellation rejected (400)
    def test_completed_campaign_cancellation_rejected(self):
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Completed Drive',
            short_description='Drive desc',
            description='Detailed text for completed drive appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.COMPLETED,
            is_active=True,
        )
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{campaign.id}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 4. Cancelled campaign excluded from public list & public slug detail returns 404
    def test_cancelled_campaign_public_visibility(self):
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Cancelled Drive Hidden Public',
            short_description='Drive desc',
            description='Detailed text for cancelled drive appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.CANCELLED,
            is_active=False,
        )
        res_list = self.client.get('/api/v1/public/campaigns/')
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        results = res_list.data.get('results', res_list.data) if isinstance(res_list.data, dict) else res_list.data
        slugs = [c['slug'] for c in results]
        self.assertNotIn(campaign.slug, slugs)

        res_detail = self.client.get(f'/api/v1/public/campaigns/{campaign.slug}/')
        self.assertEqual(res_detail.status_code, status.HTTP_404_NOT_FOUND)

    # 5. NGO owner can query own CANCELLED campaigns
    def test_ngo_list_cancelled_filter(self):
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Cancelled History Campaign',
            short_description='Drive desc',
            description='Detailed text for cancelled history drive appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.CANCELLED,
            is_active=False,
        )
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.get('/api/v1/ngo/campaigns/?status=CANCELLED')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get('results', res.data) if isinstance(res.data, dict) else res.data
        ids = [c['id'] for c in results]
        self.assertIn(str(campaign.id), ids)

    # 6. NGO cannot cancel another NGO's campaign (404)
    def test_ngo_cannot_cancel_other_ngo_campaign(self):
        campaign = Campaign.objects.create(
            ngo=self.other_ngo,
            created_by=self.other_ngo_user,
            title='Other NGO Active Drive',
            short_description='Drive desc',
            description='Detailed text for other ngo active drive appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.client.force_authenticate(user=self.ngo_user)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{campaign.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 7. Donor cannot cancel campaign (403)
    def test_donor_cannot_cancel_campaign(self):
        campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='NGO Active Drive For Donor Test',
            short_description='Drive desc',
            description='Detailed text for active drive appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.client.force_authenticate(user=self.donor)
        res = self.client.delete(f'/api/v1/ngo/campaigns/{campaign.id}/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class Phase414PublicCampaignDiscoveryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # Users
        self.ngo_user_1 = User.objects.create_user(
            email='ngo1_p414@example.com',
            password='Password123!',
            full_name='NGO Owner One',
            role=User.Role.NGO,
        )
        self.ngo_user_2 = User.objects.create_user(
            email='ngo2_p414@example.com',
            password='Password123!',
            full_name='NGO Owner Two',
            role=User.Role.NGO,
        )
        self.unapproved_ngo_user = User.objects.create_user(
            email='unapproved_p414@example.com',
            password='Password123!',
            full_name='Unapproved NGO Owner',
            role=User.Role.NGO,
        )

        # NGO Profiles
        self.approved_ngo_1 = NGOProfile.objects.create(
            user=self.ngo_user_1,
            legal_name='Seva Foundation Trust',
            display_name='Seva Foundation',
            category=NGOProfile.Category.EDUCATION,
            description='Dedicated to children education and literacy.',
            year_established=2010,
            official_email='info@sevafoundation.org',
            official_phone='+919876543210',
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        self.approved_ngo_2 = NGOProfile.objects.create(
            user=self.ngo_user_2,
            legal_name='Aarogya Health Mission',
            display_name='Aarogya Mission',
            category=NGOProfile.Category.HEALTHCARE,
            description='Community health clinics across rural sectors.',
            year_established=2015,
            official_email='contact@aarogya.org',
            official_phone='+919876543211',
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        self.unapproved_ngo = NGOProfile.objects.create(
            user=self.unapproved_ngo_user,
            legal_name='Draft Non Profit Trust',
            display_name='Draft NGO',
            category=NGOProfile.Category.DISASTER_RELIEF,
            description='Pending verification non-profit.',
            year_established=2021,
            official_email='info@draftngo.org',
            official_phone='+919876543212',
            status=NGOProfile.Status.SUBMITTED,
            is_active=False,
        )

        # Active Campaign for NGO 1
        self.active_monetary_campaign = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Primary School Library Fundraiser',
            short_description='Raising funds to build rural classrooms and books.',
            description='Comprehensive appeal for setting up school libraries and learning desks.',
            category=NGOProfile.Category.EDUCATION,
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=150000.00,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # Active Campaign for NGO 2
        self.active_healthcare_campaign = Campaign.objects.create(
            ngo=self.approved_ngo_2,
            created_by=self.ngo_user_2,
            title='Essential Health Kits Drive 2026',
            short_description='Distributing first aid and sanitation kits to villages.',
            description='Detailed request for hygiene supplies and medical consumables.',
            category=NGOProfile.Category.HEALTHCARE,
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=100000.00,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    # 1. Public list is paginated
    def test_public_campaign_list_is_paginated(self):
        res = self.client.get('/api/v1/public/campaigns/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, dict)

    # 2. Response contains count
    def test_public_campaign_list_contains_count(self):
        res = self.client.get('/api/v1/public/campaigns/')
        self.assertIn('count', res.data)
        self.assertGreaterEqual(res.data['count'], 2)

    # 3. Response contains results
    def test_public_campaign_list_contains_results(self):
        res = self.client.get('/api/v1/public/campaigns/')
        self.assertIn('results', res.data)
        self.assertIsInstance(res.data['results'], list)
        self.assertEqual(len(res.data['results']), res.data['count'])

    # 4. ACTIVE approved NGO campaign is returned
    def test_active_approved_ngo_campaign_returned(self):
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertIn(self.active_monetary_campaign.slug, slugs)
        self.assertIn(self.active_healthcare_campaign.slug, slugs)

    # 5. DRAFT campaign is excluded
    def test_draft_campaign_is_excluded(self):
        draft_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Draft Library Expansion',
            short_description='Draft short desc',
            description='Draft long description text here minimum 30 chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(draft_c.slug, slugs)

        detail_res = self.client.get(f'/api/v1/public/campaigns/{draft_c.slug}/')
        self.assertEqual(detail_res.status_code, status.HTTP_404_NOT_FOUND)

    # 6. PENDING_REVIEW campaign is excluded
    def test_pending_review_campaign_is_excluded(self):
        pending_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Pending Review Solar Lighting',
            short_description='Solar lighting for village schools.',
            description='Detailed solar lighting drive description for rural schools.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.PENDING_REVIEW,
            is_active=True,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(pending_c.slug, slugs)

    # 7. CHANGES_REQUESTED campaign is excluded
    def test_changes_requested_campaign_is_excluded(self):
        changes_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Changes Requested Clean Water',
            short_description='Water filters installation.',
            description='Detailed water filters installation project description.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.CHANGES_REQUESTED,
            is_active=True,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(changes_c.slug, slugs)

    # 8. REJECTED campaign is excluded
    def test_rejected_campaign_is_excluded(self):
        rejected_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Rejected Appeal Project',
            short_description='Rejected project summary.',
            description='Detailed rejected appeal project description.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.REJECTED,
            is_active=True,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(rejected_c.slug, slugs)

    # 9. CANCELLED campaign is excluded
    def test_cancelled_campaign_is_excluded(self):
        cancelled_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Cancelled Blanket Drive',
            short_description='Cancelled drive summary.',
            description='Detailed cancelled blanket drive project description.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.CANCELLED,
            is_active=False,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(cancelled_c.slug, slugs)

    # 10. SUSPENDED campaign is excluded
    def test_suspended_campaign_is_excluded(self):
        suspended_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Suspended Drive by Admin',
            short_description='Suspended drive summary.',
            description='Detailed suspended drive appeal project description.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.SUSPENDED,
            is_active=False,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(suspended_c.slug, slugs)

    # 11. Campaign of unapproved NGO is excluded
    def test_campaign_of_unapproved_ngo_is_excluded(self):
        unapp_c = Campaign.objects.create(
            ngo=self.unapproved_ngo,
            created_by=self.unapproved_ngo_user,
            title='Unapproved NGO Active Flag Drive',
            short_description='Drive by submitted NGO.',
            description='Detailed description of drive belonging to submitted unapproved NGO.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(unapp_c.slug, slugs)

    # 12. Campaign of inactive NGO is excluded
    def test_campaign_of_inactive_ngo_is_excluded(self):
        self.approved_ngo_1.is_active = False
        self.approved_ngo_1.save()

        res = self.client.get('/api/v1/public/campaigns/')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(self.active_monetary_campaign.slug, slugs)
        self.assertIn(self.active_healthcare_campaign.slug, slugs)

        # Restore
        self.approved_ngo_1.is_active = True
        self.approved_ngo_1.save()

    # 13. ngo_slug filter works
    def test_ngo_slug_filter_returns_only_matching_ngo_campaigns(self):
        res = self.client.get(f'/api/v1/public/campaigns/?ngo_slug={self.approved_ngo_1.slug}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slugs = [c['slug'] for c in res.data['results']]
        self.assertIn(self.active_monetary_campaign.slug, slugs)
        self.assertNotIn(self.active_healthcare_campaign.slug, slugs)

    # 14. ngo_slug does not expose another NGO's campaigns or unapproved campaigns
    def test_ngo_slug_does_not_expose_unapproved_campaigns(self):
        draft_c = Campaign.objects.create(
            ngo=self.approved_ngo_1,
            created_by=self.ngo_user_1,
            title='Draft Inside Same NGO',
            short_description='Draft inside same NGO.',
            description='Detailed text for draft campaign inside same NGO.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        res = self.client.get(f'/api/v1/public/campaigns/?ngo_slug={self.approved_ngo_1.slug}')
        slugs = [c['slug'] for c in res.data['results']]
        self.assertNotIn(draft_c.slug, slugs)

    # 15. Search works
    def test_public_campaign_search(self):
        res = self.client.get('/api/v1/public/campaigns/?search=Library')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slugs = [c['slug'] for c in res.data['results']]
        self.assertIn(self.active_monetary_campaign.slug, slugs)
        self.assertNotIn(self.active_healthcare_campaign.slug, slugs)

    # 16. Category filter works
    def test_public_campaign_category_filter(self):
        res = self.client.get(f'/api/v1/public/campaigns/?category={NGOProfile.Category.HEALTHCARE}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slugs = [c['slug'] for c in res.data['results']]
        self.assertIn(self.active_healthcare_campaign.slug, slugs)
        self.assertNotIn(self.active_monetary_campaign.slug, slugs)

    # 17. Campaign type filtering works
    def test_public_campaign_type_filter_monetary(self):
        res = self.client.get('/api/v1/public/campaigns/?campaign_type=MONETARY')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slugs = [c['slug'] for c in res.data['results']]
        self.assertIn(self.active_monetary_campaign.slug, slugs)
        self.assertIn(self.active_healthcare_campaign.slug, slugs)

    # 18. Public campaign includes ngo_logo and cover_image fields
    def test_public_campaign_includes_visual_identity_fields(self):
        res = self.client.get(f'/api/v1/public/campaigns/{self.active_monetary_campaign.slug}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('cover_image', res.data)
        self.assertIn('ngo_name', res.data)
        self.assertIn('ngo_slug', res.data)
        self.assertIn('ngo_logo', res.data)
        self.assertIn('ngo_city', res.data)
        self.assertIn('ngo_state', res.data)

    # 18b. Regression test for Finding #2: Public campaign includes ngo identifier for donation flow
    def test_public_campaign_includes_ngo_identifier(self):
        res = self.client.get(f'/api/v1/public/campaigns/{self.active_monetary_campaign.slug}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('ngo', res.data)
        self.assertIn('ngo_id', res.data)
        self.assertEqual(str(res.data['ngo']), str(self.active_monetary_campaign.ngo_id))
        self.assertEqual(str(res.data['ngo_id']), str(self.active_monetary_campaign.ngo_id))

    # 19. Public campaign strictly excludes private compliance and admin data
    def test_public_campaign_excludes_private_and_admin_data(self):
        res = self.client.get(f'/api/v1/public/campaigns/{self.active_monetary_campaign.slug}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertNotIn('admin_review_note', res.data)
        self.assertNotIn('rejection_reason', res.data)
        self.assertNotIn('reviewed_by', res.data)
        self.assertNotIn('bank_account', res.data)
        self.assertNotIn('pan_number', res.data)
        self.assertNotIn('account_number', res.data)


class Phase416CampaignTypeContributionEnforcementTests(TestCase):
    """
    Automated test suite for Phase 4.1.6:
    Campaign Type Contribution Flow Matrix, Immutability & Backend Enforcement.
    """

    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Approved NGO Owner & Profile
        self.ngo_user = User.objects.create_user(
            email='ngo_p416@example.com',
            password='Password123!',
            role='NGO',
            full_name='P416 NGO Admin',
            is_active=True,
        )
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Phase 416 Foundation',
            display_name='Phase 416 Foundation',
            slug='phase-416-foundation',
            category=NGOProfile.Category.EDUCATION,
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )

        # 2. Registered Donor
        self.donor_user = User.objects.create_user(
            email='donor_p416@example.com',
            password='Password123!',
            role='DONOR',
            full_name='P416 Generous Donor',
            is_active=True,
        )

        # 3. Active MONETARY Campaign
        self.monetary_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Monetary Classroom Fundraiser',
            slug='monetary-classroom-fundraiser',
            short_description='Monetary classroom equipment appeal.',
            description='Detailed text for classroom equipment appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    # 1. Active campaign type cannot be altered without Admin review
    def test_active_campaign_type_cannot_be_mutated(self):
        self.client.force_authenticate(user=self.ngo_user)
        payload = {
            'campaign_type': Campaign.CampaignType.MATERIAL,
        }
        res = self.client.patch(f'/api/v1/ngo/campaigns/{self.monetary_campaign.id}/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('campaign_type', res.data)

    # 2. Draft campaign type CAN be mutated before submission
    def test_draft_campaign_type_can_be_mutated(self):
        draft_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Draft Mutating Campaign',
            short_description='Draft mutating description.',
            description='Detailed text for draft mutating campaign.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        self.client.force_authenticate(user=self.ngo_user)
        payload = {
            'campaign_type': Campaign.CampaignType.MATERIAL,
        }
        res = self.client.patch(f'/api/v1/ngo/campaigns/{draft_c.id}/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        draft_c.refresh_from_db()
        self.assertEqual(draft_c.campaign_type, Campaign.CampaignType.MATERIAL)



class Phase417MonetaryContributionSecurityTests(TestCase):
    """
    Automated test suite for Phase 4.1.7:
    Monetary Contribution Minimum Amount (₹10) & Security Hardening.
    """

    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Approved NGO Owner & Profile
        self.ngo_user = User.objects.create_user(
            email='ngo_p417@example.com',
            password='Password123!',
            role='NGO',
            full_name='P417 NGO Admin',
            is_active=True,
        )
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Phase 417 Education Trust',
            display_name='Phase 417 Education Trust',
            slug='phase-417-education-trust',
            category=NGOProfile.Category.EDUCATION,
            year_established=2015,
            status='APPROVED',
            is_active=True,
        )

        # 2. Registered Donors & Non-Donor Users
        self.donor_user = User.objects.create_user(
            email='donor_p417@example.com',
            password='Password123!',
            role='DONOR',
            full_name='P417 Verified Donor',
            is_active=True,
        )
        self.non_donor_user = User.objects.create_user(
            email='nondonor_p417@example.com',
            password='Password123!',
            role='NGO',
            full_name='P417 Another NGO',
            is_active=True,
        )

        # 3. Active MONETARY Campaign
        self.monetary_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Classroom Renovation Fund',
            slug='classroom-renovation-fund',
            short_description='Monetary classroom fund appeal.',
            description='Detailed text for classroom renovation fund appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=10000,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 4. Active HYBRID Campaign
        self.hybrid_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Flood Disaster Emergency Relief',
            slug='flood-disaster-emergency-relief',
            short_description='Emergency relief appeal.',
            description='Detailed text for emergency relief appeal.',
            campaign_type=Campaign.CampaignType.HYBRID,
            target_amount=50000,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 5. Active MATERIAL Campaign
        self.material_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Winter Blankets Drive',
            slug='winter-blankets-drive',
            short_description='Winter blankets appeal.',
            description='Detailed text for winter blankets appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    # 1. ₹10 accepted
    def test_amount_ten_accepted(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '10', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['amount'], '10.00')
        self.assertEqual(res.data['formatted_amount'], '₹10.00')

    # 2. ₹9 rejected
    def test_amount_nine_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '9', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', res.data)

    # 3. ₹1 rejected
    def test_amount_one_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '1', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', res.data)

    # 4. ₹0 rejected
    def test_amount_zero_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '0', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 5. Negative amount rejected
    def test_negative_amount_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '-500', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 6. Empty amount rejected
    def test_empty_amount_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 7. Malformed amount strings rejected
    def test_malformed_amount_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        for bad_val in ['abc', '10.5.5', '1e5', 'NaN', 'null']:
            payload = {'amount': bad_val, 'campaign': str(self.monetary_campaign.id)}
            res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 8. Valid larger amount accepted
    def test_valid_larger_amount_accepted(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '25000.50', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['amount'], '25000.50')

    # 9. MATERIAL campaign cannot accept monetary contribution
    def test_material_campaign_rejects_monetary_contribution(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(self.material_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('Monetary contributions are not available for material-only campaigns.' in str(res.data))

    # 10. MONETARY campaign allows monetary contribution
    def test_monetary_campaign_allows_monetary_contribution(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['campaign_type'], 'MONETARY')

    # 11. HYBRID campaign allows monetary contribution
    def test_hybrid_campaign_allows_monetary_contribution(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '500', 'campaign': str(self.hybrid_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['campaign_type'], 'HYBRID')

    # 12. DRAFT campaign rejected
    def test_draft_campaign_rejected(self):
        draft_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Draft Appeal',
            short_description='Draft short desc',
            description='Draft long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(draft_c.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 13. PENDING_REVIEW campaign rejected
    def test_pending_review_campaign_rejected(self):
        pr_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Pending Review Appeal',
            short_description='PR short desc',
            description='PR long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.PENDING_REVIEW,
            is_active=True,
        )
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(pr_c.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 14. CANCELLED campaign rejected
    def test_cancelled_campaign_rejected(self):
        can_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Cancelled Appeal',
            short_description='Cancelled short desc',
            description='Cancelled long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.CANCELLED,
            is_active=False,
        )
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(can_c.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 15. SUSPENDED campaign rejected
    def test_suspended_campaign_rejected(self):
        sus_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Suspended Appeal',
            short_description='Suspended short desc',
            description='Suspended long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.SUSPENDED,
            is_active=False,
        )
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(sus_c.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 16. Inactive NGO campaign rejected
    def test_inactive_ngo_campaign_rejected(self):
        self.ngo_profile.is_active = False
        self.ngo_profile.save()

        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Restore
        self.ngo_profile.is_active = True
        self.ngo_profile.save()

    # 17. Unapproved NGO campaign rejected
    def test_unapproved_ngo_campaign_rejected(self):
        self.ngo_profile.status = 'SUBMITTED'
        self.ngo_profile.save()

        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '100', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Restore
        self.ngo_profile.status = 'APPROVED'
        self.ngo_profile.save()

    # 18. Non-donor role cannot access donor monetary validation
    def test_non_donor_access_rejected(self):
        self.client.force_authenticate(user=self.non_donor_user)
        payload = {'amount': '100', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 19. Client cannot force payment status to SUCCESS or PAID
    def test_client_cannot_force_payment_status(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {
            'amount': '100',
            'campaign': str(self.monetary_campaign.id),
            'status': 'PAID',
            'payment_status': 'SUCCESS',
            'transaction_id': 'TXN_FAKE_123',
        }
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'PREVIEW_VALIDATED')
        self.assertNotIn('transaction_id', res.data)

    # 20. URL amount tampering cannot bypass ₹10 validation
    def test_url_amount_tampering_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '1', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 21. PAN is masked in API responses and never logged
    def test_pan_masking_in_api_response(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {
            'amount': '500',
            'campaign': str(self.monetary_campaign.id),
            'pan_number': 'ABCDE1234F',
        }
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['pan_masked'], '******234F')
        self.assertNotIn('ABCDE', str(res.data.get('pan_masked')))

    # 22. Repeated requests (idempotency) return clean consistent responses
    def test_replayed_validation_request_is_idempotent(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {
            'amount': '250',
            'campaign': str(self.monetary_campaign.id),
            'idempotency_key': 'IDEM-TEST-12345',
        }
        res1 = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        res2 = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data['amount'], res2.data['amount'])

    # 23. Decimal precision validation works accurately
    def test_decimal_precision_handling(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '10.50', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['amount'], '10.50')

    # 24. Intent creation returns preview status without live payment processing
    def test_intent_creation_returns_preview_status(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '1000', 'campaign': str(self.monetary_campaign.id)}
        res = self.client.post('/api/v1/donor/monetary-donations/intent/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['intent_status'], 'PREVIEW_INITIALIZED')


class Phase42RealMonetaryPaymentGatewayTests(TestCase):
    """
    Automated test suite for Phase 4.2:
    Real Monetary Payment Gateway Integration (Razorpay).
    """

    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Approved NGO & Profile
        self.ngo_user = User.objects.create_user(
            email='ngo_p42@example.com',
            password='Password123!',
            role='NGO',
            full_name='P42 NGO Director',
            is_active=True,
        )
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Phase 42 Foundation',
            display_name='Phase 42 Foundation',
            slug='phase-42-foundation',
            category=NGOProfile.Category.EDUCATION,
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )

        # 2. Donors A & B
        self.donor_a = User.objects.create_user(
            email='donor_a_p42@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Donor Alpha',
            is_active=True,
        )
        self.donor_b = User.objects.create_user(
            email='donor_b_p42@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Donor Beta',
            is_active=True,
        )

        # 3. Active Campaigns (MONETARY, HYBRID, MATERIAL)
        self.monetary_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Primary School Lab Equipment',
            slug='primary-school-lab-equipment',
            short_description='Lab equipment appeal.',
            description='Detailed text for primary school lab equipment appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=100000,
            raised_amount=0,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.hybrid_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Disaster Shelter Relief Fund',
            slug='disaster-shelter-relief-fund',
            short_description='Disaster shelter appeal.',
            description='Detailed text for disaster shelter relief appeal.',
            campaign_type=Campaign.CampaignType.HYBRID,
            target_amount=200000,
            raised_amount=500,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.material_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Textbooks for Village School',
            slug='textbooks-for-village-school',
            short_description='Textbooks appeal.',
            description='Detailed text for textbooks appeal.',
            campaign_type=Campaign.CampaignType.MATERIAL,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    def _generate_valid_signature(self, order_id, payment_id):
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', 'placeholder_secret_key_12345')
        msg = f"{order_id}|{payment_id}".encode('utf-8')
        return hmac.new(key_secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()

    def _generate_webhook_signature(self, body_bytes):
        webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', 'placeholder_webhook_secret_12345')
        return hmac.new(webhook_secret.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()

    # 1. ₹10 payment order accepted
    def test_payment_order_creation_ten_rupees_accepted(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '10'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['amount'], '10.00')
        self.assertEqual(res.data['amount_paise'], 1000)
        self.assertTrue(res.data['gateway_order_id'].startswith('order_'))
        self.assertTrue(MonetaryDonation.objects.filter(id=res.data['donation_id'], status='PENDING').exists())

    # 2. ₹9 rejected
    def test_payment_order_creation_nine_rupees_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '9'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', res.data)

    # 3. ₹0 rejected
    def test_payment_order_creation_zero_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '0'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 4. Negative amount rejected
    def test_payment_order_creation_negative_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '-50'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 5. Malformed amount rejected
    def test_payment_order_creation_malformed_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        for bad_val in ['abc', '10.5.5', '1e3', 'NaN']:
            payload = {'campaign': str(self.monetary_campaign.id), 'amount': bad_val}
            res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 6. MATERIAL campaign rejected
    def test_payment_order_creation_material_campaign_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.material_campaign.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue('Monetary contributions are not available for material-only campaigns.' in str(res.data))

    # 7. MONETARY campaign accepted
    def test_payment_order_creation_monetary_campaign_accepted(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '500'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    # 8. HYBRID campaign accepted
    def test_payment_order_creation_hybrid_campaign_accepted(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.hybrid_campaign.id), 'amount': '1000'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    # 9. DRAFT campaign rejected
    def test_payment_order_creation_draft_campaign_rejected(self):
        draft_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Draft Appeal Test',
            short_description='Draft short desc',
            description='Draft long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.DRAFT,
            is_active=True,
        )
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(draft_c.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 10. PENDING_REVIEW campaign rejected
    def test_payment_order_creation_pending_review_campaign_rejected(self):
        pr_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='PR Appeal Test',
            short_description='PR short desc',
            description='PR long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.PENDING_REVIEW,
            is_active=True,
        )
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(pr_c.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 11. CANCELLED campaign rejected
    def test_payment_order_creation_cancelled_campaign_rejected(self):
        can_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Cancelled Appeal Test',
            short_description='Cancelled short desc',
            description='Cancelled long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.CANCELLED,
            is_active=False,
        )
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(can_c.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 12. SUSPENDED campaign rejected
    def test_payment_order_creation_suspended_campaign_rejected(self):
        sus_c = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Suspended Appeal Test',
            short_description='Suspended short desc',
            description='Suspended long desc text minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.SUSPENDED,
            is_active=False,
        )
        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(sus_c.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 13. Inactive NGO rejected
    def test_payment_order_creation_inactive_ngo_rejected(self):
        self.ngo_profile.is_active = False
        self.ngo_profile.save()

        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Restore
        self.ngo_profile.is_active = True
        self.ngo_profile.save()

    # 14. Unapproved NGO rejected
    def test_payment_order_creation_unapproved_ngo_rejected(self):
        self.ngo_profile.status = 'UNDER_REVIEW'
        self.ngo_profile.save()

        self.client.force_authenticate(user=self.donor_a)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '100'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Restore
        self.ngo_profile.status = 'APPROVED'
        self.ngo_profile.save()

    # 15. Invalid gateway signature rejected
    def test_invalid_gateway_signature_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '100',
        }, format='json')
        donation_id = order_res.data['donation_id']
        order_id = order_res.data['gateway_order_id']

        verify_payload = {
            'donation_id': donation_id,
            'razorpay_order_id': order_id,
            'razorpay_payment_id': 'pay_test_12345',
            'razorpay_signature': 'invalid_forged_signature_hex',
        }
        res = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', verify_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid payment gateway cryptographic signature', str(res.data))

    # 16. Missing gateway signature rejected
    def test_missing_gateway_signature_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        verify_payload = {
            'donation_id': str(uuid.uuid4()),
            'razorpay_order_id': 'order_123',
            'razorpay_payment_id': 'pay_123',
            'razorpay_signature': '',
        }
        res = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', verify_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 17. Valid gateway signature accepted & updates raised_amount exactly once
    def test_valid_gateway_signature_accepted_and_updates_raised_amount(self):
        self.client.force_authenticate(user=self.donor_a)
        initial_raised = self.monetary_campaign.raised_amount

        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '250.00',
        }, format='json')
        donation_id = order_res.data['donation_id']
        order_id = order_res.data['gateway_order_id']
        payment_id = 'pay_test_valid_999'

        valid_sig = self._generate_valid_signature(order_id, payment_id)

        verify_payload = {
            'donation_id': donation_id,
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': valid_sig,
        }
        res = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', verify_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'SUCCESS')

        # Check database records
        donation = MonetaryDonation.objects.get(id=donation_id)
        self.assertEqual(donation.status, MonetaryDonation.Status.SUCCESS)
        self.assertIsNotNone(donation.paid_at)

        tx = PaymentTransaction.objects.get(gateway_order_id=order_id)
        self.assertEqual(tx.status, PaymentTransaction.Status.SUCCESS)
        self.assertEqual(tx.gateway_payment_id, payment_id)

        self.monetary_campaign.refresh_from_db()
        self.assertEqual(self.monetary_campaign.raised_amount, initial_raised + Decimal('250.00'))

    # 18. Fake payment status in client request is rejected
    def test_fake_payment_status_in_order_creation_is_ignored(self):
        self.client.force_authenticate(user=self.donor_a)
        payload = {
            'campaign': str(self.monetary_campaign.id),
            'amount': '100',
            'status': 'SUCCESS',
            'payment_status': 'PAID',
            'paid_at': '2026-08-31T00:00:00Z',
        }
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        donation = MonetaryDonation.objects.get(id=res.data['donation_id'])
        self.assertEqual(donation.status, MonetaryDonation.Status.PENDING)
        self.assertIsNone(donation.paid_at)

    # 19. Duplicate payment verification request is idempotent (does NOT double-increment raised_amount)
    def test_repeated_verification_is_idempotent_no_double_increment(self):
        self.client.force_authenticate(user=self.donor_a)
        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '150.00',
        }, format='json')
        donation_id = order_res.data['donation_id']
        order_id = order_res.data['gateway_order_id']
        payment_id = 'pay_test_idem_123'
        valid_sig = self._generate_valid_signature(order_id, payment_id)

        verify_payload = {
            'donation_id': donation_id,
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': valid_sig,
        }
        # First verification
        res1 = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', verify_payload, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        self.monetary_campaign.refresh_from_db()
        raised_after_first = self.monetary_campaign.raised_amount

        # Second verification (retry)
        res2 = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', verify_payload, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)

        self.monetary_campaign.refresh_from_db()
        self.assertEqual(self.monetary_campaign.raised_amount, raised_after_first)

    # 20. Donor B cannot verify or access Donor A's payment transaction
    def test_donor_cross_access_prevented(self):
        self.client.force_authenticate(user=self.donor_a)
        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '200.00',
        }, format='json')
        donation_id = order_res.data['donation_id']
        order_id = order_res.data['gateway_order_id']
        payment_id = 'pay_test_cross_456'
        valid_sig = self._generate_valid_signature(order_id, payment_id)

        # Authenticate as Donor B
        self.client.force_authenticate(user=self.donor_b)
        verify_payload = {
            'donation_id': donation_id,
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': valid_sig,
        }
        res = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', verify_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Donor B listing must not contain Donor A's donation
        list_res = self.client.get('/api/v1/donor/monetary-donations/')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        results = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        donor_b_ids = [str(d['id']) for d in results]
        self.assertNotIn(str(donation_id), donor_b_ids)

    # 21. Razorpay webhook with valid signature processes payment.captured
    def test_webhook_valid_signature_processes_payment_captured(self):
        self.client.force_authenticate(user=self.donor_a)
        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '300.00',
        }, format='json')
        order_id = order_res.data['gateway_order_id']
        donation_id = order_res.data['donation_id']

        webhook_body_dict = {
            'event': 'payment.captured',
            'event_id': f'evt_test_{uuid.uuid4().hex[:8]}',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_webhook_test_111',
                        'order_id': order_id,
                        'amount': 30000,
                        'status': 'captured',
                    }
                }
            }
        }
        raw_body = json.dumps(webhook_body_dict).encode('utf-8')
        sig = self._generate_webhook_signature(raw_body)

        # Unauthenticated webhook call with signature header
        self.client.logout()
        res = self.client.post(
            '/api/v1/webhooks/razorpay/',
            raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=sig
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get('status'), 'ok')

        donation = MonetaryDonation.objects.get(id=donation_id)
        self.assertEqual(donation.status, MonetaryDonation.Status.SUCCESS)

    # 22. Razorpay webhook with invalid signature is rejected
    def test_webhook_invalid_signature_rejected(self):
        raw_body = json.dumps({'event': 'payment.captured'}).encode('utf-8')
        res = self.client.post(
            '/api/v1/webhooks/razorpay/',
            raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='forged_sig'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 23. Razorpay duplicate webhook is idempotent
    def test_webhook_duplicate_event_is_idempotent(self):
        self.client.force_authenticate(user=self.donor_a)
        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '400.00',
        }, format='json')
        order_id = order_res.data['gateway_order_id']

        evt_id = f'evt_idem_{uuid.uuid4().hex[:8]}'
        webhook_body_dict = {
            'event': 'payment.captured',
            'event_id': evt_id,
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_webhook_idem_222',
                        'order_id': order_id,
                        'amount': 40000,
                        'status': 'captured',
                    }
                }
            }
        }
        raw_body = json.dumps(webhook_body_dict).encode('utf-8')
        sig = self._generate_webhook_signature(raw_body)

        self.client.logout()
        res1 = self.client.post(
            '/api/v1/webhooks/razorpay/',
            raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=sig
        )
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        # Duplicate webhook delivery
        res2 = self.client.post(
            '/api/v1/webhooks/razorpay/',
            raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=sig
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data.get('status'), 'already_processed')

    # 24. Amount mismatch in webhook is rejected and does NOT update raised_amount
    def test_webhook_amount_mismatch_rejected(self):
        self.client.force_authenticate(user=self.donor_a)
        initial_raised = self.monetary_campaign.raised_amount

        order_res = self.client.post('/api/v1/donor/monetary-donations/create-order/', {
            'campaign': str(self.monetary_campaign.id),
            'amount': '500.00',
        }, format='json')
        order_id = order_res.data['gateway_order_id']
        donation_id = order_res.data['donation_id']

        # Webhook reports only 1000 paise (₹10) instead of ₹500
        webhook_body_dict = {
            'event': 'payment.captured',
            'event_id': f'evt_mismatch_{uuid.uuid4().hex[:8]}',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_webhook_mismatch_333',
                        'order_id': order_id,
                        'amount': 1000,
                        'status': 'captured',
                    }
                }
            }
        }
        raw_body = json.dumps(webhook_body_dict).encode('utf-8')
        sig = self._generate_webhook_signature(raw_body)

        self.client.logout()
        res = self.client.post(
            '/api/v1/webhooks/razorpay/',
            raw_body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=sig
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get('status'), 'amount_mismatch_rejected')

        donation = MonetaryDonation.objects.get(id=donation_id)
        self.assertEqual(donation.status, MonetaryDonation.Status.PENDING)

        self.monetary_campaign.refresh_from_db()
        self.assertEqual(self.monetary_campaign.raised_amount, initial_raised)


class Phase421CreateOrderFixTests(TestCase):
    """
    Automated test suite for Phase 4.2.1:
    Razorpay Create-Order Continuity & 400 Root Cause Fix.
    """

    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Approved NGO
        self.ngo_user = User.objects.create_user(
            email='ngo_p421@example.com',
            password='Password123!',
            role='NGO',
            full_name='P421 Education Foundation',
            is_active=True,
        )
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='P421 Education Foundation',
            display_name='P421 Education Foundation',
            slug='p421-education-foundation',
            category=NGOProfile.Category.EDUCATION,
            year_established=2019,
            status='APPROVED',
            is_active=True,
        )

        # 2. Donor
        self.donor_user = User.objects.create_user(
            email='donor_p421@example.com',
            password='Password123!',
            role='DONOR',
            full_name='P421 Donor User',
            is_active=True,
        )

        # 3. Active Campaign
        self.monetary_campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Help 100 Children With School Education',
            slug='help-100-children-with-school-education',
            short_description='School education appeal.',
            description='Detailed text for school education appeal minimum thirty chars.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000,
            raised_amount=0,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    # 1. create-order with valid campaign + ₹10 -> 201 Created
    def test_create_order_with_valid_campaign_accepted(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'campaign': str(self.monetary_campaign.id), 'amount': '10'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['amount'], '10.00')
        self.assertEqual(res.data['campaign_id'], str(self.monetary_campaign.id))

    # 2. create-order with ngo only -> automatically resolves active monetary campaign and returns 201 Created
    def test_create_order_with_ngo_only_resolves_active_campaign(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'ngo': str(self.ngo_profile.id), 'amount': '10'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['campaign_id'], str(self.monetary_campaign.id))

    # 3. create-order with neither campaign nor ngo -> automatically resolves active monetary campaign
    def test_create_order_without_campaign_or_ngo_resolves_active_campaign(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'amount': '10'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['campaign_id'], str(self.monetary_campaign.id))

    # 4. validate endpoint with ngo only returns campaign_id
    def test_validate_with_ngo_only_returns_campaign_id(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'ngo': str(self.ngo_profile.id), 'amount': '10'}
        res = self.client.post('/api/v1/donor/monetary-donations/validate/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['campaign_id'], str(self.monetary_campaign.id))

    # 5. create-order with invalid campaign UUID -> 400 Bad Request
    def test_create_order_invalid_campaign_uuid_rejected(self):
        self.client.force_authenticate(user=self.donor_user)
        payload = {'campaign': str(uuid.uuid4()), 'amount': '10'}
        res = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('campaign', res.data)


class Phase423FinancialVisibilityTests(TestCase):
    """
    Automated test suite for Phase 4.2.3:
    Financial Visibility & Portals (Donor + NGO + Admin).
    """

    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date.today()
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Admin User
        self.admin_user = User.objects.create_user(
            email='admin_p423@example.com',
            password='Password123!',
            role='ADMIN',
            full_name='System Administrator',
            is_active=True,
        )

        # 2. NGO A & Profile
        self.ngo_user_a = User.objects.create_user(
            email='ngo_a_p423@example.com',
            password='Password123!',
            role='NGO',
            full_name='NGO User A',
            is_active=True,
        )
        self.ngo_profile_a = NGOProfile.objects.create(
            user=self.ngo_user_a,
            legal_name='Education Trust Foundation A',
            display_name='Education Trust Foundation A',
            slug='education-trust-foundation-a',
            category=NGOProfile.Category.EDUCATION,
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )

        # 3. NGO B & Profile
        self.ngo_user_b = User.objects.create_user(
            email='ngo_b_p423@example.com',
            password='Password123!',
            role='NGO',
            full_name='NGO User B',
            is_active=True,
        )
        self.ngo_profile_b = NGOProfile.objects.create(
            user=self.ngo_user_b,
            legal_name='Healthcare Relief Trust B',
            display_name='Healthcare Relief Trust B',
            slug='healthcare-relief-trust-b',
            category=NGOProfile.Category.HEALTHCARE,
            year_established=2019,
            status='APPROVED',
            is_active=True,
        )

        # 4. Donor 1 & Donor 2
        self.donor_1 = User.objects.create_user(
            email='donor1_p423@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Donor One',
            is_active=True,
        )
        self.donor_2 = User.objects.create_user(
            email='donor2_p423@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Donor Two',
            is_active=True,
        )

        # 5. Campaigns
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Campaign A Monetary Drive',
            slug='campaign-a-monetary-drive',
            short_description='Appeal A',
            description='Detailed text for appeal A minimum thirty characters long.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=20000,
            raised_amount=1000,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title='Campaign B Monetary Drive',
            slug='campaign-b-monetary-drive',
            short_description='Appeal B',
            description='Detailed text for appeal B minimum thirty characters long.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000,
            raised_amount=500,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 6. Monetary Donations
        self.donation_1 = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('1000.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TEST01',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=False,
        )

        self.donation_2_pending = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('500.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TEST02',
            status=MonetaryDonation.Status.PENDING,
            is_anonymous=False,
        )

        self.donation_3_anonymous = MonetaryDonation.objects.create(
            donor=self.donor_2,
            campaign=self.campaign_a,
            amount=Decimal('2000.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TEST03',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=True,
        )

        self.donation_4_ngo_b = MonetaryDonation.objects.create(
            donor=self.donor_2,
            campaign=self.campaign_b,
            amount=Decimal('500.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TEST04',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=False,
        )

    # 1. Donor sees own successful donations
    def test_donor_sees_own_donations_list(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get('/api/v1/donor/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        receipts = [d['receipt_number'] for d in res.data]
        self.assertIn('DG-M-20260831-TEST01', receipts)
        self.assertIn('DG-M-20260831-TEST02', receipts)
        self.assertNotIn('DG-M-20260831-TEST03', receipts)
        self.assertNotIn('DG-M-20260831-TEST04', receipts)

    # 2. Donor cannot access another donor's donation detail
    def test_donor_cannot_access_other_donor_donation_detail(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_3_anonymous.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 3. NGO sees only its own campaign donations
    def test_ngo_sees_only_own_campaign_donations(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/campaigns/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        receipts = [d['receipt_number'] for d in res.data]
        self.assertIn('DG-M-20260831-TEST01', receipts)
        self.assertIn('DG-M-20260831-TEST02', receipts)
        self.assertIn('DG-M-20260831-TEST03', receipts)
        self.assertNotIn('DG-M-20260831-TEST04', receipts)

    # 4. Anonymous donor identity is protected in NGO view
    def test_anonymous_donor_masked_in_ngo_view(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/campaigns/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        anon_item = next(d for d in res.data if d['receipt_number'] == 'DG-M-20260831-TEST03')
        self.assertEqual(anon_item['donor_name'], 'Anonymous Donor')
        self.assertTrue(anon_item['is_anonymous'])

    # 5. NGO B cannot see NGO A's donations
    def test_ngo_b_cannot_see_ngo_a_donations(self):
        self.client.force_authenticate(user=self.ngo_user_b)
        res = self.client.get('/api/v1/ngo/campaigns/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        receipts = [d['receipt_number'] for d in res.data]
        self.assertIn('DG-M-20260831-TEST04', receipts)
        self.assertNotIn('DG-M-20260831-TEST01', receipts)
        self.assertNotIn('DG-M-20260831-TEST02', receipts)
        self.assertNotIn('DG-M-20260831-TEST03', receipts)

    # 6. Admin can view all platform monetary donations
    def test_admin_can_list_all_platform_monetary_donations(self):
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get('/api/v1/admin/campaigns/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        receipts = [d['receipt_number'] for d in res.data]
        self.assertIn('DG-M-20260831-TEST01', receipts)
        self.assertIn('DG-M-20260831-TEST02', receipts)
        self.assertIn('DG-M-20260831-TEST03', receipts)
        self.assertIn('DG-M-20260831-TEST04', receipts)

    # 7. Non-admin is forbidden from admin monetary donations endpoint
    def test_non_admin_forbidden_from_admin_monetary_donations(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get('/api/v1/admin/campaigns/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/admin/campaigns/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 8. GET operations do not mutate campaign raised_amount
    def test_get_requests_do_not_mutate_raised_amount(self):
        self.campaign_a.refresh_from_db()
        initial_raised = self.campaign_a.raised_amount

        self.client.force_authenticate(user=self.donor_1)
        self.client.get('/api/v1/donor/monetary-donations/')
        self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_1.id}/')

        self.client.force_authenticate(user=self.ngo_user_a)
        self.client.get('/api/v1/ngo/campaigns/monetary-donations/')

        self.client.force_authenticate(user=self.admin_user)
        self.client.get('/api/v1/admin/campaigns/monetary-donations/')

        self.campaign_a.refresh_from_db()
        self.assertEqual(self.campaign_a.raised_amount, initial_raised)


class Phase431TaxReceiptEngineTests(TestCase):
    """
    Automated test suite for Phase 4.3.1:
    Secure 80G Donation Receipt PDF Engine & Invariants.
    """

    def setUp(self):
        self.today = datetime.date(2026, 8, 31)
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Donor
        self.donor = User.objects.create_user(
            email='tax_donor@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Kamlesh Chaudhary',
            phone='+919876543210',
            is_active=True,
        )

        # 2. NGO with 80G Approval
        self.ngo_user_80g = User.objects.create_user(
            email='ngo_80g@example.com',
            password='Password123!',
            role='NGO',
            full_name='Education Trust Foundation',
            is_active=True,
        )
        self.ngo_profile_80g = NGOProfile.objects.create(
            user=self.ngo_user_80g,
            legal_name='Education Trust Foundation',
            display_name='Education Trust',
            slug='education-trust-foundation-tax',
            category=NGOProfile.Category.EDUCATION,
            year_established=2015,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal_80g = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_80g,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            registering_authority='Charity Commissioner, Gujarat',
            registration_number='E/1234/SURAT',
            registration_state='Gujarat',
            darpan_id='GJ/2020/0123456',
            pan_number='AAATE1234F',
            chief_trustee_name='Rajesh Kumar',
            chief_trustee_designation='Managing Trustee',
            has_80g=True,
            eighty_g_number='80G/CIT/SURAT/2021-22/104',
            eighty_g_validity=datetime.date(2028, 3, 31),
            has_12a=True,
            twelve_a_number='12A/CIT/SURAT/2021-22/502',
        )
        self.ngo_address_80g = NGOAddress.objects.create(
            ngo=self.ngo_profile_80g,
            address_line1='101 Trust House, Station Road',
            city='Surat',
            district='Surat',
            state='Gujarat',
            pincode='395003',
        )

        # 3. NGO without 80G Approval
        self.ngo_user_no_80g = User.objects.create_user(
            email='ngo_standard@example.com',
            password='Password123!',
            role='NGO',
            full_name='Community Relief Society',
            is_active=True,
        )
        self.ngo_profile_no_80g = NGOProfile.objects.create(
            user=self.ngo_user_no_80g,
            legal_name='Community Relief Society',
            display_name='Community Relief',
            slug='community-relief-society',
            category=NGOProfile.Category.DISASTER_RELIEF,
            year_established=2020,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal_no_80g = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_no_80g,
            organisation_type=NGOLegalInfo.OrgType.SOCIETY,
            registering_authority='Registrar of Societies',
            registration_number='SOC/5678',
            registration_state='Maharashtra',
            darpan_id='MH/2021/0987654',
            pan_number='AAATC5678K',
            chief_trustee_name='Suresh Sharma',
            chief_trustee_designation='President',
            has_80g=False,
        )

        # 4. Campaigns
        self.campaign_80g = Campaign.objects.create(
            ngo=self.ngo_profile_80g,
            created_by=self.ngo_user_80g,
            title='Primary School Literacy Drive',
            slug='primary-school-literacy-drive',
            short_description='Support education for underprivileged children',
            description='Detailed text for primary school literacy drive appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000,
            raised_amount=1000,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.campaign_no_80g = Campaign.objects.create(
            ngo=self.ngo_profile_no_80g,
            created_by=self.ngo_user_no_80g,
            title='Flood Relief Fund',
            slug='flood-relief-fund',
            short_description='Emergency relief supplies',
            description='Detailed text for emergency flood relief supplies appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=100000,
            raised_amount=500,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 5. Successful 80G Donation
        self.donation_success_80g = MonetaryDonation.objects.create(
            donor=self.donor,
            campaign=self.campaign_80g,
            amount=Decimal('1000.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TEST80G',
            pan_number='ABCDE1234F',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=False,
        )
        self.tx_success_80g = PaymentTransaction.objects.create(
            donation=self.donation_success_80g,
            donor=self.donor,
            gateway=PaymentTransaction.Gateway.RAZORPAY,
            gateway_order_id='order_test_80g_01',
            gateway_payment_id='pay_test_80g_01',
            amount=Decimal('1000.00'),
            currency='INR',
            status=PaymentTransaction.Status.SUCCESS,
        )

        # 6. Successful Standard Donation (No NGO 80G)
        self.donation_success_no_80g = MonetaryDonation.objects.create(
            donor=self.donor,
            campaign=self.campaign_no_80g,
            amount=Decimal('500.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TESTSTD',
            pan_number='ABCDE1234F',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=False,
        )
        self.tx_success_no_80g = PaymentTransaction.objects.create(
            donation=self.donation_success_no_80g,
            donor=self.donor,
            gateway=PaymentTransaction.Gateway.RAZORPAY,
            gateway_order_id='order_test_std_01',
            gateway_payment_id='pay_test_std_01',
            amount=Decimal('500.00'),
            currency='INR',
            status=PaymentTransaction.Status.SUCCESS,
        )

        # 7. Non-Successful Donations
        self.donation_pending = MonetaryDonation.objects.create(
            donor=self.donor,
            campaign=self.campaign_80g,
            amount=Decimal('200.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TESTPEND',
            status=MonetaryDonation.Status.PENDING,
        )

        self.donation_failed = MonetaryDonation.objects.create(
            donor=self.donor,
            campaign=self.campaign_80g,
            amount=Decimal('300.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TESTFAIL',
            status=MonetaryDonation.Status.FAILED,
        )

        self.donation_cancelled = MonetaryDonation.objects.create(
            donor=self.donor,
            campaign=self.campaign_80g,
            amount=Decimal('400.00'),
            currency='INR',
            receipt_number='DG-M-20260831-TESTCANC',
            status=MonetaryDonation.Status.CANCELLED,
        )

    # 1. SUCCESS donation with 80G approval generates EIGHTY_G receipt
    def test_success_donation_with_80g_generates_eighty_g_receipt(self):
        receipt = TaxReceiptService.get_or_create_tax_receipt(self.donation_success_80g)
        self.assertEqual(receipt.receipt_type, TaxReceiptRecord.ReceiptType.EIGHTY_G)
        self.assertEqual(receipt.receipt_number, 'DG-M-20260831-TEST80G')
        self.assertEqual(receipt.amount, Decimal('1000.00'))
        self.assertEqual(receipt.amount_in_words, 'One Thousand Rupees Only')
        self.assertEqual(receipt.ngo_legal_name_snapshot, 'Education Trust Foundation')
        self.assertEqual(receipt.ngo_80g_number_snapshot, '80G/CIT/SURAT/2021-22/104')
        self.assertEqual(receipt.donor_pan_masked_snapshot, '******234F')
        self.assertTrue(len(receipt.document_hash) == 64)
        self.assertIsNotNone(receipt.pdf_file)

    # 2. SUCCESS donation to NGO without 80G generates STANDARD receipt
    def test_success_donation_without_80g_generates_standard_receipt(self):
        receipt = TaxReceiptService.get_or_create_tax_receipt(self.donation_success_no_80g)
        self.assertEqual(receipt.receipt_type, TaxReceiptRecord.ReceiptType.STANDARD)
        self.assertEqual(receipt.receipt_number, 'DG-M-20260831-TESTSTD')
        self.assertEqual(receipt.amount, Decimal('500.00'))
        self.assertEqual(receipt.amount_in_words, 'Five Hundred Rupees Only')

    # 3. FAILED donation cannot generate tax receipt
    def test_failed_donation_raises_error(self):
        with self.assertRaises(ValueError):
            TaxReceiptService.get_or_create_tax_receipt(self.donation_failed)

    # 4. CANCELLED donation cannot generate tax receipt
    def test_cancelled_donation_raises_error(self):
        with self.assertRaises(ValueError):
            TaxReceiptService.get_or_create_tax_receipt(self.donation_cancelled)

    # 5. PENDING donation cannot generate tax receipt
    def test_pending_donation_raises_error(self):
        with self.assertRaises(ValueError):
            TaxReceiptService.get_or_create_tax_receipt(self.donation_pending)

    # 6. Idempotency: Duplicate calls return the same existing record
    def test_receipt_generation_is_idempotent(self):
        receipt_1 = TaxReceiptService.get_or_create_tax_receipt(self.donation_success_80g)
        receipt_2 = TaxReceiptService.get_or_create_tax_receipt(self.donation_success_80g)
        self.assertEqual(receipt_1.id, receipt_2.id)
        self.assertEqual(TaxReceiptRecord.objects.filter(donation=self.donation_success_80g).count(), 1)

    # 7. Financial Year utility accurately handles boundary dates
    def test_financial_year_boundaries(self):
        self.assertEqual(get_financial_year(datetime.date(2026, 4, 1)), 'FY 2026-27')
        self.assertEqual(get_financial_year(datetime.date(2026, 8, 31)), 'FY 2026-27')
        self.assertEqual(get_financial_year(datetime.date(2026, 12, 31)), 'FY 2026-27')
        self.assertEqual(get_financial_year(datetime.date(2027, 3, 31)), 'FY 2026-27')
        self.assertEqual(get_financial_year(datetime.date(2026, 3, 31)), 'FY 2025-26')
        self.assertEqual(get_financial_year(datetime.date(2026, 1, 15)), 'FY 2025-26')

    # 8. Amount in words handles multiple magnitudes
    def test_amount_to_words_magnitudes(self):
        self.assertEqual(amount_to_words_inr(Decimal('10.00')), 'Ten Rupees Only')
        self.assertEqual(amount_to_words_inr(Decimal('1000.00')), 'One Thousand Rupees Only')
        self.assertEqual(amount_to_words_inr(Decimal('25500.00')), 'Twenty Five Thousand Five Hundred Rupees Only')
        self.assertEqual(amount_to_words_inr(Decimal('100000.00')), 'One Lakh Rupees Only')
        self.assertEqual(amount_to_words_inr(Decimal('1550075.50')), 'Fifteen Lakh Fifty Thousand Seventy Five Rupees and Fifty Paise Only')
        self.assertEqual(amount_to_words_inr(Decimal('25000000.00')), 'Two Crore Fifty Lakh Rupees Only')

    # 9. PDF rendering produces valid binary PDF data starting with %PDF- and valid structure
    def test_pdf_rendering_valid_header(self):
        receipt = TaxReceiptService.get_or_create_tax_receipt(self.donation_success_80g)
        pdf_bytes = TaxReceiptService.render_receipt_pdf(receipt)
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        self.assertIn(b'ReportLab', pdf_bytes)
        self.assertIn(b'%%EOF', pdf_bytes)
        self.assertGreater(len(pdf_bytes), 1000)

    # 10. Immutable snapshot remains unchanged even if NGO updates name later
    def test_immutable_snapshot_preservation(self):
        receipt = TaxReceiptService.get_or_create_tax_receipt(self.donation_success_80g)
        original_ngo_name = receipt.ngo_legal_name_snapshot

        # NGO modifies legal name in live profile
        self.ngo_profile_80g.legal_name = 'Modified Future Trust Name'
        self.ngo_profile_80g.save()

        # Receipt snapshot must remain untouched
        receipt.refresh_from_db()
        self.assertEqual(receipt.ngo_legal_name_snapshot, original_ngo_name)
        self.assertEqual(receipt.ngo_legal_name_snapshot, 'Education Trust Foundation')


class Phase432ReceiptPdfDownloadTests(TestCase):
    """
    Automated test suite for Phase 4.3.2:
    Secure Receipt PDF Download APIs, Role-Based Access Control, and IDOR Defense.
    """

    def setUp(self):
        self.client = APIClient()
        self.today = datetime.date(2026, 8, 31)
        self.future = self.today + datetime.timedelta(days=30)

        # 1. Donors
        self.donor_1 = User.objects.create_user(
            email='donor_one@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Donor One',
            is_active=True,
        )
        self.donor_2 = User.objects.create_user(
            email='donor_two@example.com',
            password='Password123!',
            role='DONOR',
            full_name='Donor Two',
            is_active=True,
        )

        # 2. NGOs
        self.ngo_user_a = User.objects.create_user(
            email='ngo_a@example.com',
            password='Password123!',
            role='NGO',
            full_name='NGO Alpha User',
            is_active=True,
        )
        self.ngo_profile_a = NGOProfile.objects.create(
            user=self.ngo_user_a,
            legal_name='NGO Alpha Legal Trust',
            display_name='NGO Alpha',
            slug='ngo-alpha-tax',
            category=NGOProfile.Category.EDUCATION,
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal_a = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_a,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            registering_authority='Charity Commissioner, Gujarat',
            registration_number='E/9991/SURAT',
            registration_state='Gujarat',
            darpan_id='GJ/2021/0009991',
            pan_number='AAAAL1111A',
            chief_trustee_name='Alpha Trustee',
            chief_trustee_designation='Managing Trustee',
            has_80g=True,
            eighty_g_number='80G/CIT/2021/ALPHA',
            has_12a=True,
            twelve_a_number='12A/CIT/2021/ALPHA',
        )
        self.ngo_address_a = NGOAddress.objects.create(
            ngo=self.ngo_profile_a,
            address_line1='Alpha Complex',
            city='Surat',
            district='Surat',
            state='Gujarat',
            pincode='395001',
        )

        self.ngo_user_b = User.objects.create_user(
            email='ngo_b@example.com',
            password='Password123!',
            role='NGO',
            full_name='NGO Beta User',
            is_active=True,
        )
        self.ngo_profile_b = NGOProfile.objects.create(
            user=self.ngo_user_b,
            legal_name='NGO Beta Legal Society',
            display_name='NGO Beta',
            slug='ngo-beta-tax',
            category=NGOProfile.Category.HEALTHCARE,
            year_established=2019,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal_b = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_b,
            organisation_type=NGOLegalInfo.OrgType.SOCIETY,
            registering_authority='Registrar of Societies',
            registration_number='SOC/9992',
            registration_state='Maharashtra',
            darpan_id='MH/2021/0009992',
            pan_number='AAABE2222B',
            chief_trustee_name='Beta President',
            chief_trustee_designation='President',
            has_80g=False,
        )

        # 3. Admin
        self.admin_user = User.objects.create_user(
            email='admin_receipts@example.com',
            password='Password123!',
            role='ADMIN',
            full_name='Admin User',
            is_active=True,
        )

        # 4. Campaigns
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Alpha Medical Fund',
            slug='alpha-medical-fund',
            short_description='Medical aid fund',
            description='Detailed text for medical aid fund appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=50000,
            raised_amount=1000,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title='Beta School Kits',
            slug='beta-school-kits',
            short_description='School supplies kits',
            description='Detailed text for school supplies kits appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=20000,
            raised_amount=500,
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 5. Verified SUCCESS Donations
        self.donation_1 = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('1000.00'),
            currency='INR',
            receipt_number='DG-M-20260831-D1A',
            pan_number='ABCDE1111A',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=False,
        )
        self.tx_1 = PaymentTransaction.objects.create(
            donation=self.donation_1,
            donor=self.donor_1,
            gateway=PaymentTransaction.Gateway.RAZORPAY,
            gateway_order_id='order_d1_a_01',
            gateway_payment_id='pay_d1_a_01',
            amount=Decimal('1000.00'),
            currency='INR',
            status=PaymentTransaction.Status.SUCCESS,
        )

        self.donation_2 = MonetaryDonation.objects.create(
            donor=self.donor_2,
            campaign=self.campaign_b,
            amount=Decimal('500.00'),
            currency='INR',
            receipt_number='DG-M-20260831-D2B',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            is_anonymous=False,
        )
        self.tx_2 = PaymentTransaction.objects.create(
            donation=self.donation_2,
            donor=self.donor_2,
            gateway=PaymentTransaction.Gateway.RAZORPAY,
            gateway_order_id='order_d2_b_01',
            gateway_payment_id='pay_d2_b_01',
            amount=Decimal('500.00'),
            currency='INR',
            status=PaymentTransaction.Status.SUCCESS,
        )

        # 6. Non-Successful Donation
        self.donation_pending = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('250.00'),
            currency='INR',
            receipt_number='DG-M-20260831-D1PEND',
            status=MonetaryDonation.Status.PENDING,
        )

    # 1. Donor can download own verified receipt PDF (200, Content-Type: application/pdf)
    def test_donor_can_download_own_receipt_pdf(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', res['Content-Disposition'])
        self.assertIn(self.donation_1.receipt_number, res['Content-Disposition'])
        self.assertEqual(res['Cache-Control'], 'private, no-store')
        self.assertEqual(res['X-Content-Type-Options'], 'nosniff')
        self.assertTrue(res.content.startswith(b'%PDF-'))

    # 2. Donor A cannot download Donor B's receipt PDF (IDOR protection -> 404)
    def test_donor_cannot_download_another_donor_receipt(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_2.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 3. Unauthenticated request to donor receipt endpoint returns 401
    def test_unauthenticated_donor_endpoint_returns_401(self):
        res = self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    # 4. Donor cannot download receipt for non-successful donation (404)
    def test_donor_cannot_download_pending_donation_receipt(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_pending.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 5. NGO A can download receipt for donations made to its own campaign (200)
    def test_ngo_can_download_own_campaign_receipt(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get(f'/api/v1/ngo/campaigns/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertTrue(res.content.startswith(b'%PDF-'))

    # 6. NGO A cannot download receipt for NGO B's campaign (IDOR protection -> 404)
    def test_ngo_cannot_download_other_ngo_campaign_receipt(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get(f'/api/v1/ngo/campaigns/monetary-donations/{self.donation_2.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 7. Donor cannot access NGO receipt endpoint (403)
    def test_donor_cannot_access_ngo_receipt_endpoint(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(f'/api/v1/ngo/campaigns/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 8. Admin can download any verified platform donation receipt (200)
    def test_admin_can_download_any_receipt(self):
        self.client.force_authenticate(user=self.admin_user)
        res1 = self.client.get(f'/api/v1/admin/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1['Content-Type'], 'application/pdf')

        res2 = self.client.get(f'/api/v1/admin/campaigns/monetary-donations/{self.donation_2.id}/receipt-pdf/')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2['Content-Type'], 'application/pdf')

    # 9. Non-admin (Donor/NGO) cannot access Admin receipt endpoint (403)
    def test_non_admin_cannot_access_admin_receipt_endpoint(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(f'/api/v1/admin/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.ngo_user_a)
        res2 = self.client.get(f'/api/v1/admin/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        self.assertEqual(res2.status_code, status.HTTP_403_FORBIDDEN)

    # 10. Authorized download increments download_count; unauthorized does not
    def test_download_count_increments_only_on_authorized_success(self):
        receipt = TaxReceiptService.get_or_create_tax_receipt(self.donation_1)
        initial_count = receipt.download_count

        # Unauthorized attempt
        self.client.force_authenticate(user=self.donor_2)
        self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        receipt.refresh_from_db()
        self.assertEqual(receipt.download_count, initial_count)

        # Authorized attempt
        self.client.force_authenticate(user=self.donor_1)
        self.client.get(f'/api/v1/donor/monetary-donations/{self.donation_1.id}/receipt-pdf/')
        receipt.refresh_from_db()
        self.assertEqual(receipt.download_count, initial_count + 1)
        self.assertIsNotNone(receipt.last_downloaded_at)


# ===========================================================================
# PHASE 4.3.4 TESTS — NGO FORM 10BD COMPLIANCE LEDGER & EXPORT
# ===========================================================================

class Phase434ComplianceLedgerTests(TestCase):
    """
    Tests for Phase 4.3.4 Form 10BD Annual Donation Compliance Ledger,
    Financial Year filtering, dynamic summary calculations, tenant isolation,
    and CSV export generation.
    """

    def setUp(self):
        self.client = APIClient()
        # 1. Users
        self.donor_1 = User.objects.create_user(
            email='donor_comp_1@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Vikram Sharma',
            phone='+919876543210',
        )
        self.donor_2 = User.objects.create_user(
            email='donor_comp_2@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Ananya Iyer',
            phone='+919876543211',
        )
        self.ngo_user_a = User.objects.create_user(
            email='ngo_comp_a@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Aarav NGO Lead',
        )
        self.ngo_user_b = User.objects.create_user(
            email='ngo_comp_b@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Bhavna NGO Lead',
        )
        self.admin_user = User.objects.create_user(
            email='admin_comp@example.com',
            password='TestPassword123!',
            role='ADMIN',
            full_name='Super Admin',
        )

        # 2. NGO Profiles
        self.ngo_profile_a = NGOProfile.objects.create(
            user=self.ngo_user_a,
            legal_name='Aarav Welfare Foundation',
            display_name='Aarav Foundation',
            slug='aarav-welfare-foundation-comp',
            category=NGOProfile.Category.HEALTHCARE,
            year_established=2018,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        self.ngo_legal_a = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_a,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            registering_authority='Sub-Registrar Delhi',
            registration_number='TR/DEL/2024/001',
            registration_state='Delhi',
            chief_trustee_name='Aarav Lead',
            chief_trustee_designation='Managing Trustee',
            pan_number='AABBA1234A',
            has_80g=True,
            eighty_g_number='80G/DEL/2024/001',
            has_12a=True,
            twelve_a_number='12A/DEL/2024/001',
            darpan_id='DL/2024/0001',
        )

        self.ngo_profile_b = NGOProfile.objects.create(
            user=self.ngo_user_b,
            legal_name='Bhavna Health Trust',
            display_name='Bhavna Trust',
            slug='bhavna-health-trust-comp',
            category=NGOProfile.Category.HEALTHCARE,
            year_established=2019,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        self.ngo_legal_b = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_b,
            organisation_type=NGOLegalInfo.OrgType.SOCIETY,
            registering_authority='Registrar of Societies Mumbai',
            registration_number='SOC/MUM/2024/002',
            registration_state='Maharashtra',
            chief_trustee_name='Bhavna Lead',
            chief_trustee_designation='President',
            pan_number='BBBBB5678B',
            has_80g=True,
            eighty_g_number='80G/MUM/2024/002',
        )

        # 3. Campaigns
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title='Rural Healthcare Mission',
            short_description='Healthcare mission for rural villages',
            description='Detailed description for rural healthcare campaign appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('500000.00'),
            start_date=datetime.date(2026, 4, 1),
            end_date=datetime.date(2027, 3, 31),
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )
        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title='Clean Water Initiative',
            short_description='Clean water drive for drought-hit districts',
            description='Detailed description for clean drinking water infrastructure appeal.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('300000.00'),
            start_date=datetime.date(2026, 4, 1),
            end_date=datetime.date(2027, 3, 31),
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 4. Donations for NGO A (FY 2026-27: 01 Apr 2026 - 31 Mar 2027)
        # 4a. 80G Eligible Donation (PAN provided)
        self.donation_a_80g = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('5000.00'),
            currency='INR',
            receipt_number='DG-M-20260815-A11111',
            pan_number='ABCDE1234F',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.make_aware(datetime.datetime(2026, 8, 15, 10, 30)),
            is_anonymous=False,
        )
        PaymentTransaction.objects.create(
            donation=self.donation_a_80g,
            donor=self.donor_1,
            amount=Decimal('5000.00'),
            currency='INR',
            gateway='RAZORPAY',
            gateway_order_id='order_comp_a1',
            gateway_payment_id='pay_comp_a1',
            status=PaymentTransaction.Status.SUCCESS,
        )
        TaxReceiptService.get_or_create_tax_receipt(self.donation_a_80g)

        # 4b. Standard Donation (No PAN, anonymous publicly)
        self.donation_a_std = MonetaryDonation.objects.create(
            donor=self.donor_2,
            campaign=self.campaign_a,
            amount=Decimal('2000.00'),
            currency='INR',
            receipt_number='DG-M-20260901-A22222',
            pan_number='',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.make_aware(datetime.datetime(2026, 9, 1, 14, 0)),
            is_anonymous=True,
        )
        PaymentTransaction.objects.create(
            donation=self.donation_a_std,
            donor=self.donor_2,
            amount=Decimal('2000.00'),
            currency='INR',
            gateway='RAZORPAY',
            gateway_order_id='order_comp_a2',
            gateway_payment_id='pay_comp_a2',
            status=PaymentTransaction.Status.SUCCESS,
        )
        TaxReceiptService.get_or_create_tax_receipt(self.donation_a_std)

        # 4c. Non-successful donations for NGO A (MUST BE EXCLUDED)
        self.donation_a_pending = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('1000.00'),
            currency='INR',
            receipt_number='DG-M-20260820-A33333',
            status=MonetaryDonation.Status.PENDING,
            paid_at=None,
        )
        self.donation_a_failed = MonetaryDonation.objects.create(
            donor=self.donor_2,
            campaign=self.campaign_a,
            amount=Decimal('1500.00'),
            currency='INR',
            receipt_number='DG-M-20260822-A44444',
            status=MonetaryDonation.Status.FAILED,
            paid_at=None,
        )

        # 4d. Previous Financial Year Donation for NGO A (FY 2025-26: 15 Mar 2026)
        self.donation_a_prev_fy = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_a,
            amount=Decimal('3000.00'),
            currency='INR',
            receipt_number='DG-M-20260315-A55555',
            pan_number='ABCDE1234F',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.make_aware(datetime.datetime(2026, 3, 15, 11, 0)),
        )
        PaymentTransaction.objects.create(
            donation=self.donation_a_prev_fy,
            donor=self.donor_1,
            amount=Decimal('3000.00'),
            gateway='RAZORPAY',
            gateway_order_id='order_comp_a3',
            gateway_payment_id='pay_comp_a3',
            status=PaymentTransaction.Status.SUCCESS,
        )
        TaxReceiptService.get_or_create_tax_receipt(self.donation_a_prev_fy)

        # 5. Donation for NGO B (FY 2026-27)
        self.donation_b_success = MonetaryDonation.objects.create(
            donor=self.donor_1,
            campaign=self.campaign_b,
            amount=Decimal('8000.00'),
            currency='INR',
            receipt_number='DG-M-20260825-B11111',
            pan_number='ABCDE1234F',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.make_aware(datetime.datetime(2026, 8, 25, 16, 0)),
        )
        PaymentTransaction.objects.create(
            donation=self.donation_b_success,
            donor=self.donor_1,
            amount=Decimal('8000.00'),
            gateway='RAZORPAY',
            gateway_order_id='order_comp_b1',
            gateway_payment_id='pay_comp_b1',
            status=PaymentTransaction.Status.SUCCESS,
        )
        TaxReceiptService.get_or_create_tax_receipt(self.donation_b_success)

    # 1. NGO A can retrieve its own FY 2026-27 compliance ledger
    def test_ngo_can_retrieve_own_fy_ledger(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=FY%202026-27')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
        summary = res.data['summary']
        self.assertEqual(summary['financial_year'], 'FY 2026-27')
        self.assertEqual(summary['total_donations_count'], 2)
        self.assertEqual(Decimal(summary['total_donated_amount']), Decimal('7000.00'))
        self.assertEqual(summary['eighty_g_donations_count'], 1)
        self.assertEqual(Decimal(summary['eighty_g_donated_amount']), Decimal('5000.00'))
        self.assertEqual(summary['standard_donations_count'], 1)
        self.assertEqual(Decimal(summary['standard_donated_amount']), Decimal('2000.00'))
        self.assertEqual(summary['unique_donors_count'], 2)

        # Check records
        self.assertEqual(len(res.data['records']), 2)
        refs = [r['receipt_number'] for r in res.data['records']]
        self.assertIn('DG-M-20260815-A11111', refs)
        self.assertIn('DG-M-20260901-A22222', refs)

    # 2. Strict Tenant Isolation: NGO A cannot see NGO B's donations
    def test_ngo_cannot_see_other_ngo_donations(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=FY%202026-27')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        refs = [r['receipt_number'] for r in res.data['records']]
        self.assertNotIn('DG-M-20260825-B11111', refs)

    # 3. Non-successful donations (PENDING, FAILED) are excluded
    def test_non_successful_donations_excluded(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=FY%202026-27')
        refs = [r['receipt_number'] for r in res.data['records']]
        self.assertNotIn('DG-M-20260820-A33333', refs)
        self.assertNotIn('DG-M-20260822-A44444', refs)

    # 4. Previous FY donation appears only in FY 2025-26
    def test_previous_fy_filtering(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        # Check FY 2025-26
        res_prev = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=2025-26')
        self.assertEqual(res_prev.status_code, status.HTTP_200_OK)
        self.assertEqual(res_prev.data['summary']['total_donations_count'], 1)
        self.assertEqual(Decimal(res_prev.data['summary']['total_donated_amount']), Decimal('3000.00'))
        self.assertEqual(res_prev.data['records'][0]['receipt_number'], 'DG-M-20260315-A55555')

    # 5. Masked PAN in JSON API response (never expose raw PAN over standard API)
    def test_pan_is_masked_in_json_api(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=FY%202026-27')
        records = {r['receipt_number']: r for r in res.data['records']}
        self.assertEqual(records['DG-M-20260815-A11111']['donor_pan'], '******234F')
        self.assertEqual(records['DG-M-20260901-A22222']['donor_pan'], 'Not Provided')

    # 6. Anonymous donation retains internal legal donor name in compliance ledger
    def test_anonymous_donation_retains_legal_identity(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=FY%202026-27')
        records = {r['receipt_number']: r for r in res.data['records']}
        anon_rec = records['DG-M-20260901-A22222']
        self.assertEqual(anon_rec['donor_name'], 'Ananya Iyer')
        self.assertEqual(anon_rec['donor_email'], 'donor_comp_2@example.com')
        self.assertTrue(anon_rec['is_anonymous_public'])

    # 7. NGO Form 10BD CSV Export generates valid CSV with security headers
    def test_ngo_csv_export_validity_and_headers(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/export/?financial_year=FY%202026-27')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res['Content-Type'].startswith('text/csv'))
        self.assertIn('attachment; filename="DaanGives_Form10BD_Preparation_FY2026-27.csv"', res['Content-Disposition'])
        self.assertEqual(res['Cache-Control'], 'private, no-store')
        self.assertEqual(res['X-Content-Type-Options'], 'nosniff')

        csv_text = res.content.decode('utf-8')
        self.assertIn('Aarav Welfare Foundation', csv_text)
        self.assertIn('DG-M-20260815-A11111', csv_text)
        self.assertIn('DG-M-20260901-A22222', csv_text)
        self.assertIn('ABCDE1234F', csv_text)  # Raw PAN present in authorized compliance export
        self.assertNotIn('DG-M-20260825-B11111', csv_text)  # NGO B donation not present

    # 8. Donor cannot access NGO compliance ledger or export (403)
    def test_donor_cannot_access_ngo_compliance(self):
        self.client.force_authenticate(user=self.donor_1)
        res1 = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=FY%202026-27')
        self.assertEqual(res1.status_code, status.HTTP_403_FORBIDDEN)

        res2 = self.client.get('/api/v1/ngo/compliance/form-10bd/export/?financial_year=FY%202026-27')
        self.assertEqual(res2.status_code, status.HTTP_403_FORBIDDEN)

    # 9. Admin can access platform compliance ledger and filter by ngo_id
    def test_admin_can_access_compliance_ledger(self):
        self.client.force_authenticate(user=self.admin_user)
        # Platform-wide
        res_all = self.client.get('/api/v1/admin/compliance/form-10bd/?financial_year=FY%202026-27')
        self.assertEqual(res_all.status_code, status.HTTP_200_OK)
        self.assertEqual(res_all.data['summary']['total_donations_count'], 3)
        self.assertEqual(Decimal(res_all.data['summary']['total_donated_amount']), Decimal('15000.00'))

        # Filtered to NGO A
        res_ngo_a = self.client.get(f'/api/v1/admin/compliance/form-10bd/?financial_year=FY%202026-27&ngo_id={self.ngo_profile_a.id}')
        self.assertEqual(res_ngo_a.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ngo_a.data['summary']['total_donations_count'], 2)

    # 10. Invalid financial year format returns 400 Bad Request
    def test_invalid_financial_year_format_rejected(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/ngo/compliance/form-10bd/?financial_year=invalid-fy')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid financial year format', res.data['detail'])

    # 11. Indian FY date calculation boundary checks
    def test_fy_date_calculation_boundaries(self):
        start_d, end_d, fy_str = parse_financial_year('2026-27')
        self.assertEqual(start_d, datetime.date(2026, 4, 1))
        self.assertEqual(end_d, datetime.date(2027, 3, 31))
        self.assertEqual(fy_str, 'FY 2026-27')

    # 12. Non-admin cannot list platform-wide monetary donations (403 Forbidden)
    def test_non_admin_cannot_access_admin_monetary_donations_list(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get('/api/v1/admin/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.ngo_user_a)
        res2 = self.client.get('/api/v1/admin/monetary-donations/')
        self.assertEqual(res2.status_code, status.HTTP_403_FORBIDDEN)

    # 13. Non-NGO cannot access NGO monetary donations list (403 Forbidden)
    def test_non_ngo_cannot_access_ngo_monetary_donations_list(self):
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get('/api/v1/ngo/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # 14. Non-donor cannot access donor monetary donations list (403 Forbidden)
    def test_non_donor_cannot_access_donor_monetary_donations_list(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        res = self.client.get('/api/v1/donor/monetary-donations/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)