"""
CSR Admin URL Routing Configuration — Phase CSR-2.8.3
=====================================================
Defines the ADMIN namespace routes under /api/v1/admin/csr/.
All 13 endpoints correspond directly to CSR-2.0 Section 21 (#37 - #49).
"""

from django.urls import path

from csr.views.admin_views import (
    # Company Moderation (#37 - #41)
    AdminCompanyListView,
    AdminCompanyDetailView,
    AdminCompanyApproveView,
    AdminCompanyRejectView,
    AdminCompanySuspendView,
    AdminCompanyRequestCorrectionsView,
    AdminCompanyRecordManualGovCheckView,
    # Requirement Moderation (#42 - #46)
    AdminRequirementListView,
    AdminRequirementDetailView,
    AdminRequirementApproveView,
    AdminRequirementRejectView,
    AdminRequirementSuspendView,
    # Platform Monitoring & Analytics (#47 - #49)
    AdminPartnershipListView,
    AdminAuditHistoryListView,
    AdminAnalyticsView,
)
from csr.views.financial_views import (
    CSRPartnershipFinancialsView,
    CSRPartnershipDisbursementListView,
    CSRDisbursementReviewView,
    CSRPartnershipExpenseListCreateView,
    CSRExpenseReviewView,
    CSRGrantChangeRequestListCreateView,
    CSRGrantChangeAdminReviewView,
)


urlpatterns = [
    # Corporate Verification Queue (#37 - #41)
    path('companies/', AdminCompanyListView.as_view(), name='csr-admin-companies-list'),
    path('companies/<uuid:id>/', AdminCompanyDetailView.as_view(), name='csr-admin-company-detail'),
    path('companies/<uuid:id>/approve/', AdminCompanyApproveView.as_view(), name='csr-admin-company-approve'),
    path('companies/<uuid:id>/reject/', AdminCompanyRejectView.as_view(), name='csr-admin-company-reject'),
    path('companies/<uuid:id>/suspend/', AdminCompanySuspendView.as_view(), name='csr-admin-company-suspend'),
    path('companies/<uuid:id>/request-correction/', AdminCompanyRequestCorrectionsView.as_view(), name='csr-admin-company-request-correction'),
    path('companies/<uuid:id>/record-gov-check/', AdminCompanyRecordManualGovCheckView.as_view(), name='csr-admin-company-record-gov-check'),

    # Requirement Proposal Moderation Queue (#42 - #46)
    path('requirements/', AdminRequirementListView.as_view(), name='csr-admin-requirements-list'),
    path('requirements/<uuid:id>/', AdminRequirementDetailView.as_view(), name='csr-admin-requirement-detail'),
    path('requirements/<uuid:id>/approve/', AdminRequirementApproveView.as_view(), name='csr-admin-requirement-approve'),
    path('requirements/<uuid:id>/reject/', AdminRequirementRejectView.as_view(), name='csr-admin-requirement-reject'),
    path('requirements/<uuid:id>/suspend/', AdminRequirementSuspendView.as_view(), name='csr-admin-requirement-suspend'),

    # Platform Monitoring, Audit Ledger & Analytics (#47 - #49)
    path('partnerships/', AdminPartnershipListView.as_view(), name='csr-admin-partnerships-list'),
    path('audit-history/', AdminAuditHistoryListView.as_view(), name='csr-admin-audit-history'),
    path('analytics/', AdminAnalyticsView.as_view(), name='csr-admin-analytics'),

    # CSR Financial Oversight & Reconciliation
    path('partnerships/<uuid:id>/financials/', CSRPartnershipFinancialsView.as_view(), name='csr-admin-partnership-financials'),
    path('partnerships/<uuid:id>/disbursements/', CSRPartnershipDisbursementListView.as_view(), name='csr-admin-partnership-disbursements'),
    path('disbursements/<uuid:id>/review/', CSRDisbursementReviewView.as_view(), name='csr-admin-disbursement-review'),
    path('partnerships/<uuid:id>/expenses/', CSRPartnershipExpenseListCreateView.as_view(), name='csr-admin-partnership-expenses'),
    path('expenses/<uuid:id>/review/', CSRExpenseReviewView.as_view(), name='csr-admin-expense-review'),
    path('partnerships/<uuid:id>/grant-changes/', CSRGrantChangeRequestListCreateView.as_view(), name='csr-admin-partnership-grant-changes'),
    path('grant-changes/<uuid:id>/review/', CSRGrantChangeAdminReviewView.as_view(), name='csr-admin-grant-change-review'),
]

