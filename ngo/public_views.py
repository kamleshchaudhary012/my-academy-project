"""
DaanGives Public NGO Directory & Profile Views — Phase 3.3.2-G
===============================================================
Public-facing views for searching, filtering, and viewing APPROVED + active NGOs.

Security Enforced:
  - ONLY returns records where status == APPROVED AND is_active == True.
  - Returns 404 Not Found for non-approved or inactive NGOs.
  - Uses NGOPublicSerializer — never exposes bank numbers, PAN, private docs, or admin data.
  - No authentication required (AllowAny).
"""

from django.db.models import Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination

from ngo.models import NGOProfile
from ngo.serializers import NGOPublicSerializer


class NGOPublicPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50


class NGOPublicListView(APIView):
    """
    GET /api/v1/public/ngos/ — Public directory list with search, filtering, pagination, and ordering.
    Only returns APPROVED and is_active=True NGOs.
    """
    permission_classes = [AllowAny]
    pagination_class = NGOPublicPagination

    def get(self, request):
        # Enforce public visibility rule
        qs = NGOProfile.objects.filter(
            status=NGOProfile.Status.APPROVED,
            is_active=True,
        ).select_related('address', 'legal_info').prefetch_related('leadership')

        # 1. Search filter
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search) |
                Q(legal_name__icontains=search) |
                Q(gujarati_name__icontains=search) |
                Q(description__icontains=search) |
                Q(address__city__icontains=search) |
                Q(address__district__icontains=search) |
                Q(address__state__icontains=search)
            )

        # 2. Filters
        category = request.query_params.get('category')
        if category and category.strip().upper() not in ('', 'ALL'):
            qs = qs.filter(category__iexact=category.strip())

        city = request.query_params.get('city')
        if city and city.strip():
            qs = qs.filter(address__city__iexact=city.strip())

        district = request.query_params.get('district')
        if district and district.strip():
            qs = qs.filter(address__district__iexact=district.strip())

        state = request.query_params.get('state')
        if state and state.strip():
            qs = qs.filter(address__state__iexact=state.strip())

        service_areas = request.query_params.get('service_areas')
        if service_areas and service_areas.strip():
            qs = qs.filter(address__service_areas__icontains=service_areas.strip())

        has_12a = request.query_params.get('has_12a')
        if has_12a is not None and has_12a.strip():
            val = has_12a.strip().lower() in ('true', '1')
            if val:
                qs = qs.filter(legal_info__has_12a=True)

        has_80g = request.query_params.get('has_80g')
        if has_80g is not None and has_80g.strip():
            val = has_80g.strip().lower() in ('true', '1')
            if val:
                qs = qs.filter(legal_info__has_80g=True)

        has_fcra = request.query_params.get('has_fcra')
        if has_fcra is not None and has_fcra.strip():
            val = has_fcra.strip().lower() in ('true', '1')
            if val:
                qs = qs.filter(legal_info__has_fcra=True)

        # 3. Ordering
        ordering = request.query_params.get('ordering', 'display_name')
        allowed_orderings = {
            'display_name', '-display_name',
            'created_at', '-created_at',
            'year_established', '-year_established',
            'verified_at', '-verified_at',
        }
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by('display_name')

        # 4. Pagination
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = NGOPublicSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)

        serializer = NGOPublicSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOPublicSlugDetailView(APIView):
    """
    GET /api/v1/public/ngos/<slug:slug>/ — Retrieve public NGO detail by slug.
    Returns 404 for non-approved or inactive NGOs.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        profile = NGOProfile.objects.filter(
            status=NGOProfile.Status.APPROVED,
            is_active=True,
            slug=slug,
        ).first()

        if not profile:
            return Response(
                {'detail': 'NGO not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = NGOPublicSerializer(profile, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class NGOPublicUUIDDetailView(APIView):
    """
    GET /api/v1/public/ngos/id/<uuid:pk>/ — Retrieve public NGO detail by UUID.
    Returns 404 for non-approved or inactive NGOs.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        profile = NGOProfile.objects.filter(
            status=NGOProfile.Status.APPROVED,
            is_active=True,
            pk=pk,
        ).first()

        if not profile:
            return Response(
                {'detail': 'NGO not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = NGOPublicSerializer(profile, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


