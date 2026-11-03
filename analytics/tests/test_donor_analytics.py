from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse

User = get_user_model()

class DonorAnalyticsTests(APITestCase):
    def setUp(self):
        self.donor = User.objects.create_user('donor@demo.local', 'password', role='DONOR')
        self.ngo = User.objects.create_user('ngo@demo.local', 'password', role='NGO')

    def test_unauthorized(self):
        url = reverse('analytics-donor-me')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        
    def test_forbidden_for_ngo(self):
        self.client.force_authenticate(user=self.ngo)
        url = reverse('analytics-donor-me')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        
    def test_success(self):
        self.client.force_authenticate(user=self.donor)
        url = reverse('analytics-donor-me')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('total_donated', res.data)
