"""Competitors, opportunities and the profit report — §3, §4 and §5.

One module because they are one screen's worth of thinking: who else sells
this, what does it cost us, and what should we do about it.
"""
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import opportunities
from .competitor_models import Competitor, CompetitorProduct, Opportunity


class CompetitorProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompetitorProduct
        fields = [
            "id", "name", "url", "price_toman", "observed_at",
            "matches", "source",
        ]


class CompetitorSerializer(serializers.ModelSerializer):
    products = CompetitorProductSerializer(many=True, read_only=True)
    #: Shown next to the conclusions so month-old positioning is read as
    #: history rather than intelligence.
    is_stale = serializers.BooleanField(read_only=True)

    class Meta:
        model = Competitor
        fields = [
            "id", "name", "kind", "website", "instagram", "notes",
            "revenue_model", "positioning", "strengths", "weaknesses",
            "analysed_at", "is_stale", "is_active", "products", "created_at",
        ]
        read_only_fields = ["analysed_at"]


class OpportunitySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True, default=None)

    class Meta:
        model = Opportunity
        fields = [
            "id", "kind", "kind_label", "product", "product_name",
            "title", "reason", "action", "evidence", "state", "priority",
            "created_at",
        ]
        read_only_fields = ["kind", "product", "title", "reason", "action", "evidence"]


class CompetitorListView(APIView):
    """GET the shop's competitors, POST to add one."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.PRODUCTS, write=False)
        rows = store.competitors.filter(is_active=True).prefetch_related("products")
        return Response(CompetitorSerializer(rows, many=True).data)

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.PRODUCTS)
        serializer = CompetitorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = serializer.save(store=store)
        except Exception:  # unique (store, name)
            return Response(
                {"error": {
                    "code": "duplicate",
                    "message": "رقیبی با این نام قبلاً ثبت شده است.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(CompetitorSerializer(row).data, status=status.HTTP_201_CREATED)


class CompetitorDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _row(self, request, store_id, pk, write=True):
        permission = access.PRODUCTS
        store = access.get_store(request.user, store_id, permission, write=write)
        return get_object_or_404(Competitor, pk=pk, store=store)

    def patch(self, request, store_id, pk):
        row = self._row(request, store_id, pk)
        serializer = CompetitorSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, store_id, pk):
        row = self._row(request, store_id, pk)
        # Deactivated, not deleted: the observed prices attached to it are the
        # evidence behind pricing suggestions the owner may still be reading.
        row.is_active = False
        row.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompetitorProductsView(APIView):
    """Record something a competitor sells, and what it cost on the day."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.PRODUCTS)
        competitor = get_object_or_404(Competitor, pk=pk, store=store)

        serializer = CompetitorProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # A price with no date is a claim. Stamp it now rather than leaving the
        # field empty and letting a month-old number look current.
        from django.utils import timezone

        row = serializer.save(
            competitor=competitor,
            observed_at=serializer.validated_data.get("observed_at") or timezone.now(),
        )
        # Recording what a competitor sells IS the analysis of that competitor.
        # Without this the row stayed "never analysed" for ever and `is_stale`
        # flagged every competitor, however fresh its prices were.
        competitor.analysed_at = row.observed_at or timezone.now()
        competitor.save(update_fields=["analysed_at", "updated_at"])
        return Response(
            CompetitorProductSerializer(row).data, status=status.HTTP_201_CREATED
        )


class ProfitReportView(APIView):
    """Revenue and **real** profit, plus what is missing to compute it."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.ANALYTICS, write=False)
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        return Response(opportunities.profit_report(store, days))


class OpportunityListView(APIView):
    """What the shop should do next."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.ANALYTICS, write=False)
        state = request.query_params.get("state", Opportunity.State.OPEN)
        rows = store.opportunities.all()
        if state != "all":
            rows = rows.filter(state=state)
        return Response(OpportunitySerializer(rows.select_related("product"), many=True).data)

    def post(self, request, store_id):
        """Recompute. Dismissed suggestions are never resurrected."""
        store = access.get_store(request.user, store_id, access.ANALYTICS)
        try:
            days = int(request.data.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        summary = opportunities.refresh(store, days)
        rows = store.opportunities.filter(state=Opportunity.State.OPEN)
        return Response({
            "summary": summary,
            "opportunities": OpportunitySerializer(
                rows.select_related("product"), many=True
            ).data,
        })


class OpportunityDetailView(APIView):
    """Mark one done or dismissed."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.ANALYTICS)
        row = get_object_or_404(Opportunity, pk=pk, store=store)

        state = request.data.get("state")
        if state not in Opportunity.State.values:
            return Response(
                {"error": {"code": "bad_state", "message": "وضعیت نامعتبر است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row.state = state
        row.save(update_fields=["state", "updated_at"])
        return Response(OpportunitySerializer(row).data)
