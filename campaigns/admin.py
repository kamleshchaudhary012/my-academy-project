from django.contrib import admin
from campaigns.models import (
    Campaign,
    CampaignReviewHistory,
)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'ngo',
        'category',
        'campaign_type',
        'target_amount',
        'raised_amount',
        'status',
        'is_featured',
        'is_active',
        'created_at',
    )
    list_filter = ('status', 'campaign_type', 'category', 'is_featured', 'is_active')
    search_fields = ('title', 'short_description', 'ngo__display_name', 'ngo__legal_name')
    readonly_fields = ('slug', 'raised_amount', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(CampaignReviewHistory)
class CampaignReviewHistoryAdmin(admin.ModelAdmin):
    list_display = (
        'campaign',
        'old_status',
        'new_status',
        'changed_by',
        'created_at',
    )
    search_fields = ('campaign__title', 'old_status', 'new_status')
    readonly_fields = ('created_at',)
