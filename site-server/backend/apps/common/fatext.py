"""Small Persian-text helpers shared by the checks that read Persian prose.

Why this exists: the same sentence can be typed in several byte-different
ways — Persian or Arabic-Indic or Latin digits, with or without a half-space
(ZWNJ), with Arabic ي/ك from an old keyboard, with a kasra mark that the
brand copy uses («جایگزینِ مربی»). A "never say" list written one way and a
caption written another way must still meet, otherwise the protection looks
on but silently misses the very words the owner banned.
"""
from __future__ import annotations

import re

_FA_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_EN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# ZWNJ, ZWJ, LRM/RLM, tatweel, and the Arabic short-vowel / kasra marks.
_STRIP = re.compile("[\u200c\u200d\u200e\u200f\u0640\u064b-\u065f\u0670]")
_PERCENT = str.maketrans({"٪": "%"})
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
_SPACES = re.compile(r"\s+")


def en_digits(text: str) -> str:
    """Persian and Arabic-Indic digits -> ASCII digits."""
    return (text or "").translate(_FA_TO_EN)


def fa_digits(text) -> str:
    """ASCII digits -> Persian digits (for text a person will read)."""
    return str(text if text is not None else "").translate(_EN_TO_FA)


def normalize(text: str) -> str:
    """A comparison form: casefolded, ASCII digits, no half-spaces or marks,
    Persian letters unified, single spaces. Never shown to a person."""
    t = en_digits(text or "")
    t = _STRIP.sub("", t)
    t = t.translate(_LETTERS).translate(_PERCENT)
    # "98 %" and "98%" are the same claim
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    return _SPACES.sub(" ", t).casefold().strip()


def contains_phrase(text: str, phrase: str) -> bool:
    """Whether the normalised `phrase` occurs in the normalised `text`."""
    p = normalize(phrase)
    return bool(p) and p in normalize(text)
