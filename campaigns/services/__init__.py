"""
Campaign Services Module — Phase 5.2.2
=======================================
"""

from campaigns.services.exceptions import (
    CampaignServiceError,
    CampaignValidationError,
    CampaignStateError,
    CampaignOwnershipError,
    CampaignNotFoundError,
    CampaignConflictError,
    CampaignPermissionError,
)

from campaigns.services.milestone_service import (
    validate_ngo_campaign_access,
    get_milestone,
    list_milestones_for_campaign,
    create_milestone,
    update_milestone,
    transition_milestone_status,
)

from campaigns.services.distribution_proof_service import (
    get_distribution_proof,
    create_distribution_proof,
    start_proof_review,
    verify_distribution_proof,
    request_proof_revision,
    reject_distribution_proof,
    resubmit_distribution_proof,
)

__all__ = [
    'CampaignServiceError',
    'CampaignValidationError',
    'CampaignStateError',
    'CampaignOwnershipError',
    'CampaignNotFoundError',
    'CampaignConflictError',
    'CampaignPermissionError',
    'validate_ngo_campaign_access',
    'get_milestone',
    'list_milestones_for_campaign',
    'create_milestone',
    'update_milestone',
    'transition_milestone_status',
    'get_distribution_proof',
    'create_distribution_proof',
    'start_proof_review',
    'verify_distribution_proof',
    'request_proof_revision',
    'reject_distribution_proof',
    'resubmit_distribution_proof',
]
