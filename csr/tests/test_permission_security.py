"""
Deep Security & Adversarial IDOR Unit Tests — Phase CSR-2.4
============================================================
Exhaustive adversarial validation and stress testing of CSR permission classes:
- Role escalation attacks across all roles and unauthenticated states.
- Company-to-Company IDOR attack vectors.
- NGO-to-NGO IDOR attack vectors.
- Cross-tenant (Company <-> NGO) horizontal and vertical privilege attacks.
- Ownership reference manipulation and payload spoofing.
- Verification status bypass attempts across all non-approved states.
- Dual-tenant participant integrity on Support Requests and Partnerships.
- Milestone traversal security and parent hierarchy tampering.
- Fail-closed behavior on broken, missing, or malformed object graphs.
- Admin boundary isolation.
"""

from unittest.mock import Mock
import uuid
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


def make_mock_request(user=None, data=None, query_params=None):
    """Constructs a mock DRF request with given user, data payload, and query parameters."""
    request = Mock()
    request.user = user if user is not None else AnonymousUser()
    request.data = data or {}
    request.query_params = query_params or {}
    return request


class CSRDeepSecurityPermissionTests(TestCase):
    """Comprehensive adversarial test suite attacking the CSR permission layer."""

    def setUp(self):
        # 1. Users
        self.anonymous_user = AnonymousUser()
        self.donor_user = make_user(role=User.Role.DONOR)
        self.admin_user = make_user(role=User.Role.ADMIN)
        self.inactive_admin_user = make_user(role=User.Role.ADMIN, is_active=False)

        self.ngo_user_a = make_user(role=User.Role.NGO)
        self.ngo_user_b = make_user(role=User.Role.NGO)

        self.company_user_a = make_user(role=User.Role.COMPANY)
        self.company_user_b = make_user(role=User.Role.COMPANY)
        self.company_user_pending = make_user(role=User.Role.COMPANY)
        self.company_user_rejected = make_user(role=User.Role.COMPANY)
        self.company_user_suspended = make_user(role=User.Role.COMPANY)
        self.company_user_draft = make_user(role=User.Role.COMPANY)
        self.inactive_company_user = make_user(role=User.Role.COMPANY, is_active=False)

        # 2. Profiles
        self.ngo_a = make_ngo_profile(user=self.ngo_user_a)
        self.ngo_b = make_ngo_profile(user=self.ngo_user_b)

        self.company_a = make_company_profile(
            user=self.company_user_a,
            verification_status=CompanyVerificationStatus.APPROVED,
        )
        self.company_b = make_company_profile(
            user=self.company_user_b,
            verification_status=CompanyVerificationStatus.APPROVED,
        )
        self.company_p = make_company_profile(
            user=self.company_user_pending,
            verification_status=CompanyVerificationStatus.PENDING_VERIFICATION,
        )
        self.company_r = make_company_profile(
            user=self.company_user_rejected,
            verification_status=CompanyVerificationStatus.REJECTED,
        )
        self.company_s = make_company_profile(
            user=self.company_user_suspended,
            verification_status=CompanyVerificationStatus.SUSPENDED,
        )
        self.company_d = make_company_profile(
            user=self.company_user_draft,
            verification_status=CompanyVerificationStatus.DRAFT,
        )

        # 3. Domain Entities
        self.requirement_a = make_csr_requirement(ngo=self.ngo_a)
        self.requirement_b = make_csr_requirement(ngo=self.ngo_b)

        self.support_request_a = make_csr_support_request(
            company=self.company_a,
            requirement=self.requirement_a,
        )
        self.support_request_b = make_csr_support_request(
            company=self.company_b,
            requirement=self.requirement_b,
        )

        self.partnership_a = make_csr_partnership(
            company=self.company_a,
            ngo=self.ngo_a,
            requirement=self.requirement_a,
            support_request=self.support_request_a,
        )
        self.partnership_b = make_csr_partnership(
            company=self.company_b,
            ngo=self.ngo_b,
            requirement=self.requirement_b,
            support_request=self.support_request_b,
        )

        self.milestone_a = make_partnership_milestone(
            partnership=self.partnership_a,
            sequence_number=1,
        )
        self.milestone_b = make_partnership_milestone(
            partnership=self.partnership_b,
            sequence_number=1,
        )

    # -----------------------------------------------------------------------
    # Step 3: Role Escalation Attacks
    # -----------------------------------------------------------------------

    def test_role_escalation_is_company_user(self):
        """Every non-company role attempting to pass IsCompanyUser is denied."""
        perm = IsCompanyUser()
        attackers = [
            self.anonymous_user,
            self.donor_user,
            self.ngo_user_a,
            self.admin_user,
            self.inactive_company_user,
        ]
        for user in attackers:
            req = make_mock_request(user=user)
            self.assertFalse(
                perm.has_permission(req, None),
                f"Role escalation succeeded for user: {user}",
            )

        # Valid company user passes
        self.assertTrue(perm.has_permission(make_mock_request(user=self.company_user_a), None))

    def test_role_escalation_is_verified_company_user(self):
        """Every unapproved/non-company role attempting to pass IsVerifiedCompanyUser is denied."""
        perm = IsVerifiedCompanyUser()
        attackers = [
            self.anonymous_user,
            self.donor_user,
            self.ngo_user_a,
            self.admin_user,
            self.company_user_pending,
            self.company_user_rejected,
            self.company_user_suspended,
            self.company_user_draft,
            self.inactive_company_user,
        ]
        for user in attackers:
            req = make_mock_request(user=user)
            self.assertFalse(
                perm.has_permission(req, None),
                f"Verification bypass succeeded for user: {user}",
            )

        # Only APPROVED company user passes
        self.assertTrue(perm.has_permission(make_mock_request(user=self.company_user_a), None))
        self.assertTrue(perm.has_permission(make_mock_request(user=self.company_user_b), None))

    def test_role_escalation_is_requirement_owner_ngo(self):
        """Non-NGO roles attempting to pass IsRequirementOwnerNGO view-level check are denied."""
        perm = IsRequirementOwnerNGO()
        attackers = [
            self.anonymous_user,
            self.donor_user,
            self.company_user_a,
            self.admin_user,
        ]
        for user in attackers:
            req = make_mock_request(user=user)
            self.assertFalse(
                perm.has_permission(req, None),
                f"NGO role escalation succeeded for user: {user}",
            )

    # -----------------------------------------------------------------------
    # Step 4: Company-to-Company IDOR Attacks
    # -----------------------------------------------------------------------

    def test_company_to_company_idor_support_request(self):
        """Company A attempts to access Company B's Support Request -> DENY."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.company_user_a)

        # Company A accessing its own Support Request A -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.support_request_a))

        # Company A attacking Support Request B -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.support_request_b),
            "IDOR vulnerability: Company A accessed Company B's Support Request!",
        )

    def test_company_to_company_idor_partnership(self):
        """Company A attempts to access Company B's Partnership -> DENY."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.company_user_a)

        # Company A accessing its own Partnership A -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.partnership_a))

        # Company A attacking Partnership B -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.partnership_b),
            "IDOR vulnerability: Company A accessed Company B's Partnership!",
        )

    def test_company_to_company_idor_milestone(self):
        """Company A attempts to access Company B's Milestone -> DENY."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.company_user_a)

        # Company A accessing its own Milestone A -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.milestone_a))

        # Company A attacking Milestone B -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.milestone_b),
            "IDOR vulnerability: Company A accessed Company B's Milestone!",
        )

    # -----------------------------------------------------------------------
    # Step 5: NGO-to-NGO IDOR Attacks
    # -----------------------------------------------------------------------

    def test_ngo_to_ngo_idor_requirement(self):
        """NGO A attempts to access or modify NGO B's CSR Requirement -> DENY."""
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=self.ngo_user_a)

        # NGO A accessing its own Requirement A -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.requirement_a))

        # NGO A attacking Requirement B -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.requirement_b),
            "IDOR vulnerability: NGO A accessed NGO B's CSR Requirement!",
        )

    def test_ngo_to_ngo_idor_support_request(self):
        """NGO A attempts to access or decide on NGO B's Support Request -> DENY."""
        perm = IsSupportRequestParticipant()
        req = make_mock_request(user=self.ngo_user_a)

        # NGO A accessing Support Request A (for Requirement A) -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.support_request_a))

        # NGO A attacking Support Request B (for Requirement B) -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.support_request_b),
            "IDOR vulnerability: NGO A accessed NGO B's Support Request!",
        )

    def test_ngo_to_ngo_idor_partnership(self):
        """NGO A attempts to access NGO B's Partnership -> DENY."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.ngo_user_a)

        # NGO A accessing Partnership A -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.partnership_a))

        # NGO A attacking Partnership B -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.partnership_b),
            "IDOR vulnerability: NGO A accessed NGO B's Partnership!",
        )

    def test_ngo_to_ngo_idor_milestone(self):
        """NGO A attempts to access NGO B's Milestone -> DENY."""
        perm = IsPartnershipParticipant()
        req = make_mock_request(user=self.ngo_user_a)

        # NGO A accessing Milestone A -> ALLOW
        self.assertTrue(perm.has_object_permission(req, None, self.milestone_a))

        # NGO A attacking Milestone B -> DENY
        self.assertFalse(
            perm.has_object_permission(req, None, self.milestone_b),
            "IDOR vulnerability: NGO A accessed NGO B's Milestone!",
        )

    # -----------------------------------------------------------------------
    # Step 6: Cross-Tenant (Company <-> NGO) Attacks
    # -----------------------------------------------------------------------

    def test_cross_tenant_company_attacks_ngo_requirement(self):
        """Company A attempts to claim ownership of NGO A's or NGO B's Requirement -> DENY."""
        perm = IsRequirementOwnerNGO()
        req = make_mock_request(user=self.company_user_a)
        self.assertFalse(perm.has_permission(req, None))
        self.assertFalse(perm.has_object_permission(req, None, self.requirement_a))
        self.assertFalse(perm.has_object_permission(req, None, self.requirement_b))

    def test_cross_tenant_unrelated_company_and_ngo_support_request(self):
        """Company A attacking Support Request B, and NGO A attacking Support Request B -> DENY."""
        perm = IsSupportRequestParticipant()
        req_comp_a = make_mock_request(user=self.company_user_a)
        req_ngo_a = make_mock_request(user=self.ngo_user_a)

        self.assertFalse(perm.has_object_permission(req_comp_a, None, self.support_request_b))
        self.assertFalse(perm.has_object_permission(req_ngo_a, None, self.support_request_b))

    # -----------------------------------------------------------------------
    # Step 7: Ownership Reference Manipulation
    # -----------------------------------------------------------------------

    def test_ownership_reference_manipulation_in_payload_ignored(self):
        """Attacker passes foreign company_id and ngo_id in request body -> ignored."""
        perm_sr = IsSupportRequestParticipant()
        perm_pt = IsPartnershipParticipant()

        # Attacker Company B claims to be Company A in payload
        spoofed_payload = {
            'company_id': str(self.company_a.id),
            'company': str(self.company_a.id),
            'ngo_id': str(self.ngo_a.id),
            'user_id': str(self.company_user_a.id),
        }
        req_b = make_mock_request(user=self.company_user_b, data=spoofed_payload)

        # Still must deny access to Support Request A and Partnership A
        self.assertFalse(
            perm_sr.has_object_permission(req_b, None, self.support_request_a),
            "Vulnerability: Client payload manipulated support request authorization!",
        )
        self.assertFalse(
            perm_pt.has_object_permission(req_b, None, self.partnership_a),
            "Vulnerability: Client payload manipulated partnership authorization!",
        )

    # -----------------------------------------------------------------------
    # Step 8: Verification Bypass Attacks
    # -----------------------------------------------------------------------

    def test_verification_bypass_spoofing_payload_and_query_params(self):
        """Unverified company submits spoofed verification status and IDs -> DENY."""
        perm = IsVerifiedCompanyUser()
        unverified_users = [
            self.company_user_pending,
            self.company_user_rejected,
            self.company_user_suspended,
            self.company_user_draft,
        ]

        spoofed_data = {
            'verification_status': 'APPROVED',
            'status': 'APPROVED',
            'is_verified': True,
            'company': str(self.company_a.id),
            'user_id': str(self.company_user_a.id),
        }
        spoofed_query = {'verified': 'true', 'status': 'APPROVED'}

        for user in unverified_users:
            req = make_mock_request(user=user, data=spoofed_data, query_params=spoofed_query)
            self.assertFalse(
                perm.has_permission(req, None),
                f"Vulnerability: Verification bypassed for {user} via spoofed payload!",
            )

    # -----------------------------------------------------------------------
    # Step 9 & 10: Dual-Tenant Participant Matrix
    # -----------------------------------------------------------------------

    def test_support_request_participant_full_matrix(self):
        """Full participant matrix check on Support Request A (Company A + NGO A)."""
        perm = IsSupportRequestParticipant()

        # Legitimate participants
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.company_user_a), None, self.support_request_a))
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.ngo_user_a), None, self.support_request_a))

        # Unauthorized parties
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.company_user_b), None, self.support_request_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.ngo_user_b), None, self.support_request_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.donor_user), None, self.support_request_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.anonymous_user), None, self.support_request_a))
        # Admin must not implicitly bypass participant permission (admin uses IsCSRAdminUser)
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.admin_user), None, self.support_request_a))

    def test_partnership_participant_full_matrix(self):
        """Full participant matrix check on Partnership A (Company A + NGO A)."""
        perm = IsPartnershipParticipant()

        # Legitimate participants
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.company_user_a), None, self.partnership_a))
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.ngo_user_a), None, self.partnership_a))

        # Unauthorized parties
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.company_user_b), None, self.partnership_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.ngo_user_b), None, self.partnership_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.donor_user), None, self.partnership_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.anonymous_user), None, self.partnership_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.admin_user), None, self.partnership_a))

    # -----------------------------------------------------------------------
    # Step 11: Milestone Traversal Attacks
    # -----------------------------------------------------------------------

    def test_milestone_traversal_participant_validation(self):
        """Milestone A authorization is derived strictly from Partnership A's participants."""
        perm = IsPartnershipParticipant()

        # Legitimate participants of parent Partnership A
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.company_user_a), None, self.milestone_a))
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.ngo_user_a), None, self.milestone_a))

        # Third parties
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.company_user_b), None, self.milestone_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.ngo_user_b), None, self.milestone_a))
        self.assertFalse(perm.has_object_permission(make_mock_request(user=self.donor_user), None, self.milestone_a))

    # -----------------------------------------------------------------------
    # Step 12: Broken / Malformed Object Testing (Fail-Closed)
    # -----------------------------------------------------------------------

    def test_fail_closed_on_none_and_arbitrary_objects(self):
        """All object permissions must safely return False on None and unexpected types."""
        permissions = [
            IsRequirementOwnerNGO(),
            IsSupportRequestParticipant(),
            IsPartnershipParticipant(),
            IsCSRAdminUser(),
        ]
        test_objects = [
            None,
            object(),
            "invalid_string_object",
            12345,
            [],
            {},
            self.donor_user,  # User passed where domain model expected
        ]

        for perm in permissions:
            for obj in test_objects:
                req = make_mock_request(user=self.company_user_a)
                result = perm.has_object_permission(req, None, obj)
                # For IsCSRAdminUser, it checks request.user (which is company_user_a -> False)
                self.assertFalse(
                    result,
                    f"Permission {perm.__class__.__name__} failed to fail-closed on {obj}!",
                )

    def test_fail_closed_on_broken_relationship_graphs(self):
        """Domain permissions fail closed if foreign keys or reverse relations are missing/None."""
        # 1. Broken SupportRequest with requirement=None
        broken_sr = Mock(spec=CSRSupportRequest)
        broken_sr.company = self.company_a
        broken_sr.requirement = None

        perm_sr = IsSupportRequestParticipant()
        # NGO trying to access broken SR
        self.assertFalse(perm_sr.has_object_permission(make_mock_request(user=self.ngo_user_a), None, broken_sr))

        # 2. Broken Milestone with partnership=None
        broken_ms = Mock(spec=PartnershipMilestone)
        broken_ms.partnership = None

        perm_pt = IsPartnershipParticipant()
        self.assertFalse(perm_pt.has_object_permission(make_mock_request(user=self.company_user_a), None, broken_ms))
        self.assertFalse(perm_pt.has_object_permission(make_mock_request(user=self.ngo_user_a), None, broken_ms))

    # -----------------------------------------------------------------------
    # Step 13: Authentication Edge Cases
    # -----------------------------------------------------------------------

    def test_authentication_edge_cases(self):
        """Users with unexpected/empty roles, None user, or inactive states fail closed."""
        class MalformedUser:
            is_authenticated = True
            is_active = True
            role = "UNKNOWN_ROLE_XYZ"

        bad_user = MalformedUser()
        perm_classes = [
            IsCompanyUser,
            IsVerifiedCompanyUser,
            IsRequirementOwnerNGO,
            IsSupportRequestParticipant,
            IsPartnershipParticipant,
            IsCSRAdminUser,
        ]

        for cls in perm_classes:
            perm = cls()
            req = make_mock_request(user=bad_user)
            self.assertFalse(
                perm.has_permission(req, None),
                f"{cls.__name__} allowed unknown role!",
            )

    # -----------------------------------------------------------------------
    # Step 14: Admin Boundary Isolation
    # -----------------------------------------------------------------------

    def test_admin_boundary_isolation(self):
        """IsCSRAdminUser only allows active ADMINs; non-admin roles and inactive admin are denied."""
        perm = IsCSRAdminUser()

        # Active Admin -> ALLOW
        self.assertTrue(perm.has_permission(make_mock_request(user=self.admin_user), None))
        self.assertTrue(perm.has_object_permission(make_mock_request(user=self.admin_user), None, None))

        # Inactive Admin -> DENY
        self.assertFalse(perm.has_permission(make_mock_request(user=self.inactive_admin_user), None))

        # Non-admins -> DENY
        self.assertFalse(perm.has_permission(make_mock_request(user=self.donor_user), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.ngo_user_a), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.company_user_a), None))
        self.assertFalse(perm.has_permission(make_mock_request(user=self.anonymous_user), None))

    # -----------------------------------------------------------------------
    # Step 15: Unapproved NGO Defense in Depth
    # -----------------------------------------------------------------------

    def test_unapproved_ngo_cannot_access_csr_endpoints(self):
        """Unapproved NGO variants (DRAFT, REJECTED, SUSPENDED, inactive) are strictly denied by NGO permissions."""
        unapproved_statuses = [
            NGOProfile.Status.DRAFT,
            NGOProfile.Status.SUBMITTED,
            NGOProfile.Status.UNDER_REVIEW,
            NGOProfile.Status.CORRECTION_REQUIRED,
            NGOProfile.Status.REJECTED,
            NGOProfile.Status.SUSPENDED,
        ]
        perm_classes = [
            IsRequirementOwnerNGO,
            IsSupportRequestParticipant,
            IsPartnershipParticipant,
        ]

        for st in unapproved_statuses:
            user = make_user(role=User.Role.NGO)
            make_ngo_profile(user=user, status=st, is_active=False)
            req = make_mock_request(user=user)

            for perm_cls in perm_classes:
                perm = perm_cls()
                self.assertFalse(
                    perm.has_permission(req, None),
                    f"Permission {perm_cls.__name__} allowed unapproved NGO status '{st}'!",
                )

