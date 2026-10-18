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


def enqueue(kind: str, payload: dict | None = None, files: dict | None = None, *, store=None, origin: str = "",
            priority: int = 100, timeout_s: int | None = None, node: str = "", dedupe: bool = True,
            dedupe_hours: int | None = None, require_online: bool = True) -> ComputeJob:
    """یک کار در صف می‌گذارد (یا کارِ کاملِ هم‌ارزِ اخیر را برمی‌گرداند)."""
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
                     node_wanted=node or "", timeout_s=timeout_s or int(getattr(settings, "NM_COMPUTE_TIMEOUT", 1800)))
    job.save()
    root = job_root(job)
    inputs = {}
    for name, src in files.items():
        safe = os.path.basename(name)
        shutil.copyfile(src, root / "inputs" / safe)
        inputs[safe] = f"inputs/{safe}"
    if inputs:
        job.inputs = inputs
        job.save(update_fields=["inputs"])
    return job


def wait(job: ComputeJob, timeout_s: int | None = None, poll: float = 2.0, on_tick=None) -> ComputeJob:
    """تا پایانِ کار صبر می‌کند (برای Celery/درخواست‌های پس‌زمینه)."""
    budget = timeout_s or job.timeout_s
    # صف ممکن است شلوغ باشد؛ مهلت از لحظهٔ گرفته‌شدن حساب می‌شود، ولی سقفِ کلی هم هست
    overall_deadline = time.monotonic() + budget * 2 + 60
    run_deadline = None
    while True:
        job.refresh_from_db()
        if job.state == ComputeJob.State.COMPLETED:
            return job
        if job.state == ComputeJob.State.FAILED:
            raise ComputeFailed(job.error or "کار روی سرورِ پردازش ناموفق بود.")
        if job.state == ComputeJob.State.CANCELLED:
            raise ComputeCancelled("کار لغو شد.")
        if job.claimed_at and run_deadline is None:
            run_deadline = time.monotonic() + budget
        now = time.monotonic()
        if (run_deadline and now > run_deadline) or now > overall_deadline:
            cancel(job)  # هنوز در صف ⇐ همین حالا لغو (گره بیهوده نگیرد)؛ در حال اجرا ⇐ با progress ِ بعدی می‌فهمد
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
    caps = node.capabilities or {}
    q = Q(kind__startswith="echo")
    for prefix, capability in CAPABILITY_PREFIXES.items():
        if caps.get(capability):
            q |= Q(kind__startswith=prefix)
    return q


CAPABILITY_PREFIXES = {"comfy": "comfyui", "photo": "photo", "video": "video", "voice": "voice", "ollama": "ollama"}


def claim(node: ComputeNode) -> ComputeJob | None:
    """یک کار به این گره می‌دهد — اتمی، تا دو گره یک کار را نگیرند."""
    requeue_stale()
    candidates = (ComputeJob.objects.filter(state=ComputeJob.State.QUEUED, node__isnull=True)
                  .filter(Q(node_wanted="") | Q(node_wanted=node.name))
                  .filter(_kinds_q(node)).order_by("priority", "created_at")[:10])
    now = timezone.now()
    for job in candidates:
        updated = ComputeJob.objects.filter(pk=job.pk, state=ComputeJob.State.QUEUED, node__isnull=True).update(
            state=ComputeJob.State.CLAIMED, node=node, claimed_at=now, heartbeat_at=now, attempts=F("attempts") + 1,
            message="گرفته شد توسطِ " + node.name)
        if updated == 1:
            job.refresh_from_db()
            logger.info("compute: %s claimed by %s", job.uid, node.name)
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
    job.save(update_fields=fields)
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
    job.refresh_from_db()  # شمارهٔ تلاش و وضعیت باید تازه باشد، نه نسخهٔ در حافظه
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
        node.jobs_done = F("jobs_done") + 1
        node.save(update_fields=["jobs_done"])
        node.refresh_from_db()
        _learn_timing(node, job, now)
    else:
        job.error = (error or "خطای نامشخص روی سرورِ پردازش")[:4000]
        if job.cancel_requested:
            job.state = ComputeJob.State.CANCELLED
        elif job.attempts < job.max_attempts and (meta or {}).get("retryable", True):
            # تلاشِ دوباره روی هر گره‌ای (همین یا دیگری)
            job.state = ComputeJob.State.QUEUED
            job.node = None
            job.claimed_at = None
            job.message = "تلاشِ دوباره پس از خطا: " + job.error[:120]
            job.save()
            logger.warning("compute: %s failed on %s, requeued (attempt %s)", job.uid, node.name, job.attempts)
            return job
        else:
            job.state = ComputeJob.State.FAILED
        job.message = "ناموفق"
    job.finished_at = now
    job.save()
    return job


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
    node.save(update_fields=["stats"])


def cancel(job: ComputeJob) -> None:
    if job.final:
        return
    if job.state == ComputeJob.State.QUEUED:
        job.state = ComputeJob.State.CANCELLED
        job.finished_at = timezone.now()
        job.message = "لغو شد"
        job.save()
    else:
        job.cancel_requested = True
        job.save(update_fields=["cancel_requested"])


def requeue_stale() -> int:
    """کارِ گره‌ای که خاموش شد دوباره در صف می‌رود (یا بعد از چند تلاش ناموفق می‌شود)."""
    now = timezone.now()
    n = 0
    stale = ComputeJob.objects.filter(state__in=[ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING])
    for job in stale:
        last = job.heartbeat_at or job.claimed_at or job.created_at
        if (now - last).total_seconds() < job.lease_s:
            continue
        with transaction.atomic():
            fresh = ComputeJob.objects.select_for_update().get(pk=job.pk)
            if fresh.state not in (ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING):
                continue
            who = fresh.node.name if fresh.node else "?"
            if fresh.cancel_requested:
                # لغو خواسته شده بود؛ دوباره در صف گذاشتنش یعنی کارِ مرده برای هیچ‌کس اجرا شود
                fresh.state = ComputeJob.State.CANCELLED
                fresh.node = None
                fresh.finished_at = now
                fresh.message = "لغو شد"
            elif fresh.attempts < fresh.max_attempts:
                fresh.state = ComputeJob.State.QUEUED
                fresh.node = None
                fresh.claimed_at = None
                fresh.message = f"سرورِ پردازشِ {who} بی‌خبر ماند؛ دوباره در صف"
            else:
                fresh.state = ComputeJob.State.FAILED
                fresh.error = f"سرورِ پردازشِ {who} وسطِ کار بی‌خبر ماند و تلاش‌ها تمام شد."
                fresh.finished_at = now
                fresh.message = "ناموفق"
            fresh.save()
            n += 1
    return n


def summary() -> dict:
    nodes = list(ComputeNode.objects.filter(enabled=True))
    online = [n for n in nodes if n.online]
    caps = {}
    for n in online:
        for k, v in (n.capabilities or {}).items():
            if v is True:  # فقط پرچم‌ها؛ slots (عدد)، comfy_nodes/ollama_models (فهرست) و gpu (متن) قابلیت نیستند
                caps[k] = caps.get(k, 0) + 1
    return {"nodes": len(nodes), "online": len(online), "capabilities": caps,
            "queued": ComputeJob.objects.filter(state=ComputeJob.State.QUEUED).count(),
            "running": ComputeJob.objects.filter(state__in=["CLAIMED", "RUNNING"]).count()}
