"""
Grievance Ticketing Serializers — Phase 5.1
===========================================
Defines DRF serializers for grievance tickets and responses:
- GrievanceTicketSerializer (standard create + full read)
- GrievanceTicketListSerializer (lightweight list view)
- GrievanceTicketDetailSerializer (deep nested read view)
- GrievanceResponseSerializer (threaded response create + read)
- GrievanceResponseUpdateSerializer (restricted internal note update)
"""

import os
from django.contrib.auth import get_user_model
from rest_framework import serializers

from campaigns.models import Campaign, MonetaryDonation
from csr.models import CSRPartnership
from ngo.models import NGOProfile
from .models import (
    GrievanceCategory,
    GrievancePriority,
    GrievanceResponse,
    GrievanceStatus,
    GrievanceTicket,
)

User = get_user_model()

ALLOWED_ATTACHMENT_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024  # 5 MB


DANGEROUS_FILE_SIGNATURES = (
    b'MZ',           # Windows PE executable / DLL
    b'\x7fELF',      # Linux ELF executable
    b'<?php',        # PHP script
    b'<script',      # HTML/JS script
    b'#!/bin/',      # Unix shell script
    b'#!/usr/bin/',  # Unix shell script
)


def validate_attachment_file(value):
    """
    Validates uploaded file size, extension, and content for grievance tickets and responses.
    Max size: 5 MB. Allowed extensions: pdf, jpg, jpeg, png.
    Disallows executable or script files disguised with allowed extensions.
    """
    if value:
        if value.size > MAX_ATTACHMENT_SIZE:
            raise serializers.ValidationError("Attachment file size cannot exceed 5 MB.")
        ext = os.path.splitext(value.name)[1].lower().lstrip('.')
        if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
            allowed = ', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))
            raise serializers.ValidationError(
                f"Invalid file extension. Allowed extensions are: {allowed}."
            )

        if hasattr(value, 'read') and hasattr(value, 'seek'):
            try:
                pos = value.tell()
            except Exception:
                pos = 0
            value.seek(0)
            header = value.read(16)
            value.seek(pos)
            if any(header.startswith(sig) for sig in DANGEROUS_FILE_SIGNATURES):
                raise serializers.ValidationError(
                    "File contains executable or script content which is not permitted."
                )
    return value


class UserMinimalSerializer(serializers.ModelSerializer):
    """Minimal representation of a platform user."""

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name']
        read_only_fields = fields


class AssignedToMinimalSerializer(serializers.ModelSerializer):
    """Minimal representation of an assigned staff member."""

    class Meta:
        model = User
        fields = ['id', 'email']
        read_only_fields = fields


class GrievanceResponseSerializer(serializers.ModelSerializer):
    """
    Serializer for threaded responses and administrative notes on grievance tickets.
    """
    ticket = serializers.PrimaryKeyRelatedField(read_only=True)
    author = serializers.PrimaryKeyRelatedField(read_only=True)
    message = serializers.CharField(min_length=1, max_length=5000, allow_blank=False)
    attachment = serializers.FileField(required=False, allow_null=True, validators=[validate_attachment_file])
    attachment_url = serializers.SerializerMethodField()
    attachment_name = serializers.SerializerMethodField()
    attachment_available = serializers.SerializerMethodField()
    is_internal_note = serializers.BooleanField(default=False)

    class Meta:
        model = GrievanceResponse
        fields = [
            'id',
            'ticket',
            'author',
            'message',
            'attachment',
            'attachment_url',
            'attachment_name',
            'attachment_available',
            'is_internal_note',
            'created_at',
        ]
        read_only_fields = ['id', 'ticket', 'author', 'attachment_url', 'attachment_name', 'attachment_available', 'created_at']

    def get_attachment_url(self, obj):
        if not obj.attachment or not obj.attachment.name:
            return None
        request = self.context.get('request')
        endpoint = f"/api/v1/grievances/responses/{obj.id}/attachment/"
        if request:
            return request.build_absolute_uri(endpoint)
        return endpoint

    def get_attachment_name(self, obj):
        if not obj.attachment or not obj.attachment.name:
            return None
        return os.path.basename(obj.attachment.name)

    def get_attachment_available(self, obj):
        if not obj.attachment or not obj.attachment.name:
            return None
        try:
            return obj.attachment.storage.exists(obj.attachment.name)
        except Exception:
            return False

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.attachment and instance.attachment.name:
            data['attachment'] = data.get('attachment_url') or self.get_attachment_url(instance)
        return data

    def validate(self, attrs):
        attrs.pop('ticket', None)
        attrs.pop('author', None)
        return attrs


class GrievanceResponseUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an existing grievance response.
    Only `is_internal_note` is editable; other fields (like `message`) are ignored.
    """
    is_internal_note = serializers.BooleanField(required=True)

    class Meta:
        model = GrievanceResponse
        fields = ['is_internal_note']

    def to_internal_value(self, data):
        validated = super().to_internal_value(data)
        return {'is_internal_note': validated['is_internal_note']}


class GrievanceTicketSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and viewing grievance tickets.
    Enforces validation on title, description, category, priority, and attachments.
    Automatically strips client-supplied ticket_number, user, status, and assigned_to.
    """
    id = serializers.UUIDField(read_only=True)
    ticket_number = serializers.CharField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    title = serializers.CharField(min_length=5, max_length=200, allow_blank=False)
    description = serializers.CharField(min_length=10, allow_blank=False)
    category = serializers.ChoiceField(choices=GrievanceCategory.choices)
    priority = serializers.ChoiceField(choices=GrievancePriority.choices, default=GrievancePriority.MEDIUM)
    status = serializers.CharField(read_only=True)

    donation = serializers.PrimaryKeyRelatedField(
        queryset=MonetaryDonation.objects.all(),
        required=False,
        allow_null=True,
    )
    campaign = serializers.PrimaryKeyRelatedField(
        queryset=Campaign.objects.all(),
        required=False,
        allow_null=True,
    )
    partnership = serializers.PrimaryKeyRelatedField(
        queryset=CSRPartnership.objects.all(),
        required=False,
        allow_null=True,
    )
    target_ngo = serializers.PrimaryKeyRelatedField(
        queryset=NGOProfile.objects.all(),
        required=False,
        allow_null=True,
    )

    attachment = serializers.FileField(required=False, allow_null=True, validators=[validate_attachment_file])
    attachment_url = serializers.SerializerMethodField()
    attachment_name = serializers.SerializerMethodField()
    attachment_available = serializers.SerializerMethodField()
    assigned_to = serializers.PrimaryKeyRelatedField(read_only=True)
    resolution_summary = serializers.CharField(read_only=True)
    resolved_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = GrievanceTicket
        fields = [
            'id',
            'ticket_number',
            'user',
            'title',
            'description',
            'category',
            'priority',
            'status',
            'donation',
            'campaign',
            'partnership',
            'target_ngo',
            'attachment',
            'attachment_url',
            'attachment_name',
            'attachment_available',
            'assigned_to',
            'resolution_summary',
            'resolved_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'ticket_number',
            'user',
            'status',
            'attachment_url',
            'attachment_name',
            'attachment_available',
            'assigned_to',
            'resolution_summary',
            'resolved_at',
            'created_at',
            'updated_at',
        ]

    def get_attachment_url(self, obj):
        if not obj.attachment or not obj.attachment.name:
            return None
        request = self.context.get('request')
        endpoint = f"/api/v1/grievances/tickets/{obj.id}/attachment/"
        if request:
            return request.build_absolute_uri(endpoint)
        return endpoint

    def get_attachment_name(self, obj):
        if not obj.attachment or not obj.attachment.name:
            return None
        return os.path.basename(obj.attachment.name)

    def get_attachment_available(self, obj):
        if not obj.attachment or not obj.attachment.name:
            return None
        try:
            return obj.attachment.storage.exists(obj.attachment.name)
        except Exception:
            return False

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.attachment and instance.attachment.name:
            data['attachment'] = data.get('attachment_url') or self.get_attachment_url(instance)
        return data

    def validate(self, attrs):
        # Explicitly pop client-supplied read-only fields from validated data
        attrs.pop('ticket_number', None)
        attrs.pop('user', None)
        attrs.pop('status', None)
        attrs.pop('assigned_to', None)
        attrs.pop('resolution_summary', None)
        attrs.pop('resolved_at', None)
        return attrs


class GrievanceTicketListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing grievance tickets without heavy text/relation overhead.
    """

    class Meta:
        model = GrievanceTicket
        fields = [
            'id',
            'ticket_number',
            'title',
            'category',
            'priority',
            'status',
            'created_at',
        ]
        read_only_fields = fields


class GrievanceTicketDetailSerializer(GrievanceTicketSerializer):
    """
    Detailed serializer for viewing full ticket context with nested responses and user summaries.
    """
    responses = GrievanceResponseSerializer(many=True, read_only=True)
    user = UserMinimalSerializer(read_only=True)
    assigned_to = AssignedToMinimalSerializer(read_only=True, allow_null=True)

    class Meta(GrievanceTicketSerializer.Meta):
        fields = GrievanceTicketSerializer.Meta.fields + ['responses']
