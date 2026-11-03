from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from ngo.models import NGOProfile
from projects.models import (
    Project,
    ProjectDocument,
    ProjectMilestone,
    ProjectPhoto,
    ProjectCategory,
    ProjectStatus,
    ProjectDocumentType,
    MilestoneStatus,
)

User = get_user_model()


class ProjectModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='gramin_vikas@test.org',
            password='Password123!',
            full_name='Ram Charan',
            role='NGO'
        )
        self.ngo = NGOProfile.objects.create(
            user=self.user,
            legal_name='Gramin Vikas Sanstha Trust',
            display_name='Gramin Vikas Sanstha',
            category='RURAL',
            year_established=2015,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )

    def test_create_project_defaults(self):
        project = Project.objects.create(
            title='Clean Drinking Water Borewell and RO Plant',
            short_summary='Installation of 2 solar-powered RO water units for 450 families.',
            description='Detailed rural water purification project description.',
            posted_by=self.user,
            organization=self.ngo,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Koregaon Bhima',
            location_pincode='412207',
            beneficiaries_count=1800,
            beneficiaries_description='450 rural households and village primary school students',
            estimated_cost=Decimal('450000.00'),
            timeline_months=6,
        )

        self.assertEqual(project.status, ProjectStatus.DRAFT)
        self.assertEqual(str(project), f"Clean Drinking Water Borewell and RO Plant ({ProjectStatus.DRAFT})")
        self.assertEqual(project.organization.display_name, 'Gramin Vikas Sanstha')
        self.assertEqual(project.estimated_cost, Decimal('450000.00'))

    def test_project_category_choices_alignment(self):
        # Verify all 9 Schedule VII categories exist
        self.assertEqual(len(ProjectCategory.choices), 9)
        self.assertIn('POVERTY', ProjectCategory.values)
        self.assertIn('HEALTH', ProjectCategory.values)
        self.assertIn('EDUCATION', ProjectCategory.values)
        self.assertIn('GENDER', ProjectCategory.values)
        self.assertIn('ENVIRONMENT', ProjectCategory.values)
        self.assertIn('HERITAGE', ProjectCategory.values)
        self.assertIn('ARMED_FORCES', ProjectCategory.values)
        self.assertIn('RURAL', ProjectCategory.values)
        self.assertIn('DISASTER', ProjectCategory.values)

    def test_project_status_choices(self):
        self.assertEqual(len(ProjectStatus.choices), 10)
        self.assertIn('DRAFT', ProjectStatus.values)
        self.assertIn('SUBMITTED', ProjectStatus.values)
        self.assertIn('UNDER_REVIEW', ProjectStatus.values)
        self.assertIn('DOCS_PENDING', ProjectStatus.values)
        self.assertIn('VERIFIED', ProjectStatus.values)
        self.assertIn('REJECTED', ProjectStatus.values)
        self.assertIn('FUNDED', ProjectStatus.values)
        self.assertIn('IN_PROGRESS', ProjectStatus.values)
        self.assertIn('COMPLETED', ProjectStatus.values)
        self.assertIn('CLOSED', ProjectStatus.values)

    def test_project_document_creation(self):
        project = Project.objects.create(
            title='Primary Health Center Equipment Support',
            short_summary='Upgrading rural diagnostic center.',
            description='Health care machinery procurement.',
            posted_by=self.user,
            organization=self.ngo,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Satara',
            location_village='Wai',
            location_pincode='412803',
            estimated_cost=Decimal('800000.00'),
        )

        dummy_file = SimpleUploadedFile("panchayat_resolution.pdf", b"dummy resolution content", content_type="application/pdf")
        doc = ProjectDocument.objects.create(
            project=project,
            document_type=ProjectDocumentType.PANCHAYAT_RESOLUTION,
            file=dummy_file,
            notes='Signed by Gram Pradhan on Oct 10, 2026',
            uploaded_by=self.user,
        )

        self.assertEqual(doc.project, project)
        self.assertEqual(doc.document_type, ProjectDocumentType.PANCHAYAT_RESOLUTION)
        self.assertIn('Gram Panchayat Resolution', str(doc))

    def test_project_milestone_creation(self):
        project = Project.objects.create(
            title='Smart Classroom in Zilla Parishad School',
            short_summary='Setting up 3 digital smart classes.',
            description='Education enhancement.',
            posted_by=self.user,
            organization=self.ngo,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Nagpur',
            location_village='Umred',
            location_pincode='441203',
            estimated_cost=Decimal('300000.00'),
        )

        milestone1 = ProjectMilestone.objects.create(
            project=project,
            order=1,
            title='Hardware Procurement',
            description='Buying 3 smart boards and projectors',
            amount=Decimal('180000.00'),
            status=MilestoneStatus.PENDING,
        )

        milestone2 = ProjectMilestone.objects.create(
            project=project,
            order=2,
            title='Installation & Teacher Training',
            description='Installation and 2-week training',
            amount=Decimal('120000.00'),
            status=MilestoneStatus.PENDING,
        )

        self.assertEqual(project.milestones.count(), 2)
        self.assertEqual(milestone1.amount, Decimal('180000.00'))
        self.assertEqual(str(milestone1), "Milestone #1: Hardware Procurement (PENDING)")

    def test_project_photo_creation(self):
        project = Project.objects.create(
            title='Tree Plantation & Afforestation Project',
            short_summary='Planting 5000 native tree saplings.',
            description='Community environment project.',
            posted_by=self.user,
            organization=self.ngo,
            category=ProjectCategory.ENVIRONMENT,
            location_state='Maharashtra',
            location_district='Nashik',
            location_village='Trimbakeshwar',
            location_pincode='422212',
            estimated_cost=Decimal('250000.00'),
        )

        dummy_img = SimpleUploadedFile("village_land.jpg", b"image content", content_type="image/jpeg")
        photo = ProjectPhoto.objects.create(
            project=project,
            file=dummy_img,
            caption='Proposed plantation site at village border'
        )

        self.assertEqual(project.photos.count(), 1)
        self.assertEqual(photo.caption, 'Proposed plantation site at village border')
