from django.urls import path, include
from .views import (
    ProjectCreateView,
    MyProjectListView,
    ProjectDetailView,
    ProjectSubmitView,
    ProjectWithdrawView,
    ProjectDocumentUploadView,
    ProjectDocumentDeleteView,
    ProjectMilestoneCreateView,
    ProjectMilestoneDeleteView,
    ProjectPhotoUploadView,
    ProjectPhotoDeleteView,
    PublicProjectListView,
    PublicProjectDetailView,
    AdminProjectVerifyView,
)

app_name = 'projects'

urlpatterns = [
    # Village endpoints
    path('', ProjectCreateView.as_view(), name='project_create'),
    path('me/', MyProjectListView.as_view(), name='my_projects'),
    path('public/', PublicProjectListView.as_view(), name='public_project_list'),
    path('public/<uuid:id>/', PublicProjectDetailView.as_view(), name='public_project_detail'),
    path('<uuid:id>/', ProjectDetailView.as_view(), name='project_detail'),
    path('<uuid:id>/submit/', ProjectSubmitView.as_view(), name='project_submit'),
    path('<uuid:id>/withdraw/', ProjectWithdrawView.as_view(), name='project_withdraw'),
    path('<uuid:id>/documents/', ProjectDocumentUploadView.as_view(), name='project_document_upload'),
    path('<uuid:id>/documents/<uuid:doc_id>/', ProjectDocumentDeleteView.as_view(), name='project_document_delete'),
    path('<uuid:id>/milestones/', ProjectMilestoneCreateView.as_view(), name='project_milestone_create'),
    path('<uuid:id>/milestones/<uuid:mid>/', ProjectMilestoneDeleteView.as_view(), name='project_milestone_delete'),
    path('<uuid:id>/photos/', ProjectPhotoUploadView.as_view(), name='project_photo_upload'),
    path('<uuid:id>/photos/<uuid:photo_id>/', ProjectPhotoDeleteView.as_view(), name='project_photo_delete'),
    
    # Admin verification endpoints
    path('<uuid:id>/verify/', AdminProjectVerifyView.as_view(), name='admin_project_verify'),
    path('admin/', include('projects.admin_urls')),
]

