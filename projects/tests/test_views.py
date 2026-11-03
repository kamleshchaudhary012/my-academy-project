from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from ngo.models import NGOProfile
from projects.models import (
    Project,
    ProjectDocument,
    ProjectMilestone,
    ProjectCategory,
    ProjectStatus,
    ProjectDocumentType,
)

User = get_user_model()


class ProjectAPIViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.village_user = User.objects.create_user(
            email='gramin_vikas@pune.org',
            password='Password123!',
            full_name='Anil Kadam',
            role='NGO'
        )
        self.other_village_user = User.objects.create_user(
            email='other_sanstha@nashik.org',
            password='Password123!',
            full_name='Prakash More',
            role='NGO'
        )
        self.company_user = User.objects.create_user(
            email='csr_lead@tatasteel.com',
            password='Password123!',
            full_name='Rohit Sen',
            role='COMPANY'
        )
        self.admin_user = User.objects.create_user(
            email='admin@daangives.org',
            password='Password123!',
            full_name='Admin Lead',
            role='ADMIN',
            is_staff=True
        )

        self.ngo_profile = NGOProfile.objects.create(
            user=self.village_user,
            legal_name='Gramin Vikas Sanstha Pune Trust',
            display_name='Gramin Vikas Sanstha Pune',
            category='RURAL',
            year_established=2016,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )
        self.other_ngo_profile = NGOProfile.objects.create(
            user=self.other_village_user,
            legal_name='Gram Seva Nashik Trust',
            display_name='Gram Seva Nashik',
            category='RURAL',
            year_established=2019,
            status=NGOProfile.Status.APPROVED,
            is_active=True
        )

    def test_create_project_api(self):
        self.client.force_authenticate(user=self.village_user)
        payload = {
            "title": "Solar Powered Irrigation Pump for 120 Marginal Farmers",
            "short_summary": "Installation of 5HP community solar water pump.",
            "description": "Will irrigate 65 acres of collective farmland during drought season.",
            "category": "RURAL",
            "location_state": "Maharashtra",
            "location_district": "Pune",
            "location_village": "Junnar",
            "location_pincode": "410502",
            "beneficiaries_count": 550,
            "beneficiaries_description": "120 small and marginal farmer households",
            "estimated_cost": "750000.00",
            "timeline_months": 5,
            "milestones": [
                {"title": "Borewell inspection and solar pump procurement", "amount": "450000.00", "order": 1},
                {"title": "Pipeline grid network installation", "amount": "300000.00", "order": 2}
            ]
        }

        response = self.client.post('/api/v1/projects/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'DRAFT')
        self.assertEqual(response.data['organization_name'], 'Gramin Vikas Sanstha Pune')
        self.assertEqual(len(response.data['milestones']), 2)

    def test_create_project_validation_errors(self):
        self.client.force_authenticate(user=self.village_user)

        # Negative cost
        res = self.client.post('/api/v1/projects/', data={
            "title": "Valid Title Here",
            "short_summary": "Summary",
            "description": "Desc",
            "estimated_cost": "-100.00",
            "timeline_months": 3
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Zero timeline
        res = self.client.post('/api/v1/projects/', data={
            "title": "Valid Title Here",
            "short_summary": "Summary",
            "description": "Desc",
            "estimated_cost": "1000.00",
            "timeline_months": 0
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Short title
        res = self.client.post('/api/v1/projects/', data={
            "title": "ABC",
            "short_summary": "Summary",
            "description": "Desc",
            "estimated_cost": "1000.00",
            "timeline_months": 3
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_village_user_cannot_create_project(self):
        self.client.force_authenticate(user=self.company_user)
        payload = {
            "title": "Corporate Project Posting Attempt",
            "short_summary": "Invalid attempt",
            "description": "Description",
            "category": "RURAL",
            "location_state": "Maharashtra",
            "location_district": "Pune",
            "location_village": "Junnar",
            "location_pincode": "410502",
            "estimated_cost": "500000.00",
            "timeline_months": 4
        }
        response = self.client.post('/api/v1/projects/', data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_my_projects(self):
        Project.objects.create(
            title='Project 1',
            short_summary='Summary 1',
            description='Desc 1',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('300000.00'),
        )
        Project.objects.create(
            title='Project 2',
            short_summary='Summary 2',
            description='Desc 2',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('400000.00'),
        )
        Project.objects.create(
            title='Other Project',
            short_summary='Other summary',
            description='Other desc',
            posted_by=self.other_village_user,
            organization=self.other_ngo_profile,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Nashik',
            location_village='Dindori',
            location_pincode='422202',
            estimated_cost=Decimal('200000.00'),
        )

        self.client.force_authenticate(user=self.village_user)
        response = self.client.get('/api/v1/projects/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        self.assertEqual(response.data['count'], 2)
        self.assertIn('stats', response.data)
        self.assertEqual(response.data['stats']['total'], 2)

    def test_idor_protection_on_draft_project_detail(self):
        project = Project.objects.create(
            title='Confidential Village Proposal',
            short_summary='Draft summary',
            description='Draft details',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('500000.00'),
            status=ProjectStatus.DRAFT,
        )

        self.client.force_authenticate(user=self.other_village_user)
        response = self.client.get(f'/api/v1/projects/{project.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.village_user)
        response = self.client.get(f'/api/v1/projects/{project.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_document_upload_and_verification_submit_workflow(self):
        self.client.force_authenticate(user=self.village_user)

        project = Project.objects.create(
            title='Gram Panchayat Sanitation Facility',
            short_summary='Community toilets for bus stand and market.',
            description='Public hygiene infrastructure.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('420000.00'),
            status=ProjectStatus.DRAFT,
        )

        response = self.client.post(f'/api/v1/projects/{project.id}/submit/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('statutory document', response.data['detail'])

        dummy_file = SimpleUploadedFile("panchayat_approval.pdf", b"pdf stream data", content_type="application/pdf")
        doc_response = self.client.post(
            f'/api/v1/projects/{project.id}/documents/',
            data={'document_type': 'PANCHAYAT_RESOLUTION', 'file': dummy_file, 'notes': 'Resolution passed by 11 members'},
            format='multipart'
        )
        self.assertEqual(doc_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(doc_response.data['document_type'], 'PANCHAYAT_RESOLUTION')

        submit_response = self.client.post(f'/api/v1/projects/{project.id}/submit/')
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK)
        self.assertEqual(submit_response.data['project']['status'], 'SUBMITTED')

        withdraw_response = self.client.post(f'/api/v1/projects/{project.id}/withdraw/')
        self.assertEqual(withdraw_response.status_code, status.HTTP_200_OK)
        self.assertEqual(withdraw_response.data['project']['status'], 'DRAFT')

    def test_milestone_management_endpoints(self):
        self.client.force_authenticate(user=self.village_user)

        project = Project.objects.create(
            title='Community Pond Deepening',
            short_summary='Water catchment expansion.',
            description='Drought proofing.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('300000.00'),
            status=ProjectStatus.DRAFT,
        )

        # Add milestone via API
        res = self.client.post(f'/api/v1/projects/{project.id}/milestones/', data={
            'title': 'Excavation Phase',
            'amount': '150000.00',
            'order': 1
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        milestone_id = res.data['id']

        # Delete milestone via API
        del_res = self.client.delete(f'/api/v1/projects/{project.id}/milestones/{milestone_id}/')
        self.assertEqual(del_res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(project.milestones.count(), 0)

    def test_admin_verification_api(self):
        project = Project.objects.create(
            title='Drinking Water Overhead Tank',
            short_summary='50,000L water tank.',
            description='Overhead storage and gravity distribution.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('850000.00'),
            status=ProjectStatus.SUBMITTED,
        )

        self.client.force_authenticate(user=self.village_user)
        response = self.client.patch(f'/api/v1/projects/{project.id}/verify/', data={'action': 'APPROVE'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(
            f'/api/v1/projects/{project.id}/verify/',
            data={'action': 'APPROVE', 'notes': 'All technical and panchayat sanctions verified.'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['project']['status'], 'VERIFIED')

    def test_public_endpoints_list_and_detail(self):
        verified_project = Project.objects.create(
            title='Verified Rural Solar Grid',
            short_summary='Solar micro grid.',
            description='Electrification of 80 remote homes.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.ENVIRONMENT,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('650000.00'),
            status=ProjectStatus.VERIFIED,
        )
        draft_project = Project.objects.create(
            title='Unverified Draft Project',
            short_summary='Draft summary',
            description='Draft desc',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('300000.00'),
            status=ProjectStatus.DRAFT,
        )

        self.client.logout()

        list_res = self.client.get('/api/v1/projects/public/')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        project_ids = [p['id'] for p in list_res.data]
        self.assertIn(str(verified_project.id), project_ids)
        self.assertNotIn(str(draft_project.id), project_ids)

        detail_res = self.client.get(f'/api/v1/projects/public/{verified_project.id}/')
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)

        draft_detail_res = self.client.get(f'/api/v1/projects/public/{draft_project.id}/')
        self.assertEqual(draft_detail_res.status_code, status.HTTP_404_NOT_FOUND)

    def test_my_projects_pagination_filtering_and_stats(self):
        self.client.force_authenticate(user=self.village_user)
        # Create projects in various statuses
        for i in range(5):
            Project.objects.create(
                title=f'Draft Project {i}',
                short_summary='Draft summary',
                description='Draft description',
                posted_by=self.village_user,
                organization=self.ngo_profile,
                category=ProjectCategory.EDUCATION,
                location_state='Maharashtra',
                location_district='Pune',
                location_village='Junnar',
                location_pincode='410502',
                estimated_cost=Decimal('100000.00'),
                status=ProjectStatus.DRAFT,
            )
        Project.objects.create(
            title='Verified Water Project',
            short_summary='Water summary',
            description='Water description',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('500000.00'),
            status=ProjectStatus.VERIFIED,
        )

        # GET /api/v1/projects/me/
        res = self.client.get('/api/v1/projects/me/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('stats', res.data)
        stats = res.data['stats']
        self.assertEqual(stats['total'], 6)
        self.assertEqual(stats['draft'], 5)
        self.assertEqual(stats['verified'], 1)

        # Filter by status=VERIFIED
        res_verified = self.client.get('/api/v1/projects/me/?status=VERIFIED')
        self.assertEqual(res_verified.status_code, status.HTTP_200_OK)
        self.assertEqual(res_verified.data['count'], 1)
        self.assertEqual(res_verified.data['results'][0]['title'], 'Verified Water Project')
        # Stats remain complete for the NGO
        self.assertEqual(res_verified.data['stats']['total'], 6)

    def test_project_admin_correction_notes_and_resubmission_with_history(self):
        # 1. Create project
        self.client.force_authenticate(user=self.village_user)
        project = Project.objects.create(
            title='School Computer Lab Project',
            short_summary='Installing 20 computers in rural school',
            description='Digital literacy for tribal students',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Junnar',
            location_pincode='410502',
            estimated_cost=Decimal('400000.00'),
            status=ProjectStatus.DRAFT,
        )

        # 2. Attach statutory document
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_file = SimpleUploadedFile("resolution.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        upload_res = self.client.post(
            f'/api/v1/projects/{project.id}/documents/',
            data={'document_type': 'PANCHAYAT_RESOLUTION', 'file': fake_file, 'notes': 'Resolution from Gram Sabha'},
            format='multipart'
        )
        self.assertEqual(upload_res.status_code, status.HTTP_201_CREATED)

        # 3. Submit for verification
        submit_res = self.client.post(f'/api/v1/projects/{project.id}/submit/')
        self.assertEqual(submit_res.status_code, status.HTTP_200_OK)
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.SUBMITTED)

        # Check history recorded SUBMITTED
        history_records = project.verification_history.all()
        self.assertTrue(history_records.filter(action='SUBMITTED').exists())

        # 4. Admin requests corrections (DOCS_PENDING)
        self.client.force_authenticate(user=self.admin_user)
        review_res = self.client.post(
            f'/api/v1/projects/{project.id}/verify/',
            data={'action': 'DOCS_PENDING', 'notes': 'Please attach DPR technical cost estimate.'},
            format='json'
        )
        self.assertEqual(review_res.status_code, status.HTTP_200_OK)
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.DOCS_PENDING)
        self.assertEqual(project.verification_notes, 'Please attach DPR technical cost estimate.')

        # 5. NGO views project detail and sees review notes and history
        self.client.force_authenticate(user=self.village_user)
        detail_res = self.client.get(f'/api/v1/projects/{project.id}/')
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data['verification_notes'], 'Please attach DPR technical cost estimate.')
        self.assertIn('verification_history', detail_res.data)
        self.assertGreaterEqual(len(detail_res.data['verification_history']), 2)

        # 6. NGO attaches requested document and resubmits
        fake_dpr = SimpleUploadedFile("dpr_estimate.pdf", b"%PDF-1.4 DPR", content_type="application/pdf")
        self.client.post(
            f'/api/v1/projects/{project.id}/documents/',
            data={'document_type': 'TECHNICAL_ESTIMATE', 'file': fake_dpr, 'notes': 'Detailed technical estimate attached.'},
            format='multipart'
        )
        resubmit_res = self.client.post(f'/api/v1/projects/{project.id}/submit/')
        self.assertEqual(resubmit_res.status_code, status.HTTP_200_OK)
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.SUBMITTED)

        # 7. Admin approves/verifies
        self.client.force_authenticate(user=self.admin_user)
        approve_res = self.client.post(
            f'/api/v1/projects/{project.id}/verify/',
            data={'action': 'VERIFY', 'notes': 'Approved and verified for CSR partnerships.'},
            format='json'
        )
        self.assertEqual(approve_res.status_code, status.HTTP_200_OK)
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.VERIFIED)
        self.assertIsNotNone(project.verified_at)

    def test_ngo_profile_verification_and_history_api(self):
        # Authenticate NGO
        self.client.force_authenticate(user=self.village_user)
        res = self.client.get('/api/v1/ngo/profile/me/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('verification', res.data)

        # Query history
        hist_res = self.client.get('/api/v1/ngo/history/')
        self.assertEqual(hist_res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(hist_res.data, list)

    def test_admin_add_to_verify_action_sync_and_permissions(self):
        project = Project.objects.create(
            title='Financial Assistance and Skill Development Program for Underprivileged Students',
            short_summary='Skill program.',
            description='Detailed skill program for students.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Baramati',
            location_pincode='413102',
            estimated_cost=Decimal('500000.00'),
            status=ProjectStatus.SUBMITTED,
        )

        # 1. Unauthorized NGO user cannot perform Admin verify action
        self.client.force_authenticate(user=self.village_user)
        unauth_res = self.client.post(
            f'/api/v1/projects/{project.id}/verify/',
            data={'action': 'ADD_TO_VERIFY', 'notes': 'Unauthorized attempt'},
            format='json'
        )
        self.assertEqual(unauth_res.status_code, status.HTTP_403_FORBIDDEN)
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.SUBMITTED)

        # 2. Admin performs "ADD_TO_VERIFY" action
        self.client.force_authenticate(user=self.admin_user)
        admin_res = self.client.post(
            f'/api/v1/projects/{project.id}/verify/',
            data={'action': 'ADD_TO_VERIFY', 'notes': 'Added to verification queue by Administrator'},
            format='json'
        )
        self.assertEqual(admin_res.status_code, status.HTTP_200_OK)
        self.assertEqual(admin_res.data['project']['status'], 'UNDER_REVIEW')

        # 3. Verify backend DB persistence
        project.refresh_from_db()
        self.assertEqual(project.status, ProjectStatus.UNDER_REVIEW)

        # 4. Verify ProjectVerificationHistory record
        history = project.verification_history.first()
        self.assertIsNotNone(history)
        self.assertEqual(history.action, 'ADD_TO_VERIFY')
        self.assertEqual(history.from_status, 'SUBMITTED')
        self.assertEqual(history.to_status, 'UNDER_REVIEW')
        self.assertEqual(history.actor, self.admin_user)
        self.assertEqual(history.actor_type, 'ADMIN')

        # 5. NGO calls GET /api/v1/projects/me/ and sees UNDER_REVIEW status and updated KPI stats
        self.client.force_authenticate(user=self.village_user)
        ngo_list_res = self.client.get('/api/v1/projects/me/')
        self.assertEqual(ngo_list_res.status_code, status.HTTP_200_OK)
        
        found = next((p for p in ngo_list_res.data['results'] if p['id'] == str(project.id)), None)
        self.assertIsNotNone(found)
        self.assertEqual(found['status'], 'UNDER_REVIEW')
        self.assertIn('UNDER_REVIEW', found['status'])

        # Check KPI stats
        stats = ngo_list_res.data.get('stats', {})
        self.assertEqual(stats.get('submitted', 0), 0)
        self.assertEqual(stats.get('under_review', 0), 1)

        # 6. Simulate refreshing NGO project listing - status remains UNDER_REVIEW
        refresh_res = self.client.get('/api/v1/projects/me/')
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)
        refreshed_item = next((p for p in refresh_res.data['results'] if p['id'] == str(project.id)), None)
        self.assertEqual(refreshed_item['status'], 'UNDER_REVIEW')

    def test_admin_project_queue_api_and_permissions(self):
        # Create projects in various statuses
        proj1 = Project.objects.create(
            title='Rural Water Pipeline Infrastructure Project',
            short_summary='Pipeline for clean drinking water.',
            description='Water distribution network across 3 hamlets.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.RURAL,
            location_state='Maharashtra',
            location_district='Pune',
            location_village='Baramati',
            location_pincode='413102',
            estimated_cost=Decimal('750000.00'),
            status=ProjectStatus.SUBMITTED,
        )
        proj2 = Project.objects.create(
            title='Solar Power for Village High School',
            short_summary='Solar rooftop installation.',
            description='5kW solar plant for rural school.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.EDUCATION,
            location_state='Maharashtra',
            location_district='Kolhapur',
            location_village='Shirol',
            location_pincode='416103',
            estimated_cost=Decimal('350000.00'),
            status=ProjectStatus.UNDER_REVIEW,
        )
        proj3 = Project.objects.create(
            title='Community Healthcare Health Center',
            short_summary='Primary clinic support.',
            description='Clinic equipment and basic medicine.',
            posted_by=self.village_user,
            organization=self.ngo_profile,
            category=ProjectCategory.HEALTH,
            location_state='Maharashtra',
            location_district='Sangli',
            location_village='Miraj',
            location_pincode='416410',
            estimated_cost=Decimal('400000.00'),
            status=ProjectStatus.VERIFIED,
        )

        # 1. Non-admin forbidden
        self.client.force_authenticate(user=self.village_user)
        res_unauth = self.client.get('/api/v1/admin/projects/')
        self.assertEqual(res_unauth.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Admin access
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get('/api/v1/admin/projects/')
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        self.assertIn('results', res_admin.data)
        self.assertIn('stats', res_admin.data)
        self.assertGreaterEqual(res_admin.data['count'], 3)
        self.assertGreaterEqual(res_admin.data['stats']['pending'], 2)
        self.assertGreaterEqual(res_admin.data['stats']['verified'], 1)

        # 3. Status filter: PENDING (SUBMITTED + UNDER_REVIEW)
        res_pending = self.client.get('/api/v1/admin/projects/?status=PENDING')
        self.assertEqual(res_pending.status_code, status.HTTP_200_OK)
        pending_ids = [p['id'] for p in res_pending.data['results']]
        self.assertIn(str(proj1.id), pending_ids)
        self.assertIn(str(proj2.id), pending_ids)
        self.assertNotIn(str(proj3.id), pending_ids)

        # 4. Search filter: "Pipeline"
        res_search = self.client.get('/api/v1/admin/projects/?search=Pipeline')
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        search_ids = [p['id'] for p in res_search.data['results']]
        self.assertIn(str(proj1.id), search_ids)
        self.assertNotIn(str(proj2.id), search_ids)

        # 5. Detail inspection: GET /api/v1/admin/projects/<id>/
        res_detail = self.client.get(f'/api/v1/admin/projects/{proj1.id}/')
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data['id'], str(proj1.id))
        self.assertEqual(res_detail.data['title'], 'Rural Water Pipeline Infrastructure Project')

        # 6. Audit history endpoint: GET /api/v1/admin/projects/<id>/history/
        res_history = self.client.get(f'/api/v1/admin/projects/{proj1.id}/history/')
        self.assertEqual(res_history.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res_history.data, list)


