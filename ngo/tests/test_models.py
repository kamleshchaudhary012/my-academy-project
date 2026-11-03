"""
DaanGives NGO Model Tests — Models, Relationships & Validators
==============================================================
Test modules:
  - TestModelCreation (8 tests)
  - TestRelationships (8 tests)
  - TestValidators (10 tests)
Total: 26 tests
"""

import uuid
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGODocument,
    NGOLeadership,
    NGOVerification,
    NGOVerificationHistory,
    validate_pan_number,
    validate_darpan_id,
    validate_ifsc_code,
    validate_account_number,
    validate_pincode,
    validate_year_range,
)
from ngo.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_legal_info,
    make_bank_info,
)


class TestModelCreation(TestCase):
    """A. Verify all 8 models can be created with valid data."""

    def setUp(self):
        self.user = make_user(role='NGO')
        self.ngo = make_ngo_profile(user=self.user)

    def test_a1_ngoprofile_creation(self):
        """Valid NGOProfile is created correctly."""
        self.assertIsNotNone(self.ngo.pk)
        self.assertIsInstance(self.ngo.pk, uuid.UUID)
        self.assertEqual(self.ngo.status, NGOProfile.Status.DRAFT)
        self.assertFalse(self.ngo.is_active)
        self.assertFalse(self.ngo.is_public)
        self.assertIsNotNone(self.ngo.slug)

    def test_a2_ngoaddress_creation(self):
        """Valid NGOAddress is created correctly."""
        address = NGOAddress.objects.create(
            ngo=self.ngo,
            address_line1='123 Main Street',
            city='Ahmedabad',
            district='Ahmedabad',
            state='Gujarat',
            pincode='380001',
        )
        self.assertEqual(address.ngo, self.ngo)
        self.assertEqual(address.city, 'Ahmedabad')

    def test_a3_ngolegalinfo_creation(self):
        """Valid NGOLegalInfo is created correctly."""
        legal = make_legal_info(self.ngo)
        self.assertEqual(legal.ngo, self.ngo)
        self.assertEqual(legal.pan_number, 'AABCT1234D')

    def test_a4_ngobankinfo_creation(self):
        """Valid NGOBankInfo is created correctly."""
        bank = make_bank_info(self.ngo)
        self.assertEqual(bank.ngo, self.ngo)
        self.assertEqual(bank.bank_name, 'State Bank of India')

    def test_a5_ngodocument_creation(self):
        """Valid NGODocument record can be created (without actual file)."""
        doc = NGODocument.objects.create(
            ngo=self.ngo,
            uploaded_by=self.user,
            document_type=NGODocument.DocumentType.TRUST_DEED,
            file='ngo_docs/test/TRUST_DEED/fake.pdf',
            original_filename='trust_deed.pdf',
            file_size_bytes=1024,
            mime_type='application/pdf',
        )
        self.assertEqual(doc.ngo, self.ngo)
        self.assertTrue(doc.is_active)
        self.assertFalse(doc.is_verified)

    def test_a6_ngoleadership_creation(self):
        """Valid NGOLeadership record can be created."""
        leader = NGOLeadership.objects.create(
            ngo=self.ngo,
            full_name='Jane Doe',
            designation='President',
            is_primary_contact=True,
        )
        self.assertEqual(leader.ngo, self.ngo)
        self.assertTrue(leader.is_active)

    def test_a7_ngoverification_creation(self):
        """NGOVerification is created (setUp creates it)."""
        v = self.ngo.verification
        self.assertEqual(v.status, NGOVerification.Status.PENDING)
        self.assertEqual(v.resubmission_count, 0)
        self.assertEqual(v.resubmission_limit, 3)
        self.assertFalse(v.bank_correction_requested)

    def test_a8_ngoverificationhistory_creation(self):
        """NGOVerificationHistory can be created via objects.create()."""
        history = NGOVerificationHistory.objects.create(
            ngo=self.ngo,
            performed_by=self.user,
            actor_type=NGOVerificationHistory.ActorType.NGO,
            previous_status='PENDING',
            new_status='SUBMITTED',
            reason='Initial submission',
        )
        self.assertIsNotNone(history.pk)
        self.assertEqual(history.previous_status, 'PENDING')
        self.assertEqual(history.new_status, 'SUBMITTED')


class TestRelationships(TestCase):
    """D. Verify all OneToOne and FK relationships."""

    def setUp(self):
        self.ngo = make_ngo_profile()

    def test_d1_ngo_has_address(self):
        """NGOProfile → NGOAddress OneToOne works."""
        address = NGOAddress.objects.create(
            ngo=self.ngo, address_line1='Street', city='Ahmedabad',
            district='Ahmedabad', state='Gujarat', pincode='380001',
        )
        self.assertEqual(self.ngo.address, address)

    def test_d2_ngo_has_legal_info(self):
        """NGOProfile → NGOLegalInfo OneToOne works."""
        legal = make_legal_info(self.ngo)
        self.assertEqual(self.ngo.legal_info, legal)

    def test_d3_ngo_has_bank_info(self):
        """NGOProfile → NGOBankInfo OneToOne works."""
        bank = make_bank_info(self.ngo)
        self.assertEqual(self.ngo.bank_info, bank)

    def test_d4_ngo_has_verification(self):
        """NGOProfile → NGOVerification OneToOne works (created in setUp)."""
        self.assertIsNotNone(self.ngo.verification)

    def test_d5_ngo_has_multiple_documents(self):
        """NGOProfile can have many NGODocument records."""
        user = self.ngo.user
        doc1 = NGODocument.objects.create(
            ngo=self.ngo, uploaded_by=user,
            document_type=NGODocument.DocumentType.TRUST_DEED,
            file='fake/path/1.pdf', original_filename='1.pdf',
            file_size_bytes=100, mime_type='application/pdf',
        )
        doc2 = NGODocument.objects.create(
            ngo=self.ngo, uploaded_by=user,
            document_type=NGODocument.DocumentType.PAN_CARD,
            file='fake/path/2.pdf', original_filename='2.pdf',
            file_size_bytes=200, mime_type='application/pdf',
        )
        self.assertEqual(self.ngo.documents.count(), 2)

    def test_d6_ngo_has_multiple_leaders(self):
        """NGOProfile can have many NGOLeadership records."""
        NGOLeadership.objects.create(
            ngo=self.ngo, full_name='Leader A', designation='President',
            is_primary_contact=True,
        )
        NGOLeadership.objects.create(
            ngo=self.ngo, full_name='Leader B', designation='Secretary',
        )
        self.assertEqual(self.ngo.leadership.count(), 2)

    def test_d7_ngo_has_multiple_history_records(self):
        """NGOProfile can have many NGOVerificationHistory records."""
        NGOVerificationHistory.objects.create(
            ngo=self.ngo, actor_type='SYSTEM',
            previous_status='PENDING', new_status='SUBMITTED',
        )
        NGOVerificationHistory.objects.create(
            ngo=self.ngo, actor_type='ADMIN',
            previous_status='SUBMITTED', new_status='UNDER_REVIEW',
        )
        self.assertEqual(self.ngo.history.count(), 2)

    def test_d8_cascade_delete_removes_related(self):
        """Deleting NGOProfile cascades to all related records."""
        make_legal_info(self.ngo)
        make_bank_info(self.ngo)
        ngo_id = self.ngo.pk
        self.ngo.delete()
        self.assertEqual(NGOLegalInfo.objects.filter(ngo_id=ngo_id).count(), 0)
        self.assertEqual(NGOBankInfo.objects.filter(ngo_id=ngo_id).count(), 0)
        self.assertEqual(NGOVerification.objects.filter(ngo_id=ngo_id).count(), 0)


class TestValidators(TestCase):
    """K. Verify field validators work correctly."""

    def test_k1_pan_invalid_format_rejected(self):
        """Invalid PAN format raises ValidationError."""
        with self.assertRaises(ValidationError):
            validate_pan_number('INVALID123')
        with self.assertRaises(ValidationError):
            validate_pan_number('aabct1234d')  # lowercase
        with self.assertRaises(ValidationError):
            validate_pan_number('12345ABCDE')  # wrong pattern

    def test_k2_valid_pan_accepted(self):
        validate_pan_number('AABCT1234D')  # Must not raise

    def test_k3_darpan_invalid_chars_rejected(self):
        with self.assertRaises(ValidationError):
            validate_darpan_id('GJ@2010#TEST')  # invalid chars

    def test_k4_darpan_valid_accepted(self):
        validate_darpan_id('GJ/2010/ABCDE')  # Must not raise
        validate_darpan_id('MH-2015-XYZ')  # Must not raise

    def test_k5_ifsc_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            validate_ifsc_code('INVALID')
        with self.assertRaises(ValidationError):
            validate_ifsc_code('SBIN1001234')  # 5th char must be '0'

    def test_k6_ifsc_valid_accepted(self):
        validate_ifsc_code('SBIN0001234')  # Must not raise

    def test_k7_account_number_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            validate_account_number('12345')  # too short
        with self.assertRaises(ValidationError):
            validate_account_number('ABCDE12345')  # letters not allowed

    def test_k8_pincode_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            validate_pincode('38001')   # 5 digits
        with self.assertRaises(ValidationError):
            validate_pincode('ABCDEF')  # not digits

    def test_k9_year_out_of_range_rejected(self):
        with self.assertRaises(ValidationError):
            validate_year_range(1799)
        with self.assertRaises(ValidationError):
            validate_year_range(timezone.now().year + 1)

    def test_k10_legal_info_clean_validates_cert_numbers(self):
        """NGOLegalInfo.clean() enforces certificate numbers when has_XXX=True."""
        ngo = make_ngo_profile()
        legal = NGOLegalInfo(
            ngo=ngo,
            organisation_type='TRUST',
            registering_authority='Test Authority',
            registration_number='TEST/001',
            darpan_id='GJ/2010/CLEAN01',
            pan_number='AABCT1234D',
            registration_state='Gujarat',
            chief_trustee_name='Test',
            chief_trustee_designation='Trustee',
            has_12a=True,
            twelve_a_number='',  # missing — should fail
        )
        with self.assertRaises(ValidationError) as ctx:
            legal.clean()
        self.assertIn('twelve_a_number', ctx.exception.message_dict)
