"""
Unit Tests for CSR Model Validators
===================================
Tests custom validator functions defined in csr.models:
- validate_cin_number
- validate_pan_number
- validate_pincode
- validate_phone
- validate_document_extension
"""

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from csr.models import (
    validate_cin_number,
    validate_pan_number,
    validate_pincode,
    validate_phone,
    validate_document_extension,
)


class CSRValidatorTests(SimpleTestCase):
    """Test suite for CSR domain validation functions."""

    # -----------------------------------------------------------------------
    # CIN Validator Tests
    # -----------------------------------------------------------------------

    def test_valid_cin_number_passes(self):
        """Standard 21-character MCA CIN formats must pass validation."""
        valid_cins = [
            'L12345MH2020PLC123456',
            'U54321DL2015PTC654321',
            'L99999KA2001GOI999999',
            'U00000TN2018NPL000001',
        ]
        for cin in valid_cins:
            with self.subTest(cin=cin):
                try:
                    validate_cin_number(cin)
                except ValidationError:
                    self.fail(f"validate_cin_number raised ValidationError unexpectedly for valid CIN: {cin}")

    def test_cin_number_none_or_empty_passes(self):
        """None or empty CIN should not raise ValidationError directly (handled by blank/null)."""
        validate_cin_number(None)
        validate_cin_number('')

    def test_invalid_cin_numbers_fail(self):
        """Non-conforming CIN patterns must raise ValidationError."""
        invalid_cins = [
            'A12345MH2020PLC123456',   # Does not start with L or U
            'L1234MH2020PLC123456',    # 4 digits instead of 5
            'L123456MH2020PLC123456',  # 6 digits instead of 5
            'L12345M2020PLC123456',    # 1 state char instead of 2
            'L12345MH202PLC123456',    # 3-digit year
            'L12345MH2020PL123456',    # 2 company type chars instead of 3
            'L12345MH2020PLC12345',    # 5 serial digits instead of 6
            'l12345mh2020plc123456',   # lowercase
            'L12345MH2020PLC12345@',   # special characters
            'INVALID_CIN_FORMAT',
        ]
        for cin in invalid_cins:
            with self.subTest(cin=cin):
                with self.assertRaises(ValidationError, msg=f"Failed to reject invalid CIN: {cin}"):
                    validate_cin_number(cin)

    # -----------------------------------------------------------------------
    # PAN Validator Tests
    # -----------------------------------------------------------------------

    def test_valid_pan_number_passes(self):
        """Standard 10-character Indian Income Tax PANs must pass validation."""
        valid_pans = [
            'ABCDE1234F',
            'AABCA1234C',
            'ZZZZZ9999Z',
            'AAAAA0001A',
        ]
        for pan in valid_pans:
            with self.subTest(pan=pan):
                try:
                    validate_pan_number(pan)
                except ValidationError:
                    self.fail(f"validate_pan_number raised ValidationError unexpectedly for valid PAN: {pan}")

    def test_pan_number_none_or_empty_passes(self):
        """None or empty PAN should not raise ValidationError directly."""
        validate_pan_number(None)
        validate_pan_number('')

    def test_invalid_pan_numbers_fail(self):
        """Non-conforming PAN patterns must raise ValidationError."""
        invalid_pans = [
            'ABCD1234F',     # 4 leading letters instead of 5
            'ABCDEF1234F',   # 6 leading letters instead of 5
            'ABCDE123F',     # 3 digits instead of 4
            'ABCDE12345F',   # 5 digits instead of 4
            'ABCDE1234',     # missing trailing letter
            'ABCDE12345',    # missing trailing letter (digits)
            'abcde1234f',    # lowercase
            'ABCDE1234@',    # special characters
            'NOTAPAN123',
        ]
        for pan in invalid_pans:
            with self.subTest(pan=pan):
                with self.assertRaises(ValidationError, msg=f"Failed to reject invalid PAN: {pan}"):
                    validate_pan_number(pan)

    # -----------------------------------------------------------------------
    # PIN Code Validator Tests
    # -----------------------------------------------------------------------

    def test_valid_pincode_passes(self):
        """Valid 6-digit Indian PIN codes must pass validation."""
        valid_pincodes = ['400051', '110001', '560001', '700001', '380001']
        for pin in valid_pincodes:
            with self.subTest(pin=pin):
                try:
                    validate_pincode(pin)
                except ValidationError:
                    self.fail(f"validate_pincode raised ValidationError unexpectedly for valid PIN: {pin}")

    def test_pincode_none_or_empty_passes(self):
        """None or empty pincode passes validator function."""
        validate_pincode(None)
        validate_pincode('')

    def test_invalid_pincodes_fail(self):
        """Non-6-digit PIN codes must raise ValidationError."""
        invalid_pins = [
            '40005',     # 5 digits
            '4000511',   # 7 digits
            '40005A',    # alphanumeric
            '400-51',    # hyphenated
            'MUMBAI',    # text
            '00 000',    # space
        ]
        for pin in invalid_pins:
            with self.subTest(pin=pin):
                with self.assertRaises(ValidationError, msg=f"Failed to reject invalid PIN: {pin}"):
                    validate_pincode(pin)

    # -----------------------------------------------------------------------
    # Phone Validator Tests
    # -----------------------------------------------------------------------

    def test_valid_phone_passes(self):
        """Valid contact phone strings (7-20 chars) must pass validation."""
        valid_phones = [
            '+919876543210',
            '9876543210',
            '+91-22-12345678',
            '022 12345678',
            '+1-555-123-4567',
            '1234567',
        ]
        for phone in valid_phones:
            with self.subTest(phone=phone):
                try:
                    validate_phone(phone)
                except ValidationError:
                    self.fail(f"validate_phone raised ValidationError unexpectedly for valid phone: {phone}")

    def test_phone_none_or_empty_passes(self):
        """None or empty phone passes validator function."""
        validate_phone(None)
        validate_phone('')

    def test_invalid_phones_fail(self):
        """Invalid phone strings must raise ValidationError."""
        invalid_phones = [
            '123456',                     # < 7 characters
            '+919876543210123456789',    # > 20 characters
            '+919876543210abc',          # alphabetic characters
            'call-me-now',               # non-phone characters
            '+91 (022) 1234567',         # parentheses not in allowed regex ^[\+\d\s\-]{7,20}$
        ]
        for phone in invalid_phones:
            with self.subTest(phone=phone):
                with self.assertRaises(ValidationError, msg=f"Failed to reject invalid phone: {phone}"):
                    validate_phone(phone)

    # -----------------------------------------------------------------------
    # Document Extension Validator Tests
    # -----------------------------------------------------------------------

    def test_valid_document_extensions_pass(self):
        """Allowed file extensions (.pdf, .jpg, .jpeg, .png) must pass validation."""
        valid_files = [
            SimpleUploadedFile('document.pdf', b'%PDF-1.4 dummy', content_type='application/pdf'),
            SimpleUploadedFile('photo.jpg', b'dummy_jpg', content_type='image/jpeg'),
            SimpleUploadedFile('photo.jpeg', b'dummy_jpeg', content_type='image/jpeg'),
            SimpleUploadedFile('graphic.png', b'dummy_png', content_type='image/png'),
            SimpleUploadedFile('DOCUMENT.PDF', b'%PDF-1.4 dummy', content_type='application/pdf'),
            SimpleUploadedFile('IMAGE.PNG', b'dummy_png', content_type='image/png'),
        ]
        for f in valid_files:
            with self.subTest(filename=f.name):
                try:
                    validate_document_extension(f)
                except ValidationError:
                    self.fail(f"validate_document_extension raised ValidationError for valid file: {f.name}")

    def test_document_extension_none_passes(self):
        """None file value passes validator function."""
        validate_document_extension(None)

    def test_invalid_document_extensions_fail(self):
        """Disallowed file extensions must raise ValidationError."""
        invalid_files = [
            SimpleUploadedFile('script.exe', b'binary', content_type='application/octet-stream'),
            SimpleUploadedFile('shell.sh', b'echo hello', content_type='text/x-sh'),
            SimpleUploadedFile('document.docx', b'word doc', content_type='application/vnd.openxmlformats'),
            SimpleUploadedFile('archive.zip', b'zip data', content_type='application/zip'),
            SimpleUploadedFile('vector.svg', b'<svg></svg>', content_type='image/svg+xml'),
            SimpleUploadedFile('code.py', b'print(1)', content_type='text/x-python'),
        ]
        for f in invalid_files:
            with self.subTest(filename=f.name):
                with self.assertRaises(ValidationError, msg=f"Failed to reject disallowed file: {f.name}"):
                    validate_document_extension(f)
