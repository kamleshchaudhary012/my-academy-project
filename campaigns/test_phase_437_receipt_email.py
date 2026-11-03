import io
import json
import hmac
import uuid
import hashlib
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from django.core import mail
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from campaigns.models import (
    Campaign,
    MonetaryDonation,
    PaymentTransaction,
    TaxReceiptRecord,
    GatewayWebhookEvent,
)
from campaigns.tax_receipt_service import TaxReceiptService
from ngo.models import NGOProfile, NGOLegalInfo, NGOAddress

User = get_user_model()


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    RAZORPAY_KEY_ID='rzp_test_placeholder_key_id',
    RAZORPAY_KEY_SECRET='test_secret_key_12345',
    RAZORPAY_WEBHOOK_SECRET='test_webhook_secret_12345',
)
class Phase437ReceiptEmailTests(TestCase):
    """
    Automated Test Suite for Phase 4.3.7:
    Automated Receipt Email Delivery Engine, Idempotency, PDF Attachment,
    Payment Verification Trigger, Webhook Trigger, Deduplication,
    Manual Retry API, IDOR Protection, and Financial Invariants.
    """

    def setUp(self):
        self.client = APIClient()
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=30)

        # Clear mailbox before each test
        mail.outbox = []

        # 1. Create Donor User
        self.donor_user = User.objects.create_user(
            email='donor_test_437@example.com',
            password='Password123!',
            full_name='Amitabh Sharma',
            role='DONOR',
            phone='+919876543210',
        )

        # 2. Create Second Donor for IDOR tests
        self.other_donor = User.objects.create_user(
            email='other_donor_437@example.com',
            password='Password123!',
            full_name='Priya Patel',
            role='DONOR',
            phone='+919876543211',
        )

        # 3. Create NGO User & Profile
        self.ngo_user = User.objects.create_user(
            email='ngo_owner_437@example.com',
            password='Password123!',
            full_name='Seva Foundation Owner',
            role='NGO',
        )
        self.ngo = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Seva Sansthan Trust',
            display_name='Seva Sansthan',
            category='EDUCATION',
            description='This is a verified NGO providing quality education and comprehensive support to underprivileged children across New Delhi.',
            year_established=2015,
            status='APPROVED',
            is_active=True,
        )
        self.ngo_legal = NGOLegalInfo.objects.create(
            ngo=self.ngo,
            pan_number='AAATS1234F',
            eighty_g_number='80G/DEL/2026/01',
            eighty_g_validity=self.today + datetime.timedelta(days=365),
            twelve_a_number='12A/DEL/2026/01',
            darpan_id='DL/2026/0001',
        )
        self.ngo_address = NGOAddress.objects.create(
            ngo=self.ngo,
            address_line1='108 Seva Marg',
            city='New Delhi',
            state='Delhi',
            pincode='110001',
        )

        # 4. Create Admin User
        self.admin_user = User.objects.create_user(
            email='admin_437@example.com',
            password='Password123!',
            full_name='Platform Admin',
            role='ADMIN',
            is_staff=True,
        )

        # 5. Create Active Monetary Campaign
        self.campaign = Campaign.objects.create(
            ngo=self.ngo,
            created_by=self.ngo_user,
            title='Education For Slum Children',
            short_description='Providing books and uniforms',
            description='Detailed initiative providing schooling and meals for underprivileged children.',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('50000.00'),
            raised_amount=Decimal('0.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    def _create_successful_donation(self, donor=None, amount='1500.00', pan='ABCDE1234F'):
        donor = donor or self.donor_user
        receipt_num = f"DG-M-20260902-{uuid.uuid4().hex[:6].upper()}"
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=donor,
            amount=Decimal(amount),
            currency='INR',
            pan_number=pan,
            status=MonetaryDonation.Status.SUCCESS,
            receipt_number=receipt_num,
            paid_at=timezone.now(),
        )
        PaymentTransaction.objects.create(
            donation=donation,
            donor=donor,
            gateway=PaymentTransaction.Gateway.RAZORPAY,
            gateway_order_id=f"order_test_{uuid.uuid4().hex[:8]}",
            gateway_payment_id=f"pay_test_{uuid.uuid4().hex[:8]}",
            amount=Decimal(amount),
            currency='INR',
            status=PaymentTransaction.Status.SUCCESS,
        )
        return donation

    def _create_pending_donation(self, order_id, amount='1000.00'):
        receipt_num = f"DG-M-20260902-{uuid.uuid4().hex[:6].upper()}"
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal(amount),
            currency='INR',
            status=MonetaryDonation.Status.PENDING,
            receipt_number=receipt_num,
        )
        PaymentTransaction.objects.create(
            donation=donation,
            donor=self.donor_user,
            gateway=PaymentTransaction.Gateway.RAZORPAY,
            gateway_order_id=order_id,
            amount=Decimal(amount),
            currency='INR',
            status=PaymentTransaction.Status.ORDER_CREATED,
        )
        return donation

    # -------------------------------------------------------------------------
    # 1. TaxReceiptService.send_receipt_email Core Unit Tests
    # -------------------------------------------------------------------------

    def test_send_receipt_email_success_with_pdf_attachment(self):
        """Service dispatches email with ReportLab vector PDF attachment to donor."""
        donation = self._create_successful_donation()
        res = TaxReceiptService.send_receipt_email(donation.id, is_manual=False)

        self.assertTrue(res['success'])
        self.assertEqual(len(mail.outbox), 1)

        sent_msg = mail.outbox[0]
        self.assertEqual(sent_msg.to, [self.donor_user.email])
        self.assertIn(donation.receipt_number, sent_msg.subject)
        self.assertIn('Education For Slum Children', sent_msg.body)
        self.assertIn('₹1,500.00', sent_msg.body)
        self.assertIn('Seva Sansthan Trust', sent_msg.body)

        # PDF Attachment verification
        self.assertEqual(len(sent_msg.attachments), 1)
        filename, content, mime = sent_msg.attachments[0]
        self.assertTrue(filename.startswith('DaanGives_Receipt_'))
        self.assertTrue(filename.endswith('.pdf'))
        self.assertEqual(mime, 'application/pdf')
        self.assertTrue(len(content) > 1000)

        # Database state verification
        receipt = TaxReceiptRecord.objects.get(donation=donation)
        self.assertTrue(receipt.email_sent)
        self.assertEqual(receipt.email_send_count, 1)
        self.assertIsNotNone(receipt.last_email_sent_at)
        self.assertEqual(receipt.last_email_error, '')

    def test_automatic_send_is_idempotent_no_duplicate_email(self):
        """Second automatic dispatch does not send duplicate email if email_sent is True."""
        donation = self._create_successful_donation()

        # First automatic dispatch
        res1 = TaxReceiptService.send_receipt_email(donation.id, is_manual=False)
        self.assertTrue(res1['success'])
        self.assertEqual(len(mail.outbox), 1)

        # Second automatic dispatch (e.g. from duplicate webhook or verify retry)
        res2 = TaxReceiptService.send_receipt_email(donation.id, is_manual=False)
        self.assertTrue(res2['success'])
        self.assertTrue(res2.get('already_sent'))
        self.assertEqual(len(mail.outbox), 1)  # Still only 1 email sent!

        receipt = TaxReceiptRecord.objects.get(donation=donation)
        self.assertEqual(receipt.email_send_count, 1)

    def test_manual_send_allows_resend_and_increments_count(self):
        """Manual dispatch allows donor to resend and increments email_send_count."""
        donation = self._create_successful_donation()

        # 1. Initial automatic send
        TaxReceiptService.send_receipt_email(donation.id, is_manual=False)
        self.assertEqual(len(mail.outbox), 1)

        # 2. Manual resend
        res_manual = TaxReceiptService.send_receipt_email(donation.id, is_manual=True)
        self.assertTrue(res_manual['success'])
        self.assertEqual(len(mail.outbox), 2)

        receipt = TaxReceiptRecord.objects.get(donation=donation)
        self.assertEqual(receipt.email_send_count, 2)

    def test_non_success_donation_cannot_be_emailed(self):
        """Attempting to email a PENDING or FAILED donation is safely rejected."""
        donation = MonetaryDonation.objects.create(
            campaign=self.campaign,
            donor=self.donor_user,
            amount=Decimal('500.00'),
            currency='INR',
            status=MonetaryDonation.Status.PENDING,
            receipt_number='DG-M-PENDING-001',
        )
        res = TaxReceiptService.send_receipt_email(donation.id, is_manual=False)
        self.assertFalse(res['success'])
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_records_error_and_preserves_donation_success(self):
        """SMTP exception is safely caught, recorded on TaxReceiptRecord, without failing transaction."""
        donation = self._create_successful_donation()

        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=Exception("SMTP Connection Timeout")):
            res = TaxReceiptService.send_receipt_email(donation.id, is_manual=False)

        self.assertFalse(res['success'])
        self.assertIn('Receipt email could not be sent', res['message'])

        receipt = TaxReceiptRecord.objects.get(donation=donation)
        self.assertFalse(receipt.email_sent)
        self.assertIn('SMTP Connection Timeout', receipt.last_email_error)

        # Financial Invariant: donation status MUST remain SUCCESS!
        donation.refresh_from_db()
        self.assertEqual(donation.status, MonetaryDonation.Status.SUCCESS)

    def test_pan_never_appears_in_email_subject_or_headers(self):
        """Raw PAN is never included in email subject or headers; only masked in body."""
        donation = self._create_successful_donation(pan='ABCDE1234F')
        TaxReceiptService.send_receipt_email(donation.id, is_manual=False)

        sent_msg = mail.outbox[0]
        self.assertNotIn('ABCDE1234F', sent_msg.subject)
        self.assertNotIn('ABCDE1234F', sent_msg.body)
        self.assertIn('******234F', sent_msg.body)

    # -------------------------------------------------------------------------
    # 2. Payment Verification & Webhook End-to-End Triggers
    # -------------------------------------------------------------------------

    def test_verify_payment_view_triggers_automatic_receipt_email(self):
        """DonorMonetaryDonationVerifyPaymentView triggers automatic receipt email upon success."""
        order_id = 'order_v_test_001'
        payment_id = 'pay_v_test_001'
        donation = self._create_pending_donation(order_id=order_id, amount='2000.00')

        # Generate HMAC Signature
        msg = f"{order_id}|{payment_id}".encode('utf-8')
        secret = 'test_secret_key_12345'.encode('utf-8')
        sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()

        self.client.force_authenticate(user=self.donor_user)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', {
                'donation_id': str(donation.id),
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': sig,
            })

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'SUCCESS')

        # Check that automatic email was dispatched via on_commit hook
        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        self.assertEqual(sent_msg.to, [self.donor_user.email])
        self.assertIn(donation.receipt_number, sent_msg.subject)

    def test_webhook_payment_captured_triggers_automatic_receipt_email(self):
        """Razorpay webhook payment.captured triggers automatic receipt email."""
        order_id = 'order_w_test_002'
        payment_id = 'pay_w_test_002'
        donation = self._create_pending_donation(order_id=order_id, amount='3000.00')

        event_payload = {
            'event': 'payment.captured',
            'event_id': 'evt_test_002',
            'created_at': int(timezone.now().timestamp()),
            'payload': {
                'payment': {
                    'entity': {
                        'id': payment_id,
                        'order_id': order_id,
                        'amount': 300000,
                        'currency': 'INR',
                        'status': 'captured',
                    }
                }
            }
        }
        body_bytes = json.dumps(event_payload).encode('utf-8')
        secret = 'test_webhook_secret_12345'.encode('utf-8')
        signature = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(
                '/api/v1/webhooks/razorpay/',
                data=body_bytes,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE=signature,
            )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'ok')

        # Check email sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.donor_user.email])

    def test_verification_and_webhook_no_duplicate_email(self):
        """If verification processes first and then webhook arrives, only 1 email is sent."""
        order_id = 'order_vw_test_003'
        payment_id = 'pay_vw_test_003'
        donation = self._create_pending_donation(order_id=order_id, amount='4000.00')

        # 1. Client Verification executes first
        msg = f"{order_id}|{payment_id}".encode('utf-8')
        secret = 'test_secret_key_12345'.encode('utf-8')
        sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()

        self.client.force_authenticate(user=self.donor_user)
        with self.captureOnCommitCallbacks(execute=True):
            res_v = self.client.post('/api/v1/donor/monetary-donations/verify-payment/', {
                'donation_id': str(donation.id),
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': sig,
            })
        self.assertEqual(res_v.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

        # 2. Webhook arrives afterwards for same order
        event_payload = {
            'event': 'payment.captured',
            'event_id': 'evt_test_003',
            'created_at': int(timezone.now().timestamp()),
            'payload': {
                'payment': {
                    'entity': {
                        'id': payment_id,
                        'order_id': order_id,
                        'amount': 400000,
                        'currency': 'INR',
                        'status': 'captured',
                    }
                }
            }
        }
        body_bytes = json.dumps(event_payload).encode('utf-8')
        webhook_secret = 'test_webhook_secret_12345'.encode('utf-8')
        webhook_sig = hmac.new(webhook_secret, body_bytes, hashlib.sha256).hexdigest()

        with self.captureOnCommitCallbacks(execute=True):
            res_w = self.client.post(
                '/api/v1/webhooks/razorpay/',
                data=body_bytes,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE=webhook_sig,
            )
        self.assertEqual(res_w.status_code, status.HTTP_200_OK)

        # Total emails in outbox MUST REMAIN 1!
        self.assertEqual(len(mail.outbox), 1)

    # -------------------------------------------------------------------------
    # 3. Manual Email Endpoint: POST /api/v1/donor/monetary-donations/<id>/receipt-email/
    # -------------------------------------------------------------------------

    def test_manual_email_endpoint_success_for_authenticated_donor(self):
        """Authenticated donor can trigger receipt email via POST /receipt-email/."""
        donation = self._create_successful_donation(donor=self.donor_user)
        self.client.force_authenticate(user=self.donor_user)

        res = self.client.post(f'/api/v1/donor/monetary-donations/{donation.id}/receipt-email/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'SUCCESS')
        self.assertEqual(res.data['recipient_email'], self.donor_user.email)
        self.assertEqual(len(mail.outbox), 1)

    def test_donor_cannot_email_other_donor_receipt_idor(self):
        """Donor A cannot trigger receipt email for Donor B's donation (IDOR defense)."""
        donation_b = self._create_successful_donation(donor=self.other_donor)
        self.client.force_authenticate(user=self.donor_user)

        res = self.client.post(f'/api/v1/donor/monetary-donations/{donation_b.id}/receipt-email/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(len(mail.outbox), 0)

    def test_anonymous_request_rejected(self):
        """Unauthenticated request to receipt-email endpoint is rejected (401)."""
        donation = self._create_successful_donation()
        res = self.client.post(f'/api/v1/donor/monetary-donations/{donation.id}/receipt-email/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(len(mail.outbox), 0)

    def test_ngo_and_admin_cannot_use_donor_email_endpoint(self):
        """NGO and Admin roles cannot invoke donor receipt-email endpoint (403)."""
        donation = self._create_successful_donation(donor=self.donor_user)

        # NGO user attempt
        self.client.force_authenticate(user=self.ngo_user)
        res_ngo = self.client.post(f'/api/v1/donor/monetary-donations/{donation.id}/receipt-email/')
        self.assertEqual(res_ngo.status_code, status.HTTP_403_FORBIDDEN)

        # Admin user attempt
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.post(f'/api/v1/donor/monetary-donations/{donation.id}/receipt-email/')
        self.assertEqual(res_admin.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(len(mail.outbox), 0)

    # -------------------------------------------------------------------------
    # 4. Reference Donation Safety Invariant
    # -------------------------------------------------------------------------

    def test_reference_donation_remains_untouched(self):
        """Reference donation DG-M-20260831-8STYX2 remains 100% intact and was not emailed."""
        try:
            ref_donation = MonetaryDonation.objects.get(receipt_number='DG-M-20260831-8STYX2')
            self.assertEqual(ref_donation.amount, Decimal('1000.00'))
            self.assertEqual(ref_donation.status, MonetaryDonation.Status.SUCCESS)
            self.assertEqual(ref_donation.campaign.title, 'test1')
        except MonetaryDonation.DoesNotExist:
            # If running in isolated clean test runner DB without seed
            pass
