"""
CSR Permission and RBAC Layer — Phase CSR-2.3
===============================================
Defines Django REST Framework permission classes enforcing role-based access control (RBAC),
database-backed ownership verification, bilateral partnership participation validation,
and administrative privileges for the CSR Connect module.

Frozen Permission Classes:
1. IsCompanyUser: Authenticated user with role == 'COMPANY'.
2. IsVerifiedCompanyUser: Authenticated COMPANY user with CompanyProfile.verification_status == 'APPROVED'.
3. IsRequirementOwnerNGO: Authenticated NGO user owning the targeted CSRRequirement.
4. IsSupportRequestParticipant: Authenticated COMPANY author or owning NGO of the requirement.
5. IsPartnershipParticipant: Authenticated COMPANY partner or NGO partner in the bilateral CSRPartnership.
6. IsCSRAdminUser: Authenticated administrative user with role == 'ADMIN'.
"""

from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
)
from ngo.models import NGOProfile

User = get_user_model()


class IsCompanyUser(BasePermission):
    """
    Grants access only to authenticated, active users with role == 'COMPANY'.
    Unauthenticated users, DONORs, NGOs, and non-admin users are strictly denied.
    """
    message = "Access restricted to authenticated corporate users."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and getattr(request.user, 'role', None) == User.Role.COMPANY
        )


class IsVerifiedCompanyUser(BasePermission):
    """
    Grants access only to authenticated, active corporate users whose CompanyProfile
    exists on the server and has verification_status == 'APPROVED'.
    Pending, rejected, suspended, or missing company profiles are strictly denied.
    """
    message = "Access restricted to verified and approved corporate users."

    def has_permission(self, request, view):
        if not (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and getattr(request.user, 'role', None) == User.Role.COMPANY
        ):
            return False

        try:
            return CompanyProfile.objects.filter(
                user=request.user,
                verification_status=CompanyVerificationStatus.APPROVED,
            ).exists()
        except Exception:
            return False


class IsNGOUser(BasePermission):
    """
    Grants access only to authenticated, active NGO users whose NGOProfile
    status == 'APPROVED' and is_active == True, who meet statutory CSR eligibility,
    and whose CSR status is verified by Admin.
    """
    message = "Access restricted to approved, active, and CSR-verified NGO accounts."
    code = "ACCESS_DENIED"

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and getattr(request.user, 'is_active', False)):
            return False

        if getattr(request.user, 'role', None) != User.Role.NGO and getattr(request.user, 'role', None) != 'NGO':
            self.message = "Access restricted to NGO user accounts."
            self.code = "ROLE_NOT_NGO"
            return False

        try:
            profile = NGOProfile.objects.filter(user=request.user).first()
            if not profile:
                self.message = "NGO profile not found. Please complete profile setup."
                self.code = "NO_NGO_PROFILE"
                return False

            if profile.status != NGOProfile.Status.APPROVED or not profile.is_active:
                self.message = "Access restricted to approved NGO accounts. Your registration is currently pending review."
                self.code = "NGO_NOT_APPROVED"
                return False

            legal = getattr(profile, 'legal_info', None)
            if not legal or not getattr(legal, 'is_csr_eligible', False):
                self.message = "Access restricted to statutory CSR-eligible NGOs. Your organization must hold valid 12A/80G (or 10(23C)) tax exemptions, Form CSR-1 registration, and at least 3 years operational track record under Section 135 & MCA Rule 4."
                self.code = "NGO_CSR_INELIGIBLE"
                return False

            verif = getattr(profile, 'verification', None)
            if not verif or not getattr(verif, 'is_csr_verified', False):
                self.message = "Access restricted to CSR-verified NGO accounts. Your CSR eligibility credentials are pending Admin verification."
                self.code = "NGO_CSR_UNVERIFIED"
                return False

            return True
        except Exception:
            return False


# Compatibility alias
IsVerifiedNgoUser = IsNGOUser



class IsRequirementOwnerNGO(BasePermission):
    """
    Grants access only to authenticated, active NGO users whose NGOProfile
    status == 'APPROVED', is_active == True, who have verified CSR status,
    and who own the specific CSRRequirement.
    Resolves ownership strictly from database relations, ignoring client-injected parameters.
    """
    message = "Access restricted to approved, CSR-verified NGO accounts owning this CSR requirement."
    code = "ACCESS_DENIED"

    def has_permission(self, request, view):
        if not (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and (getattr(request.user, 'role', None) == User.Role.NGO or getattr(request.user, 'role', None) == 'NGO')
        ):
            return False

        try:
            profile = NGOProfile.objects.filter(user=request.user).first()
            if not profile:
                self.message = "NGO profile not found. Please complete profile setup."
                self.code = "NO_NGO_PROFILE"
                return False

            if profile.status != NGOProfile.Status.APPROVED or not profile.is_active:
                self.message = "Access restricted to approved NGO accounts. Your registration is currently pending review."
                self.code = "NGO_NOT_APPROVED"
                return False

            legal = getattr(profile, 'legal_info', None)
            if not legal or not getattr(legal, 'is_csr_eligible', False):
                self.message = "Access restricted to statutory CSR-eligible NGOs. Your organization must hold valid 12A/80G (or 10(23C)) tax exemptions, Form CSR-1 registration, and at least 3 years operational track record under Section 135 & MCA Rule 4."
                self.code = "NGO_CSR_INELIGIBLE"
                return False

            verif = getattr(profile, 'verification', None)
            if not verif or not getattr(verif, 'is_csr_verified', False):
                self.message = "Access restricted to CSR-verified NGO accounts. Your CSR eligibility credentials are pending Admin verification."
                self.code = "NGO_CSR_UNVERIFIED"
                return False

            return True
        except Exception:
            return False

    def has_object_permission(self, request, view, obj):
        if not self.has_permission(request, view):
            return False

        ngo_profile = NGOProfile.objects.filter(user=request.user).first()
        if ngo_profile is None:
            self.message = "NGO profile not found."
            self.code = "NO_NGO_PROFILE"
            return False

        is_owner = False
        # Direct CSRRequirement
        if isinstance(obj, CSRRequirement):
            is_owner = (obj.ngo_id == ngo_profile.id or obj.ngo == ngo_profile)

        # Object with direct requirement FK (e.g. CSRSupportRequest, CSRPartnership)
        elif getattr(obj, 'requirement', None) is not None and isinstance(getattr(obj, 'requirement'), CSRRequirement):
            req = getattr(obj, 'requirement')
            is_owner = (req.ngo_id == ngo_profile.id or req.ngo == ngo_profile)

        # Direct NGOProfile
        elif isinstance(obj, NGOProfile):
            is_owner = (obj.id == ngo_profile.id or obj == ngo_profile)

        # Object with direct ngo attribute
        elif getattr(obj, 'ngo', None) is not None:
            target_ngo = getattr(obj, 'ngo')
            is_owner = (target_ngo.id == ngo_profile.id or target_ngo == ngo_profile)

        if not is_owner:
            self.message = "Access restricted to approved, CSR-verified NGO accounts owning this CSR requirement."
            self.code = "REQUIREMENT_NOT_OWNED"
            return False

        return True


class IsSupportRequestParticipant(BasePermission):
    """
    Grants access only to the legitimate participants of a CSRSupportRequest:
    1. The Company that submitted the expression of interest (support_request.company.user).
    2. The NGO that owns the related requirement (support_request.requirement.ngo.user), approved if NGO.
    All third-party companies, unrelated NGOs, and donors are strictly denied.
    """
    message = "Access restricted to the corporate applicant and owning NGO of this support request."

    def has_permission(self, request, view):
        if not (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        ):
            return False

        role = getattr(request.user, 'role', None)
        if role == User.Role.COMPANY:
            return CompanyProfile.objects.filter(user=request.user).exists()
        elif role == User.Role.NGO:
            return NGOProfile.objects.filter(
                user=request.user,
                status=NGOProfile.Status.APPROVED,
                is_active=True,
            ).exists()
        return False

    def has_object_permission(self, request, view, obj):
        if not (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        ):
            return False

        # 1. Company participant check
        company_profile = CompanyProfile.objects.filter(user=request.user).first()
        if company_profile is not None:
            obj_company = getattr(obj, 'company', None)
            if obj_company is not None and (obj_company.id == company_profile.id or obj_company == company_profile):
                return True

        # 2. NGO participant check
        ngo_profile = NGOProfile.objects.filter(user=request.user).first()
        if ngo_profile is not None:
            req = getattr(obj, 'requirement', None)
            if req is not None:
                req_ngo = getattr(req, 'ngo', None)
                if req_ngo is not None and (req_ngo.id == ngo_profile.id or req_ngo == ngo_profile):
                    return True

        return False


class IsPartnershipParticipant(BasePermission):
    """
    Grants access only to legitimate participants of a CSRPartnership (or associated PartnershipMilestone):
    1. The Company partner (partnership.company.user).
    2. The NGO partner (partnership.ngo.user / partnership.requirement.ngo.user), approved if NGO.
    All unrelated companies, unrelated NGOs, and donors are strictly denied.
    """
    message = "Access restricted to the corporate partner and NGO partner of this bilateral engagement."

    def has_permission(self, request, view):
        if not (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        ):
            return False

        role = getattr(request.user, 'role', None)
        if role == User.Role.COMPANY:
            return CompanyProfile.objects.filter(user=request.user).exists()
        elif role == User.Role.NGO:
            return NGOProfile.objects.filter(
                user=request.user,
                status=NGOProfile.Status.APPROVED,
                is_active=True,
            ).exists()
        return False

    def has_object_permission(self, request, view, obj):
        if not (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
        ):
            return False

        # Resolve CSRPartnership from target object
        partnership = obj
        if isinstance(obj, PartnershipMilestone) or hasattr(obj, 'partnership'):
            partnership = getattr(obj, 'partnership', None)

        if partnership is None or not isinstance(partnership, CSRPartnership):
            return False

        # 1. Company partner check
        company_profile = CompanyProfile.objects.filter(user=request.user).first()
        if company_profile is not None:
            p_company = getattr(partnership, 'company', None)
            if p_company is not None and (p_company.id == company_profile.id or p_company == company_profile):
                return True

        # 2. NGO partner check
        ngo_profile = NGOProfile.objects.filter(user=request.user).first()
        if ngo_profile is not None:
            p_ngo = getattr(partnership, 'ngo', None)
            if p_ngo is not None and (p_ngo.id == ngo_profile.id or p_ngo == ngo_profile):
                return True

        return False


class IsCSRAdminUser(BasePermission):
    """
    Grants access only to authenticated, active platform administrators with role == 'ADMIN'.
    DONORs, NGOs, and COMPANY users are strictly denied administrative operations.
    """
    message = "Access restricted to platform administrators."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and getattr(request.user, 'role', None) == User.Role.ADMIN
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
