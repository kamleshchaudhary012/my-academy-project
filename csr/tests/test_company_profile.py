"""
Unit Tests for CompanyProfile Model
===================================
Tests CompanyProfile CRUD, validations, relationships, file handling, and constraints.
"""

import shutil
import tempfile
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    company_verification_doc_path,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    generate_valid_cin,
    generate_valid_pan,
    make_dummy_uploaded_file,
)

User = get_user_model()


class CompanyProfileModelTests(TestCase):
    """Test suite for CompanyProfile model behavior and validations."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.user = make_user(role=User.Role.COMPANY)

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_create_valid_company_profile(self):
        """Creates a complete CompanyProfile instance and verifies field values."""
        cin = generate_valid_cin()
        pan = generate_valid_pan()
        company = CompanyProfile.objects.create(
            user=self.user,
            company_name='Infosys Limited',
            legal_name='Infosys Technologies Private Limited',
            cin_number=cin,
            pan_number=pan,
            csr_registration_number='CSR00012345',
            contact_person_name='Rohit Sharma',
            contact_person_designation='Head of CSR',
            contact_email='csr@infosys.com',
            contact_phone='+919876543210',
            official_website='https://www.infosys.com',
            registered_address='Electronics City, Hosur Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560100',
            annual_csr_budget=Decimal('15000000.00'),
            verification_status=CompanyVerificationStatus.DRAFT,
        )
        self.assertIsInstance(company.id, uuid.UUID)
        self.assertEqual(company.user, self.user)
        self.assertEqual(company.company_name, 'Infosys Limited')
        self.assertEqual(company.cin_number, cin)
        self.assertEqual(company.pan_number, pan)
        self.assertEqual(company.annual_csr_budget, Decimal('15000000.00'))
        self.assertEqual(company.verification_status, CompanyVerificationStatus.DRAFT)
        self.assertIsNotNone(company.created_at)
        self.assertIsNotNone(company.updated_at)
        self.assertEqual(str(company), f"Infosys Limited ({CompanyVerificationStatus.DRAFT})")

    def test_user_role_compatibility(self):
        """Company profile can link to user with COMPANY role."""
        company = make_company_profile(user=self.user)
        self.assertEqual(company.user.role, User.Role.COMPANY)

    def test_onetoone_uniqueness_with_user(self):
        """A user account can only be linked to exactly one CompanyProfile."""
        make_company_profile(user=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CompanyProfile.objects.create(
                    user=self.user,
                    company_name='Second Company',
                    legal_name='Second Company Pvt Ltd',
                    cin_number=generate_valid_cin(),
                    pan_number=generate_valid_pan(),
                    contact_person_name='Jane',
                    contact_person_designation='Director',
                    contact_email='jane@second.com',
                    contact_phone='+919876543211',
                    registered_address='BKC',
                    city='Mumbai',
                    state='Maharashtra',
                    pincode='400051',
                )

    def test_cin_uniqueness_enforced_at_db(self):
        """Duplicate non-null CIN numbers must be rejected at database level."""
        shared_cin = generate_valid_cin()
        make_company_profile(cin_number=shared_cin)
        other_user = make_user(role=User.Role.COMPANY)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_company_profile(user=other_user, cin_number=shared_cin)

    def test_cin_nullable_allows_multiple_nulls(self):
        """Multiple companies may have null CIN (e.g. unincorporated or early draft)."""
        c1 = make_company_profile(cin_number=None)
        c2 = make_company_profile(cin_number=None)
        self.assertIsNone(c1.cin_number)
        self.assertIsNone(c2.cin_number)

    def test_full_clean_validates_cin_format(self):
        """full_clean() rejects invalid CIN formats before saving."""
        company = CompanyProfile(
            user=self.user,
            company_name='Bad CIN Corp',
            legal_name='Bad CIN Corp Ltd',
            cin_number='INVALID_CIN_123',
            pan_number=generate_valid_pan(),
            contact_person_name='John',
            contact_person_designation='Manager',
            contact_email='john@badcin.com',
            contact_phone='+919876543210',
            registered_address='Address',
            city='Delhi',
            state='Delhi',
            pincode='110001',
        )
        with self.assertRaises(ValidationError) as ctx:
            company.full_clean()
        self.assertIn('cin_number', ctx.exception.message_dict)

    def test_full_clean_validates_pan_format(self):
        """full_clean() rejects invalid PAN formats."""
        company = CompanyProfile(
            user=self.user,
            company_name='Bad PAN Corp',
            legal_name='Bad PAN Corp Ltd',
            cin_number=generate_valid_cin(),
            pan_number='BADPAN12',
            contact_person_name='John',
            contact_person_designation='Manager',
            contact_email='john@badpan.com',
            contact_phone='+919876543210',
            registered_address='Address',
            city='Delhi',
            state='Delhi',
            pincode='110001',
        )
        with self.assertRaises(ValidationError) as ctx:
            company.full_clean()
        self.assertIn('pan_number', ctx.exception.message_dict)

    def test_full_clean_validates_pincode_and_phone(self):
        """full_clean() validates pincode and phone regexes."""
        company = CompanyProfile(
            user=self.user,
            company_name='Bad Pin Corp',
            legal_name='Bad Pin Corp Ltd',
            cin_number=generate_valid_cin(),
            pan_number=generate_valid_pan(),
            contact_person_name='John',
            contact_person_designation='Manager',
            contact_email='john@badpin.com',
            contact_phone='123',  # Too short
            registered_address='Address',
            city='Delhi',
            state='Delhi',
            pincode='1100',      # Not 6 digits
        )
        with self.assertRaises(ValidationError) as ctx:
            company.full_clean()
        self.assertIn('contact_phone', ctx.exception.message_dict)
        self.assertIn('pincode', ctx.exception.message_dict)

    def test_full_clean_negative_annual_budget_rejected(self):
        """full_clean() rejects negative annual CSR budget."""
        company = CompanyProfile(
            user=self.user,
            company_name='Neg Budget Corp',
            legal_name='Neg Budget Corp Ltd',
            cin_number=generate_valid_cin(),
            pan_number=generate_valid_pan(),
            contact_person_name='John',
            contact_person_designation='Manager',
            contact_email='john@budget.com',
            contact_phone='+919876543210',
            registered_address='Address',
            city='Delhi',
            state='Delhi',
            pincode='110001',
            annual_csr_budget=Decimal('-1000.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            company.full_clean()
        self.assertIn('annual_csr_budget', ctx.exception.message_dict)

    def test_verification_status_lifecycle_values(self):
        """CompanyProfile supports all verification status values."""
        company = make_company_profile(user=self.user)
        for status in CompanyVerificationStatus.values:
            company.verification_status = status
            company.save()
            company.refresh_from_db()
            self.assertEqual(company.verification_status, status)

    def test_verified_by_set_null_on_user_deletion(self):
        """Deleting admin user who verified the company sets verified_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        company = make_company_profile(
            user=self.user,
            verification_status=CompanyVerificationStatus.APPROVED,
            verified_by=admin_user,
        )
        self.assertEqual(company.verified_by, admin_user)
        admin_user.delete()
        company.refresh_from_db()
        self.assertIsNone(company.verified_by)

    def test_filefield_upload_and_path_generation(self):
        """FileField upload works and generates expected path without polluting production."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            company = make_company_profile(user=self.user)
            dummy_file = make_dummy_uploaded_file(name='inc_cert.pdf')
            company.verification_document = dummy_file
            company.save()

            path = company.verification_document.name
            self.assertTrue(path.startswith(f'csr_docs/companies/{company.id}/'))
            self.assertTrue(path.endswith('.pdf'))

            # Test upload path generator function directly
            gen_path = company_verification_doc_path(company, 'cert.PDF')
            self.assertTrue(gen_path.startswith(f'csr_docs/companies/{company.id}/'))
            self.assertTrue(gen_path.endswith('.pdf'))
