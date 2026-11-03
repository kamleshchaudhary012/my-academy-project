from django.urls import path
from ngo.public_views import (
    NGOPublicListView,
    NGOPublicSlugDetailView,
    NGOPublicUUIDDetailView,
)

urlpatterns = [
    path('', NGOPublicListView.as_view(), name='ngo_public_list'),
    path('<slug:slug>/', NGOPublicSlugDetailView.as_view(), name='ngo_public_detail_slug'),
    path('id/<uuid:pk>/', NGOPublicUUIDDetailView.as_view(), name='ngo_public_detail_uuid'),
]

