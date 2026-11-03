import logging
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core import mail
from django.core.mail import send_mail

from users.models import User
from grievances.models import GrievanceTicket, GrievanceResponse, GrievanceStatus
from grievances.services import GrievanceService
from grievances.notifications import (
    notify_ticket_created,
    notify_ticket_assigned,
    notify_status_changed,
    notify_new_response,
    notify_internal_note,
)

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotificationTests(TestCase):
    def setUp(self):
        self.donor = User.objects.create_user(
            email='donor@test.com',
            password='pass',
            full_name='Donor User',
            role=User.Role.DONOR
        )
        self.admin = User.objects.create_user(
            email='admin@test.com',
            password='pass',
            full_name='Admin User',
            role=User.Role.ADMIN,
            is_staff=True
        )
        self.no_email_user = User.objects.create_user(
            email='nobody@test.com',
            password='pass'
        )
        self.no_email_user.email = ''
        self.no_email_user.save()

        self.ticket = GrievanceTicket.objects.create(
            user=self.donor,
            title='Test Ticket',
            description='Test Desc',
            category='TECHNICAL',
            priority='HIGH',
            status=GrievanceStatus.OPEN
        )
        mail.outbox = []

    def test_notify_ticket_created_sends_email(self):
        notify_ticket_created(self.ticket)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['donor@test.com'])

    def test_notify_ticket_created_subject(self):
        notify_ticket_created(self.ticket)
        self.assertIn('[Grievance]', mail.outbox[0].subject)
        self.assertIn('Ticket created', mail.outbox[0].subject)

    def test_notify_ticket_created_body_content(self):
        notify_ticket_created(self.ticket)
        self.assertIn(self.ticket.ticket_number, mail.outbox[0].body)
        self.assertIn('TECHNICAL', mail.outbox[0].body)
        self.assertIn('HIGH', mail.outbox[0].body)
        self.assertIn('OPEN', mail.outbox[0].body)

    def test_notify_ticket_assigned_sends_email(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        notify_ticket_assigned(self.ticket, self.admin)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@test.com'])

    def test_notify_ticket_assigned_subject(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        notify_ticket_assigned(self.ticket, self.admin)
        self.assertIn('Ticket assigned', mail.outbox[0].subject)

    def test_notify_ticket_assigned_body_content(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        notify_ticket_assigned(self.ticket, self.admin)
        self.assertIn(self.ticket.ticket_number, mail.outbox[0].body)
        self.assertIn(self.ticket.user.email, mail.outbox[0].body)

    def test_notify_status_changed_sends_email(self):
        notify_status_changed(self.ticket, 'OPEN', 'RESOLVED')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['donor@test.com'])

    def test_notify_status_changed_subject(self):
        notify_status_changed(self.ticket, 'OPEN', 'RESOLVED')
        self.assertIn('Status updated', mail.outbox[0].subject)
        self.assertIn('RESOLVED', mail.outbox[0].subject)

    def test_notify_status_changed_body_with_resolution(self):
        self.ticket.resolution_summary = "Issue was solved via backend restart"
        notify_status_changed(self.ticket, 'OPEN', 'RESOLVED')
        self.assertIn('Issue was solved', mail.outbox[0].body)
        self.assertIn('OPEN to RESOLVED', mail.outbox[0].body)

    def test_notify_status_changed_body_without_resolution(self):
        self.ticket.resolution_summary = ""
        notify_status_changed(self.ticket, 'OPEN', 'RESOLVED')
        self.assertNotIn('Resolution Summary', mail.outbox[0].body)

    def test_notify_new_response_sends_to_user_and_admin(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Admin replied'
        )
        notify_new_response(self.ticket, response)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(set(mail.outbox[0].to), {'donor@test.com', 'admin@test.com'})

    def test_notify_new_response_sends_only_to_user_if_unassigned(self):
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Admin replied'
        )
        notify_new_response(self.ticket, response)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['donor@test.com'])

    def test_notify_new_response_subject_and_body(self):
        long_msg = "X" * 300
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message=long_msg
        )
        notify_new_response(self.ticket, response)
        self.assertIn('New reply', mail.outbox[0].subject)
        # Should contain first 200 chars
        self.assertIn("X" * 200, mail.outbox[0].body)

    def test_notify_new_response_ignores_internal_note(self):
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Secret', is_internal_note=True
        )
        notify_new_response(self.ticket, response)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_internal_note_sends_to_assigned(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Secret', is_internal_note=True
        )
        notify_internal_note(self.ticket, response)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@test.com'])

    def test_notify_internal_note_subject_and_body(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Secret Message', is_internal_note=True
        )
        notify_internal_note(self.ticket, response)
        self.assertIn('Internal note', mail.outbox[0].subject)
        self.assertIn('Secret Message', mail.outbox[0].body)

    def test_notify_internal_note_ignores_unassigned(self):
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Secret', is_internal_note=True
        )
        notify_internal_note(self.ticket, response)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_internal_note_ignores_public_response(self):
        self.ticket.assigned_to = self.admin
        self.ticket.save()
        response = GrievanceResponse.objects.create(
            ticket=self.ticket, author=self.admin, message='Public', is_internal_note=False
        )
        notify_internal_note(self.ticket, response)
        self.assertEqual(len(mail.outbox), 0)

    def test_blank_email_skips_silently(self):
        self.ticket.user = self.no_email_user
        self.ticket.save()
        notify_ticket_created(self.ticket)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(GRIEVANCE_NOTIFICATIONS_ENABLED=False)
    @patch('grievances.notifications.GRIEVANCE_NOTIFICATIONS_ENABLED', False)
    def test_notifications_disabled(self):
        notify_ticket_created(self.ticket)
        self.assertEqual(len(mail.outbox), 0)

    @patch('grievances.notifications.send_mail')
    def test_notification_send_mail_fails_silently(self, mock_send):
        mock_send.side_effect = Exception("SMTP error")
        notify_ticket_created(self.ticket)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ServiceIntegrationTests(TestCase):
    def setUp(self):
        self.donor = User.objects.create_user(
            email='donor2@test.com',
            password='pass',
            full_name='Donor User',
            role=User.Role.DONOR
        )
        self.admin = User.objects.create_user(
            email='admin2@test.com',
            password='pass',
            full_name='Admin User',
            role=User.Role.ADMIN,
            is_staff=True
        )
        mail.outbox = []

    def test_create_ticket_hook(self):
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_create_response_hook_public(self):
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        mail.outbox = []
        GrievanceService.create_response(
            ticket=ticket, author=self.admin, validated_data={'message': 'Reply'}
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('New reply', mail.outbox[0].subject)

    def test_create_response_hook_internal(self):
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        GrievanceService.assign_ticket(ticket=ticket, assigned_to_user=self.admin, performed_by=self.admin)
        mail.outbox = []
        GrievanceService.create_response(
            ticket=ticket, author=self.admin, validated_data={'message': 'Secret', 'is_internal_note': True}, is_admin=True
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Internal note', mail.outbox[0].subject)

    def test_assign_ticket_hook(self):
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        mail.outbox = []
        GrievanceService.assign_ticket(ticket=ticket, assigned_to_user=self.admin, performed_by=self.admin)
        self.assertEqual(len(mail.outbox), 1)

    def test_transition_status_hook(self):
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        mail.outbox = []
        GrievanceService.transition_status(
            ticket=ticket, new_status='CLOSED', performed_by=self.admin, resolution_summary='Done.'
        )
        self.assertEqual(len(mail.outbox), 1)

    @patch('grievances.notifications.notify_ticket_created')
    def test_service_returns_ticket_when_hook_fails(self, mock_notify):
        mock_notify.side_effect = Exception("Hook failed!")
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        self.assertIsNotNone(ticket.pk)
        
    @patch('grievances.notifications.notify_ticket_assigned')
    def test_assign_returns_ticket_when_hook_fails(self, mock_notify):
        mock_notify.side_effect = Exception("Hook failed!")
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        locked = GrievanceService.assign_ticket(ticket=ticket, assigned_to_user=self.admin, performed_by=self.admin)
        self.assertIsNotNone(locked.assigned_to)

    @patch('grievances.notifications.notify_status_changed')
    def test_transition_returns_ticket_when_hook_fails(self, mock_notify):
        mock_notify.side_effect = Exception("Hook failed!")
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        locked = GrievanceService.transition_status(
            ticket=ticket, new_status='CLOSED', performed_by=self.admin, resolution_summary='Done.'
        )
        self.assertEqual(locked.status, 'CLOSED')

    @patch('grievances.notifications.notify_new_response')
    def test_response_returns_when_hook_fails(self, mock_notify):
        mock_notify.side_effect = Exception("Hook failed!")
        ticket = GrievanceService.create_ticket(
            user=self.donor,
            validated_data={'title': 'T1', 'description': 'D', 'category': 'GENERAL', 'priority': 'LOW'}
        )
        response = GrievanceService.create_response(
            ticket=ticket, author=self.donor, validated_data={'message': 'Reply'}
        )
        self.assertIsNotNone(response.pk)
