"""
Grievance Service Exceptions — Phase 5.1
=========================================
Domain exceptions for grievance services, bridging Django and DRF exceptions
so callers and tests can use either without compatibility friction.
"""

import django.core.exceptions as dj_exc
import rest_framework.exceptions as rf_exc


class GrievanceServiceError(Exception):
    """Base exception for all grievance service operations."""

    def __init__(self, message: str = "A grievance service error occurred.", code: str = "grievance_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class GrievanceValidationError(rf_exc.ValidationError, dj_exc.ValidationError):
    """
    Validation error raised by grievance services.
    Inherits from both DRF and Django ValidationError for seamless exception catching.
    """

    def __init__(self, detail=None, code=None):
        self.code = code
        rf_exc.ValidationError.__init__(self, detail, code=code)
        dj_exc.ValidationError.__init__(self, detail, code=code)


class GrievancePermissionDenied(rf_exc.PermissionDenied, dj_exc.PermissionDenied):
    """
    Permission error raised when an unauthorized user attempts an operation or internal note.
    Inherits from both DRF and Django PermissionDenied.
    """

    def __init__(self, detail=None, code=None):
        self.code = code
        rf_exc.PermissionDenied.__init__(self, detail, code=code)
        dj_exc.PermissionDenied.__init__(self, detail)


class GrievanceNotFoundError(rf_exc.NotFound, dj_exc.ObjectDoesNotExist):
    """
    Raised when a requested grievance ticket or entity does not exist.
    """

    def __init__(self, detail="Ticket not found.", code="not_found"):
        self.code = code
        rf_exc.NotFound.__init__(self, detail, code=code)
        dj_exc.ObjectDoesNotExist.__init__(self, detail)
