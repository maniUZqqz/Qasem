"""Persian-aware text handling for Instagram captions: normalization, hashtags, topic terms, and the «قلاب» (hook).

Pure functions, no Django. Deliberately small and explicit: a caption is short, a wrong clever guess is worse than a plain rule,
and every rule here has a test in tests_text.py.
"""
from __future__ import annotations

import re

# --- normalization ---------------------------------------------------------------------------------------------------------
_FIX = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ؤ": "و", "أ": "ا", "إ": "ا", "ـ": "", "‏": " ", "‎": " ",
                      "‪": " ", "‫": " ", "‬": " ", "⁦": " ", "⁧": " ", "⁩": " "})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MARKS = re.compile("[ً-ٰٟۖ-ۭ]")      # Arabic vowel marks: dropped
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_MENTION = re.compile(r"@[A-Za-z0-9._]{1,30}")
HASHTAG = re.compile(r"#([^\s#@!؟?،,.:;()\[\]{}«»\"'…]+)", re.UNICODE)
_WORD = re.compile(r"[^\W\d_]+(?:[‌'][^\W\d_]+)*", re.UNICODE)     # letters, with a half-space or apostrophe inside a word
_SPACES = re.compile(r"\s+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⭐⬆←-⇿]+")

STOPWORDS = frozenset("""
و در به از که را این آن با برای تا هم یا اما ولی اگر پس هر همه بی بر چه چی چرا چطور چگونه آیا کی کجا کدام
من تو او ما شما ایشان آنها اینها خود خودت خودم شد شده شود شوند است هست بود بودن باشد باشید باش نیست نبود دارد دارم دارید دارند
می نمی خواهد خواهید خواهم کرد کنید کنم کنی کنند کردن کن کنیم کرده کند دهد بده بدهید بدین گفت گویند گفته
یک دو سه چند بیشتر کمتر خیلی بسیار فقط تنها همین همان هنوز دیگر دیگه باید نباید میشه میشود شاید حتما حتی
ها های ان ات ام ایم اید اند ای
چون وقتی زمانی پیش بعد قبل روی زیر بین مثل مانند طور طوری نیز همچنین البته واقعا یعنی
the a an and or of to in on for with is are be this that it you your we our at by from as
""".split())
GENERIC_TAGS = frozenset("""اینستاگرام اکسپلور ریلز ریل ویدیو پست فالو فالوور لایک کامنت ایران تهران explore reels reel viral trending fyp foryou instagram
instagood love follow like likeforlike followforfollow""".split())


def normalize(text: str) -> str:
    """Lower-case, one kind of ی/ک, Latin digits, no vowel marks, no links, single spaces."""
    text = _URL.sub(" ", str(text or ""))
    text = text.translate(_FIX).translate(_DIGITS)
    text = _MARKS.sub("", text)
    return _SPACES.sub(" ", text.lower()).strip()


def hashtags(caption: str) -> list[str]:
    """Hashtags of a caption in order, normalized, without the #, no repeats."""
    out, seen = [], set()
    for raw in HASHTAG.findall(str(caption or "")):
        tag = normalize(raw).strip("_")
        if tag and tag not in seen and not tag.isdigit():
            seen.add(tag)
            out.append(tag)
    return out


def tag_phrase(tag: str) -> str:
    """تمرین_در_خانه -> «تمرین در خانه»."""
    return normalize(tag).replace("_", " ").strip()


def strip_caption(caption: str) -> str:
    """The caption without links, mentions, hashtags and emoji: the words a person wrote."""
    text = _URL.sub(" ", str(caption or ""))
    text = _MENTION.sub(" ", text)
    text = HASHTAG.sub(" ", text)
    text = _EMOJI.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ها"):
        return word[:-2]
    return word


def words(text: str) -> list[str]:
    """Content words of a text: letters only, no stop words, no one-letter bits, plural «ها» removed."""
    out = []
    for w in _WORD.findall(normalize(text)):
        for part in w.split("‌"):                       # «تمرین‌های» -> تمرین، های
            part = _stem(part.strip("'"))
            if len(part) >= 3 and part not in STOPWORDS and not part.isdigit():
                out.append(part)
    return out


def terms(caption: str, tags: list[str] | None = None) -> set[str]:
    """Topic features of one post: its hashtags («#…»), its content words and the neighbouring pairs of content words."""
    tags = tags if tags is not None else hashtags(caption)
    feats = {"#" + t for t in tags if t not in GENERIC_TAGS}
    ws = words(strip_caption(caption))
    feats.update(ws)
    feats.update("%s %s" % (a, b) for a, b in zip(ws, ws[1:]) if a != b)
    for t in tags:                                           # a hashtag's own words count a little too («تمرین_در_خانه» -> تمرین، خانه)
        if t not in GENERIC_TAGS:
            feats.update(words(tag_phrase(t)))
    return feats


def display_term(term: str) -> str:
    return tag_phrase(term[1:]) if term.startswith("#") else term


# --- the hook ---------------------------------------------------------------------------------------------------------------
_SENTENCE_END = re.compile(r"[.!؟?…\n]+")
_QUESTION_WORDS = ("چرا", "چطور", "چگونه", "آیا", "چند", "کی ", "کجا", "چه ", "چی ", "مگه", "how", "why", "what", "do you", "are you", "can you")
_NUMBER_LIST = re.compile(r"(?:^|\s)(\d{1,2})\s*(?:تا|مورد|نکته|دلیل|حرکت|روش|راه|اشتباه|قانون|ترفند|غذا|تمرین|گام|قدم)|\b\d{1,2}\s*(?:tips|ways|reasons|mistakes|exercises|rules)\b", re.I)
_CONTRARIAN = ("اشتباه", "هیچوقت", "هیچ وقت", "هرگز", "نکن", "نکنید", "نزن", "نزنید", "نباید", "دروغ", "افسانه", "باور غلط", "غلط", "stop ", "never", "mistake", "myth", "don't")
_STORY = ("من ", "وقتی ", "روزی ", "تجربه", "داستان", "قبلا", "سال پیش", "ماه پیش", "i ", "when i", "my ")
_CTA = ("ذخیره کن", "ذخیره کنید", "بفرست", "بفرستید", "کامنت", "شروع کن", "شروع کنید", "دنبال کن", "دنبال کنید", "save", "share", "comment", "follow")
_CLAIM = ("راز", "رمز", "فقط", "سریع‌ترین", "بهترین", "تضمین", "ثابت شده", "علمی", "بدون", "the secret", "best way", "fastest")
HOOK_TYPES = {"question": "پرسش", "number": "فهرستِ عددی", "contrarian": "هشدار/باورِ غلط", "story": "تجربه/داستان", "cta": "دعوت به اقدام",
              "claim": "وعدهٔ نتیجه", "statement": "جمله‌ی خبری"}


def hook_type(text: str) -> str:
    t = normalize(text).replace("‌", " ")          # «هیچ‌وقت» = «هیچ وقت»
    if not t:
        return "statement"
    if "؟" in text or "?" in text or t.startswith(_QUESTION_WORDS):
        return "question"
    if _NUMBER_LIST.search(t):
        return "number"
    if any(m in t for m in _CONTRARIAN):
        return "contrarian"
    if any(t.startswith(m) for m in _STORY[:3]) or any(m in t for m in _STORY[3:]):
        return "story"
    if any(m in t for m in _CTA):
        return "cta"
    if any(m in t for m in _CLAIM):
        return "claim"
    return "statement"


def extract_hook(caption: str, limit: int = 110) -> dict:
    """The first thing a viewer reads: the opening sentence of the caption (links, mentions, hashtags and emoji-only lines skipped)."""
    lines = [strip_caption(line) for line in str(caption or "").splitlines()]
    lines = [ln for ln in lines if len(ln) >= 3 and re.search(r"[^\W\d_]", ln)]
    if not lines:
        return {"text": "", "type": "statement"}
    first = lines[0]
    parts = [p.strip() for p in _SENTENCE_END.split(first) if p.strip()]
    text = parts[0] if parts else first
    if len(text) < 12 and len(parts) > 1:                    # «سلام.» is not a hook: take the next sentence too
        text = "%s. %s" % (text, parts[1])
    elif len(text) < 12 and len(lines) > 1:
        text = "%s %s" % (text, lines[1])
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip("،,;:") + "…"
    kind = hook_type(first if len(first) <= 200 else first[:200])
    return {"text": text.strip(), "type": kind}
