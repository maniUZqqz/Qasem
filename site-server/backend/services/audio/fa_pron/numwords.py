"""Numbers to Persian words: cardinals, ordinals, decimals, fractions, digit strings.

Everything here is pure Python with no imports from the rest of NM so it can be
unit-tested (and run on the GPU node) on its own.

Spoken Persian differs from the written digit string in ways that a voice
engine never gets right on its own:

* «۱۰۰۰» is «هزار», not «یک هزار»; «۲۰۰۰» is «دو هزار».
* «۱۵۰۰۰۰» is «صد و پنجاه هزار» - the scale words join with «و».
* Ordinals are not just «cardinal + م»: «اول» (1), «سوم» (3), «سی‌ام» (30,
  the ZWNJ keeps the word readable), «بیست و یکم» (21).
* A decimal is «ممیز»: «۲٫۵» -> «دو ممیز پنج دهم».
"""
from __future__ import annotations

# 9 carries a damma so it can never be mistaken for the negation «نه» (na).
NINE = "نُه"
ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", NINE]
TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"]
TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
# (value, word) from the largest. Beyond «کوادریلیون» nobody says a number aloud.
SCALES = [
    (10 ** 15, "کوادریلیون"),
    (10 ** 12, "تریلیون"),
    (10 ** 9, "میلیارد"),
    (10 ** 6, "میلیون"),
    (10 ** 3, "هزار"),
]

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_TABLE = {ord(c): str(i) for i, c in enumerate(PERSIAN_DIGITS)}
_DIGIT_TABLE.update({ord(c): str(i) for i, c in enumerate(ARABIC_DIGITS)})

DIGIT_NAMES = ["صفر", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", NINE]

# «۳٫۱۴ = سه ممیز چهارده صدم»: number of decimals -> word for the unit.
_DECIMAL_UNITS = {
    1: "دهم", 2: "صدم", 3: "هزارم", 4: "ده‌هزارم", 5: "صدهزارم", 6: "میلیونیم",
}

_FRACTION_NAMES = {2: "دوم", 3: "سوم", 4: "چهارم", 5: "پنجم", 6: "ششم", 7: "هفتم",
                   8: "هشتم", 9: "نهم", 10: "دهم"}


def to_ascii_digits(text: str) -> str:
    """Persian / Arabic-Indic digits -> ASCII, leaving everything else alone."""
    return text.translate(_DIGIT_TABLE)


def _under_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(HUNDREDS[n // 100])
        n %= 100
    if 10 <= n <= 19:
        parts.append(TEENS[n - 10])
    else:
        if n >= 20:
            parts.append(TENS[n // 10])
            n %= 10
        if n > 0:
            parts.append(ONES[n])
    return " و ".join(p for p in parts if p)


def cardinal(n: int) -> str:
    """۲۵۰۰۰۰ -> «دویست و پنجاه هزار»; ۱۰۰۰ -> «هزار»; ۰ -> «صفر»."""
    if n == 0:
        return "صفر"
    if n < 0:
        return "منفی " + cardinal(-n)
    parts = []
    for value, name in SCALES:
        if n >= value:
            count, n = divmod(n, value)
            if count == 1 and value == 1000:
                parts.append(name)  # «هزار», never «یک هزار»
            else:
                parts.append(f"{cardinal(count)} {name}")
    if n:
        parts.append(_under_thousand(n))
    return " و ".join(parts)


def digits_one_by_one(digits: str, group: int = 0) -> str:
    """«۱۲۳۴» -> «یک دو سه چهار». ``group`` inserts a comma every N digits (a pause)."""
    digits = to_ascii_digits(digits)
    names = [DIGIT_NAMES[int(c)] for c in digits if c.isdigit()]
    if not group:
        return " ".join(names)
    chunks = [" ".join(names[i:i + group]) for i in range(0, len(names), group)]
    return "، ".join(chunks)


def ordinal(n: int, *, first_as_aval: bool = True) -> str:
    """۱ -> «اول», ۳ -> «سوم», ۲۱ -> «بیست و یکم», ۳۰ -> «سی‌ام», ۱۳ -> «سیزدهم»."""
    if n == 1 and first_as_aval:
        return "اول"
    if n < 0:
        return "منفی " + ordinal(-n)
    if n == 0:
        return "صفرم"
    words = cardinal(n)
    if words.endswith("سه"):
        return words[:-2] + "سوم"
    if words.endswith("سی"):
        return words + "‌ام"  # سی‌ام: the ZWNJ keeps «ی» and «ا» apart
    return words + "م"


def decimal(int_part: int, frac_digits: str) -> str:
    """۳٫۱۴ -> «سه ممیز چهارده صدم». Leading zeros in the fraction are kept."""
    frac_digits = "".join(c for c in to_ascii_digits(frac_digits) if c.isdigit())
    if not frac_digits:
        return cardinal(int_part)
    unit = _DECIMAL_UNITS.get(len(frac_digits))
    frac_val = int(frac_digits)
    if unit is None:  # too many digits to say as a quantity
        return f"{cardinal(int_part)} ممیز {digits_one_by_one(frac_digits)}"
    if frac_val == 0:
        return cardinal(int_part)
    if int_part == 0:
        return f"{cardinal(frac_val)} {unit}"
    return f"{cardinal(int_part)} ممیز {cardinal(frac_val)} {unit}"


def fraction(num: int, den: int) -> str:
    """۳/۴ -> «سه چهارم», ۱/۲ -> «یک دوم»."""
    if den == 0:
        return f"{cardinal(num)} بر صفر"
    word = _FRACTION_NAMES.get(den)
    if word is None:
        word = ordinal(den, first_as_aval=False)
    return f"{cardinal(num)} {word}"


def spell_int_string(s: str) -> str:
    """A digit string (any digit script, separators allowed) -> cardinal words."""
    s = to_ascii_digits(s)
    for sep in (",", "،", "٬", " "):
        s = s.replace(sep, "")
    if not s.isdigit():
        return s
    return cardinal(int(s))
