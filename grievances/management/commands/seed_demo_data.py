import logging
from django.core.management.base import BaseCommand
from django.db import transaction

from users.models import User
from ngo.models import NGOProfile
from csr.models import CompanyProfile
from grievances.models import GrievanceTicket, GrievanceResponse, GrievanceCategory, GrievancePriority, GrievanceStatus

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Seeds realistic demo data for the Grievance Module'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Wipe existing demo data before seeding')
        parser.add_argument('--empty', action='store_true', help='Wipe existing demo data and exit')

    def handle(self, *args, **options):
        reset = options['reset']
        empty = options['empty']

        if reset or empty:
            self.stdout.write("Wiping existing demo data...")
            self.wipe_demo_data()
            if empty:
                self.stdout.write(self.style.SUCCESS('Demo data wiped successfully. Exiting.'))
                return

        self.stdout.write("Seeding demo data...")
        self.seed_data()
        self.stdout.write(self.style.SUCCESS('Demo data seeded successfully.'))

    @transaction.atomic
    def wipe_demo_data(self):
        # Delete demo tickets
        demo_emails = [
            'donor1@demo.local', 'donor2@demo.local', 'donor3@demo.local',
            'ngo1@demo.local', 'ngo2@demo.local',
            'company1@demo.local', 'company2@demo.local',
            'admin1@demo.local', 'admin2@demo.local'
        ]
        users = User.objects.filter(email__in=demo_emails)
        GrievanceTicket.objects.filter(user__in=users).delete()
        NGOProfile.objects.filter(user__in=users).delete()
        CompanyProfile.objects.filter(user__in=users).delete()
        users.delete()

    @transaction.atomic
    def seed_data(self):
        password = 'Demo@12345'
        
        # 1. Create Staff
        admin1, _ = User.objects.get_or_create(email='admin1@demo.local', defaults={
            'full_name': 'Admin One', 'role': User.Role.ADMIN, 'is_staff': True
        })
        admin1.set_password(password)
        admin1.save()
        
        admin2, _ = User.objects.get_or_create(email='admin2@demo.local', defaults={
            'full_name': 'Admin Two', 'role': User.Role.ADMIN, 'is_staff': True
        })
        admin2.set_password(password)
        admin2.save()

        # 2. Create Donors
        donor1, _ = User.objects.get_or_create(email='donor1@demo.local', defaults={
            'full_name': 'Alice Donor', 'role': User.Role.DONOR
        })
        donor1.set_password(password)
        donor1.save()

        donor2, _ = User.objects.get_or_create(email='donor2@demo.local', defaults={
            'full_name': 'Bob Donor', 'role': User.Role.DONOR
        })
        donor2.set_password(password)
        donor2.save()

        donor3, _ = User.objects.get_or_create(email='donor3@demo.local', defaults={
            'full_name': 'Charlie Donor', 'role': User.Role.DONOR
        })
        donor3.set_password(password)
        donor3.save()

        # 3. Create NGOs
        ngo1, _ = User.objects.get_or_create(email='ngo1@demo.local', defaults={
            'full_name': 'Education Trust Contact', 'role': User.Role.NGO
        })
        ngo1.set_password(password)
        ngo1.save()
        NGOProfile.objects.get_or_create(user=ngo1, defaults={
            'legal_name': 'Education Trust', 'status': 'APPROVED', 'year_established': 2010, 'slug': 'education-trust'
        })

        ngo2, _ = User.objects.get_or_create(email='ngo2@demo.local', defaults={
            'full_name': 'Health Foundation Contact', 'role': User.Role.NGO
        })
        ngo2.set_password(password)
        ngo2.save()
        NGOProfile.objects.get_or_create(user=ngo2, defaults={
            'legal_name': 'Health Foundation', 'status': 'APPROVED', 'year_established': 2015, 'slug': 'health-foundation'
        })

        # 4. Create Companies
        comp1, _ = User.objects.get_or_create(email='company1@demo.local', defaults={
            'full_name': 'KK Ind Contact', 'role': User.Role.COMPANY
        })
        comp1.set_password(password)
        comp1.save()
        CompanyProfile.objects.get_or_create(user=comp1, defaults={
            'company_name': 'KK Industries Ltd', 'cin_number': 'L11111MH2023PTC111111', 'verification_status': 'APPROVED'
        })

        comp2, _ = User.objects.get_or_create(email='company2@demo.local', defaults={
            'full_name': 'ABC Corp Contact', 'role': User.Role.COMPANY
        })
        comp2.set_password(password)
        comp2.save()
        CompanyProfile.objects.get_or_create(user=comp2, defaults={
            'company_name': 'ABC Corp', 'cin_number': 'L22222MH2023PTC222222', 'verification_status': 'APPROVED'
        })

        # 5. Seed Tickets
        t1, _ = GrievanceTicket.objects.get_or_create(
            user=donor1, title='Payment Failed but Deducted',
            defaults={
                'description': 'I tried to donate $50 but it failed on the site. However my bank was charged.',
                'category': GrievanceCategory.DONATION_PAYMENT,
                'priority': GrievancePriority.HIGH,
                'status': GrievanceStatus.IN_REVIEW,
                'assigned_to': admin1
            }
        )
        
        t2, _ = GrievanceTicket.objects.get_or_create(
            user=donor2, title='Tax Receipt Missing',
            defaults={
                'description': 'It has been 2 weeks since my donation and I have not received an 80G receipt.',
                'category': GrievanceCategory.RECEIPT_80G,
                'priority': GrievancePriority.MEDIUM,
                'status': GrievanceStatus.OPEN,
            }
        )
        
        t3, _ = GrievanceTicket.objects.get_or_create(
            user=ngo1, title='Campaign Approval Delayed',
            defaults={
                'description': 'We submitted our school rebuilding campaign 5 days ago. No update yet.',
                'category': GrievanceCategory.OTHER,
                'priority': GrievancePriority.HIGH,
                'status': GrievanceStatus.RESOLVED,
                'assigned_to': admin2,
                'resolution_summary': 'Campaign reviewed and approved.'
            }
        )
        
        t4, _ = GrievanceTicket.objects.get_or_create(
            user=comp1, title='CSR Partnership Document Upload Issue',
            defaults={
                'description': 'The portal throws a 500 error when I upload our CSR MoU PDF.',
                'category': GrievanceCategory.TECHNICAL_SUPPORT,
                'priority': GrievancePriority.HIGH,
                'status': GrievanceStatus.OPEN,
            }
        )
        
        t5, _ = GrievanceTicket.objects.get_or_create(
            user=donor3, title='App crashed during login',
            defaults={
                'description': 'When I open the app on iOS 16, it crashes immediately.',
                'category': GrievanceCategory.TECHNICAL_SUPPORT,
                'priority': GrievancePriority.LOW,
                'status': GrievanceStatus.CLOSED,
                'assigned_to': admin1,
                'resolution_summary': 'Fixed in v2.1 update.'
            }
        )
        
        t6, _ = GrievanceTicket.objects.get_or_create(
            user=ngo2, title='Harassment by donor',
            defaults={
                'description': 'A donor has been using abusive language in the comments section of our campaign.',
                'category': GrievanceCategory.NGO_CONDUCT,
                'priority': GrievancePriority.URGENT,
                'status': GrievanceStatus.IN_REVIEW,
                'assigned_to': admin2
            }
        )
        
        t7, _ = GrievanceTicket.objects.get_or_create(
            user=comp2, title='Incorrect NGO matched',
            defaults={
                'description': 'Our CSR mandate specifies healthcare, but we were matched with an animal shelter.',
                'category': GrievanceCategory.OTHER,
                'priority': GrievancePriority.MEDIUM,
                'status': GrievanceStatus.REJECTED,
                'assigned_to': admin1,
                'resolution_summary': 'The animal shelter is registered under a mixed mandate.'
            }
        )
        
        t8, _ = GrievanceTicket.objects.get_or_create(
            user=donor1, title='Profile Update Bug',
            defaults={
                'description': 'Cannot save my new address in profile settings.',
                'category': GrievanceCategory.TECHNICAL_SUPPORT,
                'priority': GrievancePriority.LOW,
                'status': GrievanceStatus.OPEN,
            }
        )

        # 6. Seed Threaded Responses
        GrievanceResponse.objects.get_or_create(
            ticket=t1, author=admin1, message='We are looking into the payment gateway logs. Please share your transaction ID.'
        )
        GrievanceResponse.objects.get_or_create(
            ticket=t1, author=admin1, message='Payment gateway confirmed failure. Processing refund now.', is_internal_note=True
        )
        GrievanceResponse.objects.get_or_create(
            ticket=t1, author=donor1, message='My transaction ID is TXN998877.'
        )

        GrievanceResponse.objects.get_or_create(
            ticket=t3, author=admin2, message='Apologies for the delay. Your campaign has now been approved.'
        )

        GrievanceResponse.objects.get_or_create(
            ticket=t6, author=admin2, message='We take this very seriously. We will moderate the comments and warn the user.'
        )
        GrievanceResponse.objects.get_or_create(
            ticket=t6, author=admin2, message='User account suspended for 7 days.', is_internal_note=True
        )
