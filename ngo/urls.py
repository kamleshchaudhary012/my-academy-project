from django.urls import path
from ngo.views import (
    NGOProfileMeView,
    NGOProfileCreateView,
    NGOLogoUploadView,
    NGOAddressMeView,
    NGOLegalMeView,
    NGOBankMeView,
    NGOLeadershipListCreateView,
    NGOLeadershipDetailView,
    NGODocumentListCreateView,
    NGODocumentDetailView,
    NGODocumentDownloadView,
    NGOSubmitView,
    NGOHistoryView,
)

urlpatterns = [
    path('profile/me/', NGOProfileMeView.as_view(), name='ngo_profile_me'),
    path('profile/logo/', NGOLogoUploadView.as_view(), name='ngo_profile_logo'),
    path('profile/', NGOProfileCreateView.as_view(), name='ngo_profile_create'),
    path('address/me/', NGOAddressMeView.as_view(), name='ngo_address_me'),
    path('legal/me/', NGOLegalMeView.as_view(), name='ngo_legal_me'),
    path('bank/me/', NGOBankMeView.as_view(), name='ngo_bank_me'),
    path('leadership/', NGOLeadershipListCreateView.as_view(), name='ngo_leadership_list_create'),
    path('leadership/<uuid:pk>/', NGOLeadershipDetailView.as_view(), name='ngo_leadership_detail'),
    path('documents/', NGODocumentListCreateView.as_view(), name='ngo_document_list_create'),
    path('documents/<uuid:pk>/', NGODocumentDetailView.as_view(), name='ngo_document_detail'),
    path('documents/<uuid:pk>/download/', NGODocumentDownloadView.as_view(), name='ngo_document_download'),
    path('submit/', NGOSubmitView.as_view(), name='ngo_submit'),
    path('history/', NGOHistoryView.as_view(), name='ngo_history'),
]

