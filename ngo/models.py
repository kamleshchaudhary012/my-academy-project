
import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, RegexValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import re

# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_safe_identifier(value):
    if not re.match(r'^[A-Za-z0-9/\-_\s]+$', value):
        raise ValidationError(
            _('%(value)s contains invalid characters. '
              'Only letters, digits, hyphens, slashes, and underscores are allowed.'),
            params={'value': value},
        )


def validate_darpan_id(value):
    if not re.match(r'^[A-Za-z0-9/\-_]+$', value):
        raise ValidationError(
            _('Darpan ID contains invalid characters. '
              'Allowed: letters, digits, hyphens, forward slashes, underscores.'),
        )


def validate_pan_number(value):
    if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', value):
        raise ValidationError(
            _('Invalid PAN number format. '
              'Expected 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F).'),
        )


def validate_csr_number(value):
    """
    Validates MCA-issued Form CSR-1 CSR Registration Number (CRN).
    Expected format: 'CSR' followed by 7 to 12 digits (e.g. CSR00012345).
    """
    if not value:
        return
    if not re.match(r'^CSR\d{7,12}$', value.strip().upper()):
        raise ValidationError(
            _('Invalid CSR-1 registration number format. Expected format: CSR followed by 7 to 12 digits (e.g. CSR00012345).'),
        )


def validate_account_number(value):
    if not re.match(r'^\d{9,20}$', value):
        raise ValidationError(
            _('Account number must be 9 to 20 numeric digits.'),
        )


def validate_ifsc_code(value):
    if not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', value):
        raise ValidationError(
            _('Invalid IFSC code. Expected format: ABCD0123456 '
              '(4 letters + 0 + 6 alphanumeric).'),
        )


def validate_pincode(value):
    if not re.match(r'^\d{6}$', value):
        raise ValidationError(_('Pincode must be exactly 6 digits.'))


def validate_phone(value):
    if not re.match(r'^[\+\d\s\-]{7,15}$', value):
        raise ValidationError(_('Enter a valid phone number.'))


def validate_year_range(value):
    """Validates year is between 1800 and current year."""
    current_year = timezone.now().year
    if not (1800 <= value <= current_year):
        raise ValidationError(
            _('Year must be between 1800 and %(current)s.'),
            params={'current': current_year},
        )


def validate_image_extension(value):
    """Rejects SVG and unsafe formats. Allows jpg, jpeg, png, webp. Enforces 5MB limit and verifies decoding."""
    from users.image_validators import validate_image_file
    validate_image_file(value)


DANGEROUS_FILE_SIGNATURES = (
    b'MZ',           # Windows PE executable / DLL
    b'\x7fELF',      # Linux ELF executable
    b'<?php',        # PHP script
    b'<script',      # HTML/JS script
    b'#!/bin/',      # Unix shell script
    b'#!/usr/bin/',  # Unix shell script
)


def validate_document_extension(value):
    """Allows pdf, jpg, jpeg, png. Blocks svg, html, js, exe, php, py, sh, xml and disguised executable scripts."""
    import os
    ext = os.path.splitext(value.name)[1].lower()
    allowed = ['.pdf', '.jpg', '.jpeg', '.png']
    if ext not in allowed:
        raise ValidationError(
            _('Unsupported file format. Allowed: .pdf, .jpg, .jpeg, .png'),
        )

    file_size = getattr(value, 'size', None)
    if file_size and file_size > 15 * 1024 * 1024:
        raise ValidationError(
            _('File size exceeds maximum allowed limit of 15 MB.'),
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


# ---------------------------------------------------------------------------
# Upload path functions
# ---------------------------------------------------------------------------

def ngo_logo_path(instance, filename):
    """Stores logo at ngo_logos/{ngo_id}/{uuid}.ext"""
    import os
    ext = os.path.splitext(filename)[1].lower()
    return f'ngo_logos/{instance.id}/{uuid.uuid4()}{ext}'


def ngo_cover_path(instance, filename):
    """Stores cover at ngo_covers/{ngo_id}/{uuid}.ext"""
    import os
    ext = os.path.splitext(filename)[1].lower()
    return f'ngo_covers/{instance.id}/{uuid.uuid4()}{ext}'


def ngo_document_path(instance, filename):
    """
    Stores document at ngo_docs/{ngo_id}/{document_type}/{uuid}.ext
    Original filename is NEVER used as storage path (security).
    """
    import os
    ext = os.path.splitext(filename)[1].lower()
    return f'ngo_docs/{instance.ngo.id}/{instance.document_type}/{uuid.uuid4()}{ext}'


# ---------------------------------------------------------------------------
# Custom Manager and QuerySet for NGOVerificationHistory (immutability)
# ---------------------------------------------------------------------------

class ImmutableRecordError(Exception):
    """Raised when attempting to mutate an immutable audit record."""
    pass


class ImmutableHistoryQuerySet(models.QuerySet):
    """
    Custom QuerySet that prevents UPDATE and DELETE on history records.
    APPLICATION-LEVEL protection.
    Note: PostgreSQL REVOKE UPDATE/DELETE is PLANNED deployment hardening
    and has NOT been applied to the database in this phase.
    """

    def update(self, **kwargs):
        raise ImmutableRecordError(
            'NGOVerificationHistory records are immutable and cannot be updated. '
            'Use change_ngo_verification_status() to create new history records.'
        )

    def delete(self):
        raise ImmutableRecordError(
            'NGOVerificationHistory records are immutable and cannot be deleted.'
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise ImmutableRecordError(
            'NGOVerificationHistory records are immutable and cannot be bulk updated.'
        )


class ImmutableHistoryManager(models.Manager):
    """
    Custom Manager that returns ImmutableHistoryQuerySet and prevents bulk_update.
    """

    def get_queryset(self):
        return ImmutableHistoryQuerySet(self.model, using=self._db)

    def bulk_update(self, objs, fields, batch_size=None):
        raise ImmutableRecordError(
            'NGOVerificationHistory records are immutable and cannot be bulk updated.'
        )


# ---------------------------------------------------------------------------
# MODEL 1: NGOProfile
# ---------------------------------------------------------------------------

class NGOProfile(models.Model):

    class Status(models.TextChoices):
        DRAFT               = 'DRAFT',               _('Draft')
        SUBMITTED           = 'SUBMITTED',            _('Submitted')
        UNDER_REVIEW        = 'UNDER_REVIEW',         _('Under Review')
        CORRECTION_REQUIRED = 'CORRECTION_REQUIRED',  _('Correction Required')
        APPROVED            = 'APPROVED',             _('Approved')
        REJECTED            = 'REJECTED',             _('Rejected')
        SUSPENDED           = 'SUSPENDED',            _('Suspended')

    class Category(models.TextChoices):
        EDUCATION          = 'EDUCATION',          _('Education & Child Welfare')
        HEALTHCARE         = 'HEALTHCARE',          _('Healthcare & Relief')
        ENVIRONMENT        = 'ENVIRONMENT',         _('Environment & Animal Care')
        WOMEN_EMPOWERMENT  = 'WOMEN_EMPOWERMENT',   _('Women Empowerment')
        CHILD_WELFARE      = 'CHILD_WELFARE',       _('Child Welfare')
        DISASTER_RELIEF    = 'DISASTER_RELIEF',     _('Disaster Relief')
        ANIMAL_CARE        = 'ANIMAL_CARE',         _('Animal Care')
        LIVELIHOOD         = 'LIVELIHOOD',          _('Livelihood')
        OTHER              = 'OTHER',               _('Other')

    # Lifecycle consistency: which statuses set is_active=True
    ACTIVE_STATUSES = {Status.APPROVED}

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text=_('Unique identifier. UUID prevents sequential enumeration.'),
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ngo_profile',
        help_text=_('The NGO user account. One user can own exactly one NGO profile.'),
    )
    legal_name = models.CharField(
        max_length=255,
        help_text=_('Legal name as on registration certificate.'),
    )
    display_name = models.CharField(
        max_length=255,
        help_text=_('Public-facing name for the NGO.'),
    )
    gujarati_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_('Optional name in Gujarati or regional language.'),
    )
    slug = models.SlugField(
        max_length=300,
        unique=True,
        db_index=True,
        editable=False,
        help_text=_('URL-safe identifier. Auto-generated from display_name. Never from user input.'),
    )
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        db_index=True,
        help_text=_('Primary operational category of the NGO.'),
    )
    description = models.TextField(
        validators=[MinLengthValidator(50)],
        help_text=_('Public-facing description of the NGO. Minimum 50 characters.'),
    )
    mission_statement = models.TextField(
        blank=True,
        default='',
        help_text=_('Optional mission statement.'),
    )
    year_established = models.PositiveSmallIntegerField(
        validators=[validate_year_range],
        help_text=_('Year the NGO was established (1800 to current year).'),
    )
    website = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text=_('Official website URL. Optional.'),
    )
    official_email = models.EmailField(
        max_length=254,
        help_text=_('Public contact email for the NGO organisation.'),
    )
    official_phone = models.CharField(
        max_length=20,
        validators=[validate_phone],
        help_text=_('Public contact phone number for the NGO organisation.'),
    )
    logo = models.ImageField(
        upload_to=ngo_logo_path,
        null=True,
        blank=True,
        validators=[validate_image_extension],
        help_text=_('NGO logo image. Served publicly only when status=APPROVED.'),
    )
    cover_image = models.ImageField(
        upload_to=ngo_cover_path,
        null=True,
        blank=True,
        validators=[validate_image_extension],
        help_text=_('NGO cover image. Served publicly only when status=APPROVED.'),
    )

    # -----------------------------------------------------------------------
    # Lifecycle fields — NEVER directly user-writable
    # Updated ONLY by change_ngo_verification_status() service
    # -----------------------------------------------------------------------
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        editable=False,
        help_text=_(
            'Authoritative lifecycle state. '
            'NEVER writable by user request. '
            'Updated only by change_ngo_verification_status() service.'
        ),
    )
    is_active = models.BooleanField(
        default=False,
        help_text=_(
            'True only when status=APPROVED. '
            'NEVER directly user-editable. '
            'Updated atomically with status by service.'
        ),
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of APPROVED transition. Set once by service.'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('NGO Profile')
        verbose_name_plural = _('NGO Profiles')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'category'], name='idx_ngoprofile_status_category'),
            models.Index(fields=['status'], name='idx_ngoprofile_status'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(year_established__gte=1800),
                name='chk_ngoprofile_year_min',
            ),
        ]

    def __str__(self):
        return f'{self.display_name} ({self.status})'

    @property
    def is_public(self):
        """
        Public visibility is DERIVED — not stored in the database.
        An NGO is publicly visible if and only if:
            status == APPROVED AND is_active == True
        This eliminates the inconsistent states:
            APPROVED + is_active=False → not public
            SUSPENDED + is_active=True → not public (status check fails)
        """
        return self.status == self.Status.APPROVED and self.is_active

    def clean(self):
        """
        Model-level validation: enforce status/is_active consistency.
        is_active must be True only when status is APPROVED.
        """
        super().clean()
        if self.status == self.Status.APPROVED and not self.is_active:
            raise ValidationError(
                _('is_active must be True when status is APPROVED. '
                  'Use change_ngo_verification_status() to update lifecycle state.')
            )
        if self.status != self.Status.APPROVED and self.is_active:
            raise ValidationError(
                _('is_active must be False for non-APPROVED status. '
                  'Use change_ngo_verification_status() to update lifecycle state.')
            )

    def save(self, *args, **kwargs):
        """
        Auto-generate slug from display_name if not set.
        Slug is never accepted from external input.
        """
        if not self.slug and self.display_name:
            from django.utils.text import slugify
            base_slug = slugify(self.display_name)
            slug = base_slug
            counter = 1
            while NGOProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# MODEL 2: NGOAddress
# ---------------------------------------------------------------------------

class NGOAddress(models.Model):
    """
    Single registered address per NGO.
    No address history required at this stage.
    Separated from NGOProfile for normalization.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.OneToOneField(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='address',
        help_text=_('One address per NGO.'),
    )
    address_line1 = models.CharField(
        max_length=255,
        help_text=_('Street address line 1. NGO+Admin only.'),
    )
    address_line2 = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_('Street address line 2. Optional.'),
    )
    city = models.CharField(
        max_length=100,
        help_text=_('City. Publicly visible.'),
    )
    district = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_('District. Indexed for directory filter. Publicly visible.'),
    )
    state = models.CharField(
        max_length=100,
        default='Gujarat',
        help_text=_('State of registration. Publicly visible.'),
    )
    pincode = models.CharField(
        max_length=6,
        validators=[validate_pincode],
        help_text=_('6-digit postal code. NGO+Admin only.'),
    )
    service_areas = models.TextField(
        blank=True,
        default='',
        help_text=_('Comma-separated districts/areas served. Optional. Publicly visible.'),
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_('Latitude for geolocation. Optional.'),
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_('Longitude for geolocation. Optional.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('NGO Address')
        verbose_name_plural = _('NGO Addresses')

    def __str__(self):
        return f'{self.city}, {self.district}, {self.state}'


# ---------------------------------------------------------------------------
# MODEL 3: NGOLegalInfo
# ---------------------------------------------------------------------------

class NGOLegalInfo(models.Model):
    class OrgType(models.TextChoices):
        TRUST     = 'TRUST',     _('Public/Private Trust')
        SOCIETY   = 'SOCIETY',   _('Registered Society')
        SECTION_8 = 'SECTION_8', _('Section 8 Company')
        NPO       = 'NPO',       _('Not For Profit Organisation')
        OTHER     = 'OTHER',     _('Other')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.OneToOneField(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='legal_info',
    )
    organisation_type = models.CharField(
        max_length=20,
        choices=OrgType.choices,
        help_text=_('Legal form of the organisation. Part of composite registration identity.'),
    )
    registering_authority = models.CharField(
        max_length=200,
        help_text=_(
            'Authority that issued the registration '
            '(e.g. "Charity Commissioner, Gujarat"). '
            'Part of composite registration identity.'
        ),
    )
    registration_number = models.CharField(
        max_length=100,
        validators=[validate_safe_identifier],
        db_index=True,
        help_text=_(
            'Registration number as issued by authority. '
            'Unique only in combination with organisation_type and registering_authority. '
            'Locked once status >= SUBMITTED.'
        ),
    )
    darpan_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        validators=[validate_darpan_id],
        help_text=_(
            'NGO Darpan ID assigned by NITI Aayog. Globally unique. '
            'No format enforced — government-assigned. '
            'Locked once status >= SUBMITTED.'
        ),
    )
    pan_number = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        validators=[validate_pan_number],
        help_text=_(
            'PAN number — normalized uppercase. Globally unique. '
            'NOTE: Stored as plaintext in Phase 3. '
            'Encryption at rest PLANNED for future hardening phase. '
            'Locked once status >= SUBMITTED.'
        ),
    )
    registration_state = models.CharField(
        max_length=100,
        help_text=_('State where the NGO is registered.'),
    )
    chief_trustee_name = models.CharField(
        max_length=255,
        help_text=_('Name of managing trustee or equivalent. NGO+Admin only.'),
    )
    chief_trustee_designation = models.CharField(
        max_length=100,
        help_text=_('Designation of chief trustee (e.g. Managing Trustee). NGO+Admin only.'),
    )

    # 12A
    has_12a = models.BooleanField(
        default=False,
        help_text=_('Whether the NGO holds a 12A certificate. Boolean publicly visible.'),
    )
    twelve_a_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text=_('12A certificate number. Required if has_12a=True. NGO+Admin only.'),
    )
    twelve_a_validity = models.DateField(
        null=True,
        blank=True,
        help_text=_('12A validity expiry date. NGO+Admin only.'),
    )

    # 80G
    has_80g = models.BooleanField(
        default=False,
        help_text=_('Whether the NGO holds an 80G certificate. Boolean publicly visible.'),
    )
    eighty_g_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text=_('80G certificate number. Required if has_80g=True. NGO+Admin only.'),
    )
    eighty_g_validity = models.DateField(
        null=True,
        blank=True,
        help_text=_('80G validity expiry date. NGO+Admin only.'),
    )

    # FCRA
    has_fcra = models.BooleanField(
        default=False,
        help_text=_('Whether the NGO has FCRA approval. Boolean publicly visible.'),
    )
    fcra_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text=_('FCRA registration number. Required if has_fcra=True. NGO+Admin only.'),
    )
    fcra_validity = models.DateField(
        null=True,
        blank=True,
        help_text=_('FCRA validity expiry date. NGO+Admin only.'),
    )

    # Section 10(23C) Exemption (sub-clauses iv, v, vi, or via)
    has_10_23c = models.BooleanField(
        default=False,
        help_text=_('Whether the NGO holds a Section 10(23C) exemption order (sub-clauses iv, v, vi, or via).'),
    )
    ten_23c_subclause = models.CharField(
        max_length=10,
        blank=True,
        default='',
        help_text=_('Sub-clause under Section 10(23C): iv, v, vi, or via. Required if has_10_23c=True.'),
    )
    ten_23c_order_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text=_('Section 10(23C) approval order number / URN. Required if has_10_23c=True.'),
    )
    ten_23c_validity = models.DateField(
        null=True,
        blank=True,
        help_text=_('Section 10(23C) validity expiry date. NGO+Admin only.'),
    )

    # Form CSR-1 / CRN (Ministry of Corporate Affairs)
    has_csr_1 = models.BooleanField(
        default=False,
        help_text=_('Whether the NGO holds an MCA Form CSR-1 registration / CSR Registration Number (CRN).'),
    )
    csr_registration_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        validators=[validate_csr_number],
        help_text=_(
            'Form CSR-1 registration number (CRN) issued by MCA (e.g. CSR00012345). '
            'Required if has_csr_1=True. NGO+Admin only.'
        ),
    )
    csr_registration_date = models.DateField(
        null=True,
        blank=True,
        help_text=_('Date of Form CSR-1 registration with MCA. Optional. NGO+Admin only.'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('NGO Legal Info')
        verbose_name_plural = _('NGO Legal Info Records')
        constraints = [
            models.UniqueConstraint(
                fields=['organisation_type', 'registering_authority', 'registration_number'],
                name='unique_ngo_registration_identity',
            ),
        ]

    def __str__(self):
        return f'{self.ngo.display_name} — {self.darpan_id}'

    @property
    def is_csr_eligible(self):
        """
        Determines statutory baseline eligibility for corporate CSR funding.
        Under MCA Rule 4(1) of Companies (CSR Policy) Rules:
        1. An implementing agency must be a Registered Trust, Society, or Section 8 Company.
        2. Must possess an MCA-issued CSR-1 Registration Number (CRN).
        3. Must hold valid tax exemption: either Section 10(23C) (sub-clauses iv, v, vi, via)
           OR both Section 12A/12AB and Section 80G.
        4. Must possess an established track record of at least 3 years (Rule 4(1)(d)).
        """
        eligible_org_types = {self.OrgType.TRUST, self.OrgType.SOCIETY, self.OrgType.SECTION_8}
        if self.organisation_type not in eligible_org_types:
            return False
        if not (self.has_csr_1 and self.csr_registration_number):
            return False

        # Tax exemption disjunction under Rule 4(1)(a)/(d): 10(23C) OR (12A AND 80G)
        tax_exempt = bool(self.has_10_23c or (self.has_12a and self.has_80g))
        if not tax_exempt:
            return False

        # 3-year track record check (Rule 4(1)(d))
        try:
            year_est = getattr(self.ngo, 'year_established', None)
            if year_est:
                current_year = timezone.now().year
                if (current_year - int(year_est)) < 3:
                    return False
        except (AttributeError, ValueError, TypeError):
            pass

        return True

    def save(self, *args, **kwargs):
        """Normalize PAN to uppercase before saving."""
        if self.pan_number:
            self.pan_number = self.pan_number.strip().upper()
        if self.darpan_id:
            self.darpan_id = self.darpan_id.strip()
        if self.registration_number:
            self.registration_number = self.registration_number.strip()
        if self.csr_registration_number:
            self.csr_registration_number = self.csr_registration_number.strip().upper()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.has_12a and not self.twelve_a_number:
            raise ValidationError({'twelve_a_number': _('12A number is required when has_12a is True.')})
        if self.has_80g and not self.eighty_g_number:
            raise ValidationError({'eighty_g_number': _('80G number is required when has_80g is True.')})
        if self.has_fcra and not self.fcra_number:
            raise ValidationError({'fcra_number': _('FCRA number is required when has_fcra is True.')})
        if self.has_10_23c and not self.ten_23c_order_number:
            raise ValidationError({'ten_23c_order_number': _('Section 10(23C) order number is required when has_10_23c is True.')})
        if self.has_csr_1 and not self.csr_registration_number:
            raise ValidationError({'csr_registration_number': _('CSR-1 registration number is required when has_csr_1 is True.')})


# ---------------------------------------------------------------------------
# MODEL 4: NGOBankInfo
# ---------------------------------------------------------------------------

class NGOBankInfo(models.Model):
    class AccountType(models.TextChoices):
        SAVINGS = 'SAVINGS', _('Savings Account')
        CURRENT = 'CURRENT', _('Current Account')
        ESCROW  = 'ESCROW',  _('Escrow Account')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.OneToOneField(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='bank_info',
    )
    bank_name = models.CharField(
        max_length=150,
        help_text=_('Name of bank (e.g. State Bank of India). NGO+Admin only.'),
    )
    account_holder_name = models.CharField(
        max_length=255,
        help_text=_('Account holder name — must match NGO legal name. NGO+Admin only.'),
    )
    # CRITICAL: account_number is NEVER serialized to any public/donor/other-NGO response.
    # Displayed masked to owner (last 4 digits). Plaintext in Phase 3.
    account_number = models.CharField(
        max_length=20,
        validators=[validate_account_number],
        help_text=_(
            'Bank account number (9-20 digits). '
            'CRITICAL: Never in public API. Masked to last 4 digits in owner view. '
            'Plaintext in Phase 3 — encryption PLANNED.'
        ),
    )
    ifsc_code = models.CharField(
        max_length=11,
        validators=[validate_ifsc_code],
        help_text=_('IFSC code (11 chars: ABCD0123456). NGO+Admin only.'),
    )
    branch_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_('Bank branch name. Optional. NGO+Admin only.'),
    )
    account_type = models.CharField(
        max_length=15,
        choices=AccountType.choices,
        default=AccountType.SAVINGS,
        help_text=_('Type of bank account. NGO+Admin only.'),
    )
    is_verified = models.BooleanField(
        default=False,
        help_text=_('Set True only after admin explicitly verifies bank details.'),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_bank_records',
        help_text=_('Admin who verified the bank details.'),
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of admin bank verification.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('NGO Bank Info')
        verbose_name_plural = _('NGO Bank Info Records')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    account_number__regex=r'^\d{9,20}$'
                ),
                name='chk_ngobankinfo_account_number_digits',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    ifsc_code__regex=r'^[A-Z]{4}0[A-Z0-9]{6}$'
                ),
                name='chk_ngobankinfo_ifsc_format',
            ),
        ]

    def __str__(self):
        return f'{self.ngo.display_name} — {self.bank_name} (****{self.account_number[-4:]})'

    @property
    def masked_account_number(self):
        """Returns account number masked to last 4 digits. Safe for owner display."""
        if len(self.account_number) >= 4:
            return f'****{self.account_number[-4:]}'
        return '****'


# ---------------------------------------------------------------------------
# MODEL 5: NGODocument
# ---------------------------------------------------------------------------

class NGODocument(models.Model):

    class DocumentType(models.TextChoices):
        TRUST_DEED          = 'TRUST_DEED',          _('Trust Deed')
        REGISTRATION_CERT   = 'REGISTRATION_CERT',   _('Registration Certificate')
        PAN_CARD            = 'PAN_CARD',            _('PAN Card')
        DARPAN_CERTIFICATE  = 'DARPAN_CERTIFICATE',  _('NGO Darpan Certificate')
        TWELVE_A_CERT       = 'TWELVE_A_CERT',       _('12A Certificate')
        EIGHTY_G_CERT       = 'EIGHTY_G_CERT',       _('80G Certificate')
        FORM_10AC           = 'FORM_10AC',           _('Form 10AC')
        FCRA_CERT           = 'FCRA_CERT',           _('FCRA Certificate')
        CSR_1_CERT          = 'CSR_1_CERT',          _('Form CSR-1 Registration Certificate')
        TEN_23C_CERT        = 'TEN_23C_CERT',        _('Section 10(23C) Approval Order')
        AUDITED_FINANCIALS  = 'AUDITED_FINANCIALS',  _('Audited Financial Statements')
        BANK_PASSBOOK       = 'BANK_PASSBOOK',       _('Bank Passbook / Statement')
        CANCELLED_CHEQUE    = 'CANCELLED_CHEQUE',    _('Cancelled Cheque')
        REPRESENTATIVE_ID   = 'REPRESENTATIVE_ID',   _('Representative ID Proof')
        OTHER               = 'OTHER',               _('Other Document')

    # Base document types unconditionally required for SUBMITTED transition
    REQUIRED_DOCUMENT_TYPES = [
        DocumentType.REGISTRATION_CERT,
        DocumentType.PAN_CARD,
        DocumentType.DARPAN_CERTIFICATE,
        DocumentType.AUDITED_FINANCIALS,
        DocumentType.BANK_PASSBOOK,
        DocumentType.CANCELLED_CHEQUE,
        DocumentType.REPRESENTATIVE_ID,
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.ForeignKey(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='documents',
        db_index=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_documents',
        help_text=_(
            'User who uploaded the document. '
            'PROTECT prevents user deletion while documents exist.'
        ),
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        db_index=True,
    )
    file = models.FileField(
        upload_to=ngo_document_path,
        validators=[validate_document_extension],
        help_text=_(
            'Document file. '
            'Stored at ngo_docs/{ngo_id}/{document_type}/{uuid}.ext. '
            'NEVER served via raw MEDIA_URL — authenticated view only.'
        ),
    )
    original_filename = models.CharField(
        max_length=255,
        help_text=_(
            'Original filename for display only. '
            'Never used as storage path (security).'
        ),
    )
    file_size_bytes = models.PositiveIntegerField(
        help_text=_('File size in bytes. Set server-side — never trusted from client.'),
    )
    mime_type = models.CharField(
        max_length=100,
        help_text=_('MIME type. Validated server-side — not from client Content-Type header.'),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_('False when replaced by a newer upload. Never deleted — retained for audit.'),
    )
    is_verified = models.BooleanField(
        default=False,
        help_text=_('Set True by admin during verification review.'),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_documents',
        help_text=_('Admin who marked this document as verified.'),
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(
        blank=True,
        default='',
        help_text=_('Admin-set reason if document rejected. Shown to NGO.'),
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    replaced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Set when a newer version of this document is uploaded.'),
    )
    replaces = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replacement',
        help_text=_('The previous document version that this record replaces.'),
    )

    class Meta:
        verbose_name = _('NGO Document')
        verbose_name_plural = _('NGO Documents')
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(
                fields=['ngo', 'document_type', 'is_active'],
                name='idx_ngodoc_ngo_type_active',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(file_size_bytes__gt=0),
                name='chk_ngodocument_file_size_positive',
            ),
        ]

    def __str__(self):
        return f'{self.ngo.display_name} — {self.document_type} ({"active" if self.is_active else "replaced"})'


# ---------------------------------------------------------------------------
# MODEL 6: NGOLeadership
# ---------------------------------------------------------------------------

class NGOLeadership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.ForeignKey(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='leadership',
        db_index=True,
    )
    full_name = models.CharField(
        max_length=255,
        help_text=_('Full name of the trustee or leader. Publicly visible when NGO is APPROVED.'),
    )
    designation = models.CharField(
        max_length=100,
        help_text=_(
            'Designation (e.g. Managing Trustee, President, Secretary). '
            'Publicly visible when NGO is APPROVED.'
        ),
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        validators=[validate_phone],
        help_text=_('Contact phone. NGO+Admin only. Never publicly exposed.'),
    )
    email = models.EmailField(
        max_length=254,
        blank=True,
        default='',
        help_text=_('Contact email. NGO+Admin only. Never publicly exposed.'),
    )
    is_primary_contact = models.BooleanField(
        default=False,
        help_text=_(
            'Marks the primary representative of the NGO. '
            'Only one per NGO enforced via partial unique constraint.'
        ),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_('False for resigned or inactive trustees. Retained for historical record.'),
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text=_('Display order. Lower number appears first.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('NGO Leadership')
        verbose_name_plural = _('NGO Leadership Records')
        ordering = ['order', 'created_at']
        indexes = [
            models.Index(fields=['ngo', 'is_active'], name='idx_ngoleadership_ngo_active'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['ngo', 'is_primary_contact'],
                condition=models.Q(is_primary_contact=True),
                name='unique_ngo_primary_contact',
            ),
        ]

    def __str__(self):
        return f'{self.full_name} ({self.designation}) — {self.ngo.display_name}'


# ---------------------------------------------------------------------------
# GovCheckStatus Enum
# ---------------------------------------------------------------------------

class GovCheckStatus(models.TextChoices):
    GOVERNMENT_CHECK_PENDING      = 'GOVERNMENT_CHECK_PENDING',      _('Government Check Pending')
    GOVERNMENT_CHECK_PASSED       = 'GOVERNMENT_CHECK_PASSED',       _('Government Check Passed')
    GOVERNMENT_CHECK_FAILED       = 'GOVERNMENT_CHECK_FAILED',       _('Government Check Failed')
    MANUAL_VERIFICATION_REQUIRED  = 'MANUAL_VERIFICATION_REQUIRED',  _('Manual Verification Required')
    GOVERNMENT_SOURCE_UNAVAILABLE = 'GOVERNMENT_SOURCE_UNAVAILABLE', _('Government Source Unavailable')


# ---------------------------------------------------------------------------
# MODEL 7: NGOVerification
# ---------------------------------------------------------------------------

class NGOVerification(models.Model):
    class Status(models.TextChoices):
        PENDING             = 'PENDING',              _('Pending')
        SUBMITTED           = 'SUBMITTED',            _('Submitted')
        UNDER_REVIEW        = 'UNDER_REVIEW',         _('Under Review')
        CORRECTION_REQUIRED = 'CORRECTION_REQUIRED',  _('Correction Required')
        APPROVED            = 'APPROVED',             _('Approved')
        REJECTED            = 'REJECTED',             _('Rejected')
        SUSPENDED           = 'SUSPENDED',            _('Suspended')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.OneToOneField(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='verification',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviews',
        help_text=_('Admin currently assigned to this application. Null if unassigned.'),
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text=_('Current review status. NEVER user-writable. Service-only.'),
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
        help_text=_('Source of government check (e.g. NITI_AAYOG_DARPAN, ITD_PAN, MCA_V3, MANUAL_INSPECTION).'),
    )
    gov_check_details = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Safe metadata regarding government check result, match details, and timestamps.'),
    )
    gov_check_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when government or manual check was completed.'),
    )

    # CSR-Specific Explicit Admin Verification
    is_csr_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_('Explicit admin verification of CSR eligibility credentials. Required for CSR participation.'),
    )
    csr_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when admin verified CSR credentials.'),
    )
    csr_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='csr_verified_ngos',
        help_text=_('Admin who verified CSR credentials.'),
    )
    csr_review_notes = models.TextField(
        blank=True,
        default='',
        help_text=_('Admin review notes addressing CSR eligibility verification.'),
    )

    # Admin-only internal fields — never exposed to NGO
    admin_notes = models.TextField(
        blank=True,
        default='',
        help_text=_('Internal admin notes. Admin-only. Never shown to NGO.'),
    )
    risk_flags = models.TextField(
        blank=True,
        default='',
        help_text=_('Internal risk/compliance flags. Admin-only. Never shown to NGO.'),
    )

    # NGO-visible when status=CORRECTION_REQUIRED
    correction_instructions = models.TextField(
        blank=True,
        default='',
        help_text=_('Instructions for the NGO on what to correct. Visible to NGO.'),
    )
    # NGO-visible when status=REJECTED
    rejection_reason = models.TextField(
        blank=True,
        default='',
        help_text=_('Reason for rejection. Visible to NGO.'),
    )

    # Bank correction flag — controls bank modification permission during CORRECTION_REQUIRED
    bank_correction_requested = models.BooleanField(
        default=False,
        help_text=_(
            'Set by admin when CORRECTION_REQUIRED includes bank info changes. '
            'When True, NGO can modify bank details during correction cycle. '
            'Reset to False on each resubmission.'
        ),
    )

    # Resubmission control
    resubmission_count = models.PositiveSmallIntegerField(
        default=0,
        help_text=_(
            'Number of times the NGO has resubmitted after CORRECTION_REQUIRED. '
            'Incremented by service on each CORRECTION_REQUIRED → SUBMITTED transition.'
        ),
    )
    resubmission_limit = models.PositiveSmallIntegerField(
        default=3,
        help_text=_(
            'Maximum correction/resubmission cycles allowed. Default 3. '
            'Admin can raise this via the reopen action.'
        ),
    )
    admin_reopened = models.BooleanField(
        default=False,
        help_text=_(
            'Set True by admin reopen action after limit reached. '
            'Resets resubmission_count to 0 and allows new cycles.'
        ),
    )

    # Timestamps — all backend-only
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of first SUBMITTED transition. Not updated on resubmissions.'),
    )
    last_submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of most recent SUBMITTED (including resubmissions).'),
    )
    review_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when status moved to UNDER_REVIEW.'),
    )
    decision_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of APPROVED / REJECTED / CORRECTION_REQUIRED decision.'),
    )
    resubmission_deadline = models.DateField(
        null=True,
        blank=True,
        help_text=_('Optional deadline for NGO correction submission. Set by admin.'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('NGO Verification')
        verbose_name_plural = _('NGO Verifications')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(resubmission_count__gte=0),
                name='chk_ngoverification_resubmission_count_non_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(resubmission_limit__gte=1),
                name='chk_ngoverification_resubmission_limit_min_1',
            ),
        ]

    def __str__(self):
        return f'{self.ngo.display_name} — {self.status}'

    @property
    def can_resubmit(self):
        if self.admin_reopened:
            return True
        return self.resubmission_count < self.resubmission_limit


# ---------------------------------------------------------------------------
# MODEL 8: NGOVerificationHistory (INSERT-ONLY / IMMUTABLE)
# ---------------------------------------------------------------------------

class NGOVerificationHistory(models.Model):
    class ActorType(models.TextChoices):
        NGO    = 'NGO',    _('NGO User')
        ADMIN  = 'ADMIN',  _('Admin User')
        SYSTEM = 'SYSTEM', _('System')

    # Attach the immutable custom manager
    objects = ImmutableHistoryManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.ForeignKey(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='history',
        db_index=True,
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_history',
        help_text=_('User who triggered the action. Null for system-generated events.'),
    )
    actor_type = models.CharField(
        max_length=20,
        choices=ActorType.choices,
        default=ActorType.SYSTEM,
        help_text=_('NGO / ADMIN / SYSTEM. Shown to NGO owner (not the identity of admin).'),
    )
    previous_status = models.CharField(
        max_length=25,
        choices=NGOVerification.Status.choices,
        help_text=_('Verification status before this transition.'),
    )
    new_status = models.CharField(
        max_length=25,
        choices=NGOVerification.Status.choices,
        help_text=_('Verification status after this transition.'),
    )
    reason = models.TextField(
        blank=True,
        default='',
        help_text=_(
            'Reason for transition. '
            'Copied from correction_instructions or rejection_reason at time of action.'
        ),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Optional metadata: document IDs affected, admin_reopen flag, etc.'),
    )
    # auto_now_add — set once on INSERT; no auto_now to prevent any update path
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text=_('Immutable creation timestamp. Set once on INSERT.'),
    )

    class Meta:
        verbose_name = _('NGO Verification History')
        verbose_name_plural = _('NGO Verification History')
        ordering = ['-timestamp']
        indexes = [
            models.Index(
                fields=['ngo', '-timestamp'],
                name='idx_ngohistory_ngo_ts',
            ),
        ]

    def __str__(self):
        return (
            f'{self.ngo.display_name}: '
            f'{self.previous_status} → {self.new_status} '
            f'[{self.actor_type}] at {self.timestamp}'
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(
                'NGOVerificationHistory records are immutable. '
                'Existing records cannot be updated. '
                'Use change_ngo_verification_status() to create new history records.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevents deletion of history records."""
        raise ImmutableRecordError(
            'NGOVerificationHistory records are immutable and cannot be deleted.'
        )

