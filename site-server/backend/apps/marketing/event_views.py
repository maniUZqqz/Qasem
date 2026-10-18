"""Event ingest.

Accepts a *batch*. The browser buffers and flushes on a timer or on page hide,
so a visit that fires eight events costs one request instead of eight — which
matters on a mobile connection and keeps the throttle meaningful.

Everything here is best-effort by design: analytics must never be the reason a
visitor sees an error. A malformed event is dropped silently rather than
failing the batch, and the endpoint always answers 202.
"""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .events import Event

logger = logging.getLogger(__name__)

MAX_BATCH = 25
VALID_NAMES = set(Event.Name.values)
UTM_KEYS = {"source", "medium", "campaign", "term", "content"}


class EventThrottle(AnonRateThrottle):
    """Generous — a real visit is a handful of batches — but not unlimited."""

    scope = "event"

    def allow_request(self, request, view):
        if getattr(settings, "IS_TEST", False):
            return True
        return super().allow_request(request, view)


def _clean(raw: dict) -> Event | None:
    """Build an Event from untrusted input, or None if it is not usable."""
    if not isinstance(raw, dict):
        return None

    name = str(raw.get("name") or "")
    if name not in VALID_NAMES:
        return None

    session = str(raw.get("session") or "").strip()[:40]
    if not session:
        return None

    utm = raw.get("utm")
    utm = (
        {k: str(v)[:120] for k, v in utm.items() if k in UTM_KEYS and v}
        if isinstance(utm, dict)
        else {}
    )

    props = raw.get("props")
    # Props are free-form by nature, but not a storage bucket: cap the keys and
    # the value length so a hostile client cannot park data in our database.
    props = (
        {str(k)[:40]: str(v)[:200] for k, v in list(props.items())[:10]}
        if isinstance(props, dict)
        else {}
    )

    return Event(
        name=name,
        session=session,
        path=str(raw.get("path") or "")[:300],
        locale=str(raw.get("locale") or "")[:5],
        referrer=str(raw.get("referrer") or "")[:300],
        utm=utm,
        props=props,
    )


class EventIngestView(APIView):
    """`POST /api/v1/events/` — `{"events": [...]}`."""

    permission_classes = [AllowAny]
    throttle_classes = [EventThrottle]

    def post(self, request):
        raw = request.data.get("events")
        if not isinstance(raw, list):
            return Response({"ok": True, "stored": 0}, status=status.HTTP_202_ACCEPTED)

        rows = [e for e in (_clean(r) for r in raw[:MAX_BATCH]) if e is not None]
        if rows:
            Event.objects.bulk_create(rows)

        return Response(
            {"ok": True, "stored": len(rows)}, status=status.HTTP_202_ACCEPTED
        )
