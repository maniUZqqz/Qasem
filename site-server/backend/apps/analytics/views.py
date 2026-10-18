from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store

from .services import store_overview, store_sales, store_timeseries
from apps.stores import access


def _owned_store(request, store_id) -> Store:
    return access.get_store(request.user, store_id, access.ANALYTICS, write=False)


class StoreAnalyticsView(APIView):
    """GET /api/v1/stores/{store_id}/analytics/ — real aggregated store metrics."""

    def get(self, request, store_id):
        store = _owned_store(request, store_id)
        return Response(store_overview(store))


class StoreTimeseriesView(APIView):
    """GET /api/v1/stores/{store_id}/analytics/timeseries/?days=14"""

    def get(self, request, store_id):
        store = _owned_store(request, store_id)
        try:
            days = int(request.query_params.get("days", 14))
        except (TypeError, ValueError):
            days = 14
        return Response(store_timeseries(store, days))


class StoreSalesView(APIView):
    """GET /api/v1/stores/{store_id}/analytics/sales/?days=30 — sales & support KPIs."""

    def get(self, request, store_id):
        store = _owned_store(request, store_id)
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        return Response(store_sales(store, days))
