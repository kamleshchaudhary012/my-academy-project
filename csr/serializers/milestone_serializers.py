"""
CSR Milestone Serializers — Phase CSR-2.1
=========================================
Serializers for PartnershipMilestone progress tracking and verification:
- PartnershipMilestoneSerializer: Full milestone representation and scheduling.
- MilestoneEvidenceSubmitSerializer: Deliverable evidence submission validation.
- MilestoneReviewSerializer: Milestone verification/revision decision validator.
"""

import os
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from csr.models import (
    PartnershipMilestone,
    MilestoneStatus,
)


class PartnershipMilestoneSerializer(serializers.ModelSerializer):
    """
    Representation and scheduling serializer for PartnershipMilestones.
    Enforces positive sequence numbers (>= 1) and completion percentage range (0-100).
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    has_evidence_document = serializers.SerializerMethodField()
    evidence_document_name = serializers.SerializerMethodField()
    evidence_document_url = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    verified_by_name = serializers.CharField(source='verified_by.full_name', read_only=True, default=None)
    verified_by_email = serializers.EmailField(source='verified_by.email', read_only=True, default=None)

    class Meta:
        model = PartnershipMilestone
        fields = [
            'id',
            'partnership',
            'sequence_number',
            'title',
            'description',
            'target_completion_date',
            'actual_completion_date',
            'status',
            'status_display',
            'completion_percentage',
            'has_evidence_document',
            'evidence_document_name',
            'evidence_document_url',
            'is_overdue',
            'evidence_notes',
            'verified_at',
            'verified_by',
            'verified_by_name',
            'verified_by_email',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'partnership',
            'status',
            'actual_completion_date',
            'verified_at',
            'verified_by',
            'verified_by_name',
            'verified_by_email',
            'created_at',
            'updated_at',
        ]

    def get_has_evidence_document(self, obj):
        return bool(obj.evidence_document)

    def get_evidence_document_name(self, obj):
        if obj.evidence_document:
            return os.path.basename(obj.evidence_document.name)
        return None

    def get_evidence_document_url(self, obj):
        if obj.evidence_document:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.evidence_document.url) if request else obj.evidence_document.url
        return None

    def get_is_overdue(self, obj):
        if obj.status == MilestoneStatus.VERIFIED:
            return False
        return bool(obj.target_completion_date and obj.target_completion_date < timezone.now().date())

    def validate_sequence_number(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError(_('Milestone sequence number must be at least 1.'))
        return value

    def validate_completion_percentage(self, value):
        if value is not None and (value < 0 or value > 100):
            raise serializers.ValidationError(_('Completion percentage must be between 0 and 100.'))
        return value


class MilestoneEvidenceSubmitSerializer(serializers.Serializer):
    """
    Payload validator for NGO milestone evidence submission.
    """
    evidence_document = serializers.FileField(
        required=True,
        help_text=_('Deliverable proof / completion report PDF or image.'),
    )
    evidence_notes = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=3000,
        help_text=_('Detailed narrative of work completed and milestones achieved.'),
    )
    submission_notes = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=3000,
    )
    completion_percentage = serializers.IntegerField(
        required=True,
        min_value=1,
        max_value=100,
        help_text=_('Cumulative completion percentage (1-100).'),
    )

    def validate(self, data):
        notes = (data.get('evidence_notes') or data.get('submission_notes') or '').strip()
        if not notes:
            raise serializers.ValidationError({
                'evidence_notes': _('Evidence notes cannot be blank.')
            })
        data['evidence_notes'] = notes
        return data


class MilestoneReviewSerializer(serializers.Serializer):
    """
    Payload validator for corporate / admin review of submitted milestone evidence.
    """
    decision = serializers.ChoiceField(
        choices=['VERIFY', 'REQUEST_REVISION'],
        required=False,
    )
    status = serializers.ChoiceField(
        choices=['VERIFIED', 'REVISION_REQUESTED', 'VERIFY', 'REQUEST_REVISION'],
        required=False,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=2000,
    )
    review_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=2000,
    )

    def validate(self, data):
        decision = data.get('decision')
        if not decision and data.get('status'):
            st = data.get('status')
            if st in ('VERIFIED', 'VERIFY'):
                decision = 'VERIFY'
            elif st in ('REVISION_REQUESTED', 'REQUEST_REVISION'):
                decision = 'REQUEST_REVISION'
        if not decision:
            raise serializers.ValidationError({
                'decision': _("A review decision ('VERIFY' or 'REQUEST_REVISION') is required.")
            })
        data['decision'] = decision

        notes = (data.get('notes') or data.get('review_notes') or '').strip()
        data['notes'] = notes

        if decision == 'REQUEST_REVISION' and not notes:
            raise serializers.ValidationError({
                'notes': _("Revision feedback notes are required when requesting a milestone revision.")
            })
        return data
