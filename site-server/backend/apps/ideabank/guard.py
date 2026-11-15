"""نگهبانِ «ادعای ساختگی» برای بانکِ ایده: عدد، قیمت، درصد، آمار و ادعای تأییدنشده.

SOURCE: واژه‌های ``RISKY`` از ``apps.thumbs.ideation`` (ported from NMarketing:backend/apps/thumbs/ideation.py، همین مخزن) گرفته شده و برای متنِ
ایده گسترش یافته. آزمونِ ``tests_seeds`` تضمین می‌کند این فهرست هیچ‌وقت از ``thumbs.ideation.RISKY`` کم‌تر نشود.

قاعده: هیچ ایده‌ای (آماده، فرمولی یا ساخته‌شده با هوش مصنوعی) عدد، قیمت، درصد، آمار، نتیجه یا نقلِ قولِ ساختگی نمی‌آورد. فقط اگر همان واژه یا عدد
در «منبعِ واقعی» بود (متنی که خودِ کاربر نوشته: موضوع، توضیح، «واقعیت‌های برند»، پروفایلِ فروشگاه) اجازه دارد.
"""
from __future__ import annotations

import re

#: واژه‌های قیمت/تخفیف/تضمین (همان فهرستِ تامنیل‌ساز)
RISKY = ("درصد", "تومان", "ریال", "تخفیف", "رایگان", "تضمین", "٪", "%", "$", "€")
#: ادعاهای آماری و برتری‌طلبیِ بی‌سند (فقط برای بانکِ ایده)
CLAIM_WORDS = ("برابر", "هزار", "میلیون", "میلیارد", "بهترین", "ارزان‌ترین", "ارزانترین", "مطمئن‌ترین", "بی‌رقیب", "اثبات‌شده", "تأییدشده")
ALL_RISKY = RISKY + CLAIM_WORDS

_DIGITS = re.compile(r"[0-9۰-۹٠-٩]+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
_FOLD_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# حرف‌های عربی/فارسی (U+0622-U+06D3 و شکل‌های نمایشی)؛ ارقامِ فارسی (U+06F0..) و عربی (U+0660..) حرف حساب نمی‌شوند
_PERSIAN_LETTER = re.compile(r"[آ-ٰٟ-ۓﭐ-﷿ﹰ-﻿]")
_LATIN_LETTER = re.compile("[A-Za-z]")


def persian_share(text: str) -> float:
    """سهمِ حرف‌های فارسی/عربی از همهٔ حرف‌ها (فارسی + لاتین)؛ متنِ بی‌حرف = ۰. ارقام و نشانه‌ها شمرده نمی‌شوند."""
    t = str(text or "")
    fa, en = len(_PERSIAN_LETTER.findall(t)), len(_LATIN_LETTER.findall(t))
    return fa / (fa + en) if (fa + en) else 0.0


def is_persian(text: str, minimum: float = 0.5) -> bool:
    """متن فارسی است (نامِ لاتینِ برند در جمله مجاز است («با Chagher شروع کن»)، جملهٔ انگلیسی نه)."""
    return persian_share(text) >= minimum


#: جای خالی که صاحبِ فروشگاه باید با دادهٔ واقعی پر کند: «[پیشنهادِ واقعیِ شما]»
SLOT = re.compile(r"\[[^\[\]]{1,80}\]")
#: جای‌گیرِ خودکار: «{محصول}»
PLACEHOLDER = re.compile(r"\{([^{}]{1,20})\}")


def _norm(text: str) -> str:
    return str(text or "").translate(_FOLD_DIGITS)


def digit_runs(text: str) -> list[str]:
    return [_norm(m) for m in _DIGITS.findall(str(text or ""))]


def problems(text: str, source: str = "") -> list[str]:
    """دلیل‌هایی که این متن «ادعای ساختگی» حساب می‌شود (خالی = سالم).

    ``source`` = متنی که خودِ کاربر نوشته؛ واژه یا عددی که در آن هست ادعای ساختگی نیست.
    """
    t = str(text or "")
    src = _norm(source)
    out: list[str] = []
    for w in ALL_RISKY:
        if w in t and w not in str(source or ""):
            out.append(f"واژهٔ «{w}»")
    for run in digit_runs(t):
        if run not in src:
            out.append(f"عدد «{run}»")
    if _EMOJI.search(t):
        out.append("ایموجی")
    return out


def is_clean(text: str, source: str = "") -> bool:
    return not problems(text, source)


def slots(text: str) -> list[str]:
    """جای‌های خالیِ «[...]» در متن (ترتیبِ دیده‌شدن، بدونِ تکرار)."""
    seen: dict[str, None] = {}
    for m in SLOT.findall(str(text or "")):
        seen[m] = None
    return list(seen)
