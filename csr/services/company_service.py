"""
CSR Company Service
===================
Manages corporate profile registration, profile updates, preference management,
and verification submission lifecycles.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from django.db import transaction
from django.contrib.auth import get_user_model

from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CompanyVerificationStatus,
    CSRAuditEntityType,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
)
from csr.services.audit_service import record_verification_event

User = get_user_model()


def _validate_company_user(user) -> None:
    """Ensure user is authenticated, active, and has the COMPANY role."""
    if not user or not getattr(user, 'is_authenticated', False):
        raise CSROwnershipError("Authentication required.", code="unauthenticated")
    if not getattr(user, 'is_active', False):
        raise CSROwnershipError("User account is inactive.", code="inactive_user")
    if getattr(user, 'role', None) != 'COMPANY':
        raise CSROwnershipError("User does not have the COMPANY role.", code="invalid_role")


def register_company(user, data: Dict[str, Any], verification_doc=None) -> CompanyProfile:
    """
    Register a new CompanyProfile for the authenticated corporate user.
    Initial state is DRAFT. Creates default CompanyCSRPreference atomically.
    """
    _validate_company_user(user)

    if CompanyProfile.objects.filter(user=user).exists():
        raise CSRConflictError(
            "A company profile already exists for this user account.",
            code="profile_already_exists",
        )

    # Sanitize input: strip protected administrative / status fields
    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'user', 'verification_status', 'verified_by',
            'verified_at', 'rejection_reason', 'suspension_reason',
            'created_at', 'updated_at', 'verification_document',
        }
    }

    # Validate required fields
    required_fields = ['company_name', 'legal_name', 'pan_number', 'contact_person_name',
                       'contact_person_designation', 'contact_email', 'contact_phone',
                       'registered_address', 'city', 'state', 'pincode']
    missing = [f for f in required_fields if not sanitized_data.get(f)]
    if missing:
        raise CSRValidationError(
            f"Missing mandatory profile fields: {', '.join(missing)}",
            code="missing_required_fields",
            details={"missing_fields": missing},
        )

    with transaction.atomic():
        company = CompanyProfile(
            user=user,
            verification_status=CompanyVerificationStatus.DRAFT,
            **sanitized_data,
        )
        if verification_doc:
            company.verification_document = verification_doc

        company.full_clean(exclude=['user'])
        company.save()

        # Create associated preferences
        CompanyCSRPreference.objects.create(company=company)

    return company


def get_company_for_user(user) -> CompanyProfile:
    """
    Retrieve the CompanyProfile belonging to the authenticated user.
    """
    _validate_company_user(user)
    try:
        return user.company_profile
    except (CompanyProfile.DoesNotExist, AttributeError):
        raise CSRNotFoundError(
            "No company profile found for this user account.",
            code="company_profile_not_found",
        )


def update_company_profile(user, data: Dict[str, Any], verification_doc=None) -> CompanyProfile:
    """
    Update editable fields of the corporate profile.
    Client-supplied status/verification fields are stripped.
    """
    company = get_company_for_user(user)

    sanitized_data = {
        k: v for k, v in data.items()
        if k not in {
            'id', 'user', 'verification_status', 'verified_by',
            'verified_at', 'rejection_reason', 'suspension_reason',
            'created_at', 'updated_at', 'verification_document',
        }
    }

    with transaction.atomic():
        company = CompanyProfile.objects.select_for_update().get(id=company.id)
        for field, val in sanitized_data.items():
            if hasattr(company, field):
                setattr(company, field, val)

        if verification_doc is not None:
            company.verification_document = verification_doc

        company.full_clean(exclude=['user'])
        company.save()

    return company


def attach_company_document(user, document_file) -> CompanyProfile:
    """
    Upload or replace the company verification document.
    """
    if not document_file:
        raise CSRValidationError("Document file is required.", code="missing_document")

    company = get_company_for_user(user)
    with transaction.atomic():
        company = CompanyProfile.objects.select_for_update().get(id=company.id)
        company.verification_document = document_file
        company.save(update_fields=['verification_document', 'updated_at'])

    return company


def request_company_verification(user) -> CompanyProfile:
    """
    Submit company profile for administrative verification (DRAFT / REJECTED -> PENDING_VERIFICATION).
    """
    company = get_company_for_user(user)

    with transaction.atomic():
        company = CompanyProfile.objects.select_for_update().get(id=company.id)

        # Idempotent return if already pending
        if company.verification_status == CompanyVerificationStatus.PENDING_VERIFICATION:
            return company

        if company.verification_status == CompanyVerificationStatus.APPROVED:
            raise CSRStateError("Company profile is already approved / verified.", code="already_approved")

        if company.verification_status == CompanyVerificationStatus.SUSPENDED:
            raise CSRStateError("Suspended company profile cannot request verification directly.", code="suspended_profile")

        if company.verification_status not in (
            CompanyVerificationStatus.DRAFT,
            CompanyVerificationStatus.REJECTED,
            CompanyVerificationStatus.CORRECTION_REQUIRED,
        ):
            raise CSRStateError(
                f"Cannot request verification from status '{company.verification_status}'.",
                code="invalid_verification_transition",
            )

        if not company.verification_document:
            raise CSRValidationError(
                "A valid verification document (e.g. Certificate of Incorporation) must be uploaded before requesting verification.",
                code="missing_verification_document",
            )

        old_status = company.verification_status
        company.verification_status = CompanyVerificationStatus.PENDING_VERIFICATION
        company.rejection_reason = None
        company.correction_instructions = ''
        company.save(update_fields=['verification_status', 'rejection_reason', 'correction_instructions', 'updated_at'])

        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=company.id,
            old_status=old_status,
            new_status=CompanyVerificationStatus.PENDING_VERIFICATION,
            actor_user=user,
            review_notes="Corporate user requested profile verification.",
        )

        # Initial government check step
        from ngo.services.government_verification_service import GovernmentVerificationService
        GovernmentVerificationService.run_company_government_verification(company)

    return company


def get_company_preferences(user) -> CompanyCSRPreference:
    """
    Retrieve the CompanyCSRPreference for the authenticated company user.
    """
    company = get_company_for_user(user)
    preference, _ = CompanyCSRPreference.objects.get_or_create(company=company)
    return preference


def update_company_preferences(user, data: Dict[str, Any]) -> CompanyCSRPreference:
    """
    Update CSR matchmaking filter preferences for the corporate user.
    """
    company = get_company_for_user(user)
    preference, _ = CompanyCSRPreference.objects.get_or_create(company=company)

    sanitized_data = {
        k: v for k, v in data.items()
        if k in {
            'preferred_categories', 'preferred_states', 'preferred_districts',
            'is_nationwide', 'has_no_location_pref', 'min_budget', 'max_budget',
            'preferred_duration_months', 'preferred_beneficiaries',
        }
    }

    min_b = sanitized_data.get('min_budget', preference.min_budget)
    max_b = sanitized_data.get('max_budget', preference.max_budget)
    if min_b is not None and max_b is not None:
        min_dec = Decimal(str(min_b))
        max_dec = Decimal(str(max_b))
        if min_dec > 0 and max_dec > 0 and min_dec > max_dec:
            raise CSRValidationError(
                "min_budget cannot exceed max_budget.",
                code="invalid_budget_range",
            )

    for field, val in sanitized_data.items():
        setattr(preference, field, val)

    # Validate list types if provided
    for list_field in ['preferred_categories', 'preferred_states', 'preferred_districts', 'preferred_beneficiaries']:
        val = getattr(preference, list_field)
        if val is not None and not isinstance(val, list):
            raise CSRValidationError(f"{list_field} must be a list.", code="invalid_list_type")

    preference.full_clean(exclude=['company', 'preferred_categories', 'preferred_states', 'preferred_districts', 'preferred_beneficiaries'])
    preference.save()
    return preference
