from rest_framework.pagination import PageNumberPagination


class GrowthPagination(PageNumberPagination):
    """``?page=2&page_size=50`` (default 25, at most 100)."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
