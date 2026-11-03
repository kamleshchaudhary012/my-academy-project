"""
CSR Milestone Service
=====================
Manages sequenced deliverables, evidence submission, completion percentage tracking,
and verification reviews for CSR partnerships.
"""

from typing import Optional, Dict, Any
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from ngo.models import NGOProfile
from csr.models import (
    CSRPartnership,
    PartnershipMilestone,
    MilestoneStatus,
    CSRPartnershipStatus,
    CSRAuditEntityType,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
    CSRUnauthorizedError,
)
from csr.services.audit_service import record_verification_event
from csr.services.partnership_service import get_partnership
from csr.services.notification_service import dispatch_csr_notification, CSRNotificationEventType

User = get_user_model()


def _is_milestone_participant(user, milestone: PartnershipMilestone) -> bool:
    """Check if the user is a participant of the parent partnership or an Admin."""
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'role', None) == 'ADMIN':
        return True
    if hasattr(user, 'company_profile') and milestone.partnership.company == user.company_profile:
        return True
    if hasattr(user, 'ngo_profile') and milestone.partnership.ngo == user.ngo_profile:
        return user.ngo_profile.status == NGOProfile.Status.APPROVED and getattr(user.ngo_profile, 'is_active', False)
    return False


def get_milestone(user, milestone_id: Any) -> PartnershipMilestone:
    """
    Retrieve a PartnershipMilestone derived through parent partnership participant scoping.
    """
    try:
        milestone = PartnershipMilestone.objects.select_related('partnership', 'partnership__company', 'partnership__ngo').get(id=milestone_id)
    except (PartnershipMilestone.DoesNotExist, ValueError):
        raise CSRNotFoundError("Partnership milestone not found.", code="milestone_not_found")

    if not _is_milestone_participant(user, milestone):
        raise CSRNotFoundError("Partnership milestone not found or access denied.", code="milestone_not_found")

    return milestone


def list_milestones(user, partnership_id: Any):
    """
    List all milestones for a partnership, accessible only to bilateral participants or Admin.
    """
    partnership = get_partnership(user, partnership_id)
    return PartnershipMilestone.objects.filter(partnership=partnership).order_by('sequence_number')


def create_milestone(
    user,
    partnership_id: Any,
    data: Dict[str, Any],
    evidence_doc=None,
) -> PartnershipMilestone:
    """
    Create a new milestone within an active or pending partnership.
    """
    partnership = get_partnership(user, partnership_id)

    if partnership.status in (CSRPartnershipStatus.COMPLETED, CSRPartnershipStatus.CANCELLED, CSRPartnershipStatus.TERMINATED):
        raise CSRStateError(
            f"Cannot add milestones to partnership in terminal status '{partnership.status}'.",
            code="cannot_modify_terminal_partnership",
        )

    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'partnership', 'status', 'verified_by', 'verified_at',
            'actual_completion_date', 'created_at', 'updated_at', 'evidence_document',
        }
    }

    required_fields = ['sequence_number', 'title', 'description', 'target_completion_date']
    missing = [f for f in required_fields if sanitized_data.get(f) is None or sanitized_data.get(f) == ""]
    if missing:
        raise CSRValidationError(
            f"Missing mandatory milestone fields: {', '.join(missing)}",
            code="missing_required_fields",
            details={"missing_fields": missing},
        )

    seq_num = int(sanitized_data['sequence_number'])
    if seq_num < 1:
        raise CSRValidationError("sequence_number must be at least 1.", code="invalid_sequence_number")

    with transaction.atomic():
        if PartnershipMilestone.objects.filter(partnership=partnership, sequence_number=seq_num).exists():
            raise CSRConflictError(
                f"Milestone #{seq_num} already exists for this partnership.",
                code="duplicate_sequence_number",
            )

        pct = int(sanitized_data.get('completion_percentage', 0))
        if pct < 0 or pct > 100:
            raise CSRValidationError("completion_percentage must be between 0 and 100.", code="invalid_completion_percentage")

        milestone = PartnershipMilestone(
            partnership=partnership,
            status=MilestoneStatus.PENDING,
            **sanitized_data,
        )
        if evidence_doc:
            milestone.evidence_document = evidence_doc

        try:
            milestone.full_clean(exclude=['partnership'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)
        milestone.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.MILESTONE,
            entity_id=milestone.id,
            old_status=None,
            new_status=MilestoneStatus.PENDING,
            actor_user=user,
            review_notes=f"Milestone #{seq_num} created for partnership {partnership.partnership_code}.",
        )

    return milestone


def update_milestone(
    user,
    milestone_id: Any,
    data: Dict[str, Any],
    evidence_doc=None,
) -> PartnershipMilestone:
    """
    Update milestone details while in PENDING or REVISION_REQUESTED state.
    """
    milestone = get_milestone(user, milestone_id)

    if milestone.status == MilestoneStatus.VERIFIED:
        raise CSRStateError("Verified milestones cannot be modified.", code="cannot_modify_verified_milestone")

    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'partnership', 'status', 'verified_by', 'verified_at',
            'actual_completion_date', 'created_at', 'updated_at', 'evidence_document',
        }
    }

    with transaction.atomic():
        milestone = PartnershipMilestone.objects.select_for_update().get(id=milestone.id)

        new_seq = sanitized_data.get('sequence_number')
        if new_seq is not None and int(new_seq) != milestone.sequence_number:
            new_seq_int = int(new_seq)
            if new_seq_int < 1:
                raise CSRValidationError("sequence_number must be at least 1.", code="invalid_sequence_number")
            if PartnershipMilestone.objects.filter(partnership=milestone.partnership, sequence_number=new_seq_int).exclude(id=milestone.id).exists():
                raise CSRConflictError(f"Milestone #{new_seq_int} already exists for this partnership.", code="duplicate_sequence_number")

        for field, val in sanitized_data.items():
            if hasattr(milestone, field):
                setattr(milestone, field, val)

        if evidence_doc is not None:
            milestone.evidence_document = evidence_doc

        try:
            milestone.full_clean(exclude=['partnership'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)
        milestone.save()

    return milestone


def submit_evidence(
    user,
    milestone_id: Any,
    evidence_notes: str = "",
    evidence_file=None,
    completion_percentage: Optional[int] = None,
) -> PartnershipMilestone:
    """
    Submit progress evidence for milestone review (PENDING / REVISION_REQUESTED -> SUBMITTED).
    """
    milestone = get_milestone(user, milestone_id)

    # Corporate partner cannot submit deliverable evidence on behalf of the executing NGO
    if hasattr(user, 'company_profile') and milestone.partnership.company == user.company_profile and not (user.is_staff or getattr(user, 'role', None) == 'ADMIN'):
        raise CSRUnauthorizedError("Only the recipient NGO partner or an administrator can submit deliverable milestone evidence.", code="unauthorized_submitter")

    with transaction.atomic():
        milestone = PartnershipMilestone.objects.select_for_update().get(id=milestone.id)

        if milestone.status == MilestoneStatus.VERIFIED:
            raise CSRStateError("Milestone is already verified.", code="already_verified")

        if evidence_file is not None:
            milestone.evidence_document = evidence_file

        if evidence_notes:
            milestone.evidence_notes = evidence_notes

        if completion_percentage is not None:
            pct = int(completion_percentage)
            if pct < 1 or pct > 100:
                raise CSRValidationError("completion_percentage on submission must be between 1 and 100.", code="invalid_completion_percentage")
            milestone.completion_percentage = pct

        try:
            milestone.full_clean(exclude=['partnership'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)

        old_status = milestone.status
        milestone.status = MilestoneStatus.SUBMITTED
        milestone.save(update_fields=['evidence_document', 'evidence_notes', 'completion_percentage', 'status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.MILESTONE,
            entity_id=milestone.id,
            old_status=old_status,
            new_status=MilestoneStatus.SUBMITTED,
            actor_user=user,
            review_notes=f"Evidence submitted for milestone #{milestone.sequence_number}.",
        )

    return milestone


def review_milestone(
    user,
    milestone_id: Any,
    decision: str,
    notes: str = "",
) -> PartnershipMilestone:
    """
    Review submitted milestone progress (decision: 'VERIFY' or 'REQUEST_REVISION').
    """
    milestone = get_milestone(user, milestone_id)

    # Executing NGO cannot review or verify its own milestone deliverables
    if hasattr(user, 'ngo_profile') and milestone.partnership.ngo == user.ngo_profile and not (user.is_staff or getattr(user, 'role', None) == 'ADMIN'):
        raise CSRUnauthorizedError("NGO partners cannot review or verify their own milestones. Only the corporate sponsor or an administrator can review deliverables.", code="unauthorized_reviewer")

    if decision not in ('VERIFY', 'REQUEST_REVISION'):
        raise CSRValidationError("Decision must be either 'VERIFY' or 'REQUEST_REVISION'.", code="invalid_review_decision")

    with transaction.atomic():
        milestone = PartnershipMilestone.objects.select_for_update().get(id=milestone.id)

        if milestone.status == MilestoneStatus.VERIFIED:
            raise CSRStateError("Milestone is already verified.", code="already_verified")

        if milestone.status != MilestoneStatus.SUBMITTED:
            raise CSRStateError(
                f"Cannot review milestone in status '{milestone.status}'. Must be SUBMITTED.",
                code="cannot_review_unsubmitted_milestone",
            )

        old_status = milestone.status
        now = timezone.now()

        if decision == 'VERIFY':
            milestone.status = MilestoneStatus.VERIFIED
            milestone.verified_by = user
            milestone.verified_at = now
            milestone.actual_completion_date = now.date()
            milestone.completion_percentage = 100
            milestone.save(update_fields=['status', 'verified_by', 'verified_at', 'actual_completion_date', 'completion_percentage', 'updated_at'])

            record_verification_event(
                entity_type=CSRAuditEntityType.MILESTONE,
                entity_id=milestone.id,
                old_status=old_status,
                new_status=MilestoneStatus.VERIFIED,
                actor_user=user,
                review_notes=f"Milestone #{milestone.sequence_number} verified and completed. {notes}".strip(),
            )
        else:  # REQUEST_REVISION
            if not notes:
                raise CSRValidationError("Feedback notes are mandatory when requesting milestone revision.", code="missing_revision_notes")

            milestone.status = MilestoneStatus.REVISION_REQUESTED
            milestone.evidence_notes = f"{milestone.evidence_notes or ''}\n[Revision Requested]: {notes}".strip()
            milestone.save(update_fields=['status', 'evidence_notes', 'updated_at'])

            record_verification_event(
                entity_type=CSRAuditEntityType.MILESTONE,
                entity_id=milestone.id,
                old_status=old_status,
                new_status=MilestoneStatus.REVISION_REQUESTED,
                actor_user=user,
                review_notes=f"Revision requested for milestone #{milestone.sequence_number}: {notes}",
            )

    return milestone
