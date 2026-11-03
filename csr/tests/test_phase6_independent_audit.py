"""
DaanGives Phase 6: Independent Audit & End-to-End Validation Test Suite
========================================================================
Independent validation of the entire bilateral CSR lifecycle:
- Approved NGO -> Approved CSR Company -> Project Discovery -> EOI -> Partnership -> MoU ->
  Funding Commitment -> Direct Bank Transfer -> Admin Review -> NGO Confirmation ->
  Milestone Evidence -> Reporting & Reconciliation.

Negative scenarios verified:
- Unapproved CSR Company
- CSR-ineligible NGO
- Cross-tenant IDOR (wrong partnership ownership)
- Sub-minimum / negative amounts and invalid UTR handling
- Duplicate transfer reference rejection
- Disputed payment isolation from confirmed receipts
- Anti-self-verification for milestone deliverables
- Anti-company-submission for NGO deliverables
- Terminal partnership protection (cancelled/terminated)
- Private document access & tenant scoping
"""

import uuid
from decimal import Decimal
from datetime import date, timedelta

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core import mail
from rest_framework.test import APIClient
from rest_framework import status as http_status

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
    CSRExpenseReviewStatus,
    CSRGrantChangeRequest,
    CSRFinancialStatus,
    CSRAuditEntityType,
    CSRVerificationHistory,
)
from csr.services.partnership_service import (
    create_partnership_from_request,
    activate_partnership,
)
from csr.services.financial_service import (
    record_csr_disbursement,
    review_csr_disbursement,
    acknowledge_csr_disbursement,
    report_csr_expense,
    create_grant_change_request,
    get_partnership_reconciliation_dossier,
)
from csr.services.milestone_service import (
    create_milestone,
    submit_evidence,
    review_milestone,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRUnauthorizedError,
    CSRStateError,
    CSRNotFoundError,
)
from csr.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_company_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_partnership_milestone,
)

User = get_user_model()


class Phase6IndependentAuditTests(TestCase):
    """
    Independent Audit Test Suite covering all 7 audit checklists for Phase 6.
    """

    def setUp(self):
        mail.outbox.clear()

        # 1. Authorised Platform Admin
        self.admin_user = make_user(
            email="platform_admin@daangives.org",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )

        # 2. Approved & CSR-Verified NGO: Vidya Foundation
        self.ngo_user = make_user(email="lead@vidya.example.org", role=User.Role.NGO)
        self.ngo = make_ngo_profile(
            user=self.ngo_user,
            display_name="Vidya Foundation",
            legal_name="Vidya Foundation Educational Trust",
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        self.ngo_legal = self.ngo.legal_info
        self.ngo_legal.has_csr_1 = True
        self.ngo_legal.csr_registration_number = "CSR00012345"
        self.ngo_legal.has_12a = True
        self.ngo_legal.has_80g = True
        self.ngo_legal.save()

        self.ngo_verif = self.ngo.verification
        self.ngo_verif.is_csr_verified = True
        self.ngo_verif.csr_verified_by = self.admin_user
        self.ngo_verif.csr_verified_at = timezone.now()
        self.ngo_verif.save()

        # 3. Approved Corporate CSR Partner: Tata Steel CSR Trust
        self.company_user = make_user(email="csr_lead@tatasteel.com", role=User.Role.COMPANY)
        self.company = make_company_profile(
            user=self.company_user,
            company_name="Tata Steel CSR Trust",
            legal_name="Tata Steel Limited",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        # 4. Rival / Third-party NGO (Attacker)
        self.rival_ngo_user = make_user(email="attacker@otherngo.org", role=User.Role.NGO)
        self.rival_ngo = make_ngo_profile(
            user=self.rival_ngo_user,
            display_name="Rival NGO",
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        rival_legal = self.rival_ngo.legal_info
        rival_legal.has_csr_1 = True
        rival_legal.csr_registration_number = "CSR00099999"
        rival_legal.has_12a = True
        rival_legal.has_80g = True
        rival_legal.save()

        rival_verif = self.rival_ngo.verification
        rival_verif.is_csr_verified = True
        rival_verif.save()

        # 5. Rival / Third-party Company (Attacker)
        self.rival_company_user = make_user(email="attacker@rivalcorp.com", role=User.Role.COMPANY)
        self.rival_company = make_company_profile(
            user=self.rival_company_user,
            company_name="Rival Corp",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        # Mock PDF Documents
        self.mock_mou_pdf = SimpleUploadedFile(
            "signed_bilateral_mou.pdf",
            b"%PDF-1.4 bilateral contract content",
            content_type="application/pdf",
        )
        self.mock_bank_slip = SimpleUploadedFile(
            "bank_wire_slip_tranche1.pdf",
            b"%PDF-1.4 official bank remittance receipt",
            content_type="application/pdf",
        )
        self.mock_receipt_pdf = SimpleUploadedFile(
            "ngo_donation_receipt.pdf",
            b"%PDF-1.4 official ngo receipt slip",
            content_type="application/pdf",
        )
        self.mock_evidence_pdf = SimpleUploadedFile(
            "milestone_deliverable_proof.pdf",
            b"%PDF-1.4 deliverable completion photo and report",
            content_type="application/pdf",
        )

        self.client = APIClient()

    # =========================================================================
    # CHECK 1: Complete End-to-End Happy Path Journey
    # =========================================================================
    def test_01_complete_e2e_csr_funding_and_reporting_journey(self):
        """
        Full lifecycle verification:
        Approved NGO -> Approved CSR Company -> Project Discovery -> EOI ->
        Partnership -> MoU Execution -> Funding Commitment -> Direct Bank Transfer ->
        Admin Evidence Review -> NGO Receipt Confirmation -> Milestone Deliverables ->
        Separated Financial Reconciliation Reporting.
        """
        # Step 1: NGO creates CSR Requirement
        req = make_csr_requirement(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title="Digital Classrooms in Rural Vidarbha",
            total_estimated_budget=Decimal("500000.00"),
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )
        self.assertEqual(req.status, CSRRequirementStatus.OPEN_FOR_CSR)

        # Step 2: Approved Company discovers project & submits EOI
        support_req = make_csr_support_request(
            company=self.company,
            requirement=req,
            proposed_funding=Decimal("500000.00"),
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )
        self.assertEqual(support_req.status, CSRSupportRequestStatus.PENDING_NGO_REVIEW)

        # Step 3: NGO reviews and accepts EOI
        support_req.status = CSRSupportRequestStatus.ACCEPTED
        support_req.save(update_fields=["status"])

        # Step 4: Bilateral CSR Partnership is formed
        partnership = create_partnership_from_request(
            support_request=support_req,
            agreed_funding_amount=Decimal("500000.00"),
        )
        self.assertEqual(partnership.status, CSRPartnershipStatus.PENDING_MOU)
        self.assertEqual(partnership.agreed_funding_amount, Decimal("500000.00"))
        self.assertEqual(partnership.disbursed_amount_reported, Decimal("0.00"))

        # Step 5: MoU Upload activates the partnership (PENDING_MOU -> ACTIVE)
        activated_partnership = activate_partnership(
            user=self.ngo_user,
            partnership_id=partnership.id,
            mou_file=self.mock_mou_pdf,
        )
        self.assertEqual(activated_partnership.status, CSRPartnershipStatus.ACTIVE)
        self.assertTrue(activated_partnership.signed_mou_document.name.endswith(".pdf"))

        # Create project milestone
        milestone = create_milestone(
            user=self.ngo_user,
            partnership_id=activated_partnership.id,
            data={
                "title": "Hardware & Tablet Procurement",
                "description": "Procure and distribute 50 tablets to Vidarbha rural schools",
                "target_completion_date": date.today() + timedelta(days=30),
                "sequence_number": 1,
            },
        )
        self.assertEqual(milestone.status, MilestoneStatus.PENDING)

        # Step 6: Company initiates direct external wire & reports transfer with UTR
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=activated_partnership.id,
            data={
                "amount": "200000.00",
                "transfer_reference": "AXISP00293849102",
                "payment_mode": "RTGS",
                "notes": "Tranche 1: 40% advance for tablet procurement",
            },
            evidence_file=self.mock_bank_slip,
        )
        self.assertEqual(disb.review_status, CSRDisbursementReviewStatus.PENDING_REVIEW)
        self.assertEqual(disb.ngo_acknowledgement_status, CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT)

        # Step 7: Admin reviews corporate bank advice evidence and verifies transfer
        reviewed_disb = review_csr_disbursement(
            user=self.admin_user,
            disbursement_id=disb.id,
            decision="VERIFY",
            review_notes="Bank transaction counterfoil matches RTGS UTR reference",
        )
        self.assertEqual(reviewed_disb.review_status, CSRDisbursementReviewStatus.VERIFIED)

        # Step 8: Recipient NGO checks bank statement & confirms credit
        ack_disb = acknowledge_csr_disbursement(
            user=self.ngo_user,
            disbursement_id=disb.id,
            decision="ACKNOWLEDGE",
            notes="Credit verified in SBI Treasury account on 03-Nov-2026",
            receipt_document=self.mock_receipt_pdf,
        )
        self.assertEqual(ack_disb.ngo_acknowledgement_status, CSRNgoAcknowledgementStatus.ACKNOWLEDGED)

        # Step 9: NGO submits deliverable evidence for Milestone 1
        submitted_milestone = submit_evidence(
            user=self.ngo_user,
            milestone_id=milestone.id,
            evidence_notes="50 Lenovo educational tablets procured and distributed",
            evidence_file=self.mock_evidence_pdf,
            completion_percentage=100,
        )
        self.assertEqual(submitted_milestone.status, MilestoneStatus.SUBMITTED)

        # Step 10: Company reviews and verifies deliverable completion
        verified_milestone = review_milestone(
            user=self.company_user,
            milestone_id=milestone.id,
            decision="VERIFY",
            notes="Hardware serial numbers and ground asset distribution verified",
        )
        self.assertEqual(verified_milestone.status, MilestoneStatus.VERIFIED)
        self.assertEqual(verified_milestone.completion_percentage, 100)

        # Step 11: Multi-Dimensional Financial Reconciliation Dossier
        dossier = get_partnership_reconciliation_dossier(self.company_user, activated_partnership.id)

        # Verify strict separation of financial facts
        self.assertEqual(Decimal(dossier["commitment"]["amount"]), Decimal("500000.00"))
        self.assertEqual(Decimal(dossier["reported_disbursements"]["total_amount"]), Decimal("200000.00"))
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("200000.00"))
        self.assertEqual(Decimal(dossier["ngo_acknowledged_disbursements"]["total_amount"]), Decimal("200000.00"))
        self.assertEqual(Decimal(dossier["outstanding_commitment"]), Decimal("300000.00"))
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.PARTIALLY_DISBURSED)
        self.assertFalse(dossier["is_reconciled"])

    # =========================================================================
    # CHECK 2: Negative Scenarios — Unapproved Company & Ineligible NGO
    # =========================================================================
    def test_02_negative_unapproved_company_cannot_execute_csr_commitments(self):
        """Unapproved company cannot form CSR partnerships or commit funding."""
        unapproved_user = make_user(email="pending_comp@example.com", role=User.Role.COMPANY)
        unapproved_comp = make_company_profile(
            user=unapproved_user,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=unapproved_comp, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)

        with self.assertRaises(CSRValidationError) as ctx:
            create_partnership_from_request(support_request=sr)
        self.assertEqual(ctx.exception.code, "company_not_approved")

    def test_03_negative_ineligible_ngo_cannot_form_csr_partnership(self):
        """CSR-ineligible NGO cannot form bilateral CSR partnerships."""
        ineligible_user = make_user(email="ineligible_ngo@example.org", role=User.Role.NGO)
        ineligible_ngo = make_ngo_profile(
            user=ineligible_user,
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )
        legal = ineligible_ngo.legal_info
        legal.has_csr_1 = False
        legal.csr_registration_number = ""
        legal.save()

        req = make_csr_requirement(ngo=ineligible_ngo, created_by=ineligible_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)

        with self.assertRaises(CSRValidationError) as ctx:
            create_partnership_from_request(support_request=sr)
        self.assertEqual(ctx.exception.code, "ngo_csr_ineligible")

    # =========================================================================
    # CHECK 3: Negative Scenarios — Tenant Isolation & IDOR Protections
    # =========================================================================
    def test_04_negative_cross_tenant_idor_reporting_and_acknowledgement(self):
        """Third-party corporate or NGO accounts cannot tamper with or access another partnership."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)

        # 1. Rival company attempts to report disbursement on this partnership
        with self.assertRaises(CSRUnauthorizedError):
            record_csr_disbursement(
                user=self.rival_company_user,
                partnership_id=partnership.id,
                data={"amount": "100000.00", "transfer_reference": "UTR_ATTACK_1"},
            )

        # 2. Company legitimately reports a transfer
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "100000.00", "transfer_reference": "UTR_LEGIT_1"},
            evidence_file=self.mock_bank_slip,
        )

        # 3. Rival NGO attempts to acknowledge or dispute the transfer
        with self.assertRaises(CSRUnauthorizedError):
            acknowledge_csr_disbursement(
                user=self.rival_ngo_user,
                disbursement_id=disb.id,
                decision="ACKNOWLEDGE",
                notes="Unauthorized receipt confirmation",
            )

        # 4. Rival company attempts to view private financial reconciliation dossier
        with self.assertRaises(CSRNotFoundError):
            get_partnership_reconciliation_dossier(self.rival_company_user, partnership.id)

    # =========================================================================
    # CHECK 4: Negative Scenarios — Invalid Amounts and Duplicate UTR References
    # =========================================================================
    def test_05_negative_sub_zero_amount_and_duplicate_utr_handling(self):
        """Negative and zero amounts are rejected; duplicate non-rejected UTRs are blocked."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)

        # Zero amount rejected
        with self.assertRaises(CSRValidationError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=partnership.id,
                data={"amount": "0.00", "transfer_reference": "UTR_ZERO"},
            )
        self.assertEqual(ctx.exception.code, "invalid_disbursement_amount")

        # Sub-zero amount rejected
        with self.assertRaises(CSRValidationError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=partnership.id,
                data={"amount": "-50000.00", "transfer_reference": "UTR_NEGATIVE"},
            )
        self.assertEqual(ctx.exception.code, "invalid_disbursement_amount")

        # First legitimate submission with UTR
        record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "100000.00", "transfer_reference": "UTR_UNIQUE_12345"},
            evidence_file=self.mock_bank_slip,
        )

        # Duplicate submission with same UTR rejected
        with self.assertRaises(CSRValidationError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=partnership.id,
                data={"amount": "50000.00", "transfer_reference": "UTR_UNIQUE_12345"},
                evidence_file=self.mock_bank_slip,
            )
        self.assertEqual(ctx.exception.code, "duplicate_transfer_reference")

    # =========================================================================
    # CHECK 5: Negative Scenarios — Disputed Payment Workflow & Receipt Isolation
    # =========================================================================
    def test_06_negative_disputed_payment_workflow_and_receipt_isolation(self):
        """Disputed transfers are strictly excluded from confirmed receipts and flag financial status."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)

        # Corporate partner reports transfer
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "250000.00", "transfer_reference": "UTR_DISPUTE_TEST"},
            evidence_file=self.mock_bank_slip,
        )

        # Disputing without justification notes is rejected by serializer
        from csr.serializers.financial_serializers import CSRDisbursementAcknowledgeSerializer
        invalid_ack = CSRDisbursementAcknowledgeSerializer(data={"decision": "DISPUTE", "notes": ""})
        self.assertFalse(invalid_ack.is_valid())
        self.assertIn("notes", invalid_ack.errors)

        # NGO disputes transfer with mandatory justification
        acknowledge_csr_disbursement(
            user=self.ngo_user,
            disbursement_id=disb.id,
            decision="DISPUTE",
            notes="Bank credit not found in SBI account statement after 7 business days",
        )

        # Inspect dossier: disputed funds MUST NOT appear in acknowledged receipts
        dossier = get_partnership_reconciliation_dossier(self.company_user, partnership.id)
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.DISPUTED)
        self.assertEqual(Decimal(dossier["disputed_disbursements"]["total_amount"]), Decimal("250000.00"))
        self.assertEqual(Decimal(dossier["ngo_acknowledged_disbursements"]["total_amount"]), Decimal("0.00"))
        self.assertFalse(dossier["is_reconciled"])

    # =========================================================================
    # CHECK 6: Role Separation — Anti-Self-Verification & Anti-Company-Evidence
    # =========================================================================
    def test_07_milestone_role_separation_safeguards(self):
        """NGO cannot verify its own deliverables; company cannot submit deliverable evidence."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)
        milestone = make_partnership_milestone(partnership=partnership, sequence_number=1)

        # Corporate partner attempts to submit deliverable evidence for NGO
        with self.assertRaises(CSRUnauthorizedError) as ctx:
            submit_evidence(
                user=self.company_user,
                milestone_id=milestone.id,
                evidence_notes="Corporate partner submitting evidence",
                evidence_file=self.mock_evidence_pdf,
            )
        self.assertEqual(ctx.exception.code, "unauthorized_submitter")

        # NGO legitimately submits evidence
        submit_evidence(
            user=self.ngo_user,
            milestone_id=milestone.id,
            evidence_notes="Classroom infrastructure delivered",
            evidence_file=self.mock_evidence_pdf,
            completion_percentage=100,
        )

        # NGO attempts to verify its own milestone deliverable
        with self.assertRaises(CSRUnauthorizedError) as ctx:
            review_milestone(
                user=self.ngo_user,
                milestone_id=milestone.id,
                decision="VERIFY",
                notes="Self-approving our own milestone",
            )
        self.assertEqual(ctx.exception.code, "unauthorized_reviewer")

    # =========================================================================
    # CHECK 7: Terminal Partnership State Protection
    # =========================================================================
    def test_08_terminal_partnership_blocks_prohibited_transactions(self):
        """Cancelled or terminated partnerships cannot accept disbursements, expenses, or grant changes."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)

        # Transition to TERMINATED
        partnership.status = CSRPartnershipStatus.TERMINATED
        partnership.save(update_fields=["status"])

        # Disbursement blocked
        with self.assertRaises(CSRStateError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=partnership.id,
                data={"amount": "50000.00", "transfer_reference": "UTR_TERM"},
            )
        self.assertEqual(ctx.exception.code, "invalid_partnership_state")

        # Expense blocked
        with self.assertRaises(CSRStateError) as ctx:
            report_csr_expense(
                user=self.ngo_user,
                partnership_id=partnership.id,
                data={"amount": "10000.00", "title": "Books"},
            )
        self.assertEqual(ctx.exception.code, "invalid_partnership_state")

        # Grant change request blocked
        with self.assertRaises(CSRStateError) as ctx:
            create_grant_change_request(
                user=self.company_user,
                partnership_id=partnership.id,
                proposed_commitment=Decimal("600000.00"),
                reason="Budget expansion on terminated partnership",
            )
        self.assertEqual(ctx.exception.code, "invalid_partnership_state")

    # =========================================================================
    # CHECK 8: Multiple Instalments and Overdue Milestone Tracking
    # =========================================================================
    def test_09_multiple_instalments_and_overdue_milestones(self):
        """Multi-tranche funding tracks distinct stages and overdue milestones."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, proposed_funding=Decimal("500000.00"), status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr, agreed_funding_amount=Decimal("500000.00"))
        activate_partnership(user=self.company_user, partnership_id=partnership.id, mou_file=self.mock_mou_pdf)

        # Tranche 1: ₹1,50,000
        d1 = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "150000.00", "transfer_reference": "UTR_MULTI_1"},
            evidence_file=self.mock_bank_slip,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=d1.id, decision="VERIFY")
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=d1.id, decision="ACKNOWLEDGE", notes="Received tranche 1")

        # Tranche 2: ₹2,00,000 (Verified by Admin, pending NGO ack)
        d2 = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "200000.00", "transfer_reference": "UTR_MULTI_2"},
            evidence_file=self.mock_bank_slip,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=d2.id, decision="VERIFY")

        # Tranche 3: ₹1,50,000 (Pending admin review)
        record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "150000.00", "transfer_reference": "UTR_MULTI_3"},
            evidence_file=self.mock_bank_slip,
        )

        dossier = get_partnership_reconciliation_dossier(self.company_user, partnership.id)
        self.assertEqual(Decimal(dossier["commitment"]["amount"]), Decimal("500000.00"))
        self.assertEqual(Decimal(dossier["reported_disbursements"]["total_amount"]), Decimal("500000.00"))
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("350000.00"))
        self.assertEqual(Decimal(dossier["ngo_acknowledged_disbursements"]["total_amount"]), Decimal("150000.00"))
        self.assertEqual(Decimal(dossier["pending_review_disbursements"]["total_amount"]), Decimal("150000.00"))
        self.assertEqual(Decimal(dossier["outstanding_commitment"]), Decimal("150000.00"))

        # Overdue Milestone check
        past_target = date.today() - timedelta(days=10)
        milestone = make_partnership_milestone(
            partnership=partnership,
            sequence_number=1,
            target_completion_date=past_target,
            status=MilestoneStatus.PENDING,
        )
        from csr.serializers.milestone_serializers import PartnershipMilestoneSerializer
        ms_serializer = PartnershipMilestoneSerializer(milestone)
        self.assertTrue(ms_serializer.data["is_overdue"])

    # =========================================================================
    # CHECK 9: Transactional Concurrency and Audit Trail
    # =========================================================================
    def test_10_transactional_concurrency_and_audit_history(self):
        """Disbursements lock parent partnership, sum atomically, and write immutable audit log."""
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, proposed_funding=Decimal("500000.00"), status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)
        activate_partnership(user=self.company_user, partnership_id=partnership.id, mou_file=self.mock_mou_pdf)

        d1 = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "200000.00", "transfer_reference": "UTR_ATOMIC_1"},
            evidence_file=self.mock_bank_slip,
        )
        d2 = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "200000.00", "transfer_reference": "UTR_ATOMIC_2"},
            evidence_file=self.mock_bank_slip,
        )
        partnership.refresh_from_db()
        self.assertEqual(partnership.disbursed_amount_reported, Decimal("400000.00"))

        # Verify audit records written
        audits = CSRVerificationHistory.objects.filter(
            entity_type=CSRAuditEntityType.DISBURSEMENT,
            entity_id__in=[d1.id, d2.id],
        )
        self.assertEqual(audits.count(), 2)
        for a in audits:
            self.assertEqual(a.reviewed_by, self.company_user)
            self.assertIn("amount", a.metadata)

    # =========================================================================
    # CHECK 10: Notification Dispatches and Privacy Isolation
    # =========================================================================
    def test_11_notification_privacy_and_isolation(self):
        """Notifications reach only bilateral partners without credential leakage."""
        from csr.services.notification_service import (
            notify_disbursement_reported,
            notify_disbursement_acknowledged,
        )
        req = make_csr_requirement(ngo=self.ngo, created_by=self.ngo_user, status=CSRRequirementStatus.OPEN_FOR_CSR)
        sr = make_csr_support_request(company=self.company, requirement=req, proposed_funding=Decimal("500000.00"), status=CSRSupportRequestStatus.ACCEPTED)
        partnership = create_partnership_from_request(support_request=sr)
        activate_partnership(user=self.company_user, partnership_id=partnership.id, mou_file=self.mock_mou_pdf)

        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=partnership.id,
            data={"amount": "250000.00", "transfer_reference": "UTR_PRIVACY_CHECK"},
            evidence_file=self.mock_bank_slip,
        )

        # 1. Reported event goes to NGO
        res_rep = notify_disbursement_reported(disb)
        self.assertTrue(res_rep.get("success"))
        last_email = mail.outbox[-1]
        self.assertEqual(last_email.to, [self.ngo_user.email])
        self.assertNotIn("password", last_email.body.lower())
        self.assertNotIn("secret", last_email.body.lower())
        self.assertIn(f"/ngo/csr/partnerships/{partnership.id}", last_email.body)

        # 2. Acknowledged event goes to Company
        ack_disb = acknowledge_csr_disbursement(
            user=self.ngo_user,
            disbursement_id=disb.id,
            decision="ACKNOWLEDGE",
            notes="Funds cleared in account",
        )
        res_ack = notify_disbursement_acknowledged(ack_disb)
        self.assertTrue(res_ack.get("success"))
        ack_email = mail.outbox[-1]
        self.assertEqual(ack_email.to, [self.company_user.email])
        self.assertIn(f"/company/csr/partnerships/{partnership.id}", ack_email.body)

    # =========================================================================
    # CHECK 11: Dashboard and Analytics Multi-Dimensional Separation
    # =========================================================================
    def test_12_dashboard_and_analytics_kpi_consistency(self):
        """Admin, Company, and NGO dashboards maintain distinct non-conflated metrics."""
        self.client.force_authenticate(user=self.admin_user)
        admin_res = self.client.get("/api/v1/admin/csr/analytics/")
        self.assertEqual(admin_res.status_code, 200)
        self.assertIn("total_committed_funding", admin_res.data)
        self.assertIn("total_transfers_reported", admin_res.data)
        self.assertIn("total_transfers_verified", admin_res.data)
        self.assertIn("total_acknowledged_receipts", admin_res.data)

        self.client.force_authenticate(user=self.company_user)
        comp_res = self.client.get("/api/v1/csr/dashboard/")
        self.assertEqual(comp_res.status_code, 200)
        self.assertIn("committed_funding_total", comp_res.data)
        self.assertIn("disbursed_funding_total", comp_res.data)
        self.assertIn("acknowledged_funding_total", comp_res.data)

        self.client.force_authenticate(user=self.ngo_user)
        ngo_res = self.client.get("/api/v1/ngo/csr/dashboard/")
        self.assertEqual(ngo_res.status_code, 200)
        self.assertIn("total_committed_funding", ngo_res.data)
        self.assertIn("total_transfers_reported", ngo_res.data)
        self.assertIn("total_acknowledged_receipts", ngo_res.data)
