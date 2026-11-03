"""
DaanGives NGO Submission Service — Phase 3.3.2-F
=================================================
Validates application completeness and executes DRAFT -> SUBMITTED (or CORRECTION_REQUIRED -> SUBMITTED)
status transitions atomically using the core verification service.
"""

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGOLeadership,
    NGODocument,
)
from ngo.services.verification_service import (
    change_ngo_verification_status,
    StatusTransitionError,
    ResubmissionLimitError,
)


class CompletenessError(Exception):
    """Raised when the NGO application is incomplete for submission."""
    def __init__(self, errors):
        self.errors = errors
        super().__init__(_('NGO application is incomplete.'))


class ConflictError(Exception):
    """Raised when the application is already SUBMITTED or UNDER_REVIEW."""
    pass


class LockedStatusError(Exception):
    """Raised when application is in a locked status (APPROVED, REJECTED, SUSPENDED)."""
    pass


def validate_ngo_completeness(profile):
    """
    Validates completeness of an NGO application for submission.
    Returns a dictionary of section errors if incomplete, or an empty dict if complete.
    """
    errors = {}

    # 1. Profile completeness check
    profile_errors = []
    required_profile_fields = [
        ('legal_name', _('Legal name is required.')),
        ('display_name', _('Display name is required.')),
        ('category', _('Category is required.')),
        ('description', _('Description is required.')),
        ('year_established', _('Year established is required.')),
        ('official_email', _('Official email is required.')),
        ('official_phone', _('Official phone is required.')),
    ]
    for field, msg in required_profile_fields:
        if not getattr(profile, field, None):
            profile_errors.append(msg)
    if profile_errors:
        errors['profile'] = profile_errors

    # 2. Address completeness check
    if not hasattr(profile, 'address') or profile.address is None:
        errors['address'] = [_('Registered address is required.')]
    else:
        address = profile.address
        addr_errors = []
        for field, msg in [
            ('address_line1', _('Address line 1 is required.')),
            ('city', _('City is required.')),
            ('district', _('District is required.')),
            ('state', _('State is required.')),
            ('pincode', _('Pincode is required.')),
        ]:
            if not getattr(address, field, None):
                addr_errors.append(msg)
        if addr_errors:
            errors['address'] = addr_errors

    # 3. Legal Info completeness check
    if not hasattr(profile, 'legal_info') or profile.legal_info is None:
        errors['legal_info'] = [_('Legal information is required.')]
    else:
        legal = profile.legal_info
        legal_errors = []
        if not legal.organisation_type:
            legal_errors.append(_('Organisation type is required.'))
        if not legal.pan_number:
            legal_errors.append(_('PAN number is required.'))
        if legal.has_10_23c and not legal.ten_23c_order_number:
            legal_errors.append(_('Section 10(23C) approval order number is required when has_10_23c is True.'))
        if legal.has_12a and not legal.twelve_a_number:
            legal_errors.append(_('12A certificate number is required when has_12a is True.'))
        if legal.has_80g and not legal.eighty_g_number:
            legal_errors.append(_('80G certificate number is required when has_80g is True.'))
        if legal.has_fcra and not legal.fcra_number:
            legal_errors.append(_('FCRA certificate number is required when has_fcra is True.'))
        if legal.has_csr_1 and not legal.csr_registration_number:
            legal_errors.append(_('CSR-1 registration number is required when has_csr_1 is True.'))
        if legal_errors:
            errors['legal_info'] = legal_errors

    # 4. Bank Info completeness check
    if not hasattr(profile, 'bank_info') or profile.bank_info is None:
        errors['bank_info'] = [_('Bank information is required.')]
    else:
        bank = profile.bank_info
        bank_errors = []
        for field, msg in [
            ('account_holder_name', _('Account holder name is required.')),
            ('account_number', _('Account number is required.')),
            ('ifsc_code', _('IFSC code is required.')),
            ('bank_name', _('Bank name is required.')),
            ('account_type', _('Account type is required.')),
        ]:
            if not getattr(bank, field, None):
                bank_errors.append(msg)
        if bank_errors:
            errors['bank_info'] = bank_errors

    # 5. Leadership completeness check
    leaders = list(profile.leadership.filter(is_active=True))
    leader_errors = []
    if not leaders:
        leader_errors.append(_('At least one active trustee or leader is required.'))
    else:
        primary_contacts = [l for l in leaders if l.is_primary_contact]
        if len(primary_contacts) == 0:
            leader_errors.append(_('At least one active primary contact is required.'))
        elif len(primary_contacts) > 1:
            leader_errors.append(_('Only one active primary contact is allowed.'))
    if leader_errors:
        errors['leadership'] = leader_errors

    # 6. Document completeness check
    active_docs = set(
        profile.documents.filter(is_active=True).values_list('document_type', flat=True)
    )
    doc_errors = []
    required_docs = list(NGODocument.REQUIRED_DOCUMENT_TYPES)

    legal = getattr(profile, 'legal_info', None)
    if legal:
        if legal.has_10_23c and NGODocument.DocumentType.TEN_23C_CERT not in required_docs:
            required_docs.append(NGODocument.DocumentType.TEN_23C_CERT)
        if legal.has_12a and NGODocument.DocumentType.TWELVE_A_CERT not in required_docs:
            required_docs.append(NGODocument.DocumentType.TWELVE_A_CERT)
        if legal.has_80g and NGODocument.DocumentType.EIGHTY_G_CERT not in required_docs:
            required_docs.append(NGODocument.DocumentType.EIGHTY_G_CERT)
        if legal.has_fcra and NGODocument.DocumentType.FCRA_CERT not in required_docs:
            required_docs.append(NGODocument.DocumentType.FCRA_CERT)
        if legal.has_csr_1 and NGODocument.DocumentType.CSR_1_CERT not in required_docs:
            required_docs.append(NGODocument.DocumentType.CSR_1_CERT)

    for doc_type in required_docs:
        if doc_type not in active_docs:
            doc_errors.append(_(f'{doc_type} document is required.'))

    if doc_errors:
        errors['documents'] = doc_errors

    return errors


@transaction.atomic
def submit_ngo_application(profile, user):
    """
    Submits an NGO application for review.
    Enforces status precondition, completeness validation, and atomic status transition.
    Triggers automated initial government check step (which sets gov_check_status).
    """
    if profile.status in (NGOProfile.Status.SUBMITTED, NGOProfile.Status.UNDER_REVIEW):
        raise ConflictError(_('NGO application is already submitted or under review.'))

    if profile.status in (
        NGOProfile.Status.APPROVED,
        NGOProfile.Status.REJECTED,
        NGOProfile.Status.SUSPENDED,
    ):
        raise LockedStatusError(_(f'Submission is locked in status {profile.status}.'))

    if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
        raise LockedStatusError(_(f'Submission is not permitted from status {profile.status}.'))

    errors = validate_ngo_completeness(profile)
    if errors:
        raise CompletenessError(errors)

    change_ngo_verification_status(
        ngo_profile=profile,
        new_status=NGOProfile.Status.SUBMITTED,
        changed_by=user,
        reason='NGO owner submitted application for verification.',
    )

    # Initial government verification step
    from ngo.services.government_verification_service import GovernmentVerificationService
    GovernmentVerificationService.run_ngo_government_verification(profile)

    return profile
