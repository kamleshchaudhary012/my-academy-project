from rest_framework import serializers
from .models import (
    Project,
    ProjectDocument,
    ProjectMilestone,
    ProjectPhoto,
    ProjectCategory,
    ProjectStatus,
    ProjectDocumentType,
    MilestoneStatus,
    ProjectVerificationHistory,
)


class ProjectDocumentSerializer(serializers.ModelSerializer):
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    uploaded_by_name = serializers.CharField(source='uploaded_by.full_name', read_only=True)

    class Meta:
        model = ProjectDocument
        fields = [
            'id',
            'project',
            'document_type',
            'document_type_display',
            'file',
            'notes',
            'uploaded_by',
            'uploaded_by_name',
            'uploaded_at',
        ]
        read_only_fields = ['id', 'project', 'uploaded_by', 'uploaded_at']


class ProjectMilestoneSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectMilestone
        fields = [
            'id',
            'project',
            'title',
            'description',
            'target_date',
            'order',
            'amount',
            'status',
            'status_display',
            'completed_at',
            'verified_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'project', 'created_at', 'updated_at']


class ProjectPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectPhoto
        fields = ['id', 'project', 'file', 'caption', 'uploaded_at']
        read_only_fields = ['id', 'project', 'uploaded_at']


class ProjectListSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    organization_name = serializers.CharField(source='organization.display_name', read_only=True)
    organization_darpan_id = serializers.SerializerMethodField()
    document_count = serializers.IntegerField(source='documents.count', read_only=True)
    milestone_count = serializers.IntegerField(source='milestones.count', read_only=True)
    is_csr_ready = serializers.BooleanField(read_only=True)

    class Meta:
        model = Project
        fields = [
            'id',
            'title',
            'short_summary',
            'category',
            'category_display',
            'location_state',
            'location_district',
            'location_village',
            'location_pincode',
            'beneficiaries_count',
            'estimated_cost',
            'timeline_months',
            'status',
            'status_display',
            'is_csr_ready',
            'organization_name',
            'organization_darpan_id',
            'document_count',
            'milestone_count',
            'created_at',
            'updated_at',
        ]

    def get_organization_darpan_id(self, obj):
        if hasattr(obj.organization, 'legal_info') and obj.organization.legal_info:
            return getattr(obj.organization.legal_info, 'darpan_id', '')
        return ''


class ProjectVerificationHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = ProjectVerificationHistory
        fields = [
            'id',
            'action',
            'from_status',
            'to_status',
            'actor_type',
            'actor_email',
            'notes',
            'created_at',
        ]
        read_only_fields = fields

    def get_actor_email(self, obj):
        if obj.actor_type == 'NGO' and obj.actor:
            return obj.actor.email
        elif obj.actor_type == 'ADMIN':
            return 'DaanGives Compliance Officer'
        return 'System'


class ProjectDetailSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    organization_name = serializers.CharField(source='organization.display_name', read_only=True)
    organization_darpan_id = serializers.SerializerMethodField()
    posted_by_name = serializers.CharField(source='posted_by.full_name', read_only=True)
    verified_by_name = serializers.CharField(source='verified_by.full_name', read_only=True)
    is_csr_ready = serializers.BooleanField(read_only=True)
    
    documents = ProjectDocumentSerializer(many=True, read_only=True)
    milestones = ProjectMilestoneSerializer(many=True, read_only=True)
    photos = ProjectPhotoSerializer(many=True, read_only=True)
    verification_history = ProjectVerificationHistorySerializer(many=True, read_only=True)
    funded_details = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id',
            'title',
            'short_summary',
            'description',
            'category',
            'category_display',
            'location_state',
            'location_district',
            'location_village',
            'location_pincode',
            'beneficiaries_count',
            'beneficiaries_description',
            'estimated_cost',
            'timeline_months',
            'status',
            'status_display',
            'is_csr_ready',
            'verification_notes',
            'rejection_reason',
            'posted_by',
            'posted_by_name',
            'organization',
            'organization_name',
            'organization_darpan_id',
            'verified_by',
            'verified_by_name',
            'verified_at',
            'funded_at',
            'completed_at',
            'documents',
            'milestones',
            'photos',
            'verification_history',
            'funded_details',
            'created_at',
            'updated_at',
        ]

    def get_organization_darpan_id(self, obj):
        if hasattr(obj.organization, 'legal_info') and obj.organization.legal_info:
            return getattr(obj.organization.legal_info, 'darpan_id', '')
        return ''

    def get_funded_details(self, obj):
        if obj.status in [ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS, ProjectStatus.COMPLETED]:
            try:
                from csr.models import CSRPartnership
                partnership = CSRPartnership.objects.filter(ngo=obj.organization).first()
                if partnership:
                    return {
                        'partnership_code': partnership.partnership_code,
                        'company_name': partnership.company.company_name,
                        'agreed_funding': str(partnership.agreed_funding_amount),
                        'disbursed_amount': str(partnership.disbursed_amount_reported),
                        'status': partnership.status,
                        'execution_start_date': str(partnership.execution_start_date) if partnership.execution_start_date else None,
                        'target_completion_date': str(partnership.target_completion_date) if partnership.target_completion_date else None,
                        'has_mou': bool(partnership.signed_mou_document),
                    }
            except Exception:
                pass
        return None


class MilestoneInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    target_date = serializers.DateField(required=False, allow_null=True, default=None)
    order = serializers.IntegerField(required=False, default=1)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0.00)


class ProjectCreateUpdateSerializer(serializers.ModelSerializer):
    milestones = MilestoneInputSerializer(many=True, required=False, default=list)

    class Meta:
        model = Project
        fields = [
            'title',
            'short_summary',
            'description',
            'category',
            'location_state',
            'location_district',
            'location_village',
            'location_pincode',
            'beneficiaries_count',
            'beneficiaries_description',
            'estimated_cost',
            'timeline_months',
            'milestones',
        ]

    def validate_estimated_cost(self, value):
        if value <= 0:
            raise serializers.ValidationError("Estimated project budget must be greater than zero.")
        return value

    def validate_timeline_months(self, value):
        if value <= 0:
            raise serializers.ValidationError("Project timeline must be at least 1 month.")
        return value

    def validate_title(self, value):
        if len(value.strip()) < 5:
            raise serializers.ValidationError("Project title must be at least 5 characters long.")
        return value.strip()


class ProjectVerificationSerializer(serializers.Serializer):
    action = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    rejection_reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_action(self, value):
        normalized = value.strip().upper().replace(' ', '_')
        allowed_actions = [
            'APPROVE', 'VERIFY',
            'REJECT',
            'REQUEST_CHANGES', 'DOCS_PENDING', 'REQUEST_DOCS',
            'START_REVIEW', 'UNDER_REVIEW',
            'ADD_TO_VERIFY', 'ADD_TO_QUEUE',
        ]
        if normalized not in allowed_actions:
            raise serializers.ValidationError(
                f"Action '{value}' is invalid. Allowed actions: {', '.join(allowed_actions)}"
            )
        return normalized
