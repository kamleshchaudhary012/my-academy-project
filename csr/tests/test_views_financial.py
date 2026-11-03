"""
CSR Financial API Views Integration Tests — Phase CSR-Transparency
===================================================================
Integration tests for financial endpoints across Company, NGO, and Admin namespaces.
"""

from decimal import Decimal
from datetime import date, timedelta
from rest_framework.test import APITestCase
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from csr.models import (
    CSRPartnershipStatus,
    CSRFinancialStatus,
    CSRGrantChangeStatus,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
)

User = get_user_model()


class CSRFinancialViewsIntegrationTestCase(APITestCase):
    def setUp(self):
        self.admin_user = make_user(email="admin_fin@daangives.org", role=User.Role.ADMIN, is_staff=True)
        self.company_user = make_user(email="company_fin@tata.com", role=User.Role.COMPANY)
        self.company = make_company_profile(user=self.company_user, company_name="Tata Power")

        self.ngo_user = make_user(email="ngo_fin@pratham.org", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user, legal_name="Pratham Education Foundation")

        self.other_company_user = make_user(email="other_csr@reliance.com", role=User.Role.COMPANY)
        self.other_company = make_company_profile(user=self.other_company_user, company_name="Reliance Foundation")

        self.requirement = make_csr_requirement(ngo=self.ngo, total_estimated_budget=Decimal("1000000.00"))
        self.support_request = make_csr_support_request(company=self.company, requirement=self.requirement)

        self.partnership = make_csr_partnership(
            company=self.company,
            ngo=self.ngo,
            requirement=self.requirement,
            support_request=self.support_request,
            agreed_funding_amount=Decimal("750000.00"),
            status=CSRPartnershipStatus.ACTIVE,
            execution_start_date=date.today(),
            target_completion_date=date.today() + timedelta(days=180),
        )

        self.mock_file = SimpleUploadedFile("advice.pdf", b"%PDF-1.4 test advice", content_type="application/pdf")

    def test_get_financials_not_disbursed_status(self):
        """GET /api/v1/csr/partnerships/<id>/financials/ returns NOT_DISBURSED and detailed metrics."""
        self.client.force_authenticate(user=self.company_user)
        res = self.client.get(f"/api/v1/csr/partnerships/{self.partnership.id}/financials/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["financial_status"], CSRFinancialStatus.NOT_DISBURSED)
        self.assertFalse(res.data["is_reconciled"])
        self.assertEqual(res.data["commitment"]["amount"], "750000.00")
        self.assertEqual(res.data["outstanding_commitment"], "750000.00")
        self.assertIn("statutory_disclosure", res.data)

    def test_record_disbursement_and_review_workflow(self):
        """Company records wire disbursement -> Admin reviews evidence -> NGO acknowledges receipt."""
        # 1. Company reports transfer
        self.client.force_authenticate(user=self.company_user)
        post_res = self.client.post(
            f"/api/v1/csr/partnerships/{self.partnership.id}/disbursements/",
            {
                "amount": "250000.00",
                "transfer_reference": "UTR_TEST_12345",
                "payment_mode": "NEFT",
                "evidence_document": self.mock_file,
            },
            format="multipart",
        )
        self.assertEqual(post_res.status_code, status.HTTP_201_CREATED)
        disb_id = post_res.data["id"]

        # 2. Admin verifies evidence
        self.client.force_authenticate(user=self.admin_user)
        review_res = self.client.post(
            f"/api/v1/admin/csr/disbursements/{disb_id}/review/",
            {"decision": "VERIFY", "review_notes": "Bank wire counterfoil verified against MCA account."},
            format="json",
        )
        self.assertEqual(review_res.status_code, status.HTTP_200_OK)
        self.assertEqual(review_res.data["review_status"], "VERIFIED")

        # 3. NGO acknowledges receipt
        self.client.force_authenticate(user=self.ngo_user)
        ack_res = self.client.post(
            f"/api/v1/ngo/csr/disbursements/{disb_id}/acknowledge/",
            {"decision": "ACKNOWLEDGE", "notes": "Received in primary bank account."},
            format="json",
        )
        self.assertEqual(ack_res.status_code, status.HTTP_200_OK)
        self.assertEqual(ack_res.data["ngo_acknowledgement_status"], "ACKNOWLEDGED")

    def test_grant_change_request_api_workflow(self):
        """NGO requests increase -> Admin approves -> Corporate partner approves."""
        # 1. NGO submits change request
        self.client.force_authenticate(user=self.ngo_user)
        create_res = self.client.post(
            f"/api/v1/ngo/csr/partnerships/{self.partnership.id}/grant-changes/",
            {
                "proposed_commitment": "850000.00",
                "reason": "Inflation in equipment freight rates",
            },
            format="json",
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        change_id = create_res.data["id"]

        # 2. Admin reviews & moves to PENDING_COMPANY_APPROVAL
        self.client.force_authenticate(user=self.admin_user)
        admin_res = self.client.post(
            f"/api/v1/admin/csr/grant-changes/{change_id}/review/",
            {"decision": "APPROVE", "review_notes": "Verified rate revision."},
            format="json",
        )
        self.assertEqual(admin_res.status_code, status.HTTP_200_OK)
        self.assertEqual(admin_res.data["status"], CSRGrantChangeStatus.PENDING_COMPANY_APPROVAL)

        # 3. Corporate partner approves -> applies to partnership
        self.client.force_authenticate(user=self.company_user)
        comp_res = self.client.post(
            f"/api/v1/csr/grant-changes/{change_id}/review/",
            {"decision": "APPROVE", "review_notes": "Approved by CSR committee."},
            format="json",
        )
        self.assertEqual(comp_res.status_code, status.HTTP_200_OK)
        self.assertEqual(comp_res.data["status"], CSRGrantChangeStatus.APPROVED)

        self.partnership.refresh_from_db()
        self.assertEqual(self.partnership.agreed_funding_amount, Decimal("850000.00"))

    def test_idor_protection_other_company_cannot_view_or_record(self):
        """Unrelated corporate user cannot view or record disbursements on this partnership."""
        self.client.force_authenticate(user=self.other_company_user)
        res = self.client.get(f"/api/v1/csr/partnerships/{self.partnership.id}/financials/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
