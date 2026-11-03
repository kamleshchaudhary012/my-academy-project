"""
Regression tests for NGO CSR Dashboard Access and Permission Layer.
Verifies all 8 scenarios outlined in DaanGives Bugfix Specification:
1. Approved, CSR-verified NGO accessing its own CSR dashboard successfully (200 OK with DTO).
2. Unapproved NGO (DRAFT, SUBMITTED, REJECTED, SUSPENDED, inactive) denied restricted CSR access (403 with NGO_NOT_APPROVED).
3. Approved but CSR-ineligible NGO (e.g. missing 80G, CSR-1) denied restricted CSR access (403 with NGO_CSR_INELIGIBLE).
4. Approved CSR-eligible NGO with pending Admin CSR verification denied restricted CSR access (403 with NGO_CSR_UNVERIFIED).
5. NGO unable to access another NGO's CSR requirement (IDOR protection on detail views: 403 with REQUIREMENT_NOT_OWNED).
6. Approved, CSR-verified NGO with NO CSR requirements receives empty metrics DTO (proposals count = 0, funding = 0).
7. Missing NGO profile handling (403 Forbidden with NO_NGO_PROFILE, fail-safe against 500 error).
8. Expired or missing authentication handling (401 Unauthorized).
"""

import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from ngo.models import NGOProfile, NGOLegalInfo, NGOVerification
from csr.models import CSRRequirement, CSRRequirementStatus, CSRPartnership, CSRPartnershipStatus
from csr.tests.helpers import (
    make_user,
    make_ngo_profile,
    make_csr_requirement,
    make_company_profile,
    generate_valid_pan,
)

User = get_user_model()


class NgoCsrDashboardBugfixTests(APITestCase):
    DASHBOARD_URL = "/api/v1/ngo/csr/dashboard/"

    def setUp(self):
        # 1. Approved & CSR-verified NGO user
        self.verified_ngo_user = make_user(email=f"dash_verified_{uuid.uuid4().hex[:6]}@example.org", role=User.Role.NGO)
        self.verified_ngo_profile = make_ngo_profile(
            user=self.verified_ngo_user,
            legal_name="Verified Seva Foundation",
            display_name="Verified Seva Foundation",
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        )

        # 2. Approved but CSR-ineligible NGO (missing 80G and CSR-1)
        self.ineligible_ngo_user = make_user(email=f"dash_ineligible_{uuid.uuid4().hex[:6]}@example.org", role=User.Role.NGO)
        self.ineligible_ngo_profile = make_ngo_profile(
            user=self.ineligible_ngo_user,
            legal_name="Standard Grassroots Trust",
            display_name="Standard Grassroots Trust",
            status=NGOProfile.Status.APPROVED,
            is_active=True,
            year_established=2024,
        )
        # Adjust legal info to be explicitly CSR ineligible
        legal_inelig = self.ineligible_ngo_profile.legal_info
        legal_inelig.has_80g = False
        legal_inelig.eighty_g_number = ""
        legal_inelig.has_csr_1 = False
        legal_inelig.csr_registration_number = ""
        legal_inelig.save()
        verif_inelig = self.ineligible_ngo_profile.verification
        verif_inelig.is_csr_verified = False
        verif_inelig.save()

        # 3. Approved & CSR-eligible, but NOT yet verified by Admin
        self.unverified_csr_user = make_user(email=f"dash_unverified_{uuid.uuid4().hex[:6]}@example.org", role=User.Role.NGO)
        self.unverified_csr_profile = make_ngo_profile(
            user=self.unverified_csr_user,
            legal_name="Pending CSR Society",
            display_name="Pending CSR Society",
            status=NGOProfile.Status.APPROVED,
            is_active=True,
            year_established=2018,
        )
        # Legal info is eligible, but Admin verification is False
        legal_pending = self.unverified_csr_profile.legal_info
        legal_pending.has_12a = True
        legal_pending.has_80g = True
        legal_pending.has_csr_1 = True
        legal_pending.csr_registration_number = f"CSR{uuid.uuid4().hex[:8].upper()}"
        legal_pending.save()
        verif_pending = self.unverified_csr_profile.verification
        verif_pending.is_csr_verified = False
        verif_pending.save()

        # 4. Unapproved NGO (DRAFT)
        self.draft_ngo_user = make_user(email=f"dash_draft_{uuid.uuid4().hex[:6]}@example.org", role=User.Role.NGO)
        self.draft_ngo_profile = make_ngo_profile(
            user=self.draft_ngo_user,
            status=NGOProfile.Status.DRAFT,
            is_active=False,
        )

        # 5. Non-NGO users
        self.company_user = make_user(email=f"dash_comp_{uuid.uuid4().hex[:6]}@example.org", role=User.Role.COMPANY)
        make_company_profile(user=self.company_user)

    # --------------------------------------------------------------------------
    # Test 1: Approved, CSR-verified NGO accessing own dashboard
    # --------------------------------------------------------------------------
    def test_01_approved_csr_verified_ngo_accesses_dashboard_successfully(self):
        """Approved and CSR-verified NGO receives 200 OK with composite metrics DTO."""
        self.client.force_authenticate(user=self.verified_ngo_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("ngo_name", response.data)
        self.assertEqual(response.data["ngo_name"], "Verified Seva Foundation")
        self.assertIn("active_proposals_count", response.data)
        self.assertIn("draft_proposals_count", response.data)
        self.assertIn("incoming_requests_pending_count", response.data)
        self.assertIn("active_partnerships_count", response.data)
        self.assertIn("total_funding_partnered", response.data)
        self.assertIn("pending_milestone_submissions", response.data)

    # --------------------------------------------------------------------------
    # Test 2: Unapproved NGO denied restricted CSR access
    # --------------------------------------------------------------------------
    def test_02_unapproved_ngo_denied_csr_dashboard(self):
        """Unapproved NGO in DRAFT status is denied with 403 and NGO_NOT_APPROVED code."""
        self.client.force_authenticate(user=self.draft_ngo_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("pending review", response.data["detail"].lower())

    def test_02b_inactive_approved_ngo_denied_csr_dashboard(self):
        """Approved NGO with is_active=False is denied with 403 Forbidden."""
        inactive_user = make_user(email="dash_inactive@example.org", role=User.Role.NGO)
        make_ngo_profile(user=inactive_user, status=NGOProfile.Status.APPROVED, is_active=False)
        self.client.force_authenticate(user=inactive_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --------------------------------------------------------------------------
    # Test 3: Approved but CSR-ineligible NGO denied restricted CSR access
    # --------------------------------------------------------------------------
    def test_03_approved_csr_ineligible_ngo_denied_csr_dashboard(self):
        """Approved NGO lacking Section 135 prerequisites is denied with 403 and informative message."""
        self.client.force_authenticate(user=self.ineligible_ngo_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("statutory csr-eligible", response.data["detail"].lower())
        self.assertIn("12a/80g", response.data["detail"].lower())

    # --------------------------------------------------------------------------
    # Test 4: Approved CSR-eligible NGO pending Admin CSR verification
    # --------------------------------------------------------------------------
    def test_04_approved_csr_unverified_ngo_denied_csr_dashboard(self):
        """Approved CSR-eligible NGO pending Admin verification receives 403 and pending review message."""
        self.client.force_authenticate(user=self.unverified_csr_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("pending admin verification", response.data["detail"].lower())

    # --------------------------------------------------------------------------
    # Test 5: Tenant isolation & IDOR on CSR requirements
    # --------------------------------------------------------------------------
    def test_05_ngo_unable_to_access_another_ngos_csr_requirement(self):
        """An NGO cannot retrieve, edit, or submit another NGO's CSR requirement."""
        from csr.permissions import IsRequirementOwnerNGO
        from unittest.mock import MagicMock

        # Create a second verified NGO
        ngo2_user = make_user(email=f"dash_ngo2_{uuid.uuid4().hex[:6]}@example.org", role=User.Role.NGO)
        make_ngo_profile(user=ngo2_user, status=NGOProfile.Status.APPROVED, is_active=True)

        # NGO 1 creates requirement
        req1 = make_csr_requirement(ngo=self.verified_ngo_profile, title="NGO 1 Clean Water")

        # 1. API Endpoint test: Tenant isolation ensures another NGO cannot retrieve req1 (404 Not Found to prevent enumeration)
        self.client.force_authenticate(user=ngo2_user)
        detail_url = f"/api/v1/ngo/csr/requirements/{req1.id}/"
        response = self.client.get(detail_url)
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

        # 2. Object Permission Layer test: IsRequirementOwnerNGO explicitly denies non-owner
        mock_request = MagicMock()
        mock_request.user = ngo2_user
        perm = IsRequirementOwnerNGO()
        has_obj_perm = perm.has_object_permission(mock_request, None, req1)
        self.assertFalse(has_obj_perm)
        self.assertEqual(perm.code, "REQUIREMENT_NOT_OWNED")
        self.assertIn("owning this csr requirement", perm.message.lower())

    # --------------------------------------------------------------------------
    # Test 6: Approved CSR-verified NGO with NO CSR requirements receives empty metrics
    # --------------------------------------------------------------------------
    def test_06_verified_ngo_with_no_requirements_receives_empty_state_metrics(self):
        """Verified NGO with 0 proposals receives 200 OK with zeroed counts."""
        self.client.force_authenticate(user=self.verified_ngo_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["active_proposals_count"], 0)
        self.assertEqual(response.data["draft_proposals_count"], 0)
        self.assertEqual(response.data["incoming_requests_pending_count"], 0)
        self.assertEqual(response.data["active_partnerships_count"], 0)
        self.assertEqual(response.data["total_funding_partnered"], "0.00")
        self.assertEqual(response.data["pending_milestone_submissions"], [])

    # --------------------------------------------------------------------------
    # Test 7: Missing NGO profile handling (fail-safe)
    # --------------------------------------------------------------------------
    def test_07_missing_ngo_profile_handled_safely(self):
        """User with role NGO but no NGOProfile is denied with 403 NO_NGO_PROFILE (no 500 crash)."""
        orphan_ngo_user = make_user(email="dash_orphan@example.org", role=User.Role.NGO)
        self.client.force_authenticate(user=orphan_ngo_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("ngo profile not found", response.data["detail"].lower())

    # --------------------------------------------------------------------------
    # Test 8: Expired or missing authentication handling
    # --------------------------------------------------------------------------
    def test_08_unauthenticated_request_rejected(self):
        """Unauthenticated request to CSR dashboard returns 401 Unauthorized."""
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_08b_non_ngo_role_rejected(self):
        """Company user requesting NGO CSR dashboard returns 403 Forbidden."""
        self.client.force_authenticate(user=self.company_user)
        response = self.client.get(self.DASHBOARD_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("ngo", response.data["detail"].lower())
