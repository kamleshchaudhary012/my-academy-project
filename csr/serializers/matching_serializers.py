"""
CSR Matching Recommendation Serializer — Phase CSR-2.1
======================================================
DTO Serializer for validating and representing deterministic 0-100 match recommendation scores.
"""

from rest_framework import serializers
from django.utils.translation import gettext_lazy as _


class CSRMatchResultSerializer(serializers.Serializer):
    """
    Representation serializer for deterministic algorithmic match scores and explainability breakdowns.
    """
    requirement_id = serializers.UUIDField(
        required=True,
        help_text=_('UUID of the matched CSRRequirement proposal.'),
    )
    match_score = serializers.FloatField(
        required=True,
        min_value=0.0,
        max_value=100.0,
        help_text=_('Aggregate algorithmic compatibility score (0.0 to 100.0).'),
    )
    breakdown = serializers.DictField(
        required=True,
        help_text=_('Itemized component score breakdown.'),
    )
    reasons = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list,
        help_text=_('Human-readable explanations for match scoring.'),
    )

    def validate_breakdown(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(_('breakdown must be a dictionary of sub-scores.'))

        max_weights = {
            'category': 35.0,
            'location': 25.0,
            'budget': 20.0,
            'demographic': 10.0,
            'duration': 10.0,
        }

        for key, max_val in max_weights.items():
            if key in value:
                score = value[key]
                if not isinstance(score, (int, float)):
                    raise serializers.ValidationError(_(f"Sub-score '{key}' must be a numeric float or int."))
                if score < 0.0 or score > (max_val + 0.01):
                    raise serializers.ValidationError(
                        _(f"Sub-score '{key}' ({score}) must be between 0.0 and {max_val}.")
                    )

        return value
