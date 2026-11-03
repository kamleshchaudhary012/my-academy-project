"""
Unit Tests for Grievance Permissions — Phase 5.1
=================================================
Tests DRF permission classes, role access checks, staff overrides,
and ALLOWED_COMBINATIONS mapping.
"""

from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from grievances.models import GrievanceCategory, GrievanceResponse, GrievanceTicket
from grievances.permissions import (
    ALLOWED_COMBINATIONS,
    CanAssignTicket,
    CanCreateTicket,
    CanTransitionStatus,
    CanViewInternalNotes,
    DenyAll,
    DenyAnyObject,
    IsAdminOrReadOnly,
    IsAuthenticatedAndActive,
    IsResponseAuthorOrStaff,
    IsTicketOwner,
    IsTicketOwnerOrAssignedStaff,
)

User = get_user_model()


class GrievancePermissionsTests(TestCase):
    """Test suite for DRF permission classes in grievances.permissions."""

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = User.objects.create_user(
            email='owner@example.com',
            password='testpassword123',
            first_name='Owner',
            last_name='User',
            role='DONOR',
            is_active=True,
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpassword123',
            first_name='Other',
            last_name='User',
            role='DONOR',
            is_active=True,
        )
        self.inactive_user = User.objects.create_user(
            email='inactive@example.com',
            password='testpassword123',
            first_name='Inactive',
            last_name='User',
            role='DONOR',
            is_active=False,
        )
        self.staff_user = User.objects.create_user(
            email='staff@example.com',
            password='testpassword123',
            first_name='Staff',
            last_name='Officer',
            role='STAFF',
            is_staff=True,
            is_active=True,
        )
        self.other_staff = User.objects.create_user(
            email='other.staff@example.com',
            password='testpassword123',
            first_name='Other',
            last_name='Staff',
            role='STAFF',
            is_staff=True,
            is_active=True,
        )
        self.anon_user = AnonymousUser()

        self.ticket = GrievanceTicket.objects.create(
            user=self.owner,
            title='Permission Test Ticket',
            description='Testing permissions',
            category=GrievanceCategory.OTHER,
            assigned_to=self.staff_user,
        )
        self.response = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.owner,
            message='Test reply',
        )
        self.dummy_view = SimpleNamespace()

    def _build_request(self, user, method='GET'):
        request = getattr(self.factory, method.lower())('/api/v1/grievances/')
        request.user = user
        return request

    # -------------------------------------------------------------------------
    # IsAuthenticatedAndActive
    # -------------------------------------------------------------------------

    def test_is_authenticated_and_active_anonymous_denied(self):
        perm = IsAuthenticatedAndActive()
        req = self._build_request(self.anon_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_authenticated_and_active_active_user_allowed(self):
        perm = IsAuthenticatedAndActive()
        req = self._build_request(self.owner)
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_authenticated_and_active_inactive_user_denied(self):
        perm = IsAuthenticatedAndActive()
        req = self._build_request(self.inactive_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    # -------------------------------------------------------------------------
    # IsTicketOwner
    # -------------------------------------------------------------------------

    def test_is_ticket_owner_owner_allowed(self):
        perm = IsTicketOwner()
        req = self._build_request(self.owner)
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_non_owner_denied(self):
        perm = IsTicketOwner()
        req = self._build_request(self.other_user)
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_staff_allowed(self):
        perm = IsTicketOwner()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_anonymous_denied(self):
        perm = IsTicketOwner()
        req = self._build_request(self.anon_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    # -------------------------------------------------------------------------
    # IsTicketOwnerOrAssignedStaff
    # -------------------------------------------------------------------------

    def test_is_ticket_owner_or_assigned_staff_owner_allowed(self):
        perm = IsTicketOwnerOrAssignedStaff()
        req = self._build_request(self.owner)
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_or_assigned_staff_assigned_staff_allowed(self):
        perm = IsTicketOwnerOrAssignedStaff()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_or_assigned_staff_non_assigned_staff_allowed(self):
        perm = IsTicketOwnerOrAssignedStaff()
        req = self._build_request(self.other_staff)
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_or_assigned_staff_non_owner_non_staff_denied(self):
        perm = IsTicketOwnerOrAssignedStaff()
        req = self._build_request(self.other_user)
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_ticket_owner_or_assigned_staff_anonymous_denied(self):
        perm = IsTicketOwnerOrAssignedStaff()
        req = self._build_request(self.anon_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    # -------------------------------------------------------------------------
    # IsResponseAuthorOrStaff
    # -------------------------------------------------------------------------

    def test_is_response_author_or_staff_author_allowed(self):
        perm = IsResponseAuthorOrStaff()
        req = self._build_request(self.owner)
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.response))

    def test_is_response_author_or_staff_other_non_staff_denied(self):
        perm = IsResponseAuthorOrStaff()
        req = self._build_request(self.other_user)
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.response))

    def test_is_response_author_or_staff_staff_allowed(self):
        perm = IsResponseAuthorOrStaff()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.response))

    # -------------------------------------------------------------------------
    # CanCreateTicket
    # -------------------------------------------------------------------------

    def test_can_create_ticket_active_auth_allowed(self):
        perm = CanCreateTicket()
        req = self._build_request(self.owner)
        self.assertTrue(perm.has_permission(req, self.dummy_view))

    def test_can_create_ticket_anonymous_denied(self):
        perm = CanCreateTicket()
        req = self._build_request(self.anon_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))

    def test_can_create_ticket_inactive_denied(self):
        perm = CanCreateTicket()
        req = self._build_request(self.inactive_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))

    # -------------------------------------------------------------------------
    # CanViewInternalNotes
    # -------------------------------------------------------------------------

    def test_can_view_internal_notes_staff_allowed(self):
        perm = CanViewInternalNotes()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_permission(req, self.dummy_view))

    def test_can_view_internal_notes_non_staff_denied(self):
        perm = CanViewInternalNotes()
        req = self._build_request(self.owner)
        self.assertFalse(perm.has_permission(req, self.dummy_view))

    # -------------------------------------------------------------------------
    # CanAssignTicket
    # -------------------------------------------------------------------------

    def test_can_assign_ticket_staff_allowed(self):
        perm = CanAssignTicket()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_permission(req, self.dummy_view))

    def test_can_assign_ticket_non_staff_denied(self):
        perm = CanAssignTicket()
        req = self._build_request(self.owner)
        self.assertFalse(perm.has_permission(req, self.dummy_view))

    # -------------------------------------------------------------------------
    # CanTransitionStatus
    # -------------------------------------------------------------------------

    def test_can_transition_status_staff_allowed(self):
        perm = CanTransitionStatus()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_permission(req, self.dummy_view))

    def test_can_transition_status_non_staff_denied(self):
        perm = CanTransitionStatus()
        req = self._build_request(self.owner)
        self.assertFalse(perm.has_permission(req, self.dummy_view))

    # -------------------------------------------------------------------------
    # IsAdminOrReadOnly
    # -------------------------------------------------------------------------

    def test_is_admin_or_read_only_get_non_staff_allowed(self):
        perm = IsAdminOrReadOnly()
        req = self._build_request(self.owner, method='GET')
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_admin_or_read_only_post_non_staff_denied(self):
        perm = IsAdminOrReadOnly()
        req = self._build_request(self.owner, method='POST')
        self.assertFalse(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_is_admin_or_read_only_post_staff_allowed(self):
        perm = IsAdminOrReadOnly()
        req = self._build_request(self.staff_user, method='POST')
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertTrue(perm.has_object_permission(req, self.dummy_view, self.ticket))

    # -------------------------------------------------------------------------
    # DenyAll & DenyAnyObject & Matrix
    # -------------------------------------------------------------------------

    def test_deny_all_always_false(self):
        perm = DenyAll()
        req = self._build_request(self.staff_user)
        self.assertFalse(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_deny_any_object_always_false(self):
        perm = DenyAnyObject()
        req = self._build_request(self.staff_user)
        self.assertTrue(perm.has_permission(req, self.dummy_view))
        self.assertFalse(perm.has_object_permission(req, self.dummy_view, self.ticket))

    def test_allowed_combinations_matrix_coverage(self):
        """ALLOWED_COMBINATIONS matrix exists and covers all 6 required endpoints."""
        expected_endpoints = {
            "ticket_list_create",
            "ticket_detail",
            "ticket_transition",
            "ticket_assign",
            "response_list_create",
            "response_update",
        }
        self.assertEqual(set(ALLOWED_COMBINATIONS.keys()), expected_endpoints)
        for endpoint, classes in ALLOWED_COMBINATIONS.items():
            self.assertTrue(len(classes) >= 2, f"Endpoint {endpoint} must have at least 2 permission classes")
            self.assertIn(IsAuthenticatedAndActive, classes)
