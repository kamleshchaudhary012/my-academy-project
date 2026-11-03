"""
DaanGives NGO Document API Tests — Phase 3.3.2-E
=================================================
Mandatory test suite covering the 5 NGO Document endpoints:
  - GET    /api/v1/ngo/documents/
  - POST   /api/v1/ngo/documents/
  - GET    /api/v1/ngo/documents/<uuid>/
  - DELETE /api/v1/ngo/documents/<uuid>/
  - GET    /api/v1/ngo/documents/<uuid>/download/

55 Mandatory Tests Covered across Authentication, Authorization, Ownership/IDOR, Upload & File Validation,
Lifecycle Status Locking, Atomic Versioning, Secure File Download, Protected Fields, and Storage Security.
"""

import io
import os
import shutil
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from ngo.models import NGODocument, NGOProfile
from ngo.tests.helpers import make_admin_user, make_ngo_profile, make_user


class TestNGODocumentAPIs(APITestCase):

    def setUp(self):
        # Create temp media directory for test files
        self.temp_media = tempfile.mkdtemp()
        self.override_media = override_settings(MEDIA_ROOT=self.temp_media)
        self.override_media.enable()

        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')
        self.admin_user = make_admin_user()

        self.url_list_create = reverse('ngo_document_list_create')

        # Test files
        self.sample_pdf = SimpleUploadedFile(
            'trust_deed.pdf',
            b'%PDF-1.4 sample pdf content for testing',
            content_type='application/pdf',
        )
        self.sample_jpg = SimpleUploadedFile(
            'pan_card.jpg',
            b'\xff\xd8\xff\xe0\x00\x10JFIF sample jpg content',
            content_type='image/jpeg',
        )
        self.sample_png = SimpleUploadedFile(
            'logo.png',
            b'\x89PNG\r\n\x1a\n sample png content',
            content_type='image/png',
        )

    def tearDown(self):
        self.override_media.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def detail_url(self, pk):
        return reverse('ngo_document_detail', kwargs={'pk': pk})

    def download_url(self, pk):
        return reverse('ngo_document_download', kwargs={'pk': pk})

    # -----------------------------------------------------------------------
    # 1. AUTHENTICATION TESTS (401)
    # -----------------------------------------------------------------------

    def test_01_unauthenticated_list_returns_401(self):
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_02_unauthenticated_upload_returns_401(self):
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_03_unauthenticated_detail_returns_401(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        response = self.client.get(self.detail_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_04_unauthenticated_download_returns_401(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        response = self.client.get(self.download_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_05_unauthenticated_deactivate_returns_401(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        response = self.client.delete(self.detail_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -----------------------------------------------------------------------
    # 2. ROLE AUTHORIZATION TESTS (403)
    # -----------------------------------------------------------------------

    def test_06_donor_cannot_list_ngo_documents(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_07_donor_cannot_upload(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_08_admin_cannot_use_owner_document_apis(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 3. OWNERSHIP / IDOR PROTECTION
    # -----------------------------------------------------------------------

    def test_09_ngo_a_cannot_retrieve_ngo_b_document(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        doc_b = NGODocument.objects.create(ngo=ngo_b, uploaded_by=self.ngo_user_b, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust_b.pdf', file_size_bytes=100, mime_type='application/pdf')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.detail_url(doc_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_10_ngo_a_cannot_download_ngo_b_document(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        doc_b = NGODocument.objects.create(ngo=ngo_b, uploaded_by=self.ngo_user_b, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust_b.pdf', file_size_bytes=100, mime_type='application/pdf')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.download_url(doc_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_11_ngo_a_cannot_deactivate_ngo_b_document(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        doc_b = NGODocument.objects.create(ngo=ngo_b, uploaded_by=self.ngo_user_b, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust_b.pdf', file_size_bytes=100, mime_type='application/pdf')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(doc_b.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        doc_b.refresh_from_db()
        self.assertTrue(doc_b.is_active)

    def test_12_ngo_a_list_never_returns_ngo_b_documents(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        NGODocument.objects.create(ngo=ngo_b, uploaded_by=self.ngo_user_b, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust_b.pdf', file_size_bytes=100, mime_type='application/pdf')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_list_create)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    # -----------------------------------------------------------------------
    # 4. UPLOAD & FILE VALIDATION
    # -----------------------------------------------------------------------

    def test_13_valid_pdf_upload_returns_201(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['document_type'], 'TRUST_DEED')

    def test_14_valid_jpg_upload_returns_201(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_15_valid_png_upload_returns_201(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'CANCELLED_CHEQUE', 'file': self.sample_png})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_16_unsupported_extension_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        bad_file = SimpleUploadedFile('script.exe', b'binary content', content_type='application/x-msdownload')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': bad_file})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)

    def test_17_oversized_file_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        large_pan = SimpleUploadedFile('large_pan.jpg', b'x' * (3 * 1024 * 1024), content_type='image/jpeg')  # 3 MB > 2 MB cap
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': large_pan})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)

    def test_18_missing_file_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_19_invalid_document_type_returns_400(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'INVALID_TYPE', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_20_suspicious_path_traversal_filename_handled_safely(self):
        make_ngo_profile(user=self.ngo_user_a)
        traversal_file = SimpleUploadedFile('../../etc/passwd.pdf', b'%PDF-1.4 content', content_type='application/pdf')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': traversal_file})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        doc = NGODocument.objects.get(pk=response.data['id'])
        self.assertNotIn('..', doc.file.name)  # Storage path is safe UUID path

    # -----------------------------------------------------------------------
    # 5. LIFECYCLE STATUS LOCKING
    # -----------------------------------------------------------------------

    def test_21_upload_in_draft_allowed(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_22_deactivate_in_draft_allowed(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_23_upload_in_correction_required_allowed(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_24_deactivate_in_correction_required_allowed(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED')
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_25_upload_in_submitted_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUBMITTED')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_26_upload_in_under_review_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='UNDER_REVIEW')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_27_upload_in_approved_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='APPROVED', is_active=True)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_28_upload_in_rejected_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='REJECTED')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_29_upload_in_suspended_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUSPENDED')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_30_deactivate_in_submitted_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUBMITTED')
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_31_deactivate_in_approved_returns_403(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        doc = NGODocument.objects.create(ngo=ngo, uploaded_by=self.ngo_user_a, document_type='TRUST_DEED', file=self.sample_pdf, original_filename='trust.pdf', file_size_bytes=100, mime_type='application/pdf')
        NGOProfile.objects.filter(pk=ngo.pk).update(status='APPROVED', is_active=True)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.delete(self.detail_url(doc.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -----------------------------------------------------------------------
    # 6. VERSIONING
    # -----------------------------------------------------------------------

    def test_32_first_upload_creates_active_version(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_active'])
        self.assertIsNone(response.data['replaces'])

    def test_33_to_36_replacement_versioning_lifecycle(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        # Upload Version 1
        res1 = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        v1_id = res1.data['id']

        # Upload Version 2 (Replacement for PAN_CARD)
        new_jpg = SimpleUploadedFile('new_pan.jpg', b'\xff\xd8\xff\xe0\x00\x10JFIF new pan', content_type='image/jpeg')
        res2 = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': new_jpg})
        v2_id = res2.data['id']

        # Verify Version 1 is deactivated
        v1 = NGODocument.objects.get(pk=v1_id)
        self.assertFalse(v1.is_active)
        self.assertIsNotNone(v1.replaced_at)

        # Verify Version 2 is active and points to Version 1
        v2 = NGODocument.objects.get(pk=v2_id)
        self.assertTrue(v2.is_active)
        self.assertEqual(v2.replaces, v1)

        # Verify old file record remains in DB
        self.assertEqual(NGODocument.objects.filter(ngo=ngo, document_type='PAN_CARD').count(), 2)

    def test_37_failed_replacement_rolls_back_transaction(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        # Upload Version 1
        res1 = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        v1_id = res1.data['id']

        # Mock exception during save
        with patch('ngo.serializers.NGODocumentSerializer.save', side_effect=Exception('DB Failure')):
            try:
                self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
            except Exception:
                pass

        # Version 1 must still remain active
        v1 = NGODocument.objects.get(pk=v1_id)
        self.assertTrue(v1.is_active)

    def test_38_only_one_active_version_exists_for_document_type(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)

        self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})

        active_count = NGODocument.objects.filter(ngo=ngo, document_type='PAN_CARD', is_active=True).count()
        self.assertEqual(active_count, 1)

    # -----------------------------------------------------------------------
    # 7. DOWNLOAD SECURITY
    # -----------------------------------------------------------------------

    def test_39_owner_can_download_own_active_document(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc_id = upload_res.data['id']

        response = self.client.get(self.download_url(doc_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_40_owner_cannot_download_inactive_document(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc_id = upload_res.data['id']

        # Deactivate
        self.client.delete(self.detail_url(doc_id))

        # Download inactive -> 404
        response = self.client.get(self.download_url(doc_id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_41_wrong_ngo_receives_404_on_download(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc_id = upload_res.data['id']

        make_ngo_profile(user=self.ngo_user_b)
        self.client.force_authenticate(user=self.ngo_user_b)
        response = self.client.get(self.download_url(doc_id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_42_download_does_not_expose_filesystem_path(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc_id = upload_res.data['id']

        response = self.client.get(self.download_url(doc_id))
        self.assertNotIn(self.temp_media, str(response.headers))

    def test_43_correct_content_type_returned(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'PAN_CARD', 'file': self.sample_jpg})
        doc_id = upload_res.data['id']

        response = self.client.get(self.download_url(doc_id))
        self.assertEqual(response['Content-Type'], 'image/jpeg')

    def test_44_full_private_media_url_is_not_exposed(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Verify raw direct media URL is not exposed
        self.assertNotIn('/media/ngo_docs/', str(response.data))

    # -----------------------------------------------------------------------
    # 8. PROTECTED FIELDS
    # -----------------------------------------------------------------------

    def test_45_to_50_client_cannot_modify_protected_fields(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {
            'document_type': 'TRUST_DEED',
            'file': self.sample_pdf,
            'ngo': str(make_ngo_profile(user=self.ngo_user_b).id),
            'uploaded_by': str(self.admin_user.id),
            'is_verified': True,
            'is_active': False,
        })
        self.assertEqual(upload_res.status_code, status.HTTP_201_CREATED)
        doc = NGODocument.objects.get(pk=upload_res.data['id'])
        self.assertEqual(doc.ngo, ngo)
        self.assertEqual(doc.uploaded_by, self.ngo_user_a)
        self.assertTrue(doc.is_active)
        self.assertFalse(doc.is_verified)

    # -----------------------------------------------------------------------
    # 9. STORAGE & PUBLIC ACCESS SECURITY
    # -----------------------------------------------------------------------

    def test_51_to_53_storage_path_safety(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc = NGODocument.objects.get(pk=upload_res.data['id'])
        self.assertIn(str(ngo.id), doc.file.name)
        self.assertIn('TRUST_DEED', doc.file.name)

    def test_54_public_anonymous_request_cannot_download_private_document(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc_id = upload_res.data['id']

        self.client.logout()
        response = self.client.get(self.download_url(doc_id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_55_donor_cannot_download_private_document(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        upload_res = self.client.post(self.url_list_create, {'document_type': 'TRUST_DEED', 'file': self.sample_pdf})
        doc_id = upload_res.data['id']

        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.download_url(doc_id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
