"""How a name should be *said*, which is not how it is written. §7.

The last line of §7 — «اسم برندها و کلمه‌های خاص را درست تلفظ می‌کنیم، نه حرف
به حرف» — is a real failure, not a nicety. Persian TTS given "Nike" reads it as
four English letters. A shop hears their own brand spelled out in a video they
are about to publish and loses trust in the whole product.

Two rules shape this module:

**The spoken form never replaces the written form.** The caption still says
"Nike"; only the narration text handed to the voice engine says «نایکی». They
are different outputs of the same script and conflating them would corrupt the
customer's own copy.

**Numbers are read as quantities, not as digits.** «۲۵۰۰۰۰ تومان» spelled digit
by digit is unusable in a sales video, and prices appear in almost every one we
make. `spell_number` is longer than the rest of this file for that reason.
"""
from __future__ import annotations

import re

#: Brands Iranian shops sell that Persian TTS reliably gets wrong. Deliberately
#: short: a giant table is a maintenance burden, and a shop can add its own
#: entries for anything we missed.
COMMON_BRANDS: dict[str, str] = {
    "Nike": "نایکی",
    "Adidas": "آدیداس",
    "Puma": "پوما",
    "Samsung": "سامسونگ",
    "Xiaomi": "شیائومی",
    "Huawei": "هواوی",
    "Apple": "اپل",
    "iPhone": "آیفون",
    "iPad": "آی‌پد",
    "AirPods": "ایرپاد",
    "MacBook": "مک‌بوک",
    "Sony": "سونی",
    "LG": "ال‌جی",
    "Philips": "فیلیپس",
    "Bosch": "بوش",
    "Zara": "زارا",
    "L'Oreal": "لورآل",
    "Nivea": "نیوآ",
    "Garnier": "گارنیه",
    "Maybelline": "میبلین",
    "Casio": "کاسیو",
    "Rolex": "رولکس",
    "Levis": "لیوایز",
    "Reebok": "ریباک",
    "Converse": "کانورس",
    "New Balance": "نیوبالانس",
    "Under Armour": "آندر آرمور",
    "Dyson": "دایسون",
    "Xbox": "ایکس‌باکس",
    "PlayStation": "پلی‌استیشن",
}

#: Words that are Persian but that the voice stumbles on, usually because they
#: are written without the vowel that disambiguates them.
COMMON_WORDS: dict[str, str] = {
    "UpMarket": "آپ‌مارکت",
    "آپ‌مارکت": "آپ مارکت",
    "AI": "هوش مصنوعی",
    "off": "تخفیف",
    "OFF": "تخفیف",
}

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

_ONES = [
    "", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه",
]
_TEENS = [
    "ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده",
    "هفده", "هجده", "نوزده",
]
_TENS = [
    "", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود",
]
_HUNDREDS = [
    "", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد",
    "هشتصد", "نهصد",
]
#: Scale words. Persian stops at میلیارد in ordinary speech; beyond that a sales
#: video is quoting a number nobody says aloud anyway.
_SCALES = [(1_000_000_000, "میلیارد"), (1_000_000, "میلیون"), (1_000, "هزار")]


def to_english_digits(text: str) -> str:
    """Normalise Persian and Arabic digits so one code path handles all three."""
    table = {ord(p): str(i) for i, p in enumerate(_PERSIAN_DIGITS)}
    table.update({ord(a): str(i) for i, a in enumerate(_ARABIC_DIGITS)})
    return text.translate(table)


def _under_thousand(number: int) -> str:
    parts = []
    if number >= 100:
        parts.append(_HUNDREDS[number // 100])
        number %= 100
    if 10 <= number <= 19:
        parts.append(_TEENS[number - 10])
    else:
        if number >= 20:
            parts.append(_TENS[number // 10])
            number %= 10
        if number > 0:
            parts.append(_ONES[number])
    return " و ".join(p for p in parts if p)


def spell_number(number: int) -> str:
    """۲۵۰۰۰۰ → «دویست و پنجاه هزار».

    Written out because a price is the single most important number in a sales
    video, and a voice that reads it "two five zero zero zero zero" has ruined
    the video regardless of how good the picture is.
    """
    if number == 0:
        return "صفر"
    sign = "منفی " if number < 0 else ""
    number = abs(number)

    parts = []
    for value, name in _SCALES:
        if number >= value:
            count = number // value
            number %= value
            parts.append(f"{_under_thousand(count)} {name}".strip())
    if number:
        parts.append(_under_thousand(number))
    return sign + " و ".join(parts)


#: Long enough that reading it digit by digit is wrong, short enough that a
#: model number like "A52" is left alone.
_NUMBER = re.compile(r"(?<![\w؀-ۿ])(\d{1,3}(?:[,،]\d{3})+|\d+)(?![\w؀-ۿ])")


def spell_numbers_in(text: str) -> str:
    """Replace bare numbers with their spoken form.

    Four digits is the floor. Below that Persian TTS reads "۲۵۰" correctly as a
    quantity already, and rewriting it only adds a chance of being wrong.
    """
    def replace(match: re.Match) -> str:
        raw = match.group(1).replace(",", "").replace("،", "")
        if len(raw) < 4:
            return match.group(1)
        try:
            return spell_number(int(raw))
        except ValueError:
            return match.group(1)

    return _NUMBER.sub(replace, to_english_digits(text))


#: A letter of any script we care about, plus the zero-width non-joiner, which
#: Persian uses *inside* words («آی‌پد») and which `\w` does not cover.
_LETTER = r"[\w‌]"


def _boundary_pattern(word: str) -> re.Pattern:
    """Match `word` only as a whole word.

    The edges are spelled out rather than using `\\b`, because the boundary that
    matters here is "not part of a longer word in any script" — and «آی‌پد»
    contains a ZWNJ that `\\b` treats as the end of a word.
    """
    return re.compile(
        rf"(?<!{_LETTER}){re.escape(word)}(?!{_LETTER})", re.IGNORECASE,
    )


def build(store=None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The pronunciation table for one store: ours, then theirs on top.

    The shop's own entries win. They know how they say their brand name and we
    do not get to overrule them. `extra` replaces the saved entries — the
    settings page previews a list before it is saved.
    """
    table = dict(COMMON_BRANDS)
    table.update(COMMON_WORDS)
    if extra is not None:
        table.update(extra)
    elif store is not None:
        table.update(store_entries(store))
    return table


def store_entries(store) -> dict[str, str]:
    """A shop's own pronunciations, from its store profile."""
    try:
        profile = store.profile
    except Exception:  # noqa: BLE001 — no profile row yet, or not a Store
        return {}
    raw = getattr(profile, "pronunciations", None)
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for written, spoken in list(raw.items())[:200]:
        written, spoken = str(written).strip(), str(spoken).strip()
        if written and spoken:
            cleaned[written] = spoken
    return cleaned


def apply(text: str, store=None, *, numbers: bool = True, extra: dict[str, str] | None = None) -> str:
    """Rewrite narration into what the voice should actually say.

    Longest entries first: a shop with both "Galaxy" and "Galaxy Watch" means
    the two-word one when they wrote two words, and replacing "Galaxy" first
    would leave «گلکسی Watch».
    """
    if not text:
        return text
    table = build(store, extra)
    spoken = text
    for written in sorted(table, key=len, reverse=True):
        spoken = _boundary_pattern(written).sub(table[written], spoken)
    if numbers:
        spoken = spell_numbers_in(spoken)
    return spoken


def unresolved_latin(text: str, store=None, extra: dict[str, str] | None = None) -> list[str]:
    """Latin words we have no pronunciation for — these are what will be spelled out.

    Surfaced to the shop rather than guessed at. A transliteration engine that
    invents «سی‌ثری» for a word it has never seen is worse than a prompt asking
    the one person who knows.
    """
    table = {w.lower() for w in build(store, extra)}
    words = re.findall(r"[A-Za-z][A-Za-z'’\-]{1,}", text or "")
    seen, out = set(), []
    for word in words:
        key = word.lower()
        if key in table or key in seen:
            continue
        seen.add(key)
        out.append(word)
    return out
