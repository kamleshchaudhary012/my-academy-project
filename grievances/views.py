"""
Grievance Ticketing API Views — Phase 5.1
==========================================
Implements DRF API views for grievance ticket management, status transitions,
staff assignment, threaded responses, and internal note moderation.
"""

import mimetypes
import os
from django.contrib.auth import get_user_model
from django.core import exceptions as dj_exceptions
from django.http import FileResponse, Http404
from rest_framework import exceptions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .exceptions import (
    GrievanceNotFoundError,
    GrievancePermissionDenied,
    GrievanceValidationError,
)
from .models import GrievanceResponse, GrievanceTicket
from .permissions import (
    CanAssignTicket,
    CanCreateTicket,
    CanTransitionStatus,
    IsAuthenticatedAndActive,
    IsResponseAuthorOrStaff,
    IsTicketOwner,
    IsTicketOwnerOrAssignedStaff,
)
from .serializers import (
    GrievanceResponseSerializer,
    GrievanceResponseUpdateSerializer,
    GrievanceTicketDetailSerializer,
    GrievanceTicketListSerializer,
    GrievanceTicketSerializer,
)
from .services import GrievanceService

User = get_user_model()


class GrievancePagination(PageNumberPagination):
    """Standard pagination for grievance ticket lists."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class GrievanceBaseAPIView(APIView):
    """
    Base view standardizing exception formatting across all grievance endpoints.
    Format: {"detail": "<message>", "code": "<MACHINE_CODE>"}
    """

    def handle_exception(self, exc):
        if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
            return Response(
                {
                    "detail": "Authentication credentials were not provided.",
                    "code": "NOT_AUTHENTICATED",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if isinstance(exc, (exceptions.PermissionDenied, dj_exceptions.PermissionDenied, GrievancePermissionDenied)):
            msg = getattr(exc, 'detail', None) or str(exc) or "You do not have permission to perform this action."
            if hasattr(msg, 'string'):
                msg = str(msg)
            return Response(
                {
                    "detail": str(msg),
                    "code": "PERMISSION_DENIED",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if isinstance(exc, (exceptions.NotFound, dj_exceptions.ObjectDoesNotExist, GrievanceNotFoundError, Http404)):
            msg = getattr(exc, 'detail', None) or str(exc) or "Resource not found."
            if hasattr(msg, 'string'):
                msg = str(msg)
            return Response(
                {
                    "detail": str(msg),
                    "code": "NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if isinstance(exc, (exceptions.ValidationError, dj_exceptions.ValidationError, GrievanceValidationError)):
            code = getattr(exc, 'code', None)
            if code != "INVALID_STATUS_TRANSITION":
                if hasattr(exc, 'detail') and isinstance(exc.detail, list) and exc.detail and getattr(exc.detail[0], 'code', None) == "INVALID_STATUS_TRANSITION":
                    code = "INVALID_STATUS_TRANSITION"
                elif hasattr(exc, 'detail') and isinstance(exc.detail, dict) and any(
                    isinstance(errs, list) and errs and getattr(errs[0], 'code', None) == "INVALID_STATUS_TRANSITION"
                    for errs in exc.detail.values()
                ):
                    code = "INVALID_STATUS_TRANSITION"
                else:
                    code = "VALIDATION_ERROR"

            detail_val = getattr(exc, 'detail', str(exc))
            if isinstance(detail_val, (dict, list)):
                detail_val = str(detail_val)
            else:
                detail_val = str(detail_val)

            return Response(
                {
                    "detail": detail_val,
                    "code": code,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().handle_exception(exc)


class GrievanceTicketListCreateView(GrievanceBaseAPIView):
    """
    GET: List current authenticated user's tickets with optional filtering and pagination.
    POST: Submit a new grievance ticket.
    """
    permission_classes = [IsAuthenticatedAndActive, CanCreateTicket]
    pagination_class = GrievancePagination

    def get(self, request):
        filters = {}
        for param in ['status', 'priority', 'category']:
            val = request.query_params.get(param)
            if val:
                filters[param] = val

        is_admin = bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'is_active', False)
            and (getattr(request.user, 'is_staff', False) or getattr(request.user, 'role', None) == 'ADMIN')
        )

        queryset = GrievanceService.get_tickets_for_user(
            user=request.user,
            filters=filters,
            is_admin=is_admin,
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = GrievanceTicketListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = GrievanceTicketListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = GrievanceTicketSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(serializer.errors, code="VALIDATION_ERROR")

        ticket = GrievanceService.create_ticket(
            user=request.user,
            validated_data=serializer.validated_data,
        )
        output_serializer = GrievanceTicketDetailSerializer(ticket)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class GrievanceTicketDetailView(GrievanceBaseAPIView):
    """
    GET: Retrieve full detail of a specific ticket.
    Non-admin callers receive filtered responses with internal notes stripped.
    """
    permission_classes = [IsAuthenticatedAndActive, IsTicketOwner]

    def get(self, request, id):
        ticket = GrievanceService.get_ticket_detail(
            user=request.user,
            ticket_id=id,
            is_admin=request.user.is_staff,
        )
        self.check_object_permissions(request, ticket)

        # Filter responses according to user privilege level
        responses = GrievanceService.filter_responses_for_user(ticket, is_admin=request.user.is_staff)
        data = GrievanceTicketDetailSerializer(ticket, context={'request': request}).data
        data['responses'] = GrievanceResponseSerializer(responses, many=True, context={'request': request}).data

        return Response(data, status=status.HTTP_200_OK)


class GrievanceTicketTransitionView(GrievanceBaseAPIView):
    """
    POST: Execute a state machine status transition on a grievance ticket.
    """
    permission_classes = [IsAuthenticatedAndActive, IsTicketOwnerOrAssignedStaff, CanTransitionStatus]

    def post(self, request, id):
        ticket = GrievanceService.get_ticket_detail(
            user=request.user,
            ticket_id=id,
            is_admin=request.user.is_staff,
        )
        self.check_object_permissions(request, ticket)

        new_status = request.data.get('new_status')
        if not new_status:
            raise exceptions.ValidationError("new_status is required.", code="VALIDATION_ERROR")

        resolution_summary = request.data.get('resolution_summary', '')
        updated_ticket = GrievanceService.transition_status(
            ticket=ticket,
            new_status=new_status,
            performed_by=request.user,
            resolution_summary=resolution_summary,
        )
        return Response(GrievanceTicketDetailSerializer(updated_ticket).data, status=status.HTTP_200_OK)


class GrievanceTicketAssignView(GrievanceBaseAPIView):
    """
    POST: Assign an administrative or support officer to investigate the ticket.
    """
    permission_classes = [IsAuthenticatedAndActive, CanAssignTicket]

    def post(self, request, id):
        ticket = GrievanceService.get_ticket_detail(
            user=request.user,
            ticket_id=id,
            is_admin=request.user.is_staff,
        )
        self.check_object_permissions(request, ticket)

        assigned_to_id = request.data.get('assigned_to_user_id') or request.data.get('assigned_to')
        if not assigned_to_id:
            raise exceptions.ValidationError("assigned_to_user_id is required.", code="VALIDATION_ERROR")

        try:
            target_user = User.objects.get(pk=assigned_to_id)
        except (User.DoesNotExist, ValueError):
            raise exceptions.ValidationError("Target assigned user does not exist.", code="VALIDATION_ERROR")

        assigned_ticket = GrievanceService.assign_ticket(
            ticket=ticket,
            assigned_to_user=target_user,
            performed_by=request.user,
        )
        return Response(GrievanceTicketDetailSerializer(assigned_ticket).data, status=status.HTTP_200_OK)


class GrievanceResponseListCreateView(GrievanceBaseAPIView):
    """
    GET: List message thread responses for a ticket.
    POST: Append a response or internal administrative note.
    """
    permission_classes = [IsAuthenticatedAndActive, IsTicketOwnerOrAssignedStaff]

    def get(self, request, id):
        ticket = GrievanceService.get_ticket_detail(
            user=request.user,
            ticket_id=id,
            is_admin=request.user.is_staff,
        )
        self.check_object_permissions(request, ticket)

        responses = GrievanceService.filter_responses_for_user(ticket, is_admin=request.user.is_staff)
        serializer = GrievanceResponseSerializer(responses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, id):
        ticket = GrievanceService.get_ticket_detail(
            user=request.user,
            ticket_id=id,
            is_admin=request.user.is_staff,
        )
        self.check_object_permissions(request, ticket)

        serializer = GrievanceResponseSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(serializer.errors, code="VALIDATION_ERROR")

        response = GrievanceService.create_response(
            ticket=ticket,
            author=request.user,
            validated_data=serializer.validated_data,
            is_admin=request.user.is_staff,
        )
        output_serializer = GrievanceResponseSerializer(response)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class GrievanceResponseUpdateView(GrievanceBaseAPIView):
    """
    PATCH: Update an existing response (only is_internal_note can be toggled by staff/author).
    """
    permission_classes = [IsAuthenticatedAndActive, IsResponseAuthorOrStaff]

    def patch(self, request, id):
        try:
            response_obj = GrievanceResponse.objects.select_related('ticket', 'author').get(pk=id)
        except (GrievanceResponse.DoesNotExist, ValueError):
            raise GrievanceNotFoundError("Grievance response not found.")

        self.check_object_permissions(request, response_obj)

        serializer = GrievanceResponseUpdateSerializer(response_obj, data=request.data, partial=True)
        if not serializer.is_valid():
            raise exceptions.ValidationError(serializer.errors, code="VALIDATION_ERROR")

        is_internal = serializer.validated_data['is_internal_note']
        if is_internal and not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff members can mark a note as internal.", code="PERMISSION_DENIED")

        response_obj.is_internal_note = is_internal
        response_obj.save(update_fields=['is_internal_note'])

        return Response(GrievanceResponseSerializer(response_obj).data, status=status.HTTP_200_OK)


def user_has_ticket_attachment_access(user, ticket):
    """
    Checks whether a user is authorized to access attachments on a grievance ticket.
    Permitted:
      - Administrators / staff (is_staff=True or role='ADMIN')
      - Assigned officer (ticket.assigned_to_id == user.id)
      - Complainant / Ticket creator (ticket.user_id == user.id)
      - Targeted NGO owner (ticket.target_ngo.user_id == user.id)
      - Bilateral CSR Partnership participant:
          partner company user (ticket.partnership.company.user_id == user.id)
          partner NGO user (ticket.partnership.ngo.user_id == user.id)
    All other users (unrelated NGOs, companies, donors, anonymous) are DENIED.
    """
    if not (user and user.is_authenticated and getattr(user, 'is_active', False)):
        return False

    if getattr(user, 'is_staff', False) or getattr(user, 'role', None) == 'ADMIN':
        return True

    if ticket.assigned_to_id and ticket.assigned_to_id == user.id:
        return True

    if ticket.user_id == user.id:
        return True

    if ticket.target_ngo_id and getattr(ticket.target_ngo, 'user_id', None) == user.id:
        return True

    if ticket.partnership_id:
        partnership = ticket.partnership
        company = getattr(partnership, 'company', None)
        if company and getattr(company, 'user_id', None) == user.id:
            return True
        ngo = getattr(partnership, 'ngo', None)
        if ngo and getattr(ngo, 'user_id', None) == user.id:
            return True

    return False


class GrievanceAttachmentAuthentication(JWTAuthentication):
    """
    Extends JWTAuthentication to support both Authorization: Bearer <token>
    and ?token=<jwt> query parameter for inline PDF viewing in new tabs.
    """
    def authenticate(self, request):
        auth = super().authenticate(request)
        if auth is not None:
            return auth
        get_params = getattr(request, 'query_params', None)
        if get_params is None:
            get_params = getattr(request, 'GET', {})
        token = get_params.get('token')
        if not token:
            return None
        try:
            val_token = self.get_validated_token(token)
            return self.get_user(val_token), val_token
        except Exception:
            return None


class GrievanceTicketAttachmentView(GrievanceBaseAPIView):
    """
    GET: Securely stream grievance ticket attachment with strict authorization.
    Accessible to authorized staff/admins and permitted ticket participants only.
    """
    authentication_classes = [GrievanceAttachmentAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, id):
        try:
            ticket = GrievanceTicket.objects.select_related(
                'user', 'assigned_to', 'target_ngo', 'partnership__company', 'partnership__ngo'
            ).get(pk=id)
        except (GrievanceTicket.DoesNotExist, ValueError):
            raise GrievanceNotFoundError("Grievance ticket not found.")

        if not user_has_ticket_attachment_access(request.user, ticket):
            raise exceptions.PermissionDenied(
                "You do not have permission to access this grievance attachment.",
                code="PERMISSION_DENIED"
            )

        if not ticket.attachment or not ticket.attachment.name:
            return Response(
                {
                    "detail": "Attachment not found on this ticket.",
                    "code": "ATTACHMENT_NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if not ticket.attachment.storage.exists(ticket.attachment.name):
            return Response(
                {
                    "detail": "Attachment file is unavailable on server.",
                    "code": "ATTACHMENT_FILE_MISSING",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            file_handle = ticket.attachment.open('rb')
        except Exception:
            return Response(
                {
                    "detail": "Unable to read attachment file from storage.",
                    "code": "ATTACHMENT_READ_ERROR",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        mime_type, _ = mimetypes.guess_type(ticket.attachment.name)
        mime_type = mime_type or 'application/octet-stream'
        filename = os.path.basename(ticket.attachment.name)
        disposition_type = 'attachment' if request.query_params.get('download') == '1' else 'inline'

        response = FileResponse(file_handle, content_type=mime_type)
        response['Content-Disposition'] = f'{disposition_type}; filename="{filename}"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'
        return response


class GrievanceResponseAttachmentView(GrievanceBaseAPIView):
    """
    GET: Securely stream grievance response attachment with strict authorization.
    Internal note attachments are restricted to administrative staff only.
    """
    authentication_classes = [GrievanceAttachmentAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request, id):
        try:
            resp = GrievanceResponse.objects.select_related(
                'ticket__user', 'ticket__assigned_to', 'ticket__target_ngo',
                'ticket__partnership__company', 'ticket__partnership__ngo'
            ).get(pk=id)
        except (GrievanceResponse.DoesNotExist, ValueError):
            raise GrievanceNotFoundError("Grievance response not found.")

        # If internal note, only staff/admin
        if resp.is_internal_note and not (getattr(request.user, 'is_staff', False) or getattr(request.user, 'role', None) == 'ADMIN'):
            raise exceptions.PermissionDenied(
                "You do not have permission to access this internal note attachment.",
                code="PERMISSION_DENIED"
            )

        if not user_has_ticket_attachment_access(request.user, resp.ticket):
            raise exceptions.PermissionDenied(
                "You do not have permission to access this grievance attachment.",
                code="PERMISSION_DENIED"
            )

        if not resp.attachment or not resp.attachment.name:
            return Response(
                {
                    "detail": "Attachment not found on this response.",
                    "code": "ATTACHMENT_NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if not resp.attachment.storage.exists(resp.attachment.name):
            return Response(
                {
                    "detail": "Attachment file is unavailable on server.",
                    "code": "ATTACHMENT_FILE_MISSING",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            file_handle = resp.attachment.open('rb')
        except Exception:
            return Response(
                {
                    "detail": "Unable to read attachment file from storage.",
                    "code": "ATTACHMENT_READ_ERROR",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        mime_type, _ = mimetypes.guess_type(resp.attachment.name)
        mime_type = mime_type or 'application/octet-stream'
        filename = os.path.basename(resp.attachment.name)
        disposition_type = 'attachment' if request.query_params.get('download') == '1' else 'inline'

        response = FileResponse(file_handle, content_type=mime_type)
        response['Content-Disposition'] = f'{disposition_type}; filename="{filename}"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'
        return response

