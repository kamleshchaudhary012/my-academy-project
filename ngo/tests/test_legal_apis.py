"""
DaanGives NGO Legal API Tests — Phase 3.3.2-B
==============================================
Mandatory test suite covering the 3 NGO Legal Info endpoints:
  - GET   /api/v1/ngo/legal/me/
  - POST  /api/v1/ngo/legal/me/
  - PATCH /api/v1/ngo/legal/me/

25 Mandatory Tests Covered:
  1. Unauthenticated GET → 401
  2. Unauthenticated POST → 401
  3. Unauthenticated PATCH → 401
  4. Donor GET → 403
  5. Admin GET → 403
  6. NGO GET without legal record → 404
  7. NGO POST valid legal data → 201
  8. NGO POST duplicate legal record → 400
  9. NGO GET own legal data → 200
  10. NGO PATCH own legal data → 200 where allowed
  11. NGO cannot access another NGO's legal data
  12. PAN lowercase input is normalized to uppercase
  13. Invalid PAN rejected
  14. Invalid Darpan characters rejected
  15. Duplicate Darpan rejected
  16. Duplicate PAN rejected
  17. Duplicate registration identity rejected
  18. Missing 12A number when has_12a=True rejected
  19. Missing 80G number when has_80g=True rejected
  20. Missing FCRA number when has_fcra=True rejected
  21. Locked identifier fields cannot be modified after submission
  22. Client cannot modify NGO ownership
  23. Client cannot modify lifecycle fields
  24. Invalid payload returns structured field errors
  25. Database integrity remains intact after failed validation
"""

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse

from ngo.models import NGOProfile, NGOLegalInfo, NGOVerification
from ngo.tests.helpers import make_user, make_ngo_profile, make_legal_info, make_admin_user


class TestNGOLegalAPIs(APITestCase):

    def setUp(self):
        self.ngo_user_a = make_user(email='ngoa@test.com', role='NGO')
        self.ngo_user_b = make_user(email='ngob@test.com', role='NGO')
        self.donor_user = make_user(email='donor@test.com', role='DONOR')
        self.admin_user = make_admin_user()

        self.url_legal_me = reverse('ngo_legal_me')

        self.valid_legal_payload = {
            'organisation_type': 'TRUST',
            'registering_authority': 'Charity Commissioner, Gujarat',
            'registration_number': 'E/12345/AHM',
            'darpan_id': 'GJ/2012/00123',
            'pan_number': 'AABCT1234D',
            'registration_state': 'Gujarat',
            'chief_trustee_name': 'Dr. Rajesh Shah',
            'chief_trustee_designation': 'Managing Trustee',
            'has_12a': False,
            'has_80g': False,
            'has_fcra': False,
        }

    # 1. Unauthenticated GET -> 401
    def test_01_unauthenticated_get_returns_401(self):
        response = self.client.get(self.url_legal_me)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # 2. Unauthenticated POST -> 401
    def test_02_unauthenticated_post_returns_401(self):
        response = self.client.post(self.url_legal_me, self.valid_legal_payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # 3. Unauthenticated PATCH -> 401
    def test_03_unauthenticated_patch_returns_401(self):
        response = self.client.patch(self.url_legal_me, {'chief_trustee_name': 'New Name'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # 4. Donor GET -> 403
    def test_04_donor_get_returns_403(self):
        self.client.force_authenticate(user=self.donor_user)
        response = self.client.get(self.url_legal_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 5. Admin GET -> 403
    def test_05_admin_get_returns_403(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url_legal_me)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 6. NGO GET without legal record -> 404
    def test_06_ngo_get_without_legal_record_returns_404(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_legal_me)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('legal information not found', response.data['detail'])

    # 7. NGO POST valid legal data -> 201
    def test_07_ngo_post_valid_legal_data_returns_201(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_legal_me, self.valid_legal_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['pan_number'], 'AABCT1234D')
        self.assertEqual(response.data['darpan_id'], 'GJ/2012/00123')

    # 8. NGO POST duplicate legal record -> 400
    def test_08_ngo_post_duplicate_legal_record_returns_400(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_legal_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.post(self.url_legal_me, self.valid_legal_payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already exists', response.data['detail'])

    # 9. NGO GET own legal data -> 200
    def test_09_ngo_get_own_legal_data_returns_200(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        legal = make_legal_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_legal_me)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['pan_number'], legal.pan_number)

    # 10. NGO PATCH own legal data -> 200 where allowed
    def test_10_ngo_patch_own_legal_data_returns_200(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        make_legal_info(ngo)
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_legal_me, {'chief_trustee_name': 'Updated Trustee'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['chief_trustee_name'], 'Updated Trustee')

    # 11. NGO cannot access another NGO's legal data
    def test_11_ngo_cannot_access_another_ngos_legal_data(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        legal_b = make_legal_info(ngo_b, pan_number='BBCDE5678E', darpan_id='GJ/2015/99999')

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.get(self.url_legal_me)
        # NGO A does not have legal info -> 404 (isolated from NGO B)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # 12. PAN lowercase input is normalized to uppercase
    def test_12_pan_lowercase_normalized_to_uppercase(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, pan_number='aabct1234d')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['pan_number'], 'AABCT1234D')

    # 13. Invalid PAN rejected
    def test_13_invalid_pan_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, pan_number='INVALID123')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pan_number', response.data)

    # 14. Invalid Darpan characters rejected
    def test_14_invalid_darpan_chars_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, darpan_id='GJ@2010#BAD')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('darpan_id', response.data)

    # 15. Duplicate Darpan rejected
    def test_15_duplicate_darpan_rejected(self):
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        make_legal_info(ngo_b, darpan_id='GJ/2012/SAME1', pan_number='BBCDE1234F')

        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, darpan_id='GJ/2012/SAME1', pan_number='AABCT5678D')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('darpan_id', response.data)

    # 16. Duplicate PAN rejected
    def test_16_duplicate_pan_rejected(self):
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        make_legal_info(ngo_b, darpan_id='GJ/2012/OTHER1', pan_number='AABCT5555D')

        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, darpan_id='GJ/2012/NEW1', pan_number='AABCT5555D')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pan_number', response.data)

    # 17. Duplicate registration identity rejected
    def test_17_duplicate_registration_identity_rejected(self):
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        make_legal_info(
            ngo_b,
            organisation_type='TRUST',
            registering_authority='Charity Commissioner, Gujarat',
            registration_number='E/999/AHM',
            darpan_id='GJ/2012/UNIQUE1',
            pan_number='BBCDE7890F',
        )

        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(
            self.valid_legal_payload,
            organisation_type='TRUST',
            registering_authority='Charity Commissioner, Gujarat',
            registration_number='E/999/AHM',
            darpan_id='GJ/2012/UNIQUE2',
            pan_number='AABCT1234D',
        )
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # 18. Missing 12A number when has_12a=True rejected
    def test_18_missing_12a_number_when_has_12a_true_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, has_12a=True, twelve_a_number='')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('twelve_a_number', response.data)

    # 19. Missing 80G number when has_80g=True rejected
    def test_19_missing_80g_number_when_has_80g_true_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, has_80g=True, eighty_g_number='')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('eighty_g_number', response.data)

    # 20. Missing FCRA number when has_fcra=True rejected
    def test_20_missing_fcra_number_when_has_fcra_true_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, has_fcra=True, fcra_number='')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('fcra_number', response.data)

    # 21. Locked identifier fields cannot be modified after submission
    def test_21_locked_identifier_fields_cannot_be_modified_after_submission(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        legal = make_legal_info(ngo, darpan_id='GJ/2012/ORIG1')
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUBMITTED')

        self.client.force_authenticate(user=self.ngo_user_a)
        # Profile is in SUBMITTED -> PATCH is blocked with 403
        response = self.client.patch(self.url_legal_me, {'darpan_id': 'GJ/2012/MODIFIED'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 22. Client cannot modify NGO ownership
    def test_22_client_cannot_modify_ngo_ownership(self):
        ngo_a = make_ngo_profile(user=self.ngo_user_a)
        ngo_b = make_ngo_profile(user=self.ngo_user_b)
        legal_a = make_legal_info(ngo_a)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_legal_me, {'ngo': str(ngo_b.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        legal_a.refresh_from_db()
        self.assertEqual(legal_a.ngo, ngo_a)  # NGO ownership untouched

    # 23. Client cannot modify lifecycle fields
    def test_23_client_cannot_modify_lifecycle_fields(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        legal = make_legal_info(ngo)

        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_legal_me, {'status': 'APPROVED', 'is_active': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ngo.refresh_from_db()
        self.assertEqual(ngo.status, 'DRAFT')  # Lifecycle fields on profile untouched

    # 24. Invalid payload returns structured field errors
    def test_24_invalid_payload_returns_structured_field_errors(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(self.valid_legal_payload, pan_number='INVALID', darpan_id='INVALID@ID#')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsInstance(response.data, dict)
        self.assertIn('pan_number', response.data)

    # 25. Database integrity remains intact after failed validation
    def test_25_db_integrity_remains_intact_after_failed_validation(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        count_before = NGOLegalInfo.objects.count()

        # Submit invalid payload
        payload = dict(self.valid_legal_payload, pan_number='BADPAN123')
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Count in DB must be unchanged
        count_after = NGOLegalInfo.objects.count()
        self.assertEqual(count_before, count_after)

    # 26. Valid CSR-1 saved and retrieved
    def test_26_valid_csr1_saved_and_retrieved(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(
            self.valid_legal_payload,
            has_csr_1=True,
            csr_registration_number='CSR00012345',
            csr_registration_date='2022-04-15',
        )
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['has_csr_1'])
        self.assertEqual(response.data['csr_registration_number'], 'CSR00012345')
        self.assertEqual(response.data['csr_registration_date'], '2022-04-15')

        # Retrieve
        get_res = self.client.get(self.url_legal_me)
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertTrue(get_res.data['has_csr_1'])
        self.assertEqual(get_res.data['csr_registration_number'], 'CSR00012345')

    # 27. CSR-1 lowercase normalized to uppercase
    def test_27_csr1_lowercase_normalized_to_uppercase(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(
            self.valid_legal_payload,
            has_csr_1=True,
            csr_registration_number='csr00098765',
        )
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['csr_registration_number'], 'CSR00098765')

    # 28. Missing CSR-1 number when has_csr_1=True rejected
    def test_28_missing_csr1_number_when_has_csr1_true_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(
            self.valid_legal_payload,
            has_csr_1=True,
            csr_registration_number='',
        )
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('csr_registration_number', response.data)

    # 29. Invalid CSR-1 format rejected
    def test_29_invalid_csr1_format_rejected(self):
        make_ngo_profile(user=self.ngo_user_a)
        self.client.force_authenticate(user=self.ngo_user_a)
        payload = dict(
            self.valid_legal_payload,
            has_csr_1=True,
            csr_registration_number='INVALID_CSR_123',
        )
        response = self.client.post(self.url_legal_me, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('csr_registration_number', response.data)

    # 30. is_csr_eligible computed property
    def test_30_is_csr_eligible_computed_property(self):
        ngo = make_ngo_profile(user=self.ngo_user_a)
        legal = make_legal_info(
            ngo,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            has_12a=True,
            twelve_a_number='12A123',
            has_80g=True,
            eighty_g_number='80G123',
            has_csr_1=True,
            csr_registration_number='CSR00012345',
        )
        self.assertTrue(legal.is_csr_eligible)

        # Ineligible if missing 80G
        legal.has_80g = False
        legal.eighty_g_number = ''
        self.assertFalse(legal.is_csr_eligible)

        # Ineligible if organisation_type is OTHER
        legal.has_80g = True
        legal.eighty_g_number = '80G123'
        legal.organisation_type = NGOLegalInfo.OrgType.OTHER
        self.assertFalse(legal.is_csr_eligible)

    # 31. CSR-1 number locked once application is submitted
    def test_31_csr1_number_locked_after_submission(self):
        ngo = make_ngo_profile(user=self.ngo_user_a, status=NGOProfile.Status.SUBMITTED)
        legal = make_legal_info(
            ngo,
            has_csr_1=True,
            csr_registration_number='CSR00012345',
        )
        self.client.force_authenticate(user=self.ngo_user_a)
        response = self.client.patch(self.url_legal_me, {'csr_registration_number': 'CSR00099999'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
