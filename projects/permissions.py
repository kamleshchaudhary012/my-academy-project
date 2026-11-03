from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsVillageUser(BasePermission):
    """
    Allows access only to authenticated users with the NGO (Village/Sanstha) role.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (getattr(request.user, 'role', None) == 'NGO' or request.user.is_staff)
        )


class IsProjectOwner(BasePermission):
    """
    Object-level permission to only allow the posting village / NGO to view/edit their own project,
    or staff/admin users.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN':
            return True

        project = obj if hasattr(obj, 'posted_by') else getattr(obj, 'project', None)
        if not project:
            return False

        is_owner = (
            project.posted_by == request.user or
            (hasattr(project, 'organization') and project.organization and project.organization.user == request.user)
        )
        return is_owner


class CanEditProject(BasePermission):
    """
    Allows editing only when the project is in DRAFT or DOCS_PENDING status.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        if request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN':
            return True

        project = obj if hasattr(obj, 'status') else getattr(obj, 'project', None)
        if not project:
            return False

        return project.status in ['DRAFT', 'DOCS_PENDING']


class IsAdminUserOrReadOnly(BasePermission):
    """
    Allows read-only access for anyone, and write/verify access for Admin users.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user and
            request.user.is_authenticated and
            (request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN')
        )
