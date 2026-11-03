"""
Unit Tests for CSRPartnership Model
===================================
Tests CSRPartnership creation, relationships, date constraints, and informational financial bounds.
Zero payment gateway or financial ledger mutation is performed.
"""

import shutil
import tempfile
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from csr.models import (
    CSRPartnership,
    CSRPartnershipStatus,
    CSRSupportRequestStatus,
    partnership_mou_doc_path,
)
from csr.tests.helpers import (
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_dummy_uploaded_file,
)


class CSRPartnershipModelTests(TestCase):
    """Test suite for CSRPartnership model behavior."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.company = make_company_profile()
        self.ngo = make_ngo_profile()
        self.requirement = make_csr_requirement(ngo=self.ngo)
        self.support_request = make_csr_support_request(
            company=self.company,
            requirement=self.requirement,
            status=CSRSupportRequestStatus.ACCEPTED,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_create_valid_csr_partnership(self):
        """Creates a valid CSRPartnership and verifies fields."""
        today = date.today()
        partnership = CSRPartnership.objects.create(
            company=self.company,
            ngo=self.ngo,
            requirement=self.requirement,
            support_request=self.support_request,
            partnership_code='CSR-PART-2026-0001',
            agreed_funding_amount=Decimal('500000.00'),
            disbursed_amount_reported=Decimal('0.00'),
            execution_start_date=today,
            target_completion_date=today + timedelta(days=180),
            status=CSRPartnershipStatus.PENDING_MOU,
        )
        self.assertIsInstance(partnership.id, uuid.UUID)
        self.assertEqual(partnership.company, self.company)
        self.assertEqual(partnership.ngo, self.ngo)
        self.assertEqual(partnership.requirement, self.requirement)
        self.assertEqual(partnership.support_request, self.support_request)
        self.assertEqual(partnership.partnership_code, 'CSR-PART-2026-0001')
        self.assertEqual(partnership.agreed_funding_amount, Decimal('500000.00'))
        self.assertEqual(partnership.disbursed_amount_reported, Decimal('0.00'))
        self.assertEqual(partnership.status, CSRPartnershipStatus.PENDING_MOU)
        self.assertIsNotNone(partnership.created_at)
        self.assertIsNotNone(partnership.updated_at)
        self.assertEqual(str(partnership), f"Partnership CSR-PART-2026-0001 ({CSRPartnershipStatus.PENDING_MOU})")

    def test_partnership_code_uniqueness_enforced_at_db(self):
        """Duplicate partnership_code values must raise IntegrityError at DB level."""
        shared_code = 'CSR-CODE-UNIQUE-101'
        make_csr_partnership(partnership_code=shared_code)

        sr2 = make_csr_support_request(status=CSRSupportRequestStatus.ACCEPTED)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_partnership(support_request=sr2, partnership_code=shared_code)

    def test_onetoone_with_support_request(self):
        """A single support request can only link to at most one CSRPartnership."""
        make_csr_partnership(support_request=self.support_request)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_csr_partnership(support_request=self.support_request)

    def test_disbursed_amount_reported_informational_boundary(self):
        """
        disbursed_amount_reported is strictly informational off-platform reporting.
        Updating disbursed amount must NOT trigger or require on-platform payment objects.
        """
        partnership = make_csr_partnership(
            support_request=self.support_request,
            agreed_funding_amount=Decimal('500000.00'),
            disbursed_amount_reported=Decimal('250000.00'),
            status=CSRPartnershipStatus.ACTIVE,
        )
        self.assertEqual(partnership.disbursed_amount_reported, Decimal('250000.00'))
        # Incremental disbursement report
        partnership.disbursed_amount_reported = Decimal('500000.00')
        partnership.save()
        partnership.refresh_from_db()
        self.assertEqual(partnership.disbursed_amount_reported, Decimal('500000.00'))

    def test_status_choices_lifecycle(self):
        """CSRPartnership supports all 6 frozen lifecycle status choices."""
        partnership = make_csr_partnership(support_request=self.support_request)
        for status in CSRPartnershipStatus.values:
            partnership.status = status
            partnership.save()
            partnership.refresh_from_db()
            self.assertEqual(partnership.status, status)

    def test_signed_mou_document_upload_and_path(self):
        """Signed MoU document file is correctly uploaded to isolated private path."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            partnership = make_csr_partnership(support_request=self.support_request)
            mou_file = make_dummy_uploaded_file(name='signed_mou.pdf')
            partnership.signed_mou_document = mou_file
            partnership.save()

            self.assertTrue(partnership.signed_mou_document.name.startswith(f'csr_docs/mous/{partnership.id}/'))
            self.assertTrue(partnership.signed_mou_document.name.endswith('.pdf'))

            # Test path function directly
            gen_path = partnership_mou_doc_path(partnership, 'mou.pdf')
            self.assertTrue(gen_path.startswith(f'csr_docs/mous/{partnership.id}/'))

    def test_full_clean_minimum_funding_validation(self):
        """full_clean() validates agreed_funding_amount >= 1000.00 and disbursed >= 0."""
        today = date.today()
        p = CSRPartnership(
            company=self.company,
            ngo=self.ngo,
            requirement=self.requirement,
            support_request=self.support_request,
            partnership_code='CODE-TEST',
            agreed_funding_amount=Decimal('999.00'),      # Below min 1000.00
            disbursed_amount_reported=Decimal('-10.00'), # Below min 0.00
            execution_start_date=today,
            target_completion_date=today + timedelta(days=90),
        )
        with self.assertRaises(ValidationError) as ctx:
            p.full_clean()
        self.assertIn('agreed_funding_amount', ctx.exception.message_dict)
        self.assertIn('disbursed_amount_reported', ctx.exception.message_dict)
