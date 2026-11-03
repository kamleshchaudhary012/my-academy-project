"""
Unit Tests for Grievance Services — Phase 5.1
==============================================
Tests business rules, state machine transitions, concurrency safety,
admin privileges, IDOR protection, and internal note filtering in GrievanceService.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from grievances.models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceResponse,
    GrievanceStatus,
    GrievanceTicket,
)
from grievances.services import GrievanceService

User = get_user_model()


class GrievanceServiceTests(TestCase):
    """Comprehensive test suite for GrievanceService domain logic."""

    def setUp(self):
        self.user1 = User.objects.create_user(
            email='donor.one@example.com',
            password='testpassword123',
            first_name='Rohan',
            last_name='Verma',
            role='DONOR',
        )
        self.user2 = User.objects.create_user(
            email='donor.two@example.com',
            password='testpassword123',
            first_name='Ananya',
            last_name='Iyer',
            role='DONOR',
        )
        self.staff_user = User.objects.create_user(
            email='support.officer@example.com',
            password='testpassword123',
            first_name='Sunita',
            last_name='Rao',
            role='STAFF',
            is_staff=True,
        )
        self.admin_user = User.objects.create_superuser(
            email='super.admin@example.com',
            password='testpassword123',
            first_name='Admin',
            last_name='System',
        )

    # -------------------------------------------------------------------------
    # create_ticket Tests
    # -------------------------------------------------------------------------

    def test_create_ticket_correct_user_set(self):
        """create_ticket associates ticket with the passed user."""
        data = {
            'title': 'Payment query for receipt 80G',
            'description': 'Tax exemption certificate missing after donation.',
            'category': GrievanceCategory.RECEIPT_80G,
            'priority': GrievancePriority.MEDIUM,
        }
        ticket = GrievanceService.create_ticket(user=self.user1, validated_data=data)
        self.assertEqual(ticket.user, self.user1)
        self.assertEqual(ticket.title, data['title'])

    def test_create_ticket_status_open_by_default(self):
        """create_ticket forces status to OPEN regardless of input."""
        data = {
            'title': 'Technical glitch during checkout',
            'description': 'Server timeout during gateway callback.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'status': GrievanceStatus.RESOLVED,  # Attempting to tamper status
        }
        ticket = GrievanceService.create_ticket(user=self.user1, validated_data=data)
        self.assertEqual(ticket.status, GrievanceStatus.OPEN)

    def test_create_ticket_forbidden_fields_ignored(self):
        """Client-injected ticket_number, assigned_to, and resolution fields are ignored."""
        data = {
            'title': 'Campaign inquiry report',
            'description': 'Need verification regarding campaign expenditure.',
            'category': GrievanceCategory.CAMPAIGN_FRAUD,
            'ticket_number': 'GRV-INJECTED-00001',
            'assigned_to': self.staff_user,
            'resolution_summary': 'Premature resolution',
            'resolved_at': timezone.now(),
        }
        ticket = GrievanceService.create_ticket(user=self.user1, validated_data=data)
        self.assertNotEqual(ticket.ticket_number, 'GRV-INJECTED-00001')
        self.assertTrue(ticket.ticket_number.startswith('GRV-'))
        self.assertIsNone(ticket.assigned_to)
        self.assertEqual(ticket.resolution_summary, '')
        self.assertIsNone(ticket.resolved_at)

    def test_create_ticket_unique_ticket_number_generated(self):
        """Unique sequential ticket number is auto-generated upon ticket creation."""
        data1 = {
            'title': 'First ticket query',
            'description': 'Detailed description number one.',
            'category': GrievanceCategory.OTHER,
        }
        data2 = {
            'title': 'Second ticket query',
            'description': 'Detailed description number two.',
            'category': GrievanceCategory.OTHER,
        }
        t1 = GrievanceService.create_ticket(user=self.user1, validated_data=data1)
        t2 = GrievanceService.create_ticket(user=self.user1, validated_data=data2)

        self.assertNotEqual(t1.ticket_number, t2.ticket_number)
        self.assertTrue(t1.ticket_number.startswith('GRV-'))
        self.assertTrue(t2.ticket_number.startswith('GRV-'))

    # -------------------------------------------------------------------------
    # create_response Tests
    # -------------------------------------------------------------------------

    def test_create_response_non_admin_cannot_set_internal_note(self):
        """Non-admin user attempting to post an internal note raises PermissionDenied."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Test Ticket for response',
                'description': 'Description for response test.',
                'category': GrievanceCategory.OTHER,
            },
        )
        data = {
            'message': 'Attempting unauthorized internal note.',
            'is_internal_note': True,
        }
        with self.assertRaises(PermissionDenied):
            GrievanceService.create_response(
                ticket=ticket,
                author=self.user1,
                validated_data=data,
                is_admin=False,
            )

    def test_create_response_admin_can_set_internal_note(self):
        """Admin or staff officer can post an internal note."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Test Ticket for response',
                'description': 'Description for response test.',
                'category': GrievanceCategory.OTHER,
            },
        )
        data = {
            'message': 'Internal audit note: User bank statement verified.',
            'is_internal_note': True,
        }
        response = GrievanceService.create_response(
            ticket=ticket,
            author=self.staff_user,
            validated_data=data,
            is_admin=True,
        )
        self.assertTrue(response.is_internal_note)
        self.assertEqual(response.author, self.staff_user)
        self.assertEqual(response.ticket, ticket)

    def test_create_response_author_forced_from_current_user(self):
        """Author is strictly assigned from the passed author argument."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Test Ticket for response',
                'description': 'Description for response test.',
                'category': GrievanceCategory.OTHER,
            },
        )
        data = {
            'message': 'Public reply from complainant.',
            'author': self.admin_user,  # Injected author
            'ticket': None,             # Injected ticket
        }
        response = GrievanceService.create_response(
            ticket=ticket,
            author=self.user1,
            validated_data=data,
            is_admin=False,
        )
        self.assertEqual(response.author, self.user1)
        self.assertEqual(response.ticket, ticket)

    # -------------------------------------------------------------------------
    # assign_ticket Tests
    # -------------------------------------------------------------------------

    def test_assign_ticket_admin_can_assign(self):
        """Staff member can successfully assign a ticket to an investigator."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'CSR partnership dispute report',
                'description': 'Milestone verification disagreement.',
                'category': GrievanceCategory.CSR_PARTNERSHIP_DISPUTE,
            },
        )
        assigned_ticket = GrievanceService.assign_ticket(
            ticket=ticket,
            assigned_to_user=self.staff_user,
            performed_by=self.staff_user,
        )
        self.assertEqual(assigned_ticket.assigned_to, self.staff_user)

    def test_assign_ticket_non_admin_cannot_assign(self):
        """Non-staff user attempting ticket assignment raises PermissionDenied."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'CSR partnership dispute report',
                'description': 'Milestone verification disagreement.',
                'category': GrievanceCategory.CSR_PARTNERSHIP_DISPUTE,
            },
        )
        with self.assertRaises(PermissionDenied):
            GrievanceService.assign_ticket(
                ticket=ticket,
                assigned_to_user=self.staff_user,
                performed_by=self.user1,
            )

    # -------------------------------------------------------------------------
    # transition_status Tests
    # -------------------------------------------------------------------------

    def test_transition_status_valid_open_to_in_review(self):
        """Valid transition from OPEN to IN_REVIEW."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Valid Transition Ticket',
                'description': 'Testing status transition.',
                'category': GrievanceCategory.OTHER,
            },
        )
        updated = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.IN_REVIEW,
            performed_by=self.staff_user,
        )
        self.assertEqual(updated.status, GrievanceStatus.IN_REVIEW)

    def test_transition_status_valid_in_review_to_resolved(self):
        """Valid transition from IN_REVIEW to RESOLVED with resolution summary."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Resolution Test Ticket',
                'description': 'Testing status transition to resolved.',
                'category': GrievanceCategory.OTHER,
            },
        )
        ticket = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.IN_REVIEW,
            performed_by=self.staff_user,
        )
        resolved = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.RESOLVED,
            performed_by=self.staff_user,
            resolution_summary='Refund processed via Razorpay gateway.',
        )
        self.assertEqual(resolved.status, GrievanceStatus.RESOLVED)
        self.assertEqual(resolved.resolution_summary, 'Refund processed via Razorpay gateway.')
        self.assertIsNotNone(resolved.resolved_at)

    def test_transition_status_invalid_open_to_resolved_rejected(self):
        """Transition directly from OPEN to RESOLVED is invalid and raises ValidationError with code."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Invalid Skip Ticket',
                'description': 'Attempting illegal status leap.',
                'category': GrievanceCategory.OTHER,
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            GrievanceService.transition_status(
                ticket=ticket,
                new_status=GrievanceStatus.RESOLVED,
                performed_by=self.staff_user,
                resolution_summary='Premature resolution summary.',
            )
        self.assertEqual(ctx.exception.code, 'INVALID_STATUS_TRANSITION')

    def test_transition_status_invalid_closed_to_anything_rejected(self):
        """Transition out of CLOSED (terminal state) is rejected."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Terminal State Ticket',
                'description': 'Closing ticket to test terminal state.',
                'category': GrievanceCategory.OTHER,
            },
        )
        closed = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.CLOSED,
            performed_by=self.staff_user,
        )
        self.assertEqual(closed.status, GrievanceStatus.CLOSED)

        for attempt_status in [GrievanceStatus.OPEN, GrievanceStatus.IN_REVIEW, GrievanceStatus.RESOLVED]:
            with self.assertRaises(ValidationError) as ctx:
                GrievanceService.transition_status(
                    ticket=closed,
                    new_status=attempt_status,
                    performed_by=self.staff_user,
                )
            self.assertEqual(ctx.exception.code, 'INVALID_STATUS_TRANSITION')

    def test_transition_status_resolved_requires_non_empty_summary(self):
        """RESOLVED transition requires non-empty resolution_summary."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Missing Summary Ticket',
                'description': 'Testing resolution summary validation.',
                'category': GrievanceCategory.OTHER,
            },
        )
        ticket = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.IN_REVIEW,
            performed_by=self.staff_user,
        )

        # Empty string
        with self.assertRaises(ValidationError):
            GrievanceService.transition_status(
                ticket=ticket,
                new_status=GrievanceStatus.RESOLVED,
                performed_by=self.staff_user,
                resolution_summary='',
            )

        # Whitespace only
        with self.assertRaises(ValidationError):
            GrievanceService.transition_status(
                ticket=ticket,
                new_status=GrievanceStatus.RESOLVED,
                performed_by=self.staff_user,
                resolution_summary='   ',
            )

    def test_transition_status_resolved_at_set_on_resolved(self):
        """resolved_at timestamp is set automatically upon reaching RESOLVED."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Timestamp Ticket',
                'description': 'Testing resolved_at timestamp setting.',
                'category': GrievanceCategory.OTHER,
            },
        )
        ticket = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.IN_REVIEW,
            performed_by=self.staff_user,
        )
        self.assertIsNone(ticket.resolved_at)

        before = timezone.now()
        resolved = GrievanceService.transition_status(
            ticket=ticket,
            new_status=GrievanceStatus.RESOLVED,
            performed_by=self.staff_user,
            resolution_summary='Issue addressed in full.',
        )
        after = timezone.now()

        self.assertIsNotNone(resolved.resolved_at)
        self.assertTrue(before <= resolved.resolved_at <= after)

    def test_transition_status_closed_and_rejected_set_resolved_at(self):
        """CLOSED and REJECTED transitions set resolved_at if not already set."""
        ticket1 = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Direct Close Ticket', 'description': 'Testing close.', 'category': GrievanceCategory.OTHER},
        )
        closed = GrievanceService.transition_status(
            ticket=ticket1,
            new_status=GrievanceStatus.CLOSED,
            performed_by=self.staff_user,
        )
        self.assertIsNotNone(closed.resolved_at)

        ticket2 = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Direct Reject Ticket', 'description': 'Testing reject.', 'category': GrievanceCategory.OTHER},
        )
        rejected = GrievanceService.transition_status(
            ticket=ticket2,
            new_status=GrievanceStatus.REJECTED,
            performed_by=self.staff_user,
        )
        self.assertIsNotNone(rejected.resolved_at)

    # -------------------------------------------------------------------------
    # get_tickets_for_user Tests
    # -------------------------------------------------------------------------

    def test_get_tickets_for_user_returns_only_own_tickets(self):
        """get_tickets_for_user isolates tickets by caller user."""
        t1 = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'User 1 Ticket', 'description': 'Description 1', 'category': GrievanceCategory.OTHER},
        )
        t2 = GrievanceService.create_ticket(
            user=self.user2,
            validated_data={'title': 'User 2 Ticket', 'description': 'Description 2', 'category': GrievanceCategory.OTHER},
        )

        user1_tickets = list(GrievanceService.get_tickets_for_user(user=self.user1))
        self.assertIn(t1, user1_tickets)
        self.assertNotIn(t2, user1_tickets)

    def test_get_tickets_for_user_filters_work(self):
        """Filtering by status, priority, and category correctly subsets tickets."""
        GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'High Priority Technical Support',
                'description': 'Critical system bug report.',
                'category': GrievanceCategory.TECHNICAL_SUPPORT,
                'priority': GrievancePriority.HIGH,
            },
        )
        t_low = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={
                'title': 'Low Priority Tax Receipt',
                'description': 'Non-urgent query about 80G receipt.',
                'category': GrievanceCategory.RECEIPT_80G,
                'priority': GrievancePriority.LOW,
            },
        )

        filtered_prio = list(GrievanceService.get_tickets_for_user(user=self.user1, filters={'priority': GrievancePriority.LOW}))
        self.assertEqual(len(filtered_prio), 1)
        self.assertEqual(filtered_prio[0], t_low)

        filtered_cat = list(GrievanceService.get_tickets_for_user(user=self.user1, filters={'category': GrievanceCategory.RECEIPT_80G}))
        self.assertEqual(len(filtered_cat), 1)
        self.assertEqual(filtered_cat[0], t_low)

    def test_get_tickets_for_user_ordering_created_at_desc(self):
        """Returned tickets are ordered by -created_at."""
        t1 = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Older Ticket', 'description': 'Description older', 'category': GrievanceCategory.OTHER},
        )
        t2 = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Newer Ticket', 'description': 'Description newer', 'category': GrievanceCategory.OTHER},
        )
        tickets = list(GrievanceService.get_tickets_for_user(user=self.user1))
        self.assertEqual(tickets[0].id, t2.id)
        self.assertEqual(tickets[1].id, t1.id)

    # -------------------------------------------------------------------------
    # get_ticket_detail Tests
    # -------------------------------------------------------------------------

    def test_get_ticket_detail_user_can_view_own_ticket(self):
        """A user can successfully retrieve their own ticket detail."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Own Ticket', 'description': 'Can view this.', 'category': GrievanceCategory.OTHER},
        )
        fetched = GrievanceService.get_ticket_detail(user=self.user1, ticket_id=ticket.id)
        self.assertEqual(fetched.id, ticket.id)

    def test_get_ticket_detail_idor_guard_prevents_viewing_others_ticket(self):
        """IDOR Guard: Non-admin user cannot access another user's ticket."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Private Ticket', 'description': 'Confidential dispute.', 'category': GrievanceCategory.OTHER},
        )
        with self.assertRaises(PermissionDenied):
            GrievanceService.get_ticket_detail(user=self.user2, ticket_id=ticket.id, is_admin=False)

    def test_get_ticket_detail_admin_can_view_any_ticket(self):
        """Admin user can view any user's ticket without IDOR restrictions."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'User 1 Ticket', 'description': 'Admin inspection.', 'category': GrievanceCategory.OTHER},
        )
        fetched = GrievanceService.get_ticket_detail(user=self.admin_user, ticket_id=ticket.id, is_admin=True)
        self.assertEqual(fetched.id, ticket.id)

    # -------------------------------------------------------------------------
    # filter_responses_for_user Tests
    # -------------------------------------------------------------------------

    def test_filter_responses_non_admin_sees_only_public_responses(self):
        """Non-admin user only sees responses where is_internal_note is False."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Thread Ticket', 'description': 'Testing note filtering.', 'category': GrievanceCategory.OTHER},
        )
        public_resp = GrievanceService.create_response(
            ticket=ticket,
            author=self.staff_user,
            validated_data={'message': 'Public reply to user.', 'is_internal_note': False},
            is_admin=True,
        )
        internal_resp = GrievanceService.create_response(
            ticket=ticket,
            author=self.staff_user,
            validated_data={'message': 'Secret investigator note.', 'is_internal_note': True},
            is_admin=True,
        )

        filtered = GrievanceService.filter_responses_for_user(ticket, is_admin=False)
        self.assertIn(public_resp, filtered)
        self.assertNotIn(internal_resp, filtered)
        self.assertEqual(len(filtered), 1)

    def test_filter_responses_admin_sees_all_responses(self):
        """Admin sees all responses including internal notes."""
        ticket = GrievanceService.create_ticket(
            user=self.user1,
            validated_data={'title': 'Thread Ticket', 'description': 'Testing note filtering.', 'category': GrievanceCategory.OTHER},
        )
        public_resp = GrievanceService.create_response(
            ticket=ticket,
            author=self.staff_user,
            validated_data={'message': 'Public reply to user.', 'is_internal_note': False},
            is_admin=True,
        )
        internal_resp = GrievanceService.create_response(
            ticket=ticket,
            author=self.staff_user,
            validated_data={'message': 'Secret investigator note.', 'is_internal_note': True},
            is_admin=True,
        )

        filtered = GrievanceService.filter_responses_for_user(ticket, is_admin=True)
        self.assertIn(public_resp, filtered)
        self.assertIn(internal_resp, filtered)
        self.assertEqual(len(filtered), 2)
