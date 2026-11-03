from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile

from ngo.models import NGOProfile
from projects.models import (
    Project,
    ProjectDocument,
    ProjectMilestone,
    ProjectCategory,
    ProjectStatus,
    ProjectDocumentType,
    MilestoneStatus,
)
from projects.services import ProjectService

User = get_user_model()


class ProjectServiceComprehensiveTests(TestCase):
    def setUp(self):
        self.village_user = User.objects.create_user(
            email='sevatrust@village.org',
            password='Password123!',
            full_name='Santosh Patil',
            role='NGO'
        )
        self.other_user = User.objects.create_user(
            email='other@village.org',
            password='Password123!',
            full_name='Vikram Sharma',
            role='NGO'
        )
        self.admin_user = User.objects.create_user(
            email='admin@daangives.org',
            password='Password123!',
            full_name='Platform Admin',
            role='ADMIN',
            is_staff=True
        )

        self.ngo_profile = NGOProfile.objects.create(
            user=self.village_user,
            legal_name='Gram Seva Mandal Trust',
            display_name='Gram Seva Mandal',
            category='RURAL',
            year_established=2015,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )
        self.other_ngo = NGOProfile.objects.create(
            user=self.other_user,
            legal_name='Other Seva Sanstha Trust',
            display_name='Other Seva Sanstha',
            category='RURAL',
            year_established=2018,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )

    def test_create_draft_project_with_milestones(self):
        data = {
            'title': 'Solar Street Lights in Gram Panchayat',
            'short_summary': 'Installation of 50 solar street lights.',
            'description': 'Comprehensive rural lighting project.',
            'category': ProjectCategory.RURAL,
            'location_state': 'Maharashtra',
            'location_district': 'Kolhapur',
            'location_village': 'Shirol',
            'location_pincode': '416103',
            'beneficiaries_count': 3200,
            'beneficiaries_description': 'All residents of village Shirol',
            'estimated_cost': Decimal('600000.00'),
            'timeline_months': 4,
            'milestones': [
                {'title': 'Survey and Procurement', 'amount': Decimal('350000.00'), 'order': 1},
                {'title': 'Erection and Commissioning', 'amount': Decimal('250000.00'), 'order': 2},
            ]
        }

        project = ProjectService.create_draft(self.village_user, data)
        self.assertEqual(project.status, ProjectStatus.DRAFT)
        self.assertEqual(project.organization, self.ngo_profile)
        self.assertEqual(project.milestones.count(), 2)

    def test_update_project_success_and_idor_protection(self):
        project = Project.objects.create(
            title='Initial Title',
            short_summary='Initial summary',
            description='Initial description',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('500000.00'),
        )

        with self.assertRaises(PermissionDenied):
            ProjectService.update_project(self.other_user, project.id, {'title': 'Hacked Title'})

        updated = ProjectService.update_project(self.village_user, project.id, {'title': 'Updated Title'})
        self.assertEqual(updated.title, 'Updated Title')

    def test_cannot_update_verified_or_funded_project(self):
        project = Project.objects.create(
            title='Locked Project',
            short_summary='Summary',
            description='Desc',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('500000.00'),
            status=ProjectStatus.VERIFIED,
        )

        with self.assertRaises(ValidationError) as ctx:
            ProjectService.update_project(self.village_user, project.id, {'title': 'New Title'})
        self.assertIn("Only DRAFT or DOCS_PENDING", str(ctx.exception))

    def test_submit_for_verification_requires_document(self):
        project = Project.objects.create(
            title='Water Conservation Check Dam',
            short_summary='Building 2 check dams.',
            description='Water harvesting structure.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('900000.00'),
        )

        with self.assertRaises(ValidationError) as ctx:
            ProjectService.submit_for_verification(self.village_user, project.id)
        self.assertIn("At least one verification / statutory document", str(ctx.exception))

        dummy_file = SimpleUploadedFile("dpr_estimate.pdf", b"pdf content", content_type="application/pdf")
        ProjectService.add_document(
            user=self.village_user,
            project_id=project.id,
            document_type=ProjectDocumentType.TECHNICAL_ESTIMATE,
            file_obj=dummy_file,
            notes='DPR from certified civil engineer'
        )

        submitted_project = ProjectService.submit_for_verification(self.village_user, project.id)
        self.assertEqual(submitted_project.status, ProjectStatus.SUBMITTED)

    def test_withdraw_submission(self):
        project = Project.objects.create(
            title='Community Hall Renovation',
            short_summary='Repairing community hall.',
            description='Sanstha infrastructure.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('400000.00'),
            status=ProjectStatus.SUBMITTED,
        )

        reverted = ProjectService.withdraw_submission(self.village_user, project.id)
        self.assertEqual(reverted.status, ProjectStatus.DRAFT)

    def test_cannot_withdraw_verified_or_draft_project(self):
        project = Project.objects.create(
            title='Already Draft Project',
            short_summary='Summary',
            description='Desc',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('400000.00'),
            status=ProjectStatus.DRAFT,
        )
        with self.assertRaises(ValidationError):
            ProjectService.withdraw_submission(self.village_user, project.id)

    def test_document_and_milestone_lifecycle(self):
        project = Project.objects.create(
            title='Sanitation Complex for Girls School',
            short_summary='Building 6 toilet units.',
            description='Health and hygiene initiative.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('350000.00'),
        )

        dummy_file = SimpleUploadedFile("resolution.pdf", b"panchayat resolution", content_type="application/pdf")
        doc = ProjectService.add_document(self.village_user, project.id, ProjectDocumentType.PANCHAYAT_RESOLUTION, dummy_file)
        self.assertEqual(project.documents.count(), 1)

        ProjectService.delete_document(self.village_user, project.id, doc.id)
        self.assertEqual(project.documents.count(), 0)

        milestone = ProjectService.add_milestone(self.village_user, project.id, {
            'title': 'Civil Work',
            'amount': Decimal('200000.00'),
            'order': 1
        })
        self.assertEqual(project.milestones.count(), 1)

        ProjectService.delete_milestone(self.village_user, project.id, milestone.id)
        self.assertEqual(project.milestones.count(), 0)

    def test_admin_verification_all_actions(self):
        project = Project.objects.create(
            title='Vocational Training Center for Rural Women',
            short_summary='Sewing and handicraft center.',
            description='Women empowerment initiative.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.GENDER,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('550000.00'),
            status=ProjectStatus.SUBMITTED,
        )

        # 1. Start Review
        under_review = ProjectService.verify_project(self.admin_user, project.id, action='START_REVIEW', notes='Assigned to desk officer')
        self.assertEqual(under_review.status, ProjectStatus.UNDER_REVIEW)

        # 2. Request Changes / Docs Pending
        docs_pending = ProjectService.verify_project(self.admin_user, project.id, action='REQUEST_DOCS', notes='Please upload Gram Panchayat land NOC')
        self.assertEqual(docs_pending.status, ProjectStatus.DOCS_PENDING)

        # 3. Reject a separate submitted project
        project_to_reject = Project.objects.create(
            title='Project To Reject',
            short_summary='Rejected project summary',
            description='Non-compliant project',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.GENDER,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('200000.00'),
            status=ProjectStatus.SUBMITTED,
        )
        rejected = ProjectService.verify_project(self.admin_user, project_to_reject.id, action='REJECT', rejection_reason='Out of Section 135 scope')
        self.assertEqual(rejected.status, ProjectStatus.REJECTED)
        self.assertEqual(rejected.rejection_reason, 'Out of Section 135 scope')

        # 4. Approve an under_review project
        project_to_approve = Project.objects.create(
            title='Project To Approve',
            short_summary='Approved project summary',
            description='Compliant project',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.GENDER,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('300000.00'),
            status=ProjectStatus.UNDER_REVIEW,
        )
        verified = ProjectService.verify_project(self.admin_user, project_to_approve.id, action='APPROVE', notes='All criteria satisfied')
        self.assertEqual(verified.status, ProjectStatus.VERIFIED)
        self.assertEqual(verified.verified_by, self.admin_user)
        self.assertIsNotNone(verified.verified_at)

    def test_non_admin_cannot_verify_project(self):
        project = Project.objects.create(
            title='Test Project',
            short_summary='Summary',
            description='Desc',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('100000.00'),
            status=ProjectStatus.SUBMITTED,
        )
        with self.assertRaises(PermissionDenied):
            ProjectService.verify_project(self.village_user, project.id, action='APPROVE')

    def test_get_my_projects_filters(self):
        Project.objects.create(
            title='Project In Kolhapur',
            short_summary='Summary',
            description='Desc',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('100000.00'),
            status=ProjectStatus.DRAFT,
        )
        Project.objects.create(
            title='Project In Sangli',
            short_summary='Summary',
            description='Desc',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Sangli',
            location_village='Miraj',
            location_pincode='416410',
            estimated_cost=Decimal('200000.00'),
            status=ProjectStatus.VERIFIED,
        )

        # Filter by category
        res = ProjectService.get_my_projects(self.village_user, category=ProjectCategory.HEALTH)
        self.assertEqual(res.count(), 1)

        # Filter by status
        res_status = ProjectService.get_my_projects(self.village_user, status=ProjectStatus.VERIFIED)
        self.assertEqual(res_status.count(), 1)

        # Filter by search query
        res_search = ProjectService.get_my_projects(self.village_user, search='Miraj')
        self.assertEqual(res_search.count(), 1)

    def test_admin_add_to_verify_action_transitions_to_under_review(self):
        project = Project.objects.create(
            title='Education and Skill Training for Rural Youths',
            short_summary='Training center.',
            description='Skill development initiative.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Baramati',
            location_pincode='413102',
            estimated_cost=Decimal('450000.00'),
            status=ProjectStatus.SUBMITTED,
        )

        # Before action
        self.assertEqual(project.status, ProjectStatus.SUBMITTED)
        stats_before = ProjectService.get_my_project_stats(self.village_user)
        self.assertGreaterEqual(stats_before['submitted'], 1)

        # Execute ADD_TO_VERIFY action
        updated = ProjectService.verify_project(
            admin_user=self.admin_user,
            project_id=project.id,
            action='ADD_TO_VERIFY',
            notes='Project added to verification queue by Administrator via Add to Verify.'
        )

        # Verify persisted status transition
        self.assertEqual(updated.status, ProjectStatus.UNDER_REVIEW)
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.UNDER_REVIEW)

        # Verify audit history
        history = project.verification_history.first()
        self.assertIsNotNone(history)
        self.assertEqual(history.action, 'ADD_TO_VERIFY')
        self.assertEqual(history.from_status, 'SUBMITTED')
        self.assertEqual(history.to_status, 'UNDER_REVIEW')
        self.assertEqual(history.actor, self.admin_user)
        self.assertEqual(history.actor_type, 'ADMIN')

        # Verify updated stats
        stats_after = ProjectService.get_my_project_stats(self.village_user)
        self.assertEqual(stats_after['submitted'], stats_before['submitted'] - 1)
        self.assertEqual(stats_after['under_review'], stats_before['under_review'] + 1)

