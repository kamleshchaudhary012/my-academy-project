"""
CSR Notification Service — Phase CSR-2.7
=========================================
Event-driven notification hooks and email dispatch infrastructure for the CSR Connect module.
Implements the frozen notification lifecycle events specified in CSR-2.0 Section 16.

Guarantees:
1. Strict failure safety: Notification failures NEVER raise exceptions to callers and NEVER roll back business operations.
2. Server-authoritative recipient resolution: Recipients are resolved strictly from verified User models in the database.
3. Privacy & compliance safety: Zero PAN numbers, bank details, filesystem paths, or JWTs are exposed in email payloads.
4. Clean portal paths: CTA links use authenticated internal platform routes (/company/csr/..., /ngo/csr/...).
5. Decoupled architecture: Zero dependencies on payments, donations, Razorpay, or tax modules.
"""

import logging
import uuid
from typing import Any, Dict, Optional, Union

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class CSRNotificationEventType:
    """Frozen CSR event types from CSR-2.0 Section 16 & Phase 6."""
    CSR_SUPPORT_REQUEST_SUBMITTED = "CSR_SUPPORT_REQUEST_SUBMITTED"
    CSR_SUPPORT_REQUEST_ACCEPTED = "CSR_SUPPORT_REQUEST_ACCEPTED"
    CSR_SUPPORT_REQUEST_REJECTED = "CSR_SUPPORT_REQUEST_REJECTED"
    CSR_PARTNERSHIP_MOU_UPLOADED = "CSR_PARTNERSHIP_MOU_UPLOADED"
    CSR_MILESTONE_EVIDENCE_SUBMITTED = "CSR_MILESTONE_EVIDENCE_SUBMITTED"
    CSR_MILESTONE_VERIFIED = "CSR_MILESTONE_VERIFIED"
    CSR_COMPANY_VERIFIED = "CSR_COMPANY_VERIFIED"
    CSR_COMPANY_REJECTED = "CSR_COMPANY_REJECTED"
    CSR_COMPANY_CHANGES_REQUESTED = "CSR_COMPANY_CHANGES_REQUESTED"
    CSR_REQUIREMENT_APPROVED = "CSR_REQUIREMENT_APPROVED"
    CSR_REQUIREMENT_REJECTED = "CSR_REQUIREMENT_REJECTED"
    CSR_REQUIREMENT_CHANGES_REQUESTED = "CSR_REQUIREMENT_CHANGES_REQUESTED"
    CSR_DISBURSEMENT_REPORTED = "CSR_DISBURSEMENT_REPORTED"
    CSR_DISBURSEMENT_ACKNOWLEDGED = "CSR_DISBURSEMENT_ACKNOWLEDGED"
    CSR_DISBURSEMENT_DISPUTED = "CSR_DISBURSEMENT_DISPUTED"
    CSR_DISBURSEMENT_VERIFIED = "CSR_DISBURSEMENT_VERIFIED"
    CSR_DISBURSEMENT_REJECTED = "CSR_DISBURSEMENT_REJECTED"


def send_csr_email(
    recipient_email: str,
    subject: str,
    template_base_name: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Renders and dispatches a multi-part (HTML + plain text) email safely.
    Catches all exceptions so email failures never disrupt business workflows.
    """
    if not recipient_email or not recipient_email.strip():
        logger.warning("CSR Notification skipped: Empty recipient email.")
        return {
            "success": False,
            "skipped": True,
            "reason": "Missing or empty recipient email address.",
        }

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "DaanGives CSR Connect <noreply@daangives.org>")

    try:
        html_template = f"emails/csr/{template_base_name}.html"
        txt_template = f"emails/csr/{template_base_name}.txt"

        html_body = render_to_string(html_template, context)
        text_body = render_to_string(txt_template, context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[recipient_email.strip()],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)

        logger.info(
            "CSR Notification dispatched successfully. Subject='%s', Recipient='%s'",
            subject,
            recipient_email,
        )
        return {
            "success": True,
            "recipient": recipient_email.strip(),
            "subject": subject,
            "template": template_base_name,
        }
    except Exception as exc:
        logger.error(
            "CSR Notification dispatch failed. Subject='%s', Recipient='%s', Error=%s",
            subject,
            recipient_email,
            str(exc),
            exc_info=True,
        )
        return {
            "success": False,
            "error": str(exc),
            "recipient": recipient_email.strip(),
            "subject": subject,
        }


# ==============================================================================
# Domain Notification Functions (CSR-2.0 Section 16)
# ==============================================================================

def notify_support_request_created(support_request: Any) -> Dict[str, Any]:
    """
    Event: CSR_SUPPORT_REQUEST_SUBMITTED
    Dispatched to the owning NGO's primary contact when an EOI/support request is created.
    """
    try:
        req = support_request.requirement
        ngo = req.ngo
        recipient_email = getattr(ngo.user, "email", "")
        recipient_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "") or getattr(ngo.user, "full_name", "") or "NGO Partner"
        company_name = getattr(support_request.company, "company_name", "Corporate Partner")

        context = {
            "recipient_name": recipient_name,
            "requirement_title": req.title,
            "company_name": company_name,
            "proposed_funding": f"₹{support_request.proposed_funding:,.2f}" if support_request.proposed_funding else "N/A",
            "request_id": str(support_request.id),
            "cta_url": f"/ngo/csr/requests/{support_request.id}",
        }
        subject = f"New CSR Support Request Received - {req.title}"
        return send_csr_email(recipient_email, subject, "support_request_submitted", context)
    except Exception as exc:
        logger.error("Error preparing support request creation notification: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_support_request_status_changed(
    support_request: Any,
    old_status: str,
    new_status: str,
) -> Dict[str, Any]:
    """
    Events: CSR_SUPPORT_REQUEST_ACCEPTED / CSR_SUPPORT_REQUEST_REJECTED
    Dispatched to the company CSR contact upon NGO review decision.
    """
    try:
        company = support_request.company
        recipient_email = getattr(company.user, "email", "")
        recipient_name = getattr(company.user, "full_name", "") or getattr(company, "company_name", "Corporate Partner")
        req = support_request.requirement
        ngo = req.ngo
        ngo_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "Non-Profit Partner")

        if new_status == "ACCEPTED":
            # Attempt to resolve partnership if created
            partnership_id = getattr(getattr(support_request, "partnership", None), "id", str(support_request.id))
            context = {
                "recipient_name": recipient_name,
                "requirement_title": req.title,
                "ngo_name": ngo_name,
                "agreed_funding": f"₹{support_request.proposed_funding:,.2f}" if support_request.proposed_funding else "N/A",
                "partnership_id": str(partnership_id),
                "cta_url": f"/company/csr/partnerships/{partnership_id}",
            }
            subject = f"CSR Support Request Accepted - {req.title}"
            return send_csr_email(recipient_email, subject, "support_request_accepted", context)

        elif new_status == "REJECTED":
            context = {
                "recipient_name": recipient_name,
                "requirement_title": req.title,
                "ngo_name": ngo_name,
                "rejection_reason": getattr(support_request, "rejection_reason", ""),
                "cta_url": "/company/csr/explore",
            }
            subject = f"Update on your CSR Support Request - {req.title}"
            return send_csr_email(recipient_email, subject, "support_request_rejected", context)

        return {"success": True, "skipped": True, "detail": f"No email action for status {new_status}"}
    except Exception as exc:
        logger.error("Error preparing support request status notification: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_partnership_created(partnership: Any) -> Dict[str, Any]:
    """
    Dispatched when a bilateral partnership is established.
    Notifies both the Company and the NGO.
    """
    results = {}
    try:
        company = partnership.company
        ngo = partnership.ngo
        req = getattr(partnership, "requirement", None)
        req_title = getattr(req, "title", "CSR Initiative")
        company_name = getattr(company, "company_name", "Corporate Partner")
        ngo_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "NGO Partner")

        # Notify Company
        comp_email = getattr(company.user, "email", "")
        comp_name = getattr(company.user, "full_name", "") or company_name
        funding_val = getattr(partnership, "agreed_funding_amount", getattr(partnership, "agreed_funding", None))
        funding_fmt = f"₹{funding_val:,.2f}" if funding_val is not None else "N/A"
        if comp_email:
            context_comp = {
                "recipient_name": comp_name,
                "requirement_title": req_title,
                "ngo_name": ngo_name,
                "agreed_funding": funding_fmt,
                "partnership_id": str(partnership.id),
                "cta_url": f"/company/csr/partnerships/{partnership.id}",
            }
            results["company"] = send_csr_email(comp_email, f"CSR Partnership Established - {req_title}", "support_request_accepted", context_comp)

        # Notify NGO
        ngo_email = getattr(ngo.user, "email", "")
        if ngo_email:
            context_ngo = {
                "recipient_name": ngo_name,
                "requirement_title": req_title,
                "company_name": company_name,
                "proposed_funding": funding_fmt,
                "request_id": str(partnership.id),
                "cta_url": f"/ngo/csr/partnerships/{partnership.id}",
            }
            results["ngo"] = send_csr_email(ngo_email, f"CSR Partnership Established - {req_title}", "support_request_submitted", context_ngo)

        return {"success": True, "results": results}
    except Exception as exc:
        logger.error("Error dispatching partnership creation notifications: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_partnership_mou_uploaded(partnership: Any) -> Dict[str, Any]:
    """
    Event: CSR_PARTNERSHIP_MOU_UPLOADED
    Dispatched to both Company and NGO when MoU document is uploaded/updated.
    """
    results = {}
    try:
        company = partnership.company
        ngo = partnership.ngo
        req = getattr(partnership, "requirement", None)
        req_title = getattr(req, "title", "CSR Initiative")
        company_name = getattr(company, "company_name", "Corporate Partner")
        ngo_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "NGO Partner")

        # Notify Company
        comp_email = getattr(company.user, "email", "")
        comp_name = getattr(company.user, "full_name", "") or company_name
        if comp_email:
            context_comp = {
                "recipient_name": comp_name,
                "requirement_title": req_title,
                "company_name": company_name,
                "ngo_name": ngo_name,
                "partnership_id": str(partnership.id),
                "cta_url": f"/company/csr/partnerships/{partnership.id}",
            }
            results["company"] = send_csr_email(comp_email, f"Partnership MoU Updated - {req_title}", "partnership_mou_uploaded", context_comp)

        # Notify NGO
        ngo_email = getattr(ngo.user, "email", "")
        if ngo_email:
            context_ngo = {
                "recipient_name": ngo_name,
                "requirement_title": req_title,
                "company_name": company_name,
                "ngo_name": ngo_name,
                "partnership_id": str(partnership.id),
                "cta_url": f"/ngo/csr/partnerships/{partnership.id}",
            }
            results["ngo"] = send_csr_email(ngo_email, f"Partnership MoU Updated - {req_title}", "partnership_mou_uploaded", context_ngo)

        return {"success": True, "results": results}
    except Exception as exc:
        logger.error("Error dispatching MoU upload notifications: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_milestone_status_changed(
    milestone: Any,
    old_status: str,
    new_status: str,
) -> Dict[str, Any]:
    """
    Events:
    - CSR_MILESTONE_EVIDENCE_SUBMITTED (to Company reviewer when evidence submitted)
    - CSR_MILESTONE_VERIFIED (to NGO project lead when verified)
    """
    try:
        partnership = milestone.partnership
        company = partnership.company
        ngo = partnership.ngo
        req = getattr(partnership, "requirement", None)
        req_title = getattr(req, "title", "CSR Project")
        company_name = getattr(company, "company_name", "Corporate Partner")
        ngo_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "NGO Partner")
        target_completion_date_str = str(getattr(milestone, "target_completion_date", "N/A"))
        completion_percentage = getattr(milestone, "completion_percentage", 0)

        if new_status in ("SUBMITTED", "UNDER_REVIEW"):
            # Evidence submitted -> notify Company reviewer
            comp_email = getattr(company.user, "email", "")
            comp_name = getattr(company.user, "full_name", "") or company_name
            context = {
                "recipient_name": comp_name,
                "milestone_title": milestone.title,
                "requirement_title": req_title,
                "ngo_name": ngo_name,
                "target_completion_date": target_completion_date_str,
                "completion_percentage": completion_percentage,
                "cta_url": f"/company/csr/partnerships/{partnership.id}/milestones/{milestone.id}",
            }
            subject = f"Milestone Evidence Ready for Verification - {milestone.title}"
            return send_csr_email(comp_email, subject, "milestone_evidence_submitted", context)

        elif new_status == "VERIFIED":
            # Milestone verified -> notify NGO project lead
            ngo_email = getattr(ngo.user, "email", "")
            context = {
                "recipient_name": ngo_name,
                "milestone_title": milestone.title,
                "requirement_title": req_title,
                "company_name": company_name,
                "completion_percentage": completion_percentage,
                "cta_url": f"/ngo/csr/partnerships/{partnership.id}/milestones/{milestone.id}",
            }
            subject = f"Milestone Successfully Verified - {milestone.title}"
            return send_csr_email(ngo_email, subject, "milestone_verified", context)

        return {"success": True, "skipped": True, "detail": f"No email action for milestone status {new_status}"}
    except Exception as exc:
        logger.error("Error dispatching milestone status notification: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_verification_status_changed(
    entity_type: str,
    entity_id: Any,
    status: str,
    admin_notes: str = "",
) -> Dict[str, Any]:
    """
    Events:
    - CSR_COMPANY_VERIFIED / REJECTED / CHANGES_REQUESTED
    - CSR_REQUIREMENT_APPROVED / REJECTED / CHANGES_REQUESTED
    """
    from csr.models import CompanyProfile, CSRRequirement

    try:
        normalized_type = str(entity_type).upper()

        if normalized_type in ("COMPANY", "COMPANYPROFILE"):
            company = CompanyProfile.objects.select_related("user").get(id=entity_id) if not isinstance(entity_id, CompanyProfile) else entity_id
            recipient_email = getattr(company.user, "email", "")
            recipient_name = getattr(company.user, "full_name", "") or getattr(company, "company_name", "Corporate Partner")

            context = {
                "recipient_name": recipient_name,
                "company_name": company.company_name,
                "status": status,
                "admin_notes": admin_notes,
                "cta_url": "/company/csr/dashboard",
            }
            subject = f"Company CSR Verification: {status}"
            return send_csr_email(recipient_email, subject, "company_verification_status", context)

        elif normalized_type in ("REQUIREMENT", "CSRREQUIREMENT"):
            req = CSRRequirement.objects.select_related("ngo", "ngo__user").get(id=entity_id) if not isinstance(entity_id, CSRRequirement) else entity_id
            recipient_email = getattr(req.ngo.user, "email", "")
            recipient_name = getattr(req.ngo, "display_name", "") or getattr(req.ngo, "legal_name", "NGO Partner")

            context = {
                "recipient_name": recipient_name,
                "requirement_title": req.title,
                "status": status,
                "admin_notes": admin_notes,
                "cta_url": f"/ngo/csr/requirements/{req.id}",
            }
            subject = f"CSR Requirement Review: {status} - {req.title}"
            return send_csr_email(recipient_email, subject, "requirement_verification_status", context)

        return {"success": False, "error": f"Unknown entity type: {entity_type}"}
    except Exception as exc:
        logger.error("Error dispatching verification status notification: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_disbursement_reported(disbursement: Any) -> Dict[str, Any]:
    """
    Event: CSR_DISBURSEMENT_REPORTED
    Notifies recipient NGO lead that a corporate bank transfer has been reported and requires credit confirmation.
    """
    try:
        partnership = disbursement.partnership
        ngo = partnership.ngo
        company = partnership.company
        req = getattr(partnership, "requirement", None)
        req_title = getattr(req, "title", "CSR Initiative")

        ngo_user = getattr(ngo, "user", None)
        recipient_email = getattr(ngo_user, "email", "")
        recipient_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "NGO Partner")

        context = {
            "recipient_name": recipient_name,
            "requirement_title": req_title,
            "company_name": getattr(company, "company_name", "Corporate Partner"),
            "amount_formatted": f"₹{disbursement.amount:,.2f}",
            "payment_mode": getattr(disbursement, "payment_mode", "Bank Transfer"),
            "disbursement_date": str(getattr(disbursement, "disbursement_date", "")),
            "cta_url": f"/ngo/csr/partnerships/{partnership.id}",
        }
        subject = f"Corporate Bank Transfer Reported - {req_title}"
        return send_csr_email(recipient_email, subject, "disbursement_reported", context)
    except Exception as exc:
        logger.error("Error dispatching disbursement reported notification: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_disbursement_acknowledged(disbursement: Any) -> Dict[str, Any]:
    """
    Event: CSR_DISBURSEMENT_ACKNOWLEDGED / CSR_DISBURSEMENT_DISPUTED
    Notifies corporate partner of the NGO's receipt confirmation or dispute.
    """
    try:
        partnership = disbursement.partnership
        company = partnership.company
        ngo = partnership.ngo
        req = getattr(partnership, "requirement", None)
        req_title = getattr(req, "title", "CSR Initiative")

        comp_user = getattr(company, "user", None)
        recipient_email = getattr(comp_user, "email", "")
        recipient_name = getattr(comp_user, "full_name", "") or getattr(company, "company_name", "Corporate Partner")

        ack_status = getattr(disbursement, "ngo_acknowledgement_status", "ACKNOWLEDGED")
        ack_notes = getattr(disbursement, "ngo_acknowledgement_notes", "")

        context = {
            "recipient_name": recipient_name,
            "requirement_title": req_title,
            "ngo_name": getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "NGO Partner"),
            "amount_formatted": f"₹{disbursement.amount:,.2f}",
            "acknowledgement_status": ack_status,
            "acknowledgement_notes": ack_notes,
            "cta_url": f"/company/csr/partnerships/{partnership.id}",
        }
        subject = f"NGO Receipt Update: {ack_status} - {req_title}"
        return send_csr_email(recipient_email, subject, "disbursement_acknowledged", context)
    except Exception as exc:
        logger.error("Error dispatching disbursement acknowledgement notification: %s", exc)
        return {"success": False, "error": str(exc)}


def notify_disbursement_reviewed(disbursement: Any) -> Dict[str, Any]:
    """
    Event: CSR_DISBURSEMENT_VERIFIED / CSR_DISBURSEMENT_REJECTED
    Notifies corporate partner and NGO of administrative evidence review decision.
    """
    results = {}
    try:
        partnership = disbursement.partnership
        company = partnership.company
        ngo = partnership.ngo
        req = getattr(partnership, "requirement", None)
        req_title = getattr(req, "title", "CSR Initiative")
        decision = getattr(disbursement, "review_status", "VERIFIED")
        review_notes = getattr(disbursement, "review_notes", "")

        # Notify Company
        comp_user = getattr(company, "user", None)
        comp_email = getattr(comp_user, "email", "")
        comp_name = getattr(comp_user, "full_name", "") or getattr(company, "company_name", "Corporate Partner")
        if comp_email:
            context_comp = {
                "recipient_name": comp_name,
                "requirement_title": req_title,
                "amount_formatted": f"₹{disbursement.amount:,.2f}",
                "review_decision": decision,
                "review_notes": review_notes,
                "cta_url": f"/company/csr/partnerships/{partnership.id}",
            }
            results["company"] = send_csr_email(comp_email, f"Transfer Evidence Review: {decision} - {req_title}", "disbursement_reviewed", context_comp)

        # Notify NGO
        ngo_user = getattr(ngo, "user", None)
        ngo_email = getattr(ngo_user, "email", "")
        ngo_name = getattr(ngo, "display_name", "") or getattr(ngo, "legal_name", "NGO Partner")
        if ngo_email:
            context_ngo = {
                "recipient_name": ngo_name,
                "requirement_title": req_title,
                "amount_formatted": f"₹{disbursement.amount:,.2f}",
                "review_decision": decision,
                "review_notes": review_notes,
                "cta_url": f"/ngo/csr/partnerships/{partnership.id}",
            }
            results["ngo"] = send_csr_email(ngo_email, f"Transfer Evidence Review: {decision} - {req_title}", "disbursement_reviewed", context_ngo)

        return {"success": True, "results": results}
    except Exception as exc:
        logger.error("Error dispatching disbursement review notification: %s", exc)
        return {"success": False, "error": str(exc)}


def dispatch_csr_notification(event_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generic event dispatcher for the frozen CSR event types from CSR-2.0 Section 16 & Phase 6.
    """
    event = str(event_type).upper()

    if event == CSRNotificationEventType.CSR_SUPPORT_REQUEST_SUBMITTED:
        req_obj = context.get("support_request")
        return notify_support_request_created(req_obj)

    elif event in (CSRNotificationEventType.CSR_SUPPORT_REQUEST_ACCEPTED, CSRNotificationEventType.CSR_SUPPORT_REQUEST_REJECTED):
        req_obj = context.get("support_request")
        old_status = context.get("old_status", "")
        new_status = "ACCEPTED" if event == CSRNotificationEventType.CSR_SUPPORT_REQUEST_ACCEPTED else "REJECTED"
        return notify_support_request_status_changed(req_obj, old_status, new_status)

    elif event == CSRNotificationEventType.CSR_PARTNERSHIP_MOU_UPLOADED:
        partnership = context.get("partnership")
        return notify_partnership_mou_uploaded(partnership)

    elif event == CSRNotificationEventType.CSR_MILESTONE_EVIDENCE_SUBMITTED:
        milestone = context.get("milestone")
        return notify_milestone_status_changed(milestone, context.get("old_status", "PENDING"), "SUBMITTED")

    elif event == CSRNotificationEventType.CSR_MILESTONE_VERIFIED:
        milestone = context.get("milestone")
        return notify_milestone_status_changed(milestone, context.get("old_status", "SUBMITTED"), "VERIFIED")

    elif event in (CSRNotificationEventType.CSR_COMPANY_VERIFIED, CSRNotificationEventType.CSR_COMPANY_REJECTED, CSRNotificationEventType.CSR_COMPANY_CHANGES_REQUESTED):
        entity_id = context.get("company_id") or context.get("company")
        status = context.get("status", "APPROVED" if event == CSRNotificationEventType.CSR_COMPANY_VERIFIED else "REJECTED")
        admin_notes = context.get("admin_notes", "")
        return notify_verification_status_changed("COMPANY", entity_id, status, admin_notes)

    elif event in (CSRNotificationEventType.CSR_REQUIREMENT_APPROVED, CSRNotificationEventType.CSR_REQUIREMENT_REJECTED, CSRNotificationEventType.CSR_REQUIREMENT_CHANGES_REQUESTED):
        entity_id = context.get("requirement_id") or context.get("requirement")
        status = context.get("status", "OPEN_FOR_CSR" if event == CSRNotificationEventType.CSR_REQUIREMENT_APPROVED else "REJECTED")
        admin_notes = context.get("admin_notes", "")
        return notify_verification_status_changed("REQUIREMENT", entity_id, status, admin_notes)

    elif event == CSRNotificationEventType.CSR_DISBURSEMENT_REPORTED:
        disbursement = context.get("disbursement")
        return notify_disbursement_reported(disbursement)

    elif event in (CSRNotificationEventType.CSR_DISBURSEMENT_ACKNOWLEDGED, CSRNotificationEventType.CSR_DISBURSEMENT_DISPUTED):
        disbursement = context.get("disbursement")
        return notify_disbursement_acknowledged(disbursement)

    elif event in (CSRNotificationEventType.CSR_DISBURSEMENT_VERIFIED, CSRNotificationEventType.CSR_DISBURSEMENT_REJECTED):
        disbursement = context.get("disbursement")
        return notify_disbursement_reviewed(disbursement)

    logger.warning("Unhandled CSR notification event: %s", event_type)
    return {"success": False, "error": f"Unhandled event type: {event_type}"}
