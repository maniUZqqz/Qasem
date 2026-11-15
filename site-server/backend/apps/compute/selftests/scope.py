"""دامنهٔ اجرای آزمونِ خودکار (۱۴۰۵/۰۸/۲۴): کدام آزمون‌ها کِی، و کِی نباید جلوی کارِ مالک را بگیرند.

مسئله: ۲۸ از ۳۶ آزمون (مدلِ بینایی ۱۹ گیگی، FLUX، MOSS، رندر …) هم‌زمان در صف می‌رفتند و با هر بستهٔ تازه (امروز سه بسته در ۴٫۵ ساعت) از نو؛
حافظهٔ ۱۲ گیگیِ کارت بین مدل‌ها جابه‌جا می‌شد و کارِ مالک پشتشان می‌ماند. قاعده‌ها:

  * آزمونِ سیستمی (origin «selftest…») اولویتِ ۱۵۰ می‌گیرد (کارِ کاربر ۶۰ تا ۱۰۰؛ services.enqueue) و با «کهنگی» از گرسنگی در می‌آید
    (services.SYSTEM_AGING_S، sched.system_turn).
  * اجرای «پس از نسخهٔ تازه» فقط وقتی در ۲۴ ساعتِ گذشته هیچ اجرای کاملی نبوده کامل است؛ وگرنه «سریع»: فقط آزمون‌های ارزان (`CHEAP`)
    + قابلیت‌هایی که فایل‌های خودشان در بستهٔ گره عوض شده. اجرای کامل: شبانه، دکمهٔ «آزمونِ کامل»، و نخستین اجرا.
  * آزمونِ سنگین (مدلِ بزرگ روی کارت) تا وقتی کارِ کاربر روی این گره در جریان یا در صف است ساخته نمی‌شود (حداکثر `HEAVY_HOLD_MAX_S`).
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

#: ارزان و بی‌مدلِ بزرگ: بعد از هر بسته اجرا می‌شوند
CHEAP = frozenset({"echo", "bootstrap", "net", "gpu", "ffmpeg_nvenc"})
#: گروه‌هایی که کارتِ گرافیک را با مدل‌های بزرگ پر می‌کنند
HEAVY_GROUPS = frozenset({"gpu", "text", "image", "audio", "video"})
#: اجرای کاملِ در ۲۴ ساعتِ گذشته ⇒ اجرای نسخهٔ تازه «سریع» است
FULL_WINDOW_H = 24
#: شبانه اگر در این‌قدر ساعت اجرای کاملی بوده باشد اجرا نمی‌شود (سقفِ «یک بار در روز»)
NIGHTLY_SKIP_H = 18
#: آزمونِ سنگین بیش از این‌قدر پشتِ کارِ کاربر نمی‌ماند؛ بعدش با اولویتِ پایین می‌رود (کارِ کاربر به‌هرحال جلوتر است)
HEAVY_HOLD_MAX_S = 3600

#: آزمون ⇒ الگوی فایل‌های processing/ که فقط خودِ آن قابلیت به آن‌ها تکیه دارد. اگر این فایل‌ها در بستهٔ تازه عوض شده باشند آزمون در اجرای
#: «سریع» هم می‌آید. قابلیت‌هایی که کدشان در agent.py است (ollama، comfy، صدا، عکس …) اینجا نیستند: agent.py با هر نسخه عوض می‌شود و
#: آن‌ها را اجرای کاملِ شبانه می‌سنجد. (یک آزمون می‌تواند با فیلدِ `files` خودش هم همین را بگوید.)
FEATURE_FILES = {
    "edit_render": ("edit_jobs.py", "edit_render.py"),
    "autoedit_mix": ("edit_jobs.py", "edit_render.py"),
    "autoedit_matte": ("edit_jobs.py", "edit_rvm.py", "edit_track.py"),
    "matting": ("photo_matting.py",),
    "up3d_stage": ("up3d_jobs.py",),
    "up3d_phone": ("up3d_jobs.py",),
    "asr_vosk": ("asr_jobs.py", "asr_worker.py"),
    "asr_gpu": ("asr_jobs.py", "asr_worker.py"),
    "autoedit_words": ("asr_jobs.py", "asr_worker.py"),
    "autoedit_words_large": ("asr_jobs.py", "asr_worker.py"),
    "multiangle": ("multiangle_*.py",),
    "motion_studio": ("motion_jobs.py",),
    "ig_health": ("abagram_jobs.py", "abagram/*"),
    "ig_scrape": ("abagram_jobs.py", "abagram/*"),
    "ollama_text": ("ollama_jobs.py",),
    "ollama_vision": ("ollama_jobs.py",),
    "site_styles_ai": ("ollama_jobs.py",),
    "model_catalog_download": ("model_auto.py", "download_models.py"),
}


def is_cheap(t) -> bool:
    return t.key in CHEAP


def is_heavy(t) -> bool:
    """سنگین: کارِ واقعی روی کارت با مدلِ بزرگ (آزمونِ مجازی/نصب/شبکه سنگین نیست)."""
    explicit = getattr(t, "heavy", None)
    if explicit is not None:
        return bool(explicit)
    return t.key not in CHEAP and not t.virtual and t.group in HEAVY_GROUPS


def feature_patterns(t) -> tuple:
    return tuple(getattr(t, "files", ()) or ()) or FEATURE_FILES.get(t.key, ())


def manifest_files() -> dict:
    """{مسیرِ فایل در بسته: sha256} از فهرستِ بستهٔ فعلیِ سایت؛ {} اگر خوانده نشد."""
    try:
        from .. import updates as U

        return {r["path"]: r["sha256"] for r in (U.current_manifest(max_age=60.0).get("files") or []) if r.get("path")}
    except Exception:  # noqa: BLE001 — بدونِ فهرست همه‌چیز «تغییرکرده» حساب نمی‌شود؛ فقط ارزان‌ها می‌آیند
        logger.warning("selftests scope: package manifest unreadable", exc_info=True)
        return {}


def feature_fp(patterns, files: dict) -> str:
    """اثرِ انگشتِ فایل‌های یک قابلیت در بسته؛ '' اگر الگو به هیچ فایلی نخورد."""
    hit = sorted((p, h) for p, h in files.items() if any(fnmatch.fnmatch(p, pat) for pat in patterns))
    if not hit:
        return ""
    return hashlib.sha1("\n".join("%s:%s" % x for x in hit).encode("utf-8")).hexdigest()[:16]


def code_fp(t, files: dict) -> str:
    pats = feature_patterns(t)
    return feature_fp(pats, files) if pats and files else ""


def last_passed_fp(node, key: str) -> str | None:
    """اثرِ انگشتی که آخرین آزمونِ قبولِ این قابلیت روی این گره با آن اجرا شد (None = هرگز قبول نشده)."""
    from ..models import SelfTestResult

    r = SelfTestResult.objects.filter(run__node=node, key=key, state=SelfTestResult.State.PASSED).order_by("-id").first()
    if r is None:
        return None
    return str((r.extra or {}).get("code_fp") or "")


def changed(node, t, files: dict) -> bool:
    """فایل‌های این قابلیت از آخرین آزمونِ قبولش عوض شده (یا هرگز قبول نشده)؟ بدونِ الگو/بدونِ فایل در بسته ⇒ نه."""
    fp = code_fp(t, files)
    if not fp:
        return False
    return last_passed_fp(node, t.key) != fp


def last_state(node, key: str) -> str:
    """آخرین نتیجهٔ نهاییِ این آزمون روی این گره ('' = هرگز نتیجه‌ای نبوده)."""
    from ..models import SelfTestResult

    r = SelfTestResult.objects.filter(run__node=node, key=key, state__in=SelfTestResult.FINAL).order_by("-id").first()
    return r.state if r else ""


def full_run_exists(node, hours: float, now=None) -> bool:
    """در این‌قدر ساعتِ گذشته برای این گره اجرایی بوده که «سریع» نبوده و متوقف هم نشده؟"""
    from ..models import SelfTestRun

    now = now or timezone.now()
    return SelfTestRun.objects.filter(node=node, created_at__gte=now - timedelta(hours=hours)).exclude(
        trigger="quick").exclude(state=SelfTestRun.State.ABORTED).exists()


def version_scope(node, now=None) -> str:
    """اجرای «پس از نسخهٔ تازه»: 'full' فقط اگر در ۲۴ ساعتِ گذشته اجرای کاملی نبوده؛ وگرنه 'quick'."""
    return "quick" if full_run_exists(node, FULL_WINDOW_H, now) else "full"


def quick_selection(node, tests: list, files: dict) -> tuple[list, int, int]:
    """(آزمون‌های اجرای سریع، چند ارزان، چند «فایلش عوض شده یا دفعهٔ قبل رد شده بود»).
    آزمونی که دفعهٔ قبل «رد» شد هم دوباره می‌آید: به‌روزرسانی شاید همان را درست کرده و مالک باید همین حالا بفهمد."""
    cheap = [t for t in tests if is_cheap(t)]
    moved = [t for t in tests if not is_cheap(t) and (changed(node, t, files) or last_state(node, t.key) == "FAILED")]
    return cheap + moved, len(cheap), len(moved)


def user_work_reason(node) -> str:
    """کارِ کاربر روی این گره در جریان یا در صف است؟ ⇒ جمله‌ای فارسی، وگرنه ''. (کارِ سیستمی/آزمون و دانلودِ مدل حساب نمی‌شود.)"""
    from .. import queue as QV
    from .. import sched
    from .. import services as SV
    from ..models import ComputeJob as J
    from ..park import PARK_KIND

    system = SV.system_origin_q()
    if J.objects.filter(node=node, state__in=[J.State.CLAIMED, J.State.RUNNING]).exclude(system).exclude(
            kind__in=sched.DOWNLOAD_KINDS).exists():
        return "کارِ شما روی این سرور در حال اجراست"
    waiting = (J.objects.filter(state=J.State.QUEUED, node__isnull=True).filter(Q(node_wanted="") | Q(node_wanted=node.name))
               .exclude(system).exclude(kind=PARK_KIND).exclude(kind__in=sched.DOWNLOAD_KINDS)
               .exclude(SV.demand_excluded_q())[:40])
    n = 0
    now = timezone.now()
    for j in waiting:
        if (j.not_before and j.not_before > now) or (j.window and not SV.in_window(j.window, now)):
            continue                                       # زمان‌بندی‌شده برای بعد: هنوز تقاضا نیست
        if QV.node_takes(node, j.kind) and not SV.job_blocked(node, j):
            n += 1
    if n:
        return ("%d کار از کارهای شما در صف است" % n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return ""
