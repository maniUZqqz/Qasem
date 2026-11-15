"""نگه‌داریِ فایل‌های کارها (۱۴۰۵/۰۸/۲۴): پوشهٔ هر کارِ تمام‌شده برای همیشه نمی‌ماند.

مسئله: `data/compute/jobs/<uid>/` برای هر کار ورودی‌ها (inputs/) + بستهٔ ساخته‌شده برای گره (package.zip، همان ورودی‌ها دوباره) + خروجی‌ها
را می‌گرفت و هیچ‌کس پاک نمی‌کرد (۵۶۵ پوشه برای ۳۱۰ کار؛ ۲۶۹ پوشه بی‌کار). امروز چون گره خاموش بود کم است؛ با FLUX/Wan و رندرِ روزانه روی دیسکی
که ۸۷٪ پر است در هفته‌ها گیگابایت می‌شود.

قاعده (از `tasks.maintenance`، کران‌دار، هر چند دقیقه یک بار):
  * کارِ **تمام‌شده** (COMPLETED/FAILED/CANCELLED) و پس از یک ساعت مهلت: `package.zip` و `assets.json` پاک می‌شود (فقط برای دانلودِ گره بود؛
    اگر لازم شود از ورودی‌ها دوباره ساخته می‌شود). نیمی از فضای هر کار همین بود: هر ورودی دو بار نگه داشته می‌شد.
  * `inputs/`: کارِ COMPLETED که کارِ اصلیِ فروشگاهش تمام شده و ≥ ۶ ساعت گذشته («نتیجه به فروشگاه منتقل شده») یا ۲ روز پس از پایان؛ FAILED
    پس از ۱۴ روز و CANCELLED پس از ۳ روز (تا «پردازشِ دوباره» ممکن بماند). چرا نه فوراً: برخی صفحه‌ها (پرکردنِ مولد، ویرایشِ عکس) نتیجه را
    وقتی کاربر برگشت و صفحه را باز کرد برمی‌دارند و در آن لحظه ورودی (ماسک) را هم می‌خوانند — گرهٔ شبانه تمام می‌کند و مالک صبح می‌آید.
  * `outputs/`: همان «نتیجه منتقل شده» ⇒ ۶ ساعت بعد؛ وگرنه COMPLETED پس از ۷ روز، FAILED پس از ۱۴ روز، CANCELLED پس از ۳ روز ⇒ کلِ پوشه پاک
    و روی ردیف «فایل‌ها پاک شد» (result["retention"]) نوشته می‌شود.
  * ردیفِ صفحه‌ای که هنوز منتظرِ برداشتنِ نتیجه است (ویرایشِ عکس در حالتِ «گره/سرور»، تکهٔ regen «در حال ساخت»، صدای «در انتظار») تا ۱۴ روز
    نگه داشته می‌شود (`consumer_pending`)؛ اگر نتوانیم بفهمیم، نگه می‌داریم.
  * پوشه‌ای که ردیفِ ComputeJob ندارد و بیش از ۱ روز از آخرین تغییرش گذشته (یتیم) پاک می‌شود.
  * ردیف‌های قدیمیِ COMPLETED/CANCELLED (بیش از max(۹۰ روز، «نگه‌داریِ آمار»)) و FAILED (بیش از یک سال؛ خطاها برای گزارش می‌مانند) پاک می‌شوند.
  * کارِ در جریان (QUEUED/CLAIMED/RUNNING) هرگز دست نمی‌خورد.
مقدارِ آزادشده در `<داده>/compute/retention.json` جمع می‌شود و صفحهٔ گزارش نشانش می‌دهد (`report()`).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

from django.core.cache import cache
from django.utils import timezone

from . import services as SV
from .models import ComputeJob, ComputeSettings
from .park import PARK_KIND

logger = logging.getLogger(__name__)
S = ComputeJob.State

#: کارِ تمام‌شده این‌قدر می‌ماند تا چیزی از پوشه‌اش برداشته شود (صفحه‌ای که ورودی/خروجی را دنبال می‌کند)
GRACE_S = 3600
#: نتیجه‌ای که کارِ اصلیِ فروشگاه تمام‌شده و این‌قدر گذشته، به فروشگاه منتقل‌شده حساب می‌شود
TAKEN_AFTER_S = 6 * 3600
OUTPUT_DAYS = {S.COMPLETED: 7, S.FAILED: 14, S.CANCELLED: 3}
#: ورودی‌های کارِ ناموفق/لغوشده برای «پردازشِ دوباره» می‌مانند؛ کارِ COMPLETED ۲ روز (صفحهٔ دنبال‌کننده ممکن است دیرتر برگردد و ورودی را بخواند)
INPUT_DAYS = {S.COMPLETED: 2, S.FAILED: 14, S.CANCELLED: 3}
#: ردیفِ صفحه‌ای که هنوز نتیجه را برنداشته تا این‌قدر روز جلوی پاک شدن را می‌گیرد
PENDING_MAX_DAYS = 14
ORPHAN_AFTER_S = 24 * 3600
ROW_DAYS = 90
FAILED_ROW_DAYS = 365
MAX_JOBS_PER_RUN = 60
MAX_ORPHANS_PER_RUN = 40
MAX_ROWS_PER_RUN = 400
BUDGET_S = 15.0
EVERY_S = 300
CACHE_KEY = "compute:retention:ran"
STATS_NAME = "retention.json"


def jobs_dir() -> Path:
    return SV.data_root() / "compute" / "jobs"


def stats_path() -> Path:
    return SV.data_root() / "compute" / STATS_NAME


def dir_size(path) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total


def _remove(path: Path) -> int:
    """فایل یا پوشه را پاک می‌کند؛ مگابایتِ آزادشده (بایت) را برمی‌گرداند. هرگز خطا نمی‌دهد."""
    try:
        if path.is_dir():
            size = dir_size(path)
            shutil.rmtree(path, ignore_errors=True)
            return size if not path.exists() else 0
        if path.is_file():
            size = path.stat().st_size
            path.unlink()
            return size
    except OSError as exc:
        logger.warning("compute retention: could not remove %s: %s", path, exc)
    return 0


def owner_taken(job) -> bool:
    """کارِ اصلیِ فروشگاهِ این کار تمام شده؟ (یعنی نتیجه‌اش پیش‌تر در رسانهٔ فروشگاه نشسته)"""
    ref = getattr(job, "job_ref", None)
    if not ref or not getattr(job, "store_id", None):
        return False
    try:
        from apps.jobs import machine
        from apps.jobs.models import Job

        state = Job.objects.filter(pk=ref).values_list("state", flat=True).first()
    except Exception:  # noqa: BLE001 — بی‌اطلاع ⇒ «منتقل نشده»: چیزی زودتر پاک نمی‌شود
        return False
    return state in machine.TERMINAL if state else False


def consumer_pending(job) -> bool:
    """صفحه‌ای که این کار را با شناسه‌اش دنبال می‌کند هنوز نتیجه را برنداشته؟ (queue.CONSUMER_ORIGINS). نامعلوم ⇒ بله (چیزی زودتر پاک نشود)."""
    uid = str(job.uid)
    try:
        if job.origin == "photoedit":
            from apps.photoedit.models import PhotoEdit

            return PhotoEdit.objects.filter(compute_job=uid, state__in=[PhotoEdit.State.NODE, PhotoEdit.State.SERVER]).exists()
        if job.origin == "regen":
            from apps.regen.models import RegenVersion

            return RegenVersion.objects.filter(compute_job=uid, state=RegenVersion.State.GENERATING).exists()
        if job.origin == "audio_studio":
            from apps.ai.models import AudioAsset

            return AudioAsset.objects.filter(job_uid=job.uid, status=AudioAsset.Status.PENDING).exists()
    except Exception:  # noqa: BLE001
        logger.warning("compute retention: cannot tell whether %s was picked up; keeping its files", uid, exc_info=True)
        return True
    return False


def plan(job, now) -> dict:
    """چه چیزی از پوشهٔ این کارِ تمام‌شده باید برود؟ {"package", "inputs", "outputs", "why"} (why فقط وقتی outputs است)."""
    since = job.finished_at or job.updated_at or now
    age = (now - since).total_seconds()
    out = {"package": False, "inputs": False, "outputs": False, "why": ""}
    if job.state not in ComputeJob.FINAL or job.kind == PARK_KIND or age < GRACE_S:
        return out
    out["package"] = True
    if job.state == S.COMPLETED and age < PENDING_MAX_DAYS * 86400 and consumer_pending(job):
        return out                                       # صفحه هنوز نتیجه را برنداشته: فقط بستهٔ گره (که دیگر لازم نیست) می‌رود
    taken = job.state == S.COMPLETED and age >= TAKEN_AFTER_S and owner_taken(job)
    keep_inputs = INPUT_DAYS.get(job.state, 2)
    out["inputs"] = taken or age >= keep_inputs * 86400
    days = OUTPUT_DAYS.get(job.state, 7)
    if age >= days * 86400:
        out["outputs"], out["why"] = True, "age"
    elif taken:
        out["outputs"], out["why"] = True, "taken"
    return out


def why_text(why: str, job) -> str:
    if why == "taken":
        return "نتیجه پیش‌تر به فروشگاه منتقل شده بود"
    days = OUTPUT_DAYS.get(job.state, 7)
    return ("از مهلتِ نگه‌داریِ فایل‌ها (%d روز) گذشته بود" % days).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def clean_job(job, now) -> int:
    """یک کارِ تمام‌شده را طبقِ `plan` پاک می‌کند؛ بایتِ آزادشده. پوشهٔ نبود یعنی کاری نیست."""
    d = jobs_dir() / str(job.uid)
    if not d.is_dir():
        return 0
    p = plan(job, now)
    if not (p["package"] or p["inputs"] or p["outputs"]):
        return 0
    freed = 0
    note = dict((job.result or {}).get("retention") or {})
    if p["outputs"]:
        names = [o.get("name") for o in (job.result or {}).get("outputs") or [] if isinstance(o, dict)]
        freed += _remove(d)
        note.update({"at": now.isoformat(), "outputs_removed": True, "inputs_removed": bool(job.inputs) or note.get("inputs_removed", False),
                     "why": p["why"], "why_text": why_text(p["why"], job), "outputs_gone": [n for n in names if n][:20],
                     "freed": int(note.get("freed", 0)) + freed})
        result = dict(job.result or {})
        result["outputs"] = []                          # دیگر لینکِ مرده نشان داده نشود؛ «dedupe» هم خروجیِ پاک‌شده را دوباره به کار نمی‌گیرد
        result["retention"] = note
        ComputeJob.objects.filter(pk=job.pk).update(result=result)
        return freed
    freed += _remove(d / "package.zip")
    for tmp in list(d.glob("package.*.tmp")):
        freed += _remove(tmp)
    if p["inputs"]:
        freed += _remove(d / "assets.json")
        if (d / "inputs").is_dir():
            freed += _remove(d / "inputs")
            note.update({"inputs_removed": bool(job.inputs), "at": now.isoformat(), "freed": int(note.get("freed", 0)) + freed})
            result = dict(job.result or {})
            result["retention"] = note
            ComputeJob.objects.filter(pk=job.pk).update(result=result)
    return freed


def _orphans(now, deadline) -> tuple[int, int]:
    """پوشه‌هایی که ردیفِ کار ندارند و بیش از ۱ روز دست نخورده‌اند ⇒ (چند پوشه، بایت)."""
    root = jobs_dir()
    if not root.is_dir():
        return 0, 0
    known = {str(u) for u in ComputeJob.objects.values_list("uid", flat=True)}
    n = freed = 0
    cutoff = time.time() - ORPHAN_AFTER_S
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if n >= MAX_ORPHANS_PER_RUN or time.monotonic() > deadline:
            break
        if entry.name in known:
            continue
        try:
            if entry.stat().st_mtime > cutoff:
                continue                                 # تازه: شاید کار همین حالا در حالِ ساخته شدن است
        except OSError:
            continue
        freed += _remove(entry)
        n += 1
    return n, freed


def _prune_rows(now, deadline) -> int:
    """ردیف‌های بسیار قدیمی. FAILED مدت‌ها برای گزارش می‌ماند."""
    days = max(ROW_DAYS, int(ComputeSettings.get().retention_days or 0))
    old = ComputeJob.objects.filter(state__in=[S.COMPLETED, S.CANCELLED], finished_at__lt=now - timedelta(days=days))
    old_failed = ComputeJob.objects.filter(state=S.FAILED, finished_at__lt=now - timedelta(days=FAILED_ROW_DAYS))
    gone = 0
    for qs in (old, old_failed):
        if time.monotonic() > deadline:
            break
        pks = list(qs.values_list("pk", flat=True)[:max(0, MAX_ROWS_PER_RUN - gone)])
        for i in range(0, len(pks), 200):
            part = pks[i:i + 200]
            for d in ComputeJob.objects.filter(pk__in=part).values_list("uid", flat=True):
                _remove(jobs_dir() / str(d))
            ComputeJob.objects.filter(pk__in=part).delete()
        gone += len(pks)
    return gone


def load_stats() -> dict:
    try:
        return json.loads(stats_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_stats(stats: dict) -> None:
    p = stats_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as exc:
        logger.warning("compute retention: stats not saved: %s", exc)


def run(now=None, deadline: float | None = None) -> dict:
    """یک دور نگه‌داری (کران‌دار). مقدارِ آزادشده را به جمعِ کل اضافه می‌کند."""
    now = now or timezone.now()
    deadline = deadline if deadline is not None else time.monotonic() + BUDGET_S
    out = {"jobs": 0, "orphans": 0, "rows": 0, "freed": 0}
    cutoff = now - timedelta(seconds=GRACE_S)
    # اول فقط (pk, uid) و وجودِ پوشه؛ ردیفِ کامل (با result) فقط برای پوشه‌هایی که هنوز هستند خوانده می‌شود
    rows = list(ComputeJob.objects.filter(state__in=ComputeJob.FINAL, finished_at__lt=cutoff).exclude(kind=PARK_KIND)
                .order_by("finished_at").values_list("pk", "uid"))
    root = jobs_dir()
    for pk, uid in rows:
        if out["jobs"] >= MAX_JOBS_PER_RUN or time.monotonic() > deadline:
            break
        if not (root / str(uid)).is_dir():
            continue
        job = ComputeJob.objects.filter(pk=pk).first()
        if job is None:
            continue
        freed = clean_job(job, now)
        if freed:
            out["jobs"] += 1
            out["freed"] += freed
    n, freed = _orphans(now, deadline)
    out["orphans"] += n
    out["freed"] += freed
    out["rows"] = _prune_rows(now, deadline)
    stats = load_stats()
    stats["last_run"] = now.isoformat()
    stats["freed_last_run"] = out["freed"]
    stats["freed_total"] = int(stats.get("freed_total", 0)) + out["freed"]
    stats["jobs_total"] = int(stats.get("jobs_total", 0)) + out["jobs"]
    stats["orphans_total"] = int(stats.get("orphans_total", 0)) + out["orphans"]
    stats["rows_total"] = int(stats.get("rows_total", 0)) + out["rows"]
    # اندازهٔ پوشه را فقط وقتی چیزی پاک شد یا یک ساعت از آخرین سنجش گذشته دوباره می‌شماریم (پیمایشِ همهٔ پوشه‌ها هر ۵ دقیقه بی‌دلیل است)
    from django.utils.dateparse import parse_datetime

    measured = parse_datetime(stats.get("size_at") or "") if stats.get("size_at") else None
    if out["freed"] or out["orphans"] or out["rows"] or measured is None or (now - measured).total_seconds() > 3600:
        stats["dirs"] = sum(1 for p in root.iterdir() if p.is_dir()) if root.is_dir() else 0
        stats["size_bytes"] = dir_size(root) if root.is_dir() else 0
        stats["size_at"] = now.isoformat()
    save_stats(stats)
    return out


def maintain(now=None, force: bool = False) -> dict:
    """از tasks.maintenance هر دقیقه؛ بیش از هر ۵ دقیقه کاری نمی‌کند (مگر force). هرگز خطا نمی‌دهد."""
    now = now or timezone.now()
    if not force:
        try:
            if not cache.add(CACHE_KEY, now.timestamp(), EVERY_S):
                return {"skipped": True}
        except Exception:  # noqa: BLE001 — کش خراب ⇒ بی‌کش (هر دور کران‌دار و ارزان است)
            pass
    try:
        return run(now)
    except Exception:  # noqa: BLE001 — نگه‌داری صفِ پردازش را نمی‌خواباند
        logger.exception("compute retention: run failed")
        return {"error": True}


def report() -> dict:
    """برای صفحهٔ گزارش: اندازهٔ فعلیِ پوشهٔ کارها و مقدارِ آزادشده."""
    st = load_stats()
    mb = lambda b: round(int(b or 0) / (1 << 20), 3)  # noqa: E731
    return {"dirs": st.get("dirs"), "size_mb": mb(st.get("size_bytes")), "freed_mb": mb(st.get("freed_total")),
            "freed_last_mb": mb(st.get("freed_last_run")), "last_run": st.get("last_run"), "jobs_cleaned": st.get("jobs_total", 0),
            "orphans_removed": st.get("orphans_total", 0), "rows_removed": st.get("rows_total", 0),
            "rules": {"output_days": 7, "failed_days": 14, "cancelled_days": 3, "grace_minutes": GRACE_S // 60}}
