from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse

User = get_user_model()

class PermissionsTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin@demo.local', 'password')
        self.donor = User.objects.create_user('donor@demo.local', 'password', role='DONOR')
        self.ngo = User.objects.create_user('ngo@demo.local', 'password', role='NGO')
        self.company = User.objects.create_user('comp@demo.local', 'password', role='COMPANY')
        
    def test_cross_role_idor_donor(self):
        self.client.force_authenticate(user=self.donor)
        self.assertEqual(self.client.get(reverse('analytics-ngo-me')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('analytics-company-me')).status_code, status.HTTP_403_FORBIDDEN)
        
    def test_cross_role_idor_ngo(self):
        self.client.force_authenticate(user=self.ngo)
        self.assertEqual(self.client.get(reverse('analytics-donor-me')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('analytics-company-me')).status_code, status.HTTP_403_FORBIDDEN)
        
    def test_cross_role_idor_company(self):
        self.client.force_authenticate(user=self.company)
        self.assertEqual(self.client.get(reverse('analytics-donor-me')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('analytics-ngo-me')).status_code, status.HTTP_403_FORBIDDEN)
