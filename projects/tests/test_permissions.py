from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from decimal import Decimal

from ngo.models import NGOProfile
from projects.models import Project, ProjectStatus
from projects.permissions import (
    IsVillageUser,
    IsProjectOwner,
    CanEditProject,
    IsAdminUserOrReadOnly,
)

User = get_user_model()


class ProjectPermissionsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.village_user = User.objects.create_user(
            email='village_rep@test.org',
            password='Password123!',
            role='NGO'
        )
        self.other_user = User.objects.create_user(
            email='other_rep@test.org',
            password='Password123!',
            role='NGO'
        )
        self.company_user = User.objects.create_user(
            email='csr_rep@test.com',
            password='Password123!',
            role='COMPANY'
        )
        self.admin_user = User.objects.create_user(
            email='admin@test.org',
            password='Password123!',
            role='ADMIN',
            is_staff=True
        )

        self.ngo_profile = NGOProfile.objects.create(
            user=self.village_user,
            legal_name='Gram Sanstha Trust',
            display_name='Gram Sanstha',
            category='RURAL',
            year_established=2014,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )

        self.project = Project.objects.create(
            title='Test Project Permission',
            short_summary='Summary',
            description='Description',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category='RURAL',
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('100000.00'),
            status=ProjectStatus.DRAFT,
        )

    def test_is_village_user_permission(self):
        perm = IsVillageUser()

        # NGO user passes
        req = self.factory.get('/')
        req.user = self.village_user
        self.assertTrue(perm.has_permission(req, None))

        # COMPANY user fails
        req.user = self.company_user
        self.assertFalse(perm.has_permission(req, None))

        # Admin passes
        req.user = self.admin_user
        self.assertTrue(perm.has_permission(req, None))

    def test_is_project_owner_permission(self):
        perm = IsProjectOwner()

        # Owner passes
        req = self.factory.get('/')
        req.user = self.village_user
        self.assertTrue(perm.has_object_permission(req, None, self.project))

        # Other NGO fails
        req.user = self.other_user
        self.assertFalse(perm.has_object_permission(req, None, self.project))

        # Admin passes
        req.user = self.admin_user
        self.assertTrue(perm.has_object_permission(req, None, self.project))

    def test_can_edit_project_permission(self):
        perm = CanEditProject()

        # DRAFT status allows PATCH
        req = self.factory.patch('/')
        req.user = self.village_user
        self.assertTrue(perm.has_object_permission(req, None, self.project))

        # VERIFIED status rejects PATCH for village user
        self.project.status = ProjectStatus.VERIFIED
        self.project.save()
        self.assertFalse(perm.has_object_permission(req, None, self.project))

        # Admin can still edit
        req.user = self.admin_user
        self.assertTrue(perm.has_object_permission(req, None, self.project))
