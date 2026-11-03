"""
Unit Tests for CSR Serializers — Phase CSR-2.1
==============================================
Tests serialization, deserialization, validations, bounds, read-only field immutability,
file representation safety, and DTO structures across all CSR serializers.
"""

import os
import tempfile
import shutil
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
    CSRVerificationHistory,
    CompanyVerificationStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CSRRequirementStatus,
    CSRSupportType,
    CSRSupportRequestStatus,
    CSRPartnershipStatus,
    MilestoneStatus,
    CSRAuditEntityType,
)
from csr.serializers import (
    CompanyProfileReadSerializer,
    CompanyProfileWriteSerializer,
    CompanyProfileAdminSerializer,
    CompanyCSRPreferenceSerializer,
    CSRRequirementListSerializer,
    CSRRequirementDetailSerializer,
    CSRRequirementWriteSerializer,
    CSRRequirementAdminSerializer,
    CSRSupportRequestCreateSerializer,
    CSRSupportRequestReadSerializer,
    CSRSupportRequestDecisionSerializer,
    CSRPartnershipListSerializer,
    CSRPartnershipDetailSerializer,
    CSRPartnershipDisbursementSerializer,
    PartnershipMilestoneSerializer,
    MilestoneEvidenceSubmitSerializer,
    MilestoneReviewSerializer,
    CSRVerificationHistorySerializer,
    CSRMatchResultSerializer,
)
from csr.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_company_profile,
    make_company_preference,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_partnership_milestone,
    make_verification_history,
    generate_valid_cin,
    generate_valid_pan,
    make_dummy_uploaded_file,
)


class CSRSerializerTests(TestCase):
    """Test suite covering all CSR domain serializers."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.ngo = make_ngo_profile()
        self.company = make_company_profile()

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    # -----------------------------------------------------------------------
    # 1. CompanyProfile Serializers
    # -----------------------------------------------------------------------

    def test_company_profile_read_serializer(self):
        """CompanyProfileReadSerializer correctly serializes and masks PAN."""
        serializer = CompanyProfileReadSerializer(instance=self.company)
        data = serializer.data

        self.assertEqual(data['id'], str(self.company.id))
        self.assertEqual(data['company_name'], self.company.company_name)
        self.assertTrue(data['has_pan'])
        self.assertTrue(data['pan_number_masked'].startswith('******'))
        self.assertEqual(data['pan_number_masked'], f"******{self.company.pan_number[-4:]}")
        self.assertFalse(data['has_verification_document'])
        self.assertIsNone(data['verification_document_name'])

    def test_company_profile_write_serializer_valid(self):
        """CompanyProfileWriteSerializer validates valid onboarding data."""
        cin = generate_valid_cin()
        pan = generate_valid_pan()
        payload = {
            'company_name': 'Tech Mahindra CSR Foundation',
            'legal_name': 'Tech Mahindra Limited',
            'cin_number': cin,
            'pan_number': pan,
            'contact_person_name': 'Amit Shah',
            'contact_person_designation': 'Director',
            'contact_email': 'csr@techm.com',
            'contact_phone': '+919876543210',
            'registered_address': 'Infotech Park, Hinjewadi',
            'city': 'Pune',
            'state': 'Maharashtra',
            'pincode': '411057',
            'annual_csr_budget': '25000000.00',
        }
        serializer = CompanyProfileWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['cin_number'], cin)
        self.assertEqual(serializer.validated_data['pan_number'], pan)

    def test_company_profile_write_serializer_invalid_cin_pan(self):
        """CompanyProfileWriteSerializer rejects malformed CIN and PAN."""
        payload = {
            'company_name': 'Bad Corp',
            'legal_name': 'Bad Corp Ltd',
            'cin_number': 'INVALID_CIN',
            'pan_number': 'BAD_PAN_1',
            'contact_person_name': 'John',
            'contact_person_designation': 'Lead',
            'contact_email': 'john@bad.com',
            'contact_phone': '123',  # Too short
            'registered_address': 'Address',
            'city': 'City',
            'state': 'State',
            'pincode': '123',  # Too short
            'annual_csr_budget': '-1000.00',  # Negative
        }
        serializer = CompanyProfileWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('cin_number', serializer.errors)
        self.assertIn('pan_number', serializer.errors)
        self.assertIn('pincode', serializer.errors)
        self.assertIn('contact_phone', serializer.errors)
        self.assertIn('annual_csr_budget', serializer.errors)

    def test_company_profile_admin_serializer(self):
        """CompanyProfileAdminSerializer exposes unmasked PAN and audit reviewer info."""
        admin_user = make_user(role='ADMIN')
        self.company.verified_by = admin_user
        self.company.verification_status = CompanyVerificationStatus.APPROVED
        self.company.save()

        serializer = CompanyProfileAdminSerializer(instance=self.company)
        data = serializer.data

        self.assertEqual(data['pan_number'], self.company.pan_number)
        self.assertEqual(data['user_email'], self.company.user.email)
        self.assertEqual(data['verified_by_email'], admin_user.email)
        self.assertEqual(data['verification_status'], CompanyVerificationStatus.APPROVED)

    # -----------------------------------------------------------------------
    # 2. CompanyCSRPreference Serializer
    # -----------------------------------------------------------------------

    def test_company_csr_preference_serializer_valid(self):
        """CompanyCSRPreferenceSerializer validates valid preference structure."""
        pref = make_company_preference(company=self.company)
        serializer = CompanyCSRPreferenceSerializer(instance=pref)
        data = serializer.data

        self.assertEqual(str(data['company']), str(self.company.id))
        self.assertEqual(data['company_name'], self.company.company_name)
        self.assertIn(ScheduleVIICategory.PROMOTING_EDUCATION, data['preferred_categories'])

    def test_company_csr_preference_serializer_invalid_choices(self):
        """CompanyCSRPreferenceSerializer rejects invalid choices and invalid duration."""
        payload = {
            'preferred_categories': ['NON_EXISTENT_CATEGORY'],
            'preferred_beneficiaries': ['INVALID_DEMOGRAPHIC'],
            'preferred_duration_months': 0,  # < 1
        }
        serializer = CompanyCSRPreferenceSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('preferred_categories', serializer.errors)
        self.assertIn('preferred_beneficiaries', serializer.errors)
        self.assertIn('preferred_duration_months', serializer.errors)

    def test_company_csr_preference_serializer_min_greater_than_max_budget(self):
        """CompanyCSRPreferenceSerializer rejects min_budget > max_budget in cross-field validation."""
        payload = {
            'preferred_categories': [ScheduleVIICategory.PROMOTING_EDUCATION],
            'preferred_beneficiaries': [BeneficiaryDemographic.CHILDREN_EDUCATION],
            'min_budget': '500000.00',
            'max_budget': '100000.00',  # min > max
            'preferred_duration_months': 12,
        }
        serializer = CompanyCSRPreferenceSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('min_budget', serializer.errors)

    # -----------------------------------------------------------------------
    # 3. CSRRequirement Serializers
    # -----------------------------------------------------------------------

    def test_csr_requirement_list_serializer(self):
        """CSRRequirementListSerializer produces compact marketplace representation."""
        req = make_csr_requirement(ngo=self.ngo)
        serializer = CSRRequirementListSerializer(instance=req)
        data = serializer.data

        self.assertEqual(data['id'], str(req.id))
        self.assertEqual(data['title'], req.title)
        self.assertEqual(data['ngo_legal_name'], self.ngo.legal_name)
        self.assertEqual(data['status'], req.status)
        self.assertNotIn('detailed_description', data)  # List should be compact

    def test_csr_requirement_detail_serializer(self):
        """CSRRequirementDetailSerializer produces comprehensive proposal view."""
        req = make_csr_requirement(ngo=self.ngo)
        serializer = CSRRequirementDetailSerializer(instance=req)
        data = serializer.data

        self.assertEqual(data['id'], str(req.id))
        self.assertEqual(data['detailed_description'], req.detailed_description)
        self.assertEqual(data['expected_outcomes'], req.expected_outcomes)
        self.assertFalse(data['has_proposal_document'])

    def test_csr_requirement_write_serializer_valid(self):
        """CSRRequirementWriteSerializer validates valid NGO proposal."""
        today = date.today()
        payload = {
            'title': 'Tribal Healthcare Clinic',
            'schedule_vii_category': ScheduleVIICategory.ERADICATING_HUNGER,
            'state': 'Odisha',
            'district': 'Koraput',
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'additional_districts': [],
            'beneficiary_demographic': BeneficiaryDemographic.HEALTHCARE_PATIENTS,
            'target_beneficiary_count': 1000,
            'summary': 'Setting up mobile health clinics for tribal communities.',
            'detailed_description': 'Full healthcare delivery mechanism with doctors and medicines.',
            'expected_outcomes': 'Direct healthcare access for 1000 tribal families.',
            'total_estimated_budget': '1000000.00',
            'required_csr_funding': '800000.00',
            'committed_funding': '200000.00',
            'start_date': str(today),
            'expected_completion_date': str(today + timedelta(days=365)),
        }
        serializer = CSRRequirementWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_csr_requirement_write_serializer_field_bounds(self):
        """CSRRequirementWriteSerializer rejects budgets below minimum threshold and negative committed funding."""
        payload = {
            'title': 'Invalid Project',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'summary': 'Summary',
            'detailed_description': 'Detailed',
            'expected_outcomes': 'Outcomes',
            'total_estimated_budget': '5000.00',    # < 10000
            'required_csr_funding': '5000.00',      # < 10000
            'committed_funding': '-100.00',         # < 0
        }
        serializer = CSRRequirementWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('total_estimated_budget', serializer.errors)
        self.assertIn('required_csr_funding', serializer.errors)
        self.assertIn('committed_funding', serializer.errors)

    def test_csr_requirement_write_serializer_cross_field_dates_and_funding(self):
        """CSRRequirementWriteSerializer cross-field validation rejects invalid date order and excessive funding."""
        today = date.today()
        payload = {
            'title': 'Invalid Project Cross Field',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'summary': 'Summary',
            'detailed_description': 'Detailed',
            'expected_outcomes': 'Outcomes',
            'total_estimated_budget': '100000.00',
            'required_csr_funding': '120000.00',    # > total budget
            'committed_funding': '10000.00',
            'start_date': str(today),
            'expected_completion_date': str(today - timedelta(days=5)),  # < start_date
        }
        serializer = CSRRequirementWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('required_csr_funding', serializer.errors)
        self.assertIn('expected_completion_date', serializer.errors)

    # -----------------------------------------------------------------------
    # 4. CSRSupportRequest Serializers
    # -----------------------------------------------------------------------

    def test_csr_support_request_create_serializer_valid(self):
        """CSRSupportRequestCreateSerializer validates valid grant proposal EOI."""
        req = make_csr_requirement(ngo=self.ngo)
        payload = {
            'requirement': str(req.id),
            'proposed_funding': '250000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'spoc_name': 'Neha Gupta',
            'spoc_email': 'neha@company.com',
            'spoc_phone': '+919876543210',
            'message': 'We are pleased to express our interest in funding this initiative.',
        }
        serializer = CSRSupportRequestCreateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_csr_support_request_create_serializer_invalid_funding_and_phone(self):
        """CSRSupportRequestCreateSerializer rejects funding below ₹1,000 and bad phone."""
        req = make_csr_requirement(ngo=self.ngo)
        payload = {
            'requirement': str(req.id),
            'proposed_funding': '500.00',  # < 1000
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'spoc_name': '',               # Blank
            'spoc_email': 'invalid_email', # Bad email
            'spoc_phone': '123',           # Bad phone
            'message': '',                 # Blank
        }
        serializer = CSRSupportRequestCreateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('proposed_funding', serializer.errors)
        self.assertIn('spoc_name', serializer.errors)
        self.assertIn('spoc_email', serializer.errors)
        self.assertIn('spoc_phone', serializer.errors)
        self.assertIn('message', serializer.errors)

    def test_csr_support_request_read_serializer(self):
        """CSRSupportRequestReadSerializer serializes company and requirement summaries."""
        sr = make_csr_support_request(company=self.company)
        serializer = CSRSupportRequestReadSerializer(instance=sr)
        data = serializer.data

        self.assertEqual(data['id'], str(sr.id))
        self.assertEqual(data['company_name'], self.company.company_name)
        self.assertEqual(data['requirement_title'], sr.requirement.title)
        self.assertEqual(data['status'], CSRSupportRequestStatus.PENDING_NGO_REVIEW)

    def test_csr_support_request_decision_serializer(self):
        """CSRSupportRequestDecisionSerializer validates decisions and requires reasons on rejection."""
        # Valid Accept
        s_accept = CSRSupportRequestDecisionSerializer(data={'action': 'ACCEPT'})
        self.assertTrue(s_accept.is_valid(), s_accept.errors)

        # Valid Reject with reason
        s_reject = CSRSupportRequestDecisionSerializer(data={'action': 'REJECT', 'reason': 'Budget mismatch'})
        self.assertTrue(s_reject.is_valid(), s_reject.errors)

        # Invalid Reject without reason
        s_reject_bad = CSRSupportRequestDecisionSerializer(data={'action': 'REJECT', 'reason': ''})
        self.assertFalse(s_reject_bad.is_valid())
        self.assertIn('reason', s_reject_bad.errors)

        # Invalid Action choice
        s_bad_act = CSRSupportRequestDecisionSerializer(data={'action': 'UNKNOWN'})
        self.assertFalse(s_bad_act.is_valid())

    # -----------------------------------------------------------------------
    # 5. CSRPartnership Serializers
    # -----------------------------------------------------------------------

    def test_csr_partnership_list_and_detail_serializers(self):
        """CSRPartnershipListSerializer and DetailSerializer serialize bilateral partnerships."""
        partnership = make_csr_partnership(company=self.company, ngo=self.ngo)
        m1 = make_partnership_milestone(partnership=partnership, sequence_number=1, status=MilestoneStatus.VERIFIED)
        m2 = make_partnership_milestone(partnership=partnership, sequence_number=2, status=MilestoneStatus.PENDING)

        list_serializer = CSRPartnershipListSerializer(instance=partnership)
        list_data = list_serializer.data
        self.assertEqual(list_data['partnership_code'], partnership.partnership_code)
        self.assertEqual(list_data['milestone_count'], 2)
        self.assertEqual(list_data['completed_milestone_count'], 1)
        self.assertEqual(list_data['progress_percentage'], 50.0)

        detail_serializer = CSRPartnershipDetailSerializer(instance=partnership)
        detail_data = detail_serializer.data
        self.assertEqual(detail_data['id'], str(partnership.id))
        self.assertEqual(len(detail_data['milestones']), 2)

    def test_csr_partnership_disbursement_serializer(self):
        """CSRPartnershipDisbursementSerializer validates non-negative informational disbursements."""
        s_valid = CSRPartnershipDisbursementSerializer(data={'disbursed_amount_reported': '500000.00', 'notes': 'Tranche 1 Bank Transfer'})
        self.assertTrue(s_valid.is_valid(), s_valid.errors)

        s_neg = CSRPartnershipDisbursementSerializer(data={'disbursed_amount_reported': '-100.00'})
        self.assertFalse(s_neg.is_valid())
        self.assertIn('disbursed_amount_reported', s_neg.errors)

    # -----------------------------------------------------------------------
    # 6. PartnershipMilestone Serializers
    # -----------------------------------------------------------------------

    def test_partnership_milestone_serializer(self):
        """PartnershipMilestoneSerializer validates sequence numbers and completion percentage."""
        m = make_partnership_milestone()
        serializer = PartnershipMilestoneSerializer(instance=m)
        self.assertEqual(serializer.data['sequence_number'], 1)

        # Test validation
        today = date.today()
        payload = {
            'sequence_number': 0,  # < 1
            'title': 'Milestone Test',
            'description': 'Description',
            'target_completion_date': str(today + timedelta(days=30)),
            'completion_percentage': 120,  # > 100
        }
        s_bad = PartnershipMilestoneSerializer(data=payload)
        self.assertFalse(s_bad.is_valid())
        self.assertIn('sequence_number', s_bad.errors)
        self.assertIn('completion_percentage', s_bad.errors)

    def test_milestone_evidence_submit_serializer(self):
        """MilestoneEvidenceSubmitSerializer validates evidence file and notes."""
        file = SimpleUploadedFile('evidence.pdf', b'dummy content', content_type='application/pdf')
        payload = {
            'evidence_document': file,
            'evidence_notes': 'Groundwork complete with site images attached.',
            'completion_percentage': 50,
        }
        serializer = MilestoneEvidenceSubmitSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Blank notes rejected
        payload_bad = {
            'evidence_document': file,
            'evidence_notes': '',
            'completion_percentage': 50,
        }
        s_bad = MilestoneEvidenceSubmitSerializer(data=payload_bad)
        self.assertFalse(s_bad.is_valid())
        self.assertIn('evidence_notes', s_bad.errors)

    def test_milestone_review_serializer(self):
        """MilestoneReviewSerializer validates verification decision and required revision notes."""
        s_verify = MilestoneReviewSerializer(data={'decision': 'VERIFY', 'notes': 'Approved'})
        self.assertTrue(s_verify.is_valid(), s_verify.errors)

        s_rev_valid = MilestoneReviewSerializer(data={'decision': 'REQUEST_REVISION', 'notes': 'Need clearer invoices'})
        self.assertTrue(s_rev_valid.is_valid(), s_rev_valid.errors)

        s_rev_bad = MilestoneReviewSerializer(data={'decision': 'REQUEST_REVISION', 'notes': ''})
        self.assertFalse(s_rev_bad.is_valid())
        self.assertIn('notes', s_rev_bad.errors)

    # -----------------------------------------------------------------------
    # 7. CSRVerificationHistory Serializer
    # -----------------------------------------------------------------------

    def test_csr_verification_history_serializer(self):
        """CSRVerificationHistorySerializer correctly serializes immutable audit history."""
        vh = make_verification_history()
        serializer = CSRVerificationHistorySerializer(instance=vh)
        data = serializer.data

        self.assertEqual(data['id'], str(vh.id))
        self.assertEqual(data['entity_type'], CSRAuditEntityType.COMPANY)
        self.assertEqual(data['new_status'], 'APPROVED')

    # -----------------------------------------------------------------------
    # 8. CSRMatchResult DTO Serializer
    # -----------------------------------------------------------------------

    def test_csr_match_result_serializer_valid(self):
        """CSRMatchResultSerializer validates valid match recommendation score DTO."""
        payload = {
            'requirement_id': str(uuid.uuid4()),
            'match_score': 87.5,
            'breakdown': {
                'category': 35.0,
                'location': 20.0,
                'budget': 20.0,
                'demographic': 10.0,
                'duration': 2.5,
            },
            'reasons': [
                "Schedule VII category matches 'Promoting Education'",
                "State matches 'Maharashtra'",
            ],
        }
        serializer = CSRMatchResultSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['match_score'], 87.5)

    def test_csr_match_result_serializer_invalid_scores_and_weights(self):
        """CSRMatchResultSerializer rejects scores > 100 or sub-scores exceeding max weights."""
        # Score > 100
        payload1 = {
            'requirement_id': str(uuid.uuid4()),
            'match_score': 105.0,  # > 100
            'breakdown': {'category': 35.0},
        }
        s1 = CSRMatchResultSerializer(data=payload1)
        self.assertFalse(s1.is_valid())
        self.assertIn('match_score', s1.errors)

        # Sub-score category > 35
        payload2 = {
            'requirement_id': str(uuid.uuid4()),
            'match_score': 50.0,
            'breakdown': {'category': 45.0},  # Max is 35
        }
        s2 = CSRMatchResultSerializer(data=payload2)
        self.assertFalse(s2.is_valid())
        self.assertIn('breakdown', s2.errors)

        # Negative sub-score
        payload3 = {
            'requirement_id': str(uuid.uuid4()),
            'match_score': 50.0,
            'breakdown': {'location': -5.0},
        }
        s3 = CSRMatchResultSerializer(data=payload3)
        self.assertFalse(s3.is_valid())
        self.assertIn('breakdown', s3.errors)

    # -----------------------------------------------------------------------
    # 9. Read-Only Protection & File Security Tests
    # -----------------------------------------------------------------------

    def test_csr_requirement_admin_serializer(self):
        """CSRRequirementAdminSerializer exposes review metadata and moderation status."""
        admin_user = make_user(role='ADMIN')
        req = make_csr_requirement(ngo=self.ngo)
        req.reviewed_by = admin_user
        req.rejection_reason = "Budget documentation incomplete"
        req.save()

        serializer = CSRRequirementAdminSerializer(instance=req)
        data = serializer.data

        self.assertEqual(data['id'], str(req.id))
        self.assertEqual(data['ngo_legal_name'], self.ngo.legal_name)
        self.assertEqual(data['created_by_email'], req.created_by.email)
        self.assertEqual(data['reviewed_by_email'], admin_user.email)
        self.assertEqual(data['rejection_reason'], "Budget documentation incomplete")

    def test_readonly_field_protection_company_write_serializer(self):
        """CompanyProfileWriteSerializer ignores client-injected verification_status or server fields."""
        attacker_user = make_user(role='CORPORATE')
        payload = {
            'company_name': 'Injected Corp',
            'legal_name': 'Injected Corp Ltd',
            'cin_number': generate_valid_cin(),
            'pan_number': generate_valid_pan(),
            'contact_person_name': 'Hacker',
            'contact_person_designation': 'Hacker',
            'contact_email': 'hacker@corp.com',
            'contact_phone': '+919999999999',
            'registered_address': 'Unknown',
            'city': 'Unknown',
            'state': 'Unknown',
            'pincode': '110001',
            # Attempted injections:
            'verification_status': CompanyVerificationStatus.APPROVED,
            'verified_by': attacker_user.id,
            'created_at': '2020-01-01T00:00:00Z',
        }
        serializer = CompanyProfileWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # Server-managed fields must NOT be in validated_data
        self.assertNotIn('verification_status', serializer.validated_data)
        self.assertNotIn('verified_by', serializer.validated_data)
        self.assertNotIn('created_at', serializer.validated_data)

    def test_readonly_field_protection_requirement_write_serializer(self):
        """CSRRequirementWriteSerializer ignores client-injected status or NGO ownership."""
        today = date.today()
        payload = {
            'title': 'Injected Requirement',
            'schedule_vii_category': ScheduleVIICategory.RURAL_DEVELOPMENT,
            'state': 'Assam',
            'district': 'Kamrup',
            'beneficiary_demographic': BeneficiaryDemographic.RURAL_COMMUNITIES,
            'summary': 'Summary',
            'detailed_description': 'Detailed',
            'expected_outcomes': 'Outcomes',
            'total_estimated_budget': '500000.00',
            'required_csr_funding': '400000.00',
            'start_date': str(today),
            'expected_completion_date': str(today + timedelta(days=180)),
            # Attempted injections:
            'status': CSRRequirementStatus.APPROVED,
            'ngo': str(self.ngo.id),
            'slug': 'injected-custom-slug',
            'created_by': make_user().id,
        }
        serializer = CSRRequirementWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('status', serializer.validated_data)
        self.assertNotIn('ngo', serializer.validated_data)
        self.assertNotIn('slug', serializer.validated_data)
        self.assertNotIn('created_by', serializer.validated_data)

    def test_file_field_representation_safety_no_raw_paths(self):
        """File fields in Read serializers only expose boolean flags and basenames, not raw paths."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            pdf_file = make_dummy_uploaded_file('doc.pdf', b'sample content')
            self.company.verification_document = pdf_file
            self.company.save()

            serializer = CompanyProfileReadSerializer(instance=self.company)
            data = serializer.data

            self.assertTrue(data['has_verification_document'])
            self.assertEqual(data['verification_document_name'], os.path.basename(self.company.verification_document.name))
            # Ensure no absolute filesystem path leakage
            self.assertNotIn(self.temp_media, str(data))
            self.assertNotIn('/Users/', str(data))
            self.assertNotIn('/mnt/', str(data))

    # -----------------------------------------------------------------------
    # 10. Deep Adversarial & Read-Only Bypass Tests
    # -----------------------------------------------------------------------

    def test_readonly_bypass_company_preference_serializer(self):
        """CompanyCSRPreferenceSerializer rejects/ignores client attempts to reassign company or ID."""
        attacker_company = make_company_profile()
        payload = {
            'id': str(uuid.uuid4()),
            'company': str(attacker_company.id),
            'company_name': 'Fake Company',
            'preferred_categories': [ScheduleVIICategory.PROMOTING_EDUCATION],
            'min_budget': '100000.00',
            'max_budget': '500000.00',
            'created_at': '2020-01-01T00:00:00Z',
        }
        serializer = CompanyCSRPreferenceSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('company', serializer.validated_data)
        self.assertNotIn('id', serializer.validated_data)
        self.assertNotIn('created_at', serializer.validated_data)

    def test_readonly_bypass_support_request_create_serializer(self):
        """CSRSupportRequestCreateSerializer ignores client-injected company, status, and reviewer fields."""
        attacker_company = make_company_profile()
        admin_user = make_user(role='ADMIN')
        req = make_csr_requirement(ngo=self.ngo)

        payload = {
            'requirement': str(req.id),
            'proposed_funding': '50000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'spoc_name': 'Test SPOC',
            'spoc_email': 'spoc@test.com',
            'spoc_phone': '+919876543210',
            'message': 'Grant proposal message.',
            # Injected fields:
            'id': str(uuid.uuid4()),
            'company': str(attacker_company.id),
            'status': CSRSupportRequestStatus.ACCEPTED,
            'reviewed_by': admin_user.id,
            'reviewed_at': '2026-01-01T00:00:00Z',
            'rejection_reason': 'Injected text',
        }
        serializer = CSRSupportRequestCreateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('company', serializer.validated_data)
        self.assertNotIn('status', serializer.validated_data)
        self.assertNotIn('reviewed_by', serializer.validated_data)
        self.assertNotIn('reviewed_at', serializer.validated_data)
        self.assertNotIn('rejection_reason', serializer.validated_data)

    def test_readonly_bypass_milestone_serializer(self):
        """PartnershipMilestoneSerializer ignores client attempts to write status, reviewer, or timestamps."""
        admin_user = make_user(role='ADMIN')
        today = date.today()
        payload = {
            'sequence_number': 1,
            'title': 'Milestone 1',
            'description': 'Deliver foundation report',
            'target_completion_date': str(today + timedelta(days=30)),
            # Injected fields:
            'status': MilestoneStatus.VERIFIED,
            'actual_completion_date': str(today),
            'verified_by': admin_user.id,
            'verified_at': '2026-01-01T00:00:00Z',
        }
        serializer = PartnershipMilestoneSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('status', serializer.validated_data)
        self.assertNotIn('actual_completion_date', serializer.validated_data)
        self.assertNotIn('verified_by', serializer.validated_data)
        self.assertNotIn('verified_at', serializer.validated_data)

    def test_audit_serializer_completely_read_only(self):
        """CSRVerificationHistorySerializer ignores all incoming mutations in payload."""
        admin_user = make_user(role='ADMIN')
        payload = {
            'entity_type': CSRAuditEntityType.REQUIREMENT,
            'entity_id': str(uuid.uuid4()),
            'old_status': 'DRAFT',
            'new_status': 'APPROVED',
            'reviewed_by': admin_user.id,
            'review_notes': 'Malicious review injection',
            'metadata': {'injected': True},
        }
        serializer = CSRVerificationHistorySerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # All fields are in read_only_fields so validated_data must be empty
        self.assertEqual(serializer.validated_data, {})

    # -----------------------------------------------------------------------
    # 11. Multi-Model File Security & Path Leakage Audits
    # -----------------------------------------------------------------------

    def test_file_field_representation_safety_requirement_detail(self):
        """CSRRequirementDetailSerializer masks absolute storage paths for all 3 attached documents."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            req = make_csr_requirement(ngo=self.ngo)
            req.proposal_document = make_dummy_uploaded_file('proposal.pdf', b'content')
            req.detailed_budget_document = make_dummy_uploaded_file('budget.xlsx', b'content')
            req.impact_assessment_report = make_dummy_uploaded_file('impact.pdf', b'content')
            req.save()

            serializer = CSRRequirementDetailSerializer(instance=req)
            data = serializer.data

            self.assertTrue(data['has_proposal_document'])
            self.assertTrue(data['has_detailed_budget_document'])
            self.assertTrue(data['has_impact_assessment_report'])
            self.assertEqual(data['proposal_document_name'], os.path.basename(req.proposal_document.name))
            self.assertEqual(data['detailed_budget_document_name'], os.path.basename(req.detailed_budget_document.name))
            self.assertEqual(data['impact_assessment_report_name'], os.path.basename(req.impact_assessment_report.name))

            # Verify no filesystem paths leaked
            serialized_str = str(data)
            self.assertNotIn(self.temp_media, serialized_str)
            self.assertNotIn('/Users/', serialized_str)
            self.assertNotIn('/mnt/', serialized_str)

    def test_file_field_representation_safety_partnership_mou(self):
        """CSRPartnershipDetailSerializer masks absolute storage paths for signed MoU document."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            partnership = make_csr_partnership(company=self.company, ngo=self.ngo)
            partnership.signed_mou_document = make_dummy_uploaded_file('signed_mou.pdf', b'content')
            partnership.save()

            serializer = CSRPartnershipDetailSerializer(instance=partnership)
            data = serializer.data

            self.assertTrue(data['has_signed_mou'])
            self.assertEqual(data['signed_mou_name'], os.path.basename(partnership.signed_mou_document.name))

            serialized_str = str(data)
            self.assertNotIn(self.temp_media, serialized_str)
            self.assertNotIn('/Users/', serialized_str)

    def test_file_field_representation_safety_milestone_evidence(self):
        """PartnershipMilestoneSerializer masks absolute storage paths for milestone evidence."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            milestone = make_partnership_milestone()
            milestone.evidence_document = make_dummy_uploaded_file('proof.png', b'content')
            milestone.save()

            serializer = PartnershipMilestoneSerializer(instance=milestone)
            data = serializer.data

            self.assertTrue(data['has_evidence_document'])
            self.assertEqual(data['evidence_document_name'], os.path.basename(milestone.evidence_document.name))

            serialized_str = str(data)
            self.assertNotIn(self.temp_media, serialized_str)
            self.assertNotIn('/Users/', serialized_str)

    # -----------------------------------------------------------------------
    # 12. Nested Representation Tests
    # -----------------------------------------------------------------------

    def test_nested_partnership_milestones_zero_one_multiple(self):
        """CSRPartnershipDetailSerializer correctly nests 0, 1, and multiple milestones in sequence."""
        p_zero = make_csr_partnership(company=self.company, ngo=self.ngo)
        d_zero = CSRPartnershipDetailSerializer(instance=p_zero).data
        self.assertEqual(len(d_zero['milestones']), 0)

        # Add 3 milestones
        m1 = make_partnership_milestone(partnership=p_zero, sequence_number=1, title='Phase 1')
        m2 = make_partnership_milestone(partnership=p_zero, sequence_number=2, title='Phase 2')
        m3 = make_partnership_milestone(partnership=p_zero, sequence_number=3, title='Phase 3')

        d_multi = CSRPartnershipDetailSerializer(instance=p_zero).data
        self.assertEqual(len(d_multi['milestones']), 3)
        self.assertEqual(d_multi['milestones'][0]['sequence_number'], 1)
        self.assertEqual(d_multi['milestones'][1]['sequence_number'], 2)
        self.assertEqual(d_multi['milestones'][2]['sequence_number'], 3)
        self.assertEqual(d_multi['milestones'][0]['title'], 'Phase 1')

    # -----------------------------------------------------------------------
    # 13. Type Fuzzing & Boundary Edge Cases
    # -----------------------------------------------------------------------

    def test_fuzz_malformed_types_company_write(self):
        """CompanyProfileWriteSerializer handles malformed non-string types cleanly."""
        payload = {
            'company_name': ['Invalid', 'List', 'Name'],
            'cin_number': 1234567890,
            'pan_number': {'nested': 'pan'},
            'contact_phone': ['+919876543210'],
            'annual_csr_budget': 'NOT_A_DECIMAL',
        }
        serializer = CompanyProfileWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('company_name', serializer.errors)
        self.assertIn('cin_number', serializer.errors)
        self.assertIn('pan_number', serializer.errors)
        self.assertIn('annual_csr_budget', serializer.errors)

    def test_fuzz_malformed_types_requirement_write(self):
        """CSRRequirementWriteSerializer rejects invalid data types and out-of-choice enums."""
        payload = {
            'title': 12345,  # int instead of string
            'schedule_vii_category': 'INVALID_CATEGORY_XYZ',
            'location_scope': 'INVALID_SCOPE',
            'beneficiary_demographic': 'INVALID_DEMO',
            'total_estimated_budget': 'INVALID_DECIMAL',
            'start_date': '2026-99-99',  # Invalid date
        }
        serializer = CSRRequirementWriteSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('schedule_vii_category', serializer.errors)
        self.assertIn('location_scope', serializer.errors)
        self.assertIn('beneficiary_demographic', serializer.errors)
        self.assertIn('total_estimated_budget', serializer.errors)
        self.assertIn('start_date', serializer.errors)

    def test_location_scope_canonical_and_alias_normalization(self):
        """CSRRequirementWriteSerializer accepts all 4 canonical scopes and normalizes frontend aliases."""
        base_payload = {
            'title': 'Solar Powered Digital Classrooms',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'summary': 'Solar classroom kits for 25 schools',
            'detailed_description': 'Detailed implementation roadmap across target region.',
            'expected_outcomes': 'Enhanced digital literacy',
            'total_estimated_budget': '500000.00',
            'required_csr_funding': '400000.00',
            'start_date': date.today(),
            'expected_completion_date': date.today() + timedelta(days=180),
        }

        # 1. Canonical scopes
        for scope in [LocationScope.SPECIFIC_DISTRICT, LocationScope.MULTI_DISTRICT, LocationScope.NATIONWIDE, LocationScope.ASPIRATIONAL_DISTRICT]:
            payload = {**base_payload, 'location_scope': scope}
            serializer = CSRRequirementWriteSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), f"Failed for canonical scope: {scope}: {serializer.errors}")
            self.assertEqual(serializer.validated_data['location_scope'], scope)

        # 2. Aliases normalization (STATE_WIDE -> MULTI_DISTRICT, etc.)
        alias_cases = [
            ('STATE_WIDE', LocationScope.MULTI_DISTRICT),
            ('DISTRICT_LOCAL', LocationScope.SPECIFIC_DISTRICT),
            ('PAN_INDIA', LocationScope.NATIONWIDE),
        ]
        for alias, expected in alias_cases:
            payload = {**base_payload, 'location_scope': alias}
            serializer = CSRRequirementWriteSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), f"Failed for alias: {alias}: {serializer.errors}")
            self.assertEqual(serializer.validated_data['location_scope'], expected)

    def test_fuzz_boundary_extremes_financials(self):
        """Test boundary thresholds: ₹9,999.99 fails, ₹10,000.00 passes for requirements."""
        today = date.today()
        # 9,999.99 fails
        p_fail = {
            'title': 'Boundary Requirement',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'summary': 'Summary',
            'detailed_description': 'Detailed',
            'expected_outcomes': 'Outcomes',
            'total_estimated_budget': '9999.99',  # Below 10k
            'required_csr_funding': '9999.99',    # Below 10k
            'start_date': str(today),
            'expected_completion_date': str(today + timedelta(days=30)),
        }
        s_fail = CSRRequirementWriteSerializer(data=p_fail)
        self.assertFalse(s_fail.is_valid())
        self.assertIn('total_estimated_budget', s_fail.errors)
        self.assertIn('required_csr_funding', s_fail.errors)

        # 10,000.00 passes
        p_pass = {
            'title': 'Boundary Requirement Pass',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'summary': 'Summary',
            'detailed_description': 'Detailed',
            'expected_outcomes': 'Outcomes',
            'total_estimated_budget': '10000.00',
            'required_csr_funding': '10000.00',
            'start_date': str(today),
            'expected_completion_date': str(today + timedelta(days=30)),
        }
        s_pass = CSRRequirementWriteSerializer(data=p_pass)
        self.assertTrue(s_pass.is_valid(), s_pass.errors)

    def test_fuzz_boundary_support_request_funding(self):
        """Test boundary thresholds: ₹999.99 fails, ₹1,000.00 passes for support requests."""
        req = make_csr_requirement(ngo=self.ngo)
        p_fail = {
            'requirement': str(req.id),
            'proposed_funding': '999.99',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'spoc_name': 'SPOC',
            'spoc_email': 'spoc@test.com',
            'spoc_phone': '+919876543210',
            'message': 'Message',
        }
        s_fail = CSRSupportRequestCreateSerializer(data=p_fail)
        self.assertFalse(s_fail.is_valid())
        self.assertIn('proposed_funding', s_fail.errors)

        p_pass = {
            'requirement': str(req.id),
            'proposed_funding': '1000.00',
            'support_type': CSRSupportType.FINANCIAL_GRANT,
            'spoc_name': 'SPOC',
            'spoc_email': 'spoc@test.com',
            'spoc_phone': '+919876543210',
            'message': 'Message',
        }
        s_pass = CSRSupportRequestCreateSerializer(data=p_pass)
        self.assertTrue(s_pass.is_valid(), s_pass.errors)

    def test_support_request_decision_withdraw_action(self):
        """CSRSupportRequestDecisionSerializer validates WITHDRAW action with reason."""
        s_valid = CSRSupportRequestDecisionSerializer(data={'action': 'WITHDRAW', 'reason': 'Board decision'})
        self.assertTrue(s_valid.is_valid(), s_valid.errors)

        s_invalid = CSRSupportRequestDecisionSerializer(data={'action': 'WITHDRAW', 'reason': ''})
        self.assertFalse(s_invalid.is_valid())
        self.assertIn('reason', s_invalid.errors)

    def test_company_profile_read_serializer_empty_pan(self):
        """CompanyProfileReadSerializer handles missing PAN gracefully."""
        self.company.pan_number = ""
        self.company.save()
        serializer = CompanyProfileReadSerializer(instance=self.company)
        data = serializer.data
        self.assertFalse(data['has_pan'])
        self.assertEqual(data['pan_number_masked'], "")


