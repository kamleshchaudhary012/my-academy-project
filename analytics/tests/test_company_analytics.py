from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse

User = get_user_model()

class CompanyAnalyticsTests(APITestCase):
    def setUp(self):
        self.company = User.objects.create_user('comp@demo.local', 'password', role='COMPANY')
        self.donor = User.objects.create_user('donor@demo.local', 'password', role='DONOR')

    def test_unauthorized(self):
        url = reverse('analytics-company-me')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_forbidden_for_donor(self):
        self.client.force_authenticate(user=self.donor)
        url = reverse('analytics-company-me')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        
    def test_success(self):
        self.client.force_authenticate(user=self.company)
        url = reverse('analytics-company-me')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('total_csr_spend', res.data)
