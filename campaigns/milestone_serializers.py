"""
Campaign Milestone & Field Distribution Proof Serializers — Phase 5.2.2
========================================================================
Robust DRF serializers providing validation, mass-assignment protection,
and role-based field sanitization for milestones and field distribution proofs.
"""

from decimal import Decimal
from typing import Optional
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError as DjangoValidationError

from users.image_validators import validate_image_file
from csr.models import BeneficiaryDemographic
from campaigns.models import Campaign, CampaignMilestone, DistributionProof


class CampaignMilestoneSerializer(serializers.ModelSerializer):
    """
    Serializer for listing, retrieving, creating, and updating CampaignMilestones.
    Protects status and completion date from client mass-assignment.
    """
    campaign_title = serializers.CharField(source='campaign.title', read_only=True)
    verified_spent_amount = serializers.SerializerMethodField(read_only=True)
    proofs_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CampaignMilestone
        fields = [
            'id',
            'campaign',
            'campaign_title',
            'sequence_number',
            'title',
            'description',
            'target_amount',
            'target_completion_date',
            'actual_completion_date',
            'status',
            'verified_spent_amount',
            'proofs_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'campaign_title',
            'status',
            'actual_completion_date',
            'verified_spent_amount',
            'proofs_count',
            'created_at',
            'updated_at',
        ]

    def get_verified_spent_amount(self, obj) -> str:
        """Returns the sum of spent amounts across all verified proofs for this milestone."""
        total = sum(
            proof.spent_amount for proof in obj.proofs.filter(status=DistributionProof.Status.VERIFIED)
        ) if hasattr(obj, 'proofs') else Decimal('0.00')
        return str(total)

    def get_proofs_count(self, obj) -> int:
        return obj.proofs.count() if hasattr(obj, 'proofs') else 0

    def validate_sequence_number(self, value):
        if value < 1:
            raise serializers.ValidationError(_("sequence_number must be at least 1."))
        return value

    def validate_target_amount(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError(_("target_amount cannot be negative."))
        return value

    def validate(self, data):
        # Prevent client from mass-assigning status through payload
        if 'status' in self.initial_data:
            data.pop('status', None)

        seq = data.get('sequence_number', getattr(self.instance, 'sequence_number', None))
        campaign = data.get('campaign', getattr(self.instance, 'campaign', None))

        if campaign and seq:
            existing_qs = CampaignMilestone.objects.filter(campaign=campaign, sequence_number=seq)
            if self.instance:
                existing_qs = existing_qs.exclude(pk=self.instance.pk)
            if existing_qs.exists():
                raise serializers.ValidationError({
                    'sequence_number': _(f"Milestone #{seq} already exists for this campaign.")
                })

        return data


class DistributionProofSerializer(serializers.ModelSerializer):
    """
    Authoritative detail serializer for field DistributionProof entities.
    Protects admin notes, reviewer fields, status, and submitter from client tampering.
    """
    milestone_title = serializers.CharField(source='milestone.title', read_only=True)
    campaign_id = serializers.UUIDField(source='milestone.campaign_id', read_only=True)
    campaign_title = serializers.CharField(source='milestone.campaign.title', read_only=True)
    photo_url = serializers.SerializerMethodField(read_only=True)
    beneficiary_type_display = serializers.CharField(source='get_beneficiary_type_display', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.full_name', read_only=True)

    class Meta:
        model = DistributionProof
        fields = [
            'id',
            'milestone',
            'milestone_title',
            'campaign_id',
            'campaign_title',
            'photo',
            'photo_url',
            'caption',
            'latitude',
            'longitude',
            'location_name',
            'beneficiary_count',
            'beneficiary_type',
            'beneficiary_type_display',
            'beneficiary_notes',
            'spent_amount',
            'expense_breakdown',
            'distribution_date',
            'status',
            'submitted_by',
            'submitted_by_name',
            'submitted_at',
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_at',
            'admin_notes',
            'rejection_reason',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'milestone_title',
            'campaign_id',
            'campaign_title',
            'photo_url',
            'beneficiary_type_display',
            'status',
            'submitted_by',
            'submitted_by_name',
            'submitted_at',
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_at',
            'admin_notes',
            'rejection_reason',
            'created_at',
            'updated_at',
        ]

    def get_photo_url(self, obj) -> Optional[str]:
        if obj.photo and hasattr(obj.photo, 'url'):
            return obj.photo.url
        return None

    def validate_photo(self, value):
        if value:
            try:
                validate_image_file(value)
            except DjangoValidationError as e:
                raise serializers.ValidationError(list(e.messages) if hasattr(e, 'messages') else str(e))
        return value

    def validate_latitude(self, value):
        if value is not None:
            if value < Decimal('-90.000000') or value > Decimal('90.000000'):
                raise serializers.ValidationError(_("Latitude must be between -90 and 90 degrees."))
        return value

    def validate_longitude(self, value):
        if value is not None:
            if value < Decimal('-180.000000') or value > Decimal('180.000000'):
                raise serializers.ValidationError(_("Longitude must be between -180 and 180 degrees."))
        return value

    def validate_beneficiary_count(self, value):
        if value < 0:
            raise serializers.ValidationError(_("beneficiary_count cannot be negative."))
        return value

    def validate_beneficiary_type(self, value):
        if value and value not in BeneficiaryDemographic.values:
            raise serializers.ValidationError(
                _(f"Invalid demographic '{value}'. Allowed: {list(BeneficiaryDemographic.values)}.")
            )
        return value

    def validate_spent_amount(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError(_("spent_amount cannot be negative."))
        return value

    def validate_expense_breakdown(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(_("expense_breakdown must be a JSON object (dictionary)."))
        return value

    def validate(self, data):
        # Explicit adversarial sanitization: strip client tampering
        for forbidden in ['status', 'submitted_by', 'reviewed_by', 'reviewed_at', 'admin_notes', 'rejection_reason']:
            if forbidden in self.initial_data:
                data.pop(forbidden, None)
        return data


class DistributionProofCreateSerializer(serializers.ModelSerializer):
    """
    Lightweight upload serializer for NGO field report submission.
    """
    class Meta:
        model = DistributionProof
        fields = [
            'photo',
            'caption',
            'latitude',
            'longitude',
            'location_name',
            'beneficiary_count',
            'beneficiary_type',
            'beneficiary_notes',
            'spent_amount',
            'expense_breakdown',
            'distribution_date',
        ]

    def validate_photo(self, value):
        if not value:
            raise serializers.ValidationError(_("A field distribution photo is required."))
        try:
            validate_image_file(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages) if hasattr(e, 'messages') else str(e))
        return value

    def validate_latitude(self, value):
        if value is not None:
            if value < Decimal('-90.000000') or value > Decimal('90.000000'):
                raise serializers.ValidationError(_("Latitude must be between -90 and 90 degrees."))
        return value

    def validate_longitude(self, value):
        if value is not None:
            if value < Decimal('-180.000000') or value > Decimal('180.000000'):
                raise serializers.ValidationError(_("Longitude must be between -180 and 180 degrees."))
        return value

    def validate_beneficiary_count(self, value):
        if value < 0:
            raise serializers.ValidationError(_("beneficiary_count cannot be negative."))
        return value

    def validate_beneficiary_type(self, value):
        if value and value not in BeneficiaryDemographic.values:
            raise serializers.ValidationError(_("Invalid beneficiary demographic choice."))
        return value

    def validate_spent_amount(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError(_("spent_amount cannot be negative."))
        return value

    def validate_expense_breakdown(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(_("expense_breakdown must be a valid JSON dictionary."))
        return value


class DistributionProofPublicSerializer(serializers.ModelSerializer):
    """
    Donor and Public visibility serializer.
    Guarantees private admin notes, rejection reasons, and reviewer internals are never exposed.
    """
    photo_url = serializers.SerializerMethodField(read_only=True)
    beneficiary_type_display = serializers.CharField(source='get_beneficiary_type_display', read_only=True)

    class Meta:
        model = DistributionProof
        fields = [
            'id',
            'photo_url',
            'caption',
            'latitude',
            'longitude',
            'location_name',
            'beneficiary_count',
            'beneficiary_type',
            'beneficiary_type_display',
            'beneficiary_notes',
            'spent_amount',
            'expense_breakdown',
            'distribution_date',
            'status',
            'reviewed_at',
        ]
        read_only_fields = fields

    def get_photo_url(self, obj) -> Optional[str]:
        if obj.photo and hasattr(obj.photo, 'url'):
            return obj.photo.url
        return None


class AdminProofReviewSerializer(serializers.Serializer):
    """
    Serializer for Admin moderation actions accepting optional notes (start-review, verify).
    """
    admin_notes = serializers.CharField(required=False, allow_blank=True, default='')


class AdminProofDecisionSerializer(serializers.Serializer):
    """
    Serializer for Admin moderation actions requiring justification (request-changes, reject).
    """
    rejection_reason = serializers.CharField(
        required=True,
        allow_blank=False,
        error_messages={
            'required': _('A rejection_reason is required.'),
            'blank': _('rejection_reason cannot be blank.'),
        },
    )
    admin_notes = serializers.CharField(required=False, allow_blank=True, default='')


class CampaignMilestonePublicSerializer(serializers.ModelSerializer):
    """
    Public and Donor transparency serializer for CampaignMilestones.
    Protects internal NGO and moderation details while exposing verified progress.
    """
    verified_spent_amount = serializers.SerializerMethodField(read_only=True)
    verified_proofs_count = serializers.SerializerMethodField(read_only=True)
    proofs = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CampaignMilestone
        fields = [
            'id',
            'sequence_number',
            'title',
            'description',
            'target_amount',
            'target_completion_date',
            'actual_completion_date',
            'status',
            'verified_spent_amount',
            'verified_proofs_count',
            'proofs',
            'created_at',
        ]
        read_only_fields = fields

    def get_verified_spent_amount(self, obj) -> str:
        total = sum(
            (proof.spent_amount for proof in obj.proofs.filter(status=DistributionProof.Status.VERIFIED)),
            Decimal('0.00')
        ) if hasattr(obj, 'proofs') else Decimal('0.00')
        return f"{Decimal(total):.2f}"

    def get_verified_proofs_count(self, obj) -> int:
        return obj.proofs.filter(status=DistributionProof.Status.VERIFIED).count() if hasattr(obj, 'proofs') else 0

    def get_proofs(self, obj):
        verified_qs = obj.proofs.filter(status=DistributionProof.Status.VERIFIED).order_by('distribution_date', 'created_at')
        return DistributionProofPublicSerializer(verified_qs, many=True, context=self.context).data

