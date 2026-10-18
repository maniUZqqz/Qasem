"""Plans and usage over the API — what the panel needs to draw its meters."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store

from . import credits, services
from .models import Plan, Subscription, Usage
from .serializers import PlanSerializer, SubscriptionSerializer, UsageSerializer
from apps.stores import access


class PlanListView(APIView):
    """Public — the pricing page reads this, logged in or not."""

    permission_classes = [AllowAny]

    def get(self, request):
        plans = Plan.objects.filter(is_public=True).order_by("sort_order", "price_toman")
        return Response(PlanSerializer(plans, many=True).data)


def _owned_store(request, pk) -> Store:
    return access.get_store(request.user, pk, access.BILLING)


class StoreUsageView(APIView):
    """Live quota state for one store: plan, period and every meter."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = _owned_store(request, pk)
        return Response(services.snapshot(store))


class StoreSubscriptionView(APIView):
    """Read the subscription, or switch plan."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = _owned_store(request, pk)
        sub = Subscription.objects.filter(store=store).select_related("plan").first()
        if sub is None:
            return Response(None)
        return Response(SubscriptionSerializer(sub).data)

    def post(self, request, pk):
        """Choose a plan. Payment is a separate step — this only records intent."""
        store = _owned_store(request, pk)
        slug = str(request.data.get("plan") or "")
        plan = Plan.objects.filter(slug=slug, is_public=True).first()
        if plan is None:
            return Response(
                {"error": {"code": "unknown_plan", "message": "چنین پلنی وجود ندارد."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub = services.subscription_for(store)
        sub.plan = plan
        # a paid plan starts as PAST_DUE until a payment is recorded, so the
        # quota gate cannot be opened by simply picking an expensive package
        sub.status = (
            Subscription.Status.ACTIVE if plan.price_toman == 0
            else Subscription.Status.PAST_DUE
        )
        sub.save(update_fields=["plan", "status", "updated_at"])
        return Response(SubscriptionSerializer(sub).data)


class StoreUsageHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = _owned_store(request, pk)
        rows = Usage.objects.filter(store=store).select_related("job")[:100]
        return Response(UsageSerializer(rows, many=True).data)


class UsageQualityView(APIView):
    """"This output is not good" — the store's half of the quality guarantee.

    POST returns the credit for one generation and reports where the chain now
    stands against the guarantee, so the panel can say "one attempt left" or
    "the next one is free" instead of leaving the owner to count.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk, usage_id):
        store = _owned_store(request, pk)
        row = get_object_or_404(Usage, pk=usage_id, store=store)

        try:
            refunded = credits.refund(
                row,
                reason=str(request.data.get("reason", ""))[:200],
                source=credits.CUSTOMER,
                actor=request.user,
            )
        except credits.NotRefundable as exc:
            return Response(
                {"error": {"code": "not_refundable", "message": str(exc)}},
                status=status.HTTP_409_CONFLICT,
            )

        return Response({
            "usage": UsageSerializer(refunded).data,
            "guarantee": credits.guarantee_status(refunded),
            "snapshot": services.snapshot(store),
        })
