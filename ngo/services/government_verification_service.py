"""
DaanGives Government Identifier Verification Service
===================================================
Manages automated and manual government verification workflows for NGOs and CSR Companies.

Statutory Rules Enforced:
1. Government/API verification is an INITIAL validation step, never a final approval.
2. Passing a government check NEVER automatically changes status to APPROVED.
3. If no live third-party API credentials are configured in the environment, the status
   evaluates safely to MANUAL_VERIFICATION_REQUIRED.
4. All results, sources, timestamps, and safe match metadata are recorded with zero
   secret credentials or raw internal keys exposed.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional
from django.utils import timezone
from django.conf import settings

from ngo.models import NGOProfile, NGOVerification, GovCheckStatus
from csr.models import CompanyProfile, CompanyVerificationStatus


class GovernmentVerificationService:
    """
    Coordinates government identifier verification checks for NGOs and Companies.
    """

    @classmethod
    def run_ngo_government_verification(
        cls,
        ngo_profile: NGOProfile,
        mock_provider_result: Optional[Dict[str, Any]] = None,
    ) -> NGOVerification:
        """
        Executes initial government identifier verification for an NGO application.
        Identifiers checked: PAN, NGO Darpan ID, Form CSR-1 CRN (if claimed).
        """
        verification, _ = NGOVerification.objects.get_or_create(ngo=ngo_profile)
        now = timezone.now()

        # Check for test mock provider injection
        if mock_provider_result is not None:
            outcome = mock_provider_result.get('status', GovCheckStatus.GOVERNMENT_CHECK_PASSED)
            source = mock_provider_result.get('source', 'MOCK_GOV_GATEWAY')
            details = {
                'source': source,
                'checked_at': now.isoformat(),
                'outcome': outcome,
                'identifiers': mock_provider_result.get('identifiers', {}),
                'match_summary': mock_provider_result.get('match_summary', {}),
                'notes': mock_provider_result.get('notes', 'Simulated verification result in test suite.'),
            }
            verification.gov_check_status = outcome
            verification.gov_check_source = source
            verification.gov_check_details = details
            verification.gov_check_completed_at = now
            verification.save(update_fields=[
                'gov_check_status', 'gov_check_source', 'gov_check_details',
                'gov_check_completed_at', 'updated_at',
            ])
            return verification

        # Check for live environment credentials
        api_key = os.getenv('GOV_VERIFY_API_KEY') or os.getenv('MCA_VERIFY_API_KEY')
        provider_url = os.getenv('GOV_VERIFY_PROVIDER_URL')

        legal = getattr(ngo_profile, 'legal_info', None)
        submitted_identifiers = {
            'pan': getattr(legal, 'pan_number', '') if legal else '',
            'darpan_id': getattr(legal, 'darpan_id', '') if legal else '',
            'has_csr_1': getattr(legal, 'has_csr_1', False) if legal else False,
            'csr_registration_number': getattr(legal, 'csr_registration_number', '') if legal else '',
        }

        if not api_key or not provider_url:
            # Safe default when no live external API is configured
            verification.gov_check_status = GovCheckStatus.MANUAL_VERIFICATION_REQUIRED
            verification.gov_check_source = 'MANUAL_INSPECTION_PENDING'
            verification.gov_check_details = {
                'status': GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
                'reason': (
                    'No live government verification API credentials configured in environment. '
                    'Manual administrative inspection required for PAN, NGO Darpan, and MCA CRN.'
                ),
                'checked_at': now.isoformat(),
                'submitted_identifiers': submitted_identifiers,
            }
            verification.gov_check_completed_at = now
            verification.save(update_fields=[
                'gov_check_status', 'gov_check_source', 'gov_check_details',
                'gov_check_completed_at', 'updated_at',
            ])
            return verification

        # If live credentials exist (future expansion): execute authenticated call safely
        try:
            # Placeholder for secure external provider client call
            verification.gov_check_status = GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE
            verification.gov_check_source = 'EXTERNAL_GATEWAY'
            verification.gov_check_details = {
                'status': GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE,
                'reason': 'External gateway endpoint connection not yet initialized.',
                'checked_at': now.isoformat(),
            }
            verification.gov_check_completed_at = now
        except Exception as exc:
            verification.gov_check_status = GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE
            verification.gov_check_details = {
                'status': GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE,
                'error': 'Service temporarily unavailable.',
                'checked_at': now.isoformat(),
            }
            verification.gov_check_completed_at = now

        verification.save(update_fields=[
            'gov_check_status', 'gov_check_source', 'gov_check_details',
            'gov_check_completed_at', 'updated_at',
        ])
        return verification

    @classmethod
    def run_company_government_verification(
        cls,
        company_profile: CompanyProfile,
        mock_provider_result: Optional[Dict[str, Any]] = None,
    ) -> CompanyProfile:
        """
        Executes initial government identifier verification for a CSR Company profile.
        Identifiers checked: CIN Number, Corporate PAN.
        """
        now = timezone.now()

        # Check for test mock provider injection
        if mock_provider_result is not None:
            outcome = mock_provider_result.get('status', GovCheckStatus.GOVERNMENT_CHECK_PASSED)
            source = mock_provider_result.get('source', 'MOCK_MCA_GATEWAY')
            details = {
                'source': source,
                'checked_at': now.isoformat(),
                'outcome': outcome,
                'identifiers': mock_provider_result.get('identifiers', {}),
                'match_summary': mock_provider_result.get('match_summary', {}),
                'notes': mock_provider_result.get('notes', 'Simulated verification result in test suite.'),
            }
            company_profile.gov_check_status = outcome
            company_profile.gov_check_source = source
            company_profile.gov_check_details = details
            company_profile.gov_check_completed_at = now
            company_profile.save(update_fields=[
                'gov_check_status', 'gov_check_source', 'gov_check_details',
                'gov_check_completed_at', 'updated_at',
            ])
            return company_profile

        # Check for live environment credentials
        api_key = os.getenv('GOV_VERIFY_API_KEY') or os.getenv('MCA_VERIFY_API_KEY')
        provider_url = os.getenv('GOV_VERIFY_PROVIDER_URL')

        submitted_identifiers = {
            'cin_number': company_profile.cin_number or '',
            'pan_number': company_profile.pan_number or '',
            'company_name': company_profile.company_name or '',
        }

        if not api_key or not provider_url:
            company_profile.gov_check_status = GovCheckStatus.MANUAL_VERIFICATION_REQUIRED
            company_profile.gov_check_source = 'MANUAL_INSPECTION_PENDING'
            company_profile.gov_check_details = {
                'status': GovCheckStatus.MANUAL_VERIFICATION_REQUIRED,
                'reason': (
                    'No live MCA/ITD verification API credentials configured in environment. '
                    'Manual administrative inspection required for Corporate CIN and PAN.'
                ),
                'checked_at': now.isoformat(),
                'submitted_identifiers': submitted_identifiers,
            }
            company_profile.gov_check_completed_at = now
            company_profile.save(update_fields=[
                'gov_check_status', 'gov_check_source', 'gov_check_details',
                'gov_check_completed_at', 'updated_at',
            ])
            return company_profile

        company_profile.gov_check_status = GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE
        company_profile.gov_check_source = 'EXTERNAL_GATEWAY'
        company_profile.gov_check_details = {
            'status': GovCheckStatus.GOVERNMENT_SOURCE_UNAVAILABLE,
            'reason': 'External MCA gateway connection not yet initialized.',
            'checked_at': now.isoformat(),
        }
        company_profile.gov_check_completed_at = now
        company_profile.save(update_fields=[
            'gov_check_status', 'gov_check_source', 'gov_check_details',
            'gov_check_completed_at', 'updated_at',
        ])
        return company_profile
