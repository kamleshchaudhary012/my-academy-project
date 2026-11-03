"""
Grievance Service Layer — Phase 5.1
===================================
Encapsulates domain business logic for grievance ticket creation,
concurrency-safe assignment, status state machine transitions,
IDOR protection, and internal note filtering.
"""

from typing import Any, Dict, List, Optional
import logging
from django.db import models, transaction

logger = logging.getLogger(__name__)
from django.utils import timezone

from .exceptions import (
    GrievanceNotFoundError,
    GrievancePermissionDenied as PermissionDenied,
    GrievanceValidationError as ValidationError,
)
from .models import GrievanceResponse, GrievanceStatus, GrievanceTicket


class GrievanceService:
    """
    Core service class for managing platform grievances and disputes.
    All mutation methods are atomic and concurrency-safe.
    """

    VALID_TRANSITIONS = {
        GrievanceStatus.OPEN: {
            GrievanceStatus.IN_REVIEW,
            GrievanceStatus.CLOSED,
            GrievanceStatus.REJECTED,
        },
        GrievanceStatus.IN_REVIEW: {
            GrievanceStatus.RESOLVED,
            GrievanceStatus.CLOSED,
            GrievanceStatus.REJECTED,
        },
        GrievanceStatus.RESOLVED: {
            GrievanceStatus.CLOSED,
        },
        GrievanceStatus.CLOSED: set(),
        GrievanceStatus.REJECTED: set(),
    }

    @classmethod
    def create_ticket(cls, *, user, validated_data: Dict[str, Any]) -> GrievanceTicket:
        """
        Creates a new grievance ticket for a user.
        Forces status=OPEN and complainant=user, stripping client-injected fields.
        """
        data = dict(validated_data)
        data.pop('ticket_number', None)
        data.pop('user', None)
        data.pop('status', None)
        data.pop('assigned_to', None)
        data.pop('resolution_summary', None)
        data.pop('resolved_at', None)

        with transaction.atomic():
            ticket = GrievanceTicket(
                user=user,
                status=GrievanceStatus.OPEN,
                **data,
            )
            ticket.save()
            try:
                from grievances.notifications import notify_ticket_created
                notify_ticket_created(ticket)
            except Exception:
                logger.exception("notify_ticket_created failed for %s", ticket.ticket_number)
            return ticket

    @classmethod
    def create_response(
        cls,
        *,
        ticket: GrievanceTicket,
        author,
        validated_data: Dict[str, Any],
        is_admin: bool = False,
    ) -> GrievanceResponse:
        """
        Appends a response message or internal note to a ticket thread.
        Enforces IDOR guard (owner/assigned/staff only) and admin-only internal notes.
        """
        is_staff_or_admin = is_admin or getattr(author, 'is_staff', False)
        is_owner = ticket.user_id == getattr(author, 'id', None)
        is_assigned = ticket.assigned_to_id == getattr(author, 'id', None)

        if not (is_staff_or_admin or is_owner or is_assigned):
            raise PermissionDenied("You do not have permission to respond to this ticket.")

        if validated_data.get('is_internal_note') and not is_staff_or_admin:
            raise PermissionDenied("Only admins can post internal notes.")

        data = dict(validated_data)
        data.pop('ticket', None)
        data.pop('author', None)

        with transaction.atomic():
            response = GrievanceResponse(
                ticket=ticket,
                author=author,
                **data,
            )
            response.save()
            try:
                from grievances.notifications import notify_new_response, notify_internal_note
                if response.is_internal_note:
                    notify_internal_note(ticket, response)
                else:
                    notify_new_response(ticket, response)
            except Exception:
                logger.exception("response notification failed for %s", ticket.ticket_number)
            return response

    @classmethod
    def assign_ticket(
        cls,
        *,
        ticket: GrievanceTicket,
        assigned_to_user,
        performed_by,
    ) -> GrievanceTicket:
        """
        Assigns an administrative/support officer to investigate the ticket.
        Requires staff privileges and concurrency row lock.
        """
        if not performed_by.is_staff:
            raise PermissionDenied("Only staff members can assign tickets.")

        with transaction.atomic():
            locked_ticket = GrievanceTicket.objects.select_for_update().get(pk=ticket.pk)
            locked_ticket.assigned_to = assigned_to_user
            locked_ticket.save(update_fields=['assigned_to', 'updated_at'])
            ticket.assigned_to = assigned_to_user
            try:
                from grievances.notifications import notify_ticket_assigned
                notify_ticket_assigned(ticket, assigned_to_user)
            except Exception:
                logger.exception("assign notification failed for %s", ticket.ticket_number)
            return locked_ticket

    @classmethod
    def transition_status(
        cls,
        *,
        ticket: GrievanceTicket,
        new_status: str,
        performed_by,
        resolution_summary: str = '',
    ) -> GrievanceTicket:
        """
        Executes a controlled state machine transition with database locking.
        Valid transitions:
          OPEN -> IN_REVIEW, CLOSED, REJECTED
          IN_REVIEW -> RESOLVED, CLOSED, REJECTED
          RESOLVED -> CLOSED
          CLOSED / REJECTED -> terminal
        """
        if not getattr(performed_by, 'is_staff', False):
            raise PermissionDenied("Only staff members can transition ticket status.")

        with transaction.atomic():
            locked_ticket = GrievanceTicket.objects.select_for_update().get(pk=ticket.pk)
            old_status = locked_ticket.status
            allowed_next = cls.VALID_TRANSITIONS.get(locked_ticket.status, set())

            if new_status not in allowed_next:
                raise ValidationError(
                    f"Invalid status transition from {locked_ticket.status} to {new_status}.",
                    code="INVALID_STATUS_TRANSITION",
                )

            if new_status == GrievanceStatus.RESOLVED:
                summary = (resolution_summary or '').strip()
                if not summary:
                    raise ValidationError(
                        "Resolution summary is required when resolving a ticket.",
                        code="REQUIRED_RESOLUTION_SUMMARY",
                    )
                locked_ticket.resolution_summary = summary
                locked_ticket.resolved_at = timezone.now()

            elif new_status in (GrievanceStatus.CLOSED, GrievanceStatus.REJECTED):
                if not locked_ticket.resolved_at:
                    locked_ticket.resolved_at = timezone.now()
                if resolution_summary:
                    locked_ticket.resolution_summary = resolution_summary.strip()

            locked_ticket.status = new_status
            locked_ticket.save()

            ticket.status = locked_ticket.status
            ticket.resolved_at = locked_ticket.resolved_at
            ticket.resolution_summary = locked_ticket.resolution_summary
            
            try:
                from grievances.notifications import notify_status_changed
                notify_status_changed(ticket, old_status, new_status)
            except Exception:
                logger.exception("status notification failed for %s", ticket.ticket_number)
                
            return locked_ticket

    @classmethod
    def get_tickets_for_user(
        cls,
        *,
        user,
        filters: Optional[Dict[str, Any]] = None,
        is_admin: Optional[bool] = None,
    ) -> models.QuerySet:
        """
        Retrieves grievance tickets.
        - Staff / Admin: retrieves all platform grievance tickets.
        - Standard user (Donor, NGO, Company): retrieves only tickets belonging to user.
        Supports filtering by status, priority, and category.
        """
        is_staff_or_admin = is_admin if is_admin is not None else bool(
            user
            and getattr(user, 'is_authenticated', False)
            and getattr(user, 'is_active', False)
            and (getattr(user, 'is_staff', False) or getattr(user, 'role', None) == 'ADMIN')
        )

        if is_staff_or_admin:
            qs = GrievanceTicket.objects.all()
        else:
            qs = GrievanceTicket.objects.filter(user=user)

        qs = qs.select_related(
            'user',
            'assigned_to',
            'donation',
            'campaign',
            'partnership',
            'target_ngo',
        ).prefetch_related('responses').order_by('-created_at')

        if filters:
            if filters.get('status'):
                qs = qs.filter(status=filters['status'])
            if filters.get('priority'):
                qs = qs.filter(priority=filters['priority'])
            if filters.get('category'):
                qs = qs.filter(category=filters['category'])

        return qs

    @classmethod
    def get_ticket_detail(
        cls,
        *,
        user,
        ticket_id,
        is_admin: bool = False,
    ) -> GrievanceTicket:
        """
        Retrieves a single ticket with full details and responses.
        Enforces IDOR guard: non-admin users cannot access tickets created by others.
        """
        try:
            ticket = GrievanceTicket.objects.select_related(
                'user',
                'assigned_to',
                'donation',
                'campaign',
                'partnership',
                'target_ngo',
            ).prefetch_related('responses').get(pk=ticket_id)
        except GrievanceTicket.DoesNotExist:
            raise GrievanceNotFoundError("You do not have access to this ticket.")

        # IDOR GUARD
        if not is_admin and ticket.user_id != user.id:
            raise PermissionDenied("You do not have access to this ticket.")

        return ticket

    @staticmethod
    def filter_responses_for_user(
        ticket: GrievanceTicket,
        is_admin: bool,
    ) -> List[GrievanceResponse]:
        """
        Filters ticket responses based on caller authorization:
        - Admin: sees all messages including internal notes.
        - Non-admin: sees only public responses (is_internal_note=False).
        """
        all_responses = list(ticket.responses.all())
        if is_admin:
            return all_responses
        return [r for r in all_responses if not r.is_internal_note]
