"""
CSR Company Verification Workflow & CSR Eligibility Enforcement Tests
=====================================================================
Validates:
1. Company registration completed != verified / approved.
2. Initial company government verification updates gov_check_status without auto-approving.
3. Admin company approval is a separate mandatory final step.
4. Company correction requested workflow (CORRECTION_REQUIRED -> resubmission).
5. P0-1 Backend CSR Eligibility Bypass Fix:
   - Unapproved or non-CSR verified NGO blocked from create_requirement.
   - Non-CSR verified NGO blocked from accept_support_request.
   - Non-CSR verified NGO blocked from create_partnership_from_request.
   - Off-platform disbursement recorded safely without payment gateway.
6. Admin manual company government check recording.
7. Company cannot partner with unapproved or non-CSR verified NGO.
"""

from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase

from users.models import User
from ngo.models import NGOProfile, NGOLegalInfo, NGOVerification, GovCheckStatus
from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    CSRRequirementStatus,
    CSRSupportRequestStatus,
    CSRSupportType,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
)
from csr.services.exceptions import (
    CSROwnershipError,
    CSRPermissionError,
    CSRValidationError,
)
from csr.services.company_service import (
    request_company_verification,
)
from csr.services.verification_service import (
    approve_company,
    request_company_corrections,
    record_company_manual_verification,
)
from csr.services.requirement_service import (
    create_requirement,
)
from csr.services.support_request_service import (
    accept_support_request,
)
from csr.services.partnership_service import (
    create_partnership_from_request,
    record_off_platform_disbursement,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_company_preference,
    make_csr_requirement,
    make_csr_support_request,
)


class CSRVerificationEnforcementTests(TestCase):
    """Integration tests for company verification and P0-1 CSR eligibility enforcement."""

    def setUp(self):
        self.admin_user = make_user(email='admin_csr@test.com', role=User.Role.ADMIN)
        self.company_user = make_user(email='company_user@test.com', role=User.Role.COMPANY)
        self.company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.DRAFT,
        )
        make_company_preference(company=self.company)

        # NGO user with an approved NGO profile
        self.ngo_user = make_user(email='ngo_csr_enforce@test.org', role=User.Role.NGO)
        self.ngo = make_ngo_profile(
            user=self.ngo_user,
            status=NGOProfile.Status.APPROVED,
        )
        self.ngo.is_active = True
        self.ngo.save()

        self.legal = self.ngo.legal_info
        self.verification = self.ngo.verification

    def test_point_8_and_9_company_gov_check_does_not_auto_approve(self):
        """Requesting verification triggers government check but sets PENDING_VERIFICATION, not APPROVED."""
        self.assertEqual(self.company.verification_status, CompanyVerificationStatus.DRAFT)
        self.company.verification_document = 'test_coi.pdf'
        self.company.save()

        updated = request_company_verification(self.company.user)
        self.company.refresh_from_db()

        self.assertEqual(self.company.verification_status, CompanyVerificationStatus.PENDING_VERIFICATION)
        self.assertIn(
            self.company.gov_check_status,
            [
                GovCheckStatus.GOVERNMENT_CHECK_PASSED,
                GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
            ],
        )

    def test_point_10_admin_approval_is_mandatory_for_company(self):
        """Admin must explicitly approve company to transition to APPROVED."""
        self.company.verification_status = CompanyVerificationStatus.PENDING_VERIFICATION
        self.company.save()

        approved = approve_company(
            admin_user=self.admin_user,
            company_id=self.company.id,
            review_notes='MCA verified and authenticated.',
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.verification_status, CompanyVerificationStatus.APPROVED)
        self.assertEqual(self.company.verified_by, self.admin_user)
        self.assertEqual(self.company.admin_notes, 'MCA verified and authenticated.')

    def test_point_11_company_correction_workflow(self):
        """Admin can request corrections; company can resubmit from CORRECTION_REQUIRED."""
        self.company.verification_status = CompanyVerificationStatus.PENDING_VERIFICATION
        self.company.save()

        # Admin requests correction
        corrected = request_company_corrections(
            admin_user=self.admin_user,
            company_id=self.company.id,
            correction_instructions='Please upload official MCA Certificate of Incorporation.',
            admin_notes='CIN valid, doc missing.',
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.verification_status, CompanyVerificationStatus.CORRECTION_REQUIRED)
        self.assertEqual(
            self.company.correction_instructions,
            'Please upload official MCA Certificate of Incorporation.',
        )

        # Company resubmits
        self.company.verification_document = 'corrected_coi.pdf'
        self.company.save()

        resubmitted = request_company_verification(self.company.user)
        self.company.refresh_from_db()
        self.assertEqual(self.company.verification_status, CompanyVerificationStatus.PENDING_VERIFICATION)

        # Admin approves from resubmission
        approve_company(
            admin_user=self.admin_user,
            company_id=self.company.id,
            review_notes='Certificate verified.',
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.verification_status, CompanyVerificationStatus.APPROVED)

    def test_point_13a_p0_1_fix_non_csr_verified_ngo_cannot_create_requirement(self):
        """Non-CSR verified NGO cannot create CSR requirements."""
        today = date.today()
        req_data = {
            'title': 'School Digital Classroom Setup',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'target_beneficiary_count': 500,
            'summary': 'Setting up smart classrooms in rural schools.',
            'detailed_description': 'Detailed plan to install smart classrooms in 10 schools.',
            'expected_outcomes': '500 students benefit from digital learning tools.',
            'total_estimated_budget': Decimal('500000.00'),
            'required_csr_funding': Decimal('400000.00'),
            'start_date': today,
            'expected_completion_date': today + timedelta(days=180),
            'state': 'Gujarat',
            'district': 'Ahmedabad',
        }

        # Case 1: NGO is not CSR eligible
        self.legal.has_csr_1 = False
        self.legal.save()
        self.verification.is_csr_verified = False
        self.verification.save()
        self.ngo.refresh_from_db()

        with self.assertRaises(CSROwnershipError):
            create_requirement(self.ngo.user, req_data)

        # Case 2: NGO is legally CSR eligible, but admin has not granted is_csr_verified
        self.legal.has_12a = True
        self.legal.twelve_a_number = '12A-11111'
        self.legal.has_80g = True
        self.legal.eighty_g_number = '80G-11111'
        self.legal.has_csr_1 = True
        self.legal.csr_registration_number = 'CSR00011111'
        self.legal.save()
        self.verification.is_csr_verified = False
        self.verification.save()
        self.ngo.refresh_from_db()

        with self.assertRaises(CSROwnershipError):
            create_requirement(self.ngo.user, req_data)

        # Case 3: Admin grants is_csr_verified -> Creation succeeds
        self.verification.is_csr_verified = True
        self.verification.save()
        self.ngo.refresh_from_db()

        req = create_requirement(self.ngo.user, req_data)
        self.assertIsNotNone(req.id)
        self.assertEqual(req.status, CSRRequirementStatus.DRAFT)

    def test_point_13b_p0_1_fix_non_csr_verified_ngo_cannot_accept_support_request(self):
        """Non-CSR verified NGO cannot accept CSR support requests."""
        self.legal.has_12a = True
        self.legal.twelve_a_number = '12A-11111'
        self.legal.has_80g = True
        self.legal.eighty_g_number = '80G-11111'
        self.legal.has_csr_1 = True
        self.legal.csr_registration_number = 'CSR00011111'
        self.legal.save()
        self.verification.is_csr_verified = True
        self.verification.save()

        self.company.verification_status = CompanyVerificationStatus.APPROVED
        self.company.save()

        req = make_csr_requirement(
            ngo=self.ngo,
            created_by=self.ngo.user,
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )

        support_req = make_csr_support_request(
            company=self.company,
            requirement=req,
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        # NGO loses CSR verification (e.g. revoked)
        self.verification.is_csr_verified = False
        self.verification.save()
        self.ngo.refresh_from_db()

        with self.assertRaises(CSROwnershipError):
            accept_support_request(self.ngo.user, support_req.id, {})

        # When CSR verified, acceptance succeeds
        self.verification.is_csr_verified = True
        self.verification.save()
        self.ngo.refresh_from_db()

        result = accept_support_request(self.ngo.user, support_req.id, {})
        accepted_req = result['support_request']
        self.assertEqual(accepted_req.status, CSRSupportRequestStatus.ACCEPTED)
        self.assertIsNotNone(result['partnership'])

    def test_point_13c_p0_1_fix_partnership_and_disbursement_guard(self):
        """Partnership formation requires both approved company and CSR-verified NGO."""
        self.legal.has_12a = True
        self.legal.twelve_a_number = '12A-11111'
        self.legal.has_80g = True
        self.legal.eighty_g_number = '80G-11111'
        self.legal.has_csr_1 = True
        self.legal.csr_registration_number = 'CSR00011111'
        self.legal.save()
        self.verification.is_csr_verified = True
        self.verification.save()

        self.company.verification_status = CompanyVerificationStatus.APPROVED
        self.company.save()

        req = make_csr_requirement(
            ngo=self.ngo,
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )

        support_req = make_csr_support_request(
            company=self.company,
            requirement=req,
            status=CSRSupportRequestStatus.ACCEPTED,
        )

        # 1. Company unapproved check
        self.company.verification_status = CompanyVerificationStatus.SUSPENDED
        self.company.save()

        with self.assertRaises(CSRValidationError):
            create_partnership_from_request(support_req)

        # 2. Re-approve company, but NGO loses CSR verification
        self.company.verification_status = CompanyVerificationStatus.APPROVED
        self.company.save()

        self.verification.is_csr_verified = False
        self.verification.save()
        self.ngo.refresh_from_db()
        support_req.refresh_from_db()

        with self.assertRaises(CSRValidationError):
            create_partnership_from_request(support_req)

        # 3. NGO is verified -> partnership creation succeeds
        self.verification.is_csr_verified = True
        self.verification.save()
        self.ngo.refresh_from_db()
        support_req.refresh_from_db()

        partnership = create_partnership_from_request(support_req)
        self.assertIsNotNone(partnership.id)

        # 4. Off-platform disbursement record
        disbursed = record_off_platform_disbursement(
            user=self.company.user,
            partnership_id=partnership.id,
            disbursed_amount=Decimal('100000.00'),
            notes='Direct NEFT/RTGS wire transfer ref UTR1234567890',
        )
        self.assertEqual(disbursed.disbursed_amount_reported, Decimal('100000.00'))

    def test_point_14_company_manual_government_check_recording(self):
        """Admin can record manual government check on Company."""
        record_company_manual_verification(
            admin_user=self.admin_user,
            company_id=self.company.id,
            outcome=GovCheckStatus.GOVERNMENT_CHECK_PASSED,
            source='MCA21 Company Master Data Portal',
            notes='CIN matches active MCA records.',
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.gov_check_status, GovCheckStatus.GOVERNMENT_CHECK_PASSED)
        self.assertEqual(self.company.gov_check_source, 'MCA21 Company Master Data Portal')
        self.assertEqual(self.company.gov_check_details.get('outcome'), GovCheckStatus.GOVERNMENT_CHECK_PASSED)
        self.assertEqual(self.company.gov_check_details.get('recorded_by'), self.admin_user.email)
