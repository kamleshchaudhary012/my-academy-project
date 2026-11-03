"""
CSR Partnership Serializers — Phase CSR-2.1
===========================================
Serializers for CSRPartnership bilateral engagement and MoU tracking:
- CSRPartnershipListSerializer: Compact summary for Company & NGO dashboards.
- CSRPartnershipDetailSerializer: Full bilateral partnership dossier with milestones.
- CSRPartnershipDisbursementSerializer: Informational off-platform disbursement reporting.
"""

import os
from decimal import Decimal
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from csr.models import (
    CSRPartnership,
    CSRPartnershipStatus,
)
from csr.serializers.milestone_serializers import PartnershipMilestoneSerializer


class CSRPartnershipListSerializer(serializers.ModelSerializer):
    """
    Compact summary serializer for bilateral CSR partnerships.
    """
    company_name = serializers.CharField(source='company.company_name', read_only=True)
    ngo_legal_name = serializers.CharField(source='ngo.legal_name', read_only=True)
    ngo_display_name = serializers.CharField(source='ngo.display_name', read_only=True)
    requirement_title = serializers.CharField(source='requirement.title', read_only=True)
    requirement_slug = serializers.CharField(source='requirement.slug', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    milestone_count = serializers.SerializerMethodField()
    completed_milestone_count = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = CSRPartnership
        fields = [
            'id',
            'partnership_code',
            'company',
            'company_name',
            'ngo',
            'ngo_legal_name',
            'ngo_display_name',
            'requirement',
            'requirement_title',
            'requirement_slug',
            'agreed_funding_amount',
            'disbursed_amount_reported',
            'execution_start_date',
            'target_completion_date',
            'actual_completion_date',
            'status',
            'status_display',
            'milestone_count',
            'completed_milestone_count',
            'progress_percentage',
            'created_at',
        ]
        read_only_fields = fields

    def get_milestone_count(self, obj):
        return obj.milestones.count()

    def get_completed_milestone_count(self, obj):
        return obj.milestones.filter(status='VERIFIED').count()

    def get_progress_percentage(self, obj):
        total = obj.milestones.count()
        if total == 0:
            return 0
        completed = obj.milestones.filter(status='VERIFIED').count()
        return round((completed / total) * 100, 1)


class CSRPartnershipDetailSerializer(serializers.ModelSerializer):
    """
    Comprehensive bilateral partnership detail representation including nested milestones.
    """
    company_name = serializers.CharField(source='company.company_name', read_only=True)
    company_city = serializers.CharField(source='company.city', read_only=True)
    company_state = serializers.CharField(source='company.state', read_only=True)
    ngo_legal_name = serializers.CharField(source='ngo.legal_name', read_only=True)
    ngo_display_name = serializers.CharField(source='ngo.display_name', read_only=True)
    requirement_title = serializers.CharField(source='requirement.title', read_only=True)
    requirement_slug = serializers.CharField(source='requirement.slug', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    has_signed_mou = serializers.SerializerMethodField()
    signed_mou_name = serializers.SerializerMethodField()
    signed_mou_url = serializers.SerializerMethodField()
    milestones = PartnershipMilestoneSerializer(many=True, read_only=True)

    class Meta:
        model = CSRPartnership
        fields = [
            'id',
            'partnership_code',
            'company',
            'company_name',
            'company_city',
            'company_state',
            'ngo',
            'ngo_legal_name',
            'ngo_display_name',
            'requirement',
            'requirement_title',
            'requirement_slug',
            'support_request',
            'agreed_funding_amount',
            'disbursed_amount_reported',
            'execution_start_date',
            'target_completion_date',
            'actual_completion_date',
            'status',
            'status_display',
            'has_signed_mou',
            'signed_mou_name',
            'signed_mou_url',
            'milestones',
            'created_at',
            'updated_at',
            'completed_at',
        ]
        read_only_fields = fields

    def get_has_signed_mou(self, obj):
        return bool(obj.signed_mou_document)

    def get_signed_mou_name(self, obj):
        if obj.signed_mou_document:
            return os.path.basename(obj.signed_mou_document.name)
        return None

    def get_signed_mou_url(self, obj):
        if obj.signed_mou_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.signed_mou_document.url) if request else obj.signed_mou_document.url
        return None


class CSRPartnershipDisbursementSerializer(serializers.Serializer):
    """
    Informational off-platform disbursement reporting serializer.
    CSR funds remain 100% off-platform; this reports corporate bank transfer sums for audit.
    """
    disbursed_amount_reported = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        help_text=_('Cumulative amount in INR disbursed via direct corporate bank transfer to NGO.'),
    )
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        help_text=_('Amount disbursed (alias for disbursed_amount_reported).'),
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=1000,
        help_text=_('Optional disbursement reference or bank transaction remarks (informational only).'),
    )
    transfer_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=255,
        help_text=_('Bank transfer reference number.'),
    )

    def validate(self, data):
        amount = data.get('disbursed_amount_reported')
        if amount is None:
            amount = data.get('amount')
        if amount is None:
            raise serializers.ValidationError({
                'disbursed_amount_reported': _('Reported disbursed amount is required.')
            })
        if amount < Decimal('0.00'):
            raise serializers.ValidationError({
                'disbursed_amount_reported': _('Reported disbursed amount cannot be negative.')
            })
        data['disbursed_amount_reported'] = amount

        notes = (data.get('notes') or '').strip()
        ref = (data.get('transfer_reference') or '').strip()
        if ref and ref not in notes:
            notes = f"{ref} - {notes}".strip(' -')
        data['notes'] = notes
        return data
