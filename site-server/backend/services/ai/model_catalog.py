# -*- coding: utf-8 -*-
"""فهرستِ مدل‌های لوکالِ شناخته‌شده: اندازه، کار، زنجیرهٔ جایگزین و فهرستِ مجازِ دانلود (۱۴۰۵/۰۸/۱۲).

سه کار می‌کند:

  ۱. `CHAINS` — برای هر نوعِ کار، ترتیبِ «مدلِ مناسبِ بعدی». اگر مدلِ انتخابی روی سرورِ پردازش نصب نبود، اولین مدلِ
     نصب‌شدهٔ این زنجیره جواب می‌دهد (پیش از آن‌که کار به متیس برود). ترتیبِ اولویتِ لوکال/متیس دست‌نخورده می‌ماند.
  ۲. `pullable()` — فهرستِ مجازِ دانلود. دکمهٔ «دانلود مدل» در پنل فقط برای برچسب‌هایی کار می‌کند که این‌جا هستند
     (یا با NM_AI_PULLABLE_EXTRA در .env اضافه شده‌اند)؛ گره هم همین فهرست را از سایت می‌پرسد و هر چیزِ بیرون از آن را
     نمی‌کشد. اندازه‌ها از manifest ِ رسمیِ registry.ollama.ai خوانده شده (۱۴۰۵/۰۸/۱۲)، یعنی همان بایت‌هایی که دانلود می‌شود.
  ۳. `request_profile()` — تنظیمِ هر درخواست برای مدل‌هایی که کلیدِ «فکر کردن» دارند (Qwen3: حالتِ بی‌فکر برای متنِ روزمره
     تا سریع باشد) و سقفِ پنجرهٔ متن برای مدل‌هایی که با ۱۶ هزار توکن در ۱۲ گیگابایت جا نمی‌شوند.

چرا مدلِ پیش‌فرضِ متنِ روزمره Gemma 3 12B است نه Qwen3 14B (اندازه‌گیری‌ها، ۱۴۰۵/۰۸/۱۲):
  · فارسی: توکنایزرِ Gemma 3 برای همان متنِ فارسی ۱٫۴۸ توکن به‌ازای هر واژه می‌سازد و Qwen3 ۲٫۹۹ (دو برابر) ⇒ همان جواب
    با نصفِ توکن، یعنی تقریباً دو برابر سریع‌تر؛ در آزمونِ فارسیِ MELAC (arXiv 2508.00673) هم Gemma-3-12B از Qwen3-14B جلوتر است.
  · اندازه: Gemma 3 12B ≈ ۸٫۲ GB (با بخشِ بینایی) و فقط ۸ لایه‌اش حافظهٔ کاملِ متن می‌خواهند (بقیه پنجرهٔ ۱۰۲۴ توکنی) ⇒ حافظهٔ
    متنش کوچک است؛ Qwen3 14B ≈ ۹٫۳ GB و حافظهٔ متنش ۱۶۰ کیلوبایت به‌ازای هر توکن است ⇒ با ۱۶ هزار توکن از ۱۲ گیگابایت بیرون
    می‌زند و بخشی روی CPU می‌رود (کند). برای اطمینان هر دو در `request_profile` سقفِ ۸ هزار توکن دارند (کارهای متنِ روزمره کوتاه‌اند)
    تا مستقل از این‌که Ollama حافظهٔ پنجره‌ای را پیاده کرده یا نه، کاملاً روی کارت بمانند؛ `ollama ps` باید ۱۰۰٪ GPU نشان بدهد.
  · Gemma 3 کلیدِ «فکر کردن» ندارد و ذاتاً سریع جواب می‌دهد؛ Qwen3 در زنجیره می‌ماند و با `think: false` بی‌فکر اجرا می‌شود.
"""
from __future__ import annotations

import os
import re

from .priority import CODE, RESEARCH, TEXT, VISION

#: برچسب ⇒ مشخصات. size_mb = مجموعِ لایه‌های manifest (مگابایتِ ۱۰۰۰۰۰۰ تایی، همان‌طور که Ollama نشان می‌دهد).
CATALOG: dict[str, dict] = {
    "gemma3:12b": {
        "label": "Gemma 3 — ۱۲ میلیاردی (گوگل)", "size_mb": 8164,
        "purpose": "متنِ روزمره: محتوا، کپشن، چتِ فروش، تبلیغ — فارسی و انگلیسیِ خوب، سریع، کاملاً روی کارتِ ۱۲ گیگابایتی",
        "vision": True,
    },
    "qwen3:14b": {
        "label": "Qwen3 — ۱۴ میلیاردی", "size_mb": 9276,
        "purpose": "جایگزینِ متنِ روزمره (بی‌فکر)، پشتیبانِ کد و پژوهش",
        "vision": False,
    },
    "qwen3:8b": {
        "label": "Qwen3 — ۸ میلیاردی", "size_mb": 5225,
        "purpose": "سبک‌تر و سریع‌تر، کیفیتِ کمتر",
        "vision": False,
    },
    "qwq:32b": {
        "label": "QwQ — ۳۲ میلیاردی (استدلال)", "size_mb": 19851,
        "purpose": "پژوهش و استدلالِ عمیق: بازار، رقبا، تحلیلِ تماس — کند ولی دقیق (روی ۱۲ گیگابایت بخشی روی CPU می‌رود)",
        "vision": False,
    },
    "qwen3-coder:30b": {
        "label": "Qwen3 Coder — ۳۰ میلیاردی", "size_mb": 18557,
        "purpose": "کد و سایت‌ساز", "vision": False,
    },
    "qwen3-vl:30b": {
        "label": "Qwen3 VL — ۳۰ میلیاردی (بینایی)", "size_mb": 19595,
        "purpose": "خواندنِ عکس: تحلیلِ محصول، کنترلِ کیفیت، ویرایشِ هوشمندِ عکس", "vision": True,
    },
}

#: هر نوعِ کار: ترتیبِ مدل‌های مناسب (اولی پیش‌فرض، بقیه جایگزین وقتی نصب نیستند)
CHAINS: dict[str, list[str]] = {
    # qwen3:8b before qwq:32b (1405/08/17): a model that fits wholly on the 12 GB card answers a caption in under a minute;
    # the 32B thinking model runs half on the CPU (2-7 min per caption; 8 jobs ran past the time limit on the owner's node)
    TEXT: ["gemma3:12b", "qwen3:14b", "qwen3:8b", "qwq:32b", "qwen3-vl:30b"],
    RESEARCH: ["qwq:32b", "qwen3:14b", "gemma3:12b", "qwen3-vl:30b"],
    # qwq:32b is not here on purpose: a whole site from a 32B thinking model on a 12 GB card runs past the site builder's
    # time limit — then Metis (or the clear error) is the better answer
    CODE: ["qwen3-coder:30b", "qwen3:14b"],
    VISION: ["qwen3-vl:30b", "gemma3:12b"],
}

#: برچسبِ مجاز ⇒ ساختارِ ساده (حروفِ کوچک و بزرگ، رقم، نقطه، خط تیره/زیرخط؛ ممکن است namespace داشته باشد)
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}(/[A-Za-z0-9][A-Za-z0-9._-]{0,60})?:[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")


def valid_tag(tag: str) -> bool:
    return bool(tag) and isinstance(tag, str) and bool(TAG_RE.fullmatch(tag)) and ".." not in tag


def _extra() -> dict[str, dict]:
    """NM_AI_PULLABLE_EXTRA="tag=size_mb,tag2=size_mb" (.env) — مدل‌های بیشتر برای دانلود از پنل. برچسبِ نادرست نادیده."""
    out: dict[str, dict] = {}
    for part in (os.environ.get("NM_AI_PULLABLE_EXTRA") or "").split(","):
        tag, _, size = part.strip().partition("=")
        tag = tag.strip()
        if not valid_tag(tag) or tag in CATALOG:
            continue
        try:
            mb = max(0, int(float(size)))
        except ValueError:
            mb = 0
        out[tag] = {"label": tag, "size_mb": mb, "purpose": "افزوده‌شده در تنظیماتِ سایت", "vision": False}
    return out


def all_models() -> dict[str, dict]:
    return {**CATALOG, **_extra()}


def pullable() -> dict[str, dict]:
    """فهرستِ مجازِ دانلود (برچسب ⇒ مشخصات). گره و پنل هر دو فقط همین‌ها را می‌کشند."""
    return all_models()


def is_pullable(tag: str) -> bool:
    return valid_tag(tag) and tag in pullable()


def info(tag: str) -> dict:
    """مشخصاتِ یک برچسب؛ ناشناخته ⇒ {}."""
    row = all_models().get(tag)
    return dict(row, tag=tag) if row else {}


def chain_for(kind: str, wanted: str = "") -> list[str]:
    """مدلِ انتخابی + مدل‌های مناسبِ بعدی (بی‌تکرار)."""
    out: list[str] = []
    for tag in [wanted] + list(CHAINS.get(kind, [])):
        if tag and tag not in out:
            out.append(tag)
    return out


# ───────────────────────────── تنظیمِ هر درخواست

_HYBRID_QWEN3 = re.compile(r"^qwen3:(\d+(?:\.\d+)?b)$", re.I)
_BIG_GEMMA3 = re.compile(r"^gemma3:(12b|27b)$", re.I)


def supports_think_switch(model: str) -> bool:
    """Qwen3ِ دورگه (qwen3:0.6b … 32b): با `think: false` بی‌فکر جواب می‌دهد. کدر/بینایی/نسخه‌های ۲۵۰۷ را شامل نمی‌شود."""
    return bool(_HYBRID_QWEN3.match((model or "").strip()))


def request_profile(model: str) -> dict:
    """{"think": False?, "num_ctx_max": int?} — چیزهایی که OllamaProvider به هر درخواستِ این مدل اضافه می‌کند."""
    prof: dict = {}
    low = (model or "").strip().lower()
    if supports_think_switch(low):
        prof["think"] = False
        m = _HYBRID_QWEN3.match(low)
        size = float(m.group(1)[:-1]) if m else 0
        if size >= 14:
            # ۹٫۳ GB وزن + ۱۶۰ KB حافظهٔ متن به‌ازای هر توکن: بیش از ۸ هزار توکن روی کارتِ ۱۲ گیگابایتی جا نمی‌شود
            prof["num_ctx_max"] = 8192
    if _BIG_GEMMA3.match(low):
        prof["num_ctx_max"] = 8192            # Gemma 3 has no think switch; only the window is capped (see the module docstring)
    return prof
