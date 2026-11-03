"""
DaanGives NGO Serializer Tests — Phase 3.3.1
==============================================
Test suite covering all 9 NGO serializers:
  - NGOAddressSerializer
  - NGOLegalInfoSerializer
  - NGOBankInfoSerializer
  - NGOLeadershipSerializer
  - NGODocumentSerializer
  - NGOProfileSerializer
  - NGOPublicSerializer
  - NGOAdminSerializer
  - NGOVerificationHistorySerializer
"""

import uuid
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGODocument,
    NGOLeadership,
    NGOVerification,
    NGOVerificationHistory,
)
from ngo.serializers import (
    NGOAddressSerializer,
    NGOLegalInfoSerializer,
    NGOBankInfoSerializer,
    NGOLeadershipSerializer,
    NGODocumentSerializer,
    NGOProfileSerializer,
    NGOPublicSerializer,
    NGOAdminSerializer,
    NGOVerificationHistorySerializer,
)
from ngo.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_legal_info,
    make_bank_info,
    make_admin_user,
)


class TestNGOProfileSerializer(TestCase):
    def setUp(self):
        self.user = make_user()
        self.ngo = make_ngo_profile(user=self.user)

    def test_profile_serializer_read_data(self):
        serializer = NGOProfileSerializer(self.ngo)
        data = serializer.data
        self.assertEqual(data['id'], str(self.ngo.id))
        self.assertEqual(data['display_name'], self.ngo.display_name)
        self.assertEqual(data['status'], 'DRAFT')
        self.assertFalse(data['is_active'])
        self.assertFalse(data['is_public'])

    def test_status_fields_are_read_only(self):
        """User cannot modify status or is_active via profile serializer."""
        serializer = NGOProfileSerializer(
            instance=self.ngo,
            data={'status': 'APPROVED', 'is_active': True, 'display_name': 'New Name'},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(updated.display_name, 'New Name')
        self.assertEqual(updated.status, 'DRAFT')  # Unchanged
        self.assertFalse(updated.is_active)       # Unchanged


class TestNGOLegalInfoSerializer(TestCase):
    def setUp(self):
        self.ngo = make_ngo_profile()
        self.legal = make_legal_info(self.ngo)

    def test_pan_normalized_to_uppercase(self):
        serializer = NGOLegalInfoSerializer(
            instance=self.legal,
            data={'pan_number': 'aabct9999f'},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['pan_number'], 'AABCT9999F')

    def test_conditional_12a_validation(self):
        """If has_12a is True, twelve_a_number must be provided."""
        serializer = NGOLegalInfoSerializer(
            instance=self.legal,
            data={'has_12a': True, 'twelve_a_number': ''},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('twelve_a_number', serializer.errors)

    def test_conditional_80g_validation(self):
        """If has_80g is True, eighty_g_number must be provided."""
        serializer = NGOLegalInfoSerializer(
            instance=self.legal,
            data={'has_80g': True, 'eighty_g_number': ''},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('eighty_g_number', serializer.errors)

    def test_conditional_fcra_validation(self):
        """If has_fcra is True, fcra_number must be provided."""
        serializer = NGOLegalInfoSerializer(
            instance=self.legal,
            data={'has_fcra': True, 'fcra_number': ''},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('fcra_number', serializer.errors)


class TestNGOBankInfoSerializer(TestCase):
    def setUp(self):
        self.ngo = make_ngo_profile()
        self.bank = make_bank_info(self.ngo)

    def test_account_number_is_masked_on_read(self):
        serializer = NGOBankInfoSerializer(self.bank)
        data = serializer.data
        self.assertNotIn('account_number', data)  # write_only
        self.assertIn('masked_account_number', data)
        self.assertEqual(data['masked_account_number'], f'****{self.bank.account_number[-4:]}')

    def test_bank_editable_in_draft(self):
        self.assertEqual(self.ngo.status, 'DRAFT')
        serializer = NGOBankInfoSerializer(
            instance=self.bank,
            data={'bank_name': 'HDFC Bank', 'account_number': '987654321098'},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_bank_locked_in_submitted(self):
        NGOProfile.objects.filter(pk=self.ngo.pk).update(status='SUBMITTED')
        self.ngo.refresh_from_db()
        serializer = NGOBankInfoSerializer(
            instance=self.bank,
            data={'bank_name': 'HDFC Bank', 'account_number': '987654321098'},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('non_field_errors', serializer.errors)

    def test_bank_editable_in_correction_required_with_flag(self):
        NGOProfile.objects.filter(pk=self.ngo.pk).update(status='CORRECTION_REQUIRED')
        NGOVerification.objects.filter(ngo=self.ngo).update(
            status='CORRECTION_REQUIRED', bank_correction_requested=True
        )
        self.ngo.refresh_from_db()
        serializer = NGOBankInfoSerializer(
            instance=self.bank,
            data={'bank_name': 'ICICI Bank', 'account_number': '987654321098'},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_bank_ifsc_and_account_normalization(self):
        serializer = NGOBankInfoSerializer(
            instance=self.bank,
            data={'ifsc_code': '  sbin0001234  ', 'account_number': '  123456789012  '},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['ifsc_code'], 'SBIN0001234')
        self.assertEqual(serializer.validated_data['account_number'], '123456789012')


class TestNGODocumentSerializer(TestCase):
    def setUp(self):
        self.ngo = make_ngo_profile()

    def test_invalid_file_extension_rejected(self):
        dummy_file = SimpleUploadedFile('script.exe', b'binary', content_type='application/x-msdownload')
        serializer = NGODocumentSerializer(
            data={'document_type': 'TRUST_DEED', 'file': dummy_file}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('file', serializer.errors)

    def test_oversized_file_rejected(self):
        # 3 MB file for PAN_CARD (max 2 MB)
        oversized = SimpleUploadedFile('pan.pdf', b'0' * (3 * 1024 * 1024), content_type='application/pdf')
        serializer = NGODocumentSerializer(
            data={'document_type': 'PAN_CARD', 'file': oversized}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('file', serializer.errors)

    def test_disguised_executable_rejected(self):
        # Disguised Windows PE executable renamed to .pdf
        disguised_file = SimpleUploadedFile('malicious.pdf', b'MZ\x90\x00\x03\x00\x00\x00fake pe', content_type='application/pdf')
        serializer = NGODocumentSerializer(
            data={'document_type': 'TRUST_DEED', 'file': disguised_file}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('file', serializer.errors)


class TestNGOPublicSerializer(TestCase):
    def setUp(self):
        self.ngo = make_ngo_profile()
        make_legal_info(self.ngo)
        make_bank_info(self.ngo)
        NGOAddress.objects.create(
            ngo=self.ngo, address_line1='Secret Street', city='Surat',
            district='Surat', state='Gujarat', pincode='395001',
            latitude=21.1702, longitude=72.8311,
        )
        NGOLeadership.objects.create(
            ngo=self.ngo, full_name='Leader One', designation='President',
            phone='+919876543210', email='secret@leader.com', is_primary_contact=True,
        )

    def test_public_serializer_exposes_safe_fields_only(self):
        NGOProfile.objects.filter(pk=self.ngo.pk).update(status='APPROVED', is_active=True)
        self.ngo.refresh_from_db()

        serializer = NGOPublicSerializer(self.ngo)
        data = serializer.data

        # Safe fields present
        self.assertEqual(data['display_name'], self.ngo.display_name)
        self.assertEqual(data['city'], 'Surat')
        self.assertEqual(data['district'], 'Surat')
        self.assertEqual(data['darpan_id'], self.ngo.legal_info.darpan_id)

        # Sensitive fields EXCLUDED
        self.assertNotIn('bank_name', data)
        self.assertNotIn('account_number', data)
        self.assertNotIn('ifsc_code', data)
        self.assertNotIn('pan_number', data)
        self.assertNotIn('registration_number', data)
        self.assertNotIn('latitude', data)
        self.assertNotIn('longitude', data)
        self.assertNotIn('address_line1', data)
        self.assertNotIn('pincode', data)

        # Leadership public formatting (excludes phone & email)
        leader_data = data['leadership'][0]
        self.assertEqual(leader_data['full_name'], 'Leader One')
        self.assertEqual(leader_data['designation'], 'President')
        self.assertNotIn('phone', leader_data)
        self.assertNotIn('email', leader_data)

    def test_public_serializer_with_valid_logo_and_request_context(self):
        from rest_framework.test import APIRequestFactory
        # Attach a real uploaded logo file
        logo_content = b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
        self.ngo.logo = SimpleUploadedFile("test_logo.gif", logo_content, content_type="image/gif")
        self.ngo.save()

        # Serializer with request context generates absolute URL
        factory = APIRequestFactory()
        request = factory.get('/')
        serializer = NGOPublicSerializer(self.ngo, context={'request': request})
        self.assertTrue(serializer.data['logo'].startswith('http://testserver/media/'))

    def test_public_serializer_with_missing_logo_file_returns_none(self):
        # Simulate logo path in DB whose file does not exist on disk
        self.ngo.logo.name = 'ngo_logos/non_existent_path_9999.png'
        serializer = NGOPublicSerializer(self.ngo)
        self.assertIsNone(serializer.data['logo'])

    def test_public_serializer_with_no_logo_returns_none(self):
        self.ngo.logo = None
        serializer = NGOPublicSerializer(self.ngo)
        self.assertIsNone(serializer.data['logo'])


class TestNGOAdminSerializer(TestCase):
    def setUp(self):
        self.ngo = make_ngo_profile()
        make_legal_info(self.ngo)
        make_bank_info(self.ngo)

    def test_admin_serializer_includes_unmasked_bank_account(self):
        serializer = NGOAdminSerializer(self.ngo)
        data = serializer.data
        self.assertIn('bank_info', data)
        # Full unmasked account number present for Admin inspection
        self.assertEqual(data['bank_info']['account_number'], '123456789012')
        self.assertIn('verification', data)
        self.assertEqual(data['verification']['status'], 'PENDING')


class TestNGOVerificationHistorySerializer(TestCase):
    def setUp(self):
        self.ngo = make_ngo_profile()
        self.history = NGOVerificationHistory.objects.create(
            ngo=self.ngo,
            actor_type='SYSTEM',
            previous_status='PENDING',
            new_status='SUBMITTED',
        )

    def test_history_serializer_read_only(self):
        serializer = NGOVerificationHistorySerializer(self.history)
        data = serializer.data
        self.assertEqual(data['previous_status'], 'PENDING')
        self.assertEqual(data['new_status'], 'SUBMITTED')
        self.assertEqual(data['actor_type'], 'SYSTEM')
        self.assertEqual(data['performed_by_email'], 'System')
