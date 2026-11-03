"""
CSR Services Package
====================
Exposes domain business services, exception classes, and audit mechanisms.
"""

from csr.services.exceptions import (
    CSRServiceError,
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
    CSRPermissionError,
)
from csr.services.audit_service import (
    record_verification_event,
    get_entity_audit_trail,
)
from csr.services.company_service import (
    register_company,
    get_company_for_user,
    update_company_profile,
    attach_company_document,
    request_company_verification,
    get_company_preferences,
    update_company_preferences,
)
from csr.services.requirement_service import (
    create_requirement,
    get_requirement_for_ngo,
    list_requirements_for_ngo,
    update_requirement,
    submit_requirement,
    withdraw_requirement,
    close_requirement,
)
from csr.services.partnership_service import (
    create_partnership_from_request,
    get_partnership,
    list_partnerships_for_user,
    activate_partnership,
    pause_partnership,
    resume_partnership,
    complete_partnership,
    cancel_partnership,
    record_off_platform_disbursement,
)
from csr.services.support_request_service import (
    create_support_request,
    get_support_request,
    list_inbox_for_ngo,
    list_outbox_for_company,
    withdraw_support_request,
    accept_support_request,
    reject_support_request,
)
from csr.services.milestone_service import (
    create_milestone,
    get_milestone,
    list_milestones,
    update_milestone,
    submit_evidence,
    review_milestone,
)
from csr.services.verification_service import (
    start_company_review,
    approve_company,
    reject_company,
    suspend_company,
    request_company_changes,
    start_requirement_review,
    approve_requirement,
    reject_requirement,
    suspend_requirement,
)

from csr.services.matching_service import (
    MatchResult,
    calculate_match_score,
    get_recommended_requirements_for_company,
)
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
    # Exceptions
    'CSRServiceError',
    'CSRValidationError',
    'CSRStateError',
    'CSROwnershipError',
    'CSRNotFoundError',
    'CSRConflictError',
    'CSRPermissionError',
    # Audit
    'record_verification_event',
    'get_entity_audit_trail',
    # Company Service
    'register_company',
    'get_company_for_user',
    'update_company_profile',
    'attach_company_document',
    'request_company_verification',
    'get_company_preferences',
    'update_company_preferences',
    # Requirement Service
    'create_requirement',
    'get_requirement_for_ngo',
    'list_requirements_for_ngo',
    'update_requirement',
    'submit_requirement',
    'withdraw_requirement',
    'close_requirement',
    # Partnership Service
    'create_partnership_from_request',
    'get_partnership',
    'list_partnerships_for_user',
    'activate_partnership',
    'pause_partnership',
    'resume_partnership',
    'complete_partnership',
    'cancel_partnership',
    'record_off_platform_disbursement',
    # Support Request Service
    'create_support_request',
    'get_support_request',
    'list_inbox_for_ngo',
    'list_outbox_for_company',
    'withdraw_support_request',
    'accept_support_request',
    'reject_support_request',
    # Milestone Service
    'create_milestone',
    'get_milestone',
    'list_milestones',
    'update_milestone',
    'submit_evidence',
    'review_milestone',
    # Verification Service
    'start_company_review',
    'approve_company',
    'reject_company',
    'suspend_company',
    'request_company_changes',
    'start_requirement_review',
    'approve_requirement',
    'reject_requirement',
    'suspend_requirement',
    # Matchmaking Engine
    'MatchResult',
    'calculate_match_score',
    'get_recommended_requirements_for_company',
    # Notifications
    'CSRNotificationEventType',
    'send_csr_email',
    'notify_support_request_created',
    'notify_support_request_status_changed',
    'notify_partnership_created',
    'notify_partnership_mou_uploaded',
    'notify_milestone_status_changed',
    'notify_verification_status_changed',
    'dispatch_csr_notification',
]
