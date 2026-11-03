"""
Unit Tests for CSR Requirement Service — Phase CSR-2.5
======================================================
Tests Schedule VII project proposal drafting, numeric invariants, submission,
withdrawal, closure, and tenant isolation.
"""

from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase

from users.models import User
from ngo.models import NGOProfile
from csr.models import (
    CSRRequirement,
    CSRRequirementStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.services.requirement_service import (
    create_requirement,
    get_requirement_for_ngo,
    list_requirements_for_ngo,
    update_requirement,
    submit_requirement,
    withdraw_requirement,
    close_requirement,
)
from csr.services.exceptions import (
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
)
from csr.tests.helpers import make_user, make_ngo_profile, make_csr_requirement


class RequirementServiceTests(TestCase):
    """Tests for CSR requirement proposal lifecycle service."""

    def setUp(self):
        self.ngo_user_a = make_user(email="ngo_a@example.com", role=User.Role.NGO)
        self.ngo_profile_a = make_ngo_profile(user=self.ngo_user_a)

        self.ngo_user_b = make_user(email="ngo_b@example.com", role=User.Role.NGO)
        self.ngo_profile_b = make_ngo_profile(user=self.ngo_user_b)

        self.company_user = make_user(email="comp@example.com", role=User.Role.COMPANY)
        self.donor_user = make_user(email="donor@example.com", role=User.Role.DONOR)

    def _sample_data(self, **kwargs):
        today = date.today()
        defaults = {
            'title': 'Solar Powered Digital Classrooms',
            'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
            'state': 'Maharashtra',
            'district': 'Pune',
            'location_scope': LocationScope.SPECIFIC_DISTRICT,
            'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
            'target_beneficiary_count': 500,
            'summary': 'Providing solar power and smart tablets to 10 rural schools.',
            'detailed_description': 'Detailed breakdown of hardware, solar installation, and teacher training.',
            'expected_outcomes': '500 students gain daily access to digital curriculum.',
            'total_estimated_budget': Decimal('500000.00'),
            'required_csr_funding': Decimal('400000.00'),
            'start_date': today,
            'expected_completion_date': today + timedelta(days=180),
        }
        defaults.update(kwargs)
        return defaults

    def test_create_requirement_success(self):
        """Creates requirement in DRAFT with generated unique slug."""
        data = self._sample_data()
        req = create_requirement(self.ngo_user_a, data)
        self.assertEqual(req.status, CSRRequirementStatus.DRAFT)
        self.assertEqual(req.ngo, self.ngo_profile_a)
        self.assertTrue(len(req.slug) > 0)
        self.assertEqual(req.committed_funding, Decimal('0.00'))

    def test_create_requirement_rejects_non_ngo_user(self):
        """Non-NGO users cannot create proposals."""
        data = self._sample_data()
        with self.assertRaises(CSROwnershipError):
            create_requirement(self.company_user, data)
        with self.assertRaises(CSROwnershipError):
            create_requirement(self.donor_user, data)

    def test_create_requirement_budget_invariants(self):
        """Validates minimum amounts and funding <= total budget."""
        # Total budget too low (< 10000)
        with self.assertRaises(CSRValidationError):
            create_requirement(self.ngo_user_a, self._sample_data(total_estimated_budget=Decimal('5000.00')))

        # Required funding too low (< 10000)
        with self.assertRaises(CSRValidationError):
            create_requirement(self.ngo_user_a, self._sample_data(required_csr_funding=Decimal('5000.00')))

        # Required funding > total budget
        with self.assertRaises(CSRValidationError):
            create_requirement(self.ngo_user_a, self._sample_data(
                total_estimated_budget=Decimal('100000.00'),
                required_csr_funding=Decimal('150000.00'),
            ))

    def test_create_requirement_date_invariants(self):
        """Expected completion date must be >= start date."""
        today = date.today()
        with self.assertRaises(CSRValidationError):
            create_requirement(self.ngo_user_a, self._sample_data(
                start_date=today + timedelta(days=30),
                expected_completion_date=today,
            ))

    def test_create_requirement_strips_status_spoofing(self):
        """Client-injected status or approval fields are stripped."""
        data = self._sample_data(status='APPROVED', committed_funding=Decimal('100000.00'))
        req = create_requirement(self.ngo_user_a, data)
        self.assertEqual(req.status, CSRRequirementStatus.DRAFT)
        self.assertEqual(req.committed_funding, Decimal('0.00'))

    def test_get_and_list_requirements_tenant_isolation(self):
        """NGO A cannot access NGO B requirements."""
        req_a = create_requirement(self.ngo_user_a, self._sample_data(title="Req A"))
        req_b = create_requirement(self.ngo_user_b, self._sample_data(title="Req B"))

        # NGO A gets req A
        fetched = get_requirement_for_ngo(self.ngo_user_a, req_a.id)
        self.assertEqual(fetched.id, req_a.id)

        # NGO A attempting to get req B -> CSRNotFoundError
        with self.assertRaises(CSRNotFoundError):
            get_requirement_for_ngo(self.ngo_user_a, req_b.id)

        # Listing only returns own NGO's requirements
        list_a = list_requirements_for_ngo(self.ngo_user_a)
        self.assertEqual(list_a.count(), 1)
        self.assertEqual(list_a.first().id, req_a.id)

    def test_update_requirement_lifecycle(self):
        """Updates allowed in DRAFT, rejected in active states."""
        req = create_requirement(self.ngo_user_a, self._sample_data())
        updated = update_requirement(self.ngo_user_a, req.id, {'summary': 'Updated summary text.'})
        self.assertEqual(updated.summary, 'Updated summary text.')

        # Transition to PENDING_REVIEW -> updates now blocked
        submit_requirement(self.ngo_user_a, req.id)
        with self.assertRaises(CSRStateError):
            update_requirement(self.ngo_user_a, req.id, {'summary': 'Blocked update'})

    def test_submit_and_withdraw_requirement(self):
        """Submitting transitions DRAFT -> PENDING_REVIEW; withdrawing transitions back to DRAFT."""
        req = create_requirement(self.ngo_user_a, self._sample_data())
        submitted = submit_requirement(self.ngo_user_a, req.id)
        self.assertEqual(submitted.status, CSRRequirementStatus.PENDING_REVIEW)

        # Audit record written
        history = CSRVerificationHistory.objects.filter(entity_id=req.id, entity_type=CSRAuditEntityType.REQUIREMENT)
        self.assertTrue(history.exists())

        # Withdraw back to DRAFT
        withdrawn = withdraw_requirement(self.ngo_user_a, req.id, reason="Need to adjust budget")
        self.assertEqual(withdrawn.status, CSRRequirementStatus.DRAFT)

    def test_close_requirement(self):
        """Closing requirement from OPEN_FOR_CSR transitions to COMPLETED."""
        req = make_csr_requirement(ngo=self.ngo_profile_a, status=CSRRequirementStatus.OPEN_FOR_CSR)
        closed = close_requirement(self.ngo_user_a, req.id, reason="Campaign targets achieved")
        self.assertEqual(closed.status, CSRRequirementStatus.COMPLETED)

    def test_create_requirement_denies_unapproved_ngo(self):
        """create_requirement raises CSROwnershipError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.DRAFT, is_active=False)
        with self.assertRaises(CSROwnershipError):
            create_requirement(unapproved_user, self._sample_data())

    def test_list_requirements_denies_unapproved_ngo(self):
        """list_requirements_for_ngo raises CSROwnershipError for unapproved NGO."""
        unapproved_user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=unapproved_user, status=NGOProfile.Status.REJECTED, is_active=False)
        with self.assertRaises(CSROwnershipError):
            list_requirements_for_ngo(unapproved_user)

