"""
CSR Verification History Serializer — Phase CSR-2.1
===================================================
Read-only audit ledger serializer for CSRVerificationHistory.
Ensures administrative decision tracking is immutable and non-writable via API.
"""

from rest_framework import serializers
from csr.models import CSRVerificationHistory


class CSRVerificationHistorySerializer(serializers.ModelSerializer):
    """
    Read-only serializer for CSRVerificationHistory audit records.
    Client mutations are completely blocked.
    """
    reviewed_by_name = serializers.CharField(source='reviewed_by.full_name', read_only=True, default=None)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True, default=None)
    entity_type_display = serializers.CharField(source='get_entity_type_display', read_only=True)

    class Meta:
        model = CSRVerificationHistory
        fields = [
            'id',
            'entity_type',
            'entity_type_display',
            'entity_id',
            'old_status',
            'new_status',
            'reviewed_by',
            'reviewed_by_name',
            'reviewed_by_email',
            'review_notes',
            'metadata',
            'created_at',
        ]
        read_only_fields = fields
