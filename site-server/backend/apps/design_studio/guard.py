"""نگهبانِ «عددِ ساختگی»: هر عددی که در متنِ هوش مصنوعی هست باید در منبعِ واقعی (محصولات، واقعیت‌های برند، شرحِ کاربر) هم باشد.

قاعدهٔ مالک: قیمت و آمار هرگز ساخته نمی‌شود. اگر مدل عددی نوشت که در منبع نبود، همان عنصر دور ریخته (یا با متنِ قاعده‌ای جایگزین) می‌شود.
"""
from __future__ import annotations

import re

from . import typeset

_NUM = re.compile(r"\d+(?:[.,٫٬]\d+)*")
_WORD_NUMS = ("یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه", "ده")


def numbers_in(text: str) -> set[str]:
    """عددها (رقم فارسی/لاتین یکی می‌شوند؛ جداکننده‌ها حذف) — «۶۰۰٬۰۰۰» و «600,000» یکی‌اند."""
    t = typeset.digits(str(text or ""), "en")
    t = re.sub(r"(?<=\d)\.0+(?!\d)", "", t)           # 600000.0 ⇒ 600000
    out = set()
    for m in _NUM.findall(t):
        n = re.sub(r"[.,٫٬]", "", m).lstrip("0") or "0"
        out.add(n)
    return out


def corpus_numbers(*texts) -> set[str]:
    s: set[str] = set()
    for t in texts:
        s |= numbers_in(t)
    return s


def unsupported(text: str, allowed: set[str]) -> set[str]:
    """عددهایی از text که در allowed نیستند (۰ و ۱ و عددهای یک‌رقمیِ شمارهٔ گام آزادند)."""
    bad = set()
    for n in numbers_in(text):
        if n in allowed or len(n) <= 1:
            continue
        bad.add(n)
    return bad


def clean_text(text: str, allowed: set[str], fallback: str = "") -> str:
    return fallback if unsupported(text, allowed) else text
