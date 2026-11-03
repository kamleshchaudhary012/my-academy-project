"""
DaanGives Admin NGO Verification URL Configuration — Phase 3.3.2-H
====================================================================
Routes for Admin NGO Verification & Review APIs:

  GET  /api/v1/admin/ngos/
  GET  /api/v1/admin/ngos/<uuid:pk>/
  POST /api/v1/admin/ngos/<uuid:pk>/start-review/
  POST /api/v1/admin/ngos/<uuid:pk>/approve/
  POST /api/v1/admin/ngos/<uuid:pk>/request-correction/
  POST /api/v1/admin/ngos/<uuid:pk>/reject/
  POST /api/v1/admin/ngos/<uuid:pk>/suspend/
  POST /api/v1/admin/ngos/<uuid:pk>/unsuspend/
  POST /api/v1/admin/ngos/<uuid:pk>/reopen/
  GET  /api/v1/admin/ngos/<uuid:pk>/history/
"""

from django.urls import path
from ngo.admin_views import (
    NGOAdminQueueView,
    NGOAdminDetailView,
    NGOAdminStartReviewView,
    NGOAdminApproveView,
    NGOAdminRequestCorrectionView,
    NGOAdminRejectView,
    NGOAdminSuspendView,
    NGOAdminUnsuspendView,
    NGOAdminReopenView,
    NGOAdminHistoryView,
    NGOAdminRecordManualGovCheckView,
)

urlpatterns = [
    path('', NGOAdminQueueView.as_view(), name='ngo_admin_queue'),
    path('<uuid:pk>/', NGOAdminDetailView.as_view(), name='ngo_admin_detail'),
    path('<uuid:pk>/start-review/', NGOAdminStartReviewView.as_view(), name='ngo_admin_start_review'),
    path('<uuid:pk>/approve/', NGOAdminApproveView.as_view(), name='ngo_admin_approve'),
    path('<uuid:pk>/request-correction/', NGOAdminRequestCorrectionView.as_view(), name='ngo_admin_request_correction'),
    path('<uuid:pk>/record-gov-check/', NGOAdminRecordManualGovCheckView.as_view(), name='ngo_admin_record_gov_check'),
    path('<uuid:pk>/reject/', NGOAdminRejectView.as_view(), name='ngo_admin_reject'),
    path('<uuid:pk>/suspend/', NGOAdminSuspendView.as_view(), name='ngo_admin_suspend'),
    path('<uuid:pk>/unsuspend/', NGOAdminUnsuspendView.as_view(), name='ngo_admin_unsuspend'),
    path('<uuid:pk>/reopen/', NGOAdminReopenView.as_view(), name='ngo_admin_reopen'),
    path('<uuid:pk>/history/', NGOAdminHistoryView.as_view(), name='ngo_admin_history'),
]
