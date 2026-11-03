import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Custom user manager where email is the unique identifier for authentication."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('The Email field must be set'))
        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', User.Role.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)


import os
from .image_validators import validate_image_file


from django.conf import settings


def donor_avatar_path(instance, filename):
    """Generates clean UUID-based media path for donor profile image."""
    ext = os.path.splitext(filename)[1].lower()
    return f'donor_avatars/{instance.id}/{uuid.uuid4().hex[:12]}{ext}'


class User(AbstractUser):
    """Custom User model using UUID primary key and email-based authentication."""

    class Role(models.TextChoices):
        DONOR = 'DONOR', 'Donor'
        NGO = 'NGO', 'NGO'
        ADMIN = 'ADMIN', 'Admin'
        COMPANY = 'COMPANY', 'Company'

    username = None
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_('email address'), unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    profile_image = models.ImageField(
        upload_to=donor_avatar_path,
        null=True,
        blank=True,
        validators=[validate_image_file],
        help_text=_('Donor profile photo / avatar image.'),
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DONOR)
    is_email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return f"{self.email} ({self.role})"


class DonorProfile(models.Model):
    """
    Donor compliance, physical address, and reusable tax profile.
    Holds mutable donor profile information while MonetaryDonation stores
    the immutable historical financial/tax snapshot for each transaction.
    """

    class EntityType(models.TextChoices):
        INDIVIDUAL   = 'INDIVIDUAL',   _('Individual')
        COMPANY      = 'COMPANY',      _('Company')
        TRUST        = 'TRUST',        _('Trust')
        LLP          = 'LLP',          _('Limited Liability Partnership (LLP)')
        PARTNERSHIP  = 'PARTNERSHIP',  _('Partnership Firm')
        HUF          = 'HUF',          _('Hindu Undivided Family (HUF)')
        OTHER        = 'OTHER',        _('Other Entity')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='donor_profile',
        help_text=_('Associated user account for this donor profile.'),
    )
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    pincode = models.CharField(max_length=10, blank=True, default='')
    country = models.CharField(max_length=100, default='India')
    pan_number = models.CharField(
        max_length=10,
        blank=True,
        default='',
        help_text=_('Reusable donor PAN for 80G tax receipt prefilling.'),
    )
    entity_type = models.CharField(
        max_length=30,
        choices=EntityType.choices,
        default=EntityType.INDIVIDUAL,
        help_text=_('Legal classification of donor entity for statutory 80G compliance.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Donor Profile')
        verbose_name_plural = _('Donor Profiles')
        ordering = ['-created_at']

    def __str__(self):
        return f"DonorProfile ({self.entity_type}) for {self.user.email}"


