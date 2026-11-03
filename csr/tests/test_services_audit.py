"""
Unit Tests for CSR Audit Service — Phase CSR-2.5
================================================
Tests immutable audit ledger creation, entity filtering, and metadata storage.
"""

import uuid
from django.test import TestCase

from users.models import User
from csr.models import (
    CSRVerificationHistory,
    CSRAuditEntityType,
    CompanyVerificationStatus,
)
from csr.services.audit_service import (
    record_verification_event,
    get_entity_audit_trail,
)
from csr.services.exceptions import CSRValidationError
from csr.tests.helpers import make_user


class AuditServiceTests(TestCase):
    """Tests for CSRVerificationHistory audit ledger service."""

    def setUp(self):
        self.admin_user = make_user(email="admin_audit@example.com", role=User.Role.ADMIN)
        self.entity_id = uuid.uuid4()

    def test_record_verification_event_success(self):
        """Records an immutable audit entry with metadata."""
        entry = record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=self.entity_id,
            old_status=CompanyVerificationStatus.DRAFT,
            new_status=CompanyVerificationStatus.PENDING_VERIFICATION,
            actor_user=self.admin_user,
            review_notes="Initial audit check.",
            metadata={"source": "api_v1", "ip": "127.0.0.1"},
        )
        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.entity_type, CSRAuditEntityType.COMPANY)
        self.assertEqual(entry.entity_id, self.entity_id)
        self.assertEqual(entry.old_status, CompanyVerificationStatus.DRAFT)
        self.assertEqual(entry.new_status, CompanyVerificationStatus.PENDING_VERIFICATION)
        self.assertEqual(entry.reviewed_by, self.admin_user)
        self.assertEqual(entry.metadata.get("source"), "api_v1")

    def test_record_verification_event_validation_errors(self):
        """Invalid entity type or missing fields raises CSRValidationError."""
        with self.assertRaises(CSRValidationError):
            record_verification_event(
                entity_type="INVALID_TYPE",
                entity_id=self.entity_id,
                old_status=None,
                new_status="ACTIVE",
            )

        with self.assertRaises(CSRValidationError):
            record_verification_event(
                entity_type=CSRAuditEntityType.COMPANY,
                entity_id=None,
                old_status=None,
                new_status="ACTIVE",
            )

        with self.assertRaises(CSRValidationError):
            record_verification_event(
                entity_type=CSRAuditEntityType.COMPANY,
                entity_id=self.entity_id,
                old_status=None,
                new_status="",
            )

    def test_get_entity_audit_trail(self):
        """Retrieves chronological audit trail for a specific entity."""
        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=self.entity_id,
            old_status="DRAFT",
            new_status="PENDING_VERIFICATION",
            actor_user=self.admin_user,
        )
        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=self.entity_id,
            old_status="PENDING_VERIFICATION",
            new_status="APPROVED",
            actor_user=self.admin_user,
        )

        # Other entity
        other_id = uuid.uuid4()
        record_verification_event(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=other_id,
            old_status="DRAFT",
            new_status="REJECTED",
        )

        trail = get_entity_audit_trail(CSRAuditEntityType.COMPANY, self.entity_id)
        self.assertEqual(trail.count(), 2)
        statuses = [item.new_status for item in trail]
        self.assertEqual(statuses, ["APPROVED", "PENDING_VERIFICATION"])
