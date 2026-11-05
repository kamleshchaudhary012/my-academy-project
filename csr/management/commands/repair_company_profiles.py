"""
Management Command: repair_company_profiles
==========================================
Auditable, safe, and idempotent repair tool for COMPANY accounts that lack an
associated CompanyProfile record (e.g. legacy registrations created prior to
integrated profile initialization).

Usage:
    python manage.py repair_company_profiles [--dry-run]
"""

import logging
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CompanyCSRPreference,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Safely and auditably creates missing DRAFT CompanyProfile records for users with role='COMPANY'."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulate the repair process without persisting any changes to the database.",
        )
        parser.add_argument(
            '--email',
            type=str,
            default=None,
            help="Target a specific company user email for repair.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        target_email = options['email']

        self.stdout.write(self.style.NOTICE(f"=== Starting Company Profile Audit & Repair (dry_run={dry_run}) ==="))

        qs = User.objects.filter(role=User.Role.COMPANY)
        if target_email:
            qs = qs.filter(email__iexact=target_email.strip())

        repaired_count = 0
        skipped_count = 0

        for user in qs.order_by('created_at'):
            has_profile = CompanyProfile.objects.filter(user=user).exists()
            if has_profile:
                skipped_count += 1
                continue

            self.stdout.write(
                self.style.WARNING(
                    f"[MISSING PROFILE DETECTED] User: {user.email} (ID: {user.id}, Registered: {user.created_at})"
                )
            )

            if dry_run:
                repaired_count += 1
                self.stdout.write(f"  -> [DRY-RUN] Would create DRAFT CompanyProfile for {user.email}")
                continue

            with transaction.atomic():
                company_name = user.full_name.strip() if user.full_name else user.email.split('@')[0]
                profile = CompanyProfile.objects.create(
                    user=user,
                    company_name=company_name,
                    legal_name=company_name,
                    cin_number=None,
                    pan_number='',
                    contact_person_name=user.full_name.strip() if user.full_name else 'Corporate Representative',
                    contact_person_designation='Corporate Representative',
                    contact_email=user.email,
                    contact_phone=user.phone or '',
                    registered_address='',
                    city='',
                    state='',
                    pincode='',
                    verification_status=CompanyVerificationStatus.DRAFT,
                )
                CompanyCSRPreference.objects.get_or_create(company=profile)

                repaired_count += 1
                msg = f"[AUDIT REPAIR] Created DRAFT CompanyProfile (ID: {profile.id}) for user {user.email} (ID: {user.id})"
                self.stdout.write(self.style.SUCCESS(f"  -> {msg}"))
                logger.info(msg)

        mode_str = "DRY-RUN SIMULATION" if dry_run else "LIVE EXECUTION"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== Audit Complete ({mode_str}) ===\n"
                f"  Profiles already healthy: {skipped_count}\n"
                f"  Missing profiles repaired: {repaired_count}\n"
            )
        )

