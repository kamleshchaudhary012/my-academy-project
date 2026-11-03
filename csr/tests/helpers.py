"""
CSR Test Helpers and Factory Functions
======================================
Shared factory methods for creating test entities across CSR unit tests.
Zero third-party test dependencies; uses pure Django ORM.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
import itertools

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from ngo.models import NGOProfile
from csr.models import (
    CompanyProfile,
    CompanyCSRPreference,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
    CSRVerificationHistory,
    CompanyVerificationStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
    CSRRequirementStatus,
    CSRSupportType,
    CSRSupportRequestStatus,
    CSRPartnershipStatus,
    MilestoneStatus,
    CSRAuditEntityType,
)

User = get_user_model()

_cin_counter = itertools.count(10000)
_seq_counter = itertools.count(1)


def generate_valid_cin():
    """Generates a strictly valid 21-character MCA standard CIN."""
    cnt = next(_cin_counter)
    part1 = f"{cnt:05d}"[:5]
    part2 = f"{cnt * 7:06d}"[:6]
    return f"L{part1}MH2020PLC{part2}"


def generate_valid_pan():
    """Generates a strictly valid 10-character Indian PAN."""
    cnt = next(_seq_counter)
    part = f"{cnt:04d}"[:4]
    return f"AABC{chr(65 + (cnt % 26))}{part}F"


def make_user(email=None, role=User.Role.COMPANY, **kwargs):
    """Creates a User instance with specified role."""
    email = email or f"user_{uuid.uuid4().hex[:8]}@example.com"
    defaults = {
        'is_active': True,
        'role': role,
    }
    defaults.update(kwargs)
    return User.objects.create_user(email=email, password='TestPassword123!', **defaults)


def make_ngo_profile(user=None, **kwargs):
    """Creates a minimal valid NGOProfile for testing."""
    if user is None:
        user = make_user(role=User.Role.NGO)
    defaults = {
        'legal_name': f'Test NGO Trust {uuid.uuid4().hex[:6]}',
        'display_name': 'Test NGO',
        'category': NGOProfile.Category.EDUCATION,
        'description': 'Test NGO description for CSR matching tests.',
        'year_established': 2015,
        'official_email': f'ngo_{uuid.uuid4().hex[:6]}@example.org',
        'official_phone': '+919876543210',
        'status': NGOProfile.Status.APPROVED,
        'is_active': True,
    }
    defaults.update(kwargs)
    ngo = NGOProfile.objects.create(user=user, **defaults)
    from ngo.models import NGOLegalInfo, NGOVerification
    NGOLegalInfo.objects.get_or_create(
        ngo=ngo,
        defaults={
            'organisation_type': 'TRUST',
            'registration_number': f'REG-{uuid.uuid4().hex[:8].upper()}',
            'darpan_id': f'GJ/2020/{uuid.uuid4().hex[:7]}',
            'pan_number': generate_valid_pan(),
            'has_12a': True,
            'twelve_a_number': '12A-TEST-123',
            'has_80g': True,
            'eighty_g_number': '80G-TEST-123',
            'has_csr_1': True,
            'csr_registration_number': f'CSR{uuid.uuid4().hex[:8].upper()}',
        }
    )
    NGOVerification.objects.get_or_create(
        ngo=ngo,
        defaults={
            'status': defaults.get('status', NGOProfile.Status.APPROVED),
            'is_csr_verified': (defaults.get('status') == NGOProfile.Status.APPROVED),
        }
    )
    return ngo


def make_company_profile(user=None, **kwargs):
    """Creates a minimal valid CompanyProfile for testing."""
    if user is None:
        user = make_user(role=User.Role.COMPANY)
    defaults = {
        'company_name': f'Test Company {uuid.uuid4().hex[:6]}',
        'legal_name': 'Test Company Private Limited',
        'cin_number': generate_valid_cin(),
        'pan_number': generate_valid_pan(),
        'contact_person_name': 'Jane Doe',
        'contact_person_designation': 'CSR Head',
        'contact_email': f'csr_{uuid.uuid4().hex[:6]}@company.com',
        'contact_phone': '+919876543210',
        'registered_address': '123 Corporate Park, BKC',
        'city': 'Mumbai',
        'state': 'Maharashtra',
        'pincode': '400051',
        'annual_csr_budget': Decimal('5000000.00'),
        'verification_status': CompanyVerificationStatus.DRAFT,
    }
    defaults.update(kwargs)
    return CompanyProfile.objects.create(user=user, **defaults)


def make_company_preference(company=None, **kwargs):
    """Creates a CompanyCSRPreference linked to a CompanyProfile."""
    if company is None:
        company = make_company_profile()
    defaults = {
        'preferred_categories': [ScheduleVIICategory.PROMOTING_EDUCATION],
        'preferred_states': ['Maharashtra'],
        'preferred_districts': ['Mumbai Suburban'],
        'is_nationwide': False,
        'has_no_location_pref': False,
        'min_budget': Decimal('100000.00'),
        'max_budget': Decimal('1000000.00'),
        'preferred_duration_months': 12,
        'preferred_beneficiaries': [BeneficiaryDemographic.CHILDREN_EDUCATION],
    }
    defaults.update(kwargs)
    return CompanyCSRPreference.objects.create(company=company, **defaults)


def make_csr_requirement(ngo=None, created_by=None, **kwargs):
    """Creates a valid CSRRequirement."""
    if ngo is None:
        ngo = make_ngo_profile()
    if created_by is None:
        created_by = ngo.user
    today = date.today()
    defaults = {
        'title': f'CSR Initiative {uuid.uuid4().hex[:6]}',
        'slug': f'csr-initiative-{uuid.uuid4().hex[:8]}',
        'schedule_vii_category': ScheduleVIICategory.PROMOTING_EDUCATION,
        'state': 'Maharashtra',
        'district': 'Pune',
        'location_scope': LocationScope.SPECIFIC_DISTRICT,
        'additional_districts': [],
        'beneficiary_demographic': BeneficiaryDemographic.CHILDREN_EDUCATION,
        'target_beneficiary_count': 500,
        'summary': 'Providing quality educational infrastructure to rural schools.',
        'detailed_description': 'Detailed plan to install smart classrooms in 10 schools.',
        'expected_outcomes': '500 students benefit from digital learning tools.',
        'total_estimated_budget': Decimal('500000.00'),
        'required_csr_funding': Decimal('400000.00'),
        'committed_funding': Decimal('100000.00'),
        'start_date': today,
        'expected_completion_date': today + timedelta(days=180),
        'status': CSRRequirementStatus.DRAFT,
    }
    defaults.update(kwargs)
    return CSRRequirement.objects.create(ngo=ngo, created_by=created_by, **defaults)


def make_csr_support_request(company=None, requirement=None, **kwargs):
    """Creates a valid CSRSupportRequest."""
    if company is None:
        company = make_company_profile()
    if requirement is None:
        requirement = make_csr_requirement()
    defaults = {
        'company_name_snapshot': company.company_name,
        'spoc_name': 'Jane Doe',
        'spoc_email': 'jane.doe@company.com',
        'spoc_phone': '+919876543210',
        'proposed_funding': Decimal('200000.00'),
        'support_type': CSRSupportType.FINANCIAL_GRANT,
        'message': 'We are eager to partner on this education initiative.',
        'status': CSRSupportRequestStatus.PENDING_NGO_REVIEW,
    }
    defaults.update(kwargs)
    return CSRSupportRequest.objects.create(company=company, requirement=requirement, **defaults)


def make_csr_partnership(company=None, ngo=None, requirement=None, support_request=None, **kwargs):
    """Creates a valid CSRPartnership."""
    if company is None:
        company = make_company_profile()
    if ngo is None:
        ngo = make_ngo_profile()
    if requirement is None:
        requirement = make_csr_requirement(ngo=ngo)
    if support_request is None:
        support_request = make_csr_support_request(
            company=company,
            requirement=requirement,
            status=CSRSupportRequestStatus.ACCEPTED,
        )
    today = date.today()
    defaults = {
        'partnership_code': f'CSR-PART-{uuid.uuid4().hex[:8].upper()}',
        'agreed_funding_amount': Decimal('200000.00'),
        'disbursed_amount_reported': Decimal('0.00'),
        'execution_start_date': today,
        'target_completion_date': today + timedelta(days=180),
        'status': CSRPartnershipStatus.PENDING_MOU,
    }
    defaults.update(kwargs)
    return CSRPartnership.objects.create(
        company=company,
        ngo=ngo,
        requirement=requirement,
        support_request=support_request,
        **defaults,
    )


def make_partnership_milestone(partnership=None, sequence_number=1, **kwargs):
    """Creates a valid PartnershipMilestone."""
    if partnership is None:
        partnership = make_csr_partnership()
    today = date.today()
    defaults = {
        'title': f'Milestone {sequence_number}',
        'description': 'Deliverable milestone progress description.',
        'target_completion_date': today + timedelta(days=30 * sequence_number),
        'status': MilestoneStatus.PENDING,
        'completion_percentage': 0,
    }
    defaults.update(kwargs)
    return PartnershipMilestone.objects.create(
        partnership=partnership,
        sequence_number=sequence_number,
        **defaults,
    )


def make_verification_history(entity_type=CSRAuditEntityType.COMPANY, entity_id=None, **kwargs):
    """Creates a valid CSRVerificationHistory entry."""
    if entity_id is None:
        entity_id = uuid.uuid4()
    defaults = {
        'entity_type': entity_type,
        'entity_id': entity_id,
        'old_status': 'DRAFT',
        'new_status': 'APPROVED',
        'review_notes': 'Document verified and approved.',
        'metadata': {'reason': 'All compliance documents verified.'},
    }
    defaults.update(kwargs)
    return CSRVerificationHistory.objects.create(**defaults)


def make_dummy_uploaded_file(name='test_doc.pdf', content=b'%PDF-1.4 dummy pdf content', content_type='application/pdf'):
    """Generates a dummy in-memory file for upload tests."""
    return SimpleUploadedFile(name, content, content_type=content_type)
