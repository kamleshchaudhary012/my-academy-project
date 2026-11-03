"""
DaanGives Public NGO API Tests — Phase 3.3.2-G
===============================================
Mandatory test suite covering the 3 Public NGO API endpoints:
  - GET /api/v1/public/ngos/
  - GET /api/v1/public/ngos/<slug:slug>/
  - GET /api/v1/public/ngos/id/<uuid:pk>/

34 Mandatory Tests Covered across Public Visibility Rules (APPROVED + is_active=True ONLY),
Exclusion of Non-Public Statuses, Multi-Field Search, Category/Location/Tax Filters, Pagination, Ordering,
Slug & UUID Detail Lookups, and Public Response Data Isolation.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGOLeadership,
    NGODocument,
)
from ngo.tests.helpers import make_user, make_ngo_profile


class TestNGOPublicAPIs(APITestCase):

    def setUp(self):
        self.url_list = reverse('ngo_public_list')

        # Create an approved & active NGO (Publicly Visible)
        self.public_user = make_user(email='public_ngo@test.com', role='NGO')
        self.public_ngo = make_ngo_profile(
            user=self.public_user,
            legal_name='Vidyadeep Educational Trust',
            display_name='Vidyadeep Foundation',
            gujarati_name='વિદ્યાદીપ ફાઉન્ડેશન',
            category='EDUCATION',
            description='Empowering children through quality rural education and nutrition across Gujarat.',
            year_established=2010,
        )

        # Set status=APPROVED and is_active=True
        NGOProfile.objects.filter(pk=self.public_ngo.pk).update(status='APPROVED', is_active=True)
        self.public_ngo.refresh_from_db()

        self.address = NGOAddress.objects.create(
            ngo=self.public_ngo,
            address_line1='100 Vidya Marg',
            city='Ahmedabad',
            district='Ahmedabad District',
            state='Gujarat',
            pincode='380001',
            service_areas='Rural Ahmedabad, Sanand',
        )

        self.legal = NGOLegalInfo.objects.create(
            ngo=self.public_ngo,
            organisation_type='TRUST',
            registration_number='REG-VIDYA-123',
            darpan_id='GJ/2010/0012345',
            pan_number='AAAAV1234F',
            registration_state='Gujarat',
            chief_trustee_name='Kiritbhai Shah',
            chief_trustee_designation='Managing Trustee',
            has_12a=True,
            twelve_a_number='12A-CERT-999',
            has_80g=True,
            eighty_g_number='80G-CERT-888',
            has_fcra=True,
            fcra_number='FCRA-CERT-777',
        )

        self.bank = NGOBankInfo.objects.create(
            ngo=self.public_ngo,
            account_holder_name='Vidyadeep Educational Trust',
            account_number='98765432101234',
            ifsc_code='SBIN0001234',
            bank_name='State Bank of India',
            branch_name='Ashram Road',
            account_type='SAVINGS',
        )

        self.leader = NGOLeadership.objects.create(
            ngo=self.public_ngo,
            full_name='Kiritbhai Shah',
            designation='Managing Trustee',
            phone='+919876543210',
            email='kirit@vidyadeep.org',
            is_primary_contact=True,
            is_active=True,
        )

    def slug_url(self, slug):
        return reverse('ngo_public_detail_slug', kwargs={'slug': slug})

    def uuid_url(self, pk):
        return reverse('ngo_public_detail_uuid', kwargs={'pk': pk})

    # -----------------------------------------------------------------------
    # 1. ANONYMOUS ACCESS & VISIBILITY (10 TESTS)
    # -----------------------------------------------------------------------

    def test_01_anonymous_public_list_access(self):
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_02_anonymous_public_detail_access(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_03_approved_and_active_ngo_appears(self):
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['display_name'], 'Vidyadeep Foundation')

    def test_04_draft_ngo_excluded(self):
        u = make_user(email='draft@test.com', role='NGO')
        make_ngo_profile(user=u)  # Default DRAFT
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    def test_05_submitted_ngo_excluded(self):
        u = make_user(email='submitted@test.com', role='NGO')
        ngo = make_ngo_profile(user=u)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUBMITTED', is_active=False)
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    def test_06_under_review_ngo_excluded(self):
        u = make_user(email='review@test.com', role='NGO')
        ngo = make_ngo_profile(user=u)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='UNDER_REVIEW', is_active=False)
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    def test_07_correction_required_ngo_excluded(self):
        u = make_user(email='correction@test.com', role='NGO')
        ngo = make_ngo_profile(user=u)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='CORRECTION_REQUIRED', is_active=False)
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    def test_08_rejected_ngo_excluded(self):
        u = make_user(email='rejected@test.com', role='NGO')
        ngo = make_ngo_profile(user=u)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='REJECTED', is_active=False)
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    def test_09_suspended_ngo_excluded(self):
        u = make_user(email='suspended@test.com', role='NGO')
        ngo = make_ngo_profile(user=u)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='SUSPENDED', is_active=False)
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    def test_10_approved_but_inactive_ngo_excluded(self):
        u = make_user(email='inactive_approved@test.com', role='NGO')
        ngo = make_ngo_profile(user=u)
        NGOProfile.objects.filter(pk=ngo.pk).update(status='APPROVED', is_active=False)
        response = self.client.get(self.url_list)
        self.assertEqual(response.data['count'], 1)

    # -----------------------------------------------------------------------
    # 2. SEARCH & FILTERS (9 TESTS)
    # -----------------------------------------------------------------------

    def test_11_multi_field_search(self):
        response = self.client.get(self.url_list, {'search': 'Vidyadeep'})
        self.assertEqual(response.data['count'], 1)

        response_city = self.client.get(self.url_list, {'search': 'Ahmedabad'})
        self.assertEqual(response_city.data['count'], 1)

        response_nomatch = self.client.get(self.url_list, {'search': 'NonexistentTerm'})
        self.assertEqual(response_nomatch.data['count'], 0)

    def test_12_category_filter(self):
        res_edu = self.client.get(self.url_list, {'category': 'EDUCATION'})
        self.assertEqual(res_edu.data['count'], 1)

        res_health = self.client.get(self.url_list, {'category': 'HEALTHCARE'})
        self.assertEqual(res_health.data['count'], 0)

    def test_13_city_filter(self):
        res_ahmedabad = self.client.get(self.url_list, {'city': 'Ahmedabad'})
        self.assertEqual(res_ahmedabad.data['count'], 1)

        res_surat = self.client.get(self.url_list, {'city': 'Surat'})
        self.assertEqual(res_surat.data['count'], 0)

    def test_14_district_filter(self):
        res_dist = self.client.get(self.url_list, {'district': 'Ahmedabad District'})
        self.assertEqual(res_dist.data['count'], 1)

    def test_15_state_filter(self):
        res_state = self.client.get(self.url_list, {'state': 'Gujarat'})
        self.assertEqual(res_state.data['count'], 1)

    def test_16_service_area_filter(self):
        res_area = self.client.get(self.url_list, {'service_areas': 'Sanand'})
        self.assertEqual(res_area.data['count'], 1)

    def test_17_has_12a_filter(self):
        res_true = self.client.get(self.url_list, {'has_12a': 'true'})
        self.assertEqual(res_true.data['count'], 1)

    def test_18_has_80g_filter(self):
        res_true = self.client.get(self.url_list, {'has_80g': 'true'})
        self.assertEqual(res_true.data['count'], 1)

    def test_19_has_fcra_filter(self):
        res_true = self.client.get(self.url_list, {'has_fcra': 'true'})
        self.assertEqual(res_true.data['count'], 1)

    # -----------------------------------------------------------------------
    # 3. PAGINATION & ORDERING (2 TESTS)
    # -----------------------------------------------------------------------

    def test_20_pagination_structure(self):
        response = self.client.get(self.url_list)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        self.assertIn('results', response.data)

    def test_21_ordering_by_display_name(self):
        response = self.client.get(self.url_list, {'ordering': 'display_name'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -----------------------------------------------------------------------
    # 4. DETAIL LOOKUPS & 404 HANDLERS (6 TESTS)
    # -----------------------------------------------------------------------

    def test_22_slug_detail_lookup(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], self.public_ngo.slug)

    def test_23_uuid_detail_lookup(self):
        response = self.client.get(self.uuid_url(self.public_ngo.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.public_ngo.id))

    def test_24_invalid_slug_returns_404(self):
        response = self.client.get(self.slug_url('nonexistent-ngo-slug'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_25_invalid_uuid_returns_404(self):
        response = self.client.get(self.uuid_url('00000000-0000-0000-0000-000000000000'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_26_non_public_ngo_slug_returns_404(self):
        u = make_user(email='draft_slug@test.com', role='NGO')
        ngo = make_ngo_profile(user=u, display_name='Draft NGO')
        response = self.client.get(self.slug_url(ngo.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_27_non_public_ngo_uuid_returns_404(self):
        u = make_user(email='draft_uuid@test.com', role='NGO')
        ngo = make_ngo_profile(user=u, display_name='Draft NGO')
        response = self.client.get(self.uuid_url(ngo.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -----------------------------------------------------------------------
    # 5. PUBLIC DATA ISOLATION & SECURITY (7 TESTS)
    # -----------------------------------------------------------------------

    def test_28_bank_information_never_exposed(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        res_str = str(response.data)
        self.assertNotIn('account_number', res_str)
        self.assertNotIn('ifsc_code', res_str)
        self.assertNotIn('bank_name', res_str)

    def test_29_pan_never_exposed(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        res_str = str(response.data)
        self.assertNotIn('pan_number', res_str)

    def test_30_registration_number_never_exposed(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        res_str = str(response.data)
        self.assertNotIn('registration_number', res_str)

    def test_31_private_documents_never_exposed(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        res_str = str(response.data)
        self.assertNotIn('/media/ngo_docs/', res_str)

    def test_32_admin_verification_data_never_exposed(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        res_str = str(response.data)
        self.assertNotIn('admin_notes', res_str)
        self.assertNotIn('risk_flags', res_str)
        self.assertNotIn('rejection_reason', res_str)

    def test_33_leader_phone_and_email_never_exposed(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        leaders = response.data['leadership']
        self.assertGreater(len(leaders), 0)
        leader = leaders[0]
        self.assertNotIn('phone', leader)
        self.assertNotIn('email', leader)

    def test_34_public_response_matches_public_serializer_schema(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_keys = {
            'id', 'display_name', 'gujarati_name', 'slug', 'category', 'description',
            'mission_statement', 'year_established', 'website', 'official_email',
            'official_phone', 'logo', 'cover_image', 'is_public', 'city', 'district',
            'state', 'service_areas', 'has_12a', 'has_80g', 'has_fcra', 'has_csr_1', 'is_csr_verified', 'darpan_id', 'leadership'
        }
        self.assertEqual(set(response.data.keys()), expected_keys)

    def test_34b_public_response_includes_has_csr_1(self):
        response = self.client.get(self.slug_url(self.public_ngo.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('has_csr_1', response.data)
        self.assertIsInstance(response.data['has_csr_1'], bool)

    # -----------------------------------------------------------------------
    # 5. CLEAR FILTERS & PARAMETER SANITIZATION (REGRESSION TESTS)
    # -----------------------------------------------------------------------

    def test_35_cleared_category_all_and_empty_string_returns_records(self):
        # Case insensitive 'All', 'all', and empty string must not filter out records
        res_all_upper = self.client.get(self.url_list, {'category': 'ALL'})
        self.assertEqual(res_all_upper.data['count'], 1)

        res_all_lower = self.client.get(self.url_list, {'category': 'all'})
        self.assertEqual(res_all_lower.data['count'], 1)

        res_all_mixed = self.client.get(self.url_list, {'category': 'All'})
        self.assertEqual(res_all_mixed.data['count'], 1)

        res_empty = self.client.get(self.url_list, {'category': ''})
        self.assertEqual(res_empty.data['count'], 1)

    def test_36_has_80g_false_or_empty_does_not_exclude_80g_approved_ngos(self):
        # When 80G filter is unchecked or cleared ('false', '0', ''), 80G approved NGOs must NOT be excluded
        res_false = self.client.get(self.url_list, {'has_80g': 'false'})
        self.assertEqual(res_false.data['count'], 1)

        res_zero = self.client.get(self.url_list, {'has_80g': '0'})
        self.assertEqual(res_zero.data['count'], 1)

        res_empty = self.client.get(self.url_list, {'has_80g': ''})
        self.assertEqual(res_empty.data['count'], 1)

    def test_37_has_fcra_and_12a_false_or_empty_does_not_exclude_ngos(self):
        res_fcra_false = self.client.get(self.url_list, {'has_fcra': 'false'})
        self.assertEqual(res_fcra_false.data['count'], 1)

        res_12a_false = self.client.get(self.url_list, {'has_12a': 'false'})
        self.assertEqual(res_12a_false.data['count'], 1)

    def test_38_cleared_filters_combined_returns_all_approved_ngos(self):
        res_cleared = self.client.get(self.url_list, {
            'search': '',
            'category': 'All',
            'has_80g': 'false',
            'has_fcra': 'false',
            'ordering': 'display_name',
            'page': 1,
        })
        self.assertEqual(res_cleared.status_code, status.HTTP_200_OK)
        self.assertEqual(res_cleared.data['count'], 1)
        self.assertEqual(res_cleared.data['results'][0]['display_name'], 'Vidyadeep Foundation')

    def test_39_unapproved_or_inactive_ngos_remain_strictly_excluded_when_filters_cleared(self):
        # Create unapproved pending NGO
        user_pending = make_user(email='pending_ngo@test.com', role='NGO')
        ngo_pending = make_ngo_profile(user=user_pending, legal_name='Pending NGO')
        NGOProfile.objects.filter(pk=ngo_pending.pk).update(status='PENDING_VERIFICATION', is_active=True)

        res = self.client.get(self.url_list, {
            'search': '',
            'category': 'All',
            'has_80g': '',
            'ordering': 'display_name',
        })
        self.assertEqual(res.data['count'], 1)
        ids = [item['id'] for item in res.data['results']]
        self.assertNotIn(str(ngo_pending.pk), ids)
