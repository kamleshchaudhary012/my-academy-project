import io
import csv
import uuid
import hashlib
import datetime
from decimal import Decimal
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from campaigns.models import MonetaryDonation, PaymentTransaction, TaxReceiptRecord, Form10BECertificate
from ngo.models import NGOProfile, NGOLegalInfo, NGOAddress

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY


def get_financial_year(dt=None) -> str:
    """
    Calculates the Indian Financial Year (April 1 – March 31).
    Example:
      2026-08-31 -> "FY 2026-27"
      2026-03-31 -> "FY 2025-26"
      2026-04-01 -> "FY 2026-27"
    """
    if dt is None:
        dt = timezone.now().date()
    elif isinstance(dt, datetime.datetime):
        dt = dt.date()

    year = dt.year
    month = dt.month

    if month >= 4:
        start_year = year
        end_year = (year + 1) % 100
    else:
        start_year = year - 1
        end_year = year % 100

    return f"FY {start_year}-{end_year:02d}"


def parse_financial_year(fy_str: str = None) -> tuple[datetime.date, datetime.date, str]:
    """
    Parses a financial year string like 'FY 2026-27' or '2026-27' into (start_date, end_date, normalized_fy).
    Example:
      'FY 2026-27' -> (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31), 'FY 2026-27')
    """
    if not fy_str or str(fy_str).strip() == '':
        today = timezone.now().date()
        normalized_fy = get_financial_year(today)
        return parse_financial_year(normalized_fy)

    clean = str(fy_str).upper().replace('FY', '').strip()
    parts = clean.split('-')
    if len(parts) != 2:
        raise ValueError(f"Invalid financial year format: '{fy_str}'. Expected format like 'FY 2026-27' or '2026-27'.")

    try:
        start_year = int(parts[0])
        end_year_part = int(parts[1])
        if end_year_part < 100:
            end_year = (start_year // 100) * 100 + end_year_part
        else:
            end_year = end_year_part

        if end_year != start_year + 1:
            raise ValueError(f"Financial year span must be exactly 1 year (e.g. 2026-27). Received '{fy_str}'.")

        start_date = datetime.date(start_year, 4, 1)
        end_date = datetime.date(end_year, 3, 31)
        normalized_fy = f"FY {start_year}-{(end_year % 100):02d}"
        return start_date, end_date, normalized_fy
    except ValueError as e:
        raise ValueError(f"Invalid financial year format: '{fy_str}'. Details: {str(e)}")


def _convert_below_thousand(n: int) -> str:
    ones = [
        '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
        'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
        'Seventeen', 'Eighteen', 'Nineteen'
    ]
    tens = [
        '', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'
    ]

    parts = []
    hundreds = n // 100
    rem = n % 100

    if hundreds > 0:
        parts.append(f"{ones[hundreds]} Hundred")

    if rem > 0:
        if rem < 20:
            parts.append(ones[rem])
        else:
            t = rem // 10
            u = rem % 10
            if u > 0:
                parts.append(f"{tens[t]} {ones[u]}")
            else:
                parts.append(tens[t])

    return ' '.join(parts)


def amount_to_words_inr(amount) -> str:
    """
    Converts a Decimal amount into words using the Indian Numbering System.
    Supports Crores, Lakhs, Thousands, Hundreds, Units, and Paise.
    """
    try:
        amt = Decimal(str(amount)).quantize(Decimal('0.01'))
    except Exception:
        return "Invalid Amount"

    if amt < 0:
        return "Negative Amount"

    rupees = int(amt)
    paise = int((amt - Decimal(rupees)) * 100)

    if rupees == 0 and paise == 0:
        return "Zero Rupees Only"

    parts = []
    if rupees > 0:
        # Crores: >= 1,00,00,000
        crores = rupees // 10000000
        rupees %= 10000000
        if crores > 0:
            parts.append(f"{amount_to_words_inr(Decimal(crores)).replace(' Rupees Only', '').replace(' Only', '')} Crore")

        # Lakhs: >= 1,00,000
        lakhs = rupees // 100000
        rupees %= 100000
        if lakhs > 0:
            parts.append(f"{_convert_below_thousand(lakhs)} Lakh")

        # Thousands: >= 1,000
        thousands = rupees // 1000
        rupees %= 1000
        if thousands > 0:
            parts.append(f"{_convert_below_thousand(thousands)} Thousand")

        # Hundreds & Remainder
        if rupees > 0:
            parts.append(_convert_below_thousand(rupees))

    rupees_str = ' '.join(parts).strip()
    if rupees_str:
        rupees_str = f"{rupees_str} Rupee{'s' if int(amt) != 1 else ''}"

    paise_str = ''
    if paise > 0:
        p_word = _convert_below_thousand(paise)
        paise_str = f"{p_word} Paise"

    if rupees_str and paise_str:
        return f"{rupees_str} and {paise_str} Only"
    elif rupees_str:
        return f"{rupees_str} Only"
    elif paise_str:
        return f"{paise_str} Only"
    else:
        return "Zero Rupees Only"


class TaxReceiptService:
    @staticmethod
    def determine_receipt_type(donation: MonetaryDonation) -> str:
        """
        Evaluates authoritative database state to determine whether donation
        qualifies for an 80G Tax Exemption Receipt or Standard Payment Receipt.
        """
        if donation.status != MonetaryDonation.Status.SUCCESS:
            return TaxReceiptRecord.ReceiptType.STANDARD

        ngo = donation.campaign.ngo
        legal_info = getattr(ngo, 'legal_info', None)

        if not legal_info:
            return TaxReceiptRecord.ReceiptType.STANDARD

        has_80g = bool(legal_info.has_80g and legal_info.eighty_g_number)
        has_pan = bool(donation.pan_number and len(donation.pan_number) == 10)

        if has_80g and has_pan:
            return TaxReceiptRecord.ReceiptType.EIGHTY_G

        return TaxReceiptRecord.ReceiptType.STANDARD

    @classmethod
    def get_or_create_tax_receipt(cls, donation: MonetaryDonation) -> TaxReceiptRecord:
        """
        Idempotently generates and persists the verified TaxReceiptRecord and PDF.
        """
        if donation.status != MonetaryDonation.Status.SUCCESS:
            raise ValueError("Receipts can only be generated for successful donations.")

        # Check existing receipt
        existing = TaxReceiptRecord.objects.filter(donation=donation).first()
        if existing:
            # Ensure PDF file exists
            if not existing.pdf_file or not existing.document_hash:
                pdf_bytes = cls.render_receipt_pdf(existing)
                doc_hash = hashlib.sha256(pdf_bytes).hexdigest()
                existing.document_hash = doc_hash
                existing.pdf_file.save(f"Receipt_{existing.receipt_number}.pdf", ContentFile(pdf_bytes), save=True)
            return existing

        campaign = donation.campaign
        ngo = campaign.ngo
        legal_info = getattr(ngo, 'legal_info', None)
        address = getattr(ngo, 'address', None)
        payment_tx = donation.transactions.filter(status=PaymentTransaction.Status.SUCCESS).first()

        receipt_type = cls.determine_receipt_type(donation)
        fy = get_financial_year(donation.paid_at or donation.created_at)
        amount_words = amount_to_words_inr(donation.amount)

        # Build address string
        addr_parts = []
        if address:
            if address.address_line1: addr_parts.append(address.address_line1)
            if getattr(address, 'address_line2', ''): addr_parts.append(address.address_line2)
            if address.city: addr_parts.append(address.city)
            if address.district and address.district != address.city: addr_parts.append(address.district)
            if address.state: addr_parts.append(address.state)
            if address.pincode: addr_parts.append(address.pincode)
        address_str = ', '.join(addr_parts) if addr_parts else 'Registered Office, India'

        pan_masked = f'******{donation.pan_number[-4:]}' if donation.pan_number and len(donation.pan_number) == 10 else ''
        donor_name = donation.donor.full_name or donation.donor.email or 'Verified Donor'

        with transaction.atomic():
            receipt = TaxReceiptRecord.objects.create(
                donation=donation,
                receipt_number=donation.receipt_number,
                receipt_type=receipt_type,
                financial_year=fy,
                donor_name_snapshot=donor_name,
                donor_pan_masked_snapshot=pan_masked,
                donor_email_snapshot=donation.donor.email,
                ngo_legal_name_snapshot=ngo.legal_name or getattr(ngo, 'display_name', 'Non-Profit Trust'),
                ngo_pan_snapshot=legal_info.pan_number if legal_info else '',
                ngo_80g_number_snapshot=legal_info.eighty_g_number if legal_info else '',
                ngo_80g_validity_snapshot=legal_info.eighty_g_validity if legal_info else None,
                ngo_12a_number_snapshot=legal_info.twelve_a_number if legal_info else '',
                ngo_darpan_id_snapshot=legal_info.darpan_id if legal_info else '',
                ngo_address_snapshot=address_str,
                campaign_title_snapshot=campaign.title,
                amount=donation.amount,
                amount_in_words=amount_words,
                payment_gateway_ref_snapshot=payment_tx.gateway_payment_id if payment_tx else '',
                donation_paid_at_snapshot=donation.paid_at or donation.created_at,
                status=TaxReceiptRecord.Status.ISSUED,
            )

            # Generate PDF
            pdf_bytes = cls.render_receipt_pdf(receipt)
            doc_hash = hashlib.sha256(pdf_bytes).hexdigest()
            receipt.document_hash = doc_hash
            receipt.pdf_file.save(f"Receipt_{receipt.receipt_number}.pdf", ContentFile(pdf_bytes), save=True)

        return receipt

    @classmethod
    def send_receipt_email(cls, donation_or_id, is_manual=False) -> dict:
        """
        Sends the official tax receipt email with the generated PDF attached.
        Guarantees:
        1. Atomic state update on TaxReceiptRecord.
        2. Strict idempotency on automatic dispatches (if email_sent is True and is_manual is False, exits as no-op).
        3. Financial invariance: email failure never reverts donation status or raises unhandled exceptions.
        4. No raw PAN exposure in email subject, headers, or logs.
        """
        from django.core.mail import EmailMultiAlternatives
        from django.conf import settings

        # 1. Resolve donation
        if isinstance(donation_or_id, (str, uuid.UUID)):
            try:
                donation = MonetaryDonation.objects.select_related(
                    'campaign', 'campaign__ngo', 'donor'
                ).get(id=donation_or_id)
            except MonetaryDonation.DoesNotExist:
                return {'success': False, 'message': 'Monetary donation not found.'}
        elif isinstance(donation_or_id, MonetaryDonation):
            donation = donation_or_id
        else:
            return {'success': False, 'message': 'Invalid donation reference provided.'}

        # 2. Check donation status
        if donation.status != MonetaryDonation.Status.SUCCESS:
            return {'success': False, 'message': 'Receipts can only be emailed for successful donations.'}

        # 3. Idempotently retrieve or generate TaxReceiptRecord and PDF
        receipt = cls.get_or_create_tax_receipt(donation)

        # 4. Check Idempotency for Automatic Dispatches
        if not is_manual and receipt.email_sent:
            return {
                'success': True,
                'already_sent': True,
                'message': 'Receipt email has already been sent.',
                'recipient_email': receipt.donor_email_snapshot,
                'receipt_number': receipt.receipt_number,
            }

        # 5. Resolve recipient email
        recipient_email = receipt.donor_email_snapshot or getattr(donation.donor, 'email', '')
        if not recipient_email:
            TaxReceiptRecord.objects.filter(id=receipt.id).update(
                last_email_error='No recipient email address found for donor.',
            )
            return {'success': False, 'message': 'Donor email address is unavailable.'}

        # 6. Retrieve or Render PDF bytes
        try:
            if receipt.pdf_file and receipt.pdf_file.storage.exists(receipt.pdf_file.name):
                with receipt.pdf_file.open('rb') as f:
                    pdf_bytes = f.read()
            else:
                pdf_bytes = cls.render_receipt_pdf(receipt)
                if not receipt.pdf_file:
                    receipt.pdf_file.save(f"Receipt_{receipt.receipt_number}.pdf", ContentFile(pdf_bytes), save=True)
        except Exception:
            pdf_bytes = cls.render_receipt_pdf(receipt)

        # 7. Construct Email Content (Text + HTML)
        subject = f"Your Official DaanGives Donation Receipt — {receipt.receipt_number}"
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'DaanGives Foundation <noreply@daangives.org>')
        donor_name = receipt.donor_name_snapshot or 'Generous Donor'
        ngo_name = receipt.ngo_legal_name_snapshot or 'Non-Profit Trust'
        campaign_title = receipt.campaign_title_snapshot or 'Campaign'
        amount_fmt = f"₹{receipt.amount:,.2f}"
        pan_info = f"Donor PAN: {receipt.donor_pan_masked_snapshot}\n" if receipt.donor_pan_masked_snapshot else ""
        pan_html = f"<tr><td style='padding: 6px 0; color: #64748b; font-size: 13px;'>Donor PAN</td><td style='padding: 6px 0; font-weight: bold; text-align: right; font-family: monospace; font-size: 13px;'>{receipt.donor_pan_masked_snapshot}</td></tr>" if receipt.donor_pan_masked_snapshot else ""
        type_badge = "80G Tax Exemption Receipt" if receipt.receipt_type == TaxReceiptRecord.ReceiptType.EIGHTY_G else "Official Contribution Receipt"

        text_body = (
            f"Dear {donor_name},\n\n"
            f"Thank you for your generous contribution of {amount_fmt} ({receipt.amount_in_words}) to '{campaign_title}', organized by {ngo_name}.\n\n"
            f"--- Receipt Summary ---\n"
            f"Receipt Number: {receipt.receipt_number}\n"
            f"Receipt Type: {type_badge}\n"
            f"Financial Year: {receipt.financial_year}\n"
            f"Amount Paid: {amount_fmt}\n"
            f"{pan_info}"
            f"Non-Profit Partner: {ngo_name}\n\n"
            f"Your verified tax receipt PDF is attached to this email. You can also view and download your full donation records anytime at your DaanGives Receipt Center.\n\n"
            f"Warm regards,\nDaanGives Foundation\nsupport@daangives.org"
        )

        html_body = f"""
        <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; color: #1e293b;">
          <div style="border-bottom: 2px solid #0f766e; padding-bottom: 16px; margin-bottom: 20px;">
            <h1 style="color: #0f766e; font-size: 22px; margin: 0; font-weight: bold;">DaanGives Foundation</h1>
            <p style="color: #64748b; font-size: 12px; margin: 4px 0 0 0;">Official Donation & Tax Exemption Receipt</p>
          </div>

          <p style="font-size: 15px; line-height: 1.5;">Dear <strong>{donor_name}</strong>,</p>
          <p style="font-size: 14px; line-height: 1.6; color: #334155;">
            Thank you for your generous contribution of <strong style="color: #0f766e; font-size: 16px;">{amount_fmt}</strong> to <strong>{campaign_title}</strong> organized by <strong>{ngo_name}</strong>.
          </p>

          <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; margin: 20px 0;">
            <table style="width: 100%; border-collapse: collapse;">
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Receipt Number</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-family: monospace; font-size: 13px;">{receipt.receipt_number}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Receipt Type</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; color: #047857; font-size: 13px;">{type_badge}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Financial Year</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 13px;">{receipt.financial_year}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Amount (INR)</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 15px; color: #0f766e;">{amount_fmt}</td>
              </tr>
              {pan_html}
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">NGO Partner</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 13px;">{ngo_name}</td>
              </tr>
            </table>
          </div>

          <div style="background-color: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 10px; padding: 12px 16px; margin-bottom: 24px; font-size: 13px; color: #065f46;">
            <strong>PDF Attached:</strong> Your official signed receipt is attached to this email as a PDF document. Please retain it for your tax records.
          </div>

          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
          <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0;">
            DaanGives Foundation • Transparent Non-Profit Platform • <a href="mailto:support@daangives.org" style="color: #0f766e;">support@daangives.org</a>
          </p>
        </div>
        """

        # 8. Dispatch Email with Attachment
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email,
                to=[recipient_email],
            )
            msg.attach_alternative(html_body, "text/html")
            pdf_filename = f"DaanGives_Receipt_{receipt.receipt_number}.pdf"
            msg.attach(pdf_filename, pdf_bytes, "application/pdf")
            msg.send(fail_silently=False)

            # 9. Update state on success
            TaxReceiptRecord.objects.filter(id=receipt.id).update(
                email_sent=True,
                email_send_count=F('email_send_count') + 1,
                last_email_sent_at=timezone.now(),
                last_email_error='',
            )

            # Refresh local receipt object
            receipt.refresh_from_db()

            return {
                'success': True,
                'message': 'Receipt email sent successfully.',
                'recipient_email': recipient_email,
                'receipt_number': receipt.receipt_number,
                'email_send_count': receipt.email_send_count,
            }
        except Exception as err:
            err_msg = str(err)[:500]
            TaxReceiptRecord.objects.filter(id=receipt.id).update(
                last_email_error=err_msg,
            )
            return {
                'success': False,
                'message': 'Receipt email could not be sent. Please try again.',
                'error': err_msg,
            }

    @classmethod
    def render_receipt_pdf(cls, receipt: TaxReceiptRecord) -> bytes:
        """
        Renders a publication-grade, vector PDF receipt using ReportLab.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()
        
        # Primary Palette
        c_primary = colors.HexColor('#0f766e')      # Teal / Emerald
        c_dark = colors.HexColor('#0f172a')         # Slate 900
        c_muted = colors.HexColor('#475569')        # Slate 600
        c_border = colors.HexColor('#cbd5e1')       # Slate 300
        c_bg_card = colors.HexColor('#f8fafc')      # Slate 50
        c_accent = colors.HexColor('#047857')       # Green 700

        # Custom Typographic Styles
        style_header = ParagraphStyle(
            'ReceiptHeader',
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=c_primary,
            alignment=TA_LEFT,
        )
        style_sub = ParagraphStyle(
            'ReceiptSub',
            fontName='Helvetica',
            fontSize=8,
            leading=11,
            textColor=c_muted,
            alignment=TA_LEFT,
        )
        style_title = ParagraphStyle(
            'DocTitle',
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=15,
            textColor=c_dark,
            alignment=TA_CENTER,
        )
        style_title_sub = ParagraphStyle(
            'DocTitleSub',
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=c_accent,
            alignment=TA_CENTER,
        )
        style_label = ParagraphStyle(
            'FieldLabel',
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=c_muted,
        )
        style_val = ParagraphStyle(
            'FieldVal',
            fontName='Helvetica',
            fontSize=8.5,
            leading=11,
            textColor=c_dark,
        )
        style_val_mono = ParagraphStyle(
            'FieldValMono',
            fontName='Courier-Bold',
            fontSize=9,
            leading=11,
            textColor=c_dark,
        )
        style_amount = ParagraphStyle(
            'AmountBig',
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=c_primary,
            alignment=TA_RIGHT,
        )
        style_legal_clause = ParagraphStyle(
            'LegalClause',
            fontName='Helvetica',
            fontSize=7.5,
            leading=10.5,
            textColor=c_dark,
            alignment=TA_JUSTIFY,
        )
        style_footer = ParagraphStyle(
            'DocFooter',
            fontName='Helvetica',
            fontSize=7,
            leading=9,
            textColor=c_muted,
            alignment=TA_CENTER,
        )

        story = []

        # 1. Header Band
        is_80g = receipt.receipt_type == TaxReceiptRecord.ReceiptType.EIGHTY_G
        badge_text = "SECTION 80G TAX DEDUCTIBLE RECEIPT" if is_80g else "OFFICIAL DONATION PAYMENT RECEIPT"
        
        header_table = Table(
            [
                [
                    Paragraph("<b>DaanGives</b><br/><font size='7' color='#475569'>National Non-Profit Giving Platform</font>", style_header),
                    Paragraph(f"<font color='{c_accent.hexval()}'><b>{badge_text}</b></font><br/><font size='8' color='#475569'><b>{receipt.financial_year}</b></font>", ParagraphStyle('RightH', parent=style_header, alignment=TA_RIGHT, fontSize=9, leading=12))
                ]
            ],
            colWidths=[260, 260]
        )
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(header_table)
        story.append(HRFlowable(width="100%", thickness=1.5, color=c_primary, spaceBefore=4, spaceAfter=8))

        # 2. Receipt Reference Bar
        paid_date_str = receipt.donation_paid_at_snapshot.strftime('%d %B %Y, %I:%M %p UTC') if receipt.donation_paid_at_snapshot else datetime.date.today().strftime('%d %B %Y')
        ref_bar_data = [
            [
                Paragraph("<b>RECEIPT NUMBER</b>", style_label),
                Paragraph("<b>DATE OF ISSUE</b>", style_label),
                Paragraph("<b>FINANCIAL YEAR</b>", style_label),
            ],
            [
                Paragraph(receipt.receipt_number, style_val_mono),
                Paragraph(paid_date_str, style_val),
                Paragraph(receipt.financial_year, style_val),
            ]
        ]
        ref_table = Table(ref_bar_data, colWidths=[200, 200, 120])
        ref_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), c_bg_card),
            ('BOX', (0, 0), (-1, -1), 0.5, c_border),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, c_border),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(ref_table)
        story.append(Spacer(1, 8))

        # 3. Donee (NGO) Details Card
        ngo_validity_str = receipt.ngo_80g_validity_snapshot.strftime('%d/%m/%Y') if receipt.ngo_80g_validity_snapshot else 'Perpetual'
        donee_data = [
            [Paragraph("<b>DONEE ORGANISATION (REGISTERED TRUST / SOCIETY)</b>", style_label), ""],
            [Paragraph("<b>Legal Name:</b>", style_label), Paragraph(f"<b>{receipt.ngo_legal_name_snapshot}</b>", style_val)],
            [Paragraph("<b>Registered Address:</b>", style_label), Paragraph(receipt.ngo_address_snapshot, style_val)],
            [Paragraph("<b>PAN:</b>", style_label), Paragraph(receipt.ngo_pan_snapshot or 'N/A', style_val_mono)],
        ]

        if is_80g and receipt.ngo_80g_number_snapshot:
            donee_data.append([Paragraph("<b>80G Order Number / URN:</b>", style_label), Paragraph(f"<b>{receipt.ngo_80g_number_snapshot}</b>", style_val_mono)])
            donee_data.append([Paragraph("<b>80G Validity:</b>", style_label), Paragraph(ngo_validity_str, style_val)])
        if receipt.ngo_12a_number_snapshot:
            donee_data.append([Paragraph("<b>12A Registration No.:</b>", style_label), Paragraph(receipt.ngo_12a_number_snapshot, style_val)])
        if receipt.ngo_darpan_id_snapshot:
            donee_data.append([Paragraph("<b>NITI Aayog Darpan ID:</b>", style_label), Paragraph(receipt.ngo_darpan_id_snapshot, style_val_mono)])

        donee_table = Table(donee_data, colWidths=[150, 370])
        donee_table.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('BOX', (0, 0), (-1, -1), 0.5, c_border),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(donee_table)
        story.append(Spacer(1, 8))

        # 4. Donor Details Card
        donor_data = [
            [Paragraph("<b>DONOR IDENTIFICATION DETAILS</b>", style_label), ""],
            [Paragraph("<b>Donor Full Name:</b>", style_label), Paragraph(f"<b>{receipt.donor_name_snapshot}</b>", style_val)],
            [Paragraph("<b>Donor Email:</b>", style_label), Paragraph(receipt.donor_email_snapshot, style_val)],
            [Paragraph("<b>Donor PAN:</b>", style_label), Paragraph(receipt.donor_pan_masked_snapshot or 'Not Provided', style_val_mono)],
        ]
        donor_table = Table(donor_data, colWidths=[150, 370])
        donor_table.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('BOX', (0, 0), (-1, -1), 0.5, c_border),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(donor_table)
        story.append(Spacer(1, 8))

        # 5. Contribution & Payment Breakdown Card
        contrib_data = [
            [Paragraph("<b>CONTRIBUTION & TRANSACTION PARTICULARS</b>", style_label), ""],
            [Paragraph("<b>Campaign Appeal:</b>", style_label), Paragraph(receipt.campaign_title_snapshot, style_val)],
            [Paragraph("<b>Payment Mode / Gateway:</b>", style_label), Paragraph("Razorpay Gateway (Online Netbanking / UPI / Cards)", style_val)],
            [Paragraph("<b>Gateway Payment ID:</b>", style_label), Paragraph(receipt.payment_gateway_ref_snapshot or 'Verified Payment', style_val_mono)],
            [Paragraph("<b>Amount Contributed (INR):</b>", style_label), Paragraph(f"<b>₹{receipt.amount:,.2f}</b>", style_amount)],
            [Paragraph("<b>Amount in Words:</b>", style_label), Paragraph(f"<b>{receipt.amount_in_words}</b>", style_val)],
        ]
        contrib_table = Table(contrib_data, colWidths=[150, 370])
        contrib_table.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('BOX', (0, 0), (-1, -1), 0.5, c_border),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(contrib_table)
        story.append(Spacer(1, 8))

        # 6. Statutory Declaration Clause
        if is_80g:
            clause_text = (
                f"<b>Statutory 80G Declaration:</b> Donations made to <b>{receipt.ngo_legal_name_snapshot}</b> "
                f"are eligible for tax deduction under Section 80G of the Income Tax Act, 1961 "
                f"vide Order No. <b>{receipt.ngo_80g_number_snapshot}</b>. "
                "This electronic receipt is issued in compliance with statutory provisions as an authentic confirmation of donation."
            )
            bg_clause = colors.HexColor('#ecfdf5')
            bdr_clause = colors.HexColor('#a7f3d0')
        else:
            clause_text = (
                f"<b>Donation Confirmation:</b> This receipt certifies that a voluntary charitable contribution of "
                f"<b>₹{receipt.amount:,.2f}</b> ({receipt.amount_in_words}) was successfully received for "
                f"<b>{receipt.campaign_title_snapshot}</b> by <b>{receipt.ngo_legal_name_snapshot}</b> through the DaanGives platform."
            )
            bg_clause = colors.HexColor('#f8fafc')
            bdr_clause = colors.HexColor('#cbd5e1')

        clause_table = Table([[Paragraph(clause_text, style_legal_clause)]], colWidths=[520])
        clause_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_clause),
            ('BOX', (0, 0), (-1, -1), 0.5, bdr_clause),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(clause_table)
        story.append(Spacer(1, 10))

        # 7. Verification & Document Integrity Hash Footer
        hash_val = receipt.document_hash or 'SHA256_PENDING'
        footer_data = [
            [Paragraph(f"<b>Digital Verification & Integrity Hash (SHA-256):</b><br/><font face='Courier' size='6'>{hash_val}</font>", style_footer)],
            [Paragraph("This is a computer-generated official receipt issued by DaanGives. Valid without physical signature.", style_footer)]
        ]
        footer_table = Table(footer_data, colWidths=[520])
        footer_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(footer_table)

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()


def get_ngo_compliance_ledger_data(ngo_profile=None, financial_year_str=None, include_raw_pan=False):
    """
    Computes the Form 10BD / Annual Donation Compliance Ledger for a given NGO (or platform-wide for admin)
    and financial year.
    """
    start_date, end_date, normalized_fy = parse_financial_year(financial_year_str)
    start_dt = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
    end_dt = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))

    qs = MonetaryDonation.objects.filter(
        status=MonetaryDonation.Status.SUCCESS,
        paid_at__gte=start_dt,
        paid_at__lte=end_dt,
    )
    if ngo_profile is not None:
        qs = qs.filter(campaign__ngo=ngo_profile)

    qs = qs.select_related('campaign', 'campaign__ngo', 'campaign__ngo__legal_info', 'donor', 'donor__donor_profile', 'tax_receipt', 'form_10be').prefetch_related('transactions').order_by('paid_at', 'created_at')

    records = []
    total_amount = Decimal('0.00')
    eighty_g_amount = Decimal('0.00')
    standard_amount = Decimal('0.00')
    eighty_g_count = 0
    standard_count = 0
    unique_donors = set()

    for idx, d in enumerate(qs, 1):
        # Resolve receipt record or classify
        receipt_rec = getattr(d, 'tax_receipt', None)
        if receipt_rec:
            receipt_type = receipt_rec.receipt_type
            receipt_num = receipt_rec.receipt_number
        else:
            receipt_type = TaxReceiptService.determine_receipt_type(d)
            receipt_num = d.receipt_number

        amount_val = Decimal(str(d.amount))
        total_amount += amount_val
        unique_donors.add(d.donor_id)

        if receipt_type == TaxReceiptRecord.ReceiptType.EIGHTY_G:
            eighty_g_amount += amount_val
            eighty_g_count += 1
        else:
            standard_amount += amount_val
            standard_count += 1

        # Payment Transaction ID
        gw_txn = d.transactions.filter(status='SUCCESS').first()
        gw_payment_id = gw_txn.gateway_payment_id if gw_txn else ''

        # Form 10BE Certificate check
        form_10be = getattr(d, 'form_10be', None)
        has_10be = bool(form_10be and form_10be.is_active)
        form_10be_cert_no = form_10be.certificate_number if has_10be else ''
        form_10be_id = str(form_10be.id) if has_10be else None

        # Donor Information (Authoritative internal legal identity)
        donor_name = d.donor.full_name if d.donor and d.donor.full_name else (d.donor.email if d.donor else 'Donor')
        donor_email = d.donor.email if d.donor else ''
        donor_phone = d.donor.phone if d.donor and d.donor.phone else ''

        # PAN handling
        raw_pan = d.pan_number or ''
        masked_pan = f"******{raw_pan[-4:]}" if (raw_pan and len(raw_pan) == 10) else "Not Provided"

        # Donor Compliance Profile (Address & Entity Type)
        donor_profile = getattr(d.donor, 'donor_profile', None) if d.donor else None
        if donor_profile and (donor_profile.address_line1 or donor_profile.city):
            addr_parts = [
                donor_profile.address_line1,
                donor_profile.address_line2,
                donor_profile.city,
                donor_profile.state,
                donor_profile.pincode,
                donor_profile.country
            ]
            donor_address_str = ', '.join([p.strip() for p in addr_parts if p and p.strip()])
        else:
            donor_address_str = 'Not Provided'

        donor_entity_type_str = donor_profile.get_entity_type_display() if donor_profile else 'Individual'

        # NGO Legal Info
        ngo_inst = d.campaign.ngo if d.campaign else None
        ngo_legal = getattr(ngo_inst, 'legal_info', None) if ngo_inst else None
        ngo_name = ngo_inst.legal_name if ngo_inst and ngo_inst.legal_name else (ngo_inst.display_name if ngo_inst else '')
        ngo_pan = ngo_legal.pan_number if ngo_legal and ngo_legal.pan_number else ''
        ngo_80g_num = ngo_legal.eighty_g_number if ngo_legal and ngo_legal.eighty_g_number else ''

        records.append({
            'serial_no': idx,
            'donation_id': str(d.id),
            'receipt_number': receipt_num,
            'donation_date': (d.paid_at or d.created_at).strftime('%d/%m/%Y'),
            'donation_datetime': (d.paid_at or d.created_at).isoformat(),
            'financial_year': normalized_fy,
            'donor_name': donor_name,
            'donor_pan': raw_pan if include_raw_pan else masked_pan,
            'donor_pan_masked': masked_pan,
            'donor_email': donor_email,
            'donor_phone': donor_phone,
            'donor_address': donor_address_str,
            'donor_entity_type': donor_entity_type_str,
            'amount': str(amount_val),
            'amount_display': f"₹{amount_val:,.2f}",
            'currency': d.currency or 'INR',
            'campaign_id': str(d.campaign.id) if d.campaign else '',
            'campaign_title': d.campaign.title if d.campaign else '',
            'ngo_name': ngo_name,
            'ngo_pan': ngo_pan,
            'ngo_80g_number': ngo_80g_num,
            'receipt_type': receipt_type,
            'receipt_type_display': '80G Tax Exemption Receipt' if receipt_type == TaxReceiptRecord.ReceiptType.EIGHTY_G else 'Standard Payment Receipt',
            'has_form_10be': has_10be,
            'form_10be_certificate_number': form_10be_cert_no,
            'form_10be_id': form_10be_id,
            'gateway_payment_id': gw_payment_id,
            'payment_status': d.status,
            'is_anonymous_public': d.is_anonymous,
        })

    summary = {
        'financial_year': normalized_fy,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'total_donations_count': len(records),
        'total_donated_amount': str(total_amount),
        'total_donated_amount_display': f"₹{total_amount:,.2f}",
        'eighty_g_donations_count': eighty_g_count,
        'eighty_g_donated_amount': str(eighty_g_amount),
        'eighty_g_donated_amount_display': f"₹{eighty_g_amount:,.2f}",
        'standard_donations_count': standard_count,
        'standard_donated_amount': str(standard_amount),
        'standard_donated_amount_display': f"₹{standard_amount:,.2f}",
        'unique_donors_count': len(unique_donors),
    }

    return {
        'financial_year': normalized_fy,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'summary': summary,
        'records': records,
    }


def generate_form_10bd_csv(ngo_profile=None, financial_year_str=None) -> tuple[str, str]:
    """
    Generates a Form 10BD Preparation / Annual Donation Compliance CSV.
    Returns:
      (csv_content_string, filename)
    """
    ledger_data = get_ngo_compliance_ledger_data(
        ngo_profile=ngo_profile,
        financial_year_str=financial_year_str,
        include_raw_pan=True,
    )
    fy_clean = ledger_data['financial_year'].replace(' ', '')
    filename = f"DaanGives_Form10BD_Preparation_{fy_clean}.csv"

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Statutory Notice & Metadata Header
    writer.writerow(["# DaanGives - Form 10BD Preparation / Annual Donation Compliance Statement"])
    writer.writerow([f"# Financial Year: {ledger_data['financial_year']} ({ledger_data['start_date']} to {ledger_data['end_date']})"])
    if ngo_profile:
        writer.writerow([f"# Non-Profit Organisation: {ngo_profile.legal_name or ngo_profile.display_name}"])
    writer.writerow([f"# Generated At (UTC): {timezone.now().isoformat()}"])
    writer.writerow([f"# Total Verified Donations: {ledger_data['summary']['total_donations_count']} | Total Amount: INR {ledger_data['summary']['total_donated_amount']}"])
    writer.writerow([])

    # 2. CSV Column Headers
    headers = [
        "Serial No.",
        "Donation Reference / Receipt No.",
        "Donation Date",
        "Financial Year",
        "Donor Full Name",
        "Donor PAN Number",
        "Donor Email",
        "Donor Phone",
        "Donor Address",
        "Donor Entity Type",
        "Donation Amount (INR)",
        "Currency",
        "Payment Mode",
        "Gateway Payment ID",
        "Campaign Appeal",
        "Donee NGO Legal Name",
        "Donee NGO PAN",
        "80G Order Number",
        "Receipt Classification",
    ]
    writer.writerow(headers)

    # 3. Data Rows
    for r in ledger_data['records']:
        writer.writerow([
            r['serial_no'],
            r['receipt_number'],
            r['donation_date'],
            r['financial_year'],
            r['donor_name'],
            r['donor_pan'] or 'NOT_PROVIDED',
            r['donor_email'],
            r['donor_phone'] or 'NOT_PROVIDED',
            r['donor_address'],
            r['donor_entity_type'],
            f"{Decimal(r['amount']):.2f}",
            r['currency'],
            'Online / Razorpay Gateway',
            r['gateway_payment_id'] or 'NOT_AVAILABLE',
            r['campaign_title'],
            r['ngo_name'],
            r['ngo_pan'] or 'NOT_AVAILABLE',
            r['ngo_80g_number'] or 'NOT_AVAILABLE',
            r['receipt_type_display'],
        ])

    return output.getvalue(), filename


class Form10BENotificationService:
    """
    Handles donor compliance communications when an official Form 10BE certificate
    is uploaded or revised by a verified non-profit partner.

    Critical Statutory Invariant:
    DaanGives does NOT generate, forge, alter, or issue official Form 10BE.
    This service only notifies donors that an officially issued certificate uploaded
    by their non-profit partner is available for secure retrieval.
    """

    @classmethod
    def notify_donor_form10be_available(cls, certificate_or_id, is_manual=False, is_revision=False) -> dict:
        """
        Dispatches an official Form 10BE availability notification email to the donor.

        Guarantees:
        1. Atomic state update on Form10BECertificate (notification_sent, notification_send_count, last_notification_sent_at).
        2. Strict idempotency on automatic dispatches: if already sent and not a revision/manual request, exits as no-op.
        3. Privacy protection: NO PDF attachment (Option B), NO raw PAN in email subject, body, headers, or URLs.
        4. Clean portal CTA: Links to /donor/receipts without sensitive query parameters or tokens.
        5. Financial & upload invariance: Email failure NEVER rolls back certificate, payment, or donation records.
        """
        from django.core.mail import EmailMultiAlternatives
        from django.conf import settings

        # 1. Resolve certificate
        if isinstance(certificate_or_id, (str, uuid.UUID)):
            try:
                cert = Form10BECertificate.objects.select_related(
                    'donation', 'donation__donor', 'donation__campaign', 'donation__campaign__ngo', 'ngo'
                ).get(id=certificate_or_id)
            except Form10BECertificate.DoesNotExist:
                return {'success': False, 'message': 'Form 10BE certificate record not found.'}
        elif isinstance(certificate_or_id, Form10BECertificate):
            cert = certificate_or_id
        else:
            return {'success': False, 'message': 'Invalid certificate reference provided.'}

        # 2. Check active certificate
        if not cert.is_active:
            return {'success': False, 'message': 'Cannot notify for an inactive certificate.'}

        # 3. Check donation status
        donation = cert.donation
        if donation.status != MonetaryDonation.Status.SUCCESS:
            return {'success': False, 'message': 'Notifications can only be sent for successfully completed donations.'}

        # 4. Check Idempotency for Automatic Dispatches
        if not is_manual and not is_revision and cert.notification_sent:
            return {
                'success': True,
                'already_sent': True,
                'message': 'Donor notification email has already been sent.',
                'recipient_email': getattr(donation.donor, 'email', ''),
                'certificate_number': cert.certificate_number,
            }

        # 5. Resolve recipient email (server-authoritative)
        recipient_email = getattr(donation.donor, 'email', '')
        if not recipient_email and hasattr(donation, 'tax_receipt') and donation.tax_receipt:
            recipient_email = donation.tax_receipt.donor_email_snapshot

        if not recipient_email:
            Form10BECertificate.objects.filter(id=cert.id).update(
                last_notification_error='Donor email address is unavailable.',
            )
            return {'success': False, 'message': 'Donor email address is unavailable.'}

        # 6. Extract non-sensitive metadata
        donor_name = getattr(donation.donor, 'full_name', '') or (donation.tax_receipt.donor_name_snapshot if hasattr(donation, 'tax_receipt') and donation.tax_receipt else '') or 'Generous Donor'
        ngo_name = getattr(cert.ngo, 'legal_name', '') or getattr(cert.ngo, 'display_name', '') or 'Non-Profit Partner'
        campaign_title = getattr(donation.campaign, 'title', 'Campaign')
        receipt_number = donation.receipt_number
        fy = cert.financial_year
        cert_number = cert.certificate_number
        amount_fmt = f"₹{donation.amount:,.2f}"

        # 7. Construct Email Subject & Body
        if is_revision:
            subject = f"Updated Form 10BE Certificate Available — {fy}"
            notification_type_heading = "Updated Form 10BE Certificate Notification"
            notification_intro_p = f"We are writing to inform you that your non-profit partner, <strong>{ngo_name}</strong>, has uploaded an <strong>updated / revised official Form 10BE certificate</strong> for your Section 80G tax-exempt donation."
            text_intro = f"Your non-profit partner, {ngo_name}, has uploaded an updated / revised official Form 10BE certificate for your Section 80G tax-exempt donation to '{campaign_title}'."
        else:
            subject = f"Official Form 10BE Certificate Available — {fy}"
            notification_type_heading = "Official Form 10BE Certificate Notification"
            notification_intro_p = f"We are pleased to inform you that your non-profit partner, <strong>{ngo_name}</strong>, has uploaded the <strong>official Form 10BE certificate</strong> for your Section 80G tax-exempt contribution to <strong>{campaign_title}</strong>."
            text_intro = f"Your non-profit partner, {ngo_name}, has uploaded the official Form 10BE certificate for your Section 80G tax-exempt contribution to '{campaign_title}'."

        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'DaanGives Foundation <noreply@daangives.org>')
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
        receipts_portal_url = f"{frontend_url}/donor/receipts"

        text_body = (
            f"Dear {donor_name},\n\n"
            f"{text_intro}\n\n"
            f"--- Certificate Summary ---\n"
            f"Non-Profit Partner: {ngo_name}\n"
            f"Campaign: {campaign_title}\n"
            f"Donation Receipt Reference: {receipt_number}\n"
            f"Financial Year: {fy}\n"
            f"Official Certificate Number: {cert_number}\n"
            f"Eligible Amount: {amount_fmt}\n\n"
            f"Form 10BE is the official Certificate of Donation issued under Section 80G of the Income Tax Act, 1961, following the non-profit partner's annual Form 10BD electronic statement filing with the Income Tax Department.\n\n"
            f"To protect your privacy and tax identification data, your Form 10BE PDF is not attached over unencrypted email. You can securely view and download your official certificate anytime through your authenticated Receipts & 80G Document Center:\n"
            f"{receipts_portal_url}\n\n"
            f"Warm regards,\nDaanGives Foundation\nsupport@daangives.org"
        )

        html_body = f"""
        <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; color: #1e293b;">
          <div style="border-bottom: 2px solid #0f766e; padding-bottom: 16px; margin-bottom: 20px;">
            <h1 style="color: #0f766e; font-size: 22px; margin: 0; font-weight: bold;">DaanGives Foundation</h1>
            <p style="color: #64748b; font-size: 12px; margin: 4px 0 0 0;">{notification_type_heading}</p>
          </div>

          <p style="font-size: 15px; line-height: 1.5;">Dear <strong>{donor_name}</strong>,</p>
          <p style="font-size: 14px; line-height: 1.6; color: #334155;">
            {notification_intro_p}
          </p>

          <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; margin: 20px 0;">
            <table style="width: 100%; border-collapse: collapse;">
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Financial Year</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 13px; color: #0f766e;">{fy}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Certificate Number</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-family: monospace; font-size: 13px;">{cert_number}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Receipt Reference</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-family: monospace; font-size: 13px;">{receipt_number}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Eligible Amount</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 14px; color: #047857;">{amount_fmt}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Non-Profit Partner</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 13px;">{ngo_name}</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #64748b; font-size: 13px;">Campaign</td>
                <td style="padding: 6px 0; font-weight: bold; text-align: right; font-size: 13px;">{campaign_title}</td>
              </tr>
            </table>
          </div>

          <div style="background-color: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 10px; padding: 14px 16px; margin-bottom: 24px; font-size: 12.5px; color: #065f46; line-height: 1.5;">
            <strong>Statutory Compliance Note:</strong> Form 10BE is the official Certificate of Donation issued under Section 80G of the Income Tax Act, 1961, following the non-profit partner's electronic statement filing with the Income Tax Department.
          </div>

          <div style="text-align: center; margin: 28px 0;">
            <a href="{receipts_portal_url}" style="background-color: #0f766e; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 12px; font-weight: bold; font-size: 14px; display: inline-block; box-shadow: 0 2px 4px rgba(15, 118, 110, 0.2);">
              Download Form 10BE Certificate
            </a>
            <p style="font-size: 11px; color: #64748b; margin-top: 10px;">
              Requires logging into your verified donor account for data privacy.
            </p>
          </div>

          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
          <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0;">
            DaanGives Foundation • Transparent Non-Profit Platform • <a href="mailto:support@daangives.org" style="color: #0f766e;">support@daangives.org</a>
          </p>
        </div>
        """

        # 8. Dispatch Email (No Attachment - Option B)
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email,
                to=[recipient_email],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=False)

            # 9. Update state on success
            Form10BECertificate.objects.filter(id=cert.id).update(
                notification_sent=True,
                notification_send_count=F('notification_send_count') + 1,
                last_notification_sent_at=timezone.now(),
                last_notification_error='',
            )

            cert.refresh_from_db()

            return {
                'success': True,
                'message': 'Form 10BE availability notification sent successfully.',
                'recipient_email': recipient_email,
                'certificate_number': cert.certificate_number,
                'notification_send_count': cert.notification_send_count,
            }
        except Exception as err:
            err_msg = str(err)[:500]
            Form10BECertificate.objects.filter(id=cert.id).update(
                notification_send_count=F('notification_send_count') + 1,
                last_notification_error=err_msg,
            )
            return {
                'success': False,
                'message': 'Form 10BE notification email could not be sent. Please try again.',
                'error': err_msg,
            }


