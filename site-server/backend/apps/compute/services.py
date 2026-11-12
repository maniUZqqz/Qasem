"""منطقِ صفِ پردازش: ثبتِ کار، انتظار برای نتیجه، گرفتنِ کار توسطِ گره، خروجی و پایان."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .dbretry import call_with_retry, is_lock_error, retry_on_lock
from .models import ComputeJob, ComputeNode, capability_for

logger = logging.getLogger(__name__)


class ComputeError(Exception):
    pass


class ComputeUnavailable(ComputeError):
    """هیچ سرورِ پردازشی با این توانایی آنلاین نیست."""


class ComputeTimeout(ComputeError):
    pass


class ComputeFailed(ComputeError):
    pass


class ComputeCancelled(ComputeError):
    pass


class NodeWaiting(ComputeError):
    """کار به سرورِ پردازشی نیاز دارد که الان نیست؛ باید در صف بماند و بعداً اجرا شود (نه اینکه ناموفق شود).

    `node_waiting` = قابلیتِ لازم («ollama»، «comfyui»، …). Job.mark_failed (apps.jobs) این نشانه را می‌شناسد:
    به‌جای «ناموفق» کارِ کاربر را در صف می‌گذارد (apps.compute.park) تا با روشن شدنِ گره دوباره اجرا شود."""

    def __init__(self, message: str = "", capability: str = ""):
        super().__init__(message or NO_NODE_QUEUED_TEXT)
        self.node_waiting = capability or "any"


#: متنِ وضعیتِ کاری که منتظرِ روشن شدنِ سرورِ پردازش است
NO_NODE_QUEUED_TEXT = "در صف — منتظرِ روشن شدنِ سرورِ پردازش"
#: وقتی گره وسطِ کار قطع شد و کار به صف برگشت
LOST_NODE_TEXT = "سرورِ پردازش قطع شد؛ کار دوباره در صف است و با وصل شدنِ سرور ادامه می‌یابد"
#: چند بار قطعِ گره را «بی‌تقصیر» حساب کنیم؛ بعد از آن کار اگر هر بار عاملِ گره را می‌کُشد، تلاش حساب می‌شود
MAX_LOST_FREE = int(getattr(settings, "NM_COMPUTE_MAX_LOST", 8))
TEHRAN_OFFSET = timedelta(hours=3, minutes=30)      # ایران ساعتِ تابستانی ندارد (از ۱۴۰۱)


def data_root() -> Path:
    return Path(getattr(settings, "NM_DATA_DIR", Path(settings.MEDIA_ROOT).parent))


def job_root(job: ComputeJob) -> Path:
    root = data_root() / job.dir_rel
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    return root


def output_path(job: ComputeJob, name: str) -> Path:
    return job_root(job) / "outputs" / os.path.basename(name)


def output_url(job: ComputeJob, name: str) -> str:
    """نشانیِ خروجی برای پنل (فقط کاربرِ واردشده؛ apps.compute.api.output_file)."""
    return f"/api/v1/compute/jobs/{job.uid}/outputs/{os.path.basename(name)}"


def _file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def request_hash(kind: str, payload: dict, files: dict | None) -> str:
    """اثرِ انگشتِ درخواست: نوع + پارامترها (مرتب) + محتوای فایل‌های ورودی."""
    parts = [kind, json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)]
    for name in sorted(files or {}):
        parts.append(f"{name}:{_file_hash(files[name])}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# ───────────────────────────── ثبت و انتظار

def online_nodes(capability: str | None = None) -> list[ComputeNode]:
    nodes = [n for n in ComputeNode.objects.filter(enabled=True) if n.online]
    if capability and capability != "any":
        nodes = [n for n in nodes if n.has(capability)]
    return nodes


def known_nodes(capability: str | None = None) -> list[ComputeNode]:
    """گره‌های فعالِ ثبت‌شده که طبقِ آخرین گزارششان این قابلیت را دارند — روشن یا خاموش.
    صفِ ماندگار با همین می‌فهمد «سروری هست که روزی روشن شود» (پس کار منتظر می‌ماند) یا هیچ سرورِ توانایی ثبت نشده."""
    nodes = list(ComputeNode.objects.filter(enabled=True))
    if capability and capability != "any":
        nodes = [n for n in nodes if n.has(capability)]
    return nodes


# ───────────────────────────── بازهٔ زمانی (وقتِ تهران)

def parse_window(window: str):
    """«02:00-07:00» ⇒ (دقیقهٔ شروع، دقیقهٔ پایان) یا None اگر خالی/نامعتبر."""
    try:
        a, b = (window or "").strip().split("-")
        ah, am = a.split(":")
        bh, bm = b.split(":")
        if not (0 <= int(ah) < 24 and 0 <= int(bh) < 24 and 0 <= int(am) < 60 and 0 <= int(bm) < 60):
            return None
        start, end = int(ah) * 60 + int(am), int(bh) * 60 + int(bm)
        if start != end:
            return start, end
    except (ValueError, AttributeError):
        pass
    return None


def tehran_now(now=None):
    now = now or timezone.now()
    return now + TEHRAN_OFFSET        # «ساعتِ دیواری» تهران، روی یک datetime ِ aware ِ UTC (فقط برای ساعت و دقیقه)


def in_window(window: str, now=None) -> bool:
    """الان (وقتِ تهران) داخلِ بازه هست؟ بازهٔ خالی/نامعتبر ⇒ همیشه بله. بازهٔ نیمه‌شب (۲۲:۰۰-۰۴:۰۰) هم درست است."""
    parsed = parse_window(window)
    if not parsed:
        return True
    start, end = parsed
    t = tehran_now(now)
    minute = t.hour * 60 + t.minute
    return (start <= minute < end) if start < end else (minute >= start or minute < end)


def next_window_start(window: str, now=None):
    """نخستین لحظهٔ آینده (UTC) که بازه باز می‌شود؛ اگر الان باز است همان الان."""
    now = now or timezone.now()
    parsed = parse_window(window)
    if not parsed or in_window(window, now):
        return now
    start = parsed[0]
    t = tehran_now(now)
    base = t.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
    if base <= t:
        base += timedelta(days=1)
    return base - TEHRAN_OFFSET


def next_clock_time(hhmm: str, now=None):
    """«در ساعتِ ۰۳:۳۰» ⇒ نخستین لحظهٔ آیندهٔ UTC که ساعتِ تهران آن است؛ نامعتبر ⇒ None."""
    now = now or timezone.now()
    try:
        hh, mm = hhmm.strip().split(":")
        hh, mm = int(hh), int(mm)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return None
    except (ValueError, AttributeError):
        return None
    t = tehran_now(now)
    base = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if base <= t:
        base += timedelta(days=1)
    return base - TEHRAN_OFFSET


# ───────────────────────────── نوشتن‌های کوتاه و تکرارپذیر (SQLite «database is locked» ⇒ دوباره، نه ناموفق)

@retry_on_lock
def _insert(job: ComputeJob) -> None:
    job.save()


@retry_on_lock
def _save(job: ComputeJob, update_fields=None) -> None:
    if update_fields:
        job.save(update_fields=update_fields)
    else:
        job.save()


@retry_on_lock
def _claim_row(pk, node: ComputeNode, now) -> int:
    return ComputeJob.objects.filter(pk=pk, state=ComputeJob.State.QUEUED, node__isnull=True).update(
        state=ComputeJob.State.CLAIMED, node=node, claimed_at=now, heartbeat_at=now, attempts=F("attempts") + 1,
        message="گرفته شد توسطِ " + node.name)


@retry_on_lock
def _mark_waited(job: ComputeJob, now) -> None:
    job.refresh_from_db()
    waited = round(max(0.0, (now - (job.queued_at or job.created_at)).total_seconds()), 1)
    ComputeJob.objects.filter(pk=job.pk).update(waited_s=waited)
    job.waited_s = waited


@retry_on_lock
def _bump_jobs_done(node: ComputeNode) -> None:
    ComputeNode.objects.filter(pk=node.pk).update(jobs_done=F("jobs_done") + 1)


def enqueue(kind: str, payload: dict | None = None, files: dict | None = None, *, store=None, origin: str = "",
            priority: int = 100, timeout_s: int | None = None, node: str = "", dedupe: bool = True,
            dedupe_hours: int | None = None, require_online: bool = True, not_before=None, window: str = "",
            category: str = "", max_wait_s: int = 0, lease_s: int | None = None,
            max_attempts: int | None = None) -> ComputeJob:
    """یک کار در صف می‌گذارد (یا کارِ کاملِ هم‌ارزِ اخیر را برمی‌گرداند).

    `require_online=True` (پیش‌فرض، برای فراخوان‌هایی که همین الان جواب می‌خواهند) اگر هیچ گرهٔ آنلاینِ توانا نباشد
    ComputeUnavailable می‌دهد؛ `False` یعنی کار در صف می‌ماند تا گره روشن شود (صفِ ماندگار). برای «ثبتِ ماندگار» بهتر است
    enqueue_durable را صدا بزنید که فقط وقتی هیچ گره‌ای هرگز نمی‌تواند آن را بگیرد خطا می‌دهد."""
    payload = dict(payload or {})
    files = dict(files or {})
    capability = capability_for(kind)
    if require_online and not online_nodes(capability):
        raise ComputeUnavailable(
            f"هیچ سرورِ پردازشی با قابلیتِ «{capability}» آنلاین نیست. "
            "روی سرورِ پردازش START.bat را اجرا کنید یا در «سرورهای پردازش» وضعیت را ببینید."
        )
    h = request_hash(kind, payload, files)
    if dedupe:
        hours = dedupe_hours if dedupe_hours is not None else int(getattr(settings, "NM_COMPUTE_DEDUPE_HOURS", 72))
        since = timezone.now() - timedelta(hours=hours)
        previous = (ComputeJob.objects.filter(request_hash=h, state=ComputeJob.State.COMPLETED,
                                              finished_at__gte=since).order_by("-finished_at").first())
        # فقط کارِ کاملی که واقعاً خروجی دارد و فایل‌هایش هنوز هست؛ کارِ «تمام‌شدهٔ بی‌خروجی» وگرنه
        # تا ۷۲ ساعت هر درخواستِ یکسان را بی‌پردازش به همان شکست می‌فرستاد
        if previous and previous.outputs() and all(output_path(previous, o["name"]).is_file()
                                                   for o in previous.outputs()):
            logger.info("compute: reusing %s for identical %s request", previous.uid, kind)
            return previous
    job = ComputeJob(kind=kind, payload=payload, priority=priority, request_hash=h, origin=origin, store=store,
                     node_wanted=node or "", timeout_s=timeout_s or int(getattr(settings, "NM_COMPUTE_TIMEOUT", 1800)),
                     queued_at=timezone.now(), not_before=not_before, window=window or "", category=category or "",
                     max_wait_s=int(max_wait_s or 0))
    if lease_s:
        job.lease_s = int(lease_s)
    if max_attempts:
        job.max_attempts = int(max_attempts)
    if capability != "any" and not online_nodes(capability):
        job.message = NO_NODE_QUEUED_TEXT       # صفِ ماندگار: تا روشن شدنِ سرور همین‌جا می‌ماند
    # ورودی‌ها پیش از ردیف کپی می‌شوند و ردیف فقط یک بار و کامل ساخته می‌شود (با تکرار روی قفلِ SQLite): هیچ کاری
    # نیمه‌ساخته (بی‌inputs) نمی‌ماند، و اگر ساخت نشد پوشهٔ ورودی‌ها هم پاک می‌شود
    root = job_root(job)
    inputs = {}
    try:
        for name, src in files.items():
            safe = os.path.basename(name)
            shutil.copyfile(src, root / "inputs" / safe)
            inputs[safe] = f"inputs/{safe}"
        job.inputs = inputs
        _insert(job)
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return job


def enqueue_durable(kind: str, payload: dict | None = None, files: dict | None = None, **kw) -> ComputeJob:
    """صفِ ماندگار: کار همیشه در صف می‌ماند تا یک گرهٔ توانا روشن شود (به‌طورِ پیش‌فرض هیچ مهلتِ انتظاری ندارد).

    فقط اگر هیچ گرهٔ فعالی با این توانایی اصلاً ثبت نشده باشد ComputeUnavailable می‌دهد — منتظرِ سروری ماندن که وجود ندارد
    بی‌معناست. (`node.*` همیشه نامِ گرهٔ خودش را دارد و `node=` را باید بدهید.)"""
    kw["require_online"] = False
    capability = capability_for(kind)
    if capability != "any" and not kind.startswith("node.") and not known_nodes(capability):
        raise ComputeUnavailable(
            f"هیچ سرورِ پردازشیِ ثبت‌شده‌ای با قابلیتِ «{capability}» نیست. روی کامپیوترِ گرافیکی START.bat را یک بار اجرا کنید "
            "تا ثبت شود؛ از آن به بعد کارها تا روشن شدنِ آن در صف می‌مانند."
        )
    return enqueue(kind, payload, files, **kw)


def wait(job: ComputeJob, timeout_s: int | None = None, poll: float = 2.0, on_tick=None, *, patient: bool = False,
         park_after_s: float | None = None) -> ComputeJob:
    """تا پایانِ کار صبر می‌کند (برای Celery/درخواست‌های پس‌زمینه).

    پیش‌فرض (patient=False) مثلِ قدیم است: سقفِ کلی `2×مهلت+۶۰` ثانیه و پس از آن کار لغو و ComputeTimeout می‌شود.
    مهلتِ اجرا فقط از لحظهٔ گرفته‌شدنِ **فعلی** حساب می‌شود: اگر گره قطع شد و کار به صف برگشت، ساعت از نو شروع می‌شود.

    `patient=True` (صفِ ماندگار): ماندن در صف هیچ‌وقت کار را لغو نمی‌کند؛ فقط خطای واقعی، لغوِ کاربر یا «بیش از مهلتِ اجرا،
    روی گرهٔ زنده» آن را می‌بُرد. اگر گره‌ای که کار را داشت خاموش شده، ساعتِ اجرا کنار می‌ماند تا کار به صف برگردد.
    `park_after_s`: اگر کار این‌قدر ثانیه در صف بماند و هیچ گرهٔ توانایی آنلاین نباشد، کار لغو و NodeWaiting داده می‌شود
    تا نخِ Celery اشغال نماند و فراخواننده (apps.jobs) کارِ کاربر را «در صف» بگذارد."""
    budget = timeout_s or job.timeout_s
    started = time.monotonic()
    # صف ممکن است شلوغ باشد؛ مهلت از لحظهٔ گرفته‌شدن حساب می‌شود، ولی سقفِ کلی هم هست (جز در حالتِ patient)
    overall_deadline = None if patient else started + budget * 2 + 60
    run_deadline = None
    claim_stamp = None
    idle_since = None
    capability = capability_for(job.kind)
    while True:
        job.refresh_from_db()
        if job.state == ComputeJob.State.COMPLETED:
            return job
        if job.state == ComputeJob.State.FAILED:
            raise ComputeFailed(job.error or "کار روی سرورِ پردازش ناموفق بود.")
        if job.state == ComputeJob.State.CANCELLED:
            raise ComputeCancelled("کار لغو شد.")
        now = time.monotonic()
        if job.state in (ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING):
            idle_since = None
            if run_deadline is None or job.claimed_at != claim_stamp:
                run_deadline = now + budget
                claim_stamp = job.claimed_at
        else:                                   # دوباره در صف: ساعتِ اجرا از نو
            run_deadline, claim_stamp = None, None
            if park_after_s is not None and capability != "any":
                if online_nodes(capability):
                    idle_since = None
                else:
                    idle_since = idle_since or now
                    if now - idle_since >= park_after_s:
                        cancel(job, "هیچ سرورِ پردازشیِ روشنی این کار را نمی‌گیرد؛ کارِ اصلی در صفِ انتظار ماند.")
                        raise NodeWaiting(NO_NODE_QUEUED_TEXT, capability)
        if run_deadline and now > run_deadline:
            node = job.node
            if patient and node is not None and not node.online:
                run_deadline = None             # گره رفته؛ منتظرِ برگشتِ کار به صف (requeue_stale) می‌مانیم
            else:
                cancel(job, f"مهلتِ اجرا تمام شد: سرورِ پردازش در {budget} ثانیه کار را تمام نکرد.")  # با progress ِ بعدی می‌فهمد
                raise ComputeTimeout(f"سرورِ پردازش در {budget} ثانیه کار را تمام نکرد.")
        if overall_deadline and now > overall_deadline:
            cancel(job, f"مهلتِ کلی تمام شد: کار در {int(budget * 2 + 60)} ثانیه برداشته یا تمام نشد.")  # گره بیهوده نگیرد
            raise ComputeTimeout(f"سرورِ پردازش در {budget} ثانیه کار را تمام نکرد.")
        if on_tick:
            on_tick(job)
        time.sleep(poll)


def run(kind: str, payload: dict | None = None, files: dict | None = None, **kw) -> ComputeJob:
    """ثبت + انتظار، در یک قدم."""
    timeout_s = kw.pop("timeout_s", None)
    job = enqueue(kind, payload, files, timeout_s=timeout_s, **kw)
    return wait(job, timeout_s)


# ───────────────────────────── سمتِ گره

def _kinds_q(node: ComputeNode) -> Q:
    """کدام نوعِ کار به این گره برسد: سرویسش بالاست، یا با سوئیچِ خودکار عاملش می‌تواند روشنش کند (ComputeNode.has)."""
    q = Q(kind__startswith="echo") | Q(kind__startswith="node.")   # node.* always names its node (node_wanted)
    for prefix, capability in CAPABILITY_PREFIXES.items():
        if node.has(capability):
            fam = Q(kind__startswith=prefix)
            if prefix == "photo":
                fam &= ~Q(kind="photo.matting")      # its own capability (photo_matting): the photo kit being up is not enough
            q |= fam
    if node.has("photo_matting"):
        q |= Q(kind="photo.matting")
    if (node.capabilities or {}).get("ollama_pull"):
        # a model download needs the agent, not a running Ollama: the agent starts it (or says clearly it cannot)
        q |= Q(kind="ollama.pull")
    return q


CAPABILITY_PREFIXES = {"comfy": "comfyui", "photo": "photo", "video": "video", "voice": "voice", "ollama": "ollama",
                       "edit": "ffmpeg"}


MOSS_ENGINES = ("moss-fa", "moss", "moss-tts")


def audio_blocked(node: ComputeNode, job: ComputeJob) -> bool:
    """An audio job this node must not take now: its model is switched off for the node in the panel
    («مدل‌های صدا»), or not installed yet (still downloading) - the job waits in the queue instead of failing."""
    p = job.payload or {}
    if job.kind == "voice.sfx":
        key, purpose = "sfx", "sfx"
    elif job.kind == "voice.music":
        key, purpose = "music", "music"
    elif job.kind in ("voice.tts", "voice.clone") and str(p.get("engine") or "").lower() in MOSS_ENGINES:
        key = "moss"
        purpose = "clone" if job.kind == "voice.clone" or p.get("clone") or p.get("reference") else "speech"
    elif job.kind == "voice.clone" or (job.kind == "voice.tts" and p.get("clone")):
        key, purpose = None, "clone"                     # the kit's Pocket cloning
    else:
        return False
    if ((node.desired or {}).get("audio") or {}).get(purpose) is False:
        return True
    audio = (node.capabilities or {}).get("audio")
    return bool(key and isinstance(audio, dict) and not audio.get(key))


def matting_blocked(node: ComputeNode, job: ComputeJob) -> bool:
    """A photo.matting job this node must not take yet: the model is not installed here (or still downloading), or no Python on
    the node can run it (yet). The job waits in the queue instead of failing (caps.matting_models / caps.matting_runtime)."""
    if job.kind != "photo.matting":
        return False
    caps = node.capabilities or {}
    if (caps.get("matting_runtime") or {}).get("ok") is not True:
        return True
    model = str((job.payload or {}).get("model") or "")
    return ((caps.get("matting_models") or {}).get(model) or {}).get("state") != "installed"


def job_blocked(node: ComputeNode, job: ComputeJob) -> bool:
    """Every «this node cannot take it yet, keep it queued» rule in one place (audio models, matting models)."""
    return audio_blocked(node, job) or matting_blocked(node, job)


def claim(node: ComputeNode) -> ComputeJob | None:
    """یک کار به این گره می‌دهد — اتمی، تا دو گره یک کار را نگیرند."""
    requeue_stale()
    now = timezone.now()
    # کارِ زمان‌بندی‌شده (not_before) و کارِ دارای بازهٔ مجاز (window، وقتِ تهران) فقط در زمانِ خودشان داده می‌شوند؛
    # بازه‌های بسته در خودِ پرس‌وجو کنار می‌روند تا ۵۰ کارِ اولِ بسته جلوی بقیه را نگیرند
    windows = set(ComputeJob.objects.filter(state=ComputeJob.State.QUEUED).exclude(window="")
                  .values_list("window", flat=True).distinct())
    open_windows = [w for w in windows if in_window(w, now)]
    candidates = (ComputeJob.objects.filter(state=ComputeJob.State.QUEUED, node__isnull=True)
                  .filter(Q(node_wanted="") | Q(node_wanted=node.name))
                  .filter(Q(not_before__isnull=True) | Q(not_before__lte=now))
                  .filter(Q(window="") | Q(window__in=open_windows))
                  .filter(_kinds_q(node)).order_by("priority", "created_at")[:50])
    for job in candidates:
        if job_blocked(node, job):
            continue
        updated = _claim_row(job.pk, node, now)
        if updated == 1:
            _mark_waited(job, now)
            waited = job.waited_s
            logger.info("compute: %s claimed by %s (waited %ss)", job.uid, node.name, waited)
            return job
    return None


def package(job: ComputeJob) -> Path:
    """بستهٔ کار برای گره: payload.json + فایل‌های ورودی.

    یک بار ساخته می‌شود (ورودی‌ها بعد از ثبت عوض نمی‌شوند) و اتمی جایش می‌نشیند؛ وگرنه هر GET دوباره
    می‌نوشت و گرهٔ دیگری که هم‌زمان می‌خواند zip ِ نیمه‌نوشته می‌گرفت."""
    root = job_root(job)
    path = root / "package.zip"
    if path.is_file():
        return path
    tmp = root / f"package.{uuid.uuid4().hex[:8]}.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("payload.json", json.dumps({"uid": str(job.uid), "kind": job.kind, "payload": job.payload,
                                                "inputs": job.inputs, "timeout_s": job.timeout_s},
                                               ensure_ascii=False))
        for name, rel in (job.inputs or {}).items():
            src = root / rel
            if src.is_file():
                zf.write(src, f"inputs/{name}")
    try:
        os.replace(tmp, path)
    except OSError:
        # روی ویندوز اگر هم‌زمان کسی همان فایل را باز کرده باشد؛ نسخهٔ او همین محتواست
        if path.is_file():
            tmp.unlink(missing_ok=True)
        else:
            raise
    return path


def progress(job: ComputeJob, data: dict) -> dict:
    if job.final:
        # لغو/پایان وقتی گره در دسترس نبود ثبت شده؛ گره باید همین‌جا بفهمد و بایستد، و ردیفِ پایان‌یافته دست نخورد
        return {"cancel": job.state == ComputeJob.State.CANCELLED or job.cancel_requested}
    fields = ["heartbeat_at", "updated_at"]
    job.heartbeat_at = timezone.now()
    if job.state == ComputeJob.State.CLAIMED:
        job.state = ComputeJob.State.RUNNING
        fields.append("state")
    if "progress" in data:
        try:
            job.progress = max(0.0, min(0.99, float(data["progress"])))
            fields.append("progress")
        except (TypeError, ValueError):
            pass
    if data.get("message"):
        job.message = str(data["message"])[:300]
        fields.append("message")
    live = data.get("meta")
    if isinstance(live, dict) and live and len(json.dumps(live, default=str)) < 2000:
        # پیشرفتِ زنده (مثلاً دانلودِ مدل: بایتِ گرفته‌شده/کل، سرعت، مرحله) — پنل از result["live"] می‌خواند؛ finish آن را نگه می‌دارد
        job.result = {**(job.result or {}), "live": live}
        fields.append("result")
    _save(job, fields)
    return {"cancel": job.cancel_requested}


def save_output(job: ComputeJob, name: str, fileobj) -> dict:
    dest = output_path(job, name)
    with open(dest, "wb") as fh:
        for chunk in fileobj.chunks() if hasattr(fileobj, "chunks") else iter(lambda: fileobj.read(1 << 20), b""):
            fh.write(chunk)
    return {"name": dest.name, "path": f"{job.dir_rel}/outputs/{dest.name}", "size": dest.stat().st_size,
            "media": _media_kind(dest.name)}


def _media_kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        return "image"
    if ext in (".mp4", ".webm", ".mov", ".mkv"):
        return "video"
    if ext in (".wav", ".mp3", ".ogg", ".flac", ".m4a"):
        return "audio"
    if ext in (".json", ".txt"):
        return "text"
    return "file"


def finish(job: ComputeJob, node: ComputeNode, ok: bool, error: str = "", meta: dict | None = None,
           outputs: list | None = None) -> ComputeJob:
    call_with_retry(job.refresh_from_db)  # شمارهٔ تلاش و وضعیت باید تازه باشد، نه نسخهٔ در حافظه
    if job.final:
        return job
    now = timezone.now()
    if ok:
        found = []
        for p in sorted((job_root(job) / "outputs").iterdir()):
            if p.is_file():
                found.append({"name": p.name, "path": f"{job.dir_rel}/outputs/{p.name}", "size": p.stat().st_size,
                              "media": _media_kind(p.name)})
        declared = {o.get("name"): o for o in (outputs or []) if isinstance(o, dict)}
        for o in found:
            o.update({k: v for k, v in declared.get(o["name"], {}).items() if k not in ("path", "size")})
        job.result = {"outputs": found, "meta": meta or {}}
        job.state = ComputeJob.State.COMPLETED
        job.progress = 1.0
        job.message = "تمام شد"
        if job.claimed_at:
            job.run_s = round(max(0.0, (now - job.claimed_at).total_seconds()), 1)
    else:
        job.error = (error or "خطای نامشخص روی سرورِ پردازش")[:4000]
        if job.cancel_requested:
            job.state = ComputeJob.State.CANCELLED
        elif job.attempts < job.max_attempts and (meta or {}).get("retryable", True):
            # تلاشِ دوباره روی هر گره‌ای (همین یا دیگری)
            job.state = ComputeJob.State.QUEUED
            job.node = None
            job.claimed_at = None
            job.queued_at = now
            job.message = "تلاشِ دوباره پس از خطا: " + job.error[:120]
            _save(job)
            logger.warning("compute: %s failed on %s, requeued (attempt %s)", job.uid, node.name, job.attempts)
            return job
        else:
            job.state = ComputeJob.State.FAILED
        job.message = "ناموفق"
        if job.claimed_at:
            job.run_s = round(max(0.0, (now - job.claimed_at).total_seconds()), 1)
    job.finished_at = now
    _save(job)                       # اول خودِ کار (مهم‌ترین)، بعد آمارِ گره (فرعی)
    if ok:
        _note_success(node, job, now)
    return job


def _note_success(node: ComputeNode, job: ComputeJob, now) -> None:
    """شمارندهٔ کارهای انجام‌شده و میانگینِ زمان — فرعی است؛ قفلِ پایدارِ SQLite کارِ تمام‌شده را خراب نمی‌کند."""
    try:
        _bump_jobs_done(node)
        node.refresh_from_db()
        _learn_timing(node, job, now)
    except Exception as exc:  # noqa: BLE001
        if not is_lock_error(exc):
            raise
        logger.warning("compute: could not update node stats after %s (database locked)", job.uid)


def _learn_timing(node: ComputeNode, job: ComputeJob, now) -> None:
    """میانگینِ زمانِ هر نوعِ کار روی این گره (برای تخمین در پنل)."""
    if not job.claimed_at:
        return
    seconds = (now - job.claimed_at).total_seconds()
    stats = dict(node.stats or {})
    old = stats.get(job.kind) or {"seconds": seconds, "n": 0}
    n = old["n"] + 1
    stats[job.kind] = {"seconds": round((old["seconds"] * old["n"] + seconds) / n, 1), "n": n}
    node.stats = stats
    call_with_retry(node.save, update_fields=["stats"])


def cancel(job: ComputeJob, reason: str = "") -> None:
    """لغو در هر لحظه: در صف ⇒ همین حالا؛ روی گرهٔ زنده ⇒ گره با progress ِ بعدی می‌فهمد؛ روی گرهٔ خاموش ⇒ همین حالا
    (کسی نیست که تأیید کند) و گره وقتی برگشت از progress می‌فهمد و کار را ول می‌کند.
    `reason` (۱۴۰۵/۰۸/۲۱): چرا — در پیام و متنِ خطای کار می‌ماند تا پنل به‌جای «لغو شد» ِ خالی علتش را بگوید
    (شبِ ۰۸/۲۰ پنجاه کار فقط با «لغو شد» ماندند و معلوم نبود سایت از مهلت لغوشان کرده)."""
    if job.final:
        return
    why = (reason or "").strip() or "لغو شد"
    if not (job.error or "").strip():
        job.error = why
    if job.state == ComputeJob.State.QUEUED:
        job.state = ComputeJob.State.CANCELLED
        job.finished_at = timezone.now()
        job.message = why[:300]
        _save(job)
        _after_cancel(job)
        return
    node = job.node
    if node is None or not node.online:
        job.cancel_requested = True
        job.state = ComputeJob.State.CANCELLED
        job.finished_at = timezone.now()
        job.message = why[:300]
        _save(job)
        _after_cancel(job)
    else:
        job.cancel_requested = True
        job.message = why[:300]
        _save(job, ["cancel_requested", "message", "error"])


def _after_cancel(job: ComputeJob) -> None:
    """کارِ منتظرِ «Job»ِ کاربر بود (apps.compute.park) ⇒ خودِ Job هم لغو شود."""
    try:
        from . import park
        park.on_cancelled(job)
    except Exception as exc:  # noqa: BLE001 — لغوِ صف نباید بخاطرِ ردیفِ مالک بشکند
        logger.warning("compute: park cancel hook failed: %s", exc)


def requeue_stale() -> int:
    """کارِ گره‌ای که خاموش شد دوباره در صف می‌رود.

    صفِ ماندگار: اگر گرهٔ کار خاموش است (قطعِ اینترنت/خاموشی/ری‌استارت) این **تلاش حساب نمی‌شود** — کار بی‌صدا به صف
    برمی‌گردد و با وصل شدنِ گره ادامه می‌یابد. فقط «گرهٔ زنده ولی کار ساکت» (کارِ گیرکرده) و خطای واقعی از تلاش‌ها کم می‌کنند.
    اگر یک کار پشتِ‌سرهم گره را می‌کُشد (بیش از MAX_LOST_FREE بار) از آن به بعد قطع‌ها هم تلاش حساب می‌شوند تا حلقهٔ بی‌پایان نشود."""
    now = timezone.now()
    n = 0
    stale = ComputeJob.objects.filter(state__in=[ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING]).select_related("node")
    for job in stale:
        last = job.heartbeat_at or job.claimed_at or job.created_at
        if (now - last).total_seconds() < job.lease_s:
            continue
        n += _requeue_one(job.pk, now)
    n += expire_overdue(now)
    return n


@retry_on_lock
def _requeue_one(pk, now) -> int:
    """یک کارِ بی‌خبر را به صف برمی‌گرداند (۱) یا کاری نمی‌کند (۰). تراکنشِ خودش را دارد و روی قفلِ SQLite تکرار می‌شود."""
    with transaction.atomic():
        fresh = ComputeJob.objects.select_for_update().get(pk=pk)
        if fresh.state not in (ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING):
            return 0
        node = fresh.node
        who = node.name if node else "?"
        node_gone = node is None or not node.online
        if fresh.cancel_requested:
            # لغو خواسته شده بود؛ دوباره در صف گذاشتنش یعنی کارِ مرده برای هیچ‌کس اجرا شود
            fresh.state = ComputeJob.State.CANCELLED
            fresh.node = None
            fresh.finished_at = now
            fresh.message = "لغو شد"
            fresh.save()
            cancelled = True
        else:
            cancelled = False
            if node_gone:
                fresh.lost_count += 1
                if fresh.lost_count <= MAX_LOST_FREE and fresh.attempts > 0:
                    fresh.attempts -= 1            # claim() یکی اضافه کرده بود؛ قطعِ گره تقصیرِ کار نیست
            if fresh.attempts < fresh.max_attempts:
                fresh.state = ComputeJob.State.QUEUED
                fresh.node = None
                fresh.claimed_at = None
                fresh.queued_at = now
                fresh.message = LOST_NODE_TEXT if node_gone else f"سرورِ پردازشِ {who} بی‌خبر ماند؛ دوباره در صف"
            else:
                fresh.state = ComputeJob.State.FAILED
                fresh.error = f"سرورِ پردازشِ {who} وسطِ کار بی‌خبر ماند و تلاش‌ها تمام شد."
                fresh.finished_at = now
                fresh.message = "ناموفق"
            fresh.save()
    if cancelled:
        _after_cancel(fresh)
    return 1


_expire_checked = 0.0


def expire_overdue(now=None, force: bool = False) -> int:
    """سقفِ انتظار (اختیاری، پیش‌فرض خاموش): کارِ منتظرِ گره بیش از سقف در صف ماند ⇒ ناموفق.
    سقفِ هر کار `max_wait_s` است؛ اگر ۰ بود «سقفِ انتظارِ کارها» در تنظیماتِ سرورهای پردازش (ساعت؛ ۰ = هرگز)."""
    global _expire_checked
    mono = time.monotonic()
    if not force and mono - _expire_checked < 30:
        return 0
    _expire_checked = mono
    now = now or timezone.now()
    try:
        from .models import ComputeSettings
        global_s = int(ComputeSettings.get().max_wait_hours or 0) * 3600
    except Exception:  # noqa: BLE001 — جدول هنوز نیست
        global_s = 0
    q = Q(max_wait_s__gt=0)
    if global_s:
        q |= Q(max_wait_s=0)
    n = 0
    for job in ComputeJob.objects.filter(state=ComputeJob.State.QUEUED).filter(q):
        limit = job.max_wait_s or global_s
        # دانلودِ زمان‌بندی‌شده منتظرِ ساعتِ خودش است، نه منتظرِ سرور: تا وقتِ شروع / بازشدنِ بازه سقفِ انتظار نمی‌شمارد
        if (job.not_before and job.not_before > now) or (job.window and not in_window(job.window, now)):
            continue
        since = job.queued_at or job.created_at
        if job.not_before and job.not_before > since:
            since = job.not_before
        if not limit or (now - since).total_seconds() < limit:
            continue
        updated = call_with_retry(ComputeJob.objects.filter(pk=job.pk, state=ComputeJob.State.QUEUED).update,
            state=ComputeJob.State.FAILED, finished_at=now, message="ناموفق",
            error=f"کار بیش از {max(1, limit // 3600)} ساعت منتظرِ روشن شدنِ سرورِ پردازش ماند و مهلتِ انتظار تمام شد.")
        if updated:
            job.refresh_from_db()
            try:
                from . import park
                park.on_expired(job)
            except Exception as exc:  # noqa: BLE001
                logger.warning("compute: park expire hook failed: %s", exc)
            n += 1
    return n


def summary() -> dict:
    nodes = list(ComputeNode.objects.filter(enabled=True))
    online = [n for n in nodes if n.online]
    caps = {}
    for n in online:
        for k, v in (n.capabilities or {}).items():
            if v is True and not k.endswith("_stale") and k != "ollama_pull":  # فقط پرچم‌ها (نه «ollama_pull»: ویژگیِ عامل است)؛ slots (عدد)، comfy_nodes/ollama_models (فهرست) و gpu (متن) قابلیت نیستند
                caps[k] = caps.get(k, 0) + 1
    return {"nodes": len(nodes), "online": len(online), "capabilities": caps,
            "queued": ComputeJob.objects.filter(state=ComputeJob.State.QUEUED).count(),
            "running": ComputeJob.objects.filter(state__in=["CLAIMED", "RUNNING"]).count()}
