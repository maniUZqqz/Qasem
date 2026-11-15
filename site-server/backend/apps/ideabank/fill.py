"""پرکردنِ جای‌گیرهای ایده از پروفایلِ فروشگاه: ``{محصول} {فروشگاه} {مخاطب} {حوزه}``.

ایده‌ها به‌صورتِ «قالب» نگه داشته می‌شوند و موقعِ نمایش پر می‌شوند؛ پس با عوض‌شدنِ محصولِ انتخابی یا پروفایل، همان ایده به‌روز می‌ماند.
هیچ داده‌ای ساخته نمی‌شود: اگر فروشگاه مخاطب یا حوزه ننوشته، یک واژهٔ عمومی («مشتری‌ها») می‌آید و به کاربر گفته می‌شود چه چیزی خالی است.
"""
from __future__ import annotations

import re

from . import guard

FALLBACK = {"محصول": "محصول", "مخاطب": "مشتری‌ها", "حوزه": "کسب‌وکار"}
#: واژه‌هایی که یک عبارتِ بریده‌شده نباید با آن‌ها تمام شود
_DANGLING = {"از", "به", "در", "با", "برای", "و", "که", "را", "تا", "یا", "هم", "این", "آن", "یک", "بر", "بی", "چون", "اگر", "مثل", "هر", "همه", "چند", "کدام", "چه", "تمام", "همین"}
_SPLIT_AUDIENCE = re.compile(r"[؛;.\n]|\s+که\s+")


def clip_phrase(text: str, max_words: int = 6, max_chars: int = 48) -> str:
    """عبارت را روی مرزِ واژه می‌برد (نه وسطِ کلمه و نه روی حرفِ اضافه)."""
    words = re.sub(r"\s+", " ", str(text or "")).strip(" ،,؛:.!؟?-—").split(" ")
    words = [w for w in words if w]
    while words and (len(words) > max_words or len(" ".join(words)) > max_chars):
        words.pop()
    while words and words[-1] in _DANGLING:
        words.pop()
    return " ".join(words)


def audience_phrase(audience: str) -> str:
    """«مربی‌های باشگاه و مربی‌های شخصی که …؛ و ورزشکارانی …» ⇒ «مربی‌های باشگاه و مربی‌های شخصی»."""
    first = _SPLIT_AUDIENCE.split(str(audience or ""), maxsplit=1)[0]
    first = re.split(r"[،,]", first, maxsplit=1)[0]
    return clip_phrase(first, 6, 48)


def business_phrase(business_type: str) -> str:
    return clip_phrase(business_type, 5, 40)


def tone_of(store) -> str:
    prof = getattr(store, "profile", None) if store is not None else None
    return str(getattr(prof, "tone", "") or getattr(prof, "brand_voice", "") or "").strip()[:100] if prof else ""


def context(store, product=None) -> dict:
    """جای‌گیرها + این‌که کدام‌شان واقعاً از پروفایل آمده (برای نمایشِ «این را در پروفایل پر کنید»)."""
    name = str(getattr(store, "name", "") or "").strip()
    audience = audience_phrase(getattr(store, "target_audience", ""))
    business = business_phrase(getattr(store, "business_type", ""))
    product_name = clip_phrase(getattr(product, "name", "") if product is not None else "", 6, 60)
    return {
        "values": {
            "محصول": product_name or FALLBACK["محصول"],
            "فروشگاه": name or "فروشگاهتان",
            "مخاطب": audience or FALLBACK["مخاطب"],
            "حوزه": business or FALLBACK["حوزه"],
        },
        "known": {"محصول": bool(product_name), "فروشگاه": bool(name), "مخاطب": bool(audience), "حوزه": bool(business)},
        "tone": tone_of(store),
    }


def fill_text(text: str, ctx: dict | None) -> str:
    values = (ctx or {}).get("values") or {}

    def repl(m):
        return values.get(m.group(1), m.group(0))

    return guard.PLACEHOLDER.sub(repl, str(text or ""))


def used_placeholders(*texts: str) -> list[str]:
    found: dict[str, None] = {}
    for t in texts:
        for m in guard.PLACEHOLDER.findall(str(t or "")):
            found[m] = None
    return list(found)
