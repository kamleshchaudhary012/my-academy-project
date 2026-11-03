from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from ngo.models import NGOProfile
from projects.models import (
    Project,
    ProjectPhoto,
    ProjectCategory,
    ProjectStatus,
)

User = get_user_model()


class ProjectPhotoEvidenceTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Users
        self.ngo_user = User.objects.create_user(
            email='sarpanch@village.org',
            password='Password123!',
            full_name='Ramesh Patil',
            role='NGO'
        )
        self.other_ngo_user = User.objects.create_user(
            email='other_ngo@village.org',
            password='Password123!',
            full_name='Suresh More',
            role='NGO'
        )
        self.admin_user = User.objects.create_user(
            email='admin@daangives.org',
            password='Password123!',
            full_name='Admin User',
            role='ADMIN',
            is_staff=True
        )

        # NGO Profile
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Gramin Vikas Sanstha',
            display_name='Gramin Vikas',
            description='Rural water and solar projects',
            year_established=2015,
            status='APPROVED',
            is_active=True,
        )
        self.other_ngo_profile = NGOProfile.objects.create(
            user=self.other_ngo_user,
            legal_name='Other Sanstha',
            display_name='Other Sanstha',
            description='Education projects',
            year_established=2018,
            status='APPROVED',
            is_active=True,
        )

        # Projects in different statuses
        self.funded_project = Project.objects.create(
            posted_by=self.ngo_user,
            organization=self.ngo_profile,
            title='Solar Water Pump Installation',
            short_summary='Solar water pump installation in village',
            description='Detailed specifications for solar pump',
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Baramati',
            location_pincode='413102',
            beneficiaries_count=800,
            estimated_cost=500000.00,
            timeline_months=6,
            status=ProjectStatus.FUNDED
        )

        self.draft_project = Project.objects.create(
            posted_by=self.ngo_user,
            organization=self.ngo_profile,
            title='Draft Community Hall',
            short_summary='Draft proposal',
            description='Draft specifications',
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Baramati',
            location_pincode='413102',
            beneficiaries_count=200,
            estimated_cost=300000.00,
            timeline_months=4,
            status=ProjectStatus.DRAFT
        )

        # Dummy valid image (1x1 transparent PNG)
        self.small_image = SimpleUploadedFile(
            name='foundation_work.png',
            content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            content_type='image/png'
        )

    def test_upload_photo_requires_authentication(self):
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.post(url, {'file': self.small_image, 'caption': 'Test'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_photo_idor_prevention(self):
        """Another NGO cannot upload evidence photos to someone else's project."""
        self.client.force_authenticate(user=self.other_ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.post(url, {'file': self.small_image, 'caption': 'Hacked'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.funded_project.photos.count(), 0)

    def test_upload_photo_rejected_on_draft_project(self):
        """Milestone evidence photos cannot be uploaded to DRAFT projects."""
        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.draft_project.id}/photos/'
        response = self.client.post(url, {'file': self.small_image, 'caption': 'Draft work'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('eligible', response.data['detail'].lower())

    def test_upload_photo_success_on_funded_project(self):
        """Project owner can successfully upload milestone evidence photo on FUNDED project."""
        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.post(url, {
            'file': self.small_image,
            'caption': 'Excavation completed for solar pump foundation'
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('id', response.data)
        self.assertEqual(response.data['caption'], 'Excavation completed for solar pump foundation')
        self.assertEqual(self.funded_project.photos.count(), 1)

    def test_upload_photo_success_on_in_progress_project(self):
        """Project owner can upload milestone evidence photo on IN_PROGRESS project."""
        self.funded_project.status = ProjectStatus.IN_PROGRESS
        self.funded_project.save(update_fields=['status'])

        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.post(url, {
            'file': self.small_image,
            'caption': 'In-progress pump installation'
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.funded_project.photos.count(), 1)

    def test_upload_photo_rejects_invalid_file_format(self):
        """Non-image files like text files or scripts are rejected."""
        text_file = SimpleUploadedFile(name='notes.txt', content=b'Some text content', content_type='text/plain')
        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.post(url, {'file': text_file, 'caption': 'Invalid file'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('format', response.data['detail'].lower())

    def test_upload_photo_rejects_oversized_file(self):
        """Files exceeding 5MB are rejected."""
        oversized_data = b'x' * (5 * 1024 * 1024 + 100)
        oversized_file = SimpleUploadedFile(name='large.jpg', content=oversized_data, content_type='image/jpeg')
        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.post(url, {'file': oversized_file, 'caption': 'Too big'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('5mb', response.data['detail'].lower())

    def test_delete_photo_by_owner(self):
        """Owner can delete uploaded photo."""
        photo = ProjectPhoto.objects.create(
            project=self.funded_project,
            file=self.small_image,
            caption='To be deleted'
        )
        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/{photo.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.funded_project.photos.count(), 0)

    def test_delete_photo_by_unauthorized_user(self):
        """Another NGO cannot delete photo belonging to another project."""
        photo = ProjectPhoto.objects.create(
            project=self.funded_project,
            file=self.small_image,
            caption='Protected photo'
        )
        self.client.force_authenticate(user=self.other_ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/{photo.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.funded_project.photos.count(), 1)

    def test_list_photos(self):
        """GET /projects/<id>/photos/ returns list of photos."""
        ProjectPhoto.objects.create(
            project=self.funded_project,
            file=self.small_image,
            caption='Photo 1'
        )
        self.client.force_authenticate(user=self.ngo_user)
        url = f'/api/v1/projects/{self.funded_project.id}/photos/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['caption'], 'Photo 1')
