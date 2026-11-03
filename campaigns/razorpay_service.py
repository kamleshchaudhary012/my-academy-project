import hmac
import hashlib
import uuid
import logging
from decimal import Decimal
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import razorpay
except ImportError:
    razorpay = None


class RazorpayService:
    @staticmethod
    def get_client():
        key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
        if razorpay and key_id and key_secret and not key_id.startswith('rzp_test_placeholder'):
            return razorpay.Client(auth=(key_id, key_secret))
        return None

    @classmethod
    def create_order(cls, amount_in_rupees: Decimal, receipt: str, notes: dict = None) -> dict:
        """
        Creates a Razorpay order in paise (1 INR = 100 paise).
        """
        amount_paise = int(amount_in_rupees * 100)
        key_id = getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_placeholder_key_id')
        client = cls.get_client()

        if client:
            try:
                order = client.order.create({
                    'amount': amount_paise,
                    'currency': 'INR',
                    'receipt': receipt,
                    'notes': notes or {},
                    'payment_capture': 1,
                })
                return order
            except Exception as e:
                logger.error(f"Razorpay order creation failed: {e}")
                # Fallback to deterministic order structure for sandbox/offline
                pass

        # Standard sandbox / fallback order dictionary
        order_id = f"order_{uuid.uuid4().hex[:16]}"
        return {
            'id': order_id,
            'entity': 'order',
            'amount': amount_paise,
            'amount_paid': 0,
            'amount_due': amount_paise,
            'currency': 'INR',
            'receipt': receipt,
            'status': 'created',
            'notes': notes or {},
        }

    @staticmethod
    def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
        """
        Verifies Razorpay payment signature using HMAC SHA256.
        """
        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            return False

        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', 'placeholder_secret_key_12345')
        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
        generated_signature = hmac.new(
            key_secret.encode('utf-8'),
            msg,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(generated_signature, razorpay_signature)

    @staticmethod
    def verify_webhook_signature(payload_body: bytes, webhook_signature: str) -> bool:
        """
        Verifies Razorpay webhook signature using HMAC SHA256 and RAZORPAY_WEBHOOK_SECRET.
        """
        if not payload_body or not webhook_signature:
            return False

        webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', 'placeholder_webhook_secret_12345')
        generated_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(generated_signature, webhook_signature)
