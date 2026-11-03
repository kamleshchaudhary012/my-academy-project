"""
DaanGives NGO Test Helpers
==========================
Shared helper functions for NGO test modules.
"""

import uuid
from users.models import User
from ngo.models import (
    NGOProfile,
    NGOLegalInfo,
    NGOBankInfo,
    NGOVerification,
)


def make_user(email=None, role='NGO', **kwargs):
    """Create a test user with the given role."""
    email = email or f'test_{uuid.uuid4().hex[:8]}@example.com'
    return User.objects.create_user(
        email=email,
        password='TestPass123!',
        role=role,
        **kwargs,
    )


def make_ngo_profile(user=None, **kwargs):
    """Create a minimal valid NGOProfile in DRAFT status."""
    user = user or make_user(role='NGO')
    defaults = dict(
        legal_name='Test Trust',
        display_name='Test NGO',
        category=NGOProfile.Category.EDUCATION,
        description='A' * 50,
        year_established=2010,
        official_email='contact@testngo.org',
        official_phone='+911234567890',
    )
    defaults.update(kwargs)
    profile = NGOProfile.objects.create(user=user, **defaults)
    # Create the required NGOVerification record if not exists
    NGOVerification.objects.get_or_create(ngo=profile)
    return profile


def make_legal_info(ngo, **kwargs):
    """Create a minimal valid NGOLegalInfo."""
    defaults = dict(
        organisation_type=NGOLegalInfo.OrgType.TRUST,
        registering_authority='Charity Commissioner, Gujarat',
        registration_number='E/12345/Ahmedabad',
        darpan_id=f'GJ/2010/{uuid.uuid4().hex[:5].upper()}',
        pan_number='AABCT1234D',
        registration_state='Gujarat',
        chief_trustee_name='John Doe',
        chief_trustee_designation='Managing Trustee',
    )
    defaults.update(kwargs)
    return NGOLegalInfo.objects.create(ngo=ngo, **defaults)


def make_bank_info(ngo, **kwargs):
    """Create valid NGOBankInfo."""
    defaults = dict(
        bank_name='State Bank of India',
        account_holder_name='Test Trust',
        account_number='123456789012',
        ifsc_code='SBIN0001234',
        account_type=NGOBankInfo.AccountType.SAVINGS,
    )
    defaults.update(kwargs)
    return NGOBankInfo.objects.create(ngo=ngo, **defaults)


def make_admin_user(email=None, **kwargs):
    """Create a test admin user."""
    return make_user(email=email, role='ADMIN', **kwargs)
