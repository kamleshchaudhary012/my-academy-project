"""
Unit Tests for CSR Permissions and RBAC Layer — Phase CSR-2.3
==============================================================
Tests all 6 DRF permission classes enforcing role-based access control (RBAC),
database-backed ownership verification, bilateral partnership participation,
IDOR protection, and fail-closed security.
"""

from unittest.mock import Mock
from django.test import TestCase
from django.contrib.auth.models import AnonymousUser

from users.models import User
from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
)
from ngo.models import NGOProfile
from csr.permissions import (
    IsCompanyUser,
    IsVerifiedCompanyUser,
    IsRequirementOwnerNGO,
    IsSupportRequestParticipant,
    IsPartnershipParticipant,
    IsCSRAdminUser,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_support_request,
    make_csr_partnership,
    make_partnership_milestone,
)


def make_mock_request(user=None, data=None):
    """Constructs a mock DRF request with given user and data payload."""
    request = Mock()
    request.user = user if user is not None else AnonymousUser()
    request.data = data or {}
    return request


class CSRRolePermissionTests(TestCase):
    """Tests for role and verification status permission classes."""

    def setUp(self):
        self.donor_user = make_user(role=User.Role.DONOR)
        self.ngo_user = make_user(role=User.Role.NGO)
        self.company_user = make_user(role=User.Role.COMPANY)
        self.admin_user = make_user(role=User.Role.ADMIN)
        self.inactive_company_user = make_user(role=User.Role.COMPANY, is_active=False)

    # -----------------------------------------------------------------------
    # 1. IsCompanyUser Tests
    # -----------------------------------------------------------------------

    def test_is_company_user_allow(self):
        """IsCompanyUser allows authenticated active COMPANY users."""
        perm = IsCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertTrue(perm.has_permission(req, None))

    def test_is_company_user_deny_anonymous(self):
        """IsCompanyUser denies anonymous unauthenticated users."""
        perm = IsCompanyUser()
        req = make_mock_request(user=AnonymousUser())
        self.assertFalse(perm.has_permission(req, None))

    def test_is_company_user_deny_inactive(self):
        """IsCompanyUser denies inactive COMPANY users."""
        perm = IsCompanyUser()
        req = make_mock_request(user=self.inactive_company_user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_company_user_deny_donor_ngo_admin(self):
        """IsCompanyUser denies DONOR, NGO, and ADMIN users."""
        perm = IsCompanyUser()
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.ngo_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.admin_user), None))

    # -----------------------------------------------------------------------
    # 2. IsVerifiedCompanyUser Tests
    # -----------------------------------------------------------------------

    def test_is_verified_company_user_allow_approved(self):
        """IsVerifiedCompanyUser allows COMPANY users with APPROVED CompanyProfile."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.APPROVED,
        )
        perm = IsVerifiedCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertTrue(perm.has_permission(req, None))

    def test_is_verified_company_user_deny_pending(self):
        """IsVerifiedCompanyUser denies COMPANY users with PENDING_VERIFICATION CompanyProfile."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )
        perm = IsVerifiedCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_verified_company_user_deny_draft(self):
        """IsVerifiedCompanyUser denies COMPANY users with DRAFT CompanyProfile."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.DRAFT,
        )
        perm = IsVerifiedCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_verified_company_user_deny_rejected(self):
        """IsVerifiedCompanyUser denies COMPANY users with REJECTED CompanyProfile."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.REJECTED,
        )
        perm = IsVerifiedCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_verified_company_user_deny_suspended(self):
        """IsVerifiedCompanyUser denies COMPANY users with SUSPENDED CompanyProfile."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.SUSPENDED,
        )
        perm = IsVerifiedCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_verified_company_user_deny_missing_profile(self):
        """IsVerifiedCompanyUser denies COMPANY users without a CompanyProfile."""
        perm = IsVerifiedCompanyUser()
        req = make_mock_request(user=self.company_user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_verified_company_user_ignores_payload_spoofing(self):
        """IsVerifiedCompanyUser inspects server state only, ignoring payload spoofing."""
        company = make_company_profile(
            user=self.company_user,
            verification_status=CompanyVerificationStatus.DRAFT,
        )
        perm = IsVerifiedCompanyUser()
        # Malicious payload claiming to be APPROVED
        req = make_mock_request(user=self.company_user, data={'verification_status': 'APPROVED'})
        self.assertFalse(perm.has_permission(req, None))

    def test_is_verified_company_user_deny_other_roles(self):
        """IsVerifiedCompanyUser denies non-corporate roles."""
        perm = IsVerifiedCompanyUser()
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.ngo_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.admin_user), None))

    # -----------------------------------------------------------------------
    # 3. IsCSRAdminUser Tests
    # -----------------------------------------------------------------------

    def test_is_csr_admin_user_allow(self):
        """IsCSRAdminUser allows authenticated active ADMIN users."""
        perm = IsCSRAdminUser()
        req = make_mock_request(user=self.admin_user)
        self.assertTrue(perm.has_permission(req, None))
        self.assertTrue(perm.has_object_permission(req, None, None))

    def test_is_csr_admin_user_deny_non_admin(self):
        """IsCSRAdminUser denies DONOR, NGO, COMPANY, and anonymous users."""
        perm = IsCSRAdminUser()
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.ngo_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.company_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=AnonymousUser()), None))


class CSRObjectOwnershipPermissionTests(TestCase):
    """Tests for object-level ownership and IDOR protection permissions."""

    def setUp(self):
        # NGO A and NGO B
        self.ngo_user_a = make_user(role=User.Role.NGO)
        self.ngo_profile_a = make_ngo_profile(user=self.ngo_user_a)

        self.ngo_user_b = make_user(role=User.Role.NGO)
        self.ngo_profile_b = make_ngo_profile(user=self.ngo_user_b)

        # Company A and Company B
        self.company_user_a = make_user(role=User.Role.COMPANY)
        self.company_profile_a = make_company_profile(user=self.company_user_a)

        self.company_user_b = make_user(role=User.Role.COMPANY)
        self.company_profile_b = make_company_profile(user=self.company_user_b)

        # Other roles
        self.donor_user = make_user(role=User.Role.DONOR)
        self.admin_user = make_user(role=User.Role.ADMIN)

        # Domain objects
        self.req_a = make_csr_requirement(ngo=self.ngo_profile_a)
        self.req_b = make_csr_requirement(ngo=self.ngo_profile_b)

        self.support_req_a = make_csr_support_request(
            company=self.company_profile_a,
            requirement=self.req_a,
        )

        self.partnership_a = make_csr_partnership(
            company=self.company_profile_a,
            ngo=self.ngo_profile_a,
            requirement=self.req_a,
            support_request=self.support_req_a,
        )

        self.milestone_a = make_partnership_milestone(
            partnership=self.partnership_a,
            sequence_number=1,
        )

    # -----------------------------------------------------------------------
    # 4. IsRequirementOwnerNGO Tests (IDOR Protection)
    # -----------------------------------------------------------------------

    def test_is_requirement_owner_ngo_allow_owner(self):
        """IsRequirementOwnerNGO allows the owning NGO."""
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=self.ngo_user_a)
        self.assertTrue(perm.has_permission(req, None))
        self.assertTrue(perm.has_object_permission(req, None, self.req_a))

    def test_is_requirement_owner_ngo_deny_non_owner_ngo_idor(self):
        """IsRequirementOwnerNGO strictly denies another NGO (IDOR protection)."""
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=self.ngo_user_b)
        self.assertTrue(perm.has_permission(req, None))  # Role is NGO
        # But object is owned by NGO A -> DENY
        self.assertFalse(perm.has_object_permission(req, None, self.req_a))

    def test_is_requirement_owner_ngo_deny_company_donor_admin(self):
        """IsRequirementOwnerNGO denies COMPANY, DONOR, and anonymous users."""
        perm = IsRequirementOwnerNGO()
        self.assertFalse(perm.has_permission(make_mock_request(user=self.company_user_a), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=AnonymousUser()), None))

    def test_is_requirement_owner_ngo_support_request_resolution(self):
        """IsRequirementOwnerNGO recognizes ownership when evaluating a CSRSupportRequest."""
        perm = IsRequirementOwnerNGO()
        req_a = make_mock_request(user=self.ngo_user_a)
        req_b = make_mock_request(user=self.ngo_user_b)
        self.assertTrue(perm.has_object_permission(req_a, None, self.support_req_a))
        self.assertFalse(perm.has_object_permission(req_b, None, self.support_req_a))

    def test_is_requirement_owner_ngo_fail_closed_malformed(self):
        """IsRequirementOwnerNGO fails closed on malformed/arbitrary objects."""
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=self.ngo_user_a)
        self.assertFalse(perm.has_object_permission(req, None, None))
        self.assertFalse(perm.has_object_permission(req, None, object()))

    # -----------------------------------------------------------------------
    # 5. IsSupportRequestParticipant Tests (Bilateral IDOR Protection)
    # -----------------------------------------------------------------------

    def test_is_support_request_participant_allow_requesting_company(self):
        """IsSupportRequestParticipant allows the authoring Company."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.company_user_a)
        self.assertTrue(perm.has_permission(req, None))
        self.assertTrue(perm.has_object_permission(req, None, self.support_req_a))

    def test_is_support_request_participant_allow_owning_ngo(self):
        """IsSupportRequestParticipant allows the requirement-owning NGO."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.ngo_user_a)
        self.assertTrue(perm.has_permission(req, None))
        self.assertTrue(perm.has_object_permission(req, None, self.support_req_a))

    def test_is_support_request_participant_deny_unrelated_company_idor(self):
        """IsSupportRequestParticipant denies an unrelated Company (IDOR)."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.company_user_b)
        self.assertTrue(perm.has_permission(req, None))  # Role is COMPANY
        self.assertFalse(perm.has_object_permission(req, None, self.support_req_a))

    def test_is_support_request_participant_deny_unrelated_ngo_idor(self):
        """IsSupportRequestParticipant denies an unrelated NGO (IDOR)."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.ngo_user_b)
        self.assertTrue(perm.has_permission(req, None))  # Role is NGO
        self.assertFalse(perm.has_object_permission(req, None, self.support_req_a))

    def test_is_support_request_participant_deny_donor_anonymous(self):
        """IsSupportRequestParticipant denies DONOR and anonymous users."""
        perm = IsSupportRequestParticipant()
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=AnonymousUser()), None))

    def test_is_support_request_participant_fail_closed_malformed(self):
        """IsSupportRequestParticipant fails closed on malformed objects."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.company_user_a)
        self.assertFalse(perm.has_object_permission(req, None, None))
        self.assertFalse(perm.has_object_permission(req, None, object()))

    # -----------------------------------------------------------------------
    # 6. IsPartnershipParticipant Tests (Partnership & Milestone IDOR Protection)
    # -----------------------------------------------------------------------

    def test_is_partnership_participant_allow_partner_company(self):
        """IsPartnershipParticipant allows the partner Company."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.company_user_a)
        self.assertTrue(perm.has_permission(req, None))
        self.assertTrue(perm.has_object_permission(req, None, self.partnership_a))

    def test_is_partnership_participant_allow_partner_ngo(self):
        """IsPartnershipParticipant allows the partner NGO."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.ngo_user_a)
        self.assertTrue(perm.has_permission(req, None))
        self.assertTrue(perm.has_object_permission(req, None, self.partnership_a))

    def test_is_partnership_participant_deny_unrelated_company_idor(self):
        """IsPartnershipParticipant denies an unrelated Company (IDOR)."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.company_user_b)
        self.assertTrue(perm.has_permission(req, None))
        self.assertFalse(perm.has_object_permission(req, None, self.partnership_a))

    def test_is_partnership_participant_deny_unrelated_ngo_idor(self):
        """IsPartnershipParticipant denies an unrelated NGO (IDOR)."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.ngo_user_b)
        self.assertTrue(perm.has_permission(req, None))
        self.assertFalse(perm.has_object_permission(req, None, self.partnership_a))

    def test_is_partnership_participant_milestone_evaluation(self):
        """IsPartnershipParticipant correctly evaluates PartnershipMilestone objects."""
        perm = IsPartnershipParticipant()
        req_comp_a = make_mock_request(user=self.company_user_a)
        req_ngo_a = make_mock_request(user=self.ngo_user_a)
        req_comp_b = make_mock_request(user=self.company_user_b)
        req_ngo_b = make_mock_request(user=self.ngo_user_b)

        # Authorized participants in the milestone's partnership
        self.assertTrue(perm.has_object_permission(req_comp_a, None, self.milestone_a))
        self.assertTrue(perm.has_object_permission(req_ngo_a, None, self.milestone_a))

        # Unauthorized third-parties
        self.assertFalse(perm.has_object_permission(req_comp_b, None, self.milestone_a))
        self.assertFalse(perm.has_object_permission(req_ngo_b, None, self.milestone_a))

    def test_is_partnership_participant_deny_donor_anonymous(self):
        """IsPartnershipParticipant denies DONOR and anonymous users."""
        perm = IsPartnershipParticipant()
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=AnonymousUser()), None))

    def test_is_partnership_participant_fail_closed_malformed(self):
        """IsPartnershipParticipant fails closed on malformed objects."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.company_user_a)
        self.assertFalse(perm.has_object_permission(req, None, None))
        self.assertFalse(perm.has_object_permission(req, None, object()))

    # -----------------------------------------------------------------------
    # 7. NGO Approval Enforcement Tests
    # -----------------------------------------------------------------------

    def test_is_requirement_owner_ngo_denies_unapproved_draft(self):
        """IsRequirementOwnerNGO denies NGO with status=DRAFT."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.DRAFT, is_active=False)
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_requirement_owner_ngo_denies_unapproved_rejected(self):
        """IsRequirementOwnerNGO denies NGO with status=REJECTED."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.REJECTED, is_active=False)
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_requirement_owner_ngo_denies_unapproved_suspended(self):
        """IsRequirementOwnerNGO denies NGO with status=SUSPENDED."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.SUSPENDED, is_active=False)
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_requirement_owner_ngo_denies_inactive(self):
        """IsRequirementOwnerNGO denies NGO when is_active=False even if APPROVED."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.APPROVED, is_active=False)
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_requirement_owner_ngo_allows_approved(self):
        """IsRequirementOwnerNGO allows active NGO with status=APPROVED."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.APPROVED, is_active=True)
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=user)
        self.assertTrue(perm.has_permission(req, None))

    def test_is_support_request_participant_denies_unapproved_ngo(self):
        """IsSupportRequestParticipant denies NGO with status=DRAFT."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.DRAFT, is_active=False)
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=user)
        self.assertFalse(perm.has_permission(req, None))

    def test_is_partnership_participant_denies_unapproved_ngo(self):
        """IsPartnershipParticipant denies NGO with status=DRAFT."""
        user = make_user(role=User.Role.NGO)
        make_ngo_profile(user=user, status=NGOProfile.Status.DRAFT, is_active=False)
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=user)
        self.assertFalse(perm.has_permission(req, None))

