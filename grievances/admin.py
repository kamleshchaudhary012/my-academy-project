"""
Django Admin Configuration for Grievance Ticketing
"""

from django.contrib import admin
from .models import GrievanceTicket, GrievanceResponse


@admin.register(GrievanceTicket)
class GrievanceTicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_number',
        'title',
        'user',
        'category',
        'priority',
        'status',
        'created_at',
    )
    list_filter = ('status', 'priority', 'category')
    search_fields = ('ticket_number', 'title', 'description', 'user__email')
    readonly_fields = ('id', 'ticket_number', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(GrievanceResponse)
class GrievanceResponseAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'author', 'is_internal_note', 'created_at')
    list_filter = ('is_internal_note',)
    readonly_fields = ('id', 'created_at')
    ordering = ('created_at',)
