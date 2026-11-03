"""
Domain Services for DistributionProof.

Phase 5.2.2 - Pure domain logic for field proof validation & moderation.
Encapsulates:
- Proof creation & attachment to active milestones
- Strict file validation (Pillow verification, 5MB ceiling, JPG/JPEG/PNG/WebP)
- Strict GPS coordinate ranges (-90..90 lat, -180..180 lng, nullable allowed)
- Beneficiary validation against canonical BeneficiaryDemographic choices
- Financial validation (spent_amount >= 0, isolated JSON expense_breakdown)
- Mass-assignment blocking (submitted_by, status, reviewed_by, admin_notes)
- Proof moderation state transitions:
    SUBMITTED -> UNDER_REVIEW -> VERIFIED
    UNDER_REVIEW -> REVISION_REQUESTED -> SUBMITTED (upon NGO resubmission)
    UNDER_REVIEW -> REJECTED (terminal)
- Database concurrency safety with row-level locking (select_for_update)
- Transaction atomicity
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from users.image_validators import validate_image_file
from campaigns.models import BeneficiaryDemographic, Campaign, CampaignMilestone, DistributionProof
from campaigns.services.exceptions import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignOwnershipError,
    CampaignPermissionError,
    CampaignServiceError,
    CampaignStateError,
    CampaignValidationError,
)
from campaigns.services.milestone_service import validate_ngo_campaign_access


# Canonical distribution proof lifecycle transitions
VALID_PROOF_TRANSITIONS = {
    DistributionProof.Status.SUBMITTED: {
        DistributionProof.Status.UNDER_REVIEW,
    },
    DistributionProof.Status.UNDER_REVIEW: {
        DistributionProof.Status.VERIFIED,
        DistributionProof.Status.REVISION_REQUESTED,
        DistributionProof.Status.REJECTED,
    },
    DistributionProof.Status.REVISION_REQUESTED: {
        DistributionProof.Status.SUBMITTED,  # Resubmission by NGO
    },
    DistributionProof.Status.VERIFIED: set(),  # Terminal state
    DistributionProof.Status.REJECTED: set(),  # Terminal state
}


def get_distribution_proof(*args, **kwargs) -> DistributionProof:
    """
    Retrieves a DistributionProof with role-aware and visibility-aware scoping.
    Supports:
      get_distribution_proof(proof_id, user=None)
      get_distribution_proof(proof=p, user=u)
    """
    proof_id = kwargs.pop('proof_id', None)
    proof = kwargs.pop('proof', None)
    user = kwargs.pop('user', None)

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                proof_id = args[1]
        else:
            proof_id = first
            if len(args) > 1:
                user = args[1]

    if hasattr(proof_id, 'id'):
        proof_id = proof_id.id

    try:
        proof_obj = DistributionProof.objects.select_related(
            'milestone', 'milestone__campaign', 'milestone__campaign__ngo', 'submitted_by', 'reviewed_by'
        ).get(id=proof_id)
    except (DistributionProof.DoesNotExist, ValueError):
        raise CampaignNotFoundError("Distribution proof not found.", code="proof_not_found")

    # Admin has global read access
    if user and (getattr(user, 'role', None) == 'ADMIN' or getattr(user, 'is_staff', False)):
        return proof_obj

    # NGO can only read proofs for campaigns it owns
    if user and getattr(user, 'role', None) == 'NGO':
        if not hasattr(user, 'ngo_profile') or proof_obj.milestone.campaign.ngo_id != user.ngo_profile.id:
            raise CampaignOwnershipError("Access denied: You do not own this distribution proof.", code="ownership_denied")
        return proof_obj

    # Donor / Public access: only VERIFIED proofs are visible
    if proof_obj.status == DistributionProof.Status.VERIFIED:
        return proof_obj

    raise CampaignNotFoundError("Distribution proof not found or access denied.", code="proof_not_found")


def create_distribution_proof(*args, **kwargs) -> DistributionProof:
    """
    Creates and attaches a new DistributionProof to an active campaign milestone.
    Supports:
      create_distribution_proof(user, milestone_id, data, photo_file)
      create_distribution_proof(milestone=m, user=u, photo=p, caption=..., ...)
    """
    user = kwargs.pop('user', None)
    milestone = kwargs.pop('milestone', None)
    milestone_id = kwargs.pop('milestone_id', None)
    photo_file = kwargs.pop('photo_file', None) or kwargs.pop('photo', None)
    data = kwargs.pop('data', None)

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            user = first
            if len(args) > 1:
                milestone = args[1]
            if len(args) > 2:
                data = args[2]
            if len(args) > 3:
                photo_file = args[3]
        else:
            milestone = first
            if len(args) > 1:
                user = args[1]
            if len(args) > 2:
                data = args[2]
            if len(args) > 3:
                photo_file = args[3]

    if milestone is not None:
        milestone_id = milestone.id if hasattr(milestone, 'id') else milestone

    if data is None:
        data = kwargs
    else:
        data = {**data, **kwargs}

    try:
        m_obj = CampaignMilestone.objects.select_related('campaign', 'campaign__ngo').get(id=milestone_id)
    except (CampaignMilestone.DoesNotExist, ValueError):
        raise CampaignNotFoundError("Milestone not found.", code="milestone_not_found")

    campaign = m_obj.campaign
    validate_ngo_campaign_access(user, campaign)

    # Lifecycle guard conditions
    if campaign.status not in [Campaign.Status.ACTIVE, Campaign.Status.COMPLETED]:
        raise CampaignStateError(
            f"Cannot submit distribution proof for campaign in status '{campaign.status}'. Campaign must be ACTIVE or COMPLETED.",
            code="invalid_campaign_status",
        )

    if campaign.raised_amount <= Decimal('0.00'):
        raise CampaignStateError(
            "Cannot submit distribution proof for a campaign with zero raised donations.",
            code="no_raised_funds",
        )

    if m_obj.status == CampaignMilestone.MilestoneStatus.VERIFIED:
        raise CampaignStateError(
            "Cannot submit new proof for an already VERIFIED milestone.",
            code="milestone_already_verified",
        )

    if m_obj.status == CampaignMilestone.MilestoneStatus.PENDING:
        raise CampaignStateError(
            "Cannot submit distribution proof for a PENDING milestone. Milestone must be IN_PROGRESS or REVISION_REQUESTED.",
            code="milestone_pending",
        )

    if not photo_file:
        raise CampaignValidationError("A geotagged distribution photo is required.", code="missing_photo")

    # Image validation (formats, pillow verification, 5MB ceiling)
    try:
        validate_image_file(photo_file)
    except DjangoValidationError as exc:
        raise CampaignValidationError(str(exc), code="invalid_photo")

    # Sanitize input against mass assignment
    protected_keys = {
        'id', 'milestone', 'status', 'submitted_by', 'submitted_at',
        'reviewed_by', 'reviewed_at', 'admin_notes', 'rejection_reason',
        'created_at', 'updated_at',
    }
    clean_data = {k: v for k, v in data.items() if k not in protected_keys}

    if not clean_data.get('caption', '').strip():
        raise CampaignValidationError("Field caption is required.", code="missing_caption")

    dist_date = clean_data.get('distribution_date')
    if not dist_date:
        clean_data['distribution_date'] = timezone.now().date()

    # GPS Validation
    lat = clean_data.get('latitude')
    if lat is not None and lat != '':
        try:
            lat = Decimal(str(lat))
            if lat < Decimal('-90.000000') or lat > Decimal('90.000000'):
                raise CampaignValidationError("Latitude must be between -90 and 90 degrees.", code="invalid_latitude")
            clean_data['latitude'] = lat
        except (ValueError, TypeError, CampaignValidationError) as e:
            if isinstance(e, CampaignValidationError):
                raise
            raise CampaignValidationError("Latitude must be a valid numeric Decimal.", code="invalid_latitude")
    else:
        clean_data['latitude'] = None

    lng = clean_data.get('longitude')
    if lng is not None and lng != '':
        try:
            lng = Decimal(str(lng))
            if lng < Decimal('-180.000000') or lng > Decimal('180.000000'):
                raise CampaignValidationError("Longitude must be between -180 and 180 degrees.", code="invalid_longitude")
            clean_data['longitude'] = lng
        except (ValueError, TypeError, CampaignValidationError) as e:
            if isinstance(e, CampaignValidationError):
                raise
            raise CampaignValidationError("Longitude must be a valid numeric Decimal.", code="invalid_longitude")
    else:
        clean_data['longitude'] = None

    # Beneficiary validation
    b_count = clean_data.get('beneficiary_count', 0)
    try:
        b_count = int(b_count)
        if b_count < 0:
            raise CampaignValidationError("beneficiary_count cannot be negative.", code="invalid_beneficiary_count")
        clean_data['beneficiary_count'] = b_count
    except (ValueError, TypeError):
        raise CampaignValidationError("beneficiary_count must be an integer.", code="invalid_beneficiary_count")

    b_type = clean_data.get('beneficiary_type', '')
    if b_type and b_type not in BeneficiaryDemographic.values:
        raise CampaignValidationError(
            f"Invalid beneficiary_type '{b_type}'. Allowed: {list(BeneficiaryDemographic.values)}.",
            code="invalid_beneficiary_type",
        )
    clean_data['beneficiary_type'] = b_type

    # Spent amount validation
    spent = clean_data.get('spent_amount', Decimal('0.00'))
    try:
        spent = Decimal(str(spent))
        if spent < Decimal('0.00'):
            raise CampaignValidationError("spent_amount cannot be negative.", code="invalid_spent_amount")
        clean_data['spent_amount'] = spent
    except Exception:
        raise CampaignValidationError("spent_amount must be a valid numeric Decimal.", code="invalid_spent_amount")

    # Expense breakdown validation
    expenses = clean_data.get('expense_breakdown', {})
    if not isinstance(expenses, dict):
        raise CampaignValidationError("expense_breakdown must be a valid JSON dictionary.", code="invalid_expense_breakdown")
    clean_data['expense_breakdown'] = expenses

    with transaction.atomic():
        proof = DistributionProof(
            milestone=m_obj,
            photo=photo_file,
            status=DistributionProof.Status.SUBMITTED,
            submitted_by=user,
            submitted_at=timezone.now(),
            **clean_data,
        )
        proof.full_clean()
        proof.save()

    return proof


def start_proof_review(*args, **kwargs) -> DistributionProof:
    """
    Transitions proof from SUBMITTED to UNDER_REVIEW by an authorized Platform Administrator.
    Supports:
      start_proof_review(admin_user, proof_id, admin_notes=None)
      start_proof_review(proof=p, admin_user=u, admin_notes=...)
    """
    admin_user = kwargs.pop('admin_user', None)
    proof = kwargs.pop('proof', None)
    proof_id = kwargs.pop('proof_id', None)
    admin_notes = kwargs.pop('admin_notes', None)

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            admin_user = first
            if len(args) > 1:
                proof = args[1]
            if len(args) > 2:
                admin_notes = args[2]
        else:
            proof = first
            if len(args) > 1:
                admin_user = args[1]
            if len(args) > 2:
                admin_notes = args[2]

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if not admin_user or (getattr(admin_user, 'role', None) != 'ADMIN' and not getattr(admin_user, 'is_staff', False)):
        raise CampaignPermissionError("Only Platform Administrators can review distribution proofs.", code="admin_required")

    with transaction.atomic():
        try:
            proof_obj = DistributionProof.objects.select_for_update().get(id=proof_id)
        except (DistributionProof.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Distribution proof not found.", code="proof_not_found")

        if proof_obj.status != DistributionProof.Status.SUBMITTED:
            raise CampaignStateError(
                f"Cannot start review on proof in status '{proof_obj.status}'. Must be SUBMITTED.",
                code="invalid_state_transition",
            )

        proof_obj.status = DistributionProof.Status.UNDER_REVIEW
        proof_obj.reviewed_by = admin_user
        proof_obj.reviewed_at = timezone.now()
        if admin_notes:
            proof_obj.admin_notes = admin_notes
        proof_obj.save()

    return proof_obj


def verify_distribution_proof(*args, **kwargs) -> DistributionProof:
    """
    Approves and verifies a field distribution proof.
    Supports:
      verify_distribution_proof(admin_user, proof_id, admin_notes=None)
      verify_distribution_proof(proof=p, admin_user=u, admin_notes=...)
    """
    admin_user = kwargs.pop('admin_user', None)
    proof = kwargs.pop('proof', None)
    proof_id = kwargs.pop('proof_id', None)
    admin_notes = kwargs.pop('admin_notes', None)

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            admin_user = first
            if len(args) > 1:
                proof = args[1]
            if len(args) > 2:
                admin_notes = args[2]
        else:
            proof = first
            if len(args) > 1:
                admin_user = args[1]
            if len(args) > 2:
                admin_notes = args[2]

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if not admin_user or (getattr(admin_user, 'role', None) != 'ADMIN' and not getattr(admin_user, 'is_staff', False)):
        raise CampaignPermissionError("Only Platform Administrators can verify distribution proofs.", code="admin_required")

    with transaction.atomic():
        try:
            proof_obj = DistributionProof.objects.select_for_update().select_related('milestone').get(id=proof_id)
        except (DistributionProof.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Distribution proof not found.", code="proof_not_found")

        allowed = VALID_PROOF_TRANSITIONS.get(proof_obj.status, set())
        if DistributionProof.Status.VERIFIED not in allowed:
            raise CampaignStateError(
                f"Cannot verify proof from status '{proof_obj.status}'. Must be UNDER_REVIEW.",
                code="invalid_state_transition",
            )

        proof_obj.status = DistributionProof.Status.VERIFIED
        proof_obj.reviewed_by = admin_user
        proof_obj.reviewed_at = timezone.now()
        if admin_notes:
            proof_obj.admin_notes = admin_notes
        proof_obj.save()

    return proof_obj


def request_proof_revision(*args, **kwargs) -> DistributionProof:
    """
    Requests revisions from the NGO regarding proof evidence (e.g. clearer photo, location coordinates).
    Supports:
      request_proof_revision(admin_user, proof_id, rejection_reason, admin_notes=None)
      request_proof_revision(proof=p, admin_user=u, rejection_reason=..., admin_notes=...)
    """
    admin_user = kwargs.pop('admin_user', None)
    proof = kwargs.pop('proof', None)
    proof_id = kwargs.pop('proof_id', None)
    rejection_reason = kwargs.pop('rejection_reason', None)
    admin_notes = kwargs.pop('admin_notes', None)

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            admin_user = first
            if len(args) > 1:
                proof = args[1]
            if len(args) > 2:
                rejection_reason = args[2]
            if len(args) > 3:
                admin_notes = args[3]
        else:
            proof = first
            if len(args) > 1:
                admin_user = args[1]
            if len(args) > 2:
                rejection_reason = args[2]
            if len(args) > 3:
                admin_notes = args[3]

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if not admin_user or (getattr(admin_user, 'role', None) != 'ADMIN' and not getattr(admin_user, 'is_staff', False)):
        raise CampaignPermissionError("Only Platform Administrators can request proof revisions.", code="admin_required")

    if not rejection_reason or not rejection_reason.strip():
        raise CampaignValidationError("A rejection_reason explaining the requested revision is required.", code="missing_reason")

    with transaction.atomic():
        try:
            proof_obj = DistributionProof.objects.select_for_update().select_related('milestone').get(id=proof_id)
        except (DistributionProof.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Distribution proof not found.", code="proof_not_found")

        allowed = VALID_PROOF_TRANSITIONS.get(proof_obj.status, set())
        if DistributionProof.Status.REVISION_REQUESTED not in allowed:
            raise CampaignStateError(
                f"Cannot request revision on proof from status '{proof_obj.status}'. Must be UNDER_REVIEW.",
                code="invalid_state_transition",
            )

        proof_obj.status = DistributionProof.Status.REVISION_REQUESTED
        proof_obj.reviewed_by = admin_user
        proof_obj.reviewed_at = timezone.now()
        proof_obj.rejection_reason = rejection_reason.strip()
        if admin_notes:
            proof_obj.admin_notes = admin_notes
        proof_obj.save()

        # Update parent milestone to REVISION_REQUESTED if not yet verified
        if proof_obj.milestone.status != CampaignMilestone.MilestoneStatus.VERIFIED:
            proof_obj.milestone.status = CampaignMilestone.MilestoneStatus.REVISION_REQUESTED
            proof_obj.milestone.save(update_fields=['status', 'updated_at'])

    return proof_obj


def reject_distribution_proof(*args, **kwargs) -> DistributionProof:
    """
    Formally rejects a fraudulent, illegitimate, or duplicate distribution proof.
    Supports:
      reject_distribution_proof(admin_user, proof_id, rejection_reason, admin_notes=None)
      reject_distribution_proof(proof=p, admin_user=u, rejection_reason=..., admin_notes=...)
    """
    admin_user = kwargs.pop('admin_user', None)
    proof = kwargs.pop('proof', None)
    proof_id = kwargs.pop('proof_id', None)
    rejection_reason = kwargs.pop('rejection_reason', None)
    admin_notes = kwargs.pop('admin_notes', None)

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            admin_user = first
            if len(args) > 1:
                proof = args[1]
            if len(args) > 2:
                rejection_reason = args[2]
            if len(args) > 3:
                admin_notes = args[3]
        else:
            proof = first
            if len(args) > 1:
                admin_user = args[1]
            if len(args) > 2:
                rejection_reason = args[2]
            if len(args) > 3:
                admin_notes = args[3]

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if not admin_user or (getattr(admin_user, 'role', None) != 'ADMIN' and not getattr(admin_user, 'is_staff', False)):
        raise CampaignPermissionError("Only Platform Administrators can reject distribution proofs.", code="admin_required")

    if not rejection_reason or not rejection_reason.strip():
        raise CampaignValidationError("A rejection_reason is required when rejecting proof.", code="missing_reason")

    with transaction.atomic():
        try:
            proof_obj = DistributionProof.objects.select_for_update().get(id=proof_id)
        except (DistributionProof.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Distribution proof not found.", code="proof_not_found")

        allowed = VALID_PROOF_TRANSITIONS.get(proof_obj.status, set())
        if DistributionProof.Status.REJECTED not in allowed:
            raise CampaignStateError(
                f"Cannot reject proof from status '{proof_obj.status}'. Must be UNDER_REVIEW.",
                code="invalid_state_transition",
            )

        proof_obj.status = DistributionProof.Status.REJECTED
        proof_obj.reviewed_by = admin_user
        proof_obj.reviewed_at = timezone.now()
        proof_obj.rejection_reason = rejection_reason.strip()
        if admin_notes:
            proof_obj.admin_notes = admin_notes
        proof_obj.save()

    return proof_obj


def resubmit_distribution_proof(*args, **kwargs) -> DistributionProof:
    """
    Allows the owning NGO to update and resubmit a proof previously marked REVISION_REQUESTED.
    Supports:
      resubmit_distribution_proof(ngo_user, proof_id, data, photo_file=None)
      resubmit_distribution_proof(proof=p, user=u, photo=..., caption=..., ...)
    """
    ngo_user = kwargs.pop('ngo_user', None) or kwargs.pop('user', None)
    proof = kwargs.pop('proof', None)
    proof_id = kwargs.pop('proof_id', None)
    photo_file = kwargs.pop('photo_file', None) or kwargs.pop('photo', None)
    data = kwargs.pop('data', None)

    if args:
        first = args[0]
        if hasattr(first, 'email') or hasattr(first, 'is_authenticated'):
            ngo_user = first
            if len(args) > 1:
                proof = args[1]
            if len(args) > 2:
                data = args[2]
            if len(args) > 3:
                photo_file = args[3]
        else:
            proof = first
            if len(args) > 1:
                ngo_user = args[1]
            if len(args) > 2:
                data = args[2]
            if len(args) > 3:
                photo_file = args[3]

    if proof is not None:
        proof_id = proof.id if hasattr(proof, 'id') else proof

    if data is None:
        data = kwargs
    else:
        data = {**data, **kwargs}

    with transaction.atomic():
        try:
            proof_obj = DistributionProof.objects.select_for_update().select_related('milestone', 'milestone__campaign').get(id=proof_id)
        except (DistributionProof.DoesNotExist, ValueError):
            raise CampaignNotFoundError("Distribution proof not found.", code="proof_not_found")

        validate_ngo_campaign_access(ngo_user, proof_obj.milestone.campaign)

        if proof_obj.status != DistributionProof.Status.REVISION_REQUESTED:
            raise CampaignStateError(
                f"Cannot resubmit proof in status '{proof_obj.status}'. Resubmission is only allowed for REVISION_REQUESTED proofs.",
                code="resubmit_disallowed",
            )

        # If new photo supplied, validate it
        if photo_file:
            try:
                validate_image_file(photo_file)
            except DjangoValidationError as exc:
                raise CampaignValidationError(str(exc), code="invalid_photo")
            proof_obj.photo = photo_file

        if 'caption' in data and data['caption'].strip():
            proof_obj.caption = data['caption'].strip()

        if 'latitude' in data:
            lat = data['latitude']
            if lat is not None and lat != '':
                lat = Decimal(str(lat))
                if lat < Decimal('-90.000000') or lat > Decimal('90.000000'):
                    raise CampaignValidationError("Latitude must be between -90 and 90 degrees.", code="invalid_latitude")
                proof_obj.latitude = lat
            else:
                proof_obj.latitude = None

        if 'longitude' in data:
            lng = data['longitude']
            if lng is not None and lng != '':
                lng = Decimal(str(lng))
                if lng < Decimal('-180.000000') or lng > Decimal('180.000000'):
                    raise CampaignValidationError("Longitude must be between -180 and 180 degrees.", code="invalid_longitude")
                proof_obj.longitude = lng
            else:
                proof_obj.longitude = None

        if 'beneficiary_count' in data:
            b_count = int(data['beneficiary_count'])
            if b_count < 0:
                raise CampaignValidationError("beneficiary_count cannot be negative.", code="invalid_beneficiary_count")
            proof_obj.beneficiary_count = b_count

        if 'beneficiary_type' in data:
            b_type = data['beneficiary_type']
            if b_type and b_type not in BeneficiaryDemographic.values:
                raise CampaignValidationError("Invalid beneficiary_type choice.", code="invalid_beneficiary_type")
            proof_obj.beneficiary_type = b_type

        if 'beneficiary_notes' in data:
            proof_obj.beneficiary_notes = data['beneficiary_notes']

        if 'spent_amount' in data:
            spent = Decimal(str(data['spent_amount']))
            if spent < Decimal('0.00'):
                raise CampaignValidationError("spent_amount cannot be negative.", code="invalid_spent_amount")
            proof_obj.spent_amount = spent

        if 'expense_breakdown' in data:
            if not isinstance(data['expense_breakdown'], dict):
                raise CampaignValidationError("expense_breakdown must be a valid JSON dictionary.", code="invalid_expense_breakdown")
            proof_obj.expense_breakdown = data['expense_breakdown']

        if 'distribution_date' in data and data['distribution_date']:
            proof_obj.distribution_date = data['distribution_date']

        proof_obj.status = DistributionProof.Status.SUBMITTED
        proof_obj.submitted_at = timezone.now()
        proof_obj.full_clean()
        proof_obj.save()

        # Advance milestone to IN_PROGRESS upon resubmission
        if proof_obj.milestone.status == CampaignMilestone.MilestoneStatus.REVISION_REQUESTED:
            proof_obj.milestone.status = CampaignMilestone.MilestoneStatus.IN_PROGRESS
            proof_obj.milestone.save(update_fields=['status', 'updated_at'])

    return proof_obj
