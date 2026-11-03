"""
CSR Partnership Service
=======================
Manages bilateral corporate-NGO CSR partnerships, MoU execution, project status
transitions, progress tracking, and informational off-platform disbursement records.
"""

import uuid
from decimal import Decimal
from typing import Optional, Dict, Any
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from ngo.models import NGOProfile
from csr.models import (
    CSRPartnership,
    CSRPartnershipStatus,
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRRequirement,
    CSRRequirementStatus,
    MilestoneStatus,
    CSRAuditEntityType,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
)
from csr.services.audit_service import record_verification_event

User = get_user_model()


def _generate_partnership_code() -> str:
    """Generate a unique bilateral partnership code (e.g. CSR-PT-20260917-ABC123)."""
    date_str = timezone.now().strftime('%Y%m%d')
    while True:
        suffix = uuid.uuid4().hex[:6].upper()
        code = f"CSR-PT-{date_str}-{suffix}"
        if not CSRPartnership.objects.filter(partnership_code=code).exists():
            return code


def _is_participant(user, partnership: CSRPartnership) -> bool:
    """Check if the user is the corporate partner, the NGO partner, or an active ADMIN."""
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'role', None) == 'ADMIN':
        return True
    from csr.models import CompanyProfile
    role = getattr(user, 'role', None)
    if role == 'COMPANY':
        company_profile = CompanyProfile.objects.filter(user=user).first()
        if company_profile and (partnership.company_id == company_profile.id or partnership.company == company_profile):
            return True
    elif role == 'NGO':
        ngo_profile = NGOProfile.objects.filter(user=user, status=NGOProfile.Status.APPROVED, is_active=True).first()
        if ngo_profile and (partnership.ngo_id == ngo_profile.id or partnership.ngo == ngo_profile):
            return True
    return False


def get_partnership(user, partnership_id: Any) -> CSRPartnership:
    """
    Retrieve a CSRPartnership scoped strictly to bilateral participants or ADMIN.
    """
    try:
        partnership = CSRPartnership.objects.select_related('company', 'ngo', 'requirement', 'support_request').get(id=partnership_id)
    except (CSRPartnership.DoesNotExist, ValueError):
        raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

    if not _is_participant(user, partnership):
        raise CSRNotFoundError("CSR partnership not found or access denied.", code="partnership_not_found")

    return partnership


def list_partnerships_for_user(user, status: Optional[str] = None):
    """
    List partnerships accessible to the authenticated tenant (Company, NGO, or Admin).
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")

    role = getattr(user, 'role', None)
    if role == 'COMPANY':
        try:
            qs = CSRPartnership.objects.filter(company=user.company_profile)
        except Exception:
            return CSRPartnership.objects.none()
    elif role == 'NGO':
        try:
            ngo_profile = user.ngo_profile
            if ngo_profile.status != NGOProfile.Status.APPROVED or not getattr(ngo_profile, 'is_active', False):
                raise CSROwnershipError("NGO account is not approved for CSR operations.", code="ngo_not_approved")
            qs = CSRPartnership.objects.filter(ngo=ngo_profile)
        except CSROwnershipError:
            raise
        except Exception:
            return CSRPartnership.objects.none()
    elif role == 'ADMIN':
        qs = CSRPartnership.objects.all()
    else:
        raise CSROwnershipError("Caller role cannot access partnerships.", code="invalid_role")

    if status:
        qs = qs.filter(status=status)

    return qs.select_related('company', 'ngo', 'requirement').order_by('-created_at')


def create_partnership_from_request(
    support_request: CSRSupportRequest,
    agreed_funding_amount: Optional[Decimal] = None,
    execution_start_date=None,
    target_completion_date=None,
) -> CSRPartnership:
    """
    Create a new bilateral CSRPartnership from an ACCEPTED CSRSupportRequest.
    Idempotent under concurrency: if a partnership already exists for this support request, returns it.
    """
    with transaction.atomic():
        # Check if already exists
        existing = CSRPartnership.objects.filter(support_request=support_request).first()
        if existing:
            return existing

        # Ensure corporate partner is verified and approved
        from csr.models import CompanyVerificationStatus
        if support_request.company.verification_status != CompanyVerificationStatus.APPROVED:
            raise CSRValidationError(
                "Corporate partner must be fully verified and approved by admin before executing CSR partnerships.",
                code="company_not_approved",
            )

        # Ensure NGO partner is approved and CSR verified (P0-1 Fix)
        ngo = support_request.requirement.ngo
        if ngo.status != NGOProfile.Status.APPROVED or not getattr(ngo, 'is_active', False):
            raise CSRValidationError("NGO partner is not active or approved.", code="ngo_not_approved")

        legal = getattr(ngo, 'legal_info', None)
        if not legal or not legal.is_csr_eligible:
            raise CSRValidationError("NGO partner does not satisfy statutory CSR eligibility criteria.", code="ngo_csr_ineligible")

        verif = getattr(ngo, 'verification', None)
        if not verif or not verif.is_csr_verified:
            raise CSRValidationError("NGO partner has not been verified by admin for CSR funding operations.", code="ngo_csr_not_verified")

        funding = agreed_funding_amount if agreed_funding_amount is not None else support_request.proposed_funding
        funding_dec = Decimal(str(funding))
        if funding_dec < Decimal('1000.00'):
            raise CSRValidationError("agreed_funding_amount must be at least ₹1,000.00.", code="funding_too_low")

        start_d = execution_start_date or support_request.requirement.start_date or timezone.now().date()
        target_d = target_completion_date or support_request.requirement.expected_completion_date
        if target_d < start_d:
            raise CSRValidationError("target_completion_date must be on or after execution_start_date.", code="invalid_date_order")

        code = _generate_partnership_code()

        partnership = CSRPartnership(
            company=support_request.company,
            ngo=support_request.requirement.ngo,
            requirement=support_request.requirement,
            support_request=support_request,
            partnership_code=code,
            agreed_funding_amount=funding_dec,
            disbursed_amount_reported=Decimal('0.00'),
            execution_start_date=start_d,
            target_completion_date=target_d,
            status=CSRPartnershipStatus.PENDING_MOU,
        )
        try:
            partnership.full_clean(exclude=['company', 'ngo', 'requirement', 'support_request'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)
        partnership.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=None,
            new_status=CSRPartnershipStatus.PENDING_MOU,
            actor_user=None,
            review_notes=f"Partnership formed from support request {support_request.id}.",
            metadata={"partnership_code": code, "agreed_funding": str(funding_dec)},
        )

    return partnership


def activate_partnership(user, partnership_id: Any, mou_file=None) -> CSRPartnership:
    """
    Activate a partnership following MoU execution (PENDING_MOU / PAUSED -> ACTIVE).
    """
    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_participant(user, partnership):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if partnership.status not in (CSRPartnershipStatus.PENDING_MOU, CSRPartnershipStatus.PAUSED):
            raise CSRStateError(
                f"Cannot activate partnership from status '{partnership.status}'.",
                code="invalid_activation_state",
            )

        old_status = partnership.status
        partnership.status = CSRPartnershipStatus.ACTIVE
        if mou_file is not None:
            partnership.signed_mou_document = mou_file

        try:
            partnership.full_clean(exclude=['company', 'ngo', 'requirement', 'support_request'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)

        partnership.save()

        # Update parent requirement status to IN_EXECUTION if appropriate
        req = CSRRequirement.objects.select_for_update().get(id=partnership.requirement_id)
        if req.status in (CSRRequirementStatus.APPROVED, CSRRequirementStatus.OPEN_FOR_CSR, CSRRequirementStatus.PARTNERED):
            req.status = CSRRequirementStatus.IN_EXECUTION
            req.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=old_status,
            new_status=CSRPartnershipStatus.ACTIVE,
            actor_user=user,
            review_notes="Partnership activated into ground execution.",
        )

    return partnership


def pause_partnership(user, partnership_id: Any, reason: str = "") -> CSRPartnership:
    """
    Pause an active partnership (ACTIVE -> PAUSED).
    """
    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_participant(user, partnership):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if partnership.status != CSRPartnershipStatus.ACTIVE:
            raise CSRStateError(
                f"Only ACTIVE partnerships can be paused. Current status: '{partnership.status}'.",
                code="cannot_pause_inactive_partnership",
            )

        old_status = partnership.status
        partnership.status = CSRPartnershipStatus.PAUSED
        partnership.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=old_status,
            new_status=CSRPartnershipStatus.PAUSED,
            actor_user=user,
            review_notes=f"Partnership paused: {reason}" if reason else "Partnership paused.",
        )

    return partnership


def resume_partnership(user, partnership_id: Any) -> CSRPartnership:
    """
    Resume a paused partnership back to ACTIVE (PAUSED -> ACTIVE).
    """
    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_participant(user, partnership):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if partnership.status != CSRPartnershipStatus.PAUSED:
            raise CSRStateError(
                f"Only PAUSED partnerships can be resumed. Current status: '{partnership.status}'.",
                code="cannot_resume_unpaused_partnership",
            )

        old_status = partnership.status
        partnership.status = CSRPartnershipStatus.ACTIVE
        partnership.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=old_status,
            new_status=CSRPartnershipStatus.ACTIVE,
            actor_user=user,
            review_notes="Partnership resumed.",
        )

    return partnership


def complete_partnership(user, partnership_id: Any) -> CSRPartnership:
    """
    Complete an active partnership (ACTIVE -> COMPLETED).
    """
    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_participant(user, partnership):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if partnership.status != CSRPartnershipStatus.ACTIVE:
            raise CSRStateError(
                f"Only ACTIVE partnerships can be completed. Current status: '{partnership.status}'.",
                code="cannot_complete_inactive_partnership",
            )

        now = timezone.now()
        old_status = partnership.status
        partnership.status = CSRPartnershipStatus.COMPLETED
        partnership.actual_completion_date = now.date()
        partnership.completed_at = now
        partnership.save(update_fields=['status', 'actual_completion_date', 'completed_at', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=old_status,
            new_status=CSRPartnershipStatus.COMPLETED,
            actor_user=user,
            review_notes="Partnership completed successfully.",
        )

    return partnership


def cancel_partnership(user, partnership_id: Any, reason: str = "") -> CSRPartnership:
    """
    Cancel or terminate a partnership (PENDING_MOU / ACTIVE / PAUSED -> CANCELLED).
    """
    if not reason:
        raise CSRValidationError("A cancellation reason is mandatory.", code="missing_cancellation_reason")

    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_participant(user, partnership):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if partnership.status in (CSRPartnershipStatus.COMPLETED, CSRPartnershipStatus.CANCELLED, CSRPartnershipStatus.TERMINATED):
            raise CSRStateError(
                f"Cannot cancel partnership with terminal status '{partnership.status}'.",
                code="cannot_cancel_terminal_partnership",
            )

        old_status = partnership.status
        partnership.status = CSRPartnershipStatus.CANCELLED
        partnership.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=old_status,
            new_status=CSRPartnershipStatus.CANCELLED,
            actor_user=user,
            review_notes=f"Partnership cancelled: {reason}",
        )

    return partnership


def record_off_platform_disbursement(
    user,
    partnership_id: Any,
    disbursed_amount: Any,
    notes: str = "",
) -> CSRPartnership:
    """
    Record an informational off-platform corporate bank disbursement report.
    PURELY INFORMATIONAL: No Razorpay, No PaymentTransaction, No MonetaryDonation.
    """
    if not disbursed_amount:
        raise CSRValidationError("disbursed_amount must be provided.", code="missing_disbursement_amount")

    amount_dec = Decimal(str(disbursed_amount))
    if amount_dec <= Decimal('0.00'):
        raise CSRValidationError("disbursed_amount must be greater than zero.", code="invalid_disbursement_amount")

    with transaction.atomic():
        try:
            partnership = CSRPartnership.objects.select_for_update().get(id=partnership_id)
        except (CSRPartnership.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        if not _is_participant(user, partnership):
            raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

        partnership.disbursed_amount_reported += amount_dec
        partnership.save(update_fields=['disbursed_amount_reported', 'updated_at'])

        # Persist itemized CSRDisbursement record for complete financial auditability
        from csr.models import CSRDisbursement, CSRDisbursementReviewStatus, CSRNgoAcknowledgementStatus
        CSRDisbursement.objects.create(
            partnership=partnership,
            reported_by=user,
            amount=amount_dec,
            currency='INR',
            notes=notes,
            review_status=CSRDisbursementReviewStatus.PENDING_REVIEW,
            ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT,
        )


        record_verification_event(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=partnership.id,
            old_status=partnership.status,
            new_status=partnership.status,
            actor_user=user,
            review_notes=f"Off-platform disbursement recorded: ₹{amount_dec}. {notes}".strip(),
            metadata={
                "disbursed_increment": str(amount_dec),
                "total_reported": str(partnership.disbursed_amount_reported),
                "notes": notes,
            },
        )

    return partnership
