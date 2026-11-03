import re
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from campaigns.models import (
    Campaign,
    MonetaryDonation,
    PaymentTransaction,
    TaxReceiptRecord,
    Form10BECertificate,
    validate_form10be_pdf,
    generate_monetary_receipt_number,
)
from ngo.models import NGOProfile

PAN_REGEX = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$')

class MonetaryContributionValidationSerializer(serializers.Serializer):
    amount = serializers.CharField(
        required=True,
        error_messages={'required': _('Contribution amount is required.')},
    )
    campaign = serializers.UUIDField(required=False, allow_null=True)
    ngo = serializers.UUIDField(required=False, allow_null=True)
    pan_number = serializers.CharField(required=False, allow_blank=True, max_length=10)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_amount(self, value):
        if value is None or str(value).strip() == '':
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        val_str = str(value).strip()
        # Reject malformed strings or scientific notation
        if not re.match(r'^\d+(\.\d{1,2})?$', val_str):
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        try:
            amt = Decimal(val_str)
        except (InvalidOperation, TypeError, ValueError):
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        if amt < Decimal('10.00'):
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        if amt > Decimal('100000000.00'):
            raise serializers.ValidationError(_('Contribution amount exceeds allowable single transaction limit.'))

        return amt.quantize(Decimal('0.01'))

    def validate_pan_number(self, value):
        if not value:
            return ''
        cleaned = value.strip().upper()
        if not PAN_REGEX.match(cleaned):
            raise serializers.ValidationError(_('Enter a valid 10-character PAN format (e.g. ABCDE1234F).'))
        return cleaned

    def validate(self, data):
        campaign_id = data.get('campaign')
        ngo_id = data.get('ngo')

        if campaign_id:
            try:
                campaign = Campaign.objects.select_related('ngo').get(pk=campaign_id)
            except Campaign.DoesNotExist:
                raise serializers.ValidationError({'campaign': _('The specified campaign does not exist.')})

            # Check campaign status & active flag
            if campaign.status != Campaign.Status.ACTIVE or not campaign.is_active:
                raise serializers.ValidationError({
                    'campaign': _('The specified campaign is not currently active for donations.')
                })

            # Check NGO status & active flag
            if campaign.ngo.status != 'APPROVED' or not campaign.ngo.is_active:
                raise serializers.ValidationError({
                    'campaign': _('The organization running this campaign is not currently active or verified.')
                })

            # Check campaign_type is MONETARY or HYBRID
            if campaign.campaign_type not in [Campaign.CampaignType.MONETARY, Campaign.CampaignType.HYBRID]:
                raise serializers.ValidationError({
                    'campaign': _('Monetary contributions are not available for material-only campaigns.')
                })

            data['campaign_obj'] = campaign
            data['ngo_obj'] = campaign.ngo

        elif ngo_id:
            try:
                ngo = NGOProfile.objects.get(pk=ngo_id)
            except NGOProfile.DoesNotExist:
                raise serializers.ValidationError({'ngo': _('The specified NGO does not exist.')})

            if ngo.status != 'APPROVED' or not ngo.is_active:
                raise serializers.ValidationError({
                    'ngo': _('The specified NGO is not currently active or verified.')
                })

            campaign = Campaign.objects.filter(
                ngo=ngo,
                status=Campaign.Status.ACTIVE,
                is_active=True,
                campaign_type__in=[Campaign.CampaignType.MONETARY, Campaign.CampaignType.HYBRID]
            ).order_by('-created_at').first()

            if campaign:
                data['campaign_obj'] = campaign
            data['ngo_obj'] = ngo

        else:
            campaign = Campaign.objects.filter(
                status=Campaign.Status.ACTIVE,
                is_active=True,
                ngo__status='APPROVED',
                ngo__is_active=True,
                campaign_type__in=[Campaign.CampaignType.MONETARY, Campaign.CampaignType.HYBRID]
            ).order_by('-created_at').first()

            if campaign:
                data['campaign_obj'] = campaign
                data['ngo_obj'] = campaign.ngo

        return data


class MonetaryDonationCreateOrderSerializer(serializers.Serializer):
    campaign = serializers.UUIDField(required=False, allow_null=True)
    ngo = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.CharField(required=True)
    pan_number = serializers.CharField(required=False, allow_blank=True, max_length=10)
    is_anonymous = serializers.BooleanField(required=False, default=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_amount(self, value):
        if value is None or str(value).strip() == '':
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        val_str = str(value).strip()
        if not re.match(r'^\d+(\.\d{1,2})?$', val_str):
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        try:
            amt = Decimal(val_str)
        except (InvalidOperation, TypeError, ValueError):
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        if amt < Decimal('10.00'):
            raise serializers.ValidationError(_('Minimum monetary contribution amount is ₹10.'))

        if amt > Decimal('100000000.00'):
            raise serializers.ValidationError(_('Contribution amount exceeds allowable single transaction limit.'))

        return amt.quantize(Decimal('0.01'))

    def validate_pan_number(self, value):
        if not value:
            return ''
        cleaned = value.strip().upper()
        if not PAN_REGEX.match(cleaned):
            raise serializers.ValidationError(_('Enter a valid 10-character PAN format (e.g. ABCDE1234F).'))
        return cleaned

    def validate(self, data):
        campaign_id = data.get('campaign')
        ngo_id = data.get('ngo')

        if campaign_id:
            try:
                campaign = Campaign.objects.select_related('ngo').get(pk=campaign_id)
            except Campaign.DoesNotExist:
                raise serializers.ValidationError({'campaign': _('The specified campaign does not exist.')})

            if campaign.status != Campaign.Status.ACTIVE or not campaign.is_active:
                raise serializers.ValidationError({
                    'campaign': _('The specified campaign is not currently active for donations.')
                })

            if campaign.ngo.status != 'APPROVED' or not campaign.ngo.is_active:
                raise serializers.ValidationError({
                    'campaign': _('The organization running this campaign is not currently active or verified.')
                })

            if campaign.campaign_type not in [Campaign.CampaignType.MONETARY, Campaign.CampaignType.HYBRID]:
                raise serializers.ValidationError({
                    'campaign': _('Monetary contributions are not available for material-only campaigns.')
                })

            data['campaign_obj'] = campaign
            data['ngo_obj'] = campaign.ngo

        elif ngo_id:
            try:
                ngo = NGOProfile.objects.get(pk=ngo_id)
            except NGOProfile.DoesNotExist:
                raise serializers.ValidationError({'ngo': _('The specified NGO does not exist.')})

            if ngo.status != 'APPROVED' or not ngo.is_active:
                raise serializers.ValidationError({
                    'ngo': _('The specified NGO is not currently active or verified.')
                })

            campaign = Campaign.objects.filter(
                ngo=ngo,
                status=Campaign.Status.ACTIVE,
                is_active=True,
                campaign_type__in=[Campaign.CampaignType.MONETARY, Campaign.CampaignType.HYBRID]
            ).order_by('-created_at').first()

            if not campaign:
                raise serializers.ValidationError({
                    'ngo': _('The selected NGO does not currently have an active monetary campaign.')
                })

            data['campaign_obj'] = campaign
            data['ngo_obj'] = ngo

        else:
            campaign = Campaign.objects.filter(
                status=Campaign.Status.ACTIVE,
                is_active=True,
                ngo__status='APPROVED',
                ngo__is_active=True,
                campaign_type__in=[Campaign.CampaignType.MONETARY, Campaign.CampaignType.HYBRID]
            ).order_by('-created_at').first()

            if not campaign:
                raise serializers.ValidationError({
                    'campaign': _('A valid campaign or verified NGO must be specified for monetary contributions.')
                })

            data['campaign_obj'] = campaign
            data['ngo_obj'] = campaign.ngo

        return data


class MonetaryDonationVerifyPaymentSerializer(serializers.Serializer):
    donation_id = serializers.UUIDField(required=True)
    razorpay_order_id = serializers.CharField(required=True)
    razorpay_payment_id = serializers.CharField(required=True)
    razorpay_signature = serializers.CharField(required=True)


class MonetaryDonationReadSerializer(serializers.ModelSerializer):
    campaign_title = serializers.CharField(source='campaign.title', read_only=True)
    campaign_slug = serializers.CharField(source='campaign.slug', read_only=True)
    ngo_name = serializers.SerializerMethodField()
    pan_masked = serializers.SerializerMethodField()
    has_form_10be = serializers.SerializerMethodField()
    form_10be_certificate_number = serializers.SerializerMethodField()
    gateway_transaction_reference = serializers.SerializerMethodField()
    gateway_order_reference = serializers.SerializerMethodField()
    tax_receipt_status = serializers.SerializerMethodField()
    tax_receipt_sha256 = serializers.SerializerMethodField()
    verification_source = serializers.SerializerMethodField()
    settlement_status = serializers.SerializerMethodField()
    settlement_status_display = serializers.SerializerMethodField()
    fund_utilization_notice = serializers.SerializerMethodField()

    class Meta:
        model = MonetaryDonation
        fields = [
            'id',
            'receipt_number',
            'amount',
            'currency',
            'status',
            'paid_at',
            'campaign',
            'campaign_title',
            'campaign_slug',
            'ngo_name',
            'pan_masked',
            'has_form_10be',
            'form_10be_certificate_number',
            'gateway_transaction_reference',
            'gateway_order_reference',
            'tax_receipt_status',
            'tax_receipt_sha256',
            'verification_source',
            'settlement_status',
            'settlement_status_display',
            'fund_utilization_notice',
            'is_anonymous',
            'created_at',
        ]
        read_only_fields = fields

    def get_ngo_name(self, obj):
        ngo = obj.campaign.ngo
        return getattr(ngo, 'display_name', getattr(ngo, 'legal_name', ''))

    def get_pan_masked(self, obj):
        if obj.pan_number and len(obj.pan_number) == 10:
            return f'******{obj.pan_number[-4:]}'
        return None

    def get_has_form_10be(self, obj):
        return hasattr(obj, 'form_10be') and getattr(obj.form_10be, 'is_active', False)

    def get_form_10be_certificate_number(self, obj):
        if hasattr(obj, 'form_10be') and getattr(obj.form_10be, 'is_active', False):
            return obj.form_10be.certificate_number
        return None

    def get_gateway_transaction_reference(self, obj):
        tx = obj.transactions.first()
        return tx.gateway_payment_id if tx and tx.gateway_payment_id else None

    def get_gateway_order_reference(self, obj):
        tx = obj.transactions.first()
        return tx.gateway_order_id if tx and tx.gateway_order_id else None

    def get_tax_receipt_status(self, obj):
        if hasattr(obj, 'tax_receipt') and obj.tax_receipt:
            return obj.tax_receipt.status
        return 'ISSUED' if obj.status == MonetaryDonation.Status.SUCCESS else 'NOT_ISSUED'

    def get_tax_receipt_sha256(self, obj):
        if hasattr(obj, 'tax_receipt') and obj.tax_receipt:
            return obj.tax_receipt.document_hash or None
        return None

    def get_verification_source(self, obj):
        if obj.status == MonetaryDonation.Status.SUCCESS:
            return 'RAZORPAY_HMAC_SHA256'
        return 'UNVERIFIED'

    def get_settlement_status(self, obj):
        return 'NOT_AVAILABLE_PENDING_VERIFICATION'

    def get_settlement_status_display(self, obj):
        return 'Settlement information not available / pending verification with payment gateway and NGO bank account'

    def get_fund_utilization_notice(self, obj):
        return 'Payment verified via payment gateway. NGO fund disbursement is tracked via campaign milestones; gateway success does not constitute immediate ground expenditure.'


class Form10BEUploadSerializer(serializers.Serializer):
    certificate_number = serializers.CharField(
        max_length=100,
        required=True,
        error_messages={'required': _('Official Form 10BE Certificate / Acknowledgement Number is required.')}
    )
    file = serializers.FileField(
        required=True,
        validators=[validate_form10be_pdf],
        error_messages={'required': _('Form 10BE certificate PDF file is required.')}
    )

    def validate_certificate_number(self, value):
        val = str(value).strip()
        if not val:
            raise serializers.ValidationError(_('Certificate number cannot be blank.'))
        if any(c in val for c in ['\r', '\n', '\0']):
            raise serializers.ValidationError(_('Certificate number contains invalid control characters.'))
        return val


class Form10BECertificateReadSerializer(serializers.ModelSerializer):
    donation_id = serializers.UUIDField(source='donation.id', read_only=True)
    receipt_number = serializers.CharField(source='donation.receipt_number', read_only=True)

    class Meta:
        model = Form10BECertificate
        fields = [
            'id',
            'donation_id',
            'receipt_number',
            'financial_year',
            'certificate_number',
            'original_filename',
            'file_size_bytes',
            'document_hash',
            'uploaded_at',
            'is_active',
            'download_count',
            'last_downloaded_at',
            'notification_sent',
            'notification_send_count',
            'last_notification_sent_at',
        ]
        read_only_fields = fields


class NGOMonetaryDonationReadSerializer(serializers.ModelSerializer):
    campaign_title = serializers.CharField(source='campaign.title', read_only=True)
    campaign_slug = serializers.CharField(source='campaign.slug', read_only=True)
    donor_name = serializers.SerializerMethodField()

    class Meta:
        model = MonetaryDonation
        fields = [
            'id',
            'receipt_number',
            'amount',
            'currency',
            'status',
            'paid_at',
            'campaign',
            'campaign_title',
            'campaign_slug',
            'donor_name',
            'is_anonymous',
            'created_at',
        ]
        read_only_fields = fields

    def get_donor_name(self, obj):
        if obj.is_anonymous:
            return 'Anonymous Donor'
        return obj.donor.full_name or obj.donor.email or 'Verified Donor'


class AdminMonetaryDonationReadSerializer(serializers.ModelSerializer):
    campaign_title = serializers.CharField(source='campaign.title', read_only=True)
    campaign_slug = serializers.CharField(source='campaign.slug', read_only=True)
    ngo_name = serializers.SerializerMethodField()
    donor_name = serializers.SerializerMethodField()
    donor_email = serializers.SerializerMethodField()
    gateway_order_id = serializers.SerializerMethodField()
    gateway_payment_id = serializers.SerializerMethodField()
    gateway_transaction_reference = serializers.SerializerMethodField()
    tax_receipt_status = serializers.SerializerMethodField()
    tax_receipt_sha256 = serializers.SerializerMethodField()
    verification_source = serializers.SerializerMethodField()
    settlement_status = serializers.SerializerMethodField()
    settlement_status_display = serializers.SerializerMethodField()
    has_form_10be = serializers.SerializerMethodField()
    form_10be_certificate_number = serializers.SerializerMethodField()

    class Meta:
        model = MonetaryDonation
        fields = [
            'id',
            'receipt_number',
            'amount',
            'currency',
            'status',
            'paid_at',
            'campaign',
            'campaign_title',
            'campaign_slug',
            'ngo_name',
            'donor_name',
            'donor_email',
            'is_anonymous',
            'gateway_order_id',
            'gateway_payment_id',
            'gateway_transaction_reference',
            'tax_receipt_status',
            'tax_receipt_sha256',
            'verification_source',
            'settlement_status',
            'settlement_status_display',
            'has_form_10be',
            'form_10be_certificate_number',
            'created_at',
        ]
        read_only_fields = fields

    def get_ngo_name(self, obj):
        ngo = obj.campaign.ngo
        return getattr(ngo, 'display_name', getattr(ngo, 'legal_name', ''))

    def get_donor_name(self, obj):
        if obj.is_anonymous:
            return f"Anonymous ({obj.donor.full_name or obj.donor.email})"
        return obj.donor.full_name or obj.donor.email

    def get_donor_email(self, obj):
        return obj.donor.email

    def get_gateway_order_id(self, obj):
        tx = obj.transactions.first()
        return tx.gateway_order_id if tx else None

    def get_gateway_payment_id(self, obj):
        tx = obj.transactions.first()
        return tx.gateway_payment_id if tx else None

    def get_gateway_transaction_reference(self, obj):
        tx = obj.transactions.first()
        return tx.gateway_payment_id if tx and tx.gateway_payment_id else None

    def get_tax_receipt_status(self, obj):
        if hasattr(obj, 'tax_receipt') and obj.tax_receipt:
            return obj.tax_receipt.status
        return 'ISSUED' if obj.status == MonetaryDonation.Status.SUCCESS else 'NOT_ISSUED'

    def get_tax_receipt_sha256(self, obj):
        if hasattr(obj, 'tax_receipt') and obj.tax_receipt:
            return obj.tax_receipt.document_hash or None
        return None

    def get_verification_source(self, obj):
        if obj.status == MonetaryDonation.Status.SUCCESS:
            return 'RAZORPAY_HMAC_SHA256'
        return 'UNVERIFIED'

    def get_settlement_status(self, obj):
        return 'NOT_AVAILABLE_PENDING_VERIFICATION'

    def get_settlement_status_display(self, obj):
        return 'Settlement information not available / pending verification with payment gateway and NGO bank account'

    def get_has_form_10be(self, obj):
        return hasattr(obj, 'form_10be') and getattr(obj.form_10be, 'is_active', False)

    def get_form_10be_certificate_number(self, obj):
        if hasattr(obj, 'form_10be') and getattr(obj.form_10be, 'is_active', False):
            return obj.form_10be.certificate_number
        return None


