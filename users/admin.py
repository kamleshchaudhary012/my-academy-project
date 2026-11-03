from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for custom User model."""
    ordering = ('email',)
    list_display = ('email', 'full_name', 'role', 'is_email_verified', 'is_staff', 'is_active', 'created_at')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active', 'is_email_verified')
    search_fields = ('email', 'full_name', 'phone')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('full_name', 'phone', 'role', 'is_email_verified')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2', 'full_name', 'role', 'is_staff', 'is_superuser'),
            },
        ),
    )
