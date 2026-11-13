"""«آزمونِ خودکارِ سرورِ پردازش» — رجیستری (۱۴۰۵/۰۸/۲۱).

وقتی سرورِ پردازش با نسخهٔ تازهٔ عامل وصل می‌شود، هر شب، و با دکمهٔ «آزمونِ کامل»، سایت برای هر قابلیت **یک کارِ واقعیِ کوچک**
به آن سرور می‌فرستد و نتیجه را می‌سنجد: قبول/رد، زمان، دستگاهِ به‌کاررفته (کارت یا پردازنده) و خروجیِ قابلِ‌دیدن.

هر ویژگی یک فایلِ کوچک در همین پوشه است که `register(SelfTest(...))` می‌زند (ویژگی‌های دیگر هم می‌توانند فایل بیندازند)؛ یا یک
`docs/selftests/<ویژگی>.md` با بلوکِ ```json (نگاه کنید به docs_loader.py).

یک آزمون:
    key        شناسهٔ کوتاه (یکتا)               label  نامِ فارسی           group  دسته (gpu، text، image، audio، video، system)
    build      ctx ⇒ Spec(kind, payload, files)   کارِ واقعی؛ None یعنی آزمونِ مجازی (بی کار؛ فقط `virtual` ارزیابی می‌شود)
    check      (ctx, job) ⇒ Verdict               سنجشِ خروجی
    available  node ⇒ (ok, چرا نه)                 اگر این گره آن قابلیت را ندارد، آزمون «ردشده» می‌شود نه «رد»
    after      کلیدهای پیش‌نیاز (خروجی‌شان ورودیِ این است)   gpu_required  اگر روی پردازنده اجرا شد = رد
    optional   اختیاری (در نتیجهٔ کلی نمی‌آید)       deep  فقط در «آزمونِ عمیق»          final  تنها وقتی همهٔ آزمون‌های دیگر تمام شدند
    requeue    {"kinds": (...), "match": job ⇒ bool}  پس از قبول، کارهای قبلاً ناموفقِ همین قابلیت دوباره به صف می‌روند
    min_agent  کمترین نسخهٔ عامل که این آزمون را می‌شناسد (مثلاً "2.11")؛ عاملِ قدیمی‌تر «نمی‌تواند» و تا رسیدنِ به‌روزرسانی
               صبر می‌شود (نه «رد»)
    needs_features  نامِ ویژگی‌های requirements.d که این آزمون به آن‌ها تکیه دارد (مثلاً "gpu-runtime")؛ تا پایانِ نصبشان صبر می‌شود
               (و تا وقتی عاملِ تازه‌بالاآمده هنوز نصبِ خودکار را گزارش نکرده)
"""
from __future__ import annotations

import importlib
import io
import json
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class Spec:
    kind: str
    payload: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)          # {نامِ فایل: bytes}
    timeout_s: int = 600
    priority: int = 15


@dataclass
class Verdict:
    ok: bool
    detail: str = ""
    device: str = ""
    warning: str = ""
    skip: bool = False
    wait: bool = False                                 # هنوز نمی‌شود قضاوت کرد (مثلاً نصب در حال انجام است)؛ بعداً دوباره
    extra: dict = field(default_factory=dict)

    @classmethod
    def passed(cls, detail: str = "", **kw):
        return cls(True, detail, **kw)

    @classmethod
    def failed(cls, detail: str, **kw):
        return cls(False, detail, **kw)

    @classmethod
    def skipped(cls, detail: str):
        return cls(False, detail, skip=True)

    @classmethod
    def waiting(cls, detail: str, **kw):
        return cls(False, detail, wait=True, **kw)


def _always(node):
    return True, ""


# ───────────────────────────── نسخهٔ عامل و نصبِ خودکار (برای صبر به‌جای رد)

BOOT_MIN_AGENT = "2.11"        # از این نسخه به بعد عامل نصبِ خودکار (caps["bootstrap"]) دارد
YOUNG_AGENT_S = 180            # عاملی که تازه‌تر از این بالا آمده هنوز نصبش را شروع نکرده/تمام نکرده است
BOOT_ABSENT_S = 6 * 60         # عاملِ جدید این‌قدر بعد از شروع باید نصبِ خودکار را گزارش کرده باشد؛ وگرنه آن را راه نینداخته
BOOT_BUSY = ("installing", "waiting")


def version_tuple(v) -> tuple:
    out = []
    for part in str(v or "").strip().lstrip("vV").split(".")[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def agent_at_least(caps: dict, minimum: str) -> bool:
    """عاملِ گره دست‌کم این نسخه است؟ (عاملی که نسخه‌اش را نگفته «قدیمی» حساب می‌شود)"""
    have = (caps or {}).get("agent")
    return bool(have) and version_tuple(have) >= version_tuple(minimum)


def agent_age_s(caps: dict, now=None) -> float | None:
    """چند ثانیه از شروعِ این پردازشِ عامل گذشته (ساعتِ گره در برابرِ ساعتِ سایت)؛ None اگر معلوم نیست یا ساعت‌ها نمی‌خوانند."""
    import time

    started = (caps or {}).get("started_at")
    try:
        age = (now if now is not None else time.time()) - float(started)
    except (TypeError, ValueError):
        return None
    return age if -60 <= age <= 24 * 3600 else None


def bootstrap_features(caps: dict) -> dict | None:
    """caps["bootstrap"]["features"]؛ None وقتی عامل هنوز گزارشش را نداده است."""
    boot = (caps or {}).get("bootstrap")
    feats = boot.get("features") if isinstance(boot, dict) else None
    return feats if isinstance(feats, dict) and feats else None


@dataclass
class SelfTest:
    key: str
    label: str
    group: str = "system"
    kind: str = ""
    build: Callable | None = None
    check: Callable | None = None
    virtual: Callable | None = None                    # ctx ⇒ Verdict (آزمونِ بی کار)
    available: Callable = _always
    after: tuple = ()
    gpu_required: object = False                        # bool یا ctx ⇒ bool
    optional: bool = False
    deep: bool = False
    final: bool = False
    requeue: dict | None = None
    order: int = 100
    wait_install_s: int = 4 * 3600                      # تا کی منتظرِ پایانِ نصبِ پیش‌نیازها می‌ماند
    describe: str = ""
    min_agent: str = ""                                 # «2.11» ⇒ عاملِ قدیمی‌تر: صبر برای به‌روزرسانی یا (اگر نمی‌آید) خطای روشن
    needs_features: tuple = ()                          # ویژگی‌های requirements.d که پیش از آزمون باید نصب شده باشند


REGISTRY: dict[str, SelfTest] = {}
_LOADED = {"done": False}


def register(test: SelfTest) -> SelfTest:
    REGISTRY[test.key] = test
    return test


def load_all(force: bool = False) -> dict:
    """همهٔ ماژول‌های این پوشه + docs/selftests/*.md را بار می‌کند (یک بار)."""
    if _LOADED["done"] and not force:
        return REGISTRY
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_") or mod.name in ("runner", "requeue", "docs_loader"):
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:  # noqa: BLE001 — یک آزمونِ خراب نباید بقیه را بخواباند
            logger.exception("selftests: module %s could not be loaded", mod.name)
    try:
        from . import docs_loader

        docs_loader.register_all()
    except Exception:  # noqa: BLE001
        logger.exception("selftests: docs/selftests could not be read")
    _LOADED["done"] = True
    return REGISTRY


def tests(deep: bool = False) -> list[SelfTest]:
    load_all()
    out = [t for t in REGISTRY.values() if deep or not t.deep]
    return sorted(out, key=lambda t: (t.order, t.key))


# ───────────────────────────── ابزارهای مشترکِ آزمون‌ها

def png(kind: str = "square", size: int = 256) -> bytes:
    """تصویرِ آزمون با Pillow: «square» = مربعِ قرمزِ بزرگ روی سفید؛ «subject» = دایرهٔ آبی روی زمینهٔ نارنجی (برای جداسازی)."""
    from PIL import Image, ImageDraw

    if kind == "subject":
        im = Image.new("RGB", (size, size), (240, 160, 40))
        d = ImageDraw.Draw(im)
        d.ellipse((size * 0.25, size * 0.2, size * 0.75, size * 0.8), fill=(30, 60, 200))
    else:
        im = Image.new("RGB", (size, size), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.rectangle((size * 0.15, size * 0.15, size * 0.85, size * 0.85), fill=(220, 20, 20))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


class Ctx:
    """آنچه یک آزمون هنگامِ ساخت و سنجش می‌بیند."""

    def __init__(self, node, run, results: dict | None = None, result=None):
        self.node = node
        self.run = run
        self.results = results or {}          # key ⇒ SelfTestResult
        self.result = result                  # ردیفِ همین آزمون (آزمون‌های مجازی در result.extra حالت نگه می‌دارند)

    @property
    def caps(self) -> dict:
        return self.node.capabilities or {}

    def job(self, key: str):
        from ..models import ComputeJob

        r = self.results.get(key)
        return ComputeJob.objects.filter(uid=r.job_uid).first() if r and r.job_uid else None

    def output_path(self, job, name: str):
        from .. import services as SV

        return SV.output_path(job, name)

    def read_output(self, job, name: str) -> bytes | None:
        p = self.output_path(job, name)
        try:
            return p.read_bytes() if p.is_file() else None
        except OSError:
            return None

    def read_json(self, job, name: str):
        raw = self.read_output(job, name)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def meta(self, job) -> dict:
        return ((job.result or {}).get("meta") or {}) if job else {}

    def installed_ollama(self) -> list[str]:
        return [m for m in (self.caps.get("ollama_models") or []) if isinstance(m, str)]


def caps_ok(node, *flags, startable: bool = True, why: str = "") -> tuple[bool, str]:
    """گره باید یکی از این پرچم‌ها را داشته باشد (یا با سوئیچِ خودکار بتواند روشنش کند)."""
    caps = node.capabilities or {}
    for f in flags:
        if caps.get(f):
            return True, ""
        if startable and node.auto_switch and (caps.get("startable") or {}).get(f):
            return True, ""
    return False, why or ("این سرور %s ندارد" % "/".join(flags))
