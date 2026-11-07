# -*- coding: utf-8 -*-
"""دانلودِ مدلِ لوکال از پنل: کارِ `ollama.pull` در صفِ سرورِ پردازش (۱۴۰۵/۰۸/۱۲).

مالک با خطِ فرمان راحت نیست؛ دکمهٔ «دانلود مدل» در کارتِ اولویتِ هوش مصنوعی یک کارِ `ollama.pull` در صفِ apps.compute می‌گذارد.
عاملِ سرورِ پردازش (processing/agent.py، نسخهٔ ≥ همین تغییر) آن را با API ِ خودِ Ollama (`POST /api/pull`، همان مسیرِ
`ollama pull`) اجرا می‌کند و درصد/مگابایت/سرعت را با `progress` به سایت می‌فرستد (`ComputeJob.result["live"]`).

· فقط برچسب‌های فهرستِ مجاز (`model_catalog.pullable()`) — هم این‌جا رد می‌شود هم گره از سایت می‌پرسد (فهرست را از
  `GET /api/v1/compute/ollama/pullable/` می‌گیرد) و بیرونِ آن را نمی‌کشد؛ `compute.submit` هم این نوعِ کار را نمی‌پذیرد.
· گرهٔ خاموش هم می‌شود: کار در صف می‌ماند و وقتی گره روشن شد شروع می‌شود (پنل می‌گوید در صف است نه در حالِ دانلود).
· اجارهٔ بلند (`lease_s` ۳۰ دقیقه): عامل هر چند ثانیه progress می‌فرستد، پس وسطِ دانلود دوباره به صف نمی‌رود؛ اگر کامپیوتر خاموش
  شد، بعد از پایانِ اجاره کار به صف برمی‌گردد و Ollama از فایل‌های `-partial` ادامه می‌دهد (از صفر شروع نمی‌شود).
· عاملِ قدیمی (بی‌پرچمِ `ollama_pull` در گزارشش) پذیرفته نمی‌شود: به‌جای شکستِ «نوعِ کار را نمی‌شناسم»، پیامِ «Update.bat بزنید».
"""
from __future__ import annotations

import logging
import uuid as _uuid

from . import model_catalog

logger = logging.getLogger(__name__)

JOB_KIND = "ollama.pull"
LEASE_S = 1800            # اجارهٔ بلند؛ عامل هر ~۵ ثانیه progress می‌فرستد
TIMEOUT_S = 6 * 3600      # سقفِ کلِ یک دانلود
MAX_ATTEMPTS = 3          # اگر کامپیوتر وسطِ کار مرد، دوباره (ادامه از -partial)
RECENT_HOURS = 24

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class PullError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _fa(value) -> str:
    return str(value).translate(_FA)


def _gb_text(mb) -> str:
    return _fa(("%.1f" % (float(mb) / 1000.0)).replace(".", "٫"))


# ───────────────────────────── گره

def _same(a, b):
    from . import models_registry

    return models_registry._same_model(a, b)


def _nodes():
    from apps.compute.models import ComputeNode

    return [n for n in ComputeNode.objects.filter(enabled=True) if _ollama_capable(n)]


def _ollama_capable(node) -> bool:
    caps = node.capabilities or {}
    return bool(node.has("ollama") or caps.get("ollama_pull") or caps.get("ollama_models"))


def pull_ready(node) -> bool:
    """عاملِ این گره `ollama.pull` را بلد است (پرچمِ گزارشش)."""
    return bool((node.capabilities or {}).get("ollama_pull"))


def node_has_model(node, tag) -> bool | None:
    names = (node.capabilities or {}).get("ollama_models")
    if not names:
        return None
    return any(_same(tag, m) for m in names)


def choose_node(tag: str, node_name: str = ""):
    from apps.compute.models import ComputeNode

    if node_name:
        node = ComputeNode.objects.filter(name=node_name, enabled=True).first()
        if node is None:
            raise PullError("سرورِ پردازشِ «%s» پیدا نشد." % node_name, 404)
        return node
    nodes = _nodes()
    if not nodes:
        raise PullError("هیچ سرورِ پردازشی با Ollama ثبت نشده است.", 409)
    # آنلاین‌ها اول؛ بعد گره‌ای که این مدل را ندارد؛ بعد نام
    nodes.sort(key=lambda n: (not n.online, node_has_model(n, tag) is True, n.name))
    return nodes[0]


def node_summary() -> list[dict]:
    """برای پنل: هر گرهٔ توانا، آنلاین بودن، نسخهٔ عامل و آیا دانلود را بلد است."""
    out = []
    for n in _nodes():
        caps = n.capabilities or {}
        out.append({"id": n.pk, "name": n.name, "online": n.online, "agent": caps.get("agent") or "",
                    "pull_ready": pull_ready(n), "last_seen": n.last_seen.isoformat() if n.last_seen else None})
    return out


def update_hint(node) -> str:
    agent = (node.capabilities or {}).get("agent") or "نامعلوم"
    return ("عاملِ سرورِ پردازشِ «%s» (نسخهٔ %s) هنوز دانلودِ مدل را نمی‌شناسد. روی آن کامپیوتر فایلِ Update.bat را اجرا کنید "
            "(یا وقتی روشن شد در «سرورهای پردازش» دکمهٔ «به‌روزرسانی» را بزنید) و بعد دوباره «دانلود مدل» را بزنید."
            % (node.name, _fa(agent)))


# ───────────────────────────── شروع و لغو

def active_job(tag: str, node_name: str):
    from apps.compute.models import ComputeJob

    for job in ComputeJob.objects.filter(kind=JOB_KIND, node_wanted=node_name).exclude(state__in=ComputeJob.FINAL):
        if (job.payload or {}).get("tag") == tag:
            return job
    return None


def _reschedule(job, sched: dict) -> None:
    """کارِ هنوز-شروع‌نشده را به زمانِ تازه می‌برد (مثلاً «الان» روی دانلودی که برای شب زمان‌بندی شده بود)."""
    from apps.compute import schedule
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    payload = {**(job.payload or {}), **schedule.payload_fields(sched)}
    text = schedule.schedule_text(sched["not_before"], sched["window"])
    updated = ComputeJob.objects.filter(pk=job.pk, state=ComputeJob.State.QUEUED).update(
        not_before=sched["not_before"], window=sched["window"], category=schedule.CATEGORY, payload=payload,
        message=text or "در صف")
    if updated:
        try:
            (compute.job_root(job) / "package.zip").unlink(missing_ok=True)     # بستهٔ ساخته‌شده payload ِ کهنه دارد
        except OSError:
            pass
        job.refresh_from_db()


def start_pull(tag: str, node_name: str = "", when=None):
    """کارِ دانلود را در صف می‌گذارد (یا کارِ فعالِ همین مدل را برمی‌گرداند). ⇒ ComputeJob؛ خطا ⇒ PullError.

    `when` (اختیاری): زمانِ شروع — {"mode": "default|now|at|window", "time": "03:30"}؛ نبودنش = «طبقِ تنظیمِ کلیِ دانلودها»
    (apps.compute.schedule). کارِ زمان‌بندی‌شده تا زمانش در صف می‌ماند و گره آن را نمی‌گیرد."""
    from apps.compute import schedule
    from apps.compute import services as compute

    tag = (tag or "").strip()
    if not model_catalog.is_pullable(tag):
        raise PullError("«%s» در فهرستِ مجازِ دانلودِ سایت نیست؛ فقط مدل‌های فهرست از این‌جا دانلود می‌شوند." % (tag or "؟"), 400)
    try:
        sched = schedule.schedule_from_when(when)
    except schedule.ScheduleError as exc:
        raise PullError(exc.message, 400)
    node = choose_node(tag, node_name)
    existing = active_job(tag, node.name)
    if existing is not None:
        if when not in (None, "") and existing.state == "QUEUED":
            _reschedule(existing, sched)               # دانلودِ منتظر: زمانِ تازهٔ انتخاب‌شده جایگزین می‌شود
        return existing
    if not pull_ready(node):
        raise PullError(update_hint(node), 409)
    if node_has_model(node, tag) is True:
        raise PullError("مدلِ %s از قبل روی سرورِ پردازشِ «%s» نصب است." % (tag, node.name), 409)
    row = model_catalog.info(tag)
    payload = {"tag": tag, "label": row.get("label") or tag, "expected_bytes": int(row.get("size_mb") or 0) * 1_000_000,
               **schedule.payload_fields(sched)}        # window/not_before: عامل هم در پس‌زمینه از بازه بیرون نمی‌زند
    # require_online=False: گرهٔ خاموش هم کار را در صف می‌گذارد؛ هر وقت روشن شد شروع می‌کند
    job = compute.enqueue(JOB_KIND, payload, origin="ai_models", priority=30, timeout_s=TIMEOUT_S, node=node.name,
                          dedupe=False, require_online=False, not_before=sched["not_before"], window=sched["window"],
                          category=schedule.CATEGORY)
    job.lease_s = LEASE_S
    job.max_attempts = MAX_ATTEMPTS
    job.message = (schedule.schedule_text(sched["not_before"], sched["window"])
                   or ("در صف" if node.online else "در صف؛ سرورِ پردازش خاموش است"))
    job.save(update_fields=["lease_s", "max_attempts", "message"])
    logger.info("model pull queued: %s on %s (job %s, window=%r, not_before=%s)", tag, node.name, job.uid,
                sched["window"], sched["not_before"])
    return job


def pull_completed(job) -> None:
    """دانلود تمام شد: اگر مسیریاب پیش‌تر برای این مدل «نصب نیست» ثبت کرده بود (فهرستِ کهنه)، فراموش شود تا از همین حالا به کار برود."""
    from . import priority

    tag = (job.payload or {}).get("tag")
    if tag:
        priority.clear_model(tag)


def cancel_pull(uid: str):
    from apps.compute import services as compute
    from apps.compute.models import ComputeJob

    try:
        uid = _uuid.UUID(str(uid))
    except ValueError:
        raise PullError("چنین دانلودی پیدا نشد.", 404)
    job = ComputeJob.objects.filter(uid=uid, kind=JOB_KIND).first()
    if job is None:
        raise PullError("چنین دانلودی پیدا نشد.", 404)
    compute.cancel(job)
    job.refresh_from_db()
    return job


# ───────────────────────────── نمایش

_ERROR_CODES = ("DISK_FULL", "NOT_FOUND", "NOT_ALLOWED", "OLLAMA_DOWN", "NO_PROGRESS", "BAD_TAG")


def friendly_error(error: str) -> str:
    """خطای عامل «CODE: english | فارسی» ⇒ بخشِ فارسی؛ وگرنه متنِ کوتاه‌شده."""
    text = (error or "").strip()
    if " | " in text:
        return text.rsplit(" | ", 1)[1].strip()[:400]
    if text.startswith("JobError: "):
        text = text[len("JobError: "):]
    return text[:400]


def _scheduled_text(job) -> str:
    from apps.compute import schedule

    return schedule.schedule_text(job.not_before, job.window) if job.state == "QUEUED" else ""


def _live_text(live: dict, job, node_online: bool) -> str:
    phase = live.get("phase") or ""
    if job.state == "QUEUED":
        scheduled = _scheduled_text(job)
        if scheduled:
            return scheduled + ("؛ همان موقع خودکار شروع می‌شود." if node_online
                                else "؛ سرورِ پردازش تا آن موقع باید روشن باشد.")
        return "در صف است؛ " + ("سرورِ پردازش همین حالا شروعش می‌کند." if node_online
                                else "سرورِ پردازش خاموش است — همین که روشن شد دانلود شروع می‌شود.")
    if job.state in ("CLAIMED", "RUNNING") and not node_online:
        return "سرورِ پردازش وسطِ دانلود خاموش شد؛ وقتی روشن شود دانلود از همان‌جا ادامه می‌یابد."
    if phase in ("window", "scheduled"):
        return "منتظرِ بازهٔ دانلود%s؛ بعد از آن خودکار ادامه می‌یابد (آنچه گرفته شده می‌ماند)." % (
            (" — " + live["resume_text"]) if live.get("resume_text") else "")
    if phase == "manifest":
        return "در حال گرفتنِ مشخصاتِ مدل…"
    if phase == "verifying":
        return "دانلود تمام شد؛ در حال بررسیِ سلامتِ فایل…"
    if phase == "writing":
        return "در حال ثبتِ مدل در Ollama…"
    if phase == "waiting":
        return "منتظرِ پایانِ دانلودِ دیگر…"
    if phase == "retry":
        return "ارتباط قطع شد؛ تلاشِ دوباره (%s از %s) — از همان‌جا ادامه می‌یابد." % (
            _fa(live.get("attempt") or "؟"), _fa(live.get("max_attempts") or "؟"))
    if live.get("done") is not None and live.get("total"):
        speed = live.get("speed_mbs")
        text = "در حال دانلود: %s از %s گیگابایت (%s٪)" % (_gb_text(live["done"] / 1e6), _gb_text(live["total"] / 1e6),
                                                         _fa(round(100.0 * live["done"] / max(1, live["total"]))))
        if speed:
            text += " — %s مگابایت در ثانیه" % _fa(("%.1f" % float(speed)).replace(".", "٫"))
        return text
    return "در حال آماده‌سازی…"


def job_view(job) -> dict:
    from apps.compute.models import ComputeJob, ComputeNode

    live = (job.result or {}).get("live") or {}
    payload = job.payload or {}
    node = job.node or ComputeNode.objects.filter(name=job.node_wanted).first()
    node_online = bool(node and node.online)
    expected = int(payload.get("expected_bytes") or 0)
    done = live.get("done")
    total = live.get("total") or expected
    if job.state == "COMPLETED":
        percent = 100.0
    elif done is not None and total:
        percent = round(min(99.0, 100.0 * done / max(1, total)), 1)
    else:
        percent = round(job.progress * 100.0, 1) if job.state in ("CLAIMED", "RUNNING") else 0.0
    if job.state == "COMPLETED":
        text = "نصب شد."
    elif job.state == "FAILED":
        text = friendly_error(job.error) or "دانلود ناموفق بود."
    elif job.state == "CANCELLED":
        text = "لغو شد."
    else:
        text = _live_text(live, job, node_online)
    return {
        "uid": str(job.uid), "tag": payload.get("tag") or "", "label": payload.get("label") or payload.get("tag") or "",
        "state": job.state, "final": job.state in ComputeJob.FINAL, "percent": percent,
        "done_mb": round((done or 0) / 1e6) if done is not None else None,
        "total_mb": round(total / 1e6) if total else None,
        "speed_mbs": live.get("speed_mbs"), "phase": live.get("phase") or "",
        "node": node.name if node else job.node_wanted, "node_online": node_online,
        "waiting_for_node": job.state in ("QUEUED", "CLAIMED", "RUNNING") and not node_online,
        "attempts": job.attempts, "text": text,
        "scheduled_for": job.not_before.isoformat() if job.not_before else None, "window": job.window or "",
        "scheduled_text": _scheduled_text(job), "category": job.category,
        "error": friendly_error(job.error) if job.state == "FAILED" else "",
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def jobs_view(limit: int = 6) -> list[dict]:
    """دانلودهای فعال + چند دانلودِ اخیر (۲۴ ساعت)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.compute.models import ComputeJob

    try:
        since = timezone.now() - timedelta(hours=RECENT_HOURS)
        rows = list(ComputeJob.objects.filter(kind=JOB_KIND, created_at__gte=since).select_related("node")
                    .order_by("-created_at")[:max(1, limit)])
    except Exception as exc:  # noqa: BLE001 — جدول هنوز نیست
        logger.info("pull jobs unavailable: %s", exc)
        return []
    views = [job_view(j) for j in rows]
    views.sort(key=lambda v: (v["final"], ))     # فعال‌ها اول (sort پایدار: تازه‌ترین‌ها جلوتر می‌مانند)
    return views


def catalog_view(installed_by_tag=None) -> list[dict]:
    """فهرستِ مدل‌های مجاز با اندازه (برای نمایشِ اندازه پیش از دانلود)."""
    out = []
    for tag, row in model_catalog.pullable().items():
        out.append({"tag": tag, "label": row.get("label") or tag, "size_mb": int(row.get("size_mb") or 0),
                    "purpose": row.get("purpose") or "", "vision": bool(row.get("vision")),
                    "installed": (installed_by_tag or {}).get(tag)})
    return out
