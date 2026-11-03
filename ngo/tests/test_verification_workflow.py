"""
Comprehensive NGO Verification Workflow Tests
==============================================
Validates the multi-stage verification workflow and CSR eligibility rules:
1. Registration completed != verified / approved.
2. Initial government verification updates gov_check_status without auto-approving.
3. Admin approval is a separate mandatory final step.
4. General approval is strictly decoupled from Section 135 CSR verification.
5. CSR-1 validation requires registration number and supporting evidence.
6. 12A/80G conditional requirement — NGOs not claiming 12A/80G or claiming Section 10(23C) can complete submission.
7. Section 10(23C) exemption validation and statutory eligibility.
8. Admin manual government check recording.
9. Public CSR-1 badge reflects verified status, not self-declaration.
10. Project verification status is distinct from CSR readiness.
"""

from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from users.models import User
from ngo.models import (
    NGOProfile,
    NGOLegalInfo,
    NGOBankInfo,
    NGOAddress,
    NGODocument,
    NGOLeadership,
    NGOVerification,
    GovCheckStatus,
)
from ngo.services.submission_service import (
    validate_ngo_completeness,
    submit_ngo_application,
)
from ngo.services.verification_service import (
    change_ngo_verification_status,
    record_ngo_manual_verification,
)
from ngo.serializers import NGOPublicSerializer
from projects.models import Project, ProjectStatus
from projects.serializers import ProjectListSerializer, ProjectDetailSerializer
from ngo.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_legal_info,
    make_bank_info,
)


class NGOVerificationWorkflowTests(TestCase):
    """Integration and unit tests for the NGO verification pipeline."""

    def setUp(self):
        self.ngo_user = make_user(email='ngo_flow@test.org', role='NGO')
        self.admin_user = make_user(email='admin_flow@test.org', role='ADMIN')
        self.profile = make_ngo_profile(user=self.ngo_user, status=NGOProfile.Status.DRAFT)
        self.address = NGOAddress.objects.create(
            ngo=self.profile,
            address_line1='123 Ashram Road',
            city='Ahmedabad',
            district='Ahmedabad',
            state='Gujarat',
            pincode='380009',
        )
        self.bank = make_bank_info(ngo=self.profile)
        self.leader = NGOLeadership.objects.create(
            ngo=self.profile,
            full_name='Ramesh Patel',
            designation='Managing Trustee',
            email='ramesh@test.org',
            phone='+919876543210',
            is_primary_contact=True,
            is_active=True,
        )
        self.verification, _ = NGOVerification.objects.get_or_create(ngo=self.profile)

    def _attach_base_documents(self, profile):
        """Creates the standard required documents for completeness."""
        for doc_type in NGODocument.REQUIRED_DOCUMENT_TYPES:
            NGODocument.objects.create(
                ngo=profile,
                document_type=doc_type,
                file=f'{doc_type.lower()}.pdf',
                file_size_bytes=1024,
                uploaded_by=profile.user,
            )

    def test_point_1_unverified_ngo_is_not_public_or_approved(self):
        """Unverified NGO in DRAFT/SUBMITTED cannot be public or treated as approved."""
        self.assertEqual(self.profile.status, NGOProfile.Status.DRAFT)
        self.assertFalse(self.profile.is_public)
        self.assertFalse(self.verification.is_csr_verified)

    def test_point_2_government_verification_never_auto_approves(self):
        """Initial government verification runs on submission but never auto-approves."""
        legal = make_legal_info(
            ngo=self.profile,
            has_12a=False,
            has_80g=False,
            has_csr_1=False,
            pan_number='AAATT1234F',
            darpan_id='GJ/2010/01234',
        )
        self._attach_base_documents(self.profile)

        submit_ngo_application(self.profile, self.ngo_user)
        self.profile.refresh_from_db()
        self.verification.refresh_from_db()

        # Status must transition to SUBMITTED, NEVER APPROVED
        self.assertEqual(self.profile.status, NGOProfile.Status.SUBMITTED)
        self.assertFalse(self.profile.is_public)
        self.assertIn(
            self.verification.gov_check_status,
            [
                GovCheckStatus.GOVERNMENT_CHECK_PASSED,
                GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
            ],
        )

    def test_point_3_admin_verification_is_mandatory_step(self):
        """Passing government check is NOT approval. Admin must explicitly approve."""
        self.profile.status = NGOProfile.Status.SUBMITTED
        self.profile.save()
        self.verification.gov_check_status = GovCheckStatus.GOVERNMENT_CHECK_PASSED
        self.verification.save()

        # Admin starts review
        change_ngo_verification_status(
            ngo_profile=self.profile,
            new_status=NGOProfile.Status.UNDER_REVIEW,
            changed_by=self.admin_user,
            reason='Admin review commenced.',
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, NGOProfile.Status.UNDER_REVIEW)

        # Admin approves
        change_ngo_verification_status(
            ngo_profile=self.profile,
            new_status=NGOProfile.Status.APPROVED,
            changed_by=self.admin_user,
            reason='Application approved.',
            verify_csr=False,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, NGOProfile.Status.APPROVED)
        self.assertTrue(self.profile.is_public)

    def test_point_4_separate_general_approval_from_csr_verification(self):
        """General approval is separate from CSR verification; un-eligible NGO cannot be CSR verified."""
        # Non-CSR eligible legal info
        legal = make_legal_info(
            ngo=self.profile,
            has_12a=False,
            has_80g=False,
            has_csr_1=False,
        )
        self.assertFalse(legal.is_csr_eligible)

        self.profile.status = NGOProfile.Status.UNDER_REVIEW
        self.profile.save()

        # Approving with verify_csr=True when ineligible must raise ValidationError
        with self.assertRaises(ValidationError):
            change_ngo_verification_status(
                ngo_profile=self.profile,
                new_status=NGOProfile.Status.APPROVED,
                changed_by=self.admin_user,
                reason='Attempting invalid CSR approval',
                verify_csr=True,
                csr_review_notes='Attempting invalid CSR approval',
            )

        # Standard general approval succeeds without CSR verification
        change_ngo_verification_status(
            ngo_profile=self.profile,
            new_status=NGOProfile.Status.APPROVED,
            changed_by=self.admin_user,
            reason='Standard non-profit approval.',
            verify_csr=False,
        )
        self.profile.refresh_from_db()
        self.verification.refresh_from_db()
        self.assertEqual(self.profile.status, NGOProfile.Status.APPROVED)
        self.assertFalse(self.verification.is_csr_verified)

    def test_point_5_csr_eligible_ngo_can_be_granted_csr_verification(self):
        """CSR eligible NGO (Trust + 3yr + 12A/80G + CSR-1) can be granted CSR verification."""
        self.profile.year_established = timezone.now().year - 4
        self.profile.save()
        legal = make_legal_info(
            ngo=self.profile,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            has_12a=True,
            twelve_a_number='12A-12345',
            has_80g=True,
            eighty_g_number='80G-12345',
            has_csr_1=True,
            csr_registration_number='CSR00012345',
            csr_registration_date=date(2022, 1, 1),
        )
        self.assertTrue(legal.is_csr_eligible)

        self.profile.status = NGOProfile.Status.UNDER_REVIEW
        self.profile.save()

        change_ngo_verification_status(
            ngo_profile=self.profile,
            new_status=NGOProfile.Status.APPROVED,
            changed_by=self.admin_user,
            reason='MCA21 Form CSR-1 verified. Section 135 approved.',
            verify_csr=True,
            csr_review_notes='MCA21 Form CSR-1 verified. Section 135 approved.',
        )
        self.profile.refresh_from_db()
        self.verification.refresh_from_db()
        self.assertEqual(self.profile.status, NGOProfile.Status.APPROVED)
        self.assertTrue(self.verification.is_csr_verified)
        self.assertIsNotNone(self.verification.csr_verified_at)
        self.assertEqual(self.verification.csr_review_notes, 'MCA21 Form CSR-1 verified. Section 135 approved.')

    def test_point_6_and_7_section_10_23c_satisfies_statutory_and_document_rules(self):
        """Section 10(23C) exemption provides an alternative to 12A/80G and satisfies completeness."""
        self.profile.year_established = timezone.now().year - 5
        self.profile.save()

        legal = make_legal_info(
            ngo=self.profile,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            has_12a=False,
            has_80g=False,
            has_10_23c=True,
            ten_23c_order_number='CIT/EXEMP/10_23C/2021',
            ten_23c_subclause='iv',
            has_csr_1=True,
            csr_registration_number='CSR00054321',
            csr_registration_date=date(2021, 6, 1),
        )
        legal.full_clean()
        self.assertTrue(legal.is_csr_eligible)

        # Base docs + TEN_23C_CERT + CSR_1_CERT
        self._attach_base_documents(self.profile)
        NGODocument.objects.create(
            ngo=self.profile,
            document_type=NGODocument.DocumentType.TEN_23C_CERT,
            file='ten23c.pdf',
            file_size_bytes=1024,
            uploaded_by=self.profile.user,
        )
        NGODocument.objects.create(
            ngo=self.profile,
            document_type=NGODocument.DocumentType.CSR_1_CERT,
            file='csr1.pdf',
            file_size_bytes=1024,
            uploaded_by=self.profile.user,
        )

        missing = validate_ngo_completeness(self.profile)
        self.assertEqual(missing, {}, f'Expected no missing requirements, got: {missing}')

    def test_point_12_record_ngo_manual_verification(self):
        """Admin can record a manual government registry check outcome."""
        record_ngo_manual_verification(
            admin_user=self.admin_user,
            ngo_profile=self.profile,
            outcome=GovCheckStatus.GOVERNMENT_CHECK_PASSED,
            source='MCA MCA21 CSR-1 Portal',
            notes='CSR-1 CRN matched active MCA company record.',
        )
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.gov_check_status, GovCheckStatus.GOVERNMENT_CHECK_PASSED)
        self.assertEqual(self.verification.gov_check_source, 'MCA MCA21 CSR-1 Portal')
        self.assertEqual(self.verification.gov_check_details.get('outcome'), GovCheckStatus.GOVERNMENT_CHECK_PASSED)
        self.assertEqual(self.verification.gov_check_details.get('recorded_by'), self.admin_user.email)

    def test_point_17_public_badge_reflects_verified_status_not_self_declaration(self):
        """NGOPublicSerializer exposes is_csr_verified strictly from admin-approved status."""
        legal = make_legal_info(
            ngo=self.profile,
            has_csr_1=True,
            csr_registration_number='CSR00099999',
        )
        self.profile.status = NGOProfile.Status.APPROVED
        self.profile.is_active = True
        self.profile.save()

        # Initially, is_csr_verified is False
        self.verification.is_csr_verified = False
        self.verification.save()
        self.profile.refresh_from_db()

        ser = NGOPublicSerializer(self.profile)
        self.assertTrue(ser.data['has_csr_1'])
        self.assertFalse(ser.data['is_csr_verified'])

        # Now admin grants CSR verification
        self.verification.is_csr_verified = True
        self.verification.save()
        self.profile.refresh_from_db()

        ser = NGOPublicSerializer(self.profile)
        self.assertTrue(ser.data['is_csr_verified'])

    def test_point_18_project_verification_distinct_from_csr_readiness(self):
        """Project model & serializers expose is_csr_ready independently from project status."""
        self.profile.status = NGOProfile.Status.APPROVED
        self.profile.is_active = True
        self.profile.year_established = timezone.now().year - 4
        self.profile.save()

        legal = make_legal_info(
            ngo=self.profile,
            organisation_type=NGOLegalInfo.OrgType.TRUST,
            has_12a=True,
            twelve_a_number='12A-12345',
            has_80g=True,
            eighty_g_number='80G-12345',
            has_csr_1=True,
            csr_registration_number='CSR00012345',
            csr_registration_date=date(2022, 1, 1),
        )
        self.assertTrue(legal.is_csr_eligible)

        # NGO is not CSR verified yet
        self.verification.is_csr_verified = False
        self.verification.save()

        project = Project.objects.create(
            organization=self.profile,
            posted_by=self.ngo_user,
            title='Clean Drinking Water Initiative',
            short_summary='Providing clean water units to primary schools.',
            category='HEALTH',
            location_state='Gujarat',
            location_district='Patan',
            location_village='Sidhpur',
            estimated_cost=250000,
            timeline_months=6,
            status=ProjectStatus.SUBMITTED,
        )
        # In SUBMITTED status, project is not verified -> is_csr_ready is False
        self.assertFalse(project.is_csr_ready)

        # Admin verifies project, but NGO is still not CSR-verified
        project.status = ProjectStatus.VERIFIED
        project.save()
        self.assertFalse(project.is_csr_ready)

        list_ser = ProjectListSerializer(project)
        self.assertFalse(list_ser.data['is_csr_ready'])

        # When NGO is granted Section 135 CSR verification, project becomes CSR ready
        self.verification.is_csr_verified = True
        self.verification.save()
        self.profile.refresh_from_db()
        project.refresh_from_db()
        self.assertTrue(project.is_csr_ready)

        detail_ser = ProjectDetailSerializer(project)
        self.assertTrue(detail_ser.data['is_csr_ready'])
