"""
CSR Company API Views — Phase CSR-2.8.1
========================================
Implements the 20 COMPANY namespace API views for the CSR Connect module
as defined in CSR-2.0 Section 21.

Key Guarantees:
1. Multi-Tenant IDOR Protection via frozen permission classes.
2. Complete failure isolation and exception mapping via handle_csr_service_error.
3. Strict delegation to CSR domain service modules (no raw DB mutations in views).
4. Asynchronous email notifications dispatched strictly via transaction.on_commit.
5. Standard DRF pagination and search/ordering filters for marketplace browsing.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import generics, status, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CompanyCSRPreference,
    CSRRequirement,
    CSRRequirementStatus,
    CSRSupportRequest,
    CSRSupportRequestStatus,
    CSRPartnership,
    CSRPartnershipStatus,
    PartnershipMilestone,
    MilestoneStatus,
    CSRDisbursement,
    CSRDisbursementReviewStatus,
    CSRNgoAcknowledgementStatus,
)
from csr.permissions import (
    IsCompanyUser,
    IsVerifiedCompanyUser,
    IsPartnershipParticipant,
)
from csr.pagination import CSRStandardPagination
from csr.exception_handler import handle_csr_service_error
from csr.services.exceptions import CSRServiceError, CSRNotFoundError

from csr.serializers import (
    CompanyProfileReadSerializer,
    CompanyProfileWriteSerializer,
    CompanyCSRPreferenceSerializer,
    CSRRequirementListSerializer,
    CSRRequirementDetailSerializer,
    CSRSupportRequestCreateSerializer,
    CSRSupportRequestReadSerializer,
    CSRPartnershipListSerializer,
    CSRPartnershipDetailSerializer,
    CSRPartnershipDisbursementSerializer,
    PartnershipMilestoneSerializer,
    MilestoneReviewSerializer,
    CSRMatchResultSerializer,
)

from csr.services import (
    # Company Service
    register_company,
    get_company_for_user,
    update_company_profile,
    attach_company_document,
    request_company_verification,
    get_company_preferences,
    update_company_preferences,
    # Support Request Service
    create_support_request,
    get_support_request,
    list_outbox_for_company,
    withdraw_support_request,
    # Partnership Service
    get_partnership,
    list_partnerships_for_user,
    activate_partnership,
    record_off_platform_disbursement,
    # Milestone Service
    list_milestones,
    review_milestone,
    # Matching Engine
    get_recommended_requirements_for_company,
    # Notification Service
    CSRNotificationEventType,
    dispatch_csr_notification,
)


# ==============================================================================
# 1. Company Profile & Verification Document Views (#1 - #4)
# ==============================================================================

class CompanyProfileMeView(APIView):
    """
    Endpoints:
      GET   /api/v1/csr/profile/me/  -> Retrieve authenticated company's profile
      POST  /api/v1/csr/profile/me/  -> Register new company profile (DRAFT)
      PATCH /api/v1/csr/profile/me/  -> Update existing company profile
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]

    def get(self, request):
        try:
            company = get_company_for_user(request.user)
            serializer = CompanyProfileReadSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def post(self, request):
        if CompanyProfile.objects.filter(user=request.user).exists():
            return Response(
                {'detail': 'A company profile already exists for this user account.'},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = CompanyProfileWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            company = register_company(request.user, serializer.validated_data)
            read_serializer = CompanyProfileReadSerializer(company)
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def patch(self, request):
        serializer = CompanyProfileWriteSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            company = update_company_profile(request.user, serializer.validated_data)
            read_serializer = CompanyProfileReadSerializer(company)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanyVerificationDocumentView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/profile/verification-document/
      Upload or replace statutory verification document (e.g. Certificate of Incorporation).
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = request.FILES.get('verification_document') or request.FILES.get('file')
        if not uploaded_file:
            return Response({'detail': 'No verification document file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            company = attach_company_document(request.user, uploaded_file)
            serializer = CompanyProfileReadSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRNotFoundError:
            return Response(
                {
                    'detail': 'Please save your corporate profile details before uploading statutory verification documents.',
                    'code': 'NO_COMPANY_PROFILE',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanyVerificationSubmitView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/profile/submit/
      Submit company profile for administrative verification (DRAFT / REJECTED -> PENDING_VERIFICATION).
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]

    def post(self, request):
        try:
            company = request_company_verification(request.user)
            serializer = CompanyProfileReadSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ==============================================================================
# 2. Company CSR Preferences Views (#5 - #6)
# ==============================================================================

class CompanyPreferencesMeView(APIView):
    """
    Endpoints:
      GET       /api/v1/csr/preferences/me/  -> Retrieve matchmaking filter settings
      PUT/PATCH /api/v1/csr/preferences/me/  -> Update matchmaking filter settings
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]

    def get(self, request):
        try:
            preference = get_company_preferences(request.user)
            serializer = CompanyCSRPreferenceSerializer(preference)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def put(self, request):
        return self._update(request, partial=False)

    def patch(self, request):
        return self._update(request, partial=True)

    def _update(self, request, partial: bool):
        serializer = CompanyCSRPreferenceSerializer(data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            preference = update_company_preferences(request.user, serializer.validated_data)
            read_serializer = CompanyCSRPreferenceSerializer(preference)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ==============================================================================
# 3. Company CSR Dashboard View (#7)
# ==============================================================================

class CompanyDashboardView(APIView):
    """
    Endpoint:
      GET /api/v1/csr/dashboard/
      Aggregated metrics summary DTO for corporate dashboard.
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]

    def get(self, request):
        try:
            company = get_company_for_user(request.user)
        except CSRNotFoundError:
            return Response(
                {
                    "detail": "No company profile found for this user account.",
                    "code": "NO_COMPANY_PROFILE",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        # Check if company profile is inactive or unverified
        if not getattr(company, 'is_active', True) or company.verification_status in (
            CompanyVerificationStatus.SUSPENDED,
            CompanyVerificationStatus.REJECTED,
        ):
            return Response(
                {
                    "detail": "Company profile is inactive or unverified.",
                    "code": "PROFILE_INACTIVE",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            partnerships = list_partnerships_for_user(request.user)

            # DB-level aggregation avoids loading all partnership objects into memory
            # and replaces three separate filter+aggregate queries with one.
            financial_agg = partnerships.aggregate(
                committed_total=Sum('agreed_funding_amount'),
                disbursed_total=Sum('disbursed_amount_reported'),
            )
            committed_total = financial_agg['committed_total'] or Decimal('0.00')
            disbursed_total = financial_agg['disbursed_total'] or Decimal('0.00')

            partnership_ids = list(partnerships.values_list('id', flat=True))
            disb_qs = CSRDisbursement.objects.filter(partnership_id__in=partnership_ids).exclude(
                review_status=CSRDisbursementReviewStatus.REJECTED
            )
            # Single aggregate call with conditional sums replaces three separate queries
            disb_agg = disb_qs.aggregate(
                acknowledged=Sum(
                    'amount',
                    filter=Q(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.ACKNOWLEDGED),
                ),
                disputed=Sum(
                    'amount',
                    filter=Q(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.DISPUTED),
                ),
                pending_ack=Sum(
                    'amount',
                    filter=Q(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT),
                ),
            )
            acknowledged_total = disb_agg['acknowledged'] or Decimal('0.00')
            disputed_total = disb_agg['disputed'] or Decimal('0.00')
            pending_ack_total = disb_agg['pending_ack'] or Decimal('0.00')
            remaining_committed_balance = max(Decimal('0.00'), committed_total - acknowledged_total)

            active_partnerships_count = partnerships.filter(
                status__in=[CSRPartnershipStatus.ACTIVE, CSRPartnershipStatus.PENDING_MOU]
            ).count()

            pending_requests_count = list_outbox_for_company(
                request.user,
                status=CSRSupportRequestStatus.PENDING_NGO_REVIEW
            ).count()

            # Recommendations (Top 5)
            recommendations = get_recommended_requirements_for_company(company, limit=5)
            recommended_proposals = CSRMatchResultSerializer(recommendations, many=True).data

            dashboard_dto = {
                'company_name': company.company_name,
                'verification_status': company.verification_status,
                'annual_csr_budget': str(company.annual_csr_budget) if company.annual_csr_budget is not None else None,
                'committed_funding_total': str(committed_total),
                'disbursed_funding_total': str(disbursed_total),
                'acknowledged_funding_total': str(acknowledged_total),
                'pending_acknowledgement_total': str(pending_ack_total),
                'disputed_funding_total': str(disputed_total),
                'remaining_committed_balance': str(remaining_committed_balance),
                'active_partnerships_count': active_partnerships_count,
                'pending_requests_count': pending_requests_count,
                'recommended_proposals': recommended_proposals,
            }

            return Response(dashboard_dto, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ==============================================================================
# 4. Marketplace & Requirement Exploration Views (#8 - #10)
# ==============================================================================

class CompanyRequirementListView(generics.ListAPIView):
    """
    Endpoint:
      GET /api/v1/csr/requirements/
      Filterable, searchable, paginated list of approved CSR requirements (OPEN_FOR_CSR).
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]
    pagination_class = CSRStandardPagination
    serializer_class = CSRRequirementListSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'summary', 'description', 'ngo__display_name', 'ngo__legal_name']
    ordering_fields = ['created_at', 'required_csr_funding', 'total_estimated_budget', 'start_date', 'expected_completion_date']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = CSRRequirement.objects.filter(
            status=CSRRequirementStatus.OPEN_FOR_CSR
        ).select_related('ngo', 'created_by')

        category = self.request.query_params.get('category')
        if category and category.upper() != 'ALL':
            qs = qs.filter(schedule_vii_category=category.upper())

        state = self.request.query_params.get('state')
        if state:
            qs = qs.filter(state__iexact=state)

        district = self.request.query_params.get('district')
        if district:
            qs = qs.filter(district__iexact=district)

        min_budget = self.request.query_params.get('min_budget')
        if min_budget:
            try:
                qs = qs.filter(required_csr_funding__gte=Decimal(min_budget))
            except Exception:
                pass

        max_budget = self.request.query_params.get('max_budget')
        if max_budget:
            try:
                qs = qs.filter(required_csr_funding__lte=Decimal(max_budget))
            except Exception:
                pass

        demographic = self.request.query_params.get('demographic')
        if demographic and demographic.upper() != 'ALL':
            qs = qs.filter(beneficiary_demographic=demographic.upper())

        return qs


class CompanyRequirementRecommendedView(APIView):
    """
    Endpoint:
      GET /api/v1/csr/requirements/recommended/
      Personalized CSR requirements scored and ranked by the deterministic Matching Engine.
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]

    def get(self, request):
        try:
            company = get_company_for_user(request.user)
            limit_param = request.query_params.get('limit', '10')
            try:
                limit = int(limit_param)
            except ValueError:
                limit = 10

            min_score_param = request.query_params.get('min_score', '0.0')
            try:
                min_score = float(min_score_param)
            except ValueError:
                min_score = 0.0

            recommendations = get_recommended_requirements_for_company(
                company,
                limit=limit,
                min_score=min_score,
            )
            serializer = CSRMatchResultSerializer(recommendations, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanyRequirementDetailView(generics.RetrieveAPIView):
    """
    Endpoint:
      GET /api/v1/csr/requirements/<uuid:id>/
      Detailed proposal representation for corporate evaluation.
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]
    serializer_class = CSRRequirementDetailSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'id'

    def get_queryset(self):
        return CSRRequirement.objects.filter(
            status=CSRRequirementStatus.OPEN_FOR_CSR
        ).select_related('ngo', 'created_by')


# ==============================================================================
# 5. Support Request / Grant EOI Views (#11 - #14)
# ==============================================================================

class CompanySupportRequestListCreateView(APIView):
    """
    Endpoints:
      GET  /api/v1/csr/support-requests/ -> List company's submitted support requests (outbox)
      POST /api/v1/csr/support-requests/ -> Submit grant Expression of Interest (EOI)
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]
    pagination_class = CSRStandardPagination

    def get(self, request):
        status_filter = request.query_params.get('status')
        try:
            qs = list_outbox_for_company(request.user, status=status_filter)
            paginator = self.pagination_class()
            page = paginator.paginate_queryset(qs, request, view=self)
            if page is not None:
                serializer = CSRSupportRequestReadSerializer(page, many=True)
                return paginator.get_paginated_response(serializer.data)

            serializer = CSRSupportRequestReadSerializer(qs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def post(self, request):
        # Enforce verified company permission for submission
        permission = IsVerifiedCompanyUser()
        if not permission.has_permission(request, self):
            return Response(
                {'detail': 'Access restricted to verified and approved corporate users.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CSRSupportRequestCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            req_field = serializer.validated_data.get('requirement')
            requirement_id = getattr(req_field, 'id', req_field)
            support_request = create_support_request(request.user, requirement_id, serializer.validated_data)
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    CSRNotificationEventType.CSR_SUPPORT_REQUEST_SUBMITTED,
                    {"support_request": support_request}
                )
            )
            read_serializer = CSRSupportRequestReadSerializer(support_request)
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanySupportRequestDetailView(APIView):
    """
    Endpoint:
      GET /api/v1/csr/support-requests/<uuid:id>/
      Retrieve single support request details.
    """
    permission_classes = [IsAuthenticated, IsCompanyUser]

    def get(self, request, id):
        try:
            req_obj = get_support_request(request.user, id)
            serializer = CSRSupportRequestReadSerializer(req_obj)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanySupportRequestWithdrawView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/support-requests/<uuid:id>/withdraw/
      Withdraw a pending support request (PENDING_NGO_REVIEW -> WITHDRAWN).
    """
    permission_classes = [IsAuthenticated, IsVerifiedCompanyUser]

    def post(self, request, id):
        reason = request.data.get('reason') or request.data.get('withdrawal_reason') or 'Withdrawn by corporate sponsor.'
        try:
            req_obj = withdraw_support_request(request.user, id, reason=reason)
            serializer = CSRSupportRequestReadSerializer(req_obj)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ==============================================================================
# 6. Corporate Partnerships & Milestones Views (#15 - #20)
# ==============================================================================

class CompanyPartnershipListView(generics.ListAPIView):
    """
    Endpoint:
      GET /api/v1/csr/partnerships/
      List all bilateral CSR partnerships for the authenticated company.
    """
    permission_classes = [IsAuthenticated, IsVerifiedCompanyUser]
    pagination_class = CSRStandardPagination
    serializer_class = CSRPartnershipListSerializer

    def get_queryset(self):
        status_param = self.request.query_params.get('status')
        return list_partnerships_for_user(self.request.user, status=status_param)


class CompanyPartnershipDetailView(APIView):
    """
    Endpoint:
      GET /api/v1/csr/partnerships/<uuid:id>/
      Detailed view of bilateral partnership including agreed funding, MoU, and milestones.
    """
    permission_classes = [IsAuthenticated, IsPartnershipParticipant]

    def get(self, request, id):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
            serializer = CSRPartnershipDetailSerializer(partnership)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanyPartnershipUploadMouView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/partnerships/<uuid:id>/upload-mou/
      Upload bilateral signed MoU document to activate partnership (PENDING_MOU -> ACTIVE).
    """
    permission_classes = [IsAuthenticated, IsVerifiedCompanyUser, IsPartnershipParticipant]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, id):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        mou_file = request.FILES.get('signed_mou_document') or request.FILES.get('mou_document') or request.FILES.get('file')
        if not mou_file:
            return Response({'detail': 'Signed MoU document file is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            activated_partnership = activate_partnership(request.user, id, mou_file=mou_file)

            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    CSRNotificationEventType.CSR_PARTNERSHIP_MOU_UPLOADED,
                    {"partnership": activated_partnership}
                )
            )

            serializer = CSRPartnershipDetailSerializer(activated_partnership)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            return Response(details, status=status.HTTP_400_BAD_REQUEST)


class CompanyPartnershipReportDisbursementView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/partnerships/<uuid:id>/report-disbursement/
      Report off-platform bank transfer / CSR grant disbursement.
    """
    permission_classes = [IsAuthenticated, IsVerifiedCompanyUser, IsPartnershipParticipant]

    def post(self, request, id):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        serializer = CSRPartnershipDisbursementSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = serializer.validated_data['disbursed_amount_reported']
            notes = serializer.validated_data.get('notes', '')

            updated_partnership = record_off_platform_disbursement(
                request.user,
                id,
                disbursed_amount=amount,
                notes=notes,
            )

            read_serializer = CSRPartnershipDetailSerializer(updated_partnership)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanyPartnershipMilestoneListView(APIView):
    """
    Endpoint:
      GET /api/v1/csr/partnerships/<uuid:id>/milestones/
      List all deliverable milestones for a given partnership.
    """
    permission_classes = [IsAuthenticated, IsPartnershipParticipant]

    def get(self, request, id):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)

            milestones = list_milestones(request.user, id)
            serializer = PartnershipMilestoneSerializer(milestones, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CompanyMilestoneReviewView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/partnerships/<uuid:id>/milestones/<uuid:mid>/review/
      Review submitted milestone evidence (VERIFY or REQUEST_REVISION).
    """
    permission_classes = [IsAuthenticated, IsVerifiedCompanyUser, IsPartnershipParticipant]

    def post(self, request, id, mid):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        serializer = MilestoneReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            decision = serializer.validated_data['decision']
            notes = serializer.validated_data.get('notes', '')

            reviewed_milestone = review_milestone(
                request.user,
                mid,
                decision=decision,
                notes=notes,
            )

            if decision == 'VERIFY':
                transaction.on_commit(
                    lambda: dispatch_csr_notification(
                        CSRNotificationEventType.CSR_MILESTONE_VERIFIED,
                        {"milestone": reviewed_milestone}
                    )
                )

            read_serializer = PartnershipMilestoneSerializer(reviewed_milestone)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)
