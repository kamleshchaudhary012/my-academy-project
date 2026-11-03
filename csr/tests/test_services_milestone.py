"""
Unit Tests for CSR Milestone Service — Phase CSR-2.5
====================================================
Tests sequenced deliverables, progress tracking, evidence upload,
verification review decisions, and participant access scoping.
"""

from datetime import date, timedelta
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from users.models import User
from ngo.models import NGOProfile
from csr.models import (
    PartnershipMilestone,
    MilestoneStatus,
    CSRPartnershipStatus,
    CompanyVerificationStatus,
    CSRSupportRequestStatus,
    CSRRequirementStatus,
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.services.milestone_service import (
    create_milestone,
    get_milestone,
    list_milestones,
    update_milestone,
    submit_evidence,
    review_milestone,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
)


class MilestoneServiceTests(TestCase):
    """Tests for partnership milestone deliverables service."""

    def setUp(self):
        self.company_user = make_user(email="comp@example.com", role=User.Role.COMPANY)
        self.company = make_company_profile(user=self.company_user, verification_status=CompanyVerificationStatus.APPROVED)

        self.unrelated_company_user = make_user(email="comp_unrel@example.com", role=User.Role.COMPANY)
        self.unrelated_company = make_company_profile(user=self.unrelated_company_user, verification_status=CompanyVerificationStatus.APPROVED)

        self.ngo_user = make_user(email="ngo@example.com", role=User.Role.NGO)
        self.ngo = make_ngo_profile(user=self.ngo_user)

        self.unrelated_ngo_user = make_user(email="ngo_unrel@example.com", role=User.Role.NGO)
        self.unrelated_ngo = make_ngo_profile(user=self.unrelated_ngo_user)

        self.admin_user = make_user(email="admin@example.com", role=User.Role.ADMIN)

        self.requirement = make_csr_requirement(ngo=self.ngo, status=CSRRequirementStatus.OPEN_FOR_CSR)
        self.support_request = make_csr_support_request(company=self.company, requirement=self.requirement, status=CSRSupportRequestStatus.ACCEPTED)
        self.partnership = make_csr_partnership(company=self.company, ngo=self.ngo, requirement=self.requirement, support_request=self.support_request, status=CSRPartnershipStatus.ACTIVE)

    def _sample_milestone_data(self, **kwargs):
        defaults = {
            'sequence_number': 1,
            'title': 'Procurement of Hardware & Tablets',
            'description': 'Procuring 50 Android tablets and solar panels for the 10 target schools.',
            'target_completion_date': date.today() + timedelta(days=60),
            'completion_percentage': 0,
        }
        defaults.update(kwargs)
        return defaults

    def test_create_milestone_success(self):
        """Creates milestone in PENDING status with unique sequence number."""
        data = self._sample_milestone_data()
        milestone = create_milestone(self.ngo_user, self.partnership.id, data)
        self.assertEqual(milestone.status, MilestoneStatus.PENDING)
        self.assertEqual(milestone.sequence_number, 1)
        self.assertEqual(milestone.partnership, self.partnership)

    def test_create_milestone_duplicate_sequence_rejected(self):
        """Duplicate sequence_number within the same partnership is rejected (CSRConflictError)."""
        create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data(sequence_number=1))
        with self.assertRaises(CSRConflictError):
            create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data(sequence_number=1))

    def test_milestone_access_control(self):
        """Only bilateral participants and Admin can view/act on milestones."""
        milestone = create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data())

        self.assertEqual(get_milestone(self.ngo_user, milestone.id).id, milestone.id)
        self.assertEqual(get_milestone(self.company_user, milestone.id).id, milestone.id)
        self.assertEqual(get_milestone(self.admin_user, milestone.id).id, milestone.id)

        with self.assertRaises(CSRNotFoundError):
            get_milestone(self.unrelated_company_user, milestone.id)
        with self.assertRaises(CSRNotFoundError):
            get_milestone(self.unrelated_ngo_user, milestone.id)

    def test_submit_evidence_lifecycle(self):
        """Submitting evidence transitions PENDING -> SUBMITTED and updates percentage."""
        milestone = create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data())
        doc = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 procurement invoices", content_type="application/pdf")

        submitted = submit_evidence(
            self.ngo_user,
            milestone.id,
            evidence_notes="Tablets received and verified at central warehouse.",
            evidence_file=doc,
            completion_percentage=50,
        )
        self.assertEqual(submitted.status, MilestoneStatus.SUBMITTED)
        self.assertEqual(submitted.completion_percentage, 50)
        self.assertTrue(bool(submitted.evidence_document))

    def test_review_milestone_verify(self):
        """Corporate partner verifies submitted milestone, setting status to VERIFIED and percentage to 100."""
        milestone = create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data())
        submit_evidence(self.ngo_user, milestone.id, evidence_notes="Work completed", completion_percentage=100)

        verified = review_milestone(self.company_user, milestone.id, decision='VERIFY', notes="Hardware inspection passed.")
        self.assertEqual(verified.status, MilestoneStatus.VERIFIED)
        self.assertEqual(verified.verified_by, self.company_user)
        self.assertIsNotNone(verified.verified_at)
        self.assertEqual(verified.completion_percentage, 100)

        # Verified milestone cannot be modified
        with self.assertRaises(CSRStateError):
            update_milestone(self.ngo_user, milestone.id, {'title': 'Changed'})

    def test_review_milestone_request_revision(self):
        """Requesting revision requires notes and transitions SUBMITTED -> REVISION_REQUESTED."""
        milestone = create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data())
        submit_evidence(self.ngo_user, milestone.id, evidence_notes="Rough draft", completion_percentage=30)

        # Missing revision notes rejected
        with self.assertRaises(CSRValidationError):
            review_milestone(self.company_user, milestone.id, decision='REQUEST_REVISION', notes="")

        revised = review_milestone(self.company_user, milestone.id, decision='REQUEST_REVISION', notes="Please attach serial numbers list.")
        self.assertEqual(revised.status, MilestoneStatus.REVISION_REQUESTED)
        self.assertIn("serial numbers", revised.evidence_notes)

    def test_create_milestone_denies_unapproved_ngo(self):
        """create_milestone raises CSRNotFoundError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.DRAFT, is_active=False)
        with self.assertRaises(CSRNotFoundError):
            create_milestone(unapproved_user, self.partnership.id, self._sample_milestone_data())

    def test_submit_evidence_denies_unapproved_ngo(self):
        """submit_evidence raises CSRNotFoundError for unapproved NGO."""
        milestone = create_milestone(self.ngo_user, self.partnership.id, self._sample_milestone_data())
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.REJECTED, is_active=False)
        with self.assertRaises(CSRNotFoundError):
            submit_evidence(unapproved_user, milestone.id, evidence_notes="Proof")

