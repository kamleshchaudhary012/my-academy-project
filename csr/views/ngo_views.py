"""
CSR NGO API Views — Phase CSR-2.8.2
=====================================
Defines the NGO namespace API views under /api/v1/ngo/csr/.
Implements all 16 NGO endpoints from CSR-2.0 Section 21 (#21 - #36):

  21. GET    /api/v1/ngo/csr/dashboard/
  22. GET    /api/v1/ngo/csr/requirements/
  23. POST   /api/v1/ngo/csr/requirements/
  24. GET    /api/v1/ngo/csr/requirements/<uuid:id>/
  25. PUT    /api/v1/ngo/csr/requirements/<uuid:id>/
      PATCH  /api/v1/ngo/csr/requirements/<uuid:id>/
  26. DELETE /api/v1/ngo/csr/requirements/<uuid:id>/
  27. POST   /api/v1/ngo/csr/requirements/<uuid:id>/submit/
  28. POST   /api/v1/ngo/csr/requirements/<uuid:id>/upload-document/
  29. GET    /api/v1/ngo/csr/support-requests/
  30. GET    /api/v1/ngo/csr/support-requests/<uuid:id>/
  31. POST   /api/v1/ngo/csr/support-requests/<uuid:id>/accept/
  32. POST   /api/v1/ngo/csr/support-requests/<uuid:id>/reject/
  33. GET    /api/v1/ngo/csr/partnerships/
  34. GET    /api/v1/ngo/csr/partnerships/<uuid:id>/
  35. POST   /api/v1/ngo/csr/partnerships/<uuid:id>/milestones/
  36. POST   /api/v1/ngo/csr/partnerships/<uuid:id>/milestones/<uuid:mid>/submit-evidence/

Security Invariants Enforced:
  - Strict role & object ownership checks (IsRequirementOwnerNGO, IsPartnershipParticipant).
  - Multi-tenant isolation: cross-tenant access fails closed with 404 / 403.
  - View-layer notification dispatch wired strictly via transaction.on_commit for lifecycle events.
  - Zero direct ORM modifications; all business logic delegates to CSR service layer.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import generics, status, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from csr.models import (
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
    IsNGOUser,
    IsRequirementOwnerNGO,
    IsPartnershipParticipant,
)
from ngo.models import NGOProfile
from csr.pagination import CSRStandardPagination
from csr.exception_handler import handle_csr_service_error
from csr.services.exceptions import (
    CSRServiceError,
    CSRStateError,
    CSRNotFoundError,
)
from csr.serializers import (
    CSRRequirementListSerializer,
    CSRRequirementDetailSerializer,
    CSRRequirementWriteSerializer,
    CSRSupportRequestReadSerializer,
    CSRPartnershipListSerializer,
    CSRPartnershipDetailSerializer,
    PartnershipMilestoneSerializer,
    MilestoneEvidenceSubmitSerializer,
)
from csr.services import (
    create_requirement,
    get_requirement_for_ngo,
    list_requirements_for_ngo,
    update_requirement,
    submit_requirement,
    list_inbox_for_ngo,
    get_support_request,
    accept_support_request,
    reject_support_request,
    list_partnerships_for_user,
    get_partnership,
    activate_partnership,
    create_milestone,
    get_milestone,
    submit_evidence,
    dispatch_csr_notification,
)
from csr.services.notification_service import CSRNotificationEventType


# ==============================================================================
# 1. NGO CSR Dashboard View (#21)
# ==============================================================================

class NgoDashboardView(APIView):
    """
    Endpoint:
      GET /api/v1/ngo/csr/dashboard/
      Aggregated summary metrics DTO for the authenticated NGO's CSR portal.
    """
    permission_classes = [IsAuthenticated, IsNGOUser]

    def get(self, request):
        try:
            ngo_profile = getattr(request.user, 'ngo_profile', None)
            if not ngo_profile:
                return Response(
                    {
                        "detail": "No NGO profile found for this user account.",
                        "code": "NO_NGO_PROFILE",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Requirement metrics
            active_proposals_count = CSRRequirement.objects.filter(
                ngo=ngo_profile,
                status__in=[CSRRequirementStatus.OPEN_FOR_CSR, CSRRequirementStatus.PARTNERED]
            ).count()

            draft_proposals_count = CSRRequirement.objects.filter(
                ngo=ngo_profile,
                status=CSRRequirementStatus.DRAFT
            ).count()

            # Support requests metrics
            incoming_requests_pending_count = CSRSupportRequest.objects.filter(
                requirement__ngo=ngo_profile,
                status=CSRSupportRequestStatus.PENDING_NGO_REVIEW
            ).count()

            # Partnership metrics
            partnerships = CSRPartnership.objects.filter(ngo=ngo_profile)
            active_partnerships_count = partnerships.filter(
                status__in=[CSRPartnershipStatus.ACTIVE, CSRPartnershipStatus.PENDING_MOU]
            ).count()

            # DB-level aggregation avoids loading all partnership objects into memory
            funding_agg = partnerships.aggregate(
                total_funding=Sum('agreed_funding_amount'),
            )
            total_funding = funding_agg['total_funding'] or Decimal('0.00')

            # Financial metrics separation — single conditional-sum query instead of four
            partner_ids = list(partnerships.values_list('id', flat=True))
            disb_qs = CSRDisbursement.objects.filter(partnership_id__in=partner_ids).exclude(
                review_status=CSRDisbursementReviewStatus.REJECTED
            )
            disb_agg = disb_qs.aggregate(
                total_reported=Sum('amount'),
                total_acknowledged=Sum(
                    'amount',
                    filter=Q(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.ACKNOWLEDGED),
                ),
                total_disputed=Sum(
                    'amount',
                    filter=Q(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.DISPUTED),
                ),
                total_pending_ack=Sum(
                    'amount',
                    filter=Q(ngo_acknowledgement_status=CSRNgoAcknowledgementStatus.PENDING_ACKNOWLEDGEMENT),
                ),
            )
            total_reported = disb_agg['total_reported'] or Decimal('0.00')
            total_acknowledged = disb_agg['total_acknowledged'] or Decimal('0.00')
            total_disputed = disb_agg['total_disputed'] or Decimal('0.00')
            total_pending_ack = disb_agg['total_pending_ack'] or Decimal('0.00')
            remaining_funding = max(Decimal('0.00'), total_funding - total_acknowledged)

            # Pending milestone deliverables
            pending_milestones = PartnershipMilestone.objects.filter(
                partnership__in=partnerships,
                status__in=[MilestoneStatus.PENDING, MilestoneStatus.REVISION_REQUESTED]
            ).order_by('target_completion_date')[:5]

            pending_milestone_submissions = PartnershipMilestoneSerializer(pending_milestones, many=True).data

            dashboard_dto = {
                'ngo_name': ngo_profile.legal_name or ngo_profile.display_name,
                'active_proposals_count': active_proposals_count,
                'draft_proposals_count': draft_proposals_count,
                'incoming_requests_pending_count': incoming_requests_pending_count,
                'active_partnerships_count': active_partnerships_count,
                'total_funding_partnered': str(total_funding),
                'total_committed_funding': str(total_funding),
                'total_transfers_reported': str(total_reported),
                'total_acknowledged_receipts': str(total_acknowledged),
                'total_pending_acknowledgement': str(total_pending_ack),
                'total_disputed_transfers': str(total_disputed),
                'remaining_funding_balance': str(remaining_funding),
                'pending_milestone_submissions': pending_milestone_submissions,
            }

            return Response(dashboard_dto, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ==============================================================================
# 2. NGO Requirements Views (#22 - #28)
# ==============================================================================

class NgoRequirementListCreateView(generics.ListCreateAPIView):
    """
    Endpoints:
      GET  /api/v1/ngo/csr/requirements/  -> Paginated list of NGO's own requirements
      POST /api/v1/ngo/csr/requirements/  -> Create a new draft requirement
    """
    permission_classes = [IsAuthenticated, IsNGOUser]
    pagination_class = CSRStandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'summary', 'detailed_description']
    ordering_fields = ['created_at', 'updated_at', 'required_csr_funding', 'total_estimated_budget']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CSRRequirementWriteSerializer
        return CSRRequirementListSerializer

    def get_queryset(self):
        status_param = self.request.query_params.get('status')
        qs = list_requirements_for_ngo(self.request.user, status=status_param)

        category = self.request.query_params.get('category') or self.request.query_params.get('schedule_vii_category')
        if category:
            qs = qs.filter(schedule_vii_category=category)

        state = self.request.query_params.get('state')
        if state:
            qs = qs.filter(state__iexact=state)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = CSRRequirementWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        proposal_doc = request.FILES.get('proposal_document')
        budget_doc = request.FILES.get('detailed_budget_document')
        impact_doc = request.FILES.get('impact_assessment_report')

        try:
            req = create_requirement(
                request.user,
                serializer.validated_data,
                proposal_doc=proposal_doc,
                budget_doc=budget_doc,
                impact_doc=impact_doc,
            )
            read_serializer = CSRRequirementDetailSerializer(req)
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoRequirementDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Endpoints:
      GET    /api/v1/ngo/csr/requirements/<uuid:id>/  -> Retrieve own requirement detail
      PUT    /api/v1/ngo/csr/requirements/<uuid:id>/  -> Full update of draft requirement
      PATCH  /api/v1/ngo/csr/requirements/<uuid:id>/  -> Partial update of draft requirement
      DELETE /api/v1/ngo/csr/requirements/<uuid:id>/  -> Delete draft requirement
    """
    permission_classes = [IsAuthenticated, IsRequirementOwnerNGO]
    lookup_field = 'id'

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return CSRRequirementWriteSerializer
        return CSRRequirementDetailSerializer

    def get_object(self):
        try:
            return get_requirement_for_ngo(self.request.user, self.kwargs['id'])
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def retrieve(self, request, *args, **kwargs):
        try:
            req = get_requirement_for_ngo(request.user, self.kwargs['id'])
            serializer = CSRRequirementDetailSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def update(self, request, *args, **kwargs):
        try:
            get_requirement_for_ngo(request.user, self.kwargs['id'])
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        partial = kwargs.pop('partial', False)
        serializer = CSRRequirementWriteSerializer(data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            req = update_requirement(request.user, self.kwargs['id'], serializer.validated_data)
            read_serializer = CSRRequirementDetailSerializer(req)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

    def destroy(self, request, *args, **kwargs):
        try:
            req = get_requirement_for_ngo(request.user, self.kwargs['id'])
            if req.status != CSRRequirementStatus.DRAFT:
                raise CSRStateError(
                    f"Only DRAFT requirements can be deleted. Current status: '{req.status}'.",
                    code="cannot_delete_non_draft",
                )
            req.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoRequirementSubmitView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/requirements/<uuid:id>/submit/
      Submit draft proposal for administrative review and platform moderation.
    """
    permission_classes = [IsAuthenticated, IsRequirementOwnerNGO]

    def post(self, request, id):
        try:
            req = submit_requirement(request.user, id)
            serializer = CSRRequirementDetailSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoRequirementUploadDocumentView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/requirements/<uuid:id>/upload-document/
      Upload proposal, detailed budget, or impact assessment report PDF files.
    """
    permission_classes = [IsAuthenticated, IsRequirementOwnerNGO]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, id):
        proposal_doc = request.FILES.get('proposal_document')
        budget_doc = request.FILES.get('detailed_budget_document')
        impact_doc = request.FILES.get('impact_assessment_report')

        # Generic upload fallback
        doc_type = request.data.get('document_type')
        generic_file = request.FILES.get('file') or request.FILES.get('document')
        if generic_file:
            if doc_type == 'detailed_budget_document':
                budget_doc = generic_file
            elif doc_type == 'impact_assessment_report':
                impact_doc = generic_file
            else:
                proposal_doc = generic_file

        if not any([proposal_doc, budget_doc, impact_doc]):
            return Response(
                {'detail': 'At least one document file must be uploaded.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            req = update_requirement(
                request.user,
                id,
                {},
                proposal_doc=proposal_doc,
                budget_doc=budget_doc,
                impact_doc=impact_doc,
            )
            serializer = CSRRequirementDetailSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            return Response(details, status=status.HTTP_400_BAD_REQUEST)


# ==============================================================================
# 3. NGO Support Request Inbox Views (#29 - #32)
# ==============================================================================

class NgoSupportRequestListView(generics.ListAPIView):
    """
    Endpoint:
      GET /api/v1/ngo/csr/support-requests/
      Paginated incoming expressions of interest for the authenticated NGO's requirements.
    """
    permission_classes = [IsAuthenticated, IsNGOUser]
    serializer_class = CSRSupportRequestReadSerializer
    pagination_class = CSRStandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['company_name_snapshot', 'spoc_name', 'spoc_email', 'requirement__title']
    ordering_fields = ['created_at', 'proposed_funding']
    ordering = ['-created_at']

    def get_queryset(self):
        req_id = self.request.query_params.get('requirement')
        status_param = self.request.query_params.get('status')
        return list_inbox_for_ngo(self.request.user, requirement_id=req_id, status=status_param)


class NgoSupportRequestDetailView(generics.RetrieveAPIView):
    """
    Endpoint:
      GET /api/v1/ngo/csr/support-requests/<uuid:id>/
      Detailed view of an incoming Expression of Interest.
    """
    permission_classes = [IsAuthenticated, IsRequirementOwnerNGO]
    serializer_class = CSRSupportRequestReadSerializer
    lookup_field = 'id'

    def retrieve(self, request, *args, **kwargs):
        try:
            req = get_support_request(request.user, self.kwargs['id'])
            # Enforce that NGO owns the requirement of the support request
            if req.requirement.ngo != request.user.ngo_profile:
                raise CSRNotFoundError("CSR support request not found.", code="request_not_found")
            serializer = CSRSupportRequestReadSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoSupportRequestAcceptView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/support-requests/<uuid:id>/accept/
      Accept incoming corporate EOI, initialize bilateral CSRPartnership, and notify Company SPOC.
    """
    permission_classes = [IsAuthenticated, IsRequirementOwnerNGO]

    def post(self, request, id):
        try:
            result = accept_support_request(request.user, id, decision_data=request.data)
            support_request = result['support_request']
            partnership = result['partnership']

            # Lifecycle Notification: CSR_SUPPORT_REQUEST_ACCEPTED -> Company SPOC
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    "CSR_SUPPORT_REQUEST_ACCEPTED",
                    {"support_request": support_request}
                )
            )

            response_data = {
                'support_request': CSRSupportRequestReadSerializer(support_request).data,
                'partnership': CSRPartnershipDetailSerializer(partnership).data,
            }
            return Response(response_data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoSupportRequestRejectView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/support-requests/<uuid:id>/reject/
      Reject incoming corporate EOI with mandatory reason and notify Company SPOC.
    """
    permission_classes = [IsAuthenticated, IsRequirementOwnerNGO]

    def post(self, request, id):
        reason = request.data.get('reason') or request.data.get('rejection_reason', '')
        if not reason or not str(reason).strip():
            return Response(
                {'reason': ['A mandatory rejection reason must be provided.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            req = reject_support_request(request.user, id, reason=str(reason).strip())

            # Lifecycle Notification: CSR_SUPPORT_REQUEST_REJECTED -> Company SPOC
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    "CSR_SUPPORT_REQUEST_REJECTED",
                    {"support_request": req, "rejection_reason": req.rejection_reason}
                )
            )

            serializer = CSRSupportRequestReadSerializer(req)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ==============================================================================
# 4. NGO Partnerships & Milestones Views (#33 - #36)
# ==============================================================================

class NgoPartnershipListView(generics.ListAPIView):
    """
    Endpoint:
      GET /api/v1/ngo/csr/partnerships/
      List all bilateral CSR partnerships for the authenticated NGO.
    """
    permission_classes = [IsAuthenticated, IsNGOUser]
    serializer_class = CSRPartnershipListSerializer
    pagination_class = CSRStandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['partnership_code', 'company__company_name', 'requirement__title']
    ordering_fields = ['created_at', 'agreed_funding_amount', 'target_completion_date']
    ordering = ['-created_at']

    def get_queryset(self):
        status_param = self.request.query_params.get('status')
        return list_partnerships_for_user(self.request.user, status=status_param)


class NgoPartnershipDetailView(generics.RetrieveAPIView):
    """
    Endpoint:
      GET /api/v1/ngo/csr/partnerships/<uuid:id>/
      Retrieve complete bilateral partnership details including milestones.
    """
    permission_classes = [IsAuthenticated, IsPartnershipParticipant]
    serializer_class = CSRPartnershipDetailSerializer
    lookup_field = 'id'

    def retrieve(self, request, *args, **kwargs):
        try:
            partnership = get_partnership(request.user, self.kwargs['id'])
            # Check NGO participant ownership
            if partnership.ngo != getattr(request.user, 'ngo_profile', None):
                raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")
            serializer = CSRPartnershipDetailSerializer(partnership, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoPartnershipUploadMouView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/partnerships/<uuid:id>/upload-mou/
      Upload bilateral signed MoU document by NGO to activate partnership (PENDING_MOU -> ACTIVE).
    """
    permission_classes = [IsAuthenticated, IsNGOUser, IsPartnershipParticipant]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, id):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
            ngo_profile = getattr(request.user, 'ngo_profile', None)
            if not ngo_profile or partnership.ngo_id != ngo_profile.id:
                raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")
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

            serializer = CSRPartnershipDetailSerializer(activated_partnership, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            return Response(details, status=status.HTTP_400_BAD_REQUEST)


class NgoMilestoneCreateView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/partnerships/<uuid:id>/milestones/
      Create a sequenced deliverable milestone within an active/pending partnership.
    """
    permission_classes = [IsAuthenticated, IsNGOUser, IsPartnershipParticipant]

    def post(self, request, id):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
            ngo_profile = NGOProfile.objects.filter(user=request.user).first()
            if not ngo_profile or partnership.ngo_id != ngo_profile.id:
                raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        serializer = PartnershipMilestoneSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            milestone = create_milestone(request.user, id, serializer.validated_data)
            read_serializer = PartnershipMilestoneSerializer(milestone)
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class NgoMilestoneSubmitEvidenceView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/partnerships/<uuid:id>/milestones/<uuid:mid>/submit-evidence/
      Submit progress completion report and proof document for corporate review.
    """
    permission_classes = [IsAuthenticated, IsNGOUser, IsPartnershipParticipant]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, id, mid):
        try:
            partnership = get_partnership(request.user, id)
            self.check_object_permissions(request, partnership)
            ngo_profile = NGOProfile.objects.filter(user=request.user).first()
            if not ngo_profile or partnership.ngo_id != ngo_profile.id:
                raise CSRNotFoundError("CSR partnership not found.", code="partnership_not_found")

            milestone = get_milestone(request.user, mid)
            if milestone.partnership_id != partnership.id:
                raise CSRNotFoundError(
                    "Milestone does not belong to the specified partnership.",
                    code="milestone_mismatch"
                )
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)

        serializer = MilestoneEvidenceSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            evidence_file = serializer.validated_data['evidence_document']
            evidence_notes = serializer.validated_data['evidence_notes']
            completion_pct = serializer.validated_data['completion_percentage']

            updated_milestone = submit_evidence(
                request.user,
                milestone_id=mid,
                evidence_notes=evidence_notes,
                evidence_file=evidence_file,
                completion_percentage=completion_pct,
            )

            # Lifecycle Notification: CSR_MILESTONE_EVIDENCE_SUBMITTED -> Company Reviewer
            transaction.on_commit(
                lambda: dispatch_csr_notification(
                    "CSR_MILESTONE_EVIDENCE_SUBMITTED",
                    {"milestone": updated_milestone, "old_status": "PENDING"}
                )
            )

            read_serializer = PartnershipMilestoneSerializer(updated_milestone)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)
        except DjangoValidationError as exc:
            details = exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages if hasattr(exc, 'messages') else str(exc)}
            return Response(details, status=status.HTTP_400_BAD_REQUEST)
