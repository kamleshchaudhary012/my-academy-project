"""
CSR Financial & Transparency Serializers
=========================================
Handles itemized off-platform corporate bank disbursements, NGO receipt acknowledgements,
project expense reporting with invoices, evidence verification, and multi-dimensional
financial reconciliation dossiers.
"""

import os
from decimal import Decimal
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from csr.models import (
    CSRPartnership,
    PartnershipMilestone,
    CSRDisbursement,
    CSRExpense,
    CSRPaymentMode,
    CSRDisbursementReviewStatus,
    CSRNgoAcknowledgementStatus,
    CSRExpenseCategory,
    CSRExpenseReviewStatus,
    CSRGrantChangeRequest,
    CSRGrantChangeStatus,
    validate_document_extension,
)



class CSRDisbursementSerializer(serializers.ModelSerializer):
    """Full detail view of an itemized off-platform corporate bank disbursement."""
    partnership_code = serializers.CharField(source='partnership.partnership_code', read_only=True)
    payment_reference = serializers.CharField(source='transfer_reference', read_only=True)
    disbursement_notes = serializers.CharField(source='notes', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    review_status_display = serializers.CharField(source='get_review_status_display', read_only=True)
    ngo_acknowledgement_status_display = serializers.CharField(
        source='get_ngo_acknowledgement_status_display', read_only=True
    )
    reported_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    ngo_acknowledged_by_name = serializers.SerializerMethodField()
    evidence_document_name = serializers.SerializerMethodField()
    evidence_document_url = serializers.SerializerMethodField()
    ngo_receipt_document_name = serializers.SerializerMethodField()
    ngo_receipt_document_url = serializers.SerializerMethodField()

    class Meta:
        model = CSRDisbursement
        fields = [
            'id',
            'partnership',
            'partnership_code',
            'amount',
            'currency',
            'disbursement_date',
            'transfer_reference',
            'payment_reference',
            'payment_mode',
            'payment_mode_display',
            'evidence_document',
            'evidence_document_name',
            'evidence_document_url',
            'notes',
            'disbursement_notes',
            'reported_by',
            'reported_by_name',
            'review_status',
            'review_status_display',
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_at',
            'review_notes',
            'ngo_acknowledgement_status',
            'ngo_acknowledgement_status_display',
            'ngo_acknowledged_by',
            'ngo_acknowledged_by_name',
            'ngo_acknowledged_at',
            'ngo_acknowledgement_notes',
            'ngo_receipt_document',
            'ngo_receipt_document_name',
            'ngo_receipt_document_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_reported_by_name(self, obj):
        if obj.reported_by:
            return obj.reported_by.get_full_name() or obj.reported_by.email
        return None

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.email
        return None

    def get_ngo_acknowledged_by_name(self, obj):
        if obj.ngo_acknowledged_by:
            return obj.ngo_acknowledged_by.get_full_name() or obj.ngo_acknowledged_by.email
        return None

    def get_evidence_document_name(self, obj):
        if obj.evidence_document:
            return os.path.basename(obj.evidence_document.name)
        return None

    def get_evidence_document_url(self, obj):
        if obj.evidence_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.evidence_document.url) if request else obj.evidence_document.url
        return None

    def get_ngo_receipt_document_name(self, obj):
        if obj.ngo_receipt_document:
            return os.path.basename(obj.ngo_receipt_document.name)
        return None

    def get_ngo_receipt_document_url(self, obj):
        if obj.ngo_receipt_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.ngo_receipt_document.url) if request else obj.ngo_receipt_document.url
        return None



class CSRDisbursementCreateSerializer(serializers.Serializer):
    """Input serializer for corporate reporting of off-platform bank disbursement."""
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('1.00'),
        required=True,
        error_messages={
            'min_value': _('Disbursed amount must be greater than zero.'),
            'required': _('Disbursed amount is required.'),
        }
    )
    disbursement_date = serializers.DateField(required=False)
    transfer_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payment_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payment_mode = serializers.ChoiceField(choices=CSRPaymentMode.choices, default=CSRPaymentMode.NEFT)
    evidence_document = serializers.FileField(
        required=False,
        validators=[validate_document_extension],
        allow_null=True,
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    disbursement_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        # Support frontend aliases payment_reference -> transfer_reference and disbursement_notes -> notes
        ref = data.get('transfer_reference') or data.get('payment_reference') or ''
        data['transfer_reference'] = str(ref).strip()
        if 'payment_reference' in data:
            data.pop('payment_reference')

        note = data.get('notes') or data.get('disbursement_notes') or ''
        data['notes'] = str(note).strip()
        if 'disbursement_notes' in data:
            data.pop('disbursement_notes')

        return data


class CSRDisbursementReviewSerializer(serializers.Serializer):
    """Input serializer for administrative or corporate evidence review."""
    decision = serializers.ChoiceField(choices=['VERIFY', 'REJECT'], required=True)
    review_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data.get('decision') == 'REJECT' and not str(data.get('review_notes', '')).strip():
            raise serializers.ValidationError({
                'review_notes': _('Review notes explaining the rejection reason are required.')
            })
        return data


class CSRDisbursementAcknowledgeSerializer(serializers.Serializer):
    """Input serializer for NGO receipt acknowledgement or dispute."""
    decision = serializers.ChoiceField(choices=['ACKNOWLEDGE', 'DISPUTE'], required=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    receipt_document = serializers.FileField(
        required=False,
        validators=[validate_document_extension],
        allow_null=True,
    )

    def validate(self, data):
        if data.get('decision') == 'DISPUTE' and not str(data.get('notes', '')).strip():
            raise serializers.ValidationError({
                'notes': _('Notes explaining the dispute or non-receipt are required.')
            })
        return data


class CSRExpenseSerializer(serializers.ModelSerializer):
    """Full detail view of an itemized ground project expenditure."""
    partnership_code = serializers.CharField(source='partnership.partnership_code', read_only=True)
    milestone_title = serializers.CharField(source='milestone.title', read_only=True, default=None)
    milestone_sequence = serializers.IntegerField(source='milestone.sequence_number', read_only=True, default=None)
    expense_category_display = serializers.CharField(source='get_expense_category_display', read_only=True)
    review_status_display = serializers.CharField(source='get_review_status_display', read_only=True)
    reported_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    invoice_document_name = serializers.SerializerMethodField()
    invoice_document_url = serializers.SerializerMethodField()

    class Meta:
        model = CSRExpense
        fields = [
            'id',
            'partnership',
            'partnership_code',
            'milestone',
            'milestone_title',
            'milestone_sequence',
            'expense_category',
            'expense_category_display',
            'title',
            'description',
            'amount',
            'currency',
            'expense_date',
            'vendor_payee',
            'invoice_number',
            'invoice_document',
            'invoice_document_name',
            'invoice_document_url',
            'review_status',
            'review_status_display',
            'reported_by',
            'reported_by_name',
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_at',
            'review_notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_reported_by_name(self, obj):
        if obj.reported_by:
            return obj.reported_by.get_full_name() or obj.reported_by.email
        return None

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.email
        return None

    def get_invoice_document_name(self, obj):
        if obj.invoice_document:
            return os.path.basename(obj.invoice_document.name)
        return None

    def get_invoice_document_url(self, obj):
        if obj.invoice_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.invoice_document.url) if request else obj.invoice_document.url
        return None



class CSRExpenseCreateSerializer(serializers.Serializer):
    """Input serializer for NGO ground project expenditure reporting."""
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('1.00'),
        required=True,
    )
    title = serializers.CharField(max_length=255, required=True)
    description = serializers.CharField(required=False, allow_blank=True)
    expense_category = serializers.ChoiceField(
        choices=CSRExpenseCategory.choices,
        default=CSRExpenseCategory.OPERATIONAL,
    )
    expense_date = serializers.DateField(required=False)
    vendor_payee = serializers.CharField(max_length=255, required=False, allow_blank=True)
    invoice_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    milestone = serializers.UUIDField(required=False, allow_null=True)
    invoice_document = serializers.FileField(
        required=False,
        validators=[validate_document_extension],
        allow_null=True,
    )


class CSRExpenseReviewSerializer(serializers.Serializer):
    """Input serializer for reviewing NGO project expenses."""
    decision = serializers.ChoiceField(choices=['VERIFY', 'REJECT'], required=True)
    review_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data.get('decision') == 'REJECT' and not str(data.get('review_notes', '')).strip():
            raise serializers.ValidationError({
                'review_notes': _('Review notes explaining why the expense was rejected are required.')
            })
        return data


# ===========================================================================
# Grant Change Request Serializers
# ===========================================================================

class CSRGrantChangeRequestSerializer(serializers.ModelSerializer):
    """Full detail view of a bilateral grant change request."""
    partnership_code = serializers.CharField(source='partnership.partnership_code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    admin_reviewed_by_name = serializers.SerializerMethodField()
    company_approved_by_name = serializers.SerializerMethodField()
    revised_budget_document_name = serializers.SerializerMethodField()
    revised_budget_document_url = serializers.SerializerMethodField()
    mou_amendment_document_name = serializers.SerializerMethodField()
    mou_amendment_document_url = serializers.SerializerMethodField()

    class Meta:
        model = CSRGrantChangeRequest
        fields = [
            'id',
            'partnership',
            'partnership_code',
            'current_commitment',
            'proposed_commitment',
            'reason',
            'revised_budget_document',
            'revised_budget_document_name',
            'revised_budget_document_url',
            'mou_amendment_document',
            'mou_amendment_document_name',
            'mou_amendment_document_url',
            'status',
            'status_display',
            'requested_by',
            'requested_by_name',
            'admin_reviewed_by',
            'admin_reviewed_by_name',
            'admin_reviewed_at',
            'admin_review_notes',
            'company_approved_by',
            'company_approved_by_name',
            'company_approved_at',
            'company_review_notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        if obj.requested_by:
            return obj.requested_by.get_full_name() or obj.requested_by.email
        return None

    def get_admin_reviewed_by_name(self, obj):
        if obj.admin_reviewed_by:
            return obj.admin_reviewed_by.get_full_name() or obj.admin_reviewed_by.email
        return None

    def get_company_approved_by_name(self, obj):
        if obj.company_approved_by:
            return obj.company_approved_by.get_full_name() or obj.company_approved_by.email
        return None

    def get_revised_budget_document_name(self, obj):
        return os.path.basename(obj.revised_budget_document.name) if obj.revised_budget_document else None

    def get_revised_budget_document_url(self, obj):
        if obj.revised_budget_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.revised_budget_document.url) if request else obj.revised_budget_document.url
        return None

    def get_mou_amendment_document_name(self, obj):
        return os.path.basename(obj.mou_amendment_document.name) if obj.mou_amendment_document else None

    def get_mou_amendment_document_url(self, obj):
        if obj.mou_amendment_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.mou_amendment_document.url) if request else obj.mou_amendment_document.url
        return None


class CSRGrantChangeRequestCreateSerializer(serializers.Serializer):
    """Input serializer for proposing a bilateral grant change / increase."""
    proposed_commitment = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('1000.00'),
        required=True,
    )
    reason = serializers.CharField(required=True)
    revised_budget_document = serializers.FileField(
        required=False,
        validators=[validate_document_extension],
        allow_null=True,
    )


class CSRGrantChangeAdminReviewSerializer(serializers.Serializer):
    """Input serializer for Admin review of grant change request."""
    decision = serializers.ChoiceField(choices=['APPROVE', 'REJECT'], required=True)
    review_notes = serializers.CharField(required=False, allow_blank=True)
    mou_amendment_document = serializers.FileField(
        required=False,
        validators=[validate_document_extension],
        allow_null=True,
    )

    def validate(self, data):
        if data.get('decision') == 'REJECT' and not str(data.get('review_notes', '')).strip():
            raise serializers.ValidationError({
                'review_notes': _('Review notes explaining rejection are required.')
            })
        return data


class CSRGrantChangeCompanyReviewSerializer(serializers.Serializer):
    """Input serializer for Corporate review of grant change request."""
    decision = serializers.ChoiceField(choices=['APPROVE', 'REJECT'], required=True)
    review_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data.get('decision') == 'REJECT' and not str(data.get('review_notes', '')).strip():
            raise serializers.ValidationError({
                'review_notes': _('Review notes explaining rejection are required.')
            })
        return data

