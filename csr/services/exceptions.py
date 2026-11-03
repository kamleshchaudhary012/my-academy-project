"""
CSR Service Layer Exception Hierarchy
======================================
Defines domain-specific business exceptions raised by CSR services.
All exceptions derive from CSRServiceError.
"""


class CSRServiceError(Exception):
    """Base exception for all CSR service-layer business errors."""

    def __init__(self, message: str = "A CSR service error occurred.", code: str = "csr_error", details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class CSRValidationError(CSRServiceError):
    """Raised when business validation or numeric constraints are violated."""

    def __init__(self, message: str = "Invalid input or constraint violation.", code: str = "validation_error", details=None):
        super().__init__(message, code=code, details=details)


class CSRStateError(CSRServiceError):
    """Raised when an invalid state transition is attempted on a CSR domain entity."""

    def __init__(self, message: str = "Invalid status transition.", code: str = "invalid_state_transition", details=None):
        super().__init__(message, code=code, details=details)


class CSROwnershipError(CSRServiceError):
    """Raised when caller role is invalid or does not own the necessary profile/resource."""

    def __init__(self, message: str = "Caller does not have required role or profile ownership.", code: str = "ownership_error", details=None):
        super().__init__(message, code=code, details=details)


class CSRNotFoundError(CSRServiceError):
    """Raised when a requested resource does not exist or is not visible to the tenant."""

    def __init__(self, message: str = "Resource not found or not visible.", code: str = "not_found", details=None):
        super().__init__(message, code=code, details=details)


class CSRConflictError(CSRServiceError):
    """Raised when a conflict or duplicate active request occurs under concurrency."""

    def __init__(self, message: str = "A conflict or duplicate active entity exists.", code: str = "conflict_error", details=None):
        super().__init__(message, code=code, details=details)


class CSRPermissionError(CSRServiceError):
    """Raised when a business-level permission check fails."""

    def __init__(self, message: str = "Permission denied for this CSR business operation.", code: str = "permission_denied", details=None):
        super().__init__(message, code=code, details=details)


# Compatibility alias
CSRUnauthorizedError = CSRPermissionError

