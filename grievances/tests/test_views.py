"""
Unit Tests for Grievance Views — Phase 5.1
===========================================
Tests authentication, authorization, validation, and error formatting for all 6 grievance views.
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


class GrievanceViewUnitTests(APITestCase):
    """Unit test suite for grievance endpoint views."""

    def setUp(self):
        self.user1 = User.objects.create_user(
            email='user1@example.com',
            password='testpassword123',
            first_name='Kavita',
            last_name='Nair',
            role='DONOR',
        )
        self.user2 = User.objects.create_user(
            email='user2@example.com',
            password='testpassword123',
            first_name='Dev',
            last_name='Mehta',
            role='DONOR',
        )
        self.staff_user = User.objects.create_user(
            email='staff@example.com',
            password='testpassword123',
            first_name='Support',
            last_name='Staff',
            role='STAFF',
            is_staff=True,
        )
        self.ticket1 = GrievanceTicket.objects.create(
            user=self.user1,
            title='Tax Receipt Delay',
            description='Waiting for 80G tax receipt for donation.',
            category=GrievanceCategory.RECEIPT_80G,
            priority=GrievancePriority.MEDIUM,
        )
        self.response1 = GrievanceResponse.objects.create(
            ticket=self.ticket1,
            author=self.user1,
            message='Initial complainant message.',
            is_internal_note=False,
        )

    # -------------------------------------------------------------------------
    # GrievanceTicketListCreateView Tests
    # -------------------------------------------------------------------------

    def test_ticket_list_unauthenticated_returns_401(self):
        response = self.client.get('/api/v1/grievances/tickets/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_ticket_create_unauthenticated_returns_401(self):
        response = self.client.post('/api/v1/grievances/tickets/', {'title': 'Valid Title', 'description': 'Valid Description'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_ticket_list_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/grievances/tickets/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)

    def test_ticket_create_valid_returns_201(self):
        self.client.force_authenticate(user=self.user1)
        payload = {
            'title': 'Campaign dispute report',
            'description': 'Campaign organizer did not publish progress report.',
            'category': GrievanceCategory.CAMPAIGN_FRAUD,
            'priority': GrievancePriority.HIGH,
        }
        response = self.client.post('/api/v1/grievances/tickets/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], payload['title'])
        self.assertEqual(response.data['user']['id'], str(self.user1.id))

    def test_ticket_create_invalid_input_returns_400(self):
        self.client.force_authenticate(user=self.user1)
        payload = {
            'title': 'Bad',  # Under 5 chars
            'description': 'Short',
            'category': GrievanceCategory.OTHER,
        }
        response = self.client.post('/api/v1/grievances/tickets/', payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'VALIDATION_ERROR')

    # -------------------------------------------------------------------------
    # GrievanceTicketDetailView Tests
    # -------------------------------------------------------------------------

    def test_ticket_detail_unauthenticated_returns_401(self):
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket1.id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_ticket_detail_wrong_user_returns_403(self):
        self.client.force_authenticate(user=self.user2)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket1.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_ticket_detail_owner_returns_200(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))

    def test_ticket_detail_nonexistent_returns_404(self):
        self.client.force_authenticate(user=self.user1)
        fake_uuid = '00000000-0000-0000-0000-000000000000'
        response = self.client.get(f'/api/v1/grievances/tickets/{fake_uuid}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get('code'), 'NOT_FOUND')

    # -------------------------------------------------------------------------
    # GrievanceTicketTransitionView Tests
    # -------------------------------------------------------------------------

    def test_ticket_transition_unauthenticated_returns_401(self):
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/transition/', {'new_status': GrievanceStatus.IN_REVIEW})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_ticket_transition_non_staff_returns_403(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/transition/', {'new_status': GrievanceStatus.IN_REVIEW})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_ticket_transition_staff_valid_returns_200(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/transition/', {'new_status': GrievanceStatus.IN_REVIEW})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], GrievanceStatus.IN_REVIEW)

    def test_ticket_transition_invalid_transition_returns_400(self):
        self.client.force_authenticate(user=self.staff_user)
        # Cannot transition OPEN directly to RESOLVED
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/transition/', {'new_status': GrievanceStatus.RESOLVED})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'INVALID_STATUS_TRANSITION')

    def test_ticket_transition_missing_status_returns_400(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/transition/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'VALIDATION_ERROR')

    # -------------------------------------------------------------------------
    # GrievanceTicketAssignView Tests
    # -------------------------------------------------------------------------

    def test_ticket_assign_unauthenticated_returns_401(self):
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/assign/', {'assigned_to_user_id': str(self.staff_user.id)})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_ticket_assign_non_staff_returns_403(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/assign/', {'assigned_to_user_id': str(self.staff_user.id)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_ticket_assign_staff_valid_returns_200(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/assign/', {'assigned_to_user_id': str(self.staff_user.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['assigned_to']['id'], str(self.staff_user.id))

    def test_ticket_assign_missing_user_returns_400(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/assign/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'VALIDATION_ERROR')

    def test_ticket_assign_nonexistent_user_returns_400(self):
        self.client.force_authenticate(user=self.staff_user)
        fake_uuid = '00000000-0000-0000-0000-000000000000'
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/assign/', {'assigned_to_user_id': fake_uuid})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'VALIDATION_ERROR')

    # -------------------------------------------------------------------------
    # GrievanceResponseListCreateView Tests
    # -------------------------------------------------------------------------

    def test_response_list_unauthenticated_returns_401(self):
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_response_create_unauthenticated_returns_401(self):
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/', {'message': 'Hello'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_response_list_wrong_user_returns_403(self):
        self.client.force_authenticate(user=self.user2)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_response_create_wrong_user_returns_403(self):
        self.client.force_authenticate(user=self.user2)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/', {'message': 'Unauthorized reply'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_response_list_owner_returns_200(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_response_create_owner_valid_returns_201(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/', {'message': 'Additional complainant info.'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['message'], 'Additional complainant info.')
        self.assertEqual(str(response.data['author']), str(self.user1.id))

    def test_response_create_invalid_input_returns_400(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(f'/api/v1/grievances/tickets/{self.ticket1.id}/responses/', {'message': ''})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get('code'), 'VALIDATION_ERROR')

    # -------------------------------------------------------------------------
    # GrievanceResponseUpdateView Tests
    # -------------------------------------------------------------------------

    def test_response_update_unauthenticated_returns_401(self):
        response = self.client.patch(f'/api/v1/grievances/responses/{self.response1.id}/', {'is_internal_note': False})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'NOT_AUTHENTICATED')

    def test_response_update_wrong_user_returns_403(self):
        self.client.force_authenticate(user=self.user2)
        response = self.client.patch(f'/api/v1/grievances/responses/{self.response1.id}/', {'is_internal_note': False})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_response_update_non_staff_cannot_mark_internal_note_returns_403(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.patch(f'/api/v1/grievances/responses/{self.response1.id}/', {'is_internal_note': True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_response_update_staff_can_mark_internal_note_returns_200(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.patch(f'/api/v1/grievances/responses/{self.response1.id}/', {'is_internal_note': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_internal_note'])
