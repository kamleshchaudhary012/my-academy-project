"""
DaanGives NGO Permissions — Phase 3.3.2-H
=========================================
Object and role permission classes for NGO Owner and Admin APIs.
"""

from rest_framework.permissions import BasePermission, IsAuthenticated
from users.models import User


class IsNgoOwner(BasePermission):
    """
    Allows access only to authenticated active users with role == 'NGO'.
    Ensures ownership is derived strictly from request.user.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.role == User.Role.NGO
        )


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.role == User.Role.ADMIN
        )
