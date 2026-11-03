import os
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    UserSerializer,
    UserRegisterSerializer,
    CustomTokenObtainPairSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """API endpoint for User registration (Donor or NGO)."""

    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "message": "User registered successfully.",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomTokenObtainPairView(TokenObtainPairView):
    """API endpoint for obtaining JWT token pair with user profile info."""

    serializer_class = CustomTokenObtainPairSerializer


from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.core.exceptions import ValidationError as DjangoValidationError
from .image_validators import validate_image_file


class UserProfileView(generics.RetrieveUpdateAPIView):
    """API endpoint for retrieving and updating current user's profile."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return self.request.user


class UserAvatarUploadView(APIView):
    """API endpoint for uploading, updating, or deleting user avatar image."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('profile_image') or request.FILES.get('avatar') or request.FILES.get('image')
        if not file_obj:
            return Response(
                {'profile_image': ['No image file provided in request.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            validate_image_file(file_obj)
        except DjangoValidationError as e:
            return Response(
                {'profile_image': list(e.messages)},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        # Cleanup old image if existing and not shared
        if user.profile_image:
            try:
                user.profile_image.delete(save=False)
            except Exception:
                pass

        user.profile_image = file_obj
        user.save(update_fields=['profile_image', 'updated_at'])

        return Response(
            {
                'message': 'Profile photo updated successfully.',
                'user': UserSerializer(user, context={'request': request}).data,
            },
            status=status.HTTP_200_OK
        )

    def delete(self, request, *args, **kwargs):
        user = request.user
        if user.profile_image:
            try:
                user.profile_image.delete(save=False)
            except Exception:
                pass
            user.profile_image = None
            user.save(update_fields=['profile_image', 'updated_at'])

        return Response(
            {
                'message': 'Profile photo removed successfully.',
                'user': UserSerializer(user, context={'request': request}).data,
            },
            status=status.HTTP_200_OK
        )


class PasswordResetRequestView(APIView):
    """
    API endpoint for requesting a password reset email.
    Provides generic response for both existing and non-existing emails to prevent account enumeration.
    """

    permission_classes = [AllowAny]
    serializer_class = PasswordResetRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email__iexact=email, is_active=True)
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173').rstrip('/')
            reset_link = f"{frontend_url}/reset-password/{uid}/{token}/"

            subject = "Reset your DaanGives password"

            text_body = (
                f"Hello {user.full_name or 'User'},\n\n"
                f"A password reset request was received for your DaanGives account.\n\n"
                f"Click the link below to set a new password:\n{reset_link}\n\n"
                f"If you did not request a password reset, please ignore this email.\n\n"
                f"Regards,\nDaanGives Foundation"
            )

            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 12px;">
              <h2 style="color: #1e293b;">DaanGives Password Reset</h2>
              <p>Hello {user.full_name or 'User'},</p>
              <p>A password reset request was received for your DaanGives account.</p>
              <div style="margin: 24px 0;">
                <a href="{reset_link}" style="background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">Reset Password</a>
              </div>
              <p style="font-size: 12px; color: #64748b;">Or copy and paste this link into your browser:<br/><a href="{reset_link}">{reset_link}</a></p>
              <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;"/>
              <p style="font-size: 11px; color: #94a3b8;">If you did not request a password reset, please ignore this email.</p>
            </div>
            """

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'DaanGives <noreply@daangives.org>'),
                to=[user.email],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=True)

        except User.DoesNotExist:
            pass

        return Response(
            {
                "detail": "If an account exists for this email address, password reset instructions have been sent."
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """
    API endpoint for confirming password reset with UID, token, and new password.
    """

    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        try:
            pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "Invalid or expired reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Invalid or expired reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {"detail": "Your password has been updated. You can now sign in with your new password."},
            status=status.HTTP_200_OK,
        )
