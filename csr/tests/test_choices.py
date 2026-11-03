"""
Unit Tests for CSR Choice / Enum Classes
========================================
Validates all TextChoices contracts in csr.models and User.Role.COMPANY.
"""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from csr.models import (
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

User = get_user_model()


class CSRChoiceEnumTests(SimpleTestCase):
    """Verifies all frozen TextChoices enums and values."""

    def test_user_role_company_exists(self):
        """User.Role.COMPANY must be defined with value 'COMPANY'."""
        self.assertEqual(User.Role.COMPANY, 'COMPANY')
        self.assertIn('COMPANY', [c[0] for c in User.Role.choices])

    def test_company_verification_status_choices(self):
        """CompanyVerificationStatus must contain exact frozen states."""
        expected = {
            'DRAFT': 'DRAFT',
            'PENDING_VERIFICATION': 'PENDING_VERIFICATION',
            'CORRECTION_REQUIRED': 'CORRECTION_REQUIRED',
            'APPROVED': 'APPROVED',
            'REJECTED': 'REJECTED',
            'SUSPENDED': 'SUSPENDED',
        }
        self.assertEqual(len(CompanyVerificationStatus.choices), 6)
        for key, val in expected.items():
            self.assertEqual(getattr(CompanyVerificationStatus, key), val)

    def test_schedule_vii_category_choices(self):
        """ScheduleVIICategory must cover all 12 statutory Schedule VII categories."""
        expected = [
            'ERADICATING_HUNGER',
            'PROMOTING_EDUCATION',
            'GENDER_EQUALITY',
            'ENVIRONMENTAL_SUSTAINABILITY',
            'NATIONAL_HERITAGE',
            'ARMED_FORCES_VETERANS',
            'RURAL_SPORTS',
            'PM_NATIONAL_RELIEF',
            'TECHNOLOGY_INCUBATORS',
            'RURAL_DEVELOPMENT',
            'SLUM_DEVELOPMENT',
            'DISASTER_MANAGEMENT',
        ]
        self.assertEqual(len(ScheduleVIICategory.choices), 12)
        actual_keys = [c[0] for c in ScheduleVIICategory.choices]
        for key in expected:
            self.assertIn(key, actual_keys)
            self.assertEqual(getattr(ScheduleVIICategory, key), key)

    def test_location_scope_choices(self):
        """LocationScope must contain 4 geographical scope options."""
        expected = ['SPECIFIC_DISTRICT', 'MULTI_DISTRICT', 'NATIONWIDE', 'ASPIRATIONAL_DISTRICT']
        self.assertEqual(len(LocationScope.choices), 4)
        for key in expected:
            self.assertEqual(getattr(LocationScope, key), key)

    def test_beneficiary_demographic_choices(self):
        """BeneficiaryDemographic must contain 9 demographic options."""
        expected = [
            'CHILDREN_EDUCATION',
            'WOMEN_EMPOWERMENT',
            'RURAL_COMMUNITIES',
            'YOUTH_SKILLING',
            'HEALTHCARE_PATIENTS',
            'SPECIALLY_ABLED',
            'ELDERLY_CARE',
            'ENVIRONMENTAL_HABITATS',
            'DISASTER_AFFECTED',
        ]
        self.assertEqual(len(BeneficiaryDemographic.choices), 9)
        actual_keys = [c[0] for c in BeneficiaryDemographic.choices]
        for key in expected:
            self.assertIn(key, actual_keys)
            self.assertEqual(getattr(BeneficiaryDemographic, key), key)

    def test_csr_requirement_status_choices(self):
        """CSRRequirementStatus must include OPEN_FOR_CSR and all 9 lifecycle states."""
        expected = [
            'DRAFT',
            'PENDING_REVIEW',
            'APPROVED',
            'OPEN_FOR_CSR',
            'PARTNERED',
            'IN_EXECUTION',
            'COMPLETED',
            'REJECTED',
            'SUSPENDED',
        ]
        self.assertEqual(len(CSRRequirementStatus.choices), 9)
        actual_keys = [c[0] for c in CSRRequirementStatus.choices]
        for key in expected:
            self.assertIn(key, actual_keys)
            self.assertEqual(getattr(CSRRequirementStatus, key), key)
        self.assertEqual(CSRRequirementStatus.OPEN_FOR_CSR, 'OPEN_FOR_CSR')

    def test_csr_support_type_choices(self):
        """CSRSupportType must contain 3 support mode options."""
        expected = ['FINANCIAL_GRANT', 'EQUIPMENT_SUPPORT', 'CO_FUNDING']
        self.assertEqual(len(CSRSupportType.choices), 3)
        for key in expected:
            self.assertEqual(getattr(CSRSupportType, key), key)

    def test_csr_support_request_status_choices(self):
        """CSRSupportRequestStatus must contain PENDING_NGO_REVIEW and all 5 states."""
        expected = ['PENDING_NGO_REVIEW', 'ACCEPTED', 'REJECTED', 'WITHDRAWN', 'EXPIRED']
        self.assertEqual(len(CSRSupportRequestStatus.choices), 5)
        for key in expected:
            self.assertEqual(getattr(CSRSupportRequestStatus, key), key)
        self.assertEqual(CSRSupportRequestStatus.PENDING_NGO_REVIEW, 'PENDING_NGO_REVIEW')

    def test_csr_partnership_status_choices(self):
        """CSRPartnershipStatus must contain 6 states."""
        expected = ['PENDING_MOU', 'ACTIVE', 'PAUSED', 'COMPLETED', 'CANCELLED', 'TERMINATED']
        self.assertEqual(len(CSRPartnershipStatus.choices), 6)
        for key in expected:
            self.assertEqual(getattr(CSRPartnershipStatus, key), key)

    def test_milestone_status_choices(self):
        """MilestoneStatus must contain 4 progress states."""
        expected = ['PENDING', 'SUBMITTED', 'VERIFIED', 'REVISION_REQUESTED']
        self.assertEqual(len(MilestoneStatus.choices), 4)
        for key in expected:
            self.assertEqual(getattr(MilestoneStatus, key), key)

    def test_csr_audit_entity_type_choices(self):
        """CSRAuditEntityType must contain 6 auditable entity types."""
        expected = ['COMPANY', 'REQUIREMENT', 'PARTNERSHIP', 'MILESTONE', 'DISBURSEMENT', 'EXPENSE']
        self.assertEqual(len(CSRAuditEntityType.choices), 6)
        for key in expected:
            self.assertEqual(getattr(CSRAuditEntityType, key), key)
