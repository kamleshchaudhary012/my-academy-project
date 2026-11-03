from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model

User = get_user_model()


class IsDonorPermission(BasePermission):
    """Allows access only to authenticated users with DONOR role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.DONOR
        )


class IsNgoPermission(BasePermission):
    """Allows access only to authenticated users with NGO role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.NGO
        )


class IsAdminPermission(BasePermission):
    """Allows access only to authenticated users with ADMIN role or staff privileges."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.role == User.Role.ADMIN or request.user.is_staff)
        )
