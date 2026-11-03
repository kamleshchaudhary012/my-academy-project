from django.urls import path
from campaigns.public_views import (
    CampaignPublicListView,
    CampaignPublicSlugDetailView,
    PublicCampaignTrackingView,
    PublicCampaignDistributionProofListView,
    PublicDistributionProofDetailView,
)

urlpatterns = [
    path('', CampaignPublicListView.as_view(), name='campaign_public_list'),
    path('distribution-proofs/<uuid:pk>/', PublicDistributionProofDetailView.as_view(), name='public_distribution_proof_detail'),
    path('<uuid:campaign_id>/distribution-proofs/', PublicCampaignDistributionProofListView.as_view(), name='public_campaign_distribution_proof_list'),
    path('<slug:slug>/distribution-proofs/', PublicCampaignDistributionProofListView.as_view(), name='public_campaign_distribution_proof_list_slug'),
    path('<slug:slug>/tracking/', PublicCampaignTrackingView.as_view(), name='public_campaign_tracking'),
    path('<slug:slug>/', CampaignPublicSlugDetailView.as_view(), name='campaign_public_detail_slug'),
]

