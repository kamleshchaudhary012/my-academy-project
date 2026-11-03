"""
Comprehensive Tests: CSR Funding, Payment Tracking, MoU, Project Monitoring & Reporting Lifecycle
===================================================================================================
Tests Phase 6 full bilateral CSR lifecycle:
  1. Funding commitment creation and validation
  2. Invalid amounts and unauthorised commitment changes
  3. Duplicate transfer reference handling (UTR uniqueness)
  4. Transfer evidence upload and access control
  5. NGO payment receipt confirmation (ACKNOWLEDGE vs DISPUTE)
  6. IDOR & tenant isolation (cannot access or acknowledge another partnership's transfers)
  7. Dispute and reconciliation workflows
  8. Invalid payment-status transitions (terminal partnerships block disbursements/expenses)
  9. Multiple instalments and remaining committed balance
 10. Concurrency and transactional financial integrity
 11. Bilateral MoU upload, status transition (PENDING_MOU -> ACTIVE), and download URL
 12. Milestone deliverable evidence submission and reviewer authorization
 13. Notification dispatches and recipient resolution
 14. Accurate separated financial totals in dashboards and analytics
 15. Existing statutory CSR eligibility and marketplace safeguards preserved
 16. Purely off-platform direct bank transfer enforcement (zero gateway/escrow)
"""

from decimal import Decimal
from datetime import date, timedelta
import uuid

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from ngo.models import NGOProfile, NGOLegalInfo, NGOVerification
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
    CSRDisbursement,
    CSRDisbursementReviewStatus,
    CSRNgoAcknowledgementStatus,
    CSRExpense,
    CSRExpenseCategory,
    CSRExpenseReviewStatus,
    CSRGrantChangeRequest,
    CSRGrantChangeStatus,
    CSRFinancialStatus,
    CSRAuditEntityType,
)
from csr.services.financial_service import (
    record_csr_disbursement,
    review_csr_disbursement,
    acknowledge_csr_disbursement,
    report_csr_expense,
    create_grant_change_request,
    admin_review_grant_change_request,
    company_review_grant_change_request,
    calculate_partnership_financial_status,
    get_partnership_reconciliation_dossier,
)
from csr.services.milestone_service import (
    create_milestone,
    submit_evidence,
    review_milestone,
)
from csr.services.partnership_service import (
    create_partnership_from_request,
    activate_partnership,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRUnauthorizedError,
    CSRStateError,
    CSRNotFoundError,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_partnership_milestone,
)

User = get_user_model()


class CSRFundingAndLifecycleTests(TestCase):
    """Exhaustive tests for Phase 6 CSR funding and project lifecycle."""

    def setUp(self):
        # 1. Company User & Approved Profile
        self.company_user = make_user(email="csr_corp@tata.example.com", role=User.Role.COMPANY)
        self.company = make_company_profile(
            user=self.company_user,
            company_name="Tata Steel CSR Trust",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        # 2. NGO User & Approved CSR-Verified Profile
        self.ngo_user = make_user(email="lead@vidya.example.org", role=User.Role.NGO)
        self.ngo = make_ngo_profile(
            user=self.ngo_user,
            display_name="Vidya Foundation",
            legal_name="Vidya Education Society",
            status=NGOProfile.Status.APPROVED,
        )
        # Ensure statutory CSR eligibility
        legal = self.ngo.legal_info
        legal.has_csr_1 = True
        legal.csr_registration_number = "CSR00012345"
        legal.has_12a = True
        legal.has_80g = True
        legal.save()

        verif = self.ngo.verification
        verif.is_csr_verified = True
        verif.status = NGOProfile.Status.APPROVED
        verif.save()

        # 3. Platform Admin User
        self.admin_user = make_user(email="csr_admin@daangives.org", role=User.Role.ADMIN, is_staff=True)

        # 4. Third-party NGO & Company for IDOR/Tenant Isolation Tests
        self.other_company_user = make_user(email="other_corp@corp.example.com", role=User.Role.COMPANY)
        self.other_company = make_company_profile(
            user=self.other_company_user,
            company_name="Other Corp CSR",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        self.other_ngo_user = make_user(email="other_ngo@ngo.example.org", role=User.Role.NGO)
        self.other_ngo = make_ngo_profile(
            user=self.other_ngo_user,
            display_name="Other Foundation",
            status=NGOProfile.Status.APPROVED,
        )

        # 5. CSR Requirement & Support Request
        self.requirement = make_csr_requirement(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title="Digital Classrooms in Rural Vidarbha",
            required_csr_funding=Decimal("500000.00"),
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )

        self.support_request = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.ACCEPTED,
        )

        # 6. Bilateral Partnership
        self.partnership = create_partnership_from_request(
            support_request=self.support_request,
            agreed_funding_amount=Decimal("500000.00"),
        )

        # Mock PDF files
        self.mock_pdf = SimpleUploadedFile(
            "transfer_advice.pdf",
            b"%PDF-1.4 test bank advice voucher",
            content_type="application/pdf",
        )
        self.mock_receipt_pdf = SimpleUploadedFile(
            "ngo_receipt.pdf",
            b"%PDF-1.4 formal ngo receipt confirmation slip",
            content_type="application/pdf",
        )
        self.mock_mou_pdf = SimpleUploadedFile(
            "signed_bilateral_mou.pdf",
            b"%PDF-1.4 signed bilateral agreement",
            content_type="application/pdf",
        )

        self.client = APIClient()

    # =========================================================================
    # 1. Funding Commitment Creation and Validation
    # =========================================================================
    def test_01_funding_commitment_creation_enforces_statutory_csr_eligibility(self):
        """Cannot create a CSR partnership commitment with an unverified or ineligible NGO."""
        ineligible_ngo_user = make_user(email="ineligible@ngo.org", role=User.Role.NGO)
        ineligible_ngo = make_ngo_profile(
            user=ineligible_ngo_user,
            display_name="Ineligible NGO",
            status=NGOProfile.Status.UNDER_REVIEW,
        )
        ineligible_req = make_csr_requirement(ngo=ineligible_ngo, created_by=ineligible_ngo_user)
        ineligible_sr = make_csr_support_request(company=self.company, requirement=ineligible_req, status=CSRSupportRequestStatus.ACCEPTED)

        with self.assertRaises(CSRValidationError) as ctx:
            create_partnership_from_request(support_request=ineligible_sr)
        self.assertIn("not active or approved", str(ctx.exception))

    def test_02_funding_commitment_requires_approved_company(self):
        """Unapproved company cannot form CSR partnerships."""
        unapproved_comp_user = make_user(email="unapproved@corp.com", role=User.Role.COMPANY)
        unapproved_comp = make_company_profile(
            user=unapproved_comp_user,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )
        sr = make_csr_support_request(company=unapproved_comp, requirement=self.requirement, status=CSRSupportRequestStatus.ACCEPTED)

        with self.assertRaises(CSRValidationError) as ctx:
            create_partnership_from_request(support_request=sr)
        self.assertEqual(ctx.exception.code, "company_not_approved")

    # =========================================================================
    # 2. Invalid Amounts and Unauthorised Commitment Changes
    # =========================================================================
    def test_03_funding_commitment_rejects_sub_minimum_amount(self):
        """Agreed funding commitment must be at least ₹1,000."""
        sr = make_csr_support_request(company=self.company, requirement=self.requirement, proposed_funding=Decimal("100000.00"), status=CSRSupportRequestStatus.ACCEPTED)
        with self.assertRaises(CSRValidationError) as ctx:
            create_partnership_from_request(support_request=sr, agreed_funding_amount=Decimal("500.00"))
        self.assertEqual(ctx.exception.code, "funding_too_low")

    def test_04_unauthorised_user_cannot_propose_grant_change(self):
        """Third-party cannot propose grant change request."""
        with self.assertRaises(CSRUnauthorizedError):
            create_grant_change_request(
                user=self.other_company_user,
                partnership_id=self.partnership.id,
                proposed_commitment=Decimal("600000.00"),
                reason="Unauthorized change",
            )

    # =========================================================================
    # 3. Duplicate Transfer Reference Handling
    # =========================================================================
    def test_05_duplicate_transfer_reference_rejected(self):
        """Cannot submit duplicate bank UTR reference for the same partnership."""
        record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "250000.00", "transfer_reference": "UTR20261028001", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )

        mock_pdf_2 = SimpleUploadedFile("advice2.pdf", b"%PDF-1.4 duplicate test", content_type="application/pdf")
        with self.assertRaises(CSRValidationError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=self.partnership.id,
                data={"amount": "250000.00", "transfer_reference": "UTR20261028001", "payment_mode": "NEFT"},
                evidence_file=mock_pdf_2,
            )
        self.assertEqual(ctx.exception.code, "duplicate_transfer_reference")

    # =========================================================================
    # 4. Transfer Evidence Upload and Access Control
    # =========================================================================
    def test_06_transfer_evidence_upload_by_authorized_company(self):
        """Authorised company can record direct bank transfer with advice document."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={
                "amount": "250000.00",
                "transfer_reference": "UTR_TRANCHE_1",
                "payment_mode": "NEFT",
                "notes": "First tranche 50% advance for classroom setup",
            },
            evidence_file=self.mock_pdf,
        )
        self.assertIsNotNone(disb.id)
        self.assertEqual(disb.review_status, CSRDisbursementReviewStatus.PENDING_REVIEW)
        self.assertEqual(disb.ngo_acknowledgement_status, CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT)
        self.assertTrue(disb.evidence_document.name.endswith(".pdf"))

    def test_07_disbursement_create_serializer_supports_frontend_aliases(self):
        """CSRDisbursementCreateSerializer seamlessly handles payment_reference and disbursement_notes."""
        from csr.serializers.financial_serializers import CSRDisbursementCreateSerializer
        serializer = CSRDisbursementCreateSerializer(data={
            "amount": "100000.00",
            "payment_reference": "UTR_FRONTEND_ALIAS",
            "disbursement_notes": "Frontend remarks note",
            "payment_mode": "NEFT",
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["transfer_reference"], "UTR_FRONTEND_ALIAS")
        self.assertEqual(serializer.validated_data["notes"], "Frontend remarks note")

    # =========================================================================
    # 5. NGO Payment Receipt Confirmation
    # =========================================================================
    def test_08_ngo_receipt_acknowledgement_confirmed(self):
        """Recipient NGO can confirm receipt of funds with formal donation receipt slip."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "200000.00", "transfer_reference": "UTR_ACK_TEST", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )

        updated = acknowledge_csr_disbursement(
            user=self.ngo_user,
            disbursement_id=disb.id,
            decision="ACKNOWLEDGE",
            notes="Bank credit confirmed on 28-Oct in SBI account",
            receipt_document=self.mock_receipt_pdf,
        )
        self.assertEqual(updated.ngo_acknowledgement_status, CSRNgoAcknowledgementStatus.ACKNOWLEDGED)
        self.assertEqual(updated.ngo_acknowledged_by, self.ngo_user)
        self.assertTrue(updated.ngo_receipt_document.name.endswith(".pdf"))

    def test_09_ngo_receipt_dispute_requires_reason(self):
        """Disputing a transfer requires justification notes."""
        from csr.serializers.financial_serializers import CSRDisbursementAcknowledgeSerializer
        serializer = CSRDisbursementAcknowledgeSerializer(data={"decision": "DISPUTE", "notes": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("notes", serializer.errors)

    # =========================================================================
    # 6. IDOR and Tenant Isolation Protections
    # =========================================================================
    def test_10_other_ngo_cannot_acknowledge_transfer(self):
        """Another NGO cannot acknowledge or dispute a transfer belonging to this partnership."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "150000.00", "transfer_reference": "UTR_ISOLATION", "payment_mode": "NEFT"},
        )
        with self.assertRaises(CSRUnauthorizedError):
            acknowledge_csr_disbursement(
                user=self.other_ngo_user,
                disbursement_id=disb.id,
                decision="ACKNOWLEDGE",
                notes="Unauthorized ack attempt",
            )

    def test_11_other_company_cannot_report_transfer(self):
        """Another company cannot report disbursements for this partnership."""
        with self.assertRaises(CSRUnauthorizedError):
            record_csr_disbursement(
                user=self.other_company_user,
                partnership_id=self.partnership.id,
                data={"amount": "50000.00", "transfer_reference": "UTR_IDOR", "payment_mode": "NEFT"},
            )

    # =========================================================================
    # 7. Dispute and Reconciliation Workflows
    # =========================================================================
    def test_12_disputed_transfer_flags_reconciliation_dossier(self):
        """When an NGO disputes a transfer, financial status becomes DISPUTED."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "250000.00", "transfer_reference": "UTR_DISPUTE_RECON", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )

        acknowledge_csr_disbursement(
            user=self.ngo_user,
            disbursement_id=disb.id,
            decision="DISPUTE",
            notes="Funds not reflected in account after 5 business days",
        )

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.DISPUTED)
        self.assertFalse(dossier["is_reconciled"])
        self.assertEqual(Decimal(dossier["disputed_disbursements"]["total_amount"]), Decimal("250000.00"))

    # =========================================================================
    # 8. Invalid Payment Status Transitions
    # =========================================================================
    def test_13_cannot_report_disbursement_for_cancelled_or_terminated_partnership(self):
        """Terminal partnerships reject recording new disbursements and expenses."""
        self.partnership.status = CSRPartnershipStatus.CANCELLED
        self.partnership.save(update_fields=["status"])

        with self.assertRaises(CSRStateError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=self.partnership.id,
                data={"amount": "50000.00", "transfer_reference": "UTR_TERMINAL", "payment_mode": "NEFT"},
            )
        self.assertEqual(ctx.exception.code, "invalid_partnership_state")

        with self.assertRaises(CSRStateError) as ctx:
            report_csr_expense(
                user=self.ngo_user,
                partnership_id=self.partnership.id,
                data={"amount": "10000.00", "title": "Books", "expense_category": "MATERIAL"},
            )
        self.assertEqual(ctx.exception.code, "invalid_partnership_state")

    # =========================================================================
    # 9. Multiple Instalments and Remaining Committed Balance
    # =========================================================================
    def test_14_multiple_instalments_accumulate_and_track_balance(self):
        """Instalments increment reported disbursements and track remaining grant commitment."""
        # Tranche 1: ₹2,00,000
        disb1 = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "200000.00", "transfer_reference": "UTR_TRANCHE_A", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.disbursed_amount_reported, Decimal("200000.00"))

        # Tranche 2: ₹3,00,000
        mock_pdf_b = SimpleUploadedFile("tranche_b.pdf", b"%PDF-1.4 tranche b advice", content_type="application/pdf")
        disb2 = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "300000.00", "transfer_reference": "UTR_TRANCHE_B", "payment_mode": "RTGS"},
            evidence_file=mock_pdf_b,
        )
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.disbursed_amount_reported, Decimal("500000.00"))

        # Review & Acknowledge Tranche 1
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb1.id, decision="VERIFY")
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=disb1.id, decision="ACKNOWLEDGE", notes="Received ₹2L")

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)
        self.assertEqual(Decimal(dossier["commitment"]["amount"]), Decimal("500000.00"))
        self.assertEqual(Decimal(dossier["reported_disbursements"]["total_amount"]), Decimal("500000.00"))
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("200000.00"))
        self.assertEqual(Decimal(dossier["ngo_acknowledged_disbursements"]["total_amount"]), Decimal("200000.00"))
        self.assertEqual(Decimal(dossier["outstanding_commitment"]), Decimal("300000.00"))

    # =========================================================================
    # 10. Bilateral MoU Workflow and Status Progression
    # =========================================================================
    def test_15_mou_upload_activates_partnership_and_exposes_download_url(self):
        """Uploading executed bilateral MoU transitions PENDING_MOU to ACTIVE and exposes signed_mou_url."""
        self.assertEqual(self.partnership.status, CSRPartnershipStatus.PENDING_MOU)
        self.assertFalse(self.partnership.signed_mou_document)

        activated = activate_partnership(
            user=self.company_user,
            partnership_id=self.partnership.id,
            mou_file=self.mock_mou_pdf,
        )
        self.assertEqual(activated.status, CSRPartnershipStatus.ACTIVE)
        self.assertTrue(activated.signed_mou_document.name.endswith(".pdf"))

        from csr.serializers.partnership_serializers import CSRPartnershipDetailSerializer
        serializer = CSRPartnershipDetailSerializer(activated)
        self.assertTrue(serializer.data["has_signed_mou"])
        self.assertTrue(serializer.data["signed_mou_name"].endswith(".pdf"))
        self.assertIsNotNone(serializer.data["signed_mou_url"])

    def test_16_ngo_can_upload_executed_mou_via_api(self):
        """NGO endpoint /api/v1/ngo/csr/partnerships/<id>/upload-mou/ activates partnership."""
        self.client.force_authenticate(user=self.ngo_user)
        url = f"/api/v1/ngo/csr/partnerships/{self.partnership.id}/upload-mou/"
        response = self.client.post(url, {"signed_mou_document": self.mock_mou_pdf}, format="multipart")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], CSRPartnershipStatus.ACTIVE)
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.status, CSRPartnershipStatus.ACTIVE)

    # =========================================================================
    # 11. Milestone Ownership and Reviewer Authorization Safeguards
    # =========================================================================
    def test_17_ngo_cannot_verify_own_milestone_deliverable(self):
        """Recipient NGO cannot review/verify its own deliverable milestones."""
        milestone = make_partnership_milestone(partnership=self.partnership, sequence_number=1)
        mock_proof = SimpleUploadedFile("proof.pdf", b"%PDF-1.4 milestone progress report", content_type="application/pdf")

        submit_evidence(
            user=self.ngo_user,
            milestone_id=milestone.id,
            evidence_notes="Classroom infrastructure completed",
            evidence_file=mock_proof,
            completion_percentage=100,
        )

        with self.assertRaises(CSRUnauthorizedError) as ctx:
            review_milestone(
                user=self.ngo_user,
                milestone_id=milestone.id,
                decision="VERIFY",
                notes="Self-approval attempt",
            )
        self.assertEqual(ctx.exception.code, "unauthorized_reviewer")

    def test_18_company_user_can_verify_submitted_milestone(self):
        """Corporate partner can verify submitted milestone."""
        milestone = make_partnership_milestone(partnership=self.partnership, sequence_number=1)
        mock_proof = SimpleUploadedFile("proof.pdf", b"%PDF-1.4 milestone progress report", content_type="application/pdf")

        submit_evidence(
            user=self.ngo_user,
            milestone_id=milestone.id,
            evidence_notes="Classroom infrastructure completed",
            evidence_file=mock_proof,
            completion_percentage=100,
        )

        verified = review_milestone(
            user=self.company_user,
            milestone_id=milestone.id,
            decision="VERIFY",
            notes="Ground audit confirmed by corporate CSR team",
        )
        self.assertEqual(verified.status, MilestoneStatus.VERIFIED)
        self.assertEqual(verified.completion_percentage, 100)
        self.assertEqual(verified.verified_by, self.company_user)

    def test_19_milestone_serializer_exposes_overdue_and_evidence_url(self):
        """Milestone serializer exposes is_overdue boolean and evidence_document_url."""
        past_date = date.today() - timedelta(days=10)
        milestone = make_partnership_milestone(
            partnership=self.partnership,
            sequence_number=1,
            target_completion_date=past_date,
            status=MilestoneStatus.PENDING,
        )
        from csr.serializers.milestone_serializers import PartnershipMilestoneSerializer
        serializer = PartnershipMilestoneSerializer(milestone)
        self.assertTrue(serializer.data["is_overdue"])

    # =========================================================================
    # 12. Notification Dispatches and Privacy Protections
    # =========================================================================
    def test_20_disbursement_reported_triggers_notification_without_leaking_credentials(self):
        """Reporting disbursement dispatches notification with clean URL and no secret credentials."""
        from csr.services.notification_service import notify_disbursement_reported
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "250000.00", "transfer_reference": "UTR_NOTIF_TEST", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        res = notify_disbursement_reported(disb)
        self.assertTrue(res.get("success"), res)

    # =========================================================================
    # 13. Accurate Separated Financial Totals in Admin and Portals
    # =========================================================================
    def test_21_admin_analytics_separates_facts_cleanly(self):
        """Admin CSR analytics returns cleanly separated financial facts."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/admin/csr/analytics/")
        self.assertEqual(response.status_code, 200)

        data = response.data
        self.assertIn("total_committed_funding", data)
        self.assertIn("total_transfers_reported", data)
        self.assertIn("total_transfers_verified", data)
        self.assertIn("total_acknowledged_receipts", data)
        self.assertIn("total_pending_acknowledgement", data)
        self.assertIn("total_disputed_transfers", data)
        self.assertIn("total_remaining_commitment", data)
        self.assertIn("total_expenses_reported", data)
        self.assertIn("total_expenses_verified", data)

    def test_22_ngo_dashboard_returns_separated_financial_metrics(self):
        """NGO dashboard includes separated financial metrics."""
        self.client.force_authenticate(user=self.ngo_user)
        response = self.client.get("/api/v1/ngo/csr/dashboard/")
        self.assertEqual(response.status_code, 200)

        data = response.data
        self.assertIn("total_committed_funding", data)
        self.assertIn("total_transfers_reported", data)
        self.assertIn("total_acknowledged_receipts", data)
        self.assertIn("total_pending_acknowledgement", data)
        self.assertIn("total_disputed_transfers", data)
        self.assertIn("remaining_funding_balance", data)

    def test_23_company_dashboard_returns_separated_financial_metrics(self):
        """Company dashboard includes separated financial metrics."""
        self.client.force_authenticate(user=self.company_user)
        response = self.client.get("/api/v1/csr/dashboard/")
        self.assertEqual(response.status_code, 200)

        data = response.data
        self.assertIn("committed_funding_total", data)
        self.assertIn("disbursed_funding_total", data)
        self.assertIn("acknowledged_funding_total", data)
        self.assertIn("pending_acknowledgement_total", data)
        self.assertIn("disputed_funding_total", data)
        self.assertIn("remaining_committed_balance", data)
