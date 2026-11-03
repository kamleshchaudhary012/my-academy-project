"""
CSR Admin API Views — Phase CSR-2.8.3
======================================
Implements the 13 ADMIN namespace API views for the CSR Connect module
as defined in CSR-2.0 Section 21 (#37 - #49).

Key Guarantees:
1. Strict Administrative RBAC: All views enforce IsAuthenticated + IsCSRAdminUser.
2. Complete failure isolation and exception mapping via handle_csr_service_error.
3. Strict delegation to CSR verification_service for all administrative state mutations.
4. Asynchronous email notifications dispatched strictly via transaction.on_commit.
5. Standard DRF pagination and search/ordering filters for moderation queues.
"""

from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from rest_framework import generics, status, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CSRRequirement,
    CSRRequirementStatus,
    CSRPartnership,
    CSRPartnershipStatus,
    CSRVerificationHistory,
    CSRDisbursement,
    CSRDisbursementReviewStatus,
    CSRNgoAcknowledgementStatus,
    CSRExpense,
    CSRExpenseReviewStatus,
    PartnershipMilestone,
    MilestoneStatus,
)
from csr.permissions import IsCSRAdminUser
from csr.pagination import CSRStandardPagination
from csr.exception_handler import handle_csr_service_error
from csr.services.exceptions import CSRServiceError
from csr.services import verification_service
from csr.services.notification_service import (
    dispatch_csr_notification,
    CSRNotificationEventType,
)
from csr.serializers import (
    CompanyProfileAdminSerializer,
    CSRRequirementAdminSerializer,
    CSRPartnershipDetailSerializer,
    CSRVerificationHistorySerializer,
)


# ===========================================================================
# 1. Corporate Verification Queue & Action Views (#37 - #41)
# ===========================================================================

class AdminCompanyListView(generics.ListAPIView):
    """
    Endpoint #37: GET /api/v1/admin/csr/companies/
    Paginated moderation queue of company profiles filterable by verification status.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]
    serializer_class = CompanyProfileAdminSerializer
    pagination_class = CSRStandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["company_name", "legal_name", "cin_number", "contact_person_name", "contact_email"]
    ordering_fields = ["created_at", "updated_at", "company_name", "annual_csr_budget"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = CompanyProfile.objects.all().select_related('user', 'verified_by')
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(verification_status=status_param.upper())
        return qs


class AdminCompanyDetailView(generics.RetrieveAPIView):
    """
    Endpoint #38: GET /api/v1/admin/csr/companies/<uuid:id>/
    Detailed administrative verification dossier for a specific corporate entity.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]
    serializer_class = CompanyProfileAdminSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'id'
    queryset = CompanyProfile.objects.all().select_related('user', 'verified_by')


class AdminCompanyApproveView(APIView):
    """
    Endpoint #39: POST /api/v1/admin/csr/companies/<uuid:id>/approve/
    Approve corporate profile and trigger CSR_COMPANY_VERIFIED notification.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        notes = request.data.get('notes', '')
        try:
            company = verification_service.approve_company(
                admin_user=request.user,
                company_id=id,
                review_notes=notes,
            )
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    CSRNotificationEventType.CSR_COMPANY_VERIFIED,
                    {"company_id": str(company.id), "status": "APPROVED", "admin_notes": notes}
                )
            )
            serializer = CompanyProfileAdminSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class AdminCompanyRejectView(APIView):
    """
    Endpoint #40: POST /api/v1/admin/csr/companies/<uuid:id>/reject/
    Reject corporate profile with a mandatory reason and trigger CSR_COMPANY_REJECTED notification.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        reason = request.data.get('reason', '')
        if not reason or not str(reason).strip():
            return Response(
                {"error": "Rejection reason is mandatory.", "code": "missing_rejection_reason"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            company = verification_service.reject_company(
                admin_user=request.user,
                company_id=id,
                reason=str(reason).strip(),
            )
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    CSRNotificationEventType.CSR_COMPANY_REJECTED,
                    {"company_id": str(company.id), "status": "REJECTED", "admin_notes": reason}
                )
            )
            serializer = CompanyProfileAdminSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class AdminCompanySuspendView(APIView):
    """
    Endpoint #41: POST /api/v1/admin/csr/companies/<uuid:id>/suspend/
    Suspend an active corporate profile with a mandatory reason.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        reason = request.data.get('reason', '')
        if not reason or not str(reason).strip():
            return Response(
                {"error": "Suspension reason is mandatory.", "code": "missing_suspension_reason"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            company = verification_service.suspend_company(
                admin_user=request.user,
                company_id=id,
                reason=str(reason).strip(),
            )
            serializer = CompanyProfileAdminSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class AdminCompanyRequestCorrectionsView(APIView):
    """
    POST /api/v1/admin/csr/companies/<uuid:id>/request-correction/
    Request corrections from corporate profile with mandatory instructions.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        instructions = request.data.get('correction_instructions', '').strip()
        admin_notes = request.data.get('admin_notes', '').strip()
        if not instructions:
            return Response(
                {"error": "Correction instructions are mandatory.", "code": "missing_correction_instructions"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            company = verification_service.request_company_corrections(
                admin_user=request.user,
                company_id=id,
                correction_instructions=instructions,
                admin_notes=admin_notes,
            )
            serializer = CompanyProfileAdminSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class AdminCompanyRecordManualGovCheckView(APIView):
    """
    POST /api/v1/admin/csr/companies/<uuid:id>/record-gov-check/
    Allows Admin to record government verification result and evidence notes for corporate profile.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        outcome = request.data.get('outcome')
        if not outcome:
            return Response(
                {"error": "Outcome is mandatory.", "code": "missing_outcome"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        source = request.data.get('source', 'MANUAL_ADMIN_CHECK')
        notes = request.data.get('notes', '')

        try:
            company = verification_service.record_company_manual_verification(
                admin_user=request.user,
                company_id=id,
                outcome=outcome,
                source=source,
                notes=notes,
            )
            serializer = CompanyProfileAdminSerializer(company)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ===========================================================================
# 2. Requirement Moderation Queue & Action Views (#42 - #46)
# ===========================================================================

class AdminRequirementListView(generics.ListAPIView):
    """
    Endpoint #42: GET /api/v1/admin/csr/requirements/
    Paginated moderation queue of NGO CSR proposals.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]
    serializer_class = CSRRequirementAdminSerializer
    pagination_class = CSRStandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "summary", "ngo__legal_name", "ngo__display_name"]
    ordering_fields = ["created_at", "updated_at", "required_csr_funding", "total_estimated_budget", "title"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = CSRRequirement.objects.all().select_related('ngo', 'created_by', 'reviewed_by')
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())
        category = self.request.query_params.get('schedule_vii_category')
        if category:
            qs = qs.filter(schedule_vii_category=category.upper())
        state = self.request.query_params.get('state')
        if state:
            qs = qs.filter(state__iexact=state.strip())
        district = self.request.query_params.get('district')
        if district:
            qs = qs.filter(district__iexact=district.strip())
        return qs


class AdminRequirementDetailView(generics.RetrieveAPIView):
    """
    Endpoint #43: GET /api/v1/admin/csr/requirements/<uuid:id>/
    Detailed administrative review dossier for a specific CSR project proposal.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]
    serializer_class = CSRRequirementAdminSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'id'
    queryset = CSRRequirement.objects.all().select_related('ngo', 'created_by', 'reviewed_by')


class AdminRequirementApproveView(APIView):
    """
    Endpoint #44: POST /api/v1/admin/csr/requirements/<uuid:id>/approve/
    Approve project proposal (status -> OPEN_FOR_CSR) and trigger CSR_REQUIREMENT_APPROVED notification.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        notes = request.data.get('notes', '')
        try:
            req = verification_service.approve_requirement(
                admin_user=request.user,
                requirement_id=id,
                publish_open_for_csr=True,
                review_notes=notes,
            )
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    CSRNotificationEventType.CSR_REQUIREMENT_APPROVED,
                    {"requirement_id": str(req.id), "status": "OPEN_FOR_CSR", "admin_notes": notes}
                )
            )
            serializer = CSRRequirementAdminSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class AdminRequirementRejectView(APIView):
    """
    Endpoint #45: POST /api/v1/admin/csr/requirements/<uuid:id>/reject/
    Reject project proposal with a mandatory reason and trigger CSR_REQUIREMENT_REJECTED notification.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        reason = request.data.get('reason', '')
        if not reason or not str(reason).strip():
            return Response(
                {"error": "Rejection reason is mandatory.", "code": "missing_rejection_reason"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            req = verification_service.reject_requirement(
                admin_user=request.user,
                requirement_id=id,
                reason=str(reason).strip(),
            )
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    CSRNotificationEventType.CSR_REQUIREMENT_REJECTED,
                    {"requirement_id": str(req.id), "status": "REJECTED", "admin_notes": reason}
                )
            )
            serializer = CSRRequirementAdminSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class AdminRequirementSuspendView(APIView):
    """
    Endpoint #46: POST /api/v1/admin/csr/requirements/<uuid:id>/suspend/
    Suspend an active proposal with a mandatory reason.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def post(self, request, id):
        reason = request.data.get('reason', '')
        if not reason or not str(reason).strip():
            return Response(
                {"error": "Suspension reason is mandatory.", "code": "missing_suspension_reason"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            req = verification_service.suspend_requirement(
                admin_user=request.user,
                requirement_id=id,
                reason=str(reason).strip(),
            )
            serializer = CSRRequirementAdminSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ===========================================================================
# 3. Platform Monitoring, Audit Ledger & Analytics Views (#47 - #49)
# ===========================================================================

class AdminPartnershipListView(generics.ListAPIView):
    """
    Endpoint #47: GET /api/v1/admin/csr/partnerships/
    Platform-wide partnership monitoring and lifecycle tracking.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]
    serializer_class = CSRPartnershipDetailSerializer
    pagination_class = CSRStandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "updated_at", "agreed_funding_amount"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = CSRPartnership.objects.all().select_related(
            'company', 'company__user', 'ngo', 'ngo__user', 'requirement', 'support_request'
        ).prefetch_related('milestones')
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())
        return qs


class AdminAuditHistoryListView(generics.ListAPIView):
    """
    Endpoint #48: GET /api/v1/admin/csr/audit-history/
    Immutable audit ledger history log filterable by entity_type and entity_id.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]
    serializer_class = CSRVerificationHistorySerializer
    pagination_class = CSRStandardPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = CSRVerificationHistory.objects.all().select_related('reviewed_by')
        entity_type = self.request.query_params.get('entity_type')
        if entity_type:
            qs = qs.filter(entity_type=entity_type.upper())
        entity_id = self.request.query_params.get('entity_id')
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        return qs


class AdminAnalyticsView(APIView):
    """
    Endpoint #49: GET /api/v1/admin/csr/analytics/
    Aggregated platform-wide CSR metrics summary.
    """
    permission_classes = [IsAuthenticated, IsCSRAdminUser]

    def get(self, request):
        # Company counts
        total_companies = CompanyProfile.objects.count()
        approved_companies = CompanyProfile.objects.filter(verification_status=CompanyVerificationStatus.APPROVED).count()
        pending_companies = CompanyProfile.objects.filter(verification_status=CompanyVerificationStatus.PENDING_VERIFICATION).count()
        rejected_companies = CompanyProfile.objects.filter(verification_status=CompanyVerificationStatus.REJECTED).count()
        suspended_companies = CompanyProfile.objects.filter(verification_status=CompanyVerificationStatus.SUSPENDED).count()

        # Requirement counts
        total_requirements = CSRRequirement.objects.count()
        open_requirements = CSRRequirement.objects.filter(status=CSRRequirementStatus.OPEN_FOR_CSR).count()
        pending_requirements = CSRRequirement.objects.filter(
            status=CSRRequirementStatus.PENDING_REVIEW
        ).count()
        closed_requirements = CSRRequirement.objects.filter(
            status__in=[CSRRequirementStatus.COMPLETED, CSRRequirementStatus.PARTNERED]
        ).count()

        # Partnership counts
        total_partnerships = CSRPartnership.objects.count()
        active_partnerships = CSRPartnership.objects.filter(
            status=CSRPartnershipStatus.ACTIVE
        ).count()
        completed_partnerships = CSRPartnership.objects.filter(
            status=CSRPartnershipStatus.COMPLETED
        ).count()

        # Financial sums - cleanly separated facts
        committed_sum = CSRPartnership.objects.aggregate(total=Sum('agreed_funding_amount'))['total'] or Decimal('0.00')
        active_disbursements = CSRDisbursement.objects.exclude(review_status=CSRDisbursementReviewStatus.REJECTED)
        total_transfers_reported = active_disbursements.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_transfers_verified = CSRDisbursement.objects.filter(review_status=CSRDisbursementReviewStatus.VERIFIED).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_acknowledged_receipts = CSRDisbursement.objects.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.ACKNOWLEDGED).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_pending_acknowledgement = CSRDisbursement.objects.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_disputed_transfers = CSRDisbursement.objects.filter(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.DISPUTED).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_remaining_commitment = max(Decimal('0.00'), committed_sum - total_acknowledged_receipts)

        total_expenses_reported = CSRExpense.objects.exclude(review_status=CSRExpenseReviewStatus.REJECTED).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_expenses_verified = CSRExpense.objects.filter(review_status=CSRExpenseReviewStatus.VERIFIED).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        total_milestones = PartnershipMilestone.objects.count()
        verified_milestones = PartnershipMilestone.objects.filter(status=MilestoneStatus.VERIFIED).count()

        data = {
            "total_companies": total_companies,
            "approved_companies": approved_companies,
            "pending_companies": pending_companies,
            "rejected_companies": rejected_companies,
            "suspended_companies": suspended_companies,

            "total_requirements": total_requirements,
            "open_requirements": open_requirements,
            "pending_requirements": pending_requirements,
            "closed_requirements": closed_requirements,

            "total_partnerships": total_partnerships,
            "active_partnerships": active_partnerships,
            "completed_partnerships": completed_partnerships,

            "total_committed_funding": str(committed_sum),
            "total_disbursed_reported": str(total_transfers_reported),
            "total_transfers_reported": str(total_transfers_reported),
            "total_transfers_verified": str(total_transfers_verified),
            "total_acknowledged_receipts": str(total_acknowledged_receipts),
            "total_pending_acknowledgement": str(total_pending_acknowledgement),
            "total_disputed_transfers": str(total_disputed_transfers),
            "total_remaining_commitment": str(total_remaining_commitment),

            "total_expenses_reported": str(total_expenses_reported),
            "total_expenses_verified": str(total_expenses_verified),

            "total_milestones": total_milestones,
            "verified_milestones": verified_milestones,
        }
        return Response(data, status=status.HTTP_200_OK)
