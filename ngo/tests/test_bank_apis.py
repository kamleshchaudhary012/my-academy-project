"""
DaanGives NGO Bank API Tests — Phase 3.3.2-C
=============================================
Mandatory test suite covering the 3 NGO Bank Information endpoints:
  - GET   /api/v1/ngo/bank/me/
  - POST  /api/v1/ngo/bank/me/
  - PATCH /api/v1/ngo/bank/me/

35 Core + Security Tests Covered:
  - Authentication (401 for unauthenticated GET/POST/PATCH)
  - Authorization (403 for DONOR and ADMIN on GET/POST/PATCH)
  - Ownership & IDOR Protection (Derived strictly from request.user)
  - Bank Data Security (account_number write_only, masked_account_number returned)
  - Bank Creation & Validation (DRAFT permitted, duplicates rejected, length/IFSC validated)
  - Bank Modification Lifecycle Rules (DRAFT & CORRECTION with bank_correction_requested=True allowed; all other states locked)
  - Integrity & Serialization Safety
"""

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse

from ngo.models import NGOProfile, NGOBankInfo, NGOVerification
from ngo.tests.helpers import make_user, make_ngo_profile, make_bank_info, make_admin_user


class TestNGOBankAPIs(APITestCase):

    def setUp(self):
        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')
        self.admin_user = make_admin_user()

        self.url_bank_me = reverse('ngo_bank_me')

        self.valid_bank_payload = {
            'bank_name': 'State Bank of India',
            'account_holder_name': 'Shree Seva Trust',
            'account_number': '123456789012',
            'ifsc_code': 'SBIN0001234',
            'branch_name': 'Main Branch, Ahmedabad',
            'account_type': 'CURRENT',
        }

    # -----------------------------------------------------------------------
    # 1. AUTHENTICATION TESTS (401 for unauthenticated)
    # -----------------------------------------------------------------------

    def test_01_unauthenticated_get_returns_401(self):
        response = self.client.get(self.url_bank_me)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_02_unauthenticated_post_returns_401(self):
        response = self.client.post(self.url_bank_me, self.valid_bank_payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_03_unauthenticated_patch_returns_401(self):
        response = self.client.patch(self.url_bank_me, {'branch_name': 'New Branch'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -----------------------------------------------------------------------
    # 2. ROLE AUTHORIZATION TESTS (403 for DONOR and ADMIN)
    # -----------------------------------------------------------------------

    def test_04_donor_get_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_bank_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_05_donor_post_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.post(self.url_bank_me, self.valid_bank_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_06_donor_patch_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'New Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_07_admin_get_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_bank_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_08_admin_post_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_bank_me, self.valid_bank_payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_09_admin_patch_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'New Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 3. OWNERSHIP & IDOR PROTECTION
    # -----------------------------------------------------------------------

    def test_10_ngo_a_can_access_only_ngo_a_bank_data(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['masked_account_number'], '****9012')

    def test_11_ngo_a_cannot_access_ngo_b_bank_data(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        make_bank_info(ngo_b, account_number='987654321099')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        # NGO A does not have bank info -> 404 (strictly isolated from NGO B)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_12_request_cannot_override_ownership_using_user_id(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_bank_payload, user_id=str(self.ngo_user_b.id))
        response = self.client.post(self.url_bank_me, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ngo_a.refresh_from_db()
        self.assertEqual(ngo_a.bank_info.account_holder_name, 'Shree Seva Trust')

    def test_13_request_cannot_override_ownership_using_ngo_id(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_bank_payload, ngo_id=str(ngo_b.id))
        response = self.client.post(self.url_bank_me, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ngo_a.refresh_from_db()
        self.assertEqual(ngo_a.bank_info.ngo, ngo_a)  # Assigned to NGO A, ignored payload param

    # -----------------------------------------------------------------------
    # 4. BANK CREATION & VALIDATION
    # -----------------------------------------------------------------------

    def test_14_valid_ngo_bank_post_in_draft_returns_201(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_bank_me, self.valid_bank_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['masked_account_number'], '****9012')
        self.assertNotIn('account_number', response.data)

    def test_15_duplicate_bank_post_returns_400(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_bank_me, self.valid_bank_payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already exists', response.data['detail'])

    def test_16_post_without_ngo_profile_returns_404(self):
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_bank_me, self.valid_bank_payload)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_17_invalid_account_number_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_bank_payload, account_number='INVALID_123')
        response = self.client.post(self.url_bank_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('account_number', response.data)

    def test_18_invalid_ifsc_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_bank_payload, ifsc_code='INVALID_IFSC')
        response = self.client.post(self.url_bank_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ifsc_code', response.data)

    # -----------------------------------------------------------------------
    # 5. RETRIEVAL & BANK DATA SECURITY
    # -----------------------------------------------------------------------

    def test_19_get_own_bank_returns_200(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_20_full_account_number_is_not_present_in_get_response(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo, account_number='123456789012')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        self.assertNotIn('account_number', response.data)

    def test_21_masked_account_number_is_present(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        self.assertIn('masked_account_number', response.data)

    def test_22_mask_shows_only_last_four_digits(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo, account_number='987654321099')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        self.assertEqual(response.data['masked_account_number'], '****1099')

    # -----------------------------------------------------------------------
    # 6. UPDATES & LIFECYCLE MODIFICATION RULES
    # -----------------------------------------------------------------------

    def test_23_patch_bank_in_draft_returns_200(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Navrangpura Branch'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['branch_name'], 'Navrangpura Branch')

    def test_24_patch_in_correction_required_with_flag_true_returns_200(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED')
        v, _ = NGOVerification.objects.get_or_create(ngo=ngo)
        v.bank_correction_requested = True
        v.save()

        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Corrected Branch'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['branch_name'], 'Corrected Branch')

    def test_25_patch_in_correction_required_with_flag_false_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED')
        v, _ = NGOVerification.objects.get_or_create(ngo=ngo)
        v.bank_correction_requested = False
        v.save()

        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Hacked Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_26_patch_in_submitted_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUBMITTED')
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Hacked Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_27_patch_in_under_review_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='UNDER_REVIEW')
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Hacked Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_28_patch_in_approved_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='APPROVED', is_active=True)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Hacked Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_29_patch_in_rejected_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='REJECTED')
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Hacked Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_30_patch_in_suspended_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUSPENDED')
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'branch_name': 'Hacked Branch'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 7. SECURITY & INTEGRITY
    # -----------------------------------------------------------------------

    def test_31_client_cannot_modify_bank_verification_fields(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'is_verified': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ngo.bank_info.refresh_from_db()
        self.assertFalse(ngo.bank_info.is_verified)  # Read-only field ignored

    def test_32_client_cannot_modify_ngo_ownership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        bank_a = make_bank_info(ngo_a)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'ngo': str(ngo_b.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bank_a.refresh_from_db()
        self.assertEqual(bank_a.ngo, ngo_a)  # NGO ownership untouched

    def test_33_client_cannot_modify_lifecycle_fields(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_bank_me, {'status': 'APPROVED'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ngo.refresh_from_db()
        self.assertEqual(ngo.status, 'DRAFT')

    def test_34_account_number_never_appears_in_serialized_response(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_bank_info(ngo, account_number='987654321012')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_bank_me)
        response_str = str(response.data)
        self.assertNotIn('987654321012', response_str)
        self.assertNotIn('account_number', response.data)

    def test_35_db_remains_unchanged_after_failed_validation(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        count_before = NGOBankInfo.objects.count()

        payload = dict(self.valid_bank_payload, ifsc_code='INVALID_IFSC')
        response = self.client.post(self.url_bank_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        count_after = NGOBankInfo.objects.count()
        self.assertEqual(count_before, count_after)
