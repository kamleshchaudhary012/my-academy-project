"""
CSR Company API Views Integration Tests — Phase CSR-2.8.1
=========================================================
Exhaustive integration tests for the 20 COMPANY namespace API endpoints under /api/v1/csr/.
Covers:
  1. Profile & Verification Document (#1 - #4)
  2. Preferences (#5 - #6)
  3. Dashboard (#7)
  4. Marketplace & Requirement Detail (#8 - #10)
  5. Support Requests / Grant EOIs (#11 - #14)
  6. Partnerships & Milestones (#15 - #20)
  7. Multi-Tenant IDOR & Security Isolation
  8. Notification Wiring via transaction.on_commit
"""

import uuid
from decimal import Decimal
from datetime import date, timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CSRRequirement,
    CSRRequirementStatus,
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRPartnership,
    CSRPartnershipStatus,
    PartnershipMilestone,
    MilestoneStatus,
    CompanyVerificationStatus,
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


class CSRCompanyAPITests(APITestCase):
    """Integration tests for all 20 COMPANY API endpoints."""

    def setUp(self):
        mail.outbox.clear()

        # Company User A (Verified)
        self.company_user_a = make_user(
            email="csr_spoc_a@reliance.com",
            full_name="Mukesh Ambani",
            role=User.Role.COMPANY,
        )
        self.company_a = make_company_profile(
            user=self.company_user_a,
            company_name="Reliance Industries Ltd",
            cin_number="L17110MH1973PLC019786",
            pan_number="AAACR1234A",
            verification_status=CompanyVerificationStatus.APPROVED,
            annual_csr_budget=Decimal("50000000.00"),
        )
        self.pref_a = CompanyCSRPreference.objects.create(
            company=self.company_a,
            preferred_categories=[ScheduleVIICategory.PROMOTING_EDUCATION],
            preferred_states=["Maharashtra"],
            min_budget=Decimal("100000.00"),
            max_budget=Decimal("5000000.00"),
        )

        # Company User B (Unverified)
        self.company_user_b = make_user(
            email="founder@startup.io",
            full_name="Aman Gupta",
            role=User.Role.COMPANY,
        )
        self.company_b = make_company_profile(
            user=self.company_user_b,
            company_name="boAt Lifestyle Ltd",
            cin_number="U74999DL2016PTC308226",
            pan_number="AAACB5678B",
            verification_status=CompanyVerificationStatus.DRAFT,
            annual_csr_budget=Decimal("1000000.00"),
        )

        # NGO User
        self.ngo_user = make_user(
            email="director@pratham.org",
            full_name="Rukmini Banerji",
            role=User.Role.NGO,
        )
        self.ngo = make_ngo_profile(
            user=self.ngo_user,
            display_name="Pratham Education Foundation",
            legal_name="Pratham Education Trust",
        )

        # Donor User
        self.donor_user = make_user(
            email="donor@gmail.com",
            full_name="Individual Donor",
            role=User.Role.DONOR,
        )

        # Approved CSR Requirements
        self.req_education = make_csr_requirement(
            ngo=self.ngo,
            title="Read India Literacy Campaign",
            schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
            state="Maharashtra",
            district="Mumbai",
            location_scope=LocationScope.SPECIFIC_DISTRICT,
            beneficiary_demographic=BeneficiaryDemographic.CHILDREN_EDUCATION,
            total_estimated_budget=Decimal("2000000.00"),
            required_csr_funding=Decimal("1500000.00"),
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )
        self.req_health = make_csr_requirement(
            ngo=self.ngo,
            title="Rural Mobile Health Clinics",
            schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER,
            state="Gujarat",
            district="Surat",
            location_scope=LocationScope.SPECIFIC_DISTRICT,
            beneficiary_demographic=BeneficiaryDemographic.RURAL_COMMUNITIES,
            total_estimated_budget=Decimal("3000000.00"),
            required_csr_funding=Decimal("2500000.00"),
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )
        self.req_draft = make_csr_requirement(
            ngo=self.ngo,
            title="Draft Proposal Not for Marketplace",
            status=CSRRequirementStatus.DRAFT,
        )

        # Support Request for Company A
        self.support_req_a = make_csr_support_request(
            company=self.company_a,
            requirement=self.req_education,
            proposed_funding=Decimal("1500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        # Partnership for Company A
        self.partnership_a = make_csr_partnership(
            company=self.company_a,
            ngo=self.ngo,
            requirement=self.req_education,
            support_request=self.support_req_a,
            agreed_funding_amount=Decimal("1500000.00"),
            status=CSRPartnershipStatus.PENDING_MOU,
        )

        # Milestone for Partnership A
        self.milestone_a = make_partnership_milestone(
            partnership=self.partnership_a,
            sequence_number=1,
            title="Procurement of Learning Tablets",
            target_completion_date=date.today() + timedelta(days=60),
            status=MilestoneStatus.SUBMITTED,
            completion_percentage=50,
        )

    # --------------------------------------------------------------------------
    # 1. Profile & Documents Endpoints (#1 - #4)
    # --------------------------------------------------------------------------

    def test_01_get_company_profile_me_success(self):
        """GET /api/v1/csr/profile/me/ returns authenticated company profile."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/profile/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['company_name'], "Reliance Industries Ltd")
        self.assertEqual(response.data['verification_status'], "APPROVED")

    def test_01_get_company_profile_unauthenticated(self):
        """GET /api/v1/csr/profile/me/ unauthenticated returns 401."""
        response = self.client.get('/api/v1/csr/profile/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_01_get_company_profile_wrong_role(self):
        """GET /api/v1/csr/profile/me/ by NGO/Donor returns 403."""
        self.client.force_authenticate(user=self.ngo_user)
        response = self.client.get('/api/v1/csr/profile/me/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_02_post_company_profile_me_creates_profile(self):
        """POST /api/v1/csr/profile/me/ creates new DRAFT profile for new company user."""
        new_user = make_user(email="newcorp@csr.com", role=User.Role.COMPANY)
        self.client.force_authenticate(user=new_user)
        payload = {
            "company_name": "Infosys Foundation",
            "legal_name": "Infosys Ltd",
            "cin_number": "L85110KA1981PLC013115",
            "pan_number": "AAACI1234K",
            "contact_person_name": "Sudha Murty",
            "contact_person_designation": "Trustee",
            "contact_email": "csr@infosys.com",
            "contact_phone": "+919876543210",
            "registered_address": "Electronics City",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560100",
            "annual_csr_budget": "100000000.00",
        }
        response = self.client.post('/api/v1/csr/profile/me/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['company_name'], "Infosys Foundation")
        self.assertEqual(response.data['verification_status'], "DRAFT")

    def test_02_post_company_profile_me_conflict_if_exists(self):
        """POST /api/v1/csr/profile/me/ returns 409 if profile already exists."""
        self.client.force_authenticate(user=self.company_user_a)
        payload = {
            "company_name": "Duplicate Company",
            "legal_name": "Duplicate Legal",
            "cin_number": "U12345MH2020PTC123456",
            "pan_number": "ABCDE9999Z",
            "contact_person_name": "Test",
            "contact_person_designation": "Manager",
            "contact_email": "test@test.com",
            "contact_phone": "+919876543210",
            "registered_address": "Test Road",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400001",
        }
        response = self.client.post('/api/v1/csr/profile/me/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_03_patch_company_profile_me_updates_fields(self):
        """PATCH /api/v1/csr/profile/me/ updates editable fields."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.patch('/api/v1/csr/profile/me/', data={"official_website": "https://www.ril.com"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['official_website'], "https://www.ril.com")

    def test_04_post_verification_document_success(self):
        """POST /api/v1/csr/profile/verification-document/ uploads statutory doc."""
        self.client.force_authenticate(user=self.company_user_b)
        pdf_file = make_dummy_uploaded_file(name="inc_cert.pdf")
        response = self.client.post(
            '/api/v1/csr/profile/verification-document/',
            data={'verification_document': pdf_file},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['has_verification_document'])

    def test_04_post_verification_document_no_file(self):
        """POST /api/v1/csr/profile/verification-document/ with no file returns 400."""
        self.client.force_authenticate(user=self.company_user_b)
        response = self.client.post('/api/v1/csr/profile/verification-document/', data={}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_04_post_profile_submit_success(self):
        """POST /api/v1/csr/profile/submit/ transitions DRAFT -> PENDING_VERIFICATION."""
        self.client.force_authenticate(user=self.company_user_b)
        # Attach doc first
        pdf_file = make_dummy_uploaded_file(name="inc_cert.pdf")
        self.client.post(
            '/api/v1/csr/profile/verification-document/',
            data={'verification_document': pdf_file},
            format='multipart',
        )
        response = self.client.post('/api/v1/csr/profile/submit/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['verification_status'], "PENDING_VERIFICATION")

    def test_04_post_profile_submit_missing_doc(self):
        """POST /api/v1/csr/profile/submit/ without document returns 400."""
        new_user = make_user(email="nodoc@csr.com", role=User.Role.COMPANY)
        make_company_profile(user=new_user, verification_status=CompanyVerificationStatus.DRAFT, verification_document=None)
        self.client.force_authenticate(user=new_user)
        response = self.client.post('/api/v1/csr/profile/submit/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --------------------------------------------------------------------------
    # 2. Preferences Endpoints (#5 - #6)
    # --------------------------------------------------------------------------

    def test_05_get_company_preferences_me(self):
        """GET /api/v1/csr/preferences/me/ retrieves preferences."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/preferences/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['preferred_categories'], [ScheduleVIICategory.PROMOTING_EDUCATION])

    def test_06_put_patch_company_preferences_me(self):
        """PUT and PATCH /api/v1/csr/preferences/me/ update preferences."""
        self.client.force_authenticate(user=self.company_user_a)
        payload = {
            "preferred_categories": [ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY],
            "preferred_states": ["Gujarat"],
            "min_budget": "50000.00",
            "max_budget": "3000000.00",
        }
        response = self.client.put('/api/v1/csr/preferences/me/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['preferred_categories'], [ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY])

        # Partial patch
        response = self.client.patch('/api/v1/csr/preferences/me/', data={"is_nationwide": True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_nationwide'])

    # --------------------------------------------------------------------------
    # 3. Dashboard Endpoint (#7)
    # --------------------------------------------------------------------------

    def test_07_get_company_dashboard(self):
        """GET /api/v1/csr/dashboard/ returns complete composite metrics DTO."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('company_name', response.data)
        self.assertIn('verification_status', response.data)
        self.assertIn('committed_funding_total', response.data)
        self.assertIn('disbursed_funding_total', response.data)
        self.assertIn('active_partnerships_count', response.data)
        self.assertIn('pending_requests_count', response.data)
        self.assertIn('recommended_proposals', response.data)
        self.assertEqual(response.data['company_name'], "Reliance Industries Ltd")

    # --------------------------------------------------------------------------
    # 4. Marketplace & Requirement Detail (#8 - #10)
    # --------------------------------------------------------------------------

    def test_08_get_requirements_marketplace_list(self):
        """GET /api/v1/csr/requirements/ returns paginated OPEN_FOR_CSR requirements."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/requirements/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        titles = [r['title'] for r in response.data['results']]
        self.assertIn("Read India Literacy Campaign", titles)
        self.assertIn("Rural Mobile Health Clinics", titles)
        self.assertNotIn("Draft Proposal Not for Marketplace", titles)

    def test_08_get_requirements_filtering(self):
        """GET /api/v1/csr/requirements/ with category and state filters."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/requirements/?category=PROMOTING_EDUCATION&state=Maharashtra')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], "Read India Literacy Campaign")

    def test_09_get_requirements_recommended(self):
        """GET /api/v1/csr/requirements/recommended/ returns scored recommendations."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/requirements/recommended/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertIn('match_score', response.data[0])
        self.assertIn('breakdown', response.data[0])

    def test_10_get_requirement_detail_success(self):
        """GET /api/v1/csr/requirements/<uuid:id>/ returns full detail."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get(f'/api/v1/csr/requirements/{self.req_education.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], "Read India Literacy Campaign")

    def test_10_get_requirement_detail_not_found(self):
        """GET /api/v1/csr/requirements/<uuid:id>/ with non-existent UUID returns 404."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get(f'/api/v1/csr/requirements/{uuid.uuid4()}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --------------------------------------------------------------------------
    # 5. Support Requests Endpoints (#11 - #14)
    # --------------------------------------------------------------------------

    def test_11_post_support_request_verified_company_success(self):
        """POST /api/v1/csr/support-requests/ submits grant EOI and fires notification."""
        self.client.force_authenticate(user=self.company_user_a)
        payload = {
            "requirement": str(self.req_health.id),
            "proposed_funding": "2000000.00",
            "support_type": CSRSupportType.FINANCIAL_GRANT,
            "spoc_name": "Mukesh Ambani",
            "spoc_email": "csr_spoc_a@reliance.com",
            "spoc_phone": "+919876543210",
            "message": "We would like to support rural healthcare under our CSR mandate.",
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/api/v1/csr/support-requests/', data=payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data['status'], "PENDING_NGO_REVIEW")

        # Verify notification was sent to NGO
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["director@pratham.org"])

    def test_11_post_support_request_unverified_company_forbidden(self):
        """POST /api/v1/csr/support-requests/ by unverified company returns 403."""
        self.client.force_authenticate(user=self.company_user_b)
        payload = {
            "requirement": str(self.req_health.id),
            "proposed_funding": "100000.00",
            "support_type": CSRSupportType.FINANCIAL_GRANT,
            "spoc_name": "Aman Gupta",
            "spoc_email": "founder@startup.io",
            "spoc_phone": "+919876543210",
            "message": "Interested in CSR.",
        }
        response = self.client.post('/api/v1/csr/support-requests/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_12_get_support_requests_list(self):
        """GET /api/v1/csr/support-requests/ lists company's outbox."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/support-requests/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertEqual(len(response.data['results']), 1)

    def test_13_get_support_request_detail(self):
        """GET /api/v1/csr/support-requests/<uuid:id>/ returns single request."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get(f'/api/v1/csr/support-requests/{self.support_req_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.support_req_a.id))

    def test_14_post_support_request_withdraw(self):
        """POST /api/v1/csr/support-requests/<uuid:id>/withdraw/ transitions status."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.post(f'/api/v1/csr/support-requests/{self.support_req_a.id}/withdraw/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], "WITHDRAWN")

    # --------------------------------------------------------------------------
    # 6. Partnerships & Milestones Endpoints (#15 - #20)
    # --------------------------------------------------------------------------

    def test_15_get_partnerships_list(self):
        """GET /api/v1/csr/partnerships/ lists company partnerships."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get('/api/v1/csr/partnerships/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertEqual(len(response.data['results']), 1)

    def test_16_get_partnership_detail(self):
        """GET /api/v1/csr/partnerships/<uuid:id>/ returns detail."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get(f'/api/v1/csr/partnerships/{self.partnership_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.partnership_a.id))

    def test_17_post_partnership_upload_mou(self):
        """POST /api/v1/csr/partnerships/<uuid:id>/upload-mou/ activates partnership and notifies parties."""
        self.client.force_authenticate(user=self.company_user_a)
        mou_pdf = make_dummy_uploaded_file(name="signed_mou.pdf")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f'/api/v1/csr/partnerships/{self.partnership_a.id}/upload-mou/',
                data={'signed_mou_document': mou_pdf},
                format='multipart',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['status'], "ACTIVE")

        # Verify MoU notification sent to both company and NGO
        self.assertEqual(len(mail.outbox), 2)
        recipients = {m.to[0] for m in mail.outbox}
        self.assertEqual(recipients, {"csr_spoc_a@reliance.com", "director@pratham.org"})

    def test_post_partnership_upload_mou_invalid_extension_rejected(self):
        """POST /api/v1/csr/partnerships/<uuid:id>/upload-mou/ rejects non-PDF/image files with 400 Bad Request."""
        self.client.force_authenticate(user=self.company_user_a)
        bad_file = make_dummy_uploaded_file(name="signed_mou.txt", content_type="text/plain")
        response = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/upload-mou/',
            data={'signed_mou_document': bad_file},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('signed_mou_document', response.data)

    def test_18_post_partnership_report_disbursement(self):
        """POST /api/v1/csr/partnerships/<uuid:id>/report-disbursement/ records payment."""
        self.partnership_a.status = CSRPartnershipStatus.ACTIVE
        self.partnership_a.save()

        self.client.force_authenticate(user=self.company_user_a)
        payload = {
            "disbursed_amount_reported": "500000.00",
            "disbursement_notes": "First tranche RTGS transfer.",
            "transaction_reference": "UTR123456789",
        }
        response = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/report-disbursement/',
            data=payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['disbursed_amount_reported'], "500000.00")

    def test_19_get_partnership_milestones_list(self):
        """GET /api/v1/csr/partnerships/<uuid:id>/milestones/ lists milestones."""
        self.client.force_authenticate(user=self.company_user_a)
        response = self.client.get(f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], "Procurement of Learning Tablets")

    def test_20_post_milestone_review_verified_success(self):
        """POST /api/v1/csr/partnerships/<uuid:id>/milestones/<uuid:mid>/review/ verifies milestone."""
        self.client.force_authenticate(user=self.company_user_a)
        payload = {
            "decision": "VERIFY",
            "notes": "All hardware vendor invoices verified.",
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/{self.milestone_a.id}/review/',
                data=payload,
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['status'], "VERIFIED")

        # Verify milestone verification email dispatched to NGO
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["director@pratham.org"])

    def test_20_post_milestone_review_revision_requested(self):
        """POST /api/v1/csr/partnerships/<uuid:id>/milestones/<uuid:mid>/review/ requests revision."""
        self.client.force_authenticate(user=self.company_user_a)
        payload = {
            "decision": "REQUEST_REVISION",
            "notes": "Please attach serial numbers for the delivered tablets.",
        }
        response = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/{self.milestone_a.id}/review/',
            data=payload,
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], "REVISION_REQUESTED")

    # --------------------------------------------------------------------------
    # 7. Multi-Tenant IDOR & Security Isolation
    # --------------------------------------------------------------------------

    def test_idor_company_b_cannot_view_company_a_support_request(self):
        """Company B cannot view Company A's support request detail (returns 403 or 404)."""
        self.client.force_authenticate(user=self.company_user_b)
        response = self.client.get(f'/api/v1/csr/support-requests/{self.support_req_a.id}/')
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_idor_company_b_cannot_view_company_a_partnership(self):
        """Company B cannot view Company A's partnership (returns 403 or 404)."""
        self.client.force_authenticate(user=self.company_user_b)
        response = self.client.get(f'/api/v1/csr/partnerships/{self.partnership_a.id}/')
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_idor_company_b_cannot_access_company_a_milestones(self):
        """Company B cannot list or review Company A's milestones (returns 403 or 404)."""
        self.client.force_authenticate(user=self.company_user_b)
        response = self.client.get(f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/')
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        review_response = self.client.post(
            f'/api/v1/csr/partnerships/{self.partnership_a.id}/milestones/{self.milestone_a.id}/review/',
            data={"decision": "VERIFY", "notes": "Attempted IDOR bypass."},
            format='json',
        )
        self.assertIn(review_response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
