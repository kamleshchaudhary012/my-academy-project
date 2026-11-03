"""
Unit Tests for CSRVerificationHistory Model (Audit Ledger)
==========================================================
Tests CSRVerificationHistory creation, audit integrity, callable dict default independence,
and SET_NULL behavior for reviewing administrators.
"""

import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase

from csr.models import (
    CSRVerificationHistory,
    CSRAuditEntityType,
)
from csr.tests.helpers import (
    make_user,
    make_verification_history,
)

User = get_user_model()


class CSRVerificationHistoryModelTests(TestCase):
    """Test suite for CSRVerificationHistory immutable audit ledger."""

    def setUp(self):
        self.admin_user = make_user(role=User.Role.ADMIN)

    def test_create_valid_verification_history(self):
        """Creates a valid audit ledger entry across entity types."""
        target_uuid = uuid.uuid4()
        history = CSRVerificationHistory.objects.create(
            entity_type=CSRAuditEntityType.COMPANY,
            entity_id=target_uuid,
            old_status='PENDING_VERIFICATION',
            new_status='APPROVED',
            reviewed_by=self.admin_user,
            review_notes='MCA CIN and PAN verified with official records.',
            metadata={'verified_fields': ['cin_number', 'pan_number'], 'risk_level': 'LOW'},
        )
        self.assertIsInstance(history.id, uuid.UUID)
        self.assertEqual(history.entity_type, CSRAuditEntityType.COMPANY)
        self.assertEqual(history.entity_id, target_uuid)
        self.assertEqual(history.old_status, 'PENDING_VERIFICATION')
        self.assertEqual(history.new_status, 'APPROVED')
        self.assertEqual(history.reviewed_by, self.admin_user)
        self.assertEqual(history.metadata['risk_level'], 'LOW')
        self.assertIsNotNone(history.created_at)
        self.assertIn(str(target_uuid), str(history))

    def test_callable_dict_default_independence(self):
        """
        CRITICAL TEST: Proves mutable dict default is independent across history instances.
        Mutating one instance's metadata must NEVER affect another instance.
        """
        h1 = CSRVerificationHistory.objects.create(
            entity_type=CSRAuditEntityType.REQUIREMENT,
            entity_id=uuid.uuid4(),
            new_status='APPROVED',
        )
        h2 = CSRVerificationHistory.objects.create(
            entity_type=CSRAuditEntityType.PARTNERSHIP,
            entity_id=uuid.uuid4(),
            new_status='ACTIVE',
        )

        self.assertEqual(h1.metadata, {})
        self.assertEqual(h2.metadata, {})

        h1.metadata['custom_flag'] = 'approved_by_board'
        h1.save()

        h2.refresh_from_db()
        self.assertEqual(h2.metadata, {})

        h1.refresh_from_db()
        self.assertEqual(h1.metadata, {'custom_flag': 'approved_by_board'})

        h3 = CSRVerificationHistory.objects.create(
            entity_type=CSRAuditEntityType.MILESTONE,
            entity_id=uuid.uuid4(),
            new_status='VERIFIED',
        )
        self.assertEqual(h3.metadata, {})

    def test_reviewed_by_set_null_on_admin_deletion(self):
        """Deleting the reviewing admin user sets reviewed_by to NULL in audit history."""
        history = make_verification_history(
            reviewed_by=self.admin_user,
        )
        self.assertEqual(history.reviewed_by, self.admin_user)
        self.admin_user.delete()
        history.refresh_from_db()
        self.assertIsNone(history.reviewed_by)

    def test_audit_all_entity_types_supported(self):
        """CSRVerificationHistory supports all 4 CSRAuditEntityType values."""
        for entity_type in CSRAuditEntityType.values:
            history = make_verification_history(
                entity_type=entity_type,
                entity_id=uuid.uuid4(),
            )
            self.assertEqual(history.entity_type, entity_type)
