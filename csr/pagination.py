"""
CSR Standard Pagination
=======================
Standard PageNumberPagination implementation for CSR Connect endpoints.
Frozen defaults: page_size=12, max_page_size=50, page_size_query_param='page_size'.
"""

from rest_framework.pagination import PageNumberPagination


class CSRStandardPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50
