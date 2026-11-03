from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from ngo.models import NGOProfile


class IsApprovedNGOOwner(permissions.BasePermission):
    """
    Permission class that grants access ONLY to authenticated users who own
    an NGOProfile with status == 'APPROVED', is_active == True, and is_public == True.
    """
    message = _('Only approved and active NGOs can create or publish campaigns.')

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.role != 'NGO':
            return False

        try:
            profile = request.user.ngo_profile
        except NGOProfile.DoesNotExist:
            raise PermissionDenied(_('NGO Profile does not exist.'))

        if profile.status != NGOProfile.Status.APPROVED:
            raise PermissionDenied(
                _(f'Only approved NGOs can manage campaigns. Current status is {profile.status}.')
            )

        if not (profile.is_active and profile.is_public):
            raise PermissionDenied(_('NGO Profile is not currently active and public.'))

        return True

    def has_object_permission(self, request, view, obj):
        if not self.has_permission(request, view):
            return False
        if hasattr(obj, 'ngo'):
            return obj.ngo == request.user.ngo_profile
        if hasattr(obj, 'campaign') and hasattr(obj.campaign, 'ngo'):
            return obj.campaign.ngo == request.user.ngo_profile
        if hasattr(obj, 'milestone') and hasattr(obj.milestone, 'campaign'):
            return obj.milestone.campaign.ngo == request.user.ngo_profile
        return False
