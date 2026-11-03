import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class ProjectCategory(models.TextChoices):
    POVERTY = 'POVERTY', _('Eradicating Hunger, Poverty and Malnutrition')
    HEALTH = 'HEALTH', _('Promoting Health Care and Sanitation')
    EDUCATION = 'EDUCATION', _('Promoting Education and Employability')
    GENDER = 'GENDER', _('Promoting Gender Equality and Women Empowerment')
    ENVIRONMENT = 'ENVIRONMENT', _('Ensuring Environmental Sustainability')
    HERITAGE = 'HERITAGE', _('Protection of National Heritage, Art and Culture')
    ARMED_FORCES = 'ARMED_FORCES', _('Measures for Armed Forces Veterans')
    RURAL = 'RURAL', _('Rural Development Projects')
    DISASTER = 'DISASTER', _('Disaster Management and Relief')


class ProjectStatus(models.TextChoices):
    DRAFT = 'DRAFT', _('Draft')
    SUBMITTED = 'SUBMITTED', _('Submitted for Verification')
    UNDER_REVIEW = 'UNDER_REVIEW', _('Under Review')
    DOCS_PENDING = 'DOCS_PENDING', _('Documents Pending')
    VERIFIED = 'VERIFIED', _('Verified Project')
    REJECTED = 'REJECTED', _('Rejected')
    FUNDED = 'FUNDED', _('Funded by CSR Partner')
    IN_PROGRESS = 'IN_PROGRESS', _('In Progress')
    COMPLETED = 'COMPLETED', _('Completed')
    CLOSED = 'CLOSED', _('Closed')


class ProjectDocumentType(models.TextChoices):
    PANCHAYAT_RESOLUTION = 'PANCHAYAT_RESOLUTION', _('Gram Panchayat Resolution / NOC')
    LAND_PERMISSION = 'LAND_PERMISSION', _('Land Availability / Permission Letter')
    TECHNICAL_ESTIMATE = 'TECHNICAL_ESTIMATE', _('Detailed Technical Estimate / DPR')
    MAINTENANCE_PLAN = 'MAINTENANCE_PLAN', _('Post-Completion Maintenance Plan')
    BUDGET_BREAKDOWN = 'BUDGET_BREAKDOWN', _('Itemized Budget Breakdown')
    NGO_REGISTRATION = 'NGO_REGISTRATION', _('NGO / Sanstha Registration Certificate')
    OTHER = 'OTHER', _('Other Supporting Document')


class MilestoneStatus(models.TextChoices):
    PENDING = 'PENDING', _('Pending')
    IN_PROGRESS = 'IN_PROGRESS', _('In Progress')
    COMPLETED = 'COMPLETED', _('Completed')
    VERIFIED = 'VERIFIED', _('Verified')


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    short_summary = models.CharField(max_length=300)
    description = models.TextField()

    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='posted_projects'
    )
    organization = models.ForeignKey(
        'ngo.NGOProfile',
        on_delete=models.PROTECT,
        related_name='projects'
    )

    category = models.CharField(
        max_length=32,
        choices=ProjectCategory.choices,
        default=ProjectCategory.RURAL
    )

    location_state = models.CharField(max_length=64)
    location_district = models.CharField(max_length=64)
    location_village = models.CharField(max_length=128)
    location_pincode = models.CharField(max_length=10)

    beneficiaries_count = models.PositiveIntegerField(default=0)
    beneficiaries_description = models.TextField(blank=True)

    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2)
    timeline_months = models.PositiveIntegerField(default=6)

    status = models.CharField(
        max_length=24,
        choices=ProjectStatus.choices,
        default=ProjectStatus.DRAFT,
        db_index=True
    )

    verification_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='verified_projects'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'category', 'created_at']),
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"

    @property
    def is_csr_ready(self):
        """
        Determines whether the project is ready for Corporate CSR funding.
        Requires:
        1. Project itself is verified / funded / in progress / completed.
        2. Organization is an APPROVED, active NGOProfile.
        3. Organization possesses verified CSR eligibility (Rule 4 criteria + is_csr_verified).
        """
        if self.status not in [
            ProjectStatus.VERIFIED,
            ProjectStatus.FUNDED,
            ProjectStatus.IN_PROGRESS,
            ProjectStatus.COMPLETED,
        ]:
            return False
        org = getattr(self, 'organization', None)
        if not org or org.status != 'APPROVED' or not getattr(org, 'is_active', False):
            return False
        legal = getattr(org, 'legal_info', None)
        verification = getattr(org, 'verification', None)
        if not (legal and legal.is_csr_eligible):
            return False
        if not (verification and getattr(verification, 'is_csr_verified', False)):
            return False
        return True


class ProjectDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    document_type = models.CharField(
        max_length=32,
        choices=ProjectDocumentType.choices,
        default=ProjectDocumentType.OTHER
    )
    file = models.FileField(upload_to='project_docs/')
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.project.title}"


class ProjectMilestone(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='milestones'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    order = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(
        max_length=24,
        choices=MilestoneStatus.choices,
        default=MilestoneStatus.PENDING
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"Milestone #{self.order}: {self.title} ({self.status})"


class ProjectPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='photos'
    )
    file = models.ImageField(upload_to='project_photos/')
    caption = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"Photo for {self.project.title}"


class ProjectVerificationHistory(models.Model):
    """
    Immutable audit history record for project submission, review, and verification status changes.
    """
    class ActorType(models.TextChoices):
        NGO = 'NGO', _('NGO User')
        ADMIN = 'ADMIN', _('Admin User')
        SYSTEM = 'SYSTEM', _('System')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='verification_history'
    )
    action = models.CharField(max_length=64)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    actor_type = models.CharField(
        max_length=20,
        choices=ActorType.choices,
        default=ActorType.NGO
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', '-created_at']),
        ]

    def __str__(self):
        return f"{self.project.title}: {self.from_status} -> {self.to_status} ({self.action})"
