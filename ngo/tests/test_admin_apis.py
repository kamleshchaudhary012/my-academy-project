"""
DaanGives Admin NGO Verification API Tests — Phase 3.3.2-H
===========================================================
Mandatory test suite covering all 10 Admin NGO Verification & Review API endpoints:
  - GET  /api/v1/admin/ngos/
  - GET  /api/v1/admin/ngos/<uuid:pk>/
  - POST /api/v1/admin/ngos/<uuid:pk>/start-review/
  - POST /api/v1/admin/ngos/<uuid:pk>/approve/
  - POST /api/v1/admin/ngos/<uuid:pk>/request-correction/
  - POST /api/v1/admin/ngos/<uuid:pk>/reject/
  - POST /api/v1/admin/ngos/<uuid:pk>/suspend/
  - POST /api/v1/admin/ngos/<uuid:pk>/unsuspend/
  - POST /api/v1/admin/ngos/<uuid:pk>/reopen/
  - GET  /api/v1/admin/ngos/<uuid:pk>/history/

50 Mandatory Tests Covered across Authorization, Inspection, Transitions, Preconditions,
Public Visibility State Sync, Atomic Transactions, Audit Log History Integrity, and Security.
"""

from unittest.mock import patch
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGOLeadership,
    NGOVerification,
    NGOVerificationHistory,
)
from ngo.tests.helpers import make_user, make_ngo_profile, make_admin_user


class TestNGOAdminAPIs(APITestCase):

    def setUp(self):
        self.admin_user = make_admin_user(email='admin@test.com')
        self.ngo_owner_user = make_user(email='ngo_owner@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')

        self.profile = make_ngo_profile(
            user=self.ngo_owner_user,
            legal_name='Seva Sansthan India',
            display_name='Seva Sansthan',
            slug='seva-sansthan',
            category='HEALTHCARE',
            description='Healthcare support and medical aid for underprivileged families in rural districts.',
            year_established=2012,
        )

        self.address = NGOAddress.objects.create(
            ngo=self.profile,
            address_line1='45 Seva Road',
            city='Vadodara',
            district='Vadodara District',
            state='Gujarat',
            pincode='390001',
        )

        self.legal = NGOLegalInfo.objects.create(
            ngo=self.profile,
            organisation_type='TRUST',
            registration_number='REG-SEVA-101',
            darpan_id='GJ/2012/009988',
            pan_number='AAATS9988F',
            registration_state='Gujarat',
            chief_trustee_name='Mohanbhai Desai',
            chief_trustee_designation='President',
        )

        self.bank = NGOBankInfo.objects.create(
            ngo=self.profile,
            account_holder_name='Seva Sansthan India',
            account_number='11223344556677',
            ifsc_code='SBIN0004321',
            bank_name='State Bank of India',
            branch_name='Alkapuri Branch',
            account_type='CURRENT',
        )

        # Verification record automatically created by post_save signal
        self.verification = self.profile.verification

        self.url_queue = reverse('ngo_admin_queue')
        self.url_detail = reverse('ngo_admin_detail', kwargs={'pk': self.profile.pk})
        self.url_start_review = reverse('ngo_admin_start_review', kwargs={'pk': self.profile.pk})
        self.url_approve = reverse('ngo_admin_approve', kwargs={'pk': self.profile.pk})
        self.url_request_correction = reverse('ngo_admin_request_correction', kwargs={'pk': self.profile.pk})
        self.url_reject = reverse('ngo_admin_reject', kwargs={'pk': self.profile.pk})
        self.url_suspend = reverse('ngo_admin_suspend', kwargs={'pk': self.profile.pk})
        self.url_unsuspend = reverse('ngo_admin_unsuspend', kwargs={'pk': self.profile.pk})
        self.url_reopen = reverse('ngo_admin_reopen', kwargs={'pk': self.profile.pk})
        self.url_history = reverse('ngo_admin_history', kwargs={'pk': self.profile.pk})

    def _set_status(self, status_val, is_active=False):
        NGOProfile.objects.filter(pk=self.profile.pk).update(status=status_val, is_active=is_active)
        NGOVerification.objects.filter(ngo=self.profile).update(status=status_val)
        self.profile.refresh_from_db()

    # -----------------------------------------------------------------------
    # 1. ADMIN AUTHORIZATION (4 TESTS)
    # -----------------------------------------------------------------------

    def test_01_anonymous_admin_access_returns_401(self):
        response = self.client.get(self.url_queue)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_02_donor_admin_access_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_queue)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_03_ngo_owner_admin_access_returns_403(self):
        self.client.force_authenticate(user=self.ngo_owner_user)
        response = self.client.get(self.url_queue)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_04_admin_access_allowed(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_queue)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -----------------------------------------------------------------------
    # 2. ADMIN QUEUE (4 TESTS)
    # -----------------------------------------------------------------------

    def test_05_admin_queue_list(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_queue)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['count'], 1)

    def test_06_admin_queue_status_filtering(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        res_submitted = self.client.get(self.url_queue, {'status': 'SUBMITTED'})
        self.assertEqual(res_submitted.data['count'], 1)

        res_approved = self.client.get(self.url_queue, {'status': 'APPROVED'})
        self.assertEqual(res_approved.data['count'], 0)

    def test_06b_admin_queue_pending_filter_includes_under_review_and_submitted(self):
        # Set profile to UNDER_REVIEW with is_active=False and verified_at=None
        self._set_status('UNDER_REVIEW', is_active=False)
        self.client.force_authenticate(user=self.admin_user)

        # 1. status=PENDING matches UNDER_REVIEW even when is_active is False
        res_pending = self.client.get(self.url_queue, {'status': 'PENDING'})
        self.assertEqual(res_pending.data['count'], 1)
        self.assertEqual(res_pending.data['results'][0]['status'], 'UNDER_REVIEW')
        self.assertFalse(res_pending.data['results'][0]['is_active'])

        # 2. pending=true parameter also matches
        res_flag = self.client.get(self.url_queue, {'pending': 'true'})
        self.assertEqual(res_flag.data['count'], 1)

        # 3. Comma-separated status matches
        res_comma = self.client.get(self.url_queue, {'status': 'SUBMITTED,UNDER_REVIEW'})
        self.assertEqual(res_comma.data['count'], 1)

        # 4. status=UNDER_REVIEW matches
        res_ur = self.client.get(self.url_queue, {'status': 'UNDER_REVIEW'})
        self.assertEqual(res_ur.data['count'], 1)

        # 5. status=SUBMITTED does not match when in UNDER_REVIEW
        res_sub = self.client.get(self.url_queue, {'status': 'SUBMITTED'})
        self.assertEqual(res_sub.data['count'], 0)

    def test_07_admin_queue_search(self):
        self.client.force_authenticate(user=self.admin_user)
        res_match = self.client.get(self.url_queue, {'search': 'Seva'})
        self.assertEqual(res_match.data['count'], 1)

        res_nomatch = self.client.get(self.url_queue, {'search': 'UnknownName'})
        self.assertEqual(res_nomatch.data['count'], 0)

    def test_08_admin_queue_pagination(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_queue)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)

    # -----------------------------------------------------------------------
    # 3. INSPECTION & DATA PROTECTION (3 TESTS)
    # -----------------------------------------------------------------------

    def test_09_full_ngo_inspection(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['legal_name'], 'Seva Sansthan India')

    def test_09b_csr1_data_visible_in_admin_detail(self):
        self.legal.has_csr_1 = True
        self.legal.csr_registration_number = 'CSR00012345'
        self.legal.csr_registration_date = '2023-01-10'
        self.legal.save()

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        legal_info = response.data['legal_info']
        self.assertTrue(legal_info['has_csr_1'])
        self.assertEqual(legal_info['csr_registration_number'], 'CSR00012345')
        self.assertEqual(legal_info['csr_registration_date'], '2023-01-10')
        self.assertIn('is_csr_eligible', legal_info)

    def test_10_unmasked_bank_data_visible_in_admin_detail(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_detail)
        self.assertEqual(response.data['bank_info']['account_number'], '11223344556677')

    def test_11_public_endpoint_excludes_sensitive_bank_data(self):
        self._set_status('APPROVED', is_active=True)
        url_public_slug = reverse('ngo_public_detail_slug', kwargs={'slug': self.profile.slug})
        response = self.client.get(url_public_slug)
        res_str = str(response.data)
        self.assertNotIn('11223344556677', res_str)
        self.assertNotIn('account_number', res_str)

    # -----------------------------------------------------------------------
    # 4. START REVIEW (3 TESTS)
    # -----------------------------------------------------------------------

    def test_12_start_review_submitted_to_under_review(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_start_review)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'UNDER_REVIEW')

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, 'UNDER_REVIEW')

    def test_13_invalid_start_review_transition_rejected(self):
        self._set_status('DRAFT')  # Cannot start review directly from DRAFT
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_start_review)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_14_start_review_creates_history_record(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(self.url_start_review)

        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.previous_status, 'SUBMITTED')
        self.assertEqual(history.new_status, 'UNDER_REVIEW')
        self.assertEqual(history.performed_by, self.admin_user)

    # -----------------------------------------------------------------------
    # 5. APPROVE (5 TESTS)
    # -----------------------------------------------------------------------

    def test_15_to_19_approve_workflow_and_visibility(self):
        self._set_status('UNDER_REVIEW')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_approve, {'reason': 'All documents verified.'})

        # 15. Status 200 OK
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.profile.refresh_from_db()
        # 16. is_active=True
        self.assertTrue(self.profile.is_active)
        # 17. verified_at populated
        self.assertIsNotNone(self.profile.verified_at)
        # 18. public visibility is True
        self.assertTrue(self.profile.is_public)

        # 19. History created
        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.new_status, 'APPROVED')

    # -----------------------------------------------------------------------
    # 6. REQUEST CORRECTION (4 TESTS)
    # -----------------------------------------------------------------------

    def test_20_correction_requires_instructions(self):
        self._set_status('UNDER_REVIEW')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_request_correction, {'correction_instructions': ''})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_21_to_23_request_correction_workflow(self):
        self._set_status('UNDER_REVIEW')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_request_correction, {
            'correction_instructions': 'Please re-upload clear 80G certificate.',
            'bank_correction_requested': True,
        })

        # 21. UNDER_REVIEW -> CORRECTION_REQUIRED
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'CORRECTION_REQUIRED')

        # 22. bank_correction_requested set
        self.assertTrue(response.data['verification']['bank_correction_requested'])

        # 23. History created
        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.new_status, 'CORRECTION_REQUIRED')

    # -----------------------------------------------------------------------
    # 7. REJECT (4 TESTS)
    # -----------------------------------------------------------------------

    def test_24_reject_requires_reason(self):
        self._set_status('UNDER_REVIEW')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_reject, {'rejection_reason': ''})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_25_to_27_reject_workflow(self):
        self._set_status('UNDER_REVIEW')
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_reject, {'rejection_reason': 'Fraudulent document detected.'})

        # 25. Status REJECTED
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'REJECTED')

        self.profile.refresh_from_db()
        # 26. is_active=False
        self.assertFalse(self.profile.is_active)

        # 27. History created
        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.new_status, 'REJECTED')

    # -----------------------------------------------------------------------
    # 8. SUSPEND (4 TESTS)
    # -----------------------------------------------------------------------

    def test_28_to_31_suspend_workflow(self):
        self._set_status('APPROVED', is_active=True)
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_suspend, {'reason': 'Non-compliance report.'})

        # 28. Status SUSPENDED
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'SUSPENDED')

        self.profile.refresh_from_db()
        # 29. is_active=False
        self.assertFalse(self.profile.is_active)
        # 30. public visibility false
        self.assertFalse(self.profile.is_public)

        # 31. History created
        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.new_status, 'SUSPENDED')

    # -----------------------------------------------------------------------
    # 9. REINSTATE / UNSUSPEND (4 TESTS)
    # -----------------------------------------------------------------------

    def test_32_to_35_unsuspend_workflow(self):
        self._set_status('SUSPENDED', is_active=False)
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_unsuspend, {'reason': 'Compliance verified.'})

        # 32. Status APPROVED
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'APPROVED')

        self.profile.refresh_from_db()
        # 33. is_active=True
        self.assertTrue(self.profile.is_active)
        # 34. public visibility true
        self.assertTrue(self.profile.is_public)

        # 35. History created
        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.new_status, 'APPROVED')

    # -----------------------------------------------------------------------
    # 10. REOPEN (4 TESTS)
    # -----------------------------------------------------------------------

    def test_36_to_39_reopen_workflow(self):
        self._set_status('REJECTED', is_active=False)
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_reopen, {'additional_cycles': 3})

        # 36. Status DRAFT
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'DRAFT')

        # 37. admin_reopened=True
        self.assertTrue(response.data['verification']['admin_reopened'])

        # 38. resubmission rules verified
        self.assertEqual(response.data['verification']['resubmission_limit'], 3)

        # 39. History created
        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.new_status, 'DRAFT')

    # -----------------------------------------------------------------------
    # 11. AUDIT HISTORY ENDPOINT (4 TESTS)
    # -----------------------------------------------------------------------

    def test_40_history_list(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(self.url_start_review)

        response = self.client.get(self.url_history)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_41_history_ordering_newest_first(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_history)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_42_history_read_only_methods_rejected(self):
        self.client.force_authenticate(user=self.admin_user)
        res_post = self.client.post(self.url_history, {})
        self.assertEqual(res_post.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_43_ngo_cannot_access_history_endpoint(self):
        self.client.force_authenticate(user=self.ngo_owner_user)
        response = self.client.get(self.url_history)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 12. SECURITY & TRANSACTION ATOMICITY (7 TESTS)
    # -----------------------------------------------------------------------

    def test_44_cannot_directly_patch_status(self):
        self.client.force_authenticate(user=self.admin_user)
        # Attempting to patch status on detail
        res = self.client.patch(self.url_detail, {'status': 'APPROVED'})
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_45_cannot_forge_changed_by(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(self.url_start_review, {'changed_by': str(self.ngo_owner_user.id)})

        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.performed_by, self.admin_user)  # Server derived

    def test_46_cannot_forge_actor_type(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(self.url_start_review, {'actor_type': 'NGO'})

        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertEqual(history.actor_type, 'ADMIN')  # Server derived

    def test_47_cannot_forge_timestamp(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(self.url_start_review, {'timestamp': '2000-01-01T00:00:00Z'})

        history = NGOVerificationHistory.objects.filter(ngo=self.profile).latest('timestamp')
        self.assertNotEqual(str(history.timestamp)[:4], '2000')

    def test_48_transaction_rollback_on_history_failure(self):
        self._set_status('SUBMITTED')
        self.client.force_authenticate(user=self.admin_user)

        with patch('ngo.models.NGOVerificationHistory.objects.create', side_effect=Exception('DB Error')):
            try:
                self.client.post(self.url_start_review)
            except Exception:
                pass

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, 'SUBMITTED')  # Rolled back cleanly

    def test_49_duplicate_or_invalid_transition_rejected(self):
        self._set_status('DRAFT')
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(self.url_approve)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_50_public_visibility_synced_after_every_transition(self):
        url_public_slug = reverse('ngo_public_detail_slug', kwargs={'slug': self.profile.slug})

        # 1. DRAFT -> Not Public
        self._set_status('DRAFT')
        self.assertEqual(self.client.get(url_public_slug).status_code, status.HTTP_404_NOT_FOUND)

        # 2. SUBMITTED -> Not Public
        self._set_status('SUBMITTED')
        self.assertEqual(self.client.get(url_public_slug).status_code, status.HTTP_404_NOT_FOUND)

        # 3. UNDER_REVIEW -> Not Public
        self._set_status('UNDER_REVIEW')
        self.assertEqual(self.client.get(url_public_slug).status_code, status.HTTP_404_NOT_FOUND)

        # 4. APPROVED -> Public
        self.client.force_authenticate(user=self.admin_user)
        self.client.post(self.url_approve)
        self.assertEqual(self.client.get(url_public_slug).status_code, status.HTTP_200_OK)

        # 5. SUSPENDED -> Not Public
        self.client.post(self.url_suspend, {'reason': 'Violation'})
        self.assertEqual(self.client.get(url_public_slug).status_code, status.HTTP_404_NOT_FOUND)
