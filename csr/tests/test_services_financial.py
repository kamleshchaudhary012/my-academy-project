"""
CSR Financial Integrity & Milestone Payment Control — Phase CSR-Transparency Tests
===================================================================================
Tests covering:
1. Positive commitment with zero payments is not reconciled (produces NOT_DISBURSED).
2. Partial payment produces correct outstanding amount (PARTIALLY_DISBURSED).
3. Reported payment without adequate evidence is not falsely verified (AWAITING_EVIDENCE).
4. NGO acknowledgement is distinct from evidence review (AWAITING_NGO_ACKNOWLEDGEMENT).
5. Disputed transfers prevent full reconciliation (DISPUTED).
6. Duplicate UTR/reference submissions are handled safely according to uniqueness policy.
7. Duplicate expenses cannot inflate verified totals.
8. Overdue status requires a real applicable deadline (OVERDUE).
9. Grant increases cannot take effect without all required approvals (Admin & Company).
10. Transfers exceeding approved grant are flagged (OVER-COMMITMENT).
11. Unauthorized users cannot approve evidence, milestones, or grant changes.
12. Audit history records critical financial changes.
13. Existing partnership reconciliation dossier works across roles (Company, NGO, Admin).
"""

from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from csr.models import (
    CSRPartnership,
    CSRPartnershipStatus,
    PartnershipMilestone,
    MilestoneStatus,
    CSRDisbursement,
    CSRExpense,
    CSRGrantChangeRequest,
    CSRGrantChangeStatus,
    CSRFinancialStatus,
    CSRDisbursementReviewStatus,
    CSRNgoAcknowledgementStatus,
    CSRExpenseReviewStatus,
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.services.financial_service import (
    record_csr_disbursement,
    review_csr_disbursement,
    acknowledge_csr_disbursement,
    report_csr_expense,
    review_csr_expense,
    create_grant_change_request,
    admin_review_grant_change_request,
    company_review_grant_change_request,
    get_partnership_reconciliation_dossier,
    calculate_partnership_financial_status,
    get_contractual_payment_due_date,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRUnauthorizedError,
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


class CSRFinancialIntegrityTestCase(TestCase):
    def setUp(self):
        self.admin_user = make_user(email="admin@daangives.org", role=User.Role.ADMIN, is_staff=True)
        self.company_user = make_user(email="csr@tata.com", role=User.Role.COMPANY)
        self.company = make_company_profile(user=self.company_user, company_name="Tata Steel Ltd")

        self.ngo_user = make_user(email="contact@pratham.org", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user, legal_name="Pratham Education Foundation")

        self.requirement = make_csr_requirement(ngo=self.ngo, total_estimated_budget=Decimal("1000000.00"))
        self.support_request = make_csr_support_request(company=self.company, requirement=self.requirement)

        # Committed grant: ₹7,50,000
        self.partnership = make_csr_partnership(
            company=self.company,
            ngo=self.ngo,
            requirement=self.requirement,
            support_request=self.support_request,
            agreed_funding_amount=Decimal("750000.00"),
            status=CSRPartnershipStatus.ACTIVE,
            execution_start_date=date.today(),
            target_completion_date=date.today() + timedelta(days=180),
        )

        self.mock_pdf = SimpleUploadedFile("advice.pdf", b"%PDF-1.4 mock transfer advice", content_type="application/pdf")

    # -------------------------------------------------------------------------
    # Scenario 1: Positive commitment with zero payments is NOT reconciled
    # -------------------------------------------------------------------------
    def test_positive_commitment_with_zero_payments_is_not_reconciled(self):
        """A commitment of ₹7,50,000 with 0 disbursements must be NOT_DISBURSED, never RECONCILED."""
        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)

        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.NOT_DISBURSED)
        self.assertFalse(dossier["is_reconciled"])
        self.assertTrue(dossier["unreconciled_discrepancies"]["needs_reconciliation"])
        self.assertEqual(Decimal(dossier["commitment"]["amount"]), Decimal("750000.00"))
        self.assertEqual(Decimal(dossier["outstanding_commitment"]), Decimal("750000.00"))
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("0.00"))

    # -------------------------------------------------------------------------
    # Scenario 2: Partial payment produces correct outstanding amount
    # -------------------------------------------------------------------------
    def test_partial_payment_produces_correct_outstanding_amount(self):
        """Transferring ₹3,00,000 against ₹7,50,000 produces outstanding ₹4,50,000 and PARTIALLY_DISBURSED."""
        # 1. Report disbursement with evidence
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "300000.00", "transfer_reference": "UTR300000ABC", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        # 2. Admin verifies evidence
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY")
        # 3. NGO acknowledges receipt
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=disb.id, decision="ACKNOWLEDGE")

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)

        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.PARTIALLY_DISBURSED)
        self.assertFalse(dossier["is_reconciled"])
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("300000.00"))
        self.assertEqual(Decimal(dossier["outstanding_commitment"]), Decimal("450000.00"))
        self.assertEqual(Decimal(dossier["ngo_acknowledged_disbursements"]["total_amount"]), Decimal("300000.00"))

    # -------------------------------------------------------------------------
    # Scenario 3: Reported payment without adequate evidence is not falsely verified
    # -------------------------------------------------------------------------
    def test_reported_payment_without_evidence_is_awaiting_evidence(self):
        """A disbursement recorded without an evidence file must have status AWAITING_EVIDENCE."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "100000.00", "transfer_reference": "UTR_NO_DOC", "payment_mode": "RTGS"},
            evidence_file=None,
        )
        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)

        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.AWAITING_EVIDENCE)
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("0.00"))
        self.assertEqual(Decimal(dossier["reported_disbursements"]["total_amount"]), Decimal("100000.00"))

    def test_reported_payment_with_evidence_pending_review(self):
        """A disbursement recorded with evidence but unreviewed must have status DISBURSEMENT_REPORTED."""
        record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "150000.00", "transfer_reference": "UTR_WITH_DOC", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )
        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)

        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.DISBURSEMENT_REPORTED)
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("0.00"))

    # -------------------------------------------------------------------------
    # Scenario 4: NGO acknowledgement is distinct from evidence review
    # -------------------------------------------------------------------------
    def test_ngo_acknowledgement_is_distinct_from_evidence_review(self):
        """Admin verifying evidence does NOT auto-acknowledge receipt for the NGO."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "200000.00", "transfer_reference": "UTR200K", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        # Admin verifies evidence
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY")

        # Refresh and check state
        disb.refresh_from_db()
        self.assertEqual(disb.review_status, CSRDisbursementReviewStatus.VERIFIED)
        self.assertEqual(disb.ngo_acknowledgement_status, CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT)

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.AWAITING_NGO_ACKNOWLEDGEMENT)
        self.assertEqual(Decimal(dossier["verified_disbursements"]["total_amount"]), Decimal("200000.00"))
        self.assertEqual(Decimal(dossier["ngo_acknowledged_disbursements"]["total_amount"]), Decimal("0.00"))

    # -------------------------------------------------------------------------
    # Scenario 5: Disputed transfers prevent full reconciliation
    # -------------------------------------------------------------------------
    def test_disputed_transfers_prevent_full_reconciliation(self):
        """When an NGO disputes a reported disbursement, status transitions to DISPUTED."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "750000.00", "transfer_reference": "UTR_DISPUTED", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY")
        acknowledge_csr_disbursement(
            user=self.ngo_user,
            disbursement_id=disb.id,
            decision="DISPUTE",
            notes="Funds not credited to NGO account; incorrect beneficiary IFSC.",
        )

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.DISPUTED)
        self.assertFalse(dossier["is_reconciled"])
        self.assertEqual(Decimal(dossier["disputed_disbursements"]["total_amount"]), Decimal("750000.00"))

    # -------------------------------------------------------------------------
    # Scenario 6: Duplicate UTR/reference submissions handled safely
    # -------------------------------------------------------------------------
    def test_duplicate_utr_reference_rejected(self):
        """Submitting the same non-empty UTR for the partnership raises CSRValidationError."""
        record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "100000.00", "transfer_reference": "UTR_DUPLICATE_999", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        with self.assertRaises(CSRValidationError) as ctx:
            record_csr_disbursement(
                user=self.company_user,
                partnership_id=self.partnership.id,
                data={"amount": "50000.00", "transfer_reference": "UTR_DUPLICATE_999", "payment_mode": "NEFT"},
                evidence_file=self.mock_pdf,
            )
        self.assertEqual(ctx.exception.code, "duplicate_transfer_reference")

    # -------------------------------------------------------------------------
    # Scenario 7: Duplicate expenses cannot inflate verified totals
    # -------------------------------------------------------------------------
    def test_duplicate_expense_rejected(self):
        """Reporting the same invoice number for a vendor raises CSRValidationError."""
        report_csr_expense(
            user=self.ngo_user,
            partnership_id=self.partnership.id,
            data={"amount": "50000.00", "title": "Books Delivery", "invoice_number": "INV-2026-001", "vendor_payee": "Tata Books"},
        )
        with self.assertRaises(CSRValidationError) as ctx:
            report_csr_expense(
                user=self.ngo_user,
                partnership_id=self.partnership.id,
                data={"amount": "50000.00", "title": "Duplicate Books", "invoice_number": "INV-2026-001", "vendor_payee": "Tata Books"},
            )
        self.assertEqual(ctx.exception.code, "duplicate_invoice")

    # -------------------------------------------------------------------------
    # Scenario 8: Overdue status requires a real contractual payment deadline
    # -------------------------------------------------------------------------
    def test_project_completion_date_elapsed_without_contractual_payment_deadline_not_overdue(self):
        """
        Elapsed project completion date (target_completion_date) does NOT make payment OVERDUE
        when no contractual payment deadline exists. Preserves NOT_DISBURSED / PARTIALLY_DISBURSED.
        """
        self.partnership.execution_start_date = date.today() - timedelta(days=60)
        self.partnership.target_completion_date = date.today() - timedelta(days=5)
        self.partnership.save()

        # Zero disbursements -> preserves NOT_DISBURSED (not OVERDUE)
        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)
        self.assertFalse(dossier["is_overdue"])
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.NOT_DISBURSED)

        # Partial verified disbursement -> preserves PARTIALLY_DISBURSED (not OVERDUE)
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "300000.00", "transfer_reference": "UTR_PARTIAL_REG", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY")
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=disb.id, decision="ACKNOWLEDGE")

        dossier_partial = get_partnership_reconciliation_dossier(self.company_user, self.partnership)
        self.assertFalse(dossier_partial["is_overdue"])
        self.assertEqual(dossier_partial["financial_status"], CSRFinancialStatus.PARTIALLY_DISBURSED)
        self.assertEqual(Decimal(dossier_partial["outstanding_commitment"]), Decimal("450000.00"))

    def test_ngo_milestone_deadline_elapsed_without_contractual_payment_deadline_not_overdue(self):
        """
        Elapsed NGO milestone deliverable deadline does NOT make grant payment OVERDUE
        when no contractual payment deadline exists. Milestone dates are deliverable milestones.
        """
        PartnershipMilestone.objects.create(
            partnership=self.partnership,
            sequence_number=1,
            title="Classroom Solar Panels",
            description="Install solar microgrid",
            target_completion_date=date.today() - timedelta(days=20),
            status=MilestoneStatus.PENDING,
        )

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership)
        self.assertFalse(dossier["is_overdue"])
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.NOT_DISBURSED)

    def test_actual_contractual_payment_deadline_elapsed_with_outstanding_commitment_is_overdue(self):
        """
        When an actual contractual payment deadline has elapsed with positive outstanding commitment,
        status correctly transitions to OVERDUE with explicit explanation and alerts.
        """
        self.partnership.contractual_payment_due_date = date.today() - timedelta(days=5)

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership)
        self.assertTrue(dossier["is_overdue"])
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.OVERDUE)
        self.assertIn("Contractual payment deadline", dossier["financial_status_explanation"])
        self.assertIn("750000.00", dossier["financial_status_explanation"])
        self.assertTrue(any("PAYMENT OVERDUE" in alert for alert in dossier["unreconciled_discrepancies"]["alerts"]))

    def test_contractual_payment_schedule_evaluation(self):
        """
        Evaluates contractual payment installment schedules:
        - Past due installment date with outstanding funds -> OVERDUE
        - Future installment dates -> NOT_DISBURSED
        """
        # Overdue installment schedule
        self.partnership.payment_schedule = [
            {"due_date": date.today() - timedelta(days=3), "amount": Decimal("250000.00")},
            {"due_date": date.today() + timedelta(days=30), "amount": Decimal("500000.00")},
        ]
        dossier_overdue = get_partnership_reconciliation_dossier(self.company_user, self.partnership)
        self.assertTrue(dossier_overdue["is_overdue"])
        self.assertEqual(dossier_overdue["financial_status"], CSRFinancialStatus.OVERDUE)

        # Future installment schedule
        self.partnership.payment_schedule = [
            {"due_date": date.today() + timedelta(days=15), "amount": Decimal("250000.00")},
            {"due_date": date.today() + timedelta(days=45), "amount": Decimal("500000.00")},
        ]
        dossier_future = get_partnership_reconciliation_dossier(self.company_user, self.partnership)
        self.assertFalse(dossier_future["is_overdue"])
        self.assertEqual(dossier_future["financial_status"], CSRFinancialStatus.NOT_DISBURSED)

    def test_historical_deadline_with_zero_outstanding_commitment_is_not_overdue(self):
        """
        When all committed grant funds have been fully disbursed and verified, an elapsed
        contractual payment deadline or completion date does NOT trigger OVERDUE status.
        """
        # Fully disburse and verify commitment
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "750000.00", "transfer_reference": "UTR_FULL_PAID", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY")
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=disb.id, decision="ACKNOWLEDGE")

        # Report and verify full matching expenses
        exp = report_csr_expense(
            user=self.ngo_user,
            partnership_id=self.partnership.id,
            data={"amount": "750000.00", "title": "Full Equipment Project", "invoice_number": "INV-FULL-01", "vendor_payee": "Bharat Solar Ltd"},
            invoice_document=self.mock_pdf,
        )
        review_csr_expense(user=self.admin_user, expense_id=exp.id, decision="VERIFY")

        # Set contractual deadline and project completion date into the past
        self.partnership.contractual_payment_due_date = date.today() - timedelta(days=10)
        self.partnership.execution_start_date = date.today() - timedelta(days=60)
        self.partnership.target_completion_date = date.today() - timedelta(days=5)
        self.partnership.save()

        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership)
        self.assertFalse(dossier["is_overdue"])
        self.assertEqual(Decimal(dossier["outstanding_commitment"]), Decimal("0.00"))
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.RECONCILED)
        self.assertTrue(dossier["is_reconciled"])


    # -------------------------------------------------------------------------
    # Scenario 9: Grant increases cannot take effect without all required approvals
    # -------------------------------------------------------------------------
    def test_grant_change_request_requires_dual_approval(self):
        """Increasing commitment from ₹7,50,000 to ₹9,00,000 requires Admin and Company approvals."""
        # 1. NGO proposes increase
        change = create_grant_change_request(
            user=self.ngo_user,
            partnership_id=self.partnership.id,
            proposed_commitment="900000.00",
            reason="Expansion to 3 additional village clusters",
            revised_budget_document=self.mock_pdf,
        )
        self.assertEqual(change.status, CSRGrantChangeStatus.PENDING_ADMIN_REVIEW)
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.agreed_funding_amount, Decimal("750000.00"))  # Unchanged!

        # 2. Admin reviews & approves -> moves to PENDING_COMPANY_APPROVAL
        admin_review_grant_change_request(
            user=self.admin_user,
            request_id=change.id,
            decision="APPROVE",
            review_notes="Eligibility verified. Budget breakdown validated.",
        )
        change.refresh_from_db()
        self.assertEqual(change.status, CSRGrantChangeStatus.PENDING_COMPANY_APPROVAL)
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.agreed_funding_amount, Decimal("750000.00"))  # Still unchanged!

        # 3. Company approves -> transitions to APPROVED and updates partnership commitment
        company_review_grant_change_request(
            user=self.company_user,
            request_id=change.id,
            decision="APPROVE",
            review_notes="Board approved CSR budget revision.",
        )
        change.refresh_from_db()
        self.assertEqual(change.status, CSRGrantChangeStatus.APPROVED)
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.agreed_funding_amount, Decimal("900000.00"))  # Officially updated!

    def test_grant_change_request_rejection_leaves_commitment_intact(self):
        """If corporate partner rejects the change request, commitment remains unchanged."""
        change = create_grant_change_request(
            user=self.ngo_user,
            partnership_id=self.partnership.id,
            proposed_commitment="850000.00",
            reason="Unplanned equipment replacement",
        )
        admin_review_grant_change_request(user=self.admin_user, request_id=change.id, decision="APPROVE")
        company_review_grant_change_request(
            user=self.company_user,
            request_id=change.id,
            decision="REJECT",
            review_notes="CSR budget for this fiscal quarter is fully allocated.",
        )
        change.refresh_from_db()
        self.assertEqual(change.status, CSRGrantChangeStatus.REJECTED)
        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.agreed_funding_amount, Decimal("750000.00"))  # Preserved!

    # -------------------------------------------------------------------------
    # Scenario 10: Transfers exceeding the approved grant are flagged
    # -------------------------------------------------------------------------
    def test_transfers_exceeding_approved_grant_flagged_over_commitment(self):
        """Reporting ₹8,00,000 against a ₹7,50,000 grant triggers is_over_commitment warning."""
        record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "800000.00", "transfer_reference": "UTR_EXCESS", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )
        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)

        self.assertTrue(dossier["is_over_commitment"])
        self.assertEqual(Decimal(dossier["over_commitment_amount"]), Decimal("50000.00"))
        # Warning alert present in response
        self.assertTrue(any("OVER-COMMITMENT" in alert for alert in dossier["unreconciled_discrepancies"]["alerts"]))

    # -------------------------------------------------------------------------
    # Scenario 11: Unauthorized users cannot approve evidence or grant changes
    # -------------------------------------------------------------------------
    def test_unauthorized_user_cannot_verify_disbursement(self):
        """NGO user cannot verify corporate disbursement evidence."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "50000.00", "transfer_reference": "UTR_AUTH", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        with self.assertRaises(CSRUnauthorizedError):
            review_csr_disbursement(user=self.ngo_user, disbursement_id=disb.id, decision="VERIFY")

    def test_unauthorized_user_cannot_approve_grant_change(self):
        """NGO cannot approve its own grant change proposal."""
        change = create_grant_change_request(
            user=self.ngo_user,
            partnership_id=self.partnership.id,
            proposed_commitment="800000.00",
            reason="Inflation adjustment",
        )
        with self.assertRaises(CSRUnauthorizedError):
            admin_review_grant_change_request(user=self.ngo_user, request_id=change.id, decision="APPROVE")

    # -------------------------------------------------------------------------
    # Scenario 12: Audit history records critical financial changes
    # -------------------------------------------------------------------------
    def test_audit_history_records_financial_events(self):
        """Disbursement reporting, evidence review, and acknowledgements are recorded in audit ledger."""
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "100000.00", "transfer_reference": "UTR_AUDIT_1", "payment_mode": "NEFT"},
            evidence_file=self.mock_pdf,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY", review_notes="Clean bank advice.")
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=disb.id, decision="ACKNOWLEDGE", notes="Received into trust account.")

        audits = CSRVerificationHistory.objects.filter(entity_type=CSRAuditEntityType.DISBURSEMENT, entity_id=disb.id)
        self.assertGreaterEqual(audits.count(), 3)
        statuses = [a.new_status for a in audits]
        self.assertIn(CSRDisbursementReviewStatus.PENDING_REVIEW, statuses)
        self.assertIn(CSRDisbursementReviewStatus.VERIFIED, statuses)
        self.assertIn(CSRNgoAcknowledgementStatus.ACKNOWLEDGED, statuses)

    # -------------------------------------------------------------------------
    # Scenario 13: Full reconciliation achieved only when all conditions satisfied
    # -------------------------------------------------------------------------
    def test_full_reconciliation_workflow(self):
        """RECONCILED status is achieved when commitment is fully disbursed, verified, acknowledged, and spent."""
        # 1. Full disbursement of ₹7,50,000
        disb = record_csr_disbursement(
            user=self.company_user,
            partnership_id=self.partnership.id,
            data={"amount": "750000.00", "transfer_reference": "UTR_FULL_REC", "payment_mode": "RTGS"},
            evidence_file=self.mock_pdf,
        )
        review_csr_disbursement(user=self.admin_user, disbursement_id=disb.id, decision="VERIFY")
        acknowledge_csr_disbursement(user=self.ngo_user, disbursement_id=disb.id, decision="ACKNOWLEDGE")

        # 2. Report and verify matching ground expenses of ₹7,50,000
        exp = report_csr_expense(
            user=self.ngo_user,
            partnership_id=self.partnership.id,
            data={"amount": "750000.00", "title": "Infrastructure Implementation", "invoice_number": "INV-FINAL-001", "vendor_payee": "L&T Infrastructure"},
            invoice_document=self.mock_pdf,
        )
        review_csr_expense(user=self.company_user, expense_id=exp.id, decision="VERIFY", review_notes="Deliverables and site photos audited.")

        # 3. Check reconciliation
        dossier = get_partnership_reconciliation_dossier(self.company_user, self.partnership.id)
        self.assertEqual(dossier["financial_status"], CSRFinancialStatus.RECONCILED)
        self.assertTrue(dossier["is_reconciled"])
        self.assertFalse(dossier["unreconciled_discrepancies"]["needs_reconciliation"])
