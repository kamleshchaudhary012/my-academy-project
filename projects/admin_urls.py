from django.urls import path
from .admin_views import (
    AdminProjectQueueView,
    AdminProjectDetailView,
    AdminProjectHistoryView,
    AdminProjectVerifyView,
)

app_name = 'projects_admin'

urlpatterns = [
    path('', AdminProjectQueueView.as_view(), name='queue'),
    path('<uuid:id>/', AdminProjectDetailView.as_view(), name='detail'),
    path('<uuid:id>/verify/', AdminProjectVerifyView.as_view(), name='verify'),
    path('<uuid:id>/history/', AdminProjectHistoryView.as_view(), name='history'),
]
