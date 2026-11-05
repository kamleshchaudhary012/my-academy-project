"""
Tests for Company Registration & Profile Creation Fix
=====================================================
Validates that:
1. Registration with role=COMPANY creates User, CompanyProfile (DRAFT), and CompanyCSRPreference.
2. Registration with organization_name and cin_number properly populates the CompanyProfile.
3. Non-company registrations do not create CompanyProfile.
4. CompanyVerificationDocumentView returns clean 400 with NO_COMPANY_PROFILE when user has no profile.
5. The repair_company_profiles management command safely repairs orphaned company accounts.
"""

from io import StringIO
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CompanyCSRPreference,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    generate_valid_cin,
)

User = get_user_model()


class CompanyRegistrationFixTests(APITestCase):
    """Verifies that Company user registration creates CompanyProfile and CompanyCSRPreference atomically."""

    def test_company_registration_creates_profile_and_preferences(self):
        url = reverse('auth-register') if 'auth-register' in [u._endpoint for u in []] else '/api/v1/auth/register/'
        cin = generate_valid_cin()
        payload = {
            'email': 'acme_csr@example.com',
            'full_name': 'Acme Director',
            'phone': '+919876543210',
            'password': 'SecurePassword123!',
            'password_confirm': 'SecurePassword123!',
            'role': User.Role.COMPANY,
            'organization_name': 'Acme Industries Private Limited',
            'registration_number': cin,
            'cin_number': cin,
        }

        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        # Verify User was created
        user = User.objects.get(email='acme_csr@example.com')
        self.assertEqual(user.role, User.Role.COMPANY)
        self.assertEqual(user.full_name, 'Acme Director')

        # Verify CompanyProfile was created in DRAFT status
        self.assertTrue(hasattr(user, 'company_profile'))
        company = user.company_profile
        self.assertEqual(company.company_name, 'Acme Industries Private Limited')
        self.assertEqual(company.legal_name, 'Acme Industries Private Limited')
        self.assertEqual(company.cin_number, cin)
        self.assertEqual(company.contact_person_name, 'Acme Director')
        self.assertEqual(company.contact_email, 'acme_csr@example.com')
        self.assertEqual(company.contact_phone, '+919876543210')
        self.assertEqual(company.verification_status, CompanyVerificationStatus.DRAFT)

        # Verify default CSR preferences were created
        self.assertTrue(CompanyCSRPreference.objects.filter(company=company).exists())

    def test_donor_registration_does_not_create_company_profile(self):
        url = '/api/v1/auth/register/'
        payload = {
            'email': 'individual_donor@example.com',
            'full_name': 'Individual Donor',
            'phone': '+919876543211',
            'password': 'SecurePassword123!',
            'password_confirm': 'SecurePassword123!',
            'role': User.Role.DONOR,
        }

        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        user = User.objects.get(email='individual_donor@example.com')
        self.assertFalse(CompanyProfile.objects.filter(user=user).exists())

    def test_document_upload_without_company_profile_returns_400_with_code(self):
        """When an orphaned company user tries to upload document before profile is created,
        returns 400 with NO_COMPANY_PROFILE instead of unhandled 404."""
        orphan_user = make_user(email='orphan_company@example.com', role=User.Role.COMPANY)
        self.client.force_authenticate(user=orphan_user)

        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_pdf = SimpleUploadedFile("cert.pdf", b"%PDF-1.4 test certificate content", content_type="application/pdf")

        response = self.client.post(
            '/api/v1/csr/profile/verification-document/',
            {'verification_document': fake_pdf},
            format='multipart'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'NO_COMPANY_PROFILE')
        self.assertIn('corporate profile details', response.data.get('detail', ''))

    def test_repair_company_profiles_command_dry_run(self):
        """Dry-run should identify orphaned users but make zero database modifications."""
        orphan_user = make_user(
            email='orphan_repair_dry@example.com',
            role=User.Role.COMPANY,
            full_name='Dry Run Company'
        )

        out = StringIO()
        call_command('repair_company_profiles', '--dry-run', stdout=out)
        output = out.getvalue()

        self.assertIn('orphan_repair_dry@example.com', output)
        self.assertIn('Audit Complete (DRY-RUN SIMULATION)', output)
        self.assertFalse(CompanyProfile.objects.filter(user=orphan_user).exists())

    def test_repair_company_profiles_command_live_execution(self):
        """Live run should create DRAFT CompanyProfile and CSR preferences."""
        orphan_user = make_user(
            email='orphan_repair_live@example.com',
            role=User.Role.COMPANY,
            full_name='Live Repair Company User',
            phone='+919876543299'
        )

        out = StringIO()
        call_command('repair_company_profiles', email='orphan_repair_live@example.com', stdout=out)
        output = out.getvalue()

        self.assertIn('Created DRAFT CompanyProfile', output)
        self.assertTrue(CompanyProfile.objects.filter(user=orphan_user).exists())

        profile = CompanyProfile.objects.get(user=orphan_user)
        self.assertEqual(profile.verification_status, CompanyVerificationStatus.DRAFT)
        self.assertEqual(profile.contact_person_name, 'Live Repair Company User')
        self.assertEqual(profile.contact_email, 'orphan_repair_live@example.com')
        self.assertTrue(CompanyCSRPreference.objects.filter(company=profile).exists())

        # Second run should be idempotent
        out2 = StringIO()
        call_command('repair_company_profiles', email='orphan_repair_live@example.com', stdout=out2)
        self.assertIn('Missing profiles repaired: 0', out2.getvalue())
