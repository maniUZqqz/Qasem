"""فونت‌های فارسیِ ادیتورِ عکس (همه با مجوزِ SIL OFL 1.1؛ متنِ مجوزها کنارِ فایل‌ها در ``fonts/``).

وزیرمتن (``vazirmatn``) از ``textlayer.font_files()`` می‌آید (فونتِ سیستم یا ``services/imaging/fonts``)؛ بقیه این‌جاست.
هر فونت: کلید، عنوانِ فارسی، خانوادهٔ CSS، وزن ← نامِ فایل، و «نقش» (متنِ خوان یا تیترِ پرجلوه).

* ``path(key, weight)`` ⇐ نزدیک‌ترین وزنِ موجود (همان قاعده‌ای که مرورگر برای وزن‌های فایل‌دارِ همین فهرست به کار می‌برد).
* فونتی که فایلش روی سرور نیست در ``available()`` نمی‌آید.
"""
from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "fonts"
DEFAULT = "vazirmatn"

#: key ⇒ مشخصات. weights: وزن ⇒ نامِ فایل (در FONT_DIR)
FONTS: dict[str, dict] = {
    "estedad": {
        "title": "استعداد", "family": "Estedad", "role": "both", "license": "SIL OFL 1.1",
        "weights": {300: "Estedad-Light.ttf", 400: "Estedad-Regular.ttf", 500: "Estedad-Medium.ttf",
                    600: "Estedad-SemiBold.ttf", 700: "Estedad-Bold.ttf", 800: "Estedad-ExtraBold.ttf"},
        "note": "مدرن و تمیز؛ برای تیتر و متنِ تبلیغات",
    },
    "lalezar": {
        "title": "لاله‌زار", "family": "Lalezar", "role": "display", "license": "SIL OFL 1.1",
        "weights": {400: "Lalezar-Regular.ttf"},
        "note": "تیترِ درشت و پرجلوه (فقط یک وزن)",
    },
    "shabnam": {
        "title": "شبنم", "family": "Shabnam", "role": "text", "license": "SIL OFL 1.1",
        "weights": {300: "Shabnam-Light.ttf", 400: "Shabnam-Regular.ttf", 500: "Shabnam-Medium.ttf", 700: "Shabnam-Bold.ttf"},
        "note": "ساده و خوانا؛ برای متن‌های کوچک",
    },
    "sahel": {
        "title": "ساحل", "family": "Sahel", "role": "both", "license": "SIL OFL 1.1",
        "weights": {300: "Sahel-Light.ttf", 400: "Sahel-Regular.ttf", 600: "Sahel-SemiBold.ttf", 700: "Sahel-Bold.ttf",
                    800: "Sahel-Black.ttf"},
        "note": "گرم و گرد؛ برای پیام‌های دوستانه",
    },
    "samim": {
        "title": "صمیم", "family": "Samim", "role": "text", "license": "SIL OFL 1.1",
        "weights": {400: "Samim-Regular.ttf", 500: "Samim-Medium.ttf", 700: "Samim-Bold.ttf"},
        "note": "رسمی و آرام",
    },
}

#: فقط برای کدِ ما: کدام فونت برای کدام نقش در طراحیِ خودکار
DISPLAY_FONTS = ("lalezar", "estedad")
TEXT_FONTS = ("vazirmatn", "estedad", "shabnam", "samim", "sahel")


def _files(key: str) -> dict[int, Path]:
    spec = FONTS.get(key)
    if not spec:
        return {}
    out = {}
    for w, name in spec["weights"].items():
        p = FONT_DIR / name
        if p.is_file():
            out[w] = p
    return out


def available() -> list[str]:
    """کلیدِ فونت‌های اضافه‌ای که فایلشان روی سرور هست (به ترتیبِ تعریف)."""
    return [k for k in FONTS if _files(k)]


def known(key) -> bool:
    return isinstance(key, str) and (key == DEFAULT or key in available())


def weights(key: str) -> list[int]:
    return sorted(_files(key))


def path(key: str, weight: int) -> str | None:
    """نزدیک‌ترین وزن؛ None اگر این فونت روی سرور نیست."""
    files = _files(key)
    if not files:
        return None
    best = min(files, key=lambda w: (abs(w - int(weight)), -w))
    return str(files[best])


def info(key: str) -> dict:
    spec = FONTS[key]
    return {"key": key, "title": spec["title"], "family": spec["family"], "weights": weights(key), "rtl": True,
            "role": spec["role"], "note": spec["note"], "license": spec["license"]}
