"""مثال‌های آمادهٔ دستور برای «طراح خودکار»: از خودِ فروشگاه ساخته می‌شود (نامِ فروشگاه و محصول‌ها).

قاعده: هیچ قیمت، درصدِ تخفیف یا عددِ ساختگی در مثال‌ها نمی‌آید (مثالِ «کفش ورزشی با تخفیف ۳۰ درصد» برای فروشگاهِ خدماتِ
دیجیتال غلط بود). اگر نامِ محصول عدد، قیمت یا نشانهٔ تخفیف دارد کنار گذاشته می‌شود؛ بخشِ بعد از « — » و پرانتز هم حذف می‌شود.
"""
from __future__ import annotations

import re

#: مثال‌های بی‌نیاز به فروشگاه (وقتی محصولی نیست یا چند مثالِ دیگر لازم است) — بی قیمت
GENERIC_DESIGN = [
    "عکسِ کاتالوگ با پس‌زمینهٔ تمیز",
    "پستِ «محصولِ جدید»، شیک و خوانا",
    "استوریِ معرفی، رنگی و پرانرژی",
]

MAX_EXAMPLES = 5
MAX_NAME_LEN = 42
_UNSAFE = re.compile(r"[0-9۰-۹٠-٩%٪]|تومان|ریال|قیمت|تخفیف|درصد|رایگان|حراج|ارزان")
_DASH = re.compile(r"\s[—–-]\s")
_PAREN = re.compile(r"[(（][^)）]*[)）]")


def clean_name(name: str) -> str:
    """نامِ محصول ⇒ نامِ کوتاهِ بی‌عدد؛ '' اگر قابلِ‌استفاده نباشد."""
    n = _DASH.split(str(name or ""), maxsplit=1)[0]
    n = _PAREN.sub("", n)
    n = re.sub(r"\s+", " ", n).strip(" \t‌‏-–—:،,.")
    if not n or len(n) > MAX_NAME_LEN or _UNSAFE.search(n):
        return ""
    return n


def _quoted(name: str) -> str:
    """«…» فقط اگر خودِ نام گیومه ندارد."""
    return name if "«" in name else f"«{name}»"


def design_examples(store, products=None) -> list[str]:
    """نمونه دستورهای «طراح خودکار» برای همین فروشگاه (۳ تا ۵ مورد)."""
    if products is None:
        try:
            products = list(store.products.filter(is_available=True).order_by("-created_at", "-pk").values_list("name", flat=True)[:12])
        except Exception:  # noqa: BLE001 — مثال‌ها اختیاری‌اند؛ هرگز صفحه را خراب نکنند
            products = []
    names: list[str] = []
    for raw in products:
        n = clean_name(raw)
        if n and n not in names:
            names.append(n)
        if len(names) >= 3:
            break
    store_name = clean_name(getattr(store, "name", "") or "")
    out: list[str] = []
    if names:
        out.append(f"پستِ معرفیِ {_quoted(names[0])}، شیک و خوانا")
        out.append(f"استوریِ {_quoted(names[1] if len(names) > 1 else names[0])} با دعوت به اقدام، رنگی و پرانرژی")
        if len(names) > 2:
            out.append(f"بنرِ {_quoted(names[2])} با رنگ‌های برند")
    if store_name:
        out.append(f"پستِ معرفیِ {_quoted(store_name)}، شیک و گرم")
    for g in GENERIC_DESIGN:
        if len(out) >= MAX_EXAMPLES:
            break
        if g not in out:
            out.append(g)
    return out[:MAX_EXAMPLES]


def for_store(store) -> dict:
    return {"design": design_examples(store)}
