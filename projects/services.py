import uuid
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404
from .models import (
    Project,
    ProjectDocument,
    ProjectMilestone,
    ProjectPhoto,
    ProjectStatus,
    ProjectCategory,
    ProjectVerificationHistory,
)
from ngo.models import NGOProfile


class ProjectService:
    @staticmethod
    def get_user_ngo_profile(user):
        """
        Retrieves the NGOProfile associated with the user.
        """
        try:
            return user.ngo_profile
        except (AttributeError, NGOProfile.DoesNotExist):
            profile = NGOProfile.objects.filter(user=user).first()
            if not profile:
                raise ValidationError("A registered Village / NGO profile is required to post development projects.")
            return profile

    @classmethod
    @transaction.atomic
    def create_draft(cls, user, validated_data):
        """
        Creates a new draft project for the village/NGO representative.
        """
        organization = cls.get_user_ngo_profile(user)
        
        milestones_data = validated_data.pop('milestones', [])
        
        project = Project.objects.create(
            posted_by=user,
            organization=organization,
            status=ProjectStatus.DRAFT,
            **validated_data
        )

        for idx, m_data in enumerate(milestones_data):
            order = m_data.get('order', idx + 1)
            ProjectMilestone.objects.create(
                project=project,
                order=order,
                title=m_data.get('title', f'Milestone {order}'),
                description=m_data.get('description', ''),
                target_date=m_data.get('target_date'),
                amount=m_data.get('amount', 0.00),
            )

        ProjectVerificationHistory.objects.create(
            project=project,
            action='CREATED',
            from_status='',
            to_status=ProjectStatus.DRAFT,
            actor=user,
            actor_type=ProjectVerificationHistory.ActorType.NGO,
            notes='Project draft created by NGO representative.',
        )

        return project

    @classmethod
    @transaction.atomic
    def update_project(cls, user, project_id, validated_data):
        """
        Updates an existing draft or docs-pending project.
        """
        project = get_object_or_404(Project, id=project_id)

        # IDOR / Ownership verification
        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to edit this project.")

        if project.status not in [ProjectStatus.DRAFT, ProjectStatus.DOCS_PENDING]:
            raise ValidationError(f"Cannot edit project in status '{project.status}'. Only DRAFT or DOCS_PENDING projects can be modified.")

        milestones_data = validated_data.pop('milestones', None)

        for field, value in validated_data.items():
            setattr(project, field, value)

        project.save()

        if milestones_data is not None:
            # Recreate or update milestones
            project.milestones.all().delete()
            for idx, m_data in enumerate(milestones_data):
                order = m_data.get('order', idx + 1)
                ProjectMilestone.objects.create(
                    project=project,
                    order=order,
                    title=m_data.get('title', f'Milestone {order}'),
                    description=m_data.get('description', ''),
                    target_date=m_data.get('target_date'),
                    amount=m_data.get('amount', 0.00),
                )

        return project

    @classmethod
    @transaction.atomic
    def submit_for_verification(cls, user, project_id):
        """
        Submits the project for administrative verification.
        Requires at least 1 document uploaded.
        """
        project = get_object_or_404(Project, id=project_id)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to submit this project.")

        if project.status not in [ProjectStatus.DRAFT, ProjectStatus.DOCS_PENDING]:
            raise ValidationError(f"Project cannot be submitted from current status '{project.status}'.")

        # Mandatory document validation
        if project.documents.count() == 0:
            raise ValidationError("At least one verification / statutory document (e.g. Panchayat Resolution or DPR) is required before submitting.")

        from_status = project.status
        project.status = ProjectStatus.SUBMITTED
        project.rejection_reason = ""
        project.save(update_fields=['status', 'rejection_reason', 'updated_at'])

        ProjectVerificationHistory.objects.create(
            project=project,
            action='SUBMITTED',
            from_status=from_status,
            to_status=ProjectStatus.SUBMITTED,
            actor=user,
            actor_type=ProjectVerificationHistory.ActorType.NGO,
            notes='Project proposal submitted for administrative verification.',
        )

        return project

    @classmethod
    @transaction.atomic
    def withdraw_submission(cls, user, project_id):
        """
        Withdraws a submitted project back to draft status.
        """
        project = get_object_or_404(Project, id=project_id)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to withdraw this project.")

        if project.status not in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW, ProjectStatus.DOCS_PENDING]:
            raise ValidationError(f"Cannot withdraw project with status '{project.status}'.")

        from_status = project.status
        project.status = ProjectStatus.DRAFT
        project.save(update_fields=['status', 'updated_at'])

        ProjectVerificationHistory.objects.create(
            project=project,
            action='WITHDRAWN',
            from_status=from_status,
            to_status=ProjectStatus.DRAFT,
            actor=user,
            actor_type=ProjectVerificationHistory.ActorType.NGO,
            notes='Project submission withdrawn and reverted to draft.',
        )

        return project

    @classmethod
    @transaction.atomic
    def add_document(cls, user, project_id, document_type, file_obj, notes=""):
        """
        Uploads and attaches a statutory verification document to a project.
        """
        project = get_object_or_404(Project, id=project_id)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to upload documents to this project.")

        if project.status not in [ProjectStatus.DRAFT, ProjectStatus.DOCS_PENDING, ProjectStatus.SUBMITTED]:
            raise ValidationError(f"Cannot add documents to a project in status '{project.status}'.")

        document = ProjectDocument.objects.create(
            project=project,
            document_type=document_type,
            file=file_obj,
            notes=notes,
            uploaded_by=user,
        )
        return document

    @classmethod
    @transaction.atomic
    def delete_document(cls, user, project_id, document_id):
        """
        Deletes an attached document if project is still in editable state.
        """
        project = get_object_or_404(Project, id=project_id)
        document = get_object_or_404(ProjectDocument, id=document_id, project=project)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to delete this document.")

        if project.status not in [ProjectStatus.DRAFT, ProjectStatus.DOCS_PENDING]:
            raise ValidationError("Cannot delete documents once project has been submitted or verified.")

        document.delete()
        return True

    @classmethod
    @transaction.atomic
    def add_milestone(cls, user, project_id, milestone_data):
        """
        Adds a project milestone.
        """
        project = get_object_or_404(Project, id=project_id)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to add milestones to this project.")

        if project.status not in [ProjectStatus.DRAFT, ProjectStatus.DOCS_PENDING]:
            raise ValidationError(f"Cannot add milestones when project status is '{project.status}'.")

        order = milestone_data.get('order') or (project.milestones.count() + 1)
        milestone = ProjectMilestone.objects.create(
            project=project,
            order=order,
            title=milestone_data['title'],
            description=milestone_data.get('description', ''),
            target_date=milestone_data.get('target_date'),
            amount=milestone_data.get('amount', 0.00),
        )
        return milestone

    @classmethod
    @transaction.atomic
    def delete_milestone(cls, user, project_id, milestone_id):
        """
        Deletes a project milestone.
        """
        project = get_object_or_404(Project, id=project_id)
        milestone = get_object_or_404(ProjectMilestone, id=milestone_id, project=project)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or project.organization.user == user):
            raise PermissionDenied("You do not have permission to delete milestones from this project.")

        if project.status not in [ProjectStatus.DRAFT, ProjectStatus.DOCS_PENDING]:
            raise ValidationError("Cannot delete milestones when project is locked.")

        milestone.delete()
        return True

    @classmethod
    @transaction.atomic
    def add_photo(cls, user, project_id, file_obj, caption=""):
        """
        Uploads and attaches a milestone or field execution evidence photo to a Village project.
        Allowed for authorized NGO representatives/owners when the project is in
        FUNDED, IN_PROGRESS, or COMPLETED status.
        """
        project = get_object_or_404(Project, id=project_id)

        # IDOR / Ownership check
        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or (hasattr(project, 'organization') and project.organization and project.organization.user == user)):
            raise PermissionDenied("You do not have permission to upload photos to this project.")

        eligible_statuses = [ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS, ProjectStatus.COMPLETED]
        if project.status not in eligible_statuses:
            raise ValidationError(
                f"Cannot upload milestone evidence photos for a project in status '{project.status}'. "
                f"Only projects in FUNDED, IN_PROGRESS, or COMPLETED status are eligible."
            )

        if not file_obj:
            raise ValidationError("An image file is required.")

        # Validate file size (max 5MB)
        max_size = 5 * 1024 * 1024
        if file_obj.size > max_size:
            raise ValidationError("File size must not exceed 5MB.")

        # Validate file format
        valid_extensions = ['jpg', 'jpeg', 'png', 'webp']
        filename = getattr(file_obj, 'name', '') or ''
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        content_type = getattr(file_obj, 'content_type', '')
        valid_mimes = ['image/jpeg', 'image/png', 'image/webp', 'image/pjpeg']

        if ext not in valid_extensions:
            raise ValidationError("Invalid file format. Only JPG, PNG, and WebP images are supported.")
        if content_type and content_type not in valid_mimes and not content_type.startswith('image/'):
            raise ValidationError("Uploaded file must be a valid image.")

        photo = ProjectPhoto.objects.create(
            project=project,
            file=file_obj,
            caption=(caption or "")[:200]
        )
        return photo

    @classmethod
    @transaction.atomic
    def delete_photo(cls, user, project_id, photo_id):
        """
        Deletes an uploaded milestone evidence photo.
        """
        project = get_object_or_404(Project, id=project_id)
        photo = get_object_or_404(ProjectPhoto, id=photo_id, project=project)

        if not (user.is_staff or getattr(user, 'role', None) == 'ADMIN' or project.posted_by == user or (hasattr(project, 'organization') and project.organization and project.organization.user == user)):
            raise PermissionDenied("You do not have permission to delete photos from this project.")

        if photo.file:
            photo.file.delete(save=False)
        photo.delete()
        return True

    @classmethod
    def list_photos(cls, user, project_id):
        """
        Lists milestone evidence photos for a project.
        """
        project = get_object_or_404(Project, id=project_id)
        return project.photos.all()

    @classmethod
    def get_my_projects(cls, user, category=None, status=None, search=None):
        """
        Lists projects posted by the user's NGO organization.
        """
        queryset = Project.objects.filter(
            models.Q(posted_by=user) | models.Q(organization__user=user)
        ).select_related('organization', 'posted_by').prefetch_related('documents', 'milestones')

        if category:
            queryset = queryset.filter(category=category)
        if status:
            if status == 'FUNDED_ACTIVE':
                queryset = queryset.filter(status__in=[ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS])
            elif status == 'COMPLETED_CLOSED':
                queryset = queryset.filter(status__in=[ProjectStatus.COMPLETED, ProjectStatus.CLOSED])
            else:
                queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search) |
                models.Q(location_district__icontains=search) |
                models.Q(location_village__icontains=search)
            )

        return queryset.order_by('-created_at')

    @classmethod
    def get_my_project_stats(cls, user):
        """
        Calculates exact KPI counts across all projects belonging to the NGO user.
        Statuses counted:
          - total: all projects
          - draft: DRAFT
          - submitted: SUBMITTED
          - under_review: UNDER_REVIEW
          - action_required: DOCS_PENDING
          - verified: VERIFIED
          - funded: FUNDED, IN_PROGRESS
          - completed: COMPLETED, CLOSED
          - rejected: REJECTED
        """
        base_qs = Project.objects.filter(
            models.Q(posted_by=user) | models.Q(organization__user=user)
        )
        return base_qs.aggregate(
            total=models.Count('id'),
            draft=models.Count('id', filter=models.Q(status=ProjectStatus.DRAFT)),
            submitted=models.Count('id', filter=models.Q(status=ProjectStatus.SUBMITTED)),
            under_review=models.Count('id', filter=models.Q(status=ProjectStatus.UNDER_REVIEW)),
            action_required=models.Count('id', filter=models.Q(status=ProjectStatus.DOCS_PENDING)),
            verified=models.Count('id', filter=models.Q(status=ProjectStatus.VERIFIED)),
            funded=models.Count('id', filter=models.Q(status__in=[ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS])),
            completed=models.Count('id', filter=models.Q(status__in=[ProjectStatus.COMPLETED, ProjectStatus.CLOSED])),
            rejected=models.Count('id', filter=models.Q(status=ProjectStatus.REJECTED)),
        )

    @classmethod
    def get_admin_projects(cls, status=None, category=None, search=None, ordering='-created_at'):
        """
        Retrieves projects across all organizations for administrative review.
        """
        queryset = Project.objects.all().select_related(
            'organization', 'posted_by', 'verified_by'
        ).prefetch_related('documents', 'milestones', 'verification_history')

        if category and category != 'All':
            queryset = queryset.filter(category=category)

        if status:
            status_clean = status.strip().upper()
            if status_clean == 'PENDING':
                queryset = queryset.filter(status__in=[ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW])
            elif status_clean in ('ACTIVE', 'FUNDED_ACTIVE'):
                queryset = queryset.filter(status__in=[ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS])
            elif status_clean == 'COMPLETED_CLOSED':
                queryset = queryset.filter(status__in=[ProjectStatus.COMPLETED, ProjectStatus.CLOSED])
            elif ',' in status_clean:
                statuses = [s.strip() for s in status_clean.split(',') if s.strip()]
                queryset = queryset.filter(status__in=statuses)
            elif status_clean != 'ALL':
                queryset = queryset.filter(status=status_clean)

        if search:
            search_str = search.strip()
            queryset = queryset.filter(
                models.Q(title__icontains=search_str) |
                models.Q(short_summary__icontains=search_str) |
                models.Q(organization__display_name__icontains=search_str) |
                models.Q(organization__legal_name__icontains=search_str) |
                models.Q(location_district__icontains=search_str) |
                models.Q(location_village__icontains=search_str)
            )

        allowed_orderings = {
            'created_at', '-created_at',
            'title', '-title',
            'estimated_cost', '-estimated_cost',
            'updated_at', '-updated_at',
        }
        if ordering in allowed_orderings:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at')

        return queryset

    @classmethod
    def get_admin_project_stats(cls):
        """
        Calculates global KPI aggregates across all projects for administrators.
        """
        return Project.objects.aggregate(
            total=models.Count('id'),
            pending=models.Count('id', filter=models.Q(status__in=[ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW])),
            draft=models.Count('id', filter=models.Q(status=ProjectStatus.DRAFT)),
            submitted=models.Count('id', filter=models.Q(status=ProjectStatus.SUBMITTED)),
            under_review=models.Count('id', filter=models.Q(status=ProjectStatus.UNDER_REVIEW)),
            action_required=models.Count('id', filter=models.Q(status=ProjectStatus.DOCS_PENDING)),
            verified=models.Count('id', filter=models.Q(status=ProjectStatus.VERIFIED)),
            funded=models.Count('id', filter=models.Q(status__in=[ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS])),
            completed=models.Count('id', filter=models.Q(status__in=[ProjectStatus.COMPLETED, ProjectStatus.CLOSED])),
            rejected=models.Count('id', filter=models.Q(status=ProjectStatus.REJECTED)),
        )

    @classmethod
    def get_project_detail(cls, user, project_id):
        """
        Retrieves project details with IDOR protection.
        """
        project = get_object_or_404(
            Project.objects.select_related('organization', 'posted_by', 'verified_by').prefetch_related('documents', 'milestones', 'photos', 'verification_history'),
            id=project_id
        )

        is_owner = bool(user and user.is_authenticated and (project.posted_by == user or project.organization.user == user))
        is_staff = bool(user and user.is_authenticated and (user.is_staff or getattr(user, 'role', None) == 'ADMIN'))

        if is_owner or is_staff:
            return project

        # Public access: only VERIFIED / FUNDED / IN_PROGRESS / COMPLETED projects
        if project.status in [ProjectStatus.VERIFIED, ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS, ProjectStatus.COMPLETED]:
            return project

        raise PermissionDenied("You do not have access to view this unverified draft project.")

    @classmethod
    @transaction.atomic
    def verify_project(cls, admin_user, project_id, action, notes="", rejection_reason=""):
        """
        Admin action to verify, reject, or request changes on a project.
        """
        if not (admin_user.is_staff or getattr(admin_user, 'role', None) == 'ADMIN'):
            raise PermissionDenied("Only administrative officers can review and verify projects.")

        project = get_object_or_404(Project, id=project_id)
        from_status = project.status

        action_upper = action.strip().upper().replace(' ', '_')
        if action_upper in ['VERIFY', 'APPROVE']:
            if project.status not in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW]:
                raise ValidationError(f"Cannot verify project from status '{project.status}'.")
            project.status = ProjectStatus.VERIFIED
            project.verified_by = admin_user
            project.verified_at = timezone.now()
            project.verification_notes = notes
            project.rejection_reason = ""
        elif action_upper in ['REJECT']:
            if project.status not in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW, ProjectStatus.DOCS_PENDING]:
                raise ValidationError(f"Cannot reject project from status '{project.status}'.")
            project.status = ProjectStatus.REJECTED
            project.rejection_reason = rejection_reason or notes or "Project proposal does not meet Section 135 criteria."
        elif action_upper in ['REQUEST_CHANGES', 'DOCS_PENDING', 'REQUEST_DOCS']:
            if project.status not in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW]:
                raise ValidationError(f"Cannot request changes on project with status '{project.status}'.")
            project.status = ProjectStatus.DOCS_PENDING
            project.verification_notes = notes
        elif action_upper in ['START_REVIEW', 'UNDER_REVIEW', 'ADD_TO_VERIFY', 'ADD_TO_QUEUE']:
            if project.status not in [ProjectStatus.SUBMITTED, ProjectStatus.UNDER_REVIEW]:
                raise ValidationError(f"Cannot add to review queue from status '{project.status}'. Project must be in SUBMITTED status.")
            project.status = ProjectStatus.UNDER_REVIEW
            if notes:
                project.verification_notes = notes
        else:
            raise ValidationError(f"Invalid verification action '{action}'.")

        project.save()

        ProjectVerificationHistory.objects.create(
            project=project,
            action=action_upper,
            from_status=from_status,
            to_status=project.status,
            actor=admin_user,
            actor_type=ProjectVerificationHistory.ActorType.ADMIN,
            notes=notes or rejection_reason or f"Project review action: {action_upper}",
        )

        return project
