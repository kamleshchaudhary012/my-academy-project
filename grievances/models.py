"""
Grievance Ticketing Models — Phase 5.1
=======================================
Implements database entities for platform grievances, complaint tracking,
cross-app entity disputes (donations, campaigns, CSR partnerships, NGOs),
and two-way threaded communication between users and platform inspectors/admins.
"""

import uuid
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class GrievanceCategory(models.TextChoices):
    DONATION_PAYMENT         = 'DONATION_PAYMENT', _('Donation & Payment')
    RECEIPT_80G              = 'RECEIPT_80G', _('80G Tax Receipt')
    CAMPAIGN_FRAUD           = 'CAMPAIGN_FRAUD', _('Campaign Fraud / Misrepresentation')
    CSR_PARTNERSHIP_DISPUTE  = 'CSR_PARTNERSHIP_DISPUTE', _('CSR Partnership Dispute')
    NGO_CONDUCT              = 'NGO_CONDUCT', _('NGO Conduct & Compliance')
    TECHNICAL_SUPPORT        = 'TECHNICAL_SUPPORT', _('Technical Support')
    OTHER                    = 'OTHER', _('Other')


class GrievancePriority(models.TextChoices):
    LOW    = 'LOW', _('Low')
    MEDIUM = 'MEDIUM', _('Medium')
    HIGH   = 'HIGH', _('High')
    URGENT = 'URGENT', _('Urgent')


class GrievanceStatus(models.TextChoices):
    OPEN       = 'OPEN', _('Open')
    IN_REVIEW  = 'IN_REVIEW', _('In Review')
    RESOLVED   = 'RESOLVED', _('Resolved')
    CLOSED     = 'CLOSED', _('Closed')
    REJECTED   = 'REJECTED', _('Rejected')


class GrievanceTicket(models.Model):
    """
    Primary grievance ticket submitted by a platform user or raised regarding
    donations, campaigns, CSR partnerships, or NGO conduct.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text=_('Unique UUID primary key for the grievance ticket.'),
    )
    ticket_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text=_('Human-readable ticket identifier (e.g. GRV-202609-00001).'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='grievance_tickets',
        help_text=_('User who submitted the grievance ticket.'),
    )
    title = models.CharField(
        max_length=200,
        help_text=_('Brief summary title of the grievance.'),
    )
    description = models.TextField(
        help_text=_('Comprehensive description of the issue or inquiry.'),
    )
    category = models.CharField(
        max_length=32,
        choices=GrievanceCategory.choices,
        help_text=_('Categorization domain for triage and routing.'),
    )
    priority = models.CharField(
        max_length=16,
        choices=GrievancePriority.choices,
        default=GrievancePriority.MEDIUM,
        db_index=True,
        help_text=_('Severity priority level.'),
    )
    status = models.CharField(
        max_length=16,
        choices=GrievanceStatus.choices,
        default=GrievanceStatus.OPEN,
        db_index=True,
        help_text=_('Lifecycle moderation status.'),
    )

    # Optional cross-app references
    donation = models.ForeignKey(
        'campaigns.MonetaryDonation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='grievance_tickets',
        help_text=_('Associated monetary donation record, if applicable.'),
    )
    campaign = models.ForeignKey(
        'campaigns.Campaign',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='grievance_tickets',
        help_text=_('Targeted campaign project, if applicable.'),
    )
    partnership = models.ForeignKey(
        'csr.CSRPartnership',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='grievance_tickets',
        help_text=_('Targeted CSR bilateral partnership, if applicable.'),
    )
    target_ngo = models.ForeignKey(
        'ngo.NGOProfile',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='grievance_tickets',
        help_text=_('Targeted NGO profile under report or dispute, if applicable.'),
    )

    # Support & administrative resolution fields
    attachment = models.FileField(
        upload_to='grievance_attachments/',
        null=True,
        blank=True,
        help_text=_('Supporting document or evidence screenshot.'),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='assigned_grievance_tickets',
        null=True,
        blank=True,
        help_text=_('Platform administrative officer assigned to investigate.'),
    )
    resolution_summary = models.TextField(
        blank=True,
        default='',
        help_text=_('Administrative notes or resolution findings upon closing.'),
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_('Timestamp when the ticket was marked resolved or closed.'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text=_('Timestamp when the ticket was created.'),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text=_('Timestamp when the ticket was last updated.'),
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'priority', 'created_at'], name='grv_stat_prio_created_idx'),
            models.Index(fields=['user', 'status'], name='grv_user_stat_idx'),
        ]
        verbose_name = _('Grievance Ticket')
        verbose_name_plural = _('Grievance Tickets')

    def __str__(self):
        return f"{self.ticket_number} - {self.title}"

    def save(self, *args, **kwargs):
        """
        Auto-generates sequential, human-readable ticket numbers (GRV-YYYYMM-XXXXX)
        under concurrency-safe database locks.
        """
        is_new = self._state.adding or not self.pk
        if is_new or not self.ticket_number:
            now_str = timezone.now().strftime('%Y%m')
            prefix = f"GRV-{now_str}-"
            with transaction.atomic():
                count = GrievanceTicket.objects.select_for_update().filter(
                    ticket_number__startswith=prefix
                ).count()
                candidate_number = f"{prefix}{(count + 1):05d}"
                # Handle sequence collision in case of previous row deletions
                while GrievanceTicket.objects.filter(ticket_number=candidate_number).exists():
                    count += 1
                    candidate_number = f"{prefix}{(count + 1):05d}"
                self.ticket_number = candidate_number

        super().save(*args, **kwargs)


class GrievanceResponse(models.Model):
    """
    Two-way threaded message or administrative internal note linked to a GrievanceTicket.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text=_('Unique UUID primary key for the grievance response.'),
    )
    ticket = models.ForeignKey(
        GrievanceTicket,
        on_delete=models.CASCADE,
        related_name='responses',
        help_text=_('Parent grievance ticket for this message thread.'),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='grievance_responses',
        help_text=_('Author of this response or note.'),
    )
    message = models.TextField(
        help_text=_('Response message body.'),
    )
    attachment = models.FileField(
        upload_to='grievance_responses/',
        null=True,
        blank=True,
        help_text=_('Optional file attachment associated with this reply.'),
    )
    is_internal_note = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_('If True, visible only to administrators/investigators; hidden from complainant.'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text=_('Timestamp when this response was recorded.'),
    )

    class Meta:
        ordering = ['created_at']
        verbose_name = _('Grievance Response')
        verbose_name_plural = _('Grievance Responses')

    def __str__(self):
        return f"Response on {self.ticket.ticket_number}"
