"""«پارک»: کارِ کاربر که به سرورِ پردازش نیاز دارد و سرور خاموش است، شکست نمی‌خورد؛ در صف می‌ماند.

مسئله: کارهای Celery (ساختِ تصویر/ویدیو، تحلیلِ هوشمند…) وقتی هیچ مسیری جواب نمی‌داد (سرورِ پردازش خاموش + اعتبارِ ابری
تمام) با «ناموفق» تمام می‌شدند. نخِ Celery را هم نمی‌شود روزها منتظر نگه داشت (فقط ۴ نخ داریم برای همهٔ کارها).

راه‌حل: خطایی که نشانهٔ `node_waiting` دارد (NodeWaiting، ComfyUIUnavailable با سرورِ شناخته‌شدهٔ خاموش،
AllProvidersFailed وقتی لوکال خاموش است) در `Job.mark_failed` به `maybe_park` می‌رسد:

  * ردیفِ Job «در صف — منتظرِ روشن شدنِ سرورِ پردازش» می‌شود (و ریپرِ کارهای مرده آن را نمی‌کُشد)؛
  * یک «کارِ منتظر» (ComputeJob با kind=wait.node) ساخته می‌شود تا در «صفِ پردازش» دیده شود، شمرده شود و لغو شود؛
  * نخِ Celery آزاد می‌شود. هر دقیقه `wake_parked` (از maintenance) می‌بیند سرورِ توانا روشن شده یا نه و همان تسکِ Celery را
    با همان آرگومان‌ها دوباره می‌فرستد.

کارهای ComputeJob واقعی (ولی «wait.node» نه) از قبل ماندگارند: در صف می‌مانند و گره که وصل شد می‌گیرد.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import services as SV
from .dbretry import call_with_retry
from .models import ComputeJob

logger = logging.getLogger(__name__)

PARK_KIND = "wait.node"
#: سقفِ کارهای هم‌زمان منتظر (از این بیشتر ⇒ مثلِ قبل «ناموفق»، تا صف بی‌حساب پر نشود)
MAX_PARKED = int(getattr(settings, "NM_COMPUTE_MAX_PARKED", 200))
#: کارِ فرستاده‌شدهٔ دوباره که ده دقیقه بعد هنوز «در صف» است ⇒ نشانهٔ منتظر برداشته شود
DISPATCH_GRACE_S = 600
#: وقتی سرور روشن می‌شود و ده‌ها کارِ منتظر هست، همه را یک‌جا نمی‌فرستیم (Celery چهار نخ دارد و SQLite یک نویسنده):
#: در هر دقیقه حداکثر این‌قدر (به ترتیبِ نوبت)؛ ۲۴ کار ≈ سه دقیقه
WAKE_BATCH = int(getattr(settings, "NM_COMPUTE_WAKE_BATCH", 8))
#: متنِ هوشمند (ollama) روی یک گره پشتِ‌سرهم اجرا می‌شود و هر تسک فقط ۴۵ ثانیه منتظرِ برداشته‌شدنِ کارش می‌ماند؛ پس از آن‌ها
#: در هر دقیقه کمتر بیدار می‌کنیم تا ردیفِ آخر بیهوده منقضی و دوباره پارک نشود
WAKE_BATCH_BY_CAP = {"ollama": 3}


def _flag_of(error) -> str:
    """قابلیتِ لازم اگر این خطا «منتظرِ سرور» است، وگرنه ''."""
    if error is None or isinstance(error, str):
        return ""
    for e in (error, getattr(error, "__cause__", None), getattr(error, "__context__", None)):
        cap = getattr(e, "node_waiting", "")
        if cap:
            return str(cap)
    return ""


def _current_task():
    try:
        from celery import current_task
        task = current_task
        if task is None or not getattr(task, "request", None):
            return None
        if getattr(task.request, "called_directly", True) or not getattr(task.request, "id", None):
            return None
        return task
    except Exception:  # noqa: BLE001
        return None


def maybe_park(job, error) -> bool:
    """از `apps.jobs.models.Job.mark_failed` صدا زده می‌شود. True ⇒ کار پارک شد و «ناموفق» ثبت نشود."""
    cap = _flag_of(error)
    if not cap:
        return False
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return False                       # بی‌صفِ واقعیِ Celery کسی بعداً دوباره اجرایش نمی‌کند
    task = _current_task()
    if task is None:
        return False
    try:
        if job.cancel_pending():
            return False
        if cap != "any" and not SV.known_nodes(cap):
            return False                   # هیچ سروری با این توانایی اصلاً ثبت نیست؛ منتظرِ هیچ نمی‌مانیم
        if ComputeJob.objects.filter(kind=PARK_KIND, state=ComputeJob.State.QUEUED).count() >= MAX_PARKED:
            return False
        payload = {
            "capability": cap, "task": task.name, "args": list(task.request.args or ()),
            "kwargs": dict(task.request.kwargs or {}),
            "queue": (getattr(task.request, "delivery_info", None) or {}).get("routing_key") or "",
            "ref": {"model": "jobs.Job", "id": job.pk}, "title": job.get_type_display(),
            "message": str(error)[:300],
        }
        json.dumps(payload)                # باید قابلِ ذخیره و ارسالِ دوباره باشد
    except Exception as exc:  # noqa: BLE001
        logger.info("park: not parking job %s: %s", getattr(job, "pk", "?"), exc)
        return False
    from apps.jobs.models import Job
    now = timezone.now()
    def _write():
        with transaction.atomic():
            old = [ph for ph in ComputeJob.objects.filter(kind=PARK_KIND, state=ComputeJob.State.QUEUED)
                   if (ph.payload or {}).get("ref") == payload["ref"]]
            if old:
                ph = old[0]
                ph.payload = payload
                ph.save(update_fields=["payload", "updated_at"])
            else:
                ph = ComputeJob.objects.create(
                    kind=PARK_KIND, payload=payload, origin="park", store=getattr(job, "store", None), priority=100,
                    state=ComputeJob.State.QUEUED, queued_at=now, message=SV.NO_NODE_QUEUED_TEXT,
                    request_hash="", timeout_s=0)
            ctx = dict(job.context or {})
            ctx["node_wait"] = {"since": ctx.get("node_wait", {}).get("since") or now.isoformat(), "cap": cap,
                                "park": str(ph.uid)}
            job.state = Job.State.QUEUED
            job.current_step_label = SV.NO_NODE_QUEUED_TEXT
            job.error = ""
            job.context = ctx
            job.save(update_fields=["state", "current_step_label", "error", "context", "updated_at"])
        return ph

    ph = call_with_retry(_write, _what="park")
    logger.info("park: job %s waits for a '%s' node (placeholder %s)", job.pk, cap, ph.uid)
    return True


def _row(ref: dict):
    if (ref or {}).get("model") == "jobs.Job":
        from apps.jobs.models import Job
        return Job.objects.filter(pk=ref.get("id")).first()
    return None


def on_cancelled(ph: ComputeJob) -> None:
    """کارِ منتظر در صفِ پردازش لغو شد ⇒ Job ِ کاربر هم لغو شود (اعتبارِ رزرو شده پس می‌آید)."""
    if ph.kind != PARK_KIND:
        return
    row = _row((ph.payload or {}).get("ref"))
    if row is None:
        return
    from apps.jobs import cancellation, machine
    if row.state not in machine.TERMINAL:
        cancellation.cancel(row, reason="در صفِ پردازش لغو شد.")


def on_expired(ph: ComputeJob) -> None:
    """سقفِ انتظار (اختیاری) تمام شد ⇒ Job ِ کاربر ناموفق شود، با پیامِ روشن."""
    if ph.kind != PARK_KIND:
        return
    row = _row((ph.payload or {}).get("ref"))
    if row is not None:
        from apps.jobs import machine
        if row.state not in machine.TERMINAL:
            row.mark_failed(ph.error or "مهلتِ انتظار برای سرورِ پردازش تمام شد.")


def _dispatch(ph: ComputeJob, payload: dict) -> bool:
    try:
        from celery import current_app
        kwargs = {"args": payload.get("args") or [], "kwargs": payload.get("kwargs") or {}}
        if payload.get("queue"):
            kwargs["queue"] = payload["queue"]
        current_app.send_task(payload["task"], **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 — فردا دوباره امتحان می‌شود
        logger.warning("park: could not re-dispatch %s: %s", payload.get("task"), exc)
        return False


def wake_parked() -> int:
    """هر دقیقه: برای هر «کارِ منتظر» که سرورِ توانایش آنلاین شده، همان تسکِ Celery را دوباره بفرست.
    کارِ لغوشده (از خودِ صفحهٔ کاربر) دوباره فرستاده نمی‌شود."""
    from apps.jobs import machine
    n = 0
    woken: dict = {}
    now = timezone.now()
    for ph in ComputeJob.objects.filter(kind=PARK_KIND, state=ComputeJob.State.QUEUED).order_by("created_at"):
        payload = ph.payload or {}
        row = _row(payload.get("ref"))
        if row is None or row.state in machine.TERMINAL or row.cancel_requested:
            call_with_retry(ComputeJob.objects.filter(pk=ph.pk, state=ComputeJob.State.QUEUED).update,
                            state=ComputeJob.State.CANCELLED, finished_at=now, message="لغو شد")
            if row is not None and row.state not in machine.TERMINAL:
                from apps.jobs import cancellation
                cancellation.cancel(row, reason="توسط کاربر لغو شد.")
            continue
        cap = payload.get("capability") or "any"
        if cap != "any" and not SV.online_nodes(cap):
            continue
        if n >= WAKE_BATCH:
            break                          # بقیه در دقیقهٔ بعد؛ همان ترتیبِ نوبت
        if woken.get(cap, 0) >= WAKE_BATCH_BY_CAP.get(cap, WAKE_BATCH):
            continue                       # سهمِ این توانایی در این دقیقه پر شد؛ توانایی‌های دیگر ادامه می‌دهند
        if not _dispatch(ph, payload):
            continue
        woken[cap] = woken.get(cap, 0) + 1
        waited = round(max(0.0, (now - (ph.queued_at or ph.created_at)).total_seconds()), 1)
        ctx = dict(row.context or {})
        nw = dict(ctx.get("node_wait") or {})
        nw["dispatched_at"] = now.isoformat()
        ctx["node_wait"] = nw
        row.current_step_label = "سرورِ پردازش روشن شد؛ در حال شروع…"
        row.context = ctx
        call_with_retry(row.save, update_fields=["current_step_label", "context", "updated_at"])
        call_with_retry(ph.delete)        # کارِ منتظر تمام شد؛ ردیفِ موقت لازم نیست
        n += 1
        logger.info("park: woke job %s after %ss", row.pk, waited)
    n += _release_stuck(now)
    return n


def _release_stuck(now) -> int:
    """نشانهٔ «منتظرِ گره» روی Jobی که ده دقیقه پس از ارسالِ دوباره هنوز QUEUED است برداشته می‌شود (ریپر دوباره بررسی‌اش کند)."""
    from apps.jobs.models import Job
    n = 0
    try:
        stuck = Job.objects.filter(state=Job.State.QUEUED, context__has_key="node_wait")
        live = {str((p.payload or {}).get("ref", {}).get("id")) for p in
                ComputeJob.objects.filter(kind=PARK_KIND, state=ComputeJob.State.QUEUED)}
        for row in stuck:
            nw = (row.context or {}).get("node_wait") or {}
            at = nw.get("dispatched_at")
            if not at or str(row.pk) in live:
                continue
            from django.utils.dateparse import parse_datetime
            when = parse_datetime(at)
            if when and (now - when).total_seconds() > DISPATCH_GRACE_S:
                ctx = dict(row.context or {})
                ctx.pop("node_wait", None)
                row.context = ctx
                call_with_retry(row.save, update_fields=["context", "updated_at"])
                n += 1
    except Exception as exc:  # noqa: BLE001 — فقط نظافت است
        logger.debug("park: stuck sweep skipped: %s", exc)
    return n


# ───────────────────────────── دروازه‌ها (ابتدای تسک)

def gate(job, capability: str, message: str = "") -> bool:
    """ابتدای یک تسکِ Celery: اگر سرورِ توانا آنلاین نیست (و چنین سروری ثبت است) کار پارک می‌شود و True برمی‌گردد؛
    تسک باید فوراً `return` کند. وگرنه False و تسک ادامه می‌دهد (مثلِ قدیم)."""
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return False
    if SV.online_nodes(capability):
        return False
    return maybe_park(job, SV.NodeWaiting(message, capability))


def gate_comfy(job) -> bool:
    """دروازهٔ ComfyUI: فقط وقتی تولیدِ تصویر/ویدیو واقعاً روی سرورِ پردازش (agent://) انجام می‌شود."""
    try:
        url = str((getattr(settings, "UPMARKET_AI", {}) or {}).get("COMFYUI_BASE_URL") or "")
    except Exception:  # noqa: BLE001
        url = ""
    if not url.startswith("agent://"):
        return False
    return gate(job, "comfyui")
