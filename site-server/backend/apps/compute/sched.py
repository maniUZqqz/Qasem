"""نوبت‌دهیِ عادلانهٔ صف (۱۴۰۵/۰۸/۲۱): کارِ کوتاه پشتِ کارِ بلند گرسنه نمی‌ماند.

خواستهٔ مالک: «شب می‌روم خانه و روشنش می‌کنم؛ همه‌چیز می‌افتد توی صف و خودش انجام می‌شود». یک ویدیوی Wan چند دقیقه کارتِ گرافیک
را می‌گیرد؛ نباید ۳۰ پرسشِ کوتاهِ متنی پشتش تا ابد بمانند. ترتیبِ ثابتِ (اولویت، زمانِ ثبت) تنها کافی نیست.

قاعده (فقط میانِ کارهای هم‌اولویت؛ اولویتِ کمتر همیشه جلوتر است):
  * هر کار «کوتاه» (≤ ۹۰ ثانیه)، «متوسط» (≤ ۸ دقیقه)، «بلند» یا «دانلود» است — از میانگینِ زمانِ واقعیِ همان نوع روی همین گره
    (node.stats) و اگر نبود از جدولِ پیش‌فرض؛ ویدیو/Wan و مهلتِ بلند همیشه «بلند»اند.
  * کوتاه‌ها اول (قدیمی‌ترین جلوتر). پس از `short_burst` (پیش‌فرض ۱۲) کارِ کوتاهِ پشتِ هم، نوبتِ متوسط/بلند می‌رسد
    (شمارنده با هر کارِ غیرکوتاه صفر می‌شود).
  * کارِ متوسط/بلندی که بیش از ۲ ساعت منتظر مانده، از همه جلوتر است (گرسنگیِ کارِ بلند هم نداریم).
  * میانِ کوتاه‌ها، موتورِ همان کارِ قبلی (Ollama / ComfyUI / صدا) ترجیح دارد تا مدل بی‌دلیل بین حافظهٔ کارت و دیسک نرود،
    مگر قدیمی‌ترین کارِ کوتاهِ موتورِ دیگر بیش از ۱۰ دقیقه منتظر مانده باشد.
  * دانلودها (ollama.pull، node.models) آخرند و فقط وقتی گره کارِ دیگری ندارد.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

SHORT_S = 90
MEDIUM_S = 480
LONG_MAX_WAIT = timedelta(hours=2)
SAME_ENGINE_MAX_WAIT = timedelta(minutes=10)
DEFAULT_BURST = 12

#: کارهایی که پهنای‌باند می‌گیرند نه کارت؛ فقط وقتی گره بی‌کار است
DOWNLOAD_KINDS = ("ollama.pull", "node.models")
#: کارهایی که کارتِ گرافیک را اشغال نمی‌کنند: «راهروی سبک» ِ گره (کنارِ یک کارِ بلند) فقط همین‌ها را می‌گیرد
LIGHT_KINDS = ("echo", "selftest.gpu", "edit.track")

#: زمانِ پیش‌فرضِ هر نوع (ثانیه) تا وقتی میانگینِ واقعی نیست
DEFAULT_SECONDS = {
    "echo": 3, "selftest.gpu": 20, "selftest.ffmpeg": 20, "ollama.chat": 40, "ollama.generate": 40, "voice.tts": 30,
    "voice.asr": 25, "asr.transcribe": 60, "voice.sfx": 45, "voice.music": 150, "voice.clone": 150, "voice.http": 10,
    "photo.edit": 25, "photo.analyze": 25, "photo.matting": 20, "photo.http": 10, "video.edit": 300, "edit.track": 60,
    "edit.matte": 180, "edit.render": 300, "comfy.graph": 120, "comfy.profile": 120, "node.bench": 120, "node.update": 60,
    "node.models": 1800, "ollama.pull": 1800,
}
LONG_HINTS = ("wan", "video", "i2v", "animate", "svd", "hunyuan", "ltx")
VIDEO_NODES = ("VHS_VideoCombine", "SaveVideo", "CreateVideo", "WanImageToVideo", "WanFirstLastFrameToVideo", "SaveAnimatedWEBP")


def engine_of(kind: str) -> str:
    fam = (kind or "").split(".", 1)[0]
    return {"ollama": "ollama", "comfy": "comfy", "voice": "audio", "asr": "audio", "photo": "photo", "edit": "ffmpeg",
            "video": "ffmpeg", "node": "node", "selftest": "node", "echo": "node"}.get(fam, fam)


def est_seconds(job, node=None) -> float:
    stats = ((node.stats if node is not None else None) or {}).get(job.kind) or {}
    if stats.get("n") and stats.get("seconds"):
        return float(stats["seconds"])
    base = float(DEFAULT_SECONDS.get(job.kind, 120))
    p = job.payload or {}
    if job.kind == "comfy.profile":
        name = str(p.get("profile") or p.get("profile_id") or p.get("kind") or "").lower()
        if any(h in name for h in LONG_HINTS):
            base = max(base, 900)
    elif job.kind == "comfy.graph":
        graph = p.get("graph")
        if isinstance(graph, dict):
            text = " ".join(str(n.get("class_type", "")) for n in graph.values() if isinstance(n, dict))
            if any(v in text for v in VIDEO_NODES):
                base = max(base, 900)
    elif job.kind == "voice.tts" and str(p.get("engine") or "").lower() in ("moss-fa", "moss", "moss-tts"):
        base = max(base, 60)
    return base


def job_class(job, node=None) -> str:
    if job.kind in DOWNLOAD_KINDS:
        return "download"
    if (job.timeout_s or 0) >= 3600 and job.kind not in ("echo",) and not job.kind.startswith("selftest."):
        return "long"
    secs = est_seconds(job, node)
    if secs <= SHORT_S:
        return "short"
    if secs <= MEDIUM_S:
        return "medium"
    return "long"


def burst_of(settings_obj=None) -> int:
    try:
        return max(1, int(getattr(settings_obj, "short_burst", DEFAULT_BURST) or DEFAULT_BURST))
    except (TypeError, ValueError):
        return DEFAULT_BURST


def order(node, candidates, auto, node_busy: bool = False, burst: int = DEFAULT_BURST, now=None):
    """candidates: already sorted by (priority, created_at). Returns them in the order they should be offered to the node."""
    now = now or timezone.now()
    out = []
    i = 0
    cands = list(candidates)
    while i < len(cands):
        j = i
        while j < len(cands) and cands[j].priority == cands[i].priority:
            j += 1
        out.extend(_order_band(node, cands[i:j], auto, node_busy, burst, now))
        i = j
    return out


def _since(job, now):
    return job.queued_at or job.created_at or now


def _order_band(node, band, auto, node_busy, burst, now):
    classes = {j.pk: job_class(j, node) for j in band}
    short = [j for j in band if classes[j.pk] == "short"]
    rest = [j for j in band if classes[j.pk] in ("medium", "long")]
    downloads = [] if node_busy else [j for j in band if classes[j.pk] == "download"]
    streak = getattr(auto, "short_streak", 0) if auto is not None else 0
    last_engine = getattr(auto, "last_engine", "") if auto is not None else ""
    # قدیمی‌ترین کارِ سنگینِ بیش از ۲ ساعت منتظر، از همه جلوتر
    starving = [j for j in rest if now - _since(j, now) > LONG_MAX_WAIT]
    if short and last_engine:
        oldest = min(short, key=lambda j: _since(j, now))
        if engine_of(oldest.kind) != last_engine and now - _since(oldest, now) <= SAME_ENGINE_MAX_WAIT:
            same = [j for j in short if engine_of(j.kind) == last_engine]
            if same:
                short = same + [j for j in short if engine_of(j.kind) != last_engine]
    head = list(starving)
    if streak >= burst:
        ordered = head + [j for j in rest if j not in head] + short
    else:
        ordered = head + short + [j for j in rest if j not in head]
    return ordered + downloads


def after_claim(auto, job, node=None) -> None:
    """شمارنده‌های نوبت‌دهی را بعد از هر گرفتنِ کار به‌روز می‌کند."""
    if auto is None:
        return
    cls = job_class(job, node)
    auto.short_streak = (auto.short_streak + 1) if cls == "short" else (0 if cls in ("medium", "long") else auto.short_streak)
    auto.last_engine = engine_of(job.kind)
    auto.save(update_fields=["short_streak", "last_engine", "updated_at"])


def light_only(candidates):
    return [j for j in candidates if j.kind in LIGHT_KINDS]


def progress_by_kind(now=None, hours: int = 24) -> dict:
    """{kind: {queued, running, done, failed}} + جمع، برای «پیشرفتِ کلی» ِ پنل (صف، در حال اجرا، تمام‌شده و ناموفقِ ۲۴ ساعتِ اخیر)."""
    from django.db.models import Count

    from .models import ComputeJob as J

    now = now or timezone.now()
    since = now - timedelta(hours=hours)
    rows: dict = {}

    def bump(kind, key, n):
        r = rows.setdefault(kind, {"queued": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0})
        r[key] += n

    for kind, n in J.objects.filter(state=J.State.QUEUED).values_list("kind").annotate(n=Count("id")):
        bump(kind, "queued", n)
    for kind, n in J.objects.filter(state__in=[J.State.CLAIMED, J.State.RUNNING]).values_list("kind").annotate(n=Count("id")):
        bump(kind, "running", n)
    for state, key in ((J.State.COMPLETED, "done"), (J.State.FAILED, "failed"), (J.State.CANCELLED, "cancelled")):
        for kind, n in J.objects.filter(state=state, finished_at__gte=since).values_list("kind").annotate(n=Count("id")):
            bump(kind, key, n)
    totals = {k: sum(r[k] for r in rows.values()) for k in ("queued", "running", "done", "failed", "cancelled")}
    try:
        from . import queue as QV

        for kind, r in rows.items():
            r["label"] = QV.kind_label(kind)
    except Exception:  # noqa: BLE001 — بدونِ برچسب هم صفحه کار می‌کند
        pass
    total_all = totals["queued"] + totals["running"] + totals["done"]
    pct = int(round(100.0 * totals["done"] / total_all)) if total_all else 100
    return {"kinds": rows, "totals": totals, "percent": pct, "hours": hours}
