"""«پردازشِ دوباره» در «صفِ پردازش» (فقط کارکنان).

    POST /api/v1/compute/queue/retry-failed/          {state: "FAILED"|"CANCELLED", kind?}  ⇒ همهٔ ردیف‌های همان فیلتر
    GET  /api/v1/compute/store-jobs/?state=bad|failed|cancelled&days=7&limit=50  ⇒ کارهای فروشگاه‌ها که ناموفق/لغو شدند
    POST /api/v1/compute/store-jobs/<id>/retry/                                   ⇒ یکی
    POST /api/v1/compute/store-jobs/retry-all/        {state: "failed"|"cancelled", days?} ⇒ همه

منطق: apps.compute.queue (ردیف‌های صف) و apps.jobs.retry (کارهای فروشگاه).
"""
from __future__ import annotations

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import queue as QV


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def queue_retry_failed(request):
    d = _data(request)
    state = str(d.get("state") or "FAILED").upper()
    out = QV.retry_many(state=state, kind=str(d.get("kind") or "").strip()[:40])
    return Response(out)


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def store_jobs(request):
    qp = request.query_params
    return Response(QV.store_jobs(state=(qp.get("state") or "bad").strip().lower(), days=_int(qp.get("days"), 7, 1, 90),
                                  limit=_int(qp.get("limit"), 50, 1, 200)))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def store_job_retry(request, pk: int):
    from apps.jobs import retry as JR
    from apps.jobs.models import Job

    job = get_object_or_404(Job.objects.select_related("store"), pk=pk)
    try:
        job = JR.retry(job, actor=request.user)
    except JR.RetryError as exc:
        return Response({"error": exc.message}, status=exc.status)
    return Response({**QV.store_job_row(job), "notice": "کار دوباره در صف گذاشته شد."})


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def store_jobs_retry_all(request):
    from apps.jobs import retry as JR
    from apps.jobs.models import Job

    d = _data(request)
    state = {"failed": "FAILED", "cancelled": "CANCELLED"}.get(str(d.get("state") or "failed").lower(), "FAILED")
    since = timezone.now() - timedelta(days=_int(d.get("days"), 7, 1, 90))
    qs = Job.objects.filter(state=state, updated_at__gte=since).order_by("updated_at")
    return Response(JR.retry_many(qs, actor=request.user, limit=100))
