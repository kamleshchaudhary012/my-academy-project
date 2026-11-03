"""
CSR Company Serializers — Phase CSR-2.1
========================================
Serializers for CompanyProfile and CompanyCSRPreference models:
- CompanyProfileReadSerializer: Safe representation for company & platform viewers.
- CompanyProfileWriteSerializer: Onboarding & profile update validation.
- CompanyProfileAdminSerializer: Complete inspection serializer for administrative review.
- CompanyCSRPreferenceSerializer: Matchmaking preferences validation & representation.
"""

import os
import re
from decimal import Decimal
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CompanyVerificationStatus,
    ScheduleVIICategory,
    BeneficiaryDemographic,
    validate_cin_number,
    validate_pan_number,
    validate_pincode,
    validate_phone,
    validate_document_extension,
)

CIN_REGEX = re.compile(r'^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$')
PAN_REGEX = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$')
PINCODE_REGEX = re.compile(r'^\d{6}$')
PHONE_REGEX = re.compile(r'^[\+\d\s\-]{7,20}$')


class CompanyProfileReadSerializer(serializers.ModelSerializer):
    """
    Read-only public/participant representation of CompanyProfile.
    Masks sensitive PAN and hides internal verification metadata.
    """
    pan_number_masked = serializers.SerializerMethodField()
    has_pan = serializers.SerializerMethodField()
    has_verification_document = serializers.SerializerMethodField()
    verification_document_name = serializers.SerializerMethodField()
    verification_document_url = serializers.SerializerMethodField()

    class Meta:
        model = CompanyProfile
        fields = [
            'id',
            'company_name',
            'legal_name',
            'cin_number',
            'pan_number_masked',
            'has_pan',
            'csr_registration_number',
            'contact_person_name',
            'contact_person_designation',
            'contact_email',
            'contact_phone',
            'official_website',
            'registered_address',
            'city',
            'state',
            'pincode',
            'annual_csr_budget',
            'verification_status',
            'gov_check_status',
            'correction_instructions',
            'verified_at',
            'has_verification_document',
            'verification_document_name',
            'verification_document_url',
            'rejection_reason',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_pan_number_masked(self, obj):
        if obj.pan_number and len(obj.pan_number) == 10:
            return f"******{obj.pan_number[-4:]}"
        return ""

    def get_has_pan(self, obj):
        return bool(obj.pan_number)

    def get_has_verification_document(self, obj):
        return bool(obj.verification_document)

    def get_verification_document_name(self, obj):
        if obj.verification_document:
            return os.path.basename(obj.verification_document.name)
        return None

    def get_verification_document_url(self, obj):
        if obj.verification_document:
            try:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.verification_document.url)
                return obj.verification_document.url
            except Exception:
                return None
        return None


class CompanyProfileWriteSerializer(serializers.ModelSerializer):
    """
    Writable serializer for CompanyProfile onboarding and updates.
    Enforces format validation on CIN, PAN, Pincode, and Phone.
    Server-managed fields (id, verification_status, verified_by, etc.) are strictly read-only.
    """
    class Meta:
        model = CompanyProfile
        fields = [
            'id',
            'company_name',
            'legal_name',
            'cin_number',
            'pan_number',
            'csr_registration_number',
            'contact_person_name',
            'contact_person_designation',
            'contact_email',
            'contact_phone',
            'official_website',
            'registered_address',
            'city',
            'state',
            'pincode',
            'annual_csr_budget',
            'verification_status',
            'verification_document',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'verification_status',
            'created_at',
            'updated_at',
        ]

    def validate_cin_number(self, value):
        if value:
            cleaned = value.strip().upper()
            if not CIN_REGEX.match(cleaned):
                raise serializers.ValidationError(
                    _('Invalid CIN format. Expected 21-character MCA standard (e.g. L12345MH2020PLC123456).')
                )
            return cleaned
        return value

    def validate_pan_number(self, value):
        if value:
            cleaned = value.strip().upper()
            if not PAN_REGEX.match(cleaned):
                raise serializers.ValidationError(
                    _('Invalid PAN number format. Expected 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F).')
                )
            return cleaned
        return value

    def validate_pincode(self, value):
        if value:
            cleaned = value.strip()
            if not PINCODE_REGEX.match(cleaned):
                raise serializers.ValidationError(_('Pincode must be exactly 6 digits.'))
            return cleaned
        return value

    def validate_contact_phone(self, value):
        if value:
            cleaned = value.strip()
            if not PHONE_REGEX.match(cleaned):
                raise serializers.ValidationError(_('Enter a valid phone number (7–20 digits/characters).'))
            return cleaned
        return value

    def validate_annual_csr_budget(self, value):
        if value is not None and value < Decimal('0.00'):
            raise serializers.ValidationError(_('Annual CSR budget cannot be negative.'))
        return value


class CompanyProfileAdminSerializer(serializers.ModelSerializer):
    """
    Full administrative review serializer for CompanyProfile.
    Exposes unmasked PAN, rejection/suspension reasons, and review metadata.
    """
    user_email = serializers.EmailField(source='user.email', read_only=True)
    verified_by_email = serializers.EmailField(source='verified_by.email', read_only=True, default=None)
    has_verification_document = serializers.SerializerMethodField()
    verification_document_name = serializers.SerializerMethodField()
    verification_document_url = serializers.SerializerMethodField()

    class Meta:
        model = CompanyProfile
        fields = [
            'id',
            'user',
            'user_email',
            'company_name',
            'legal_name',
            'cin_number',
            'pan_number',
            'csr_registration_number',
            'contact_person_name',
            'contact_person_designation',
            'contact_email',
            'contact_phone',
            'official_website',
            'registered_address',
            'city',
            'state',
            'pincode',
            'annual_csr_budget',
            'verification_status',
            'gov_check_status',
            'gov_check_source',
            'gov_check_details',
            'gov_check_completed_at',
            'correction_instructions',
            'admin_notes',
            'has_verification_document',
            'verification_document_name',
            'verification_document_url',
            'rejection_reason',
            'suspension_reason',
            'verified_at',
            'verified_by',
            'verified_by_email',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user',
            'user_email',
            'verified_at',
            'verified_by',
            'verified_by_email',
            'created_at',
            'updated_at',
        ]

    def get_has_verification_document(self, obj):
        return bool(obj.verification_document)

    def get_verification_document_name(self, obj):
        if obj.verification_document:
            return os.path.basename(obj.verification_document.name)
        return None

    def get_verification_document_url(self, obj):
        if obj.verification_document:
            try:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.verification_document.url)
                return obj.verification_document.url
            except Exception:
                return None
        return None


class CompanyCSRPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for CompanyCSRPreference matchmaking configuration.
    Validates JSON list fields, budget consistency (min <= max), and duration limits.
    """
    company_name = serializers.CharField(source='company.company_name', read_only=True)

    class Meta:
        model = CompanyCSRPreference
        fields = [
            'id',
            'company',
            'company_name',
            'preferred_categories',
            'preferred_states',
            'preferred_districts',
            'is_nationwide',
            'has_no_location_pref',
            'min_budget',
            'max_budget',
            'preferred_duration_months',
            'preferred_beneficiaries',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'company',
            'company_name',
            'created_at',
            'updated_at',
        ]

    def validate_preferred_categories(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(_('preferred_categories must be a list of Schedule VII category keys.'))
        valid_choices = set(ScheduleVIICategory.values)
        for cat in value:
            if cat not in valid_choices:
                raise serializers.ValidationError(_(f"'{cat}' is not a valid Schedule VII category."))
        return value

    def validate_preferred_beneficiaries(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(_('preferred_beneficiaries must be a list of demographic keys.'))
        valid_choices = set(BeneficiaryDemographic.values)
        for b in value:
            if b not in valid_choices:
                raise serializers.ValidationError(_(f"'{b}' is not a valid beneficiary demographic."))
        return value

    def validate_preferred_states(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(_('preferred_states must be a list of state names.'))
        return value

    def validate_preferred_districts(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(_('preferred_districts must be a list of district names.'))
        return value

    def validate_min_budget(self, value):
        if value is not None and value < Decimal('0.00'):
            raise serializers.ValidationError(_('Minimum budget cannot be negative.'))
        return value

    def validate_max_budget(self, value):
        if value is not None and value < Decimal('0.00'):
            raise serializers.ValidationError(_('Maximum budget cannot be negative.'))
        return value

    def validate_preferred_duration_months(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError(_('Preferred duration must be at least 1 month.'))
        return value

    def validate(self, data):
        min_b = data.get('min_budget', getattr(self.instance, 'min_budget', Decimal('0.00')))
        max_b = data.get('max_budget', getattr(self.instance, 'max_budget', Decimal('0.00')))

        if min_b is not None and max_b is not None and max_b > Decimal('0.00'):
            if min_b > max_b:
                raise serializers.ValidationError({
                    'min_budget': _('Minimum budget cannot exceed maximum budget.')
                })
        return data
