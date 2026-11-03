"""
DaanGives NGO Admin Registration — Phase 3.2

All admin views are read-optimized for review.
NGOVerificationHistory: all fields set as readonly — no edits or deletes permitted.
"""

from django.contrib import admin
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
)


class NGOAddressInline(admin.StackedInline):
    model = NGOAddress
    extra = 0
    can_delete = False


class NGOLegalInfoInline(admin.StackedInline):
    model = NGOLegalInfo
    extra = 0
    can_delete = False


class NGOBankInfoInline(admin.StackedInline):
    model = NGOBankInfo
    extra = 0
    can_delete = False
    # Restrict sensitive fields in admin display
    readonly_fields = ('verified_by', 'verified_at', 'masked_account_number')

    def masked_account_number(self, obj):
        return obj.masked_account_number if obj.pk else '—'
    masked_account_number.short_description = 'Account Number (Masked)'


class NGOLeadershipInline(admin.TabularInline):
    model = NGOLeadership
    extra = 0
    ordering = ['order', 'created_at']


class NGODocumentInline(admin.TabularInline):
    model = NGODocument
    extra = 0
    readonly_fields = ('id', 'uploaded_by', 'mime_type', 'file_size_bytes', 'uploaded_at', 'is_active')
    fields = ('document_type', 'original_filename', 'is_active', 'is_verified', 'uploaded_at', 'uploaded_by')
    can_delete = False  # Documents should never be deleted via admin


class NGOVerificationInline(admin.StackedInline):
    model = NGOVerification
    extra = 0
    readonly_fields = (
        'reviewed_by', 'submitted_at', 'last_submitted_at',
        'review_started_at', 'decision_at', 'resubmission_count',
        'created_at', 'updated_at',
    )
    can_delete = False


@admin.register(NGOProfile)
class NGOProfileAdmin(admin.ModelAdmin):
    list_display = (
        'display_name', 'category', 'status', 'is_active',
        'is_public_display', 'created_at',
    )
    list_filter = ('status', 'category', 'is_active')
    search_fields = ('display_name', 'legal_name', 'slug', 'user__email')
    readonly_fields = (
        'id', 'user', 'slug', 'status', 'is_active',
        'verified_at', 'created_at', 'updated_at',
    )
    inlines = [
        NGOAddressInline,
        NGOLegalInfoInline,
        NGOBankInfoInline,
        NGOLeadershipInline,
        NGODocumentInline,
        NGOVerificationInline,
    ]
    ordering = ['-created_at']

    def is_public_display(self, obj):
        return obj.is_public
    is_public_display.boolean = True
    is_public_display.short_description = 'Is Public'


@admin.register(NGOVerification)
class NGOVerificationAdmin(admin.ModelAdmin):
    list_display = ('ngo', 'status', 'reviewed_by', 'resubmission_count', 'submitted_at')
    list_filter = ('status',)
    search_fields = ('ngo__display_name', 'ngo__user__email')
    readonly_fields = (
        'ngo', 'status', 'reviewed_by',
        'submitted_at', 'last_submitted_at', 'review_started_at', 'decision_at',
        'resubmission_count', 'created_at', 'updated_at',
    )
    ordering = ['-created_at']


@admin.register(NGOVerificationHistory)
class NGOVerificationHistoryAdmin(admin.ModelAdmin):
    """
    Immutable audit log. ALL fields are readonly.
    No add, change, or delete permissions permitted via admin.
    """
    list_display = ('ngo', 'previous_status', 'new_status', 'actor_type', 'performed_by', 'timestamp')
    list_filter = ('actor_type', 'new_status')
    search_fields = ('ngo__display_name',)
    ordering = ['-timestamp']

    # ALL fields are readonly — immutable record
    readonly_fields = (
        'id', 'ngo', 'performed_by', 'actor_type',
        'previous_status', 'new_status', 'reason', 'metadata', 'timestamp',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NGODocument)
class NGODocumentAdmin(admin.ModelAdmin):
    list_display = ('ngo', 'document_type', 'is_active', 'is_verified', 'uploaded_at')
    list_filter = ('document_type', 'is_active', 'is_verified')
    search_fields = ('ngo__display_name',)
    readonly_fields = (
        'id', 'ngo', 'uploaded_by', 'file', 'original_filename',
        'file_size_bytes', 'mime_type', 'uploaded_at',
    )
    ordering = ['-uploaded_at']

    def has_delete_permission(self, request, obj=None):
        # Documents should not be deleted via admin — retained for audit
        return False


