"""
DaanGives Admin NGO Verification & Review Views — Phase 3.3.2-H
================================================================
Admin-only views for inspecting, reviewing, approving, requesting corrections,
rejecting, suspending, reinstating, reopening, and auditing NGO applications.

Security Enforced:
  - Requires JWT authentication & active user with role == 'ADMIN' (IsAdminUser).
  - Rejects non-admin users with 403 Forbidden and anonymous users with 401 Unauthorized.
  - Derives actor strictly from request.user (never client body).
  - Operates atomically inside transaction.atomic() via verification service.
"""

from django.db.models import Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError, PermissionDenied

from ngo.models import NGOProfile, NGOVerificationHistory
from ngo.permissions import IsAdminUser
from ngo.serializers import (
    NGOAdminSerializer,
    NGOVerificationHistorySerializer,
)
from ngo.services.verification_service import (
    change_ngo_verification_status,
    reopen_ngo_application,
    StatusTransitionError,
    ResubmissionLimitError,
)


class NGOAdminPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50


class NGOAdminQueueView(APIView):
    """
    GET /api/v1/admin/ngos/ — Admin verification queue list.
    Supports status & category filters, multi-field search, ordering, and pagination.
    """
    permission_classes = [IsAdminUser]
    pagination_class = NGOAdminPagination

    def get(self, request):
        qs = NGOProfile.objects.all().select_related(
            'address', 'legal_info', 'bank_info', 'verification'
        ).prefetch_related('leadership', 'documents')

        # 1. Status filter
        status_param = request.query_params.get('status')
        pending_param = request.query_params.get('pending')
        if pending_param and pending_param.lower() in ('true', '1'):
            qs = qs.filter(status__in=[NGOProfile.Status.SUBMITTED, NGOProfile.Status.UNDER_REVIEW])
        elif status_param:
            status_clean = status_param.strip().upper()
            if status_clean == 'PENDING':
                qs = qs.filter(status__in=[NGOProfile.Status.SUBMITTED, NGOProfile.Status.UNDER_REVIEW])
            elif ',' in status_clean:
                statuses = [s.strip() for s in status_clean.split(',') if s.strip()]
                qs = qs.filter(status__in=statuses)
            elif status_clean != 'ALL':
                qs = qs.filter(status=status_clean)

        # 2. Category filter
        category = request.query_params.get('category')
        if category and category != 'All':
            qs = qs.filter(category=category)

        # 3. Search filter
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search) |
                Q(legal_name__icontains=search) |
                Q(legal_info__registration_number__icontains=search) |
                Q(legal_info__darpan_id__icontains=search)
            )

        # 4. Ordering — default by submitted_at/created_at descending
        ordering = request.query_params.get('ordering', '-created_at')
        allowed_orderings = {'created_at', '-created_at', 'display_name', '-display_name'}
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('-created_at')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = NGOAdminSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = NGOAdminSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminDetailView(APIView):
    """
    GET /api/v1/admin/ngos/<uuid:pk>/ — Full NGO inspection serializer for Admin only.
    Exposes complete profile, address, legal info, unmasked bank account, and documents.
    """
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminStartReviewView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/start-review/
    Transition: SUBMITTED -> UNDER_REVIEW. Sets review_started_at = now().
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            change_ngo_verification_status(
                ngo_profile=profile,
                new_status=NGOProfile.Status.UNDER_REVIEW,
                changed_by=request.user,
                reason='Admin started review.',
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminApproveView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/approve/
    Transition: UNDER_REVIEW -> APPROVED.
    Sets status = APPROVED, is_active = True, verified_at = now(), decision_at = now().
    Public visibility immediately becomes True.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', 'Application approved by admin.')
        verify_csr = bool(request.data.get('verify_csr', False))
        csr_notes = request.data.get('csr_notes', '')

        try:
            change_ngo_verification_status(
                ngo_profile=profile,
                new_status=NGOProfile.Status.APPROVED,
                changed_by=request.user,
                reason=reason,
                verify_csr=verify_csr,
                csr_review_notes=csr_notes,
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as e:
            return Response(e.detail if hasattr(e, 'detail') else {'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminRequestCorrectionView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/request-correction/
    Transition: UNDER_REVIEW -> CORRECTION_REQUIRED.
    Requires non-empty correction_instructions. Optional bank_correction_requested boolean.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        instructions = request.data.get('correction_instructions', '').strip()
        if not instructions:
            return Response(
                {'correction_instructions': ['Correction instructions are required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bank_flag = bool(request.data.get('bank_correction_requested', False))
        admin_notes = request.data.get('admin_notes', '').strip()

        try:
            change_ngo_verification_status(
                ngo_profile=profile,
                new_status=NGOProfile.Status.CORRECTION_REQUIRED,
                changed_by=request.user,
                correction_instructions=instructions,
                bank_correction_requested=bank_flag,
                admin_notes=admin_notes,
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as e:
            return Response(e.detail if hasattr(e, 'detail') else {'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminRejectView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/reject/
    Transition: UNDER_REVIEW -> REJECTED.
    Requires non-empty rejection_reason. Sets is_active = False.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('rejection_reason', '').strip()
        if not reason:
            return Response(
                {'rejection_reason': ['Rejection reason is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admin_notes = request.data.get('admin_notes', '').strip()

        try:
            change_ngo_verification_status(
                ngo_profile=profile,
                new_status=NGOProfile.Status.REJECTED,
                changed_by=request.user,
                rejection_reason=reason,
                admin_notes=admin_notes,
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminSuspendView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/suspend/
    Transition: APPROVED -> SUSPENDED.
    Requires non-empty reason. Sets is_active = False (public visibility becomes False).
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {'reason': ['Reason is required for suspension.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            change_ngo_verification_status(
                ngo_profile=profile,
                new_status=NGOProfile.Status.SUSPENDED,
                changed_by=request.user,
                reason=reason,
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminUnsuspendView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/unsuspend/
    Transition: SUSPENDED -> APPROVED.
    Requires non-empty reason. Sets is_active = True (public visibility becomes True).
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {'reason': ['Reason is required for reinstatement.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            change_ngo_verification_status(
                ngo_profile=profile,
                new_status=NGOProfile.Status.APPROVED,
                changed_by=request.user,
                reason=reason,
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminReopenView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/reopen/
    Resets status to DRAFT and sets admin_reopened = True for REJECTED or CORRECTION_REQUIRED NGOs.
    Allows NGO to resubmit application.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        additional_cycles = int(request.data.get('additional_cycles', 3))
        try:
            reopen_ngo_application(
                ngo_profile=profile,
                admin_user=request.user,
                additional_cycles=additional_cycles,
            )
        except StatusTransitionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminHistoryView(APIView):
    """
    GET /api/v1/admin/ngos/<uuid:pk>/history/ — Read-only verification history audit log.
    Ordered newest first by timestamp.
    """
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        history = NGOVerificationHistory.objects.filter(ngo=profile).order_by('-timestamp')
        serializer = NGOVerificationHistorySerializer(history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOAdminRecordManualGovCheckView(APIView):
    """
    POST /api/v1/admin/ngos/<uuid:pk>/record-gov-check/
    Allows Admin to record government verification result and evidence notes.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        profile = NGOProfile.objects.filter(pk=pk).first()
        if not profile:
            return Response({'detail': 'NGO application not found.'}, status=status.HTTP_404_NOT_FOUND)

        outcome = request.data.get('outcome')
        if not outcome:
            return Response({'detail': 'Outcome is required.'}, status=status.HTTP_400_BAD_REQUEST)

        source = request.data.get('source', 'MANUAL_ADMIN_CHECK')
        notes = request.data.get('notes', '')

        try:
            from ngo.services.verification_service import record_ngo_manual_verification
            record_ngo_manual_verification(
                admin_user=request.user,
                ngo_profile=profile,
                outcome=outcome,
                source=source,
                notes=notes,
            )
        except ValidationError as e:
            return Response(e.detail if hasattr(e, 'detail') else {'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)

        profile.refresh_from_db()
        serializer = NGOAdminSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

