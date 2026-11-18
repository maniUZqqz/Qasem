"""THE ROUND-3 ALGORITHM, KEPT ONLY SO THE "BEFORE" NUMBERS OF THE EZAFE CHECK CAN BE REPRODUCED (ezafe_gold.measure).

Nothing in the product imports this module any more: ezafe.py replaced it with a conservative one. It is the version that said
«چغرِ برنامه» and «علیِ کتاب»; see docs/pronunciation/ezafe-fa.md.

Ezafe: the unwritten «-e» / «-ye» that links a noun to what follows it.

    کتابِ من   ketAb-e man        خانهٔ بزرگ   xAne-ye bozorg
    نامِ شما   nAm-e SomA         ورزشِ روزانه varzeS-e ruzAne

Persian script does not write it, and a Persian voice that does not know the
grammar reads «کتاب من» with no link at all, which is the second most audible
"foreign accent" after the vowels.

We are deliberately conservative: a wrong ezafe sounds worse than a missing one.
We add it only when

  * the first word is a noun/adjective we know (lexicon tag N, a stem + plural /
    comparative suffix, or an unknown word that is not verb-shaped),
  * the next word is one that can follow an ezafe (a known noun/adjective, a
    pronoun, or a plural-looking word),
  * nothing (a pause, a verb, a preposition, the object marker «را») stands
    between them.
"""
from __future__ import annotations

import re

from . import dictionary as D
from . import numwords as _N

ZWNJ = "‌"

#: Never take an ezafe (and never follow one): function words and common verbs.
_NO_EZAFE = {
    "از", "در", "به", "با", "بر", "تا", "برای", "بی", "را", "که", "و", "یا", "اگر", "اما", "ولی",
    "چون", "زیرا", "پس", "هم", "نیز", "هر", "این", "آن", "همین", "همان", "چه", "چرا", "کجا",
    "کی", "کدام", "چند", "چقدر", "است", "هست", "نیست", "بود", "شد", "شده", "باشد", "بودن", "کرد",
    "کردن", "می", "نمی", "باید", "شاید", "فقط", "حتی", "هیچ", "خیلی", "بسیار", "همه", "همیشه",
    "هنوز", "دیگر", "حالا", "الان", "امروز", "فردا", "دیروز", "اینجا", "آنجا", "یک", "دو", "سه",
    "چهار", "پنج", "شش", "هفت", "هشت", "نه", "ده", "صد", "هزار", "میلیون", "نیم", "درصد",
    "دارد", "دارم", "دارید", "داریم", "دارند", "ندارد", "بدون", "مثل", "مانند", "درباره", "طی",
    "جز", "بعد", "قبل", "زیر", "روی", "کنار", "بالای", "جلوی", "پشت", "بین", "میان",
}
# every spoken number («سی», «بیست», «هزار», «نُه» ...) counts a noun, it never links to it: «سی دقیقه», not «سیِ دقیقه»
NUMBER_WORDS = {D.canon(w) for w in (_N.ONES + _N.TEENS + _N.TENS + _N.HUNDREDS + [x[1] for x in _N.SCALES] + ["صفر", "نیم"]) if w}
_NO_EZAFE |= NUMBER_WORDS

#: «دو لیتر آب», «دویست گرم پروتئین», «ده دقیقه گرم کردن», «سه عدد سیب»: a measure word after a number is not linked to what it
#: measures (a counted noun is: «دو جلسهٔ تمرین»).
MEASURE_NOUNS = {D.canon(w) for w in (
    "کیلو کیلوگرم گرم میلی‌گرم لیتر میلی‌لیتر متر سانتی‌متر میلی‌متر کیلومتر قاشق لیوان فنجان کف بسته عدد تکه برش مشت لقمه جرعه "
    "دقیقه ثانیه ساعت روز هفته ماه سال تومان ریال دلار یورو درصد نفر بار ست تکرار کالری کیلوکالری قدم گام درجه").split()}

#: May follow an ezafe although they are pronouns (کتابِ من).
_PRONOUNS = {"من", "تو", "او", "ما", "شما", "ایشان", "آنها", "آن‌ها", "اینها", "این‌ها", "خود",
             "خودم", "خودت", "خودش", "خودمان", "خودتان", "خودشان", "کسی", "چیزی"}

_VERBISH = re.compile(r"^(ن?می‌?[آ-ی]{2,}|[آ-ی]{2,}(?:یم|ید|ند)|ب[آ-ی]{3,}(?:یم|ید|ند)|"
                      r"[آ-ی]{2,}(?:ام|ای)ست)$")
_NOUNISH_END = re.compile(r"(?:‌ها|‌های|ان|ات|گی|ه|ی|ر|ن|ک|ل|ب|د|س|ز)$")      # not ش ت م: possessive clitics («پدرش», «کتابم»)
_PLURALISH = re.compile(r"(?:‌ها|‌های|ها|های|ان|ات)$")


#: «پیشنهاد کرد»، «کمک کنید»، «تمرین بده»: the noun before these is part of the verb (a light-verb construction), so the
#: word in front of it must not be linked to it by an ezafe («مکملِ خوبی پیشنهاد کرد», not «خوبیِ پیشنهاد»).
LIGHT_VERBS = {D.canon(w) for w in (
    "کرد کردن کردند کردم کردیم کردید کنم کنی کند کنیم کنید کنند کن نکرد نکن نکنید می‌کند می‌کنم می‌کنی می‌کنیم می‌کنید می‌کنند "
    "نمی‌کند نمی‌کنم نمی‌کنید داد دادن دادم دادند بده بدهید بدهم بدهد می‌دهد می‌دهم می‌دهید می‌دهند نمی‌دهد "
    "شد شدن شدند می‌شود می‌شوند نمی‌شود زد زدن بزن بزنید گرفت گرفتن بگیر بگیرید می‌گیرد می‌گیرند".split())}


#: «برنامه عالی است», «غذا خوشمزه بود»: an adjective that ENDS the clause with a copula is the predicate, it is not linked to the noun
#: before it. Without the mark in the text a wrong ezafe («برنامهٔ عالی است») sounds worse than a missing one.
COPULAS = {D.canon(w) for w in (
    "است هست نیست بود بودند بودم بودی بودیم بودید هستم هستی هستیم هستید هستند نیستم نیستی نیستیم نیستید نیستند "
    "باشد باشند باشم باشی باشیم باشید می‌باشد می‌باشند شد شدند شدم شدی شدیم شدید می‌شود می‌شوند می‌شوم می‌شوی می‌شویم می‌شوید "
    "نمی‌شود نمی‌شوند نشد نبود نیست".split())}


def _is_verbish(w: str, tag: str) -> bool:
    return tag == "V" or bool(_VERBISH.match(w))


def can_take(token_text: str, tag: str, source: str) -> bool:
    key = D.canon(token_text)
    if key in _NO_EZAFE or tag in ("F", "V"):
        return False
    if _is_verbish(key, tag):
        return False
    if key in _PRONOUNS:
        return False
    return True


def can_follow(token_text: str, tag: str) -> bool:
    key = D.canon(token_text)
    if key in _PRONOUNS:
        return True
    if key in _NO_EZAFE or tag in ("F", "V"):
        return False
    if _is_verbish(key, tag):
        return False
    return tag == "N" or bool(_PLURALISH.search(key))


#: nouns that merely END in what looks like a possessive clitic («مردم» = people, not «مرد» + «م»)
_NOT_POSSESSED = {D.canon(w) for w in ("مردم", "قدرت", "حکومت", "عادت", "حرکت", "سلامت", "صحبت", "دقت", "همت", "ثروت",
                                      "علت", "جمعیت", "کیفیت", "ماهیت", "فعالیت", "اهمیت", "نیت", "ملت", "وقت", "سخت",
                                      "اسم", "جسم", "حکم", "علم", "رسم", "قسم", "عشق", "حرم", "کرم", "نرم", "گرم", "رزم")}


def _is_possessed(t, dic: D.Dictionary) -> bool:
    """«پدرش», «کتابم», «خانه‌مان»: a noun we know + a possessive clitic. It never takes an ezafe itself."""
    if t.source in ("shared", "store", "global", "phrase", "letters", "conj") or t.pn and t.source != "morph":
        return False
    w = D.canon(t.text).replace(ZWNJ, "")
    if w in _NOT_POSSESSED or dic.lookup(w) is not None:
        return False
    for suf in ("مان", "تان", "شان", "ش", "م", "ت"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            e = dic.lookup(w[: -len(suf)])
            if e is not None and e.tag == "N":
                return True
    return False


def mark_ezafe(tokens, dic: D.Dictionary) -> None:
    """Set ``token.ezafe`` in place (tokens are ``pipeline.Token``)."""
    words = [t for t in tokens if t.kind == "word"]
    for idx, t in enumerate(tokens):
        if t.kind != "word" or idx + 1 >= len(tokens):
            continue
        nxt = tokens[idx + 1]
        if nxt.kind != "word":
            continue
        if not any("؀" <= c <= "ۿ" for c in t.text) or not any("؀" <= c <= "ۿ" for c in nxt.text):
            continue
        after = tokens[idx + 2] if idx + 2 < len(tokens) else None
        if after is not None and after.kind == "word" and D.canon(after.text) in LIGHT_VERBS:
            continue          # «… خوبی پیشنهاد کرد»: the next word belongs to the verb
        if t.written_ezafe:
            continue          # already set from what the writer wrote
        if D.canon(t.text) in MEASURE_NOUNS and idx > 0 and tokens[idx - 1].kind == "word" and D.canon(tokens[idx - 1].text) in NUMBER_WORDS:
            continue          # «دو لیتر آب»: a measure after a number
        if D.canon(t.text).endswith(ZWNJ + "ای") or _is_possessed(t, dic):
            continue          # «برنامه‌ای عالی»: no ezafe after the indefinite «ای»; «پدرش مرد»: none after a possessive ending
        if after is not None and after.kind == "word" and D.canon(after.text) in COPULAS and D.canon(nxt.text) not in _PRONOUNS:
            continue          # «برنامه عالی است»: «عالی» is the predicate (but «کتابِ من است»: a pronoun does take the ezafe)
        first_ok = can_take(t.text, t.tag, t.source) and (t.tag == "N" or t.source in ("morph", "homograph") or
                                                          bool(_PLURALISH.search(D.canon(t.text))))
        # an unknown word with noun shape may also take it when the next word is a sure follower
        if not first_ok and t.tag == "-" and not t.pn and can_take(t.text, t.tag, t.source) and \
                (D.canon(nxt.text) in _PRONOUNS or nxt.tag == "N") and _NOUNISH_END.search(D.canon(t.text)):
            first_ok = True
        if first_ok and can_follow(nxt.text, nxt.tag):
            t.ezafe = True
    _ = words
