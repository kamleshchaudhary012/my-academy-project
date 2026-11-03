"""
CSR E2E Security Test Suite — Phase CSR-2.10
============================================
Cross-role isolation, IDOR, approval enforcement, and boundary attack
scenarios across the full CSR Connect module.

Test Classes:
  A. CompanyCrossTenantE2ETests
  B. NgoCrossTenantE2ETests
  C. UnapprovedNgoE2ETests
  D. UnverifiedCompanyE2ETests
  E. AdminBoundaryE2ETests
  F. RoleEscalationE2ETests
  G. VerificationSpoofingE2ETests
  H. NotificationIsolationE2ETests

Design:
- Each class uses isolated setUpTestData with its own users/profiles.
- All uploads use make_dummy_uploaded_file.
- No real emails (locmem backend via override_settings).
- No PAN numbers asserted in emails.
- No production code changes.
"""

from decimal import Decimal
from datetime import date, timedelta

from django.core import mail
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework import status as http_status

from ngo.models import NGOProfile
from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRPartnership,
    CSRPartnershipStatus,
    PartnershipMilestone,
    MilestoneStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CSRSupportType,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_partnership_milestone,
    make_dummy_uploaded_file,
)

User = get_user_model()


# ===========================================================================
# A. Company Cross-Tenant Isolation
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CompanyCrossTenantE2ETests(APITestCase):
    """Company B cannot access Company A's resources."""

    @classmethod
    def setUpTestData(cls):
        cls.user_a = make_user(email='sec_co_a@alpha.com', role=User.Role.COMPANY)
        cls.company_a = make_company_profile(
            user=cls.user_a, verification_status=CompanyVerificationStatus.APPROVED)

        cls.user_b = make_user(email='sec_co_b@beta.com', role=User.Role.COMPANY)
        cls.company_b = make_company_profile(
            user=cls.user_b, verification_status=CompanyVerificationStatus.APPROVED)

        cls.ngo_user = make_user(email='sec_ngo_shared@example.org', role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user)

        cls.req = make_csr_requirement(
            ngo=cls.ngo, status=CSRRequirementStatus.OPEN_FOR_CSR)

        cls.sr_a = make_csr_support_request(
            company=cls.company_a, requirement=cls.req,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW)

        cls.partnership_a = make_csr_partnership(
            company=cls.company_a, ngo=cls.ngo, requirement=cls.req,
            support_request=cls.sr_a, status=CSRPartnershipStatus.ACTIVE)

        cls.milestone_a = make_partnership_milestone(
            partnership=cls.partnership_a, sequence_number=1,
            status=MilestoneStatus.SUBMITTED)

    def setUp(self):
        mail.outbox.clear()

    def test_company_b_cannot_view_company_a_support_request(self):
        """Company B accessing Company A's EOI detail receives 404."""
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.get(f'/api/v1/csr/support-requests/{self.sr_a.id}/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_company_b_cannot_withdraw_company_a_eoi(self):
        """Company B cannot withdraw Company A's EOI."""
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.post(f'/api/v1/csr/support-requests/{self.sr_a.id}/withdraw/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_company_b_cannot_view_company_a_partnership(self):
        """Company B accessing Company A's partnership receives 404."""
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.get(f'/api/v1/csr/partnerships/{self.partnership_a.id}/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_company_b_cannot_upload_mou_on_company_a_partnership(self):
        """Company B cannot upload MoU on Company A's partnership."""
        self.client.force_authenticate(user=self.user_b)
        doc = make_dummy_uploaded_file()
        resp = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/upload-mou/',
            {'mou_document': doc}, format='multipart',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_company_b_cannot_report_disbursement_on_company_a_partnership(self):
        """Company B cannot report disbursement on Company A's partnership."""
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/report-disbursement/',
            {'amount': '100000.00'}, format='json',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_company_b_cannot_review_milestone_on_company_a_partnership(self):
        """Company B cannot review a milestone on Company A's partnership."""
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/{self.milestone_a.id}/review/',
            {'status': MilestoneStatus.VERIFIED, 'review_notes': 'Attacker approval'},
            format='json',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])
        # Milestone must remain SUBMITTED
        self.milestone_a.refresh_from_db()
        self.assertEqual(self.milestone_a.status, MilestoneStatus.SUBMITTED)

    def test_company_b_cannot_view_company_a_milestones(self):
        """Company B cannot list milestones from Company A's partnership."""
        self.client.force_authenticate(user=self.user_b)
        resp = self.client.get(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])


# ===========================================================================
# B. NGO Cross-Tenant Isolation
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NgoCrossTenantE2ETests(APITestCase):
    """NGO B cannot access NGO A's resources."""

    @classmethod
    def setUpTestData(cls):
        cls.ngo_user_a = make_user(email='sec_ngo_a@alpha.org', role=User.Role.NGO)
        cls.ngo_a = make_ngo_profile(user=cls.ngo_user_a)

        cls.ngo_user_b = make_user(email='sec_ngo_b@beta.org', role=User.Role.NGO)
        cls.ngo_b = make_ngo_profile(user=cls.ngo_user_b)

        cls.company_user = make_user(email='sec_co@gamma.com', role=User.Role.COMPANY)
        cls.company = make_company_profile(
            user=cls.company_user, verification_status=CompanyVerificationStatus.APPROVED)

        cls.req_a = make_csr_requirement(
            ngo=cls.ngo_a, status=CSRRequirementStatus.DRAFT)

        cls.sr_a = make_csr_support_request(
            company=cls.company, requirement=cls.req_a,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW)

        cls.partnership_a = make_csr_partnership(
            company=cls.company, ngo=cls.ngo_a, requirement=cls.req_a,
            support_request=cls.sr_a, status=CSRPartnershipStatus.ACTIVE)

        cls.milestone_a = make_partnership_milestone(
            partnership=cls.partnership_a, sequence_number=1,
            status=MilestoneStatus.PENDING)

    def setUp(self):
        mail.outbox.clear()

    def test_ngo_b_cannot_view_ngo_a_requirement(self):
        """NGO B receives 404 on NGO A's requirement detail."""
        self.client.force_authenticate(user=self.ngo_user_b)
        resp = self.client.get(f'/api/v1/ngo/csr/requirements/{self.req_a.id}/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_ngo_b_cannot_update_ngo_a_requirement(self):
        """NGO B cannot PUT update NGO A's requirement."""
        self.client.force_authenticate(user=self.ngo_user_b)
        resp = self.client.put(
            f'/api/v1/ngo/csr/requirements/{self.req_a.id}/',
            {'title': 'Attacker hijack'}, format='json',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_ngo_b_cannot_delete_ngo_a_requirement(self):
        """NGO B cannot DELETE NGO A's requirement."""
        self.client.force_authenticate(user=self.ngo_user_b)
        resp = self.client.delete(f'/api/v1/ngo/csr/requirements/{self.req_a.id}/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND,
                       http_status.HTTP_405_METHOD_NOT_ALLOWED])

    def test_ngo_b_cannot_accept_ngo_a_incoming_eoi(self):
        """NGO B cannot accept an EOI addressed to NGO A."""
        self.client.force_authenticate(user=self.ngo_user_b)
        resp = self.client.post(
            f'/api/v1/ngo/csr/support-requests/{self.sr_a.id}/accept/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])
        self.sr_a.refresh_from_db()
        self.assertEqual(self.sr_a.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)

    def test_ngo_b_cannot_submit_evidence_on_ngo_a_milestone(self):
        """NGO B cannot submit evidence on a milestone belonging to NGO A's partnership."""
        self.client.force_authenticate(user=self.ngo_user_b)
        doc = make_dummy_uploaded_file()
        resp = self.client.post(
            f'/api/v1/ngo/csr/partnerships/{self.partnership_a.id}/milestones/'
            f'{self.milestone_a.id}/submit-evidence/',
            {'evidence_document': doc, 'completion_percentage': 100},
            format='multipart',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])
        self.milestone_a.refresh_from_db()
        self.assertEqual(self.milestone_a.status, MilestoneStatus.PENDING)

    def test_ngo_b_cannot_view_ngo_a_partnership(self):
        """NGO B cannot see NGO A's partnership detail."""
        self.client.force_authenticate(user=self.ngo_user_b)
        resp = self.client.get(f'/api/v1/ngo/csr/partnerships/{self.partnership_a.id}/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])


# ===========================================================================
# C. Unapproved NGO Restrictions
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class UnapprovedNgoE2ETests(APITestCase):
    """NGOs not in APPROVED status are blocked from all NGO CSR endpoints."""

    @classmethod
    def setUpTestData(cls):
        # Draft NGO
        cls.draft_user = make_user(email='sec_ngo_draft@example.org', role=User.Role.NGO)
        cls.draft_ngo = make_ngo_profile(
            user=cls.draft_user, status=NGOProfile.Status.DRAFT, is_active=False)

        # Pending verification NGO
        cls.pending_user = make_user(email='sec_ngo_pending@example.org', role=User.Role.NGO)
        cls.pending_ngo = make_ngo_profile(
            user=cls.pending_user, status=NGOProfile.Status.UNDER_REVIEW, is_active=False)

        # Rejected NGO
        cls.rejected_user = make_user(email='sec_ngo_rejected@example.org', role=User.Role.NGO)
        cls.rejected_ngo = make_ngo_profile(
            user=cls.rejected_user, status=NGOProfile.Status.REJECTED, is_active=False)

        # Suspended NGO
        cls.suspended_user = make_user(email='sec_ngo_suspended@example.org', role=User.Role.NGO)
        cls.suspended_ngo = make_ngo_profile(
            user=cls.suspended_user, status=NGOProfile.Status.SUSPENDED, is_active=False)

        # Approved NGO (control — should succeed on dashboard)
        cls.approved_user = make_user(email='sec_ngo_approved@example.org', role=User.Role.NGO)
        cls.approved_ngo = make_ngo_profile(
            user=cls.approved_user, status=NGOProfile.Status.APPROVED, is_active=True)

    def setUp(self):
        mail.outbox.clear()

    def _assert_ngo_endpoint_blocked(self, user, url, method='get', expected_codes=None):
        if expected_codes is None:
            expected_codes = [http_status.HTTP_403_FORBIDDEN]
        self.client.force_authenticate(user=user)
        resp = getattr(self.client, method)(url)
        self.assertIn(resp.status_code, expected_codes,
                      f"Expected {expected_codes} for {user.email} on {url}, got {resp.status_code}")

    def test_draft_ngo_blocked_from_requirements_list(self):
        self._assert_ngo_endpoint_blocked(self.draft_user, '/api/v1/ngo/csr/requirements/')

    def test_draft_ngo_blocked_from_dashboard(self):
        self._assert_ngo_endpoint_blocked(self.draft_user, '/api/v1/ngo/csr/dashboard/')

    def test_draft_ngo_blocked_from_support_requests(self):
        self._assert_ngo_endpoint_blocked(self.draft_user, '/api/v1/ngo/csr/support-requests/')

    def test_draft_ngo_blocked_from_partnerships(self):
        self._assert_ngo_endpoint_blocked(self.draft_user, '/api/v1/ngo/csr/partnerships/')

    def test_pending_ngo_blocked_from_requirements_list(self):
        self._assert_ngo_endpoint_blocked(self.pending_user, '/api/v1/ngo/csr/requirements/')

    def test_pending_ngo_blocked_from_dashboard(self):
        self._assert_ngo_endpoint_blocked(self.pending_user, '/api/v1/ngo/csr/dashboard/')

    def test_rejected_ngo_blocked_from_requirements_list(self):
        self._assert_ngo_endpoint_blocked(self.rejected_user, '/api/v1/ngo/csr/requirements/')

    def test_rejected_ngo_blocked_from_support_requests(self):
        self._assert_ngo_endpoint_blocked(self.rejected_user, '/api/v1/ngo/csr/support-requests/')

    def test_suspended_ngo_blocked_from_requirements_list(self):
        self._assert_ngo_endpoint_blocked(self.suspended_user, '/api/v1/ngo/csr/requirements/')

    def test_suspended_ngo_blocked_from_partnerships(self):
        self._assert_ngo_endpoint_blocked(self.suspended_user, '/api/v1/ngo/csr/partnerships/')

    def test_approved_ngo_can_access_dashboard(self):
        """Approved NGO can access NGO CSR dashboard."""
        self.client.force_authenticate(user=self.approved_user)
        resp = self.client.get('/api/v1/ngo/csr/dashboard/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"Approved NGO should access dashboard. Got: {resp.status_code}")

    def test_approved_ngo_can_list_requirements(self):
        """Approved NGO can list their requirements."""
        self.client.force_authenticate(user=self.approved_user)
        resp = self.client.get('/api/v1/ngo/csr/requirements/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)


# ===========================================================================
# D. Unverified Company Restrictions
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class UnverifiedCompanyE2ETests(APITestCase):
    """Companies not in APPROVED status are blocked from sending EOIs."""

    @classmethod
    def setUpTestData(cls):
        # NGO for EOI attempts
        cls.ngo_user = make_user(email='sec_co_d_ngo@example.org', role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user)
        cls.req = make_csr_requirement(ngo=cls.ngo, status=CSRRequirementStatus.OPEN_FOR_CSR)

        # DRAFT company
        cls.draft_user = make_user(email='sec_co_draft@example.com', role=User.Role.COMPANY)
        cls.draft_company = make_company_profile(
            user=cls.draft_user, verification_status=CompanyVerificationStatus.DRAFT)

        # PENDING_VERIFICATION company
        cls.pending_user = make_user(email='sec_co_pending@example.com', role=User.Role.COMPANY)
        cls.pending_company = make_company_profile(
            user=cls.pending_user,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION)

        # REJECTED company
        cls.rejected_user = make_user(email='sec_co_rejected@example.com', role=User.Role.COMPANY)
        cls.rejected_company = make_company_profile(
            user=cls.rejected_user, verification_status=CompanyVerificationStatus.REJECTED)

        # SUSPENDED company
        cls.suspended_user = make_user(email='sec_co_suspended@example.com', role=User.Role.COMPANY)
        cls.suspended_company = make_company_profile(
            user=cls.suspended_user, verification_status=CompanyVerificationStatus.SUSPENDED)

        # APPROVED company (control)
        cls.approved_user = make_user(email='sec_co_approved@example.com', role=User.Role.COMPANY)
        cls.approved_company = make_company_profile(
            user=cls.approved_user, verification_status=CompanyVerificationStatus.APPROVED)

    def setUp(self):
        mail.outbox.clear()

    def _try_send_eoi(self, user, req_id):
        self.client.force_authenticate(user=user)
        return self.client.post(
            '/api/v1/csr/support-requests/',
            {
                'requirement': str(req_id),
                'spoc_name': 'Test SPOC',
                'spoc_email': 'test@example.com',
                'spoc_phone': '+919876543210',
                'proposed_funding': '100000.00',
                'support_type': CSRSupportType.FINANCIAL_GRANT,
                'message': 'Test EOI from unverified company.',
            },
            format='json',
        )

    def test_draft_company_cannot_send_eoi(self):
        resp = self._try_send_eoi(self.draft_user, self.req.id)
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_400_BAD_REQUEST])

    def test_pending_company_cannot_send_eoi(self):
        resp = self._try_send_eoi(self.pending_user, self.req.id)
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_400_BAD_REQUEST])

    def test_rejected_company_cannot_send_eoi(self):
        resp = self._try_send_eoi(self.rejected_user, self.req.id)
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_400_BAD_REQUEST])

    def test_suspended_company_cannot_send_eoi(self):
        resp = self._try_send_eoi(self.suspended_user, self.req.id)
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_400_BAD_REQUEST])

    def test_draft_company_can_access_own_profile(self):
        """DRAFT company CAN still GET their own profile (IsCompanyUser, not IsApprovedCompany)."""
        self.client.force_authenticate(user=self.draft_user)
        resp = self.client.get('/api/v1/csr/profile/me/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         "DRAFT company must be able to read own profile")

    def test_approved_company_can_send_eoi(self):
        """Approved company CAN send EOI."""
        resp = self._try_send_eoi(self.approved_user, self.req.id)
        self.assertIn(resp.status_code,
                      [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"Approved company EOI failed: {resp.data}")


# ===========================================================================
# E. Admin Boundary Tests
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminBoundaryE2ETests(APITestCase):
    """Only ADMIN users can access admin CSR endpoints."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = make_user(email='sec_admin_e@daangives.org', role=User.Role.ADMIN)
        cls.donor_user = make_user(email='sec_donor_e@example.com', role=User.Role.DONOR)
        cls.ngo_user = make_user(email='sec_ngo_e@example.org', role=User.Role.NGO)
        cls.company_user = make_user(email='sec_co_e@example.com', role=User.Role.COMPANY)
        cls.ngo = make_ngo_profile(user=cls.ngo_user)
        cls.company = make_company_profile(
            user=cls.company_user, verification_status=CompanyVerificationStatus.APPROVED)

        cls.admin_endpoints = [
            '/api/v1/admin/csr/companies/',
            '/api/v1/admin/csr/requirements/',
            '/api/v1/admin/csr/partnerships/',
            '/api/v1/admin/csr/analytics/',
            '/api/v1/admin/csr/audit-history/',
        ]

    def setUp(self):
        mail.outbox.clear()

    def test_anonymous_gets_401_on_admin_endpoints(self):
        for url in self.admin_endpoints:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED,
                             f"Anonymous should get 401 on {url}, got {resp.status_code}")

    def test_donor_gets_403_on_admin_endpoints(self):
        self.client.force_authenticate(user=self.donor_user)
        for url in self.admin_endpoints:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN,
                             f"Donor should get 403 on {url}, got {resp.status_code}")

    def test_ngo_gets_403_on_admin_endpoints(self):
        self.client.force_authenticate(user=self.ngo_user)
        for url in self.admin_endpoints:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN,
                             f"NGO should get 403 on {url}, got {resp.status_code}")

    def test_company_gets_403_on_admin_endpoints(self):
        self.client.force_authenticate(user=self.company_user)
        for url in self.admin_endpoints:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN,
                             f"Company should get 403 on {url}, got {resp.status_code}")

    def test_admin_gets_200_on_admin_endpoints(self):
        self.client.force_authenticate(user=self.admin_user)
        for url in self.admin_endpoints:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                             f"Admin should get 200 on {url}, got {resp.status_code}")


# ===========================================================================
# F. Role Escalation Tests
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RoleEscalationE2ETests(APITestCase):
    """Companies cannot POST to NGO namespace; NGOs cannot POST to Company namespace."""

    @classmethod
    def setUpTestData(cls):
        cls.company_user = make_user(email='sec_esc_co@example.com', role=User.Role.COMPANY)
        cls.company = make_company_profile(
            user=cls.company_user, verification_status=CompanyVerificationStatus.APPROVED)

        cls.ngo_user = make_user(email='sec_esc_ngo@example.org', role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user)

        cls.req = make_csr_requirement(ngo=cls.ngo, status=CSRRequirementStatus.DRAFT)

    def setUp(self):
        mail.outbox.clear()

    def test_company_cannot_create_ngo_requirement(self):
        """Company user cannot POST to NGO requirements endpoint."""
        self.client.force_authenticate(user=self.company_user)
        resp = self.client.post('/api/v1/ngo/csr/requirements/', {
            'title': 'Escalation Attempt',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
        }, format='json')
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN,
                         f"Company should be 403 on NGO requirements. Got: {resp.status_code}")

    def test_company_cannot_submit_ngo_requirement(self):
        """Company user cannot POST to NGO requirement submit endpoint."""
        self.client.force_authenticate(user=self.company_user)
        resp = self.client.post(f'/api/v1/ngo/csr/requirements/{self.req.id}/submit/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_company_cannot_accept_eoi_via_ngo_namespace(self):
        """Company user cannot call NGO accept endpoint."""
        sr = make_csr_support_request(
            company=self.company, requirement=self.req,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW)
        self.client.force_authenticate(user=self.company_user)
        resp = self.client.post(f'/api/v1/ngo/csr/support-requests/{sr.id}/accept/')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_ngo_cannot_send_eoi_via_company_namespace(self):
        """NGO user cannot POST to Company support-requests endpoint."""
        self.client.force_authenticate(user=self.ngo_user)
        resp = self.client.post('/api/v1/csr/support-requests/', {
            'requirement': str(self.req.id),
            'proposed_funding': '100000.00',
        }, format='json')
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN,
                         f"NGO should be 403 on company EOI endpoint. Got: {resp.status_code}")

    def test_ngo_cannot_upload_mou_via_company_namespace(self):
        """NGO user cannot POST to Company upload-mou endpoint."""
        sr = make_csr_support_request(
            company=self.company, requirement=self.req,
            status=CSRSupportRequestStatus.ACCEPTED)
        partnership = make_csr_partnership(
            company=self.company, ngo=self.ngo, requirement=self.req,
            support_request=sr, status=CSRPartnershipStatus.PENDING_MOU)
        self.client.force_authenticate(user=self.ngo_user)
        doc = make_dummy_uploaded_file()
        resp = self.client.post(
            f'/api/v1/csr/partnerships/{partnership.id}/upload-mou/',
            {'mou_document': doc}, format='multipart',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])

    def test_ngo_cannot_review_milestone_via_company_namespace(self):
        """NGO user cannot call company milestone review endpoint."""
        sr = make_csr_support_request(
            company=self.company, requirement=self.req,
            status=CSRSupportRequestStatus.ACCEPTED)
        partnership = make_csr_partnership(
            company=self.company, ngo=self.ngo, requirement=self.req,
            support_request=sr, status=CSRPartnershipStatus.ACTIVE)
        milestone = make_partnership_milestone(
            partnership=partnership, sequence_number=1, status=MilestoneStatus.SUBMITTED)
        self.client.force_authenticate(user=self.ngo_user)
        resp = self.client.post(
            f'/api/v1/csr/partnerships/{partnership.id}/milestones/{milestone.id}/review/',
            {'status': MilestoneStatus.VERIFIED}, format='json',
        )
        self.assertIn(resp.status_code,
                      [http_status.HTTP_403_FORBIDDEN, http_status.HTTP_404_NOT_FOUND])
        milestone.refresh_from_db()
        self.assertEqual(milestone.status, MilestoneStatus.SUBMITTED)


# ===========================================================================
# G. Verification Spoofing Tests
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class VerificationSpoofingE2ETests(APITestCase):
    """Users cannot escalate their own verification status via payload fields."""

    @classmethod
    def setUpTestData(cls):
        cls.company_user = make_user(email='sec_spoof_co@example.com', role=User.Role.COMPANY)
        cls.company = make_company_profile(
            user=cls.company_user, verification_status=CompanyVerificationStatus.DRAFT)

        cls.ngo_user = make_user(email='sec_spoof_ngo@example.org', role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user, status=NGOProfile.Status.DRAFT)

    def setUp(self):
        mail.outbox.clear()

    def test_company_cannot_self_approve_via_patch_payload(self):
        """PATCH/PUT to profile/me/ with verification_status=APPROVED is ignored by server."""
        self.client.force_authenticate(user=self.company_user)
        resp = self.client.patch(
            '/api/v1/csr/profile/me/',
            {'verification_status': CompanyVerificationStatus.APPROVED,
             'city': 'Mumbai'},
            format='json',
        )
        # Either the field is stripped (200/201) or rejected (400); never upgrades status
        if resp.status_code in [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED]:
            self.company.refresh_from_db()
            self.assertNotEqual(
                self.company.verification_status, CompanyVerificationStatus.APPROVED,
                "Verification status must not be changed to APPROVED via self-service PATCH",
            )

    def test_company_cannot_self_approve_via_post_payload(self):
        """POST to profile/me/ with verification_status=APPROVED in body is stripped."""
        self.client.force_authenticate(user=self.company_user)
        # This is an upsert endpoint — verification_status should not be writable
        resp = self.client.post(
            '/api/v1/csr/profile/me/',
            {
                'company_name': 'Spoof Corp',
                'legal_name': 'Spoof Corp Pvt Ltd',
                'cin_number': 'L12345MH2020PLC099999',
                'pan_number': 'AAACS9999S',
                'contact_person_name': 'Spoofer',
                'contact_person_designation': 'Hacker',
                'contact_email': 'spoof@corp.com',
                'contact_phone': '+919000000000',
                'registered_address': '1 Attacker Lane',
                'city': 'Delhi',
                'state': 'Delhi',
                'pincode': '110001',
                'annual_csr_budget': '9999999.00',
                'verification_status': CompanyVerificationStatus.APPROVED,
            },
            format='json',
        )
        if resp.status_code in [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED]:
            # Check status — must remain DRAFT
            resp2 = self.client.get('/api/v1/csr/profile/me/')
            self.assertEqual(resp2.data.get('verification_status'), 'DRAFT',
                             "Server must ignore verification_status in POST payload")

    def test_ngo_cannot_spoof_requirement_status_to_open(self):
        """NGO cannot set requirement status to OPEN_FOR_CSR via PUT body."""
        self.client.force_authenticate(user=self.ngo_user)
        req = make_csr_requirement(ngo=self.ngo, status=CSRRequirementStatus.DRAFT)
        resp = self.client.put(
            f'/api/v1/ngo/csr/requirements/{req.id}/',
            {
                'title': 'Spoofed Requirement',
                'status': CSRRequirementStatus.OPEN_FOR_CSR,
                'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
                'state': 'Maharashtra',
                'district': 'Pune',
                'location_scope': LocationScope.SPECIFIC_DISTRICT,
                'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
                'target_beneficiary_count': 100,
                'summary': 'Spoof.',
                'detailed_description': 'Spoof attempt.',
                'expected_outcomes': 'Spoof outcomes.',
                'total_estimated_budget': '100000.00',
                'required_csr_funding': '80000.00',
                'committed_funding': '20000.00',
                'start_date': str(date.today()),
                'expected_completion_date': str(date.today() + timedelta(days=90)),
            },
            format='json',
        )
        if resp.status_code in [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED]:
            req.refresh_from_db()
            self.assertNotEqual(req.status, CSRRequirementStatus.OPEN_FOR_CSR,
                                "NGO must not be able to set status to OPEN_FOR_CSR via PUT")


# ===========================================================================
# H. Notification Isolation Tests
# ===========================================================================

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotificationIsolationE2ETests(APITestCase):
    """Notifications must be tenant-isolated and PAN-free."""

    @classmethod
    def setUpTestData(cls):
        # Tenant A
        cls.ngo_user_a = make_user(email='sec_notif_ngo_a@example.org', role=User.Role.NGO)
        cls.ngo_a = make_ngo_profile(user=cls.ngo_user_a)

        cls.co_user_a = make_user(email='sec_notif_co_a@example.com', role=User.Role.COMPANY)
        cls.company_a = make_company_profile(
            user=cls.co_user_a,
            pan_number='AAACN1234A',
            verification_status=CompanyVerificationStatus.APPROVED)

        cls.req_a = make_csr_requirement(ngo=cls.ngo_a, status=CSRRequirementStatus.OPEN_FOR_CSR)

        # Tenant B
        cls.ngo_user_b = make_user(email='sec_notif_ngo_b@example.org', role=User.Role.NGO)
        cls.ngo_b = make_ngo_profile(user=cls.ngo_user_b)

        cls.co_user_b = make_user(email='sec_notif_co_b@example.com', role=User.Role.COMPANY)
        cls.company_b = make_company_profile(
            user=cls.co_user_b,
            pan_number='AAACN5678B',
            verification_status=CompanyVerificationStatus.APPROVED)

        cls.req_b = make_csr_requirement(ngo=cls.ngo_b, status=CSRRequirementStatus.OPEN_FOR_CSR)

    def setUp(self):
        mail.outbox.clear()

    def test_company_a_eoi_notifies_only_ngo_a_not_ngo_b(self):
        """When Company A sends EOI to NGO A's requirement, NGO B receives no notification."""
        self.client.force_authenticate(user=self.co_user_a)
        resp = self.client.post('/api/v1/csr/support-requests/', {
            'requirement': str(self.req_a.id),
            'spoc_name': 'A SPOC',
            'spoc_email': 'a@example.com',
            'spoc_phone': '+919000000001',
            'proposed_funding': '100000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'message': 'Tenant A EOI.',
        }, format='json')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED])

        # No email should be addressed to NGO B
        for m in mail.outbox:
            self.assertNotIn(self.ngo_user_b.email, m.to,
                             f"NGO B email {self.ngo_user_b.email} should not receive notification "
                             f"for NGO A's EOI. Found in: {m.to}")

    def test_no_pan_in_any_notification_email(self):
        """PAN numbers of any tenant must never appear in email bodies."""
        self.client.force_authenticate(user=self.co_user_b)
        resp = self.client.post('/api/v1/csr/support-requests/', {
            'requirement': str(self.req_b.id),
            'spoc_name': 'B SPOC',
            'spoc_email': 'b@example.com',
            'spoc_phone': '+919000000002',
            'proposed_funding': '200000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'message': 'Tenant B EOI.',
        }, format='json')
        self.assertIn(resp.status_code,
                      [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED])

        for m in mail.outbox:
            self.assertNotIn('AAACN1234A', m.body,
                             "PAN of Company A must not appear in any notification")
            self.assertNotIn('AAACN5678B', m.body,
                             "PAN of Company B must not appear in any notification")

    def test_no_duplicate_notification_on_resubmission(self):
        """
        If a company tries to submit a second EOI for the same requirement
        (if the API prevents duplicates), no spurious extra notification fires.
        """
        self.client.force_authenticate(user=self.co_user_a)
        eoi_payload = {
            'requirement': str(self.req_a.id),
            'spoc_name': 'A SPOC',
            'spoc_email': 'a@example.com',
            'spoc_phone': '+919000000001',
            'proposed_funding': '100000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'message': 'First submission.',
        }
        resp1 = self.client.post('/api/v1/csr/support-requests/', eoi_payload, format='json')
        first_count = len(mail.outbox)

        # Second identical submission — should either 400 (duplicate blocked)
        # or 201 (allowed, 1 more email). Either way, no > 2 emails per action.
        resp2 = self.client.post('/api/v1/csr/support-requests/', eoi_payload, format='json')
        second_count = len(mail.outbox)

        if resp2.status_code in [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED]:
            # One additional notification at most for each new EOI
            self.assertLessEqual(
                second_count - first_count, 2,
                "No more than 2 notification emails should fire per EOI submission",
            )
        else:
            # Blocked — outbox should not grow
            self.assertEqual(
                second_count, first_count,
                "Blocked EOI must not trigger additional notifications",
            )
