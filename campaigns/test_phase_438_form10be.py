import os
import io
import hashlib
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from users.models import DonorProfile
from ngo.models import NGOProfile, NGOLegalInfo, NGOAddress
from campaigns.models import (
    Campaign,
    MonetaryDonation,
    PaymentTransaction,
    TaxReceiptRecord,
    Form10BECertificate,
)
from campaigns.tax_receipt_service import TaxReceiptService

User = get_user_model()


class Phase438Form10BETests(TestCase):
    """
    Exhaustive Test Suite for Phase 4.3.8 — Form 10BE Official Certificate Management.
    """

    def setUp(self):
        self.client = APIClient()

        # 1. Primary Donor User & Profile
        self.donor_user = User.objects.create_user(
            email='donor_phase438@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Vikramaditya Sharma',
            phone='+919876543210',
            is_active=True,
        )
        self.donor_profile = DonorProfile.objects.create(
            user=self.donor_user,
            entity_type='INDIVIDUAL',
            pan_number='ABCDE1234F',
            address_line1='Flat 402, Golden Palms',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            country='India',
        )

        # 2. Secondary Donor User (for IDOR attack tests)
        self.donor_user_2 = User.objects.create_user(
            email='donor_phase438_other@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Sneha Patel',
            phone='+919876543211',
            is_active=True,
        )

        # 3. NGO 1 User & Profile (Approved & Active)
        self.ngo_user_1 = User.objects.create_user(
            email='ngo1_phase438@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Seva Foundation Lead',
            is_active=True,
        )
        self.ngo_profile_1 = NGOProfile.objects.create(
            user=self.ngo_user_1,
            legal_name='Seva Child Welfare Trust',
            display_name='Seva Trust',
            category='EDUCATION',
            description='NGO providing education support to children in need.',
            year_established=2015,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal_1 = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_1,
            organisation_type='TRUST',
            registering_authority='Sub-Registrar Delhi',
            registration_number='REG/2021/0091',
            pan_number='AAATS1234K',
            twelve_a_number='12A/2021/DEL/0091',
            has_80g=True,
            eighty_g_number='80G/2021/DEL/0091',
            eighty_g_validity=timezone.now().date(),
            darpan_id='DL/2021/0091',
        )

        # 4. NGO 2 User & Profile (Separate tenant for cross-NGO IDOR tests)
        self.ngo_user_2 = User.objects.create_user(
            email='ngo2_phase438@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Udaan Care Lead',
            is_active=True,
        )
        self.ngo_profile_2 = NGOProfile.objects.create(
            user=self.ngo_user_2,
            legal_name='Udaan Education Society',
            display_name='Udaan Society',
            category='HEALTH',
            description='Society dedicated to health and social services.',
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal_2 = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_2,
            organisation_type='SOCIETY',
            registering_authority='Registrar of Societies Mumbai',
            registration_number='REG/2022/0045',
            pan_number='BBBTU5678L',
            twelve_a_number='12A/2022/MUM/0045',
            has_80g=True,
            eighty_g_number='80G/2022/MUM/0045',
            eighty_g_validity=timezone.now().date(),
            darpan_id='MH/2022/0045',
        )
        self.ngo_profile_1 = NGOProfile.objects.select_related('legal_info').get(id=self.ngo_profile_1.id)
        self.ngo_profile_2 = NGOProfile.objects.select_related('legal_info').get(id=self.ngo_profile_2.id)

        # 5. Platform Admin User
        self.admin_user = User.objects.create_user(
            email='admin_phase438@example.com',
            password='TestPassword123!',
            role='ADMIN',
            is_staff=True,
            is_active=True,
        )

        self.today = timezone.now().date()
        import datetime
        self.future = self.today + datetime.timedelta(days=30)

        # 6. Active Monetary Campaign for NGO 1
        self.campaign_1 = Campaign.objects.create(
            ngo=self.ngo_profile_1,
            created_by=self.ngo_user_1,
            title='Educate 100 Children in Need',
            short_description='Providing books and uniforms',
            description='Detailed initiative providing schooling and meals for underprivileged children.',
            slug='educate-100-children-in-need-phase438',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('500000.00'),
            raised_amount=Decimal('5000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 7. Successful 80G Monetary Donation
        self.donation_1 = MonetaryDonation.objects.create(
            donor=self.donor_user,
            campaign=self.campaign_1,
            amount=Decimal('5000.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            receipt_number='DG-M-20260902-TEST80G',
            pan_number='ABCDE1234F',
            paid_at=timezone.now(),
        )
        self.txn_1 = PaymentTransaction.objects.create(
            donation=self.donation_1,
            donor=self.donor_user,
            gateway_order_id='order_phase438_001',
            gateway_payment_id='pay_phase438_001',
            amount=Decimal('5000.00'),
            currency='INR',
            status='SUCCESS',
        )
        self.receipt_1 = TaxReceiptService.get_or_create_tax_receipt(self.donation_1)

        # Valid Sample PDF File binary with %PDF- header
        self.valid_pdf_content = b'%PDF-1.4\n1 0 obj\n<< /Title (Official Form 10BE Certificate) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF'

    def _create_sample_pdf(self, name='Form10BE_Sample.pdf', content=None):
        data = content if content is not None else self.valid_pdf_content
        return SimpleUploadedFile(name, data, content_type='application/pdf')

    # =========================================================================
    # 1. NGO UPLOAD TESTS
    # =========================================================================

    def test_01_valid_ngo_upload_succeeds(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})

        res = self.client.post(url, {
            'certificate_number': '10BE/2026-27/0001',
            'file': pdf_file,
        }, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['status'], 'SUCCESS')
        self.assertEqual(res.data['certificate']['certificate_number'], '10BE/2026-27/0001')

        # Check DB Record
        cert = Form10BECertificate.objects.get(donation=self.donation_1)
        self.assertEqual(cert.certificate_number, '10BE/2026-27/0001')
        self.assertEqual(cert.ngo, self.ngo_profile_1)
        self.assertEqual(cert.donor, self.donor_user)
        self.assertEqual(cert.financial_year, self.receipt_1.financial_year)
        self.assertEqual(cert.document_hash, hashlib.sha256(self.valid_pdf_content).hexdigest())
        self.assertTrue(cert.is_active)

    def test_02_unauthenticated_upload_denied(self):
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': pdf_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_03_donor_cannot_upload_form10be(self):
        self.client.force_authenticate(user=self.donor_user)
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': pdf_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_04_ngo_cannot_upload_for_other_ngo_donation(self):
        # NGO 2 attempts to upload certificate for NGO 1's donation
        self.client.force_authenticate(user=self.ngo_user_2)
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': pdf_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_05_pending_or_failed_donation_cannot_receive_form10be(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        pending_donation = MonetaryDonation.objects.create(
            donor=self.donor_user,
            campaign=self.campaign_1,
            amount=Decimal('1000.00'),
            status=MonetaryDonation.Status.PENDING,
            receipt_number='DG-M-PENDING-001',
        )
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': pending_donation.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': pdf_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('successfully completed donations', res.data['detail'])

    def test_06_non_80g_standard_donation_cannot_receive_form10be(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        # Create standard non-80G donation (no PAN provided, standard receipt)
        std_donation = MonetaryDonation.objects.create(
            donor=self.donor_user,
            campaign=self.campaign_1,
            amount=Decimal('1000.00'),
            status=MonetaryDonation.Status.SUCCESS,
            receipt_number='DG-M-STANDARD-001',
            pan_number='',  # No PAN
            paid_at=timezone.now(),
        )
        TaxReceiptRecord.objects.create(
            donation=std_donation,
            receipt_type=TaxReceiptRecord.ReceiptType.STANDARD,
            receipt_number='DG-M-STANDARD-001',
            financial_year='FY 2026-27',
            amount=Decimal('1000.00'),
            amount_in_words='One Thousand Rupees Only',
            donor_name_snapshot='Vikramaditya Sharma',
            donor_email_snapshot='donor_phase438@example.com',
            ngo_legal_name_snapshot='Seva Child Welfare Trust',
            ngo_pan_snapshot='AAATS1234K',
        )
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': std_donation.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': pdf_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Section 80G tax-exempt donations', res.data['detail'])

    # =========================================================================
    # 2. FILE VALIDATION & INTEGRITY TESTS
    # =========================================================================

    def test_07_upload_rejects_non_pdf_file_jpg(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        fake_jpg = SimpleUploadedFile('certificate.jpg', b'\xff\xd8\xff\xe0\x00\x10JFIF', content_type='image/jpeg')
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': fake_jpg}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', res.data)

    def test_08_upload_rejects_fake_pdf_wrong_magic_bytes(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        fake_pdf = SimpleUploadedFile('certificate.pdf', b'NOT_A_REAL_PDF_HEADER_CONTENT', content_type='application/pdf')
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': fake_pdf}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', res.data)

    def test_09_upload_rejects_oversized_file(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        # Create file > 5 MB
        big_content = b'%PDF-1.4\n' + (b'0' * (5 * 1024 * 1024 + 100))
        big_pdf = SimpleUploadedFile('large_cert.pdf', big_content, content_type='application/pdf')
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '10BE/2026/001', 'file': big_pdf}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', res.data)

    def test_10_certificate_number_required_and_validated(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf_file = self._create_sample_pdf()
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.post(url, {'certificate_number': '   ', 'file': pdf_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('certificate_number', res.data)

    # =========================================================================
    # 3. RE-UPLOAD & REPLACEMENT TESTS
    # =========================================================================

    def test_11_reupload_replaces_existing_certificate_idempotently(self):
        self.client.force_authenticate(user=self.ngo_user_1)
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})

        # Upload 1
        pdf_1 = self._create_sample_pdf('initial.pdf', b'%PDF-1.4\nInitial Certificate Content\n%%EOF')
        res1 = self.client.post(url, {'certificate_number': '10BE/OLD/001', 'file': pdf_1}, format='multipart')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Upload 2 (Replacement / Correction)
        pdf_2_content = b'%PDF-1.4\nCorrected Certificate Revised Statement\n%%EOF'
        pdf_2 = self._create_sample_pdf('corrected.pdf', pdf_2_content)
        res2 = self.client.post(url, {'certificate_number': '10BE/REVISED/002', 'file': pdf_2}, format='multipart')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['certificate']['certificate_number'], '10BE/REVISED/002')

        # Check only 1 active record exists for this donation
        certs = Form10BECertificate.objects.filter(donation=self.donation_1)
        self.assertEqual(certs.count(), 1)
        cert = certs.first()
        self.assertEqual(cert.certificate_number, '10BE/REVISED/002')
        self.assertEqual(cert.document_hash, hashlib.sha256(pdf_2_content).hexdigest())

    # =========================================================================
    # 4. DONOR DOWNLOAD & IDOR DEFENSE TESTS
    # =========================================================================

    def test_12_donor_can_download_own_certificate_with_secure_headers(self):
        # 1. Upload certificate
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/2026/0088', 'file': pdf}, format='multipart')

        # 2. Donor requests download
        self.client.force_authenticate(user=self.donor_user)
        download_url = reverse('donor_monetary_donation_form10be', kwargs={'id': self.donation_1.id})
        res = self.client.get(download_url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('attachment; filename="DaanGives_Form10BE_10BE_2026_0088.pdf"', res['Content-Disposition'])
        self.assertIn('private, no-store, no-cache, must-revalidate', res['Cache-Control'])
        self.assertEqual(res['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(res['Pragma'], 'no-cache')
        self.assertEqual(res.content, self.valid_pdf_content)

        # Audit metric incremented
        cert = Form10BECertificate.objects.get(donation=self.donation_1)
        self.assertEqual(cert.download_count, 1)
        self.assertIsNotNone(cert.last_downloaded_at)

    def test_13_donor_cannot_download_another_donor_certificate(self):
        # Upload certificate for Donor 1
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/2026/0088', 'file': pdf}, format='multipart')

        # Donor 2 attempts to download Donor 1's certificate
        self.client.force_authenticate(user=self.donor_user_2)
        download_url = reverse('donor_monetary_donation_form10be', kwargs={'id': self.donation_1.id})
        res = self.client.get(download_url)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        # Verify download count did not increment
        cert = Form10BECertificate.objects.get(donation=self.donation_1)
        self.assertEqual(cert.download_count, 0)

    def test_14_anonymous_user_cannot_download_certificate(self):
        download_url = reverse('donor_monetary_donation_form10be', kwargs={'id': self.donation_1.id})
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_15_missing_certificate_returns_clean_404(self):
        self.client.force_authenticate(user=self.donor_user)
        # Certificate not uploaded yet
        download_url = reverse('donor_monetary_donation_form10be', kwargs={'id': self.donation_1.id})
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('not yet been uploaded', res.data['detail'])

    # =========================================================================
    # 5. NGO & ADMIN DOWNLOAD TESTS
    # =========================================================================

    def test_16_ngo_can_download_own_certificate(self):
        # Upload certificate
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/2026/0099', 'file': pdf}, format='multipart')

        # Download by NGO 1
        download_url = reverse('ngo_compliance_form10be_download_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')

    def test_17_ngo_cannot_download_other_ngo_certificate(self):
        # Upload certificate for NGO 1
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/2026/0099', 'file': pdf}, format='multipart')

        # Attempt download by NGO 2
        self.client.force_authenticate(user=self.ngo_user_2)
        download_url = reverse('ngo_compliance_form10be_download_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_18_admin_can_download_platform_form10be(self):
        # Upload certificate for NGO 1
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/2026/0099', 'file': pdf}, format='multipart')

        # Download by Admin
        self.client.force_authenticate(user=self.admin_user)
        download_url = reverse('admin_compliance_form10be_download_direct', kwargs={'donation_id': self.donation_1.id})
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')

    # =========================================================================
    # 6. INVARIANTS & INTEGRATION TESTS
    # =========================================================================

    def test_19_monetary_serializer_includes_form10be_flags(self):
        # Before upload
        self.client.force_authenticate(user=self.donor_user)
        list_url = reverse('donor_monetary_donation_list')
        res1 = self.client.get(list_url)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        item = [d for d in res1.data if d['id'] == str(self.donation_1.id)][0]
        self.assertFalse(item['has_form_10be'])
        self.assertIsNone(item['form_10be_certificate_number'])

        # Upload certificate
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/SERIALIZER/01', 'file': pdf}, format='multipart')

        # After upload
        self.client.force_authenticate(user=self.donor_user)
        res2 = self.client.get(list_url)
        item2 = [d for d in res2.data if d['id'] == str(self.donation_1.id)][0]
        self.assertTrue(item2['has_form_10be'])
        self.assertEqual(item2['form_10be_certificate_number'], '10BE/SERIALIZER/01')

    def test_20_financial_and_payment_invariants_preserved(self):
        # Upload Form 10BE
        self.client.force_authenticate(user=self.ngo_user_1)
        pdf = self._create_sample_pdf()
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})
        self.client.post(upload_url, {'certificate_number': '10BE/INVARIANT/01', 'file': pdf}, format='multipart')

        # Verify donation and payment transactions remain strictly SUCCESS and untouched
        self.donation_1.refresh_from_db()
        self.txn_1.refresh_from_db()
        self.receipt_1.refresh_from_db()

        self.assertEqual(self.donation_1.status, MonetaryDonation.Status.SUCCESS)
        self.assertEqual(self.donation_1.amount, Decimal('5000.00'))
        self.assertEqual(self.txn_1.status, 'SUCCESS')
        self.assertEqual(self.txn_1.amount, Decimal('5000.00'))
        self.assertEqual(self.receipt_1.receipt_number, 'DG-M-20260902-TEST80G')

    def test_21_reference_donation_safety_rule(self):
        """
        Verify that reference donation DG-M-20260831-8STYX2 is 100% intact and unchanged.
        """
        ref_donation = MonetaryDonation.objects.filter(receipt_number='DG-M-20260831-8STYX2').first()
        if ref_donation:
            self.assertEqual(ref_donation.amount, Decimal('1000.00'))
            self.assertEqual(ref_donation.status, MonetaryDonation.Status.SUCCESS)
            self.assertEqual(ref_donation.campaign.title, 'test1')
            self.assertEqual(ref_donation.campaign.ngo.legal_name, 'Education trust')
            self.assertFalse(hasattr(ref_donation, 'form_10be'))
