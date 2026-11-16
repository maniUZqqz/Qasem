"""Ezafe: the unwritten «-e» / «-ye» that links a noun to what follows it.

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
_NO_EZAFE |= {D.canon(w) for w in (_N.ONES + _N.TEENS + _N.TENS + _N.HUNDREDS + [x[1] for x in _N.SCALES] + ["صفر"]) if w}

#: May follow an ezafe although they are pronouns (کتابِ من).
_PRONOUNS = {"من", "تو", "او", "ما", "شما", "ایشان", "آنها", "آن‌ها", "اینها", "این‌ها", "خود",
             "خودم", "خودت", "خودش", "خودمان", "خودتان", "خودشان", "کسی", "چیزی"}

_VERBISH = re.compile(r"^(ن?می‌?[آ-ی]{2,}|[آ-ی]{2,}(?:یم|ید|ند)|ب[آ-ی]{3,}(?:یم|ید|ند)|"
                      r"[آ-ی]{2,}(?:ام|ای)ست)$")
_NOUNISH_END = re.compile(r"(?:‌ها|‌های|ان|ات|گی|ش|ه|ی|ت|ر|ن|ک|ل|م|ب|د|س|ز)$")
_PLURALISH = re.compile(r"(?:‌ها|‌های|ها|های|ان|ات)$")


#: «پیشنهاد کرد»، «کمک کنید»، «تمرین بده»: the noun before these is part of the verb (a light-verb construction), so the
#: word in front of it must not be linked to it by an ezafe («مکملِ خوبی پیشنهاد کرد», not «خوبیِ پیشنهاد»).
LIGHT_VERBS = {D.canon(w) for w in (
    "کرد کردن کردند کردم کردیم کردید کنم کنی کند کنیم کنید کنند کن نکرد نکن نکنید می‌کند می‌کنم می‌کنی می‌کنیم می‌کنید می‌کنند "
    "نمی‌کند نمی‌کنم نمی‌کنید داد دادن دادم دادند بده بدهید بدهم بدهد می‌دهد می‌دهم می‌دهید می‌دهند نمی‌دهد "
    "شد شدن شدند می‌شود می‌شوند نمی‌شود زد زدن بزن بزنید گرفت گرفتن بگیر بگیرید می‌گیرد می‌گیرند".split())}


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
        first_ok = can_take(t.text, t.tag, t.source) and (t.tag == "N" or t.source in ("morph", "homograph") or
                                                          bool(_PLURALISH.search(D.canon(t.text))))
        # an unknown word with noun shape may also take it when the next word is a sure follower
        if not first_ok and t.tag == "-" and can_take(t.text, t.tag, t.source) and \
                (D.canon(nxt.text) in _PRONOUNS or nxt.tag == "N") and _NOUNISH_END.search(D.canon(t.text)):
            first_ok = True
        if first_ok and can_follow(nxt.text, nxt.tag):
            t.ezafe = True
    _ = words
