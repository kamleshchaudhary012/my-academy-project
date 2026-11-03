import uuid
from decimal import Decimal
from rest_framework.pagination import PageNumberPagination
from rest_framework import generics, filters, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from campaigns.models import Campaign, CampaignMilestone, DistributionProof
from campaigns.serializers import (
    CampaignPublicSerializer,
    CampaignMilestonePublicSerializer,
    DistributionProofPublicSerializer,
)
from campaigns.services.distribution_proof_service import get_distribution_proof
from campaigns.services.exceptions import CampaignNotFoundError
from ngo.models import NGOProfile


class CampaignPublicPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50


class CampaignPublicListView(generics.ListAPIView):
    serializer_class = CampaignPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = CampaignPublicPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'short_description', 'description', 'ngo__display_name', 'ngo__legal_name']
    ordering_fields = ['created_at', 'end_date', 'target_amount', 'raised_amount']

    def get_queryset(self):
        qs = Campaign.objects.filter(
            status=Campaign.Status.ACTIVE,
            is_active=True,
            ngo__status=NGOProfile.Status.APPROVED,
            ngo__is_active=True,
        )

        ngo_slug = self.request.query_params.get('ngo_slug')
        if ngo_slug and ngo_slug.strip():
            qs = qs.filter(ngo__slug=ngo_slug.strip())

        category = self.request.query_params.get('category')
        if category and category.strip().upper() not in ('', 'ALL'):
            qs = qs.filter(category=category.strip().upper())

        campaign_type = self.request.query_params.get('campaign_type')
        if campaign_type and campaign_type.strip().upper() not in ('', 'ALL'):
            qs = qs.filter(campaign_type=campaign_type.strip().upper())

        is_featured = self.request.query_params.get('is_featured')
        if is_featured and is_featured.strip().lower() in ('true', '1'):
            qs = qs.filter(is_featured=True)

        return qs


class CampaignPublicSlugDetailView(generics.RetrieveAPIView):
    serializer_class = CampaignPublicSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return Campaign.objects.filter(
            status=Campaign.Status.ACTIVE,
            is_active=True,
            ngo__status=NGOProfile.Status.APPROVED,
            ngo__is_active=True,
        )


class PublicCampaignTrackingView(generics.GenericAPIView):
    """
    Public Campaign Tracking Overview API.
    GET /api/v1/public/campaigns/<slug:slug>/tracking/
    Provides complete public transparency for an appeal including campaign details,
    ordered milestones, verified expenditure, and verified distribution proofs.
    """
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Campaign.objects.filter(
            status__in=[Campaign.Status.ACTIVE, Campaign.Status.COMPLETED],
            is_active=True,
            ngo__status=NGOProfile.Status.APPROVED,
            ngo__is_active=True,
        ).select_related('ngo')

    def get_object(self):
        slug_or_id = self.kwargs.get('slug') or self.kwargs.get('campaign_id') or self.kwargs.get('pk')
        qs = self.get_queryset()

        try:
            val_uuid = uuid.UUID(str(slug_or_id))
            obj = qs.filter(id=val_uuid).first()
            if obj:
                return obj
        except (ValueError, AttributeError):
            pass

        obj = qs.filter(slug=slug_or_id).first()
        if not obj:
            raise NotFound("Campaign tracking not found or appeal is not currently active.")
        return obj

    def get(self, request, *args, **kwargs):
        campaign = self.get_object()

        # Query ordered milestones
        milestones_qs = CampaignMilestone.objects.filter(
            campaign=campaign
        ).order_by('sequence_number', 'created_at')

        # Flat list of all verified proofs for the campaign
        verified_proofs_qs = DistributionProof.objects.filter(
            milestone__campaign=campaign,
            status=DistributionProof.Status.VERIFIED,
        ).order_by('distribution_date', 'created_at')

        total_verified_spent = sum(
            (proof.spent_amount for proof in verified_proofs_qs),
            Decimal('0.00')
        ) if verified_proofs_qs.exists() else Decimal('0.00')

        campaign_data = CampaignPublicSerializer(campaign, context={'request': request}).data
        milestones_data = CampaignMilestonePublicSerializer(milestones_qs, many=True, context={'request': request}).data
        proofs_data = DistributionProofPublicSerializer(verified_proofs_qs, many=True, context={'request': request}).data

        return Response({
            'campaign': campaign_data,
            'total_verified_spent': f"{Decimal(total_verified_spent):.2f}",
            'milestones': milestones_data,
            'verified_distribution_proofs': proofs_data,
        }, status=status.HTTP_200_OK)


class PublicCampaignDistributionProofListView(generics.ListAPIView):
    """
    Public Verified Distribution Proof List (Campaign Scoped).
    GET /api/v1/public/campaigns/<uuid:campaign_id>/distribution-proofs/
    Returns verified DistributionProof records belonging only to the specified campaign.
    """
    serializer_class = DistributionProofPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = CampaignPublicPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['caption', 'location_name', 'beneficiary_type', 'beneficiary_notes']
    ordering_fields = ['distribution_date', 'created_at', 'spent_amount', 'beneficiary_count']
    ordering = ['-distribution_date', '-created_at']

    def get_campaign(self):
        slug_or_id = self.kwargs.get('campaign_id') or self.kwargs.get('slug')
        qs = Campaign.objects.filter(
            status__in=[Campaign.Status.ACTIVE, Campaign.Status.COMPLETED],
            is_active=True,
            ngo__status=NGOProfile.Status.APPROVED,
            ngo__is_active=True,
        )
        try:
            val_uuid = uuid.UUID(str(slug_or_id))
            campaign = qs.filter(id=val_uuid).first()
            if campaign:
                return campaign
        except (ValueError, AttributeError):
            pass

        campaign = qs.filter(slug=slug_or_id).first()
        if not campaign:
            raise NotFound("Campaign not found or is not currently active.")
        return campaign

    def get_queryset(self):
        campaign = self.get_campaign()
        qs = DistributionProof.objects.filter(
            milestone__campaign=campaign,
            status=DistributionProof.Status.VERIFIED,
        ).select_related('milestone')

        milestone_id = self.request.query_params.get('milestone')
        if milestone_id:
            try:
                m_uuid = uuid.UUID(str(milestone_id))
                qs = qs.filter(milestone_id=m_uuid)
            except (ValueError, AttributeError):
                raise NotFound("Invalid milestone filter.")

        return qs


class PublicDistributionProofDetailView(generics.GenericAPIView):
    """
    Public Verified Distribution Proof Detail API.
    GET /api/v1/public/campaigns/distribution-proofs/<uuid:pk>/
    Returns one DistributionProof only if it is in VERIFIED status.
    Unverified proofs return 404 NOT FOUND to prevent status leakage.
    """
    serializer_class = DistributionProofPublicSerializer
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        proof_pk = self.kwargs.get('pk')
        try:
            # Delegate to existing domain service with user=None for public access
            proof_obj = get_distribution_proof(proof_id=proof_pk, user=None)
        except (CampaignNotFoundError, ValueError):
            raise NotFound("Distribution proof not found.")

        # Ensure parent campaign and NGO are public
        campaign = proof_obj.milestone.campaign
        if campaign.status not in [Campaign.Status.ACTIVE, Campaign.Status.COMPLETED] or not campaign.is_active:
            raise NotFound("Distribution proof not found.")
        if not campaign.ngo.is_active or campaign.ngo.status != NGOProfile.Status.APPROVED:
            raise NotFound("Distribution proof not found.")

        serializer = self.get_serializer(proof_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)


