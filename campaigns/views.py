import uuid
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, filters, serializers
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import PermissionDenied, NotFound

from campaigns.models import (
    Campaign,
    CampaignMilestone,
    CampaignReviewHistory,
    DistributionProof,
)
from campaigns.serializers import (
    CampaignSerializer,
    CampaignMilestoneSerializer,
    DistributionProofSerializer,
    DistributionProofCreateSerializer,
    AdminProofReviewSerializer,
    AdminProofDecisionSerializer,
)
from campaigns.services.milestone_service import (
    create_milestone,
    get_milestone,
    list_milestones_for_campaign,
    update_milestone,
)
from campaigns.services.distribution_proof_service import (
    create_distribution_proof,
    get_distribution_proof,
    start_proof_review,
    verify_distribution_proof,
    request_proof_revision,
    reject_distribution_proof,
)
from campaigns.services.exceptions import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignOwnershipError,
    CampaignPermissionError,
    CampaignServiceError,
    CampaignStateError,
    CampaignValidationError,
)
from campaigns.permissions import IsApprovedNGOOwner
from ngo.permissions import IsAdminUser


class NGOCampaignListCreateView(generics.ListCreateAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'short_description', 'description']
    ordering_fields = ['created_at', 'end_date', 'target_amount', 'status']

    def get_queryset(self):
        ngo = self.request.user.ngo_profile
        qs = Campaign.objects.filter(ngo=ngo)
        status_param = self.request.query_params.get('status')
        if status_param and status_param.upper() != 'ALL':
            qs = qs.filter(status=status_param.upper())
        return qs


class NGOCampaignDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    lookup_field = 'pk'

    def get_queryset(self):
        ngo = self.request.user.ngo_profile
        return Campaign.objects.filter(ngo=ngo)

    def perform_destroy(self, instance):
        if instance.status == Campaign.Status.DRAFT:
            instance.delete()
        elif instance.status in [
            Campaign.Status.ACTIVE,
            Campaign.Status.PENDING_REVIEW,
            Campaign.Status.CHANGES_REQUESTED,
            Campaign.Status.REJECTED,
        ]:
            instance.status = Campaign.Status.CANCELLED
            instance.is_active = False
            instance.save()
        elif instance.status == Campaign.Status.COMPLETED:
            raise serializers.ValidationError({
                'detail': 'Completed campaigns cannot be deleted or cancelled.'
            })
        elif instance.status == Campaign.Status.CANCELLED:
            raise serializers.ValidationError({
                'detail': 'Campaign is already cancelled.'
            })
        elif instance.status == Campaign.Status.SUSPENDED:
            raise serializers.ValidationError({
                'detail': 'Suspended campaigns cannot be cancelled by NGO.'
            })
        else:
            instance.status = Campaign.Status.CANCELLED
            instance.is_active = False
            instance.save()


# ============================================================================
# CAMPAIGN MODERATION & ADMIN REVIEW VIEWS (Phase 4.1.1)
# ============================================================================

class NGOCampaignSubmitReviewView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]

    def post(self, request, pk):
        ngo = request.user.ngo_profile
        campaign = get_object_or_404(Campaign, pk=pk, ngo=ngo)

        if campaign.status not in [Campaign.Status.DRAFT, Campaign.Status.CHANGES_REQUESTED]:
            return Response(
                {'detail': f'Campaign in status {campaign.status} cannot be submitted for review.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_st = campaign.status
        campaign.status = Campaign.Status.PENDING_REVIEW
        campaign.submitted_at = timezone.now()
        campaign.save()

        CampaignReviewHistory.objects.create(
            campaign=campaign,
            old_status=old_st,
            new_status=campaign.status,
            changed_by=request.user,
            note='NGO submitted campaign for administrative review.',
        )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)



class AdminCampaignListView(generics.ListAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'short_description', 'description', 'ngo__display_name', 'ngo__legal_name']
    ordering_fields = ['created_at', 'submitted_at', 'status']

    def get_queryset(self):
        qs = Campaign.objects.all()
        status_param = self.request.query_params.get('status')
        if status_param and status_param.upper() != 'ALL':
            qs = qs.filter(status=status_param.upper())
        return qs


class AdminCampaignDetailView(generics.RetrieveAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Campaign.objects.all()
    lookup_field = 'pk'


class AdminCampaignApproveView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)

        if campaign.status not in [Campaign.Status.PENDING_REVIEW, Campaign.Status.DRAFT]:
            return Response(
                {'detail': f'Cannot approve campaign in status {campaign.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_st = campaign.status
        campaign.status = Campaign.Status.ACTIVE
        campaign.is_active = True
        campaign.reviewed_at = timezone.now()
        campaign.reviewed_by = request.user
        campaign.save()

        CampaignReviewHistory.objects.create(
            campaign=campaign,
            old_status=old_st,
            new_status=campaign.status,
            changed_by=request.user,
            note=request.data.get('note', 'Admin approved campaign for public publishing.'),
        )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)


class AdminCampaignRequestChangesView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)
        note = request.data.get('note')

        if not note or not note.strip():
            return Response(
                {'detail': 'A review note explaining the requested changes is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_st = campaign.status
        campaign.status = Campaign.Status.CHANGES_REQUESTED
        campaign.admin_review_note = note
        campaign.reviewed_at = timezone.now()
        campaign.reviewed_by = request.user
        campaign.save()

        CampaignReviewHistory.objects.create(
            campaign=campaign,
            old_status=old_st,
            new_status=campaign.status,
            changed_by=request.user,
            note=f'Admin requested changes: {note}',
        )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)


class AdminCampaignRejectView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)
        reason = request.data.get('rejection_reason')

        if not reason or not reason.strip():
            return Response(
                {'detail': 'Rejection reason is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_st = campaign.status
        campaign.status = Campaign.Status.REJECTED
        campaign.rejection_reason = reason
        campaign.reviewed_at = timezone.now()
        campaign.reviewed_by = request.user
        campaign.save()

        CampaignReviewHistory.objects.create(
            campaign=campaign,
            old_status=old_st,
            new_status=campaign.status,
            changed_by=request.user,
            note=f'Admin rejected campaign: {reason}',
        )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)


class AdminCampaignSuspendView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)

        old_st = campaign.status
        campaign.status = Campaign.Status.SUSPENDED
        campaign.is_active = False
        campaign.save()

        CampaignReviewHistory.objects.create(
            campaign=campaign,
            old_status=old_st,
            new_status=campaign.status,
            changed_by=request.user,
            note='Admin suspended campaign appeal.',
        )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)


class AdminCampaignReopenView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)

        old_st = campaign.status
        campaign.status = Campaign.Status.DRAFT
        campaign.save()

        CampaignReviewHistory.objects.create(
            campaign=campaign,
            old_status=old_st,
            new_status=campaign.status,
            changed_by=request.user,
            note='Admin reopened campaign as DRAFT for corrections.',
        )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_200_OK)


# ============================================================================
# CAMPAIGN MILESTONE & DISTRIBUTION PROOF NGO VIEWS (Phase 5.2.3)
# ============================================================================

class NGOCampaignMilestoneListCreateView(generics.GenericAPIView):
    """
    GET:  List all chronological milestones for an authenticated NGO-owned campaign.
    POST: Create a sequential milestone on an NGO-owned campaign appeal.
    """
    serializer_class = CampaignMilestoneSerializer
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, campaign_id):
        ngo = request.user.ngo_profile
        campaign = get_object_or_404(Campaign, id=campaign_id, ngo=ngo)

        try:
            milestones = list_milestones_for_campaign(campaign=campaign, user=request.user)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)

        page = self.paginate_queryset(milestones)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(milestones, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, campaign_id):
        ngo = request.user.ngo_profile
        campaign = get_object_or_404(Campaign, id=campaign_id, ngo=ngo)

        # Enforce server-controlled authoritative campaign
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data['campaign'] = str(campaign.id)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        payload = dict(serializer.validated_data)
        payload.pop('campaign', None)

        try:
            milestone = create_milestone(
                campaign=campaign,
                user=request.user,
                **payload,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = self.get_serializer(milestone)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class NGOCampaignMilestoneDetailView(generics.GenericAPIView):
    """
    GET:       Retrieve milestone detail and evidence metrics for an NGO-owned campaign.
    PUT/PATCH: Update milestone title, description, target amount, or completion date.
    """
    serializer_class = CampaignMilestoneSerializer
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_milestone(self, pk):
        ngo = self.request.user.ngo_profile
        return get_object_or_404(CampaignMilestone, pk=pk, campaign__ngo=ngo)

    def get(self, request, pk):
        milestone = self._get_milestone(pk)
        serializer = self.get_serializer(milestone)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial=False):
        milestone = self._get_milestone(pk)

        if milestone.status == CampaignMilestone.MilestoneStatus.VERIFIED:
            return Response(
                {'detail': 'Verified milestones are sealed and cannot be modified.', 'code': 'milestone_sealed'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        # Authoritative campaign and sequence_number preservation for PUT/PATCH:
        # A milestone's campaign cannot be modified. If not provided or if different,
        # ensure serializer validates with the milestone's existing campaign.
        data['campaign'] = str(milestone.campaign_id)
        if not partial and 'sequence_number' not in data:
            data['sequence_number'] = milestone.sequence_number

        serializer = self.get_serializer(milestone, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)

        payload = dict(serializer.validated_data)
        payload.pop('campaign', None)

        try:
            updated = update_milestone(
                milestone=milestone,
                user=request.user,
                **payload,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = self.get_serializer(updated)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class NGOCampaignMilestoneProofUploadView(generics.GenericAPIView):
    """
    POST: Upload a field distribution proof photo, GPS coordinates, beneficiary
          count/demographics, and expenditure breakdown for an in-progress milestone.
    """
    serializer_class = DistributionProofCreateSerializer
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        ngo = request.user.ngo_profile
        milestone = get_object_or_404(CampaignMilestone, pk=pk, campaign__ngo=ngo)

        serializer = self.get_serializer(data=request.data, context={'request': request, 'milestone': milestone})
        serializer.is_valid(raise_exception=True)

        photo = serializer.validated_data.pop('photo', None) or request.FILES.get('photo')
        if not photo:
            return Response(
                {'detail': 'A photo file is required.', 'code': 'missing_photo'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            proof = create_distribution_proof(
                milestone=milestone,
                user=request.user,
                photo=photo,
                **serializer.validated_data,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = DistributionProofSerializer(proof, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class NGODistributionProofListView(generics.ListAPIView):
    """
    GET: Return distribution proof records belonging to the authenticated NGO across its campaigns.
    """
    serializer_class = DistributionProofSerializer
    permission_classes = [IsAuthenticated, IsApprovedNGOOwner]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['caption', 'location_name', 'beneficiary_notes']
    ordering_fields = ['created_at', 'distribution_date', 'spent_amount', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        ngo = self.request.user.ngo_profile
        qs = DistributionProof.objects.filter(
            milestone__campaign__ngo=ngo
        ).select_related(
            'milestone', 'milestone__campaign', 'submitted_by', 'reviewed_by'
        )

        status_param = self.request.query_params.get('status')
        if status_param and status_param.upper() != 'ALL':
            qs = qs.filter(status=status_param.upper())

        milestone_param = self.request.query_params.get('milestone')
        if milestone_param:
            qs = qs.filter(milestone_id=milestone_param)

        campaign_param = self.request.query_params.get('campaign')
        if campaign_param:
            qs = qs.filter(milestone__campaign_id=campaign_param)

        return qs


# ============================================================================
# Phase 5.2.4 — Admin Distribution Proof Moderation Views
# ============================================================================

class AdminDistributionProofListView(generics.ListAPIView):
    """
    GET: Admin moderation queue containing DistributionProof records across all NGOs/campaigns.
    """
    serializer_class = DistributionProofSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'caption',
        'location_name',
        'beneficiary_notes',
        'milestone__title',
        'milestone__campaign__title',
        'milestone__campaign__ngo__display_name',
    ]
    ordering_fields = ['created_at', 'distribution_date', 'spent_amount', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = DistributionProof.objects.all().select_related(
            'milestone', 'milestone__campaign', 'milestone__campaign__ngo', 'submitted_by', 'reviewed_by'
        )

        status_param = self.request.query_params.get('status')
        if status_param and status_param.upper() != 'ALL':
            qs = qs.filter(status=status_param.upper())

        campaign_param = self.request.query_params.get('campaign')
        if campaign_param:
            qs = qs.filter(milestone__campaign_id=campaign_param)

        return qs


class AdminDistributionProofDetailView(generics.RetrieveAPIView):
    """
    GET: Retrieve comprehensive DistributionProof data for administrative inspection.
    """
    serializer_class = DistributionProofSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = DistributionProof.objects.all().select_related(
        'milestone', 'milestone__campaign', 'milestone__campaign__ngo', 'submitted_by', 'reviewed_by'
    )
    lookup_field = 'pk'


class AdminDistributionProofStartReviewView(generics.GenericAPIView):
    """
    POST: Transition proof from SUBMITTED to UNDER_REVIEW by Platform Administrator.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminProofReviewSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        admin_notes = serializer.validated_data.get('admin_notes', '')

        try:
            proof = start_proof_review(
                admin_user=request.user,
                proof_id=pk,
                admin_notes=admin_notes,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = DistributionProofSerializer(proof, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class AdminDistributionProofVerifyView(generics.GenericAPIView):
    """
    POST: Approve and verify a distribution proof (UNDER_REVIEW -> VERIFIED).
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminProofReviewSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        admin_notes = serializer.validated_data.get('admin_notes', '')

        try:
            proof = verify_distribution_proof(
                admin_user=request.user,
                proof_id=pk,
                admin_notes=admin_notes,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = DistributionProofSerializer(proof, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class AdminDistributionProofRequestChangesView(generics.GenericAPIView):
    """
    POST: Request NGO revisions on proof evidence (UNDER_REVIEW -> REVISION_REQUESTED).
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminProofDecisionSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rejection_reason = serializer.validated_data.get('rejection_reason')
        admin_notes = serializer.validated_data.get('admin_notes', '')

        try:
            proof = request_proof_revision(
                admin_user=request.user,
                proof_id=pk,
                rejection_reason=rejection_reason,
                admin_notes=admin_notes,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = DistributionProofSerializer(proof, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class AdminDistributionProofRejectView(generics.GenericAPIView):
    """
    POST: Formally reject a fraudulent or illegitimate proof (UNDER_REVIEW -> REJECTED).
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = AdminProofDecisionSerializer

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rejection_reason = serializer.validated_data.get('rejection_reason')
        admin_notes = serializer.validated_data.get('admin_notes', '')

        try:
            proof = reject_distribution_proof(
                admin_user=request.user,
                proof_id=pk,
                rejection_reason=rejection_reason,
                admin_notes=admin_notes,
            )
        except CampaignValidationError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignStateError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except CampaignConflictError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST)
        except (CampaignOwnershipError, CampaignPermissionError) as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except CampaignNotFoundError as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = DistributionProofSerializer(proof, context={'request': request})
        return Response(out_serializer.data, status=status.HTTP_200_OK)



