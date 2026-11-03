from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model

from ngo.models import NGOProfile
from projects.models import (
    Project,
    ProjectDocument,
    ProjectMilestone,
    ProjectCategory,
    ProjectStatus,
    ProjectDocumentType,
)
from projects.serializers import (
    ProjectListSerializer,
    ProjectDetailSerializer,
    ProjectCreateUpdateSerializer,
    ProjectDocumentSerializer,
    ProjectMilestoneSerializer,
    ProjectVerificationSerializer,
)

User = get_user_model()


class ProjectSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='village@test.org',
            password='Password123!',
            full_name='Ramesh Kadam',
            role='NGO'
        )
        self.ngo = NGOProfile.objects.create(
            user=self.user,
            legal_name='Ramesh Seva Sanstha Trust',
            display_name='Ramesh Seva Sanstha',
            category='RURAL',
            year_established=2012,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )

    def test_project_create_update_serializer_valid(self):
        payload = {
            "title": "Clean Water RO Plant in Village Center",
            "short_summary": "5000L per day solar RO unit.",
            "description": "Safe drinking water for rural school and community.",
            "category": "RURAL",
            "location_state": "Maharashtra",
            "location_district": "Pune",
            "location_village": "Manchar",
            "location_pincode": "410503",
            "beneficiaries_count": 850,
            "beneficiaries_description": "Villagers and students",
            "estimated_cost": "350000.00",
            "timeline_months": 6,
            "milestones": [
                {"title": "Civil Construction", "amount": "150000.00", "order": 1},
                {"title": "RO Machinery Installation", "amount": "200000.00", "order": 2}
            ]
        }
        serializer = ProjectCreateUpdateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_project_create_update_serializer_invalid_budget(self):
        payload = {
            "title": "Clean Water RO Plant",
            "short_summary": "Short",
            "description": "Description",
            "category": "RURAL",
            "location_state": "Maharashtra",
            "location_district": "Pune",
            "location_village": "Manchar",
            "location_pincode": "410503",
            "estimated_cost": "-500.00",
            "timeline_months": 6
        }
        serializer = ProjectCreateUpdateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('estimated_cost', serializer.errors)

    def test_project_create_update_serializer_invalid_timeline(self):
        payload = {
            "title": "Clean Water RO Plant",
            "short_summary": "Short",
            "description": "Description",
            "category": "RURAL",
            "location_state": "Maharashtra",
            "location_district": "Pune",
            "location_village": "Manchar",
            "location_pincode": "410503",
            "estimated_cost": "50000.00",
            "timeline_months": 0
        }
        serializer = ProjectCreateUpdateSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn('timeline_months', serializer.errors)

    def test_project_verification_serializer_choices(self):
        valid = ProjectVerificationSerializer(data={'action': 'APPROVE', 'notes': 'Looks good'})
        self.assertTrue(valid.is_valid())

        invalid = ProjectVerificationSerializer(data={'action': 'INVALID_ACTION'})
        self.assertFalse(invalid.is_valid())
        self.assertIn('action', invalid.errors)

    def test_project_list_serializer_output(self):
        project = Project.objects.create(
            title='Rural Anganwadi Renovation',
            short_summary='Renovating 2 Anganwadi centers.',
            description='Child welfare and nutrition centers.',
            posted_by=self.user,
            organization=self.ngo,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Manchar',
            location_pincode='410503',
            beneficiaries_count=120,
            estimated_cost=Decimal('280000.00'),
            timeline_months=3,
        )
        serializer = ProjectListSerializer(project)
        self.assertEqual(serializer.data['title'], 'Rural Anganwadi Renovation')
        self.assertEqual(serializer.data['organization_name'], 'Ramesh Seva Sanstha')
        self.assertEqual(serializer.data['status_display'], 'Draft')
        self.assertEqual(serializer.data['document_count'], 0)

    def test_project_detail_serializer_nested_documents_and_milestones(self):
        project = Project.objects.create(
            title='Village Library & Study Center',
            short_summary='Equipping community reading room.',
            description='Library with 1000 books and 4 computers.',
            posted_by=self.user,
            organization=self.ngo,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Manchar',
            location_pincode='410503',
            beneficiaries_count=350,
            estimated_cost=Decimal('150000.00'),
            timeline_months=2,
        )
        ProjectMilestone.objects.create(
            project=project,
            order=1,
            title='Furniture & Shelves',
            amount=Decimal('50000.00')
        )
        serializer = ProjectDetailSerializer(project)
        self.assertEqual(len(serializer.data['milestones']), 1)
        self.assertEqual(serializer.data['milestones'][0]['title'], 'Furniture & Shelves')
        self.assertEqual(serializer.data['posted_by_name'], 'Ramesh Kadam')
