"""
CSR Financial & Transparency Service — Phase CSR-Transparency
=============================================================
Manages itemized corporate disbursements, bank transfer evidence verification,
NGO receipt acknowledgements, project ground expenditure reports, bilateral grant
change requests, and real-time multi-dimensional financial reconciliation dossiers.
"""

import os
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from csr.models import (
    CSRPartnership,
    CSRPartnershipStatus,
    PartnershipMilestone,
    MilestoneStatus,
    CSRDisbursement,
    CSRExpense,
    CSRGrantChangeRequest,
    CSRGrantChangeStatus,
    CSRAuditEntityType,
    CSRFinancialStatus,
    CSRDisbursementReviewStatus,
    CSRNgoAcknowledgementStatus,
    CSRExpenseReviewStatus,
    CSRVerificationHistory,
)
from csr.services.exceptions import (
    CSRNotFoundError,
    CSRValidationError,
    CSRUnauthorizedError,
    CSRStateError,
)
from csr.services.audit_service import record_verification_event
from csr.services.notification_service import dispatch_csr_notification, CSRNotificationEventType
from csr.serializers.financial_serializers import (
    CSRDisbursementSerializer,
    CSRExpenseSerializer,
    CSRGrantChangeRequestSerializer,
)


def _is_partnership_participant(user, partnership):
    """Checks if user belongs to the corporate partner, recipient NGO, or platform staff."""
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
        return True
    if getattr(user, 'role', '') == 'COMPANY' and hasattr(user, 'company_profile') and partnership.company_id == user.company_profile.id:
        return True
    if getattr(user, 'role', '') == 'NGO' and hasattr(user, 'ngo_profile') and partnership.ngo_id == user.ngo_profile.id:
        return True
    return False


def _is_company_participant(user, partnership):
    """Checks if user belongs to the corporate partner or is an administrator."""
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
        return True
    return getattr(user, 'role', '') == 'COMPANY' and hasattr(user, 'company_profile') and partnership.company_id == user.company_profile.id


def _is_ngo_participant(user, partnership):
    """Checks if user belongs to the recipient NGO or is an administrator."""
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
        return True
    return getattr(user, 'role', '') == 'NGO' and hasattr(user, 'ngo_profile') and partnership.ngo_id == user.ngo_profile.id


# ===========================================================================
# 1. Bank Disbursements Workflow
# ===========================================================================

def record_csr_disbursement(user, partnership_id, data, evidence_file=None):
    """
    Records an itemized off-platform bank disbursement with wire references and evidence.
    Enforces duplicate UTR detection, updates partnership.disbursed_amount_reported,
    and writes audit trail.
    """
    amount = Decimal(str(data.get('amount') or 0))
    if amount <= Decimal('0.00'):
        raise CSRValidationError("Disbursed amount must be greater than zero.", code="invalid_disbursement_amount")

    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_company_participant(user, partnership):
            raise CSRUnauthorizedError("Only authorized corporate partners can report disbursements.", code="unauthorized_company")

        if partnership.status in (CSRPartnershipStatus.CANCELLED, CSRPartnershipStatus.TERMINATED):
            raise CSRStateError("Cannot report disbursements for a cancelled or terminated partnership.", code="invalid_partnership_state")

        transfer_reference = str(data.get('transfer_reference') or '').strip()
        if transfer_reference:
            # Prevent duplicate UTR submissions across non-rejected records for this partnership
            existing_ref = CSRDisbursement.objects.filter(
                partnership=partnership,
                transfer_reference__iexact=transfer_reference
            ).exclude(review_status=CSRDisbursementReviewStatus.REJECTED).exists()
            if existing_ref:
                raise CSRValidationError(
                    f"A disbursement with UTR / reference '{transfer_reference}' has already been reported.",
                    code="duplicate_transfer_reference"
                )

        disbursement_date = data.get('disbursement_date') or timezone.now().date()
        payment_mode = data.get('payment_mode') or 'NEFT'
        notes = str(data.get('notes') or '').strip()

        disbursement = CSRDisbursement(
            partnership=partnership,
            reported_by=user,
            amount=amount,
            currency='INR',
            disbursement_date=disbursement_date,
            transfer_reference=transfer_reference,
            payment_mode=payment_mode,
            notes=notes,
            review_status=CSRDisbursementReviewStatus.PENDING_REVIEW,
            ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT,
        )

        if evidence_file:
            disbursement.evidence_document = evidence_file

        disbursement.save()

        # Recalculate cumulative non-rejected reported disbursements
        agg = CSRDisbursement.objects.filter(partnership=partnership).exclude(
            review_status=CSRDisbursementReviewStatus.REJECTED
        ).aggregate(total=Sum('amount'))
        total_reported = agg['total'] or amount
        partnership.disbursed_amount_reported = total_reported
        partnership.save(update_fields=['disbursed_amount_reported', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.DISBURSEMENT,
            entity_id=disbursement.id,
            old_status=None,
            new_status=disbursement.review_status,
            actor_user=user,
            review_notes=f"Reported corporate bank disbursement: ₹{amount} (Ref: {transfer_reference or 'None'}).",
            metadata={
                "partnership_id": str(partnership.id),
                "partnership_code": partnership.partnership_code,
                "amount": str(amount),
                "transfer_reference": transfer_reference,
                "payment_mode": payment_mode,
                "has_evidence": bool(evidence_file),
            },
        )

        transaction.on_commit(
            lambda: dispatch_csr_notification(
                CSRNotificationEventType.CSR_DISBURSEMENT_REPORTED,
                {"disbursement": disbursement}
            )
        )

        return disbursement


def review_csr_disbursement(user, disbursement_id, decision, review_notes=""):
    """
    Administrative review of off-platform corporate bank transfer evidence.
    Requires administrative privileges (platform staff or admin).
    """
    if not (user.is_staff or getattr(user, 'role', '') == 'ADMIN'):
        raise CSRUnauthorizedError("Administrative privileges required to verify disbursement evidence.", code="admin_required")

    decision_norm = str(decision).strip().upper()
    if decision_norm not in ['VERIFY', 'REJECT']:
        raise CSRValidationError("Decision must be either VERIFY or REJECT.", code="invalid_decision")

    with transaction.atomic():
        try:
            disbursement = CSRDisbursement.objects.select_for_update().select_related('partnership').get(id=disbursement_id)
        except (CSRDisbursement.DoesNotExist, ValueError):
            raise CSRNotFoundError("Disbursement record not found.", code="disbursement_not_found")

        old_status = disbursement.review_status
        new_status = CSRDisbursementReviewStatus.VERIFIED if decision_norm == 'VERIFY' else CSRDisbursementReviewStatus.REJECTED

        disbursement.review_status = new_status
        disbursement.reviewed_by = user
        disbursement.reviewed_at = timezone.now()
        disbursement.review_notes = review_notes
        disbursement.save(update_fields=['review_status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])

        # Recalculate cumulative non-rejected reported disbursements
        agg = CSRDisbursement.objects.filter(partnership=disbursement.partnership).exclude(
            review_status=CSRDisbursementReviewStatus.REJECTED
        ).aggregate(total=Sum('amount'))
        disbursement.partnership.disbursed_amount_reported = agg['total'] or Decimal('0.00')
        disbursement.partnership.save(update_fields=['disbursed_amount_reported', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.DISBURSEMENT,
            entity_id=disbursement.id,
            old_status=old_status,
            new_status=new_status,
            actor_user=user,
            review_notes=f"Disbursement review decision: {new_status}. {review_notes}".strip(),
            metadata={
                "partnership_id": str(disbursement.partnership.id),
                "partnership_code": disbursement.partnership.partnership_code,
                "amount": str(disbursement.amount),
                "transfer_reference": disbursement.transfer_reference,
            },
        )

        event_type = (
            CSRNotificationEventType.CSR_DISBURSEMENT_VERIFIED
            if new_status == CSRDisbursementReviewStatus.VERIFIED
            else CSRNotificationEventType.CSR_DISBURSEMENT_REJECTED
        )
        transaction.on_commit(
            lambda: dispatch_csr_notification(
                event_type,
                {"disbursement": disbursement}
            )
        )

        return disbursement


def acknowledge_csr_disbursement(user, disbursement_id, decision, notes="", receipt_document=None):
    """
    NGO receipt acknowledgement or non-receipt dispute for an off-platform bank disbursement.
    """
    decision_norm = str(decision).strip().upper()
    if decision_norm not in ['ACKNOWLEDGE', 'DISPUTE']:
        raise CSRValidationError("Decision must be either ACKNOWLEDGE or DISPUTE.", code="invalid_decision")

    with transaction.atomic():
        try:
            disbursement = CSRDisbursement.objects.select_for_update().select_related('partnership').get(id=disbursement_id)
        except (CSRDisbursement.DoesNotExist, ValueError):
            raise CSRNotFoundError("Disbursement record not found.", code="disbursement_not_found")

        if not _is_ngo_participant(user, disbursement.partnership):
            raise CSRUnauthorizedError("Only authorized recipient NGO representatives can acknowledge receipts.", code="unauthorized_ngo")

        old_ack = disbursement.ngo_acknowledgement_status
        new_ack = (
            CSRNgoAcknowledgementStatus.ACKNOWLEDGED
            if decision_norm == 'ACKNOWLEDGE'
            else CSRNgoAcknowledgementStatus.DISPUTED
        )

        disbursement.ngo_acknowledgement_status = new_ack
        disbursement.ngo_acknowledged_by = user
        disbursement.ngo_acknowledged_at = timezone.now()
        disbursement.ngo_acknowledgement_notes = notes

        if receipt_document:
            disbursement.ngo_receipt_document = receipt_document

        disbursement.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.DISBURSEMENT,
            entity_id=disbursement.id,
            old_status=old_ack,
            new_status=new_ack,
            actor_user=user,
            review_notes=f"NGO acknowledgement action: {new_ack}. {notes}".strip(),
            metadata={
                "partnership_id": str(disbursement.partnership.id),
                "partnership_code": disbursement.partnership.partnership_code,
                "amount": str(disbursement.amount),
                "transfer_reference": disbursement.transfer_reference,
                "has_receipt_document": bool(receipt_document),
            },
        )

        event_type = (
            CSRNotificationEventType.CSR_DISBURSEMENT_ACKNOWLEDGED
            if new_ack == CSRNgoAcknowledgementStatus.ACKNOWLEDGED
            else CSRNotificationEventType.CSR_DISBURSEMENT_DISPUTED
        )
        transaction.on_commit(
            lambda: dispatch_csr_notification(
                event_type,
                {"disbursement": disbursement}
            )
        )

        return disbursement


# ===========================================================================
# 2. Project Ground Expenses Workflow
# ===========================================================================

def report_csr_expense(user, partnership_id, data, invoice_document=None):
    """
    Records an itemized ground project expenditure reported by the NGO with invoice proof.
    Enforces duplicate voucher / invoice prevention.
    """
    amount = Decimal(str(data.get('amount') or 0))
    if amount <= Decimal('0.00'):
        raise CSRValidationError("Expense amount must be greater than zero.", code="invalid_expense_amount")

    title = str(data.get('title') or '').strip()
    if not title:
        raise CSRValidationError("Expense title is required.", code="missing_title")

    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_ngo_participant(user, partnership):
            raise CSRUnauthorizedError("Only authorized NGO partners can report project expenses.", code="unauthorized_ngo")

        if partnership.status in (CSRPartnershipStatus.CANCELLED, CSRPartnershipStatus.TERMINATED):
            raise CSRStateError("Cannot report project expenses for a cancelled or terminated partnership.", code="invalid_partnership_state")

        invoice_number = str(data.get('invoice_number') or '').strip()
        vendor_payee = str(data.get('vendor_payee') or '').strip()

        if invoice_number and vendor_payee:
            existing_exp = CSRExpense.objects.filter(
                partnership=partnership,
                invoice_number__iexact=invoice_number,
                vendor_payee__iexact=vendor_payee
            ).exclude(review_status=CSRExpenseReviewStatus.REJECTED).exists()
            if existing_exp:
                raise CSRValidationError(
                    f"An expense with invoice number '{invoice_number}' from '{vendor_payee}' has already been reported.",
                    code="duplicate_invoice"
                )

        milestone_obj = None
        milestone_id = data.get('milestone')
        if milestone_id:
            try:
                milestone_obj = PartnershipMilestone.objects.get(id=milestone_id, partnership=partnership)
            except (PartnershipMilestone.DoesNotExist, ValueError):
                raise CSRValidationError("Associated milestone does not belong to this partnership.", code="invalid_milestone")

        expense = CSRExpense(
            partnership=partnership,
            milestone=milestone_obj,
            reported_by=user,
            expense_category=data.get('expense_category') or 'OPERATIONAL',
            title=title,
            description=str(data.get('description') or '').strip(),
            amount=amount,
            currency='INR',
            expense_date=data.get('expense_date') or timezone.now().date(),
            vendor_payee=vendor_payee,
            invoice_number=invoice_number,
            review_status=CSRExpenseReviewStatus.SUBMITTED,
        )

        if invoice_document:
            expense.invoice_document = invoice_document

        expense.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.EXPENSE,
            entity_id=expense.id,
            old_status=None,
            new_status=expense.review_status,
            actor_user=user,
            review_notes=f"Reported project expenditure: ₹{amount} ({title}).",
            metadata={
                "partnership_id": str(partnership.id),
                "partnership_code": partnership.partnership_code,
                "amount": str(amount),
                "category": expense.expense_category,
                "has_invoice": bool(invoice_document),
            },
        )

        return expense


def review_csr_expense(user, expense_id, decision, review_notes=""):
    """
    Review and verify or reject an itemized project expense (corporate partner or admin).
    """
    decision_norm = str(decision).strip().upper()
    if decision_norm in ['VERIFY', 'APPROVE']:
        decision_norm = 'VERIFY'
    elif decision_norm not in ['VERIFY', 'REJECT']:
        raise CSRValidationError("Decision must be either VERIFY (or APPROVE) or REJECT.", code="invalid_decision")

    with transaction.atomic():
        try:
            expense = CSRExpense.objects.select_for_update().select_related('partnership').get(id=expense_id)
        except (CSRExpense.DoesNotExist, ValueError):
            raise CSRNotFoundError("Expense record not found.", code="expense_not_found")

        # Must be company participant or admin
        if not (user.is_staff or getattr(user, 'role', '') == 'ADMIN' or _is_company_participant(user, expense.partnership)):
            raise CSRUnauthorizedError("Only authorized corporate reviewers or administrators can verify expenses.", code="unauthorized_reviewer")

        old_status = expense.review_status
        new_status = CSRExpenseReviewStatus.VERIFIED if decision_norm == 'VERIFY' else CSRExpenseReviewStatus.REJECTED

        expense.review_status = new_status
        expense.reviewed_by = user
        expense.reviewed_at = timezone.now()
        expense.review_notes = review_notes
        expense.save(update_fields=['review_status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.EXPENSE,
            entity_id=expense.id,
            old_status=old_status,
            new_status=new_status,
            actor_user=user,
            review_notes=f"Expense review decision: {new_status}. {review_notes}".strip(),
            metadata={
                "partnership_id": str(expense.partnership.id),
                "partnership_code": expense.partnership.partnership_code,
                "amount": str(expense.amount),
                "title": expense.title,
            },
        )

        return expense


# ===========================================================================
# 3. Grant Change Request Workflow
# ===========================================================================

def create_grant_change_request(user, partnership_id, proposed_commitment, reason, revised_budget_document=None):
    """
    Proposes an increase or revision to the approved bilateral grant commitment.
    Does NOT alter the approved commitment until Admin and Corporate partner approve.
    """
    proposed_decimal = Decimal(str(proposed_commitment or 0))
    if proposed_decimal < Decimal('1000.00'):
        raise CSRValidationError("Proposed grant commitment must be at least ₹1,000.00.", code="invalid_proposed_commitment")

    reason_text = str(reason or '').strip()
    if not reason_text:
        raise CSRValidationError("A detailed justification reason for the grant change is required.", code="missing_reason")

    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_partnership_participant(user, partnership):
            raise CSRUnauthorizedError("Only authorized bilateral partners can submit grant change requests.", code="unauthorized_partner")

        if partnership.status in (CSRPartnershipStatus.CANCELLED, CSRPartnershipStatus.TERMINATED, CSRPartnershipStatus.COMPLETED):
            raise CSRStateError("Cannot submit grant change requests for completed, cancelled, or terminated partnerships.", code="invalid_partnership_state")

        if proposed_decimal == partnership.agreed_funding_amount:
            raise CSRValidationError("Proposed commitment is identical to the current approved commitment.", code="identical_commitment")

        # Check for existing active change request
        active_request = CSRGrantChangeRequest.objects.filter(
            partnership=partnership,
            status__in=[CSRGrantChangeStatus.PENDING_ADMIN_REVIEW, CSRGrantChangeStatus.PENDING_COMPANY_APPROVAL]
        ).exists()
        if active_request:
            raise CSRValidationError("An active grant change request is already pending review for this partnership.", code="pending_change_request_exists")

        change_request = CSRGrantChangeRequest(
            partnership=partnership,
            requested_by=user,
            current_commitment=partnership.agreed_funding_amount,
            proposed_commitment=proposed_decimal,
            reason=reason_text,
            status=CSRGrantChangeStatus.PENDING_ADMIN_REVIEW,
        )

        if revised_budget_document:
            change_request.revised_budget_document = revised_budget_document

        change_request.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=None,
            new_status=change_request.status,
            actor_user=user,
            review_notes=f"Proposed grant change from ₹{change_request.current_commitment} to ₹{change_request.proposed_commitment}. Reason: {reason_text}",
            metadata={
                "change_request_id": str(change_request.id),
                "partnership_id": str(partnership.id),
                "partnership_code": partnership.partnership_code,
                "current_commitment": str(change_request.current_commitment),
                "proposed_commitment": str(change_request.proposed_commitment),
                "has_revised_budget": bool(revised_budget_document),
            },
        )

        return change_request


def admin_review_grant_change_request(user, request_id, decision, review_notes="", mou_amendment_document=None):
    """
    Stage 1 review by Platform Administrator for eligibility and supporting documents.
    If APPROVED: moves to PENDING_COMPANY_APPROVAL for corporate signatory sign-off.
    If REJECTED: transitions to REJECTED.
    """
    if not (user.is_staff or getattr(user, 'role', '') == 'ADMIN'):
        raise CSRUnauthorizedError("Only platform administrators can perform initial grant change review.", code="admin_required")

    decision_norm = str(decision).strip().upper()
    if decision_norm not in ['APPROVE', 'REJECT']:
        raise CSRValidationError("Decision must be either APPROVE or REJECT.", code="invalid_decision")

    with transaction.atomic():
        try:
            change_request = CSRGrantChangeRequest.objects.select_for_update().select_related('partnership').get(id=request_id)
        except (CSRGrantChangeRequest.DoesNotExist, ValueError):
            raise CSRNotFoundError("Grant change request not found.", code="change_request_not_found")

        if change_request.status != CSRGrantChangeStatus.PENDING_ADMIN_REVIEW:
            raise CSRValidationError("This grant change request is not in PENDING_ADMIN_REVIEW status.", code="invalid_status")

        old_status = change_request.status
        new_status = CSRGrantChangeStatus.PENDING_COMPANY_APPROVAL if decision_norm == 'APPROVE' else CSRGrantChangeStatus.REJECTED

        change_request.status = new_status
        change_request.admin_reviewed_by = user
        change_request.admin_reviewed_at = timezone.now()
        change_request.admin_review_notes = review_notes

        if mou_amendment_document:
            change_request.mou_amendment_document = mou_amendment_document

        change_request.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=change_request.partnership.id,
            old_status=old_status,
            new_status=new_status,
            actor_user=user,
            review_notes=f"Admin grant change review: {new_status}. {review_notes}".strip(),
            metadata={
                "change_request_id": str(change_request.id),
                "partnership_id": str(change_request.partnership.id),
                "partnership_code": change_request.partnership.partnership_code,
                "proposed_commitment": str(change_request.proposed_commitment),
            },
        )

        return change_request


def company_review_grant_change_request(user, request_id, decision, review_notes=""):
    """
    Stage 2 final approval by Corporate Partner.
    If APPROVED: updates the partnership's agreed_funding_amount in the database,
    logging the full transition history in the audit ledger.
    If REJECTED: rejects the request and keeps the original approved commitment intact.
    """
    decision_norm = str(decision).strip().upper()
    if decision_norm not in ['APPROVE', 'REJECT']:
        raise CSRValidationError("Decision must be either APPROVE or REJECT.", code="invalid_decision")

    with transaction.atomic():
        try:
            change_request = CSRGrantChangeRequest.objects.select_for_update().select_related('partnership').get(id=request_id)
        except (CSRGrantChangeRequest.DoesNotExist, ValueError):
            raise CSRNotFoundError("Grant change request not found.", code="change_request_not_found")

        if not _is_company_participant(user, change_request.partnership):
            raise CSRUnauthorizedError("Only the authorized corporate partner can approve bilateral grant amendments.", code="unauthorized_company")

        if change_request.status != CSRGrantChangeStatus.PENDING_COMPANY_APPROVAL:
            raise CSRValidationError("Grant change request must be reviewed by Admin before corporate decision.", code="invalid_status")

        old_status = change_request.status
        partnership = change_request.partnership

        if decision_norm == 'APPROVE':
            new_status = CSRGrantChangeStatus.APPROVED
            old_commitment = partnership.agreed_funding_amount
            new_commitment = change_request.proposed_commitment

            # Update the persisted commitment
            partnership.agreed_funding_amount = new_commitment
            partnership.save(update_fields=['agreed_funding_amount', 'updated_at'])

            change_request.status = new_status
            change_request.company_approved_by = user
            change_request.company_approved_at = timezone.now()
            change_request.company_review_notes = review_notes
            change_request.save()

            record_verification_event(
                entity_type=CSRAuditEntityType.PARTNERSHIP,
                entity_id=partnership.id,
                old_status=str(old_commitment),
                new_status=str(new_commitment),
                actor_user=user,
                review_notes=f"Approved bilateral grant amendment: Commitment increased from ₹{old_commitment} to ₹{new_commitment}. {review_notes}".strip(),
                metadata={
                    "change_request_id": str(change_request.id),
                    "old_commitment": str(old_commitment),
                    "new_commitment": str(new_commitment),
                    "approved_by_company": True,
                },
            )
        else:
            new_status = CSRGrantChangeStatus.REJECTED
            change_request.status = new_status
            change_request.company_approved_by = user
            change_request.company_approved_at = timezone.now()
            change_request.company_review_notes = review_notes
            change_request.save()

            record_verification_event(
                entity_type=CSRAuditEntityType.PARTNERSHIP,
                entity_id=partnership.id,
                old_status=old_status,
                new_status=new_status,
                actor_user=user,
                review_notes=f"Corporate grant change decision: {new_status}. {review_notes}".strip(),
                metadata={
                    "change_request_id": str(change_request.id),
                    "partnership_id": str(partnership.id),
                    "partnership_code": partnership.partnership_code,
                    "current_commitment": str(partnership.agreed_funding_amount),
                },
            )

        return change_request



# ===========================================================================
# 4. Financial Status Calculation & Reconciliation Dossier
# ===========================================================================

def get_contractual_payment_due_date(partnership):
    """
    Retrieves the contractual CSR payment due date or installment schedule deadline.

    CRITICAL FINANCIAL INTEGRITY RULES:
    1. Project execution horizon (`partnership.target_completion_date`) and NGO ground
       milestone deliverable deadlines (`milestone.target_completion_date`) represent
       project operational delivery timelines, NOT contractual CSR corporate wire deadlines.
       They MUST NEVER be treated as payment deadlines.
    2. In the current DaanGives database schema and migrations, there is no separate
       contractual payment schedule / installment table or persisted payment due date field.
       We do not invent artificial payment deadlines.
    3. If an authorized workflow or future schedule agreement establishes a genuine
       contractual schedule (e.g., via `partnership.get_contractual_payment_due_date()`,
       an agreed installment list/queryset in `partnership.payment_schedule`,
       or an explicit contractual attribute `contractual_payment_due_date` / `payment_due_date`
       populated by an authorized workflow), this helper inspects and returns that genuine
       contractual deadline.
    4. If no contractual payment deadline exists, returns None.
    """
    if not partnership:
        return None

    # 1. Custom/authorized callable on partnership
    if hasattr(partnership, 'get_contractual_payment_due_date') and callable(partnership.get_contractual_payment_due_date):
        try:
            return partnership.get_contractual_payment_due_date()
        except Exception:
            pass

    # 2. Contractual payment schedule (iterable of installment objects or dicts with due_date)
    schedule = getattr(partnership, 'payment_schedule', None)
    if schedule:
        today = timezone.now().date()
        due_dates = []
        try:
            for item in schedule:
                d = getattr(item, 'due_date', None) or (item.get('due_date') if isinstance(item, dict) else None)
                if d:
                    due_dates.append(d)
            if due_dates:
                overdue = [d for d in due_dates if d < today]
                return min(overdue) if overdue else min(due_dates)
        except Exception:
            pass

    # 3. Explicit contractual payment due date attribute populated on the instance
    contractual_due = getattr(partnership, 'contractual_payment_due_date', None)
    if contractual_due:
        return contractual_due

    # 4. Check payment_due_date if populated by an authorized workflow/migration
    explicit_payment_due = getattr(partnership, 'payment_due_date', None)
    if explicit_payment_due:
        return explicit_payment_due

    return None


def calculate_partnership_financial_status(partnership, disb_qs, exp_qs, contractual_payment_due_date=None):
    """
    Server-side rule-based financial status calculation.
    Never produces RECONCILED on zero or partial payments against a positive commitment.
    Separates facts:
      - Reported Wire != Evidence Reviewed != NGO Acknowledged != Project Expense Verified.

    Overdue Payment Policy:
      - OVERDUE status is ONLY triggered when an actual contractual payment deadline has elapsed
        with a positive outstanding grant commitment.
      - Project execution completion dates (target_completion_date) and NGO milestone
        deliverable dates are operational milestones, NOT contractual payment deadlines.
      - When no contractual payment due date exists, outstanding grants preserve their
        factual financial status (e.g. NOT_DISBURSED, PARTIALLY_DISBURSED, or PENDING_RECONCILIATION).
    """
    committed_amount = partnership.agreed_funding_amount or Decimal('0.00')

    # Exclude rejected disbursements from legitimate totals
    active_disb = disb_qs.exclude(review_status=CSRDisbursementReviewStatus.REJECTED)
    total_reported_disbursement = active_disb.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_verified_disbursement = disb_qs.filter(review_status=CSRDisbursementReviewStatus.VERIFIED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_pending_review_disbursement = disb_qs.filter(review_status=CSRDisbursementReviewStatus.PENDING_REVIEW).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_acknowledged_receipt = disb_qs.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.ACKNOWLEDGED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_disputed_receipt = disb_qs.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.DISPUTED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_pending_ack_receipt = disb_qs.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    disbursements_without_evidence = active_disb.filter(Q(evidence_document__isnull=True) | Q(evidence_document=''))
    disbursements_without_evidence_count = disbursements_without_evidence.count()

    # Expenses aggregates
    active_exp = exp_qs.exclude(review_status=CSRExpenseReviewStatus.REJECTED)
    total_reported_expenses = active_exp.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_verified_expenses = exp_qs.filter(review_status=CSRExpenseReviewStatus.VERIFIED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_pending_expenses = exp_qs.filter(review_status=CSRExpenseReviewStatus.SUBMITTED).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    # Outstanding commitment
    outstanding_commitment = max(Decimal('0.00'), committed_amount - total_verified_disbursement)

    # Contractual payment due date evaluation:
    # Stop deriving OVERDUE solely from target_completion_date or milestone dates.
    # Overdue requires a genuine contractual payment deadline to have elapsed with outstanding funds.
    today = timezone.now().date()
    is_overdue = False
    overdue_reason = ""
    contractual_due = contractual_payment_due_date or get_contractual_payment_due_date(partnership)

    if contractual_due and contractual_due < today and outstanding_commitment > Decimal('0.00'):
        is_overdue = True
        overdue_reason = (
            f"Contractual payment deadline ({contractual_due}) has passed "
            f"with ₹{outstanding_commitment} in committed funds outstanding."
        )

    # Hierarchy of status calculation
    if total_disputed_receipt > Decimal('0.00'):
        financial_status = CSRFinancialStatus.DISPUTED
        explanation = f"Recipient NGO has disputed ₹{total_disputed_receipt} in reported bank transfers (funds not credited)."
    elif active_disb.count() == 0:
        if is_overdue:
            financial_status = CSRFinancialStatus.OVERDUE
            explanation = overdue_reason
        else:
            financial_status = CSRFinancialStatus.NOT_DISBURSED
            explanation = f"Agreed grant commitment is ₹{committed_amount}. Zero corporate bank disbursements have been reported yet."
    elif disbursements_without_evidence_count > 0:
        financial_status = CSRFinancialStatus.AWAITING_EVIDENCE
        explanation = f"{disbursements_without_evidence_count} reported bank transfer(s) lack supporting payment advice or counterfoil."
    elif total_verified_disbursement == Decimal('0.00') and total_reported_disbursement > Decimal('0.00'):
        financial_status = CSRFinancialStatus.DISBURSEMENT_REPORTED
        explanation = f"₹{total_reported_disbursement} in corporate bank transfers has been reported with evidence and is awaiting administrative evidence review."
    elif total_pending_ack_receipt > Decimal('0.00'):
        financial_status = CSRFinancialStatus.AWAITING_NGO_ACKNOWLEDGEMENT
        explanation = f"₹{total_pending_ack_receipt} in reported bank transfers is awaiting NGO bank credit acknowledgement."
    elif total_verified_disbursement < committed_amount:
        if is_overdue:
            financial_status = CSRFinancialStatus.OVERDUE
            explanation = overdue_reason
        else:
            financial_status = CSRFinancialStatus.PARTIALLY_DISBURSED
            explanation = f"Partially disbursed: ₹{total_verified_disbursement} verified against ₹{committed_amount} commitment. Outstanding balance: ₹{outstanding_commitment}."
    else:
        # Full commitment has been disbursed and verified
        has_pending_items = (
            total_pending_review_disbursement > Decimal('0.00') or
            total_acknowledged_receipt < total_verified_disbursement or
            total_pending_expenses > Decimal('0.00')
        )
        milestones_qs = partnership.milestones.all()
        all_milestones_verified = milestones_qs.count() > 0 and milestones_qs.filter(status=MilestoneStatus.VERIFIED).count() == milestones_qs.count()

        if not has_pending_items and (total_verified_expenses >= total_acknowledged_receipt or all_milestones_verified):
            financial_status = CSRFinancialStatus.RECONCILED
            explanation = "All committed bank wire disbursements and audited project vouchers are fully verified, acknowledged, and reconciled."
        else:
            financial_status = CSRFinancialStatus.PENDING_RECONCILIATION
            explanation = f"Full commitment disbursed, but final expense audit or voucher verification is pending reconciliation (Verified Expenses: ₹{total_verified_expenses} / Disbursed: ₹{total_acknowledged_receipt})."

    return {
        "financial_status": financial_status,
        "explanation": explanation,
        "is_overdue": is_overdue,
        "contractual_payment_due_date": contractual_due,
        "committed_amount": committed_amount,
        "total_reported_disbursement": total_reported_disbursement,
        "total_verified_disbursement": total_verified_disbursement,
        "total_pending_review_disbursement": total_pending_review_disbursement,
        "total_acknowledged_receipt": total_acknowledged_receipt,
        "total_disputed_receipt": total_disputed_receipt,
        "total_pending_ack_receipt": total_pending_ack_receipt,
        "total_reported_expenses": total_reported_expenses,
        "total_verified_expenses": total_verified_expenses,
        "total_pending_expenses": total_pending_expenses,
        "outstanding_commitment": outstanding_commitment,
        "disbursements_without_evidence_count": disbursements_without_evidence_count,
    }


def get_partnership_reconciliation_dossier(user, partnership_id, request=None, contractual_payment_due_date=None):
    """
    Generates a multi-dimensional financial reconciliation dossier.
    Accurately separates:
      - Agreed Grant Commitment
      - Reported Corporate Disbursements (Off-platform wire)
      - Evidence-Reviewed Corporate Disbursements
      - NGO Acknowledged Receipts
      - Reported Project Expenses
      - Verified Eligible Project Expenses
      - Discrepancies and Gap Analysis
      - Grant Change Requests History
    """
    if isinstance(partnership_id, CSRPartnership):
        partnership = partnership_id
    else:
        try:
            partnership = CSRPartnership.objects.select_related('company', 'ngo', 'requirement').get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

    if not _is_partnership_participant(user, partnership):
        raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

    disb_qs = CSRDisbursement.objects.filter(partnership=partnership).order_by('-disbursement_date', '-created_at')
    exp_qs = CSRExpense.objects.filter(partnership=partnership).order_by('-expense_date', '-created_at')
    change_requests_qs = CSRGrantChangeRequest.objects.filter(partnership=partnership).order_by('-created_at')

    calc = calculate_partnership_financial_status(
        partnership, disb_qs, exp_qs, contractual_payment_due_date=contractual_payment_due_date
    )

    committed_amount = calc["committed_amount"]
    total_reported_disbursement = calc["total_reported_disbursement"]
    total_verified_disbursement = calc["total_verified_disbursement"]
    total_pending_disbursement = calc["total_pending_review_disbursement"]
    total_acknowledged_receipt = calc["total_acknowledged_receipt"]
    total_disputed_receipt = calc["total_disputed_receipt"]
    total_reported_expenses = calc["total_reported_expenses"]
    total_verified_expenses = calc["total_verified_expenses"]
    total_pending_expenses = calc["total_pending_expenses"]
    outstanding_commitment = calc["outstanding_commitment"]
    financial_status = calc["financial_status"]
    status_explanation = calc["explanation"]

    # Gaps and Over-commitment
    unverified_disbursement_gap = total_reported_disbursement - total_verified_disbursement
    unacknowledged_receipt_gap = total_verified_disbursement - total_acknowledged_receipt
    unspent_acknowledged_funds = total_acknowledged_receipt - total_verified_expenses
    is_over_commitment = total_reported_disbursement > committed_amount
    over_commitment_amount = max(Decimal('0.00'), total_reported_disbursement - committed_amount)

    alerts = []
    if is_over_commitment:
        alerts.append(f"OVER-COMMITMENT WARNING: Reported corporate disbursements (₹{total_reported_disbursement}) exceed the approved bilateral grant (₹{committed_amount}) by ₹{over_commitment_amount}.")
    if total_disputed_receipt > Decimal('0.00'):
        alerts.append(f"NGO has raised a formal dispute regarding ₹{total_disputed_receipt} in reported bank transfers.")
    if unverified_disbursement_gap > Decimal('0.00'):
        alerts.append(f"₹{unverified_disbursement_gap} in reported company disbursements awaits administrative evidence verification.")
    if unacknowledged_receipt_gap > Decimal('0.00'):
        alerts.append(f"₹{unacknowledged_receipt_gap} in verified bank disbursements has not yet been acknowledged by the NGO.")
    if total_pending_expenses > Decimal('0.00'):
        alerts.append(f"₹{total_pending_expenses} in reported ground expenditures awaits invoice verification.")
    if financial_status == CSRFinancialStatus.NOT_DISBURSED:
        alerts.append(f"Awaiting initial corporate disbursement of ₹{committed_amount}. No bank transfers have been reported yet.")
    elif financial_status == CSRFinancialStatus.PARTIALLY_DISBURSED:
        alerts.append(f"Partially disbursed: ₹{outstanding_commitment} of the ₹{committed_amount} commitment remains outstanding.")
    elif financial_status == CSRFinancialStatus.OVERDUE:
        alerts.append(f"PAYMENT OVERDUE: {status_explanation}")

    # Milestones Summary
    milestones_qs = partnership.milestones.all()
    total_milestones = milestones_qs.count()
    verified_milestones = milestones_qs.filter(status=MilestoneStatus.VERIFIED).count()
    progress_pct = int(round((verified_milestones / total_milestones) * 100)) if total_milestones > 0 else 0

    # Recent Audit Log for Partnership
    recent_audits = CSRVerificationHistory.objects.filter(
        Q(entity_type=CSRAuditEntityType.PARTNERSHIP, entity_id=partnership.id) |
        Q(entity_type=CSRAuditEntityType.DISBURSEMENT, entity_id__in=disb_qs.values_list('id', flat=True)) |
        Q(entity_type=CSRAuditEntityType.EXPENSE, entity_id__in=exp_qs.values_list('id', flat=True)) |
        Q(entity_type=CSRAuditEntityType.MILESTONE, entity_id__in=milestones_qs.values_list('id', flat=True))
    ).order_by('-created_at')[:25]


    audit_timeline = [
        {
            "id": str(a.id),
            "entity_type": a.entity_type,
            "old_status": a.old_status,
            "new_status": a.new_status,
            "reviewed_by_name": a.reviewed_by.get_full_name() or a.reviewed_by.email if a.reviewed_by else "System",
            "review_notes": a.review_notes,
            "created_at": a.created_at.isoformat(),
        }
        for a in recent_audits
    ]

    serializer_context = {'request': request} if request else {}
    serialized_disbursements = CSRDisbursementSerializer(disb_qs, many=True, context=serializer_context).data
    serialized_expenses = CSRExpenseSerializer(exp_qs, many=True, context=serializer_context).data
    serialized_change_requests = CSRGrantChangeRequestSerializer(change_requests_qs, many=True, context=serializer_context).data

    # Human readable display for financial status
    status_display_map = dict(CSRFinancialStatus.choices)
    financial_status_display = status_display_map.get(financial_status, financial_status)

    is_reconciled = (financial_status == CSRFinancialStatus.RECONCILED)
    needs_reconciliation = not is_reconciled

    total_unreconciled_delta = (
        outstanding_commitment +
        unverified_disbursement_gap +
        unacknowledged_receipt_gap +
        total_disputed_receipt +
        total_pending_expenses
    )

    dossier = {
        "partnership_id": str(partnership.id),
        "partnership_code": partnership.partnership_code,
        "requirement_title": partnership.requirement.title,
        "company_name": partnership.company.company_name,
        "ngo_name": getattr(partnership.ngo, 'display_name', getattr(partnership.ngo, 'legal_name', '')),
        "status": partnership.status,
        "status_display": partnership.get_status_display(),

        # Server-side authoritative financial status
        "financial_status": financial_status,
        "financial_status_display": financial_status_display,
        "financial_status_explanation": status_explanation,
        "explanation": status_explanation,
        "is_overdue": calc.get("is_overdue", False),
        "contractual_payment_due_date": str(calc.get("contractual_payment_due_date")) if calc.get("contractual_payment_due_date") else None,
        "is_reconciled": is_reconciled,

        # Multi-dimensional comparison blocks
        "commitment": {
            "amount": str(committed_amount),
            "currency": "INR",
        },
        "reported_disbursements": {
            "total_amount": str(total_reported_disbursement),
            "count": disb_qs.exclude(review_status=CSRDisbursementReviewStatus.REJECTED).count(),
        },
        "verified_disbursements": {
            "total_amount": str(total_verified_disbursement),
            "count": disb_qs.filter(review_status=CSRDisbursementReviewStatus.VERIFIED).count(),
        },
        "pending_review_disbursements": {
            "total_amount": str(total_pending_disbursement),
            "count": disb_qs.filter(review_status=CSRDisbursementReviewStatus.PENDING_REVIEW).count(),
        },
        "ngo_acknowledged_disbursements": {
            "total_amount": str(total_acknowledged_receipt),
            "count": disb_qs.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.ACKNOWLEDGED).count(),
        },
        "disputed_disbursements": {
            "total_amount": str(total_disputed_receipt),
            "count": disb_qs.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.DISPUTED).count(),
        },
        "reported_expenses": {
            "total_amount": str(total_reported_expenses),
            "count": exp_qs.exclude(review_status=CSRExpenseReviewStatus.REJECTED).count(),
        },
        "verified_expenses": {
            "total_amount": str(total_verified_expenses),
            "count": exp_qs.filter(review_status=CSRExpenseReviewStatus.VERIFIED).count(),
        },
        "pending_expenses": {
            "total_amount": str(total_pending_expenses),
            "count": exp_qs.filter(review_status=CSRExpenseReviewStatus.SUBMITTED).count(),
        },
        "outstanding_commitment": str(outstanding_commitment),
        "is_over_commitment": is_over_commitment,
        "over_commitment_amount": str(over_commitment_amount),

        # Discrepancy details
        "unreconciled_discrepancies": {
            "needs_reconciliation": needs_reconciliation,
            "is_reconciled": is_reconciled,
            "explanation": status_explanation,
            "total_unreconciled_delta": str(total_unreconciled_delta),
            "alerts": alerts,
        },

        # Backward compatibility block for frontend views expecting financials.*
        "financials": {
            "agreed_funding_amount": str(committed_amount),
            "total_disbursed_reported": str(total_reported_disbursement),
            "total_disbursed_verified": str(total_verified_disbursement),
            "total_disbursed_pending_review": str(total_pending_disbursement),
            "total_acknowledged_by_ngo": str(total_acknowledged_receipt),
            "total_disputed_by_ngo": str(total_disputed_receipt),
            "total_expenses_reported": str(total_reported_expenses),
            "total_expenses_verified": str(total_verified_expenses),
            "total_expenses_pending": str(total_pending_expenses),
            "unverified_disbursement_gap": str(unverified_disbursement_gap),
            "unacknowledged_receipt_gap": str(unacknowledged_receipt_gap),
            "unspent_acknowledged_funds": str(unspent_acknowledged_funds),
            "remaining_commitment": str(outstanding_commitment),
            "needs_reconciliation": needs_reconciliation,
            "is_reconciled": is_reconciled,
            "is_overdue": calc.get("is_overdue", False),
            "contractual_payment_due_date": str(calc.get("contractual_payment_due_date")) if calc.get("contractual_payment_due_date") else None,
            "financial_status": financial_status,
            "financial_status_display": financial_status_display,
            "reconciliation_alerts": alerts,
        },

        # Itemized lists
        "disbursements": serialized_disbursements,
        "expenses": serialized_expenses,
        "change_requests": serialized_change_requests,
        "milestones_summary": {
            "total": total_milestones,
            "verified": verified_milestones,
            "progress_percentage": progress_pct,
        },
        "audit_timeline": audit_timeline,
        "audit_history": audit_timeline,
        "statutory_disclosure": (
            "Direct Corporate-to-NGO Bank Transfer: DaanGives does not collect, hold, or escrow CSR funds. "
            "Reported disbursements represent bilateral bank wires with uploaded transfer advice and are independently "
            "cross-referenced against NGO bank receipts, evidence reviews, and project vouchers. Evidence review by platform "
            "reviewers confirms receipt documentation on file and does not constitute independent banking API confirmation."
        ),
    }

    return dossier
