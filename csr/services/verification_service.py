"""
CSR Verification Service
========================
Manages administrative review, approval, rejection, and suspension lifecycles
for corporate profiles and Schedule VII CSR project requirements.
"""

from typing import Optional, Any
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRRequirementStatus,
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


def _validate_admin_user(user) -> None:
    """Ensure caller has active ADMIN privileges."""
    if not user or not getattr(user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    if not getattr(user, 'is_active', False):
        raise CSROwnershipError("User account is inactive.", code="inactive_user")
    if getattr(user, 'role', None) != 'ADMIN':
        raise CSROwnershipError("Administrative role required for verification actions.", code="admin_privilege_required")


# ===========================================================================
# Corporate Profile Admin Verification
# ===========================================================================

def start_company_review(admin_user, company_id: Any) -> CompanyProfile:
    """
    Retrieve and lock a company profile for administrative inspection.
    """
    _validate_admin_user(admin_user)
    try:
        return CompanyProfile.objects.get(id=company_id)
    except (CompanyProfile.DoesNotExist, ValueError):
        raise CSRNotFoundError("Company profile not found.", code="company_not_found")


def approve_company(admin_user, company_id: Any, review_notes: str = "") -> CompanyProfile:
    """
    Approve a corporate entity (PENDING_VERIFICATION / SUSPENDED -> APPROVED).
    Idempotent under repeat approval calls.
    """
    _validate_admin_user(admin_user)

    with transaction.atomic():
        try:
            company = CompanyProfile.objects.select_for_update().get(id=company_id)
        except (CompanyProfile.DoesNotExist, ValueError):
            raise CSRNotFoundError("Company profile not found.", code="company_not_found")

        if company.verification_status == CompanyVerificationStatus.APPROVED:
            return company

        if company.verification_status not in (
            CompanyVerificationStatus.PENDING_VERIFICATION,
            CompanyVerificationStatus.SUSPENDED,
            CompanyVerificationStatus.DRAFT,
            CompanyVerificationStatus.CORRECTION_REQUIRED,
        ):
            raise CSRStateError(
                f"Cannot approve company in status '{company.verification_status}'.",
                code="invalid_company_approval_state",
            )

        old_status = company.verification_status
        company.verification_status = CompanyVerificationStatus.APPROVED
        company.verified_by = admin_user
        company.verified_at = timezone.now()
        company.rejection_reason = None
        company.suspension_reason = None
        company.correction_instructions = ''
        if review_notes:
            company.admin_notes = review_notes
        company.save(update_fields=[
            'verification_status', 'verified_by', 'verified_at',
            'rejection_reason', 'suspension_reason', 'correction_instructions',
            'admin_notes', 'updated_at',
        ])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=old_status,
            new_status=CompanyVerificationStatus.APPROVED,
            actor_user=admin_user,
            review_notes=review_notes or "Company profile verified and approved.",
        )

    return company


def reject_company(admin_user, company_id: Any, reason: str = "") -> CompanyProfile:
    """
    Reject a corporate verification application (PENDING_VERIFICATION -> REJECTED).
    Requires a non-empty reason.
    """
    _validate_admin_user(admin_user)
    if not reason:
        raise CSRValidationError("Rejection reason is mandatory.", code="missing_rejection_reason")

    with transaction.atomic():
        try:
            company = CompanyProfile.objects.select_for_update().get(id=company_id)
        except (CompanyProfile.DoesNotExist, ValueError):
            raise CSRNotFoundError("Company profile not found.", code="company_not_found")

        old_status = company.verification_status
        company.verification_status = CompanyVerificationStatus.REJECTED
        company.rejection_reason = reason
        company.save(update_fields=['verification_status', 'rejection_reason', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=old_status,
            new_status=CompanyVerificationStatus.REJECTED,
            actor_user=admin_user,
            review_notes=f"Company profile rejected: {reason}",
        )

    return company


def suspend_company(admin_user, company_id: Any, reason: str = "") -> CompanyProfile:
    """
    Suspend an active corporate entity (APPROVED -> SUSPENDED).
    """
    _validate_admin_user(admin_user)
    if not reason:
        raise CSRValidationError("Suspension reason is mandatory.", code="missing_suspension_reason")

    with transaction.atomic():
        try:
            company = CompanyProfile.objects.select_for_update().get(id=company_id)
        except (CompanyProfile.DoesNotExist, ValueError):
            raise CSRNotFoundError("Company profile not found.", code="company_not_found")

        old_status = company.verification_status
        company.verification_status = CompanyVerificationStatus.SUSPENDED
        company.suspension_reason = reason
        company.save(update_fields=['verification_status', 'suspension_reason', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=old_status,
            new_status=CompanyVerificationStatus.SUSPENDED,
            actor_user=admin_user,
            review_notes=f"Company profile suspended: {reason}",
        )

    return company


def request_company_changes(admin_user, company_id: Any, notes: str = "") -> CompanyProfile:
    """
    Request modifications from company, moving back to DRAFT (PENDING_VERIFICATION -> DRAFT).
    """
    _validate_admin_user(admin_user)
    if not notes:
        raise CSRValidationError("Change request notes are mandatory.", code="missing_change_notes")

    with transaction.atomic():
        try:
            company = CompanyProfile.objects.select_for_update().get(id=company_id)
        except (CompanyProfile.DoesNotExist, ValueError):
            raise CSRNotFoundError("Company profile not found.", code="company_not_found")

        old_status = company.verification_status
        company.verification_status = CompanyVerificationStatus.DRAFT
        company.rejection_reason = notes
        company.save(update_fields=['verification_status', 'rejection_reason', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=old_status,
            new_status=CompanyVerificationStatus.DRAFT,
            actor_user=admin_user,
            review_notes=f"Changes requested for company profile: {notes}",
        )

    return company


def request_company_corrections(
    admin_user,
    company_id: Any,
    correction_instructions: str,
    admin_notes: str = "",
) -> CompanyProfile:
    """
    Admin requests specific corrections from corporate user (PENDING_VERIFICATION -> CORRECTION_REQUIRED).
    Mandates non-empty correction_instructions.
    """
    _validate_admin_user(admin_user)
    if not correction_instructions or not str(correction_instructions).strip():
        raise CSRValidationError("Correction instructions are mandatory.", code="missing_correction_instructions")

    with transaction.atomic():
        try:
            company = CompanyProfile.objects.select_for_update().get(id=company_id)
        except (CompanyProfile.DoesNotExist, ValueError):
            raise CSRNotFoundError("Company profile not found.", code="company_not_found")

        old_status = company.verification_status
        company.verification_status = CompanyVerificationStatus.CORRECTION_REQUIRED
        company.correction_instructions = str(correction_instructions).strip()
        if admin_notes:
            company.admin_notes = admin_notes
        company.save(update_fields=['verification_status', 'correction_instructions', 'admin_notes', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=old_status,
            new_status=CompanyVerificationStatus.CORRECTION_REQUIRED,
            actor_user=admin_user,
            review_notes=f"Corrections requested: {correction_instructions}",
        )

    return company


def record_company_manual_verification(
    admin_user,
    company_id: Any,
    outcome: str,
    source: str = 'MANUAL_ADMIN_CHECK',
    notes: str = '',
) -> CompanyProfile:
    """
    Records administrative manual verification result for corporate government identifiers (CIN, PAN).
    Passing this check NEVER automatically approves the company!
    """
    _validate_admin_user(admin_user)
    from ngo.models import GovCheckStatus
    valid_outcomes = {
        GovCheckStatus.GOVERNMENT_CHECK_PASSED,
        GovCheckStatus.GOVERNMENT_CHECK_FAILED,
        GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
        GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE,
        GovCheckStatus.GOVERNMENT_CHECK_PENDING,
    }
    if outcome not in valid_outcomes:
        raise CSRValidationError(f"Invalid verification outcome {outcome}.", code="invalid_outcome")

    with transaction.atomic():
        try:
            company = CompanyProfile.objects.select_for_update().get(id=company_id)
        except (CompanyProfile.DoesNotExist, ValueError):
            raise CSRNotFoundError("Company profile not found.", code="company_not_found")

        now = timezone.now()
        company.gov_check_status = outcome
        company.gov_check_source = source
        company.gov_check_details = {
            'outcome': outcome,
            'source': source,
            'notes': notes,
            'recorded_by': admin_user.email,
            'timestamp': now.isoformat(),
        }
        company.gov_check_completed_at = now
        company.save(update_fields=[
            'gov_check_status', 'gov_check_source',
            'gov_check_details', 'gov_check_completed_at',
            'updated_at',
        ])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=company.verification_status,
            new_status=company.verification_status,
            actor_user=admin_user,
            review_notes=f"Admin recorded manual verification check: {outcome} via {source}. Notes: {notes}",
        )

    return company


# ===========================================================================
# CSR Requirement Admin Verification
# ===========================================================================

def start_requirement_review(admin_user, requirement_id: Any) -> CSRRequirement:
    """
    Retrieve and lock a proposal for administrative inspection.
    """
    _validate_admin_user(admin_user)
    try:
        return CSRRequirement.objects.get(id=requirement_id)
    except (CSRRequirement.DoesNotExist, ValueError):
        raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")


def approve_requirement(
    admin_user,
    requirement_id: Any,
    publish_open_for_csr: bool = True,
    review_notes: str = "",
) -> CSRRequirement:
    """
    Approve a proposal (PENDING_REVIEW / SUSPENDED -> OPEN_FOR_CSR or APPROVED).
    Idempotent under repeat calls.
    """
    _validate_admin_user(admin_user)

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        target_status = CSRRequirementStatus.OPEN_FOR_CSR if publish_open_for_csr else CSRRequirementStatus.APPROVED
        if req.status == target_status:
            return req

        if req.status not in (CSRRequirementStatus.PENDING_REVIEW, CSRRequirementStatus.APPROVED, CSRRequirementStatus.SUSPENDED):
            raise CSRStateError(
                f"Cannot approve requirement from status '{req.status}'.",
                code="invalid_requirement_approval_state",
            )

        old_status = req.status
        req.status = target_status
        req.reviewed_by = admin_user
        req.reviewed_at = timezone.now()
        req.rejection_reason = None
        req.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.id,
            old_status=old_status,
            new_status=target_status,
            actor_user=admin_user,
            review_notes=review_notes or f"Requirement approved and set to {target_status}.",
        )

    return req


def reject_requirement(admin_user, requirement_id: Any, reason: str = "") -> CSRRequirement:
    """
    Reject a proposal (PENDING_REVIEW -> REJECTED).
    Requires a non-empty reason.
    """
    _validate_admin_user(admin_user)
    if not reason:
        raise CSRValidationError("Rejection reason is mandatory.", code="missing_rejection_reason")

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        old_status = req.status
        req.status = CSRRequirementStatus.REJECTED
        req.rejection_reason = reason
        req.reviewed_by = admin_user
        req.reviewed_at = timezone.now()
        req.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.id,
            old_status=old_status,
            new_status=CSRRequirementStatus.REJECTED,
            actor_user=admin_user,
            review_notes=f"Requirement rejected: {reason}",
        )

    return req


def suspend_requirement(admin_user, requirement_id: Any, reason: str = "") -> CSRRequirement:
    """
    Suspend an active proposal (OPEN_FOR_CSR / APPROVED -> SUSPENDED).
    """
    _validate_admin_user(admin_user)
    if not reason:
        raise CSRValidationError("Suspension reason is mandatory.", code="missing_suspension_reason")

    with transaction.atomic():
        try:
            req = CSRRequirement.objects.select_for_update().get(id=requirement_id)
        except (CSRRequirement.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

        old_status = req.status
        req.status = CSRRequirementStatus.SUSPENDED
        req.save(update_fields=['status', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.id,
            old_status=old_status,
            new_status=CSRRequirementStatus.SUSPENDED,
            actor_user=admin_user,
            review_notes=f"Requirement suspended: {reason}",
        )

    return req
