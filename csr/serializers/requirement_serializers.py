"""
CSR Requirement Serializers — Phase CSR-2.1
===========================================
Serializers for CSRRequirement proposal management:
- CSRRequirementListSerializer: Compact marketplace proposal card representation.
- CSRRequirementDetailSerializer: Full participant-facing proposal view.
- CSRRequirementWriteSerializer: NGO proposal creation and editing validation.
- CSRRequirementAdminSerializer: Administrative moderation and review serializer.
"""

import os
from decimal import Decimal
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from csr.models import (
    CSRRequirement,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CSRRequirementStatus,
)


class CSRRequirementListSerializer(serializers.ModelSerializer):
    """
    Compact marketplace listing representation for CSR Requirements.
    """
    ngo_legal_name = serializers.CharField(source='ngo.legal_name', read_only=True)
    ngo_display_name = serializers.CharField(source='ngo.display_name', read_only=True)
    category_display = serializers.CharField(source='get_schedule_vii_category_display', read_only=True)
    location_scope_display = serializers.CharField(source='get_location_scope_display', read_only=True)
    demographic_display = serializers.CharField(source='get_beneficiary_demographic_display', read_only=True)

    class Meta:
        model = CSRRequirement
        fields = [
            'id',
            'title',
            'slug',
            'ngo_legal_name',
            'ngo_display_name',
            'schedule_vii_category',
            'category_display',
            'state',
            'district',
            'location_scope',
            'location_scope_display',
            'beneficiary_demographic',
            'demographic_display',
            'target_beneficiary_count',
            'summary',
            'total_estimated_budget',
            'required_csr_funding',
            'committed_funding',
            'start_date',
            'expected_completion_date',
            'status',
            'created_at',
        ]
        read_only_fields = fields


class CSRRequirementDetailSerializer(serializers.ModelSerializer):
    """
    Comprehensive proposal detail serializer for corporate matching and NGO management.
    """
    ngo_legal_name = serializers.CharField(source='ngo.legal_name', read_only=True)
    ngo_display_name = serializers.CharField(source='ngo.display_name', read_only=True)
    ngo_category = serializers.CharField(source='ngo.category', read_only=True)
    category_display = serializers.CharField(source='get_schedule_vii_category_display', read_only=True)
    location_scope_display = serializers.CharField(source='get_location_scope_display', read_only=True)
    demographic_display = serializers.CharField(source='get_beneficiary_demographic_display', read_only=True)
    has_proposal_document = serializers.SerializerMethodField()
    has_detailed_budget_document = serializers.SerializerMethodField()
    has_impact_assessment_report = serializers.SerializerMethodField()
    proposal_document_name = serializers.SerializerMethodField()
    detailed_budget_document_name = serializers.SerializerMethodField()
    impact_assessment_report_name = serializers.SerializerMethodField()

    class Meta:
        model = CSRRequirement
        fields = [
            'id',
            'title',
            'slug',
            'ngo_legal_name',
            'ngo_display_name',
            'ngo_category',
            'schedule_vii_category',
            'category_display',
            'state',
            'district',
            'location_scope',
            'location_scope_display',
            'additional_districts',
            'beneficiary_demographic',
            'demographic_display',
            'target_beneficiary_count',
            'summary',
            'detailed_description',
            'expected_outcomes',
            'total_estimated_budget',
            'required_csr_funding',
            'committed_funding',
            'start_date',
            'expected_completion_date',
            'status',
            'has_proposal_document',
            'has_detailed_budget_document',
            'has_impact_assessment_report',
            'proposal_document_name',
            'detailed_budget_document_name',
            'impact_assessment_report_name',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_has_proposal_document(self, obj):
        return bool(obj.proposal_document)

    def get_has_detailed_budget_document(self, obj):
        return bool(obj.detailed_budget_document)

    def get_has_impact_assessment_report(self, obj):
        return bool(obj.impact_assessment_report)

    def get_proposal_document_name(self, obj):
        if obj.proposal_document:
            return os.path.basename(obj.proposal_document.name)
        return None

    def get_detailed_budget_document_name(self, obj):
        if obj.detailed_budget_document:
            return os.path.basename(obj.detailed_budget_document.name)
        return None

    def get_impact_assessment_report_name(self, obj):
        if obj.impact_assessment_report:
            return os.path.basename(obj.impact_assessment_report.name)
        return None


class CSRRequirementWriteSerializer(serializers.ModelSerializer):
    """
    Writable serializer for NGO proposal creation and draft editing.
    Enforces minimum financial bounds (₹10,000) and date ordering (completion >= start).
    """
    class Meta:
        model = CSRRequirement
        fields = [
            'id',
            'title',
            'schedule_vii_category',
            'state',
            'district',
            'location_scope',
            'additional_districts',
            'beneficiary_demographic',
            'target_beneficiary_count',
            'summary',
            'detailed_description',
            'expected_outcomes',
            'total_estimated_budget',
            'required_csr_funding',
            'committed_funding',
            'start_date',
            'expected_completion_date',
            'proposal_document',
            'detailed_budget_document',
            'impact_assessment_report',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'created_at',
            'updated_at',
        ]

    def to_internal_value(self, data):
        if isinstance(data, dict) and 'location_scope' in data:
            data = data.copy() if hasattr(data, 'copy') else dict(data)
            scope = data.get('location_scope')
            normalization_map = {
                'STATE_WIDE': LocationScope.MULTI_DISTRICT,
                'DISTRICT_LOCAL': LocationScope.SPECIFIC_DISTRICT,
                'PAN_INDIA': LocationScope.NATIONWIDE,
            }
            if scope in normalization_map:
                data['location_scope'] = normalization_map[scope]
        return super().to_internal_value(data)

    def validate_location_scope(self, value):
        normalization_map = {
            'STATE_WIDE': LocationScope.MULTI_DISTRICT,
            'DISTRICT_LOCAL': LocationScope.SPECIFIC_DISTRICT,
            'PAN_INDIA': LocationScope.NATIONWIDE,
        }
        canonical = normalization_map.get(value, value)
        if canonical not in LocationScope.values:
            raise serializers.ValidationError(_(f'"{value}" is not a valid choice.'))
        return canonical

    def validate_total_estimated_budget(self, value):
        if value is not None and value < Decimal('10000.00'):
            raise serializers.ValidationError(_('Total estimated budget must be at least ₹10,000.00.'))
        return value

    def validate_required_csr_funding(self, value):
        if value is not None and value < Decimal('10000.00'):
            raise serializers.ValidationError(_('Required CSR funding must be at least ₹10,000.00.'))
        return value

    def validate_committed_funding(self, value):
        if value is not None and value < Decimal('0.00'):
            raise serializers.ValidationError(_('Committed funding cannot be negative.'))
        return value

    def validate_additional_districts(self, value):
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError(_('additional_districts must be a list of district strings.'))
        return value or []

    def validate(self, data):
        errors = {}
        start = data.get('start_date', getattr(self.instance, 'start_date', None))
        completion = data.get('expected_completion_date', getattr(self.instance, 'expected_completion_date', None))

        if start and completion and completion < start:
            errors['expected_completion_date'] = _('Expected completion date must be on or after the start date.')

        total = data.get('total_estimated_budget', getattr(self.instance, 'total_estimated_budget', None))
        req = data.get('required_csr_funding', getattr(self.instance, 'required_csr_funding', None))
        committed = data.get('committed_funding', getattr(self.instance, 'committed_funding', Decimal('0.00')))

        if total is not None and req is not None and req > total:
            errors['required_csr_funding'] = _('Required CSR funding cannot exceed the total estimated budget.')

        if total is not None and req is not None and committed is not None:
            if (req + committed) > total:
                errors['committed_funding'] = _('Sum of committed funding and required CSR funding cannot exceed total budget.')

        if errors:
            raise serializers.ValidationError(errors)

        return data


class CSRRequirementAdminSerializer(serializers.ModelSerializer):
    """
    Full administrative moderation serializer for CSRRequirement.
    Includes moderation history, author identity, and rejection notes.
    """
    ngo_legal_name = serializers.CharField(source='ngo.legal_name', read_only=True)
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True, default=None)

    class Meta:
        model = CSRRequirement
        fields = [
            'id',
            'ngo',
            'ngo_legal_name',
            'created_by',
            'created_by_email',
            'title',
            'slug',
            'schedule_vii_category',
            'state',
            'district',
            'location_scope',
            'additional_districts',
            'beneficiary_demographic',
            'target_beneficiary_count',
            'summary',
            'detailed_description',
            'expected_outcomes',
            'total_estimated_budget',
            'required_csr_funding',
            'committed_funding',
            'start_date',
            'expected_completion_date',
            'status',
            'reviewed_by',
            'reviewed_by_email',
            'reviewed_at',
            'rejection_reason',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'ngo',
            'ngo_legal_name',
            'created_by',
            'created_by_email',
            'slug',
            'reviewed_by',
            'reviewed_by_email',
            'reviewed_at',
            'created_at',
            'updated_at',
        ]
