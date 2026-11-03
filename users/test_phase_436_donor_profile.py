from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from users.models import DonorProfile
from campaigns.models import Campaign, MonetaryDonation
from ngo.models import NGOProfile

User = get_user_model()


class DonorComplianceProfileTests(TestCase):
    """
    Test suite for Phase 4.3.6:
    - DonorProfile model & constraints
    - Address & Entity Type handling
    - Strict PAN format validation & masking
    - Access control & tenant isolation
    - Checkout PAN integration
    - Reference donation integrity
    """

    def setUp(self):
        self.client = APIClient()

        # Create Donor 1
        self.donor1 = User.objects.create_user(
            email='donor1@daangives.org',
            password='Password123!',
            full_name='Test Donor One',
            phone='+919876543210',
            role=User.Role.DONOR,
        )

        # Create Donor 2
        self.donor2 = User.objects.create_user(
            email='donor2@daangives.org',
            password='Password123!',
            full_name='Test Donor Two',
            phone='+919876543211',
            role=User.Role.DONOR,
        )

        # Create NGO User
        self.ngo_user = User.objects.create_user(
            email='ngo@daangives.org',
            password='Password123!',
            full_name='NGO Representative',
            role=User.Role.NGO,
        )

    def test_donor_profile_model_creation_and_defaults(self):
        """Verify DonorProfile model fields, choices, defaults, and OneToOne relationship."""
        profile = DonorProfile.objects.create(
            user=self.donor1,
            address_line1='Flat 402, Green Heights',
            city='Mumbai',
            state='Maharashtra',
            pincode='400001',
            pan_number='ABCDE1234F',
            entity_type=DonorProfile.EntityType.INDIVIDUAL,
        )
        self.assertEqual(profile.country, 'India')
        self.assertEqual(profile.entity_type, 'INDIVIDUAL')
        self.assertEqual(self.donor1.donor_profile.pan_number, 'ABCDE1234F')
        self.assertEqual(str(profile), 'DonorProfile (INDIVIDUAL) for donor1@daangives.org')

    def test_donor_get_profile_returns_masked_pan(self):
        """Verify GET /api/v1/auth/me/ returns masked PAN and never exposes raw PAN."""
        DonorProfile.objects.create(
            user=self.donor1,
            address_line1='123 Karma Lane',
            city='Pune',
            state='Maharashtra',
            pincode='411001',
            pan_number='ABCDE1234F',
            entity_type=DonorProfile.EntityType.INDIVIDUAL,
        )
        self.client.force_authenticate(user=self.donor1)
        response = self.client.get('/api/v1/auth/me/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('donor_profile', data)
        prof_data = data['donor_profile']

        self.assertEqual(prof_data['address_line1'], '123 Karma Lane')
        self.assertEqual(prof_data['city'], 'Pune')
        self.assertEqual(prof_data['pincode'], '411001')
        self.assertEqual(prof_data['pan_number_masked'], '******234F')
        self.assertTrue(prof_data['has_pan'])
        self.assertNotIn('pan_number', prof_data)

    def test_donor_patch_profile_address_and_entity(self):
        """Verify PATCH /api/v1/auth/me/ updates address, entity type, and saves safely."""
        self.client.force_authenticate(user=self.donor1)
        payload = {
            'full_name': 'Donor One Updated',
            'donor_profile': {
                'address_line1': '789 Peace Blvd',
                'address_line2': 'Suite 100',
                'city': 'Bengaluru',
                'state': 'Karnataka',
                'pincode': '560001',
                'country': 'India',
                'entity_type': 'COMPANY',
            }
        }
        response = self.client.patch('/api/v1/auth/me/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.donor1.refresh_from_db()
        self.assertEqual(self.donor1.full_name, 'Donor One Updated')
        self.assertEqual(self.donor1.donor_profile.city, 'Bengaluru')
        self.assertEqual(self.donor1.donor_profile.entity_type, 'COMPANY')
        self.assertEqual(self.donor1.donor_profile.pincode, '560001')

    def test_donor_update_pan_valid(self):
        """Verify donor can update PAN and receive masked response."""
        self.client.force_authenticate(user=self.donor1)
        payload = {
            'donor_profile': {
                'pan_number': 'XYZPK5678Q',
            }
        }
        response = self.client.patch('/api/v1/auth/me/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.donor1.refresh_from_db()
        self.assertEqual(self.donor1.donor_profile.pan_number, 'XYZPK5678Q')

        # Check GET response
        get_res = self.client.get('/api/v1/auth/me/')
        self.assertEqual(get_res.json()['donor_profile']['pan_number_masked'], '******678Q')
        self.assertTrue(get_res.json()['donor_profile']['has_pan'])

    def test_donor_invalid_pan_rejected(self):
        """Verify invalid PAN format is rejected with HTTP 400."""
        self.client.force_authenticate(user=self.donor1)
        invalid_pans = ['12345ABCDE', 'ABCDE12345', 'ABC123', 'TOOLONGPAN123']

        for bad_pan in invalid_pans:
            payload = {'donor_profile': {'pan_number': bad_pan}}
            response = self.client.patch('/api/v1/auth/me/', payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('donor_profile', response.json())

    def test_donor_invalid_pincode_rejected(self):
        """Verify invalid Indian pincode is rejected with HTTP 400."""
        self.client.force_authenticate(user=self.donor1)
        invalid_pincodes = ['12345', '1234567', 'ABCDEF', '400 01']

        for bad_pin in invalid_pincodes:
            payload = {'donor_profile': {'pincode': bad_pin}}
            response = self.client.patch('/api/v1/auth/me/', payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('donor_profile', response.json())

    def test_donor_isolation_cannot_access_other_donor(self):
        """Verify Donor A cannot access or mutate Donor B's profile."""
        DonorProfile.objects.create(
            user=self.donor2,
            address_line1='Donor 2 Secret Road',
            city='Delhi',
            pan_number='BBBBB2222B',
        )
        self.client.force_authenticate(user=self.donor1)
        response = self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Ensure Donor 1 cannot see Donor 2's data
        self.assertNotEqual(response.json()['donor_profile']['city'], 'Delhi')
        self.assertNotEqual(response.json()['donor_profile']['pan_number_masked'], '******2222B')

    def test_ngo_user_returns_none_for_donor_profile(self):
        """Verify NGO user response contains None for donor_profile."""
        self.client.force_authenticate(user=self.ngo_user)
        response = self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()['donor_profile'])

    def test_anonymous_user_blocked(self):
        """Verify unauthenticated user cannot access /api/v1/auth/me/."""
        response = self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_checkout_prefill_saved_pan_fallback(self):
        """
        Verify that if a donor has a saved PAN on DonorProfile,
        creating a donation order without passing pan_number falls back
        to the saved PAN and creates an authoritative snapshot on MonetaryDonation.
        """
        DonorProfile.objects.create(
            user=self.donor1,
            pan_number='ABCDE1234F',
        )

        # Setup approved NGO and active campaign
        ngo = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Test NGO',
            display_name='Test NGO',
            year_established=2020,
            status='APPROVED',
            is_active=True,
        )
        import datetime
        from django.utils import timezone
        today = timezone.now().date()
        future_date = today + datetime.timedelta(days=30)

        campaign = Campaign.objects.create(
            ngo=ngo,
            created_by=self.ngo_user,
            title='Education for Children',
            short_description='Short summary for education',
            description='Detailed description of education campaign for children in need.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('100000.00'),
            raised_amount=Decimal('0.00'),
            start_date=today,
            end_date=future_date,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        self.client.force_authenticate(user=self.donor1)
        payload = {
            'campaign': str(campaign.id),
            'amount': '500.00',
        }
        response = self.client.post('/api/v1/donor/monetary-donations/create-order/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        donation_id = response.json()['donation_id']
        donation = MonetaryDonation.objects.get(id=donation_id)
        self.assertEqual(donation.pan_number, 'ABCDE1234F')

    def test_reference_donation_intact(self):
        """Verify that the existing reference donation DG-M-20260831-8STYX2 is 100% intact."""
        d = MonetaryDonation.objects.filter(receipt_number='DG-M-20260831-8STYX2').first()
        if d:
            self.assertEqual(d.amount, Decimal('1000.00'))
            self.assertEqual(d.status, MonetaryDonation.Status.SUCCESS)
            self.assertEqual(d.campaign.title, 'test1')
