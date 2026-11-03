"""
CSR Support Request Service
===========================
Manages corporate Expressions of Interest (EOIs) / support requests, duplicate prevention,
NGO review acceptance workflows, and automated partnership initialization.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from ngo.models import NGOProfile
from csr.models import (
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CompanyProfile,
    CompanyVerificationStatus,
    CSRAuditEntityType,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
    CSRPermissionError,
)
from csr.services.audit_service import record_verification_event
from csr.services.partnership_service import create_partnership_from_request

User = get_user_model()


def _validate_verified_company_user(user) -> CompanyProfile:
    """Validate user is an authenticated, active COMPANY with an APPROVED CompanyProfile."""
    if not user or not getattr(user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    if not getattr(user, 'is_active', False):
        raise CSROwnershipError("User account is inactive.", code="inactive_user")
    if getattr(user, 'role', None) != 'COMPANY':
        raise CSROwnershipError("User does not have the COMPANY role.", code="invalid_role")

    company = CompanyProfile.objects.filter(user=user).first()
    if not company:
        raise CSROwnershipError("No company profile found for this user account.", code="company_profile_not_found")

    if company.verification_status != CompanyVerificationStatus.APPROVED:
        raise CSRPermissionError(
            f"Only verified corporate accounts can submit CSR support requests. Current status: '{company.verification_status}'.",
            code="company_not_verified",
        )

    return company


def _validate_ngo_user(user):
    """Validate user is an authenticated, active NGO with an APPROVED, active NGOProfile."""
    if not user or not getattr(user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    if not getattr(user, 'is_active', False):
        raise CSROwnershipError("User account is inactive.", code="inactive_user")
    if getattr(user, 'role', None) != 'NGO':
        raise CSROwnershipError("User does not have the NGO role.", code="invalid_role")

    ngo_profile = NGOProfile.objects.filter(user=user).first()
    if not ngo_profile:
        raise CSROwnershipError("No NGO profile found for this user account.", code="ngo_profile_not_found")

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


def _is_support_request_participant(user, request: CSRSupportRequest) -> bool:
    """Check if the user is the author company, the requirement's owning NGO, or an ADMIN."""
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'role', None) == 'ADMIN':
        return True
    if hasattr(user, 'company_profile') and request.company == user.company_profile:
        return True
    if hasattr(user, 'ngo_profile') and request.requirement.ngo == user.ngo_profile:
        return user.ngo_profile.status == NGOProfile.Status.APPROVED and getattr(user.ngo_profile, 'is_active', False)
    return False


def create_support_request(
    company_user,
    requirement_id: Any,
    data: Dict[str, Any],
) -> CSRSupportRequest:
    """
    Create a new Expression of Interest (EOI) / CSRSupportRequest for a requirement.
    Requirement must be in OPEN_FOR_CSR status.
    """
    company = _validate_verified_company_user(company_user)

    try:
        requirement = CSRRequirement.objects.select_related('ngo').get(id=requirement_id)
    except (CSRRequirement.DoesNotExist, ValueError):
        raise CSRNotFoundError("CSR requirement not found.", code="requirement_not_found")

    if requirement.status != CSRRequirementStatus.OPEN_FOR_CSR:
        raise CSRStateError(
            f"Cannot submit support request for requirement in status '{requirement.status}'. Must be OPEN_FOR_CSR.",
            code="requirement_not_open",
        )

    # Check for existing active/pending support request
    if CSRSupportRequest.objects.filter(
        company=company,
        requirement=requirement,
        status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
    ).exists():
        raise CSRConflictError(
            "An active support request from your company is already pending review for this requirement.",
            code="duplicate_pending_request",
        )

    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'company', 'requirement', 'company_name_snapshot', 'status',
            'rejection_reason', 'withdrawal_reason', 'reviewed_by', 'reviewed_at',
            'expires_at', 'created_at', 'updated_at',
        }
    }

    required_fields = ['spoc_name', 'spoc_email', 'proposed_funding', 'support_type', 'message']
    missing = [f for f in required_fields if not sanitized_data.get(f)]
    if missing:
        raise CSRValidationError(
            f"Missing required fields: {', '.join(missing)}",
            code="missing_required_fields",
            details={"missing_fields": missing},
        )

    funding_dec = Decimal(str(sanitized_data['proposed_funding']))
    if funding_dec < Decimal('1000.00'):
        raise CSRValidationError("proposed_funding must be at least ₹1,000.00.", code="funding_too_low")

    expires_at = timezone.now() + timedelta(days=60)

    with transaction.atomic():
        support_req = CSRSupportRequest(
            company=company,
            requirement=requirement,
            company_name_snapshot=company.company_name,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
            expires_at=expires_at,
            **sanitized_data,
        )
        support_req.full_clean(exclude=['company', 'requirement'])
        support_req.save()

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=requirement.id,
            old_status=requirement.status,
            new_status=requirement.status,
            actor_user=company_user,
            review_notes=f"Support request {support_req.id} submitted by company '{company.company_name}'.",
            metadata={"support_request_id": str(support_req.id), "proposed_funding": str(funding_dec)},
        )

    return support_req


def get_support_request(user, request_id: Any) -> CSRSupportRequest:
    """
    Retrieve a CSRSupportRequest scoped strictly to participants (author company, owning NGO, or Admin).
    """
    try:
        req = CSRSupportRequest.objects.select_related('company', 'requirement', 'requirement__ngo').get(id=request_id)
    except (CSRSupportRequest.DoesNotExist, ValueError):
        raise CSRNotFoundError("CSR support request not found.", code="request_not_found")

    if not _is_support_request_participant(user, req):
        raise CSRNotFoundError("CSR support request not found or access denied.", code="request_not_found")

    return req


def list_inbox_for_ngo(ngo_user, requirement_id: Optional[Any] = None, status: Optional[str] = None):
    """
    List incoming support requests for the NGO's requirements.
    """
    ngo_profile = _validate_ngo_user(ngo_user)
    qs = CSRSupportRequest.objects.filter(requirement__ngo=ngo_profile).select_related('company', 'requirement')
    if requirement_id:
        qs = qs.filter(requirement_id=requirement_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by('-created_at')


def list_outbox_for_company(company_user, status: Optional[str] = None):
    """
    List submitted support requests for the corporate user.
    """
    if not company_user or not getattr(company_user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    try:
        company = company_user.company_profile
    except Exception:
        raise CSROwnershipError("User has no associated company profile.", code="company_profile_not_found")

    qs = CSRSupportRequest.objects.filter(company=company).select_related('requirement', 'requirement__ngo')
    if status:
        qs = qs.filter(status=status)
    return qs.order_by('-created_at')


def withdraw_support_request(company_user, request_id: Any, reason: str = "") -> CSRSupportRequest:
    """
    Withdraw a submitted support request (PENDING_NGO_REVIEW -> WITHDRAWN).
    Only the authoring company can withdraw.
    """
    if not reason:
        raise CSRValidationError("A withdrawal reason is required.", code="missing_withdrawal_reason")

    if not company_user or not getattr(company_user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    try:
        company = company_user.company_profile
    except Exception:
        raise CSROwnershipError("User has no associated company profile.", code="company_profile_not_found")

    with transaction.atomic():
        try:
            req = CSRSupportRequest.objects.select_for_update().get(id=request_id, company=company)
        except (CSRSupportRequest.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR support request not found.", code="request_not_found")

        if req.status != CSRSupportRequestStatus.PENDING_NGO_REVIEW:
            raise CSRStateError(
                f"Only pending requests can be withdrawn. Current status: '{req.status}'.",
                code="cannot_withdraw_non_pending",
            )

        old_status = req.status
        req.status = CSRSupportRequestStatus.WITHDRAWN
        req.withdrawal_reason = reason
        req.save(update_fields=['status', 'withdrawal_reason', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.requirement_id,
            old_status=old_status,
            new_status=CSRSupportRequestStatus.WITHDRAWN,
            actor_user=company_user,
            review_notes=f"Support request {req.id} withdrawn by company: {reason}",
        )

    return req


def accept_support_request(
    ngo_user,
    request_id: Any,
    decision_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Accept a support request and atomically generate a bilateral CSRPartnership.
    Idempotent under concurrent calls.
    """
    ngo_profile = _validate_ngo_user(ngo_user)
    decision_data = decision_data or {}

    with transaction.atomic():
        try:
            req = CSRSupportRequest.objects.select_for_update().select_related('requirement').get(
                id=request_id,
                requirement__ngo=ngo_profile,
            )
        except (CSRSupportRequest.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR support request not found.", code="request_not_found")

        # Idempotent response if already accepted
        if req.status == CSRSupportRequestStatus.ACCEPTED:
            partnership = getattr(req, 'partnership', None)
            if not partnership:
                partnership = create_partnership_from_request(req)
            return {"support_request": req, "partnership": partnership}

        if req.status != CSRSupportRequestStatus.PENDING_NGO_REVIEW:
            raise CSRStateError(
                f"Cannot accept support request in status '{req.status}'. Must be PENDING_NGO_REVIEW.",
                code="invalid_acceptance_state",
            )

        old_status = req.status
        req.status = CSRSupportRequestStatus.ACCEPTED
        req.reviewed_by = ngo_user
        req.reviewed_at = timezone.now()
        req.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        # Update requirement committed funding
        requirement = CSRRequirement.objects.select_for_update().get(id=req.requirement_id)
        requirement.committed_funding += req.proposed_funding
        if requirement.committed_funding >= requirement.required_csr_funding:
            requirement.status = CSRRequirementStatus.PARTNERED
        requirement.save(update_fields=['committed_funding', 'status', 'updated_at'])

        # Create bilateral partnership
        agreed_amount = decision_data.get('agreed_funding_amount', req.proposed_funding)
        start_d = decision_data.get('execution_start_date', requirement.start_date)
        target_d = decision_data.get('target_completion_date', requirement.expected_completion_date)

        partnership = create_partnership_from_request(
            support_request=req,
            agreed_funding_amount=agreed_amount,
            execution_start_date=start_d,
            target_completion_date=target_d,
        )

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=requirement.id,
            old_status=old_status,
            new_status=CSRSupportRequestStatus.ACCEPTED,
            actor_user=ngo_user,
            review_notes=f"NGO accepted support request from '{req.company_name_snapshot}'. Partnership code: {partnership.partnership_code}.",
            metadata={"partnership_id": str(partnership.id), "partnership_code": partnership.partnership_code},
        )

    return {"support_request": req, "partnership": partnership}


def reject_support_request(ngo_user, request_id: Any, reason: str = "") -> CSRSupportRequest:
    """
    Reject a support request (PENDING_NGO_REVIEW -> REJECTED).
    Requires a non-empty reason.
    """
    if not reason:
        raise CSRValidationError("A rejection reason is mandatory.", code="missing_rejection_reason")

    ngo_profile = _validate_ngo_user(ngo_user)

    with transaction.atomic():
        try:
            req = CSRSupportRequest.objects.select_for_update().get(
                id=request_id,
                requirement__ngo=ngo_profile,
            )
        except (CSRSupportRequest.DoesNotExist, ValueError):
            raise CSRNotFoundError("CSR support request not found.", code="request_not_found")

        if req.status != CSRSupportRequestStatus.PENDING_NGO_REVIEW:
            raise CSRStateError(
                f"Cannot reject support request in status '{req.status}'. Must be PENDING_NGO_REVIEW.",
                code="cannot_reject_non_pending",
            )

        old_status = req.status
        req.status = CSRSupportRequestStatus.REJECTED
        req.rejection_reason = reason
        req.reviewed_by = ngo_user
        req.reviewed_at = timezone.now()
        req.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=req.requirement_id,
            old_status=old_status,
            new_status=CSRSupportRequestStatus.REJECTED,
            actor_user=ngo_user,
            review_notes=f"Support request rejected by NGO: {reason}",
        )

    return req
