"""
Unit & Integration Tests for CSR Dashboard Profile Fix
======================================================
Tests error handling and response structures for:
1. User with active corporate profile -> 200 OK dashboard DTO.
2. User without corporate profile -> 404 with code 'NO_COMPANY_PROFILE'.
3. User with inactive/suspended profile -> 404 with code 'PROFILE_INACTIVE'.
4. Token user mismatch (role != COMPANY or unauthenticated) -> 403 / 401.
5. link_csr_profile management command idempotency and linking.
"""

from io import StringIO
from django.contrib.auth import get_user_model
from django.core.management import call_command
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
)

User = get_user_model()


class CSRDashboardProfileFixTests(APITestCase):
    """Validates CSR dashboard behavior across all corporate profile states."""

    @classmethod
    def setUpTestData(cls):
        # 1. Company user with APPROVED active profile
        cls.active_user = make_user(email="active_csr@example.com", role=User.Role.COMPANY)
        cls.active_company = make_company_profile(
            user=cls.active_user,
            company_name="Active CSR Corp",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        # 2. Company user with DRAFT profile (active for dashboard exploration)
        cls.draft_user = make_user(email="draft_csr@example.com", role=User.Role.COMPANY)
        cls.draft_company = make_company_profile(
            user=cls.draft_user,
            company_name="Draft CSR Corp",
            verification_status=CompanyVerificationStatus.DRAFT,
        )

        # 3. Company user without any CompanyProfile
        cls.noprofile_user = make_user(email="noprofile_csr@example.com", role=User.Role.COMPANY)

        # 4. Company user with SUSPENDED (inactive) profile
        cls.suspended_user = make_user(email="suspended_csr@example.com", role=User.Role.COMPANY)
        cls.suspended_company = make_company_profile(
            user=cls.suspended_user,
            company_name="Suspended CSR Corp",
            verification_status=CompanyVerificationStatus.SUSPENDED,
        )

        # 5. Non-company users for mismatch tests
        cls.donor_user = make_user(email="donor_user@example.com", role=User.Role.DONOR)
        cls.ngo_user = make_user(email="ngo_user@example.org", role=User.Role.NGO)

    def test_user_with_active_profile_loads_dashboard_successfully(self):
        """User with active approved company profile loads dashboard with HTTP 200."""
        self.client.force_authenticate(user=self.active_user)
        response = self.client.get('/api/v1/csr/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['company_name'], "Active CSR Corp")
        self.assertEqual(response.data['verification_status'], "APPROVED")
        self.assertIn('committed_funding_total', response.data)
        self.assertIn('disbursed_funding_total', response.data)
        self.assertIn('active_partnerships_count', response.data)
        self.assertIn('pending_requests_count', response.data)
        self.assertIn('recommended_proposals', response.data)

    def test_user_with_draft_profile_loads_dashboard_successfully(self):
        """User with draft company profile loads dashboard (showing verification notice)."""
        self.client.force_authenticate(user=self.draft_user)
        response = self.client.get('/api/v1/csr/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['company_name'], "Draft CSR Corp")
        self.assertEqual(response.data['verification_status'], "DRAFT")

    def test_user_without_profile_returns_404_no_company_profile(self):
        """User without linked CompanyProfile receives HTTP 404 with code NO_COMPANY_PROFILE."""
        self.client.force_authenticate(user=self.noprofile_user)
        response = self.client.get('/api/v1/csr/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get('code'), 'NO_COMPANY_PROFILE')
        self.assertEqual(
            response.data.get('detail'),
            'No company profile found for this user account.'
        )

    def test_user_with_inactive_suspended_profile_returns_404_profile_inactive(self):
        """User with suspended profile receives HTTP 404 with code PROFILE_INACTIVE."""
        self.client.force_authenticate(user=self.suspended_user)
        response = self.client.get('/api/v1/csr/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get('code'), 'PROFILE_INACTIVE')
        self.assertEqual(
            response.data.get('detail'),
            'Company profile is inactive or unverified.'
        )

    def test_user_with_explicit_is_active_false_returns_404_profile_inactive(self):
        """User with is_active=False on company profile receives HTTP 404 with code PROFILE_INACTIVE."""
        self.active_company.is_active = False
        try:
            self.client.force_authenticate(user=self.active_user)
            response = self.client.get('/api/v1/csr/dashboard/')

            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response.data.get('code'), 'PROFILE_INACTIVE')
        finally:
            self.active_company.is_active = True

    def test_token_user_mismatch_role_donor_denied(self):
        """Authenticated DONOR token accessing CSR dashboard is denied with 403 Forbidden."""
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get('/api/v1/csr/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Access restricted to authenticated corporate users", response.data.get('detail', ''))

    def test_token_user_mismatch_role_ngo_denied(self):
        """Authenticated NGO token accessing CSR dashboard is denied with 403 Forbidden."""
        self.client.force_authenticate(user=self.ngo_user)
        response = self.client.get('/api/v1/csr/dashboard/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Access restricted to authenticated corporate users", response.data.get('detail', ''))

    def test_unauthenticated_request_denied(self):
        """Unauthenticated request to CSR dashboard is rejected with 401 Unauthorized."""
        response = self.client.get('/api/v1/csr/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_management_command_links_profile_idempotently(self):
        """Management command creates profile when missing, and updates safely when existing."""
        test_email = "new_command_user@example.com"
        out = StringIO()

        # 1. First run creates user & profile
        call_command('link_csr_profile', email=test_email, company_name="Command Created Corp", stdout=out)
        output1 = out.getvalue()
        self.assertIn("Successfully created and linked CompanyProfile", output1)

        user = User.objects.get(email=test_email)
        self.assertEqual(user.role, User.Role.COMPANY)
        self.assertTrue(CompanyProfile.objects.filter(user=user).exists())
        profile = CompanyProfile.objects.get(user=user)
        self.assertEqual(profile.company_name, "Command Created Corp")
        self.assertEqual(profile.verification_status, "APPROVED")

        # 2. Second run is idempotent
        out2 = StringIO()
        call_command('link_csr_profile', email=test_email, company_name="Command Updated Corp", stdout=out2)
        output2 = out2.getvalue()
        self.assertIn("CompanyProfile already linked", output2)

        profile.refresh_from_db()
        self.assertEqual(profile.company_name, "Command Updated Corp")
