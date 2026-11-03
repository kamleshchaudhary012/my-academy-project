"""
DaanGives NGO Verification Service — Phase 3.2
===============================================
change_ngo_verification_status() is the SOLE authorized path for
all NGO verification state transitions.

Architecture:
  1. Validates the proposed transition is in ALLOWED_TRANSITIONS
  2. Validates the actor has permission for this transition
  3. Applies side effects (is_active, timestamps) based on new_status
  4. Updates NGOProfile.status + is_active (atomic)
  5. Updates NGOVerification fields (atomic, same transaction)
  6. Creates exactly ONE NGOVerificationHistory record (INSERT-only)
  7. All steps wrapped in transaction.atomic() — full rollback on failure

Email notifications are dispatched via Django's on_commit() hook
AFTER the transaction commits, so a failed email never rolls back
a successful status change.

IMPORTANT:
  No API endpoint calls this service directly in Phase 3.
  It is used by model-layer tests in Phase 3.4.
  API views will call it in Phase 3.6.
"""

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _


class StatusTransitionError(Exception):
    """Raised when a status transition is not in the allowed transition map."""
    pass


class ResubmissionLimitError(Exception):
    """Raised when an NGO has exhausted resubmission cycles."""
    pass


# ---------------------------------------------------------------------------
# Allowed Transition Map
# ---------------------------------------------------------------------------
# Format: (from_status, to_status) → actor_types_allowed
# actor_types_allowed: set of strings from NGOVerificationHistory.ActorType
#
# NOTE: These are the APPLICATION-LEVEL allowed transitions.
# Permission checks (is_admin, is_owner) are enforced separately.
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS = {
    # NGO submits for the first time
    ('DRAFT',               'SUBMITTED'):           {'NGO'},
    # Admin starts review
    ('SUBMITTED',           'UNDER_REVIEW'):         {'ADMIN'},
    # Admin decisions
    ('UNDER_REVIEW',        'APPROVED'):             {'ADMIN'},
    ('UNDER_REVIEW',        'CORRECTION_REQUIRED'):  {'ADMIN'},
    ('UNDER_REVIEW',        'REJECTED'):             {'ADMIN'},
    # NGO resubmits after correction
    ('CORRECTION_REQUIRED', 'SUBMITTED'):            {'NGO'},
    # Admin lifecycle management
    ('APPROVED',            'SUSPENDED'):            {'ADMIN'},
    ('SUSPENDED',           'APPROVED'):             {'ADMIN'},
    # Admin reopen workflow
    ('REJECTED',            'DRAFT'):                {'ADMIN'},
    ('CORRECTION_REQUIRED', 'DRAFT'):                {'ADMIN'},
}

# Statuses where is_active must be True
ACTIVE_ON_STATUS = {'APPROVED'}


def _apply_side_effects(ngo_profile, verification, new_status, actor, now):
    """
    Apply status-specific side effects to NGOProfile and NGOVerification.
    Called inside transaction.atomic() before saving.
    """
    from ngo.models import NGOProfile

    # --- NGOProfile side effects ---
    if new_status == NGOProfile.Status.APPROVED:
        ngo_profile.is_active = True
        ngo_profile.verified_at = now
    else:
        ngo_profile.is_active = False

    # --- NGOVerification timestamp side effects ---
    if new_status == 'SUBMITTED':
        if verification.submitted_at is None:
            # First-ever submission
            verification.submitted_at = now
        verification.last_submitted_at = now
        # Reset bank correction flag on resubmission
        verification.bank_correction_requested = False

    elif new_status == 'UNDER_REVIEW':
        verification.review_started_at = now

    elif new_status in ('APPROVED', 'REJECTED', 'CORRECTION_REQUIRED'):
        verification.decision_at = now

    # --- Resubmission count increment ---
    # Only increment when going CORRECTION_REQUIRED → SUBMITTED
    if (verification.status == 'CORRECTION_REQUIRED' and new_status == 'SUBMITTED'):
        verification.resubmission_count += 1

    # --- Admin reopen reset ---
    # If admin_reopened was True and NGO is now resubmitting, clear the flag
    if new_status == 'SUBMITTED' and verification.admin_reopened:
        verification.admin_reopened = False


@transaction.atomic
def change_ngo_verification_status(
    ngo_profile,
    new_status,
    changed_by,
    reason='',
    metadata=None,
    correction_instructions='',
    rejection_reason='',
    admin_notes='',
    bank_correction_requested=False,
    verify_csr=False,
    csr_review_notes='',
):
    
    from ngo.models import NGOVerificationHistory

    if metadata is None:
        metadata = {}

    # -----------------------------------------------------------------------
    # Step 1: Get current verification record
    # -----------------------------------------------------------------------
    try:
        verification = ngo_profile.verification
    except Exception:
        raise ValidationError(
            _('NGOVerification record does not exist for this NGO profile.')
        )

    current_status = ngo_profile.status

    # -----------------------------------------------------------------------
    # Step 2: Validate the transition is allowed
    # -----------------------------------------------------------------------
    transition_key = (current_status, new_status)
    if transition_key not in ALLOWED_TRANSITIONS:
        raise StatusTransitionError(
            f'Transition from {current_status!r} to {new_status!r} is not permitted. '
            f'Allowed from {current_status!r}: '
            f'{[t for (f, t) in ALLOWED_TRANSITIONS if f == current_status]}'
        )

    # -----------------------------------------------------------------------
    # Step 3: Determine actor type and validate permission
    # -----------------------------------------------------------------------
    from ngo.models import NGOVerificationHistory

    allowed_actor_types = ALLOWED_TRANSITIONS[transition_key]

    if changed_by is None:
        actor_type = NGOVerificationHistory.ActorType.SYSTEM
    elif hasattr(changed_by, 'role') and changed_by.role == 'ADMIN':
        actor_type = NGOVerificationHistory.ActorType.ADMIN
        if 'ADMIN' not in allowed_actor_types:
            raise PermissionDenied(
                f'Admin is not authorized to perform the {current_status!r} → {new_status!r} transition.'
            )
    else:
        actor_type = NGOVerificationHistory.ActorType.NGO
        if 'NGO' not in allowed_actor_types:
            raise PermissionDenied(
                f'NGO user is not authorized to perform the {current_status!r} → {new_status!r} transition.'
            )
        # Verify the NGO user owns this profile
        if changed_by != ngo_profile.user:
            raise PermissionDenied(
                'NGO user is not the owner of this NGO profile.'
            )

    # -----------------------------------------------------------------------
    # Step 4: Resubmission limit check (NGO resubmission only)
    # -----------------------------------------------------------------------
    if actor_type == NGOVerificationHistory.ActorType.NGO and new_status == 'SUBMITTED':
        if not verification.can_resubmit:
            raise ResubmissionLimitError(
                f'Maximum resubmission cycles ({verification.resubmission_limit}) reached. '
                f'Contact admin to reopen the application.'
            )

    # -----------------------------------------------------------------------
    # Step 5: Validate required fields for specific transitions
    # -----------------------------------------------------------------------
    if new_status == 'CORRECTION_REQUIRED' and not correction_instructions:
        raise ValidationError(
            {'correction_instructions': _('Correction instructions are required when requesting corrections.')}
        )
    if new_status == 'REJECTED' and not rejection_reason:
        raise ValidationError(
            {'rejection_reason': _('Rejection reason is required when rejecting an application.')}
        )

    # CSR verification validation upon approval
    if new_status == 'APPROVED':
        if verify_csr:
            legal = getattr(ngo_profile, 'legal_info', None)
            if not legal or not legal.is_csr_eligible:
                raise ValidationError(
                    {'verify_csr': _('NGO does not meet statutory CSR eligibility requirements (CSR-1, 3-year track record, and 12A+80G or 10(23C)).')}
                )

    # -----------------------------------------------------------------------
    # Step 6: Capture previous status for history record
    # -----------------------------------------------------------------------
    previous_status = current_status
    now = timezone.now()

    # -----------------------------------------------------------------------
    # Step 7: Apply side effects to model instances (not yet saved)
    # -----------------------------------------------------------------------
    _apply_side_effects(ngo_profile, verification, new_status, changed_by, now)

    # -----------------------------------------------------------------------
    # Step 8: Update NGOProfile — within atomic transaction
    # -----------------------------------------------------------------------
    # Use update() on specific fields to avoid race conditions
    from ngo.models import NGOProfile as NGOProfileModel
    NGOProfileModel.objects.filter(pk=ngo_profile.pk).update(
        status=new_status,
        is_active=ngo_profile.is_active,
        verified_at=ngo_profile.verified_at,
        updated_at=now,
    )
    # Refresh in-memory instance
    ngo_profile.status = new_status

    # -----------------------------------------------------------------------
    # Step 9: Update NGOVerification fields — within atomic transaction
    # -----------------------------------------------------------------------
    if new_status == 'CORRECTION_REQUIRED':
        verification.correction_instructions = correction_instructions
        verification.bank_correction_requested = bank_correction_requested
    if new_status == 'REJECTED':
        verification.rejection_reason = rejection_reason
        verification.is_csr_verified = False
    if new_status == 'SUSPENDED':
        verification.is_csr_verified = False
    if new_status == 'APPROVED':
        if verify_csr:
            verification.is_csr_verified = True
            verification.csr_verified_at = now
            verification.csr_verified_by = changed_by
            verification.csr_review_notes = csr_review_notes
        else:
            verification.is_csr_verified = False
            verification.csr_review_notes = csr_review_notes

    if admin_notes:
        verification.admin_notes = admin_notes

    verification.status = new_status

    # Save all verification fields explicitly
    verification.save(update_fields=[
        'status',
        'admin_notes',
        'risk_flags',
        'correction_instructions',
        'rejection_reason',
        'bank_correction_requested',
        'resubmission_count',
        'resubmission_limit',
        'admin_reopened',
        'submitted_at',
        'last_submitted_at',
        'review_started_at',
        'decision_at',
        'is_csr_verified',
        'csr_verified_at',
        'csr_verified_by',
        'csr_review_notes',
        'updated_at',
    ])

    # -----------------------------------------------------------------------
    # Step 10: Create exactly ONE immutable history record — INSERT only
    # -----------------------------------------------------------------------
    history_record = NGOVerificationHistory.objects.create(
        ngo=ngo_profile,
        performed_by=changed_by,
        actor_type=actor_type,
        previous_status=previous_status,
        new_status=new_status,
        reason=reason or correction_instructions or rejection_reason,
        metadata=metadata,
    )

    # -----------------------------------------------------------------------
    # Step 11: Schedule post-commit email notification
    # -----------------------------------------------------------------------
    # Email is sent AFTER the transaction commits.
    # This ensures a failed email does NOT roll back the status change.
    transaction.on_commit(
        lambda: _send_status_notification(ngo_profile, new_status, reason)
    )

    return history_record


def _send_status_notification(ngo_profile, new_status, reason=''):
    from django.core.mail import send_mail
    from django.conf import settings

    EMAIL_SUBJECTS = {
        'SUBMITTED':           'DaanGives: Your application has been received',
        'UNDER_REVIEW':        'DaanGives: Your application is under review',
        'CORRECTION_REQUIRED': 'DaanGives: Corrections required for your application',
        'APPROVED':            'DaanGives: Congratulations! Your NGO application is approved',
        'REJECTED':            'DaanGives: Your NGO application has been rejected',
        'SUSPENDED':           'DaanGives: Your NGO account has been suspended',
    }

    subject = EMAIL_SUBJECTS.get(new_status)
    if not subject:
        return  # No notification for this status

    recipient_email = ngo_profile.user.email
    message = (
        f'Dear {ngo_profile.display_name},\n\n'
        f'Your DaanGives NGO application status has changed to: {new_status}\n'
    )
    if reason:
        message += f'\nDetails: {reason}\n'
    message += '\nPlease log in to your DaanGives dashboard for full details.\n\nThe DaanGives Team'

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@daangives.org'),
            recipient_list=[recipient_email],
            fail_silently=True,  # Never propagate email failure to user
        )
    except Exception:
        # Log but do not raise — email failure must never affect status change
        pass


def reopen_ngo_application(ngo_profile, admin_user, additional_cycles=3):
    """
    Admin action: reopens an NGO application (REJECTED or CORRECTION_REQUIRED).
    Resets status to DRAFT, sets admin_reopened=True, resets resubmission_count=0,
    raises resubmission_limit by additional_cycles.
    Creates a history record for the admin reopen action.
    """
    from ngo.models import NGOVerificationHistory, NGOProfile

    if not (hasattr(admin_user, 'role') and admin_user.role == 'ADMIN'):
        raise PermissionDenied('Only admin users can reopen NGO applications.')

    try:
        verification = ngo_profile.verification
    except Exception:
        raise ValidationError('NGOVerification record does not exist.')

    previous_status = ngo_profile.status
    allowed_reopen_statuses = ('REJECTED', 'CORRECTION_REQUIRED', 'DRAFT', 'SUBMITTED')
    if previous_status not in allowed_reopen_statuses:
        raise StatusTransitionError(
            f'Reopen is not allowed from status {previous_status!r}. Allowed from: {allowed_reopen_statuses}'
        )

    now = timezone.now()
    with transaction.atomic():
        verification.admin_reopened = True
        verification.resubmission_count = 0
        verification.resubmission_limit = additional_cycles
        verification.status = NGOProfile.Status.DRAFT
        verification.updated_at = now
        verification.save(update_fields=[
            'status', 'admin_reopened', 'resubmission_count', 'resubmission_limit', 'updated_at'
        ])

        NGOProfile.objects.filter(pk=ngo_profile.pk).update(
            status=NGOProfile.Status.DRAFT,
            is_active=False,
            updated_at=now,
        )
        ngo_profile.status = NGOProfile.Status.DRAFT
        ngo_profile.is_active = False

        history_record = NGOVerificationHistory.objects.create(
            ngo=ngo_profile,
            performed_by=admin_user,
            actor_type=NGOVerificationHistory.ActorType.ADMIN,
            previous_status=previous_status,
            new_status=NGOProfile.Status.DRAFT,
            reason='Admin reopened application for resubmission.',
            metadata={
                'admin_reopen': True,
                'additional_cycles': additional_cycles,
                'new_limit': additional_cycles,
            },
        )

    return history_record


def record_ngo_manual_verification(
    admin_user,
    ngo_profile,
    outcome: str,
    source: str = 'MANUAL_ADMIN_CHECK',
    notes: str = '',
):
    """
    Allows authorized Admin to record manual verification results for an NGO's
    government identifiers (PAN, Darpan, 12A/80G, CSR-1) when live APIs are unavailable.
    
    IMPORTANT: This records verification audit evidence only.
    Passing a government/manual check NEVER automatically approves the NGO profile!
    """
    from ngo.models import NGOVerificationHistory, GovCheckStatus

    if not (hasattr(admin_user, 'role') and admin_user.role == 'ADMIN'):
        raise PermissionDenied('Only admin users can record manual verification evidence.')

    valid_outcomes = {
        GovCheckStatus.GOVERNMENT_CHECK_PASSED,
        GovCheckStatus.GOVERNMENT_CHECK_FAILED,
        GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
        GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE,
        GovCheckStatus.GOVERNMENT_CHECK_PENDING,
    }
    if outcome not in valid_outcomes:
        raise ValidationError({'outcome': f'Invalid verification outcome {outcome}. Valid choices: {valid_outcomes}'})

    try:
        verification = ngo_profile.verification
    except Exception:
        raise ValidationError('NGOVerification record does not exist.')

    now = timezone.now()
    with transaction.atomic():
        verification.gov_check_status = outcome
        verification.gov_check_source = source
        verification.gov_check_details = {
            'outcome': outcome,
            'source': source,
            'notes': notes,
            'recorded_by': admin_user.email,
            'timestamp': now.isoformat(),
        }
        verification.gov_check_completed_at = now
        verification.updated_at = now
        verification.save(update_fields=[
            'gov_check_status',
            'gov_check_source',
            'gov_check_details',
            'gov_check_completed_at',
            'updated_at',
        ])

        # Record audit history
        history_record = NGOVerificationHistory.objects.create(
            ngo=ngo_profile,
            performed_by=admin_user,
            actor_type=NGOVerificationHistory.ActorType.ADMIN,
            previous_status=ngo_profile.status,
            new_status=ngo_profile.status,
            reason=f'Admin recorded manual verification check: {outcome} via {source}. Notes: {notes}',
            metadata={
                'action': 'RECORD_MANUAL_GOV_CHECK',
                'outcome': outcome,
                'source': source,
                'notes': notes,
            },
        )

    return history_record


