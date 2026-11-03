from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from campaigns.models import (
    Campaign,
    CampaignReviewHistory,
)


class CampaignReviewHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True)

    class Meta:
        model = CampaignReviewHistory
        fields = [
            'id',
            'old_status',
            'new_status',
            'changed_by_name',
            'note',
            'created_at',
        ]


class CampaignSerializer(serializers.ModelSerializer):
    ngo_display_name = serializers.CharField(source='ngo.display_name', read_only=True)
    ngo_slug = serializers.CharField(source='ngo.slug', read_only=True)
    review_history = CampaignReviewHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id',
            'title',
            'slug',
            'category',
            'campaign_type',
            'short_description',
            'description',
            'target_amount',
            'raised_amount',
            'cover_image',
            'start_date',
            'end_date',
            'status',
            'is_featured',
            'is_active',
            'submitted_at',
            'reviewed_at',
            'admin_review_note',
            'rejection_reason',
            'ngo_display_name',
            'ngo_slug',
            'review_history',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'slug',
            'raised_amount',
            'status',
            'submitted_at',
            'reviewed_at',
            'admin_review_note',
            'rejection_reason',
            'ngo_display_name',
            'ngo_slug',
            'review_history',
            'created_at',
            'updated_at',
        ]

    def validate(self, data):
        start_date = data.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = data.get('end_date', getattr(self.instance, 'end_date', None))

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({
                'end_date': _('End date cannot be earlier than start date.')
            })

        target_amount = data.get('target_amount', getattr(self.instance, 'target_amount', 0))
        if target_amount is not None and float(target_amount) < 0:
            raise serializers.ValidationError({
                'target_amount': _('Target amount cannot be negative.')
            })

        if self.instance is not None:
            new_type = data.get('campaign_type')
            if new_type and new_type != self.instance.campaign_type:
                if self.instance.status not in [Campaign.Status.DRAFT, Campaign.Status.CHANGES_REQUESTED]:
                    raise serializers.ValidationError({
                        'campaign_type': _(f'Cannot change campaign type when campaign is in status {self.instance.status}.')
                    })

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        ngo = user.ngo_profile
        validated_data['ngo'] = ngo
        validated_data['created_by'] = user
        # FORCE creation to start as DRAFT (NGO approval != Campaign approval)
        validated_data['status'] = Campaign.Status.DRAFT
        return super().create(validated_data)


class CampaignPublicSerializer(serializers.ModelSerializer):
    ngo = serializers.UUIDField(source='ngo_id', read_only=True)
    ngo_id = serializers.UUIDField(read_only=True)
    ngo_name = serializers.CharField(source='ngo.display_name', read_only=True)
    ngo_slug = serializers.CharField(source='ngo.slug', read_only=True)
    ngo_logo = serializers.SerializerMethodField()
    ngo_city = serializers.SerializerMethodField()
    ngo_state = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            'id',
            'title',
            'slug',
            'category',
            'campaign_type',
            'short_description',
            'description',
            'target_amount',
            'raised_amount',
            'cover_image',
            'start_date',
            'end_date',
            'status',
            'is_featured',
            'ngo',
            'ngo_id',
            'ngo_name',
            'ngo_slug',
            'ngo_logo',
            'ngo_city',
            'ngo_state',
            'created_at',
        ]

    def get_ngo_logo(self, obj):
        if obj.ngo and obj.ngo.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.ngo.logo.url)
            return obj.ngo.logo.url
        return None

    def get_ngo_city(self, obj):
        return getattr(getattr(obj.ngo, 'address', None), 'city', '')

    def get_ngo_state(self, obj):
        return getattr(getattr(obj.ngo, 'address', None), 'state', '')


# Phase 5.2 Milestone & Distribution Proof Serializers
from campaigns.milestone_serializers import (
    CampaignMilestoneSerializer,
    CampaignMilestonePublicSerializer,
    DistributionProofSerializer,
    DistributionProofCreateSerializer,
    DistributionProofPublicSerializer,
    AdminProofReviewSerializer,
    AdminProofDecisionSerializer,
)

