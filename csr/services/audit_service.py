"""
CSR Audit Service
=================
Provides immutable, append-only ledger recording for administrative
and lifecycle state changes across CSR domain entities.
"""

from typing import Optional, Dict, Any
from django.contrib.auth import get_user_model
from django.db import transaction

from csr.models import CSRVerificationHistory, CSRAuditEntityType
from csr.services.exceptions import CSRValidationError

User = get_user_model()


def record_verification_event(
    entity_type: str,
    entity_id: Any,
    old_status: Optional[str],
    new_status: str,
    actor_user: Optional[Any] = None,
    review_notes: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> CSRVerificationHistory:
    """
    Append an immutable audit entry to CSRVerificationHistory.
    Must be called within an active transaction if part of a state transition.
    """
    if entity_type not in CSRAuditEntityType.values:
        raise CSRValidationError(
            f"Invalid audit entity type '{entity_type}'. Must be one of {CSRAuditEntityType.values}.",
            code="invalid_entity_type",
        )

    if not entity_id:
        raise CSRValidationError("entity_id is required for audit recording.", code="missing_entity_id")

    if not new_status:
        raise CSRValidationError("new_status is required for audit recording.", code="missing_new_status")

    # Ensure actor_user is a User instance or None
    actor = actor_user if (actor_user and getattr(actor_user, 'is_authenticated', False)) else None

    entry = CSRVerificationHistory.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        old_status=old_status,
        new_status=new_status,
        reviewed_by=actor,
        review_notes=review_notes or "",
        metadata=metadata or {},
    )
    return entry


def get_entity_audit_trail(entity_type: str, entity_id: Any):
    """
    Retrieve chronological audit ledger entries for a specific CSR entity.
    """
    if entity_type not in CSRAuditEntityType.values:
        raise CSRValidationError(
            f"Invalid audit entity type '{entity_type}'.",
            code="invalid_entity_type",
        )
    return CSRVerificationHistory.objects.filter(
        entity_type=entity_type,
        entity_id=entity_id,
    ).order_by('-created_at')
