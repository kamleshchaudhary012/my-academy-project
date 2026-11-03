"""
Grievance App Permissions & Access Control — Phase 5.1
======================================================
Defines granular DRF permission classes for grievance ticket creation,
ticket lifecycle moderation, staff assignment, IDOR prevention, and internal note cloaking.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAuthenticatedAndActive(BasePermission):
    """
    Purpose:
        Ensures the requesting user is fully authenticated and has an active account status.
    When to use:
        Baseline requirement for any grievance endpoint.
    Combination hints:
        Combine as the first class in permission_classes alongside resource-specific rules.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        )

    def has_object_permission(self, request, view, obj):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        )


class IsTicketOwner(BasePermission):
    """
    Purpose:
        Restricts object-level access on GrievanceTicket to the ticket complainant or staff.
    When to use:
        Ticket detail retrieve, update, partial update, or cancellation endpoints.
    Combination hints:
        Pair with IsAuthenticatedAndActive. Staff members (is_staff=True) bypass ownership.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        )

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated and getattr(request.user, 'is_active', False)):
            return False
        if getattr(request.user, 'is_staff', False):
            return True
        owner_id = getattr(obj, 'user_id', None)
        if owner_id is None and hasattr(obj, 'user'):
            owner_id = getattr(obj.user, 'id', None)
        return owner_id == request.user.id


class IsTicketOwnerOrAssignedStaff(BasePermission):
    """
    Purpose:
        Grants access if the requesting user is the ticket owner, the assigned staff officer, or general staff.
    When to use:
        Threaded message creation, response listing, and ticket review flows.
    Combination hints:
        Combine with IsAuthenticatedAndActive. Useful for bidirectional dispute workflows.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        )

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated and getattr(request.user, 'is_active', False)):
            return False
        if getattr(request.user, 'is_staff', False):
            return True

        # Check ticket owner
        owner_id = getattr(obj, 'user_id', None)
        if owner_id is None and hasattr(obj, 'user'):
            owner_id = getattr(obj.user, 'id', None)
        if owner_id == request.user.id:
            return True

        # Check assigned staff
        assigned_id = getattr(obj, 'assigned_to_id', None)
        if assigned_id is None and hasattr(obj, 'assigned_to') and obj.assigned_to:
            assigned_id = getattr(obj.assigned_to, 'id', None)
        if assigned_id and assigned_id == request.user.id:
            return True

        return False


class IsResponseAuthorOrStaff(BasePermission):
    """
    Purpose:
        Restricts modification of a grievance response to its original author or administrative staff.
    When to use:
        Grievance response update endpoints (e.g. toggling internal note flags).
    Combination hints:
        Pair with IsAuthenticatedAndActive.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        )

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated and getattr(request.user, 'is_active', False)):
            return False
        if getattr(request.user, 'is_staff', False):
            return True

        author_id = getattr(obj, 'author_id', None)
        if author_id is None and hasattr(obj, 'author'):
            author_id = getattr(obj.author, 'id', None)
        return author_id == request.user.id


class CanCreateTicket(BasePermission):
    """
    Purpose:
        Authorizes an active, authenticated user to submit a new grievance ticket.
    When to use:
        POST /api/v1/grievances/ ticket creation endpoint.
    Combination hints:
        Currently open to all active authenticated users (donors, NGOs, CSR companies, public users).
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanViewInternalNotes(BasePermission):
    """
    Purpose:
        Restricts access to internal administrative notes on grievance tickets exclusively to staff.
    When to use:
        Admin endpoints or query filters that expose internal notes.
    Combination hints:
        Pair with IsAuthenticatedAndActive.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and getattr(request.user, 'is_staff', False)
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanAssignTicket(BasePermission):
    """
    Purpose:
        Restricts ticket assignment and re-routing capabilities to staff members.
    When to use:
        POST/PATCH /api/v1/grievances/<id>/assign/ endpoint.
    Combination hints:
        Pair with IsAuthenticatedAndActive.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and getattr(request.user, 'is_staff', False)
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanTransitionStatus(BasePermission):
    """
    Purpose:
        Restricts status transitions (e.g. IN_REVIEW, RESOLVED, CLOSED, REJECTED) to platform staff.
    When to use:
        POST/PATCH /api/v1/grievances/<id>/status/ endpoint.
    Combination hints:
        Combine with IsTicketOwnerOrAssignedStaff to allow assigned investigators to advance status.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and getattr(request.user, 'is_staff', False)
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsAdminOrReadOnly(BasePermission):
    """
    Purpose:
        Permits read-only (GET, HEAD, OPTIONS) access to authenticated users, but requires staff for mutations.
    When to use:
        Publicly or organizationally visible reference endpoints.
    Combination hints:
        Pair with IsAuthenticatedAndActive.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and getattr(request.user, 'is_active', False)):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(request.user, 'is_staff', False))

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated and getattr(request.user, 'is_active', False)):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(request.user, 'is_staff', False))


class DenyAll(BasePermission):
    """
    Purpose:
        Always denies access unconditionally. Failsafe default.
    When to use:
        Unimplemented or permanently disabled endpoints.
    Combination hints:
        Stands alone.
    """

    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


class DenyAnyObject(BasePermission):
    """
    Purpose:
        Allows view-level checks if appropriate but unconditionally denies object-level access.
    When to use:
        Write-only or bulk endpoints where object retrieval is prohibited.
    Combination hints:
        Failsafe object-level guard.
    """

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return False


# =============================================================================
# ALLOWED COMBINATIONS MATRIX (Documentation Reference for Phase 5.1.4 Views)
# =============================================================================

ALLOWED_COMBINATIONS = {
    "ticket_list_create": [IsAuthenticatedAndActive, CanCreateTicket],
    "ticket_detail": [IsAuthenticatedAndActive, IsTicketOwner],
    "ticket_transition": [IsAuthenticatedAndActive, IsTicketOwnerOrAssignedStaff, CanTransitionStatus],
    "ticket_assign": [IsAuthenticatedAndActive, CanAssignTicket],
    "response_list_create": [IsAuthenticatedAndActive, IsTicketOwnerOrAssignedStaff],
    "response_update": [IsAuthenticatedAndActive, IsResponseAuthorOrStaff],
}
