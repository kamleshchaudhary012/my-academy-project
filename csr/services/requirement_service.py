"""
CSR Requirement Service
=======================
Manages Schedule VII CSR project proposal lifecycles authored by verified NGOs.
Handles drafting, validation, review submission, withdrawal, and closing.
"""

import uuid
from decimal import Decimal
from typing import Optional, Dict, Any
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.text import slugify
from django.contrib.auth import get_user_model

from ngo.models import NGOProfile
from csr.models import (
    CSRRequirement,
    CSRRequirementStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
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


def _validate_ngo_user(user):
    """Ensure user is authenticated, active, and has an APPROVED, active NGOProfile."""
    if not user or not getattr(user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    if not getattr(user, 'is_active', False):
        raise CSROwnershipError("User account is inactive.", code="inactive_user")
    if getattr(user, 'role', None) != 'NGO':
        raise CSROwnershipError("User does not have the NGO role.", code="invalid_role")
    try:
        ngo_profile = user.ngo_profile
    except (AttributeError, Exception):
        raise CSROwnershipError("User has no associated NGO profile.", code="missing_ngo_profile")

    if ngo_profile.status != NGOProfile.Status.APPROVED:
        raise CSROwnershipError(
            "NGO account is not approved for CSR operations.",
            code="ngo_not_approved",
        )

    if not getattr(ngo_profile, 'is_active', False):
        raise CSROwnershipError(
            "NGO account is inactive.",
            code="ngo_inactive",
        )

    # Statutory CSR Eligibility Check (P0-1 Defect Fix)
    legal = getattr(ngo_profile, 'legal_info', None)
    if not legal or not legal.is_csr_eligible:
        raise CSROwnershipError(
            "NGO account does not satisfy statutory CSR eligibility criteria (CSR-1, 3-year track record, and 12A+80G or 10(23C)).",
            code="ngo_csr_ineligible",
        )

    # Admin CSR Verification Check
    verif = getattr(ngo_profile, 'verification', None)
    if not verif or not verif.is_csr_verified:
        raise CSROwnershipError(
            "NGO account has not received administrative CSR verification approval.",
            code="ngo_csr_not_verified",
        )

    return ngo_profile


def _generate_unique_slug(title: str) -> str:
    """Generate a collision-resistant unique slug from title."""
    base_slug = slugify(title)[:200]
    unique_suffix = uuid.uuid4().hex[:8]
    return f"{base_slug}-{unique_suffix}" if base_slug else f"requirement-{unique_suffix}"


def create_requirement(
    ngo_user,
    data: Dict[str, Any],
    proposal_doc=None,
    budget_doc=None,
    impact_doc=None,
) -> CSRRequirement:
    """
    Create a new CSRRequirement in DRAFT status for the authenticated NGO.
    """
    ngo_profile = _validate_ngo_user(ngo_user)

    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'ngo', 'created_by', 'status', 'slug', 'committed_funding',
            'reviewed_by', 'reviewed_at', 'rejection_reason', 'created_at', 'updated_at',
            'proposal_document', 'detailed_budget_document', 'impact_assessment_report',
        }
    }

    required_fields = [
        'title', 'schedule_vii_category', 'state', 'district',
        'location_scope', 'beneficiary_demographic', 'summary',
        'detailed_description', 'expected_outcomes',
        'total_estimated_budget', 'required_csr_funding',
        'start_date', 'expected_completion_date',
    ]
    missing = [f for f in required_fields if sanitized_data.get(f) is None or sanitized_data.get(f) == ""]
    if missing:
        raise CSRValidationError(
            f"Missing required proposal fields: {', '.join(missing)}",
            code="missing_required_fields",
            details={"missing_fields": missing},
        )

    total_budget = Decimal(str(sanitized_data['total_estimated_budget']))
    required_funding = Decimal(str(sanitized_data['required_csr_funding']))

    if total_budget < Decimal('10000.00'):
        raise CSRValidationError("total_estimated_budget must be at least ₹10,000.00.", code="budget_too_low")

    if required_funding < Decimal('10000.00'):
        raise CSRValidationError("required_csr_funding must be at least ₹10,000.00.", code="funding_too_low")

    if required_funding > total_budget:
        raise CSRValidationError(
            "required_csr_funding cannot exceed total_estimated_budget.",
            code="required_funding_exceeds_total",
        )

    start_d = sanitized_data['start_date']
    end_d = sanitized_data['expected_completion_date']
    if end_d < start_d:
        raise CSRValidationError(
            "expected_completion_date must be on or after start_date.",
            code="invalid_date_order",
        )

    slug = _generate_unique_slug(sanitized_data['title'])

    with transaction.atomic():
        requirement = CSRRequirement(
            ngo=ngo_profile,
            created_by=ngo_user,
            status=CSRRequirementStatus.DRAFT,
            slug=slug,
            committed_funding=Decimal('0.00'),
            **sanitized_data,
        )
        if proposal_doc:
            requirement.proposal_document = proposal_doc
        if budget_doc:
            requirement.detailed_budget_document = budget_doc
        if impact_doc:
            requirement.impact_assessment_report = impact_doc

        try:
            requirement.full_clean(exclude=['ngo', 'created_by'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)
        requirement.save()

    return requirement


def get_requirement_for_ngo(ngo_user, requirement_id: Any) -> CSRRequirement:
    """
    Retrieve a CSRRequirement owned by the authenticated NGO.
    Fails closed with CSRNotFoundError on cross-tenant access.
    """
    ngo_profile = _validate_ngo_user(ngo_user)
    try:
        return CSRRequirement.objects.get(id=requirement_id, ngo=ngo_profile)
    except (CSRRequirement.DoesNotExist, ValueError):
        raise CSRNotFoundError(
            "CSR requirement not found or does not belong to this NGO.",
            code="requirement_not_found",
        )


def list_requirements_for_ngo(ngo_user, status: Optional[str] = None):
    """
    List all CSRRequirements owned by the authenticated NGO, optionally filtered by status.
    """
    ngo_profile = _validate_ngo_user(ngo_user)
    qs = CSRRequirement.objects.filter(ngo=ngo_profile)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by('-created_at')


def update_requirement(
    ngo_user,
    requirement_id: Any,
    data: Dict[str, Any],
    proposal_doc=None,
    budget_doc=None,
    impact_doc=None,
) -> CSRRequirement:
    """
    Update editable proposal fields in DRAFT or REJECTED state.
    """
    ngo_profile = _validate_ngo_user(ngo_user)

    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'ngo', 'created_by', 'status', 'slug', 'committed_funding',
            'reviewed_by', 'reviewed_at', 'rejection_reason', 'created_at', 'updated_at',
            'proposal_document', 'detailed_budget_document', 'impact_assessment_report',
        }
    }

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id, ngo=ngo_profile)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        if req.status not in (CSRRequirementStatus.DRAFT, CSRRequirementStatus.REJECTED):
            raise CSRStateError(
                f"Cannot update requirement in status '{req.status}'. Must be in DRAFT or REJECTED.",
                code="cannot_edit_active_requirement",
            )

        for field, val in sanitized_data.items():
            if hasattr(req, field):
                setattr(req, field, val)

        if proposal_doc is not None:
            req.proposal_document = proposal_doc
        if budget_doc is not None:
            req.detailed_budget_document = budget_doc
        if impact_doc is not None:
            req.impact_assessment_report = impact_doc

        # Validate numeric and date constraints
        if req.total_estimated_budget < Decimal('10000.00'):
            raise CSRValidationError("total_estimated_budget must be at least ₹10,000.00.", code="budget_too_low")
        if req.required_csr_funding < Decimal('10000.00'):
            raise CSRValidationError("required_csr_funding must be at least ₹10,000.00.", code="funding_too_low")
        if req.required_csr_funding > req.total_estimated_budget:
            raise CSRValidationError("required_csr_funding cannot exceed total_estimated_budget.", code="required_funding_exceeds_total")
        if req.expected_completion_date < req.start_date:
            raise CSRValidationError("expected_completion_date must be on or after start_date.", code="invalid_date_order")

        try:
            req.full_clean(exclude=['ngo', 'created_by'])
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            msg = str(exc.messages[0]) if (hasattr(exc, 'messages') and exc.messages) else str(exc)
            raise CSRValidationError(msg, code="model_validation_error", details=details)
        req.save()

    return req


def submit_requirement(ngo_user, requirement_id: Any) -> CSRRequirement:
    """
    Submit proposal for administrative review (DRAFT / REJECTED -> PENDING_REVIEW).
    """
    ngo_profile = _validate_ngo_user(ngo_user)

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id, ngo=ngo_profile)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        if req.status == CSRRequirementStatus.PENDING_REVIEW:
            return req

        if req.status not in (CSRRequirementStatus.DRAFT, CSRRequirementStatus.REJECTED):
            raise CSRStateError(
                f"Cannot submit requirement from status '{req.status}'.",
                code="invalid_submission_state",
            )

        # Invariant checks
        if req.required_csr_funding > req.total_estimated_budget:
            raise CSRValidationError("required_csr_funding cannot exceed total_estimated_budget.", code="required_funding_exceeds_total")
        if req.expected_completion_date < req.start_date:
            raise CSRValidationError("expected_completion_date must be on or after start_date.", code="invalid_date_order")

        old_status = req.status
        req.status = CSRRequirementStatus.PENDING_REVIEW
        req.rejection_reason = None
        req.save(update_fields=['status', 'rejection_reason', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.id,
            old_status=old_status,
            new_status=CSRRequirementStatus.PENDING_REVIEW,
            actor_user=ngo_user,
            review_notes="NGO submitted proposal for platform verification.",
        )

    return req


def withdraw_requirement(ngo_user, requirement_id: Any, reason: str = "") -> CSRRequirement:
    """
    Withdraw proposal from review back to DRAFT (PENDING_REVIEW -> DRAFT).
    """
    ngo_profile = _validate_ngo_user(ngo_user)

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id, ngo=ngo_profile)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        if req.status != CSRRequirementStatus.PENDING_REVIEW:
            raise CSRStateError(
                f"Only proposals in PENDING_REVIEW can be withdrawn. Current status: '{req.status}'.",
                code="invalid_withdrawal_state",
            )

        old_status = req.status
        req.status = CSRRequirementStatus.DRAFT
        req.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.id,
            old_status=old_status,
            new_status=CSRRequirementStatus.DRAFT,
            actor_user=ngo_user,
            review_notes=f"Proposal withdrawn by NGO: {reason}" if reason else "Proposal withdrawn by NGO.",
        )

    return req


def close_requirement(ngo_user, requirement_id: Any, reason: str = "") -> CSRRequirement:
    """
    Close an active requirement (OPEN_FOR_CSR / PARTNERED -> COMPLETED).
    """
    ngo_profile = _validate_ngo_user(ngo_user)

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id, ngo=ngo_profile)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        if req.status not in (CSRRequirementStatus.OPEN_FOR_CSR, CSRRequirementStatus.PARTNERED):
            raise CSRStateError(
                f"Cannot close requirement in status '{req.status}'.",
                code="invalid_closing_state",
            )

        old_status = req.status
        req.status = CSRRequirementStatus.COMPLETED
        req.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.id,
            old_status=old_status,
            new_status=CSRRequirementStatus.COMPLETED,
            actor_user=ngo_user,
            review_notes=f"Requirement closed by NGO: {reason}" if reason else "Requirement closed by NGO.",
        )

    return req
