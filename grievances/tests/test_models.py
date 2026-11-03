"""
Unit Tests for Grievance Ticketing Models — Phase 5.1.1
========================================================
Validates database schema, constraints, auto-generated ticket numbers,
ordering, referential integrity, choices validation, and default states
for GrievanceTicket and GrievanceResponse models.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from grievances.models import (
    GrievanceTicket,
    GrievanceResponse,
    GrievanceCategory,
    GrievancePriority,
    GrievanceStatus,
)

User = get_user_model()


class GrievanceTicketModelTests(TestCase):
    """Unit tests for the GrievanceTicket model."""

    def setUp(self):
        self.donor_user = User.objects.create_user(
            email='donor_grv@example.com',
            password='TestPassword123!',
            role=User.Role.DONOR,
            first_name='Ananya',
            last_name='Sharma',
        )
        self.admin_user = User.objects.create_user(
            email='admin_grv@daangives.org',
            password='AdminPassword123!',
            role=User.Role.ADMIN,
            first_name='Rajesh',
            last_name='Kumar',
        )

    def test_create_ticket_with_required_fields(self):
        """Ticket can be created with minimum required fields and auto-generates key fields."""
        ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Tax Receipt Issue',
            description='I did not receive my 80G receipt for donation.',
            category=GrievanceCategory.RECEIPT_80G,
        )
        self.assertIsNotNone(ticket.pk)
        self.assertIsInstance(ticket.id, uuid.UUID)
        self.assertTrue(ticket.ticket_number.startswith('GRV-'))
        self.assertEqual(ticket.user, self.donor_user)
        self.assertEqual(ticket.title, 'Tax Receipt Issue')
        self.assertEqual(ticket.category, GrievanceCategory.RECEIPT_80G)
        self.assertEqual(ticket.priority, GrievancePriority.MEDIUM)
        self.assertEqual(ticket.status, GrievanceStatus.OPEN)
        self.assertEqual(ticket.resolution_summary, '')
        self.assertIsNone(ticket.resolved_at)
        self.assertIsNone(ticket.assigned_to)

    def test_ticket_number_auto_generated_and_format(self):
        """Ticket number matches format GRV-YYYYMM-XXXXX (5 digits)."""
        ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Discrepancy in Campaign',
            description='Milestone photos do not match campaign description.',
            category=GrievanceCategory.CAMPAIGN_FRAUD,
        )
        now_str = timezone.now().strftime('%Y%m')
        self.assertTrue(
            ticket.ticket_number.startswith(f'GRV-{now_str}-'),
            f"Expected prefix GRV-{now_str}-, got {ticket.ticket_number}",
        )
        seq_str = ticket.ticket_number.split('-')[-1]
        self.assertEqual(len(seq_str), 5)
        self.assertTrue(seq_str.isdigit())

    def test_ticket_number_unique_constraint(self):
        """ticket_number is enforced as unique in database."""
        ticket1 = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='First Ticket',
            description='First issue',
            category=GrievanceCategory.TECHNICAL_SUPPORT,
        )
        # Attempt to duplicate ticket1's ticket_number directly
        ticket2 = GrievanceTicket(
            user=self.donor_user,
            title='Duplicate Number Ticket',
            description='Attempt duplicate',
            category=GrievanceCategory.OTHER,
        )
        ticket2.ticket_number = ticket1.ticket_number
        with self.assertRaises((IntegrityError, Exception)):
            # Bypass auto-generation by calling super().save() directly
            super(GrievanceTicket, ticket2).save()

    def test_default_status_and_priority(self):
        """Defaults for priority (MEDIUM) and status (OPEN) are set properly."""
        ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Default Test Ticket',
            description='Testing model field defaults.',
            category=GrievanceCategory.DONATION_PAYMENT,
        )
        self.assertEqual(ticket.status, GrievanceStatus.OPEN)
        self.assertEqual(ticket.priority, GrievancePriority.MEDIUM)

    def test_invalid_choice_rejected(self):
        """Invalid category, priority, or status triggers ValidationError upon full_clean()."""
        ticket = GrievanceTicket(
            user=self.donor_user,
            title='Invalid Choices Ticket',
            description='Invalid values test.',
            category='INVALID_CATEGORY',
            priority='SUPER_URGENT',
            status='PENDING_MAGIC',
        )
        with self.assertRaises(ValidationError):
            ticket.full_clean()

    def test_uuid_primary_key_generated(self):
        """GrievanceTicket primary key is a valid UUID4 instance."""
        ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='UUID PK Test',
            description='Testing UUID primary key uniqueness.',
            category=GrievanceCategory.OTHER,
        )
        self.assertIsInstance(ticket.id, uuid.UUID)
        self.assertEqual(len(str(ticket.id)), 36)

    def test_user_protect_on_delete(self):
        """Deleting the user is blocked with ProtectedError while tickets exist."""
        ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Protection Test',
            description='Testing models.PROTECT behavior on user delete.',
            category=GrievanceCategory.OTHER,
        )
        with self.assertRaises(ProtectedError):
            self.donor_user.delete()

    def test_str_representation(self):
        """__str__ returns f'{ticket_number} - {title}'."""
        ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Sample Grievance Title',
            description='Detail text.',
            category=GrievanceCategory.TECHNICAL_SUPPORT,
        )
        expected = f"{ticket.ticket_number} - Sample Grievance Title"
        self.assertEqual(str(ticket), expected)

    def test_sequential_ticket_numbering_within_month(self):
        """Ticket numbers increment sequentially within the same month."""
        t1 = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Ticket 1',
            description='Desc 1',
            category=GrievanceCategory.OTHER,
        )
        t2 = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Ticket 2',
            description='Desc 2',
            category=GrievanceCategory.OTHER,
        )
        seq1 = int(t1.ticket_number.split('-')[-1])
        seq2 = int(t2.ticket_number.split('-')[-1])
        self.assertEqual(seq2, seq1 + 1)

    def test_ticket_numbering_different_months(self):
        """Ticket numbers use different YYYYMM prefixes across distinct months."""
        # Create a ticket in past month (2026-08)
        past_date = timezone.datetime(2026, 8, 15, 12, 0, tzinfo=timezone.get_current_timezone())
        with patch('django.utils.timezone.now', return_value=past_date):
            ticket_august = GrievanceTicket.objects.create(
                user=self.donor_user,
                title='August Ticket',
                description='August issue',
                category=GrievanceCategory.OTHER,
            )

        # Create ticket in current month (e.g. 2026-09)
        current_date = timezone.datetime(2026, 9, 22, 12, 0, tzinfo=timezone.get_current_timezone())
        with patch('django.utils.timezone.now', return_value=current_date):
            ticket_sept = GrievanceTicket.objects.create(
                user=self.donor_user,
                title='September Ticket',
                description='September issue',
                category=GrievanceCategory.OTHER,
            )

        self.assertTrue(ticket_august.ticket_number.startswith('GRV-202608-'))
        self.assertTrue(ticket_sept.ticket_number.startswith('GRV-202609-'))
        # Both start sequence at 00001 for their respective months
        self.assertEqual(ticket_august.ticket_number.split('-')[-1], '00001')
        self.assertEqual(ticket_sept.ticket_number.split('-')[-1], '00001')

    def test_tickets_ordering_by_created_at_desc(self):
        """GrievanceTicket default ordering is -created_at."""
        t1 = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='First in time',
            description='Desc',
            category=GrievanceCategory.OTHER,
        )
        t2 = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Second in time',
            description='Desc',
            category=GrievanceCategory.OTHER,
        )
        tickets = list(GrievanceTicket.objects.filter(id__in=[t1.id, t2.id]))
        self.assertEqual(tickets[0].id, t2.id)
        self.assertEqual(tickets[1].id, t1.id)


class GrievanceResponseModelTests(TestCase):
    """Unit tests for the GrievanceResponse model."""

    def setUp(self):
        self.donor_user = User.objects.create_user(
            email='donor_resp@example.com',
            password='TestPassword123!',
            role=User.Role.DONOR,
        )
        self.admin_user = User.objects.create_user(
            email='admin_resp@daangives.org',
            password='AdminPassword123!',
            role=User.Role.ADMIN,
        )
        self.ticket = GrievanceTicket.objects.create(
            user=self.donor_user,
            title='Receipt Correction Needed',
            description='PAN was mistyped on 80G receipt.',
            category=GrievanceCategory.RECEIPT_80G,
        )

    def test_create_response_linked_to_ticket(self):
        """GrievanceResponse can be created and linked to ticket."""
        resp = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.admin_user,
            message='We have notified the tax team to regenerate your receipt.',
            is_internal_note=False,
        )
        self.assertIsNotNone(resp.pk)
        self.assertIsInstance(resp.id, uuid.UUID)
        self.assertEqual(resp.ticket, self.ticket)
        self.assertEqual(resp.author, self.admin_user)
        self.assertFalse(resp.is_internal_note)
        self.assertEqual(self.ticket.responses.count(), 1)
        self.assertEqual(self.ticket.responses.first(), resp)

    def test_response_is_internal_note_default_false(self):
        """is_internal_note defaults to False."""
        resp = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.donor_user,
            message='Thank you, here is the corrected PAN number.',
        )
        self.assertFalse(resp.is_internal_note)

    def test_cascade_on_ticket_delete(self):
        """Deleting GrievanceTicket cascades and removes all associated responses."""
        resp = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.donor_user,
            message='Response to be cascaded.',
        )
        resp_id = resp.id
        self.ticket.delete()
        self.assertFalse(GrievanceResponse.objects.filter(id=resp_id).exists())

    def test_response_str_representation(self):
        """__str__ returns f'Response on {ticket.ticket_number}'."""
        resp = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.admin_user,
            message='Resolution in progress.',
        )
        expected = f"Response on {self.ticket.ticket_number}"
        self.assertEqual(str(resp), expected)

    def test_responses_ordering_by_created_at_asc(self):
        """GrievanceResponse default ordering is created_at (ascending)."""
        r1 = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.donor_user,
            message='First response',
        )
        r2 = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.admin_user,
            message='Second response',
        )
        responses = list(self.ticket.responses.all())
        self.assertEqual(responses[0].id, r1.id)
        self.assertEqual(responses[1].id, r2.id)

    def test_author_protected_on_delete(self):
        """Author cannot be deleted while grievance responses exist (models.PROTECT)."""
        GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.donor_user,
            message='Protected author test message.',
        )
        with self.assertRaises(ProtectedError):
            self.donor_user.delete()
