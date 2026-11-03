"""
Tests for GET /api/v1/public/campaigns/ — Public Campaign List & Filtering.
"""

from decimal import Decimal
import datetime
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign
from ngo.models import NGOProfile
from ngo.tests.helpers import make_user, make_ngo_profile


class TestPublicCampaignListView(APITestCase):

    def setUp(self):
        self.url = reverse('campaign_public_list')

        # Approved NGO 1
        self.ngo_user = make_user(email='ngo_campaign@test.com', role='NGO')
        self.approved_ngo = make_ngo_profile(
            user=self.ngo_user,
            legal_name='Vidyadeep Educational Trust',
            display_name='Vidyadeep Foundation',
            category='EDUCATION',
        )
        NGOProfile.objects.filter(pk=self.approved_ngo.pk).update(status='APPROVED', is_active=True)
        self.approved_ngo.refresh_from_db()

        # Approved NGO 2
        self.ngo_user_2 = make_user(email='ngo2_campaign@test.com', role='NGO')
        self.approved_ngo_2 = make_ngo_profile(
            user=self.ngo_user_2,
            legal_name='Prakriti Sanstha',
            display_name='Prakriti Trust',
            category='ENVIRONMENT',
        )
        NGOProfile.objects.filter(pk=self.approved_ngo_2.pk).update(status='APPROVED', is_active=True)
        self.approved_ngo_2.refresh_from_db()

        # Unapproved NGO
        self.unapproved_user = make_user(email='pending_camp@test.com', role='NGO')
        self.unapproved_ngo = make_ngo_profile(
            user=self.unapproved_user,
            legal_name='Unverified Trust',
            display_name='Unverified NGO',
        )
        NGOProfile.objects.filter(pk=self.unapproved_ngo.pk).update(status='PENDING_VERIFICATION', is_active=True)
        self.unapproved_ngo.refresh_from_db()

        # 1. Active Public Campaign for Approved NGO 1 (Visible)
        self.camp_edu = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.ngo_user,
            title='Rural Schools Digital Labs',
            short_description='Bring computers to rural Gujarat schools',
            description='Detailed digital lab initiative description for education.',
            category='EDUCATION',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('100000.00'),
            raised_amount=Decimal('25000.00'),
            status=Campaign.Status.ACTIVE,
            is_active=True,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + datetime.timedelta(days=60),
        )

        # 2. Active Public Campaign for Approved NGO 2 (Visible)
        self.camp_env = Campaign.objects.create(
            ngo=self.approved_ngo_2,
            created_by=self.ngo_user_2,
            title='Clean River Project',
            short_description='Restoring riverbanks and planting native trees',
            description='Comprehensive tree plantation and clean river drive for environmental care.',
            category='ENVIRONMENT',
            campaign_type=Campaign.CampaignType.MATERIAL,
            target_amount=Decimal('50000.00'),
            raised_amount=Decimal('10000.00'),
            status=Campaign.Status.ACTIVE,
            is_active=True,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + datetime.timedelta(days=90),
        )

        # 3. Non-active / Inactive campaign (Hidden)
        self.camp_draft = Campaign.objects.create(
            ngo=self.approved_ngo,
            created_by=self.ngo_user,
            title='Draft Appeal',
            short_description='Draft non-active appeal',
            description='Detailed description for draft non-active appeal must be 30 chars.',
            category='EDUCATION',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('10000.00'),
            status=Campaign.Status.DRAFT,
            is_active=True,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + datetime.timedelta(days=30),
        )

        # 4. Campaign for Unapproved NGO (Hidden)
        self.camp_unapproved_ngo = Campaign.objects.create(
            ngo=self.unapproved_ngo,
            created_by=self.unapproved_user,
            title='Unapproved Appeal',
            short_description='Appeal by unverified NGO',
            description='Detailed description for unapproved NGO appeal must be 30 chars.',
            category='EDUCATION',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('15000.00'),
            status=Campaign.Status.ACTIVE,
            is_active=True,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + datetime.timedelta(days=30),
        )

    def test_unfiltered_list_returns_eligible_active_campaigns_only(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 2)
        titles = [c['title'] for c in res.data['results']]
        self.assertIn('Rural Schools Digital Labs', titles)
        self.assertIn('Clean River Project', titles)
        self.assertNotIn('Draft Appeal', titles)
        self.assertNotIn('Unapproved Appeal', titles)

    def test_filter_by_category_and_cleared_category(self):
        # Specific category
        res_edu = self.client.get(self.url, {'category': 'EDUCATION'})
        self.assertEqual(res_edu.data['count'], 1)
        self.assertEqual(res_edu.data['results'][0]['title'], 'Rural Schools Digital Labs')

        # 'ALL', 'all', 'All', and '' must all act as cleared/unfiltered
        for cleared_val in ['ALL', 'all', 'All', '']:
            res = self.client.get(self.url, {'category': cleared_val})
            self.assertEqual(res.data['count'], 2, f"Failed for category={cleared_val}")

    def test_filter_by_campaign_type_and_cleared_type(self):
        res_mat = self.client.get(self.url, {'campaign_type': 'MATERIAL'})
        self.assertEqual(res_mat.data['count'], 1)
        self.assertEqual(res_mat.data['results'][0]['title'], 'Clean River Project')

        for cleared_val in ['ALL', 'all', 'All', '']:
            res = self.client.get(self.url, {'campaign_type': cleared_val})
            self.assertEqual(res.data['count'], 2, f"Failed for campaign_type={cleared_val}")

    def test_filter_by_search_and_cleared_search(self):
        res_search = self.client.get(self.url, {'search': 'Digital'})
        self.assertEqual(res_search.data['count'], 1)

        res_cleared = self.client.get(self.url, {'search': ''})
        self.assertEqual(res_cleared.data['count'], 2)

    def test_cleared_filters_combined_returns_all_eligible_campaigns(self):
        res = self.client.get(self.url, {
            'search': '',
            'category': 'All',
            'campaign_type': 'All',
            'ordering': '-created_at',
            'page': 1,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 2)
