"""
CSR NGO API Views Integration Tests — Phase CSR-2.8.2
=====================================================
Exhaustive integration tests for the 16 NGO namespace API endpoints under /api/v1/ngo/csr/.
Covers:
  1. Dashboard (#21)
  2. Requirements CRUD, Submission & Upload (#22 - #28)
  3. Support Request Inbox, Acceptance & Rejection (#29 - #32)
  4. Partnerships & Milestone Management (#33 - #36)
  5. Multi-Tenant IDOR & Security Isolation
  6. Notification Wiring via transaction.on_commit
"""

import uuid
from decimal import Decimal
from datetime import date, timedelta

from django.core import mail
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from ngo.models import NGOProfile

from csr.models import (
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


class CSRNgoAPITests(APITestCase):
    """Integration tests for all 16 NGO API endpoints."""

    def setUp(self):
        mail.outbox.clear()

        # Primary NGO User A
        self.ngo_user_a = make_user(
            email="lead@gramin-vikas.org",
            full_name="Rajesh Sharma",
            role=User.Role.NGO,
        )
        self.ngo_profile_a = make_ngo_profile(
            user=self.ngo_user_a,
            legal_name="Gramin Vikas Trust",
            display_name="Gramin Vikas",
        )

        # Secondary NGO User B (for IDOR isolation testing)
        self.ngo_user_b = make_user(
            email="director@shiksha-foundation.org",
            full_name="Sunita Deshmukh",
            role=User.Role.NGO,
        )
        self.ngo_profile_b = make_ngo_profile(
            user=self.ngo_user_b,
            legal_name="Shiksha Foundation",
            display_name="Shiksha Foundation",
        )

        # Corporate Partner (Company)
        self.company_user = make_user(
            email="csr_spoc@tatapower.com",
            full_name="Natarajan Chandrasekaran",
            role=User.Role.COMPANY,
        )
        self.company = make_company_profile(
            user=self.company_user,
            company_name="Tata Power Company Limited",
            cin_number="L28920MH1919PLC000567",
            pan_number="AAACT1234T",
            verification_status=CompanyVerificationStatus.APPROVED,
            annual_csr_budget=Decimal("25000000.00"),
        )

        # Donor User (for RBAC rejection testing)
        self.donor_user = make_user(
            email="donor@example.com",
            full_name="Individual Donor",
            role=User.Role.DONOR,
        )

        # Seed initial requirements for NGO A
        self.req_draft_a = make_csr_requirement(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title="Solar Micro-Grids in Rural Maharashtra",
            schedule_vii_category=ScheduleVIICategory.ERADICATING_HUNGER,
            state="Maharashtra",
            district="Gadchiroli",
            status=CSRRequirementStatus.DRAFT,
            total_estimated_budget=Decimal("500000.00"),
            required_csr_funding=Decimal("500000.00"),
        )

        self.req_open_a = make_csr_requirement(
            ngo=self.ngo_profile_a,
            created_by=self.ngo_user_a,
            title="Clean Drinking Water RO Plants in Vidarbha",
            schedule_vii_category=ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY,
            state="Maharashtra",
            district="Amravati",
            status=CSRRequirementStatus.OPEN_FOR_CSR,
            total_estimated_budget=Decimal("1000000.00"),
            required_csr_funding=Decimal("1000000.00"),
        )

        # Seed initial requirements for NGO B
        self.req_draft_b = make_csr_requirement(
            ngo=self.ngo_profile_b,
            created_by=self.ngo_user_b,
            title="Tribal Girl Child Secondary Education Program",
            schedule_vii_category=ScheduleVIICategory.PROMOTING_EDUCATION,
            state="Maharashtra",
            district="Nandurbar",
            status=CSRRequirementStatus.DRAFT,
            total_estimated_budget=Decimal("750000.00"),
            required_csr_funding=Decimal("750000.00"),
        )

    # ==========================================================================
    # 1. Dashboard (#21)
    # ==========================================================================

    def test_ngo_dashboard_success(self):
        """GET /api/v1/ngo/csr/dashboard/ returns composite DTO with accurate metrics."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/dashboard/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["ngo_name"], "Gramin Vikas Trust")
        self.assertEqual(data["active_proposals_count"], 1)  # req_open_a
        self.assertEqual(data["draft_proposals_count"], 1)   # req_draft_a
        self.assertEqual(data["incoming_requests_pending_count"], 0)
        self.assertEqual(data["active_partnerships_count"], 0)
        self.assertEqual(data["total_funding_partnered"], "0.00")
        self.assertIsInstance(data["pending_milestone_submissions"], list)

    # ==========================================================================
    # 2. Requirements Views (#22 - #28)
    # ==========================================================================

    def test_ngo_requirement_list_scoped(self):
        """GET /api/v1/ngo/csr/requirements/ lists only own NGO requirements."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/requirements/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        titles = [item["title"] for item in response.data["results"]]
        self.assertIn("Solar Micro-Grids in Rural Maharashtra", titles)
        self.assertIn("Clean Drinking Water RO Plants in Vidarbha", titles)
        self.assertNotIn("Tribal Girl Child Secondary Education Program", titles)

    def test_ngo_requirement_list_filtering(self):
        """GET /api/v1/ngo/csr/requirements/ supports filtering by status, category, and state."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/requirements/?status=DRAFT"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Solar Micro-Grids in Rural Maharashtra")

    def test_ngo_requirement_create_success(self):
        """POST /api/v1/ngo/csr/requirements/ creates draft proposal."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/requirements/"
        payload = {
            "title": "Mobile Health Clinics for Remote Hamlets",
            "schedule_vii_category": ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY,
            "state": "Maharashtra",
            "district": "Yavatmal",
            "location_scope": LocationScope.SPECIFIC_DISTRICT,
            "beneficiary_demographic": BeneficiaryDemographic.RURAL_COMMUNITIES,
            "target_beneficiary_count": 5000,
            "summary": "Providing primary healthcare checkups and generic medicines.",
            "detailed_description": "A fleet of 3 equipped vans visiting 40 villages every month.",
            "expected_outcomes": "Reduction in seasonal diseases and early diagnosis of malnutrition.",
            "total_estimated_budget": "1500000.00",
            "required_csr_funding": "1200000.00",
            "start_date": str(date.today() + timedelta(days=30)),
            "expected_completion_date": str(date.today() + timedelta(days=365)),
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Mobile Health Clinics for Remote Hamlets")
        self.assertEqual(response.data["status"], "DRAFT")

    def test_ngo_requirement_create_with_state_wide_alias_and_aspirational_district(self):
        """POST /api/v1/ngo/csr/requirements/ successfully creates proposal with STATE_WIDE alias and ASPIRATIONAL_DISTRICT."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/requirements/"

        # 1. Test exact failure report: STATE_WIDE alias
        payload_state_wide = {
            "title": "State-Wide Digital Skills Initiative",
            "schedule_vii_category": ScheduleVIICategory.PROMOTING_EDUCATION,
            "state": "Maharashtra",
            "district": "Pune",
            "location_scope": "STATE_WIDE",
            "beneficiary_demographic": BeneficiaryDemographic.YOUTH_SKILLING,
            "target_beneficiary_count": 3000,
            "summary": "State-wide digital skilling labs for vocational colleges.",
            "detailed_description": "Comprehensive 36-district skilling rollout with industry-aligned certification.",
            "expected_outcomes": "80% placement rate for 3,000 youth.",
            "total_estimated_budget": "2000000.00",
            "required_csr_funding": "1500000.00",
            "start_date": str(date.today() + timedelta(days=15)),
            "expected_completion_date": str(date.today() + timedelta(days=365)),
        }
        res1 = self.client.post(url, payload_state_wide, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED, f"Failed: {res1.data}")
        self.assertEqual(res1.data["location_scope"], LocationScope.MULTI_DISTRICT)
        self.assertEqual(res1.data["location_scope_display"], "Multiple Districts / State-wide")

        # 2. Test ASPIRATIONAL_DISTRICT scope
        payload_aspirational = {
            "title": "Aspirational District Nutrition Project",
            "schedule_vii_category": ScheduleVIICategory.ERADICATING_HUNGER,
            "state": "Maharashtra",
            "district": "Gadchiroli",
            "location_scope": LocationScope.ASPIRATIONAL_DISTRICT,
            "beneficiary_demographic": BeneficiaryDemographic.CHILDREN_EDUCATION,
            "target_beneficiary_count": 1500,
            "summary": "Targeted supplementary nutrition in aspirational district.",
            "detailed_description": "Community kitchen and micronutrient fortification in rural tribal centers.",
            "expected_outcomes": "Significant reduction in severe acute malnutrition.",
            "total_estimated_budget": "800000.00",
            "required_csr_funding": "600000.00",
            "start_date": str(date.today() + timedelta(days=20)),
            "expected_completion_date": str(date.today() + timedelta(days=200)),
        }
        res2 = self.client.post(url, payload_aspirational, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED, f"Failed: {res2.data}")
        self.assertEqual(res2.data["location_scope"], LocationScope.ASPIRATIONAL_DISTRICT)
        self.assertEqual(res2.data["location_scope_display"], "NITI Aayog Aspirational District")

    def test_ngo_requirement_create_invalid_budget(self):
        """POST /api/v1/ngo/csr/requirements/ rejects funding < ₹10,000."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/requirements/"
        payload = {
            "title": "Small Project",
            "schedule_vii_category": ScheduleVIICategory.PROMOTING_EDUCATION,
            "state": "Maharashtra",
            "district": "Pune",
            "location_scope": LocationScope.SPECIFIC_DISTRICT,
            "beneficiary_demographic": BeneficiaryDemographic.CHILDREN_EDUCATION,
            "summary": "Small scale project.",
            "detailed_description": "Details here.",
            "expected_outcomes": "Outcomes here.",
            "total_estimated_budget": "5000.00",  # Below 10k
            "required_csr_funding": "5000.00",
            "start_date": str(date.today()),
            "expected_completion_date": str(date.today() + timedelta(days=90)),
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ngo_requirement_detail_own_success(self):
        """GET /api/v1/ngo/csr/requirements/<id>/ retrieves own requirement."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.req_draft_a.id))

    def test_ngo_requirement_detail_other_ngo_404(self):
        """GET /api/v1/ngo/csr/requirements/<id>/ fails closed with 404 on cross-NGO access."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_b.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ngo_requirement_update_draft_success(self):
        """PATCH /api/v1/ngo/csr/requirements/<id>/ updates draft fields."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/"
        response = self.client.patch(url, {"summary": "Updated summary for solar microgrids."}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summary"], "Updated summary for solar microgrids.")

    def test_ngo_requirement_delete_draft_success(self):
        """DELETE /api/v1/ngo/csr/requirements/<id>/ deletes draft requirement."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CSRRequirement.objects.filter(id=self.req_draft_a.id).exists())

    def test_ngo_requirement_submit_success(self):
        """POST /api/v1/ngo/csr/requirements/<id>/submit/ moves DRAFT to PENDING_REVIEW."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/submit/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "PENDING_REVIEW")

    def test_ngo_requirement_upload_document_success(self):
        """POST /api/v1/ngo/csr/requirements/<id>/upload-document/ attaches PDF."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/upload-document/"
        pdf_file = make_dummy_uploaded_file(name="proposal.pdf")

        response = self.client.post(
            url,
            {"proposal_document": pdf_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["has_proposal_document"])

    # ==========================================================================
    # 3. Support Requests (#29 - #32)
    # ==========================================================================

    def test_ngo_support_request_inbox(self):
        """GET /api/v1/ngo/csr/support-requests/ lists incoming requests for own NGO."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/support-requests/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(support_req.id))

    def test_ngo_support_request_detail_cross_ngo_404(self):
        """GET /api/v1/ngo/csr/support-requests/<id>/ denies cross-NGO access."""
        support_req_b = make_csr_support_request(
            company=self.company,
            requirement=self.req_draft_b,
            proposed_funding=Decimal("300000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/support-requests/{support_req_b.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ngo_support_request_accept_success_and_notification(self):
        """POST /api/v1/ngo/csr/support-requests/<id>/accept/ initializes partnership & dispatches notification."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/support-requests/{support_req.id}/accept/"

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("partnership", response.data)
            self.assertIn("support_request", response.data)
            self.assertEqual(response.data["support_request"]["status"], "ACCEPTED")

        # Verify email notification dispatched to Company SPOC
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Accepted", mail.outbox[0].subject)

    def test_ngo_support_request_reject_success_and_notification(self):
        """POST /api/v1/ngo/csr/support-requests/<id>/reject/ rejects with reason & dispatches notification."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/support-requests/{support_req.id}/reject/"

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"reason": "Proposed budget does not meet our minimum co-funding requirement."}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["status"], "REJECTED")

        # Verify notification dispatched to Company SPOC
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Update on your CSR Support Request", mail.outbox[0].subject)

    def test_ngo_support_request_reject_missing_reason_fails(self):
        """POST /api/v1/ngo/csr/support-requests/<id>/reject/ fails if reason is missing."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/support-requests/{support_req.id}/reject/"
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ==========================================================================
    # 4. Partnerships & Milestones (#33 - #36)
    # ==========================================================================

    def test_ngo_partnership_list_scoped(self):
        """GET /api/v1/ngo/csr/partnerships/ lists only partnerships for own NGO."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership_a = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("1000000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = "/api/v1/ngo/csr/partnerships/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(partnership_a.id))

    def test_ngo_partnership_detail_cross_ngo_404(self):
        """GET /api/v1/ngo/csr/partnerships/<id>/ denies cross-NGO access."""
        support_req_b = make_csr_support_request(
            company=self.company,
            requirement=self.req_draft_b,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership_b = make_csr_partnership(
            support_request=support_req_b,
            company=self.company,
            ngo=self.ngo_profile_b,
            requirement=self.req_draft_b,
            agreed_funding_amount=Decimal("500000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership_b.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ngo_milestone_create_success(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/ creates sequenced deliverable."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("1000000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership.id}/milestones/"
        payload = {
            "sequence_number": 1,
            "title": "Procurement of RO Filtration Plants",
            "description": "Acquire 5 industrial grade RO units and transport to sites.",
            "target_completion_date": str(date.today() + timedelta(days=60)),
            "completion_percentage": 25,
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["sequence_number"], 1)
        self.assertEqual(response.data["status"], "PENDING")

    def test_ngo_milestone_submit_evidence_success_and_notification(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/<mid>/submit-evidence/ submits proof & notifies."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("1000000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )
        milestone = make_partnership_milestone(
            partnership=partnership,
            sequence_number=1,
            title="Procurement of RO units",
            status=MilestoneStatus.PENDING,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership.id}/milestones/{milestone.id}/submit-evidence/"
        evidence_file = make_dummy_uploaded_file(name="invoice_ro.pdf")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                url,
                {
                    "evidence_document": evidence_file,
                    "evidence_notes": "All 5 RO filtration units delivered and inspected at Amravati warehouse.",
                    "completion_percentage": 25,
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["status"], "SUBMITTED")
            self.assertTrue(response.data["has_evidence_document"])

        # Verify notification dispatched to Company Reviewer
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Evidence Ready for Verification", mail.outbox[0].subject)

    def test_ngo_milestone_submit_evidence_invalid_file_extension_fails_400(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/<mid>/submit-evidence/ rejects non-PDF/image files."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("1000000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )
        milestone = make_partnership_milestone(
            partnership=partnership,
            sequence_number=1,
            title="Procurement of RO units",
            status=MilestoneStatus.PENDING,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership.id}/milestones/{milestone.id}/submit-evidence/"
        bad_file = make_dummy_uploaded_file(name="proof.txt", content_type="text/plain")

        response = self.client.post(
            url,
            {
                "evidence_document": bad_file,
                "evidence_notes": "Invoice txt.",
                "completion_percentage": 50,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("evidence_document", response.data)

    def test_ngo_milestone_submit_evidence_mismatched_partnership_fails(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/<mid>/submit-evidence/ rejects mismatched partnership in URL."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership_1 = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("500000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )
        partnership_2 = make_csr_partnership(
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("500000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )
        milestone = make_partnership_milestone(
            partnership=partnership_1,
            sequence_number=1,
            title="Milestone 1",
            status=MilestoneStatus.PENDING,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        # Pass partnership_2 ID with milestone from partnership_1
        url = f"/api/v1/ngo/csr/partnerships/{partnership_2.id}/milestones/{milestone.id}/submit-evidence/"
        evidence_file = make_dummy_uploaded_file(name="invoice.pdf")

        response = self.client.post(
            url,
            {
                "evidence_document": evidence_file,
                "evidence_notes": "Completed work.",
                "completion_percentage": 20,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ==========================================================================
    # 5. Additional Edge Cases & Cross-NGO IDOR
    # ==========================================================================

    def test_ngo_requirement_put_update_success(self):
        """PUT /api/v1/ngo/csr/requirements/<id>/ performs full update on draft."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/"
        payload = {
            "title": "Solar Micro-Grids in Rural Maharashtra (Expanded)",
            "schedule_vii_category": ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY,
            "state": "Maharashtra",
            "district": "Gadchiroli",
            "location_scope": LocationScope.SPECIFIC_DISTRICT,
            "beneficiary_demographic": BeneficiaryDemographic.RURAL_COMMUNITIES,
            "target_beneficiary_count": 8000,
            "summary": "Expanded solar microgrids covering 15 villages.",
            "detailed_description": "Full detailed description of technical specifications.",
            "expected_outcomes": "Uninterrupted clean energy for 8000 villagers.",
            "total_estimated_budget": "800000.00",
            "required_csr_funding": "800000.00",
            "start_date": str(date.today() + timedelta(days=15)),
            "expected_completion_date": str(date.today() + timedelta(days=200)),
        }
        response = self.client.put(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Solar Micro-Grids in Rural Maharashtra (Expanded)")

    def test_ngo_requirement_put_other_ngo_404(self):
        """PUT /api/v1/ngo/csr/requirements/<id>/ on other NGO requirement returns 404."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_b.id}/"
        response = self.client.put(url, {"title": "Attempted Override"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ngo_requirement_delete_non_draft_fails(self):
        """DELETE /api/v1/ngo/csr/requirements/<id>/ fails with 409 on non-draft requirement."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_open_a.id}/"
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_ngo_requirement_upload_document_missing_file_400(self):
        """POST /api/v1/ngo/csr/requirements/<id>/upload-document/ fails with 400 when no files are uploaded."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/upload-document/"
        response = self.client.post(url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ngo_support_request_accept_idempotent(self):
        """POST /api/v1/ngo/csr/support-requests/<id>/accept/ is idempotent if already accepted."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/support-requests/{support_req.id}/accept/"
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ngo_milestone_create_invalid_sequence_400(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/ rejects sequence_number < 1."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            status=CSRPartnershipStatus.ACTIVE,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership.id}/milestones/"
        payload = {
            "sequence_number": 0,  # Invalid
            "title": "Invalid Milestone",
            "description": "Description",
            "target_completion_date": str(date.today() + timedelta(days=30)),
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ngo_milestone_create_duplicate_sequence_409(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/ rejects duplicate sequence_number."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            status=CSRPartnershipStatus.ACTIVE,
        )
        make_partnership_milestone(
            partnership=partnership,
            sequence_number=1,
            title="Existing Milestone 1",
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership.id}/milestones/"
        payload = {
            "sequence_number": 1,  # Duplicate
            "title": "Duplicate Milestone",
            "description": "Description",
            "target_completion_date": str(date.today() + timedelta(days=30)),
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    # ==========================================================================
    # 6. Additional Detailed Coverage per Step 12
    # ==========================================================================

    def test_ngo_requirement_submit_already_submitted_fails_409(self):
        """POST /api/v1/ngo/csr/requirements/<id>/submit/ returns 409 when already submitted/approved."""
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/requirements/{self.req_open_a.id}/submit/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_ngo_support_request_detail_own_success(self):
        """GET /api/v1/ngo/csr/support-requests/<id>/ returns 200 for own requirement's support request."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/support-requests/{support_req.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(support_req.id))

    def test_ngo_partnership_detail_own_success(self):
        """GET /api/v1/ngo/csr/partnerships/<id>/ returns 200 for own bilateral partnership."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership_a = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("1000000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership_a.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(partnership_a.id))

    def test_ngo_milestone_submit_evidence_invalid_percentage_400(self):
        """POST /api/v1/ngo/csr/partnerships/<id>/milestones/<mid>/submit-evidence/ rejects invalid completion_percentage (> 100 or <= 0)."""
        support_req = make_csr_support_request(
            company=self.company,
            requirement=self.req_open_a,
            proposed_funding=Decimal("1000000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )
        partnership = make_csr_partnership(
            support_request=support_req,
            company=self.company,
            ngo=self.ngo_profile_a,
            requirement=self.req_open_a,
            agreed_funding_amount=Decimal("1000000.00"),
            status=CSRPartnershipStatus.ACTIVE,
        )
        milestone = make_partnership_milestone(
            partnership=partnership,
            sequence_number=1,
            title="Procurement of RO units",
            status=MilestoneStatus.PENDING,
        )
        self.client.force_authenticate(user=self.ngo_user_a)
        url = f"/api/v1/ngo/csr/partnerships/{partnership.id}/milestones/{milestone.id}/submit-evidence/"
        evidence_file = make_dummy_uploaded_file(name="invoice_ro.pdf")

        response = self.client.post(
            url,
            {
                "evidence_document": evidence_file,
                "evidence_notes": "All RO units delivered.",
                "completion_percentage": 150,  # Invalid (> 100)
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ==========================================================================
    # 7. RBAC & Security Boundaries
    # ==========================================================================

    def test_unauthenticated_requests_fail(self):
        """Unauthenticated requests to NGO endpoints return 401 Unauthorized."""
        url = "/api/v1/ngo/csr/dashboard/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_role_access_denied(self):
        """Company or Donor users accessing NGO endpoints receive 403 Forbidden."""
        # 1. Company User
        self.client.force_authenticate(user=self.company_user)
        url = "/api/v1/ngo/csr/dashboard/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Donor User
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ==========================================================================
    # 8. Unapproved NGO Denial Tests (CSR-2.8.2-FIX)
    # ==========================================================================

    def test_unapproved_ngo_draft_denied_all_endpoints(self):
        """Unapproved NGO in DRAFT status receives 403 Forbidden on all 16 endpoints."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.DRAFT, is_active=False)
        self.client.force_authenticate(user=user)

        # 1. Dashboard (#21)
        res = self.client.get("/api/v1/ngo/csr/dashboard/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Requirements (#22 - #28)
        res = self.client.get("/api/v1/ngo/csr/requirements/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post("/api/v1/ngo/csr/requirements/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.get(f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.put(f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.delete(f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post(f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/submit/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post(f"/api/v1/ngo/csr/requirements/{self.req_draft_a.id}/upload-document/", {}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Support Requests (#29 - #32)
        res = self.client.get("/api/v1/ngo/csr/support-requests/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        dummy_id = uuid.uuid4()
        res = self.client.get(f"/api/v1/ngo/csr/support-requests/{dummy_id}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post(f"/api/v1/ngo/csr/support-requests/{dummy_id}/accept/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post(f"/api/v1/ngo/csr/support-requests/{dummy_id}/reject/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Partnerships & Milestones (#33 - #36)
        res = self.client.get("/api/v1/ngo/csr/partnerships/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.get(f"/api/v1/ngo/csr/partnerships/{dummy_id}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post(f"/api/v1/ngo/csr/partnerships/{dummy_id}/milestones/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post(f"/api/v1/ngo/csr/partnerships/{dummy_id}/milestones/{uuid.uuid4()}/submit-evidence/", {}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unapproved_ngo_rejected_denied(self):
        """Unapproved NGO in REJECTED status receives 403 Forbidden."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.REJECTED, is_active=False)
        self.client.force_authenticate(user=user)
        res = self.client.get("/api/v1/ngo/csr/dashboard/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unapproved_ngo_suspended_denied(self):
        """Unapproved NGO in SUSPENDED status receives 403 Forbidden."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.SUSPENDED, is_active=False)
        self.client.force_authenticate(user=user)
        res = self.client.get("/api/v1/ngo/csr/dashboard/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_ngo_denied(self):
        """NGO with is_active=False receives 403 Forbidden."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.APPROVED, is_active=False)
        self.client.force_authenticate(user=user)
        res = self.client.get("/api/v1/ngo/csr/dashboard/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)



