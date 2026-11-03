from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse
from analytics.services import AdminAnalyticsService

User = get_user_model()

class AdditionalAnalyticsTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin2@demo.local', 'password')

    def test_overview_keys_detailed_1(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('donations', res.data)
        
    def test_overview_keys_detailed_2(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('ngos', res.data)
        
    def test_overview_keys_detailed_3(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('campaigns', res.data)
        
    def test_overview_keys_detailed_4(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('csr', res.data)
        
    def test_overview_keys_detailed_5(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('grievances', res.data)
        
    def test_admin_donations_filters_1(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-donations') + "?group_by=day")
        self.assertEqual(res.status_code, 200)

    def test_admin_donations_filters_2(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-donations') + "?group_by=week")
        self.assertEqual(res.status_code, 200)

    def test_admin_donations_filters_3(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-donations') + "?group_by=month")
        self.assertEqual(res.status_code, 200)
        
    def test_admin_donations_filters_4(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-donations') + "?from=2026-01-01&to=2026-12-31")
        self.assertEqual(res.status_code, 200)

    def test_services_admin_overview(self):
        data = AdminAnalyticsService.get_overview()
        self.assertIsInstance(data, dict)

    def test_services_admin_donations(self):
        data = AdminAnalyticsService.get_donations()
        self.assertIsInstance(data, list)

    def test_services_admin_ngos(self):
        data = AdminAnalyticsService.get_ngos()
        # QuerySet returned, but truthy
        self.assertIsNotNone(data)

    def test_services_admin_csr(self):
        data = AdminAnalyticsService.get_csr()
        self.assertIsNotNone(data)

    def test_services_admin_grievances(self):
        data = AdminAnalyticsService.get_grievances()
        self.assertIsNotNone(data)

    def test_admin_overview_content(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('total_amount', res.data['donations'])
        self.assertIn('total_count', res.data['donations'])
        
    def test_admin_ngo_content(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('total', res.data['ngos'])
        self.assertIn('verified', res.data['ngos'])
        
    def test_admin_campaign_content(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('total', res.data['campaigns'])
        self.assertIn('active', res.data['campaigns'])
        
    def test_admin_csr_content(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('companies', res.data['csr'])
        
    def test_admin_grievances_content(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse('analytics-admin-overview'))
        self.assertIn('open', res.data['grievances'])
