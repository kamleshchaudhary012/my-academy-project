"""
IDOR Hardening & Access Isolation Tests — Phase 5.1
===================================================
Tests multi-tenant isolation, IDOR guards on tickets and response creation,
staff privilege enforcement, and cross-account data leakage prevention.
"""

import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.test import TestCase

from grievances.models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceResponse,
    GrievanceStatus,
    GrievanceTicket,
)
from grievances.services import GrievanceService

User = get_user_model()


class GrievanceIDORHardeningTests(TestCase):
    """Test suite verifying cross-user isolation and IDOR protections in GrievanceService."""

    def setUp(self):
        # User A (Complainant 1)
        self.user_a = User.objects.create_user(
            email='user_a@example.com',
            password='testpassword123',
            first_name='Alice',
            last_name='Sharma',
            role='DONOR',
        )
        # User B (Complainant 2 / Adversary)
        self.user_b = User.objects.create_user(
            email='user_b@example.com',
            password='testpassword123',
            first_name='Bob',
            last_name='Verma',
            role='DONOR',
        )
        # Staff Officer
        self.staff_user = User.objects.create_user(
            email='staff_officer@example.com',
            password='testpassword123',
            first_name='Sunil',
            last_name='Gupta',
            role='STAFF',
            is_staff=True,
        )

        # Create baseline ticket owned by User A
        self.ticket_a = GrievanceService.create_ticket(
            user=self.user_a,
            validated_data={
                'title': "User A's Confidential Grievance",
                'description': 'Private financial dispute details regarding campaign donation.',
                'category': GrievanceCategory.DONATION_PAYMENT,
                'priority': GrievancePriority.HIGH,
            },
        )
        # Create baseline ticket owned by User B
        self.ticket_b = GrievanceService.create_ticket(
            user=self.user_b,
            validated_data={
                'title': "User B's Private Ticket",
                'description': 'Dispute regarding 80G tax certificate.',
                'category': GrievanceCategory.RECEIPT_80G,
                'priority': GrievancePriority.MEDIUM,
            },
        )

    # -------------------------------------------------------------------------
    # get_ticket_detail IDOR Tests
    # -------------------------------------------------------------------------

    def test_get_ticket_detail_owner_can_retrieve(self):
        """User A can successfully retrieve their own ticket."""
        ticket = GrievanceService.get_ticket_detail(user=self.user_a, ticket_id=self.ticket_a.id)
        self.assertEqual(ticket.id, self.ticket_a.id)
        self.assertEqual(ticket.user, self.user_a)

    def test_get_ticket_detail_non_owner_blocked(self):
        """User B attempting to view User A's ticket raises PermissionDenied (IDOR Guard)."""
        with self.assertRaises(PermissionDenied):
            GrievanceService.get_ticket_detail(
                user=self.user_b,
                ticket_id=self.ticket_a.id,
                is_admin=False,
            )

    def test_get_ticket_detail_staff_can_retrieve_any_ticket(self):
        """Staff member can retrieve User A's ticket with is_admin=True."""
        ticket = GrievanceService.get_ticket_detail(
            user=self.staff_user,
            ticket_id=self.ticket_a.id,
            is_admin=True,
        )
        self.assertEqual(ticket.id, self.ticket_a.id)

    def test_get_ticket_detail_non_existent_id_raises_does_not_exist(self):
        """Requesting a non-existent UUID raises ObjectDoesNotExist / GrievanceNotFoundError."""
        random_uuid = uuid.uuid4()
        with self.assertRaises(ObjectDoesNotExist):
            GrievanceService.get_ticket_detail(
                user=self.user_a,
                ticket_id=random_uuid,
            )

    # -------------------------------------------------------------------------
    # create_response IDOR Tests
    # -------------------------------------------------------------------------

    def test_create_response_owner_can_respond(self):
        """User A can add a response to their own ticket."""
        response = GrievanceService.create_response(
            ticket=self.ticket_a,
            author=self.user_a,
            validated_data={'message': 'User A providing additional bank transaction ID.'},
            is_admin=False,
        )
        self.assertEqual(response.ticket, self.ticket_a)
        self.assertEqual(response.author, self.user_a)

    def test_create_response_non_owner_blocked_from_responding(self):
        """User B cannot post a response on User A's ticket (IDOR Guard)."""
        with self.assertRaises(PermissionDenied):
            GrievanceService.create_response(
                ticket=self.ticket_a,
                author=self.user_b,
                validated_data={'message': 'Adversary injecting message into foreign ticket.'},
                is_admin=False,
            )

    def test_create_response_staff_can_respond_on_any_ticket(self):
        """Staff member can post a response on any user ticket."""
        response = GrievanceService.create_response(
            ticket=self.ticket_a,
            author=self.staff_user,
            validated_data={'message': 'Staff officer requesting further documentation.'},
            is_admin=True,
        )
        self.assertEqual(response.ticket, self.ticket_a)
        self.assertEqual(response.author, self.staff_user)

    # -------------------------------------------------------------------------
    # assign_ticket Authorization Tests
    # -------------------------------------------------------------------------

    def test_assign_ticket_non_staff_blocked(self):
        """Non-staff user (User A) cannot assign or re-route tickets."""
        with self.assertRaises(PermissionDenied):
            GrievanceService.assign_ticket(
                ticket=self.ticket_a,
                assigned_to_user=self.staff_user,
                performed_by=self.user_a,
            )

    def test_assign_ticket_staff_allowed(self):
        """Staff officer can assign a ticket to an investigator."""
        assigned = GrievanceService.assign_ticket(
            ticket=self.ticket_a,
            assigned_to_user=self.staff_user,
            performed_by=self.staff_user,
        )
        self.assertEqual(assigned.assigned_to, self.staff_user)

    # -------------------------------------------------------------------------
    # transition_status Authorization Tests
    # -------------------------------------------------------------------------

    def test_transition_status_non_staff_blocked(self):
        """Non-staff user (User A) cannot execute status transitions."""
        with self.assertRaises(PermissionDenied):
            GrievanceService.transition_status(
                ticket=self.ticket_a,
                new_status=GrievanceStatus.IN_REVIEW,
                performed_by=self.user_a,
            )

    def test_transition_status_staff_allowed(self):
        """Staff officer can transition ticket status from OPEN to IN_REVIEW."""
        updated = GrievanceService.transition_status(
            ticket=self.ticket_a,
            new_status=GrievanceStatus.IN_REVIEW,
            performed_by=self.staff_user,
        )
        self.assertEqual(updated.status, GrievanceStatus.IN_REVIEW)

    # -------------------------------------------------------------------------
    # filter_responses_for_user Visibility Tests
    # -------------------------------------------------------------------------

    def test_filter_responses_non_admin_sees_only_public_notes(self):
        """Complainant (User A) only sees public responses; internal notes are cloaked."""
        public_resp = GrievanceService.create_response(
            ticket=self.ticket_a,
            author=self.staff_user,
            validated_data={'message': 'Public reply from officer.', 'is_internal_note': False},
            is_admin=True,
        )
        internal_note = GrievanceService.create_response(
            ticket=self.ticket_a,
            author=self.staff_user,
            validated_data={'message': 'Private audit log: escalating to compliance officer.', 'is_internal_note': True},
            is_admin=True,
        )

        filtered = GrievanceService.filter_responses_for_user(self.ticket_a, is_admin=False)
        self.assertIn(public_resp, filtered)
        self.assertNotIn(internal_note, filtered)
        self.assertEqual(len(filtered), 1)

    def test_filter_responses_admin_sees_all_notes(self):
        """Admin/Staff sees all responses including internal administrative notes."""
        public_resp = GrievanceService.create_response(
            ticket=self.ticket_a,
            author=self.staff_user,
            validated_data={'message': 'Public reply from officer.', 'is_internal_note': False},
            is_admin=True,
        )
        internal_note = GrievanceService.create_response(
            ticket=self.ticket_a,
            author=self.staff_user,
            validated_data={'message': 'Private audit log: escalating to compliance officer.', 'is_internal_note': True},
            is_admin=True,
        )

        filtered = GrievanceService.filter_responses_for_user(self.ticket_a, is_admin=True)
        self.assertIn(public_resp, filtered)
        self.assertIn(internal_note, filtered)
        self.assertEqual(len(filtered), 2)

    # -------------------------------------------------------------------------
    # get_tickets_for_user Multi-tenant Leakage Tests
    # -------------------------------------------------------------------------

    def test_get_tickets_for_user_complete_isolation(self):
        """User A sees only A's tickets; User B sees only B's tickets with zero leakage."""
        user_a_tickets = list(GrievanceService.get_tickets_for_user(user=self.user_a))
        user_b_tickets = list(GrievanceService.get_tickets_for_user(user=self.user_b))

        self.assertIn(self.ticket_a, user_a_tickets)
        self.assertNotIn(self.ticket_b, user_a_tickets)

        self.assertIn(self.ticket_b, user_b_tickets)
        self.assertNotIn(self.ticket_a, user_b_tickets)
