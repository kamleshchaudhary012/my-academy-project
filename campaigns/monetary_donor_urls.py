from django.urls import path
from campaigns.monetary_views import (
    DonorMonetaryContributionValidateView,
    DonorMonetaryContributionIntentView,
    DonorMonetaryDonationCreateOrderView,
    DonorMonetaryDonationVerifyPaymentView,
    DonorMonetaryDonationListView,
    DonorMonetaryDonationDetailView,
    DonorMonetaryDonationReceiptPdfView,
    DonorMonetaryDonationReceiptEmailView,
    DonorForm10BEDownloadView,
    DonorForm10BENotifyView,
)

urlpatterns = [
    path('', DonorMonetaryDonationListView.as_view(), name='donor_monetary_donation_list'),
    path('validate/', DonorMonetaryContributionValidateView.as_view(), name='donor_monetary_contribution_validate'),
    path('intent/', DonorMonetaryContributionIntentView.as_view(), name='donor_monetary_contribution_intent'),
    path('create-order/', DonorMonetaryDonationCreateOrderView.as_view(), name='donor_monetary_donation_create_order'),
    path('verify-payment/', DonorMonetaryDonationVerifyPaymentView.as_view(), name='donor_monetary_donation_verify_payment'),
    path('<uuid:id>/receipt-pdf/', DonorMonetaryDonationReceiptPdfView.as_view(), name='donor_monetary_donation_receipt_pdf'),
    path('<uuid:pk>/receipt-pdf/', DonorMonetaryDonationReceiptPdfView.as_view(), name='donor_monetary_donation_receipt_pdf_pk'),
    path('<uuid:id>/receipt-email/', DonorMonetaryDonationReceiptEmailView.as_view(), name='donor_monetary_donation_receipt_email'),
    path('<uuid:pk>/receipt-email/', DonorMonetaryDonationReceiptEmailView.as_view(), name='donor_monetary_donation_receipt_email_pk'),
    path('<uuid:id>/form-10be/', DonorForm10BEDownloadView.as_view(), name='donor_monetary_donation_form10be'),
    path('<uuid:pk>/form-10be/', DonorForm10BEDownloadView.as_view(), name='donor_monetary_donation_form10be_pk'),
    path('<uuid:id>/form-10be/notify/', DonorForm10BENotifyView.as_view(), name='donor_monetary_donation_form10be_notify'),
    path('<uuid:pk>/form-10be/notify/', DonorForm10BENotifyView.as_view(), name='donor_monetary_donation_form10be_notify_pk'),
    path('<uuid:pk>/', DonorMonetaryDonationDetailView.as_view(), name='donor_monetary_donation_detail'),
]


