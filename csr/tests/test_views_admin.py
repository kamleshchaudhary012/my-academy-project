"""
CSR Admin API Views Test Suite — Phase CSR-2.8.3
=================================================
Tests all 13 ADMIN namespace endpoints for the CSR Connect module (#37 - #49).
Verifies:
1. Strict RBAC & Tenant Security (Admin-only access, 401/403 for non-admins).
2. Corporate verification queues, detail retrieval, approval, rejection, and suspension.
3. NGO CSR requirement moderation queues, detail, approval (OPEN_FOR_CSR), rejection, and suspension.
4. Platform-wide partnership monitoring and milestone visibility.
5. Immutable audit ledger history querying and filtering.
6. Aggregated CSR platform analytics DTO calculation.
7. Asynchronous transactional notification hooks and email dispatching.
"""

import uuid
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core import mail
from rest_framework import status
from rest_framework.test import APIClient

from users.models import User
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
    CSRVerificationHistory,
    CSRAuditEntityType,
    ScheduleVIICategory,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_partnership_milestone,
    make_verification_history,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminAuthenticationAndRBACSecurityTests(TestCase):
    """Verifies that all 13 Admin endpoints strictly enforce IsCSRAdminUser RBAC."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = make_user(email="csr_admin@daangives.org", role=User.Role.ADMIN)
        cls.donor_user = make_user(email="retail_donor@example.com", role=User.Role.DONOR)
        cls.company_user = make_user(email="corporate@tatasteel.com", role=User.Role.COMPANY)
        cls.company = make_company_profile(user=cls.company_user, verification_status=CompanyVerificationStatus.APPROVED)

        cls.ngo_user = make_user(email="lead@gramin.org", role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user, status=NGOProfile.Status.APPROVED, is_active=True)

        cls.unapproved_ngo_user = make_user(email="unapproved@ngo.org", role=User.Role.NGO)
        cls.unapproved_ngo = make_ngo_profile(user=cls.unapproved_ngo_user, status=NGOProfile.Status.DRAFT, is_active=False)

        # Create dummy resources for parameterized endpoint checks
        cls.sample_req = make_csr_requirement(ngo=cls.ngo, created_by=cls.ngo_user, status=CSRRequirementStatus.PENDING_REVIEW)
        cls.sample_partnership = make_csr_partnership(company=cls.company, ngo=cls.ngo, requirement=cls.sample_req)

    def setUp(self):
        self.client = APIClient()

    def test_unauthenticated_requests_receive_401(self):
        """Unauthenticated requests to any Admin endpoint receive 401 Unauthorized."""
        endpoints = [
            ("get", reverse('csr-admin-companies-list')),
            ("get", reverse('csr-admin-company-detail', kwargs={'id': self.company.id})),
            ("post", reverse('csr-admin-company-approve', kwargs={'id': self.company.id})),
            ("post", reverse('csr-admin-company-reject', kwargs={'id': self.company.id})),
            ("post", reverse('csr-admin-company-suspend', kwargs={'id': self.company.id})),
            ("get", reverse('csr-admin-requirements-list')),
            ("get", reverse('csr-admin-requirement-detail', kwargs={'id': self.sample_req.id})),
            ("post", reverse('csr-admin-requirement-approve', kwargs={'id': self.sample_req.id})),
            ("post", reverse('csr-admin-requirement-reject', kwargs={'id': self.sample_req.id})),
            ("post", reverse('csr-admin-requirement-suspend', kwargs={'id': self.sample_req.id})),
            ("get", reverse('csr-admin-partnerships-list')),
            ("get", reverse('csr-admin-audit-history')),
            ("get", reverse('csr-admin-analytics')),
        ]
        for method, url in endpoints:
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, f"Failed for {method.upper()} {url}")

    def test_non_admin_roles_receive_403(self):
        """DONOR, COMPANY, approved NGO, and unapproved NGO all receive 403 Forbidden."""
        forbidden_users = [
            self.donor_user,
            self.company_user,
            self.ngo_user,
            self.unapproved_ngo_user,
        ]
        test_urls = [
            ("get", reverse('csr-admin-companies-list')),
            ("get", reverse('csr-admin-requirements-list')),
            ("get", reverse('csr-admin-partnerships-list')),
            ("get", reverse('csr-admin-audit-history')),
            ("get", reverse('csr-admin-analytics')),
        ]
        for user in forbidden_users:
            self.client.force_authenticate(user=user)
            for method, url in test_urls:
                response = getattr(self.client, method)(url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"User {user.email} (role {user.role}) did not receive 403 on {url}",
                )

    def test_disallowed_http_methods_receive_405(self):
        """Action endpoints reject disallowed HTTP verbs with 405 Method Not Allowed."""
        self.client.force_authenticate(user=self.admin_user)
        # GET not allowed on approve/reject/suspend action endpoints
        disallowed = [
            reverse('csr-admin-company-approve', kwargs={'id': self.company.id}),
            reverse('csr-admin-company-reject', kwargs={'id': self.company.id}),
            reverse('csr-admin-company-suspend', kwargs={'id': self.company.id}),
            reverse('csr-admin-requirement-approve', kwargs={'id': self.sample_req.id}),
            reverse('csr-admin-requirement-reject', kwargs={'id': self.sample_req.id}),
            reverse('csr-admin-requirement-suspend', kwargs={'id': self.sample_req.id}),
        ]
        for url in disallowed:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED, f"Expected 405 for GET {url}")


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminCompanyModerationTests(TestCase):
    """Tests Endpoints #37, #38, #39, #40, #41 (Company Queue, Detail, Approve, Reject, Suspend)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = make_user(email="admin_moderator@daangives.org", role=User.Role.ADMIN)

        cls.c_pending_user = make_user(email="pending_comp@example.com", role=User.Role.COMPANY)
        cls.c_pending = make_company_profile(
            user=cls.c_pending_user,
            company_name="Pending Solutions Pvt Ltd",
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )

        cls.c_approved_user = make_user(email="approved_comp@example.com", role=User.Role.COMPANY)
        cls.c_approved = make_company_profile(
            user=cls.c_approved_user,
            company_name="Approved Industries Ltd",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        cls.c_rejected_user = make_user(email="rejected_comp@example.com", role=User.Role.COMPANY)
        cls.c_rejected = make_company_profile(
            user=cls.c_rejected_user,
            company_name="Rejected Ventures LLP",
            verification_status=CompanyVerificationStatus.REJECTED,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)
        mail.outbox.clear()

    def test_list_companies_pagination_and_all(self):
        """GET /api/v1/admin/csr/companies/ returns paginated corporate profiles."""
        url = reverse('csr-admin-companies-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('count', response.data)
        self.assertGreaterEqual(response.data['count'], 3)

    def test_filter_companies_by_status(self):
        """GET /api/v1/admin/csr/companies/?status=PENDING_VERIFICATION filters accurately."""
        url = reverse('csr-admin-companies-list')
        response = self.client.get(url, {'status': 'PENDING_VERIFICATION'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        statuses = [c['verification_status'] for c in response.data['results']]
        self.assertTrue(all(s == 'PENDING_VERIFICATION' for s in statuses))
        self.assertIn(str(self.c_pending.id), [c['id'] for c in response.data['results']])

    def test_search_companies_by_name_or_cin(self):
        """GET /api/v1/admin/csr/companies/?search=... matches company name or CIN."""
        url = reverse('csr-admin-companies-list')
        response = self.client.get(url, {'search': 'Pending Solutions'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['company_name'], "Pending Solutions Pvt Ltd")

    def test_ordering_companies(self):
        """GET /api/v1/admin/csr/companies/?ordering=company_name orders alphabetically."""
        url = reverse('csr-admin-companies-list')
        response = self.client.get(url, {'ordering': 'company_name'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [c['company_name'] for c in response.data['results']]
        self.assertEqual(names, sorted(names))

    def test_retrieve_company_detail_success(self):
        """GET /api/v1/admin/csr/companies/<uuid:id>/ returns full dossier with unmasked PAN."""
        url = reverse('csr-admin-company-detail', kwargs={'id': self.c_pending.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.c_pending.id))
        self.assertEqual(response.data['cin_number'], self.c_pending.cin_number)
        self.assertEqual(response.data['pan_number'], self.c_pending.pan_number)
        self.assertIn('user_email', response.data)

    def test_retrieve_company_detail_invalid_uuid(self):
        """GET /api/v1/admin/csr/companies/<non_existent_uuid>/ returns 404."""
        url = reverse('csr-admin-company-detail', kwargs={'id': uuid.uuid4()})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_approve_company_success_and_notification(self):
        """POST /api/v1/admin/csr/companies/<id>/approve/ approves profile and triggers email."""
        url = reverse('csr-admin-company-approve', kwargs={'id': self.c_pending.id})
        notes = "MCA Certificate and CIN verified on official portal."
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'notes': notes}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['verification_status'], 'APPROVED')

        self.c_pending.refresh_from_db()
        self.assertEqual(self.c_pending.verification_status, CompanyVerificationStatus.APPROVED)
        self.assertEqual(self.c_pending.verified_by, self.admin_user)

        # Audit ledger record created
        audit_entry = CSRVerificationHistory.objects.filter(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=self.c_pending.id,
            new_status=CompanyVerificationStatus.APPROVED,
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.reviewed_by, self.admin_user)

        # Notification email sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.c_pending.user.email, mail.outbox[0].to)
        self.assertIn("Company CSR Verification: APPROVED", mail.outbox[0].subject)

    def test_reject_company_success_and_notification(self):
        """POST /api/v1/admin/csr/companies/<id>/reject/ rejects profile with mandatory reason."""
        comp_user = make_user(email="reject_target@example.com", role=User.Role.COMPANY)
        comp = make_company_profile(user=comp_user, verification_status=CompanyVerificationStatus.PENDING_VERIFICATION)

        url = reverse('csr-admin-company-reject', kwargs={'id': comp.id})
        reason = "Invalid incorporation document provided."
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'reason': reason}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['verification_status'], 'REJECTED')

        comp.refresh_from_db()
        self.assertEqual(comp.verification_status, CompanyVerificationStatus.REJECTED)
        self.assertEqual(comp.rejection_reason, reason)

        # Notification email sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(comp.user.email, mail.outbox[0].to)
        self.assertIn("Company CSR Verification: REJECTED", mail.outbox[0].subject)

    def test_reject_company_missing_reason_returns_400(self):
        """POST /api/v1/admin/csr/companies/<id>/reject/ without reason returns 400."""
        url = reverse('csr-admin-company-reject', kwargs={'id': self.c_pending.id})
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'missing_rejection_reason')

    def test_suspend_company_success(self):
        """POST /api/v1/admin/csr/companies/<id>/suspend/ suspends active company."""
        url = reverse('csr-admin-company-suspend', kwargs={'id': self.c_approved.id})
        reason = "Non-compliance with statutory CSR guidelines."
        response = self.client.post(url, {'reason': reason}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['verification_status'], 'SUSPENDED')

        self.c_approved.refresh_from_db()
        self.assertEqual(self.c_approved.verification_status, CompanyVerificationStatus.SUSPENDED)
        self.assertEqual(self.c_approved.suspension_reason, reason)

        # No email sent on suspend per spec
        self.assertEqual(len(mail.outbox), 0)

    def test_suspend_company_missing_reason_returns_400(self):
        """POST /api/v1/admin/csr/companies/<id>/suspend/ without reason returns 400."""
        url = reverse('csr-admin-company-suspend', kwargs={'id': self.c_approved.id})
        response = self.client.post(url, {'reason': ''}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminRequirementModerationTests(TestCase):
    """Tests Endpoints #42, #43, #44, #45, #46 (Requirement Queue, Detail, Approve, Reject, Suspend)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = make_user(email="req_admin@daangives.org", role=User.Role.ADMIN)

        cls.ngo_user = make_user(email="project_head@sevatrust.org", role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user, legal_name="Seva Rural Trust", status=NGOProfile.Status.APPROVED, is_active=True)

        cls.req_pending = make_csr_requirement(
            ngo=cls.ngo,
            created_by=cls.ngo_user,
            title="Solar Micro-Grids in Bundelkhand",
            status=CSRRequirementStatus.PENDING_REVIEW,
            schedule_vii_category=ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY,
        )

        cls.req_approved = make_csr_requirement(
            ngo=cls.ngo,
            created_by=cls.ngo_user,
            title="Clean Water Project",
            status=CSRRequirementStatus.OPEN_FOR_CSR,
            schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER,
        )

        cls.req_draft = make_csr_requirement(
            ngo=cls.ngo,
            created_by=cls.ngo_user,
            title="Draft Mobile Clinic",
            status=CSRRequirementStatus.DRAFT,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)
        mail.outbox.clear()

    def test_list_requirements_pagination(self):
        """GET /api/v1/admin/csr/requirements/ returns paginated moderation queue."""
        url = reverse('csr-admin-requirements-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertGreaterEqual(response.data['count'], 2)

    def test_filter_requirements_by_status_and_category(self):
        """GET /api/v1/admin/csr/requirements/?status=PENDING_REVIEW filters accurately."""
        url = reverse('csr-admin-requirements-list')
        response = self.client.get(url, {
            'status': 'PENDING_REVIEW',
            'schedule_vii_category': 'ENVIRONMENTAL_SUSTAINABILITY',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], "Solar Micro-Grids in Bundelkhand")

    def test_search_requirements_by_title_or_ngo_name(self):
        """GET /api/v1/admin/csr/requirements/?search=... matches title or NGO."""
        url = reverse('csr-admin-requirements-list')
        response = self.client.get(url, {'search': 'Seva Rural'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)

    def test_retrieve_requirement_detail_success(self):
        """GET /api/v1/admin/csr/requirements/<uuid:id>/ returns full moderation dossier."""
        url = reverse('csr-admin-requirement-detail', kwargs={'id': self.req_pending.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.req_pending.id))
        self.assertEqual(response.data['ngo_legal_name'], "Seva Rural Trust")
        self.assertEqual(response.data['created_by_email'], self.ngo_user.email)

    def test_approve_requirement_success_and_notification(self):
        """POST /api/v1/admin/csr/requirements/<id>/approve/ sets OPEN_FOR_CSR and notifies NGO."""
        url = reverse('csr-admin-requirement-approve', kwargs={'id': self.req_pending.id})
        notes = "Budget sheet validated and Schedule VII alignment verified."
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'notes': notes}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'OPEN_FOR_CSR')

        self.req_pending.refresh_from_db()
        self.assertEqual(self.req_pending.status, CSRRequirementStatus.OPEN_FOR_CSR)
        self.assertEqual(self.req_pending.reviewed_by, self.admin_user)

        # Audit ledger record created
        audit_entry = CSRVerificationHistory.objects.filter(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=self.req_pending.id,
            new_status=CSRRequirementStatus.OPEN_FOR_CSR,
        ).first()
        self.assertIsNotNone(audit_entry)

        # Notification email dispatched
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.ngo.user.email, mail.outbox[0].to)
        self.assertIn("CSR Requirement Review: OPEN_FOR_CSR", mail.outbox[0].subject)

    def test_approve_requirement_invalid_state_returns_409(self):
        """POST approve on DRAFT requirement raises CSRStateError -> 409 Conflict."""
        url = reverse('csr-admin-requirement-approve', kwargs={'id': self.req_draft.id})
        response = self.client.post(url, {'notes': 'Premature approval'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Cannot approve requirement", response.data['detail'])

    def test_reject_requirement_success_and_notification(self):
        """POST /api/v1/admin/csr/requirements/<id>/reject/ rejects proposal and notifies NGO."""
        req_to_reject = make_csr_requirement(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title="Proposal with Flawed Budget",
            status=CSRRequirementStatus.PENDING_REVIEW,
        )
        url = reverse('csr-admin-requirement-reject', kwargs={'id': req_to_reject.id})
        reason = "Administrative cost exceeds 5% statutory threshold."
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'reason': reason}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'REJECTED')

        req_to_reject.refresh_from_db()
        self.assertEqual(req_to_reject.status, CSRRequirementStatus.REJECTED)
        self.assertEqual(req_to_reject.rejection_reason, reason)

        # Notification email sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.ngo.user.email, mail.outbox[0].to)
        self.assertIn("CSR Requirement Review: REJECTED", mail.outbox[0].subject)

    def test_reject_requirement_missing_reason_returns_400(self):
        """POST /api/v1/admin/csr/requirements/<id>/reject/ without reason returns 400."""
        url = reverse('csr-admin-requirement-reject', kwargs={'id': self.req_pending.id})
        response = self.client.post(url, {'reason': '   '}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suspend_requirement_success(self):
        """POST /api/v1/admin/csr/requirements/<id>/suspend/ suspends active proposal."""
        url = reverse('csr-admin-requirement-suspend', kwargs={'id': self.req_approved.id})
        reason = "NGO compliance renewal pending."
        response = self.client.post(url, {'reason': reason}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'SUSPENDED')

        self.req_approved.refresh_from_db()
        self.assertEqual(self.req_approved.status, CSRRequirementStatus.SUSPENDED)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminPartnershipAuditAnalyticsTests(TestCase):
    """Tests Endpoints #47, #48, #49 (Partnerships List, Audit History, Analytics)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = make_user(email="csr_super_admin@daangives.org", role=User.Role.ADMIN)

        cls.comp_user = make_user(email="corp_partner@reliance.com", role=User.Role.COMPANY)
        cls.comp = make_company_profile(user=cls.comp_user, company_name="Reliance CSR Foundation", verification_status=CompanyVerificationStatus.APPROVED)

        cls.ngo_user = make_user(email="lead@pratham.org", role=User.Role.NGO)
        cls.ngo = make_ngo_profile(user=cls.ngo_user, legal_name="Pratham Education Foundation", status=NGOProfile.Status.APPROVED, is_active=True)

        cls.req = make_csr_requirement(
            ngo=cls.ngo,
            created_by=cls.ngo_user,
            title="Read India Literacy Campaign",
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )

        cls.support_req = make_csr_support_request(
            company=cls.comp,
            requirement=cls.req,
            status=CSRSupportRequestStatus.ACCEPTED,
        )

        cls.partnership_active = make_csr_partnership(
            company=cls.comp,
            ngo=cls.ngo,
            requirement=cls.req,
            support_request=cls.support_req,
            agreed_funding_amount=Decimal('5000000.00'),
            disbursed_amount_reported=Decimal('2500000.00'),
            status=CSRPartnershipStatus.ACTIVE,
        )

        cls.milestone = make_partnership_milestone(
            partnership=cls.partnership_active,
            title="Phase 1: Tablet Procurement",
            status=MilestoneStatus.VERIFIED,
        )

        # Audit ledger entries
        cls.audit_entry_1 = make_verification_history(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=cls.comp.id,
            old_status=CompanyVerificationStatus.PENDING_VERIFICATION,
            new_status=CompanyVerificationStatus.APPROVED,
            reviewed_by=cls.admin_user,
            review_notes="Verified against MCA portal",
        )

        cls.audit_entry_2 = make_verification_history(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=cls.req.id,
            old_status=CSRRequirementStatus.PENDING_REVIEW,
            new_status=CSRRequirementStatus.OPEN_FOR_CSR,
            reviewed_by=cls.admin_user,
            review_notes="Approved proposal",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

    def test_list_partnerships_platform_wide(self):
        """GET /api/v1/admin/csr/partnerships/ returns all platform partnerships."""
        url = reverse('csr-admin-partnerships-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertGreaterEqual(response.data['count'], 1)
        p_data = response.data['results'][0]
        self.assertEqual(p_data['id'], str(self.partnership_active.id))
        self.assertIn('milestones', p_data)

    def test_filter_partnerships_by_status(self):
        """GET /api/v1/admin/csr/partnerships/?status=ACTIVE filters accurately."""
        url = reverse('csr-admin-partnerships-list')
        response = self.client.get(url, {'status': 'ACTIVE'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        response_empty = self.client.get(url, {'status': 'CANCELLED'})
        self.assertEqual(response_empty.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_empty.data['results']), 0)

    def test_list_audit_history_and_filters(self):
        """GET /api/v1/admin/csr/audit-history/ returns immutable audit entries."""
        url = reverse('csr-admin-audit-history')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['count'], 2)

        # Filter by entity_type=COMPANY
        response_comp = self.client.get(url, {'entity_type': 'COMPANY'})
        self.assertEqual(response_comp.status_code, status.HTTP_200_OK)
        self.assertTrue(all(e['entity_type'] == 'COMPANY' for e in response_comp.data['results']))

        # Filter by entity_id
        response_id = self.client.get(url, {'entity_id': str(self.comp.id)})
        self.assertEqual(response_id.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_id.data['results']), 1)
        self.assertEqual(response_id.data['results'][0]['entity_id'], str(self.comp.id))

    def test_get_csr_analytics_dto(self):
        """GET /api/v1/admin/csr/analytics/ returns correct aggregated metrics DTO."""
        url = reverse('csr-admin-analytics')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_keys = [
            "total_companies",
            "approved_companies",
            "pending_companies",
            "rejected_companies",
            "suspended_companies",
            "total_requirements",
            "open_requirements",
            "pending_requirements",
            "closed_requirements",
            "total_partnerships",
            "active_partnerships",
            "completed_partnerships",
            "total_committed_funding",
            "total_disbursed_reported",
        ]
        for key in expected_keys:
            self.assertIn(key, response.data, f"Missing key {key} in analytics DTO")

        self.assertIsInstance(response.data['total_companies'], int)
        self.assertIsInstance(response.data['total_requirements'], int)
        self.assertIsInstance(response.data['total_partnerships'], int)
        self.assertIsInstance(response.data['total_committed_funding'], str)
        self.assertIsInstance(response.data['total_disbursed_reported'], str)

        # Numerical integrity checks
        self.assertEqual(response.data['active_partnerships'], 1)
        self.assertEqual(response.data['total_committed_funding'], "5000000.00")
        self.assertEqual(response.data['total_disbursed_reported'], "2500000.00")
