"""«پردازشِ دوباره» برای کارهای فروشگاه (Job) که ناموفق شده‌اند یا لغو شده‌اند.

مالک (۱۴۰۵/۰۸/۱۷): «کاری که ناموفق یا لغو شده بود بشه پردازش دوباره رو زد».

یک Job خودش نمی‌داند کدام تسکِ Celery و با چه ورودی‌هایی اجرا شده بود؛ آن را فقط view ِ سازنده می‌دانست. پس:

1. هر بار که تسکی شروع می‌شود که پارامترِ اولش `job_id` است (سیگنالِ `task_prerun`)، نام و ورودی‌های همان تسک در
   `Job.context["_task"]` نوشته می‌شود. این برای هر راهی که کار را فرستاده درست است (view، بیدار شدن از صفِ منتظرِ
   گره، api_platform، اسکریپت).
2. برای کارهای قدیمی که پیش از این ثبت ناموفق شده‌اند: اگر ردیفِ «کارِ منتظرِ سرورِ پردازش» (wait.node) هنوز هست، همان
   ورودی‌ها از آن خوانده می‌شود؛ وگرنه برای نوع‌هایی که ورودی‌شان در context هست، از روی context ساخته می‌شود.

دوباره‌اجرا یعنی همان تسک با همان ورودی‌ها، روی همان ردیفِ Job (شمارهٔ کار عوض نمی‌شود، retry_count یکی بالا می‌رود و
تاریخچهٔ خطاها در `context["_retries"]` می‌ماند). اعتبار را خودِ تسک دوباره رزرو می‌کند، مثلِ بارِ اول؛ پس لغو و دوباره‌زدن
اعتبارِ مجانی نمی‌سازد.

این تنها راهِ خروج از FAILED/CANCELLED است و عمداً از `Job.advance()` نمی‌گذرد: ماشینِ وضعیت می‌گوید «از پایان برنمی‌گردد»
و برای یک اجرای عادی هم درست می‌گوید؛ دوباره‌اجرا یک تلاشِ تازه است، نه ادامهٔ قبلی.

همان سیگنال شناسهٔ Job ِ در حالِ اجرا را برای همان نخ نگه می‌دارد (`current_job_id`) تا کارهایی که این تسک برای سرورِ
پردازش می‌سازد (ComputeJob.job_ref) بدانند مالِ کدام کارِ فروشگاه‌اند، و «پردازشِ دوباره» در صفِ پردازش به کارِ اصلی برسد.
"""
from __future__ import annotations

import importlib
import inspect
import json
import logging
import threading

from django.db.models import F
from django.utils import timezone

from .models import Job

logger = logging.getLogger(__name__)

TASK_KEY = "_task"
RETRIES_KEY = "_retries"
FIRST_CREATED_KEY = "_first_created_at"
RETRYABLE_STATES = (Job.State.FAILED, Job.State.CANCELLED)
RETRY_LABEL = "دوباره در صف — منتظرِ شروع…"

_local = threading.local()
_PARAM_CACHE: dict[str, bool] = {}


class RetryError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ───────────────────────────── ثبتِ تسک (سیگنال‌های Celery)

def current_job_id() -> int | None:
    """شناسهٔ Job ِ تسکی که همین حالا در همین نخ اجرا می‌شود (یا None)."""
    return getattr(_local, "job_id", None)


def _takes_job_id(task) -> bool:
    name = getattr(task, "name", "") or ""
    if name in _PARAM_CACHE:
        return _PARAM_CACHE[name]
    ok = False
    try:
        params = [p for p in inspect.signature(task.run).parameters if p != "self"]
        ok = bool(params) and params[0] == "job_id"
    except (TypeError, ValueError, AttributeError):
        ok = False
    _PARAM_CACHE[name] = ok
    return ok


def _jsonable(value):
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return None


def _job_id_of(args, kwargs):
    raw = args[0] if args else (kwargs or {}).get("job_id")
    if isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def record(job_id: int, name: str, args, kwargs) -> bool:
    """`Job.context["_task"]` = {name, args, kwargs}. فقط وقتی عوض شده می‌نویسد (یک UPDATE ِ کوچک)."""
    from apps.compute.dbretry import call_with_retry

    rec = {"name": name, "args": _jsonable(list(args or [])), "kwargs": _jsonable(dict(kwargs or {}))}
    if rec["args"] is None or rec["kwargs"] is None:
        return False
    row = Job.objects.filter(pk=job_id).only("id", "context").first()
    if row is None:
        return False
    ctx = dict(row.context or {})
    if ctx.get(TASK_KEY) == rec:
        return False
    ctx[TASK_KEY] = rec
    call_with_retry(Job.objects.filter(pk=job_id).update, context=ctx, _what="Job._task")
    return True


def on_task_prerun(sender=None, task_id=None, task=None, args=None, kwargs=None, **_extra):
    _local.job_id = None
    try:
        if task is None or not _takes_job_id(task):
            return
        jid = _job_id_of(args or [], kwargs or {})
        if jid is None:
            return
        _local.job_id = jid
        record(jid, task.name, args or [], kwargs or {})
    except Exception as exc:  # noqa: BLE001 — ثبت فرعی است؛ نباید خودِ کار را بخواباند
        logger.debug("retry: could not record task %s: %s", getattr(task, "name", task), exc)


def on_task_postrun(**_extra):
    _local.job_id = None


def connect_signals() -> None:
    try:
        from celery.signals import task_postrun, task_prerun
    except Exception:  # noqa: BLE001 — بی Celery (آزمون‌های خاص) فقط ثبت نمی‌شود
        return
    task_prerun.connect(on_task_prerun, weak=False, dispatch_uid="jobs.retry.prerun")
    task_postrun.connect(on_task_postrun, weak=False, dispatch_uid="jobs.retry.postrun")


# ───────────────────────────── «همان کار با همان ورودی‌ها»

def _ctx(job: Job) -> dict:
    return job.context or {}


def _need(*values):
    return all(v not in (None, "") for v in values)


def _b_product_analysis(job):
    pid = _ctx(job).get("product_id")
    return ("apps.ai.tasks.analyze_product_task", [job.id, pid], {}) if _need(pid) else None


def _b_market_analysis(job):
    c = _ctx(job)
    pid = c.get("product_id")
    return ("apps.ai.tasks.analyze_market_task", [job.id, pid, c.get("research_inputs") or ""], {}) if _need(pid) else None


def _b_captions(job):
    c = _ctx(job)
    pid = c.get("product_id")
    if not _need(pid):
        return None
    return ("apps.content.tasks.generate_captions_task",
            [job.id, pid, c.get("platforms") or [], c.get("tone") or "", c.get("objective") or "",
             c.get("image_id"), c.get("video_script_id")], {})


def _b_image(job):
    c = _ctx(job)
    pid, kind = c.get("product_id"), c.get("kind")
    if not _need(pid, kind):
        return None
    return ("apps.content.tasks.generate_image_task",
            [job.id, pid, kind, c.get("style") or "", c.get("instructions") or "", c.get("source_image_id")], {})


def _b_script(job):
    c = _ctx(job)
    pid = c.get("product_id")
    if not _need(pid):
        return None
    return ("apps.content.tasks.generate_video_script_task",
            [job.id, pid, c.get("duration") or 30, c.get("objective") or "", c.get("language") or "fa"], {})


def _b_video(job):
    sid = _ctx(job).get("script_id")
    return ("apps.content.tasks.generate_video_task", [job.id, sid], {}) if _need(sid) else None


def _b_voice(job):
    sid = _ctx(job).get("script_id")
    return ("apps.content.tasks.generate_voice_task", [job.id, sid], {}) if _need(sid) else None


def _b_embeddings(job):
    return ("apps.ai.tasks.build_embeddings_task", [job.id, job.store_id], {})


#: نوع ⇒ ساختنِ (تسک، ورودی‌ها) از روی context، فقط برای کارهایی که پیش از ثبتِ خودکار ناموفق شده‌اند
BUILDERS = {
    Job.Type.PRODUCT_ANALYSIS: _b_product_analysis,
    Job.Type.MARKET_ANALYSIS: _b_market_analysis,
    Job.Type.CAPTION_GENERATION: _b_captions,
    Job.Type.IMAGE_GENERATION: _b_image,
    Job.Type.VIDEO_SCRIPT: _b_script,
    Job.Type.VIDEO_GENERATION: _b_video,
    Job.Type.VIDEO_SEGMENT: _b_video,
    Job.Type.VOICE_GENERATION: _b_voice,
    Job.Type.EMBEDDING_BUILD: _b_embeddings,
}


def _recorded(job: Job):
    rec = _ctx(job).get(TASK_KEY)
    if not isinstance(rec, dict) or not rec.get("name"):
        return None
    args = rec.get("args") if isinstance(rec.get("args"), list) else []
    kwargs = rec.get("kwargs") if isinstance(rec.get("kwargs"), dict) else {}
    if _job_id_of(args, kwargs) != job.id:
        return None
    return str(rec["name"]), list(args), dict(kwargs)


def _from_park(job: Job):
    """ردیفِ «کارِ منتظرِ سرورِ پردازش» (wait.node) نام و ورودی‌های تسک را دارد؛ ردیف‌های لغوشده می‌مانند."""
    try:
        from apps.compute.models import ComputeJob
        from apps.compute.park import PARK_KIND
    except Exception:  # noqa: BLE001
        return None
    ph = (ComputeJob.objects.filter(kind=PARK_KIND, payload__ref__id=job.id, payload__ref__model="jobs.Job")
          .order_by("-created_at").first())
    if ph is None:
        return None
    p = ph.payload or {}
    args = p.get("args") if isinstance(p.get("args"), list) else []
    kwargs = p.get("kwargs") if isinstance(p.get("kwargs"), dict) else {}
    if not p.get("task") or _job_id_of(args, kwargs) != job.id:
        return None
    return str(p["task"]), list(args), dict(kwargs)


def plan_for(job: Job, *, deep: bool = True):
    """(نامِ تسک، args، kwargs) یا None. deep=False: بی پرس‌وجوی اضافه (برای فهرست‌ها)."""
    plan = _recorded(job)
    if plan is None and deep:
        plan = _from_park(job)
    if plan is None:
        builder = BUILDERS.get(job.type)
        plan = builder(job) if builder else None
    return plan


def can_retry(job: Job) -> bool:
    """دکمهٔ «پردازشِ دوباره» دیده شود؟ (ارزان: بی پرس‌وجوی پایگاه‌داده)"""
    return job.state in RETRYABLE_STATES and plan_for(job, deep=False) is not None


def why_not(job: Job) -> str:
    if job.state not in RETRYABLE_STATES:
        return "فقط کارِ ناموفق یا لغوشده دوباره پردازش می‌شود."
    return "ورودی‌های این کار ثبت نشده؛ از همان صفحه‌ای که ساختید دوباره بسازید."


# ───────────────────────────── اجرا

def _resolve(name: str):
    try:
        from celery import current_app

        task = current_app.tasks.get(name)
        if task is not None:
            return task
    except Exception:  # noqa: BLE001
        pass
    module, _, attr = name.rpartition(".")
    try:
        return getattr(importlib.import_module(module), attr)
    except Exception:  # noqa: BLE001
        return None


def _queue_problem() -> str:
    from . import services as JS

    if JS.eager_mode():
        return ""
    if not JS.broker_reachable():
        return "صفِ پردازش (Redis) در دسترس نیست؛ چند دقیقهٔ دیگر دوباره بزنید."
    if not JS.workers_online():
        return "کارگرِ صفِ سایت روشن نیست؛ چند دقیقهٔ دیگر دوباره بزنید."
    return ""


def retry(job: Job, actor=None) -> Job:
    """همان تسک با همان ورودی‌ها دوباره فرستاده می‌شود. RetryError با پیامِ فارسی اگر نشود."""
    from apps.compute.dbretry import call_with_retry

    if job.state not in RETRYABLE_STATES:
        raise RetryError(why_not(job), 409)
    plan = plan_for(job)
    if plan is None:
        raise RetryError(why_not(job))
    name, args, kwargs = plan
    task = _resolve(name)
    if task is None:
        raise RetryError("این نوع کار دیگر در برنامه نیست؛ از صفحهٔ خودش دوباره بسازید.")
    problem = _queue_problem()
    if problem:
        raise RetryError(problem, 503)

    now = timezone.now()
    ctx = dict(job.context or {})
    ctx.pop("node_wait", None)
    ctx.setdefault(FIRST_CREATED_KEY, job.created_at.isoformat() if job.created_at else now.isoformat())
    history = list(ctx.get(RETRIES_KEY) or [])[-4:]
    history.append({"at": now.isoformat(), "from": job.state, "error": (job.error or "")[:300],
                    "by": getattr(actor, "pk", None)})
    ctx[RETRIES_KEY] = history
    ctx[TASK_KEY] = {"name": name, "args": args, "kwargs": kwargs}
    # created_at هم تازه می‌شود: «در صف ماندنِ بیش از حد» (staleness) از created_at حساب می‌شود و کارِ دیروز را بلافاصله مرده
    # می‌شمرد؛ زمانِ ساختِ اول در context می‌ماند.
    moved = call_with_retry(
        Job.objects.filter(pk=job.pk, state__in=RETRYABLE_STATES).update,
        state=Job.State.QUEUED, error="", progress_step=0, current_step_label=RETRY_LABEL, cancel_requested=False,
        retry_count=F("retry_count") + 1, context=ctx, created_at=now, updated_at=now, _what="Job retry")
    if not moved:
        raise RetryError("وضعیتِ این کار همین حالا عوض شد؛ صفحه را تازه کنید.", 409)
    try:
        result = task.apply_async(args=args, kwargs=kwargs)
    except Exception as exc:  # noqa: BLE001 — صادق: کار دوباره ناموفق نشان داده می‌شود
        logger.warning("retry: dispatch of %s for job %s failed: %s", name, job.pk, exc)
        job.refresh_from_db()
        job.mark_failed(f"اجرای دوباره شروع نشد ({exc}).")
        raise RetryError("اجرای دوباره شروع نشد؛ چند دقیقهٔ دیگر دوباره بزنید.", 503)
    tid = str(getattr(result, "id", "") or "")
    if tid:
        call_with_retry(Job.objects.filter(pk=job.pk).update, celery_task_id=tid, _what="Job retry task id")
    logger.info("retry: job %s (%s) dispatched again as %s", job.pk, job.type, name)
    job.refresh_from_db()
    return job


def retry_many(jobs, actor=None, limit: int = 100) -> dict:
    """«پردازشِ دوبارهٔ همه»: تک‌تک، با شمارشِ موفق/ردشده و چند پیامِ خطا."""
    out = {"retried": 0, "skipped": 0, "errors": []}
    for job in list(jobs)[:limit]:
        if not can_retry(job) and plan_for(job) is None:
            out["skipped"] += 1
            continue
        try:
            retry(job, actor=actor)
            out["retried"] += 1
        except RetryError as exc:
            out["skipped"] += 1
            if exc.message not in out["errors"] and len(out["errors"]) < 5:
                out["errors"].append(exc.message)
            if exc.status == 503:          # صف خاموش است؛ بقیه هم نمی‌روند
                break
    return out
