from django.urls import path
from campaigns.views import (
    AdminCampaignListView,
    AdminCampaignDetailView,
    AdminCampaignApproveView,
    AdminCampaignRequestChangesView,
    AdminCampaignRejectView,
    AdminCampaignSuspendView,
    AdminCampaignReopenView,
    AdminDistributionProofListView,
    AdminDistributionProofDetailView,
    AdminDistributionProofStartReviewView,
    AdminDistributionProofVerifyView,
    AdminDistributionProofRequestChangesView,
    AdminDistributionProofRejectView,
)
from campaigns.monetary_views import (
    AdminMonetaryDonationListView,
    AdminMonetaryDonationReceiptPdfView,
    AdminForm10BDLedgerView,
    AdminForm10BDExportCsvView,
    AdminForm10BEDownloadView,
)

urlpatterns = [
    path('', AdminCampaignListView.as_view(), name='admin_campaign_list'),
    path('monetary-donations/', AdminMonetaryDonationListView.as_view(), name='admin_monetary_donation_list'),
    path('monetary-donations/<uuid:id>/receipt-pdf/', AdminMonetaryDonationReceiptPdfView.as_view(), name='admin_monetary_donation_receipt_pdf'),
    path('monetary-donations/<uuid:pk>/receipt-pdf/', AdminMonetaryDonationReceiptPdfView.as_view(), name='admin_monetary_donation_receipt_pdf_pk'),
    path('compliance/form-10bd/', AdminForm10BDLedgerView.as_view(), name='admin_form10bd_ledger'),
    path('compliance/form-10bd/export/', AdminForm10BDExportCsvView.as_view(), name='admin_form10bd_export_csv'),
    path('compliance/donations/<uuid:donation_id>/form-10be/', AdminForm10BEDownloadView.as_view(), name='admin_form10be_download'),
    # Phase 5.2.4 — Distribution Proof Moderation
    path('distribution-proofs/', AdminDistributionProofListView.as_view(), name='admin_distribution_proof_list'),
    path('distribution-proofs/<uuid:pk>/', AdminDistributionProofDetailView.as_view(), name='admin_distribution_proof_detail'),
    path('distribution-proofs/<uuid:pk>/start-review/', AdminDistributionProofStartReviewView.as_view(), name='admin_distribution_proof_start_review'),
    path('distribution-proofs/<uuid:pk>/verify/', AdminDistributionProofVerifyView.as_view(), name='admin_distribution_proof_verify'),
    path('distribution-proofs/<uuid:pk>/request-changes/', AdminDistributionProofRequestChangesView.as_view(), name='admin_distribution_proof_request_changes'),
    path('distribution-proofs/<uuid:pk>/reject/', AdminDistributionProofRejectView.as_view(), name='admin_distribution_proof_reject'),
    path('<uuid:pk>/', AdminCampaignDetailView.as_view(), name='admin_campaign_detail'),
    path('<uuid:pk>/approve/', AdminCampaignApproveView.as_view(), name='admin_campaign_approve'),
    path('<uuid:pk>/request-changes/', AdminCampaignRequestChangesView.as_view(), name='admin_campaign_request_changes'),
    path('<uuid:pk>/reject/', AdminCampaignRejectView.as_view(), name='admin_campaign_reject'),
    path('<uuid:pk>/suspend/', AdminCampaignSuspendView.as_view(), name='admin_campaign_suspend'),
    path('<uuid:pk>/reopen/', AdminCampaignReopenView.as_view(), name='admin_campaign_reopen'),
]

