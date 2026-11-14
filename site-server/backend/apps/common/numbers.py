"""Numbers typed by Persian speakers, and numbers shown back to them.

A shop owner types «۳۰۰٬۰۰۰» — Persian digits, Persian thousands separator —
because that is what their keyboard and their muscle memory produce. Python's
`Decimal("۳۰۰٬۰۰۰")` raises, an HTML `<input type=number>` silently drops it,
and the person is left staring at an empty box. This is the one place that
turns what they typed into what code can read.

The panel does the same conversion as they type (`components/numberInput.ts`);
this is the server's half, so an API client — a script, the mobile app, a paste
that bypassed the field — gets the same forgiveness and the same message.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

#: Everything people use to group thousands, plus the spaces around it.
_DROP = dict.fromkeys(map(ord, ",٬،_'’    ‌‏‎⁦⁧⁨⁩"), None)
_TABLE = {
    **{ord(p): str(i) for i, p in enumerate(_PERSIAN_DIGITS)},
    **{ord(a): str(i) for i, a in enumerate(_ARABIC_DIGITS)},
    ord("٫"): ".",      # Arabic decimal separator
    ord("−"): "-",      # real minus sign
    ord("–"): "-",
    **_DROP,
}


def normalize_number_text(value: str) -> str:
    """«۳۰۰٬۰۰۰» -> «300000», «۱٫۵» -> «1.5». Anything else is left for the validator.

    Only characters that *mean* a digit, a thousands separator or a decimal
    point are touched — a word stays a word, so «سی هزار» still fails with the
    «باید عدد باشد» message instead of turning into something else.
    """
    return str(value).translate(_TABLE).strip()


def parse_decimal(value) -> Decimal | None:
    """`Decimal` from what a person typed, or None when it is not a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = normalize_number_text(str(value))
    if not text:
        return None
    try:
        out = Decimal(text)
    except InvalidOperation:
        return None
    return out if out.is_finite() else None


def fa_digits(text) -> str:
    return str(text).translate({ord(str(i)): p for i, p in enumerate(_PERSIAN_DIGITS)})


def fa_money(value) -> str:
    """«۳۰۰٬۰۰۰» — whole tomans with the Persian thousands separator."""
    number = parse_decimal(value)
    if number is None:
        return ""
    whole = f"{int(number):,}".replace(",", "٬")
    return fa_digits(whole)
