"""
CSR Exception Handler Helper
============================
Maps CSR domain service exceptions to standardized DRF HTTP responses.
Enforces DRF-standard error format:
  {"detail": "..."} for simple errors / state conflicts
  {"field": ["error"]} or details dict for validation errors
"""

from rest_framework import status
from rest_framework.response import Response

from csr.services.exceptions import (
    CSRServiceError,
    CSRValidationError,
    CSRStateError,
    CSROwnershipError,
    CSRNotFoundError,
    CSRConflictError,
    CSRPermissionError,
)


def handle_csr_service_error(exc: CSRServiceError) -> Response:
    """
    Maps a CSRServiceError instance to an appropriate DRF Response.
    """
    if isinstance(exc, CSRValidationError):
        if getattr(exc, 'details', None):
            return Response(exc.details, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)

    elif isinstance(exc, CSRNotFoundError):
        return Response({'detail': str(exc.message)}, status=status.HTTP_404_NOT_FOUND)

    elif isinstance(exc, (CSROwnershipError, CSRPermissionError)):
        return Response({'detail': str(exc.message) or 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

    elif isinstance(exc, (CSRConflictError, CSRStateError)):
        return Response({'detail': str(exc.message)}, status=status.HTTP_409_CONFLICT)

    return Response({'detail': str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)
