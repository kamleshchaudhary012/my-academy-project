from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView,
    CustomTokenObtainPairView,
    UserProfileView,
    UserAvatarUploadView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
)

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='auth_register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='auth_login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth_refresh'),
    path('auth/me/', UserProfileView.as_view(), name='auth_me'),
    path('auth/avatar/', UserAvatarUploadView.as_view(), name='auth_avatar'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='auth_password_reset'),
    path('auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='auth_password_reset_confirm'),
]
