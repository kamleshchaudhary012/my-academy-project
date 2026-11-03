"""
Campaign Milestone & Distribution Proof Service Exceptions — Phase 5.2.2
========================================================================
Defines domain-specific business exceptions raised by campaign milestone
and field distribution proof services.
"""


class CampaignServiceError(Exception):
    """Base exception for all campaign milestone & proof service operations."""

    def __init__(self, message: str = "A campaign service error occurred.", code: str = "campaign_error", details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class CampaignValidationError(CampaignServiceError):
    """Raised when domain constraints or input validation fail."""

    def __init__(self, message: str = "Invalid input or constraint violation.", code: str = "validation_error", details=None):
        super().__init__(message, code=code, details=details)


class CampaignStateError(CampaignServiceError):
    """Raised when an invalid state transition is attempted on a milestone or proof."""

    def __init__(self, message: str = "Invalid status transition.", code: str = "invalid_state_transition", details=None):
        super().__init__(message, code=code, details=details)


class CampaignOwnershipError(CampaignServiceError):
    """Raised when caller does not own the campaign or NGO profile."""

    def __init__(self, message: str = "Caller does not own this campaign resource.", code: str = "ownership_denied", details=None):
        super().__init__(message, code=code, details=details)


class CampaignNotFoundError(CampaignServiceError):
    """Raised when a requested campaign, milestone, or proof is not found."""

    def __init__(self, message: str = "Resource not found or not visible.", code: str = "not_found", details=None):
        super().__init__(message, code=code, details=details)


class CampaignConflictError(CampaignServiceError):
    """Raised when a conflict (such as duplicate sequence number) occurs."""

    def __init__(self, message: str = "A conflicting resource already exists.", code: str = "conflict_error", details=None):
        super().__init__(message, code=code, details=details)


class CampaignPermissionError(CampaignServiceError):
    """Raised when an operation is forbidden due to role or unapproved status."""

    def __init__(self, message: str = "Permission denied for this campaign operation.", code: str = "permission_denied", details=None):
        super().__init__(message, code=code, details=details)
