import uuid
import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from ngo.models import NGOProfile
from campaigns.models import Campaign, CampaignMilestone

User = get_user_model()


class CampaignMilestoneModelTests(TestCase):
    """
    Exhaustive Model-Level Unit Tests for CampaignMilestone (Phase 5.2.1).
    """

    def setUp(self):
        # 1. NGO User & Profile
        self.ngo_user = User.objects.create_user(
            email='ngo_milestone_test@example.com',
            password='TestPassword123!',
            role='NGO',
            full_name='Milestone Test NGO',
            is_active=True,
        )
        self.ngo_profile = NGOProfile.objects.create(
            user=self.ngo_user,
            legal_name='Milestone Test Trust',
            display_name='Milestone Trust',
            category='EDUCATION',
            description='Test NGO for milestone model testing.',
            year_established=2019,
            status='APPROVED',
            is_active=True,
        )

        # 2. Campaign A (Target: 100,000)
        self.today = timezone.now().date()
        self.future = self.today + datetime.timedelta(days=60)
        self.campaign_a = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Clean Water Initiative Phase 1',
            short_description='Clean water for rural schools',
            description='Providing solar water purification plants to 5 primary schools.',
            slug='clean-water-initiative-phase-1',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('100000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

        # 3. Campaign B (For multi-campaign sequence isolation tests)
        self.campaign_b = Campaign.objects.create(
            ngo=self.ngo_profile,
            created_by=self.ngo_user,
            title='Winter Blankets Drive',
            short_description='Warm blankets for rural families',
            description='Distributing high quality thermal blankets to 400 rural families.',
            slug='winter-blankets-drive-milestone',
            campaign_type=Campaign.CampaignType.MONETARY,
            target_amount=Decimal('50000.00'),
            start_date=self.today,
            end_date=self.future,
            status=Campaign.Status.ACTIVE,
            is_active=True,
        )

    # 1. Create valid milestone
    def test_create_valid_milestone(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Procure Water Purification Units',
            description='Procure 5 solar filtration kits from authorized manufacturer.',
            target_amount=Decimal('40000.00'),
            target_completion_date=self.today + datetime.timedelta(days=15),
        )
        self.assertIsNotNone(milestone.pk)
        self.assertEqual(milestone.campaign, self.campaign_a)
        self.assertEqual(milestone.title, 'Procure Water Purification Units')
        self.assertEqual(milestone.sequence_number, 1)
        self.assertEqual(milestone.target_amount, Decimal('40000.00'))

    # 2. UUID generation
    def test_uuid_primary_key_generated(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Site Survey and Soil Testing',
            description='Field engineers inspect school grounds.',
            target_amount=Decimal('5000.00'),
            target_completion_date=self.today + datetime.timedelta(days=5),
        )
        self.assertIsInstance(milestone.id, uuid.UUID)
        self.assertTrue(len(str(milestone.id)) > 30)

    # 3. Default sequence_number is 1
    def test_default_sequence_number_is_one(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            title='Initial Planning Phase',
            description='Detailed logistical mapping.',
            target_amount=Decimal('10000.00'),
            target_completion_date=self.today + datetime.timedelta(days=7),
        )
        self.assertEqual(milestone.sequence_number, 1)

    # 4. Default status is PENDING
    def test_default_status_is_pending(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            title='Filter Unit Assembly',
            description='Assemble units on site.',
            target_amount=Decimal('15000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
        )
        self.assertEqual(milestone.status, CampaignMilestone.MilestoneStatus.PENDING)

    # 5. Target amount precision and positive value
    def test_target_amount_precision(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Pipeline Laying',
            description='Connect water filters to school distribution lines.',
            target_amount=Decimal('25450.75'),
            target_completion_date=self.today + datetime.timedelta(days=20),
        )
        milestone.refresh_from_db()
        self.assertEqual(milestone.target_amount, Decimal('25450.75'))

    # 6. Target amount can be zero
    def test_target_amount_zero_allowed(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Volunteer Community Orientation',
            description='Community meeting with zero budget allocation.',
            target_amount=Decimal('0.00'),
            target_completion_date=self.today + datetime.timedelta(days=3),
        )
        self.assertEqual(milestone.target_amount, Decimal('0.00'))
        milestone.full_clean()

    # 7. Negative target amount rejected
    def test_negative_target_amount_rejected(self):
        milestone = CampaignMilestone(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Invalid Negative Budget',
            description='Attempt to specify negative target.',
            target_amount=Decimal('-500.00'),
            target_completion_date=self.today + datetime.timedelta(days=5),
        )
        with self.assertRaises(ValidationError):
            milestone.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                milestone.save()

    # 8. Sequence >= 1 allowed
    def test_sequence_greater_than_or_equal_to_one(self):
        m1 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Milestone 1',
            description='First deliverable',
            target_amount=Decimal('1000.00'),
            target_completion_date=self.today + datetime.timedelta(days=5),
        )
        m2 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=2,
            title='Milestone 2',
            description='Second deliverable',
            target_amount=Decimal('2000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
        )
        self.assertEqual(m1.sequence_number, 1)
        self.assertEqual(m2.sequence_number, 2)

    # 9. Sequence 0 or negative rejected
    def test_sequence_zero_or_negative_rejected(self):
        milestone_zero = CampaignMilestone(
            campaign=self.campaign_a,
            sequence_number=0,
            title='Invalid Zero Sequence',
            description='Zero sequence deliverable',
            target_amount=Decimal('1000.00'),
            target_completion_date=self.today + datetime.timedelta(days=5),
        )
        with self.assertRaises(ValidationError):
            milestone_zero.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                milestone_zero.save()

    # 10. Duplicate sequence on same campaign rejected
    def test_duplicate_campaign_sequence_rejected(self):
        CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Original Milestone #1',
            description='First milestone',
            target_amount=Decimal('5000.00'),
            target_completion_date=self.today + datetime.timedelta(days=5),
        )
        dup = CampaignMilestone(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Duplicate Milestone #1',
            description='Duplicate sequence number on same campaign',
            target_amount=Decimal('6000.00'),
            target_completion_date=self.today + datetime.timedelta(days=8),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                dup.save()

    # 11. Different campaign with same sequence number allowed
    def test_different_campaign_same_sequence_allowed(self):
        m_a1 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Campaign A Milestone #1',
            description='First milestone of Campaign A',
            target_amount=Decimal('5000.00'),
            target_completion_date=self.today + datetime.timedelta(days=5),
        )
        m_b1 = CampaignMilestone.objects.create(
            campaign=self.campaign_b,
            sequence_number=1,
            title='Campaign B Milestone #1',
            description='First milestone of Campaign B',
            target_amount=Decimal('8000.00'),
            target_completion_date=self.today + datetime.timedelta(days=7),
        )
        self.assertEqual(m_a1.sequence_number, m_b1.sequence_number)
        self.assertNotEqual(m_a1.campaign, m_b1.campaign)

    # 12. actual_completion_date nullable and blank
    def test_actual_completion_date_nullable(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Uncompleted Milestone',
            description='Deliverable still pending execution.',
            target_amount=Decimal('10000.00'),
            target_completion_date=self.today + datetime.timedelta(days=30),
            actual_completion_date=None,
        )
        self.assertIsNone(milestone.actual_completion_date)

        # Set completion date upon verification
        milestone.actual_completion_date = self.today + datetime.timedelta(days=25)
        milestone.status = CampaignMilestone.MilestoneStatus.VERIFIED
        milestone.save()
        milestone.refresh_from_db()
        self.assertEqual(milestone.actual_completion_date, self.today + datetime.timedelta(days=25))
        self.assertEqual(milestone.status, CampaignMilestone.MilestoneStatus.VERIFIED)

    # 13. Reverse FK relationship
    def test_reverse_fk_relationship(self):
        m1 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Stage 1',
            description='First phase',
            target_amount=Decimal('10000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
        )
        m2 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=2,
            title='Stage 2',
            description='Second phase',
            target_amount=Decimal('20000.00'),
            target_completion_date=self.today + datetime.timedelta(days=20),
        )
        milestones = self.campaign_a.milestones.all()
        self.assertEqual(milestones.count(), 2)
        self.assertIn(m1, milestones)
        self.assertIn(m2, milestones)

    # 14. Campaign CASCADE deletion behavior
    def test_campaign_cascade_deletes_milestones(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Will Be Deleted on Cascade',
            description='Temporary milestone for cascade test.',
            target_amount=Decimal('5000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
        )
        milestone_id = milestone.id
        self.assertTrue(CampaignMilestone.objects.filter(id=milestone_id).exists())

        # Delete campaign
        self.campaign_a.delete()
        self.assertFalse(CampaignMilestone.objects.filter(id=milestone_id).exists())

    # 15. Ordering by campaign, sequence_number, created_at
    def test_milestone_ordering(self):
        m3 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=3,
            title='Stage 3 Final Inspection',
            description='Third deliverable',
            target_amount=Decimal('5000.00'),
            target_completion_date=self.today + datetime.timedelta(days=30),
        )
        m1 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Stage 1 Groundwork',
            description='First deliverable',
            target_amount=Decimal('10000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
        )
        m2 = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=2,
            title='Stage 2 Execution',
            description='Second deliverable',
            target_amount=Decimal('20000.00'),
            target_completion_date=self.today + datetime.timedelta(days=20),
        )
        ordered = list(CampaignMilestone.objects.filter(campaign=self.campaign_a))
        self.assertEqual(ordered, [m1, m2, m3])

    # 16. String representation
    def test_string_representation(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Water Tank Fabrication',
            description='Construct 5000L overhead water tank.',
            target_amount=Decimal('25000.00'),
            target_completion_date=self.today + datetime.timedelta(days=14),
        )
        expected = f"{self.campaign_a.title} — Milestone #1: Water Tank Fabrication (PENDING)"
        self.assertEqual(str(milestone), expected)

    # 17. Valid status transitions
    def test_all_milestone_status_choices_valid(self):
        milestone = CampaignMilestone.objects.create(
            campaign=self.campaign_a,
            sequence_number=1,
            title='Status Machine Check',
            description='Checking status lifecycle.',
            target_amount=Decimal('1000.00'),
            target_completion_date=self.today + datetime.timedelta(days=10),
        )
        for st in [
            CampaignMilestone.MilestoneStatus.PENDING,
            CampaignMilestone.MilestoneStatus.IN_PROGRESS,
            CampaignMilestone.MilestoneStatus.REVISION_REQUESTED,
            CampaignMilestone.MilestoneStatus.VERIFIED,
        ]:
            milestone.status = st
            milestone.save()
            milestone.refresh_from_db()
            self.assertEqual(milestone.status, st)
