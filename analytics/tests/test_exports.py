from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse

User = get_user_model()

class ExportTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin@demo.local', 'password')
        self.user = User.objects.create_user('user@demo.local', 'password', role='DONOR')
        self.endpoints = [
            'analytics-export-ngos',
            'analytics-export-csr',
            'analytics-export-grievances',
        ]

    def test_exports_csv_success(self):
        self.client.force_authenticate(user=self.admin)
        for ep in self.endpoints:
            url = reverse(ep)
            res = self.client.get(url, {'format': 'csv'})
            self.assertEqual(res.status_code, status.HTTP_200_OK, f"Failed at {ep}: {res.content}")
            self.assertEqual(res['Content-Type'], 'text/csv')

    def test_exports_excel_success(self):
        self.client.force_authenticate(user=self.admin)
        for ep in self.endpoints:
            url = reverse(ep)
            res = self.client.get(url, {'format': 'excel'})
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertEqual(res['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_exports_pdf_success(self):
        self.client.force_authenticate(user=self.admin)
        for ep in self.endpoints:
            url = reverse(ep)
            res = self.client.get(url, {'format': 'pdf'})
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertEqual(res['Content-Type'], 'application/pdf')

    def test_form_csr_1(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('analytics-export-form-csr-1')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')

    def test_forbidden(self):
        self.client.force_authenticate(user=self.user)
        for ep in self.endpoints:
            url = reverse(ep)
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
