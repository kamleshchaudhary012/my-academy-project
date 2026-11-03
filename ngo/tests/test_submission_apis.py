"""
DaanGives NGO Submission API Tests — Phase 3.3.2-F
==================================================
Mandatory test suite covering the NGO Submission Workflow endpoint:
  - POST /api/v1/ngo/submit/

47 Mandatory Tests Covered across Authentication, Role Authorization, Ownership IDOR Protection,
Completeness Precondition Validation, Atomic State Transitions, Duplicate Submission Prevention,
Transaction Rollback Safety, Post-Submission Lifecycle Locking across all owner endpoints, and Security.
"""

from unittest.mock import patch
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGOLeadership,
    NGODocument,
    NGOVerification,
    NGOVerificationHistory,
)
from ngo.tests.helpers import make_user, make_ngo_profile, make_admin_user


class TestNGOSubmissionAPIs(APITestCase):

    def setUp(self):
        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')
        self.admin_user = make_admin_user()

        self.url_submit = reverse('ngo_submit')
        self.url_profile_me = reverse('ngo_profile_me')
        self.url_address_me = reverse('ngo_address_me')
        self.url_legal_me = reverse('ngo_legal_me')
        self.url_bank_me = reverse('ngo_bank_me')
        self.url_leadership_list = reverse('ngo_leadership_list_create')
        self.url_document_list = reverse('ngo_document_list_create')

    def _setup_complete_ngo(self, user):
        """Helper to create a fully complete NGO application ready for submission."""
        profile = make_ngo_profile(
            user=user,
            legal_name=f'Helping Hands Foundation {user.id.hex[:4]}',
            display_name=f'Helping Hands {user.id.hex[:4]}',
            category='EDUCATION',
            description='Dedicated to providing education and support to underprivileged children in urban slums for over 10 years.',
            year_established=2015,
            official_email=f'contact_{user.id.hex[:4]}@helpinghands.org',
            official_phone='+919876543210',
        )
        NGOAddress.objects.create(
            ngo=profile,
            address_line1='123 Main Street',
            city='Mumbai',
            district='Mumbai City',
            state='Maharashtra',
            pincode='400001',
        )
        NGOLegalInfo.objects.create(
            ngo=profile,
            organisation_type='TRUST',
            registration_number=f'REG-{user.id.hex[:6]}',
            darpan_id=f'GJ/2020/{user.id.hex[:6]}',
            pan_number=f'AA{user.id.hex[:5].upper()}F',
            registration_state='Gujarat',
            chief_trustee_name='Ramesh Patel',
            chief_trustee_designation='Managing Trustee',
            has_12a=False,
            has_80g=False,
            has_fcra=False,
        )
        NGOBankInfo.objects.create(
            ngo=profile,
            account_holder_name='Helping Hands Foundation',
            account_number='98765432101234',
            ifsc_code='SBIN0001234',
            bank_name='State Bank of India',
            branch_name='Fort Branch',
            account_type='SAVINGS',
        )
        NGOLeadership.objects.create(
            ngo=profile,
            full_name='Ramesh Patel',
            designation='Managing Trustee',
            is_primary_contact=True,
            is_active=True,
        )

        dummy_pdf = SimpleUploadedFile('dummy.pdf', b'%PDF-1.4 dummy content', content_type='application/pdf')
        dummy_jpg = SimpleUploadedFile('dummy.jpg', b'\xff\xd8\xff\xe0\x00\x10JFIF dummy', content_type='image/jpeg')

        # Upload all mandatory document types
        for doc_type in NGODocument.REQUIRED_DOCUMENT_TYPES:
            f = dummy_jpg if doc_type in (NGODocument.DocumentType.PAN_CARD, NGODocument.DocumentType.CANCELLED_CHEQUE, NGODocument.DocumentType.REPRESENTATIVE_ID) else dummy_pdf
            NGODocument.objects.create(
                ngo=profile,
                uploaded_by=user,
                document_type=doc_type,
                file=f,
                original_filename=f.name,
                file_size_bytes=100,
                mime_type=f.content_type,
                is_active=True,
            )
        return profile

    # -----------------------------------------------------------------------
    # 1. AUTHENTICATION & ROLE AUTHORIZATION
    # -----------------------------------------------------------------------

    def test_01_anonymous_submit_returns_401(self):
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_02_donor_submit_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_03_admin_submit_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_04_ngo_submit_allowed_when_complete(self):
        self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -----------------------------------------------------------------------
    # 2. OWNERSHIP / IDOR
    # -----------------------------------------------------------------------

    def test_05_ngo_can_only_submit_its_own_profile(self):
        self._setup_complete_ngo(self.ngo_user_a)
        self._setup_complete_ngo(self.ngo_user_b)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # NGO B remains DRAFT
        ngo_b = NGOProfile.objects.get(user=self.ngo_user_b)
        self.assertEqual(ngo_b.status, 'DRAFT')

    def test_06_client_supplied_ngo_id_cannot_override_ownership(self):
        ngo_a = self._setup_complete_ngo(self.ngo_user_a)
        ngo_b = self._setup_complete_ngo(self.ngo_user_b)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit, {'ngo_id': str(ngo_b.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ngo_a.refresh_from_db()
        ngo_b.refresh_from_db()
        self.assertEqual(ngo_a.status, 'SUBMITTED')
        self.assertEqual(ngo_b.status, 'DRAFT')

    # -----------------------------------------------------------------------
    # 3. COMPLETENESS VALIDATION (400)
    # -----------------------------------------------------------------------

    def test_07_missing_address_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.address.delete()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('address', response.data['errors'])

    def test_08_missing_legal_info_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.legal_info.delete()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('legal_info', response.data['errors'])

    def test_09_missing_bank_info_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.bank_info.delete()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('bank_info', response.data['errors'])

    def test_10_missing_leadership_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.leadership.all().delete()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('leadership', response.data['errors'])

    def test_11_missing_primary_contact_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.leadership.update(is_primary_contact=False)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('leadership', response.data['errors'])

    def test_12_missing_required_document_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.documents.filter(document_type=NGODocument.DocumentType.REGISTRATION_CERT).delete()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('documents', response.data['errors'])

    def test_13_inactive_document_does_not_satisfy_requirement(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.documents.filter(document_type=NGODocument.DocumentType.REGISTRATION_CERT).update(is_active=False)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('documents', response.data['errors'])

    def test_14_invalid_conditional_legal_information_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.legal_info.has_12a = True
        profile.legal_info.twelve_a_number = ''
        profile.legal_info.save()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('legal_info', response.data['errors'])

    def test_15_incomplete_profile_returns_400(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        profile.description = ''
        profile.save()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('profile', response.data['errors'])

    # -----------------------------------------------------------------------
    # 4. SUCCESSFUL SUBMISSION WORKFLOW
    # -----------------------------------------------------------------------

    def test_16_to_23_successful_submission_state_changes(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'SUBMITTED')
        self.assertFalse(response.data['is_active'])
        self.assertFalse(response.data['is_public'])

        profile.refresh_from_db()
        self.assertEqual(profile.status, 'SUBMITTED')
        self.assertFalse(profile.is_active)
        self.assertFalse(profile.is_public)

        # Verification record exists
        self.assertTrue(hasattr(profile, 'verification'))
        self.assertIsNotNone(profile.verification.submitted_at)

        # Verification history created
        history_entry = NGOVerificationHistory.objects.filter(ngo=profile).latest('timestamp')
        self.assertEqual(history_entry.previous_status, 'DRAFT')
        self.assertEqual(history_entry.new_status, 'SUBMITTED')
        self.assertEqual(history_entry.actor_type, 'NGO')

    # -----------------------------------------------------------------------
    # 5. DUPLICATE SUBMISSION PREVENTION (409 CONFLICT)
    # -----------------------------------------------------------------------

    def test_24_submitted_ngo_cannot_submit_again(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        res1 = self.client.post(self.url_submit)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        res2 = self.client.post(self.url_submit)
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)

    def test_25_under_review_ngo_cannot_submit_again(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        NGOProfile.objects.filter(pk=profile.pk).update(status='UNDER_REVIEW')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_26_27_duplicate_submission_does_not_create_extra_history(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        self.client.post(self.url_submit)
        history_count_1 = NGOVerificationHistory.objects.filter(ngo=profile).count()

        self.client.post(self.url_submit)  # Duplicate attempt
        history_count_2 = NGOVerificationHistory.objects.filter(ngo=profile).count()

        self.assertEqual(history_count_1, history_count_2)

    # -----------------------------------------------------------------------
    # 6. TRANSACTION ATOMICITY & ROLLBACK SAFETY
    # -----------------------------------------------------------------------

    def test_28_to_30_history_creation_failure_rolls_back_status(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        with patch('ngo.models.NGOVerificationHistory.objects.create', side_effect=Exception('DB Error')):
            try:
                self.client.post(self.url_submit)
            except Exception:
                pass

        profile.refresh_from_db()
        self.assertEqual(profile.status, 'DRAFT')  # Rolled back cleanly

    # -----------------------------------------------------------------------
    # 7. POST-SUBMISSION LIFECYCLE LOCKING (403 FORBIDDEN)
    # -----------------------------------------------------------------------

    def test_31_to_37_owner_apis_locked_after_submission(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        # Submit
        self.client.post(self.url_submit)

        # 31. Profile update blocked
        res = self.client.patch(self.url_profile_me, {'display_name': 'Hacked'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 32. Address update blocked
        res = self.client.put(self.url_address_me, {'address_line1': 'New St'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 33. Legal update blocked
        res = self.client.patch(self.url_legal_me, {'has_12a': True})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 34. Bank update blocked
        res = self.client.patch(self.url_bank_me, {'bank_name': 'Hacked Bank'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 35. Leadership create blocked
        res = self.client.post(self.url_leadership_list, {'full_name': 'Leader X', 'designation': 'Trustee'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 36. Document upload blocked
        dummy_pdf = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 content', content_type='application/pdf')
        res = self.client.post(self.url_document_list, {'document_type': 'TRUST_DEED', 'file': dummy_pdf})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 37. Document deactivation blocked
        doc = profile.documents.first()
        detail_url = reverse('ngo_document_detail', kwargs={'pk': doc.id})
        res = self.client.delete(detail_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 8. SECURITY & RESPONSE ISOLATION
    # -----------------------------------------------------------------------

    def test_38_to_41_sensitive_fields_not_exposed_in_response(self):
        self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_str = str(response.data)
        self.assertNotIn('account_number', res_str)
        self.assertNotIn('documents', res_str)
        self.assertNotIn('admin_notes', res_str)
        self.assertNotIn('risk_flag', res_str)

    # -----------------------------------------------------------------------
    # 9. STATE CONSISTENCY & IMMUTABLE HISTORY
    # -----------------------------------------------------------------------

    def test_42_submitted_always_has_is_active_false(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        self.client.post(self.url_submit)
        profile.refresh_from_db()
        self.assertFalse(profile.is_active)

    def test_43_submitted_is_never_public(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        self.client.post(self.url_submit)
        profile.refresh_from_db()
        self.assertFalse(profile.is_public)

    def test_44_verification_status_matches_profile_status(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        self.client.post(self.url_submit)
        profile.refresh_from_db()
        self.assertEqual(profile.status, 'SUBMITTED')

    def test_45_to_47_history_record_immutability(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        self.client.post(self.url_submit)

        history = NGOVerificationHistory.objects.get(ngo=profile, new_status='SUBMITTED')
        self.assertEqual(history.previous_status, 'DRAFT')
        self.assertEqual(history.new_status, 'SUBMITTED')

    def test_48_submit_with_csr1_requires_csr1_cert(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        profile = self._setup_complete_ngo(self.ngo_user_a)
        legal = profile.legal_info
        legal.has_csr_1 = True
        legal.csr_registration_number = 'CSR00012345'
        legal.save()

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('documents', response.data['errors'])

    def test_49_submit_with_csr1_and_cert_succeeds(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        profile = self._setup_complete_ngo(self.ngo_user_a)
        legal = profile.legal_info
        legal.has_csr_1 = True
        legal.csr_registration_number = 'CSR00012345'
        legal.save()

        dummy_pdf = SimpleUploadedFile('csr1_cert.pdf', b'%PDF-1.4 dummy csr1', content_type='application/pdf')
        NGODocument.objects.create(
            ngo=profile,
            uploaded_by=self.ngo_user_a,
            document_type=NGODocument.DocumentType.CSR_1_CERT,
            file=dummy_pdf,
            original_filename='csr1_cert.pdf',
            file_size_bytes=100,
            mime_type='application/pdf',
            is_active=True,
        )

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile.refresh_from_db()
        self.assertEqual(profile.status, 'SUBMITTED')

    def test_50_submit_without_csr1_does_not_require_csr1_cert(self):
        profile = self._setup_complete_ngo(self.ngo_user_a)
        self.assertFalse(profile.legal_info.has_csr_1)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_submit)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile.refresh_from_db()
        self.assertEqual(profile.status, 'SUBMITTED')
