"""
Unit Tests for CSR Relationship on_delete Semantics
===================================================
Explicitly tests Django ORM deletion semantics across all 16 relationships:
- 8 PROTECT relationships
- 3 CASCADE relationships
- 5 SET_NULL relationships
"""

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase

from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
    CSRVerificationHistory,
    CSRSupportRequestStatus,
    MilestoneStatus,
    CSRAuditEntityType,
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
)

User = get_user_model()


class CSRRelationshipOnDeleteTests(TestCase):
    """Verifies all 16 ForeignKey / OneToOneField on_delete behaviors in CSR domain."""

    # -----------------------------------------------------------------------
    # PROTECT Relations (8 tests)
    # -----------------------------------------------------------------------

    def test_protect_csr_requirement_ngo(self):
        """Deleting NGOProfile with active CSRRequirement must raise ProtectedError."""
        ngo = make_ngo_profile()
        make_csr_requirement(ngo=ngo)
        with self.assertRaises(ProtectedError):
            ngo.delete()

    def test_protect_csr_requirement_created_by(self):
        """Deleting User creator with active CSRRequirement must raise ProtectedError."""
        ngo = make_ngo_profile()
        creator = ngo.user
        make_csr_requirement(ngo=ngo, created_by=creator)
        with self.assertRaises(ProtectedError):
            creator.delete()

    def test_protect_csr_support_request_company(self):
        """Deleting CompanyProfile with active CSRSupportRequest must raise ProtectedError."""
        company = make_company_profile()
        make_csr_support_request(company=company)
        with self.assertRaises(ProtectedError):
            company.delete()

    def test_protect_csr_support_request_requirement(self):
        """Deleting CSRRequirement with active CSRSupportRequest must raise ProtectedError."""
        requirement = make_csr_requirement()
        make_csr_support_request(requirement=requirement)
        with self.assertRaises(ProtectedError):
            requirement.delete()

    def test_protect_csr_partnership_company(self):
        """Deleting CompanyProfile with active CSRPartnership must raise ProtectedError."""
        partnership = make_csr_partnership()
        with self.assertRaises(ProtectedError):
            partnership.company.delete()

    def test_protect_csr_partnership_ngo(self):
        """Deleting NGOProfile with active CSRPartnership must raise ProtectedError."""
        partnership = make_csr_partnership()
        with self.assertRaises(ProtectedError):
            partnership.ngo.delete()

    def test_protect_csr_partnership_requirement(self):
        """Deleting CSRRequirement with active CSRPartnership must raise ProtectedError."""
        partnership = make_csr_partnership()
        with self.assertRaises(ProtectedError):
            partnership.requirement.delete()

    def test_protect_csr_partnership_support_request(self):
        """Deleting CSRSupportRequest with active CSRPartnership must raise ProtectedError."""
        partnership = make_csr_partnership()
        with self.assertRaises(ProtectedError):
            partnership.support_request.delete()

    # -----------------------------------------------------------------------
    # CASCADE Relations (3 tests)
    # -----------------------------------------------------------------------

    def test_cascade_company_profile_user(self):
        """Deleting User account cascades to delete its CompanyProfile."""
        user = make_user(role=User.Role.COMPANY)
        company = make_company_profile(user=user)
        company_id = company.id

        user.delete()
        self.assertFalse(CompanyProfile.objects.filter(id=company_id).exists())

    def test_cascade_company_csr_preference_company(self):
        """Deleting CompanyProfile cascades to delete its CompanyCSRPreference."""
        company = make_company_profile()
        pref = make_company_preference(company=company)
        pref_id = pref.id

        company.delete()
        self.assertFalse(CompanyCSRPreference.objects.filter(id=pref_id).exists())

    def test_cascade_partnership_milestone_partnership(self):
        """Deleting CSRPartnership cascades to delete its PartnershipMilestones."""
        partnership = make_csr_partnership()
        m1 = make_partnership_milestone(partnership=partnership, sequence_number=1)
        m2 = make_partnership_milestone(partnership=partnership, sequence_number=2)
        m1_id = m1.id
        m2_id = m2.id

        partnership.delete()
        self.assertFalse(PartnershipMilestone.objects.filter(id=m1_id).exists())
        self.assertFalse(PartnershipMilestone.objects.filter(id=m2_id).exists())

    # -----------------------------------------------------------------------
    # SET_NULL Relations (5 tests)
    # -----------------------------------------------------------------------

    def test_set_null_company_profile_verified_by(self):
        """Deleting reviewing admin user sets CompanyProfile.verified_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        company = make_company_profile(verified_by=admin_user)
        self.assertEqual(company.verified_by, admin_user)

        admin_user.delete()
        company.refresh_from_db()
        self.assertIsNone(company.verified_by)

    def test_set_null_csr_requirement_reviewed_by(self):
        """Deleting reviewing admin user sets CSRRequirement.reviewed_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        req = make_csr_requirement(reviewed_by=admin_user)
        self.assertEqual(req.reviewed_by, admin_user)

        admin_user.delete()
        req.refresh_from_db()
        self.assertIsNone(req.reviewed_by)

    def test_set_null_csr_support_request_reviewed_by(self):
        """Deleting reviewing admin user sets CSRSupportRequest.reviewed_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        sr = make_csr_support_request(
            status=CSRSupportRequestStatus.ACCEPTED,
            reviewed_by=admin_user,
        )
        self.assertEqual(sr.reviewed_by, admin_user)

        admin_user.delete()
        sr.refresh_from_db()
        self.assertIsNone(sr.reviewed_by)

    def test_set_null_csr_verification_history_reviewed_by(self):
        """Deleting reviewing admin user sets CSRVerificationHistory.reviewed_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        vh = make_verification_history(
            reviewed_by=admin_user,
        )
        self.assertEqual(vh.reviewed_by, admin_user)

        admin_user.delete()
        vh.refresh_from_db()
        self.assertIsNone(vh.reviewed_by)

    def test_set_null_partnership_milestone_verified_by(self):
        """Deleting verifying admin user sets PartnershipMilestone.verified_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        ms = make_partnership_milestone(
            status=MilestoneStatus.VERIFIED,
            verified_by=admin_user,
        )
        self.assertEqual(ms.verified_by, admin_user)

        admin_user.delete()
        ms.refresh_from_db()
        self.assertIsNone(ms.verified_by)
