"""
Grievance Attachment Security, Storage & Access Control Tests — Phase 5.1
========================================================================
Tests attachment streaming, authorization rules, URL generation, and missing-file handling:
1. Admin can retrieve valid ticket attachment.
2. Ticket owner can retrieve valid ticket attachment.
3. Target NGO participant can retrieve dispute attachment.
4. Unrelated NGO / Cross-organization user is denied (403).
5. Anonymous request is denied (401).
6. Missing file returns 404 with ATTACHMENT_FILE_MISSING.
7. Grievance response attachment access & internal note protection.
8. Query parameter JWT token authentication for direct viewing.
"""

import os
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from grievances.models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceResponse,
    GrievanceStatus,
    GrievanceTicket,
)
from ngo.models import NGOProfile

User = get_user_model()


class GrievanceAttachmentSecurityTests(APITestCase):
    """Test suite for grievance ticket and response attachment streaming and access control."""

    def setUp(self):
        # 1. Users
        self.admin_user = User.objects.create_user(
            email='admin.officer@example.com',
            password='testpassword123',
            first_name='Admin',
            last_name='Officer',
            role='ADMIN',
            is_staff=True,
        )
        self.company_user = User.objects.create_user(
            email='company.lead@example.com',
            password='testpassword123',
            first_name='Company',
            last_name='Lead',
            role='COMPANY',
        )
        self.target_ngo_user = User.objects.create_user(
            email='target.ngo@example.com',
            password='testpassword123',
            first_name='Target',
            last_name='NGO',
            role='NGO',
        )
        self.target_ngo_profile = NGOProfile.objects.create(
            user=self.target_ngo_user,
            legal_name='Target Seva Sanstha',
            display_name='Target Seva Sanstha',
            category='EDUCATION',
            year_established=2015,
            status=NGOProfile.Status.APPROVED,
        )
        self.unrelated_ngo_user = User.objects.create_user(
            email='unrelated.ngo@example.com',
            password='testpassword123',
            first_name='Unrelated',
            last_name='NGO',
            role='NGO',
        )
        self.unrelated_donor = User.objects.create_user(
            email='unrelated.donor@example.com',
            password='testpassword123',
            first_name='Unrelated',
            last_name='Donor',
            role='DONOR',
        )

        # 2. Upload dummy PDF attachment
        pdf_content = b"%PDF-1.4 Mock valid PDF document content for testing."
        uploaded_file = SimpleUploadedFile(
            name='Receipt_Test_123.pdf',
            content=pdf_content,
            content_type='application/pdf',
        )

        # 3. Create Ticket with Attachment
        self.ticket = GrievanceTicket.objects.create(
            user=self.company_user,
            title='Company 80G Receipt Dispute',
            description='Inquiry regarding 80G receipt formatting.',
            category=GrievanceCategory.RECEIPT_80G,
            priority=GrievancePriority.HIGH,
            status=GrievanceStatus.IN_REVIEW,
            target_ngo=self.target_ngo_profile,
            attachment=uploaded_file,
        )

    def tearDown(self):
        # Cleanup uploaded files from disk
        if self.ticket.attachment and self.ticket.attachment.name:
            if self.ticket.attachment.storage.exists(self.ticket.attachment.name):
                self.ticket.attachment.storage.delete(self.ticket.attachment.name)

    def test_admin_can_retrieve_attachment(self):
        """Admin can access ticket attachment with 200 and application/pdf."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get('Content-Type'), 'application/pdf')
        self.assertIn('Receipt_Test_123', response.get('Content-Disposition'))

    def test_ticket_owner_can_retrieve_attachment(self):
        """Complainant / ticket owner can access their own attachment."""
        self.client.force_authenticate(user=self.company_user)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get('Content-Type'), 'application/pdf')

    def test_target_ngo_participant_can_retrieve_attachment(self):
        """Target NGO involved in the dispute can access the supporting attachment."""
        self.client.force_authenticate(user=self.target_ngo_user)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unrelated_ngo_is_denied_access(self):
        """Unrelated NGO account receives 403 Forbidden when trying to access private attachment."""
        self.client.force_authenticate(user=self.unrelated_ngo_user)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get('code'), 'PERMISSION_DENIED')

    def test_unrelated_donor_is_denied_access(self):
        """Unrelated donor receives 403 Forbidden."""
        self.client.force_authenticate(user=self.unrelated_donor)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_request_is_denied(self):
        """Unauthenticated request receives 401 Unauthorized."""
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_query_param_token_authentication(self):
        """Valid JWT in ?token= query parameter authenticates user for direct tab viewing."""
        token = str(RefreshToken.for_user(self.company_user).access_token)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/?token={token}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_missing_file_returns_404(self):
        """If file record exists in database but physical file is missing from storage, return 404."""
        # Delete file from storage
        if self.ticket.attachment.storage.exists(self.ticket.attachment.name):
            self.ticket.attachment.storage.delete(self.ticket.attachment.name)

        self.client.force_authenticate(user=self.company_user)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get('code'), 'ATTACHMENT_FILE_MISSING')

    def test_ticket_detail_serializer_fields(self):
        """Serializer generates secure attachment_url, attachment_name, and attachment_available."""
        self.client.force_authenticate(user=self.company_user)
        response = self.client.get(f'/api/v1/grievances/tickets/{self.ticket.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        self.assertIn(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/', data.get('attachment'))
        self.assertIn(f'/api/v1/grievances/tickets/{self.ticket.id}/attachment/', data.get('attachment_url'))
        self.assertIn('Receipt_Test_123', data.get('attachment_name'))
        self.assertTrue(data.get('attachment_available'))

    def test_response_attachment_internal_note_protection(self):
        """Response attachment on internal notes cannot be accessed by non-admins."""
        resp_file = SimpleUploadedFile(
            name='Internal_Audit.pdf',
            content=b"%PDF-1.4 Internal staff audit report.",
            content_type='application/pdf',
        )
        response_obj = GrievanceResponse.objects.create(
            ticket=self.ticket,
            author=self.admin_user,
            message='Internal moderation note with attachment',
            attachment=resp_file,
            is_internal_note=True,
        )

        # 1. Admin can access internal note attachment
        self.client.force_authenticate(user=self.admin_user)
        admin_resp = self.client.get(f'/api/v1/grievances/responses/{response_obj.id}/attachment/')
        self.assertEqual(admin_resp.status_code, status.HTTP_200_OK)

        # 2. Ticket owner cannot access internal note attachment
        self.client.force_authenticate(user=self.company_user)
        owner_resp = self.client.get(f'/api/v1/grievances/responses/{response_obj.id}/attachment/')
        self.assertEqual(owner_resp.status_code, status.HTTP_403_FORBIDDEN)

        # Cleanup
        if response_obj.attachment and response_obj.attachment.storage.exists(response_obj.attachment.name):
            response_obj.attachment.storage.delete(response_obj.attachment.name)
