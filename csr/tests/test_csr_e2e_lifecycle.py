"""
CSR E2E Lifecycle Test Suite — Phase CSR-2.10
==============================================
End-to-end happy-path validation of the COMPLETE CSR Connect lifecycle
across all four roles: ADMIN, COMPANY, NGO.

Covers steps A-N from the CSR-2.10 specification:
  A. Setup
  B. Company Onboarding (profile + verification doc)
  C. Admin Approves Company
  D. Company Sets Preferences
  E. NGO Creates Requirement
  F. Admin Approves Requirement
  G. Company Discovers & Sends EOI
  H. NGO Accepts EOI -> Partnership Created
  I. Company Uploads MoU
  J. Company Reports Disbursement
  K. NGO Creates Milestone
  L. NGO Submits Evidence
  M. Company Reviews Milestone
  N. Final Verification (Admin audit & analytics)

NOTE: All lifecycle steps are implemented as a SINGLE test method
(test_complete_csr_lifecycle) to ensure DB state persists across
all steps. Django's APITestCase wraps each test method in a separate
transaction that rolls back, so cross-method state sharing via class
attributes only works for Python objects, not DB records.
"""

from decimal import Decimal
from datetime import date, timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
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
from csr.tests.helpers import make_user, make_ngo_profile, make_dummy_uploaded_file

User = get_user_model()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CSRFullLifecycleE2ETest(APITestCase):
    """
    Full CSR Connect lifecycle end-to-end test.

    All steps A-N are executed sequentially in a SINGLE test method
    to maintain DB state across the lifecycle. The single method
    structure is required because APITestCase wraps each test method
    in a transaction that rolls back, which would destroy intermediate
    DB state needed by subsequent steps.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = make_user(
            email='e2e_admin@daangives.org',
            role=User.Role.ADMIN,
            full_name='DaanGives Admin',
        )
        cls.company_user = make_user(
            email='e2e_csr@infosys.com',
            role=User.Role.COMPANY,
            full_name='Infosys CSR Head',
        )
        cls.ngo_user = make_user(
            email='e2e_director@aidngo.org',
            role=User.Role.NGO,
            full_name='NGO Director',
        )
        cls.ngo_profile = make_ngo_profile(
            user=cls.ngo_user,
            legal_name='Aid For Education Trust',
            display_name='AidNGO',
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        cls.donor_user = make_user(email='e2e_donor@example.com', role=User.Role.DONOR)

    def setUp(self):
        mail.outbox.clear()

    def test_complete_csr_lifecycle(self):
        """
        Steps A–N: Full CSR Connect happy-path lifecycle.

        A. Setup (done in setUpTestData)
        B. Company Onboarding — profile POST (DRAFT) + verification doc upload
        C. Admin Approves Company — status → APPROVED
        D. Company Sets Preferences
        E. NGO Creates Requirement — DRAFT → submit → PENDING_REVIEW
        F. Admin Approves Requirement — PENDING_REVIEW → OPEN_FOR_CSR
        G. Company Discovers & Sends EOI — PENDING_NGO_REVIEW
        H. NGO Accepts EOI — status → ACCEPTED; Partnership created (PENDING_MOU)
        I. Company Uploads MoU — Partnership → ACTIVE
        J. Company Reports Disbursement
        K. NGO Creates Milestone — PENDING
        L. NGO Submits Evidence — SUBMITTED
        M. Company Reviews Milestone — VERIFIED
        N. Admin Audit/Analytics + Protected donation check
        """
        pan = 'AABCI1234K'

        # ==================================================================
        # B — Company Onboarding
        # ==================================================================

        self.client.force_authenticate(user=self.company_user)

        # B1: No profile yet → 404
        resp = self.client.get('/api/v1/csr/profile/me/')
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND,
                         f"B1: Expected 404 before profile creation, got {resp.status_code}")

        # B2: Create company profile
        resp = self.client.post('/api/v1/csr/profile/me/', {
            'company_name': 'Infosys Limited',
            'legal_name': 'Infosys Limited',
            'cin_number': 'L72200KA1981PLC004369',
            'pan_number': pan,
            'contact_person_name': 'Salil Parekh',
            'contact_person_designation': 'CEO & CSR Chair',
            'contact_email': 'csr@infosys.com',
            'contact_phone': '+919876500000',
            'registered_address': 'Electronics City Phase I',
            'city': 'Bengaluru',
            'state': 'Karnataka',
            'pincode': '560100',
            'annual_csr_budget': '50000000.00',
        }, format='json')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"B2: Profile creation failed: {resp.data}")
        self.assertEqual(resp.data['verification_status'], 'DRAFT',
                         "B2: New profile must be DRAFT")
        company_id = resp.data['id']

        # B3: GET profile → 200
        resp = self.client.get('/api/v1/csr/profile/me/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"B3: Profile GET failed: {resp.status_code}")

        # B4: Upload verification document
        doc = make_dummy_uploaded_file(name='coi.pdf')
        resp = self.client.post(
            '/api/v1/csr/profile/verification-document/',
            {'verification_document': doc},
            format='multipart',
        )
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"B4: Document upload failed: {resp.data}")

        # PAN must not appear in any email
        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "B: PAN leaked in onboarding email")

        # ==================================================================
        # C — Admin Approves Company
        # ==================================================================

        self.client.force_authenticate(user=self.admin_user)
        mail.outbox.clear()

        resp = self.client.get('/api/v1/admin/csr/companies/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "C: admin companies list failed")
        items = resp.data.get('results') or resp.data
        self.assertIn(str(company_id), [str(c['id']) for c in items],
                      "C: Company not visible in admin list")

        resp = self.client.get(f'/api/v1/admin/csr/companies/{company_id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "C: admin company detail failed")

        resp = self.client.post(
            f'/api/v1/admin/csr/companies/{company_id}/approve/',
            {'review_notes': 'All docs verified.'}, format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"C: Approval failed: {resp.data}")

        cp = CompanyProfile.objects.get(id=company_id)
        self.assertEqual(cp.verification_status, CompanyVerificationStatus.APPROVED,
                         "C: Company must be APPROVED after admin action")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "C: PAN leaked in approval email")

        # ==================================================================
        # D — Company Sets Preferences
        # ==================================================================

        self.client.force_authenticate(user=self.company_user)
        mail.outbox.clear()

        resp = self.client.put('/api/v1/csr/preferences/me/', {
            'preferred_categories': [ScheduleVIICategory.PROMOTING_EDUCATION],
            'preferred_states': ['Karnataka'],
            'preferred_districts': ['Bengaluru Urban'],
            'is_nationwide': False,
            'has_no_location_pref': False,
            'min_budget': '500000.00',
            'max_budget': '10000000.00',
            'preferred_duration_months': 12,
            'preferred_beneficiaries': [BeneficiaryDemographic.CHILDREN_EDUCATION],
        }, format='json')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"D: Preferences upsert failed: {resp.data}")

        resp = self.client.get('/api/v1/csr/preferences/me/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "D: preferences GET failed")
        self.assertIn(ScheduleVIICategory.PROMOTING_EDUCATION,
                      resp.data.get('preferred_categories', []),
                      "D: preferred_categories not persisted")

        # ==================================================================
        # E — NGO Creates Requirement
        # ==================================================================

        self.client.force_authenticate(user=self.ngo_user)
        mail.outbox.clear()

        today = date.today()
        resp = self.client.post('/api/v1/ngo/csr/requirements/', {
            'title': 'E2E Smart Classrooms Initiative',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'additional_districts': [],
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'target_beneficiary_count': 800,
            'summary': 'Installing smart boards in 20 schools.',
            'detailed_description': 'Comprehensive digital education programme.',
            'expected_outcomes': '800 students gain digital learning access.',
            'total_estimated_budget': '1000000.00',
            'required_csr_funding': '800000.00',
            'committed_funding': '200000.00',
            'start_date': str(today),
            'expected_completion_date': str(today + timedelta(days=365)),
        }, format='json')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"E: Requirement creation failed: {resp.data}")
        self.assertEqual(resp.data['status'], CSRRequirementStatus.DRAFT,
                         "E: Requirement must start as DRAFT")
        req_id = resp.data['id']

        # E.1: PUT update
        resp = self.client.put(f'/api/v1/ngo/csr/requirements/{req_id}/', {
            'title': 'E2E Smart Classrooms Initiative',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'additional_districts': [],
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'target_beneficiary_count': 800,
            'summary': 'Updated: 25 schools now included.',
            'detailed_description': 'Comprehensive digital education programme.',
            'expected_outcomes': '800 students gain digital learning access.',
            'total_estimated_budget': '1000000.00',
            'required_csr_funding': '800000.00',
            'committed_funding': '200000.00',
            'start_date': str(today),
            'expected_completion_date': str(today + timedelta(days=365)),
        }, format='json')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"E.1: Requirement update failed: {resp.data}")

        # E.2: Upload 3 documents
        for i in range(3):
            doc = make_dummy_uploaded_file(name=f'doc_{i+1}.pdf')
            resp = self.client.post(
                f'/api/v1/ngo/csr/requirements/{req_id}/upload-document/',
                {'document': doc, 'document_type': 'PROJECT_PROPOSAL'},
                format='multipart',
            )
            self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                          f"E.2: Doc upload {i+1} failed: {resp.data}")

        # E.3: Submit → PENDING_REVIEW
        resp = self.client.post(f'/api/v1/ngo/csr/requirements/{req_id}/submit/')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"E.3: Submit failed: {resp.data}")

        req_obj = CSRRequirement.objects.get(id=req_id)
        self.assertEqual(req_obj.status, CSRRequirementStatus.PENDING_REVIEW,
                         "E.3: Requirement must be PENDING_REVIEW after submit")

        # ==================================================================
        # F — Admin Approves Requirement
        # ==================================================================

        self.client.force_authenticate(user=self.admin_user)
        mail.outbox.clear()

        resp = self.client.get('/api/v1/admin/csr/requirements/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "F: admin req list failed")
        items = resp.data.get('results') or resp.data
        self.assertIn(str(req_id), [str(r['id']) for r in items],
                      "F: Requirement not visible in admin list")

        resp = self.client.post(
            f'/api/v1/admin/csr/requirements/{req_id}/approve/',
            {'review_notes': 'Meets Schedule VII criteria.'}, format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"F: Requirement approval failed: {resp.data}")

        req_obj.refresh_from_db()
        self.assertEqual(req_obj.status, CSRRequirementStatus.OPEN_FOR_CSR,
                         "F: Requirement must be OPEN_FOR_CSR after admin approval")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "F: PAN leaked in requirement approval email")

        # ==================================================================
        # G — Company Discovers & Sends EOI
        # ==================================================================

        self.client.force_authenticate(user=self.company_user)
        mail.outbox.clear()

        resp = self.client.get('/api/v1/csr/requirements/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "G: marketplace list failed")
        items = resp.data.get('results') or resp.data
        self.assertIn(str(req_id), [str(r['id']) for r in items],
                      "G: Approved requirement not visible in marketplace")

        resp = self.client.get('/api/v1/csr/requirements/recommended/')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_204_NO_CONTENT],
                      "G: recommended endpoint failed")

        resp = self.client.get(f'/api/v1/csr/requirements/{req_id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "G: requirement detail failed")

        resp = self.client.post('/api/v1/csr/support-requests/', {
            'requirement': str(req_id),
            'spoc_name': 'Salil Parekh',
            'spoc_email': 'csr@infosys.com',
            'spoc_phone': '+919876500000',
            'proposed_funding': '800000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'message': 'Infosys supports this initiative.',
        }, format='json')
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"G: EOI creation failed: {resp.data}")
        sr_id = resp.data['id']

        sr_obj = CSRSupportRequest.objects.get(id=sr_id)
        self.assertEqual(sr_obj.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW,
                         "G: EOI must be PENDING_NGO_REVIEW")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "G: PAN leaked in EOI notification")

        # ==================================================================
        # H — NGO Accepts EOI
        # ==================================================================

        self.client.force_authenticate(user=self.ngo_user)
        mail.outbox.clear()

        resp = self.client.get('/api/v1/ngo/csr/support-requests/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "H: NGO SR list failed")
        items = resp.data.get('results') or resp.data
        self.assertIn(str(sr_id), [str(s['id']) for s in items],
                      "H: EOI not visible to NGO")

        resp = self.client.post(
            f'/api/v1/ngo/csr/support-requests/{sr_id}/accept/',
            {'notes': 'Pleased to partner.'}, format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"H: EOI acceptance failed: {resp.data}")

        sr_obj.refresh_from_db()
        self.assertEqual(sr_obj.status, CSRSupportRequestStatus.ACCEPTED,
                         "H: EOI must be ACCEPTED")

        partnerships = CSRPartnership.objects.filter(support_request_id=sr_id)
        self.assertEqual(partnerships.count(), 1, "H: Exactly 1 partnership must be created")
        partnership = partnerships.first()
        self.assertEqual(partnership.status, CSRPartnershipStatus.PENDING_MOU,
                         "H: Partnership must be PENDING_MOU")
        partnership_id = partnership.id

        req_obj.refresh_from_db()
        self.assertEqual(req_obj.status, CSRRequirementStatus.PARTNERED,
                         "H: Requirement must be PARTNERED after EOI acceptance")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "H: PAN leaked in acceptance email")

        # ==================================================================
        # I — Company Uploads MoU
        # ==================================================================

        self.client.force_authenticate(user=self.company_user)
        mail.outbox.clear()

        resp = self.client.get('/api/v1/csr/partnerships/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK, "I: company partnerships list failed")
        items = resp.data.get('results') or resp.data
        self.assertIn(str(partnership_id), [str(p['id']) for p in items],
                      "I: Partnership not visible to company")

        mou_doc = make_dummy_uploaded_file(name='mou.pdf')
        resp = self.client.post(
            f'/api/v1/csr/partnerships/{partnership_id}/upload-mou/',
            {'mou_document': mou_doc}, format='multipart',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"I: MoU upload failed: {resp.data}")

        partnership.refresh_from_db()
        self.assertEqual(partnership.status, CSRPartnershipStatus.ACTIVE,
                         "I: Partnership must be ACTIVE after MoU upload")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "I: PAN leaked in MoU email")

        # ==================================================================
        # J — Company Reports Disbursement
        # ==================================================================

        mail.outbox.clear()

        resp = self.client.post(
            f'/api/v1/csr/partnerships/{partnership_id}/report-disbursement/',
            {'amount': '400000.00', 'transfer_reference': 'NEFT-2026-001',
             'notes': 'First tranche disbursed.'},
            format='json',
        )
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"J: Disbursement failed: {resp.data}")

        partnership.refresh_from_db()
        self.assertGreater(partnership.disbursed_amount_reported, Decimal('0.00'),
                           "J: Disbursed amount must be > 0 after reporting")

        # ==================================================================
        # K — NGO Creates Milestone
        # ==================================================================

        self.client.force_authenticate(user=self.ngo_user)
        mail.outbox.clear()

        resp = self.client.post(
            f'/api/v1/ngo/csr/partnerships/{partnership_id}/milestones/',
            {
                'title': 'Phase 1: Smart Board Procurement',
                'description': 'Procure 25 smart boards across 5 schools.',
                'target_completion_date': str(today + timedelta(days=90)),
                'completion_percentage': 0,
            },
            format='json',
        )
        self.assertIn(resp.status_code, [http_status.HTTP_200_OK, http_status.HTTP_201_CREATED],
                      f"K: Milestone creation failed: {resp.data}")

        milestone_id = resp.data['id']
        ms_obj = PartnershipMilestone.objects.get(id=milestone_id)
        self.assertEqual(ms_obj.status, MilestoneStatus.PENDING,
                         "K: New milestone must be PENDING")

        # ==================================================================
        # L — NGO Submits Evidence
        # ==================================================================

        mail.outbox.clear()

        ev_doc = make_dummy_uploaded_file(name='evidence.pdf')
        resp = self.client.post(
            f'/api/v1/ngo/csr/partnerships/{partnership_id}/milestones/{milestone_id}/submit-evidence/',
            {
                'evidence_document': ev_doc,
                'completion_percentage': 60,
                'submission_notes': 'Phase 1 complete.',
            },
            format='multipart',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"L: Evidence submission failed: {resp.data}")

        ms_obj.refresh_from_db()
        self.assertEqual(ms_obj.status, MilestoneStatus.SUBMITTED,
                         "L: Milestone must be SUBMITTED after evidence upload")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "L: PAN leaked in evidence email")

        # ==================================================================
        # M — Company Reviews Milestone → VERIFIED
        # ==================================================================

        self.client.force_authenticate(user=self.company_user)
        mail.outbox.clear()

        resp = self.client.post(
            f'/api/v1/csr/partnerships/{partnership_id}/milestones/{milestone_id}/review/',
            {'status': MilestoneStatus.VERIFIED, 'review_notes': 'All boards installed. Approved.'},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK,
                         f"M: Milestone review failed: {resp.data}")

        ms_obj.refresh_from_db()
        self.assertEqual(ms_obj.status, MilestoneStatus.VERIFIED,
                         "M: Milestone must be VERIFIED after company review")

        for m in mail.outbox:
            self.assertNotIn(pan, m.body, "M: PAN leaked in milestone review email")

        # ==================================================================
        # N — Admin Audit, Analytics, Protected Donation
        # ==================================================================

        self.client.force_authenticate(user=self.admin_user)

        p_list = self.client.get('/api/v1/admin/csr/partnerships/')
        self.assertEqual(p_list.status_code, http_status.HTTP_200_OK, "N: admin partnerships failed")
        items = p_list.data.get('results') or p_list.data
        self.assertIn(str(partnership_id), [str(p['id']) for p in items],
                      "N: Partnership not visible in admin list")

        audit_resp = self.client.get('/api/v1/admin/csr/audit-history/')
        self.assertEqual(audit_resp.status_code, http_status.HTTP_200_OK, "N: audit history failed")
        audit_items = audit_resp.data.get('results') or audit_resp.data
        self.assertGreater(len(audit_items), 0, "N: Audit history must be non-empty after lifecycle")

        analytics_resp = self.client.get('/api/v1/admin/csr/analytics/')
        self.assertEqual(analytics_resp.status_code, http_status.HTTP_200_OK, "N: analytics failed")
        analytics = analytics_resp.data
        total = (
            analytics.get('total_companies', 0) +
            analytics.get('total_requirements', 0) +
            analytics.get('total_partnerships', 0)
        )
        self.assertGreater(total, 0, f"N: Analytics must be non-zero: {analytics}")

        # N.1: Protected donation intact
        from campaigns.models import MonetaryDonation, TaxReceiptRecord
        don = MonetaryDonation.objects.filter(receipt_number='DG-M-20260831-8STYX2').first()
        if don:
            self.assertEqual(str(don.amount), '1000.00',
                             "N.1: Protected donation amount must be 1000.00")
            self.assertEqual(don.status, 'SUCCESS',
                             "N.1: Protected donation status must be SUCCESS")
            tr = TaxReceiptRecord.objects.filter(receipt_number='DG-M-20260831-8STYX2').first()
            if tr:
                self.assertEqual(tr.financial_year, 'FY 2026-27',
                                 "N.1: Tax receipt financial_year mismatch")
                self.assertEqual(
                    tr.document_hash,
                    '678541b65a931e3a426556fea20225a3f9dc7f3ac6dc5177d4ea5fb58bf88edd',
                    "N.1: Tax receipt document_hash mismatch",
                )

        # N.2: Donor blocked from CSR admin
        self.client.force_authenticate(user=self.donor_user)
        donor_resp = self.client.get('/api/v1/admin/csr/companies/')
        self.assertEqual(donor_resp.status_code, http_status.HTTP_403_FORBIDDEN,
                         "N.2: Donor must be blocked from admin CSR endpoints")
