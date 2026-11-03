"""
Integration Tests for Grievance REST APIs — Phase 5.1
=====================================================
Tests full end-to-end API workflows: ticket creation, filtering, detail retrieval,
state machine transitions, staff assignment, threaded messaging, pagination,
error schema formatting, and cross-endpoint IDOR isolation.
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from grievances.models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceResponse,
    GrievanceStatus,
    GrievanceTicket,
)

User = get_user_model()


class GrievanceAPIFullIntegrationTests(APITestCase):
    """Integration test suite covering all grievance endpoints."""

    def setUp(self):
        self.user_a = User.objects.create_user(
            email='alice@example.com',
            password='testpassword123',
            first_name='Alice',
            last_name='Nair',
            role='DONOR',
        )
        self.user_b = User.objects.create_user(
            email='bob@example.com',
            password='testpassword123',
            first_name='Bob',
            last_name='Kapoor',
            role='DONOR',
        )
        self.staff_officer = User.objects.create_user(
            email='staff.lead@example.com',
            password='testpassword123',
            first_name='Sunil',
            last_name='Verma',
            role='STAFF',
            is_staff=True,
        )

        self.ticket_a = GrievanceTicket.objects.create(
            user=self.user_a,
            title="Alice's Campaign Dispute",
            description='Detailed explanation of donation dispute.',
            category=GrievanceCategory.DONATION_PAYMENT,
            priority=GrievancePriority.HIGH,
            status=GrievanceStatus.OPEN,
        )
        self.ticket_b = GrievanceTicket.objects.create(
            user=self.user_b,
            title="Bob's 80G Certificate Inquiry",
            description='Detailed explanation of receipt inquiry.',
            category=GrievanceCategory.RECEIPT_80G,
            priority=GrievancePriority.LOW,
            status=GrievanceStatus.OPEN,
        )

    # -------------------------------------------------------------------------
    # Ticket Endpoints
    # -------------------------------------------------------------------------

    def test_post_tickets_creates_ticket_with_request_user(self):
        """POST /tickets/ associates ticket with authenticated user."""
        self.client.force_authenticate(user=self.user_a)
        payload = {
            'title': 'New Grievance Ticket Title',
            'description': 'Description with more than ten characters for validation.',
            'category': GrievanceCategory.TECHNICAL_SUPPORT,
            'priority': GrievancePriority.MEDIUM,
        }
        response = self.client.post('/api/v1/grievances/tickets/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['id'], str(self.user_a.id))
        self.assertEqual(response.data['status'], GrievanceStatus.OPEN)
        self.assertTrue(response.data['ticket_number'].startswith('GRV-'))

    def test_post_tickets_strips_forbidden_fields(self):
        """POST /tickets/ ignores client-injected ticket_number, user, status, and assigned_to."""
        self.client.force_authenticate(user=self.user_a)
        payload = {
            'title': 'Tamper Test Ticket',
            'description': 'Attempting to inject administrative fields.',
            'category': GrievanceCategory.OTHER,
            'ticket_number': 'GRV-FAKE-99999',
            'user': str(self.user_b.id),
            'status': GrievanceStatus.RESOLVED,
            'assigned_to': str(self.staff_officer.id),
        }
        response = self.client.post('/api/v1/grievances/tickets/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data['ticket_number'], 'GRV-FAKE-99999')
        self.assertEqual(response.data['user']['id'], str(self.user_a.id))
        self.assertEqual(response.data['status'], GrievanceStatus.OPEN)
        self.assertIsNone(response.data['assigned_to'])

    def test_get_tickets_lists_only_current_user_tickets(self):
        """GET /tickets/ returns only tickets owned by caller."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get('/api/v1/grievances/tickets/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        ticket_ids = [t['id'] for t in results]
        self.assertIn(str(self.ticket_a.id), ticket_ids)
        self.assertNotIn(str(self.ticket_b.id), ticket_ids)

    def test_get_tickets_filters_correctly(self):
        """GET /tickets/?status=...&priority=...&category=... filters properly."""
        self.client.force_authenticate(user=self.user_a)
        # Create extra ticket with different priority
        t_low = GrievanceTicket.objects.create(
            user=self.user_a,
            title='Low Priority Query',
            description='Description here.',
            category=GrievanceCategory.OTHER,
            priority=GrievancePriority.LOW,
            status=GrievanceStatus.OPEN,
        )

        resp_status = self.client.get('/api/v1/grievances/tickets/?status=OPEN')
        self.assertEqual(len(resp_status.data['results']), 2)

        resp_prio = self.client.get('/api/v1/grievances/tickets/?priority=HIGH')
        self.assertEqual(len(resp_prio.data['results']), 1)
        self.assertEqual(resp_prio.data['results'][0]['id'], str(self.ticket_a.id))

        resp_cat = self.client.get('/api/v1/grievances/tickets/?category=DONATION_PAYMENT')
        self.assertEqual(len(resp_cat.data['results']), 1)
        self.assertEqual(resp_cat.data['results'][0]['id'], str(self.ticket_a.id))

    def test_get_ticket_detail_returns_nested_responses(self):
        """GET /tickets/{id}/ returns full ticket representation with nested messages."""
        self.client.force_authenticate(user=self.user_a)
        GrievanceResponse.objects.create(
            ticket=self.ticket_a,
            author=self.user_a,
            message='Initial reply message.',
            is_internal_note=False,
        )
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket_a.id))
        self.assertIn('responses', response.data)
        self.assertEqual(len(response.data['responses']), 1)

    def test_get_ticket_detail_another_user_returns_403_with_code(self):
        """GET /tickets/{id}/ of foreign ticket returns 403 PERMISSION_DENIED."""
        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_get_ticket_detail_nonexistent_returns_404_with_code(self):
        """GET /tickets/{id}/ of non-existent UUID returns 404 NOT_FOUND."""
        self.client.force_authenticate(user=self.user_a)
        fake_uuid = '00000000-0000-0000-0000-000000000000'
        response = self.client.get(f'/api/v1/grievances/tickets/{fake_uuid}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get('code'), 'NOT_FOUND')

    def test_post_ticket_transition_valid_returns_200(self):
        """POST /tickets/{id}/transition/ by staff advances state to IN_REVIEW."""
        self.client.force_authenticate(user=self.staff_officer)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/transition/',
            {'new_status': GrievanceStatus.IN_REVIEW},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], GrievanceStatus.IN_REVIEW)

    def test_post_ticket_transition_invalid_returns_400_with_code(self):
        """POST /tickets/{id}/transition/ with illegal jump returns 400 INVALID_STATUS_TRANSITION."""
        self.client.force_authenticate(user=self.staff_officer)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/transition/',
            {'new_status': GrievanceStatus.RESOLVED},  # Cannot jump OPEN -> RESOLVED
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'INVALID_STATUS_TRANSITION')

    def test_post_ticket_transition_non_staff_returns_403(self):
        """POST /tickets/{id}/transition/ by regular user returns 403 PERMISSION_DENIED."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/transition/',
            {'new_status': GrievanceStatus.IN_REVIEW},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_post_ticket_assign_by_staff_returns_200(self):
        """POST /tickets/{id}/assign/ by staff assigns investigator successfully."""
        self.client.force_authenticate(user=self.staff_officer)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/assign/',
            {'assigned_to_user_id': str(self.staff_officer.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['assigned_to']['id'], str(self.staff_officer.id))

    def test_post_ticket_assign_by_non_staff_returns_403(self):
        """POST /tickets/{id}/assign/ by regular user returns 403 PERMISSION_DENIED."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/assign/',
            {'assigned_to_user_id': str(self.staff_officer.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    # -------------------------------------------------------------------------
    # Response Endpoints
    # -------------------------------------------------------------------------

    def test_post_responses_creates_response_with_author(self):
        """POST /tickets/{id}/responses/ assigns caller as author."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/',
            {'message': 'Alice submitting bank transaction reference.'},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data['author']), str(self.user_a.id))
        self.assertFalse(response.data['is_internal_note'])

    def test_post_responses_internal_note_by_non_admin_returns_403(self):
        """POST /tickets/{id}/responses/ with is_internal_note=True by non-staff returns 403."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/',
            {'message': 'Unauthorized internal note attempt.', 'is_internal_note': True},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_post_responses_internal_note_by_admin_returns_201(self):
        """POST /tickets/{id}/responses/ with is_internal_note=True by staff returns 201."""
        self.client.force_authenticate(user=self.staff_officer)
        response = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/',
            {'message': 'Internal staff investigation notes.', 'is_internal_note': True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_internal_note'])

    def test_get_responses_filters_internal_notes_for_non_admin(self):
        """GET /tickets/{id}/responses/ conceals internal notes from non-staff complainant."""
        GrievanceResponse.objects.create(
            ticket=self.ticket_a,
            author=self.staff_officer,
            message='Public update for user.',
            is_internal_note=False,
        )
        GrievanceResponse.objects.create(
            ticket=self.ticket_a,
            author=self.staff_officer,
            message='Private auditor note.',
            is_internal_note=True,
        )

        # Non-staff caller
        self.client.force_authenticate(user=self.user_a)
        response_non_staff = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/')
        self.assertEqual(response_non_staff.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_non_staff.data), 1)
        self.assertEqual(response_non_staff.data[0]['message'], 'Public update for user.')

        # Staff caller
        self.client.force_authenticate(user=self.staff_officer)
        response_staff = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/')
        self.assertEqual(response_staff.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_staff.data), 2)

    def test_patch_response_toggle_internal_note(self):
        """PATCH /responses/{id}/ by staff toggles is_internal_note successfully."""
        resp = GrievanceResponse.objects.create(
            ticket=self.ticket_a,
            author=self.staff_officer,
            message='Staff message.',
            is_internal_note=False,
        )
        self.client.force_authenticate(user=self.staff_officer)
        response = self.client.patch(
            f'/api/v1/grievances/responses/{resp.id}/',
            {'is_internal_note': True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_internal_note'])

    def test_patch_response_by_foreign_user_returns_403(self):
        """PATCH /responses/{id}/ by other user returns 403 PERMISSION_DENIED."""
        resp = GrievanceResponse.objects.create(
            ticket=self.ticket_a,
            author=self.user_a,
            message='Alice message.',
            is_internal_note=False,
        )
        self.client.force_authenticate(user=self.user_b)
        response = self.client.patch(
            f'/api/v1/grievances/responses/{resp.id}/',
            {'is_internal_note': False},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    # -------------------------------------------------------------------------
    # Comprehensive IDOR Across Endpoints
    # -------------------------------------------------------------------------

    def test_user_cannot_access_foreign_ticket_across_endpoints(self):
        """User B cannot access or modify User A's ticket across all ticket endpoints."""
        self.client.force_authenticate(user=self.user_b)

        # GET detail
        resp1 = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/')
        self.assertEqual(resp1.status_code, status.HTTP_403_FORBIDDEN)

        # GET responses
        resp2 = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/')
        self.assertEqual(resp2.status_code, status.HTTP_403_FORBIDDEN)

        # POST responses
        resp3 = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/responses/',
            {'message': 'Attacking foreign thread.'},
        )
        self.assertEqual(resp3.status_code, status.HTTP_403_FORBIDDEN)

        # POST transition
        resp4 = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/transition/',
            {'new_status': GrievanceStatus.CLOSED},
        )
        self.assertEqual(resp4.status_code, status.HTTP_403_FORBIDDEN)

        # POST assign
        resp5 = self.client.post(
            f'/api/v1/grievances/tickets/{self.ticket_a.id}/assign/',
            {'assigned_to_user_id': str(self.staff_officer.id)},
        )
        self.assertEqual(resp5.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # Error Response Format Verification
    # -------------------------------------------------------------------------

    def test_standardized_error_format_401(self):
        """Unauthenticated error payload adheres to {detail, code} format."""
        response = self.client.get('/api/v1/grievances/tickets/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('detail', response.data)
        self.assertEqual(response.data['code'], 'NOT_AUTHENTICATED')

    def test_standardized_error_format_403(self):
        """Forbidden error payload adheres to {detail, code} format."""
        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('detail', response.data)
        self.assertEqual(response.data['code'], 'PERMISSION_DENIED')

    # -------------------------------------------------------------------------
    # Pagination
    # -------------------------------------------------------------------------

    def test_tickets_pagination_structure_and_counts(self):
        """GET /tickets/ returns {count, next, previous, results} with 20 items per page."""
        self.client.force_authenticate(user=self.user_a)

        # Create 24 more tickets for user_a (total 25 with self.ticket_a)
        bulk_tickets = [
            GrievanceTicket(
                user=self.user_a,
                ticket_number=f'GRV-202609-PAG{i:04d}',
                title=f'Pagination Ticket {i}',
                description=f'Bulk test description for ticket {i}.',
                category=GrievanceCategory.OTHER,
            )
            for i in range(1, 25)
        ]
        GrievanceTicket.objects.bulk_create(bulk_tickets)

        # Page 1
        page1 = self.client.get('/api/v1/grievances/tickets/')
        self.assertEqual(page1.status_code, status.HTTP_200_OK)
        self.assertEqual(page1.data['count'], 25)
        self.assertIsNotNone(page1.data['next'])
        self.assertIsNone(page1.data['previous'])
        self.assertEqual(len(page1.data['results']), 20)

        # Page 2
        page2 = self.client.get(page1.data['next'])
        self.assertEqual(page2.status_code, status.HTTP_200_OK)
        self.assertEqual(page2.data['count'], 25)
        self.assertIsNone(page2.data['next'])
        self.assertIsNotNone(page2.data['previous'])
        self.assertEqual(len(page2.data['results']), 5)
