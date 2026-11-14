"""A quality gate for caption text, read from the shop's own rules.

A local model that writes Persian marketing copy is fast and tireless and now
and then wrong in ways a tired owner does not see at 11 p.m.: a price with a
lost digit («۶۰۰٬۰۰ تومان»), the same call-to-action printed twice, a claim the
owner explicitly banned. None of that is worth blocking a draft over, but all
of it is worth *saying* before the draft is copied into a post.

So this module never rewrites and never rejects. It reads a caption and returns
plain warnings; the panel shows them next to the text and the owner decides.
Every rule here is arithmetic or a list the owner wrote («never_say» in the
sales-agent rules) — no model is asked, so the check works when the AI is off.
"""
from __future__ import annotations

import re

from apps.common.fatext import contains_phrase, en_digits, normalize

#: a Persian/Latin price whose thousands separator is followed by 1-2 digits,
#: i.e. a number that lost its last zero(s): «600,00» «۶۰۰٬۰۰»
_BROKEN_NUMBER = re.compile(r"(?<![\d.,٬،])(\d{1,3}[,٬،]\d{1,2})(?![\d,٬،])")

_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2194-\u21AA\u231A-\u23FF\uFE0F]"
)

#: more than this many emoji in one caption reads as noise, not warmth
MAX_EMOJI = 6

#: a repeated phrase shorter than this is probably a connective, not a copy-paste
MIN_REPEAT_CHARS = 8


def _fields(caption) -> list[tuple[str, str]]:
    return [
        ("short_text", caption.short_text or ""),
        ("medium_text", caption.medium_text or ""),
        ("long_text", caption.long_text or ""),
        ("cta", caption.cta or ""),
    ]


def _repeated_phrase(text: str) -> str | None:
    """A sentence/phrase that appears twice in a row (the classic «لینک در بایو.
    لینک در بایو»), or None."""
    parts = [p.strip(" \t\n.!؟?،,;؛…-—") for p in re.split(r"[.!؟?\n]+", normalize(text))]
    parts = [p for p in parts if p]
    for a, b in zip(parts, parts[1:]):
        if len(a) >= MIN_REPEAT_CHARS and a == b:
            return a
    return None


def check(caption, banned: list[str] | None = None) -> list[dict]:
    """Warnings for one `Caption` row: `[{"code", "message"}]`, possibly empty.

    `banned` is the shop's «never say» list (one phrase each). Passing it in,
    rather than looking it up here, keeps this function free of queries so a
    list of thirty captions costs one lookup, not thirty.
    """
    banned = banned or []
    warnings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(code: str, message: str, key: str = "") -> None:
        if (code, key) not in seen:
            seen.add((code, key))
            warnings.append({"code": code, "message": message})

    emoji_total = 0
    for name, text in _fields(caption):
        if not text:
            continue
        for phrase in banned:
            if contains_phrase(text, phrase):
                add("banned", f"عبارتِ ممنوعِ شما در متن آمده: «{phrase}»", phrase)
        for m in _BROKEN_NUMBER.finditer(en_digits(text)):
            add("broken_number", f"عددِ ناقص: «{m.group(1)}» — احتمالاً صفرِ آخر افتاده است.", m.group(1))
        rep = _repeated_phrase(text)
        if rep:
            add("repeated", f"یک جمله دو بار پشتِ هم آمده: «{rep}»", rep)
        emoji_total += len(_EMOJI.findall(text))

    if emoji_total > MAX_EMOJI:
        add("emoji", f"ایموجی زیاد است ({emoji_total}).")
    # Hashtags are stored as plain words («هوش مصنوعی»); the panel writes them as Instagram wants them
    # (#هوش_مصنوعی) when it shows and copies them, so a missing «#» is not something to warn about.
    return warnings


def banned_for(store) -> list[str]:
    """The store's «never say» phrases, without creating a settings row."""
    from apps.stores.models import SalesAgentSettings

    row = SalesAgentSettings.objects.filter(store=store).first()
    return row.banned_phrases if row else []
