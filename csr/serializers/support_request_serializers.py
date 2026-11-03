"""
CSR Support Request Serializers — Phase CSR-2.1
===============================================
Serializers for CSRSupportRequest expressions of interest:
- CSRSupportRequestCreateSerializer: Corporate EOI submission validation.
- CSRSupportRequestReadSerializer: Bidirectional representation for Company outbox and NGO inbox.
- CSRSupportRequestDecisionSerializer: Accept/Reject/Withdraw action payload validator.
"""

import re
from decimal import Decimal
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from csr.models import (
    CSRSupportRequest,
    CSRSupportType,
    CSRSupportRequestStatus,
)

PHONE_REGEX = re.compile(r'^[\+\d\s\-]{7,20}$')


class CSRSupportRequestCreateSerializer(serializers.ModelSerializer):
    """
    Writable serializer for submitting a Corporate Support Request (Expression of Interest).
    Validates minimum proposed funding (₹1,000) and contact information.
    Server-managed fields (company, status, rejection_reason, etc.) are strictly read-only.
    """
    class Meta:
        model = CSRSupportRequest
        fields = [
            'id',
            'requirement',
            'proposed_funding',
            'support_type',
            'spoc_name',
            'spoc_email',
            'spoc_phone',
            'message',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
        ]

    def validate_proposed_funding(self, value):
        if value is not None and value < Decimal('1000.00'):
            raise serializers.ValidationError(_('Proposed funding amount must be at least ₹1,000.00.'))
        return value

    def validate_spoc_phone(self, value):
        if value:
            cleaned = value.strip()
            if not PHONE_REGEX.match(cleaned):
                raise serializers.ValidationError(_('Enter a valid phone number (7–20 digits/characters).'))
            return cleaned
        return value

    def validate_spoc_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError(_('SPOC name cannot be blank.'))
        return value.strip()

    def validate_message(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError(_('Expression of interest message cannot be blank.'))
        return value.strip()


class CSRSupportRequestReadSerializer(serializers.ModelSerializer):
    """
    Representation serializer for Corporate outbox, NGO inbox, and Admin inspection.
    """
    company_name = serializers.CharField(source='company.company_name', read_only=True)
    company_city = serializers.CharField(source='company.city', read_only=True)
    company_state = serializers.CharField(source='company.state', read_only=True)
    requirement_title = serializers.CharField(source='requirement.title', read_only=True)
    requirement_slug = serializers.CharField(source='requirement.slug', read_only=True)
    requirement_category = serializers.CharField(source='requirement.schedule_vii_category', read_only=True)
    ngo_legal_name = serializers.CharField(source='requirement.ngo.legal_name', read_only=True)
    ngo_display_name = serializers.CharField(source='requirement.ngo.display_name', read_only=True)
    support_type_display = serializers.CharField(source='get_support_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = CSRSupportRequest
        fields = [
            'id',
            'company',
            'company_name',
            'company_name_snapshot',
            'company_city',
            'company_state',
            'requirement',
            'requirement_title',
            'requirement_slug',
            'requirement_category',
            'ngo_legal_name',
            'ngo_display_name',
            'proposed_funding',
            'support_type',
            'support_type_display',
            'spoc_name',
            'spoc_email',
            'spoc_phone',
            'message',
            'status',
            'status_display',
            'rejection_reason',
            'withdrawal_reason',
            'reviewed_at',
            'expires_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class CSRSupportRequestDecisionSerializer(serializers.Serializer):
    """
    Action payload validator for accepting, rejecting, or withdrawing a support request.
    """
    class Action(serializers.ChoiceField):
        pass

    action = serializers.ChoiceField(
        choices=['ACCEPT', 'REJECT', 'WITHDRAW'],
        required=True,
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=2000,
    )

    def validate(self, data):
        action = data.get('action')
        reason = data.get('reason', '').strip()

        if action in ['REJECT', 'WITHDRAW'] and not reason:
            raise serializers.ValidationError({
                'reason': _(f"A detailed reason is required when performing action '{action}'.")
            })
        return data
