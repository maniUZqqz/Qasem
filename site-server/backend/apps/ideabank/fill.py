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


#: پرانتز/نقل‌قولِ باز و بسته: عبارتِ بریده‌شده هیچ‌وقت با یکی از این‌ها «باز» نمی‌ماند
_BRACKETS = (("(", ")"), ("[", "]"), ("«", "»"), ("“", "”"))
#: عبارتِ توضیحیِ آخرِ نام: «برنامهٔ تکی (فقط ورزشی یا فقط غذایی)» ⇒ «برنامهٔ تکی»
_TAIL_NOTE = re.compile(r"\s*(?:\([^()]*\)|\[[^\[\]]*\]|«[^«»]*»)\s*$")
_EDGE = " ،,؛:.!؟?-—"


def balanced(text: str) -> bool:
    """همهٔ پرانتز، کروشه و گیومه‌ها بسته شده‌اند؟ («فقط (ورزشی» ⇒ False)"""
    t = str(text or "")
    return all(t.count(o) == t.count(c) for o, c in _BRACKETS)


def clip_phrase(text: str, max_words: int = 6, max_chars: int = 48) -> str:
    """عبارت را روی مرزِ واژه می‌برد: نه وسطِ کلمه، نه روی حرفِ اضافه و **نه وسطِ پرانتز یا گیومه**.

    اگر عبارت جا می‌شود دست نمی‌خورد (نامِ محصول نباید کوتاه شود). اگر جا نمی‌شود اول توضیحِ پرانتزیِ آخرش می‌افتد، بعد واژه‌های آخر تا
    عبارتِ باقی‌مانده بسته و کامل باشد."""
    words = [w for w in re.sub(r"\s+", " ", str(text or "")).strip(_EDGE).split(" ") if w]

    def fits(ws: list[str]) -> bool:
        return len(ws) <= max_words and len(" ".join(ws)) <= max_chars

    if not fits(words):
        short = _TAIL_NOTE.sub("", " ".join(words)).strip(_EDGE)
        if short and short != " ".join(words):
            words = [w for w in short.split(" ") if w]
    while words and (not fits(words) or not balanced(" ".join(words))):
        words.pop()
    while words and words[-1] in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ،,؛:-—")


def audience_phrase(audience: str) -> str:
    """«مربی‌های باشگاه و مربی‌های شخصی که …؛ و ورزشکارانی …» ⇒ «مربی‌های باشگاه و مربی‌های شخصی»."""
    first = _SPLIT_AUDIENCE.split(str(audience or ""), maxsplit=1)[0]
    first = re.split(r"[،,]", first, maxsplit=1)[0]
    return clip_phrase(first, 6, 48)


def business_phrase(business_type: str) -> str:
    """«نرم‌افزار و خدمات دیجیتال برای مربیان ورزشی» کامل می‌ماند (تا ۸ واژه)؛ فقط توضیحِ خیلی بلند بریده می‌شود."""
    return clip_phrase(business_type, 8, 64)


#: نامِ محصول تا این اندازه هیچ‌وقت بریده نمی‌شود (نامِ بیشترِ محصول‌ها کوتاه‌تر است؛ نیمه‌کاره‌بودنِ نام معنی را عوض می‌کند)
PRODUCT_WORDS, PRODUCT_CHARS = 14, 80


def product_phrase(name: str) -> str:
    return clip_phrase(name, PRODUCT_WORDS, PRODUCT_CHARS)


_IMPERATIVE_END = re.compile(
    r"(?:شو|شوید|کن|کنید|بساز|بسازید|بخر|بخرید|ببین|ببینید|بیا|بیایید|باش|باشید|بگیر|بگیرید|بده|بدهید|بخوان|بخوانید|بنویس|بنویسید|بفرست|بفرستید|بزن|بزنید|"
    r"برو|بروید|بپرس|بپرسید|بمان|بمانید|بخواه|بخواهید|بدان|بدانید|بچش|بچشید|بپوش|بپوشید|بردار|بردارید|بگو|بگویید|بپیوند|بپیوندید)$")


def is_slogan(fact: str) -> bool:
    """شعار یا دستورِ تبلیغاتی («با چغر چغر تر شو»): با فعلِ امری یا «!» تمام می‌شود. شعار «واقعیت» نیست و «پرسش و پاسخ دربارهٔ شعار» بی‌معنی است؛
    آن را فقط در کارتِ یک‌جمله‌ای و ریلِ شعار می‌آوریم."""
    t = re.sub(r"\s+", " ", str(fact or "")).strip()
    words = [w for w in t.strip(_EDGE).split(" ") if w]
    return bool(words) and (t.endswith("!") or bool(_IMPERATIVE_END.search(words[-1])))


def tone_of(store) -> str:
    prof = getattr(store, "profile", None) if store is not None else None
    return str(getattr(prof, "tone", "") or getattr(prof, "brand_voice", "") or "").strip()[:100] if prof else ""


def context(store, product=None) -> dict:
    """جای‌گیرها + این‌که کدام‌شان واقعاً از پروفایل آمده (برای نمایشِ «این را در پروفایل پر کنید»)."""
    name = str(getattr(store, "name", "") or "").strip()
    audience = audience_phrase(getattr(store, "target_audience", ""))
    business = business_phrase(getattr(store, "business_type", ""))
    product_name = product_phrase(getattr(product, "name", "") if product is not None else "")
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
