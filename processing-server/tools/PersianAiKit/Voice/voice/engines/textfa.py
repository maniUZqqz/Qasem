# متنِ فارسی ⇒ شکلی که مدل‌های صدا با آن آموزش دیده‌اند.
# کیت (C#) پیش از فرستادن ToSpeakable را اجرا می‌کند (ساعت، تاریخ، واحد، کدِ لاتین)؛ این‌جا فقط
# یکدست‌سازیِ حروف و پشتیبانِ عدد و لاتین برای وقتی که سرویس مستقیم صدا زده شود.
import re
import unicodedata

ZWNJ = "‌"
LETTERS = "آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئ"
KEPT_PUNCT = ".،؛؟!:"
_ALLOWED = set(LETTERS + ZWNJ + KEPT_PUNCT + " ")

# حروفِ عربیِ هم‌شکل ⇒ فارسی (برای مدل نویسه‌های دیگری‌اند)
_FOLD = str.maketrans({
    "ي": "ی", "ى": "ی", "ۍ": "ی", "ې": "ی", "ك": "ک", "ڪ": "ک", "ة": "ه", "ۀ": "ه", "ۂ": "ه", "ۃ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "ٲ": "ا", "ٳ": "ا", "ؤ": "و", "ء": "", "ـ": "",
    **{chr(0x06F0 + i): str(i) for i in range(10)}, **{chr(0x0660 + i): str(i) for i in range(10)},
    ",": "،", "?": "؟", ";": "؛", "…": ".", "٫": ".", "٬": "",
})
_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")
_INVISIBLE = re.compile(r"[​‍‎‏‪-‮⁦-⁩﻿­]")

_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
_SCALES = [(10 ** 12, "تریلیون"), (10 ** 9, "میلیارد"), (10 ** 6, "میلیون"), (10 ** 3, "هزار")]


def _below_1000(n):
    parts = []
    if n >= 100:
        parts.append(_HUNDREDS[n // 100])
        n %= 100
    if 10 <= n < 20:
        parts.append(_TEENS[n - 10])
    else:
        if n >= 20:
            parts.append(_TENS[n // 10])
        if n % 10:
            parts.append(_ONES[n % 10])
    return " و ".join(parts)


def number_words(n: int) -> str:
    if n == 0:
        return "صفر"
    parts = []
    for size, name in _SCALES:
        if n >= size:
            q, n = divmod(n, size)
            parts.append((_below_1000(q) + " " + name) if not (q == 1 and size == 1000) else name)
    if n:
        parts.append(_below_1000(n))
    return " و ".join(parts)


def _digits_each(d):
    return " ".join("صفر" if c == "0" else _ONES[int(c)] for c in d)


def _number(m):
    whole, frac = m.group(1), m.group(2)
    if len(whole) > 12 or (len(whole) > 1 and whole.startswith("0")):   # تلفن، کد: رقم‌به‌رقم
        return " " + _digits_each(whole) + (" ممیز " + _digits_each(frac) if frac else "") + " "
    out = number_words(int(whole))
    if frac and frac.rstrip("0"):
        frac = frac.rstrip("0")
        unit = {1: "دهم", 2: "صدم", 3: "هزارم"}.get(len(frac))
        out += " ممیز " + (number_words(int(frac)) + " " + unit if unit else _digits_each(frac))
    return " " + out + " "


# لاتین: حروفِ بزرگِ کوتاه حرف‌به‌حرف (PLC ⇒ پی اِل سی)، بقیه آوانگاریِ تقریبی
_LETTER_NAMES = dict(zip("abcdefghijklmnopqrstuvwxyz", [
    "ای", "بی", "سی", "دی", "ای", "اف", "جی", "اچ", "آی", "جی", "کی", "ال", "ام",
    "ان", "او", "پی", "کیو", "آر", "اس", "تی", "یو", "وی", "دبلیو", "ایکس", "وای", "زد"]))
_DIGRAPHS = {"sh": "ش", "ch": "چ", "kh": "خ", "gh": "غ", "ph": "ف", "th": "ت", "oo": "و", "ee": "ی",
             "ou": "او", "ai": "ای", "ay": "ای", "ey": "ای", "ck": "ک", "qu": "کو"}
_CHARS = dict(zip("abcdefghijklmnopqrstuvwxyz",
                  ["ا", "ب", "ک", "د", "", "ف", "گ", "ه", "ی", "ج", "ک", "ل", "م",
                   "ن", "و", "پ", "ک", "ر", "س", "ت", "و", "و", "و", "کس", "ی", "ز"]))
_LATIN = re.compile(r"[A-Za-z]+")


def _latin(m):
    w = m.group(0)
    if w.isupper() and len(w) <= 5:
        return " " + " ".join(_LETTER_NAMES[c] for c in w.lower()) + " "
    lw, out, i = w.lower(), [], 0
    while i < len(lw):
        if lw[i:i + 2] in _DIGRAPHS:
            out.append(_DIGRAPHS[lw[i:i + 2]])
            i += 2
        else:
            out.append(("آ" if i == 0 else "ا") if lw[i] == "a" else ("ا" if i == 0 and lw[i] in "eiou" else _CHARS[lw[i]]))
            i += 1
    s = "".join(out)
    if len(s) >= 2 and s[0] == "س" and s[1] in "پتکبگ":     # sp/st/sk ⇒ اسپ/است/اسک
        s = "ا" + s
    return " " + s + " "


def normalize(text: str) -> str:
    """فقط حروفِ فارسی، نیم‌فاصله، فاصله و «. ، ؛ ؟ ! :» می‌ماند."""
    t = unicodedata.normalize("NFC", text or "")
    t = _INVISIBLE.sub("", t)
    t = _DIACRITICS.sub("", t)
    t = re.sub(r"(?<=\d)[,٬](?=\d{3}(?!\d))", "", t)        # ۱٬۲۵۰٬۰۰۰ یک عدد است (\d رقمِ فارسی را هم می‌گیرد)
    t = t.translate(_FOLD)
    t = re.sub(r"[٪%]", " درصد ", t)
    t = re.sub(r"(\d+)(?:\.(\d+))?", _number, t)
    t = _LATIN.sub(_latin, t)
    t = "".join(c if c in _ALLOWED else " " for c in t)
    t = re.sub(ZWNJ + "+", ZWNJ, t)
    t = re.sub(r"\s*" + ZWNJ + r"\s*", lambda m: ZWNJ if " " not in m.group(0) else " ", t)
    t = re.sub(r"(?<![" + LETTERS + "])" + ZWNJ + "|" + ZWNJ + "(?![" + LETTERS + "])", "", t)
    t = re.sub(r"\s+([" + re.escape(KEPT_PUNCT) + "])", r"\1", t)
    t = re.sub(r"([" + re.escape(KEPT_PUNCT) + r"])\1+", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.lstrip(KEPT_PUNCT + " ")


_SENT = re.compile(r"(?<=[.!؟])\s+")
_PHRASE = re.compile(r"(?<=[،؛:])\s+")


def sentences(text: str):
    """جمله‌ها، هر کدام فهرستِ عبارت‌ها (جایی که نویسنده مکث گذاشته)."""
    out = []
    for line in re.split(r"[\r\n]+", text or ""):
        for s in _SENT.split(normalize(line)):
            ph = [p.strip() for p in _PHRASE.split(s) if re.search("[" + LETTERS + "]", p)]
            if ph:
                out.append(ph)
    return out
