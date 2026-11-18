"""Text normaliser: written Persian -> text a voice can read.

``normalize(text)`` turns what people actually type (Arabic letters, Latin
brand names, digits, dates, prices, phone numbers, emoji, markdown) into plain
Persian words with a small, fixed punctuation vocabulary:

    «،»  short pause      «.»  «؟»  «!»  long pause      «\\n»  paragraph break

Every rule is a small function so it can be tested alone. The order matters and
is fixed in ``normalize``: structured things (URLs, dates, times, phones,
prices) are recognised *before* bare numbers, otherwise «۱۴۰۵/۰۸/۲۶» would be
read as three numbers.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import latin, numwords
from .numwords import cardinal, ordinal, to_ascii_digits

ZWNJ = "‌"

# ------------------------------------------------------------------ letters

_LETTER_FIX = {
    ord("ي"): "ی", ord("ى"): "ی", ord("ې"): "ی", ord("ێ"): "ی", ord("ك"): "ک",
    ord("ڪ"): "ک", ord("ہ"): "ه", ord("ھ"): "ه", ord("ۀ"): "هٔ", ord("ة"): "ه",
    ord("ۃ"): "ه", ord("ٱ"): "ا", ord("ؤ"): "ؤ", ord("ڵ"): "ل", ord("ڕ"): "ر",
    ord("ݘ"): "ی", ord("ە"): "ه",
}
_INVISIBLE = dict.fromkeys(map(ord, [
    "​", "‍", "‎", "‏", "‪", "‫", "‬", "‭",
    "‮", "⁦", "⁧", "⁨", "⁩", "﻿", "­", "؜",
    "ـ", "︎", "️", "⁠",
]))
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002300-\U000023FF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U00002190-\U000021FF\U000025A0-\U000025FF"
    "\U0001F900-\U0001F9FF\U00002700-\U000027BF\U00003030\U000000A9\U000000AE\U00002122]+"
)


def unify_letters(text: str) -> str:
    """Arabic letter forms -> Persian, invisible controls out, NFKC for presentation forms."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_LETTER_FIX).translate(_INVISIBLE)
    # re-compose «ه + ٔ» (hamza above) that the translate may have split
    return text


def strip_emoji(text: str) -> str:
    return _EMOJI.sub(" ", text)


def fix_half_spaces(text: str) -> str:
    """Put the ZWNJ where Persian needs it so words are read as one word.

    «می خواهم» -> «می‌خواهم», «کتاب ها» -> «کتاب‌ها», «بزرگ تر» -> «بزرگ‌تر».
    """
    text = re.sub(r"(?<![آ-ی])(ن?می)[ ]+(?=[آ-ی])", lambda m: m.group(1) + ZWNJ, text)
    text = re.sub(r"([آ-ی])[ ]+(ها|های|هایی|هایم|هایت|هایش|هایمان|هایتان|هایشان)(?![آ-ی])",
                  lambda m: m.group(1) + ZWNJ + m.group(2), text)
    text = re.sub(r"([آ-ی])[ ]+(تر|ترین)(?![آ-ی])",
                  lambda m: m.group(1) + ZWNJ + m.group(2), text)
    return text


_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>|<!--.*?-->", re.S)


def strip_markup(text: str) -> str:
    """HTML tags («<b>», «<br/>») are not speech: «<b>سلام</b>» must not be read as «بی سلام».

    ``<br>`` and ``</p>`` become a line break, every other tag a space.
    """
    text = re.sub(r"<br\s*/?>|</p\s*>|</li\s*>|</h[1-6]\s*>", "\n", text, flags=re.I)
    return _TAG.sub(" ", text)


# a digit glued to a Persian word («۳جلسه», «۲۰تومان», «جلسه۳»): read as two words. The ordinal endings («۱۲ام», «۳م»,
# «۱۰مین») are left alone, spell_numbers turns them into «دوازدهم».
_FA = "آ-يپچژکگی"      # Persian letters without the Arabic-Indic digits and the decimal / thousands marks that sit in between
_DIGIT_THEN_WORD = re.compile(r"(\d)(?=[" + _FA + "])(?!(?:‌?ام(?:ین)?|م(?:ین)?)(?![" + _FA + "]))")
_WORD_THEN_DIGIT = re.compile(r"(?<=[" + _FA + "]{2})(?=\d)")


def split_glued_digits(text: str) -> str:
    text = _DIGIT_THEN_WORD.sub(r"\1 ", text)
    return _WORD_THEN_DIGIT.sub(" ", text)


#: «۴۵۰.۰۰۰ تومان»: a dot (or the Arabic decimal mark «٫», which many keyboards type for it) between a digit and exactly three digits is the
#: thousands separator when it repeats («۱.۲۵۰.۰۰۰», «۱٫۲۰۰٫۰۰۰»), when the three digits are «000» («۴۵۰.۰۰۰») or when a price / count
#: word follows («۲.۵۰۰ تومان», «۳٫۵۰۰ تومان»); otherwise it is a decimal point («۳.۱۴۱»).
_SEP = "[.٫]"
_DOT_THOUSANDS_MULTI = re.compile(rf"(?<![\d.,/٫])(\d{{1,3}}(?:{_SEP}\d{{3}}){{2,}})(?![\d])(?!{_SEP}\d)")
_DOT_THOUSANDS_ZEROS = re.compile(rf"(?<![\d.,/٫])([1-9]\d{{0,2}}{_SEP}000)(?![\d])(?!{_SEP}\d)")
_DOT_THOUSANDS_ONE = re.compile(
    rf"(?<![\d.,/٫])([1-9]\d{{0,2}}{_SEP}\d{{3}})(?![\d])(?=\s*(?:تومان|تومن|ریال|دلار|یورو|پوند|درهم|نفر|عدد|فالوور|دنبال‌کننده|بازدید|لایک|"
    r"کالری|کیلوکالری|گام|قدم|بار|جلسه|دقیقه|ثانیه|کلمه|واژه))")


def _group(m) -> str:
    return m.group(1).replace(".", ",").replace("٫", ",")


def fix_dot_thousands(text: str) -> str:
    text = _DOT_THOUSANDS_MULTI.sub(_group, text)
    text = _DOT_THOUSANDS_ZEROS.sub(_group, text)
    return _DOT_THOUSANDS_ONE.sub(_group, text)


# ------------------------------------------------------------------ names

JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان",
                 "آذر", "دی", "بهمن", "اسفند"]
GREGORIAN_MONTHS = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن", "ژوئیه", "اوت",
                    "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
_MONTH_ALT = "|".join(JALALI_MONTHS + GREGORIAN_MONTHS)


def _jalali_days(month: int, year: int) -> int:
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    return 30 if year % 33 in (1, 5, 9, 13, 17, 22, 26, 30) else 29


def _valid_date(y: int, m: int, d: int) -> str | None:
    if 1300 <= y <= 1499:
        if 1 <= m <= 12 and 1 <= d <= _jalali_days(m, y):
            return "j"
    elif 1900 <= y <= 2100:
        if 1 <= m <= 12 and 1 <= d <= 31:
            return "g"
    return None


KASRA = "ِ"


def _say_date(y: int, m: int, d: int, kind: str) -> str:
    """«۱۴۰۵/۰۸/۲۶» -> «بیست و ششم آبانِ هزار و چهارصد و پنج»: the month is linked to the year by an ezafe, written as the kasra the
    pronunciation layer reads as one (a plain «آبان هزار» is two nouns side by side)."""
    months = JALALI_MONTHS if kind == "j" else GREGORIAN_MONTHS
    return f"{ordinal(d, first_as_aval=False)} {months[m - 1]}{KASRA} {cardinal(y)}"


#: English month names (a capital first letter, so «may» / «mar» the words stay words) -> the Persian month name
_EN_MONTH_FA = {
    "jan": "ژانویه", "feb": "فوریه", "mar": "مارس", "apr": "آوریل", "may": "مه", "jun": "ژوئن", "jul": "ژوئیه", "aug": "اوت",
    "sep": "سپتامبر", "oct": "اکتبر", "nov": "نوامبر", "dec": "دسامبر",
}
_EN_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
             r"Nov(?:ember)?|Dec(?:ember)?)")
_EN_DATE_MD = re.compile(rf"(?<![A-Za-z]){_EN_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?![\d])")
_EN_DATE_DM = re.compile(rf"(?<![\d.])(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_EN_MONTH}\.?(?:,?\s+(\d{{4}}))?(?![\dA-Za-z])")


def _en_date(month: str, day: str, year: str | None) -> str:
    """«Nov», «18», «2026» -> «18 نوامبر 2026» (digits stay: the textual date pass above reads them next)."""
    if not 1 <= int(day) <= 31:
        return f"{month} {day}" + (f" {year}" if year else "")
    out = f"{int(day)} {_EN_MONTH_FA[month[:3].lower()]}"
    return out + (f" {year}" if year else "")


_DATE_YMD = re.compile(r"(?<![\d./])(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?![\d/]|\.\d)")
_DATE_DMY = re.compile(r"(?<![\d./])(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?![\d/]|\.\d)")


def spell_dates(text: str) -> str:
    def ymd(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        kind = _valid_date(y, mo, d)
        return _say_date(y, mo, d, kind) if kind else m.group(0)

    def dmy(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        kind = _valid_date(y, mo, d)
        return _say_date(y, mo, d, kind) if kind else m.group(0)

    text = _DATE_YMD.sub(ymd, text)
    text = _DATE_DMY.sub(dmy, text)
    # «Nov 18», «November 18th, 2026», «18 Nov 2026»: English month names become «۱۸ نوامبر [۲۰۲۶]», read below like any dated line
    text = _EN_DATE_MD.sub(lambda m: _en_date(m.group(1), m.group(2), m.group(3)), text)
    text = _EN_DATE_DM.sub(lambda m: _en_date(m.group(2), m.group(1), m.group(3)), text)

    # «۲۶ آبان ۱۴۰۵» and «۲۶ آبان»
    def textual(m):
        d = int(m.group(1))
        year = m.group(3)
        out = f"{ordinal(d, first_as_aval=False)} {m.group(2)}"
        if year:
            out += f"{KASRA} {cardinal(int(year))}"
        return out

    text = re.sub(rf"(?<![\d])(\d{{1,2}})\s+({_MONTH_ALT})(?:\s+(\d{{4}}))?(?![\d])", textual, text)
    return text


# ------------------------------------------------------------------ times

_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?![\d:])")


def spell_times(text: str) -> str:
    def rep(m):
        start = m.start()
        before = text[max(0, start - 6):start]
        h, mi, s = int(m.group(1)), int(m.group(2)), m.group(3)
        out = cardinal(h)
        if mi:
            out += f" و {cardinal(mi)} دقیقه"
        if s and int(s):
            out += f" و {cardinal(int(s))} ثانیه"
        if "ساعت" not in before:
            out = "ساعت " + out
        return out

    return _TIME.sub(rep, text)


# ------------------------------------------------------------------ phones

_MOBILE = re.compile(r"(?<![\d])(?:\+98|0098|98|0)[\s\-]?(9\d{2})[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})(?![\d])")
_LANDLINE = re.compile(r"(?<![\d])0(\d{2})[\s\-]?(\d{8})(?![\d])")
_CARD = re.compile(r"(?<![\d])(\d{4})[\s\-](\d{4})[\s\-](\d{4})[\s\-](\d{4})(?![\d])")
_LONG_DIGITS = re.compile(r"(?<![\d.,])\d{11,}(?![\d])")


def _three(s: str) -> str:
    return cardinal(int(s))


def spell_phones(text: str) -> str:
    def mobile(m):
        a, b, c, d = m.group(1), m.group(2), m.group(3), m.group(4)
        # «+98 912 ...»: the country code is said as a number («نود و هشت»); only the national form starts with «صفر»
        head = "نود و هشت،" if re.match(r"(?:\+98|0098|98)", m.group(0)) else "صفر"
        return f"{head} {_three(a)}، {_three(b)}، {cardinal(int(c)) if c[0] != '0' else numwords.digits_one_by_one(c)}، " \
               f"{cardinal(int(d)) if d[0] != '0' else numwords.digits_one_by_one(d)}،"

    def landline(m):
        area, num = m.group(1), m.group(2)
        pairs = [num[i:i + 2] for i in range(0, 8, 2)]
        spoken = "، ".join(cardinal(int(p)) if p[0] != "0" else numwords.digits_one_by_one(p) for p in pairs)
        return f"صفر {cardinal(int(area))}، {spoken}،"

    def card(m):
        return "، ".join(numwords.digits_one_by_one(g) for g in m.groups()) + "،"

    def long_digits(m):
        return numwords.digits_one_by_one(m.group(0), group=4) + "،"

    text = _CARD.sub(card, text)
    text = _MOBILE.sub(mobile, text)
    text = _LANDLINE.sub(landline, text)
    text = _LONG_DIGITS.sub(long_digits, text)
    return text


# ------------------------------------------------------------------ symbols & units

UNITS_EN = {
    "kg": "کیلوگرم", "g": "گرم", "mg": "میلی‌گرم", "km": "کیلومتر", "m": "متر",
    "cm": "سانتی‌متر", "mm": "میلی‌متر", "ml": "میلی‌لیتر", "l": "لیتر", "lit": "لیتر",
    "kcal": "کیلوکالری", "cal": "کالری", "gb": "گیگابایت", "mb": "مگابایت",
    "kb": "کیلوبایت", "tb": "ترابایت", "hz": "هرتز", "khz": "کیلوهرتز", "mhz": "مگاهرتز",
    "ghz": "گیگاهرتز", "kw": "کیلووات", "w": "وات", "v": "ولت", "min": "دقیقه",
    "h": "ساعت", "hr": "ساعت", "hrs": "ساعت", "s": "ثانیه", "sec": "ثانیه",
    "bpm": "ضربه در دقیقه", "rpm": "دور در دقیقه", "mph": "مایل در ساعت",
    "km/h": "کیلومتر بر ساعت", "m/s": "متر بر ثانیه", "kmh": "کیلومتر بر ساعت",
    "px": "پیکسل", "fps": "فریم بر ثانیه", "usd": "دلار", "eur": "یورو",
    "rep": "تکرار", "reps": "تکرار", "set": "ست", "sets": "ست",
}
_UNIT_RE = "|".join(sorted((re.escape(k) for k in UNITS_EN), key=len, reverse=True))

SYMBOL_UNITS = {"°C": "درجه سانتی‌گراد", "℃": "درجه سانتی‌گراد", "°F": "درجه فارنهایت",
                "°": "درجه", "m²": "متر مربع", "m2": "متر مربع", "km²": "کیلومتر مربع"}

CURRENCY_BEFORE = {"$": "دلار", "€": "یورو", "£": "پوند", "﷼": "ریال", "¥": "ین"}

ABBREVIATIONS = {
    "ق.ظ": "قبل از ظهر", "ب.ظ": "بعد از ظهر", "ه.ش": "هجری شمسی", "ه.ق": "هجری قمری",
    "ر.ک": "رجوع کنید به", "ص.پ": "صندوق پستی", "ص.ب": "صندوق پستی",
    "ج.ا.ا": "جمهوری اسلامی ایران", "ج.ا": "جمهوری اسلامی", "الخ": "الی آخر",
    "ق.م": "قبل از میلاد",
    "Dr.": "دکتر", "Mr.": "آقای", "Mrs.": "خانم", "Ms.": "خانم", "vs.": "در برابر",
    "etc.": "و غیره", "a.m.": "صبح", "p.m.": "بعدازظهر", "No.": "شماره",
}


def spell_abbreviations(text: str) -> str:
    for ab, full in ABBREVIATIONS.items():
        if re.search(r"[A-Za-z]", ab):
            text = re.sub(rf"(?<![A-Za-z]){re.escape(ab)}(?![A-Za-z])", full + " ", text)
        else:
            text = text.replace(ab, full)
    text = re.sub(r"(?<![آ-ی])ص\s*(\d+)(?![\d])", r"صفحهٔ \1", text)
    return text


_NUM = r"\d+(?:[.,٬]\d+)*"
_ORD_FA = re.compile(r"(?<![\d.])(\d+)(?:‌?ام(?:ین)?|م(?:ین)?|[ ]مین|[ ]امین)(?![آ-یA-Za-z\d])")
_ORD_EN = re.compile(r"(?<![\d.])(\d+)(?:st|nd|rd|th)\b", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|٪)|(?:%|٪)\s*(\d+(?:\.\d+)?)")
_RANGE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[\-–—]\s*(\d+(?:\.\d+)?)(?![\d])")
_TIMES = re.compile(r"(?<![\d.])(\d+)\s*[x×]\s*(\d+)(?![\d])", re.I)
_TIMES_SPACED = re.compile(r"(?<=[A-Za-z؀-ۿ])\s+[x×]\s+(?=\d)")
_PLUS_AFTER = re.compile(r"(?<![\d.])(\d+)\+(?![\d\w])")
_FRACTION = re.compile(r"(?<![\d./])(\d{1,3})/(\d{1,3})(?![\d/])")
_KMB = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?([kKmM])(?![A-Za-z\d])")
_CURR_BEFORE = re.compile(r"([$€£﷼¥])\s?(\d+(?:[.,٬]\d+)*)")
_CURR_AFTER = re.compile(r"(\d+(?:[.,٬]\d+)*)\s?([$€£﷼¥])")
_UNIT_AFTER = re.compile(rf"(?<![\d.])(\d+(?:\.\d+)?)\s?(°C|℃|°F|km²|m²|m2|{_UNIT_RE})(?![A-Za-z0-9])", re.I)
_THOUSANDS = re.compile(r"(?<![\d.,])\d{1,3}(?:[,٬]\d{3})+(?![\d])(?!\.\d)")
_DECIMAL = re.compile(r"(?<![\d.])(\d+)[.٫](\d+)(?![\d.])")
_BARE = re.compile(r"(?<![\d.])\d+(?![\d])")


def _num_to_words(s: str) -> str:
    """'1,250,000' / '12' / '3.5' -> words."""
    s = s.replace(",", "").replace("٬", "")
    if "." in s or "٫" in s:
        ip, fp = re.split(r"[.٫]", s, maxsplit=1)
        return numwords.decimal(int(ip or 0), fp)
    return cardinal(int(s))


#: «۹۹۰/۰۰۰ تومان» (a slash as the thousands separator): only when the last group is «000» or a price word follows.
_SLASH_THOUSANDS = re.compile(
    r"(?<![\d/])(\d{1,3})/(\d{3})(?![\d/])(?=(?<=000)|\s*(?:تومان|تومن|ریال|دلار|یورو))")
#: «۲۴/۷» (support «24/7»): said as what it means.
_ALL_DAY = re.compile(r"(?<![\d/.])(?:24/7|7/24)(?![\d/])")
#: «-۵ کیلو»: a minus sign in front of a number (not a range «۵-۱۰», not a dash between words «برنامه - ۵ روز»).
_MINUS = re.compile(r"(?<![\w)\]])[-−](?=\d)")
#: «4G», «5G» (mobile network) and «4K» (picture size) are letter names, not grams / thousands.
_NETWORK_G = re.compile(r"(?<![\d.\w])([3-6])\s?G(?![A-Za-z0-9])")
_PICTURE_K = re.compile(r"(?<![\d.\w])([248])\s?[kK](?![A-Za-z0-9])")
#: «۲٫۵ میلیون» -> «دو و نیم میلیون» (and «۰٫۵ ساعت» -> «نیم ساعت»): a half before a quantity word is said «N و نیم».
_QUANT_FA = ("میلیون|میلیارد|هزار|ساعت|دقیقه|ثانیه|روز|هفته|ماه|سال|کیلو|کیلوگرم|گرم|متر|سانتی‌متر|لیتر|میلی‌لیتر|تومان|ریال|دلار|"
             "یورو|درصد|ست|تکرار|عدد|نفر|بار|جلسه|وعده|لیوان|قاشق|کالری|کیلوکالری|کیلومتر|مایل|قدم|گام")
_HALF_FA = re.compile(rf"(?<![\d.])(\d+)\.5(?!\d)(?=\s+(?:{_QUANT_FA})(?![آ-ی]))")
_HALF_UNIT = re.compile(rf"(?<![\d.])(\d+)\.5(?!\d)\s?(°C|℃|°F|km²|m²|m2|{_UNIT_RE})(?![A-Za-z0-9])", re.I)


#: «۲/۵ کیلو» (a slash typed as the decimal mark, common in Persian text): a decimal when a unit follows and it cannot be a plain
#: fraction («۱/۲ کیلو» stays one half, «۳/۴ لیتر» three quarters): the numerator is not smaller than the denominator, or the denominator
#: is a digit from 5 up, or it has two digits.
_SLASH_DECIMAL = re.compile(
    rf"(?<![\d/.])(\d{{1,3}})/(\d{{1,2}})(?![\d/])(?=\s*(?:(?:{_QUANT_FA})(?![آ-ی])|(?:{_UNIT_RE})(?![A-Za-z0-9])))", re.I)


def _slash_decimal(m) -> str:
    num, den = m.group(1), m.group(2)
    if int(num) >= int(den) or int(den) >= 5 or len(den) == 2:
        return f"{num}.{den}"
    return m.group(0)


def _half(n: str) -> str:
    return "نیم" if int(n) == 0 else f"{cardinal(int(n))} و نیم"


def spell_numbers(text: str) -> str:
    """Prices, units, ordinals, percentages, ranges, fractions, decimals and plain numbers."""
    text = _TIMES_SPACED.sub(" در ", text)       # «۴ ست × ۱۲ تکرار», «4 sets x 12 reps» (a word before the sign): said «در», like the unspaced «۴×۱۲»; first, before the units eat the digits
    text = _NETWORK_G.sub(lambda m: f"{cardinal(int(m.group(1)))} جی ", text)
    text = _PICTURE_K.sub(lambda m: f"{cardinal(int(m.group(1)))} کی ", text)
    text = _SLASH_THOUSANDS.sub(lambda m: f"{m.group(1)},{m.group(2)}", text)
    text = _ALL_DAY.sub(" بیست و چهار ساعته و هفت روز هفته ", text)
    text = _SLASH_DECIMAL.sub(_slash_decimal, text)
    text = _MINUS.sub("منفی ", text)
    text = _CURR_BEFORE.sub(lambda m: f"{_num_to_words(m.group(2))} {CURRENCY_BEFORE[m.group(1)]}", text)
    text = _CURR_AFTER.sub(lambda m: f"{_num_to_words(m.group(1))} {CURRENCY_BEFORE[m.group(2)]}", text)
    text = _PERCENT.sub(lambda m: f"{_num_to_words(m.group(1) or m.group(2))} درصد", text)

    def kmb(m):
        n, suf = m.group(1), m.group(2).lower()
        mult = 1000 if suf == "k" else 1_000_000
        try:
            val = round(float(n) * mult)
        except ValueError:
            return m.group(0)
        return cardinal(val)

    text = _KMB.sub(kmb, text)
    text = _HALF_UNIT.sub(lambda m: f"{_half(m.group(1))} {SYMBOL_UNITS.get(m.group(2)) or SYMBOL_UNITS.get(m.group(2).replace('2', '²')) or UNITS_EN.get(m.group(2).lower(), m.group(2))}", text)
    text = _HALF_FA.sub(lambda m: _half(m.group(1)), text)

    def unit(m):
        n, u = m.group(1), m.group(2)
        word = SYMBOL_UNITS.get(u) or SYMBOL_UNITS.get(u.replace("2", "²")) or UNITS_EN.get(u.lower(), u)
        return f"{_num_to_words(n)} {word}"

    text = _UNIT_AFTER.sub(unit, text)
    text = _ORD_EN.sub(lambda m: ordinal(int(m.group(1))), text)
    text = _ORD_FA.sub(lambda m: ordinal(int(m.group(1))) + ("ین" if m.group(0).endswith("ین") else ""), text)
    text = _TIMES.sub(lambda m: f"{cardinal(int(m.group(1)))} در {cardinal(int(m.group(2)))}", text)
    text = text.replace("×", " در ")
    text = _RANGE.sub(lambda m: f"{_num_to_words(m.group(1))} تا {_num_to_words(m.group(2))}", text)
    text = _PLUS_AFTER.sub(lambda m: f"{cardinal(int(m.group(1)))} به بالا", text)
    text = _FRACTION.sub(lambda m: numwords.fraction(int(m.group(1)), int(m.group(2))), text)
    text = _THOUSANDS.sub(lambda m: _num_to_words(m.group(0)), text)
    text = _DECIMAL.sub(lambda m: numwords.decimal(int(m.group(1)), m.group(2)), text)
    text = _BARE.sub(lambda m: cardinal(int(m.group(0))) if len(m.group(0)) <= 15
                     else numwords.digits_one_by_one(m.group(0), group=4), text)
    return text


# ------------------------------------------------------------------ web

_URL = re.compile(r"(?:https?://|www\.)[^\s،؛؟!)\]»]+", re.I)
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,30})")
_HASHTAG = re.compile(r"#([\w؀-ۿ‌]+)")


#: how the ending of an address is said («chagher.ir» = «چغر دات آی‌آر»): letter names for the short ones, never a guessed word
TLD_SAY = {"ir": "آی‌آر", "com": "کام", "org": "ارگ", "net": "نت", "io": "آی‌او", "ai": "ای‌آی", "app": "اپ", "me": "می",
           "info": "اینفو", "co": "سی‌او", "ac": "ای‌سی", "edu": "ای‌دی‌یو", "tv": "تی‌وی", "dev": "دِو"}
_BARE_DOMAIN = re.compile(
    r"(?<![\w@./:\-])((?:[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?\.)+(?:ir|com|org|net|io|ai|app|me|info|co|ac|edu|tv|dev))(?![A-Za-z0-9\-])"
    r"(?:/([A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*))?", re.I)


def _say_domain(host: str) -> str:
    parts = [p for p in re.split(r"[.]", host) if p]
    out = []
    for k, part in enumerate(parts):
        if k > 0 and k == len(parts) - 1 and part.lower() in TLD_SAY:
            out.append(TLD_SAY[part.lower()])
            continue
        if k > 0 and part.lower() in ("co", "ac") and k == len(parts) - 2:
            out.append(TLD_SAY[part.lower()])
            continue
        spoken, _ = latin.speak_latin(part) if re.fullmatch(r"[A-Za-z0-9\-]+", part) else (part, False)
        out.append(spoken)
    return " دات ".join(out)


def spell_web(text: str) -> str:
    def url(m):
        u = re.sub(r"^(?:https?://)?(?:www\.)?", "", m.group(0), flags=re.I).rstrip("/.")
        host, _, path = u.partition("/")
        spoken = _say_domain(host)
        if path:
            spoken += " اسلش " + " ".join(
                latin.speak_latin(p)[0] if re.fullmatch(r"[A-Za-z0-9\-]+", p) else p
                for p in re.split(r"[/_\-]", path) if p)
        return " " + spoken + " "

    def email(m):
        local, _, domain = m.group(0).partition("@")
        l = latin.speak_latin(local)[0] if re.fullmatch(r"[A-Za-z0-9\-]+", local) else \
            " ".join(latin.speak_latin(p)[0] for p in re.split(r"[._+\-]", local) if p)
        return f" {l} اَت {_say_domain(domain)} "

    def bare(m):
        spoken = _say_domain(m.group(1))
        if m.group(2):
            spoken += " اسلش " + " ".join(
                latin.speak_latin(p)[0] for p in re.split(r"[/_\-]", m.group(2)) if p)
        return " " + spoken + " "

    text = _URL.sub(url, text)
    text = _EMAIL.sub(email, text)
    text = _BARE_DOMAIN.sub(bare, text)
    text = _HANDLE.sub(lambda m: " " + " ".join(
        latin.speak_latin(p)[0] for p in re.split(r"[._]", m.group(1)) if p) + " ", text)
    text = _HASHTAG.sub(lambda m: " " + m.group(1).replace("_", " ") + " ", text)
    return text


# ------------------------------------------------------------------ latin words

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")


@dataclass
class NormNotes:
    """What the normaliser could not be sure about (feeds the «مشکل‌دار» list)."""
    latin_guesses: list[str] = field(default_factory=list)
    latin_known: list[str] = field(default_factory=list)


def spell_latin(text: str, notes: NormNotes | None = None) -> str:
    def rep(m):
        spoken, guess = latin.speak_latin(m.group(0))
        if notes is not None:
            (notes.latin_guesses if guess else notes.latin_known).append(m.group(0))
        return " " + spoken + " "

    return _LATIN.sub(rep, text)


# ------------------------------------------------------------------ punctuation

_SHORT = "،,;؛:"
_LONG = ".؟?!…"
#: the marks of a bulleted list («• مورد»): not emoji, not words
_BULLETS = "•‣⁃∙◦▪▫●○■□·"


def fix_punctuation(text: str) -> str:
    """Collapse everything into «،» «.» «؟» «!» and newlines; drop markup characters."""
    # list bullets: at the start of a line only decoration (the line break is the pause), inside a line a short pause
    text = re.sub(r"(?m)^[ \t]*[" + _BULLETS + r"]+[ \t]*", "", text)
    text = re.sub(r"[ \t]*[" + _BULLETS + r"]+[ \t]*", "، ", text)
    # an equals sign is said («۲+۳=۵» -> «... مساوی پنج»); a run of three or more is a markdown underline
    text = re.sub(r"={3,}", " ", text)
    text = re.sub(r"\s*=\s*", " مساوی ", text).replace("÷", " تقسیم بر ")
    # markdown / decoration
    text = re.sub(r"[*_~`^|<>\\{}\[\]]+", " ", text)
    text = text.replace("(", "،").replace(")", "،")
    text = re.sub(r"[«»“”\"'‘’„‹›]", " ", text)
    text = re.sub(r"\s*و\s*/\s*یا\s*", " و یا ", text)
    text = text.replace("&", " و ").replace("+", " به علاوه ").replace("/", " یا ")
    text = re.sub(r"\s[-–—]+\s|[–—]+", "،", text)
    text = text.replace("-", " ")
    text = re.sub(r"\.{2,}|…+", ".", text)
    text = text.replace("?", "؟").replace(",", "،").replace(";", "،").replace("؛", "،")
    text = text.replace(":", "،")
    text = re.sub(r"[ \t\r\f\v]*\n[ \t\r\f\v]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    # no space before a mark, one space after; collapse runs of marks to the strongest
    text = re.sub(r"\s+([،.؟!])", r"\1", text)
    text = re.sub(r"([،.؟!])(?=[^\s\n،.؟!])", r"\1 ", text)

    def strongest(m):
        s = m.group(0)
        for ch in "؟!.":
            if ch in s:
                return ch
        return "،"

    text = re.sub(r"[،.؟!][\s،.؟!]*[،.؟!]|[،.؟!]\s+(?=[،.؟!])", strongest, text)
    text = re.sub(r"^[\s،.]+", "", text)
    text = re.sub(r"[،\s]+$", "", text)          # a short pause at the very end says nothing («+98 ...،»)
    return text.strip()


# ------------------------------------------------------------------ driver


@dataclass
class NormResult:
    text: str
    notes: NormNotes


def normalize(text: str, *, collect: bool = True) -> NormResult:
    """Run the whole normaliser. Idempotent: normalising twice changes nothing."""
    notes = NormNotes()
    text = text or ""
    text = unify_letters(text)
    text = strip_markup(text)
    text = strip_emoji(text)
    text = text.replace("ة", "ه")
    # digits -> ASCII once, here
    text = to_ascii_digits(text)
    text = split_glued_digits(text)
    text = fix_dot_thousands(text)          # before «٫» (the real decimal separator) is turned into a plain dot
    text = text.replace("٫", ".").replace("٬", ",")
    text = spell_web(text)
    text = spell_abbreviations(text)
    text = spell_dates(text)
    text = spell_times(text)
    text = spell_phones(text)
    text = spell_numbers(text)
    text = spell_latin(text, notes if collect else None)
    text = fix_half_spaces(text)
    text = fix_punctuation(text)
    return NormResult(text, notes)
