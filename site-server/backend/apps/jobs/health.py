"""Is this system actually working? Phase 18 — Monitoring.

Three endpoints, and the difference between them is the whole design:

* **`/healthz`** — am I alive? Answers instantly, touches nothing. A load
  balancer asks this every second and it must never be the thing that falls
  over under its own monitoring.
* **`/readyz`** — can I serve? Checks the database and the queue, because a
  process that cannot reach either will accept requests and fail every one.
  This is what an orchestrator should gate traffic on.
* **`/metrics`** — what is going on? The numbers a person looks at when
  something is wrong: queue depth, failure rate, how long jobs have been
  parked, what the GPU engines say.

**The rule that shapes all three: a check that cannot be answered says so, and
does not answer "healthy".** An unknown that reports OK is worse than no check
at all — it is a monitor that tells you everything is fine while the thing it
was meant to watch is down.

**And none of them is public.** Queue depth and failure rates are a map of how
to overload us, and they name customers' jobs. `/healthz` is open because a load
balancer has no credentials; the other two want staff.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.db import connection
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Job

logger = logging.getLogger(__name__)

#: A job running longer than this is either wedged or the GPU is thrashing.
#: Not an error on its own — a long video legitimately takes a while — but it
#: is the first number to look at when a shop says "nothing is happening".
STUCK_AFTER = timedelta(hours=2)

#: Failures above this share of recent jobs mean something systemic, not a
#: run of bad luck.
BAD_FAILURE_RATE = 0.25


def _timed(check):
    """Run one check, never let it raise, and record how long it took."""
    started = time.monotonic()
    try:
        ok, detail = check()
    except Exception as exc:  # noqa: BLE001 — a check that crashes is a check that failed
        ok, detail = False, str(exc)[:200]
    return {
        "ok": ok,
        "detail": detail,
        "ms": int((time.monotonic() - started) * 1000),
    }


def _database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return True, connection.vendor


def _queue():
    from apps.jobs.services import broker_reachable

    if broker_reachable():
        return True, "reachable"
    # Named rather than reported as a generic failure: in eager mode there is
    # deliberately no broker, and confusing the two sends someone to debug a
    # Redis that was never supposed to be running.
    from django.conf import settings

    if settings.CELERY_TASK_ALWAYS_EAGER:
        return True, "eager mode — tasks run inline, no broker needed"
    return False, "صف پردازش (Redis) در دسترس نیست"


def _storage():
    from django.conf import settings

    if settings.MEDIA_IS_SHARED:
        return True, f"{settings.MEDIA_STORAGE} — shared"
    # Not a failure. It is correct in development and wrong on more than one
    # machine, and the honest answer is to say which one this is.
    return True, "local volume — single machine only"


def _ai_engines():
    """What the model engines say. Never fails readiness.

    A shop can log in, see their products and read their inbox with the GPU
    box switched off. Gating readiness on Ollama would take the whole product
    down for a maintenance window on one engine.
    """
    from services.ai import providers

    out = {}
    for capability in (providers.TEXT, providers.VISION, providers.IMAGE, providers.VIDEO):
        try:
            out[capability] = providers.api_mode(capability)
        except Exception as exc:  # noqa: BLE001
            out[capability] = f"unknown ({exc})"
    return out


class LiveView(APIView):
    """`/healthz` — am I alive? Touches nothing."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"ok": True, "at": timezone.now()})


class ReadyView(APIView):
    """`/readyz` — can I serve? Database and queue.

    503 when not, so an orchestrator stops sending traffic here instead of
    letting every request fail individually.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {
            "database": _timed(_database),
            "queue": _timed(_queue),
            "storage": _timed(_storage),
        }
        ready = all(check["ok"] for check in checks.values())
        return Response(
            {"ready": ready, "checks": checks, "at": timezone.now()},
            status=200 if ready else 503,
        )


class MetricsView(APIView):
    """`/metrics` — what is going on. Staff only.

    Queue depth and failure rates are a map of how to overload us, and the job
    rows name customers' work.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.jobs.machine import AWAITING_HUMAN, BUSY

        now = timezone.now()
        day_ago = now - timedelta(days=1)

        recent = Job.objects.filter(created_at__gte=day_ago)
        total = recent.count()
        failed = recent.filter(state=Job.State.FAILED).count()
        rate = (failed / total) if total else None

        running = Job.objects.filter(state__in=list(BUSY))
        stuck = running.filter(updated_at__lt=now - STUCK_AFTER)
        parked = Job.objects.filter(state__in=list(AWAITING_HUMAN))

        return Response({
            "at": now,
            "checks": {
                "database": _timed(_database),
                "queue": _timed(_queue),
                "storage": _timed(_storage),
            },
            "jobs": {
                "queued": Job.objects.filter(state=Job.State.QUEUED).count(),
                "running": running.count(),
                # Parked is not stuck. A job waiting for its owner to press
                # approve is perfectly healthy, and counting it as a problem
                # makes a working feature look like an outage.
                "waiting_for_a_person": parked.count(),
                "longest_wait_hours": _longest_wait_hours(parked, now),
                "stuck": stuck.count(),
                "stuck_ids": list(stuck.values_list("id", flat=True)[:20]),
            },
            "last_24h": {
                "total": total,
                "completed": recent.filter(state=Job.State.COMPLETED).count(),
                "failed": failed,
                "cancelled": recent.filter(state=Job.State.CANCELLED).count(),
                # None, not 0.0, when nothing ran. A quiet night is not a
                # perfect success rate.
                "failure_rate": round(rate, 3) if rate is not None else None,
                "alarming": rate is not None and rate > BAD_FAILURE_RATE,
            },
            "ai": _ai_engines(),
        })


def _longest_wait_hours(parked, now) -> float | None:
    oldest = parked.order_by("updated_at").first()
    if oldest is None:
        return None
    return round((now - oldest.updated_at).total_seconds() / 3600, 1)
