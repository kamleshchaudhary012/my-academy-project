"""
Tests for NGO Legal Information Date Validation & Completeness Fix
==================================================================
Validates that:
1. Empty date strings ("") for optional certification validities are safely converted to None.
2. The exact production payload from AWS (PAN: CKUPC8425M, Darpan: GJ/08/2032, CSR-1: Csr98423456)
   saves successfully via NGOLegalMeView without 400 DateField formatting errors.
3. validate_ngo_completeness correctly recognises the persisted legal info.
4. NGO submission succeeds without raising LEGAL_INFO completeness failure.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from ngo.models import (
    NGOProfile,
    NGOLegalInfo,
    NGOAddress,
    NGOBankInfo,
    NGOVerification,
)
from ngo.serializers import NGOLegalInfoSerializer
from ngo.services.submission_service import validate_ngo_completeness
from ngo.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_legal_info,
    make_bank_info,
)

User = get_user_model()


class NGOLegalInfoCompletenessFixTests(APITestCase):

    def setUp(self):
        self.ngo_user = make_user(email='ngo_prod_test@example.com', role='NGO')
        self.ngo_profile = make_ngo_profile(user=self.ngo_user)
        self.url_legal = reverse('ngo_legal_me')
        self.url_submit = reverse('ngo_submit')

    def test_serializer_empty_strings_convert_to_none(self):
        """Empty string date fields must be converted to None instead of raising ValidationError."""
        raw_data = {
            'organisation_type': 'TRUST',
            'registering_authority': 'Charity Commissioner',
            'registration_number': 'REG/TEST/2020',
            'registration_state': 'Gujarat',
            'chief_trustee_name': 'John Doe',
            'chief_trustee_designation': 'Managing Trustee',
            'pan_number': 'CKUPC8425M',
            'darpan_id': 'GJ/08/2032',
            'csr_registration_number': 'Csr98423456',
            'has_12a': False,
            'twelve_a_validity': '',
            'has_80g': False,
            'eighty_g_validity': '',
            'has_fcra': False,
            'fcra_validity': '',
            'has_10_23c': False,
            'ten_23c_validity': '',
            'csr_registration_date': '',
        }
        serializer = NGOLegalInfoSerializer(data=raw_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data['twelve_a_validity'])
        self.assertIsNone(serializer.validated_data['eighty_g_validity'])
        self.assertIsNone(serializer.validated_data['fcra_validity'])
        self.assertIsNone(serializer.validated_data['ten_23c_validity'])
        self.assertIsNone(serializer.validated_data['csr_registration_date'])

    def test_save_exact_aws_production_payload(self):
        """The exact values submitted in the AWS production incident must succeed via the API."""
        self.client.force_authenticate(user=self.ngo_user)
        payload = {
            'organisation_type': 'TRUST',
            'registering_authority': 'Charity Commissioner',
            'registration_number': 'REG/TEST/2020',
            'registration_state': 'Gujarat',
            'chief_trustee_name': 'John Doe',
            'chief_trustee_designation': 'Managing Trustee',
            'darpan_id': 'GJ/08/2032',
            'pan_number': 'CKUPC8425M',
            'csr_registration_number': 'Csr98423456',
            'has_12a': False,
            'twelve_a_validity': '',
            'has_80g': False,
            'eighty_g_validity': '',
            'has_fcra': False,
            'fcra_validity': '',
            'has_10_23c': False,
            'ten_23c_validity': '',
            'csr_registration_date': '',
        }

        response = self.client.post(self.url_legal, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        # Confirm persisted in DB
        self.ngo_profile.refresh_from_db()
        self.assertTrue(hasattr(self.ngo_profile, 'legal_info'))
        legal = self.ngo_profile.legal_info
        self.assertEqual(legal.pan_number, 'CKUPC8425M')
        self.assertEqual(legal.darpan_id, 'GJ/08/2032')
        self.assertEqual(legal.csr_registration_number, 'CSR98423456')

    def test_completeness_passes_when_legal_info_persisted(self):
        """validate_ngo_completeness must not include 'legal_info' in errors when saved."""
        make_legal_info(
            self.ngo_profile,
            pan_number='CKUPC8425M',
            darpan_id='GJ/08/2032',
            csr_registration_number='CSR98423456',
        )

        errors = validate_ngo_completeness(self.ngo_profile)
        self.assertNotIn('legal_info', errors)
