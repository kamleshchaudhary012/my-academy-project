import os
import uuid
import datetime
import random
import string
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinLengthValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from ngo.models import NGOProfile, validate_image_extension
from users.image_validators import validate_image_file
from csr.models import BeneficiaryDemographic


def campaign_cover_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f'campaign_covers/{instance.ngo.id}/{uuid.uuid4()}{ext}'


class Campaign(models.Model):
    class CampaignType(models.TextChoices):
        MONETARY = 'MONETARY', _('Monetary Fundraiser')
        MATERIAL = 'MATERIAL', _('Material Goods Drive')
        HYBRID   = 'HYBRID',   _('Monetary & Material Drive')

    class Status(models.TextChoices):
        DRAFT             = 'DRAFT',             _('Draft')
        PENDING_REVIEW    = 'PENDING_REVIEW',    _('Pending Admin Review')
        CHANGES_REQUESTED = 'CHANGES_REQUESTED', _('Changes Requested by Admin')
        ACTIVE            = 'ACTIVE',            _('Active / Published')
        REJECTED          = 'REJECTED',          _('Rejected by Admin')
        COMPLETED         = 'COMPLETED',         _('Completed')
        CANCELLED         = 'CANCELLED',         _('Cancelled')
        SUSPENDED         = 'SUSPENDED',         _('Suspended by Admin')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ngo = models.ForeignKey(
        NGOProfile,
        on_delete=models.CASCADE,
        related_name='campaigns',
        db_index=True,
        help_text=_('NGO profile creating this campaign appeal.'),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_campaigns',
        help_text=_('Authenticated NGO representative who created this campaign.'),
    )
    title = models.CharField(
        max_length=255,
        help_text=_('Title of the campaign / need request.'),
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text=_('URL-friendly unique slug for public campaign discovery.'),
    )
    category = models.CharField(
        max_length=30,
        choices=NGOProfile.Category.choices,
        default=NGOProfile.Category.OTHER,
        help_text=_('Category of the campaign.'),
    )
    campaign_type = models.CharField(
        max_length=20,
        choices=CampaignType.choices,
        default=CampaignType.MONETARY,
        help_text=_('Type of campaign appeal (Monetary, Material, or Hybrid).'),
    )
    short_description = models.CharField(
        max_length=500,
        help_text=_('Brief summary of the campaign appeal.'),
    )
    description = models.TextField(
        validators=[MinLengthValidator(30)],
        help_text=_('Full detailed description of the campaign and itemized needs. Minimum 30 characters.'),
    )
    target_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_('Target monetary goal in INR.'),
    )
    raised_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_('Total monetary amount collected so far.'),
    )
    cover_image = models.ImageField(
        upload_to=campaign_cover_path,
        null=True,
        blank=True,
        validators=[validate_image_extension],
        help_text=_('Campaign cover image.'),
    )
    start_date = models.DateField(
        help_text=_('Campaign start date.'),
    )
    end_date = models.DateField(
        help_text=_('Campaign end date.'),
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        help_text=_('Lifecycle status of the campaign.'),
    )
    is_featured = models.BooleanField(
        default=False,
        help_text=_('Whether this campaign is featured on the platform homepage.'),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_('Soft deletion / active toggle.'),
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_campaigns',
    )
    admin_review_note = models.TextField(blank=True, default='')
    rejection_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = _('Campaign / Need Request')
        verbose_name_plural = _('Campaigns / Need Requests')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.ngo.display_name}) — {self.status}'

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': _('End date cannot be earlier than start date.')})
        if self.target_amount is not None and self.target_amount < 0:
            raise ValidationError({'target_amount': _('Target amount cannot be negative.')})

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or 'campaign'
            slug = base_slug
            counter = 1
            while Campaign.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        self.full_clean()
        super().save(*args, **kwargs)


class CampaignReviewHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='review_history',
        db_index=True,
    )
    old_status = models.CharField(max_length=30)
    new_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Campaign Review History Audit')
        verbose_name_plural = _('Campaign Review History Audits')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.campaign.title}: {self.old_status} -> {self.new_status} by {self.changed_by}'


def generate_monetary_receipt_number():
    date_str = datetime.date.today().strftime('%Y%m%d')
    rand_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f'DG-M-{date_str}-{rand_str}'


class MonetaryDonation(models.Model):
    class Status(models.TextChoices):
        PENDING   = 'PENDING',   _('Pending Payment')
        SUCCESS   = 'SUCCESS',   _('Payment Successful')
        FAILED    = 'FAILED',    _('Payment Failed')
        CANCELLED = 'CANCELLED', _('Payment Cancelled')
        REFUNDED  = 'REFUNDED',  _('Refunded')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='monetary_donations',
        db_index=True,
        help_text=_('Authenticated donor who initiated this monetary contribution.'),
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        related_name='monetary_donations',
        db_index=True,
        help_text=_('Target campaign receiving this monetary contribution.'),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('10.00'))],
        help_text=_('Validated monetary donation amount in INR (minimum ₹10.00).'),
    )
    currency = models.CharField(
        max_length=10,
        default='INR',
        help_text=_('Currency code (e.g. INR).'),
    )
    receipt_number = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text=_('Human-readable unique donation receipt reference (e.g. DG-M-YYYYMMDD-XXXXX).'),
    )
    pan_number = models.CharField(
        max_length=10,
        blank=True,
        default='',
        help_text=_('Donor PAN for tax compliance (stored securely).'),
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text=_('Status of the monetary donation.'),
    )
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when payment was successfully verified.'),
    )
    is_anonymous = models.BooleanField(
        default=False,
        help_text=_('Whether donor chose to keep their identity anonymous to the public.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Monetary Donation')
        verbose_name_plural = _('Monetary Donations')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.receipt_number} — ₹{self.amount} ({self.status})'


class PaymentTransaction(models.Model):
    class Gateway(models.TextChoices):
        RAZORPAY = 'RAZORPAY', _('Razorpay')

    class Status(models.TextChoices):
        ORDER_CREATED        = 'ORDER_CREATED',        _('Order Created')
        PAYMENT_ATTEMPTED    = 'PAYMENT_ATTEMPTED',    _('Payment Attempted')
        VERIFICATION_PENDING = 'VERIFICATION_PENDING', _('Verification Pending')
        SUCCESS              = 'SUCCESS',              _('Success')
        FAILED               = 'FAILED',               _('Failed')
        CANCELLED            = 'CANCELLED',            _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    donation = models.ForeignKey(
        MonetaryDonation,
        on_delete=models.CASCADE,
        related_name='transactions',
        db_index=True,
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payment_transactions',
        db_index=True,
    )
    gateway = models.CharField(
        max_length=30,
        choices=Gateway.choices,
        default=Gateway.RAZORPAY,
    )
    gateway_order_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_('Gateway-provided order ID (e.g. order_xxx).'),
    )
    gateway_payment_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        help_text=_('Gateway-provided payment ID (e.g. pay_xxx).'),
    )
    gateway_signature = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_('Gateway cryptographic verification signature.'),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('10.00'))],
    )
    currency = models.CharField(
        max_length=10,
        default='INR',
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.ORDER_CREATED,
        db_index=True,
    )
    error_code = models.CharField(max_length=100, blank=True, default='')
    error_description = models.TextField(blank=True, default='')
    gateway_response_payload = models.JSONField(blank=True, default=dict)
    idempotency_key = models.CharField(max_length=100, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Payment Transaction')
        verbose_name_plural = _('Payment Transactions')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.gateway} {self.gateway_order_id} — ₹{self.amount} ({self.status})'


class GatewayWebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.CharField(max_length=100, unique=True, db_index=True)
    event_type = models.CharField(max_length=100, db_index=True)
    gateway = models.CharField(max_length=30, default='RAZORPAY')
    payload = models.JSONField(default=dict)
    is_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Gateway Webhook Event')
        verbose_name_plural = _('Gateway Webhook Events')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.gateway} Webhook {self.event_id} ({self.event_type}) - Processed: {self.is_processed}'


class TaxReceiptRecord(models.Model):
    class ReceiptType(models.TextChoices):
        EIGHTY_G = 'EIGHTY_G', _('80G Tax Exemption Receipt')
        STANDARD = 'STANDARD', _('Standard Payment Receipt')

    class Status(models.TextChoices):
        ISSUED    = 'ISSUED',    _('Issued')
        CANCELLED = 'CANCELLED', _('Cancelled')
        REVOKED   = 'REVOKED',   _('Revoked')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    donation = models.OneToOneField(
        MonetaryDonation,
        on_delete=models.PROTECT,
        related_name='tax_receipt',
        db_index=True,
    )
    receipt_number = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text=_('Authoritative unique receipt number corresponding to donation.'),
    )
    receipt_type = models.CharField(
        max_length=20,
        choices=ReceiptType.choices,
        default=ReceiptType.STANDARD,
        db_index=True,
    )
    financial_year = models.CharField(
        max_length=15,
        help_text=_('Indian Financial Year e.g. FY 2026-27.'),
    )

    # Immutable Snapshot Fields
    donor_name_snapshot = models.CharField(max_length=255)
    donor_pan_masked_snapshot = models.CharField(max_length=10, blank=True, default='')
    donor_email_snapshot = models.CharField(max_length=255)
    ngo_legal_name_snapshot = models.CharField(max_length=255)
    ngo_pan_snapshot = models.CharField(max_length=10)
    ngo_80g_number_snapshot = models.CharField(max_length=50, blank=True, default='')
    ngo_80g_validity_snapshot = models.DateField(null=True, blank=True)
    ngo_12a_number_snapshot = models.CharField(max_length=50, blank=True, default='')
    ngo_darpan_id_snapshot = models.CharField(max_length=50, blank=True, default='')
    ngo_address_snapshot = models.TextField(blank=True, default='')
    campaign_title_snapshot = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_in_words = models.CharField(max_length=255)
    payment_gateway_ref_snapshot = models.CharField(max_length=100, blank=True, default='')
    donation_paid_at_snapshot = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ISSUED,
        db_index=True,
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    document_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=_('SHA-256 integrity hash of verified receipt document.'),
    )
    pdf_file = models.FileField(
        upload_to='tax_receipts/%Y/%m/',
        null=True,
        blank=True,
        help_text=_('Rendered receipt PDF file.'),
    )
    download_count = models.PositiveIntegerField(
        default=0,
        help_text=_('Number of times this receipt PDF has been downloaded.'),
    )
    last_downloaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of the most recent download.'),
    )
    email_sent = models.BooleanField(
        default=False,
        help_text=_('Whether official receipt email has been dispatched.'),
    )
    email_send_count = models.PositiveIntegerField(
        default=0,
        help_text=_('Total count of receipt email dispatches (automatic + manual).'),
    )
    last_email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of most recent receipt email delivery.'),
    )
    last_email_error = models.TextField(
        blank=True,
        default='',
        help_text=_('Error message if the latest email dispatch attempt failed.'),
    )

    class Meta:
        verbose_name = _('Tax Receipt Record')
        verbose_name_plural = _('Tax Receipt Records')
        ordering = ['-issued_at']

    def __str__(self):
        return f'{self.receipt_type} {self.receipt_number} — ₹{self.amount} ({self.status})'


def validate_form10be_pdf(value):
    """
    Validates uploaded Form 10BE certificate file:
    - Maximum 5 MB file size.
    - PDF extension only.
    - Genuine PDF binary magic bytes (%PDF-).
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext != '.pdf':
        raise ValidationError(_('Unsupported file format. Only official PDF certificates (.pdf) are accepted.'))

    if value.size > 5 * 1024 * 1024:
        raise ValidationError(_('Form 10BE certificate file size cannot exceed 5 MB.'))

    # Read binary magic bytes
    try:
        current_pos = value.tell() if hasattr(value, 'tell') else 0
        value.seek(0)
        header = value.read(5)
        value.seek(current_pos)
        if not header.startswith(b'%PDF'):
            raise ValidationError(_('The uploaded file is not a valid PDF document.'))
    except Exception as e:
        if isinstance(e, ValidationError):
            raise
        raise ValidationError(_('Unable to verify PDF integrity. Please upload a valid PDF document.'))


def form_10be_upload_path(instance, filename):
    """
    Stores Form 10BE certificate with randomized UUID path:
    form_10be_certificates/{ngo_id}/{financial_year}/{uuid}.pdf
    Original filename is NEVER used as storage path for security.
    """
    fy_clean = str(instance.financial_year).replace(' ', '_').replace('/', '_')
    return f'form_10be_certificates/{instance.ngo_id}/{fy_clean}/{uuid.uuid4()}.pdf'


class Form10BECertificate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    donation = models.OneToOneField(
        MonetaryDonation,
        on_delete=models.PROTECT,
        related_name='form_10be',
        help_text=_('The verified Section 80G monetary donation this Form 10BE belongs to.'),
    )
    ngo = models.ForeignKey(
        'ngo.NGOProfile',
        on_delete=models.PROTECT,
        related_name='form_10be_certificates',
        help_text=_('The issuing NGO that uploaded this official certificate.'),
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='donor_form_10be_certificates',
        help_text=_('The authenticated donor who received this certificate.'),
    )
    financial_year = models.CharField(
        max_length=20,
        db_index=True,
        help_text=_('Financial Year for which the certificate was issued (e.g. FY 2026-27).'),
    )
    certificate_number = models.CharField(
        max_length=100,
        db_index=True,
        help_text=_('Official Form 10BE Certificate / Acknowledgement Number from ITD.'),
    )
    pdf_file = models.FileField(
        upload_to=form_10be_upload_path,
        validators=[validate_form10be_pdf],
        help_text=_('Official Form 10BE PDF. Stored securely with randomized UUID path.'),
    )
    original_filename = models.CharField(
        max_length=255,
        help_text=_('Original filename as uploaded by NGO (display metadata only).'),
    )
    file_size_bytes = models.PositiveIntegerField(
        help_text=_('Server-computed file size in bytes.'),
    )
    document_hash = models.CharField(
        max_length=64,
        help_text=_('SHA-256 integrity checksum of the certificate PDF.'),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_('Timestamp when certificate was uploaded.'),
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='+',
        help_text=_('User account that uploaded this certificate.'),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_('Whether this certificate is the active version.'),
    )
    download_count = models.PositiveIntegerField(
        default=0,
        help_text=_('Number of times this Form 10BE PDF has been downloaded.'),
    )
    last_downloaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of the most recent download.'),
    )
    notification_sent = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_('Whether donor notification email has been dispatched.'),
    )
    notification_send_count = models.PositiveIntegerField(
        default=0,
        help_text=_('Total count of notification email dispatches (initial + revision).'),
    )
    last_notification_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp of most recent notification email delivery.'),
    )
    last_notification_error = models.TextField(
        blank=True,
        default='',
        help_text=_('Error message if the latest notification dispatch attempt failed.'),
    )

    class Meta:
        verbose_name = _('Form 10BE Certificate')
        verbose_name_plural = _('Form 10BE Certificates')
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'Form 10BE {self.certificate_number} — {self.donation.receipt_number} ({self.financial_year})'


def distribution_proof_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    campaign_id = getattr(getattr(instance, 'milestone', None), 'campaign_id', None) or 'general'
    return f'distribution_proofs/{campaign_id}/{uuid.uuid4()}{ext}'


class CampaignMilestone(models.Model):
    class MilestoneStatus(models.TextChoices):
        PENDING            = 'PENDING', _('Pending')
        IN_PROGRESS        = 'IN_PROGRESS', _('In Progress')
        REVISION_REQUESTED = 'REVISION_REQUESTED', _('Revision Requested')
        VERIFIED           = 'VERIFIED', _('Verified')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='milestones',
        db_index=True,
        help_text=_('Campaign that this milestone belongs to.'),
    )
    sequence_number = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_('Sequence order of this milestone deliverable (1, 2, 3...).'),
    )
    title = models.CharField(
        max_length=255,
        help_text=_('Title of the milestone deliverable.'),
    )
    description = models.TextField(
        help_text=_('Detailed description of the milestone target and execution plan.'),
    )
    target_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_('Target allocated budget in INR for this milestone.'),
    )
    target_completion_date = models.DateField(
        help_text=_('Target estimated completion date for this milestone.'),
    )
    actual_completion_date = models.DateField(
        null=True,
        blank=True,
        help_text=_('Actual completion date verified by Admin.'),
    )
    status = models.CharField(
        max_length=30,
        choices=MilestoneStatus.choices,
        default=MilestoneStatus.PENDING,
        db_index=True,
        help_text=_('Current verification status of this milestone.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'campaigns_campaignmilestone'
        verbose_name = _('Campaign Milestone')
        verbose_name_plural = _('Campaign Milestones')
        ordering = ['campaign', 'sequence_number', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'sequence_number'],
                name='unique_campaign_milestone_sequence',
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_number__gte=1),
                name='check_campaign_milestone_sequence_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(target_amount__gte=0),
                name='check_campaign_milestone_target_amount_positive',
            ),
        ]

    def __str__(self):
        return f'{self.campaign.title} — Milestone #{self.sequence_number}: {self.title} ({self.status})'

    def clean(self):
        super().clean()
        if self.sequence_number is not None and self.sequence_number < 1:
            raise ValidationError({'sequence_number': _('Sequence number must be at least 1.')})
        if self.target_amount is not None and self.target_amount < Decimal('0.00'):
            raise ValidationError({'target_amount': _('Target amount cannot be negative.')})


class DistributionProof(models.Model):
    class Status(models.TextChoices):
        SUBMITTED          = 'SUBMITTED', _('Submitted for Review')
        UNDER_REVIEW       = 'UNDER_REVIEW', _('Under Review')
        VERIFIED           = 'VERIFIED', _('Verified')
        REVISION_REQUESTED = 'REVISION_REQUESTED', _('Revision Requested')
        REJECTED           = 'REJECTED', _('Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    milestone = models.ForeignKey(
        CampaignMilestone,
        on_delete=models.CASCADE,
        related_name='proofs',
        db_index=True,
        help_text=_('Milestone for which this field proof was submitted.'),
    )
    photo = models.ImageField(
        upload_to=distribution_proof_path,
        validators=[validate_image_file],
        help_text=_('Field distribution photo evidence (max 5 MB, JPG/JPEG/PNG/WebP).'),
    )
    caption = models.TextField(
        help_text=_('Detailed caption / narrative of distribution activity.'),
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_('Field distribution GPS latitude (-90 to 90).'),
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=_('Field distribution GPS longitude (-180 to 180).'),
    )
    location_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text=_('Village, ward, district, or landmark name.'),
    )
    beneficiary_count = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_('Number of verified beneficiaries served in this activity.'),
    )
    beneficiary_type = models.CharField(
        max_length=50,
        blank=True,
        default='',
        choices=BeneficiaryDemographic.choices,
        help_text=_('Primary beneficiary demographic served.'),
    )
    beneficiary_notes = models.TextField(
        blank=True,
        default='',
        help_text=_('Qualitative feedback or demographic notes.'),
    )
    spent_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_('Actual expenditure incurred in INR for this distribution activity.'),
    )
    expense_breakdown = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Structured itemized breakdown of expenses (items, quantities, unit costs).'),
    )
    distribution_date = models.DateField(
        help_text=_('Date when field distribution took place.'),
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.SUBMITTED,
        db_index=True,
        help_text=_('Administrative review status of this proof.'),
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_distribution_proofs',
        help_text=_('User account that submitted this proof.'),
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_('Timestamp when proof was submitted.'),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_distribution_proofs',
        help_text=_('Platform administrator who reviewed this proof.'),
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when proof was reviewed.'),
    )
    admin_notes = models.TextField(
        blank=True,
        default='',
        help_text=_('Internal admin notes (never displayed to public/donor).'),
    )
    rejection_reason = models.TextField(
        blank=True,
        default='',
        help_text=_('Feedback returned to NGO if proof rejected or revision requested.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'campaigns_distributionproof'
        verbose_name = _('Distribution Proof')
        verbose_name_plural = _('Distribution Proofs')
        ordering = ['-submitted_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(latitude__isnull=True) | (models.Q(latitude__gte=-90) & models.Q(latitude__lte=90)),
                name='check_proof_latitude_range',
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__isnull=True) | (models.Q(longitude__gte=-180) & models.Q(longitude__lte=180)),
                name='check_proof_longitude_range',
            ),
            models.CheckConstraint(
                condition=models.Q(spent_amount__gte=0),
                name='check_proof_spent_amount_positive',
            ),
        ]

    def __str__(self):
        return f'Proof for {self.milestone.title} ({self.status}) — {self.distribution_date}'

    def clean(self):
        super().clean()
        if self.spent_amount is not None and self.spent_amount < Decimal('0.00'):
            raise ValidationError({'spent_amount': _('Spent amount cannot be negative.')})
        if self.latitude is not None and (self.latitude < Decimal('-90.000000') or self.latitude > Decimal('90.000000')):
            raise ValidationError({'latitude': _('Latitude must be between -90 and 90 degrees.')})
        if self.longitude is not None and (self.longitude < Decimal('-180.000000') or self.longitude > Decimal('180.000000')):
            raise ValidationError({'longitude': _('Longitude must be between -180 and 180 degrees.')})
        if self.beneficiary_count is not None and self.beneficiary_count < 0:
            raise ValidationError({'beneficiary_count': _('Beneficiary count cannot be negative.')})


