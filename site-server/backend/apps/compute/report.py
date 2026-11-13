"""«گزارشِ سرورهای پردازش» — نوشتن و نگه‌داریِ آمار + چند تابعِ خالصِ محاسبه (نماها در views_report.py).

سه کار:

  1. `record_heartbeat(node, caps)` از `api.heartbeat` و `api.claim` صدا زده می‌شود:
       * نوبتِ اتصال (ComputeNodeSession) را باز/ادامه/می‌بندد: heartbeat ی که تا ۹۰ ثانیه (همان تعریفِ «خاموش»
         در ComputeNode.online) بعد از آخرین تپش برسد همان نوبت را ادامه می‌دهد، وگرنه نوبتِ قدیمی در آخرین تپشش
         بسته و نوبتِ تازه باز می‌شود؛
       * حداکثر دقیقه‌ای یک نمونهٔ منابع (ComputeNodeSample) می‌نویسد.
     هیچ‌وقت خطا نمی‌دهد و کند هم نمی‌کند (heartbeat ِ گره نباید به‌خاطرِ گزارش بیفتد).
  2. `maintain()` از `tasks.maintenance` (هر دقیقه) صدا زده می‌شود ولی بیش از هر ۱۰ دقیقه کار نمی‌کند: نوبت‌های ساکت را
     می‌بندد، هرچه از «نگه‌داریِ آمار» (ComputeSettings.retention_days) قدیمی‌تر است پاک می‌کند و نمونه‌های خامِ
     قدیمی‌تر از ۴۸ ساعت را به میانگینِ ۱۵ دقیقه‌ای تبدیل می‌کند. هر اجرا کران‌دار (تعدادِ ردیف و زمان) و
     تکرارپذیر (idempotent) است.
  3. توابعِ خالص: بازه‌های اتصال ⇒ درصدِ آنلاین بودن، کاهشِ نقاطِ نمودار، و `explain()` که متنِ خطای خام را به زبانِ ساده
     و یک پیشنهاد تبدیل می‌کند.
"""
from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import ComputeJob, ComputeSettings
from .models_report import ComputeNodeSample, ComputeNodeSession

logger = logging.getLogger(__name__)

#: وقفهٔ بیشتر از این (ثانیه) یعنی اتصال قطع شده بود و نوبتِ تازه باز می‌شود (= تعریفِ ComputeNode.online)
GAP_S = 90
#: تپشِ یک گره بیش از هر این‌قدر ثانیه یک‌بار در پایگاه داده نوشته نمی‌شود (claim هر چند ثانیه می‌آید)
TOUCH_EVERY_S = 10
#: حداکثر یک نمونهٔ خام در هر این‌قدر ثانیه برای هر گره
SAMPLE_EVERY_S = 60
#: نمونهٔ خام تا این‌قدر ساعت می‌ماند، بعد میانگینِ ۱۵ دقیقه‌ای
RAW_KEEP_H = 48
BUCKET_S = 15 * 60
#: maintain() بیش از هر این‌قدر ثانیه کار نمی‌کند
MAINTAIN_EVERY_S = 600
#: ... و هر اجرا بیش از این‌قدر ثانیه طول نمی‌کشد (ادامه‌اش نوبتِ بعد)
MAINTAIN_BUDGET_S = 20.0
CACHE_KEY = "compute:report:maintained"
#: کرانِ هر دسته‌ی پایگاه‌داده‌ای (ردیف) و تعدادِ دسته‌ها در هر اجرا — maintain همیشه کوتاه می‌ماند
BATCH = 5000
MAX_BATCHES = 10

SERVICE_KEYS = ("comfyui", "ollama", "photo", "video", "voice", "blender")
METRICS = ("ram_used_pct", "vram_used_pct", "disk_free_gb", "gpu_util_pct", "gpu_temp_c")

#: آخرین باری که این پردازه برای هر گره تپش/نمونه نوشت (تا heartbeat ِ بعدی بی‌پرس‌وجو رد شود)
_LAST_TOUCH: dict[int, datetime] = {}
_LAST_SAMPLE: dict[int, datetime] = {}
_last_error_log = 0.0


def reset_state() -> None:
    """حافظهٔ درون‌پردازه را پاک می‌کند (آزمون‌ها؛ در تولید لازم نیست)."""
    global _last_error_log
    _LAST_TOUCH.clear()
    _LAST_SAMPLE.clear()
    _last_error_log = 0.0


# ───────────────────────────── اعدادِ ورودی از گره (هر چیزی ممکن است برسد)

def num(value, lo: float = -1e18, hi: float = 1e18):
    """عددِ معتبر در بازهٔ [lo, hi] یا None. bool، متنِ غیرعددی، NaN و بی‌نهایت عدد حساب نمی‌شوند؛
    متنِ عددی («1234») قبول می‌شود (عاملِ قدیمی/تازه ممکن است عدد را متن بفرستد)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value or len(value) > 32:
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    elif not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except (OverflowError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f) or f < lo or f > hi:
        return None
    return f


def sample_values(caps: dict) -> dict:
    """از گزارشِ گره فقط عددهایی که معنی دارند؛ هر چه نباشد (عاملِ قدیمی) None می‌ماند."""
    caps = caps if isinstance(caps, dict) else {}
    return {
        "ram_free_mb": num(caps.get("ram_free_mb"), 0, 1e8),
        "ram_total_mb": num(caps.get("ram_total_mb"), 0, 1e8),
        "vram_used_mb": num(caps.get("vram_used_mb"), 0, 1e8),
        "vram_total_mb": num(caps.get("vram_total_mb"), 0, 1e8),
        "disk_free_gb": num(caps.get("disk_free_gb"), 0, 1e7),
        "disk_total_gb": num(caps.get("disk_total_gb"), 0, 1e7),
        "gpu_util_pct": num(caps.get("gpu_util_pct"), 0, 100),
        "gpu_temp_c": num(caps.get("gpu_temp_c"), -30, 160),
    }


def used_pct(used, total):
    """درصدِ مصرف (۰ تا ۱۰۰)؛ ناشناخته یا کلِ صفر ⇒ None. مصرفِ بیشتر از کل (گزارشِ ناسازگار) روی ۱۰۰ می‌ماند."""
    if used is None or not total or total <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * used / total)), 1)


def ram_used_pct(free, total):
    return None if free is None or not total else used_pct(total - free, total)


# ───────────────────────────── ۱) نوشتن از heartbeat

def _due(table: dict, key: int, now, every_s: int) -> bool:
    last = table.get(key)
    return last is None or not (0 <= (now - last).total_seconds() < every_s)


def record_heartbeat(node, caps=None, now=None) -> None:
    """نوبتِ اتصال و نمونهٔ منابعِ این گره. هرگز خطا نمی‌دهد؛ وقتی کاری لازم نیست (claim هر چند ثانیه می‌آید) هیچ پرس‌وجویی نمی‌زند."""
    global _last_error_log
    try:
        now = now or timezone.now()
        touch, sample = _due(_LAST_TOUCH, node.pk, now, TOUCH_EVERY_S), _due(_LAST_SAMPLE, node.pk, now, SAMPLE_EVERY_S)
        if not touch and not sample:
            return
        caps = node.capabilities if caps is None else caps
        caps = caps if isinstance(caps, dict) else {}
        with transaction.atomic():           # خطا فقط همین بخش را برمی‌گرداند، نه تراکنشِ فراخوان را
            if touch:
                _touch_session(node, caps, now)
            if sample:
                _maybe_sample(node, caps, now)
    except Exception:  # noqa: BLE001 — گزارش نباید heartbeat را بیندازد
        if time.monotonic() - _last_error_log > 600:       # مثلاً پیش از migrate: هر ۲۰ ثانیه لاگ نریزد
            _last_error_log = time.monotonic()
            logger.exception("compute report: could not record the heartbeat of node %s", getattr(node, "pk", "?"))


def _touch_session(node, caps: dict, now) -> None:
    fields = {"last_beat": now}
    for key, limit in (("agent", 20), ("hostname", 80), ("gpu", 200)):
        value = str(caps.get(key) or "").strip()[:limit]
        if value:
            fields[key] = value
    # حالتِ همیشگی: یک UPDATE و تمام (بدونِ خواندن)
    extended = ComputeNodeSession.objects.filter(node=node, ended_at__isnull=True, last_beat__gte=now - timedelta(seconds=GAP_S)
                                                 ).update(**fields)
    if not extended:
        # وقفهٔ طولانی (یا اولین بار): نوبتِ قدیمی در آخرین تپشش بسته می‌شود و نوبتِ تازه باز
        ComputeNodeSession.objects.filter(node=node, ended_at__isnull=True).update(ended_at=F("last_beat"))
        ComputeNodeSession.objects.create(node=node, started_at=now, last_beat=now, agent=fields.get("agent", ""),
                                          hostname=fields.get("hostname", ""), gpu=fields.get("gpu", ""))
    _LAST_TOUCH[node.pk] = now


def _maybe_sample(node, caps: dict, now) -> None:
    _LAST_SAMPLE[node.pk] = now
    if ComputeNodeSample.objects.filter(node=node, kind=ComputeNodeSample.RAW,
                                        at__gt=now - timedelta(seconds=SAMPLE_EVERY_S)).exists():
        return                               # پردازهٔ دیگری همین حالا نوشته
    running = ComputeJob.objects.filter(node=node, state__in=[ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING]).count()
    ComputeNodeSample.objects.create(
        node=node, at=now, kind=ComputeNodeSample.RAW, running_jobs=min(running, 30000),
        services={k: bool(caps.get(k)) for k in SERVICE_KEYS}, **sample_values(caps))


# ───────────────────────────── ۲) نگه‌داری

def _floor15(dt: datetime) -> datetime:
    return datetime.fromtimestamp(int(dt.timestamp()) // BUCKET_S * BUCKET_S, tz=dt_timezone.utc)


def _chunks(seq, n=900):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def close_stale(now) -> int:
    """نوبتی که بیش از ۹۰ ثانیه تپشی نداشته بسته می‌شود (پایان = آخرین تپش)."""
    return ComputeNodeSession.objects.filter(ended_at__isnull=True, last_beat__lt=now - timedelta(seconds=GAP_S)
                                             ).update(ended_at=F("last_beat"))


_AVG_FIELDS = ("ram_free_mb", "ram_total_mb", "vram_used_mb", "vram_total_mb", "disk_free_gb", "disk_total_gb",
               "gpu_util_pct", "gpu_temp_c")


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def rollup(now, batch: int = BATCH, max_batches: int = MAX_BATCHES, deadline: float | None = None) -> tuple[int, int]:
    """نمونه‌های خامِ قدیمی‌تر از ۴۸ ساعت ⇒ میانگینِ ۱۵ دقیقه‌ای (kind="15m")؛ خام‌ها پاک می‌شوند.
    (ردیفِ ساخته‌شده، پاک‌شده) را برمی‌گرداند. هر دسته فقط سطل‌های کاملِ ۱۵ دقیقه‌ای را می‌گیرد، پس تکرارپذیر است."""
    cutoff = _floor15(now - timedelta(hours=RAW_KEEP_H))
    made = removed = 0
    for _ in range(max_batches):
        if deadline is not None and time.monotonic() > deadline:
            break
        rows = list(ComputeNodeSample.objects.filter(kind=ComputeNodeSample.RAW, at__lt=cutoff).order_by("at")[:batch])
        if not rows:
            break
        full = len(rows) == batch
        if full:
            tail = _floor15(rows[-1].at)         # سطلِ آخر شاید در دستهٔ بعد ادامه داشته باشد
            rows = [r for r in rows if _floor15(r.at) < tail]
            if not rows:
                break
        groups: dict[tuple, list] = defaultdict(list)
        for r in rows:
            groups[(r.node_id, _floor15(r.at))].append(r)
        lo = min(k[1] for k in groups)
        hi = max(k[1] for k in groups)
        existing = set(ComputeNodeSample.objects.filter(kind=ComputeNodeSample.M15, at__gte=lo, at__lte=hi,
                                                        node_id__in={k[0] for k in groups}).values_list("node_id", "at"))
        new = []
        for (node_id, bucket), items in groups.items():
            if (node_id, bucket) in existing:
                continue
            services: dict = items[-1].services or {}
            new.append(ComputeNodeSample(
                node_id=node_id, at=bucket, kind=ComputeNodeSample.M15,
                running_jobs=max(r.running_jobs for r in items), services=services,
                **{f: _mean(getattr(r, f) for r in items) for f in _AVG_FIELDS}))
        with transaction.atomic():
            if new:
                ComputeNodeSample.objects.bulk_create(new, ignore_conflicts=True)
            for part in _chunks([r.pk for r in rows]):
                ComputeNodeSample.objects.filter(pk__in=part).delete()
        made += len(new)
        removed += len(rows)
        if not full:
            break                                # دستهٔ ناقص = چیزِ قدیمی‌ترِ دیگری نمانده
    return made, removed


def prune(now, days: int, batch: int = BATCH, max_batches: int = MAX_BATCHES, deadline: float | None = None) -> tuple[int, int]:
    """نمونه‌ها و نوبت‌های بسته‌شدهٔ قدیمی‌تر از «نگه‌داریِ آمار». (نمونه‌های پاک‌شده، نوبت‌های پاک‌شده)."""
    cutoff = now - timedelta(days=max(1, int(days)))
    gone_samples = gone_sessions = 0
    for _ in range(max_batches):
        if deadline is not None and time.monotonic() > deadline:
            break
        pks = list(ComputeNodeSample.objects.filter(at__lt=cutoff).values_list("pk", flat=True)[:batch])
        if not pks:
            break
        for part in _chunks(pks):
            ComputeNodeSample.objects.filter(pk__in=part).delete()
        gone_samples += len(pks)
    for _ in range(max_batches):
        if deadline is not None and time.monotonic() > deadline:
            break
        pks = list(ComputeNodeSession.objects.filter(ended_at__isnull=False, ended_at__lt=cutoff
                                                     ).values_list("pk", flat=True)[:batch])
        if not pks:
            break
        for part in _chunks(pks):
            ComputeNodeSession.objects.filter(pk__in=part).delete()
        gone_sessions += len(pks)
    return gone_samples, gone_sessions


def maintain(now=None, force: bool = False) -> dict:
    """از tasks.maintenance هر دقیقه صدا زده می‌شود؛ بیش از هر ۱۰ دقیقه کاری نمی‌کند (مگر force). هرگز خطا نمی‌دهد."""
    now = now or timezone.now()
    if not force:
        try:
            if not cache.add(CACHE_KEY, now.timestamp(), MAINTAIN_EVERY_S):
                return {"skipped": True}
        except Exception:  # noqa: BLE001 — کش خراب بود ⇒ بی‌کش ادامه (کارها همه ارزان‌اند)
            pass
    out = {"closed": 0, "rolled_up": 0, "raw_removed": 0, "samples_pruned": 0, "sessions_pruned": 0}
    deadline = time.monotonic() + MAINTAIN_BUDGET_S
    try:
        out["closed"] = close_stale(now)
        days = ComputeSettings.get().retention_days or 30
        # اول پاک‌کردنِ قدیمی‌ها، بعد فشرده‌سازیِ باقی (ردیفی که همین حالا باید پاک شود میانگین‌گیری نمی‌شود)
        out["samples_pruned"], out["sessions_pruned"] = prune(now, days, deadline=deadline)
        out["rolled_up"], out["raw_removed"] = rollup(now, deadline=deadline)
    except Exception:  # noqa: BLE001 — نگه‌داریِ آمار صفِ پردازش را نمی‌خواباند
        logger.exception("compute report: maintenance failed")
        out["error"] = True
    return out


# ───────────────────────────── ۳) توابعِ خالص (بازه‌ها و نمودار)

def session_spans(rows, now, gap_s: int = GAP_S) -> list[tuple[float, float, bool]]:
    """(started_at, last_beat, ended_at) ⇒ [(شروع، پایان، ادامه‌دارد)] به ثانیهٔ epoch.
    نوبتِ بازی که تپشش تازه است تا «الان» حساب می‌شود؛ نوبتِ بازِ ساکت (هنوز بسته نشده) تا آخرین تپشش."""
    out = []
    for started, last_beat, ended in rows:
        s = started.timestamp()
        if ended is not None:
            e, ongoing = ended.timestamp(), False
        elif (now - last_beat).total_seconds() <= gap_s:
            e, ongoing = now.timestamp(), True
        else:
            e, ongoing = last_beat.timestamp(), False
        out.append((s, max(s, e), ongoing))
    return out


def merge_spans(spans) -> list[list[float]]:
    """بازه‌های هم‌پوشان/چسبیده یکی می‌شوند (دو heartbeat ِ هم‌زمان ممکن است دو نوبت بسازند)."""
    merged: list[list[float]] = []
    for s, e in sorted((a, b) for a, b, *_ in spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def clip_spans(merged, lo: float, hi: float) -> list[list[float]]:
    return [[max(s, lo), min(e, hi)] for s, e in merged if e >= lo and s <= hi]


def uptime_stats(clipped, lo: float, hi: float) -> dict:
    """درصدِ آنلاین بودن و طولانی‌ترین خاموشی در [lo, hi] از روی بازه‌های بریده‌شده و ادغام‌شده."""
    total = hi - lo
    if total <= 0:
        return {"range_s": 0, "online_s": 0, "pct": None, "longest_gap_s": 0}
    online = sum(max(0.0, e - s) for s, e in clipped)
    cursor, longest = lo, 0.0
    for s, e in clipped:
        longest = max(longest, s - cursor)
        cursor = max(cursor, e)
    longest = max(longest, hi - cursor)
    return {"range_s": int(total), "online_s": int(min(online, total)), "pct": round(min(100.0, 100.0 * online / total), 1),
            "longest_gap_s": int(longest)}


def downsample(points, lo: float, hi: float, buckets: int = 240) -> list[list[float]]:
    """[(t، مقدار)] ⇒ حداکثر `buckets` نقطهٔ میانگین‌گرفته روی بازهٔ [lo, hi]؛ سطلِ خالی نقطه ندارد (نمودار آن‌جا می‌شکند)."""
    if hi <= lo or not points:
        return []
    width = (hi - lo) / buckets
    sums = [0.0] * buckets
    tsum = [0.0] * buckets
    cnt = [0] * buckets
    for t, v in points:
        if v is None or t < lo or t > hi:
            continue
        i = min(buckets - 1, int((t - lo) / width))
        sums[i] += v
        tsum[i] += t
        cnt[i] += 1
    return [[int(round(tsum[i] / cnt[i])), round(sums[i] / cnt[i], 1)] for i in range(buckets) if cnt[i]]


def percentile(sorted_values, p: float):
    """نزدیک‌ترین رتبه؛ فهرستِ خالی ⇒ None."""
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, int(math.ceil(p / 100.0 * len(sorted_values))) - 1))
    return sorted_values[k]


# ───────────────────────────── توضیحِ خطا به زبانِ ساده

def _rule(code: str, pattern: str, what: str, advice: str):
    return code, re.compile(pattern, re.I | re.S), what, advice


#: به ترتیب: اولین الگوی منطبق جواب می‌دهد (خاص‌ترها اول). متن‌های خطای عامل اغلب «English | فارسی» است.
#: متن‌های فارسیِ خودِ سایت (مهلتِ انتظار، قطعِ سرور، لغو) اول می‌آیند تا الگوهای عامِ «مهلت» یا «وسطِ کار» آن‌ها را نبلعد.
EXPLAIN_RULES = [
    _rule("wait_limit", r"منتظرِ روشن شدنِ سرورِ پردازش ماند|مهلتِ انتظار تمام شد",
          "کار بیش از «سقفِ انتظار» در صف ماند و سرور روشن نشد.",
          "سرورِ پردازش را روشن کنید و کار را دوباره بزنید. اگر نمی‌خواهید کارها هیچ‌وقت منقضی شوند، «سقفِ انتظار» را در تنظیماتِ سرورها ۰ بگذارید."),
    _rule("lost_node", r"بی.?خبر ماند|سرورِ پردازش قطع شد|وسطِ کار|lease (?:expired|lost)|heartbeat (?:lost|missing)|node (?:went|dropped) away",
          "سرورِ پردازش وسطِ کار قطع شد (برق، اینترنت یا خاموش شدنِ کامپیوتر) و سایت دیگر از آن خبری نگرفت.",
          "برق و اینترنتِ آن کامپیوتر را بررسی کنید. با وصل شدنِ دوباره، کار خودکار از نو شروع می‌شود؛ اگر پشتِ هم تکرار شد، لاگِ همان سرور را در همین صفحه ببینید."),
    _rule("node_offline", r"هیچ سرورِ پردازشی|سرورِ پردازش(?:ی)? (?:خاموش|آنلاین نیست|روشن نیست)|no (?:processing )?node (?:is )?(?:online|available)|"
                          r"node (?:is )?offline|computeunavailable",
          "هیچ سرورِ پردازشِ روشنی برای این کار نبود (سرور خاموش است یا اینترنتش قطع است).",
          "کامپیوترِ گرافیکی را روشن کنید و START.bat را اجرا کنید؛ کارهای ماندگار با روشن شدنِ سرور خودکار ادامه می‌یابند."),
    _rule("cancelled", r"\bcancel(?:l)?ed\b|cancelled by|cancel requested|لغو شد|درخواستِ لغو",
          "این کار لغو شد.",
          "اگر خودتان لغو نکرده‌اید، ببینید کسی دیگر از پنل لغوش نکرده باشد؛ برای اجرای دوباره، کار را از همان صفحه‌ای که ساختید دوباره بزنید."),
    _rule("disk_full", r"no space left|not enough space|disk full|insufficient disk|disk_full|disk space|دیسک.{0,40}پر",
          "دیسکِ کامپیوترِ سرورِ پردازش پر شده است.",
          "روی آن کامپیوتر فایل‌های اضافه را پاک کنید تا جا باز شود؛ بعد کار را دوباره بزنید. دانلودِ نیمه‌کاره از همان‌جا ادامه می‌یابد."),
    _rule("gpu_memory", r"out of memory|outofmemory|cuda out of|ran out of gpu memory|\boom\b|حافظهٔ? کارت",
          "حافظهٔ کارتِ گرافیکِ سرور (VRAM) تمام شد (چند کارِ سنگین هم‌زمان، یا برنامهٔ دیگری آن را گرفته).",
          "برنامه‌های دیگری که از کارتِ گرافیک استفاده می‌کنند (بازی، مرورگرِ سنگین) را ببندید و «سوئیچِ خودکار» را روشن بگذارید. "
          "اگر باز هم شد، همین کار را با اندازهٔ کوچک‌تر بزنید."),
    _rule("gpu_error", r"cuda error|cuda driver|cudnn|cublas|device-side assert|nvidia-smi|nvml",
          "کارتِ گرافیکِ سرور خطا داد.",
          "درایورِ کارتِ گرافیک را به‌روز کنید یا کامپیوترِ سرور را یک بار خاموش و روشن کنید؛ بعد کار را دوباره بزنید."),
    _rule("models_missing", r"models_missing|downloading:|still being downloaded|are still being downloaded",
          "مدل‌های لازمِ این کار هنوز روی سرور کامل نیست (نصب نشده یا هنوز در حالِ دانلود است).",
          "در همین صفحه بخشِ «دانلودها» را ببینید و صبر کنید تمام شود؛ کار خودش دوباره امتحان می‌شود. "
          "اگر دانلود شروع نشده، از «سرورهای پردازش ⇐ مدل‌ها» دانلود را بزنید."),
    _rule("comfy_model", r"value not in list|prompt_outputs_failed_validation|(?:ckpt|unet|lora|vae|clip)_name",
          "ComfyUI فایلِ مدلِ لازم را روی سرور پیدا نکرد (مدل نصب نیست).",
          "از «سرورهای پردازش ⇐ مدل‌ها» مدل‌های ویدیو و تصویر را دانلود کنید و بعد کار را دوباره بزنید."),
    _rule("voice_missing", r"voice_missing|voice '.{0,60}' is not on this node|reference voice .{0,80}is not on this node|could not rebuild voice",
          "صدای انتخاب‌شده روی این سرور نیست.",
          "سایت کار را دوباره با فایلِ ضبط‌شده می‌فرستد. اگر باز هم خطا داد، آن صدا را از نو بسازید."),
    _rule("consent", r"consent",
          "اجازهٔ صاحبِ صدا برای ساختنِ صدای کلون‌شده ثبت نشده بود.",
          "هنگام ساختنِ صدا تیکِ «اجازهٔ صاحبِ صدا» را بزنید و دوباره امتحان کنید."),
    _rule("not_allowed", r"not_allowed|allow-?list|فهرستِ مجاز|bad_tag|is not a model name",
          "این مدل در فهرستِ مدل‌های مجازِ سایت نیست.",
          "فقط مدل‌های فهرستِ مجاز دانلود می‌شوند؛ از کارتِ «اولویتِ هوش مصنوعی» (ادمین ⇐ موتورهای AI) یکی از مدل‌های مجاز را انتخاب کنید."),
    _rule("ollama_model", r"\A(?=.*ollama)(?=.*(?:not found|try pulling|manifest unknown|pull model manifest|not installed|pull failed))",
          "مدلِ خواسته‌شده در Ollamaِ سرور نصب نیست.",
          "از کارتِ «اولویتِ هوش مصنوعی» (ادمین ⇐ موتورهای AI) همان مدل را دانلود کنید؛ تا تمام شدنِ دانلود کار را نزنید."),
    _rule("not_installed", r"not_installed|not_found|manifest unknown|file does not exist|model .{0,80}not found|try pulling it first|"
                           r"pull model manifest|invalid model name|is not installed|نصب نیست|پیدا نشد",
          "مدلِ خواسته‌شده روی سرور نصب نیست یا پیدا نشد.",
          "نامِ مدل را بررسی کنید و از کارتِ «اولویتِ هوش مصنوعی» دوباره دانلودش کنید؛ تا تمام شدنِ دانلود کار را نزنید."),
    _rule("credit", r"\b402\b|payment required|insufficient (?:credit|balance|funds)|\bcredits?\b|out of credit|اعتبار|quota",
          "اعتبارِ سرویسِ ابریِ هوش مصنوعی (Metis) تمام شده است.",
          "اعتبارِ حسابِ سرویسِ ابری را شارژ کنید، یا کار را روی سرورِ پردازشِ خودتان (لوکال) انجام دهید."),
    _rule("service_slow", r"is running but did not (?:answer|finish)|did not answer within",
          "سرویسِ روی سرورِ پردازش روشن است ولی تا مهلتِ تعیین‌شده جواب نداد (سرگرمِ کارِ سنگین یا گیر کرده)؛ قطع نبوده است.",
          "کمی صبر کنید و کار را دوباره بزنید. اگر تکرار شد، در بخشِ منابعِ همین صفحه ببینید کارتِ گرافیک یا حافظه پر نیست و لاگِ همان سرویس را روی "
          "آن کامپیوتر نگاه کنید؛ برای ساخت‌های طولانی مهلتِ کار را بیشتر بگیرید."),
    _rule("ollama_down", r"ollama_down|ollama is not running|ollama .{0,40}not reachable|ollama .{0,40}refused|ollama .{0,40}connection",
          "Ollama (موتورِ متنِ هوشمند) روی سرور روشن نیست.",
          "در «سرورهای پردازش» سرویسِ Ollama را روشن کنید یا «سوئیچِ خودکار» را روشن بگذارید تا خودش روشن شود."),
    _rule("comfy_down", r"comfyui.{0,80}(?:not reachable|refused|did not start|not running|did not become ready|unavailable|not responding)",
          "ComfyUI (موتورِ ساختنِ تصویر و ویدیو) روی سرور روشن نیست یا جواب نمی‌دهد.",
          "در «سرورهای پردازش» سرویسِ ComfyUI را روشن کنید؛ اگر روشن نشد، لاگِ همان سرور را ببینید و در صورتِ لزوم کامپیوتر را دوباره راه بیندازید."),
    _rule("service_down", r"is not reachable at|not reachable|connection refused|actively refused|econnrefused|winerror 10061|"
                          r"did not start|did not become ready|is not running on this node|service .{0,40}is not running",
          "یکی از سرویس‌های روی سرورِ پردازش روشن نیست یا جواب نمی‌دهد.",
          "در «سرورهای پردازش» سرویسِ مربوط را روشن کنید یا سوئیچِ خودکار را روشن بگذارید. اگر روشن نمی‌شود، لاگِ همان سرور را ببینید."),
    _rule("site_error", r"\b50[0234]\b|bad gateway|service unavailable|gateway time-?out|internal server error",
          "سایت لحظه‌ای جواب نداد.",
          "چند دقیقه صبر کنید؛ کار خودش دوباره امتحان می‌شود. اگر ادامه داشت به پشتیبان خبر بدهید."),
    _rule("site_transfer", r"site unreachable|could not reach the site|truncated download|download failed after \d+ attempts|"
                           r"upload (?:failed|error)|failed to upload|could not upload|(?:GET|POST) /api/v1/compute/",
          "ارسال یا دریافتِ فایل بینِ سرورِ پردازش و سایت ناموفق بود (اینترنتِ سرور یا خودِ سایت لحظه‌ای مشکل داشت).",
          "اینترنتِ آن کامپیوتر را بررسی کنید و چند دقیقه صبر کنید؛ کار خودش دوباره امتحان می‌شود. اگر فایل خیلی بزرگ است، اینترنتِ پایدارتر لازم است."),
    _rule("checksum", r"sha-?256|checksum|hash mismatch|corrupt|wrongfile|wrong file",
          "فایلِ دانلودشده سالم نبود (ناقص یا خراب).",
          "دانلود را دوباره بزنید؛ فایلِ خراب خودکار پاک و دوباره گرفته می‌شود. اگر تکرار شد، اینترنتِ سرور را بررسی کنید."),
    _rule("download", r"no_progress|download (?:failed|ended|keeps failing|did not)|keeps failing|gives up after|دانلود.{0,40}(?:ناموفق|قطع)",
          "دانلود چند بار پشتِ هم قطع شد و کامل نشد.",
          "اینترنتِ سرورِ پردازش را بررسی کنید و دوباره دانلود را بزنید؛ آنچه تا حالا گرفته شده می‌ماند و از همان‌جا ادامه می‌یابد."),
    _rule("network", r"getaddrinfo|name resolution|dial tcp|network is unreachable|no route to host|max retries exceeded|connection aborted|"
                     r"connection reset|certificate verify|\bssl\b|10060|10054|remote end closed|read timed out|connect timeout|"
                     r"connecttimeout|temporary failure|remotedisconnected",
          "ارتباطِ اینترنتیِ سرورِ پردازش قطع یا ناپایدار بود.",
          "اینترنتِ آن کامپیوتر را بررسی کنید. معمولاً وقتی اینترنت برگشت کار خودش دوباره شروع می‌شود."),
    _rule("timeout", r"timed? ?out|timeout|did not finish (?:in time|within)|deadline|took too long|مهلت|ثانیه کار را تمام نکرد",
          "کار از زمانِ مجازش بیشتر طول کشید.",
          "ممکن است کار خیلی سنگین بوده یا سرور کند شده باشد. یک بار دیگر امتحان کنید، یا ورودیِ کوچک‌تر بدهید. "
          "اگر تکرار شد، وضعیتِ کارتِ گرافیک و حافظهٔ سرور را همین‌جا در بخشِ منابع ببینید."),
    _rule("other_node", r"مالِ سرورِ پردازشِ دیگری|belongs to another|another node|\b403\b",
          "کار به سرورِ دیگری سپرده شده بود و این سرور اجازهٔ دست زدن به آن را نداشت.",
          "معمولاً بعد از قطع و وصل شدنِ سرور پیش می‌آید و خودش درست می‌شود؛ کاری لازم نیست."),
    _rule("token", r"توکنِ سرورِ پردازش نامعتبر|invalid token|rejected the node token|authentication ?failed|\b401\b|unauthori[sz]ed|not authenticated",
          "توکنِ این سرور نامعتبر است یا سرور در پنل غیرفعال شده.",
          "در «سرورهای پردازش» فعال بودنِ سرور را ببینید؛ اگر توکن عوض شده، فایلِ START تازه را دوباره روی آن کامپیوتر بگذارید."),
    _rule("update_failed", r"update failed|به.?روز.{0,30}(?:نشد|ناموفق)",
          "به‌روزرسانیِ نرم‌افزارِ سرورِ پردازش انجام نشد.",
          "در پوشهٔ سرورِ پردازش فایلِ Update.bat را اجرا کنید و بعد START.bat را دوباره بزنید."),
    _rule("ffmpeg", r"ffmpeg|ffprobe",
          "ابزارِ ویدیو (ffmpeg) روی سرور پیدا نشد یا خطا داد.",
          "با Update.bat پوشه را به‌روز کنید و START.bat را دوباره اجرا کنید؛ اگر ویدیو خراب یا نامعمول است، ویدیوی دیگری امتحان کنید."),
    _rule("empty_input", r"is empty|is missing from the job|no recordings|name is missing|must be a number|متن.{0,20}خالی",
          "ورودیِ کار ناقص یا خالی بود.",
          "متن یا توضیحِ لازم را کامل کنید و دوباره بزنید."),
    _rule("no_output", r"returned no audio|no audio file|finished without a file|no output|returned no|خروجی نداشت",
          "سرویس تمام شد ولی خروجی‌ای نساخت.",
          "یک بار دیگر امتحان کنید. اگر تکرار شد، متنِ کاملِ خطا را به پشتیبان بدهید."),
]

UNKNOWN_EXPLAIN = {
    "code": "unknown", "known": False,
    "what": "خطای ناشناخته.",
    "advice": "خطای ناشناخته — متنِ کامل را به پشتیبان بدهید.",
}


def explain(text) -> dict:
    """{"code", "known", "what", "advice"}: متنِ خطای خام ⇒ توضیحِ ساده + پیشنهاد (الگوی ناشناخته ⇒ UNKNOWN_EXPLAIN)."""
    raw = str(text or "")[:6000]
    for code, rx, what, advice in EXPLAIN_RULES:
        if rx.search(raw):
            return {"code": code, "known": True, "what": what, "advice": advice}
    return dict(UNKNOWN_EXPLAIN)
