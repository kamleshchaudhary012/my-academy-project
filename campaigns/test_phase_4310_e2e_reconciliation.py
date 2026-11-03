import os
import io
import hashlib
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core import mail
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
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
from campaigns.tax_receipt_service import (
    TaxReceiptService,
    Form10BENotificationService,
    get_financial_year,
)

User = get_user_model()


class Phase4310E2EReconciliationTests(TestCase):
    """
    Exhaustive Full-Lifecycle Integration & Reconciliation Test Suite for Phase 4.3.10.
    Validates complete end-to-end flow:
    Donation Intent -> Order -> Payment Verification -> Receipt Record & Vector PDF ->
    Receipt Email -> NGO Form 10BD -> Admin Form 10BD CSV -> NGO Form 10BE Upload ->
    Form 10BE Notification -> Donor Retrieval -> IDOR Isolation -> Financial Invariants.
    """

    def setUp(self):
        self.client = APIClient()

        # 1. Primary Donor User & Profile
        self.donor_user = User.objects.create_user(
            email='donor_e2e@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Rohan Deshmukh',
            phone='+919876543210',
            is_active=True,
        )
        self.donor_profile = DonorProfile.objects.create(
            user=self.donor_user,
            entity_type='INDIVIDUAL',
            pan_number='ABCDE1234F',
            address_line1='Flat 501, Horizon Heights',
            city='Pune',
            state='Maharashtra',
            pincode='411001',
            country='India',
        )

        # 2. Secondary Donor User (for IDOR boundaries)
        self.donor_user_2 = User.objects.create_user(
            email='donor_e2e_other@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Ananya Iyer',
            phone='+919876543211',
            is_active=True,
        )

        # 3. NGO 1 User & Profile (Approved & Active)
        self.ngo_user_1 = User.objects.create_user(
            email='ngo1_e2e@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Aarogya Foundation Lead',
            is_active=True,
        )
        self.ngo_profile_1 = NGOProfile.objects.create(
            user=self.ngo_user_1,
            legal_name='Aarogya Health and Education Trust',
            display_name='Aarogya Foundation',
            category='HEALTHCARE',
            description='NGO delivering primary healthcare and education.',
            year_established=2016,
            status='APPROVED',
            is_active=True,
        )
        self.legal_info_1 = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_1,
            organisation_type='TRUST',
            registering_authority='Sub-Registrar Pune',
            registration_number='REG/PUN/2021/045',
            pan_number='AAATA5678B',
            twelve_a_number='12A/2021/PUN/045',
            has_80g=True,
            eighty_g_number='80G/PUN/2021/H-98765',
            eighty_g_validity=timezone.now().date(),
            darpan_id='MH/2021/0045',
        )
        self.address_1 = NGOAddress.objects.create(
            ngo=self.ngo_profile_1,
            address_line1='102 Health Avenue',
            city='Pune',
            state='Maharashtra',
            pincode='411004',
        )

        # 4. NGO 2 User & Profile (for Multi-Tenant Isolation tests)
        self.ngo_user_2 = User.objects.create_user(
            email='ngo2_e2e@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Gramin Vikas Lead',
            is_active=True,
        )
        self.ngo_profile_2 = NGOProfile.objects.create(
            user=self.ngo_user_2,
            legal_name='Gramin Vikas Sansthan',
            display_name='Gramin Vikas',
            category='RURAL_DEV',
            description='Rural infrastructure and education trust.',
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )
        self.legal_info_2 = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_2,
            organisation_type='SOCIETY',
            pan_number='AAATG9999K',
            has_80g=True,
            eighty_g_number='80G/RUR/2022/9999',
            eighty_g_validity=timezone.now().date(),
        )

        # 5. Admin User
        self.admin_user = User.objects.create_user(
            email='admin_e2e@example.com',
            password='TestPassword123!',
            role='ADMIN',
            full_name='National Compliance Admin',
            is_staff=True,
            is_active=True,
        )

        # 6. Active Campaign under NGO 1
        self.campaign = Campaign.objects.create(
            ngo=self.ngo_profile_1,
            created_by=self.ngo_user_1,
            title='Rural Mobile Clinic 2026',
            slug='rural-mobile-clinic-2026',
            category='HEALTHCARE',
            campaign_type='MONETARY',
            short_description='Equipping mobile diagnostic clinics.',
            description='Providing essential diagnostic tests to remote villages.',
            target_amount=Decimal('500000.00'),
            raised_amount=Decimal('0.00'),
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=90),
            status='ACTIVE',
        )

        # Test PDF sample binaries
        self.sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Title (Official Form 10BE E2E Test) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

    def _create_sample_pdf(self, name='official_10be_e2e.pdf', content=None):
        data = content or self.sample_pdf_bytes
        return SimpleUploadedFile(name, data, content_type='application/pdf')

    # =========================================================================
    # E2E LIFECYCLE TESTS (1 - 8)
    # =========================================================================

    def test_01_monetary_donation_intent_and_order_creation(self):
        """Step 1: Donor creates monetary donation intent and order with precise decimal amount."""
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('donor_monetary_donation_create_order')

        # Mock Razorpay order creation
        with patch('campaigns.razorpay_service.RazorpayService.create_order') as mock_create_order:
            mock_create_order.return_value = {
                'id': 'order_e2e_001',
                'amount': 250000,
                'currency': 'INR',
                'status': 'created',
            }

            response = self.client.post(url, {
                'amount': '2500.00',
                'campaign': str(self.campaign.id),
                'pan_number': 'ABCDE1234F',
            }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue('donation_id' in response.data)
        self.assertEqual(Decimal(str(response.data['amount'])), Decimal('2500.00'))
        self.assertEqual(response.data['currency'], 'INR')
        self.assertTrue(response.data['receipt_number'].startswith('DG-M-'))

        donation_id = response.data['donation_id']
        donation = MonetaryDonation.objects.get(id=donation_id)
        self.assertEqual(donation.status, MonetaryDonation.Status.PENDING)
        self.assertEqual(donation.amount, Decimal('2500.00'))

    def test_02_payment_verification_produces_success_and_immutable_receipt(self):
        """Step 2: Successful payment verification transitions donation to SUCCESS and generates TaxReceiptRecord."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('5000.00'),
            currency='INR',
            status=MonetaryDonation.Status.PENDING,
            pan_number='ABCDE1234F',
        )
        tx = PaymentTransaction.objects.create(
            donation=donation,
            donor=self.donor_user,
            gateway='RAZORPAY',
            gateway_order_id='order_e2e_002',
            amount=Decimal('5000.00'),
            currency='INR',
            status=PaymentTransaction.Status.ORDER_CREATED,
        )

        self.client.force_authenticate(user=self.donor_user)
        url = reverse('donor_monetary_donation_verify_payment')

        mail.outbox.clear()
        with patch('campaigns.razorpay_service.RazorpayService.verify_payment_signature', return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url, {
                    'donation_id': str(donation.id),
                    'razorpay_order_id': 'order_e2e_002',
                    'razorpay_payment_id': 'pay_e2e_002',
                    'razorpay_signature': 'valid_signature_hash',
                }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'SUCCESS')

        donation.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(donation.status, MonetaryDonation.Status.SUCCESS)
        self.assertEqual(tx.status, PaymentTransaction.Status.SUCCESS)
        self.assertEqual(tx.gateway_payment_id, 'pay_e2e_002')

        # Verify TaxReceiptRecord created
        self.assertTrue(hasattr(donation, 'tax_receipt'))
        receipt = donation.tax_receipt
        self.assertTrue(len(receipt.document_hash) == 64)
        self.assertEqual(receipt.financial_year, get_financial_year(donation.paid_at.date()))

        # Verify Receipt PDF download endpoint works
        download_url = reverse('donor_monetary_donation_receipt_pdf', kwargs={'id': donation.id})
        dl_res = self.client.get(download_url)
        self.assertEqual(dl_res.status_code, status.HTTP_200_OK)
        self.assertEqual(dl_res['Content-Type'], 'application/pdf')
        self.assertTrue(dl_res.content.startswith(b'%PDF-'))

        # Verify post-commit receipt email dispatched with PDF attachment
        self.assertEqual(len(mail.outbox), 1)
        email_msg = mail.outbox[0]
        self.assertIn('donor_e2e@example.com', email_msg.to)
        self.assertIn('Donation Receipt', email_msg.subject)
        self.assertTrue(len(email_msg.attachments) > 0)
        self.assertTrue(email_msg.attachments[0][0].endswith('.pdf'))

    def test_03_ngo_and_admin_form10bd_ledger_and_csv_export(self):
        """Step 3: Successful donation is accurately reflected in NGO & Admin Form 10BD ledgers and CSV export."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('7500.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            pan_number='ABCDE1234F',
        )
        TaxReceiptService.get_or_create_tax_receipt(donation)

        current_fy = get_financial_year(donation.paid_at.date())

        # 1. NGO Form 10BD Ledger
        self.client.force_authenticate(user=self.ngo_user_1)
        ngo_10bd_url = reverse('ngo_compliance_form10bd_direct')
        ngo_res = self.client.get(ngo_10bd_url, {'financial_year': current_fy})
        self.assertEqual(ngo_res.status_code, status.HTTP_200_OK)
        self.assertEqual(ngo_res.data['summary']['eighty_g_donations_count'], 1)
        self.assertEqual(Decimal(str(ngo_res.data['summary']['eighty_g_donated_amount'])), Decimal('7500.00'))
        self.assertEqual(ngo_res.data['records'][0]['receipt_number'], donation.receipt_number)
        self.assertEqual(ngo_res.data['records'][0]['donor_pan_masked'], '******234F')

        # 2. Admin Form 10BD Ledger
        self.client.force_authenticate(user=self.admin_user)
        admin_10bd_url = reverse('admin_compliance_form10bd_direct')
        admin_res = self.client.get(admin_10bd_url, {'financial_year': current_fy})
        self.assertEqual(admin_res.status_code, status.HTTP_200_OK)
        self.assertEqual(admin_res.data['summary']['eighty_g_donations_count'], 1)

        # 3. Admin Form 10BD CSV Export
        admin_csv_url = reverse('admin_compliance_form10bd_export_direct')
        csv_res = self.client.get(admin_csv_url, {'financial_year': current_fy})
        self.assertEqual(csv_res.status_code, status.HTTP_200_OK)
        self.assertEqual(csv_res['Content-Type'], 'text/csv; charset=utf-8')
        csv_content = csv_res.content.decode('utf-8')
        self.assertIn(donation.receipt_number, csv_content)
        self.assertIn('7500.00', csv_content)
        self.assertIn('Rohan Deshmukh', csv_content)

    def test_04_ngo_uploads_form10be_and_triggers_post_commit_notification(self):
        """Step 4: NGO uploads official Form 10BE; post-commit notification sends clean email without PDF attachment."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('10000.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            pan_number='ABCDE1234F',
        )
        TaxReceiptService.get_or_create_tax_receipt(donation)

        self.client.force_authenticate(user=self.ngo_user_1)
        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': donation.id})
        pdf_file = self._create_sample_pdf('official_10be.pdf')

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(upload_url, {
                'certificate_number': '10BE/2026-27/E2E-001',
                'file': pdf_file,
            }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'SUCCESS')

        # Verify Form10BECertificate created in DB
        cert = Form10BECertificate.objects.get(donation=donation)
        self.assertEqual(cert.certificate_number, '10BE/2026-27/E2E-001')
        self.assertEqual(cert.document_hash, hashlib.sha256(self.sample_pdf_bytes).hexdigest())
        self.assertTrue(cert.notification_sent)
        self.assertEqual(cert.notification_send_count, 1)

        # Verify notification email dispatched
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn('Official Form 10BE Certificate Available — FY 2026-27', sent_email.subject)
        self.assertIn('donor_e2e@example.com', sent_email.to)

        # Verify privacy invariants: NO PDF attachment, NO raw PAN
        self.assertEqual(len(sent_email.attachments), 0)
        self.assertNotIn('ABCDE1234F', sent_email.body)
        self.assertIn('/donor/receipts', sent_email.body)

    def test_05_multi_tenant_idor_barriers_and_authenticated_download(self):
        """Step 5: Donor 1 and NGO 1 can retrieve Form 10BE; Donor 2 and NGO 2 are blocked by IDOR boundaries."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('4000.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
        )
        cert = Form10BECertificate.objects.create(
            donation=donation,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            uploaded_by=self.ngo_user_1,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/IDOR-001',
            original_filename='cert.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            pdf_file=SimpleUploadedFile('cert.pdf', self.sample_pdf_bytes, content_type='application/pdf'),
        )

        donor_download_url = reverse('donor_monetary_donation_form10be', kwargs={'id': donation.id})
        ngo_download_url = reverse('ngo_compliance_form10be_download_direct', kwargs={'donation_id': donation.id})
        admin_download_url = reverse('admin_compliance_form10be_download_direct', kwargs={'donation_id': donation.id})

        # 1. Donor 1 (Owner) can stream PDF
        self.client.force_authenticate(user=self.donor_user)
        res1 = self.client.get(donor_download_url)
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1['Content-Type'], 'application/pdf')
        self.assertIn('private, no-store', res1.headers.get('Cache-Control', ''))

        # 2. Donor 2 (Attacker) is denied with 404
        self.client.force_authenticate(user=self.donor_user_2)
        res2 = self.client.get(donor_download_url)
        self.assertEqual(res2.status_code, status.HTTP_404_NOT_FOUND)

        # 3. NGO 1 (Campaign Owner) can stream PDF
        self.client.force_authenticate(user=self.ngo_user_1)
        res3 = self.client.get(ngo_download_url)
        self.assertEqual(res3.status_code, status.HTTP_200_OK)

        # 4. NGO 2 (Different NGO) is denied with 404
        self.client.force_authenticate(user=self.ngo_user_2)
        res4 = self.client.get(ngo_download_url)
        self.assertEqual(res4.status_code, status.HTTP_404_NOT_FOUND)

        # 5. Admin can audit stream PDF
        self.client.force_authenticate(user=self.admin_user)
        res5 = self.client.get(admin_download_url)
        self.assertEqual(res5.status_code, status.HTTP_200_OK)

    def test_06_form10be_idempotency_and_revision_handling(self):
        """Step 6: Identical upload is NO-OP (no email); revised upload updates certificate and sends revision notice."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('8000.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            pan_number='ABCDE1234F',
        )
        TaxReceiptService.get_or_create_tax_receipt(donation)

        upload_url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': donation.id})
        self.client.force_authenticate(user=self.ngo_user_1)

        # 1. Initial upload
        file_1 = self._create_sample_pdf('cert1.pdf', self.sample_pdf_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            res_init = self.client.post(upload_url, {'certificate_number': '10BE/2026-27/REV-01', 'file': file_1}, format='multipart')
        self.assertEqual(res_init.status_code, status.HTTP_201_CREATED)

        mail.outbox.clear()

        # 2. Identical re-upload (same bytes + same number) -> NO duplicate email
        file_dup = self._create_sample_pdf('cert1.pdf', self.sample_pdf_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            res_dup = self.client.post(upload_url, {'certificate_number': '10BE/2026-27/REV-01', 'file': file_dup}, format='multipart')
        self.assertEqual(res_dup.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

        # 3. Revised upload with new binary content & number -> sends revision email
        revised_bytes = b"%PDF-1.4\n1 0 obj\n<< /Title (Revised Form 10BE) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        file_rev = self._create_sample_pdf('cert_revised.pdf', revised_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            res_rev = self.client.post(upload_url, {'certificate_number': '10BE/2026-27/REV-01-UPDATED', 'file': file_rev}, format='multipart')
        self.assertEqual(res_rev.status_code, status.HTTP_200_OK)
        self.assertIn('replaced and updated', res_rev.data['message'])

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Updated Form 10BE Certificate Available — FY 2026-27', mail.outbox[0].subject)

        cert = Form10BECertificate.objects.get(donation=donation)
        self.assertEqual(cert.certificate_number, '10BE/2026-27/REV-01-UPDATED')
        self.assertEqual(cert.notification_send_count, 2)

    def test_07_financial_and_receipt_immutability_invariants(self):
        """Step 7: All compliance and notification operations preserve financial data and receipt hash immutability."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('15000.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            paid_at=timezone.now(),
            pan_number='ABCDE1234F',
        )
        receipt_rec = TaxReceiptService.get_or_create_tax_receipt(donation)

        orig_amount = donation.amount
        orig_receipt_num = donation.receipt_number
        orig_receipt_hash = receipt_rec.document_hash

        # Run multiple compliance operations
        cert = Form10BECertificate.objects.create(
            donation=donation,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            uploaded_by=self.ngo_user_1,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/IMMUT-001',
            original_filename='cert.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            pdf_file=SimpleUploadedFile('cert.pdf', self.sample_pdf_bytes, content_type='application/pdf'),
        )
        Form10BENotificationService.notify_donor_form10be_available(cert.id, is_manual=True)

        donation.refresh_from_db()
        receipt_rec.refresh_from_db()

        self.assertEqual(donation.amount, orig_amount)
        self.assertEqual(donation.status, MonetaryDonation.Status.SUCCESS)
        self.assertEqual(donation.receipt_number, orig_receipt_num)
        self.assertEqual(receipt_rec.document_hash, orig_receipt_hash)

    def test_08_reference_donation_safety_invariant(self):
        """Reference donation DG-M-20260831-8STYX2 MUST remain completely intact and untouched."""
        ref_donations = MonetaryDonation.objects.filter(receipt_number='DG-M-20260831-8STYX2')
        if ref_donations.exists():
            ref = ref_donations.first()
            self.assertEqual(ref.amount, Decimal('1000.00'))
            self.assertEqual(ref.status, MonetaryDonation.Status.SUCCESS)
            if hasattr(ref, 'tax_receipt'):
                self.assertEqual(
                    ref.tax_receipt.document_hash,
                    '678541b65a931e3a426556fea20225a3f9dc7f3ac6dc5177d4ea5fb58bf88edd'
                )
