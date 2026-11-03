"""
Unit Tests for PartnershipMilestone Model
=========================================
Tests PartnershipMilestone creation, unique sequence constraints, CASCADE deletion, and evidence uploads.
"""

import shutil
import tempfile
import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from csr.models import (
    PartnershipMilestone,
    MilestoneStatus,
    milestone_evidence_doc_path,
)
from csr.tests.helpers import (
    make_user,
    make_csr_partnership,
    make_partnership_milestone,
    make_dummy_uploaded_file,
)

User = get_user_model()


class PartnershipMilestoneModelTests(TestCase):
    """Test suite for PartnershipMilestone model behavior."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.partnership = make_csr_partnership()

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_create_valid_milestone(self):
        """Creates a valid PartnershipMilestone and checks attributes."""
        today = date.today()
        milestone = PartnershipMilestone.objects.create(
            partnership=self.partnership,
            sequence_number=1,
            title='Phase 1: Initial Foundation',
            description='Site survey and groundwork completion.',
            target_completion_date=today + timedelta(days=30),
            status=MilestoneStatus.PENDING,
            completion_percentage=0,
        )
        self.assertIsInstance(milestone.id, uuid.UUID)
        self.assertEqual(milestone.partnership, self.partnership)
        self.assertEqual(milestone.sequence_number, 1)
        self.assertEqual(milestone.title, 'Phase 1: Initial Foundation')
        self.assertEqual(milestone.status, MilestoneStatus.PENDING)
        self.assertEqual(milestone.completion_percentage, 0)
        self.assertIsNotNone(milestone.created_at)
        self.assertIsNotNone(milestone.updated_at)
        self.assertEqual(str(milestone), f"Milestone #1: Phase 1: Initial Foundation ({MilestoneStatus.PENDING})")

    def test_unique_partnership_and_sequence_number_constraint(self):
        """
        CRITICAL TEST: Database constraint unique_partnership_milestone_sequence
        MUST prevent duplicate sequence_number for the same partnership.
        """
        make_partnership_milestone(partnership=self.partnership, sequence_number=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_partnership_milestone(partnership=self.partnership, sequence_number=1)

    def test_different_partnerships_can_have_same_sequence_number(self):
        """Distinct partnerships may independently have milestone sequence_number=1."""
        partnership2 = make_csr_partnership()
        m1 = make_partnership_milestone(partnership=self.partnership, sequence_number=1)
        m2 = make_partnership_milestone(partnership=partnership2, sequence_number=1)
        self.assertEqual(m1.sequence_number, 1)
        self.assertEqual(m2.sequence_number, 1)

    def test_milestone_ordering_by_sequence_number(self):
        """Milestones are naturally ordered by sequence_number."""
        today = date.today()
        m3 = make_partnership_milestone(partnership=self.partnership, sequence_number=3, target_completion_date=today + timedelta(days=90))
        m1 = make_partnership_milestone(partnership=self.partnership, sequence_number=1, target_completion_date=today + timedelta(days=30))
        m2 = make_partnership_milestone(partnership=self.partnership, sequence_number=2, target_completion_date=today + timedelta(days=60))

        milestones = list(PartnershipMilestone.objects.filter(partnership=self.partnership))
        self.assertEqual([m.sequence_number for m in milestones], [1, 2, 3])

    def test_cascade_deletion_when_partnership_deleted(self):
        """Deleting a parent CSRPartnership cascades to delete all its milestones."""
        m1 = make_partnership_milestone(partnership=self.partnership, sequence_number=1)
        m2 = make_partnership_milestone(partnership=self.partnership, sequence_number=2)
        m1_id = m1.id
        m2_id = m2.id

        self.partnership.delete()

        self.assertFalse(PartnershipMilestone.objects.filter(id=m1_id).exists())
        self.assertFalse(PartnershipMilestone.objects.filter(id=m2_id).exists())

    def test_verified_by_set_null_on_user_deletion(self):
        """Deleting the verifying user sets milestone.verified_by to NULL."""
        admin_user = make_user(role=User.Role.ADMIN)
        milestone = make_partnership_milestone(
            partnership=self.partnership,
            sequence_number=1,
            status=MilestoneStatus.VERIFIED,
            verified_by=admin_user,
        )
        self.assertEqual(milestone.verified_by, admin_user)
        admin_user.delete()
        milestone.refresh_from_db()
        self.assertIsNone(milestone.verified_by)

    def test_evidence_document_upload_and_path(self):
        """Milestone evidence document upload is isolated to private media directory."""
        with override_settings(MEDIA_ROOT=self.temp_media):
            milestone = make_partnership_milestone(partnership=self.partnership, sequence_number=1)
            evidence_file = make_dummy_uploaded_file(name='milestone_report.pdf')
            milestone.evidence_document = evidence_file
            milestone.save()

            self.assertTrue(milestone.evidence_document.name.startswith(f'csr_docs/milestones/{milestone.id}/'))
            self.assertTrue(milestone.evidence_document.name.endswith('.pdf'))

            # Test path generator function
            gen_path = milestone_evidence_doc_path(milestone, 'report.pdf')
            self.assertTrue(gen_path.startswith(f'csr_docs/milestones/{milestone.id}/'))

    def test_full_clean_completion_percentage_and_sequence(self):
        """full_clean() validates completion_percentage <= 100 and sequence_number >= 1."""
        today = date.today()
        # Test completion percentage > 100
        m_bad_pct = PartnershipMilestone(
            partnership=self.partnership,
            sequence_number=1,
            title='Bad Pct',
            description='Test',
            target_completion_date=today + timedelta(days=30),
            completion_percentage=101,  # Max is 100
        )
        with self.assertRaises(ValidationError) as ctx:
            m_bad_pct.full_clean()
        self.assertIn('completion_percentage', ctx.exception.message_dict)

        # Test sequence number < 1
        m_bad_seq = PartnershipMilestone(
            partnership=self.partnership,
            sequence_number=0,  # Min is 1
            title='Bad Seq',
            description='Test',
            target_completion_date=today + timedelta(days=30),
            completion_percentage=50,
        )
        with self.assertRaises(ValidationError) as ctx:
            m_bad_seq.full_clean()
        self.assertIn('sequence_number', ctx.exception.message_dict)
