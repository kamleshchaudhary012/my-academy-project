"""
CSR NGO URL Routing Configuration — Phase CSR-2.8.2
===================================================
Defines the NGO namespace routes under /api/v1/ngo/csr/.
All 16 endpoints correspond directly to CSR-2.0 Section 21 (#21 - #36).
"""

from django.urls import path

from csr.views.ngo_views import (
    # Dashboard (#21)
    NgoDashboardView,
    # Requirements (#22 - #28)
    NgoRequirementListCreateView,
    NgoRequirementDetailView,
    NgoRequirementSubmitView,
    NgoRequirementUploadDocumentView,
    # Support Requests (#29 - #32)
    NgoSupportRequestListView,
    NgoSupportRequestDetailView,
    NgoSupportRequestAcceptView,
    NgoSupportRequestRejectView,
    # Partnerships & Milestones (#33 - #36)
    NgoPartnershipListView,
    NgoPartnershipDetailView,
    NgoPartnershipUploadMouView,
    NgoMilestoneCreateView,
    NgoMilestoneSubmitEvidenceView,
)
from csr.views.financial_views import (
    CSRPartnershipFinancialsView,
    CSRPartnershipDisbursementListView,
    CSRDisbursementAcknowledgeView,
    CSRPartnershipExpenseListCreateView,
    CSRGrantChangeRequestListCreateView,
)


urlpatterns = [
    # Dashboard (#21)
    path('dashboard/', NgoDashboardView.as_view(), name='csr-ngo-dashboard'),

    # Requirements & Proposals (#22 - #28)
    path('requirements/', NgoRequirementListCreateView.as_view(), name='csr-ngo-requirements'),
    path('requirements/<uuid:id>/', NgoRequirementDetailView.as_view(), name='csr-ngo-requirement-detail'),
    path('requirements/<uuid:id>/submit/', NgoRequirementSubmitView.as_view(), name='csr-ngo-requirement-submit'),
    path('requirements/<uuid:id>/upload-document/', NgoRequirementUploadDocumentView.as_view(), name='csr-ngo-requirement-upload-document'),

    # Support Requests / Incoming Expressions of Interest (#29 - #32)
    path('support-requests/', NgoSupportRequestListView.as_view(), name='csr-ngo-support-requests'),
    path('support-requests/<uuid:id>/', NgoSupportRequestDetailView.as_view(), name='csr-ngo-support-request-detail'),
    path('support-requests/<uuid:id>/accept/', NgoSupportRequestAcceptView.as_view(), name='csr-ngo-support-request-accept'),
    path('support-requests/<uuid:id>/reject/', NgoSupportRequestRejectView.as_view(), name='csr-ngo-support-request-reject'),

    # Bilateral Partnerships & Milestones (#33 - #36)
    path('partnerships/', NgoPartnershipListView.as_view(), name='csr-ngo-partnerships'),
    path('partnerships/<uuid:id>/', NgoPartnershipDetailView.as_view(), name='csr-ngo-partnership-detail'),
    path('partnerships/<uuid:id>/upload-mou/', NgoPartnershipUploadMouView.as_view(), name='csr-ngo-partnership-upload-mou'),
    path('partnerships/<uuid:id>/milestones/', NgoMilestoneCreateView.as_view(), name='csr-ngo-milestone-create'),
    path('partnerships/<uuid:id>/milestones/<uuid:mid>/submit-evidence/', NgoMilestoneSubmitEvidenceView.as_view(), name='csr-ngo-milestone-submit-evidence'),

    # Financial Tracking & Transparency
    path('partnerships/<uuid:id>/financials/', CSRPartnershipFinancialsView.as_view(), name='csr-ngo-partnership-financials'),
    path('partnerships/<uuid:id>/disbursements/', CSRPartnershipDisbursementListView.as_view(), name='csr-ngo-partnership-disbursements'),
    path('disbursements/<uuid:id>/acknowledge/', CSRDisbursementAcknowledgeView.as_view(), name='csr-ngo-disbursement-acknowledge'),
    path('partnerships/<uuid:id>/expenses/', CSRPartnershipExpenseListCreateView.as_view(), name='csr-ngo-partnership-expenses'),
    path('partnerships/<uuid:id>/grant-changes/', CSRGrantChangeRequestListCreateView.as_view(), name='csr-ngo-partnership-grant-changes'),
]


