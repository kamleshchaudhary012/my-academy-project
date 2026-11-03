import re
import json
import hashlib
import logging
from decimal import Decimal
from django.http import HttpResponse
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import PermissionDenied, ValidationError

from users.models import DonorProfile
from campaigns.models import (
    Campaign,
    MonetaryDonation,
    PaymentTransaction,
    GatewayWebhookEvent,
    TaxReceiptRecord,
    Form10BECertificate,
    generate_monetary_receipt_number,
)
from campaigns.monetary_serializers import (
    MonetaryContributionValidationSerializer,
    MonetaryDonationCreateOrderSerializer,
    MonetaryDonationVerifyPaymentSerializer,
    MonetaryDonationReadSerializer,
    NGOMonetaryDonationReadSerializer,
    AdminMonetaryDonationReadSerializer,
    Form10BEUploadSerializer,
    Form10BECertificateReadSerializer,
)
from campaigns.razorpay_service import RazorpayService
from campaigns.tax_receipt_service import (
    TaxReceiptService,
    Form10BENotificationService,
    get_financial_year,
    get_ngo_compliance_ledger_data,
    generate_form_10bd_csv,
)

logger = logging.getLogger(__name__)


class DonorMonetaryContributionValidateView(APIView):
    """
    Validates monetary contribution details before preview or payment intent.
    Enforces minimum contribution amount of ₹10, decimal precision, active campaign status,
    and valid campaign contribution modes (MONETARY / HYBRID).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can initiate monetary contributions.')

        serializer = MonetaryContributionValidationSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        campaign = validated.get('campaign_obj')
        ngo = validated.get('ngo_obj')
        amount = validated['amount']
        pan = validated.get('pan_number', '')

        masked_pan = f'******{pan[-4:]}' if pan else None

        return Response({
            'is_valid': True,
            'amount': str(amount),
            'formatted_amount': f'₹{amount:,.2f}',
            'currency': 'INR',
            'campaign_id': str(campaign.id) if campaign else None,
            'campaign_title': campaign.title if campaign else None,
            'campaign_type': campaign.campaign_type if campaign else None,
            'ngo_id': str(ngo.id) if ngo else None,
            'ngo_name': getattr(ngo, 'display_name', getattr(ngo, 'legal_name', None)) if ngo else None,
            'has_80g': getattr(ngo, 'has_80g', False) if ngo else False,
            'pan_masked': masked_pan,
            'status': 'PREVIEW_VALIDATED',
            'message': 'Monetary contribution details validated successfully.',
        }, status=status.HTTP_200_OK)


class DonorMonetaryContributionIntentView(APIView):
    """
    Idempotent contribution intent creation endpoint for preview.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can initiate monetary contributions.')

        serializer = MonetaryContributionValidationSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        campaign = validated.get('campaign_obj')
        ngo = validated.get('ngo_obj')
        amount = validated['amount']
        pan = validated.get('pan_number', '')

        masked_pan = f'******{pan[-4:]}' if pan else None

        return Response({
            'is_valid': True,
            'intent_status': 'PREVIEW_INITIALIZED',
            'amount': str(amount),
            'formatted_amount': f'₹{amount:,.2f}',
            'currency': 'INR',
            'campaign_id': str(campaign.id) if campaign else None,
            'campaign_title': campaign.title if campaign else None,
            'ngo_name': getattr(ngo, 'display_name', getattr(ngo, 'legal_name', None)) if ngo else None,
            'pan_masked': masked_pan,
            'message': 'Monetary contribution intent registered for preview.',
        }, status=status.HTTP_200_OK)


class DonorMonetaryDonationCreateOrderView(APIView):
    """
    Creates a formal Razorpay order and creates a PENDING MonetaryDonation & PaymentTransaction.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can create monetary donation orders.')

        serializer = MonetaryDonationCreateOrderSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        campaign = validated['campaign_obj']
        amount = validated['amount']
        pan_number = validated.get('pan_number', '')
        is_anonymous = validated.get('is_anonymous', False)
        idempotency_key = validated.get('idempotency_key', '')

        # Connect reusable DonorProfile PAN if none explicitly provided for this order
        if not pan_number and request.user.role == 'DONOR':
            donor_prof = getattr(request.user, 'donor_profile', None)
            if donor_prof and donor_prof.pan_number:
                pan_number = donor_prof.pan_number

        # If donor provided a valid PAN and profile does not have one yet, safely store it
        if pan_number and request.user.role == 'DONOR':
            donor_prof, _ = DonorProfile.objects.get_or_create(user=request.user)
            if not donor_prof.pan_number:
                donor_prof.pan_number = pan_number
                donor_prof.save(update_fields=['pan_number', 'updated_at'])

        with transaction.atomic():
            receipt = generate_monetary_receipt_number()
            # Ensure unique receipt number
            while MonetaryDonation.objects.filter(receipt_number=receipt).exists():
                receipt = generate_monetary_receipt_number()

            donation = MonetaryDonation.objects.create(
                donor=request.user,
                campaign=campaign,
                amount=amount,
                currency='INR',
                receipt_number=receipt,
                pan_number=pan_number,
                status=MonetaryDonation.Status.PENDING,
                is_anonymous=is_anonymous,
            )

            # Create Razorpay Order
            notes = {
                'donation_id': str(donation.id),
                'receipt_number': receipt,
                'campaign_id': str(campaign.id),
                'campaign_title': campaign.title[:40],
                'donor_email': request.user.email,
            }
            rzp_order = RazorpayService.create_order(
                amount_in_rupees=amount,
                receipt=receipt,
                notes=notes,
            )

            payment_tx = PaymentTransaction.objects.create(
                donation=donation,
                donor=request.user,
                gateway=PaymentTransaction.Gateway.RAZORPAY,
                gateway_order_id=rzp_order['id'],
                amount=amount,
                currency='INR',
                status=PaymentTransaction.Status.ORDER_CREATED,
                gateway_response_payload=rzp_order,
                idempotency_key=idempotency_key,
            )

        key_id = getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_placeholder_key_id')
        ngo = campaign.ngo
        ngo_name = getattr(ngo, 'display_name', getattr(ngo, 'legal_name', ''))

        return Response({
            'donation_id': str(donation.id),
            'receipt_number': donation.receipt_number,
            'gateway': 'RAZORPAY',
            'razorpay_key_id': key_id,
            'gateway_order_id': rzp_order['id'],
            'amount': str(amount),
            'amount_paise': int(amount * 100),
            'currency': 'INR',
            'campaign_id': str(campaign.id),
            'campaign_title': campaign.title,
            'ngo_name': ngo_name,
            'donor_name': request.user.full_name or request.user.email,
            'donor_email': request.user.email,
            'donor_phone': getattr(request.user, 'phone', ''),
        }, status=status.HTTP_201_CREATED)


class DonorMonetaryDonationVerifyPaymentView(APIView):
    """
    Cryptographically verifies Razorpay payment signature and completes donation transaction.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can verify monetary donations.')

        serializer = MonetaryDonationVerifyPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        donation_id = serializer.validated_data['donation_id']
        razorpay_order_id = serializer.validated_data['razorpay_order_id']
        razorpay_payment_id = serializer.validated_data['razorpay_payment_id']
        razorpay_signature = serializer.validated_data['razorpay_signature']

        # 1. Cryptographic Signature Verification
        is_valid_sig = RazorpayService.verify_payment_signature(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        )

        if not is_valid_sig:
            return Response({
                'detail': 'Invalid payment gateway cryptographic signature. Payment verification rejected.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Atomic Database State Transition
        with transaction.atomic():
            try:
                payment_tx = PaymentTransaction.objects.select_for_update().get(
                    gateway_order_id=razorpay_order_id,
                    donor=request.user,
                )
            except PaymentTransaction.DoesNotExist:
                return Response({
                    'detail': 'Payment transaction matching this order was not found or belongs to another user.'
                }, status=status.HTTP_404_NOT_FOUND)

            donation = MonetaryDonation.objects.select_for_update().get(id=donation_id)
            if donation.donor != request.user:
                raise PermissionDenied('You do not have permission to verify this donation.')

            if payment_tx.donation_id != donation.id:
                return Response({
                    'detail': 'Order and donation reference mismatch.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Idempotency Check: if already successful, return success without double-increment
            if donation.status == MonetaryDonation.Status.SUCCESS:
                ngo = donation.campaign.ngo
                return Response({
                    'status': 'SUCCESS',
                    'message': 'Payment has already been successfully verified.',
                    'donation_id': str(donation.id),
                    'receipt_number': donation.receipt_number,
                    'amount': str(donation.amount),
                    'currency': donation.currency,
                    'paid_at': donation.paid_at.isoformat() if donation.paid_at else None,
                    'campaign_title': donation.campaign.title,
                    'ngo_name': getattr(ngo, 'display_name', getattr(ngo, 'legal_name', '')),
                }, status=status.HTTP_200_OK)

            # Verify Campaign status
            campaign = Campaign.objects.select_for_update().get(id=donation.campaign_id)
            if campaign.status != Campaign.Status.ACTIVE or not campaign.is_active:
                payment_tx.status = PaymentTransaction.Status.FAILED
                payment_tx.error_description = 'Campaign is no longer active.'
                payment_tx.save()
                return Response({
                    'detail': 'Campaign is no longer active for monetary contributions.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Update PaymentTransaction
            payment_tx.gateway_payment_id = razorpay_payment_id
            payment_tx.gateway_signature = razorpay_signature
            payment_tx.status = PaymentTransaction.Status.SUCCESS
            payment_tx.save()

            # Update MonetaryDonation
            donation.status = MonetaryDonation.Status.SUCCESS
            donation.paid_at = timezone.now()
            donation.save()

            # Update Campaign raised_amount atomically
            Campaign.objects.filter(id=campaign.id).update(
                raised_amount=F('raised_amount') + donation.amount
            )

            # Post-Commit Automatic Receipt Email Hook (Phase 4.3.7)
            donation_id_str = str(donation.id)
            transaction.on_commit(
                lambda: TaxReceiptService.send_receipt_email(donation_id_str, is_manual=False)
            )

        ngo = campaign.ngo
        ngo_name = getattr(ngo, 'display_name', getattr(ngo, 'legal_name', ''))

        return Response({
            'status': 'SUCCESS',
            'message': 'Payment verified and monetary donation recorded successfully.',
            'donation_id': str(donation.id),
            'receipt_number': donation.receipt_number,
            'amount': str(donation.amount),
            'currency': donation.currency,
            'paid_at': donation.paid_at.isoformat() if donation.paid_at else None,
            'campaign_title': campaign.title,
            'ngo_name': ngo_name,
        }, status=status.HTTP_200_OK)


class DonorMonetaryDonationListView(generics.ListAPIView):
    """
    Lists only the authenticated donor's monetary donations.
    """
    serializer_class = MonetaryDonationReadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != 'DONOR':
            raise PermissionDenied('Only donors can access personal donation records.')
        return MonetaryDonation.objects.filter(donor=self.request.user).select_related('campaign', 'campaign__ngo')


class DonorMonetaryDonationDetailView(generics.RetrieveAPIView):
    """
    Retrieves detail of a specific monetary donation belonging to the authenticated donor.
    """
    serializer_class = MonetaryDonationReadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != 'DONOR':
            raise PermissionDenied('Only donors can access personal donation records.')
        return MonetaryDonation.objects.filter(donor=self.request.user).select_related('campaign', 'campaign__ngo')


def _serve_receipt_pdf_response(donation: MonetaryDonation):
    """
    Helper to safely retrieve/render the verified TaxReceiptRecord PDF,
    update download audit metrics, and return a secure HTTP PDF attachment.
    """
    receipt = TaxReceiptService.get_or_create_tax_receipt(donation)

    if receipt.pdf_file and receipt.pdf_file.storage.exists(receipt.pdf_file.name):
        try:
            with receipt.pdf_file.open('rb') as f:
                pdf_bytes = f.read()
        except Exception:
            pdf_bytes = TaxReceiptService.render_receipt_pdf(receipt)
    else:
        pdf_bytes = TaxReceiptService.render_receipt_pdf(receipt)
        if not receipt.pdf_file:
            from django.core.files.base import ContentFile
            import hashlib
            receipt.pdf_file.save(f"Receipt_{receipt.receipt_number}.pdf", ContentFile(pdf_bytes), save=False)
            receipt.document_hash = hashlib.sha256(pdf_bytes).hexdigest()
            receipt.save()

    # Atomically increment download count and update last_downloaded_at
    TaxReceiptRecord.objects.filter(id=receipt.id).update(
        download_count=F('download_count') + 1,
        last_downloaded_at=timezone.now(),
    )

    filename = f"DaanGives_Receipt_{receipt.receipt_number}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class DonorMonetaryDonationReceiptPdfView(APIView):
    """
    Downloads verified receipt PDF for a donation belonging to the authenticated donor.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None, id=None):
        donation_id = pk or id
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can download donor donation receipts.')

        try:
            donation = MonetaryDonation.objects.select_related(
                'campaign', 'campaign__ngo', 'campaign__ngo__legal_info', 'campaign__ngo__address'
            ).get(id=donation_id, donor=request.user, status=MonetaryDonation.Status.SUCCESS)
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Verified monetary donation receipt not found.'}, status=status.HTTP_404_NOT_FOUND)

        return _serve_receipt_pdf_response(donation)


class DonorMonetaryDonationReceiptEmailView(APIView):
    """
    Allows an authenticated donor to manually request / resend their tax receipt email.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk=None, id=None):
        donation_id = pk or id
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can request donation receipt emails.')

        try:
            donation = MonetaryDonation.objects.select_related(
                'campaign', 'campaign__ngo', 'donor'
            ).get(id=donation_id, donor=request.user, status=MonetaryDonation.Status.SUCCESS)
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response(
                {'detail': 'Verified monetary donation receipt not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        result = TaxReceiptService.send_receipt_email(donation, is_manual=True)

        if result.get('success'):
            return Response({
                'status': 'SUCCESS',
                'message': result.get('message', 'Receipt email sent successfully.'),
                'recipient_email': result.get('recipient_email', ''),
                'receipt_number': result.get('receipt_number', donation.receipt_number),
                'email_send_count': result.get('email_send_count', 1),
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'detail': result.get('message', 'Receipt email could not be sent. Please try again.')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _serve_form_10be_pdf_response(certificate: Form10BECertificate):
    """
    Helper to safely retrieve the uploaded Form 10BE certificate PDF,
    update download audit metrics, and return a secure HTTP PDF attachment.
    """
    if not certificate.pdf_file or not certificate.pdf_file.storage.exists(certificate.pdf_file.name):
        return Response({'detail': 'Certificate PDF file is missing or unavailable on storage.'}, status=status.HTTP_404_NOT_FOUND)

    try:
        with certificate.pdf_file.open('rb') as f:
            pdf_bytes = f.read()
    except Exception:
        return Response({'detail': 'Unable to read certificate PDF file.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Atomically increment download count and update last_downloaded_at
    Form10BECertificate.objects.filter(id=certificate.id).update(
        download_count=F('download_count') + 1,
        last_downloaded_at=timezone.now(),
    )

    safe_cert_no = re.sub(r'[^A-Za-z0-9_\-\.]', '_', str(certificate.certificate_number))
    filename = f"DaanGives_Form10BE_{safe_cert_no}.pdf"

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Pragma'] = 'no-cache'
    return response


class DonorForm10BEDownloadView(APIView):
    """
    Downloads official Form 10BE certificate PDF for a donation belonging to the authenticated donor.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None, id=None):
        donation_id = pk or id
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can download donor Form 10BE certificates.')

        try:
            donation = MonetaryDonation.objects.select_related('form_10be', 'donor').get(
                id=donation_id,
                donor=request.user,
                status=MonetaryDonation.Status.SUCCESS,
            )
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Verified monetary donation not found.'}, status=status.HTTP_404_NOT_FOUND)

        form_10be = getattr(donation, 'form_10be', None)
        if not form_10be or not form_10be.is_active:
            return Response(
                {'detail': 'Official Form 10BE certificate has not yet been uploaded by the non-profit partner for this donation.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return _serve_form_10be_pdf_response(form_10be)


class DonorForm10BENotifyView(APIView):
    """
    Manually requests a Form 10BE availability notification email to be re-sent to the authenticated donor.
    Role-gated: Authenticated Donor only.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, id=None, pk=None):
        donation_id = id or pk
        if request.user.role != 'DONOR':
            raise PermissionDenied('Only registered donors can request Form 10BE notification emails.')

        try:
            donation = MonetaryDonation.objects.select_related('form_10be', 'donor', 'campaign', 'campaign__ngo', 'tax_receipt').get(
                id=donation_id,
                donor=request.user,
                status=MonetaryDonation.Status.SUCCESS,
            )
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Verified monetary donation not found.'}, status=status.HTTP_404_NOT_FOUND)

        form_10be = getattr(donation, 'form_10be', None)
        if not form_10be or not form_10be.is_active:
            return Response(
                {'detail': 'Official Form 10BE certificate has not yet been uploaded by the non-profit partner for this donation.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = Form10BENotificationService.notify_donor_form10be_available(form_10be, is_manual=True)

        if result.get('success'):
            return Response({
                'status': 'SUCCESS',
                'message': result.get('message', 'Form 10BE availability notification sent successfully.'),
                'recipient_email': result.get('recipient_email', ''),
                'certificate_number': result.get('certificate_number', form_10be.certificate_number),
                'notification_send_count': result.get('notification_send_count', form_10be.notification_send_count),
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'detail': result.get('message', 'Form 10BE notification email could not be sent. Please try again.')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NGOMonetaryDonationReceiptPdfView(APIView):
    """
    Downloads verified receipt PDF for a donation to campaigns belonging to the authenticated NGO.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None, id=None):
        donation_id = pk or id
        if request.user.role != 'NGO':
            raise PermissionDenied('Only verified NGOs can download campaign donation receipts.')

        try:
            donation = MonetaryDonation.objects.select_related(
                'campaign', 'campaign__ngo', 'campaign__ngo__legal_info', 'campaign__ngo__address'
            ).get(id=donation_id, campaign__ngo__user=request.user, status=MonetaryDonation.Status.SUCCESS)
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Verified campaign monetary donation receipt not found.'}, status=status.HTTP_404_NOT_FOUND)

        return _serve_receipt_pdf_response(donation)


class NGOForm10BEUploadView(APIView):
    """
    Uploads or replaces an official Form 10BE certificate PDF for an eligible 80G donation.
    Role-gated: Verified NGO only.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, donation_id=None, id=None, pk=None):
        target_donation_id = donation_id or id or pk
        if request.user.role != 'NGO':
            raise PermissionDenied('Only registered non-profit organisations can upload Form 10BE certificates.')

        ngo_profile = getattr(request.user, 'ngo_profile', None)
        if not ngo_profile or ngo_profile.status != 'APPROVED' or not ngo_profile.is_active:
            raise PermissionDenied('Only verified and active NGOs can upload compliance certificates.')

        try:
            donation = MonetaryDonation.objects.select_related(
                'campaign', 'campaign__ngo', 'campaign__ngo__legal_info', 'donor', 'tax_receipt', 'form_10be'
            ).get(
                id=target_donation_id,
                campaign__ngo=ngo_profile,
            )
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Donation matching this reference was not found under your organization.'}, status=status.HTTP_404_NOT_FOUND)

        if donation.status != MonetaryDonation.Status.SUCCESS:
            return Response({'detail': 'Form 10BE certificates can only be uploaded for successfully completed donations.'}, status=status.HTTP_400_BAD_REQUEST)

        # Verify 80G eligibility
        receipt = getattr(donation, 'tax_receipt', None)
        if receipt:
            receipt_type = receipt.receipt_type
            financial_year = receipt.financial_year
        else:
            receipt_type = TaxReceiptService.determine_receipt_type(donation)
            financial_year = get_financial_year(donation.paid_at.date() if donation.paid_at else donation.created_at.date())

        if receipt_type != TaxReceiptRecord.ReceiptType.EIGHTY_G:
            return Response({'detail': 'Form 10BE certificates are only applicable to Section 80G tax-exempt donations.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = Form10BEUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        cert_number = serializer.validated_data['certificate_number']
        uploaded_file = serializer.validated_data['file']

        # Compute SHA-256 hash and read bytes
        try:
            uploaded_file.seek(0)
            file_bytes = uploaded_file.read()
            doc_hash = hashlib.sha256(file_bytes).hexdigest()
            file_size = len(file_bytes)
            uploaded_file.seek(0)
        except Exception:
            return Response({'detail': 'Unable to process certificate file binary.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            existing_cert = getattr(donation, 'form_10be', None)
            if existing_cert:
                # Check if this is an identical re-upload (same hash AND same certificate number)
                is_identical = (
                    existing_cert.document_hash == doc_hash and
                    existing_cert.certificate_number == cert_number
                )
                if is_identical:
                    cert_instance = existing_cert
                    msg = 'Official Form 10BE certificate is already uploaded and active.'
                    should_notify = False
                    is_revision = False
                else:
                    # Update / replace existing certificate (Revision)
                    existing_cert.certificate_number = cert_number
                    existing_cert.pdf_file = uploaded_file
                    existing_cert.original_filename = uploaded_file.name[:255]
                    existing_cert.file_size_bytes = file_size
                    existing_cert.document_hash = doc_hash
                    existing_cert.uploaded_by = request.user
                    existing_cert.uploaded_at = timezone.now()
                    existing_cert.is_active = True
                    existing_cert.financial_year = financial_year
                    existing_cert.save()
                    cert_instance = existing_cert
                    msg = 'Official Form 10BE certificate replaced and updated successfully.'
                    should_notify = True
                    is_revision = True
            else:
                # Initial upload
                cert_instance = Form10BECertificate.objects.create(
                    donation=donation,
                    ngo=ngo_profile,
                    donor=donation.donor,
                    financial_year=financial_year,
                    certificate_number=cert_number,
                    pdf_file=uploaded_file,
                    original_filename=uploaded_file.name[:255],
                    file_size_bytes=file_size,
                    document_hash=doc_hash,
                    uploaded_by=request.user,
                    is_active=True,
                )
                msg = 'Official Form 10BE certificate uploaded successfully.'
                should_notify = True
                is_revision = False

            # Post-Commit Automatic Form 10BE Availability Notification Hook (Phase 4.3.9)
            if should_notify:
                cert_id_str = str(cert_instance.id)
                transaction.on_commit(
                    lambda: Form10BENotificationService.notify_donor_form10be_available(
                        cert_id_str, is_manual=False, is_revision=is_revision
                    )
                )

        return Response({
            'status': 'SUCCESS',
            'message': msg,
            'certificate': Form10BECertificateReadSerializer(cert_instance).data,
        }, status=status.HTTP_201_CREATED if not existing_cert else status.HTTP_200_OK)


class NGOForm10BEDownloadView(APIView):
    """
    Downloads official Form 10BE certificate PDF for a donation belonging to the authenticated NGO.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, donation_id=None, id=None, pk=None):
        target_donation_id = donation_id or id or pk
        if request.user.role != 'NGO':
            raise PermissionDenied('Only registered NGOs can access this endpoint.')

        ngo_profile = getattr(request.user, 'ngo_profile', None)
        if not ngo_profile:
            raise PermissionDenied('NGO profile not found.')

        try:
            donation = MonetaryDonation.objects.select_related('form_10be').get(
                id=target_donation_id,
                campaign__ngo=ngo_profile,
                status=MonetaryDonation.Status.SUCCESS,
            )
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Donation record not found under your organization.'}, status=status.HTTP_404_NOT_FOUND)

        form_10be = getattr(donation, 'form_10be', None)
        if not form_10be or not form_10be.is_active:
            return Response({'detail': 'Form 10BE certificate not found for this donation.'}, status=status.HTTP_404_NOT_FOUND)

        return _serve_form_10be_pdf_response(form_10be)


class AdminMonetaryDonationReceiptPdfView(APIView):
    """
    Downloads verified receipt PDF for any platform monetary donation (Admin only).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None, id=None):
        donation_id = pk or id
        if request.user.role != 'ADMIN':
            raise PermissionDenied('Administrative privileges required to access all platform receipts.')

        try:
            donation = MonetaryDonation.objects.select_related(
                'campaign', 'campaign__ngo', 'campaign__ngo__legal_info', 'campaign__ngo__address'
            ).get(id=donation_id, status=MonetaryDonation.Status.SUCCESS)
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Verified platform monetary donation receipt not found.'}, status=status.HTTP_404_NOT_FOUND)

        return _serve_receipt_pdf_response(donation)


class AdminForm10BEDownloadView(APIView):
    """
    Downloads official Form 10BE certificate PDF for platform compliance auditing (Admin only).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, donation_id=None, id=None, pk=None):
        target_donation_id = donation_id or id or pk
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            raise PermissionDenied('Administrative privileges required to access platform compliance certificates.')

        try:
            donation = MonetaryDonation.objects.select_related('form_10be').get(
                id=target_donation_id,
                status=MonetaryDonation.Status.SUCCESS,
            )
        except (MonetaryDonation.DoesNotExist, ValidationError):
            return Response({'detail': 'Donation record not found.'}, status=status.HTTP_404_NOT_FOUND)

        form_10be = getattr(donation, 'form_10be', None)
        if not form_10be or not form_10be.is_active:
            return Response({'detail': 'Form 10BE certificate not found for this donation.'}, status=status.HTTP_404_NOT_FOUND)

        return _serve_form_10be_pdf_response(form_10be)


class NGOMonetaryDonationListView(generics.ListAPIView):
    """
    Lists monetary donations received for campaigns belonging to the authenticated NGO.
    """
    serializer_class = NGOMonetaryDonationReadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != 'NGO':
            raise PermissionDenied('Only authenticated non-profit organisations can access this endpoint.')

        qs = MonetaryDonation.objects.filter(
            campaign__ngo__user=self.request.user
        ).select_related('campaign', 'campaign__ngo', 'donor').order_by('-created_at')

        campaign_id = self.request.query_params.get('campaign_id')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())

        return qs


class AdminMonetaryDonationListView(generics.ListAPIView):
    """
    Lists platform-wide monetary donations for administration & compliance oversight.
    """
    serializer_class = AdminMonetaryDonationReadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != 'ADMIN' and not self.request.user.is_staff:
            raise PermissionDenied('Administrative privileges required to access platform donations.')

        qs = MonetaryDonation.objects.all().select_related(
            'campaign', 'campaign__ngo', 'donor'
        ).prefetch_related('transactions').order_by('-created_at')

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())

        search_param = self.request.query_params.get('search')
        if search_param:
            search_param = search_param.strip()
            qs = qs.filter(
                models.Q(receipt_number__icontains=search_param) |
                models.Q(campaign__title__icontains=search_param) |
                models.Q(campaign__ngo__legal_name__icontains=search_param) |
                models.Q(campaign__ngo__display_name__icontains=search_param) |
                models.Q(transactions__gateway_payment_id__icontains=search_param) |
                models.Q(transactions__gateway_order_id__icontains=search_param)
            ).distinct()

        return qs


class RazorpayWebhookView(APIView):
    """
    Public webhook endpoint for Razorpay payment notifications.
    Validates X-Razorpay-Signature and updates donation/campaign state transactionally.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        webhook_signature = request.headers.get('X-Razorpay-Signature', '')
        payload_body = request.body

        if not webhook_signature or not RazorpayService.verify_webhook_signature(payload_body, webhook_signature):
            return Response({'detail': 'Invalid webhook signature.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            event_data = json.loads(payload_body.decode('utf-8'))
        except Exception:
            return Response({'detail': 'Invalid JSON body.'}, status=status.HTTP_400_BAD_REQUEST)

        event_id = event_data.get('event_id') or event_data.get('id') or f"event_{timezone.now().timestamp()}"
        event_type = event_data.get('event', '')

        # Idempotency check on webhook event
        webhook_event, created = GatewayWebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                'event_type': event_type,
                'gateway': 'RAZORPAY',
                'payload': event_data,
                'is_processed': False,
            }
        )

        if not created and webhook_event.is_processed:
            return Response({'status': 'already_processed'}, status=status.HTTP_200_OK)

        # Handle successful payment events: payment.captured, order.paid
        if event_type in ['payment.captured', 'order.paid']:
            payment_entity = event_data.get('payload', {}).get('payment', {}).get('entity', {})
            order_id = payment_entity.get('order_id')
            payment_id = payment_entity.get('id')
            amount_paise = payment_entity.get('amount')

            if order_id:
                with transaction.atomic():
                    try:
                        payment_tx = PaymentTransaction.objects.select_for_update().get(gateway_order_id=order_id)
                        donation = MonetaryDonation.objects.select_for_update().get(id=payment_tx.donation_id)

                        # Verify amount matches
                        if amount_paise is not None:
                            expected_paise = int(donation.amount * 100)
                            if amount_paise != expected_paise:
                                payment_tx.status = PaymentTransaction.Status.FAILED
                                payment_tx.error_description = f'Amount mismatch: order {expected_paise} != paid {amount_paise}'
                                payment_tx.save()
                                webhook_event.is_processed = True
                                webhook_event.processed_at = timezone.now()
                                webhook_event.save()
                                return Response({'status': 'amount_mismatch_rejected'}, status=status.HTTP_200_OK)

                        if donation.status != MonetaryDonation.Status.SUCCESS:
                            payment_tx.status = PaymentTransaction.Status.SUCCESS
                            payment_tx.gateway_payment_id = payment_id
                            payment_tx.save()

                            donation.status = MonetaryDonation.Status.SUCCESS
                            donation.paid_at = timezone.now()
                            donation.save()

                            # Update Campaign raised_amount atomically
                            Campaign.objects.filter(id=donation.campaign_id).update(
                                raised_amount=F('raised_amount') + donation.amount
                            )

                            # Post-Commit Automatic Receipt Email Hook (Phase 4.3.7)
                            donation_id_str = str(donation.id)
                            transaction.on_commit(
                                lambda: TaxReceiptService.send_receipt_email(donation_id_str, is_manual=False)
                            )
                    except (PaymentTransaction.DoesNotExist, MonetaryDonation.DoesNotExist):
                        pass

        elif event_type in ['payment.failed']:
            payment_entity = event_data.get('payload', {}).get('payment', {}).get('entity', {})
            order_id = payment_entity.get('order_id')
            error_code = payment_entity.get('error_code', '')
            error_desc = payment_entity.get('error_description', '')

            if order_id:
                try:
                    payment_tx = PaymentTransaction.objects.get(gateway_order_id=order_id)
                    payment_tx.status = PaymentTransaction.Status.FAILED
                    payment_tx.error_code = error_code
                    payment_tx.error_description = error_desc
                    payment_tx.save()
                except PaymentTransaction.DoesNotExist:
                    pass

        webhook_event.is_processed = True
        webhook_event.processed_at = timezone.now()
        webhook_event.save()

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# FORM 10BD ANNUAL COMPLIANCE LEDGER & EXPORT (Phase 4.3.4)
# ---------------------------------------------------------------------------

class NGOForm10BDLedgerView(APIView):
    """
    Returns annual Form 10BD donation compliance summary and ledger records for the authenticated NGO.
    Strict tenant isolation: campaign__ngo__user = request.user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'NGO':
            raise PermissionDenied('Only authenticated non-profit organisations can access the compliance ledger.')

        ngo_profile = getattr(request.user, 'ngo_profile', None)
        if not ngo_profile:
            return Response({'detail': 'No registered non-profit profile found for this account.'}, status=status.HTTP_404_NOT_FOUND)

        fy_param = request.query_params.get('financial_year') or request.query_params.get('fy')
        try:
            data = get_ngo_compliance_ledger_data(
                ngo_profile=ngo_profile,
                financial_year_str=fy_param,
                include_raw_pan=False,
            )
            return Response(data, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class NGOForm10BDExportCsvView(APIView):
    """
    Streams Form 10BD Preparation CSV for the authenticated NGO and financial year.
    Strict tenant isolation: campaign__ngo__user = request.user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'NGO':
            raise PermissionDenied('Only authenticated non-profit organisations can export compliance records.')

        ngo_profile = getattr(request.user, 'ngo_profile', None)
        if not ngo_profile:
            return Response({'detail': 'No registered non-profit profile found for this account.'}, status=status.HTTP_404_NOT_FOUND)

        fy_param = request.query_params.get('financial_year') or request.query_params.get('fy')
        try:
            csv_content, filename = generate_form_10bd_csv(
                ngo_profile=ngo_profile,
                financial_year_str=fy_param,
            )
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Cache-Control'] = 'private, no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class AdminForm10BDLedgerView(APIView):
    """
    Administrative overview of Form 10BD compliance ledger across the platform or for a specific NGO.
    Role-gated: ADMIN only.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            raise PermissionDenied('Only platform administrators can access administrative compliance ledgers.')

        ngo_id = request.query_params.get('ngo_id')
        target_ngo = None
        if ngo_id:
            from ngo.models import NGOProfile
            target_ngo = get_object_or_404(NGOProfile, id=ngo_id)

        fy_param = request.query_params.get('financial_year') or request.query_params.get('fy')
        try:
            data = get_ngo_compliance_ledger_data(
                ngo_profile=target_ngo,
                financial_year_str=fy_param,
                include_raw_pan=False,
            )
            return Response(data, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class AdminForm10BDExportCsvView(APIView):
    """
    Administrative export of Form 10BD Preparation CSV across the platform or for a specific NGO.
    Role-gated: ADMIN only.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            raise PermissionDenied('Only platform administrators can export compliance records.')

        ngo_id = request.query_params.get('ngo_id')
        target_ngo = None
        if ngo_id:
            from ngo.models import NGOProfile
            target_ngo = get_object_or_404(NGOProfile, id=ngo_id)

        fy_param = request.query_params.get('financial_year') or request.query_params.get('fy')
        try:
            csv_content, filename = generate_form_10bd_csv(
                ngo_profile=target_ngo,
                financial_year_str=fy_param,
            )
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Cache-Control'] = 'private, no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

