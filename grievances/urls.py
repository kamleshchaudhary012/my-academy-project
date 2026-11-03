"""
Grievance App URL Configuration — Phase 5.1
===========================================
Defines URL routing for grievance tickets, responses, transitions, and assignment.
"""

from django.urls import path
from .views import (
    GrievanceResponseAttachmentView,
    GrievanceResponseListCreateView,
    GrievanceResponseUpdateView,
    GrievanceTicketAssignView,
    GrievanceTicketAttachmentView,
    GrievanceTicketDetailView,
    GrievanceTicketListCreateView,
    GrievanceTicketTransitionView,
)

app_name = 'grievances'

urlpatterns = [
    path('tickets/', GrievanceTicketListCreateView.as_view(), name='ticket_list_create'),
    path('tickets/<uuid:id>/', GrievanceTicketDetailView.as_view(), name='ticket_detail'),
    path('tickets/<uuid:id>/attachment/', GrievanceTicketAttachmentView.as_view(), name='ticket_attachment'),
    path('tickets/<uuid:id>/transition/', GrievanceTicketTransitionView.as_view(), name='ticket_transition'),
    path('tickets/<uuid:id>/assign/', GrievanceTicketAssignView.as_view(), name='ticket_assign'),
    path('tickets/<uuid:id>/responses/', GrievanceResponseListCreateView.as_view(), name='response_list_create'),
    path('responses/<uuid:id>/', GrievanceResponseUpdateView.as_view(), name='response_update'),
    path('responses/<uuid:id>/attachment/', GrievanceResponseAttachmentView.as_view(), name='response_attachment'),
]
