import re
from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import DonorProfile

User = get_user_model()

PAN_REGEX = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$')
PINCODE_REGEX = re.compile(r'^\d{6}$')


class DonorProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for Donor compliance and address profile.
    Enforces PAN format validation, 6-digit pincode validation, and strict PAN masking.
    Raw PAN is write-only and NEVER returned in GET representations.
    """
    pan_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10,
        write_only=True,
        help_text='10-character PAN number for 80G tax deductions.'
    )
    pan_number_masked = serializers.SerializerMethodField(read_only=True)
    has_pan = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DonorProfile
        fields = (
            'address_line1',
            'address_line2',
            'city',
            'state',
            'pincode',
            'country',
            'pan_number',
            'pan_number_masked',
            'has_pan',
            'entity_type',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('created_at', 'updated_at')

    def get_pan_number_masked(self, obj):
        if obj.pan_number and len(obj.pan_number) == 10:
            return f"******{obj.pan_number[-4:]}"
        return ""

    def get_has_pan(self, obj):
        return bool(obj.pan_number and len(obj.pan_number) == 10)

    def validate_pan_number(self, value):
        if not value:
            return ""
        cleaned = value.strip().upper()
        if not PAN_REGEX.match(cleaned):
            raise serializers.ValidationError("Enter a valid 10-character PAN format (e.g. ABCDE1234F).")
        return cleaned

    def validate_pincode(self, value):
        if not value:
            return ""
        cleaned = value.strip()
        if not PINCODE_REGEX.match(cleaned):
            raise serializers.ValidationError("Pincode must be exactly 6 digits.")
        return cleaned


class UserSerializer(serializers.ModelSerializer):
    donor_profile = DonorProfileSerializer(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ('id', 'email', 'full_name', 'phone', 'profile_image', 'role', 'is_email_verified', 'donor_profile', 'created_at')
        read_only_fields = ('id', 'role', 'is_email_verified', 'created_at')

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.role == User.Role.DONOR:
            profile = getattr(instance, 'donor_profile', None)
            if profile:
                ret['donor_profile'] = DonorProfileSerializer(profile, context=self.context).data
            else:
                ret['donor_profile'] = {
                    'address_line1': '',
                    'address_line2': '',
                    'city': '',
                    'state': '',
                    'pincode': '',
                    'country': 'India',
                    'pan_number_masked': '',
                    'has_pan': False,
                    'entity_type': DonorProfile.EntityType.INDIVIDUAL,
                    'created_at': None,
                    'updated_at': None,
                }
        else:
            ret['donor_profile'] = None
        return ret

    def update(self, instance, validated_data):
        donor_profile_data = validated_data.pop('donor_profile', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if instance.role == User.Role.DONOR and donor_profile_data is not None:
            donor_profile, _ = DonorProfile.objects.get_or_create(user=instance)
            for attr, value in donor_profile_data.items():
                if attr == 'pan_number' and not value and not ('pan_number' in self.initial_data.get('donor_profile', {})):
                    continue
                setattr(donor_profile, attr, value)
            donor_profile.save()

        return instance


class UserRegisterSerializer(serializers.ModelSerializer):
    """Serializer handling User registration with password validation and role restrictions."""

    password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('email', 'full_name', 'phone', 'password', 'password_confirm', 'role')

    def validate_email(self, value):
        normalized_email = value.lower().strip()
        if User.objects.filter(email__iexact=normalized_email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized_email

    def validate_role(self, value):
        if value == User.Role.ADMIN:
            raise serializers.ValidationError("Self-registration as ADMIN is strictly prohibited.")
        if value not in [User.Role.DONOR, User.Role.NGO, User.Role.COMPANY]:
            raise serializers.ValidationError("Invalid role selected.")
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, **validated_data)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom SimpleJWT token serializer returning user metadata alongside JWT tokens."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer validating email format for password reset request."""
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer validating password reset confirmation payload."""
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    new_password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        if attrs.get('new_password') != attrs.get('new_password_confirm'):
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        return attrs
