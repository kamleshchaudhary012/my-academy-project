"""
Unit Tests for CSR Company Service — Phase CSR-2.5
===================================================
Tests CompanyProfile registration, updating, document upload, verification
request lifecycle, and preferences management.
"""

from decimal import Decimal
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from users.models import User
from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CompanyVerificationStatus,
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.services.company_service import (
    register_company,
    get_company_for_user,
    update_company_profile,
    attach_company_document,
    request_company_verification,
    get_company_preferences,
    update_company_preferences,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
)
from csr.tests.helpers import make_user, make_company_profile, generate_valid_cin, generate_valid_pan


class CompanyServiceTests(TestCase):
    """Tests for corporate profile business logic service."""

    def setUp(self):
        self.company_user = make_user(email="comp1@example.com", role=User.Role.COMPANY)
        self.company_user_2 = make_user(email="comp2@example.com", role=User.Role.COMPANY)
        self.ngo_user = make_user(email="ngo@example.com", role=User.Role.NGO)
        self.donor_user = make_user(email="donor@example.com", role=User.Role.DONOR)
        self.inactive_user = make_user(email="inactive@example.com", role=User.Role.COMPANY, is_active=False)

    def test_register_company_success(self):
        """Successfully registers a new company profile in DRAFT with associated preferences."""
        data = {
            'company_name': 'Tech Corp India',
            'legal_name': 'Tech Corp India Pvt Ltd',
            'cin_number': generate_valid_cin(),
            'pan_number': generate_valid_pan(),
            'contact_person_name': 'Alice Smith',
            'contact_person_designation': 'Director',
            'contact_email': 'alice@techcorp.com',
            'contact_phone': '+919876543210',
            'registered_address': '45 Tech Hub, Whitefield',
            'city': 'Bengaluru',
            'state': 'Karnataka',
            'pincode': '560066',
            'annual_csr_budget': '5000000.00',
        }
        company = register_company(self.company_user, data)
        self.assertEqual(company.company_name, 'Tech Corp India')
        self.assertEqual(company.verification_status, CompanyVerificationStatus.DRAFT)
        self.assertTrue(CompanyCSRPreference.objects.filter(company=company).exists())

    def test_register_company_strips_client_status_spoofing(self):
        """Registering company ignores client-injected status or verification fields."""
        data = {
            'company_name': 'Spoof Corp',
            'legal_name': 'Spoof Corp Pvt Ltd',
            'cin_number': generate_valid_cin(),
            'pan_number': generate_valid_pan(),
            'contact_person_name': 'Bob',
            'contact_person_designation': 'CEO',
            'contact_email': 'bob@spoof.com',
            'contact_phone': '+919876543210',
            'registered_address': '123 Fake St',
            'city': 'Mumbai',
            'state': 'Maharashtra',
            'pincode': '400001',
            'verification_status': 'APPROVED',  # Attempted spoof
        }
        company = register_company(self.company_user, data)
        self.assertEqual(company.verification_status, CompanyVerificationStatus.DRAFT)

    def test_register_company_rejects_non_company_user(self):
        """Non-COMPANY roles cannot register a company profile."""
        data = {
            'company_name': 'NGO Corp',
            'legal_name': 'NGO Corp Pvt Ltd',
            'pan_number': generate_valid_pan(),
            'contact_person_name': 'Charlie',
            'contact_person_designation': 'Head',
            'contact_email': 'charlie@ngo.com',
            'contact_phone': '+919876543210',
            'registered_address': '123 St',
            'city': 'Delhi',
            'state': 'Delhi',
            'pincode': '110001',
        }
        with self.assertRaises(CSROwnershipError):
            register_company(self.ngo_user, data)
        with self.assertRaises(CSROwnershipError):
            register_company(self.donor_user, data)
        with self.assertRaises(CSROwnershipError):
            register_company(self.inactive_user, data)

    def test_register_company_duplicate_prevention(self):
        """Cannot register more than one CompanyProfile for the same user."""
        make_company_profile(user=self.company_user)
        data = {
            'company_name': 'Second Corp',
            'legal_name': 'Second Corp Pvt Ltd',
            'pan_number': generate_valid_pan(),
            'contact_person_name': 'Dan',
            'contact_person_designation': 'Manager',
            'contact_email': 'dan@second.com',
            'contact_phone': '+919876543210',
            'registered_address': '123 St',
            'city': 'Pune',
            'state': 'Maharashtra',
            'pincode': '411001',
        }
        with self.assertRaises(CSRConflictError):
            register_company(self.company_user, data)

    def test_register_company_missing_fields_validation(self):
        """Missing mandatory profile fields raises CSRValidationError."""
        data = {'company_name': 'Incomplete Corp'}
        with self.assertRaises(CSRValidationError):
            register_company(self.company_user, data)

    def test_get_company_for_user(self):
        """Retrieves profile or raises CSRNotFoundError."""
        with self.assertRaises(CSRNotFoundError):
            get_company_for_user(self.company_user)

        created = make_company_profile(user=self.company_user)
        fetched = get_company_for_user(self.company_user)
        self.assertEqual(created.id, fetched.id)

    def test_update_company_profile(self):
        """Updates contact info while ignoring client-injected verification fields."""
        company = make_company_profile(user=self.company_user)
        update_data = {
            'city': 'Navi Mumbai',
            'verification_status': 'APPROVED',  # Must be ignored
        }
        updated = update_company_profile(self.company_user, update_data)
        self.assertEqual(updated.city, 'Navi Mumbai')
        self.assertEqual(updated.verification_status, company.verification_status)

    def test_attach_company_document(self):
        """Attaches verification document successfully."""
        company = make_company_profile(user=self.company_user, verification_document=None)
        doc = SimpleUploadedFile("coi.pdf", b"%PDF-1.4 test certificate", content_type="application/pdf")
        updated = attach_company_document(self.company_user, doc)
        self.assertTrue(bool(updated.verification_document))

    def test_request_company_verification_success(self):
        """Submitting for verification transitions DRAFT -> PENDING_VERIFICATION and records audit."""
        doc = SimpleUploadedFile("coi.pdf", b"%PDF-1.4 test certificate", content_type="application/pdf")
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.DRAFT,
            verification_document=doc,
        )
        updated = request_company_verification(self.company_user)
        self.assertEqual(updated.verification_status, CompanyVerificationStatus.PENDING_VERIFICATION)

        # Verify audit record
        history = CSRVerificationHistory.objects.filter(entity_id=company.id, entity_type=CSRAuditEntityType.COMPANY)
        self.assertTrue(history.exists())
        self.assertEqual(history.first().new_status, CompanyVerificationStatus.PENDING_VERIFICATION)

    def test_request_company_verification_missing_document_rejected(self):
        """Requesting verification without an uploaded document raises CSRValidationError."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.DRAFT,
            verification_document=None,
        )
        with self.assertRaises(CSRValidationError):
            request_company_verification(self.company_user)

    def test_request_company_verification_invalid_states(self):
        """Already approved or suspended company cannot request verification directly."""
        doc = SimpleUploadedFile("coi.pdf", b"%PDF-1.4 test certificate", content_type="application/pdf")
        company_app = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.APPROVED,
            verification_document=doc,
        )
        with self.assertRaises(CSRStateError):
            request_company_verification(self.company_user)

        company_app.verification_status = CompanyVerificationStatus.SUSPENDED
        company_app.save()
        with self.assertRaises(CSRStateError):
            request_company_verification(self.company_user)

    def test_preferences_lifecycle(self):
        """Getting and updating preferences enforces min_budget <= max_budget."""
        company = make_company_profile(user=self.company_user)
        prefs = get_company_preferences(self.company_user)
        self.assertIsNotNone(prefs)

        updated_prefs = update_company_preferences(self.company_user, {
            'is_nationwide': True,
            'min_budget': Decimal('100000.00'),
            'max_budget': Decimal('500000.00'),
            'preferred_categories': ['PROMOTING_EDUCATION'],
        })
        self.assertTrue(updated_prefs.is_nationwide)
        self.assertEqual(updated_prefs.min_budget, Decimal('100000.00'))

        # Invalid range: min > max
        with self.assertRaises(CSRValidationError):
            update_company_preferences(self.company_user, {
                'min_budget': Decimal('600000.00'),
                'max_budget': Decimal('500000.00'),
            })
