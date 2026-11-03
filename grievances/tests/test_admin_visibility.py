"""
Phase 5.1.8 — Admin Grievance Visibility Regression Tests
==========================================================
Verifies that:
- Administrators (is_staff=True / role='ADMIN') can view platform-wide grievance tickets on GET /api/v1/grievances/tickets/.
- Cross-tenant isolation is strictly maintained for Donors, NGOs, and Companies (they see ONLY their own tickets).
- Filters (status, priority, category) and pagination work seamlessly for both Admin and standard users.
- Inactive or unauthenticated users cannot list tickets.
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from grievances.models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceStatus,
    GrievanceTicket,
)
from grievances.services import GrievanceService

User = get_user_model()


class AdminGrievanceVisibilityRegressionTests(APITestCase):
    """Test suite ensuring Admin platform-wide ticket visibility & strict multi-tenant isolation."""

    def setUp(self):
        # Admin / Staff user
        self.admin = User.objects.create_user(
            email='admin.oversight@example.com',
            password='testpassword123',
            first_name='Admin',
            last_name='Officer',
            role='ADMIN',
            is_staff=True,
            is_active=True,
        )

        # Inactive Admin user
        self.inactive_admin = User.objects.create_user(
            email='inactive.admin@example.com',
            password='testpassword123',
            role='ADMIN',
            is_staff=True,
            is_active=False,
        )

        # Company 1
        self.company_1 = User.objects.create_user(
            email='kk.industries@example.com',
            password='testpassword123',
            role='COMPANY',
            is_active=True,
        )

        # Company 2
        self.company_2 = User.objects.create_user(
            email='techcorp@example.com',
            password='testpassword123',
            role='COMPANY',
            is_active=True,
        )

        # NGO 1
        self.ngo_1 = User.objects.create_user(
            email='hope.foundation@example.com',
            password='testpassword123',
            role='NGO',
            is_active=True,
        )

        # NGO 2
        self.ngo_2 = User.objects.create_user(
            email='care.trust@example.com',
            password='testpassword123',
            role='NGO',
            is_active=True,
        )

        # Donor 1
        self.donor_1 = User.objects.create_user(
            email='rahul.donor@example.com',
            password='testpassword123',
            role='DONOR',
            is_active=True,
        )

        # Donor 2
        self.donor_2 = User.objects.create_user(
            email='priya.donor@example.com',
            password='testpassword123',
            role='DONOR',
            is_active=True,
        )

        # Create diverse tickets across roles, statuses, and assignments
        # Ticket 1: Company 1, Unassigned, OPEN, HIGH priority, DONATION_PAYMENT
        self.ticket_company_1 = GrievanceTicket.objects.create(
            user=self.company_1,
            title='Payment Gateway Timeout for CSR Deposit',
            description='CSR escrow transaction did not reconcile after deduction.',
            category=GrievanceCategory.DONATION_PAYMENT,
            priority=GrievancePriority.HIGH,
            status=GrievanceStatus.OPEN,
        )

        # Ticket 2: Company 2, Assigned to Admin, IN_REVIEW, MEDIUM priority, CSR_PARTNERSHIP_DISPUTE
        self.ticket_company_2 = GrievanceTicket.objects.create(
            user=self.company_2,
            title='MoU Milestone Approval Pending',
            description='NGO milestone pending administrative sign-off.',
            category=GrievanceCategory.CSR_PARTNERSHIP_DISPUTE,
            priority=GrievancePriority.MEDIUM,
            status=GrievanceStatus.IN_REVIEW,
            assigned_to=self.admin,
        )

        # Ticket 3: NGO 1, Assigned to Admin, RESOLVED, URGENT priority, NGO_CONDUCT
        self.ticket_ngo_1 = GrievanceTicket.objects.create(
            user=self.ngo_1,
            title='Defamatory Review on Verified Profile',
            description='False claims reported on public profile page.',
            category=GrievanceCategory.NGO_CONDUCT,
            priority=GrievancePriority.URGENT,
            status=GrievanceStatus.RESOLVED,
            assigned_to=self.admin,
            resolution_summary='Investigated and defamatory comments moderated.',
        )

        # Ticket 4: NGO 2, Unassigned, CLOSED, LOW priority, TECHNICAL_SUPPORT
        self.ticket_ngo_2 = GrievanceTicket.objects.create(
            user=self.ngo_2,
            title='Certificate Upload Form Issue',
            description='FCRA PDF file upload failed due to extension restriction.',
            category=GrievanceCategory.TECHNICAL_SUPPORT,
            priority=GrievancePriority.LOW,
            status=GrievanceStatus.CLOSED,
            resolution_summary='Resolved via technical patch.',
        )

        # Ticket 5: Donor 1, Unassigned, OPEN, MEDIUM priority, RECEIPT_80G
        self.ticket_donor_1 = GrievanceTicket.objects.create(
            user=self.donor_1,
            title='80G Certificate Missing PAN Information',
            description='Tax receipt generated without correct PAN identifier.',
            category=GrievanceCategory.RECEIPT_80G,
            priority=GrievancePriority.MEDIUM,
            status=GrievanceStatus.OPEN,
        )

        # Ticket 6: Donor 2, Unassigned, REJECTED, HIGH priority, CAMPAIGN_FRAUD
        self.ticket_donor_2 = GrievanceTicket.objects.create(
            user=self.donor_2,
            title='Campaign Organizer Contact Inactive',
            description='Organizer phone number unreachable.',
            category=GrievanceCategory.CAMPAIGN_FRAUD,
            priority=GrievancePriority.HIGH,
            status=GrievanceStatus.REJECTED,
            resolution_summary='Verified organizer contact updated by NGO admin.',
        )

        self.list_url = '/api/v1/grievances/tickets/'

    # -------------------------------------------------------------------------
    # TEST 1 - TEST 9: Admin Platform-Wide Visibility
    # -------------------------------------------------------------------------

    def test_01_admin_can_list_company_created_ticket(self):
        """TEST 1: Admin can list a Company-created ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_company_1.id), ticket_ids)

    def test_02_admin_can_list_ngo_created_ticket(self):
        """TEST 2: Admin can list an NGO-created ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_ngo_1.id), ticket_ids)

    def test_03_admin_can_list_donor_created_ticket(self):
        """TEST 3: Admin can list a Donor-created ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_donor_1.id), ticket_ids)

    def test_04_admin_can_list_unassigned_ticket(self):
        """TEST 4: Admin can list an unassigned ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_company_1.id), ticket_ids)
        self.assertIsNone(self.ticket_company_1.assigned_to)

    def test_05_admin_can_list_assigned_ticket(self):
        """TEST 5: Admin can list an assigned ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_company_2.id), ticket_ids)
        self.assertEqual(self.ticket_company_2.assigned_to, self.admin)

    def test_06_admin_can_list_open_ticket(self):
        """TEST 6: Admin can list OPEN ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f'{self.list_url}?status=OPEN')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_company_1.id), ticket_ids)
        self.assertIn(str(self.ticket_donor_1.id), ticket_ids)

    def test_07_admin_can_list_in_review_ticket(self):
        """TEST 7: Admin can list IN_REVIEW ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f'{self.list_url}?status=IN_REVIEW')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_company_2.id), ticket_ids)

    def test_08_admin_can_list_resolved_ticket(self):
        """TEST 8: Admin can list RESOLVED ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f'{self.list_url}?status=RESOLVED')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_ngo_1.id), ticket_ids)

    def test_09_admin_can_list_closed_ticket(self):
        """TEST 9: Admin can list CLOSED ticket."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f'{self.list_url}?status=CLOSED')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertIn(str(self.ticket_ngo_2.id), ticket_ids)

    # -------------------------------------------------------------------------
    # TEST 10 - TEST 16: Multi-Tenant Strict Isolation
    # -------------------------------------------------------------------------

    def test_10_company_sees_only_its_own_tickets(self):
        """TEST 10: Company sees only its own tickets."""
        self.client.force_authenticate(user=self.company_1)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['id'], str(self.ticket_company_1.id))

    def test_11_ngo_sees_only_its_own_tickets(self):
        """TEST 11: NGO sees only its own tickets."""
        self.client.force_authenticate(user=self.ngo_1)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['id'], str(self.ticket_ngo_1.id))

    def test_12_donor_sees_only_its_own_tickets(self):
        """TEST 12: Donor sees only its own tickets."""
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['id'], str(self.ticket_donor_1.id))

    def test_13_company_cannot_see_another_company_ticket(self):
        """TEST 13: Company cannot see another Company's ticket."""
        self.client.force_authenticate(user=self.company_1)
        res = self.client.get(self.list_url)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertNotIn(str(self.ticket_company_2.id), ticket_ids)

    def test_14_ngo_cannot_see_another_ngo_ticket(self):
        """TEST 14: NGO cannot see another NGO's ticket."""
        self.client.force_authenticate(user=self.ngo_1)
        res = self.client.get(self.list_url)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertNotIn(str(self.ticket_ngo_2.id), ticket_ids)

    def test_15_donor_cannot_see_another_donor_ticket(self):
        """TEST 15: Donor cannot see another Donor's ticket."""
        self.client.force_authenticate(user=self.donor_1)
        res = self.client.get(self.list_url)
        ticket_ids = [t['id'] for t in res.data['results']]
        self.assertNotIn(str(self.ticket_donor_2.id), ticket_ids)

    def test_16_non_admin_cannot_obtain_platform_wide_list(self):
        """TEST 16: Non-admin cannot obtain platform-wide grievance list."""
        for non_admin_user in [self.company_1, self.company_2, self.ngo_1, self.ngo_2, self.donor_1, self.donor_2]:
            self.client.force_authenticate(user=non_admin_user)
            res = self.client.get(self.list_url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertEqual(res.data['count'], 1)
            # Ensure none of them see all 6 tickets
            self.assertNotEqual(res.data['count'], 6)

    # -------------------------------------------------------------------------
    # TEST 17: Specific Regression for GRV-202609-00001
    # -------------------------------------------------------------------------

    def test_17_specific_regression_company_ticket_in_admin_list(self):
        """TEST 17: Specific regression: Company ticket appears in the Admin list."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ticket_numbers = [t['ticket_number'] for t in res.data['results']]
        self.assertIn(self.ticket_company_1.ticket_number, ticket_numbers)

    # -------------------------------------------------------------------------
    # TEST 18 - TEST 20: Filters and Pagination
    # -------------------------------------------------------------------------

    def test_18_admin_list_pagination_remains_correct(self):
        """TEST 18: Admin list pagination remains correct."""
        # Create 25 additional tickets to test pagination (page_size default is 20)
        bulk_tickets = [
            GrievanceTicket(
                user=self.donor_1,
                ticket_number=f'GRV-202609-PAG{i:04d}',
                title=f'Pagination Test Ticket {i}',
                description='Automated test description for pagination.',
                category=GrievanceCategory.OTHER,
                priority=GrievancePriority.LOW,
                status=GrievanceStatus.OPEN,
            )
            for i in range(1, 26)
        ]
        GrievanceTicket.objects.bulk_create(bulk_tickets)

        self.client.force_authenticate(user=self.admin)
        res_page_1 = self.client.get(f'{self.list_url}?page=1')
        self.assertEqual(res_page_1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_page_1.data['results']), 20)
        self.assertIsNotNone(res_page_1.data['next'])
        self.assertEqual(res_page_1.data['count'], 6 + 25)

        res_page_2 = self.client.get(f'{self.list_url}?page=2')
        self.assertEqual(res_page_2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_page_2.data['results']), 11)
        self.assertIsNone(res_page_2.data['next'])

    def test_19_admin_status_filter_remains_correct(self):
        """TEST 19: Admin status filter correctly subsets platform-wide tickets."""
        self.client.force_authenticate(user=self.admin)
        res_open = self.client.get(f'{self.list_url}?status=OPEN')
        self.assertEqual(res_open.status_code, status.HTTP_200_OK)
        self.assertTrue(all(t['status'] == 'OPEN' for t in res_open.data['results']))
        self.assertEqual(len(res_open.data['results']), 2)

    def test_20_admin_priority_and_category_filters_remain_correct(self):
        """TEST 20: Admin priority and category filters correctly subset platform-wide tickets."""
        self.client.force_authenticate(user=self.admin)
        
        # Priority filter: URGENT
        res_urgent = self.client.get(f'{self.list_url}?priority=URGENT')
        self.assertEqual(res_urgent.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_urgent.data['results']), 1)
        self.assertEqual(res_urgent.data['results'][0]['id'], str(self.ticket_ngo_1.id))

        # Category filter: CSR_PARTNERSHIP_DISPUTE
        res_csr = self.client.get(f'{self.list_url}?category=CSR_PARTNERSHIP_DISPUTE')
        self.assertEqual(res_csr.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_csr.data['results']), 1)
        self.assertEqual(res_csr.data['results'][0]['id'], str(self.ticket_company_2.id))

    # -------------------------------------------------------------------------
    # Additional Security & Isolation Edge Cases
    # -------------------------------------------------------------------------

    def test_unauthenticated_request_returns_401(self):
        """Unauthenticated user cannot access ticket list."""
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_admin_blocked_with_403(self):
        """Inactive Admin user is rejected by IsAuthenticatedAndActive."""
        self.client.force_authenticate(user=self.inactive_admin)
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_service_level_get_tickets_for_user_respects_is_admin(self):
        """Direct service call verifies is_admin parameter behavior."""
        # Standard user without is_admin
        donor_tickets = list(GrievanceService.get_tickets_for_user(user=self.donor_1))
        self.assertEqual(len(donor_tickets), 1)

        # Admin user
        admin_tickets = list(GrievanceService.get_tickets_for_user(user=self.admin))
        self.assertEqual(len(admin_tickets), 6)

        # Admin user with explicit is_admin=False (e.g. view personal complaints only)
        admin_personal = list(GrievanceService.get_tickets_for_user(user=self.admin, is_admin=False))
        self.assertEqual(len(admin_personal), 0)
