"""
Domain Services for CampaignMilestone.

Phase 5.2.2 - Pure domain logic for milestone operations.
Encapsulates:
- Canonical NGO ownership & approval verification
- Milestone CRUD lifecycle
- Milestone state machine transitions
- Terminal state locking (VERIFIED milestones are sealed)
- Race condition mitigation with database-level row-locking (select_for_update)
- Transaction atomicity
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from campaigns.models import Campaign, CampaignMilestone
from campaigns.services.exceptions import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignOwnershipError,
    CampaignPermissionError,
    CampaignServiceError,
    CampaignStateError,
    CampaignValidationError,
)
from ngo.models import NGOProfile


# Canonical milestone state machine transitions
VALID_MILESTONE_TRANSITIONS = {
    CampaignMilestone.MilestoneStatus.PENDING: {
        CampaignMilestone.MilestoneStatus.IN_PROGRESS,
    },
    CampaignMilestone.MilestoneStatus.IN_PROGRESS: {
        CampaignMilestone.MilestoneStatus.VERIFIED,
        CampaignMilestone.MilestoneStatus.REVISION_REQUESTED,
    },
    CampaignMilestone.MilestoneStatus.REVISION_REQUESTED: {
        CampaignMilestone.MilestoneStatus.IN_PROGRESS,
        CampaignMilestone.MilestoneStatus.VERIFIED,
    },
    CampaignMilestone.MilestoneStatus.VERIFIED: set(),  # Terminal state: strictly sealed
}


def validate_ngo_campaign_access(user, campaign: Campaign) -> NGOProfile:
    """
    Validates that:
    1. User is active and authenticated.
    2. User possesses the 'NGO' role (or staff/admin).
    3. User has an attached NGOProfile.
    4. NGO is active and in 'APPROVED' verification status.
    5. NGO owns the target Campaign appeal (preventing IDOR).

    Returns the verified NGOProfile instance.
    """
    if not user or not user.is_authenticated or not user.is_active:
        raise CampaignPermissionError(
            "Authentication required and user account must be active.",
            code="inactive_or_unauthenticated",
        )

    # Superusers / Platform Admin staff bypass ownership check for moderation purposes
    if getattr(user, 'is_staff', False) or getattr(user, 'role', None) == 'ADMIN':
        return getattr(campaign, 'ngo', None)

    if getattr(user, 'role', None) != 'NGO':
        raise CampaignPermissionError(
            "Only verified NGO accounts can manage campaign milestones.",
            code="ngo_role_required",
        )

    ngo_profile = getattr(user, 'ngo_profile', None)
    if not ngo_profile:
        raise CampaignPermissionError(
            "NGO profile not found for authenticated user.",
            code="missing_ngo_profile",
        )

    if not ngo_profile.is_active:
        raise CampaignPermissionError(
            "NGO account is currently inactive.",
            code="ngo_inactive",
        )

    if ngo_profile.status != 'APPROVED':
        raise CampaignPermissionError(
            f"NGO is not approved to manage milestones (current status: '{ngo_profile.status}').",
            code="ngo_not_approved",
        )

    # Strict multi-tenant IDOR protection
    if campaign.ngo_id != ngo_profile.id:
        raise CampaignOwnershipError(
            "Access denied: You do not own this campaign appeal.",
            code="ownership_denied",
        )

    return ngo_profile


def get_milestone(*args, **kwargs) -> CampaignMilestone:
    """
    Retrieves a CampaignMilestone with role-aware and tenant-aware scoping.
    Supports:
      get_milestone(milestone_id, user=None, for_update=False)
      get_milestone(user, milestone_id)
      get_milestone(milestone=m, user=u)
    """
    user = kwargs.pop('user', None)
    milestone_id = kwargs.pop('milestone_id', None)
    for_update = kwargs.pop('for_update', False)

    if 'milestone' in kwargs:
        m = kwargs.pop('milestone')
        milestone_id = m.id if hasattr(m, 'id') else m

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                milestone_id = args[1]
        else:
            milestone_id = first
            if len(args) > 1:
                user = args[1]
            if len(args) > 2:
                for_update = args[2]

    if hasattr(milestone_id, 'id'):
        milestone_id = milestone_id.id

    qs = CampaignMilestone.objects.select_related('campaign', 'campaign__ngo')
    if for_update:
        qs = qs.select_for_update()

    try:
        milestone = qs.get(id=milestone_id)
    except (CampaignMilestone.DoesNotExist, ValueError):
        raise CampaignNotFoundError("Campaign milestone not found.", code="milestone_not_found")

    # If caller is admin, allow access
    if user and (getattr(user, 'role', None) == 'ADMIN' or getattr(user, 'is_staff', False)):
        return milestone

    # If caller is NGO, verify tenant ownership
    if user and getattr(user, 'role', None) == 'NGO':
        if not hasattr(user, 'ngo_profile') or milestone.campaign.ngo_id != user.ngo_profile.id:
            raise CampaignOwnershipError("Access denied: You do not own this milestone's campaign.", code="ownership_denied")
        return milestone

    # Donor or public access: only allowed if campaign is publicly published/active/completed
    if milestone.campaign.status in [Campaign.Status.ACTIVE, Campaign.Status.COMPLETED]:
        return milestone

    raise CampaignNotFoundError("Campaign milestone not found or access denied.", code="milestone_not_found")


def list_milestones_for_campaign(*args, **kwargs):
    """
    Lists all milestones for a campaign with tenant isolation.
    Supports:
      list_milestones_for_campaign(campaign, user=None)
      list_milestones_for_campaign(user, campaign_id)
    """
    campaign = kwargs.pop('campaign', None)
    campaign_id = kwargs.pop('campaign_id', None)
    user = kwargs.pop('user', None)

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                campaign = args[1]
        else:
            campaign = first
            if len(args) > 1:
                user = args[1]

    if campaign is not None:
        campaign_id = campaign.id if hasattr(campaign, 'id') else campaign

    try:
        camp_obj = Campaign.objects.select_related('ngo').get(id=campaign_id)
    except (Campaign.DoesNotExist, ValueError):
        raise CampaignNotFoundError("Campaign not found.", code="campaign_not_found")

    # Access check for draft/inactive campaigns
    if camp_obj.status in [Campaign.Status.DRAFT, Campaign.Status.PENDING_REVIEW, Campaign.Status.CHANGES_REQUESTED]:
        validate_ngo_campaign_access(user, camp_obj)

    return CampaignMilestone.objects.filter(campaign=camp_obj).order_by('sequence_number', 'created_at')


def create_milestone(*args, **kwargs) -> CampaignMilestone:
    """
    Creates a new CampaignMilestone for an authorized NGO campaign.
    Supports:
      create_milestone(user, campaign_id, data)
      create_milestone(campaign=c, user=u, sequence_number=1, title=..., ...)
    """
    user = kwargs.pop('user', None)
    campaign = kwargs.pop('campaign', None)
    campaign_id = kwargs.pop('campaign_id', None)
    data = kwargs.pop('data', None)

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                campaign = args[1]
            if len(args) > 2:
                data = args[2]
        else:
            campaign = first
            if len(args) > 1:
                user = args[1]
            if len(args) > 2:
                data = args[2]

    if campaign is not None:
        campaign_id = campaign.id if hasattr(campaign, 'id') else campaign

    if data is None:
        data = kwargs
    else:
        data = {**data, **kwargs}

    try:
        camp_obj = Campaign.objects.select_related('ngo').get(id=campaign_id)
    except (Campaign.DoesNotExist, ValueError):
        raise CampaignNotFoundError("Campaign not found.", code="campaign_not_found")

    validate_ngo_campaign_access(user, camp_obj)

    if camp_obj.status in [Campaign.Status.REJECTED, Campaign.Status.CANCELLED, Campaign.Status.SUSPENDED]:
        raise CampaignStateError(
            f"Cannot create milestones for campaign in status '{camp_obj.status}'.",
            code="campaign_terminal_status",
        )

    # Sanitize data against mass assignment
    protected_keys = {'id', 'campaign', 'status', 'actual_completion_date', 'created_at', 'updated_at'}
    clean_data = {k: v for k, v in data.items() if k not in protected_keys}

    # Required fields check
    for req in ['title', 'description', 'target_completion_date']:
        if not clean_data.get(req):
            raise CampaignValidationError(f"Field '{req}' is required.", code="missing_field")

    # Sequence number handling
    seq_num = clean_data.get('sequence_number')
    if seq_num is None:
        last_seq = CampaignMilestone.objects.filter(campaign=camp_obj).order_by('-sequence_number').values_list('sequence_number', flat=True).first() or 0
        seq_num = last_seq + 1
        clean_data['sequence_number'] = seq_num
    else:
        try:
            seq_num = int(seq_num)
        except (ValueError, TypeError):
            raise CampaignValidationError("sequence_number must be a valid integer.", code="invalid_sequence")
        if seq_num < 1:
            raise CampaignValidationError("sequence_number must be at least 1.", code="invalid_sequence")

    # Target amount validation
    target_amount = clean_data.get('target_amount', Decimal('0.00'))
    try:
        target_amount = Decimal(str(target_amount))
    except Exception:
        raise CampaignValidationError("target_amount must be a valid numeric Decimal.", code="invalid_target_amount")
    if target_amount < Decimal('0.00'):
        raise CampaignValidationError("target_amount cannot be negative.", code="negative_target_amount")
    clean_data['target_amount'] = target_amount

    with transaction.atomic():
        if CampaignMilestone.objects.filter(campaign=camp_obj, sequence_number=seq_num).exists():
            raise CampaignConflictError(
                f"Milestone #{seq_num} already exists for this campaign.",
                code="duplicate_sequence_number",
            )

        milestone = CampaignMilestone(
            campaign=camp_obj,
            status=CampaignMilestone.MilestoneStatus.PENDING,
            **clean_data,
        )
        milestone.full_clean()
        milestone.save()

    return milestone


def update_milestone(*args, **kwargs) -> CampaignMilestone:
    """
    Updates an existing CampaignMilestone. Verified milestones are locked against modification.
    Supports:
      update_milestone(user, milestone_id, data)
      update_milestone(milestone=m, user=u, title=..., ...)
    """
    user = kwargs.pop('user', None)
    milestone = kwargs.pop('milestone', None)
    milestone_id = kwargs.pop('milestone_id', None)
    data = kwargs.pop('data', None)

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                milestone = args[1]
            if len(args) > 2:
                data = args[2]
        else:
            milestone = first
            if len(args) > 1:
                user = args[1]
            if len(args) > 2:
                data = args[2]

    if milestone is not None:
        milestone_id = milestone.id if hasattr(milestone, 'id') else milestone

    if data is None:
        data = kwargs
    else:
        data = {**data, **kwargs}

    with transaction.atomic():
        try:
            m_obj = CampaignMilestone.objects.select_for_update().select_related('campaign', 'campaign__ngo').get(id=milestone_id)
        except (CampaignMilestone.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Milestone not found.", code="milestone_not_found")

        validate_ngo_campaign_access(user, m_obj.campaign)

        if m_obj.status == CampaignMilestone.MilestoneStatus.VERIFIED:
            raise CampaignStateError("Verified milestones are sealed and cannot be modified.", code="milestone_sealed")

        protected_keys = {'id', 'campaign', 'status', 'actual_completion_date', 'created_at', 'updated_at'}
        clean_data = {k: v for k, v in data.items() if k not in protected_keys}

        if 'sequence_number' in clean_data:
            new_seq = int(clean_data['sequence_number'])
            if new_seq < 1:
                raise CampaignValidationError("sequence_number must be at least 1.", code="invalid_sequence")
            if new_seq != m_obj.sequence_number:
                if CampaignMilestone.objects.filter(campaign=m_obj.campaign, sequence_number=new_seq).exclude(id=m_obj.id).exists():
                    raise CampaignConflictError(
                        f"Milestone #{new_seq} already exists for this campaign.",
                        code="duplicate_sequence_number",
                    )
                m_obj.sequence_number = new_seq

        if 'title' in clean_data:
            if not clean_data['title'].strip():
                raise CampaignValidationError("Title cannot be blank.", code="blank_title")
            m_obj.title = clean_data['title']

        if 'description' in clean_data:
            if not clean_data['description'].strip():
                raise CampaignValidationError("Description cannot be blank.", code="blank_description")
            m_obj.description = clean_data['description']

        if 'target_amount' in clean_data:
            try:
                amt = Decimal(str(clean_data['target_amount']))
            except Exception:
                raise CampaignValidationError("Invalid target_amount format.", code="invalid_amount")
            if amt < Decimal('0.00'):
                raise CampaignValidationError("target_amount cannot be negative.", code="negative_amount")
            m_obj.target_amount = amt

        if 'target_completion_date' in clean_data:
            m_obj.target_completion_date = clean_data['target_completion_date']

        m_obj.full_clean()
        m_obj.save()

    return m_obj


def transition_milestone_status(*args, **kwargs) -> CampaignMilestone:
    """
    Executes a validated status transition on a milestone with row-locking.
    Supports:
      transition_milestone_status(user, milestone_id, new_status, actual_completion_date=None)
      transition_milestone_status(milestone=m, new_status=s, actor=u, reason=...)
    """
    user = kwargs.pop('user', None) or kwargs.pop('actor', None)
    milestone = kwargs.pop('milestone', None)
    milestone_id = kwargs.pop('milestone_id', None)
    new_status = kwargs.pop('new_status', None)
    actual_completion_date = kwargs.pop('actual_completion_date', None)
    reason = kwargs.pop('reason', None)

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                milestone = args[1]
            if len(args) > 2:
                new_status = args[2]
            if len(args) > 3:
                actual_completion_date = args[3]
        else:
            milestone = first
            if len(args) > 1:
                new_status = args[1]
            if len(args) > 2:
                user = args[2]
            if len(args) > 3:
                reason = args[3]

    if milestone is not None:
        milestone_id = milestone.id if hasattr(milestone, 'id') else milestone

    with transaction.atomic():
        try:
            m_obj = CampaignMilestone.objects.select_for_update().select_related('campaign', 'campaign__ngo').get(id=milestone_id)
        except (CampaignMilestone.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Milestone not found.", code="milestone_not_found")

        current_status = m_obj.status

        if new_status == current_status:
            return m_obj

        allowed_targets = VALID_MILESTONE_TRANSITIONS.get(current_status, set())
        if new_status not in allowed_targets:
            raise CampaignStateError(
                f"Cannot transition milestone from '{current_status}' to '{new_status}'. Allowed: {sorted(list(allowed_targets)) or 'None'}.",
                code="invalid_state_transition",
            )

        # Verification requires ADMIN role or staff
        if new_status == CampaignMilestone.MilestoneStatus.VERIFIED:
            if not user or (getattr(user, 'role', None) != 'ADMIN' and not getattr(user, 'is_staff', False)):
                raise CampaignPermissionError("Only Platform Administrators can verify milestones.", code="admin_required")
            m_obj.actual_completion_date = actual_completion_date or timezone.now().date()

        m_obj.status = new_status
        m_obj.full_clean()
        m_obj.save()

    return m_obj
