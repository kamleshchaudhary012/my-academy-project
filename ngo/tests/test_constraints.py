"""
DaanGives NGO Model Tests — Constraints
=======================================
Test modules:
  - TestUniqueConstraints (6 tests)
Total: 6 tests
"""

from django.test import TestCase
from django.db import IntegrityError

from ngo.models import NGOLeadership
from ngo.tests.helpers import (
    make_ngo_profile,
    make_legal_info,
)


class TestUniqueConstraints(TestCase):
    """C. Verify all uniqueness constraints."""

    def setUp(self):
        self.ngo1 = make_ngo_profile()
        self.ngo2 = make_ngo_profile()

    def test_c1_duplicate_darpan_id_rejected(self):
        """Two NGOs cannot have the same Darpan ID."""
        make_legal_info(self.ngo1, darpan_id='GJ/2010/UNIQUE1', pan_number='AABCT1234D')
        with self.assertRaises(IntegrityError):
            make_legal_info(self.ngo2, darpan_id='GJ/2010/UNIQUE1', pan_number='BBCDE2345E')

    def test_c2_duplicate_pan_rejected(self):
        """Two NGOs cannot have the same PAN number."""
        make_legal_info(self.ngo1, darpan_id='GJ/2010/UNIQUE2', pan_number='AABCT5678D')
        with self.assertRaises(IntegrityError):
            make_legal_info(
                self.ngo2,
                darpan_id='GJ/2011/UNIQUE3',
                pan_number='AABCT5678D',  # same PAN
            )

    def test_c3_composite_registration_identity_unique(self):
        """Same (org_type, authority, reg_number) cannot be used twice."""
        make_legal_info(
            self.ngo1,
            organisation_type='TRUST',
            registering_authority='Charity Commissioner, Gujarat',
            registration_number='E/999/AHM',
            darpan_id='GJ/2010/UNIQUE4',
            pan_number='AABCT9012D',
        )
        with self.assertRaises(IntegrityError):
            make_legal_info(
                self.ngo2,
                organisation_type='TRUST',
                registering_authority='Charity Commissioner, Gujarat',
                registration_number='E/999/AHM',  # same composite
                darpan_id='GJ/2011/UNIQUE5',
                pan_number='BBCDE3456E',
            )

    def test_c4_same_reg_number_different_authority_is_allowed(self):
        """Same registration number under a different authority is allowed."""
        make_legal_info(
            self.ngo1,
            organisation_type='TRUST',
            registering_authority='Charity Commissioner, Gujarat',
            registration_number='SAME/001',
            darpan_id='GJ/2010/UNIQUE6',
            pan_number='AABCT3456D',
        )
        # Different authority — should succeed
        legal2 = make_legal_info(
            self.ngo2,
            organisation_type='TRUST',
            registering_authority='Charity Commissioner, Maharashtra',
            registration_number='SAME/001',  # same number, different authority
            darpan_id='MH/2010/UNIQUE7',
            pan_number='BBCDE4567E',
        )
        self.assertIsNotNone(legal2.pk)

    def test_c5_only_one_primary_contact_per_ngo(self):
        """Only one is_primary_contact=True allowed per NGO."""
        ngo = make_ngo_profile()
        NGOLeadership.objects.create(
            ngo=ngo, full_name='Leader One', designation='President',
            is_primary_contact=True,
        )
        with self.assertRaises(IntegrityError):
            NGOLeadership.objects.create(
                ngo=ngo, full_name='Leader Two', designation='Secretary',
                is_primary_contact=True,  # Second primary — must fail
            )

    def test_c6_pan_is_normalized_to_uppercase(self):
        """PAN number is normalized to uppercase on save."""
        ngo = make_ngo_profile()
        legal = make_legal_info(ngo, pan_number='aabct1234d', darpan_id='GJ/2010/NORMTEST')
        self.assertEqual(legal.pan_number, 'AABCT1234D')
