from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse

User = get_user_model()

class AdminAnalyticsTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin@demo.local', 'password')
        self.user = User.objects.create_user('user@demo.local', 'password', role='DONOR')

    def test_overview_unauthorized(self):
        url = reverse('analytics-admin-overview')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_overview_forbidden(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('analytics-admin-overview')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        
    def test_overview_success(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('analytics-admin-overview')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('donations', res.data)
        self.assertIn('ngos', res.data)
        
    def test_donations_success(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('analytics-admin-donations')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
    def test_ngos_success(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('analytics-admin-ngos')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
    def test_csr_success(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('analytics-admin-csr')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        
    def test_grievances_success(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('analytics-admin-grievances')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_overview_aggregation_counts_with_real_records(self):
        """
        Regression Test for Finding #1:
        Verifies that AdminAnalyticsService.get_overview() correctly aggregates counts
        for verified/pending/rejected NGOs, active/completed/draft campaigns, and
        open/in_review/resolved/closed grievances rather than returning zero due to invalid F() expressions.
        """
        import uuid
        from datetime import timedelta
        from django.utils import timezone
        from ngo.models import NGOProfile, NGOVerification
        from campaigns.models import Campaign
        from grievances.models import GrievanceTicket, GrievanceStatus

        # 1. Create NGOs with distinct statuses
        ngo_user1 = User.objects.create_user('ngo1@demo.local', 'password', role='NGO')
        ngo1 = NGOProfile.objects.create(
            user=ngo_user1, legal_name='Approved Trust', display_name='Approved Trust',
            category='EDUCATION', year_established=2015, status=NGOProfile.Status.APPROVED
        )
        NGOVerification.objects.get_or_create(ngo=ngo1)

        ngo_user2 = User.objects.create_user('ngo2@demo.local', 'password', role='NGO')
        ngo2 = NGOProfile.objects.create(
            user=ngo_user2, legal_name='Submitted Trust', display_name='Submitted Trust',
            category='HEALTHCARE', year_established=2018, status=NGOProfile.Status.SUBMITTED
        )
        NGOVerification.objects.get_or_create(ngo=ngo2)

        ngo_user3 = User.objects.create_user('ngo3@demo.local', 'password', role='NGO')
        ngo3 = NGOProfile.objects.create(
            user=ngo_user3, legal_name='Under Review Trust', display_name='Under Review Trust',
            category='ENVIRONMENT', year_established=2020, status=NGOProfile.Status.UNDER_REVIEW
        )
        NGOVerification.objects.get_or_create(ngo=ngo3)

        ngo_user4 = User.objects.create_user('ngo4@demo.local', 'password', role='NGO')
        ngo4 = NGOProfile.objects.create(
            user=ngo_user4, legal_name='Rejected Trust', display_name='Rejected Trust',
            category='DISASTER_RELIEF', year_established=2021, status=NGOProfile.Status.REJECTED
        )
        NGOVerification.objects.get_or_create(ngo=ngo4)

        # 2. Create Campaigns with distinct statuses
        today = timezone.now().date()
        c_active = Campaign.objects.create(
            ngo=ngo1, created_by=ngo_user1, title='Active Appeal', category='EDUCATION',
            campaign_type='MONETARY', target_amount=5000, start_date=today,
            end_date=today + timedelta(days=30), status=Campaign.Status.ACTIVE,
            short_description='Short active desc', description='Long active description text that satisfies minimum length'
        )
        c_completed = Campaign.objects.create(
            ngo=ngo1, created_by=ngo_user1, title='Completed Appeal', category='EDUCATION',
            campaign_type='MONETARY', target_amount=10000, start_date=today - timedelta(days=60),
            end_date=today - timedelta(days=10), status=Campaign.Status.COMPLETED,
            short_description='Short completed desc', description='Long completed description text that satisfies minimum length'
        )
        c_draft = Campaign.objects.create(
            ngo=ngo1, created_by=ngo_user1, title='Draft Appeal', category='EDUCATION',
            campaign_type='MONETARY', target_amount=2000, start_date=today,
            end_date=today + timedelta(days=15), status=Campaign.Status.DRAFT,
            short_description='Short draft desc', description='Long draft description text that satisfies minimum length'
        )

        # 3. Create GrievanceTickets with distinct statuses
        g_open = GrievanceTicket.objects.create(
            user=self.user, ticket_number=f'GRV-{uuid.uuid4().hex[:8]}',
            category='DONATION_PAYMENT', priority='HIGH', status=GrievanceStatus.OPEN
        )
        g_review = GrievanceTicket.objects.create(
            user=self.user, ticket_number=f'GRV-{uuid.uuid4().hex[:8]}',
            category='TECHNICAL_SUPPORT', priority='MEDIUM', status=GrievanceStatus.IN_REVIEW
        )
        g_resolved = GrievanceTicket.objects.create(
            user=self.user, ticket_number=f'GRV-{uuid.uuid4().hex[:8]}',
            category='RECEIPT_80G', priority='LOW', status=GrievanceStatus.RESOLVED
        )
        g_closed = GrievanceTicket.objects.create(
            user=self.user, ticket_number=f'GRV-{uuid.uuid4().hex[:8]}',
            category='OTHER', priority='URGENT', status=GrievanceStatus.CLOSED
        )

        # 4. Verify API endpoint output via client
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # NGO assertions
        ngos_data = res.data['ngos']
        self.assertEqual(ngos_data['total'], 4)
        self.assertEqual(ngos_data['verified'], 1)
        self.assertEqual(ngos_data['pending'], 2)  # SUBMITTED + UNDER_REVIEW
        self.assertEqual(ngos_data['rejected'], 1)

        # Campaign assertions
        campaigns_data = res.data['campaigns']
        self.assertEqual(campaigns_data['total'], 3)
        self.assertEqual(campaigns_data['active'], 1)
        self.assertEqual(campaigns_data['completed'], 1)
        self.assertEqual(campaigns_data['draft'], 1)

        # Grievance assertions
        grievances_data = res.data['grievances']
        self.assertEqual(grievances_data['total'], 4)
        self.assertEqual(grievances_data['open'], 1)
        self.assertEqual(grievances_data['in_review'], 1)
        self.assertEqual(grievances_data['resolved'], 1)
        self.assertEqual(grievances_data['closed'], 1)

    def test_overview_empty_state(self):
        """Verify that when no records exist, overview returns 0 counts without error."""
        from analytics.services import AdminAnalyticsService
        data = AdminAnalyticsService.get_overview()
        self.assertEqual(data['ngos']['total'], 0)
        self.assertEqual(data['ngos']['verified'], 0)
        self.assertEqual(data['ngos']['pending'], 0)
        self.assertEqual(data['campaigns']['total'], 0)
        self.assertEqual(data['campaigns']['active'], 0)
        self.assertEqual(data['grievances']['total'], 0)
        self.assertEqual(data['grievances']['open'], 0)
