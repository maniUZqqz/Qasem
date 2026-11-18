"""Ezafe: the unwritten «-e» / «-ye» that links a noun to what follows it.

    کتابِ من   ketAb-e man        خانهٔ بزرگ   xAne-ye bozorg
    نامِ شما   nAm-e SomA         ورزشِ روزانه varzeS-e ruzAne

Persian script does not write it, and a Persian voice that does not know the grammar reads «کتاب من» with no link at all.
Without a parser the layer cannot know every ezafe, and a WRONG one («چغرِ برنامه» in «با چغر برنامه بساز», «علیِ کتاب» in «علی کتاب
می‌خواند») is far worse than a missing one: the voice then says something the writer never meant, and says the brand wrong.

So this module is CONSERVATIVE (round 3 of the review): an automatic ezafe is added only where one of these rules is confident, and
nowhere else. «Where in doubt, none.»

  1. noun + ADJECTIVE we know («برنامه ورزشی», «غذای سالم»). Classifying adjectives («ورزشی», «روزانه») are always attributive; qualitative
     ones («سالم», «سنگین») only when what follows cannot be a verb («بچه‌ها سالم رسیدند» is not «بچه‌هایِ سالم»); adjectives that are also
     adverbs («خوب», «سریع») only at the end of the phrase. A copula after the adjective means it is the predicate («برنامه عالی است»).
  2. noun + POSSESSIVE pronoun («کتابِ من», «نامِ شما»), unless the pronoun is followed by «را» («مربی شما را» = the coach ... you).
  3. noun + a noun that normally takes a genitive («کاهشِ وزن», «قیمتِ محصول»): only the curated list ``ezafe_data.HEADS``; any other
     pair of nouns («مربی برنامه می‌نویسد», «شنا حرکت‌ها») is left alone.
  4. a product word + a brand («اپِ چغر»).
  5. the writer's own mark («هٔ», a kasra, «ه‌ی») - always honoured (``Token.written_ezafe``), and a lexicon phrase.

A name, a title or a brand never takes an automatic ezafe («علی کتاب ...», «دکتر علی رضایی», «با چغر برنامه ...»), and neither does a word the
lexicon and the lists do not know as a noun (it only takes one in front of a classifying adjective: «کفش ورزشی»).
How many wrong and missing ezafes this leaves is measured on a hand-checked set (``ezafe_gold.py``, docs/pronunciation/ezafe-fa.md).
"""
from __future__ import annotations

import re

from . import dictionary as D
from . import ezafe_data as L
from . import numwords as _N

ZWNJ = "‌"


def _key(word: str) -> str:
    """Lookup form: Persian letters, no short-vowel marks, no half-space."""
    return D.canon(word).replace(ZWNJ, "")


def _set(words) -> frozenset[str]:
    return frozenset(_key(w) for w in words)


#: Never take an ezafe (and never follow one): function words, interjections and the commonest verbs.
_NO_EZAFE = {
    "از", "در", "به", "با", "بر", "تا", "برای", "بی", "را", "که", "و", "یا", "اگر", "اما", "ولی",
    "چون", "زیرا", "پس", "هم", "نیز", "هر", "این", "آن", "همین", "همان", "چه", "چرا", "کجا",
    "کی", "کدام", "چند", "چقدر", "است", "هست", "نیست", "بود", "شد", "شده", "باشد", "بودن", "کرد",
    "کردن", "می", "نمی", "باید", "شاید", "فقط", "حتی", "هیچ", "خیلی", "بسیار", "همه", "همیشه",
    "هنوز", "دیگر", "حالا", "الان", "امروز", "فردا", "دیروز", "اینجا", "آنجا", "یک", "دو", "سه",
    "چهار", "پنج", "شش", "هفت", "هشت", "نه", "ده", "صد", "هزار", "میلیون", "نیم", "درصد",
    "دارد", "دارم", "دارید", "داریم", "دارند", "ندارد", "بدون", "مثل", "مانند", "درباره", "طی",
    "جز", "بعد", "قبل", "زیر", "روی", "کنار", "بالای", "جلوی", "پشت", "بین", "میان",
    # interjections and light infinitives: «سلام من علی هستم», «گرفتن آبی»
    "سلام", "درود", "خداحافظ", "لطفا", "لطفاً", "ممنون", "متشکرم", "بله", "خیر", "ببخشید", "عزیزم", "شدن", "داشتن", "گرفتن",
    "دادن", "زدن", "رفتن", "آمدن", "خواستن", "توانستن", "گفتن", "سپاس", "تبریک", "خوش",
}
# every spoken number («سی», «بیست», «هزار», «نُه» ...) counts a noun, it never links to it: «سی دقیقه», not «سیِ دقیقه»
NUMBER_WORDS = {D.canon(w) for w in (_N.ONES + _N.TEENS + _N.TENS + _N.HUNDREDS + [x[1] for x in _N.SCALES] + ["صفر", "نیم"]) if w}
_NO_EZAFE |= NUMBER_WORDS
_NO_EZAFE_K = _set(_NO_EZAFE)
_NUMBER_K = _set(NUMBER_WORDS)

#: «دو لیتر آب», «دویست گرم پروتئین», «ده دقیقه گرم کردن», «سه عدد سیب»: a measure word after a number is not linked to what it
#: measures (a counted noun is: «دو جلسهٔ تمرین»).
MEASURE_NOUNS = {D.canon(w) for w in (
    "کیلو کیلوگرم گرم میلی‌گرم لیتر میلی‌لیتر متر سانتی‌متر میلی‌متر کیلومتر قاشق لیوان فنجان کف بسته عدد تکه برش مشت لقمه جرعه "
    "دقیقه ثانیه ساعت روز هفته ماه سال تومان ریال دلار یورو درصد نفر بار ست تکرار کالری کیلوکالری قدم گام درجه").split()}
_MEASURE_K = _set(MEASURE_NOUNS)

_ATTR = _set(L.ATTR)
_QUAL = _set(L.QUAL)
_AMBIG = _set(L.AMBIG)
_ADJ_ALL = _ATTR | _QUAL | _AMBIG
#: «خوبی», «سالمی»: an adjective + the indefinite -i. (Not «کمی», «زیادی»: those are adverbs of their own.)
_INDEFINITE_STEMS = _QUAL | _set("خوب بد دقیق راحت درست محکم".split())
_POSSESSOR = _set(L.POSSESSOR)
_REFLEXIVE = _set(L.REFLEXIVE)
_HEADS = _set(L.HEADS)
_PRODUCT_HEADS = _set(L.PRODUCT_HEADS)
_PREP_NOUNS = _set(L.PREP_NOUNS)
_BRANDS = _set(L.BRANDS)
_NAMES = _set(L.NAMES) | _set(L.TITLES)
_COMMON_NOUNS = _set(L.COMMON_NOUNS)
_PERSON = _set(L.PERSON)
_PLACE_HEADS = _set(L.PLACE_HEADS)
_VERB_FORMS = _set(L.VERB_FORMS)
_RESULT_VERBS = _set(L.RESULT_VERBS)

#: May follow an ezafe although they are pronouns (کتابِ من). (Kept for the helpers below.)
_PRONOUNS = {"من", "تو", "او", "ما", "شما", "ایشان", "آنها", "آن‌ها", "اینها", "این‌ها", "خود",
             "خودم", "خودت", "خودش", "خودمان", "خودتان", "خودشان", "کسی", "چیزی"}

_VERBISH = re.compile(r"^(ن?می‌?[آ-ی]{2,}|[آ-ی]{2,}(?:یم|ید|ند)|ب[آ-ی]{3,}(?:یم|ید|ند)|"
                      r"[آ-ی]{2,}(?:ام|ای)ست)$")
_PLURALISH = re.compile(r"(?:‌ها|‌های|ها|های|ان|ات)$")
_PERSIAN = re.compile(r"[؀-ۿ]")


#: «پیشنهاد کرد»، «کمک کنید»، «تمرین بده»: the noun before these is part of the verb (a light-verb construction), so the
#: word in front of it must not be linked to it by an ezafe («مکملِ خوبی پیشنهاد کرد», not «خوبیِ پیشنهاد»).
LIGHT_VERBS = {D.canon(w) for w in (
    "کرد کردن کردند کردم کردیم کردید کنم کنی کند کنیم کنید کنند کن نکرد نکن نکنید می‌کند می‌کنم می‌کنی می‌کنیم می‌کنید می‌کنند "
    "نمی‌کند نمی‌کنم نمی‌کنید داد دادن دادم دادند بده بدهید بدهم بدهد می‌دهد می‌دهم می‌دهید می‌دهند نمی‌دهد "
    "شد شدن شدند می‌شود می‌شوند نمی‌شود زد زدن بزن بزنید گرفت گرفتن بگیر بگیرید می‌گیرد می‌گیرند".split())}
_LIGHT_K = _set(LIGHT_VERBS) | _set(L.RESULT_VERBS)

#: «برنامه عالی است», «غذا خوشمزه بود»: an adjective that ENDS the clause with a copula is the predicate, it is not linked to the noun
#: before it. Without the mark in the text a wrong ezafe («برنامهٔ عالی است») sounds worse than a missing one.
COPULAS = {D.canon(w) for w in (
    "است هست نیست بود بودند بودم بودی بودیم بودید هستم هستی هستیم هستید هستند نیستم نیستی نیستیم نیستید نیستند "
    "باشد باشند باشم باشی باشیم باشید می‌باشد می‌باشند شد شدند شدم شدی شدیم شدید می‌شود می‌شوند می‌شوم می‌شوی می‌شویم می‌شوید "
    "نمی‌شود نمی‌شوند نشد نبود نیست".split())}
_COPULA_K = _set(COPULAS)

#: Words that may follow a qualitative adjective with the noun in front of it still linked: «غذای سالم و ...», «منبع خوب برای ...».
_CLAUSE_OK = _set("سلام درود ممنون لطفا لطفاً و یا را که تا با از در به برای بر بی بدون مثل مانند درباره روی زیر کنار بین بعد قبل پس اما ولی اگر چون هر همه این آن همین همان چند".split())
#: ... and after an adjective that is also an adverb only these («منبع خوب.», «منبع خوب و ...»).
_AMBIG_OK = _set("و یا را که".split())


# ------------------------------------------------------------------ small tests on one word

def _plain(t) -> str:
    return _key(t.text)


def _is_verbish(w: str, tag: str) -> bool:
    """A verb form. The lexicon's own «N» is trusted («رژیم», «تصمیم», «پیوند» end like a first-person verb but are nouns)."""
    if tag == "N":
        return False
    return tag == "V" or bool(_VERBISH.match(w)) or _key(w) in _VERB_FORMS


def _is_persian(t) -> bool:
    return t.kind == "word" and bool(_PERSIAN.search(t.text))


def _split_comparative(k: str) -> str:
    """«سنگین‌تر» -> «سنگین», «سالم‌ترین» -> «سالم» (as the half-space-free keys)."""
    for suf in ("ترین", "تر"):
        if k.endswith(suf) and len(k) - len(suf) >= 3:
            return k[: -len(suf)]
    return k


def _lexicon_category(t, dic: D.Dictionary) -> str:
    e = dic.lookup(t.text)
    return e.category if e else ""


def _is_proper(t, dic: D.Dictionary) -> bool:
    k = _plain(t)
    if k in _NAMES or k in _BRANDS:
        return True
    return _lexicon_category(t, dic).startswith("نام‌ها") or _lexicon_category(t, dic).startswith("نام‌های")


def _is_adjective(k: str) -> bool:
    return k in _ADJ_ALL or _split_comparative(k) in _QUAL


def _second_kind(nxt, dic: D.Dictionary) -> str | None:
    """What kind of follower is ``nxt``: 'attr' | 'qual' | 'ambig' | 'pron' | 'refl' | 'brand' | 'noun' | 'name' | 'unknown' | None."""
    raw = D.canon(nxt.text)
    k = _key(nxt.text)
    if k in _POSSESSOR:
        return "pron"
    if k in _REFLEXIVE:
        return "refl"
    if k in _BRANDS:
        return "brand"
    # the curated adjective lists first: «جدید», «سفید», «بلند» end like a verb («ید», «ند») but are adjectives
    if k in _ATTR:
        return "attr"
    if raw.endswith(ZWNJ + "ای") and len(raw) > 4 and not _VERBISH.match(raw):
        return "attr"                           # «حرفه‌ای», «هفته‌ای», «تغذیه‌ای»: a derived adjective
    if k in _QUAL or _split_comparative(k) in _QUAL:
        return "qual"
    if k.endswith("ی") and k[:-1] in _INDEFINITE_STEMS:
        return "attr"                           # «مکملِ خوبی», «برنامهٔ سالمی»: the indefinite -i makes it a noun's attribute
    if k in _AMBIG or _split_comparative(k) in _AMBIG:
        return "ambig"
    if k in _NO_EZAFE_K or nxt.tag in ("F", "V") or _is_verbish(nxt.text, nxt.tag):
        return None
    if _is_proper(nxt, dic):
        return "name"
    if _is_noun(nxt, dic):
        return "noun"
    if _is_unknown_word(nxt, dic):
        return "unknown"
    return None


def _is_noun(t, dic: D.Dictionary) -> bool:
    """A word we KNOW to be a noun: tagged N in the lexicon, built from known stems, plural-looking, or in the common-noun list."""
    k = _plain(t)
    if t.kind != "word" or k in _NO_EZAFE_K or t.tag in ("F", "V"):
        return False
    if k in _POSSESSOR or k in _REFLEXIVE or _is_adjective(k) or k in _NAMES or k in _BRANDS:
        return False
    if t.source in ("store", "global", "phrase", "conj", "letters", "rule"):
        return False
    if k in _COMMON_NOUNS:
        return True
    if _is_verbish(t.text, t.tag):
        return False
    if _lexicon_category(t, dic).startswith("نام‌"):
        return False
    return (t.tag == "N" or t.source in ("morph", "homograph") or k in _COMMON_NOUNS
            or bool(_PLURALISH.search(D.canon(t.text))) and _PERSIAN.search(t.text) is not None)


def _is_unknown_word(t, dic: D.Dictionary) -> bool:
    """A Persian word nobody lists: may be a noun, a verb, a name. It only takes an ezafe in front of a classifying adjective."""
    k = _plain(t)
    if t.kind != "word" or len(k) < 3 or k in _NO_EZAFE_K or t.tag in ("F", "V") or _is_verbish(t.text, t.tag):
        return False
    if k in _POSSESSOR or k in _REFLEXIVE or _is_adjective(k) or k in _NAMES or k in _BRANDS:
        return False
    if t.source in ("store", "global", "phrase", "conj", "letters", "rule", "homograph") or t.n_words > 1:
        return False
    return t.tag == "-" and not t.pn or t.source == "shared" and t.tag == "-"


#: nouns that merely END in what looks like a possessive clitic («مردم» = people, not «مرد» + «م»)
_NOT_POSSESSED = {D.canon(w) for w in ("کارت", "مردم", "قدرت", "حکومت", "عادت", "حرکت", "سلامت", "صحبت", "دقت", "همت", "ثروت",
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


# ------------------------------------------------------------------ public helpers (kept for callers and tests)

def can_take(token_text: str, tag: str, source: str) -> bool:
    """May this word be the FIRST word of an automatic ezafe? (A weaker test than ``mark_ezafe`` applies.)"""
    key = _key(token_text)
    if key in _NO_EZAFE_K or tag in ("F", "V") or key in _NAMES or key in _BRANDS:
        return False
    if _is_verbish(token_text, tag):
        return False
    if key in _POSSESSOR or key in _REFLEXIVE:
        return False
    return True


def can_follow(token_text: str, tag: str) -> bool:
    key = _key(token_text)
    if key in _POSSESSOR or key in _REFLEXIVE:
        return True
    if key in _NO_EZAFE_K or tag in ("F", "V") or _is_verbish(token_text, tag):
        return False
    return tag == "N" or bool(_PLURALISH.search(D.canon(token_text))) or key in _ADJ_ALL


# ------------------------------------------------------------------ the rules

def _after_ok(after, kind: str, dic: D.Dictionary) -> bool:
    """May the follower ``kind`` stand in front of ``after`` and still be an attribute of the noun?"""
    if kind == "attr":
        return True
    boundary = after is None or after.kind != "word" or not _PERSIAN.search(after.text)
    k = "" if boundary else _key(after.text)
    if kind == "ambig":
        return boundary or k in _AMBIG_OK
    # qualitative: the clause goes on with something that cannot be a verb
    if boundary or k in _CLAUSE_OK:
        return True
    if _is_adjective(k) or k in _POSSESSOR or k in _REFLEXIVE or k in _BRANDS:
        return True
    return _is_noun(after, dic)


def _decide(tokens, idx: int, dic: D.Dictionary, prev_linked: bool) -> bool:
    t, nxt = tokens[idx], tokens[idx + 1]
    after = tokens[idx + 2] if idx + 2 < len(tokens) else None
    after_word = after is not None and after.kind == "word"
    k = _plain(t)
    after_k = _key(after.text) if after_word else ""

    if k in _MEASURE_K and idx > 0 and tokens[idx - 1].kind == "word" and _key(tokens[idx - 1].text) in _NUMBER_K:
        return False          # «دو لیتر آب»: a measure after a number
    if D.canon(t.text).endswith(ZWNJ + "ای") or _is_possessed(t, dic):
        return False          # «برنامه‌ای عالی»: no ezafe after the indefinite «ای»; «پدرش مرد»: none after a possessive ending
    kind = _second_kind(nxt, dic)
    if kind is None:
        return False
    nxt_k = _key(nxt.text)

    # ---- the FIRST word
    if _is_adjective(k) or k in _NAMES or k in _BRANDS and kind != "brand" or t.tag in ("F", "V"):
        # an adjective is linked to what follows it only inside a chain «برنامهٔ ورزشیِ شما» / «رژیمِ غذاییِ سالم»
        if not (prev_linked and (k in _ATTR or k in _QUAL) and kind in ("pron", "refl", "attr", "qual", "brand")):
            return False
        first = "chain"
    elif _is_proper(t, dic) or _plain(t) in _NO_EZAFE_K and k not in _PREP_NOUNS:
        return False
    elif k in _PREP_NOUNS:
        first = "prep"
    elif _is_noun(t, dic) or k in _HEADS or k in _PRODUCT_HEADS:
        first = "noun"
    elif _is_unknown_word(t, dic):
        first = "unknown"
    else:
        return False

    # ---- the FOLLOWER
    if kind == "refl":
        # «کارِ خود را» is possessive; «مربی خودش تصمیم می‌گیرد» is the coach HIMSELF: only in front of «را», and never after a person word
        if first not in ("noun", "chain") or k in _PERSON or not (after_word and after_k == _key("را")):
            return False
        return True
    if kind == "pron":
        if first == "unknown":
            return False
        if after_word and after_k == _key("را"):
            return False      # «مربی شما را» = the coach ... you: no way to tell it from «برنامهٔ شما را» without a parser
        if after_word and after_k in _LIGHT_K and first != "chain":
            return False      # «اسم شما بنویس»
        return True
    if first == "prep":
        return False
    if kind == "brand":
        if after_word and after_k in _COPULA_K:
            return False
        return first == "chain" or (first == "noun" and k in _PRODUCT_HEADS)
    if kind in ("attr", "qual", "ambig"):
        if first == "unknown" and kind != "attr":
            return False
        if after_word and after_k in _COPULA_K:
            return False      # «برنامه عالی است»: the predicate
        if after_word and after_k in _RESULT_VERBS:
            return False      # «غذا آماده کرد», «خانه تمیز شد»: a result, not an attribute
        if kind == "attr" and nxt_k in _MEASURE_K:
            return False
        return _after_ok(after, kind, dic)
    if kind in ("name", "unknown"):
        # «شهرِ تهران», «کشورِ ایران»: only a place word links to a name (or to a word nobody lists)
        return first == "noun" and k in _PLACE_HEADS and not (after_word and after_k in _LIGHT_K | _COPULA_K)
    if kind == "noun":
        if first != "noun" or not (k in _HEADS or k in _PRODUCT_HEADS or k in _PLACE_HEADS):
            return False
        if after_word and after_k in _LIGHT_K:
            return False      # «… خوبی پیشنهاد کرد»: the next word belongs to the verb
        return True
    return False


def mark_ezafe(tokens, dic: D.Dictionary) -> None:
    """Set ``token.ezafe`` in place (tokens are ``pipeline.Token``)."""
    prev_linked = False
    for idx, t in enumerate(tokens):
        if t.kind != "word":
            prev_linked = False
            continue
        if t.written_ezafe or t.ezafe_inside:
            # the spelling already carries it («هٔ», a kasra, «ه‌ی», «ورزش‌های»): never added twice, never taken away
            t.ezafe = True
            prev_linked = True
            continue
        decided = False
        if idx + 1 < len(tokens) and _is_persian(t) and tokens[idx + 1].kind == "word" and _is_persian(tokens[idx + 1]):
            decided = _decide(tokens, idx, dic, prev_linked)
        if decided:
            t.ezafe = True
        prev_linked = bool(t.ezafe)
