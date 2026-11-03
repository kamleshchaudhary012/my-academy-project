import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

GRIEVANCE_NOTIFICATIONS_ENABLED = getattr(settings, 'GRIEVANCE_NOTIFICATIONS_ENABLED', True)

def _send_notification(subject, message, recipient_list):
    if not GRIEVANCE_NOTIFICATIONS_ENABLED:
        logger.debug("Notifications disabled. Skipping: %s", subject)
        return
    
    valid_recipients = [email for email in recipient_list if email]
    if not valid_recipients:
        logger.debug("No valid recipient emails. Skipping: %s", subject)
        return

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@daangives.local')
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=valid_recipients,
            fail_silently=True,
        )
        logger.info("Notification sent successfully: %s to %s", subject, valid_recipients)
    except Exception as e:
        logger.warning("Failed to send notification '%s': %s", subject, str(e))


def notify_ticket_created(ticket) -> None:
    subject = f"[Grievance] Ticket created - {ticket.ticket_number}"
    message = (
        f"Ticket Number: {ticket.ticket_number}\n"
        f"Title: {ticket.title}\n"
        f"Category: {ticket.category}\n"
        f"Priority: {ticket.priority}\n"
        f"Status: {ticket.status}\n"
    )
    _send_notification(subject, message, [ticket.user.email] if ticket.user else [])

def notify_ticket_assigned(ticket, assigned_to_user) -> None:
    subject = f"[Grievance] Ticket assigned - {ticket.ticket_number}"
    message = (
        f"Ticket Number: {ticket.ticket_number}\n"
        f"Title: {ticket.title}\n"
        f"Complainant Email: {ticket.user.email if ticket.user else 'Unknown'}\n"
    )
    _send_notification(subject, message, [assigned_to_user.email] if assigned_to_user else [])

def notify_status_changed(ticket, old_status, new_status) -> None:
    subject = f"[Grievance] Status updated - {ticket.ticket_number} ({new_status})"
    message = (
        f"Ticket Number: {ticket.ticket_number}\n"
        f"Title: {ticket.title}\n"
        f"Status changed from {old_status} to {new_status}.\n"
    )
    if getattr(ticket, 'resolution_summary', None):
        message += f"\nResolution Summary:\n{ticket.resolution_summary}\n"
    _send_notification(subject, message, [ticket.user.email] if ticket.user else [])

def notify_new_response(ticket, response) -> None:
    if getattr(response, 'is_internal_note', False):
        return
        
    subject = f"[Grievance] New reply - {ticket.ticket_number}"
    message = (
        f"Ticket Number: {ticket.ticket_number}\n"
        f"Title: {ticket.title}\n"
        f"\nNew Reply:\n{response.message[:200]}"
    )
    
    recipients = set()
    if ticket.user and ticket.user.email:
        recipients.add(ticket.user.email)
    if ticket.assigned_to and ticket.assigned_to.email:
        recipients.add(ticket.assigned_to.email)
        
    _send_notification(subject, message, list(recipients))

def notify_internal_note(ticket, response) -> None:
    if not getattr(response, 'is_internal_note', False):
        return
        
    subject = f"[Grievance] Internal note - {ticket.ticket_number}"
    message = (
        f"Ticket Number: {ticket.ticket_number}\n"
        f"Title: {ticket.title}\n"
        f"\nInternal Note:\n{response.message}"
    )
    
    _send_notification(subject, message, [ticket.assigned_to.email] if ticket.assigned_to else [])
