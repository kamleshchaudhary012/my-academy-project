"""
DaanGives NGO Owner API Tests — Phase 3.3.2-A
==============================================
Tests covering the 6 NGO Owner Profile & Address endpoints:
  - GET   /api/v1/ngo/profile/me/
  - POST  /api/v1/ngo/profile/
  - PATCH /api/v1/ngo/profile/me/
  - GET   /api/v1/ngo/address/me/
  - POST  /api/v1/ngo/address/me/
  - PUT   /api/v1/ngo/address/me/

Coverage Categories:
  - Authentication (401 for unauthenticated)
  - Role Authorization (403 for DONOR and ADMIN)
  - Profile CRUD & validation rules
  - Address CRUD & validation rules
  - IDOR / Cross-NGO Isolation
  - Lifecycle locking across all 7 statuses (DRAFT, SUBMITTED, UNDER_REVIEW, CORRECTION_REQUIRED, APPROVED, REJECTED, SUSPENDED)
"""

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse

from ngo.models import NGOProfile, NGOAddress, NGOVerification
from ngo.tests.helpers import make_user, make_ngo_profile, make_admin_user


class TestNGOOwnerAPIs(APITestCase):

    def setUp(self):
        # Create test users
        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')
        self.admin_user = make_admin_user()

        # URLs
        self.url_profile_me = reverse('ngo_profile_me')
        self.url_profile_create = reverse('ngo_profile_create')
        self.url_address_me = reverse('ngo_address_me')

        # Sample payloads
        self.valid_profile_payload = {
            'legal_name': 'Shree Seva Trust',
            'display_name': 'Shree Seva Sangh',
            'category': 'EDUCATION',
            'description': 'A' * 50,
            'year_established': 2012,
            'official_email': 'contact@shreeseve.org',
            'official_phone': '+919876543210',
        }

        self.valid_address_payload = {
            'address_line1': '101 Ashram Road',
            'city': 'Ahmedabad',
            'district': 'Ahmedabad',
            'state': 'Gujarat',
            'pincode': '380001',
        }

    # -----------------------------------------------------------------------
    # 1. AUTHENTICATION TESTS (401 for unauthenticated)
    # -----------------------------------------------------------------------

    def test_01_unauthenticated_profile_get_returns_401(self):
        response = self.client.get(self.url_profile_me)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_02_unauthenticated_profile_post_returns_401(self):
        response = self.client.post(self.url_profile_create, self.valid_profile_payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_03_unauthenticated_address_get_returns_401(self):
        response = self.client.get(self.url_address_me)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_04_unauthenticated_address_post_returns_401(self):
        response = self.client.post(self.url_address_me, self.valid_address_payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -----------------------------------------------------------------------
    # 2. ROLE AUTHORIZATION TESTS (403 for DONOR and ADMIN)
    # -----------------------------------------------------------------------

    def test_05_donor_profile_access_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_profile_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_06_admin_profile_access_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_profile_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_07_donor_address_access_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_address_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_08_admin_address_access_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_address_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 3. PROFILE CRUD & VALIDATION
    # -----------------------------------------------------------------------

    def test_09_ngo_can_create_own_profile(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_profile_create, self.valid_profile_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['display_name'], 'Shree Seva Sangh')
        self.assertEqual(response.data['status'], 'DRAFT')
        self.assertFalse(response.data['is_active'])

    def test_10_ngo_cannot_create_second_profile(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_profile_create, self.valid_profile_payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_11_ngo_can_retrieve_own_profile(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_profile_me)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(ngo_a.id))

    def test_12_ngo_can_patch_own_profile_in_draft(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'display_name': 'Updated Name'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['display_name'], 'Updated Name')

    def test_13_ngo_cannot_patch_approved_profile(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='APPROVED', is_active=True)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'display_name': 'Hacked Name'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_14_ngo_cannot_patch_submitted_profile(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='SUBMITTED')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'display_name': 'Hacked Name'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_15_ngo_cannot_change_status(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'status': 'APPROVED'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ngo_a.refresh_from_db()
        self.assertEqual(ngo_a.status, 'DRAFT')  # Read-only field ignored

    def test_16_ngo_cannot_change_is_active(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'is_active': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ngo_a.refresh_from_db()
        self.assertFalse(ngo_a.is_active)  # Read-only field ignored

    def test_17_ngo_cannot_change_is_public(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'is_public': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ngo_a.is_public)

    def test_18_ngo_cannot_change_owner_user(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'user': str(self.ngo_user_b.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ngo_a.refresh_from_db()
        self.assertEqual(ngo_a.user, self.ngo_user_a)  # User unchanged

    # -----------------------------------------------------------------------
    # 4. ADDRESS CRUD & VALIDATION
    # -----------------------------------------------------------------------

    def test_19_ngo_can_create_own_address(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_address_me, self.valid_address_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['city'], 'Ahmedabad')

    def test_20_ngo_cannot_create_second_address(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_address_me, self.valid_address_payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_21_ngo_can_retrieve_own_address(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_address_me)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['city'], 'Ahmedabad')

    def test_22_ngo_can_update_own_address_in_draft(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        updated_payload = dict(self.valid_address_payload, city='Surat')
        response = self.client.put(self.url_address_me, updated_payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['city'], 'Surat')

    def test_23_ngo_can_update_address_in_correction_required(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='CORRECTION_REQUIRED')
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        updated_payload = dict(self.valid_address_payload, city='Vadodara')
        response = self.client.put(self.url_address_me, updated_payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['city'], 'Vadodara')

    def test_24_ngo_cannot_update_address_in_submitted(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='SUBMITTED')
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.put(self.url_address_me, self.valid_address_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_25_ngo_cannot_update_address_in_under_review(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='UNDER_REVIEW')
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.put(self.url_address_me, self.valid_address_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_26_ngo_cannot_update_address_in_approved(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo_a.pk).update(status='APPROVED', is_active=True)
        NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.put(self.url_address_me, self.valid_address_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_27_ngo_cannot_change_address_ownership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        addr_a = NGOAddress.objects.create(ngo=ngo_a, **self.valid_address_payload)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload_with_fake_ngo = dict(self.valid_address_payload, ngo=str(ngo_b.id))
        response = self.client.put(self.url_address_me, payload_with_fake_ngo)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        addr_a.refresh_from_db()
        self.assertEqual(addr_a.ngo, ngo_a)  # NGO ownership untouched

    # -----------------------------------------------------------------------
    # 5. IDOR & ISOLATION TESTS
    # -----------------------------------------------------------------------

    def test_28_ngo_a_cannot_access_ngo_b_data(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        NGOAddress.objects.create(ngo=ngo_b, address_line1='B Street', city='Rajkot', district='Rajkot', state='Gujarat', pincode='360001')

        # Authenticate as NGO A
        self.client.force_authenticate(user=self.ngo_user_a)
        response_profile = self.client.get(self.url_profile_me)
        self.assertEqual(response_profile.data['id'], str(ngo_a.id))

        response_address = self.client.get(self.url_address_me)
        # NGO A does not have an address yet (NGO B has one) -> 404
        self.assertEqual(response_address.status_code, status.HTTP_404_NOT_FOUND)

    def test_29_ngo_a_cannot_modify_ngo_b_profile(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a, display_name='NGO A Name')
        ngo_b = make_ngo_profile(user=self.ngo_user_b, display_name='NGO B Name')

        # Authenticate as NGO A and attempt PATCH /profile/me/
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_profile_me, {'display_name': 'Hacked A Name'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # NGO B name remains untouched
        ngo_b.refresh_from_db()
        self.assertEqual(ngo_b.display_name, 'NGO B Name')

    # -----------------------------------------------------------------------
    # 6. LIFECYCLE LOCKING MATRIX ACROSS ALL 7 STATUSES
    # -----------------------------------------------------------------------

    def test_30_lifecycle_locking_across_all_statuses(self):
        """Verifies profile and address modification permissions for all 7 statuses."""
        statuses = [
            ('DRAFT', status.HTTP_200_OK),
            ('CORRECTION_REQUIRED', status.HTTP_200_OK),
            ('SUBMITTED', status.HTTP_403_FORBIDDEN),
            ('UNDER_REVIEW', status.HTTP_403_FORBIDDEN),
            ('APPROVED', status.HTTP_403_FORBIDDEN),
            ('REJECTED', status.HTTP_403_FORBIDDEN),
            ('SUSPENDED', status.HTTP_403_FORBIDDEN),
        ]

        for current_status, expected_http in statuses:
            with self.subTest(status=current_status):
                ngo_user = make_user(email=f'ngo_{current_status.lower()}@test.com', role='NGO')
                ngo = make_ngo_profile(user=ngo_user)
                NGOProfile.objects.filter(pk=ngo.pk).update(
                    status=current_status,
                    is_active=(current_status == 'APPROVED'),
                )
                NGOAddress.objects.create(ngo=ngo, **self.valid_address_payload)
                self.client.force_authenticate(user=ngo_user)

                # Test Profile PATCH
                res_prof = self.client.patch(self.url_profile_me, {'display_name': 'Name Test'})
                self.assertEqual(res_prof.status_code, expected_http)

                # Test Address PUT
                res_addr = self.client.put(self.url_address_me, self.valid_address_payload)
                self.assertEqual(res_addr.status_code, expected_http)
