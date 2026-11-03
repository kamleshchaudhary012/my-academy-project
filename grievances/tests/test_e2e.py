from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.db.models import ProtectedError
import datetime

from grievances.models import (
    GrievanceTicket,
    GrievanceCategory,
    GrievancePriority,
    GrievanceStatus,
)
from campaigns.models import Campaign, MonetaryDonation
from ngo.models import NGOProfile
from csr.models import CompanyProfile, CSRRequirement, CSRPartnership, CSRSupportRequest

User = get_user_model()

class GrievanceE2ETests(APITestCase):
    """
    End-to-End API Integration tests for the Grievance module.
    Covers lifecycles across Donor, NGO, Company, and Admin roles.
    """

    def setUp(self):
        # Create users
        self.donor_a = User.objects.create_user(email='donorA@example.com', password='TestPassword123!', role=User.Role.DONOR)
        self.donor_b = User.objects.create_user(email='donorB@example.com', password='TestPassword123!', role=User.Role.DONOR)
        self.admin_user = User.objects.create_user(email='admin@example.com', password='TestPassword123!', role=User.Role.ADMIN, is_staff=True)
        self.ngo_user = User.objects.create_user(email='ngo@example.com', password='TestPassword123!', role=User.Role.NGO)
        self.company_user = User.objects.create_user(email='company@example.com', password='TestPassword123!', role=User.Role.COMPANY)

        # Setup related entities for Scenario 8
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user, 
            legal_name='Test NGO', 
            status='APPROVED',
            year_established=2020
        )
        
        self.campaign = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Save the Trees',
            short_description='Save the Trees',
            description='This is a detailed description of the campaign which is at least 30 chars.',
            target_amount=100000,
            status='ACTIVE',
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31)
        )
        
        self.donation = MonetaryDonation.objects.create(
            donor=self.donor_a,
            campaign=self.campaign,
            amount=500,
            status='SUCCESS',
            receipt_number='REC-123'
        )
        
        self.company_profile = CompanyProfile.objects.create(
            user=self.company_user,
            company_name='Test Corp',
            cin_number='L12345MH2023PTC123456',
            verification_status='APPROVED'
        )
        
        self.requirement = CSRRequirement.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Planting trees',
            schedule_vii_category='ENVIRONMENT',
            state='Maharashtra',
            district='Mumbai',
            beneficiary_demographic='ALL',
            summary='CSR initiative',
            detailed_description='Detailed CSR initiative description',
            expected_outcomes='Many trees',
            total_estimated_budget=500000,
            required_csr_funding=500000,
            start_date=datetime.date(2026, 1, 1),
            expected_completion_date=datetime.date(2026, 12, 31)
        )
        
        self.support_request = CSRSupportRequest.objects.create(
            company=self.company_profile,
            requirement=self.requirement,
            company_name_snapshot='Test Corp',
            spoc_name='John Doe',
            spoc_email='john@testcorp.com',
            proposed_funding=500000
        )
        
        self.partnership = CSRPartnership.objects.create(
            company=self.company_profile,
            ngo=self.ngo_profile,
            requirement=self.requirement,
            support_request=self.support_request,
            partnership_code='PT-12345',
            agreed_funding_amount=500000,
            execution_start_date=datetime.date(2026, 1, 1),
            target_completion_date=datetime.date(2026, 12, 31),
            status='ACTIVE'
        )

        self.list_create_url = reverse('grievances:ticket_list_create')

    # SCENARIO 1: Donor full lifecycle
    def test_scenario_1_donor_lifecycle(self):
        self.client.force_authenticate(user=self.donor_a)
        
        # 1. Create ticket
        payload = {
            'title': 'Test Donor Issue',
            'description': 'I have a problem with my donation.',
            'category': GrievanceCategory.DONATION_PAYMENT,
            'priority': GrievancePriority.HIGH
        }
        resp = self.client.post(self.list_create_url, payload)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        ticket_id = resp.data['id']
        self.assertTrue('ticket_number' in resp.data)
        
        # 2. List ticket
        resp_list = self.client.get(self.list_create_url)
        self.assertEqual(resp_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_list.data['results']), 1)
        self.assertEqual(resp_list.data['results'][0]['id'], ticket_id)
        
        # 3. Get details
        detail_url = reverse('grievances:ticket_detail', args=[ticket_id])
        resp_detail = self.client.get(detail_url)
        self.assertEqual(resp_detail.status_code, status.HTTP_200_OK)
        
        # 4. Donor adds reply
        response_url = reverse('grievances:response_list_create', args=[ticket_id])
        resp_reply = self.client.post(response_url, {'message': 'Just following up.'})
        self.assertEqual(resp_reply.status_code, status.HTTP_201_CREATED)

        # 5. Admin transitions
        self.client.force_authenticate(user=self.admin_user)
        transition_url = reverse('grievances:ticket_transition', args=[ticket_id])
        
        self.client.post(transition_url, {'new_status': GrievanceStatus.IN_REVIEW})
        ticket = GrievanceTicket.objects.get(id=ticket_id)
        self.assertEqual(ticket.status, GrievanceStatus.IN_REVIEW)
        
        self.client.post(transition_url, {'new_status': GrievanceStatus.RESOLVED, 'resolution_summary': 'Fixed issue'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, GrievanceStatus.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)
        
        self.client.post(transition_url, {'new_status': GrievanceStatus.CLOSED})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, GrievanceStatus.CLOSED)
        
        # Verify donor sees closed state
        self.client.force_authenticate(user=self.donor_a)
        donor_detail = self.client.get(detail_url)
        self.assertEqual(donor_detail.data['status'], GrievanceStatus.CLOSED)

    # SCENARIO 2: IDOR across roles
    def test_scenario_2_idor_across_roles(self):
        ticket = GrievanceTicket.objects.create(
            user=self.donor_a, title='Donor A Ticket', description='Detailed description', category=GrievanceCategory.OTHER
        )
        detail_url = reverse('grievances:ticket_detail', args=[ticket.id])
        response_url = reverse('grievances:response_list_create', args=[ticket.id])
        
        # Donor B tries to access A's ticket
        self.client.force_authenticate(user=self.donor_b)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(response_url, {'message': 'Hello'}).status_code, status.HTTP_403_FORBIDDEN)
        
        list_resp = self.client.get(self.list_create_url)
        self.assertEqual(list_resp.data['count'], 0) # B shouldn't see A's tickets
        
        # NGO tries to access A's ticket
        self.client.force_authenticate(user=self.ngo_user)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)

    # SCENARIO 3: Admin full control
    def test_scenario_3_admin_full_control(self):
        ticket = GrievanceTicket.objects.create(
            user=self.donor_a, title='Ticket for admin', description='Detailed description', category=GrievanceCategory.OTHER
        )
        self.client.force_authenticate(user=self.admin_user)
        
        # Assign
        assign_url = reverse('grievances:ticket_assign', args=[ticket.id])
        assign_resp = self.client.post(assign_url, {'assigned_to_user_id': str(self.admin_user.id)})
        self.assertEqual(assign_resp.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.admin_user)
        
        # Internal Note
        response_url = reverse('grievances:response_list_create', args=[ticket.id])
        note_resp = self.client.post(response_url, {'message': 'Secret note', 'is_internal_note': True})
        self.assertEqual(note_resp.status_code, status.HTTP_201_CREATED)
        
        # Admin fetching responses sees internal note
        admin_responses = self.client.get(response_url)
        self.assertEqual(len(admin_responses.data), 1)
        self.assertTrue(admin_responses.data[0]['is_internal_note'])
        
        # Donor fetching responses does not see internal note
        self.client.force_authenticate(user=self.donor_a)
        donor_responses = self.client.get(response_url)
        self.assertEqual(len(donor_responses.data), 0)
        
        # Admin invalid transition
        self.client.force_authenticate(user=self.admin_user)
        transition_url = reverse('grievances:ticket_transition', args=[ticket.id])
        invalid_trans = self.client.post(transition_url, {'new_status': GrievanceStatus.RESOLVED}) # Can't jump from OPEN to RESOLVED
        self.assertEqual(invalid_trans.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid_trans.data['code'], 'INVALID_STATUS_TRANSITION')

    # SCENARIO 4: NGO lifecycle
    def test_scenario_4_ngo_lifecycle(self):
        self.client.force_authenticate(user=self.ngo_user)
        
        payload = {'title': 'NGO Ticket', 'description': 'Detailed description', 'category': GrievanceCategory.OTHER}
        resp = self.client.post(self.list_create_url, payload)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        ticket_id = resp.data['id']
        
        # NGO can view own
        detail_url = reverse('grievances:ticket_detail', args=[ticket_id])
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)
        
        # NGO cannot transition/assign
        transition_url = reverse('grievances:ticket_transition', args=[ticket_id])
        assign_url = reverse('grievances:ticket_assign', args=[ticket_id])
        response_url = reverse('grievances:response_list_create', args=[ticket_id])
        
        self.assertEqual(self.client.post(transition_url, {'new_status': GrievanceStatus.IN_REVIEW}).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(assign_url, {'assigned_to_user_id': str(self.admin_user.id)}).status_code, status.HTTP_403_FORBIDDEN)
        
        # NGO cannot post internal note
        note_resp = self.client.post(response_url, {'message': 'My Note', 'is_internal_note': True})
        self.assertEqual(note_resp.status_code, status.HTTP_403_FORBIDDEN)

    # SCENARIO 5: Company (CSR) lifecycle
    def test_scenario_5_company_lifecycle(self):
        self.client.force_authenticate(user=self.company_user)
        
        payload = {'title': 'Company Ticket', 'description': 'Detailed description', 'category': GrievanceCategory.OTHER}
        resp = self.client.post(self.list_create_url, payload)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        ticket_id = resp.data['id']
        
        detail_url = reverse('grievances:ticket_detail', args=[ticket_id])
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)
        
        transition_url = reverse('grievances:ticket_transition', args=[ticket_id])
        self.assertEqual(self.client.post(transition_url, {'new_status': GrievanceStatus.IN_REVIEW}).status_code, status.HTTP_403_FORBIDDEN)

    # SCENARIO 6: Error format consistency
    def test_scenario_6_error_format(self):
        # 401 Not Authenticated
        self.client.logout()
        resp_401 = self.client.get(self.list_create_url)
        self.assertEqual(resp_401.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp_401.data['code'], 'NOT_AUTHENTICATED')
        
        # 403 Permission Denied
        ticket = GrievanceTicket.objects.create(user=self.donor_a, title='Ticket for format', description='Detailed description', category=GrievanceCategory.OTHER)
        self.client.force_authenticate(user=self.donor_b)
        resp_403 = self.client.get(reverse('grievances:ticket_detail', args=[ticket.id]))
        self.assertEqual(resp_403.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_403.data['code'], 'PERMISSION_DENIED')
        
        # 404 Not Found
        self.client.force_authenticate(user=self.donor_a)
        import uuid
        resp_404 = self.client.get(reverse('grievances:ticket_detail', args=[uuid.uuid4()]))
        self.assertEqual(resp_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp_404.data['code'], 'NOT_FOUND')

    # SCENARIO 7: Pagination
    def test_scenario_7_pagination(self):
        self.client.force_authenticate(user=self.donor_a)
        
        for i in range(25):
            GrievanceTicket.objects.create(user=self.donor_a, title=f'Ticket {i}', description='Detailed description', category=GrievanceCategory.OTHER)
        
        resp = self.client.get(self.list_create_url)
        self.assertEqual(resp.data['count'], 25)
        self.assertEqual(len(resp.data['results']), 20)
        self.assertIsNotNone(resp.data['next'])
        self.assertIsNone(resp.data['previous'])
        
        resp_page2 = self.client.get(self.list_create_url + '?page=2')
        self.assertEqual(len(resp_page2.data['results']), 5)

    # SCENARIO 8: Cross-app references
    def test_scenario_8_cross_app_references(self):
        self.client.force_authenticate(user=self.donor_a)
        
        # Create with all foreign keys
        payload = {
            'title': 'Cross App Ticket',
            'description': 'Complex linkages',
            'category': GrievanceCategory.OTHER,
            'donation': str(self.donation.id),
            'campaign': str(self.campaign.id),
            'partnership': str(self.partnership.id),
            'target_ngo': str(self.ngo_profile.id),
        }
        resp = self.client.post(self.list_create_url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        
        ticket = GrievanceTicket.objects.get(id=resp.data['id'])
        self.assertEqual(ticket.donation, self.donation)
        self.assertEqual(ticket.campaign, self.campaign)
        self.assertEqual(ticket.partnership, self.partnership)
        self.assertEqual(ticket.target_ngo, self.ngo_profile)
        
        # Verify PROTECT
        with self.assertRaises(ProtectedError):
            self.donation.delete()
