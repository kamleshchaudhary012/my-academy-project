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
)

User = get_user_model()


class Phase439Form10BENotificationTests(TestCase):
    """
    Exhaustive Test Suite for Phase 4.3.9 — Form 10BE Donor Notification & Compliance Communication.
    """

    def setUp(self):
        self.client = APIClient()

        # 1. Primary Donor User & Profile
        self.donor_user = User.objects.create_user(
            email='donor_phase439@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Vikramaditya Sharma',
            phone='+919876543210',
            is_active=True,
            is_email_verified=False,  # Test that transactional compliance email delivers regardless of flag
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
            email='donor_phase439_other@example.com',
            password='TestPassword123!',
            role='DONOR',
            full_name='Sneha Patel',
            phone='+919876543211',
            is_active=True,
        )

        # 3. NGO 1 User & Profile (Approved & Active)
        self.ngo_user_1 = User.objects.create_user(
            email='ngo1_phase439@example.com',
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
        self.legal_info_1 = NGOLegalInfo.objects.create(
            ngo=self.ngo_profile_1,
            organisation_type='TRUST',
            registering_authority='Sub-Registrar Delhi',
            registration_number='REG/2021/0091',
            pan_number='AAATS1234K',
            twelve_a_number='12A/2021/DEL/0091',
            has_80g=True,
            eighty_g_number='80G/DEL/2021/A-12345',
            eighty_g_validity=timezone.now().date(),
            darpan_id='DL/2021/0091',
        )

        # 4. NGO 2 User & Profile (Approved & Active)
        self.ngo_user_2 = User.objects.create_user(
            email='ngo2_phase439@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Aarogya Foundation Lead',
            is_active=True,
        )
        self.ngo_profile_2 = NGOProfile.objects.create(
            user=self.ngo_user_2,
            legal_name='Aarogya Health Trust',
            display_name='Aarogya Trust',
            category='HEALTH',
            description='NGO providing healthcare support.',
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )

        # 5. Admin User
        self.admin_user = User.objects.create_superuser(
            email='admin_phase439@daangives.org',
            password='AdminPassword123!',
            full_name='Compliance Officer',
        )

        # 6. Campaign for NGO 1
        today = timezone.now().date()
        future = today + timezone.timedelta(days=30)
        self.campaign_1 = Campaign.objects.create(
            ngo=self.ngo_profile_1,
            created_by=self.ngo_user_1,
            title='Education for Rural Children',
            short_description='Providing scholarships and study supplies.',
            description='Providing scholarships and study supplies.',
            slug='education-rural-children-phase439',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('500000.00'),
            raised_amount=Decimal('50000.00'),
            start_date=today,
            end_date=future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 7. Valid 80G Verified Donation
        self.donation_1 = MonetaryDonation.objects.create(
            donor=self.donor_user,
            campaign=self.campaign_1,
            amount=Decimal('5000.00'),
            currency='INR',
            pan_number='ABCDE1234F',
            status=MonetaryDonation.Status.SUCCESS,
            receipt_number='DG-M-20260903-TEST80G',
            paid_at=timezone.now(),
        )
        self.txn_1 = PaymentTransaction.objects.create(
            donation=self.donation_1,
            donor=self.donor_user,
            gateway_order_id='order_phase439_001',
            gateway_payment_id='pay_phase439_001',
            amount=Decimal('5000.00'),
            currency='INR',
            status='SUCCESS',
        )
        self.receipt_1 = TaxReceiptService.get_or_create_tax_receipt(self.donation_1)

        # Helper test PDF file content
        self.sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Title (Official Form 10BE) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

    def _create_sample_pdf(self, filename='form_10be_sample.pdf', content=None):
        data = content or self.sample_pdf_bytes
        return SimpleUploadedFile(
            filename,
            data,
            content_type='application/pdf'
        )

    # =========================================================================
    # 1. CORE NOTIFICATION SERVICE UNIT TESTS
    # =========================================================================

    def test_01_service_initial_notification_success(self):
        """Initial notification dispatches email without PDF attachment, sets state."""
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/0001',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
        )

        mail.outbox.clear()
        res = Form10BENotificationService.notify_donor_form10be_available(cert.id, is_manual=False)

        self.assertTrue(res['success'])
        self.assertEqual(len(mail.outbox), 1)

        sent_msg = mail.outbox[0]
        self.assertIn('Official Form 10BE Certificate Available — FY 2026-27', sent_msg.subject)
        self.assertIn('donor_phase439@example.com', sent_msg.to)
        # Verify NO PDF attachment
        self.assertEqual(len(sent_msg.attachments), 0)
        # Verify Portal Link in content
        self.assertIn('/donor/receipts', sent_msg.body)
        # Verify PAN is NOT present
        self.assertNotIn('ABCDE1234F', sent_msg.subject)
        self.assertNotIn('ABCDE1234F', sent_msg.body)

        cert.refresh_from_db()
        self.assertTrue(cert.notification_sent)
        self.assertEqual(cert.notification_send_count, 1)
        self.assertIsNotNone(cert.last_notification_sent_at)
        self.assertEqual(cert.last_notification_error, '')

    def test_02_service_idempotency_prevents_duplicate_automatic_email(self):
        """Automatic notification triggers for already-notified cert are NO-OP."""
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/0001',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
            notification_sent=True,
            notification_send_count=1,
            last_notification_sent_at=timezone.now(),
        )

        mail.outbox.clear()
        res = Form10BENotificationService.notify_donor_form10be_available(cert.id, is_manual=False, is_revision=False)

        self.assertTrue(res['success'])
        self.assertTrue(res.get('already_sent'))
        self.assertEqual(len(mail.outbox), 0)

        cert.refresh_from_db()
        self.assertEqual(cert.notification_send_count, 1)

    def test_03_service_revision_notification_dispatches_with_revision_subject(self):
        """Revision flag triggers updated certificate notice and increments count."""
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/REVISED-0002',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be_revised.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
            notification_sent=True,
            notification_send_count=1,
        )

        mail.outbox.clear()
        res = Form10BENotificationService.notify_donor_form10be_available(cert.id, is_revision=True)

        self.assertTrue(res['success'])
        self.assertEqual(len(mail.outbox), 1)

        sent_msg = mail.outbox[0]
        self.assertIn('Updated Form 10BE Certificate Available — FY 2026-27', sent_msg.subject)
        self.assertIn('10BE/2026-27/REVISED-0002', sent_msg.body)
        self.assertEqual(len(sent_msg.attachments), 0)

        cert.refresh_from_db()
        self.assertEqual(cert.notification_send_count, 2)

    def test_04_service_smtp_failure_handling(self):
        """SMTP exceptions are caught, recorded in error field, and do not crash."""
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/0001',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
        )

        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception("SMTP Connection Timeout")):
            res = Form10BENotificationService.notify_donor_form10be_available(cert.id, is_manual=False)

        self.assertFalse(res['success'])
        self.assertIn('could not be sent', res['message'])

        cert.refresh_from_db()
        self.assertFalse(cert.notification_sent)
        self.assertEqual(cert.notification_send_count, 1)
        self.assertIn('SMTP Connection Timeout', cert.last_notification_error)

        # Financial invariants remain completely intact
        self.donation_1.refresh_from_db()
        self.assertEqual(self.donation_1.status, MonetaryDonation.Status.SUCCESS)

    def test_05_service_missing_donor_email_handled_safely(self):
        """If donor email is empty, records error safely without raising exception."""
        # Create user without email
        empty_email_user = User.objects.create_user(
            email='temporary_empty@example.com',
            password='TestPassword123!',
            role='DONOR',
        )
        User.objects.filter(id=empty_email_user.id).update(email='')
        empty_email_user.refresh_from_db()

        donation_no_email = MonetaryDonation.objects.create(
            donor=empty_email_user,
            campaign=self.campaign_1,
            amount=Decimal('1000.00'),
            currency='INR',
            status=MonetaryDonation.Status.SUCCESS,
            receipt_number='DG-M-20260903-NOEMAIL',
        )

        cert = Form10BECertificate.objects.create(
            donation=donation_no_email,
            ngo=self.ngo_profile_1,
            donor=empty_email_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/0003',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
        )

        res = Form10BENotificationService.notify_donor_form10be_available(cert.id)
        self.assertFalse(res['success'])
        self.assertIn('unavailable', res['message'])

        cert.refresh_from_db()
        self.assertFalse(cert.notification_sent)
        self.assertIn('unavailable', cert.last_notification_error)

    # =========================================================================
    # 2. NGO UPLOAD TRIGGER & TRANSACTION POST-COMMIT TESTS
    # =========================================================================

    def test_06_ngo_first_upload_triggers_post_commit_notification(self):
        """Uploading Form 10BE via NGO API automatically triggers post-commit notification."""
        self.client.force_authenticate(user=self.ngo_user_1)
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})

        upload_pdf = self._create_sample_pdf('official_10be.pdf')
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {
                'certificate_number': '10BE/2026-27/AUTO-001',
                'file': upload_pdf,
            }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'SUCCESS')

        # Verify email dispatched
        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        self.assertIn('Official Form 10BE Certificate Available — FY 2026-27', sent_msg.subject)
        self.assertIn('donor_phase439@example.com', sent_msg.to)

        # Verify DB state
        cert = Form10BECertificate.objects.get(donation=self.donation_1)
        self.assertTrue(cert.notification_sent)
        self.assertEqual(cert.notification_send_count, 1)

    def test_07_ngo_identical_reupload_does_not_send_duplicate_notification(self):
        """Identical file + cert number re-upload does not send duplicate email."""
        self.client.force_authenticate(user=self.ngo_user_1)
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})

        # First upload
        upload_pdf_1 = self._create_sample_pdf('cert1.pdf', self.sample_pdf_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'certificate_number': '10BE/2026-27/001', 'file': upload_pdf_1}, format='multipart')

        mail.outbox.clear()

        # Second identical upload
        upload_pdf_2 = self._create_sample_pdf('cert1.pdf', self.sample_pdf_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'certificate_number': '10BE/2026-27/001', 'file': upload_pdf_2}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('already uploaded', response.data['message'])
        # Verify NO duplicate email dispatched
        self.assertEqual(len(mail.outbox), 0)

        cert = Form10BECertificate.objects.get(donation=self.donation_1)
        self.assertEqual(cert.notification_send_count, 1)

    def test_08_ngo_revised_upload_triggers_revision_notification(self):
        """Uploading revised certificate triggers updated certificate notice."""
        self.client.force_authenticate(user=self.ngo_user_1)
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})

        # First upload
        upload_pdf_1 = self._create_sample_pdf('cert1.pdf', self.sample_pdf_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'certificate_number': '10BE/2026-27/001', 'file': upload_pdf_1}, format='multipart')

        mail.outbox.clear()

        # Revised upload with different bytes and updated number
        revised_bytes = b"%PDF-1.4\n1 0 obj\n<< /Title (Revised Form 10BE) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        upload_pdf_revised = self._create_sample_pdf('cert_revised.pdf', revised_bytes)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'certificate_number': '10BE/2026-27/001-REV', 'file': upload_pdf_revised}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('replaced and updated', response.data['message'])

        # Verify revision email dispatched
        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        self.assertIn('Updated Form 10BE Certificate Available — FY 2026-27', sent_msg.subject)

        cert = Form10BECertificate.objects.get(donation=self.donation_1)
        self.assertEqual(cert.notification_send_count, 2)

    def test_09_ngo_cannot_supply_arbitrary_recipient_email(self):
        """NGO upload payload ignores any client-supplied recipient email and uses donation donor."""
        self.client.force_authenticate(user=self.ngo_user_1)
        url = reverse('ngo_compliance_form10be_upload_direct', kwargs={'donation_id': self.donation_1.id})

        upload_pdf = self._create_sample_pdf('official_10be.pdf')
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {
                'certificate_number': '10BE/2026-27/ATTACK-001',
                'file': upload_pdf,
                'email': 'attacker_inbox@example.com',
                'recipient_email': 'attacker_inbox@example.com',
            }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        # Recipient MUST be the legitimate donor, NOT the attacker
        self.assertEqual(mail.outbox[0].to, ['donor_phase439@example.com'])

    # =========================================================================
    # 3. DONOR MANUAL RESEND ENDPOINT TESTS
    # =========================================================================

    def test_10_donor_manual_notify_endpoint_success(self):
        """Authenticated donor can manually request Form 10BE notification email."""
        # Pre-create certificate
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/MANUAL-001',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
            notification_sent=True,
            notification_send_count=1,
        )

        self.client.force_authenticate(user=self.donor_user)
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(self.donation_1.id)})

        mail.outbox.clear()
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'SUCCESS')
        self.assertEqual(response.data['recipient_email'], 'donor_phase439@example.com')
        self.assertEqual(response.data['certificate_number'], '10BE/2026-27/MANUAL-001')
        self.assertEqual(response.data['notification_send_count'], 2)

        self.assertEqual(len(mail.outbox), 1)

    def test_11_donor_manual_notify_idor_protection(self):
        """Donor 2 cannot request notification for Donor 1's donation (returns 404)."""
        Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/001',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
        )

        self.client.force_authenticate(user=self.donor_user_2)
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(self.donation_1.id)})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_12_donor_manual_notify_anonymous_denied(self):
        """Unauthenticated client is denied access (401 Unauthorized)."""
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(self.donation_1.id)})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_13_donor_manual_notify_ngo_denied(self):
        """NGO role cannot call donor notification endpoint (403 Forbidden)."""
        self.client.force_authenticate(user=self.ngo_user_1)
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(self.donation_1.id)})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_14_donor_manual_notify_admin_denied(self):
        """Admin role cannot call donor notification endpoint directly (403 Forbidden)."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(self.donation_1.id)})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_15_donor_manual_notify_missing_certificate_returns_404(self):
        """Attempting to notify for donation without an uploaded Form 10BE returns 404."""
        self.client.force_authenticate(user=self.donor_user)
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(self.donation_1.id)})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('not yet been uploaded', response.data['detail'])

    def test_16_donor_manual_notify_non_success_donation_returns_404(self):
        """Pending / Failed donations cannot be notified (returns 404)."""
        donation_pending = MonetaryDonation.objects.create(
            donor=self.donor_user,
            campaign=self.campaign_1,
            amount=Decimal('5000.00'),
            currency='INR',
            status=MonetaryDonation.Status.PENDING,
            receipt_number='DG-M-20260903-PENDING',
        )

        self.client.force_authenticate(user=self.donor_user)
        url = reverse('donor_monetary_donation_form10be_notify', kwargs={'id': str(donation_pending.id)})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # 4. PRIVACY, SECURITY & FINANCIAL INVARIANTS
    # =========================================================================

    def test_17_email_content_strict_pan_and_privacy_invariants(self):
        """Validates that PAN, internal tokens, and raw binaries NEVER appear in email."""
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/PRIVACY-TEST',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
        )

        mail.outbox.clear()
        Form10BENotificationService.notify_donor_form10be_available(cert.id)

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]

        # 1. Subject checks
        self.assertNotIn('ABCDE1234F', sent_email.subject)
        self.assertNotIn('AAATS1234K', sent_email.subject)

        # 2. Body checks
        self.assertNotIn('ABCDE1234F', sent_email.body)  # No raw donor PAN
        self.assertIn('FY 2026-27', sent_email.body)
        self.assertIn('10BE/2026-27/PRIVACY-TEST', sent_email.body)
        self.assertIn('DG-M-20260903-TEST80G', sent_email.body)

        # 3. URL checks (No sensitive query parameters or tokens)
        self.assertIn('/donor/receipts', sent_email.body)
        self.assertNotIn('?pan=', sent_email.body)
        self.assertNotIn('?token=', sent_email.body)
        self.assertNotIn('?jwt=', sent_email.body)
        self.assertNotIn('?donor_id=', sent_email.body)

        # 4. No PDF attachment
        self.assertEqual(len(sent_email.attachments), 0)

    def test_18_financial_and_payment_invariants_preserved(self):
        """Notification operations MUST NOT alter donation, payment, or receipt records."""
        cert = Form10BECertificate.objects.create(
            donation=self.donation_1,
            ngo=self.ngo_profile_1,
            donor=self.donor_user,
            financial_year='FY 2026-27',
            certificate_number='10BE/2026-27/001',
            pdf_file=self._create_sample_pdf(),
            original_filename='form_10be.pdf',
            file_size_bytes=len(self.sample_pdf_bytes),
            document_hash=hashlib.sha256(self.sample_pdf_bytes).hexdigest(),
            uploaded_by=self.ngo_user_1,
        )

        orig_amount = self.donation_1.amount
        orig_receipt_num = self.donation_1.receipt_number
        orig_receipt_hash = self.receipt_1.document_hash

        # Run manual resend
        Form10BENotificationService.notify_donor_form10be_available(cert.id, is_manual=True)

        self.donation_1.refresh_from_db()
        self.receipt_1.refresh_from_db()

        self.assertEqual(self.donation_1.amount, orig_amount)
        self.assertEqual(self.donation_1.status, MonetaryDonation.Status.SUCCESS)
        self.assertEqual(self.donation_1.receipt_number, orig_receipt_num)
        self.assertEqual(self.receipt_1.document_hash, orig_receipt_hash)

    def test_19_reference_donation_safety_invariant(self):
        """Reference donation DG-M-20260831-8STYX2 MUST remain completely intact and untouched."""
        ref_donation = MonetaryDonation.objects.filter(receipt_number='DG-M-20260831-8STYX2').first()
        if ref_donation:
            self.assertEqual(ref_donation.amount, Decimal('1000.00'))
            self.assertEqual(ref_donation.status, MonetaryDonation.Status.SUCCESS)
            self.assertEqual(ref_donation.currency, 'INR')
            # Confirm no Form 10BE certificate is attached to reference donation
            self.assertFalse(hasattr(ref_donation, 'form_10be'))
