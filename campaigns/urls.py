from django.urls import path
from campaigns.views import (
    NGOCampaignListCreateView,
    NGOCampaignDetailView,
    NGOCampaignSubmitReviewView,
    NGOCampaignMilestoneListCreateView,
    NGOCampaignMilestoneDetailView,
    NGOCampaignMilestoneProofUploadView,
    NGODistributionProofListView,
)
from campaigns.monetary_views import (
    NGOMonetaryDonationListView,
    NGOMonetaryDonationReceiptPdfView,
    NGOForm10BDLedgerView,
    NGOForm10BDExportCsvView,
    NGOForm10BEUploadView,
    NGOForm10BEDownloadView,
)

urlpatterns = [
    path('', NGOCampaignListCreateView.as_view(), name='ngo_campaign_list_create'),
    path('distribution-proofs/', NGODistributionProofListView.as_view(), name='ngo_distribution_proof_list'),
    path('milestones/<uuid:pk>/', NGOCampaignMilestoneDetailView.as_view(), name='ngo_campaign_milestone_detail'),
    path('milestones/<uuid:pk>/proofs/', NGOCampaignMilestoneProofUploadView.as_view(), name='ngo_campaign_milestone_proof_upload'),
    path('<uuid:campaign_id>/milestones/', NGOCampaignMilestoneListCreateView.as_view(), name='ngo_campaign_milestones_list_create'),
    path('<uuid:pk>/', NGOCampaignDetailView.as_view(), name='ngo_campaign_detail'),
    path('<uuid:pk>/submit-review/', NGOCampaignSubmitReviewView.as_view(), name='ngo_campaign_submit_review'),
    path('monetary-donations/', NGOMonetaryDonationListView.as_view(), name='ngo_monetary_donation_list'),
    path('monetary-donations/<uuid:id>/receipt-pdf/', NGOMonetaryDonationReceiptPdfView.as_view(), name='ngo_monetary_donation_receipt_pdf'),
    path('monetary-donations/<uuid:pk>/receipt-pdf/', NGOMonetaryDonationReceiptPdfView.as_view(), name='ngo_monetary_donation_receipt_pdf_pk'),
    path('compliance/form-10bd/', NGOForm10BDLedgerView.as_view(), name='ngo_form10bd_ledger'),
    path('compliance/form-10bd/export/', NGOForm10BDExportCsvView.as_view(), name='ngo_form10bd_export_csv'),
    path('compliance/donations/<uuid:donation_id>/form-10be/', NGOForm10BEUploadView.as_view(), name='ngo_form10be_upload'),
    path('compliance/donations/<uuid:donation_id>/form-10be/download/', NGOForm10BEDownloadView.as_view(), name='ngo_form10be_download'),
]


