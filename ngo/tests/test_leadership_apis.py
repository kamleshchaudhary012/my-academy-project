"""
DaanGives NGO Leadership API Tests — Phase 3.3.2-D
===================================================
Mandatory test suite covering the 5 NGO Leadership endpoints:
  - GET    /api/v1/ngo/leadership/
  - POST   /api/v1/ngo/leadership/
  - GET    /api/v1/ngo/leadership/<uuid>/
  - PATCH  /api/v1/ngo/leadership/<uuid>/
  - DELETE /api/v1/ngo/leadership/<uuid>/

30 Mandatory Tests Covered:
  1-3. Authentication (401 for unauthenticated)
  4-7. Role Authorization (403 for DONOR and ADMIN)
  8-12. Creation, Ownership Assignment & Primary Contact Validation
  13-16. List / Detail & Deterministic Ordering
  17-19. Update & Status Locking
  20-22. Delete / Soft-Deactivation & Status Locking
  23-25. Primary Contact Transition Rules
  26-30. Security, IDOR (404 on Cross-NGO UUID) & Response Isolation
"""

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse

from ngo.models import NGOProfile, NGOLeadership
from ngo.tests.helpers import make_user, make_ngo_profile, make_admin_user


class TestNGOLeadershipAPIs(APITestCase):

    def setUp(self):
        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')
        self.admin_user = make_admin_user()

        self.url_list_create = reverse('ngo_leadership_list_create')

        self.valid_leader_payload = {
            'full_name': 'Rameshchandra Patel',
            'designation': 'Managing Trustee',
            'phone': '+919876543210',
            'email': 'ramesh@trust.org',
            'is_primary_contact': True,
            'is_active': True,
            'order': 1,
        }

    def detail_url(self, pk):
        return reverse('ngo_leadership_detail', kwargs={'pk': pk})

    # -----------------------------------------------------------------------
    # 1. AUTHENTICATION TESTS (401)
    # -----------------------------------------------------------------------

    def test_01_unauthenticated_get_list_returns_401(self):
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_02_unauthenticated_post_returns_401(self):
        response = self.client.post(self.url_list_create, self.valid_leader_payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_03_unauthenticated_detail_returns_401(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        leader = NGOLeadership.objects.create(ngo=ngo, **self.valid_leader_payload)
        response = self.client.get(self.detail_url(leader.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -----------------------------------------------------------------------
    # 2. ROLE AUTHORIZATION TESTS (403)
    # -----------------------------------------------------------------------

    def test_04_donor_get_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_05_donor_post_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.post(self.url_list_create, self.valid_leader_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_06_admin_get_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_07_admin_post_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_list_create, self.valid_leader_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 3. CREATE & OWNERSHIP ASSIGNMENT
    # -----------------------------------------------------------------------

    def test_08_ngo_creates_leadership(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, self.valid_leader_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['full_name'], 'Rameshchandra Patel')

    def test_09_ownership_automatically_assigned_from_request_user(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, self.valid_leader_payload)
        leader = NGOLeadership.objects.get(pk=response.data['id'])
        self.assertEqual(leader.ngo, ngo_a)

    def test_10_client_cannot_override_ngo_ownership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        self.client.force_authenticate(user=self.ngo_user_a)

        payload_with_ngo_b = dict(self.valid_leader_payload, ngo=str(ngo_b.id))
        response = self.client.post(self.url_list_create, payload_with_ngo_b)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        leader = NGOLeadership.objects.get(pk=response.data['id'])
        self.assertEqual(leader.ngo, ngo_a)  # Assigned to NGO A

    def test_11_invalid_leadership_data_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_leader_payload, full_name='', phone='INVALID_PHONE')
        response = self.client.post(self.url_list_create, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_12_duplicate_primary_contact_rejected(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        payload_b = dict(self.valid_leader_payload, full_name='Second Leader', is_primary_contact=True)
        response = self.client.post(self.url_list_create, payload_b)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_primary_contact', response.data)

    # -----------------------------------------------------------------------
    # 4. LIST / DETAIL / ORDERING
    # -----------------------------------------------------------------------

    def test_13_ngo_sees_only_own_leadership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_14_ngo_a_cannot_see_ngo_b_leadership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        NGOLeadership.objects.create(ngo=ngo_b, full_name='Leader B', designation='Trustee')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_15_ngo_a_cannot_retrieve_ngo_b_detail(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        leader_b = NGOLeadership.objects.create(ngo=ngo_b, full_name='Leader B', designation='Trustee')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.detail_url(leader_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_16_deterministic_ordering_verified(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOLeadership.objects.create(ngo=ngo_a, full_name='Leader Second', order=2)
        NGOLeadership.objects.create(ngo=ngo_a, full_name='Leader First', order=1)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]['full_name'], 'Leader First')
        self.assertEqual(response.data[1]['full_name'], 'Leader Second')

    # -----------------------------------------------------------------------
    # 5. UPDATE
    # -----------------------------------------------------------------------

    def test_17_ngo_updates_own_leadership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        leader = NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.detail_url(leader.id), {'designation': 'Chairman'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['designation'], 'Chairman')

    def test_18_ngo_cannot_update_another_ngos_leadership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        leader_b = NGOLeadership.objects.create(ngo=ngo_b, full_name='Leader B', designation='Trustee')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.detail_url(leader_b.id), {'designation': 'Hacked'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_19_locked_status_prevents_patch(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        leader = NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='SUBMITTED')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.detail_url(leader.id), {'designation': 'Hacked'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 6. DELETE (SOFT-DEACTIVATION)
    # -----------------------------------------------------------------------

    def test_20_ngo_deactivates_own_leadership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        leader = NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(leader.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        leader.refresh_from_db()
        self.assertFalse(leader.is_active)  # Soft-deactivated to retain audit history

    def test_21_ngo_cannot_delete_another_ngos_leadership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        leader_b = NGOLeadership.objects.create(ngo=ngo_b, full_name='Leader B', designation='Trustee')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(leader_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_22_locked_status_prevents_delete(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        leader = NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='APPROVED', is_active=True)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(leader.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 7. PRIMARY CONTACT TRANSITION RULES
    # -----------------------------------------------------------------------

    def test_23_first_primary_contact_succeeds(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, self.valid_leader_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_primary_contact'])

    def test_24_second_primary_contact_fails(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        payload_b = dict(self.valid_leader_payload, full_name='Leader B', is_primary_contact=True)
        response = self.client.post(self.url_list_create, payload_b)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_25_primary_contact_transition_works(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        leader_a = NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        # Demote leader A to non-primary
        res_a = self.client.patch(self.detail_url(leader_a.id), {'is_primary_contact': False})
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)

        # Create leader B as primary
        payload_b = dict(self.valid_leader_payload, full_name='Leader B', is_primary_contact=True)
        res_b = self.client.post(self.url_list_create, payload_b)
        self.assertEqual(res_b.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res_b.data['is_primary_contact'])

    # -----------------------------------------------------------------------
    # 8. SECURITY, IDOR & RESPONSE ISOLATION
    # -----------------------------------------------------------------------

    def test_26_attempt_to_inject_ngo_id_ignored(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)

        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_leader_payload, ngo_id=str(ngo_b.id))
        response = self.client.post(self.url_list_create, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        leader = NGOLeadership.objects.get(pk=response.data['id'])
        self.assertEqual(leader.ngo, ngo_a)

    def test_27_attempt_to_inject_user_id_ignored(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_leader_payload, user_id=str(self.ngo_user_b.id))
        response = self.client.post(self.url_list_create, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_28_attempt_to_modify_protected_fields_ignored(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        leader = NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.detail_url(leader.id), {'id': '00000000-0000-0000-0000-000000000000'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        leader.refresh_from_db()
        self.assertNotEqual(str(leader.id), '00000000-0000-0000-0000-000000000000')

    def test_29_cross_ngo_uuid_access_returns_404(self):
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        leader_b = NGOLeadership.objects.create(ngo=ngo_b, full_name='Leader B', designation='Trustee')

        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.detail_url(leader_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_30_response_does_not_expose_unrelated_sensitive_data(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOLeadership.objects.create(ngo=ngo_a, **self.valid_leader_payload)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        leader_data = response.data[0]
        self.assertNotIn('password', leader_data)
        self.assertNotIn('bank_info', leader_data)
        self.assertNotIn('account_number', leader_data)
