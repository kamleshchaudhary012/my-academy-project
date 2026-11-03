"""
CSR URL Routing Configuration — Phase CSR-2.8.1
================================================
Defines the COMPANY namespace routes under /api/v1/csr/.
All 20 endpoints correspond directly to CSR-2.0 Section 21 (#1 - #20).
"""

from django.urls import path

from csr.views.company_views import (
    # Profile & Documents
    CompanyProfileMeView,
    CompanyVerificationDocumentView,
    CompanyVerificationSubmitView,
    # Preferences
    CompanyPreferencesMeView,
    # Dashboard
    CompanyDashboardView,
    # Requirements & Recommendations
    CompanyRequirementListView,
    CompanyRequirementRecommendedView,
    CompanyRequirementDetailView,
    # Support Requests
    CompanySupportRequestListCreateView,
    CompanySupportRequestDetailView,
    CompanySupportRequestWithdrawView,
    # Partnerships & Milestones
    CompanyPartnershipListView,
    CompanyPartnershipDetailView,
    CompanyPartnershipUploadMouView,
    CompanyPartnershipReportDisbursementView,
    CompanyPartnershipMilestoneListView,
    CompanyMilestoneReviewView,
)
from csr.views.financial_views import (
    CSRPartnershipFinancialsView,
    CSRPartnershipDisbursementListView,
    CSRDisbursementReviewView,
    CSRPartnershipExpenseListCreateView,
    CSRExpenseReviewView,
    CSRGrantChangeRequestListCreateView,
    CSRGrantChangeCompanyReviewView,
)


urlpatterns = [
    # Profile & Verification Document (#1 - #4)
    path('profile/me/', CompanyProfileMeView.as_view(), name='csr-company-profile-me'),
    path('profile/verification-document/', CompanyVerificationDocumentView.as_view(), name='csr-company-verification-doc'),
    path('profile/submit/', CompanyVerificationSubmitView.as_view(), name='csr-company-profile-submit'),

    # Preferences (#5 - #6)
    path('preferences/me/', CompanyPreferencesMeView.as_view(), name='csr-company-preferences-me'),

    # Dashboard (#7)
    path('dashboard/', CompanyDashboardView.as_view(), name='csr-company-dashboard'),

    # Requirements & Marketplace (#8 - #10)
    path('requirements/', CompanyRequirementListView.as_view(), name='csr-company-requirements'),
    path('requirements/recommended/', CompanyRequirementRecommendedView.as_view(), name='csr-company-requirements-recommended'),
    path('requirements/<uuid:id>/', CompanyRequirementDetailView.as_view(), name='csr-company-requirement-detail'),

    # Support Requests / Grant EOIs (#11 - #14)
    path('support-requests/', CompanySupportRequestListCreateView.as_view(), name='csr-company-support-requests'),
    path('support-requests/<uuid:id>/', CompanySupportRequestDetailView.as_view(), name='csr-company-support-request-detail'),
    path('support-requests/<uuid:id>/withdraw/', CompanySupportRequestWithdrawView.as_view(), name='csr-company-support-request-withdraw'),

    # Partnerships & Milestones (#15 - #20)
    path('partnerships/', CompanyPartnershipListView.as_view(), name='csr-company-partnerships'),
    path('partnerships/<uuid:id>/', CompanyPartnershipDetailView.as_view(), name='csr-company-partnership-detail'),
    path('partnerships/<uuid:id>/upload-mou/', CompanyPartnershipUploadMouView.as_view(), name='csr-company-partnership-upload-mou'),
    path('partnerships/<uuid:id>/report-disbursement/', CompanyPartnershipReportDisbursementView.as_view(), name='csr-company-partnership-report-disbursement'),
    path('partnerships/<uuid:id>/milestones/', CompanyPartnershipMilestoneListView.as_view(), name='csr-company-partnership-milestones'),
    path('partnerships/<uuid:id>/milestones/<uuid:mid>/review/', CompanyMilestoneReviewView.as_view(), name='csr-company-milestone-review'),

    # Financial Tracking & Transparency
    path('partnerships/<uuid:id>/financials/', CSRPartnershipFinancialsView.as_view(), name='csr-company-partnership-financials'),
    path('partnerships/<uuid:id>/disbursements/', CSRPartnershipDisbursementListView.as_view(), name='csr-company-partnership-disbursements'),
    path('disbursements/<uuid:id>/review/', CSRDisbursementReviewView.as_view(), name='csr-company-disbursement-review'),
    path('partnerships/<uuid:id>/expenses/', CSRPartnershipExpenseListCreateView.as_view(), name='csr-company-partnership-expenses'),
    path('expenses/<uuid:id>/review/', CSRExpenseReviewView.as_view(), name='csr-company-expense-review'),
    path('partnerships/<uuid:id>/grant-changes/', CSRGrantChangeRequestListCreateView.as_view(), name='csr-company-partnership-grant-changes'),
    path('grant-changes/<uuid:id>/review/', CSRGrantChangeCompanyReviewView.as_view(), name='csr-company-grant-change-review'),
]


