"""
Unit Tests for Grievance Serializers — Phase 5.1
=================================================
Tests validation rules, stripping of read-only fields, attachment constraints,
and nested structures for Grievance serializers.
"""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from grievances.models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceResponse,
    GrievanceStatus,
    GrievanceTicket,
)
from grievances.serializers import (
    GrievanceResponseSerializer,
    GrievanceResponseUpdateSerializer,
    GrievanceTicketDetailSerializer,
    GrievanceTicketListSerializer,
    GrievanceTicketSerializer,
)

User = get_user_model()


class GrievanceSerializerTests(TestCase):
    """Test suite for grievance tickets and response serializers."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='complainant@example.com',
            password='testpassword123',
            first_name='Aarav',
            last_name='Sharma',
            role='DONOR',
        )
        self.staff_user = User.objects.create_user(
            email='support.agent@example.com',
            password='testpassword123',
            first_name='Priya',
            last_name='Patel',
            role='STAFF',
            is_staff=True,
        )

    # -------------------------------------------------------------------------
    # GrievanceTicketSerializer Tests
    # -------------------------------------------------------------------------

    def test_ticket_serializer_valid_payload_accepted(self):
        """Valid payload passes serializer validation."""
        payload = {
            'title': 'Payment deducted but no receipt generated',
            'description': 'My bank account was debited for 5000 INR on campaign test1 but no receipt was issued.',
            'category': GrievanceCategory.DONATION_PAYMENT,
            'priority': GrievancePriority.HIGH,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['title'], payload['title'])
        self.assertEqual(serializer.validated_data['category'], GrievanceCategory.DONATION_PAYMENT)
        self.assertEqual(serializer.validated_data['priority'], GrievancePriority.HIGH)

    def test_ticket_serializer_missing_title_rejected(self):
        """Missing title fails validation."""
        payload = {
            'description': 'Detailed description here with enough characters.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('title', serializer.errors)

    def test_ticket_serializer_missing_description_rejected(self):
        """Missing description fails validation."""
        payload = {
            'title': 'Valid Title Here',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('description', serializer.errors)

    def test_ticket_serializer_title_under_5_chars_rejected(self):
        """Title with fewer than 5 characters is rejected."""
        payload = {
            'title': 'Help',
            'description': 'Detailed description here with enough characters.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('title', serializer.errors)

    def test_ticket_serializer_description_under_10_chars_rejected(self):
        """Description with fewer than 10 characters is rejected."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Too short',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('description', serializer.errors)

    def test_ticket_serializer_invalid_category_rejected(self):
        """Invalid category choice is rejected."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': 'INVALID_CATEGORY_XYZ',
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('category', serializer.errors)

    def test_ticket_serializer_invalid_priority_rejected(self):
        """Invalid priority choice is rejected."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.OTHER,
            'priority': 'SUPER_URGENT',
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('priority', serializer.errors)

    def test_ticket_serializer_client_supplied_ticket_number_stripped(self):
        """Client-supplied ticket_number is stripped from validated_data."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'ticket_number': 'GRV-FAKE-99999',
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('ticket_number', serializer.validated_data)

    def test_ticket_serializer_client_supplied_user_stripped(self):
        """Client-supplied user is stripped from validated_data."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'user': self.staff_user.id,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('user', serializer.validated_data)

    def test_ticket_serializer_client_supplied_status_stripped_on_create(self):
        """Client-supplied status is stripped on create."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'status': GrievanceStatus.RESOLVED,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('status', serializer.validated_data)

    def test_ticket_serializer_client_supplied_assigned_to_stripped_on_create(self):
        """Client-supplied assigned_to is stripped on create."""
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'assigned_to': self.staff_user.id,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('assigned_to', serializer.validated_data)

    def test_ticket_serializer_attachment_too_large_rejected(self):
        """Attachment exceeding 5 MB is rejected."""
        large_content = b'x' * (5 * 1024 * 1024 + 10)
        large_file = SimpleUploadedFile('large.pdf', large_content, content_type='application/pdf')
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'attachment': large_file,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('attachment', serializer.errors)

    def test_ticket_serializer_attachment_invalid_extension_rejected(self):
        """Attachment with unauthorized extension (.exe) is rejected."""
        unauthorized_file = SimpleUploadedFile('script.exe', b'binary_data', content_type='application/octet-stream')
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'attachment': unauthorized_file,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('attachment', serializer.errors)

    def test_ticket_serializer_attachment_valid_extensions_accepted(self):
        """Valid file extensions (pdf, jpg, jpeg, png) are accepted."""
        for ext in ['pdf', 'jpg', 'jpeg', 'png']:
            valid_file = SimpleUploadedFile(f'evidence.{ext}', b'file_bytes', content_type='application/octet-stream')
            payload = {
                'title': 'Valid Ticket Title',
                'description': 'Valid description with sufficient details.',
                'category': GrievanceCategory.TECHNICAL_SUPPORT,
                'attachment': valid_file,
            }
            serializer = GrievanceTicketSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), f"Failed for .{ext}: {serializer.errors}")

    def test_ticket_serializer_disguised_executable_rejected(self):
        """Disguised executable or PHP script with valid extension (.pdf) is rejected."""
        disguised_file = SimpleUploadedFile('malicious.pdf', b'<?php phpinfo(); ?>', content_type='application/pdf')
        payload = {
            'title': 'Valid Ticket Title',
            'description': 'Valid description with sufficient details.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'attachment': disguised_file,
        }
        serializer = GrievanceTicketSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('attachment', serializer.errors)

    # -------------------------------------------------------------------------
    # GrievanceTicketListSerializer Tests
    # -------------------------------------------------------------------------

    def test_ticket_list_serializer_exposes_only_whitelisted_fields(self):
        """List serializer outputs only whitelisted lightweight fields."""
        ticket = GrievanceTicket.objects.create(
            user=self.user,
            title='List View Test Ticket',
            description='Detailed description that is not exposed in list view.',
            category=GrievanceCategory.RECEIPT_80G,
            priority=GrievancePriority.MEDIUM,
        )
        serializer = GrievanceTicketListSerializer(ticket)
        expected_fields = {
            'id',
            'ticket_number',
            'title',
            'category',
            'priority',
            'status',
            'created_at',
        }
        self.assertEqual(set(serializer.data.keys()), expected_fields)
        self.assertNotIn('description', serializer.data)
        self.assertNotIn('user', serializer.data)

    # -------------------------------------------------------------------------
    # GrievanceTicketDetailSerializer Tests
    # -------------------------------------------------------------------------

    def test_ticket_detail_serializer_includes_nested_responses(self):
        """Detail serializer includes nested responses array."""
        ticket = GrievanceTicket.objects.create(
            user=self.user,
            title='Detail View Test Ticket',
            description='Detailed inquiry regarding 80G receipt.',
            category=GrievanceCategory.RECEIPT_80G,
        )
        response1 = GrievanceResponse.objects.create(
            ticket=ticket,
            author=self.staff_user,
            message='First response from support staff.',
            is_internal_note=False,
        )
        response2 = GrievanceResponse.objects.create(
            ticket=ticket,
            author=self.user,
            message='Complainant follow-up message.',
            is_internal_note=False,
        )

        serializer = GrievanceTicketDetailSerializer(ticket)
        data = serializer.data
        self.assertIn('responses', data)
        self.assertEqual(len(data['responses']), 2)
        response_messages = [r['message'] for r in data['responses']]
        self.assertIn(response1.message, response_messages)
        self.assertIn(response2.message, response_messages)

    def test_ticket_detail_serializer_includes_nested_user(self):
        """Detail serializer includes nested user representation (id, email, first_name, last_name)."""
        ticket = GrievanceTicket.objects.create(
            user=self.user,
            title='User Detail Test Ticket',
            description='Detailed inquiry description.',
            category=GrievanceCategory.RECEIPT_80G,
        )
        serializer = GrievanceTicketDetailSerializer(ticket)
        user_data = serializer.data.get('user')
        self.assertIsInstance(user_data, dict)
        self.assertEqual(str(user_data['id']), str(self.user.id))
        self.assertEqual(user_data['email'], self.user.email)
        self.assertEqual(user_data['first_name'], self.user.first_name)
        self.assertEqual(user_data['last_name'], self.user.last_name)

    def test_ticket_detail_serializer_includes_nested_assigned_to_nullable(self):
        """Detail serializer handles unassigned and assigned staff members properly."""
        ticket_unassigned = GrievanceTicket.objects.create(
            user=self.user,
            title='Unassigned Ticket',
            description='No officer assigned yet.',
            category=GrievanceCategory.OTHER,
        )
        serializer1 = GrievanceTicketDetailSerializer(ticket_unassigned)
        self.assertIsNone(serializer1.data.get('assigned_to'))

        ticket_assigned = GrievanceTicket.objects.create(
            user=self.user,
            title='Assigned Ticket',
            description='Assigned officer present.',
            category=GrievanceCategory.OTHER,
            assigned_to=self.staff_user,
        )
        serializer2 = GrievanceTicketDetailSerializer(ticket_assigned)
        assigned_data = serializer2.data.get('assigned_to')
        self.assertIsInstance(assigned_data, dict)
        self.assertEqual(str(assigned_data['id']), str(self.staff_user.id))
        self.assertEqual(assigned_data['email'], self.staff_user.email)

    # -------------------------------------------------------------------------
    # GrievanceResponseSerializer Tests
    # -------------------------------------------------------------------------

    def test_response_serializer_valid_message_accepted(self):
        """Valid response message passes serializer validation."""
        payload = {
            'message': 'We are looking into your transaction with the payment gateway.',
            'is_internal_note': False,
        }
        serializer = GrievanceResponseSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['message'], payload['message'])

    def test_response_serializer_empty_message_rejected(self):
        """Empty message fails validation."""
        payload = {'message': ''}
        serializer = GrievanceResponseSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('message', serializer.errors)

    def test_response_serializer_message_over_5000_chars_rejected(self):
        """Message exceeding 5000 characters is rejected."""
        payload = {'message': 'a' * 5001}
        serializer = GrievanceResponseSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('message', serializer.errors)

    def test_response_serializer_is_internal_note_defaults_false(self):
        """is_internal_note defaults to False if omitted."""
        payload = {'message': 'Standard response message.'}
        serializer = GrievanceResponseSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertFalse(serializer.validated_data.get('is_internal_note', False))

    def test_response_serializer_author_and_ticket_read_only(self):
        """Client-supplied ticket and author fields are ignored in response serializer."""
        ticket = GrievanceTicket.objects.create(
            user=self.user,
            title='Response Read-Only Test Ticket',
            description='Ticket to test read-only fields.',
            category=GrievanceCategory.OTHER,
        )
        payload = {
            'message': 'Testing read-only author and ticket.',
            'author': self.staff_user.id,
            'ticket': ticket.id,
        }
        serializer = GrievanceResponseSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('author', serializer.validated_data)
        self.assertNotIn('ticket', serializer.validated_data)

    # -------------------------------------------------------------------------
    # GrievanceResponseUpdateSerializer Tests
    # -------------------------------------------------------------------------

    def test_response_update_serializer_only_is_internal_note_editable(self):
        """Only is_internal_note is extracted into validated_data."""
        payload = {'is_internal_note': True}
        serializer = GrievanceResponseUpdateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {'is_internal_note': True})

    def test_response_update_serializer_message_ignored_if_sent(self):
        """Message field sent in update payload is ignored."""
        payload = {
            'is_internal_note': True,
            'message': 'Attempting to change original response body.',
        }
        serializer = GrievanceResponseUpdateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('message', serializer.validated_data)
        self.assertEqual(serializer.validated_data, {'is_internal_note': True})
