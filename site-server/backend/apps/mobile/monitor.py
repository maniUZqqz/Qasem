"""Monitoring summary and the SAFE actions a phone may take.

Only app-level actions NM already supports for staff (cancel / retry a job, enable/disable a compute node, reset the AI
route circuit, pause the SMS queue). Never service restarts, never shell access. Every action is audited with user + device.
"""
from __future__ import annotations

import logging
import shutil
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db import connection
from django.utils import timezone

from .base import MobileError, log_action
from .models import MobileCall, MobileDevice, MobileSettings, SmsMessage

logger = logging.getLogger(__name__)

ACTIONS = [
    {"action": "job.cancel", "label": "لغوِ کار", "target_kind": "job", "confirm_text": "این کار لغو شود؟ (اعتبارِ مصرف‌شده برمی‌گردد)", "danger": False},
    {"action": "compute_job.cancel", "label": "لغوِ کارِ پردازشی", "target_kind": "compute_job", "confirm_text": "این کارِ پردازشی لغو شود؟", "danger": False},
    {"action": "compute_job.retry", "label": "تلاشِ دوباره", "target_kind": "compute_job", "confirm_text": "این کارِ ناموفق دوباره در صف گذاشته شود؟", "danger": False},
    {"action": "compute_node.disable", "label": "توقفِ سرورِ پردازش", "target_kind": "compute_node", "confirm_text": "این سرورِ پردازش دیگر کار نگیرد؟ (کارهای در صف منتظر می‌مانند)", "danger": True},
    {"action": "compute_node.enable", "label": "ازسرگیریِ سرورِ پردازش", "target_kind": "compute_node", "confirm_text": "این سرورِ پردازش دوباره کار بگیرد؟", "danger": False},
    {"action": "ai.reset_circuit", "label": "آزادکردنِ مسیرهای کنارگذاشتهٔ هوش مصنوعی", "target_kind": "", "confirm_text": "مسیرهای کنارگذاشتهٔ هوش مصنوعی دوباره امتحان شوند؟", "danger": False},
    {"action": "sms.pause", "label": "توقفِ صفِ پیامک", "target_kind": "", "confirm_text": "ارسالِ همهٔ پیامک‌ها از همهٔ گوشی‌ها متوقف شود؟", "danger": True},
    {"action": "sms.resume", "label": "ازسرگیریِ صفِ پیامک", "target_kind": "", "confirm_text": "صفِ پیامک دوباره کار کند؟", "danger": False},
    {"action": "sms.cancel", "label": "لغوِ یک پیامک", "target_kind": "sms", "confirm_text": "این پیامکِ در صف لغو شود؟", "danger": False},
]
ACTION_KEYS = {a["action"] for a in ACTIONS}


def _iso(v):
    return v.isoformat() if v else None


def _disk(path="/"):
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    gb = 1024 ** 3
    pct = round(u.used / u.total * 100) if u.total else None
    return {"path": path, "total_gb": round(u.total / gb, 1), "used_gb": round(u.used / gb, 1), "free_gb": round(u.free / gb, 1),
            "percent_used": pct, "low": bool(pct is not None and (pct >= 90 or u.free / gb < 3))}


def _queue_lengths():
    url = getattr(dj_settings, "CELERY_BROKER_URL", "") or ""
    if not url.startswith("redis"):
        return None
    try:
        import redis

        r = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        return {name: int(r.llen(name)) for name in ("celery", "ai", "gpu")}
    except Exception:  # noqa: BLE001 - unknown stays unknown
        return None


def _checks(nodes_online, disk, queue):
    checks = []
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks.append({"name": "database", "label": "پایگاه داده", "ok": True, "detail": ""})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "database", "label": "پایگاه داده", "ok": False, "detail": str(exc)[:120]})
    checks.append({"name": "queue", "label": "صفِ کارها (Redis)", "ok": queue is not None,
                   "detail": "" if queue is not None else "وضعیتِ صف معلوم نیست"})
    checks.append({"name": "compute", "label": "سرورِ پردازش", "ok": nodes_online > 0,
                   "detail": "" if nodes_online > 0 else "هیچ سرورِ پردازشی آنلاین نیست"})
    ok_disk = bool(disk) and (disk["percent_used"] or 0) < 95 and disk["free_gb"] >= 1
    checks.append({"name": "disk", "label": "فضای دیسک", "ok": ok_disk,
                   "detail": "" if ok_disk else (f"{disk['free_gb']} گیگابایت خالی" if disk else "نامعلوم")})
    return checks


def _ai():
    from django.core.cache import cache

    cached = cache.get("mobile:ai-status")
    if cached is not None:
        return cached
    try:
        from services.ai import priority, status

        snap = status.snapshot()
        local, metis = snap.get("local") or {}, snap.get("metis") or {}
        out = {
            "priority": snap.get("priority"),
            "priority_label": next((o["label"] for o in snap.get("orders", []) if o["value"] == snap.get("priority")), ""),
            "local": {"online": bool(local.get("online")), "node": local.get("node") or None, "last_error": local.get("last_error")},
            "metis": {"configured": bool(metis.get("configured")), "last_error": metis.get("last_error"),
                      "circuit_open": bool(metis.get("circuit_open_until"))},
        }
    except Exception:  # noqa: BLE001
        logger.info("ai status unavailable", exc_info=True)
        out = None
    cache.set("mobile:ai-status", out, 20)
    return out


def summary() -> dict:
    from apps.compute.models import ComputeJob, ComputeNode
    from apps.jobs.models import Job

    now = timezone.now()
    nodes = [{"id": n.pk, "name": n.name, "online": n.online, "enabled": n.enabled, "last_seen": _iso(n.last_seen),
              "gpu": (n.capabilities or {}).get("gpu"),
              "services": {k: bool((n.capabilities or {}).get(k)) for k in ("voice", "ollama", "comfyui", "photo", "video")},
              "jobs_done": n.jobs_done} for n in ComputeNode.objects.all()]
    online = sum(1 for n in nodes if n["online"] and n["enabled"])
    disk = _disk("/")
    queue = _queue_lengths()
    failures = []
    for j in Job.objects.filter(state=Job.State.FAILED).order_by("-updated_at")[:10]:
        failures.append({"kind": "job", "id": str(j.pk), "type": j.type, "error": (j.error or "")[:200], "at": _iso(j.updated_at)})
    for j in ComputeJob.objects.filter(state=ComputeJob.State.FAILED).order_by("-updated_at")[:10]:
        failures.append({"kind": "compute_job", "id": str(j.uid), "type": j.kind, "error": (j.error or "")[-200:], "at": _iso(j.updated_at)})
    failures.sort(key=lambda f: f["at"] or "", reverse=True)
    checks = _checks(online, disk, queue)
    status = "down" if not checks[0]["ok"] else ("ok" if all(c["ok"] for c in checks) else "degraded")
    day = now - timedelta(days=1)
    return {
        "generated_at": _iso(now),
        "health": {"status": status, "checks": checks},
        "nodes": nodes,
        "queue": {
            "compute": {"queued": ComputeJob.objects.filter(state=ComputeJob.State.QUEUED).count(),
                        "running": ComputeJob.objects.filter(state__in=["CLAIMED", "RUNNING"]).count()},
            "jobs": {"queued": Job.objects.filter(state=Job.State.QUEUED).count(),
                     "processing": Job.objects.filter(state__in=[Job.State.PROCESSING, Job.State.RUNNING, Job.State.RENDERING]).count(),
                     "waiting_approval": Job.objects.filter(state__in=[Job.State.WAITING_APPROVAL, Job.State.PREVIEW]).count()},
            "celery": queue,
        },
        "failures": failures[:10],
        "ai": _ai(),
        "disk": disk,
        "mobile": {
            "devices_online": sum(1 for d in MobileDevice.objects.filter(revoked_at__isnull=True) if d.online),
            "sms_queued": SmsMessage.objects.filter(state=SmsMessage.State.QUEUED).count(),
            "sms_sent_today": SmsMessage.objects.filter(state__in=[SmsMessage.State.SENT, SmsMessage.State.DELIVERED], sent_at__gte=day).count(),
            "calls_today": MobileCall.objects.filter(started_at__gte=day).count(),
            "sms_paused": not MobileSettings.get().sms_enabled,
        },
        "actions": ACTIONS,
    }


# ------------------------------------------------------------------ actions

def run_action(request, action: str, target="", params=None) -> dict:
    params = params if isinstance(params, dict) else {}
    target = "" if target is None else str(target).strip()
    if action not in ACTION_KEYS:
        raise MobileError("unknown_action", "این اقدام مجاز نیست.", 400)
    try:
        message = _DISPATCH[action](request, target, params)
    except MobileError as exc:
        log_action(request, action, target, params, ok=False, message=exc.message)
        raise
    log_action(request, action, target, params, ok=True, message=message)
    return {"ok": True, "action": action, "target": target, "message": message}


def _need_target(target):
    if not target:
        raise MobileError("missing_fields", "شناسهٔ هدف لازم است.", 400)


def _job_cancel(request, target, params):
    from apps.jobs import cancellation
    from apps.jobs.models import Job

    _need_target(target)
    job = Job.objects.filter(pk=int(target)).first() if target.isdigit() else None
    if job is None:
        raise MobileError("target_not_found", "این کار پیدا نشد.", 404)
    if job.state in (Job.State.COMPLETED, Job.State.CANCELLED, Job.State.FAILED):
        raise MobileError("bad_state", "این کار دیگر در جریان نیست.", 409)
    cancellation.cancel(job, actor=request.user)
    return "کار لغو شد."


def _compute_job(target):
    from apps.compute.models import ComputeJob

    _need_target(target)
    try:
        job = ComputeJob.objects.filter(uid=target).first()
    except Exception:  # noqa: BLE001 - malformed uuid
        job = None
    if job is None:
        raise MobileError("target_not_found", "این کارِ پردازشی پیدا نشد.", 404)
    return job


def _compute_cancel(request, target, params):
    from apps.compute import services as sv

    job = _compute_job(target)
    if job.final:
        raise MobileError("bad_state", "این کارِ پردازشی تمام شده است.", 409)
    sv.cancel(job)
    return "کارِ پردازشی لغو شد."


def _compute_retry(request, target, params):
    from apps.compute.models import ComputeJob

    job = _compute_job(target)
    if job.state not in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
        raise MobileError("bad_state", "فقط کارِ ناموفق یا لغوشده دوباره در صف می‌رود.", 409)
    job.state, job.node, job.claimed_at, job.finished_at = ComputeJob.State.QUEUED, None, None, None
    job.attempts, job.error, job.cancel_requested, job.progress = 0, "", False, 0.0
    # صفِ ماندگار (compute-r1): انتظار از همین لحظه حساب شود و «قطعِ گره»های قبلی پاک شوند
    job.lost_count, job.queued_at, job.waited_s, job.run_s = 0, timezone.now(), None, None
    job.message = "دوباره در صف (از موبایل)"
    job.save()
    return "کار دوباره در صف گذاشته شد."


def _node(target):
    from apps.compute.models import ComputeNode

    _need_target(target)
    node = ComputeNode.objects.filter(pk=int(target)).first() if target.isdigit() else None
    if node is None:
        raise MobileError("target_not_found", "این سرورِ پردازش پیدا نشد.", 404)
    return node


def _node_disable(request, target, params):
    node = _node(target)
    node.enabled = False
    node.save(update_fields=["enabled", "updated_at"])
    return f"سرورِ «{node.name}» متوقف شد."


def _node_enable(request, target, params):
    node = _node(target)
    node.enabled = True
    node.save(update_fields=["enabled", "updated_at"])
    return f"سرورِ «{node.name}» دوباره فعال شد."


def _ai_reset(request, target, params):
    from services.ai import priority

    provider = params.get("provider")
    n = priority.reset(provider if provider in priority.PROVIDERS else None)
    return "مسیرهای کنارگذاشته آزاد شدند." if n else "مسیری کنار گذاشته نشده بود."


def _sms_pause(request, target, params):
    s = MobileSettings.get()
    s.sms_enabled = False
    s.save(update_fields=["sms_enabled"])
    return "صفِ پیامک متوقف شد."


def _sms_resume(request, target, params):
    s = MobileSettings.get()
    s.sms_enabled = True
    s.save(update_fields=["sms_enabled"])
    return "صفِ پیامک دوباره کار می‌کند."


def _sms_cancel(request, target, params):
    from . import sms

    _need_target(target)
    try:
        msg = SmsMessage.objects.filter(uid=target).first()
    except Exception:  # noqa: BLE001
        msg = None
    if msg is None:
        raise MobileError("target_not_found", "این پیامک پیدا نشد.", 404)
    if not sms.cancel(msg):
        raise MobileError("bad_state", "فقط پیامکِ در صف لغو می‌شود.", 409)
    return "پیامک لغو شد."


_DISPATCH = {
    "job.cancel": _job_cancel, "compute_job.cancel": _compute_cancel, "compute_job.retry": _compute_retry,
    "compute_node.disable": _node_disable, "compute_node.enable": _node_enable, "ai.reset_circuit": _ai_reset,
    "sms.pause": _sms_pause, "sms.resume": _sms_resume, "sms.cancel": _sms_cancel,
}
