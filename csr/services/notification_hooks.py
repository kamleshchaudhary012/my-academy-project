"""
CSR Notification Hooks — Phase CSR-2.7
=======================================
Public event notification hooks for the CSR Connect module.
Re-exports and wraps asynchronous event notification handlers from notification_service.py.
"""

from typing import Any, Dict, Optional

from csr.services.notification_service import (
    CSRNotificationEventType,
    send_csr_email,
    notify_support_request_created,
    notify_support_request_status_changed,
    notify_partnership_created,
    notify_partnership_mou_uploaded,
    notify_milestone_status_changed,
    notify_verification_status_changed,
    dispatch_csr_notification,
)

__all__ = [
    "CSRNotificationEventType",
    "send_csr_email",
    "notify_support_request_created",
    "notify_support_request_status_changed",
    "notify_partnership_created",
    "notify_partnership_mou_uploaded",
    "notify_milestone_status_changed",
    "notify_verification_status_changed",
    "dispatch_csr_notification",
]
