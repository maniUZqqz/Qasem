"""ابزارِ کوتاه‌کردنِ هوشمندِ عبارت‌های فارسی برای عنوان و زیرعنوانِ تامنیل (بدونِ هوش مصنوعی).

مشکلِ نسخهٔ قبل: «۴ کلمهٔ اول» می‌برید و عبارت وسطِ جمله تمام می‌شد («برنامهٔ ورزشی شخصی برای»، «…اختصاصیِ یک»). این‌جا:

* هیچ عبارتی روی واژهٔ ناتمام (حرفِ اضافه، «و»، «را»، «که»، کلمهٔ دارای کسرهٔ اضافه…) تمام نمی‌شود؛
* اگر موضوع بلند است، پیش از نخستین «حرفِ اضافه/عطف» بریده می‌شود و باقیِ جمله (مثلاً «برای مبتدی‌ها در خانه») می‌ماند تا زیرعنوان شود؛
* محتوای داخلِ پرانتز از عنوان جدا می‌شود («برنامه‌سازِ دستیِ چغر (بدونِ هوش مصنوعی)» ⇒ عنوان + زیرعنوان)؛
* موضوعی که با عدد شروع می‌شود («۷ اشتباه در تمرینِ پا») عددش را نگه می‌دارد و دوباره عدد نمی‌گذارند؛
* موضوعِ «جمله‌ای» (چطور…، چرا…، آیا…، یا فعل‌دار) از موضوعِ «اسمی» جدا تشخیص داده می‌شود، چون قالب‌هایی مثلِ
  «{موضوع} را از اول بشناسید» فقط برای عبارتِ اسمی معنا دارند.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import typo

_MARKS = re.compile("[ً-ْٰٔ]")
_EDGE = " .؛،:!؟?-–—«»\"'()[]{}*|"
#: واژه‌هایی که یک عبارت نباید رویشان تمام شود
FUNC = frozenset("""و یا که را با برای از در به تا بر بی بدون مثل مانند چون اگر هم نیز اما ولی پس نه
درباره دربارهٔ همراه بین روی زیر علیه طبق مثلِ بجز جز""".split())
#: واژه‌هایی که «پیشِ اسم» می‌آیند؛ عبارت رویشان تمام نمی‌شود («… اختصاصیِ یک | ورزشکار»)
DETERMINERS = frozenset("""یک این آن هر همه چند دو سه چهار پنج همین همان هیچ برخی بعضی تمام چه کدام چطور چگونه آیا فقط""".split())
#: آغازِ یک عبارتِ تازه؛ بهترین جای بریدن درست پیشِ این واژه‌هاست
BOUNDARY = frozenset("""که با برای از در به تا بدون بی مثل مانند درباره دربارهٔ همراه بین""".split())
#: حرفِ عطف: بریدنِ پیش از آن‌ها یک گروهِ هم‌پایه («شکم و پهلو») را می‌شکند
COORD = frozenset("""و یا + &""".split())
QUESTION_START = frozenset("آیا چرا چطور چگونه چه کدام کی کجا چند".split())
VERB_WORDS = frozenset("""کنیم کنید کنم کنند کند بکنیم بکنید بسازیم بسازید بسازد شویم شوید شوم شود بشویم بشوید بشود است هست هستند هستیم هستید
باشد باشید باشیم نیست دارد دارند دارید داریم کرد شد بود بدانیم بدهیم ببریم بگیریم برسیم ببینیم بخوریم بخریم بسوزانیم بسوزانید بدهید بشناسیم
بشناسید بیاموزیم بیاموزید بمانیم بنویسیم بنویسید بخوانیم بخوانید بیاوریم بیاورید بروید برویم بخوابیم بخوابید""".split())


def is_verb(word: str) -> bool:
    w = norm(word)
    if w in VERB_WORDS:
        return True
    if w.startswith(("می‌", "نمی‌")) and len(w) >= 5:
        return True
    return len(w) >= 6 and w.startswith("ب") and w.endswith(("یم", "ید"))


LIST_NOUNS = frozenset("""اشتباه اشتباهات نکته نکات روش روش‌ها راه راه‌ها ایده ایده‌ها دلیل دلیل‌ها حرکت حرکت‌ها تمرین تمرین‌ها قدم گام ترفند
ترفندها عادت عادت‌ها غذا غذاها خوراکی خوراکی‌ها مکمل مکمل‌ها مورد موردها باور باورها افسانه افسانه‌ها""".split())
_LEAD_NUM = re.compile(r"^\s*([۰-۹0-9]{1,3})\s+(\S+)\s*(.*)$", re.S)
_PREP_LEAD = re.compile(r"^(?:رایج\s+)?(در|برای|از|به|دربارهٔ|درباره|درباره‌ی|برایِ)\s+(.+)$", re.S)
_RISKY = ("درصد", "تومان", "ریال", "تخفیف", "رایگان", "تضمین", "٪", "%", "$", "€")
_QUOTES = re.compile("[«»\"“”]")
_PAREN = re.compile(r"\(([^()]*)\)|（([^()]*)）")


def norm(word: str) -> str:
    """واژه بدونِ اعراب/کسره و نشانه‌گذاریِ کناری (برای مقایسه)."""
    return _MARKS.sub("", word).strip(_EDGE)


def is_func(word: str) -> bool:
    return norm(word) in FUNC


def dangling(word: str) -> bool:
    """عبارت روی این واژه ناتمام می‌ماند: حرفِ اضافه/عطف، «+»، واژهٔ پیشِ‌اسم («یک»، «این»…) یا کلمه‌ای که کسرهٔ اضافه دارد."""
    w = word.strip(_EDGE)
    n = norm(w)
    return (n in FUNC or n in DETERMINERS or w in ("+", "&") or word.strip().endswith(("\u0650", "\u0654", "\u06c0")) or not n)


def _clean(text) -> str:
    t = _QUOTES.sub("", typo.clean(text))
    t = re.sub(r"[*|]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_DASH = re.compile(r"\s+[—–]\s+")


def split_paren(text) -> tuple[str, str]:
    """«الف (ب) — ج» ⇒ («الف»، «ب ج»): پرانتز و بخشِ بعد از خط‌تیرهٔ جداشده از عبارتِ اصلی جدا می‌شود (برای زیرعنوان)."""
    t = _clean(text)
    inner: list[str] = []

    def take(m):
        inner.append((m.group(1) or m.group(2) or "").strip())
        return " "

    t = _PAREN.sub(take, t)
    t = re.sub(r"[()（）]", " ", t)
    parts = _DASH.split(t)
    if len(parts) > 1:
        t = parts[0]
        inner.extend(x.strip() for x in parts[1:])
    return re.sub(r"\s+", " ", t).strip(_EDGE), " ".join(i for i in inner if i).strip(_EDGE)


def _chars(ws: list[str]) -> int:
    return len(" ".join(ws))


def clip(text: str, max_words: int, max_chars: int = 0) -> tuple[str, str]:
    """⇒ (سرِ عبارت، باقی). سر هیچ‌وقت روی واژهٔ ناتمام تمام نمی‌شود؛ ترجیح با بریدنِ پیش از آغازِ «حرفِ اضافه» است
    («برنامهٔ ورزشی شخصی | برای مبتدی‌ها در خانه») و یک گروهِ هم‌پایه («شکم و پهلو») هرگز نصف نمی‌شود (تا ۲ واژه بیشتر از سقف
    مجاز است تا کامل بماند).

    ``max_words`` سقفِ تعدادِ واژه و ``max_chars`` (اختیاری) سقفِ تعدادِ حرف؛ اگر کلِ متن جا شود، باقی خالی است."""
    ws = _clean(text).strip(_EDGE).split()
    if not ws:
        return "", ""
    n = min(len(ws), max(1, max_words))
    while n > 1 and max_chars and _chars(ws[:n]) > max_chars:
        n -= 1
    if n >= len(ws) and not dangling(ws[-1]):
        return " ".join(ws), ""

    def ok(k: int) -> bool:
        return 1 <= k <= len(ws) and not dangling(ws[k - 1])

    def klass(k: int) -> int:
        """۰ = پایانِ متن یا پیش از حرفِ اضافه (بهترین)، ۱ = وسطِ گروه، ۲ = پیش از حرفِ عطف (گروهِ هم‌پایه را می‌شکند)، ۳ = پیش از فعل."""
        if k >= len(ws):
            return 0
        nxt = norm(ws[k])
        if is_verb(ws[k]):
            return 3                                           # فعلِ همین جمله را از جمله جدا نکن
        return 2 if (nxt in COORD or ws[k] in COORD) else (0 if nxt in BOUNDARY else 1)

    cap = max_chars * 1.25 if max_chars else 0
    cands = []
    for k in range(1, min(len(ws), n + 2) + 1):
        if not ok(k):
            continue
        if k > n and not (norm(ws[k - 2]) in COORD or ws[k - 2] in COORD or (k == n + 1 and is_verb(ws[k - 1]))):
            continue                                           # بیش از سقف فقط برای کامل‌کردنِ یک گروهِ هم‌پایه یا رسیدن به فعل
        if k > n and cap and _chars(ws[:k]) > cap:
            continue
        cands.append((klass(k), k))
    lo = max(1, n - 2)
    for want in (0, 1, 2):
        pool = [k for c, k in cands if c == want and k >= lo and (k >= 2 or n <= 2 or len(ws) == 1)]
        if pool:
            k = max(pool)
            return " ".join(ws[:k]), " ".join(ws[k:])
    if cands:
        k = max(k for _, k in cands)
        return " ".join(ws[:k]), " ".join(ws[k:])
    for k in range(1, len(ws) + 1):                           # آخرین راه: اولین واژهٔ تمام‌شده
        if ok(k):
            return " ".join(ws[:k]), " ".join(ws[k:])
    return "", ""


def tail_phrase(rest: str, max_words: int = 6) -> str:
    """باقیِ جملهٔ بریده‌شده (مثلاً «برای مبتدی‌ها در خانه») برای زیرعنوان؛ کامل (بی واژهٔ ناتمام)، دست‌کم دو واژه و بدونِ «و»ی ابتدایی."""
    first = norm((rest or "").split()[0]) if (rest or "").split() else ""
    if not first or first in COORD or (rest or "").split()[0] in COORD:
        return ""
    head, _ = clip(rest, max_words, 40)
    return head if len(head.split()) >= 2 else ""


_STRONG = re.compile(r"\s*[.!؟?؛;\n]+\s*|\s+[—–]\s+|\s*—\s*|[:：]\s+|،\s*")


def first_clause(text, max_words: int = 10, max_chars: int = 64) -> str:
    """از یک توضیحِ بلند (مثلاً توضیحِ محصول) کوتاه‌ترین بخشِ کامل و بی‌خطر را برمی‌دارد: اولین «بند» (تا نقطه، «؛»، «—»، «،»)
    و اگر هنوز بلند است، تا نزدیک‌ترین مرزِ طبیعی. بندی که قیمت/درصد/تخفیف/تضمین دارد کنار گذاشته می‌شود (ادعا نمی‌سازیم)."""
    body = split_paren(text)[0]
    for part in _STRONG.split(body):
        part = part.strip(_EDGE)
        if not part or any(w in part for w in _RISKY) or not typo.is_rtl(part):
            continue
        head, _ = clip(part, max_words, max_chars)
        if len(head.split()) >= 2:
            return head
    return ""


@dataclass
class Topic:
    full: str                 # متنِ پاک‌شده (بدونِ پرانتز و نشانه‌ها)
    main: str                 # عبارتِ اصلی (همان full، یا بعد از برداشتنِ عددِ ابتدایی)
    inner: str                # محتوای پرانتز
    kind: str                 # noun | clause
    lead_n: str = ""          # «۷» در «۷ اشتباه در تمرینِ پا»
    lead_noun: str = ""       # «اشتباه»
    lead_prep: str = ""       # «در»
    question: bool = False


def kind_of(text: str) -> tuple[str, bool]:
    ws = _clean(text).split()
    if not ws:
        return "noun", False
    q = norm(ws[0]) in QUESTION_START or _clean(text).rstrip().endswith(("؟", "?"))
    verb = len(ws) >= 3 and is_verb(ws[-1])
    return ("clause" if (q or verb) else "noun"), q


def parse_topic(topic: str) -> Topic:
    main, inner = split_paren(topic)
    full = main
    kind, q = kind_of(main)
    t = Topic(full=full, main=main, inner=inner, kind=kind, question=q)
    m = _LEAD_NUM.match(main)
    if m and norm(m.group(2)) in LIST_NOUNS:
        rest = m.group(3).strip()
        pm = _PREP_LEAD.match(rest)
        t.lead_n = typo.to_fa_digits(m.group(1)).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        t.lead_noun = m.group(2)
        if pm:
            t.lead_prep, t.main = pm.group(1), pm.group(2).strip()
        else:
            t.lead_prep, t.main = "", rest
        t.kind, t.question = "noun", False
        if not t.main:
            t.main = t.lead_noun
    return t


def mark_key(phrase: str) -> str:
    """فقط یک کلمهٔ مهمِ عبارت را برای رنگی‌شدن علامت می‌زند («برنامهٔ ورزشی شخصی» ⇒ «*برنامهٔ* ورزشی شخصی»): بلندترین واژهٔ معنادار."""
    words = _clean(phrase).split()
    if not words:
        return ""
    cand = [i for i, w in enumerate(words) if not dangling(w) and norm(w) not in QUESTION_START and norm(w) not in {"واقعاً", "خیلی"}]
    if not cand:
        cand = list(range(len(words)))
    best = max(cand, key=lambda i: (len(norm(words[i])), -i))
    if len(words) == 1:
        return f"*{words[0]}*"
    return " ".join(f"*{w}*" if i == best else w for i, w in enumerate(words))
