# -*- coding: utf-8 -*-
"""«تصویر به کد»: ساختنِ تبدیل (بارگذاری یا نشانی)، اجرای پس‌زمینه با سقفِ حافظه و زمان، امتیازهای فارسی، فایل‌ها و حذف.

معماری: کارِ سنگین در **پردازهٔ جدا** (``runner.py``) اجرا می‌شود، همیشه **یکی‌یکی** (قفلِ فایل)، با ``nice`` و سقفِ حافظه/زمان؛ یک تبدیلِ معمولی روی این سرور
(۲ هسته، رمِ کم) حدود ۴ تا ۹ ثانیه و کمتر از ۲۵۰ مگابایت است، پس به سرورِ پردازشِ GPU نیازی نیست و همه‌چیز همین حالا کار می‌کند؛
خواندنِ متن با Tesseract (فارسی+انگلیسی) روی CPU. وقتی نشانیِ صفحه داده شود، متن‌ها از خودِ صفحه (DOM) می‌آیند، نه OCR: دقیق و با فارسیِ درست.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import netguard
from .models import Conversion

try:  # لینوکس (سرور)؛ روی ویندوزِ توسعه قفل کار نمی‌کند ولی آزمون‌ها هم‌چنان می‌گذرند
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 30_000_000
MIN_SIDE = 64
HISTORY_CAP = 60
WIDTHS = [(1280, "رایانه (۱۲۸۰)"), (1440, "رایانهٔ بزرگ (۱۴۴۰)"), (768, "تبلت (۷۶۸)"), (390, "گوشی (۳۹۰)")]
SHOT_TIMEOUT = 100
CONVERT_TIMEOUT = 330     # نگاهِ دومِ OCR تا ۷۵ ثانیه به تبدیل اضافه می‌کند
RENDER_TIMEOUT = 120
CONVERT_MEM = 3 * 1024 ** 3
STALE_MINUTES = 30
FILES = {
    "original.png": ("out", "image/png"),
    "rendered.png": ("out", "image/png"),
    # پیش‌نمایشِ سبک (WebP) برای مقایسه؛ ۴ تا ۶ برابر کم‌حجم‌تر از PNG ⇒ روی اینترنتِ کند هم زود باز می‌شود. PNGِ کامل در ZIP می‌ماند.
    "original.preview.webp": ("out", "image/webp"),
    "rendered.preview.webp": ("out", "image/webp"),
    "source.png": ("", "image/png"),
    "index.html": ("out", "text/html; charset=utf-8"),
    "style.css": ("out", "text/css; charset=utf-8"),
    "tree.json": ("out", "application/json"),
    "report.json": ("out", "application/json"),
}
STEPS = [("queue", "در صف"), ("shot", "گرفتنِ عکس از صفحه"), ("convert", "خواندنِ تصویر و ساختنِ کد"), ("render", "نمایشِ نتیجه و سنجش"), ("done", "آماده")]


class Img2CodeError(Exception):
    def __init__(self, message: str, code: str = "img2code", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


# ───────────────────────────────────────────────────────────────── وضعیتِ موتور
_PROBE: dict = {"at": 0.0, "data": None}


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("OMP_THREAD_LIMIT", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


# پردازهٔ فرزند خودش nice و سقفِ حافظه را می‌گذارد (preexec_fn داخلِ worker ِ چندنخی ممکن است قفل کند؛ این‌طوری fork ِ امن است)
BOOTSTRAP = """
import os, runpy, sys
try:
    os.nice(10)
except OSError:
    pass
mem = int(os.environ.get("IMG2CODE_AS_LIMIT") or 0)
if mem:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ImportError, ValueError, OSError):
        pass
mod = sys.argv[1]
sys.argv = [mod] + sys.argv[2:]
runpy.run_module(mod, run_name="__main__", alter_sys=True)
"""


def run_process(args: list[str], timeout: float, mem: int = 0, tick: Optional[Callable[[float], bool]] = None) -> dict:
    """runner.py را در پردازهٔ جدا اجرا می‌کند ⇒ dict ِ «RESULT». ``tick(elapsed)`` هر ثانیه صدا می‌خورد و اگر True بدهد (لغو) پردازه کشته می‌شود."""
    cmd = [sys.executable, "-c", BOOTSTRAP, "apps.img2code.runner"] + [str(a) for a in args]
    t0 = time.monotonic()
    env = _env()
    if mem:
        env["IMG2CODE_AS_LIMIT"] = str(int(mem))
    kw = {"cwd": str(BACKEND_DIR), "env": env, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace"}
    if os.name == "posix":
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    out = err = ""
    cancelled = False
    last_tick = 0.0
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - t0
                if elapsed > timeout:
                    _kill(proc)
                    return {"ok": False, "error": "timeout", "message": "زمانِ این مرحله بیش از اندازه شد و متوقف شد."}
                if tick is not None and elapsed - last_tick >= 1.0:
                    last_tick = elapsed
                    if tick(elapsed):
                        cancelled = True
                        _kill(proc)
                        return {"ok": False, "error": "cancelled", "message": "لغو شد."}
    finally:
        if proc.poll() is None:
            _kill(proc)
    if cancelled:
        return {"ok": False, "error": "cancelled", "message": "لغو شد."}
    for line in reversed((out or "").splitlines()):
        if line.startswith("RESULT "):
            try:
                return json.loads(line[7:])
            except ValueError:
                break
    rc = proc.returncode
    if rc is not None and rc < 0:
        return {"ok": False, "error": "killed", "message": "پردازش ناگهان متوقف شد (احتمالاً کمبودِ حافظهٔ سرور)؛ تصویرِ کوچک‌تری امتحان کنید.", "detail": "signal %s" % -rc}
    log.warning("img2code runner failed rc=%s stderr=%s", rc, (err or "")[-400:])
    return {"ok": False, "error": "crashed", "message": "پردازش به خطا خورد.", "detail": (err or "")[-300:]}


def _kill(proc) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:  # noqa: BLE001
        pass


def engine_status(refresh: bool = False) -> dict:
    """آیا موتور روی این سرور آماده است؟ پنج دقیقه حافظه می‌شود. ⇒ {ready, url_ok, compare_ok, ocr, version, messages[]}"""
    now = time.time()
    if not refresh and _PROBE["data"] is not None and now - _PROBE["at"] < 300:
        return _PROBE["data"]
    res = run_process(["probe"], timeout=40)
    msgs: list[str] = []
    ready = bool(res.get("ok") and res.get("mv2code"))
    tess = res.get("tesseract") or {}
    ocr = bool(res.get("pytesseract") and tess.get("fas") and tess.get("eng"))
    browser = bool(res.get("playwright") and res.get("chrome"))
    if not res.get("mv2code"):
        msgs.append("موتورِ تبدیل (mv2code) روی این سرور نصب نیست؛ مدیرِ سرور باید «deploy/nm/install-img2code.sh» را اجرا کند.")
    if not ocr:
        msgs.append("خواندنِ متنِ فارسی/انگلیسی (Tesseract) کامل نصب نیست؛ تبدیلِ تصویرِ بارگذاری‌شده بی‌متن می‌شود. نشانیِ صفحه هم‌چنان متن را از خودِ صفحه می‌گیرد.")
    if not browser:
        msgs.append("مرورگرِ بی‌سرِ سرور آماده نیست؛ گرفتنِ عکس از نشانی و تصویرِ مقایسهٔ نتیجه کار نمی‌کند.")
    lexicon_ok = bool(res.get("lexicon"))
    if ready and not lexicon_ok:
        msgs.append("واژه‌نامهٔ فارسیِ اصلاحِ غلط‌های OCR در موتور نیست؛ متنِ فارسیِ تصویرِ بارگذاری‌شده بدونِ اصلاحِ نقطه‌ها می‌آید (موتور را دوباره نصب کنید).")
    data = {"ready": ready, "ocr": ocr, "lexicon": lexicon_ok, "url_ok": bool(ready and browser), "compare_ok": bool(ready and browser), "version": res.get("mv2code") or "", "messages": msgs}
    _PROBE.update(at=now, data=data)
    return data


def options() -> dict:
    return {
        "modes": [{"key": k, "label": l, "hint": h} for k, l, h in (
            ("responsive", "واکنش‌گرا", "چیدمانِ انعطاف‌پذیر (flex/جدول) و تگ‌های معنادار؛ مناسبِ ساختنِ سایت"),
            ("exact", "دقیق", "جای هر چیز پیکسل‌به‌پیکسل مثلِ تصویر؛ مناسبِ نمونهٔ دقیق"))],
        "langs": [{"key": k, "label": l} for k, l in (("auto", "خودکار"), ("fa", "فارسی"), ("en", "انگلیسی"))],
        "widths": [{"key": w, "label": l} for w, l in WIDTHS],
        "limits": {"max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024), "max_megapixels": MAX_PIXELS // 1_000_000, "history": HISTORY_CAP},
    }


# ───────────────────────────────────────────────────────────────── ساختن
def _clean_choice(value, allowed, default):
    v = str(value or "").strip()
    return v if v in allowed else default


def _check_capacity(store) -> None:
    if Conversion.objects.filter(store=store).count() >= HISTORY_CAP:
        raise Img2CodeError("تاریخچهٔ این فروشگاه پر است (%d مورد)؛ چند تبدیلِ قدیمی را پاک کنید." % HISTORY_CAP, "history_full", 409)
    if Conversion.objects.filter(store=store, state__in=Conversion.ACTIVE).count() >= 3:
        raise Img2CodeError("سه تبدیل در جریان دارید؛ صبر کنید تمام شوند.", "too_many_active", 429)


def _normalize_image(data: bytes) -> tuple[bytes, int, int]:
    """بایت‌های بارگذاری‌شده ⇒ PNGِ تمیز (بی‌متادیتا). ImportError/تصویرِ خراب ⇒ Img2CodeError."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = None            # ابعاد را خودمان پیش از load می‌سنجیم (w*h > MAX_PIXELS)
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        w, h = im.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise Img2CodeError("این فایل تصویر نیست یا خراب است. PNG، JPG یا WebP بفرستید.", "bad_image") from None
    if fmt not in ("PNG", "JPEG", "WEBP", "MPO"):
        raise Img2CodeError("این نوعِ تصویر پذیرفته نمی‌شود؛ PNG، JPG یا WebP بفرستید.", "bad_image")
    if w < MIN_SIDE or h < MIN_SIDE:
        raise Img2CodeError("تصویر خیلی کوچک است (دست‌کم %d پیکسل)." % MIN_SIDE, "small_image")
    if w * h > MAX_PIXELS:
        raise Img2CodeError("تصویر بیش از اندازه بزرگ است (بیشینه %d مگاپیکسل)." % (MAX_PIXELS // 1_000_000), "big_image")
    try:
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P", "PA"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        im = im.convert("RGB")
    except (OSError, ValueError, SyntaxError):
        raise Img2CodeError("این تصویر خراب است.", "bad_image") from None
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=False, compress_level=3)
    return buf.getvalue(), im.width, im.height


def create_upload(store, user, upload, mode="responsive", lang="auto", title="") -> Conversion:
    _check_capacity(store)
    size = getattr(upload, "size", None)
    if size is None or size <= 0:
        raise Img2CodeError("فایلی نیامد.", "no_file")
    if size > MAX_UPLOAD_BYTES:
        raise Img2CodeError("حجمِ فایل زیاد است؛ حداکثر %d مگابایت." % (MAX_UPLOAD_BYTES // (1024 * 1024)), "big_file")
    png, w, h = _normalize_image(upload.read())
    name = os.path.splitext(os.path.basename(str(getattr(upload, "name", "") or "")))[0]
    conv = Conversion.objects.create(
        store=store, created_by=user if getattr(user, "is_authenticated", False) else None, title=(title or name or "تصویر بارگذاری‌شده")[:160],
        source_kind=Conversion.Source.UPLOAD, mode=_clean_choice(mode, ("exact", "responsive"), "responsive"), lang=_clean_choice(lang, ("auto", "fa", "en"), "auto"),
        size_w=w, size_h=h, message="در صف")
    conv.dir.mkdir(parents=True, exist_ok=True)
    (conv.dir / "source.png").write_bytes(png)
    _enqueue(conv)
    return conv


def create_url(store, user, url, mode="responsive", lang="auto", width=1280, dom_text=True, title="") -> Conversion:
    _check_capacity(store)
    try:
        clean = netguard.check_url(url)
    except netguard.UrlRefused as exc:
        raise Img2CodeError(str(exc), "url_refused") from None
    width = int(width) if str(width).isdigit() and int(width) in {w for w, _ in WIDTHS} else 1280
    conv = Conversion.objects.create(
        store=store, created_by=user if getattr(user, "is_authenticated", False) else None, title=(title or clean)[:160], source_kind=Conversion.Source.URL, source_url=clean[:500],
        mode=_clean_choice(mode, ("exact", "responsive"), "responsive"), lang=_clean_choice(lang, ("auto", "fa", "en"), "auto"), width=width, dom_text=bool(dom_text), message="در صف")
    conv.dir.mkdir(parents=True, exist_ok=True)
    _enqueue(conv)
    return conv


def create_again(conv: Conversion, user, mode=None, lang=None) -> Conversion:
    """همان تصویر با حالت/زبانِ دیگر (بدونِ گرفتنِ دوبارهٔ عکس)."""
    src = conv.dir / "source.png"
    if not src.exists():
        raise Img2CodeError("تصویرِ اصلیِ این مورد دیگر نیست؛ دوباره بارگذاری کنید.", "no_source", 404)
    _check_capacity(conv.store)
    new = Conversion.objects.create(
        store=conv.store, created_by=user if getattr(user, "is_authenticated", False) else None, title=conv.title, source_kind=Conversion.Source.UPLOAD, source_url=conv.source_url,
        mode=_clean_choice(mode, ("exact", "responsive"), "exact" if conv.mode == "responsive" else "responsive"), lang=_clean_choice(lang, ("auto", "fa", "en"), conv.lang),
        width=conv.width, size_w=conv.size_w, size_h=conv.size_h, message="در صف")
    new.dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, new.dir / "source.png")
    if (conv.dir / "lines.json").exists():
        shutil.copy2(conv.dir / "lines.json", new.dir / "lines.json")
        new.dom_text = True
        new.save(update_fields=["dom_text"])
    _enqueue(new)
    return new


def _enqueue(conv: Conversion) -> None:
    from . import tasks
    transaction.on_commit(lambda: tasks.run_conversion.delay(conv.pk))


# ───────────────────────────────────────────────────────────────── قفلِ «یکی‌یکی»
class RunLock:
    """قفلِ فایلیِ بین‌پردازه‌ای: روی این سرورِ ۲هسته‌ای هم‌زمان فقط یک تبدیل اجرا می‌شود."""

    def __init__(self):
        self.fh = None

    def acquire(self) -> bool:
        if fcntl is None:
            return True
        path = Path(settings.NM_DATA_DIR) / "img2code" / "run.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a+")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False

    def release(self) -> None:
        if self.fh is not None and fcntl is not None:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None


def _earlier(conv: Conversion):
    """تبدیل‌های قدیمی‌تر از این (با همان ترتیبِ ثبت)."""
    return Q(created_at__lt=conv.created_at) | Q(created_at=conv.created_at, pk__lt=conv.pk)


def queue_position(conv: Conversion) -> int:
    return Conversion.objects.filter(state__in=Conversion.ACTIVE).filter(_earlier(conv)).count() + 1


WAIT_FRESH_SECONDS = 90


def is_my_turn(conv: Conversion) -> bool:
    """نوبتِ «اولین وارد، اولین خارج»: تا وقتی تبدیلِ قدیمی‌تری در صف است که کارگرش هنوز زنده است (هر ۵ ثانیه ردیفش را به‌روز می‌کند)، این یکی صبر می‌کند.
    پیش‌تر هر کار هر ۵ ثانیه قفل را امتحان می‌کرد و هر کس زودتر می‌رسید برنده بود؛ پس جدیدتر می‌توانست از قدیمی‌تر جلو بزند.
    ردیفِ بی‌کارگر (کارگر مرده) بعد از ۹۰ ثانیه جلوی بقیه را نمی‌گیرد."""
    fresh = timezone.now() - timedelta(seconds=WAIT_FRESH_SECONDS)
    return not Conversion.objects.filter(state=Conversion.State.QUEUED, updated_at__gte=fresh).filter(_earlier(conv)).exists()


# ───────────────────────────────────────────────────────────────── اجرا
def _set(conv: Conversion, **kw) -> bool:
    """مقدارها را روی ردیف می‌نویسد. اگر کاربر وسطِ کار «حذف» را زده باشد ردیف نیست؛ این خطا نیست (False برمی‌گرداند، بی‌خطا و بی‌ردِ traceback در لاگ).
    ``update()`` (نه ``save(update_fields)``): save برای ردیفِ رفته خطای DatabaseError می‌دهد و تراکنشِ بازِ بیرونی را هم خراب می‌کرد."""
    for k, v in kw.items():
        setattr(conv, k, v)
    now = timezone.now()
    if not Conversion.objects.filter(pk=conv.pk).update(updated_at=now, **kw):
        return False
    conv.updated_at = now
    return True


def _cancelled(conv_id: int) -> bool:
    return Conversion.objects.filter(pk=conv_id, state=Conversion.State.CANCELLED).exists() or not Conversion.objects.filter(pk=conv_id).exists()


def _fail(conv: Conversion, message: str, detail: str = "") -> Conversion:
    log.warning("img2code #%s failed: %s | %s", conv.pk, message, detail)
    _set(conv, state=Conversion.State.FAILED, error=message[:900], message="ناموفق", finished_at=timezone.now())
    return conv


def run(conv: Conversion) -> Conversion:
    """همهٔ مرحله‌ها را پشتِ‌سرِ‌هم اجرا می‌کند (از tasks.run_conversion زیرِ قفل صدا زده می‌شود)."""
    if conv.state not in (Conversion.State.QUEUED, Conversion.State.RUNNING):
        return conv
    _set(conv, state=Conversion.State.RUNNING, started_at=timezone.now(), step="queue", progress=3.0, message="شروع شد", error="")
    d, out = conv.dir, conv.out_dir
    d.mkdir(parents=True, exist_ok=True)
    src = d / "source.png"
    lines = d / "lines.json"
    warnings: list[str] = []
    text_source = "ocr"
    t_all = time.monotonic()

    def cancel_tick(_elapsed: float) -> bool:
        return _cancelled(conv.pk)

    try:
        if conv.source_kind == Conversion.Source.URL and not src.exists():
            _set(conv, step="shot", progress=8.0, message="در حال بازکردنِ صفحه و گرفتنِ عکسِ کامل…")
            args = ["shot", "--url", conv.source_url, "--out", src, "--width", conv.width]
            if conv.dom_text:
                args += ["--lines-out", lines]
            res = run_process(args, SHOT_TIMEOUT, tick=cancel_tick)
            if res.get("error") == "cancelled":
                return conv
            if not res.get("ok"):
                return _fail(conv, res.get("message") or "گرفتنِ عکس از صفحه شکست خورد.", res.get("detail", ""))
            if res.get("truncated"):
                warnings.append("صفحه خیلی بلند بود؛ فقط ۹۰۰۰ پیکسلِ بالای آن تبدیل شد.")
            if res.get("blocked_requests"):
                warnings.append("چند درخواستِ صفحه به آدرس‌های داخلی بود و بسته شد.")
            if (not conv.title or conv.title == conv.source_url) and res.get("title"):
                conv.title = str(res["title"])[:160]
            _set(conv, size_w=int(res.get("width") or 0), size_h=int(res.get("height") or 0), title=conv.title)
        if not src.exists():
            return _fail(conv, "تصویرِ ورودی پیدا نشد.")
        if _cancelled(conv.pk):
            return conv
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)
        use_dom = lines.exists() and conv.dom_text
        text_source = "dom" if use_dom else "ocr"
        _set(conv, step="convert", progress=15.0, message="در حال تشخیصِ بخش‌ها و خواندنِ متن‌ها (خط‌های نامطمئن دوباره خوانده می‌شوند؛ تا یک دقیقه)…" if not use_dom else "در حال تشخیصِ بخش‌ها (متن‌ها از خودِ صفحه می‌آیند)…")

        def convert_tick(elapsed: float) -> bool:
            _set(conv, progress=round(15 + 55 * (1 - math.exp(-elapsed / 35.0)), 1))
            return _cancelled(conv.pk)

        args = ["convert", "--image", src, "--outdir", out, "--mode", conv.mode, "--lang", conv.lang, "--title", (conv.title or "Converted page")[:80]]
        if use_dom:
            args += ["--lines", lines]
        else:
            words = brand_words(conv)
            if words:
                args += ["--glossary", ",".join(words)]
        res = run_process(args, CONVERT_TIMEOUT, mem=CONVERT_MEM, tick=convert_tick)
        if res.get("error") == "cancelled":
            return conv
        if not res.get("ok"):
            return _fail(conv, res.get("message") or "تبدیل شکست خورد.", "%s %s" % (res.get("error"), res.get("detail", "")))
        report = res.get("report") or {}
        size = res.get("size") or [conv.size_w, conv.size_h]
        slim = _slim_report(report)
        slim["text_source"] = text_source
        _set(conv, report=slim, size_w=int(size[0]), size_h=int(size[1]), progress=72.0)
        if report.get("ocr") == "none" and not use_dom:
            warnings.append("خواندنِ متن (OCR) روی سرور آماده نبود؛ این نتیجه بدونِ متن ساخته شد.")
        raw: dict = {}
        if _cancelled(conv.pk):
            return conv
        if engine_status().get("compare_ok"):
            _set(conv, step="render", progress=78.0, message="در حال نمایشِ نتیجه در مرورگر و سنجشِ شباهت…")
            res2 = run_process(["render", "--dir", out], RENDER_TIMEOUT, tick=cancel_tick)
            if res2.get("error") == "cancelled":
                return conv
            if res2.get("ok"):
                raw = res2.get("scores") or {}
            else:
                warnings.append((res2.get("message") or "نمایشِ نتیجه در مرورگر شکست خورد.") + " کد ساخته شد ولی تصویرِ مقایسه و امتیازها نیست.")
        else:
            warnings.append("مرورگرِ بی‌سرِ سرور آماده نیست؛ کد ساخته شد ولی تصویرِ مقایسه و امتیازها نیست.")
        share = measure_image_share(out / "tree.json")
        if share is not None:
            slim["image_share"] = share
            _set(conv, report=slim)
        scores, extra = build_scores(raw, slim, text_source, conv.lang)
        warnings.extend(extra)
        for which in ("original", "rendered"):
            preview_path(conv, which)                 # از همین حالا آماده باشد تا اولین باز کردنِ نتیجه سریع شود
        if not _set(conv, scores=scores, raw_scores=raw, warnings=warnings, state=Conversion.State.READY, step="done", progress=100.0, message="آماده شد", finished_at=timezone.now()):
            shutil.rmtree(conv.dir, ignore_errors=True)       # کاربر وسطِ کار حذفش کرد؛ فایل‌هایی که در این فاصله ساخته شد نماند
            return conv
        log.info("img2code #%s ready in %.1fs (%s)", conv.pk, time.monotonic() - t_all, conv.mode)
        return conv
    except Exception as exc:  # noqa: BLE001 — خطای پیش‌بینی‌نشده نباید ردیف را در «در حال تبدیل» بگذارد
        log.exception("img2code #%s crashed", conv.pk)
        return _fail(conv, "خطای پیش‌بینی‌نشده در تبدیل؛ دوباره امتحان کنید.", "%s: %s" % (type(exc).__name__, exc))
    finally:
        if not Conversion.objects.filter(pk=conv.pk).exists():          # کاربر وسطِ کار حذفش کرد: فایل‌هایی که runner در این فاصله نوشت نماند
            shutil.rmtree(conv.dir, ignore_errors=True)


def brand_words(conv: Conversion) -> list[str]:
    """نامِ فروشگاه (و نامِ صفحه برای نشانی): واژه‌هایی که در هیچ واژه‌نامه‌ای نیستند. OCR آن‌ها را خراب می‌خواند (چغر ⇒ چخر / چفر)؛ با این فهرست درست می‌شوند و هرگز «اصلاح» نمی‌شوند."""
    words: list[str] = []
    for src in (getattr(conv.store, "name", ""), conv.title if conv.source_kind == Conversion.Source.URL else ""):
        for w in str(src or "").replace("،", " ").replace("|", " ").replace("—", " ").replace("-", " ").split():
            w = w.strip(".,:;()«»\"'")
            if 2 <= len(w) <= 24 and "," not in w and w not in words:
                words.append(w)
    return words[:12]


# ───────────────────────────────────────────────────────────────── «این نتیجه عملاً یک تصویر است»
IMAGE_SHARE_WARN = 0.15           # از این بیشتر ⇒ نکته (زرد)
IMAGE_SHARE_BAD = 0.30            # از این بیشتر ⇒ هشدارِ قرمز: به‌جای موفقیتِ ساده
EDITABLE_BAD = 0.40               # سهمِ کدِ قابل‌ویرایش زیرِ این ⇒ قرمز
FEW_NODES = 8                     # صفحه‌ای بلندتر از ۵۰۰ پیکسل با کمتر از این جزء ⇒ قرمز


def measure_image_share(tree_path: Path) -> Optional[float]:
    """چند درصدِ مساحتِ صفحه در درختِ اجزا «تصویرِ چسبانده‌شده» است (اجتماعِ جعبهٔ گره‌های تصویر و آیکن‌های بدونِ برداری).
    موتورِ ۲٫۲ و قبل‌تر یک صفحهٔ گرادیان‌دار را یک تصویر می‌کرد و نتیجه «موفق» به نظر می‌آمد؛ این عدد جلوی آن را می‌گیرد."""
    try:
        tree = json.loads(Path(tree_path).read_text(encoding="utf-8"))
        W, H = int(tree.get("width") or 0), int(tree.get("height") or 0)
        if W <= 0 or H <= 0:
            return None
        k = 4                                                      # شبکهٔ درشت: کافی و سبک (صفحهٔ ۹۰۰۰ پیکسلی ⇒ ~۲ میلیون خانه)
        gw, gh = (W + k - 1) // k, (H + k - 1) // k
        grid = bytearray(gw * gh)

        def mark(box):
            x, y, w, h = [float(v) for v in box]
            x0, y0 = max(0, int(x // k)), max(0, int(y // k))
            x1, y1 = min(gw, int(-(-(x + w) // k))), min(gh, int(-(-(y + h) // k)))
            for yy in range(y0, y1):
                grid[yy * gw + x0:yy * gw + x1] = b"" * max(0, x1 - x0)

        def walk(n):
            role = n.get("role")
            if role == "image" or (role == "icon" and not n.get("vector", True)):
                if isinstance(n.get("box"), (list, tuple)) and len(n["box"]) == 4:
                    mark(n["box"])
            for c in n.get("children") or []:
                walk(c)
        walk(tree)
        return round(sum(grid) / float(gw * gh), 3)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def quality_alert(report: dict, raw: dict, source_kind: str = "upload") -> Optional[dict]:
    """هشدارِ پررنگ وقتی نتیجه عملاً یک تصویرِ چسبانده است (نه HTML قابل‌ویرایش)؛ ``None`` یعنی همه‌چیز عادی.
    level: «bad» (قرمز) یا «warn» (زرد). برای پنجرهٔ «ساختِ صفحه» هم همین می‌آید تا کاربر پیش از ساختنِ پیش‌نویس بداند."""
    share = report.get("image_share")
    ed = (raw or {}).get("editable_share")
    nodes = report.get("nodes")
    height = (report.get("size") or [0, 0])[1] if isinstance(report.get("size"), (list, tuple)) and len(report.get("size")) == 2 else 0
    bad = False
    reasons: list[str] = []
    if share is not None and share > IMAGE_SHARE_BAD:
        bad = True
        reasons.append("%s از مساحتِ صفحه به‌جای HTML/CSS با تصویرِ چسبانده‌شده پر شده" % _pct(share))
    if ed is not None and ed < EDITABLE_BAD:
        bad = True
        reasons.append("فقط %s از صفحه کدِ قابل‌ویرایش است" % _pct(ed))
    if nodes is not None and nodes < FEW_NODES and height >= 500:
        bad = True
        reasons.append("در صفحه فقط %s جزء شناخته شد" % _fa_digits(str(nodes)))
    if not bad:
        if share is not None and share > IMAGE_SHARE_WARN:
            return {"level": "warn", "title": "بخشی از صفحه تصویر مانده است",
                    "text": "%s از مساحتِ صفحه با تصویر پر شده (عکس‌های خودِ صفحه و هر چیزی که موتور نتوانست به کد تبدیل کند). اگر عکسِ واقعی نیست، آن بخش را در سایت‌ساز دستی بسازید." % _pct(share)}
        return None
    how = ("همین تصویر را با حالتِ دیگر (دکمهٔ «همین تصویر با حالتِ دیگر») دوباره بسازید؛ اگر باز هم تصویر شد، آن بخش را در سایت‌ساز دستی بسازید."
           if source_kind == "url" else
           "اگر صفحه آنلاین است نشانیِ آن را بدهید (تبِ «از نشانی») تا متن‌ها و رنگ‌ها از خودِ صفحه گرفته شود؛ وگرنه همین تصویر را با حالتِ دیگر (دکمهٔ «همین تصویر با حالتِ دیگر») دوباره بسازید.")
    return {"level": "bad", "title": "این نتیجه عملاً یک تصویر است، نه صفحهٔ قابل‌ویرایش",
            "text": "%s. پس متن‌ها و دکمه‌ها قابل‌ویرایش نیستند و پیش‌نویسِ سایت‌ساز بیشترش یک عکس می‌شود؛ این را «موفق» حساب نکنید. %s" % ("؛ ".join(reasons), how)}


REVIEW_KEEP = 40          # خط‌های نیازمندِ بررسی که در ردیف می‌ماند (کم‌اطمینان‌ترین‌ها)


def _slim_report(rep: dict) -> dict:
    keep = ("version", "mode", "lang", "page_direction", "ocr", "ocr_stats", "digits", "size", "scale", "regions", "text_lines", "nodes", "seconds", "review_lines", "image_share")
    out = {k: rep.get(k) for k in keep if k in rep}
    rows = []
    for r in (rep.get("review") or [])[:REVIEW_KEEP]:
        try:
            x, y, w, h = [int(v) for v in r["box"]]
            rows.append({"box": [x, y, w, h], "text": str(r.get("text") or "")[:200], "conf": round(float(r.get("conf") or 0), 2), "why": [str(k)[:12] for k in (r.get("why") or [])][:4]})
        except (KeyError, TypeError, ValueError):
            continue
    if rows or "review_lines" in rep:
        out["review"] = rows
    return out


def _verdict(v: float, good: float, ok: float) -> str:
    return "good" if v >= good else ("ok" if v >= ok else "weak")


VERDICT_FA = {"good": "خوب", "ok": "متوسط", "weak": "ضعیف"}


def _pct(v: float) -> str:
    return "%s٪" % _fa_digits(str(int(round(v * 100))))


def _fa_digits(s: str) -> str:
    return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def build_scores(raw: dict, report: dict, text_source: str, lang: str = "auto") -> tuple[list, list]:
    """امتیازهای خام ⇒ فهرستِ فارسیِ ساده + هشدارها."""
    out: list = []
    warns: list[str] = []
    ssim = raw.get("ssim")
    if ssim is not None:
        v = _verdict(ssim, 0.88, 0.72)
        out.append({"key": "ssim", "label": "شباهتِ ظاهرِ نتیجه به تصویر", "value": ssim, "display": _pct(ssim), "verdict": v, "verdict_fa": VERDICT_FA[v],
                    "hint": "هرچه به ۱۰۰٪ نزدیک‌تر باشد چیدمان و ظاهرِ صفحهٔ ساخته‌شده بیشتر شبیهِ تصویر است. بالای ۸۸٪ یعنی تقریباً همان؛ زیرِ ۷۲٪ یعنی ظاهرِ متفاوت."})
        if ssim < 0.65:
            warns.append("این تصویر برای تبدیل سخت بود (مثلاً عکس‌گونه، پس‌زمینهٔ پیچیده یا گرادیانِ بزرگ)؛ نتیجه را با «دقیق» هم امتحان کنید یا نشانیِ صفحه بدهید.")
    pix = raw.get("pixel_similarity")
    if pix is not None:
        v = _verdict(pix, 0.9, 0.8)
        out.append({"key": "pixel", "label": "تطابقِ رنگ‌به‌رنگِ پیکسل‌ها", "value": pix, "display": _pct(pix), "verdict": v, "verdict_fa": VERDICT_FA[v],
                    "hint": "میانگینِ نزدیکیِ رنگِ هر نقطه با تصویرِ اصلی. به‌تنهایی گول‌زنک است (صفحهٔ خالی هم عدد بالا می‌گیرد)؛ کنارِ «شباهتِ ظاهر» بخوانید."})
    ed = raw.get("editable_share")
    if ed is not None:
        v = _verdict(ed, 0.95, 0.8)
        out.append({"key": "editable", "label": "سهمِ کدِ قابل‌ویرایش", "value": ed, "display": _pct(ed), "verdict": v, "verdict_fa": VERDICT_FA[v],
                    "hint": "چند درصدِ صفحه HTML/CSSِ واقعی است و تصویرِ چسبانده‌شده نیست. عکس‌ها عمداً تصویر می‌مانند و حساب نمی‌شوند."})
    chars = raw.get("real_text_chars")
    n_lines = report.get("text_lines")
    if chars is not None:
        out.append({"key": "text", "label": "متنِ واقعی در نتیجه", "value": chars, "display": "%s نویسه" % _fa_digits(str(chars)), "verdict": "good" if chars else "weak",
                    "verdict_fa": VERDICT_FA["good" if chars else "weak"], "hint": "نوشته‌ها متنِ واقعی‌اند (قابل‌انتخاب و جست‌وجو و ویرایش)، نه عکسِ نوشته. %s خط متن پیدا شد." % _fa_digits(str(n_lines or 0))})
    share = report.get("image_share")
    if share is not None:
        v = "good" if share <= IMAGE_SHARE_WARN else ("ok" if share <= IMAGE_SHARE_BAD else "weak")
        out.append({"key": "image_share", "label": "بخشِ صفحه که تصویرِ چسبانده شد", "value": share, "display": _pct(share), "verdict": v, "verdict_fa": VERDICT_FA[v],
                    "hint": "چند درصدِ مساحتِ صفحه به‌جای HTML/CSS با یک تصویر پر شده (عکس‌های خودِ صفحه و هر چیزی که موتور نتوانست بسازد). هرچه کمتر بهتر؛ بالای ۳۰٪ یعنی نتیجه بیشترش عکس است و آن را موفق حساب نکنید."})
    nodes = report.get("nodes")
    if nodes is not None:
        out.append({"key": "nodes", "label": "اجزای شناسایی‌شده", "value": nodes, "display": "%s جزء" % _fa_digits(str(nodes)), "verdict": "good" if nodes else "weak",
                    "verdict_fa": VERDICT_FA["good" if nodes else "weak"], "hint": "دکمه، کارت، متن، ورودی، تصویر و … که جدا از هم تشخیص داده و در درختِ اجزا ثبت شد."})
    src_fa = "از خودِ صفحه (دقیق)" if text_source == "dom" else "با OCR (Tesseract)"
    v = "good" if text_source == "dom" else "ok"
    out.append({"key": "text_source", "label": "روشِ خواندنِ متن", "value": text_source, "display": src_fa, "verdict": v, "verdict_fa": VERDICT_FA[v],
                "hint": "وقتی نشانیِ صفحه داده شود نوشته‌ها از خودِ صفحه برداشته می‌شود و غلطِ املایی ندارد. در تصویرِ بارگذاری‌شده، متن با OCR خوانده می‌شود (غلط‌های نقطه‌ایِ فارسی با واژه‌نامه و نامِ فروشگاه اصلاح می‌شود) ولی در نوشته‌های ریزِ فارسی هنوز ممکن است چند حرف غلط باشد."})
    rv = report.get("review_lines")
    if text_source == "ocr" and rv is not None and report.get("ocr") not in (None, "none"):
        total = int(report.get("text_lines") or 0)
        share = (rv / total) if total else 0.0
        v = "good" if rv == 0 else ("ok" if share <= 0.25 else "weak")
        out.append({"key": "review", "label": "خط‌های نیازمندِ بررسی", "value": rv, "display": "%s از %s خط" % (_fa_digits(str(rv)), _fa_digits(str(total))), "verdict": v,
                    "verdict_fa": VERDICT_FA[v],
                    "hint": "خط‌هایی که OCR با اطمینانِ کم خوانده یا واژه‌ای دارند که در واژه‌نامه نیست. در تبِ «مقایسه» رویِ تصویر با کادرِ زرد و برچسبِ «این خط را بررسی کن» نشان داده می‌شوند؛ بقیهٔ خط‌ها را مطمئن‌تر خوانده‌ایم."})
        if rv:
            warns.append("%s خط از متن‌ها را با اطمینانِ کم خواندیم («این خط را بررسی کن»): در تبِ «مقایسه» با کادرِ زرد مشخص شده‌اند؛ یک بار بخوانیدشان." % _fa_digits(str(rv)))
    if text_source == "ocr" and report.get("page_direction") == "rtl":
        warns.append("متن‌ها با OCR خوانده شد؛ نوشته‌های ریزِ فارسی را یک بار بخوانید. اگر نشانیِ صفحه را دارید، با آن بسازید تا متن‌ها دقیق بیایند.")
    return out, warns


# ───────────────────────────────────────────────────────────────── خروجی‌ها
PREVIEW_MAX_W = 1400          # تصویرهای عریض‌تر برای نمایش کوچک می‌شوند؛ فایلِ کامل در ZIP و دانلود می‌ماند
PREVIEW_QUALITY = 86


def preview_path(conv: Conversion, which: str) -> Optional[Path]:
    """«original» / «rendered» ⇒ مسیرِ پیش‌نمایشِ WebP (اگر نبود همین حالا از PNG ساخته و کنارش نگه داشته می‌شود)."""
    src = conv.out_dir / ("%s.png" % which)
    if not src.is_file():
        return None
    dst = conv.out_dir / ("%s.preview.webp" % which)
    try:
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size > 0:
            return dst
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > PREVIEW_MAX_W:
                im = im.resize((PREVIEW_MAX_W, max(1, round(im.height * PREVIEW_MAX_W / im.width))), Image.LANCZOS)
            tmp = dst.with_name(dst.name + ".tmp")
            im.save(tmp, "WEBP", quality=PREVIEW_QUALITY, method=4)
        os.replace(tmp, dst)
        return dst
    except Exception as exc:  # noqa: BLE001 — پیش‌نمایش نشد ⇒ رابط به PNG برمی‌گردد
        log.warning("img2code preview for #%s %s failed: %s", conv.pk, which, exc)
        return None


def file_path(conv: Conversion, name: str) -> Optional[Path]:
    spec = FILES.get(name)
    if not spec:
        return None
    if name.endswith(".preview.webp"):
        return preview_path(conv, name.split(".", 1)[0])
    base = conv.out_dir if spec[0] == "out" else conv.dir
    p = base / name
    return p if p.is_file() else None


def files_available(conv: Conversion) -> dict:
    return {"original": file_path(conv, "original.png") is not None, "rendered": file_path(conv, "rendered.png") is not None,
            "html": file_path(conv, "index.html") is not None, "tree": file_path(conv, "tree.json") is not None}


def zip_bytes(conv: Conversion) -> bytes:
    out = conv.out_dir
    if not (out / "index.html").is_file():
        raise Img2CodeError("هنوز نتیجه‌ای نیست.", "not_ready", 409)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in ("index.html", "tree.json", "report.json", "original.png", "rendered.png"):
            p = out / rel
            if p.is_file():
                z.write(p, rel)
        fonts = out / "fonts"
        if fonts.is_dir():
            for p in sorted(fonts.iterdir()):
                if p.is_file():
                    z.write(p, "fonts/" + p.name)
    return buf.getvalue()


def code_payload(conv: Conversion) -> dict:
    def read(name, limit):
        p = file_path(conv, name)
        if p is None:
            return "", False
        data = p.read_text(encoding="utf-8", errors="replace")
        return (data[:limit], len(data) > limit)
    html, t1 = read("index.html", 1_200_000)
    css, t2 = read("style.css", 600_000)
    tree = ""
    p = file_path(conv, "tree.json")
    t3 = False
    if p is not None:
        try:
            tree = json.dumps(json.loads(p.read_text(encoding="utf-8")), ensure_ascii=False, indent=1)
        except ValueError:
            tree = ""
        if len(tree) > 400_000:
            tree, t3 = tree[:400_000], True
    return {"html": html, "css": css, "tree": tree, "truncated": bool(t1 or t2 or t3)}


def ui_design_link(conv: Conversion) -> Optional[dict]:
    """«باز کردن در طراحیِ UI»: فقط وقتی استودیوی طراحی روشن باشد (``uidesign.enabled``). ⇒ {label, path}؛ ``path`` وقتی هست که سندِ UI قبلاً از همین تبدیل ساخته شده
    (دکمه آن را باز می‌کند)، وگرنه None (دکمه اول سند را می‌سازد)."""
    from . import uidesign
    if conv.state != Conversion.State.READY or not uidesign.enabled():
        return None
    path = None
    if conv.ui_doc_id and uidesign.existing_doc(conv) is not None:
        path = uidesign.path_for(conv.store_id, conv.ui_doc_id)
    return {"label": "باز کردن در طراحیِ UI", "path": path}


def item_dict(conv: Conversion, detail: bool = False) -> dict:
    draft = None
    if conv.draft_project_slug and conv.draft_page_id:
        draft = {"project_slug": conv.draft_project_slug, "page_id": conv.draft_page_id, "url": "/tools/studio/p/%s/builder/page/%d" % (conv.draft_project_slug, conv.draft_page_id), "at": conv.draft_at}
    d = {
        "id": conv.pk, "title": conv.title, "source_kind": conv.source_kind, "source_label": conv.get_source_kind_display(), "source_url": conv.source_url,
        "mode": conv.mode, "mode_label": conv.get_mode_display(), "lang": conv.lang, "lang_label": conv.get_lang_display(), "width": conv.width,
        "state": conv.state, "state_label": conv.get_state_display(), "active": conv.active, "step": conv.step, "progress": round(conv.progress, 1),
        "message": conv.message, "error": conv.error, "size": [conv.size_w, conv.size_h], "created_at": conv.created_at, "finished_at": conv.finished_at,
        "scores": conv.scores or [], "warnings": conv.warnings or [], "draft": draft, "files": files_available(conv),
        "seconds": ((conv.report or {}).get("seconds") or {}).get("total"), "ocr": (conv.report or {}).get("ocr"),
    }
    rep = conv.report or {}
    if conv.state == Conversion.State.READY:
        d["alert"] = quality_alert(dict(rep, size=rep.get("size") or [conv.size_w, conv.size_h]), conv.raw_scores or {}, conv.source_kind)
    if conv.state == Conversion.State.READY and rep.get("text_source", "ocr") == "ocr" and rep.get("review_lines"):
        d["review"] = {"count": int(rep.get("review_lines") or 0), "lines": list(rep.get("review") or [])[:REVIEW_KEEP]}
    if conv.state == Conversion.State.QUEUED:
        d["queue_position"] = queue_position(conv)
    if conv.state == Conversion.State.READY:
        d["ui_design"] = ui_design_link(conv)
    return d


def cancel(conv: Conversion) -> Conversion:
    if conv.state in Conversion.ACTIVE:
        _set(conv, state=Conversion.State.CANCELLED, message="لغو شد", finished_at=timezone.now())
    return conv


def delete(conv: Conversion) -> None:
    d = conv.dir
    conv.delete()
    shutil.rmtree(d, ignore_errors=True)


def sweep() -> dict:
    """کارِ دوره‌ای: تبدیل‌های گیرکرده (بیش از ۳۰ دقیقه) را ناموفق کن؛ پوشه‌های بی‌ردیف را پاک کن."""
    now = timezone.now()
    # «در حال تبدیل» که نیم‌ساعت خبری نشد یعنی worker وسطِ کار مرد؛ «در صف» ماندگار است (اگر worker ساعت‌ها خاموش بود کار گم نمی‌شود) ⇒ فقط بعد از ۶ ساعت
    stale = list(Conversion.objects.filter(state=Conversion.State.RUNNING, updated_at__lt=now - timedelta(minutes=STALE_MINUTES))) +         list(Conversion.objects.filter(state=Conversion.State.QUEUED, updated_at__lt=now - timedelta(hours=6)))
    for c in stale:
        _set(c, state=Conversion.State.FAILED, error="این تبدیل متوقف شد (سرور در میانهٔ کار بسته یا دوباره بالا آمد)؛ دوباره بسازید.", message="ناموفق", finished_at=timezone.now())
    root = Path(settings.NM_DATA_DIR) / "img2code"
    removed = 0
    if root.is_dir():
        known = set(Conversion.objects.values_list("pk", flat=True))
        for p in root.iterdir():
            if p.is_dir() and p.name.startswith("conv") and p.name[4:].isdigit() and int(p.name[4:]) not in known:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
    return {"stale": len(stale), "removed_dirs": removed}
