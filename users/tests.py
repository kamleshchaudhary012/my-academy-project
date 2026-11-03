import uuid
from django.test import TestCase
from django.urls import reverse
from django.db.utils import IntegrityError
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from users.permissions import IsDonorPermission, IsNgoPermission, IsAdminPermission

User = get_user_model()


class UserModelTests(TestCase):
    """Test suite for custom User model architecture and constraints."""

    def test_create_user_successful(self):
        """Verify normal donor user creation with UUID primary key and password hashing."""
        user = User.objects.create_user(
            email="donor@example.com",
            password="SecurePassword123!",
            full_name="Test Donor",
            phone="+91 98765 43210",
            role=User.Role.DONOR,
        )
        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.email, "donor@example.com")
        self.assertTrue(user.check_password("SecurePassword123!"))
        self.assertFalse(user.check_password("WrongPassword"))
        self.assertNotEqual(user.password, "SecurePassword123!")  # Password hashed
        self.assertEqual(user.role, User.Role.DONOR)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser_successful(self):
        """Verify admin user creation with is_staff, is_superuser, and ADMIN role."""
        admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="AdminPassword123!",
            full_name="System Admin",
        )
        self.assertEqual(admin_user.role, User.Role.ADMIN)
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)

    def test_email_uniqueness(self):
        """Verify duplicate email rejection at database constraint level."""
        User.objects.create_user(
            email="unique@example.com",
            password="Password123!",
        )
        with self.assertRaises(IntegrityError):
            User.objects.create(
                email="unique@example.com",
                password="Password456!",
            )


class AuthAPITests(APITestCase):
    """Test suite for DRF Registration, JWT Login, Refresh, and Role Permissions."""

    def setUp(self):
        self.register_url = reverse('auth_register')
        self.login_url = reverse('auth_login')
        self.refresh_url = reverse('auth_refresh')
        self.me_url = reverse('auth_me')

        self.donor_user = User.objects.create_user(
            email="existingdonor@example.com",
            password="Password123!",
            full_name="Existing Donor",
            role=User.Role.DONOR,
        )
        self.ngo_user = User.objects.create_user(
            email="existingngo@example.com",
            password="Password123!",
            full_name="Existing NGO",
            role=User.Role.NGO,
        )
        self.admin_user = User.objects.create_superuser(
            email="existingadmin@example.com",
            password="Password123!",
            full_name="Existing Admin",
        )

    def test_registration_valid_donor(self):
        """Verify successful donor registration."""
        payload = {
            "email": "newdonor@example.com",
            "full_name": "New Donor",
            "phone": "+91 99999 88888",
            "password": "Password123!",
            "password_confirm": "Password123!",
            "role": "DONOR",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("user", response.data)
        self.assertNotIn("password", response.data["user"])
        self.assertEqual(response.data["user"]["email"], "newdonor@example.com")

    def test_registration_duplicate_email(self):
        """Verify registration fails for existing email."""
        payload = {
            "email": "existingdonor@example.com",
            "full_name": "Duplicate User",
            "password": "Password123!",
            "password_confirm": "Password123!",
            "role": "DONOR",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_admin_role_escalation_blocked(self):
        """Verify self-registration as ADMIN is blocked."""
        payload = {
            "email": "hacker@example.com",
            "full_name": "Fake Admin",
            "password": "Password123!",
            "password_confirm": "Password123!",
            "role": "ADMIN",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", response.data)

    def test_registration_password_mismatch(self):
        """Verify registration fails when password and confirmation do not match."""
        payload = {
            "email": "mismatch@example.com",
            "full_name": "Mismatch User",
            "password": "Password123!",
            "password_confirm": "DifferentPassword123!",
            "role": "DONOR",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_valid_credentials(self):
        """Verify JWT token generation on valid login credentials."""
        payload = {
            "email": "existingdonor@example.com",
            "password": "Password123!",
        }
        response = self.client.post(self.login_url, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["email"], "existingdonor@example.com")

    def test_login_invalid_password(self):
        """Verify login fails with wrong password."""
        payload = {
            "email": "existingdonor@example.com",
            "password": "WrongPassword123!",
        }
        response = self.client.post(self.login_url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_jwt_token_refresh(self):
        """Verify access token refresh flow."""
        login_res = self.client.post(self.login_url, {
            "email": "existingdonor@example.com",
            "password": "Password123!",
        })
        refresh_token = login_res.data["refresh"]

        refresh_res = self.client.post(self.refresh_url, {"refresh": refresh_token})
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_res.data)

    def test_profile_authenticated_access(self):
        """Verify authenticated request to /auth/me/ endpoint."""
        login_res = self.client.post(self.login_url, {
            "email": "existingdonor@example.com",
            "password": "Password123!",
        })
        access_token = login_res.data["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "existingdonor@example.com")

    def test_profile_unauthenticated_access_denied(self):
        """Verify 401 Unauthorized when accessing /auth/me/ without token."""
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_role_permission_classes(self):
        """Verify custom permission classes for Donor, NGO, and Admin roles."""
        donor_perm = IsDonorPermission()
        ngo_perm = IsNgoPermission()
        admin_perm = IsAdminPermission()

        class MockRequest:
            def __init__(self, user):
                self.user = user

        donor_req = MockRequest(self.donor_user)
        ngo_req = MockRequest(self.ngo_user)
        admin_req = MockRequest(self.admin_user)

        self.assertTrue(donor_perm.has_permission(donor_req, None))
        self.assertFalse(donor_perm.has_permission(ngo_req, None))

        self.assertTrue(ngo_perm.has_permission(ngo_req, None))
        self.assertFalse(ngo_perm.has_permission(donor_req, None))

        self.assertTrue(admin_perm.has_permission(admin_req, None))
        self.assertFalse(admin_perm.has_permission(donor_req, None))


class PasswordResetAPITests(APITestCase):
    """Test suite for Password Reset Request and Password Reset Confirmation APIs."""

    def setUp(self):
        self.request_url = reverse('auth_password_reset')
        self.confirm_url = reverse('auth_password_reset_confirm')
        self.login_url = reverse('auth_login')
        self.user = User.objects.create_user(
            email="resetuser@example.com",
            password="OldPassword123!",
            full_name="Reset User",
            role=User.Role.DONOR,
        )

    def test_request_reset_valid_email(self):
        """Verify password reset request with registered email returns generic 200 and sends email."""
        from django.core import mail
        response = self.client.post(self.request_url, {"email": "resetuser@example.com"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("detail", response.data)
        self.assertNotIn("token", response.data)  # Token must NOT be returned in API
        self.assertNotIn("uid", response.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reset your DaanGives password", mail.outbox[0].subject)

    def test_request_reset_unknown_email_account_enumeration_protection(self):
        """Verify password reset with unknown email returns identical generic 200 response to prevent enumeration."""
        from django.core import mail
        response = self.client.post(self.request_url, {"email": "nonexistent@example.com"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "If an account exists for this email address, password reset instructions have been sent."
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_request_reset_invalid_email_format(self):
        """Verify HTTP 400 when email format is invalid."""
        response = self.client.post(self.request_url, {"email": "not-an-email"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_reset_successful(self):
        """Verify successful password reset using generated token and UID."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        confirm_res = self.client.post(self.confirm_url, {
            "uid": uid,
            "token": token,
            "new_password": "NewPassword123!",
            "new_password_confirm": "NewPassword123!",
        })
        self.assertEqual(confirm_res.status_code, status.HTTP_200_OK)
        self.assertIn("updated", confirm_res.data["detail"].lower())

        # Verify old password fails
        old_login = self.client.post(self.login_url, {
            "email": "resetuser@example.com",
            "password": "OldPassword123!",
        })
        self.assertEqual(old_login.status_code, status.HTTP_401_UNAUTHORIZED)

        # Verify new password succeeds
        new_login = self.client.post(self.login_url, {
            "email": "resetuser@example.com",
            "password": "NewPassword123!",
        })
        self.assertEqual(new_login.status_code, status.HTTP_200_OK)

    def test_confirm_reset_invalid_token(self):
        """Verify HTTP 400 when token is invalid or expired."""
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.post(self.confirm_url, {
            "uid": uid,
            "token": "invalid-token-123",
            "new_password": "NewPassword123!",
            "new_password_confirm": "NewPassword123!",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid or expired reset link.")

    def test_confirm_reset_reused_token_fails(self):
        """Verify token cannot be reused after successful password reset."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        # First use succeeds
        self.client.post(self.confirm_url, {
            "uid": uid,
            "token": token,
            "new_password": "FirstNewPassword123!",
            "new_password_confirm": "FirstNewPassword123!",
        })

        # Second use fails
        reuse_res = self.client.post(self.confirm_url, {
            "uid": uid,
            "token": token,
            "new_password": "SecondNewPassword123!",
            "new_password_confirm": "SecondNewPassword123!",
        })
        self.assertEqual(reuse_res.status_code, status.HTTP_400_BAD_REQUEST)

