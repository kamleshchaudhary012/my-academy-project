from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import PageNumberPagination
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404
from django.db.models import Q

from .models import Project, ProjectStatus
from .permissions import IsVillageUser, IsProjectOwner, CanEditProject, IsAdminUserOrReadOnly
from .services import ProjectService
from .serializers import (
    ProjectListSerializer,
    ProjectDetailSerializer,
    ProjectCreateUpdateSerializer,
    ProjectDocumentSerializer,
    ProjectMilestoneSerializer,
    ProjectPhotoSerializer,
    ProjectVerificationSerializer,
)


class MyProjectPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class ProjectCreateView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]
    parser_classes = [JSONParser]

    def post(self, request):
        serializer = ProjectCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Validation failed", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project = ProjectService.create_draft(request.user, serializer.validated_data)
            return Response(
                ProjectDetailSerializer(project).data,
                status=status.HTTP_201_CREATED
            )
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class MyProjectListView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]

    def get(self, request):
        category = request.query_params.get('category')
        status_param = request.query_params.get('status')
        search = request.query_params.get('search')

        projects = ProjectService.get_my_projects(
            user=request.user,
            category=category,
            status=status_param,
            search=search
        )
        stats = ProjectService.get_my_project_stats(request.user)

        paginator = MyProjectPagination()
        page = paginator.paginate_queryset(projects, request)
        if page is not None:
            serializer = ProjectListSerializer(page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response.data['stats'] = stats
            return response

        serializer = ProjectListSerializer(projects, many=True)
        return Response({
            'count': projects.count(),
            'next': None,
            'previous': None,
            'results': serializer.data,
            'stats': stats,
        }, status=status.HTTP_200_OK)


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            project = ProjectService.get_project_detail(request.user, id)
            return Response(ProjectDetailSerializer(project).data, status=status.HTTP_200_OK)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

    def patch(self, request, id):
        serializer = ProjectCreateUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {"detail": "Validation failed", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project = ProjectService.update_project(request.user, id, serializer.validated_data)
            return Response(ProjectDetailSerializer(project).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectSubmitView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]

    def post(self, request, id):
        try:
            project = ProjectService.submit_for_verification(request.user, id)
            return Response(
                {
                    "detail": "Project submitted for administrative verification successfully.",
                    "project": ProjectDetailSerializer(project).data
                },
                status=status.HTTP_200_OK
            )
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectWithdrawView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]

    def post(self, request, id):
        try:
            project = ProjectService.withdraw_submission(request.user, id)
            return Response(
                {
                    "detail": "Project submission withdrawn and reverted to draft.",
                    "project": ProjectDetailSerializer(project).data
                },
                status=status.HTTP_200_OK
            )
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectDocumentUploadView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, id):
        file_obj = request.FILES.get('file')
        document_type = request.data.get('document_type', 'OTHER')
        notes = request.data.get('notes', '')

        if not file_obj:
            return Response(
                {"detail": "File is required for document upload."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # File size check: 5MB maximum
        if file_obj.size > 5 * 1024 * 1024:
            return Response(
                {"detail": "Uploaded file exceeds the maximum allowed size of 5MB."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            document = ProjectService.add_document(
                user=request.user,
                project_id=id,
                document_type=document_type,
                file_obj=file_obj,
                notes=notes
            )
            return Response(ProjectDocumentSerializer(document).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectDocumentDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]

    def delete(self, request, id, doc_id):
        try:
            ProjectService.delete_document(request.user, id, doc_id)
            return Response({"detail": "Document removed successfully."}, status=status.HTTP_204_NO_CONTENT)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectMilestoneCreateView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]
    parser_classes = [JSONParser]

    def post(self, request, id):
        title = request.data.get('title')
        if not title:
            return Response({"detail": "Milestone title is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            milestone = ProjectService.add_milestone(request.user, id, request.data)
            return Response(ProjectMilestoneSerializer(milestone).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectMilestoneDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]

    def delete(self, request, id, mid):
        try:
            ProjectService.delete_milestone(request.user, id, mid)
            return Response({"detail": "Milestone removed successfully."}, status=status.HTTP_204_NO_CONTENT)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectPhotoUploadView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, id):
        photos = ProjectService.list_photos(request.user, id)
        serializer = ProjectPhotoSerializer(photos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, id):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"detail": "No photo file provided."}, status=status.HTTP_400_BAD_REQUEST)

        caption = request.data.get('caption', '')
        try:
            photo = ProjectService.add_photo(
                user=request.user,
                project_id=id,
                file_obj=file_obj,
                caption=caption
            )
            return Response(ProjectPhotoSerializer(photo).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class ProjectPhotoDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsVillageUser]

    def delete(self, request, id, photo_id):
        try:
            ProjectService.delete_photo(request.user, id, photo_id)
            return Response({"detail": "Photo removed successfully."}, status=status.HTTP_204_NO_CONTENT)
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)


class PublicProjectListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        queryset = Project.objects.filter(
            status=ProjectStatus.VERIFIED
        ).select_related('organization', 'posted_by').prefetch_related('documents', 'milestones')

        category = request.query_params.get('category')
        state = request.query_params.get('state')
        district = request.query_params.get('district')
        search = request.query_params.get('search')

        if category:
            queryset = queryset.filter(category=category)
        if state:
            queryset = queryset.filter(location_state__iexact=state)
        if district:
            queryset = queryset.filter(location_district__iexact=district)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(short_summary__icontains=search) |
                Q(location_village__icontains=search) |
                Q(location_district__icontains=search) |
                Q(organization__name__icontains=search)
            )

        serializer = ProjectListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicProjectDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, id):
        project = get_object_or_404(
            Project.objects.filter(
                status__in=[
                    ProjectStatus.VERIFIED,
                    ProjectStatus.FUNDED,
                    ProjectStatus.IN_PROGRESS,
                    ProjectStatus.COMPLETED
                ]
            ).select_related('organization', 'posted_by', 'verified_by').prefetch_related('documents', 'milestones', 'photos'),
            id=id
        )
        serializer = ProjectDetailSerializer(project)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminProjectVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        return self._handle_verification(request, id)

    def post(self, request, id):
        return self._handle_verification(request, id)

    def _handle_verification(self, request, id):
        if not (request.user.is_staff or getattr(request.user, 'role', None) == 'ADMIN'):
            return Response({"detail": "Admin authorization required."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ProjectVerificationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Validation error", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        action = serializer.validated_data['action']
        notes = serializer.validated_data.get('notes', '')
        rejection_reason = serializer.validated_data.get('rejection_reason', '')

        try:
            project = ProjectService.verify_project(
                admin_user=request.user,
                project_id=id,
                action=action,
                notes=notes,
                rejection_reason=rejection_reason
            )
            return Response(
                {
                    "detail": f"Project status updated to {project.status}.",
                    "project": ProjectDetailSerializer(project).data
                },
                status=status.HTTP_200_OK
            )
        except ValidationError as e:
            return Response({"detail": str(e.message if hasattr(e, 'message') else e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
