from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import Project, ProjectVerificationHistory
from .serializers import (
    ProjectListSerializer,
    ProjectDetailSerializer,
    ProjectVerificationHistorySerializer,
)
from .services import ProjectService
from .views import AdminProjectVerifyView


class ProjectAdminPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50


class AdminProjectQueueView(APIView):
    """
    GET /api/v1/admin/projects/ — Admin project verification queue list.
    Supports status & category filters, multi-field search, ordering, pagination, and KPI aggregates.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = ProjectAdminPagination

    def get(self, request):
        if not (request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN'):
            return Response(
                {"detail": "Administrator access required."},
                status=status.HTTP_403_FORBIDDEN
            )

        status_param = request.query_params.get('status')
        category = request.query_params.get('category')
        search = request.query_params.get('search')
        ordering = request.query_params.get('ordering', '-created_at')

        projects = ProjectService.get_admin_projects(
            status=status_param,
            category=category,
            search=search,
            ordering=ordering
        )
        stats_data = ProjectService.get_admin_project_stats()

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(projects, request, view=self)
        if page is not None:
            serializer = ProjectListSerializer(page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response.data['stats'] = stats_data
            return response

        serializer = ProjectListSerializer(projects, many=True)
        return Response({
            'count': projects.count(),
            'next': None,
            'previous': None,
            'results': serializer.data,
            'stats': stats_data,
        }, status=status.HTTP_200_OK)


class AdminProjectDetailView(APIView):
    """
    GET /api/v1/admin/projects/<uuid:id>/ — Full project inspection for Administrator.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        if not (request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN'):
            return Response(
                {"detail": "Administrator access required."},
                status=status.HTTP_403_FORBIDDEN
            )

        project = get_object_or_404(
            Project.objects.select_related(
                'organization', 'posted_by', 'verified_by'
            ).prefetch_related(
                'documents', 'milestones', 'photos', 'verification_history'
            ),
            id=id
        )

        serializer = ProjectDetailSerializer(project)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminProjectHistoryView(APIView):
    """
    GET /api/v1/admin/projects/<uuid:id>/history/ — Read-only verification history audit log.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        if not (request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN'):
            return Response(
                {"detail": "Administrator access required."},
                status=status.HTTP_403_FORBIDDEN
            )

        project = get_object_or_404(Project, id=id)
        history = project.verification_history.all().order_by('-created_at')
        serializer = ProjectVerificationHistorySerializer(history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
