"""
Unit Tests for CompanyCSRPreference Model
=========================================
Tests CompanyCSRPreference CRUD, OneToOne relationship, and callable JSON defaults.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from csr.models import (
    CompanyCSRPreference,
    ScheduleVIICategory,
    BeneficiaryDemographic,
)
from csr.tests.helpers import (
    make_company_profile,
    make_company_preference,
)


class CompanyCSRPreferenceModelTests(TestCase):
    """Test suite for CompanyCSRPreference model behavior and JSON isolation."""

    def setUp(self):
        self.company = make_company_profile()

    def test_create_valid_preference(self):
        """Creates a valid CompanyCSRPreference and verifies fields."""
        pref = CompanyCSRPreference.objects.create(
            company=self.company,
            preferred_categories=[
                ScheduleVIICategory.PROMOTING_EDUCATION,
                ScheduleVIICategory.ERADICATING_HUNGER,
            ],
            preferred_states=['Maharashtra', 'Gujarat'],
            preferred_districts=['Pune', 'Ahmedabad'],
            is_nationwide=False,
            has_no_location_pref=False,
            min_budget=Decimal('500000.00'),
            max_budget=Decimal('5000000.00'),
            preferred_duration_months=24,
            preferred_beneficiaries=[
                BeneficiaryDemographic.CHILDREN_EDUCATION,
                BeneficiaryDemographic.RURAL_COMMUNITIES,
            ],
        )
        self.assertEqual(pref.company, self.company)
        self.assertEqual(len(pref.preferred_categories), 2)
        self.assertEqual(pref.min_budget, Decimal('500000.00'))
        self.assertEqual(pref.max_budget, Decimal('5000000.00'))
        self.assertEqual(pref.preferred_duration_months, 24)
        self.assertIsNotNone(pref.created_at)
        self.assertIsNotNone(pref.updated_at)
        self.assertEqual(str(pref), f"CSR Preferences for {self.company.company_name}")

    def test_onetoone_uniqueness_with_company(self):
        """A company can have at most one CompanyCSRPreference object."""
        make_company_preference(company=self.company)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CompanyCSRPreference.objects.create(
                    company=self.company,
                    preferred_categories=[],
                )

    def test_callable_json_defaults_independent_instances(self):
        """
        CRITICAL TEST: Proves mutable JSON list defaults are independent across instances.
        Mutating one instance's JSON lists must NEVER affect another instance or the model default.
        """
        company2 = make_company_profile()
        pref1 = CompanyCSRPreference.objects.create(company=self.company)
        pref2 = CompanyCSRPreference.objects.create(company=company2)

        # Both start with empty lists
        self.assertEqual(pref1.preferred_categories, [])
        self.assertEqual(pref2.preferred_categories, [])
        self.assertEqual(pref1.preferred_states, [])
        self.assertEqual(pref2.preferred_states, [])

        # Mutate in memory and save pref1
        pref1.preferred_categories.append(ScheduleVIICategory.ERADICATING_HUNGER)
        pref1.preferred_states.append('Karnataka')
        pref1.preferred_districts.append('Bengaluru Urban')
        pref1.preferred_beneficiaries.append(BeneficiaryDemographic.WOMEN_EMPOWERMENT)
        pref1.save()

        # Reload pref2 from DB and check in-memory pref2
        pref2.refresh_from_db()
        self.assertEqual(pref2.preferred_categories, [])
        self.assertEqual(pref2.preferred_states, [])
        self.assertEqual(pref2.preferred_districts, [])
        self.assertEqual(pref2.preferred_beneficiaries, [])

        # Verify pref1 has its mutated values
        pref1.refresh_from_db()
        self.assertEqual(pref1.preferred_categories, [ScheduleVIICategory.ERADICATING_HUNGER])
        self.assertEqual(pref1.preferred_states, ['Karnataka'])

        # Create a third instance and verify it also gets fresh empty lists
        company3 = make_company_profile()
        pref3 = CompanyCSRPreference.objects.create(company=company3)
        self.assertEqual(pref3.preferred_categories, [])
        self.assertEqual(pref3.preferred_states, [])

    def test_full_clean_duration_months_minimum_one(self):
        """full_clean() enforces preferred_duration_months >= 1 when set."""
        pref = CompanyCSRPreference(
            company=self.company,
            preferred_duration_months=0,
        )
        with self.assertRaises(ValidationError) as ctx:
            pref.full_clean()
        self.assertIn('preferred_duration_months', ctx.exception.message_dict)

    def test_full_clean_negative_budgets_rejected(self):
        """full_clean() rejects negative min/max budget values."""
        pref = CompanyCSRPreference(
            company=self.company,
            min_budget=Decimal('-1.00'),
            max_budget=Decimal('-10.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            pref.full_clean()
        self.assertIn('min_budget', ctx.exception.message_dict)
        self.assertIn('max_budget', ctx.exception.message_dict)

    def test_cascade_deletion_on_company_deletion(self):
        """Deleting the parent CompanyProfile cascades to delete CompanyCSRPreference."""
        pref = make_company_preference(company=self.company)
        pref_id = pref.id
        self.company.delete()
        self.assertFalse(CompanyCSRPreference.objects.filter(id=pref_id).exists())
