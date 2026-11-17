"""Small, boring normalisers - the reason two channels can be one person.

Merging a customer across Telegram and SMS only works if "۰۹۱۲ ۳۴۵ ۶۷۸۹",
"+98 912 345 6789" and "09123456789" are the same string. These functions are
that agreement, and they are used on every write path (webhook, widget, API,
CSV) so a number cannot be stored two ways.
"""
from __future__ import annotations

import re

_FA = "۰۱۲۳۴۵۶۷۸۹"
_AR = "٠١٢٣٤٥٦٧٨٩"
_TABLE = {ord(c): str(i) for i, c in enumerate(_FA)} | {ord(c): str(i) for i, c in enumerate(_AR)}


def ascii_digits(text: str) -> str:
    """Persian / Arabic-Indic digits to ASCII."""
    return (text or "").translate(_TABLE)


def normalize_phone(raw: str) -> str:
    """Iranian mobiles become `09xxxxxxxxx`; anything else keeps its digits.

    Returns "" when there is no usable number, so a caller can `if phone:`
    without a second validity check.
    """
    digits = re.sub(r"\D", "", ascii_digits(raw or ""))
    if not digits:
        return ""
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) >= 12:
        digits = digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    if len(digits) < 7 or len(digits) > 15:
        return ""
    return digits


def is_mobile(phone: str) -> bool:
    return bool(re.fullmatch(r"09\d{9}", phone or ""))


def normalize_username(raw: str) -> str:
    """`@Ali_Fit` -> `ali_fit`. Too-short handles are noise, not identity."""
    name = (raw or "").strip().lstrip("@").lower()
    name = re.sub(r"[^a-z0-9_.]", "", name)
    return name if len(name) >= 3 else ""


def fa_digits(value) -> str:
    """ASCII digits to Persian, for text we show."""
    return str(value).translate({ord(str(i)): c for i, c in enumerate(_FA)})


# ---------------------------------------------------------------- whole words
#
# «Does this text ask for X?» must not be `x in text`: «مدیر» is inside «مدیریت»,
# «آدم» inside «آدم‌های دیابتی», «human» inside «the human body». The two helpers
# below compare *words* - after the spelling variants Persian keyboards and
# phones produce have been folded together - and nothing else.

_STRIP = dict.fromkeys(
    map(ord, "‌‍‎‏‪‫‬ـًٌٍَُِّْٰ"),
    None,
)
_LETTERS = {ord("ي"): "ی", ord("ى"): "ی", ord("ك"): "ک", ord("ۀ"): "ه", ord("ة"): "ه", ord("أ"): "ا", ord("إ"): "ا"}
_WORD = re.compile(r"\w+", re.UNICODE)

#: What may follow a word and still be that word: plural / colloquial plural
#: (and the English «s»). Deliberately **not** «ی»: «پشتیبانی» is a department
#: («پشتیبانی چطوره؟»), not the person «پشتیبان».
WORD_SUFFIXES = ("", "ها", "های", "ان", "ا", "s")


def fold(text: str) -> str:
    """Lower-case, ASCII digits, one spelling of ی/ک, no half-spaces or diacritics."""
    return ascii_digits(text or "").lower().translate(_LETTERS).translate(_STRIP)


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def has_phrase(text: str, phrase: str, *, suffixes: tuple[str, ...] = WORD_SUFFIXES) -> bool:
    """True when `phrase` (one word or several) appears in `text` as whole words.

    A **single** word may carry a plural ending (`suffixes`: «اپراتورها»); in a
    several-word phrase («با آدم») every word must match exactly, otherwise
    «با آدم‌های دیابتی» would be read as «با آدم».
    """
    want = words(phrase)
    if not want:
        return False
    if len(want) > 1:
        suffixes = ("",)
    have = words(text)
    last = len(want) - 1
    for start in range(len(have) - last):
        for offset, wanted in enumerate(want):
            token = have[start + offset]
            if offset == last:
                if not (token == wanted or (token.startswith(wanted) and token[len(wanted):] in suffixes)):
                    break
            elif token != wanted:
                break
        else:
            return True
    return False
