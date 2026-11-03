"""
Phase 4.3.5 Automated Test Suite: Media, Profile Images, NGO Logos & Campaign Visuals
===================================================================================
Tests covering:
1. Image validation (JPG, PNG, WebP allowed; SVG, text, oversize rejected).
2. Donor avatar upload, serialization, replace, and deletion.
3. NGO logo upload and deletion for authorized NGO owner.
4. Campaign cover image upload and update.
"""

import io
from PIL import Image
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from users.image_validators import validate_image_file
from ngo.models import NGOProfile

User = get_user_model()


def create_test_image(format='PNG', size=(100, 100), color=(73, 109, 137)):
    """Generate in-memory image for upload testing."""
    file_obj = io.BytesIO()
    image = Image.new('RGB', size, color=color)
    image.save(file_obj, format=format)
    file_obj.seek(0)
    ext = format.lower()
    if ext == 'jpeg':
        ext = 'jpg'
    return SimpleUploadedFile(
        f'test_image.{ext}',
        file_obj.read(),
        content_type=f'image/{format.lower()}'
    )


class Phase435MediaValidationTests(TestCase):
    """Test unit validator validate_image_file."""

    def test_valid_png_and_jpg_and_webp(self):
        png = create_test_image(format='PNG')
        validate_image_file(png)  # Should not raise

        jpg = create_test_image(format='JPEG')
        validate_image_file(jpg)  # Should not raise

        webp = create_test_image(format='WEBP')
        validate_image_file(webp)  # Should not raise

    def test_reject_svg_and_text_and_invalid_extension(self):
        svg_file = SimpleUploadedFile(
            'bad.svg',
            b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>',
            content_type='image/svg+xml'
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(svg_file)
        self.assertIn('Unsupported image format', str(ctx.exception))

        txt_file = SimpleUploadedFile('bad.txt', b'hello world', content_type='text/plain')
        with self.assertRaises(ValidationError):
            validate_image_file(txt_file)

    def test_reject_fake_extension(self):
        # File has .jpg name but content is plaintext
        fake_jpg = SimpleUploadedFile('fake.jpg', b'Not a real image file content', content_type='image/jpeg')
        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(fake_jpg)
        self.assertIn('not a valid or readable image', str(ctx.exception))

    def test_reject_oversize_image(self):
        # > 5 MB file
        large_content = b'0' * (5 * 1024 * 1024 + 100)
        large_file = SimpleUploadedFile('large.jpg', large_content, content_type='image/jpeg')
        with self.assertRaises(ValidationError) as ctx:
            validate_image_file(large_file)
        self.assertIn('exceeds maximum limit of 5 MB', str(ctx.exception))


class Phase435DonorAvatarApiTests(TestCase):
    """Test Donor avatar upload and deletion endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='donor_avatar@test.com',
            password='TestPassword123!',
            full_name='Avatar Donor',
            role='DONOR',
            phone='+919876543210',
            is_active=True
        )
        self.client.force_authenticate(user=self.user)

    def test_donor_upload_avatar_success(self):
        img = create_test_image(format='PNG')
        response = self.client.post('/api/v1/auth/avatar/', {'profile_image': img}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('profile_image', response.data['user'])
        self.assertIsNotNone(response.data['user']['profile_image'])

        # Verify DB
        self.user.refresh_from_db()
        self.assertTrue(bool(self.user.profile_image))

    def test_donor_remove_avatar_success(self):
        # Upload first
        img = create_test_image(format='JPEG')
        self.client.post('/api/v1/auth/avatar/', {'profile_image': img}, format='multipart')
        self.user.refresh_from_db()
        self.assertTrue(bool(self.user.profile_image))

        # Remove
        del_res = self.client.delete('/api/v1/auth/avatar/')
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(bool(self.user.profile_image))

    def test_donor_upload_avatar_validation_error(self):
        svg_file = SimpleUploadedFile('bad.svg', b'<svg></svg>', content_type='image/svg+xml')
        res = self.client.post('/api/v1/auth/avatar/', {'profile_image': svg_file}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('profile_image', res.data)


class Phase435NgoLogoApiTests(TestCase):
    """Test NGO logo upload and deletion endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.ngo_user = User.objects.create_user(
            email='ngo_logo@test.com',
            password='TestPassword123!',
            full_name='NGO Owner',
            role='NGO',
            phone='+919876543211',
            is_active=True
        )
        self.profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Logo Test Foundation',
            category='EDUCATION',
            year_established=2020,
            status=NGOProfile.Status.APPROVED
        )
        self.client.force_authenticate(user=self.ngo_user)

    def test_ngo_upload_logo_success(self):
        img = create_test_image(format='PNG')
        response = self.client.post('/api/v1/ngo/profile/logo/', {'logo': img}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('logo', response.data['profile'])
        self.assertIsNotNone(response.data['profile']['logo'])

        self.profile.refresh_from_db()
        self.assertTrue(bool(self.profile.logo))

    def test_ngo_remove_logo_success(self):
        img = create_test_image(format='PNG')
        self.client.post('/api/v1/ngo/profile/logo/', {'logo': img}, format='multipart')
        self.profile.refresh_from_db()
        self.assertTrue(bool(self.profile.logo))

        del_res = self.client.delete('/api/v1/ngo/profile/logo/')
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertFalse(bool(self.profile.logo))


class Phase435CampaignCoverApiTests(TestCase):
    """Test campaign cover image upload and public exposure."""

    def setUp(self):
        from campaigns.models import Campaign
        self.Campaign = Campaign
        self.client = APIClient()
        self.ngo_user = User.objects.create_user(
            email='ngo_campaign@test.com',
            password='TestPassword123!',
            full_name='Campaign NGO Owner',
            role='NGO',
            phone='+919876543212',
            is_active=True
        )
        self.profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Campaign Test Trust',
            category='EDUCATION',
            year_established=2020,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )
        self.client.force_authenticate(user=self.ngo_user)

    def test_create_campaign_with_cover_image(self):
        img = create_test_image(format='PNG')
        payload = {
            'title': 'Test Campaign With Cover',
            'category': 'EDUCATION',
            'campaign_type': 'MONETARY',
            'short_description': 'A short description for test campaign appeal.',
            'description': 'A detailed description that is sufficiently long for verification.',
            'target_amount': 50000.0,
            'start_date': '2026-09-01',
            'end_date': '2026-10-01',
            'cover_image': img
        }
        res = self.client.post('/api/v1/ngo/campaigns/', payload, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn('cover_image', res.data)
        self.assertIsNotNone(res.data['cover_image'])

        campaign_id = res.data['id']
        campaign = self.Campaign.objects.get(id=campaign_id)
        self.assertTrue(bool(campaign.cover_image))

    def test_update_campaign_cover_image(self):
        campaign = self.Campaign.objects.create(
            ngo=self.profile,
            created_by=self.ngo_user,
            title='Pre-existing Campaign',
            category='EDUCATION',
            campaign_type='MONETARY',
            short_description='Short desc',
            description='Detailed description here with minimum 30 chars.',
            target_amount=10000.0,
            start_date='2026-09-01',
            end_date='2026-10-01',
            status=self.Campaign.Status.ACTIVE,
            is_active=True
        )
        img = create_test_image(format='JPEG')
        res = self.client.patch(f'/api/v1/ngo/campaigns/{campaign.id}/', {'cover_image': img}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('cover_image', res.data)
        self.assertIsNotNone(res.data['cover_image'])

        # Check public endpoint
        pub_client = APIClient()
        pub_res = pub_client.get(f'/api/v1/public/campaigns/{campaign.slug}/')
        self.assertEqual(pub_res.status_code, status.HTTP_200_OK)
        self.assertIn('cover_image', pub_res.data)
        self.assertIsNotNone(pub_res.data['cover_image'])
        self.assertIn('media', pub_res.data['cover_image'])

