"""Small helpers that put a quota check in front of a generation endpoint.

Views stay readable: one call that either returns `None` (go ahead) or a
ready-made 402 response explaining exactly what ran out.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from .models import Usage
from .services import (
    NoSubscription,
    QuotaExceeded,
    billing_enabled,
    remaining,
    subscription_for,
)

# HTTP 402 is the honest code here: the request is well-formed and the caller
# is authenticated — they simply have to pay (or wait) to get it served.
PAYMENT_REQUIRED = status.HTTP_402_PAYMENT_REQUIRED


def _error(code: str, message: str, **extra) -> Response:
    return Response(
        {"error": {"code": code, "message": message, **extra}}, status=PAYMENT_REQUIRED
    )


def check(store, metric: str, quantity: int) -> Response | None:
    """`None` when the store may proceed, otherwise a 402 to return as-is."""
    if not billing_enabled():
        return None
    try:
        sub = subscription_for(store)
    except NoSubscription as exc:
        return _error("no_subscription", str(exc))

    left = remaining(sub, metric)
    if quantity > left:
        exc = QuotaExceeded(metric, quantity, left, sub.plan.name)
        return _error(
            "quota_exceeded", str(exc),
            metric=metric, needed=quantity, remaining=left, plan=sub.plan.slug,
        )
    return None


def check_feature(store, feature: str, message: str) -> Response | None:
    """Gate an on/off plan feature such as publishing."""
    if not billing_enabled():
        return None
    try:
        sub = subscription_for(store)
    except NoSubscription as exc:
        return _error("no_subscription", str(exc))
    if not getattr(sub.plan, f"allows_{feature}", False):
        return _error(
            "feature_not_in_plan", message, feature=feature, plan=sub.plan.slug
        )
    return None


# convenient aliases so views read well
VIDEO_SECONDS = Usage.Metric.VIDEO_SECONDS
IMAGES = Usage.Metric.IMAGES
CAPTIONS = Usage.Metric.CAPTIONS
