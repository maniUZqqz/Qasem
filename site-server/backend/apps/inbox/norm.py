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
