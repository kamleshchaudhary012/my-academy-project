import os
import re
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# ===========================================================================
# Upload Path Generators (Private Media Storage)
# ===========================================================================

def company_verification_doc_path(instance, filename):
    """Stores company verification document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/companies/{instance.id}/{uuid.uuid4().hex}{ext}'


def requirement_proposal_doc_path(instance, filename):
    """Stores CSR requirement proposal document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/proposals/{instance.id}/{uuid.uuid4().hex}{ext}'


def requirement_budget_doc_path(instance, filename):
    """Stores CSR requirement budget document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/budgets/{instance.id}/{uuid.uuid4().hex}{ext}'


def requirement_impact_doc_path(instance, filename):
    """Stores CSR requirement impact assessment report in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/impact/{instance.id}/{uuid.uuid4().hex}{ext}'


def partnership_mou_doc_path(instance, filename):
    """Stores signed bilateral partnership MoU in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/mous/{instance.id}/{uuid.uuid4().hex}{ext}'


def milestone_evidence_doc_path(instance, filename):
    """Stores partnership milestone evidence document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/milestones/{instance.id}/{uuid.uuid4().hex}{ext}'


def disbursement_evidence_doc_path(instance, filename):
    """Stores bank transfer proof in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/disbursements/{instance.id}/{uuid.uuid4().hex}{ext}'


def disbursement_ack_doc_path(instance, filename):
    """Stores NGO official receipt acknowledgement document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/acknowledgements/{instance.id}/{uuid.uuid4().hex}{ext}'


def expense_invoice_doc_path(instance, filename):
    """Stores NGO expense invoice / bill document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/expenses/{instance.id}/{uuid.uuid4().hex}{ext}'


def grant_change_doc_path(instance, filename):
    """Stores CSR grant change / revised budget document in private media path."""
    ext = os.path.splitext(filename)[1].lower()
    return f'csr_docs/change_requests/{instance.id}/{uuid.uuid4().hex}{ext}'


payment_evidence_doc_path = disbursement_evidence_doc_path
receipt_ack_doc_path = disbursement_ack_doc_path




# ===========================================================================
# Model Validators
# ===========================================================================

def validate_cin_number(value):
    """Validates MCA Corporate Identification Number (CIN) format."""
    if value:
        pattern = r'^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
        if not re.match(pattern, value):
            raise ValidationError(
                _('Invalid CIN format. Expected 21-character MCA standard (e.g. L12345MH2020PLC123456).'),
            )


def validate_pan_number(value):
    """Validates Indian Income Tax PAN format."""
    if value:
        pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
        if not re.match(pattern, value):
            raise ValidationError(
                _('Invalid PAN number format. Expected 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F).'),
            )


def validate_pincode(value):
    """Validates 6-digit Indian postal PIN code."""
    if value:
        if not re.match(r'^\d{6}$', value):
            raise ValidationError(_('Pincode must be exactly 6 digits.'))


def validate_phone(value):
    """Validates contact phone number format (7–20 chars)."""
    if value:
        if not re.match(r'^[\+\d\s\-]{7,20}$', value):
            raise ValidationError(_('Enter a valid phone number (7–20 digits/characters).'))


DANGEROUS_FILE_SIGNATURES = (
    b'MZ',           # Windows PE executable / DLL
    b'\x7fELF',      # Linux ELF executable
    b'<?php',        # PHP script
    b'<script',      # HTML/JS script
    b'#!/bin/',      # Unix shell script
    b'#!/usr/bin/',  # Unix shell script
)


def validate_document_extension(value):
    """Allows safe document extensions: .pdf, .jpg, .jpeg, .png and blocks disguised executables."""
    if value:
        ext = os.path.splitext(value.name)[1].lower()
        allowed = ['.pdf', '.jpg', '.jpeg', '.png']
        if ext not in allowed:
            raise ValidationError(
                _('Unsupported file format. Allowed formats: .pdf, .jpg, .jpeg, .png'),
            )

        file_size = getattr(value, 'size', None)
        if file_size and file_size > 15 * 1024 * 1024:
            raise ValidationError(
                _('Document size exceeds maximum allowed limit of 15 MB.'),
            )

        if hasattr(value, 'read') and hasattr(value, 'seek'):
            try:
                pos = value.tell()
            except Exception:
                pos = 0
            value.seek(0)
            header = value.read(16)
            value.seek(pos)
            if any(header.startswith(sig) for sig in DANGEROUS_FILE_SIGNATURES):
                raise ValidationError(
                    _('File contains executable or script content which is not permitted.'),
                )


# ===========================================================================
# Choices / Enums
# ===========================================================================

class GovCheckStatus(models.TextChoices):
    GOVERNMENT_CHECK_PENDING      = 'GOVERNMENT_CHECK_PENDING',      _('Government Check Pending')
    GOVERNMENT_CHECK_PASSED       = 'GOVERNMENT_CHECK_PASSED',       _('Government Check Passed')
    GOVERNMENT_CHECK_FAILED       = 'GOVERNMENT_CHECK_FAILED',       _('Government Check Failed')
    MANUAL_VERIFICATION_REQUIRED  = 'MANUAL_VERIFICATION_REQUIRED',  _('Manual Verification Required')
    GOVERNMENT_SOURCE_UNAVAILABLE = 'GOVERNMENT_SOURCE_UNAVAILABLE', _('Government Source Unavailable')


class CompanyVerificationStatus(models.TextChoices):
    DRAFT                = 'DRAFT', _('Draft Profile')
    PENDING_VERIFICATION = 'PENDING_VERIFICATION', _('Pending Verification')
    CORRECTION_REQUIRED  = 'CORRECTION_REQUIRED', _('Correction Required')
    APPROVED             = 'APPROVED', _('Approved / Verified')
    REJECTED             = 'REJECTED', _('Rejected')
    SUSPENDED            = 'SUSPENDED', _('Suspended')


class ScheduleVIICategory(models.TextChoices):
    ERADICATING_HUNGER             = 'ERADICATING_HUNGER', _('Eradicating Hunger, Poverty & Malnutrition')
    PROMOTING_EDUCATION            = 'PROMOTING_EDUCATION', _('Promoting Education & Special Education')
    GENDER_EQUALITY                = 'GENDER_EQUALITY', _('Gender Equality & Women Empowerment')
    ENVIRONMENTAL_SUSTAINABILITY   = 'ENVIRONMENTAL_SUSTAINABILITY', _('Environmental Sustainability & Ecological Balance')
    NATIONAL_HERITAGE              = 'NATIONAL_HERITAGE', _('Protection of National Heritage, Art & Culture')
    ARMED_FORCES_VETERANS          = 'ARMED_FORCES_VETERANS', _('Armed Forces Veterans & War Widows Measures')
    RURAL_SPORTS                   = 'RURAL_SPORTS', _('Training to Promote Rural & Nationally Recognized Sports')
    PM_NATIONAL_RELIEF             = 'PM_NATIONAL_RELIEF', _('Prime Minister National Relief Fund & Other Funds')
    TECHNOLOGY_INCUBATORS          = 'TECHNOLOGY_INCUBATORS', _('Technology Incubators & Academic R&D')
    RURAL_DEVELOPMENT              = 'RURAL_DEVELOPMENT', _('Rural Development Projects')
    SLUM_DEVELOPMENT               = 'SLUM_DEVELOPMENT', _('Slum Area Development')
    DISASTER_MANAGEMENT            = 'DISASTER_MANAGEMENT', _('Disaster Management, Relief & Rehabilitation')


class LocationScope(models.TextChoices):
    SPECIFIC_DISTRICT     = 'SPECIFIC_DISTRICT', _('District / Local Block')
    MULTI_DISTRICT        = 'MULTI_DISTRICT', _('Multiple Districts / State-wide')
    NATIONWIDE            = 'NATIONWIDE', _('Pan-India / Multi-State')
    ASPIRATIONAL_DISTRICT = 'ASPIRATIONAL_DISTRICT', _('NITI Aayog Aspirational District')


class BeneficiaryDemographic(models.TextChoices):
    CHILDREN_EDUCATION     = 'CHILDREN_EDUCATION', _('Children & Primary Education')
    WOMEN_EMPOWERMENT      = 'WOMEN_EMPOWERMENT', _('Women Empowerment & Maternal Health')
    RURAL_COMMUNITIES      = 'RURAL_COMMUNITIES', _('Rural Communities & Farmers')
    YOUTH_SKILLING         = 'YOUTH_SKILLING', _('Youth Skilling & Livelihoods')
    HEALTHCARE_PATIENTS    = 'HEALTHCARE_PATIENTS', _('Healthcare & Critical Patients')
    SPECIALLY_ABLED        = 'SPECIALLY_ABLED', _('Persons with Disabilities (PwD)')
    ELDERLY_CARE           = 'ELDERLY_CARE', _('Elderly & Senior Citizens')
    ENVIRONMENTAL_HABITATS = 'ENVIRONMENTAL_HABITATS', _('Ecological & Environmental Habitats')
    DISASTER_AFFECTED      = 'DISASTER_AFFECTED', _('Disaster Affected Populations')


class CSRRequirementStatus(models.TextChoices):
    DRAFT          = 'DRAFT', _('Draft Proposal')
    PENDING_REVIEW = 'PENDING_REVIEW', _('Pending Admin Review')
    APPROVED       = 'APPROVED', _('Approved by Admin')
    OPEN_FOR_CSR   = 'OPEN_FOR_CSR', _('Open for CSR Matching & Inquiries')
    PARTNERED      = 'PARTNERED', _('Fully Partnered / Funded')
    IN_EXECUTION   = 'IN_EXECUTION', _('In Ground Execution')
    COMPLETED      = 'COMPLETED', _('Completed & Verified')
    REJECTED       = 'REJECTED', _('Rejected by Admin')
    SUSPENDED      = 'SUSPENDED', _('Suspended by Admin')


class CSRSupportType(models.TextChoices):
    FINANCIAL_GRANT   = 'FINANCIAL_GRANT', _('Financial CSR Grant')
    EQUIPMENT_SUPPORT = 'EQUIPMENT_SUPPORT', _('Equipment / Infrastructure Support')
    CO_FUNDING        = 'CO_FUNDING', _('Co-Funding Consortium')


class CSRSupportRequestStatus(models.TextChoices):
    PENDING_NGO_REVIEW = 'PENDING_NGO_REVIEW', _('Pending NGO Review')
    ACCEPTED           = 'ACCEPTED', _('Accepted')
    REJECTED           = 'REJECTED', _('Rejected')
    WITHDRAWN          = 'WITHDRAWN', _('Withdrawn by Company')
    EXPIRED            = 'EXPIRED', _('Expired')


class CSRPartnershipStatus(models.TextChoices):
    PENDING_MOU = 'PENDING_MOU', _('Pending MoU Execution')
    ACTIVE      = 'ACTIVE', _('Active / In Ground Execution')
    PAUSED      = 'PAUSED', _('Paused / Clarification Pending')
    COMPLETED   = 'COMPLETED', _('Completed & Verified')
    CANCELLED   = 'CANCELLED', _('Cancelled Prior to Execution')
    TERMINATED  = 'TERMINATED', _('Terminated / Contractual Breach')


class MilestoneStatus(models.TextChoices):
    PENDING            = 'PENDING', _('Pending Execution')
    SUBMITTED          = 'SUBMITTED', _('Submitted for Review')
    VERIFIED           = 'VERIFIED', _('Verified / Completed')
    REVISION_REQUESTED = 'REVISION_REQUESTED', _('Revision Requested')


class CSRAuditEntityType(models.TextChoices):
    COMPANY      = 'COMPANY', _('Company Profile')
    REQUIREMENT  = 'REQUIREMENT', _('CSR Requirement')
    PARTNERSHIP  = 'PARTNERSHIP', _('CSR Partnership')
    MILESTONE    = 'MILESTONE', _('Partnership Milestone')
    DISBURSEMENT = 'DISBURSEMENT', _('CSR Disbursement')
    EXPENSE      = 'EXPENSE', _('CSR Project Expense')



class CSRFinancialStatus(models.TextChoices):
    NOT_DISBURSED                = 'NOT_DISBURSED', _('Not Disbursed / Awaiting Initial Payment')
    PARTIALLY_DISBURSED          = 'PARTIALLY_DISBURSED', _('Partially Disbursed')
    DISBURSEMENT_REPORTED        = 'DISBURSEMENT_REPORTED', _('Disbursement Reported (Pending Evidence Review)')
    AWAITING_EVIDENCE            = 'AWAITING_EVIDENCE', _('Awaiting Transfer Evidence')
    AWAITING_NGO_ACKNOWLEDGEMENT = 'AWAITING_NGO_ACKNOWLEDGEMENT', _('Awaiting NGO Acknowledgement')
    DISPUTED                     = 'DISPUTED', _('Payment Disputed by NGO')
    OVERDUE                      = 'OVERDUE', _('Payment Overdue')
    PENDING_RECONCILIATION       = 'PENDING_RECONCILIATION', _('Pending Final Reconciliation')
    RECONCILED                   = 'RECONCILED', _('Financially Reconciled')


class CSRGrantChangeStatus(models.TextChoices):
    PENDING_ADMIN_REVIEW     = 'PENDING_ADMIN_REVIEW', _('Pending Admin Review')
    PENDING_COMPANY_APPROVAL = 'PENDING_COMPANY_APPROVAL', _('Pending Corporate Approval')
    APPROVED                 = 'APPROVED', _('Approved & Applied')
    REJECTED                 = 'REJECTED', _('Rejected')


class CSRPaymentMode(models.TextChoices):
    NEFT            = 'NEFT', _('NEFT Wire Transfer')
    RTGS            = 'RTGS', _('RTGS Wire Transfer')
    IMPS            = 'IMPS', _('IMPS Instant Transfer')
    DIRECT_TRANSFER = 'DIRECT_TRANSFER', _('Direct Corporate Bank Transfer')
    CHEQUE          = 'CHEQUE', _('Cheque / Demand Draft')


class CSRDisbursementReviewStatus(models.TextChoices):
    PENDING_REVIEW = 'PENDING_REVIEW', _('Pending Review')
    VERIFIED       = 'VERIFIED', _('Verified by Reviewer')
    REJECTED       = 'REJECTED', _('Rejected / Incomplete Evidence')


class CSRNgoAcknowledgementStatus(models.TextChoices):
    PENDING_ACKNOWLEDGEMENT = 'PENDING_ACKNOWLEDGEMENT', _('Pending NGO Acknowledgement')
    ACKNOWLEDGED            = 'ACKNOWLEDGED', _('Acknowledged as Received')
    DISPUTED                = 'DISPUTED', _('Disputed / Funds Not Credited')


class CSRExpenseCategory(models.TextChoices):
    EQUIPMENT   = 'EQUIPMENT', _('Equipment & Infrastructure')
    MATERIAL    = 'MATERIAL', _('Relief & Project Materials')
    LOGISTICS   = 'LOGISTICS', _('Logistics & Distribution')
    PERSONNEL   = 'PERSONNEL', _('Field Staff & Direct Honoraria')
    OPERATIONAL = 'OPERATIONAL', _('Operational & Project Execution')
    OTHER       = 'OTHER', _('Other Project Expenditure')


class CSRExpenseReviewStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', _('Submitted for Review')
    VERIFIED  = 'VERIFIED', _('Verified & Approved')
    REJECTED  = 'REJECTED', _('Rejected / Inadmissible')




# ===========================================================================
# Model 1: CompanyProfile
# ===========================================================================

class CompanyProfile(models.Model):
    """
    Corporate entity verification and statutory profile.
    Links 1:1 with User (role='COMPANY').
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='company_profile',
        help_text=_('Associated user account for this corporate profile.'),
    )
    company_name = models.CharField(max_length=255, db_index=True)
    legal_name = models.CharField(max_length=255)
    cin_number = models.CharField(
        max_length=21,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[validate_cin_number],
        help_text=_('Corporate Identification Number (MCA format: L/U + 5 digits + 2 letters + 4 digits + 3 letters + 6 digits).'),
    )
    pan_number = models.CharField(
        max_length=10,
        db_index=True,
        validators=[validate_pan_number],
        help_text=_('Corporate Income Tax PAN (5 letters, 4 digits, 1 letter).'),
    )
    csr_registration_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text=_('Form CSR-1 registration number (conditional: applies only if registered Foundation/Implementing agency).'),
    )
    contact_person_name = models.CharField(max_length=255)
    contact_person_designation = models.CharField(max_length=100)
    contact_email = models.EmailField(max_length=254, db_index=True)
    contact_phone = models.CharField(max_length=20, validators=[validate_phone])
    official_website = models.URLField(max_length=255, null=True, blank=True)
    registered_address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, db_index=True)
    pincode = models.CharField(max_length=10, validators=[validate_pincode])
    annual_csr_budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_('Estimated annual CSR budget outlay for matchmaking guidance.'),
    )
    verification_status = models.CharField(
        max_length=30,
        choices=CompanyVerificationStatus.choices,
        default=CompanyVerificationStatus.DRAFT,
        db_index=True,
    )
    verification_document = models.FileField(
        upload_to=company_verification_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
        help_text=_('Certificate of Incorporation or Corporate Authorization Proof (PDF/Image).'),
    )
    # Government / External API Verification State
    gov_check_status = models.CharField(
        max_length=40,
        choices=GovCheckStatus.choices,
        default=GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
        db_index=True,
        help_text=_('Automated or manual government identifier verification outcome.'),
    )
    gov_check_source = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text=_('Source of government check (e.g. MCA_21_CIN, ITD_PAN, MANUAL_INSPECTION).'),
    )
    gov_check_details = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Safe details of government check result, match details, and timestamps.'),
    )
    gov_check_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when government or manual check completed.'),
    )
    admin_notes = models.TextField(
        blank=True,
        default='',
        help_text=_('Internal admin notes for corporate verification.'),
    )
    correction_instructions = models.TextField(
        blank=True,
        default='',
        help_text=_('Instructions for corporate user on what to correct. Visible to company.'),
    )
    rejection_reason = models.TextField(null=True, blank=True)
    suspension_reason = models.TextField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_companies',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_companyprofile'
        verbose_name = _('Company Profile')
        verbose_name_plural = _('Company Profiles')
        indexes = [
            models.Index(fields=['verification_status'], name='idx_csr_comp_status'),
            models.Index(fields=['cin_number'], name='idx_csr_comp_cin'),
        ]

    def __str__(self):
        return f"{self.company_name} ({self.verification_status})"

    @property
    def is_active(self):
        """
        Determines if company profile is active and eligible for dashboard access.
        Allows explicit override or checks verification status against suspension/rejection.
        """
        if hasattr(self, '_is_active_override'):
            return self._is_active_override
        return self.verification_status not in (
            CompanyVerificationStatus.SUSPENDED,
            CompanyVerificationStatus.REJECTED,
        )

    @is_active.setter
    def is_active(self, value):
        self._is_active_override = bool(value)


# ===========================================================================
# Model 2: CompanyCSRPreference
# ===========================================================================

class CompanyCSRPreference(models.Model):
    """
    Corporate CSR matchmaking filter preferences.
    Links 1:1 with CompanyProfile.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.OneToOneField(
        CompanyProfile,
        on_delete=models.CASCADE,
        related_name='csr_preferences',
    )
    preferred_categories = models.JSONField(
        default=list,
        help_text=_('List of preferred Schedule VII category keys.'),
    )
    preferred_states = models.JSONField(
        default=list,
        help_text=_('List of preferred state names.'),
    )
    preferred_districts = models.JSONField(
        default=list,
        help_text=_('List of preferred district names.'),
    )
    is_nationwide = models.BooleanField(
        default=False,
        help_text=_('Flag indicating corporate willingness to support initiatives across all Indian states.'),
    )
    has_no_location_pref = models.BooleanField(
        default=False,
        help_text=_('Flag indicating no geographical preference/constraint.'),
    )
    min_budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    max_budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    preferred_duration_months = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_('Preferred project duration in months (optional).'),
    )
    preferred_beneficiaries = models.JSONField(
        default=list,
        help_text=_('List of targeted beneficiary demographic keys.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_companycsrpreference'
        verbose_name = _('Company CSR Preference')
        verbose_name_plural = _('Company CSR Preferences')

    def __str__(self):
        return f"CSR Preferences for {self.company.company_name}"


# ===========================================================================
# Model 3: CSRRequirement
# ===========================================================================

class CSRRequirement(models.Model):
    """
    Itemized project proposal authored by an approved NGO under Schedule VII.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.ForeignKey(
        'ngo.NGOProfile',
        on_delete=models.PROTECT,
        related_name='csr_requirements',
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_csr_requirements',
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    schedule_vii_category = models.CharField(
        max_length=50,
        choices=ScheduleVIICategory.choices,
        db_index=True,
    )
    state = models.CharField(max_length=100, db_index=True)
    district = models.CharField(max_length=100, db_index=True)
    location_scope = models.CharField(
        max_length=30,
        choices=LocationScope.choices,
        default=LocationScope.SPECIFIC_DISTRICT,
    )
    additional_districts = models.JSONField(
        default=list,
        blank=True,
        help_text=_('List of additional project districts for multi-district scope.'),
    )
    beneficiary_demographic = models.CharField(
        max_length=50,
        choices=BeneficiaryDemographic.choices,
        db_index=True,
    )
    target_beneficiary_count = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    summary = models.CharField(max_length=500)
    detailed_description = models.TextField()
    expected_outcomes = models.TextField()
    total_estimated_budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('10000.00'))],
    )
    required_csr_funding = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('10000.00'))],
    )
    committed_funding = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    start_date = models.DateField()
    expected_completion_date = models.DateField()
    status = models.CharField(
        max_length=30,
        choices=CSRRequirementStatus.choices,
        default=CSRRequirementStatus.DRAFT,
        db_index=True,
    )
    proposal_document = models.FileField(
        upload_to=requirement_proposal_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
    )
    detailed_budget_document = models.FileField(
        upload_to=requirement_budget_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
    )
    impact_assessment_report = models.FileField(
        upload_to=requirement_impact_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_csr_requirements',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_csrrequirement'
        verbose_name = _('CSR Requirement')
        verbose_name_plural = _('CSR Requirements')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expected_completion_date__gte=models.F('start_date')),
                name='check_csr_requirement_dates_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(total_estimated_budget__gte=Decimal('10000.00')),
                name='check_csr_requirement_budget_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(required_csr_funding__gte=Decimal('10000.00')),
                name='check_csr_required_funding_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(committed_funding__gte=Decimal('0.00')),
                name='check_csr_committed_funding_non_negative',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'schedule_vii_category'], name='idx_csr_req_status_cat'),
            models.Index(fields=['status', 'state'], name='idx_csr_req_status_state'),
            models.Index(fields=['status', 'beneficiary_demographic'], name='idx_csr_req_status_demog'),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"


# ===========================================================================
# Model 4: CSRSupportRequest
# ===========================================================================

class CSRSupportRequest(models.Model):
    """
    Corporate expression of interest / grant proposal for a CSRRequirement.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        CompanyProfile,
        on_delete=models.PROTECT,
        related_name='support_requests',
        db_index=True,
    )
    requirement = models.ForeignKey(
        CSRRequirement,
        on_delete=models.PROTECT,
        related_name='support_requests',
        db_index=True,
    )
    company_name_snapshot = models.CharField(max_length=255)
    spoc_name = models.CharField(max_length=255)
    spoc_email = models.EmailField(max_length=254)
    spoc_phone = models.CharField(max_length=20, null=True, blank=True, validators=[validate_phone])
    proposed_funding = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1000.00'))],
    )
    support_type = models.CharField(
        max_length=30,
        choices=CSRSupportType.choices,
        default=CSRSupportType.FINANCIAL_GRANT,
    )
    message = models.TextField()
    status = models.CharField(
        max_length=30,
        choices=CSRSupportRequestStatus.choices,
        default=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        db_index=True,
    )
    rejection_reason = models.TextField(null=True, blank=True)
    withdrawal_reason = models.TextField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_support_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_csrsupportrequest'
        verbose_name = _('CSR Support Request')
        verbose_name_plural = _('CSR Support Requests')
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'requirement'],
                condition=models.Q(status='PENDING_NGO_REVIEW'),
                name='unique_pending_csr_support_request',
            ),
            models.CheckConstraint(
                condition=models.Q(proposed_funding__gte=Decimal('1000.00')),
                name='check_csr_proposed_funding_positive',
            ),
        ]
        indexes = [
            models.Index(fields=['requirement', 'status'], name='idx_csr_req_inbox'),
            models.Index(fields=['company', 'status'], name='idx_csr_comp_outbox'),
        ]

    def __str__(self):
        return f"Support Request from {self.company_name_snapshot} ({self.status})"


# ===========================================================================
# Model 5: CSRPartnership
# ===========================================================================

class CSRPartnership(models.Model):
    """
    Formal bilateral corporate-NGO engagement & MoU tracking record.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        CompanyProfile,
        on_delete=models.PROTECT,
        related_name='partnerships',
        db_index=True,
    )
    ngo = models.ForeignKey(
        'ngo.NGOProfile',
        on_delete=models.PROTECT,
        related_name='csr_partnerships',
        db_index=True,
    )
    requirement = models.ForeignKey(
        CSRRequirement,
        on_delete=models.PROTECT,
        related_name='partnerships',
        db_index=True,
    )
    support_request = models.OneToOneField(
        CSRSupportRequest,
        on_delete=models.PROTECT,
        related_name='partnership',
    )
    partnership_code = models.CharField(max_length=50, unique=True, db_index=True)
    agreed_funding_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1000.00'))],
    )
    disbursed_amount_reported = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_('Informational reported total of off-platform corporate bank disbursements.'),
    )
    execution_start_date = models.DateField()
    target_completion_date = models.DateField()
    actual_completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=30,
        choices=CSRPartnershipStatus.choices,
        default=CSRPartnershipStatus.PENDING_MOU,
        db_index=True,
    )
    signed_mou_document = models.FileField(
        upload_to=partnership_mou_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'csr_csrpartnership'
        verbose_name = _('CSR Partnership')
        verbose_name_plural = _('CSR Partnerships')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(target_completion_date__gte=models.F('execution_start_date')),
                name='check_csr_partnership_dates_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(agreed_funding_amount__gte=Decimal('1000.00')),
                name='check_csr_agreed_funding_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(disbursed_amount_reported__gte=Decimal('0.00')),
                name='check_csr_disbursed_funding_non_negative',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'status'], name='idx_csr_pt_comp_status'),
            models.Index(fields=['ngo', 'status'], name='idx_csr_pt_ngo_status'),
        ]

    def __str__(self):
        return f"Partnership {self.partnership_code} ({self.status})"


# ===========================================================================
# Model 6: PartnershipMilestone
# ===========================================================================

class PartnershipMilestone(models.Model):
    """
    Sequenced deliverable deliverable and progress verification record for a CSRPartnership.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partnership = models.ForeignKey(
        CSRPartnership,
        on_delete=models.CASCADE,
        related_name='milestones',
        db_index=True,
    )
    sequence_number = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    target_completion_date = models.DateField()
    actual_completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=30,
        choices=MilestoneStatus.choices,
        default=MilestoneStatus.PENDING,
        db_index=True,
    )
    evidence_document = models.FileField(
        upload_to=milestone_evidence_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
    )
    evidence_notes = models.TextField(null=True, blank=True)
    completion_percentage = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_milestones',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_partnershipmilestone'
        verbose_name = _('Partnership Milestone')
        verbose_name_plural = _('Partnership Milestones')
        ordering = ['partnership', 'sequence_number', 'target_completion_date']
        constraints = [
            models.UniqueConstraint(
                fields=['partnership', 'sequence_number'],
                name='unique_partnership_milestone_sequence',
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_number__gte=1),
                name='check_csr_milestone_sequence_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(completion_percentage__lte=100),
                name='check_csr_milestone_completion_pct',
            ),
        ]
        indexes = [
            models.Index(fields=['partnership', 'sequence_number'], name='idx_csr_ms_pt_seq'),
        ]

    def __str__(self):
        return f"Milestone #{self.sequence_number}: {self.title} ({self.status})"


# ===========================================================================
# Model 7: CSRVerificationHistory (Audit Ledger)
# ===========================================================================

class CSRVerificationHistory(models.Model):
    """
    Immutable audit ledger for administrative decisions across CSR domain entities.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(
        max_length=30,
        choices=CSRAuditEntityType.choices,
        db_index=True,
    )
    entity_id = models.UUIDField(db_index=True)
    old_status = models.CharField(max_length=50, null=True, blank=True)
    new_status = models.CharField(max_length=50)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='csr_audit_actions',
    )
    review_notes = models.TextField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict,
        help_text=_('Contextual snapshot dictionary for audit diff tracking.'),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'csr_csrverificationhistory'
        verbose_name = _('CSR Verification History')
        verbose_name_plural = _('CSR Verification Histories')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id', 'created_at'], name='idx_csr_audit_entity'),
        ]

    def __str__(self):
        return f"Audit: {self.entity_type} {self.entity_id} -> {self.new_status} at {self.created_at}"


# ===========================================================================
# Model 8: CSRDisbursement (Off-Platform Corporate Wire Disbursement)
# ===========================================================================

class CSRDisbursement(models.Model):
    """
    Itemized off-platform corporate bank transfer disbursement record.
    Tracks UTR / wire references, supporting transfer receipts, and verification decisions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partnership = models.ForeignKey(
        CSRPartnership,
        on_delete=models.CASCADE,
        related_name='disbursements',
        db_index=True,
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reported_csr_disbursements',
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        help_text=_('Reported tranche disbursement amount in INR.'),
    )
    currency = models.CharField(max_length=3, default='INR')
    disbursement_date = models.DateField(
        default=timezone.now,
        help_text=_('Date when corporate bank wire / transfer was initiated.'),
    )
    transfer_reference = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text=_('Bank UTR or transaction reference number.'),
    )
    payment_mode = models.CharField(
        max_length=30,
        choices=CSRPaymentMode.choices,
        default=CSRPaymentMode.NEFT,
    )
    evidence_document = models.FileField(
        upload_to=disbursement_evidence_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
        help_text=_('Bank transfer receipt / wire advice document.'),
    )
    notes = models.TextField(blank=True, default='')
    review_status = models.CharField(
        max_length=30,
        choices=CSRDisbursementReviewStatus.choices,
        default=CSRDisbursementReviewStatus.PENDING_REVIEW,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_csr_disbursements',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default='')
    ngo_acknowledgement_status = models.CharField(
        max_length=30,
        choices=CSRNgoAcknowledgementStatus.choices,
        default=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT,
        db_index=True,
    )
    ngo_acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_csr_disbursements',
    )
    ngo_acknowledged_at = models.DateTimeField(null=True, blank=True)
    ngo_acknowledgement_notes = models.TextField(blank=True, default='')
    ngo_receipt_document = models.FileField(
        upload_to=disbursement_ack_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
        help_text=_('Formal NGO donation receipt or bank credit confirmation slip.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_csrdisbursement'
        verbose_name = _('CSR Disbursement')
        verbose_name_plural = _('CSR Disbursements')
        ordering = ['-disbursement_date', '-created_at']
        indexes = [
            models.Index(fields=['partnership', 'review_status'], name='idx_csr_disb_pt_rev'),
            models.Index(fields=['partnership', 'ngo_acknowledgement_status'], name='idx_csr_disb_pt_ack'),
        ]

    def __str__(self):
        return f"Disbursement ₹{self.amount} ({self.transfer_reference}) - {self.review_status}"


# ===========================================================================
# Model 9: CSRExpense (NGO Ground Project Expenditure Tracking)
# ===========================================================================

class CSRExpense(models.Model):
    """
    Itemized ground project expenditure reported by NGO against a CSR Partnership.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partnership = models.ForeignKey(
        CSRPartnership,
        on_delete=models.CASCADE,
        related_name='expenses',
        db_index=True,
    )
    milestone = models.ForeignKey(
        PartnershipMilestone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses',
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reported_csr_expenses',
    )
    expense_category = models.CharField(
        max_length=30,
        choices=CSRExpenseCategory.choices,
        default=CSRExpenseCategory.OPERATIONAL,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
    )
    currency = models.CharField(max_length=3, default='INR')
    expense_date = models.DateField(default=timezone.now)
    vendor_payee = models.CharField(max_length=255, blank=True, default='')
    invoice_number = models.CharField(max_length=100, blank=True, default='')
    invoice_document = models.FileField(
        upload_to=expense_invoice_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
        help_text=_('Invoice / Bill / Voucher receipt document.'),
    )
    review_status = models.CharField(
        max_length=30,
        choices=CSRExpenseReviewStatus.choices,
        default=CSRExpenseReviewStatus.SUBMITTED,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_csr_expenses',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_csrexpense'
        verbose_name = _('CSR Project Expense')
        verbose_name_plural = _('CSR Project Expenses')
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['partnership', 'review_status'], name='idx_csr_exp_pt_rev'),
        ]

    def __str__(self):
        return f"Expense ₹{self.amount} ({self.title}) - {self.review_status}"


# Aliases for compatibility
CSRPaymentReport = CSRDisbursement
CSRExpenseReport = CSRExpense


# ===========================================================================
# Model 10: CSRGrantChangeRequest (Controlled Bilateral Budget Amendment)
# ===========================================================================

class CSRGrantChangeRequest(models.Model):
    """
    Controlled bilateral grant amendment workflow to prevent silent grant increases.
    Requires Admin eligibility review and explicit Corporate Partner approval before
    the approved partnership commitment is updated.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partnership = models.ForeignKey(
        CSRPartnership,
        on_delete=models.CASCADE,
        related_name='grant_change_requests',
        db_index=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_grant_changes',
    )
    current_commitment = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1000.00'))],
    )
    proposed_commitment = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1000.00'))],
    )
    reason = models.TextField()
    revised_budget_document = models.FileField(
        upload_to=grant_change_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
        help_text=_('Itemized revised budget document or rationale breakdown.'),
    )
    mou_amendment_document = models.FileField(
        upload_to=grant_change_doc_path,
        null=True,
        blank=True,
        validators=[validate_document_extension],
        help_text=_('Formal bilateral MoU addendum / amendment document.'),
    )
    status = models.CharField(
        max_length=30,
        choices=CSRGrantChangeStatus.choices,
        default=CSRGrantChangeStatus.PENDING_ADMIN_REVIEW,
        db_index=True,
    )
    admin_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_reviewed_grant_changes',
    )
    admin_reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_review_notes = models.TextField(blank=True, default='')
    company_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='company_approved_grant_changes',
    )
    company_approved_at = models.DateTimeField(null=True, blank=True)
    company_review_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'csr_grantchangerequest'
        verbose_name = _('CSR Grant Change Request')
        verbose_name_plural = _('CSR Grant Change Requests')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['partnership', 'status'], name='idx_csr_gcr_pt_status'),
        ]

    def __str__(self):
        return f"Grant Change for {self.partnership.partnership_code}: ₹{self.current_commitment} -> ₹{self.proposed_commitment} ({self.status})"



