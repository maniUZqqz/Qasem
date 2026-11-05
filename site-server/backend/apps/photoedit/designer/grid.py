"""قاب‌ها، حاشیهٔ امن و شبکهٔ چیدمان.

* ``FORMATS``: قابِ نهایی (همان ``catalog.SOCIAL_FORMATS``) + «orig» (اندازهٔ خودِ عکس).
* ``safe_rect``: حاشیهٔ امن به کسری از بوم. استوری: بالا ۱۴٪ (نامِ صفحه و پیشرفت) و پایین ۲۰٪ (پاسخ/دکمه‌ها) — پایینِ
  ۲۵۰px ِ بالا و ۳۴۰px ِ پایین در ۱۹۲۰. پستِ عمودی ۴:۵: در پروفایل مربعِ وسط دیده می‌شود ⇒ متنِ مهم در ۸۰٪ وسطِ ارتفاع.
* ``slot``: جعبه‌های نام‌دار داخلِ حاشیهٔ امن (کسری از بوم) برای چیدنِ تیتر، قیمت، دکمه…
  همه راست‌به‌چپ فکر شده‌اند: «شروع» = راست.
"""
from __future__ import annotations

from .. import catalog

FORMAT_KEYS = ("square", "portrait", "story", "landscape", "wide", "store", "orig")
FORMAT_FA = {"square": "مربع ۱:۱ (پست)", "portrait": "عمودی ۴:۵ (پست)", "story": "استوری ۹:۱۶", "landscape": "افقی ۱٫۹۱:۱ (بنر)",
             "wide": "افقی ۱۶:۹", "store": "مربعِ فروشگاه (۲۰۰۰)", "orig": "اندازهٔ خودِ عکس"}

#: l, t, r, b — کسری از پهنا/ارتفاعِ بوم
_SAFE = {
    "square": (0.07, 0.07, 0.07, 0.07),
    "portrait": (0.07, 0.10, 0.07, 0.10),      # مربعِ وسطِ ۴:۵ = ۱۲٪ تا ۸۸٪ ارتفاع؛ حاشیهٔ ۱۰٪ تقریباً آن را می‌پوشاند
    "story": (0.07, 0.14, 0.07, 0.20),
    "landscape": (0.06, 0.09, 0.06, 0.09),
    "wide": (0.06, 0.08, 0.06, 0.08),
    "store": (0.07, 0.07, 0.07, 0.07),
    "orig": (0.06, 0.06, 0.06, 0.06),
}


def canvas_size(fmt: str, photo_size: tuple[int, int] | None = None) -> tuple[int, int]:
    if fmt in catalog.SOCIAL_FORMATS:
        w, h, _ = catalog.SOCIAL_FORMATS[fmt]
        return w, h
    w, h = photo_size or (1080, 1080)
    return int(w), int(h)


def safe_rect(fmt: str) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) به کسری از بوم."""
    l, t, r, b = _SAFE.get(fmt, _SAFE["orig"])
    return l, t, 1.0 - r, 1.0 - b


def class_of(fmt: str, W: int | None = None, H: int | None = None) -> str:
    """دسته‌ی چیدمان: post (مربع/عمودی)، story، wide (افقی)."""
    if fmt == "story":
        return "story"
    if fmt in ("landscape", "wide"):
        return "wide"
    if fmt == "orig" and W and H:
        r = W / H
        return "wide" if r > 1.25 else "story" if r < 0.62 else "post"
    return "post"


def slot(name: str, fmt: str, W: int, H: int) -> tuple[float, float, float, float]:
    """جعبهٔ نام‌دار (x0, y0, x1, y1) به کسری از بوم، داخلِ حاشیهٔ امن."""
    sx0, sy0, sx1, sy1 = safe_rect(fmt)
    sw, sh = sx1 - sx0, sy1 - sy0
    cls = class_of(fmt, W, H)

    def box(fx0, fy0, fx1, fy1):
        return (sx0 + sw * fx0, sy0 + sh * fy0, sx0 + sw * fx1, sy0 + sh * fy1)

    th = 0.26 if cls == "post" else 0.30 if cls == "story" else 0.40   # ارتفاعِ باندِ بالا/پایین
    table = {
        "top": box(0, 0, 1, th),
        "bottom": box(0, 1 - th, 1, 1),
        "middle": box(0, 0.5 - th / 2, 1, 0.5 + th / 2),
        "upper": box(0, 0.0, 1, 0.5),
        "lower": box(0, 0.5, 1, 1.0),
        "left": box(0, 0, 0.5, 1),
        "right": box(0.5, 0, 1, 1),
        "tl": box(0, 0, 0.5, 0.2),
        "tr": box(0.5, 0, 1, 0.2),
        "bl": box(0, 0.8, 0.5, 1),
        "br": box(0.5, 0.8, 1, 1),
        "full": box(0, 0, 1, 1),
        "low": box(0, 0.65, 1, 0.78),
        "mr": box(0.62, 0.34, 1, 0.66),
        "ml": box(0, 0.34, 0.38, 0.66),
        "cta": box(0.22, 0.80 if cls != "wide" else 0.76, 0.78, 0.96 if cls != "wide" else 0.96),
    }
    if name not in table:
        raise KeyError(name)
    return table[name]


SLOT_NAMES = ("top", "bottom", "middle", "upper", "lower", "left", "right", "tl", "tr", "bl", "br", "mr", "ml", "low", "full", "cta")
#: نامِ فارسیِ جا (برای مرحله‌های خوانا)
SLOT_FA = {"top": "بالا", "bottom": "پایین", "middle": "وسط", "upper": "نیمهٔ بالا", "lower": "نیمهٔ پایین", "left": "چپ",
           "right": "راست", "tl": "گوشهٔ بالا-چپ", "tr": "گوشهٔ بالا-راست", "bl": "گوشهٔ پایین-چپ", "br": "گوشهٔ پایین-راست",
           "mr": "وسطِ راست", "ml": "وسطِ چپ", "low": "پایین‌تر از وسط", "full": "کلِ قاب", "cta": "جای دکمه", "auto": "خودکار (آرام‌ترین جا)"}


def inside(rect, safe) -> bool:
    return rect[0] >= safe[0] - 1e-3 and rect[1] >= safe[1] - 1e-3 and rect[2] <= safe[2] + 1e-3 and rect[3] <= safe[3] + 1e-3


def overlap_area(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def area(a) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
