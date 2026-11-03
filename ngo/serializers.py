"""
DaanGives NGO Serializers — Phase 3.3.1
========================================
Implements the 9 approved role-aware serializers for the NGO app:

  1. NGOAddressSerializer               — Registered address (read/write)
  2. NGOLegalInfoSerializer             — Legal identifiers & conditional certs
  3. NGOBankInfoSerializer              — Bank details with account number masking
  4. NGOLeadershipSerializer            — Leadership / trustees
  5. NGODocumentSerializer              — Document upload validation & metadata
  6. NGOProfileSerializer               — NGO Owner profile (read/write)
  7. NGOPublicSerializer                — SAFE public directory response
  8. NGOAdminSerializer                 — Full inspection serializer for Admin
  9. NGOVerificationHistorySerializer   — Read-only audit log serializer

Security Rules Enforced:
  - status, is_active, verified_at, is_public are strictly read-only in user serializers.
  - account_number is write_only in NGOBankInfoSerializer (masked as ****1234 on read).
  - Public serializer exposes ZERO bank info, ZERO PAN, ZERO reg numbers, ZERO private docs, ZERO coordinates.
  - Full account_number exposed ONLY in NGOAdminSerializer for Admin inspection.
  - 12A / 80G / FCRA certificate numbers enforced conditionally on serializer validation.
"""

from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGODocument,
    NGOLeadership,
    NGOVerification,
    NGOVerificationHistory,
    validate_account_number,
    validate_image_extension,
    validate_document_extension,
)


# ---------------------------------------------------------------------------
# 1. NGOAddressSerializer
# ---------------------------------------------------------------------------

class NGOAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = NGOAddress
        fields = [
            'id',
            'address_line1',
            'address_line2',
            'city',
            'district',
            'state',
            'pincode',
            'service_areas',
            'latitude',
            'longitude',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ---------------------------------------------------------------------------
# 2. NGOLegalInfoSerializer
# ---------------------------------------------------------------------------

class NGOLegalInfoSerializer(serializers.ModelSerializer):
    is_csr_eligible = serializers.BooleanField(read_only=True)

    class Meta:
        model = NGOLegalInfo
        fields = [
            'id',
            'organisation_type',
            'registering_authority',
            'registration_number',
            'darpan_id',
            'pan_number',
            'registration_state',
            'chief_trustee_name',
            'chief_trustee_designation',
            'has_10_23c',
            'ten_23c_subclause',
            'ten_23c_order_number',
            'ten_23c_validity',
            'has_12a',
            'twelve_a_number',
            'twelve_a_validity',
            'has_80g',
            'eighty_g_number',
            'eighty_g_validity',
            'has_fcra',
            'fcra_number',
            'fcra_validity',
            'has_csr_1',
            'csr_registration_number',
            'csr_registration_date',
            'is_csr_eligible',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_csr_eligible', 'created_at', 'updated_at']

    def to_internal_value(self, data):
        if 'pan_number' in data and isinstance(data['pan_number'], str):
            data = data.copy()
            data['pan_number'] = data['pan_number'].strip().upper()
        if 'csr_registration_number' in data and isinstance(data['csr_registration_number'], str):
            data = data.copy()
            data['csr_registration_number'] = data['csr_registration_number'].strip().upper()
        return super().to_internal_value(data)

    def validate_pan_number(self, value):
        """Normalize PAN number to uppercase."""
        if value:
            return value.strip().upper()
        return value

    def validate_csr_registration_number(self, value):
        """Normalize CSR-1 registration number to uppercase."""
        if value:
            return value.strip().upper()
        return value

    def validate_darpan_id(self, value):
        if value:
            return value.strip()
        return value

    def validate_registration_number(self, value):
        if value:
            return value.strip()
        return value

    def validate(self, data):
        """
        Enforce Option B Conditional Rule:
          - If has_12a is True, twelve_a_number must be non-empty.
          - If has_80g is True, eighty_g_number must be non-empty.
          - If has_fcra is True, fcra_number must be non-empty.
          - If has_csr_1 is True, csr_registration_number must be non-empty.
        Also check field-locking if status >= SUBMITTED.
        """
        # Determine effective values (merged with existing instance if partial update)
        instance = self.instance
        has_10_23c = data.get('has_10_23c', instance.has_10_23c if instance else False)
        ten_23c_order_num = data.get('ten_23c_order_number', instance.ten_23c_order_number if instance else '')
        has_12a = data.get('has_12a', instance.has_12a if instance else False)
        twelve_a_num = data.get('twelve_a_number', instance.twelve_a_number if instance else '')
        has_80g = data.get('has_80g', instance.has_80g if instance else False)
        eighty_g_num = data.get('eighty_g_number', instance.eighty_g_number if instance else '')
        has_fcra = data.get('has_fcra', instance.has_fcra if instance else False)
        fcra_num = data.get('fcra_number', instance.fcra_number if instance else '')
        has_csr_1 = data.get('has_csr_1', instance.has_csr_1 if instance else False)
        csr_num = data.get('csr_registration_number', instance.csr_registration_number if instance else '')

        errors = {}
        if has_10_23c and not ten_23c_order_num.strip():
            errors['ten_23c_order_number'] = _('Section 10(23C) approval order number is required when has_10_23c is True.')
        if has_12a and not twelve_a_num.strip():
            errors['twelve_a_number'] = _('12A certificate number is required when has_12a is True.')
        if has_80g and not eighty_g_num.strip():
            errors['eighty_g_number'] = _('80G certificate number is required when has_80g is True.')
        if has_fcra and not fcra_num.strip():
            errors['fcra_number'] = _('FCRA registration number is required when has_fcra is True.')
        if has_csr_1 and not csr_num.strip():
            errors['csr_registration_number'] = _('CSR-1 registration number is required when has_csr_1 is True.')

        if errors:
            raise serializers.ValidationError(errors)

        # Field locking rule: if status >= SUBMITTED, identifiers cannot be changed
        if instance and hasattr(instance, 'ngo'):
            ngo_status = instance.ngo.status
            if ngo_status in ('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'SUSPENDED'):
                for field in ('registration_number', 'darpan_id', 'pan_number', 'csr_registration_number'):
                    if field in data and getattr(instance, field) != data[field]:
                        raise serializers.ValidationError({
                            field: _(f'{field} cannot be modified once application is submitted.')
                        })

        return data


# ---------------------------------------------------------------------------
# 3. NGOBankInfoSerializer
# ---------------------------------------------------------------------------

class NGOBankInfoSerializer(serializers.ModelSerializer):
    """
    Bank details serializer for NGO Owner.
    account_number is WRITE_ONLY so full value is NEVER in GET responses.
    masked_account_number property is provided on GET for owner reference.
    """
    masked_account_number = serializers.CharField(read_only=True)
    account_number = serializers.CharField(write_only=True, required=True, validators=[validate_account_number])

    class Meta:
        model = NGOBankInfo
        fields = [
            'id',
            'bank_name',
            'account_holder_name',
            'account_number',
            'masked_account_number',
            'ifsc_code',
            'branch_name',
            'account_type',
            'is_verified',
            'verified_by',
            'verified_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'is_verified',
            'verified_by',
            'verified_at',
            'created_at',
            'updated_at',
            'masked_account_number',
        ]

    def to_internal_value(self, data):
        if 'ifsc_code' in data and isinstance(data['ifsc_code'], str):
            data = data.copy()
            data['ifsc_code'] = data['ifsc_code'].strip().upper()
        if 'account_number' in data and isinstance(data['account_number'], str):
            data = data.copy()
            data['account_number'] = data['account_number'].strip()
        return super().to_internal_value(data)

    def validate_ifsc_code(self, value):
        if value:
            return value.strip().upper()
        return value

    def validate_account_number(self, value):
        if value:
            return value.strip()
        return value

    def validate(self, data):
        """
        Bank info is editable ONLY if:
          ngo.status == 'DRAFT'
          OR (ngo.status == 'CORRECTION_REQUIRED' and ngo.verification.bank_correction_requested == True)
        """
        instance = self.instance
        if instance and hasattr(instance, 'ngo'):
            ngo = instance.ngo
            v = getattr(ngo, 'verification', None)
            bank_correction_allowed = v and v.bank_correction_requested if v else False

            is_editable = (
                ngo.status == 'DRAFT'
                or (ngo.status == 'CORRECTION_REQUIRED' and bank_correction_allowed)
            )

            if not is_editable:
                raise serializers.ValidationError(
                    _('Bank details are locked and cannot be modified at this stage.')
                )

        return data


# ---------------------------------------------------------------------------
# 4. NGOLeadershipSerializer
# ---------------------------------------------------------------------------

class NGOLeadershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = NGOLeadership
        fields = [
            'id',
            'full_name',
            'designation',
            'phone',
            'email',
            'is_primary_contact',
            'is_active',
            'order',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        """
        Enforce that only ONE active primary contact exists per NGO.
        """
        ngo = self.context.get('ngo') or (self.instance.ngo if self.instance else None)
        is_primary = data.get('is_primary_contact', self.instance.is_primary_contact if self.instance else False)
        is_active = data.get('is_active', self.instance.is_active if self.instance else True)

        if ngo and is_primary and is_active:
            qs = NGOLeadership.objects.filter(ngo=ngo, is_primary_contact=True, is_active=True)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    'is_primary_contact': _('An active primary contact already exists for this NGO.')
                })
        return data


# ---------------------------------------------------------------------------
# 5. NGODocumentSerializer
# ---------------------------------------------------------------------------

class NGODocumentSerializer(serializers.ModelSerializer):
    """
    Document upload and metadata serializer.
    Validates file extension, size, and document_type.
    Exposes secure download_url route instead of raw media path.
    """
    file = serializers.FileField(write_only=True, required=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = NGODocument
        fields = [
            'id',
            'document_type',
            'file',
            'download_url',
            'original_filename',
            'file_size_bytes',
            'mime_type',
            'is_active',
            'is_verified',
            'verified_at',
            'rejection_reason',
            'uploaded_at',
            'replaced_at',
            'replaces',
        ]
        read_only_fields = [
            'id',
            'download_url',
            'original_filename',
            'file_size_bytes',
            'mime_type',
            'is_active',
            'is_verified',
            'verified_at',
            'rejection_reason',
            'uploaded_at',
            'replaced_at',
            'replaces',
        ]

    def get_download_url(self, obj):
        return f'/api/v1/ngo/documents/{obj.id}/download/'

    def validate_file(self, value):
        """Validate file extension and file size by document_type."""
        # 1. Extension check
        try:
            validate_document_extension(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message)

        # 2. File size limits
        size_bytes = value.size
        doc_type = self.initial_data.get('document_type')

        # Size caps:
        # TRUST_DEED, AUDITED_FINANCIALS -> 10 MB
        # PAN_CARD, CANCELLED_CHEQUE, REPRESENTATIVE_ID, OTHER -> 2 MB
        # All others -> 5 MB
        if doc_type in (NGODocument.DocumentType.TRUST_DEED, NGODocument.DocumentType.AUDITED_FINANCIALS):
            max_size = 10 * 1024 * 1024
            max_desc = '10 MB'
        elif doc_type in (
            NGODocument.DocumentType.PAN_CARD,
            NGODocument.DocumentType.CANCELLED_CHEQUE,
            NGODocument.DocumentType.REPRESENTATIVE_ID,
            NGODocument.DocumentType.OTHER,
        ):
            max_size = 2 * 1024 * 1024
            max_desc = '2 MB'
        else:
            max_size = 5 * 1024 * 1024
            max_desc = '5 MB'

        if size_bytes > max_size:
            raise serializers.ValidationError(
                _(f'File size ({size_bytes / (1024 * 1024):.1f} MB) exceeds maximum allowed {max_desc} for {doc_type}.')
            )

        return value


# ---------------------------------------------------------------------------
# 6. NGOProfileSerializer (Owner Serializer)
# ---------------------------------------------------------------------------

class NGOOwnerVerificationSerializer(serializers.ModelSerializer):
    """
    Sanitized verification state serializer for NGO owner.
    Exposes verification status, correction instructions, rejection reason,
    resubmission limits, and timestamps.
    HIDES admin_notes and risk_flags.
    """
    can_resubmit = serializers.BooleanField(read_only=True)

    class Meta:
        model = NGOVerification
        fields = [
            'id',
            'status',
            'gov_check_status',
            'is_csr_verified',
            'correction_instructions',
            'rejection_reason',
            'bank_correction_requested',
            'resubmission_count',
            'resubmission_limit',
            'admin_reopened',
            'can_resubmit',
            'submitted_at',
            'last_submitted_at',
            'decision_at',
            'resubmission_deadline',
        ]
        read_only_fields = fields


class NGOProfileSerializer(serializers.ModelSerializer):
    """
    NGO Owner profile serializer for GET/POST/PATCH.
    Includes nested address, legal_info, bank_info, leadership, documents, verification.
    `status`, `is_active`, `is_public`, `verified_at` are read_only.
    """
    is_public = serializers.BooleanField(read_only=True)
    address = NGOAddressSerializer(read_only=True)
    legal_info = NGOLegalInfoSerializer(read_only=True)
    bank_info = NGOBankInfoSerializer(read_only=True)
    leadership = NGOLeadershipSerializer(many=True, read_only=True)
    documents = NGODocumentSerializer(many=True, read_only=True)
    verification = NGOOwnerVerificationSerializer(read_only=True)

    class Meta:
        model = NGOProfile
        fields = [
            'id',
            'legal_name',
            'display_name',
            'gujarati_name',
            'slug',
            'category',
            'description',
            'mission_statement',
            'year_established',
            'website',
            'official_email',
            'official_phone',
            'logo',
            'cover_image',
            'status',
            'is_active',
            'is_public',
            'verified_at',
            'created_at',
            'updated_at',
            'address',
            'legal_info',
            'bank_info',
            'leadership',
            'documents',
            'verification',
        ]
        read_only_fields = [
            'id',
            'slug',
            'status',
            'is_active',
            'is_public',
            'verified_at',
            'created_at',
            'updated_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.logo:
            try:
                if not instance.logo.storage.exists(instance.logo.name):
                    data['logo'] = None
            except Exception:
                data['logo'] = None
        if instance.cover_image:
            try:
                if not instance.cover_image.storage.exists(instance.cover_image.name):
                    data['cover_image'] = None
            except Exception:
                data['cover_image'] = None
        return data


# ---------------------------------------------------------------------------
# 7. NGOPublicSerializer (Safe Public Directory & Profile Response)
# ---------------------------------------------------------------------------

class NGOPublicLeaderSerializer(serializers.ModelSerializer):
    """Public leader serializer — name and designation ONLY. Excludes phone & email."""
    class Meta:
        model = NGOLeadership
        fields = ['full_name', 'designation', 'is_primary_contact']


class NGOPublicSerializer(serializers.ModelSerializer):
    """
    SAFE public response serializer for APPROVED NGOs (`status=APPROVED and is_active=True`).

    EXCLUDES:
      - All bank details (account_number, ifsc_code, bank_name)
      - PAN number & registration number
      - 12A/80G/FCRA certificate numbers
      - Chief trustee details, leader phone/email
      - Geolocation coordinates (latitude, longitude)
      - Private document files
      - Internal verification notes & timestamps
    """
    is_public = serializers.BooleanField(read_only=True)
    city = serializers.SerializerMethodField()
    district = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    service_areas = serializers.SerializerMethodField()
    has_12a = serializers.SerializerMethodField()
    has_80g = serializers.SerializerMethodField()
    has_fcra = serializers.SerializerMethodField()
    has_csr_1 = serializers.SerializerMethodField()
    is_csr_verified = serializers.SerializerMethodField()
    darpan_id = serializers.SerializerMethodField()
    leadership = serializers.SerializerMethodField()

    class Meta:
        model = NGOProfile
        fields = [
            'id',
            'display_name',
            'gujarati_name',
            'slug',
            'category',
            'description',
            'mission_statement',
            'year_established',
            'website',
            'official_email',
            'official_phone',
            'logo',
            'cover_image',
            'is_public',
            'city',
            'district',
            'state',
            'service_areas',
            'has_12a',
            'has_80g',
            'has_fcra',
            'has_csr_1',
            'is_csr_verified',
            'darpan_id',
            'leadership',
        ]

    def get_city(self, obj):
        return obj.address.city if hasattr(obj, 'address') and obj.address else ''

    def get_district(self, obj):
        return obj.address.district if hasattr(obj, 'address') and obj.address else ''

    def get_state(self, obj):
        return obj.address.state if hasattr(obj, 'address') and obj.address else ''

    def get_service_areas(self, obj):
        return obj.address.service_areas if hasattr(obj, 'address') and obj.address else ''

    def get_has_12a(self, obj):
        return obj.legal_info.has_12a if hasattr(obj, 'legal_info') and obj.legal_info else False

    def get_has_80g(self, obj):
        return obj.legal_info.has_80g if hasattr(obj, 'legal_info') and obj.legal_info else False

    def get_has_fcra(self, obj):
        return obj.legal_info.has_fcra if hasattr(obj, 'legal_info') and obj.legal_info else False

    def get_has_csr_1(self, obj):
        return obj.legal_info.has_csr_1 if hasattr(obj, 'legal_info') and obj.legal_info else False

    def get_is_csr_verified(self, obj):
        """P0-2 Fix: Returns True ONLY if NGO is approved, active, and admin-verified for CSR."""
        if obj.status != NGOProfile.Status.APPROVED or not getattr(obj, 'is_active', False):
            return False
        verif = getattr(obj, 'verification', None)
        return bool(verif and verif.is_csr_verified)

    def get_darpan_id(self, obj):
        return obj.legal_info.darpan_id if hasattr(obj, 'legal_info') and obj.legal_info else ''

    def get_leadership(self, obj):
        active_leaders = obj.leadership.filter(is_active=True)
        return NGOPublicLeaderSerializer(active_leaders, many=True).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.logo:
            try:
                if not instance.logo.storage.exists(instance.logo.name):
                    data['logo'] = None
            except Exception:
                data['logo'] = None
        if instance.cover_image:
            try:
                if not instance.cover_image.storage.exists(instance.cover_image.name):
                    data['cover_image'] = None
            except Exception:
                data['cover_image'] = None
        return data


# ---------------------------------------------------------------------------
# 8. NGOAdminSerializer (Full Inspection Serializer for Admin Only)
# ---------------------------------------------------------------------------

class NGOAdminBankInfoSerializer(serializers.ModelSerializer):
    """Admin-only bank serializer — includes UNMASKED account number for verification."""
    class Meta:
        model = NGOBankInfo
        fields = [
            'id',
            'bank_name',
            'account_holder_name',
            'account_number',  # Unmasked for Admin verification
            'ifsc_code',
            'branch_name',
            'account_type',
            'is_verified',
            'verified_by',
            'verified_at',
            'created_at',
            'updated_at',
        ]


class NGOAdminVerificationSerializer(serializers.ModelSerializer):
    """Admin verification state serializer."""
    can_resubmit = serializers.BooleanField(read_only=True)

    class Meta:
        model = NGOVerification
        fields = [
            'id',
            'status',
            'gov_check_status',
            'gov_check_source',
            'gov_check_details',
            'gov_check_completed_at',
            'is_csr_verified',
            'csr_verified_at',
            'csr_verified_by',
            'csr_review_notes',
            'reviewed_by',
            'admin_notes',
            'risk_flags',
            'correction_instructions',
            'rejection_reason',
            'bank_correction_requested',
            'resubmission_count',
            'resubmission_limit',
            'admin_reopened',
            'can_resubmit',
            'submitted_at',
            'last_submitted_at',
            'review_started_at',
            'decision_at',
            'resubmission_deadline',
            'created_at',
            'updated_at',
        ]


class NGOAdminSerializer(serializers.ModelSerializer):
    """
    Full inspection serializer for Admin use ONLY.
    Exposes full legal info, unmasked bank details, all documents, and verification state.
    """
    is_public = serializers.BooleanField(read_only=True)
    address = NGOAddressSerializer(read_only=True)
    legal_info = NGOLegalInfoSerializer(read_only=True)
    bank_info = NGOAdminBankInfoSerializer(read_only=True)
    leadership = NGOLeadershipSerializer(many=True, read_only=True)
    documents = NGODocumentSerializer(many=True, read_only=True)
    verification = NGOAdminVerificationSerializer(read_only=True)

    class Meta:
        model = NGOProfile
        fields = [
            'id',
            'user',
            'legal_name',
            'display_name',
            'gujarati_name',
            'slug',
            'category',
            'description',
            'mission_statement',
            'year_established',
            'website',
            'official_email',
            'official_phone',
            'logo',
            'cover_image',
            'status',
            'is_active',
            'is_public',
            'verified_at',
            'created_at',
            'updated_at',
            'address',
            'legal_info',
            'bank_info',
            'leadership',
            'documents',
            'verification',
        ]


# ---------------------------------------------------------------------------
# 9. NGOVerificationHistorySerializer (Read-Only Audit Log)
# ---------------------------------------------------------------------------

class NGOVerificationHistorySerializer(serializers.ModelSerializer):
    """Read-only serializer for history audit log."""
    performed_by_email = serializers.SerializerMethodField()

    class Meta:
        model = NGOVerificationHistory
        fields = [
            'id',
            'ngo',
            'performed_by',
            'performed_by_email',
            'actor_type',
            'previous_status',
            'new_status',
            'reason',
            'metadata',
            'timestamp',
        ]
        read_only_fields = fields

    def get_performed_by_email(self, obj):
        return obj.performed_by.email if obj.performed_by else 'System'


