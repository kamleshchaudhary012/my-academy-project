from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from campaigns.monetary_views import (
    RazorpayWebhookView,
    NGOMonetaryDonationListView,
    AdminMonetaryDonationListView,
    NGOMonetaryDonationReceiptPdfView,
    AdminMonetaryDonationReceiptPdfView,
    NGOForm10BDLedgerView,
    NGOForm10BDExportCsvView,
    AdminForm10BDLedgerView,
    AdminForm10BDExportCsvView,
    NGOForm10BEUploadView,
    NGOForm10BEDownloadView,
    AdminForm10BEDownloadView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('users.urls')),
    path('api/v1/projects/', include('projects.urls')),
    path('api/v1/csr/', include('csr.urls')),
    path('api/v1/ngo/csr/', include('csr.ngo_urls')),
    path('api/v1/admin/csr/', include('csr.admin_urls')),
    path('api/v1/ngo/', include('ngo.urls')),
    path('api/v1/public/ngos/', include('ngo.public_urls')),
    path('api/v1/admin/ngos/', include('ngo.admin_urls')),
    path('api/v1/admin/projects/', include('projects.admin_urls')),
    path('api/v1/ngo/campaigns/', include('campaigns.urls')),
    path('api/v1/admin/campaigns/', include('campaigns.admin_urls')),
    path('api/v1/public/campaigns/', include('campaigns.public_urls')),
    path('api/v1/donor/monetary-donations/', include('campaigns.monetary_donor_urls')),
    path('api/v1/grievances/', include('grievances.urls')),
    path('api/v1/analytics/', include('analytics.urls')),
    path('api/v1/ngo/monetary-donations/', NGOMonetaryDonationListView.as_view(), name='ngo_monetary_donations_direct'),
    path('api/v1/ngo/monetary-donations/<uuid:id>/receipt-pdf/', NGOMonetaryDonationReceiptPdfView.as_view(), name='ngo_monetary_donation_receipt_pdf_direct'),
    path('api/v1/ngo/monetary-donations/<uuid:pk>/receipt-pdf/', NGOMonetaryDonationReceiptPdfView.as_view(), name='ngo_monetary_donation_receipt_pdf_direct_pk'),
    path('api/v1/ngo/compliance/form-10bd/', NGOForm10BDLedgerView.as_view(), name='ngo_compliance_form10bd_direct'),
    path('api/v1/ngo/compliance/form-10bd/export/', NGOForm10BDExportCsvView.as_view(), name='ngo_compliance_form10bd_export_direct'),
    path('api/v1/ngo/compliance/donations/<uuid:donation_id>/form-10be/', NGOForm10BEUploadView.as_view(), name='ngo_compliance_form10be_upload_direct'),
    path('api/v1/ngo/compliance/donations/<uuid:donation_id>/form-10be/download/', NGOForm10BEDownloadView.as_view(), name='ngo_compliance_form10be_download_direct'),
    path('api/v1/admin/monetary-donations/', AdminMonetaryDonationListView.as_view(), name='admin_monetary_donations_direct'),
    path('api/v1/admin/monetary-donations/<uuid:id>/receipt-pdf/', AdminMonetaryDonationReceiptPdfView.as_view(), name='admin_monetary_donation_receipt_pdf_direct'),
    path('api/v1/admin/monetary-donations/<uuid:pk>/receipt-pdf/', AdminMonetaryDonationReceiptPdfView.as_view(), name='admin_monetary_donation_receipt_pdf_direct_pk'),
    path('api/v1/admin/compliance/form-10bd/', AdminForm10BDLedgerView.as_view(), name='admin_compliance_form10bd_direct'),
    path('api/v1/admin/compliance/form-10bd/export/', AdminForm10BDExportCsvView.as_view(), name='admin_compliance_form10bd_export_direct'),
    path('api/v1/admin/compliance/donations/<uuid:donation_id>/form-10be/', AdminForm10BEDownloadView.as_view(), name='admin_compliance_form10be_download_direct'),
    path('api/v1/webhooks/razorpay/', RazorpayWebhookView.as_view(), name='razorpay_webhook'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

