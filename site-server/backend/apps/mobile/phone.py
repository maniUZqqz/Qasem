"""Phone numbers and STOP words, in one place so every part of NM-Mobile agrees.

Normal form = digits with country code and no plus: ``989121234567``. Persian/Arabic digits, ``+98``, ``0098``
and a leading ``0`` all collapse to it. Matching between sources always uses the last 10 digits (``key``),
which survives every spelling of an Iranian number.
"""
from __future__ import annotations

import re

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def ascii_digits(value) -> str:
    return str(value or "").translate(_DIGITS)


def normalize(raw) -> str:
    """``09121234567`` / ``+98 912 123 4567`` / ``۰۹۱۲…`` -> ``989121234567``. Empty string when no digits."""
    digits = re.sub(r"\D", "", ascii_digits(raw))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "98" + digits[1:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "98" + digits
    return digits


def is_valid(norm: str) -> bool:
    return bool(norm) and 8 <= len(norm) <= 15


def key(norm_or_raw) -> str:
    """Last 10 digits: the cross-source match key."""
    norm = normalize(norm_or_raw)
    return norm[-10:]


def national(norm: str) -> str:
    """``989121234567`` -> ``09121234567`` (for display); other countries unchanged with a plus."""
    if norm.startswith("98") and len(norm) >= 11:
        return "0" + norm[2:]
    return "+" + norm if norm else ""


# ------------------------------------------------------------------ STOP words

_STOP_FIRST = {
    "لغو", "لغو11", "stop", "stopall", "unsubscribe", "توقف", "انصراف", "remove", "optout",
}
_STOP_PHRASES = {"لغو عضویت", "لغو اشتراک", "opt out", "لغو ارسال", "لغو پیامک"}


def clean_text(value) -> str:
    text = ascii_digits(value).replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    text = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def is_stop_text(body) -> bool:
    """A reply that means «never message me again». Short messages only, so a normal sentence that happens to
    contain the word «لغو» (e.g. a long complaint) is not treated as an opt-out."""
    text = clean_text(body)
    if not text:
        return False
    tokens = text.split(" ")
    if len(tokens) > 3:
        return False
    if tokens[0] in _STOP_FIRST:
        return True
    return " ".join(tokens[:2]) in _STOP_PHRASES
