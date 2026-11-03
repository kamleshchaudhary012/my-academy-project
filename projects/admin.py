from django.contrib import admin
from django.utils import timezone
from .models import (
    Project,
    ProjectStatus,
    ProjectDocument,
    ProjectMilestone,
    ProjectPhoto,
    ProjectVerificationHistory,
)
from .services import ProjectService


class ProjectDocumentInline(admin.TabularInline):
    model = ProjectDocument
    extra = 0
    readonly_fields = ['uploaded_by', 'uploaded_at']


class ProjectMilestoneInline(admin.TabularInline):
    model = ProjectMilestone
    extra = 0


class ProjectPhotoInline(admin.TabularInline):
    model = ProjectPhoto
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['title', 'organization', 'category', 'status', 'location_state', 'estimated_cost', 'created_at']
    list_filter = ['status', 'category', 'location_state', 'created_at']
    search_fields = ['title', 'description', 'organization__legal_name', 'organization__display_name', 'location_village', 'location_district']
    readonly_fields = ['id', 'created_at', 'updated_at', 'verified_at', 'funded_at', 'completed_at']
    inlines = [ProjectDocumentInline, ProjectMilestoneInline, ProjectPhotoInline]
    actions = ['add_to_verify', 'approve_and_verify', 'request_changes_selected', 'reject_selected']

    @admin.action(description="Add to Verify / Start Review (move to UNDER_REVIEW)")
    def add_to_verify(self, request, queryset):
        count = 0
        for project in queryset:
            if project.status == ProjectStatus.SUBMITTED:
                ProjectService.verify_project(
                    admin_user=request.user,
                    project_id=project.id,
                    action='ADD_TO_VERIFY',
                    notes='Project added to verification queue by administrator via Django Admin.'
                )
                count += 1
            else:
                self.message_user(
                    request,
                    f"Skipped '{project.title}': status is '{project.status}', must be 'SUBMITTED'.",
                    level='warning'
                )
        if count > 0:
            self.message_user(request, f"{count} project(s) moved to Under Review queue.")

    @admin.action(description="Approve & Verify for CSR (move to VERIFIED)")
    def approve_and_verify(self, request, queryset):
        count = 0
        for project in queryset:
            if project.status in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW]:
                ProjectService.verify_project(
                    admin_user=request.user,
                    project_id=project.id,
                    action='VERIFY',
                    notes='Project verified and approved for CSR partnerships by administrator via Django Admin.'
                )
                count += 1
        if count > 0:
            self.message_user(request, f"{count} project(s) approved and verified.")

    @admin.action(description="Request Changes / Documents (move to DOCS_PENDING)")
    def request_changes_selected(self, request, queryset):
        count = 0
        for project in queryset:
            if project.status in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW]:
                ProjectService.verify_project(
                    admin_user=request.user,
                    project_id=project.id,
                    action='REQUEST_CHANGES',
                    notes='Additional documents or revisions requested by administrator via Django Admin.'
                )
                count += 1
        if count > 0:
            self.message_user(request, f"{count} project(s) marked as DOCS_PENDING.")

    @admin.action(description="Reject Proposal (move to REJECTED)")
    def reject_selected(self, request, queryset):
        count = 0
        for project in queryset:
            ProjectService.verify_project(
                admin_user=request.user,
                project_id=project.id,
                action='REJECT',
                rejection_reason='Proposal rejected by administrator via Django Admin.'
            )
            count += 1
        if count > 0:
            self.message_user(request, f"{count} project(s) rejected.")

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            from_status = form.initial.get('status', '')
            super().save_model(request, obj, form, change)
            if obj.status == ProjectStatus.VERIFIED and not obj.verified_at:
                obj.verified_by = request.user
                obj.verified_at = timezone.now()
                obj.save(update_fields=['verified_by', 'verified_at'])
            ProjectVerificationHistory.objects.create(
                project=obj,
                action=f"ADMIN_SET_{obj.status}",
                from_status=from_status,
                to_status=obj.status,
                actor=request.user,
                actor_type=ProjectVerificationHistory.ActorType.ADMIN,
                notes=obj.verification_notes or f"Status changed from {from_status} to {obj.status} via Admin portal."
            )
        else:
            super().save_model(request, obj, form, change)


@admin.register(ProjectDocument)
class ProjectDocumentAdmin(admin.ModelAdmin):
    list_display = ['project', 'document_type', 'uploaded_by', 'uploaded_at']
    list_filter = ['document_type', 'uploaded_at']
    search_fields = ['project__title', 'notes']


@admin.register(ProjectMilestone)
class ProjectMilestoneAdmin(admin.ModelAdmin):
    list_display = ['project', 'order', 'title', 'amount', 'status', 'target_date']
    list_filter = ['status', 'target_date']
    search_fields = ['project__title', 'title']


@admin.register(ProjectVerificationHistory)
class ProjectVerificationHistoryAdmin(admin.ModelAdmin):
    list_display = ['project', 'action', 'from_status', 'to_status', 'actor', 'actor_type', 'created_at']
    list_filter = ['action', 'to_status', 'actor_type', 'created_at']
    search_fields = ['project__title', 'actor__email', 'notes']
    readonly_fields = ['id', 'project', 'action', 'from_status', 'to_status', 'actor', 'actor_type', 'notes', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
