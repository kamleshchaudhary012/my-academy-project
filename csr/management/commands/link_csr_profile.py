"""
Management Command: link_csr_profile
====================================
Creates or links a CompanyProfile for a specified user email address.
Safe, idempotent, and useful for initializing or repairing corporate accounts.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

from csr.models import (
    CompanyProfile,
    CompanyVerificationStatus,
    CompanyCSRPreference,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Creates or links a CompanyProfile for a given user email."

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            required=True,
            help="Email address of the corporate user.",
        )
        parser.add_argument(
            '--company-name',
            type=str,
            default="Test CSR Corporate Entity",
            help="Display name for the corporate entity.",
        )
        parser.add_argument(
            '--status',
            type=str,
            default="APPROVED",
            choices=["DRAFT", "PENDING_VERIFICATION", "APPROVED", "REJECTED", "SUSPENDED"],
            help="Verification status to assign (default: APPROVED).",
        )

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        company_name = options['company_name'].strip()
        status_choice = options['status'].upper()

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            self.stdout.write(self.style.WARNING(f"User with email '{email}' does not exist. Creating new COMPANY user."))
            user = User.objects.create_user(
                email=email,
                password="TempPassword123!",
                role=User.Role.COMPANY,
                is_active=True,
            )

        # Ensure user role is COMPANY
        if getattr(user, 'role', None) != User.Role.COMPANY:
            user.role = User.Role.COMPANY
            user.save(update_fields=['role'])
            self.stdout.write(self.style.SUCCESS(f"Updated role for user '{email}' to COMPANY."))

        with transaction.atomic():
            profile = CompanyProfile.objects.filter(user=user).first()
            if profile:
                # Idempotent update
                profile.company_name = company_name or profile.company_name
                profile.verification_status = getattr(CompanyVerificationStatus, status_choice, CompanyVerificationStatus.APPROVED)
                profile.save(update_fields=['company_name', 'verification_status', 'updated_at'])
                CompanyCSRPreference.objects.get_or_create(company=profile)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"CompanyProfile already linked for '{email}' (ID: {profile.id}). Updated name/status to '{status_choice}'."
                    )
                )
                return

            # Generate synthetic valid unique CIN / PAN for database constraints
            import random
            random_cin_num = random.randint(10000, 99999)
            random_pan_num = random.randint(1000, 9999)
            cin = f"L{random_cin_num}MH2020PLC123456"
            pan = f"ABCDE{random_pan_num}F"

            profile = CompanyProfile.objects.create(
                user=user,
                company_name=company_name,
                legal_name=company_name,
                cin_number=cin,
                pan_number=pan,
                contact_person_name="Corporate SPOC",
                contact_person_designation="CSR Lead",
                contact_email=email,
                contact_phone="+919876543210",
                registered_address="Corporate Towers, Financial District",
                city="Mumbai",
                state="Maharashtra",
                pincode="400001",
                verification_status=getattr(CompanyVerificationStatus, status_choice, CompanyVerificationStatus.APPROVED),
            )
            CompanyCSRPreference.objects.get_or_create(company=profile)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully created and linked CompanyProfile '{profile.company_name}' (ID: {profile.id}) to user '{email}'."
                )
            )
