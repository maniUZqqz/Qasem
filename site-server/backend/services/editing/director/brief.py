"""From a sentence to a *brief*: what the owner wants, as plain values the recipes can use.

This is the deterministic half of "understanding the prompt" — Persian/English keywords, numbers and quotes — so that a
shop with no AI available still gets what it asked for in the common cases. The model (`ai.refine_brief`) only improves on it.
"""
from __future__ import annotations

import re

PLATFORMS: dict[str, dict] = {
    "reels": {"title": "ریلز اینستاگرام", "preset": "reel", "zone": "reels", "target": 22, "max": 60, "shot": (1.3, 3.4)},
    "story": {"title": "استوری", "preset": "reel", "zone": "story", "target": 12, "max": 15, "shot": (1.2, 3.0)},
    "tiktok": {"title": "تیک‌تاک", "preset": "reel", "zone": "tiktok", "target": 24, "max": 60, "shot": (1.2, 3.2)},
    "shorts": {"title": "شورتسِ یوتیوب", "preset": "reel", "zone": "shorts", "target": 24, "max": 60, "shot": (1.3, 3.5)},
    "feed": {"title": "پستِ اینستاگرام", "preset": "feed", "zone": "feed", "target": 20, "max": 60, "shot": (1.8, 4.0)},
    "square": {"title": "پستِ مربع", "preset": "square", "zone": "feed", "target": 20, "max": 60, "shot": (1.8, 4.0)},
    "youtube": {"title": "یوتیوب / آپارات", "preset": "wide", "zone": "feed", "target": 45, "max": 180, "shot": (2.5, 8.0)},
}
RECIPES: dict[str, dict] = {
    "product_showcase": {"title": "معرفیِ محصول", "hint": "نماهای پرجذبه، تیتر، موسیقی و دعوت به خرید"},
    "unboxing": {"title": "جعبه‌گشایی", "hint": "ترتیبِ فیلم حفظ می‌شود؛ سکوت‌ها حذف، زیرنویس و زومِ کوچک"},
    "before_after": {"title": "قبل و بعد", "hint": "دو نما با برچسبِ «قبل» و «بعد» و گذارِ پاک‌کننده"},
    "sale": {"title": "حراج و تخفیف", "hint": "برچسبِ درشتِ تخفیف، برش‌های تند و کارتِ پایانی"},
    "testimonial": {"title": "نظرِ مشتری", "hint": "حرفِ مشتری بدون مکث، زیرنویسِ درشت و نامِ گوینده"},
    "slideshow": {"title": "اسلایدشوی عکس", "hint": "عکس‌ها با حرکتِ آرام، گذارِ نرم و موسیقی"},
    "polish": {"title": "ویدیوی گفتاری — تدوینِ حرفه‌ای", "hint": "مکثِ بی‌دلیل کوتاه (مکثِ عمدی می‌ماند)، نور و رنگ، قابِ دنبالِ چهره، زیرنویس، موسیقیِ هم‌خوان و صدای استاندارد"},
}
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_PLAT_WORDS = (
    ("story", r"استوری|story|stories"),
    ("tiktok", r"تیک[ ‌]?تاک|tiktok"),
    ("shorts", r"شورت|shorts?\b"),
    ("reels", r"ریلز|ریل\b|reels?|اینستا(?!گرام پست)"),
    ("youtube", r"یوتیوب|یوتوب|youtube|آپارات|افقی"),
    ("square", r"مربع|square|1:1"),
    ("feed", r"پست|فید|feed"),
)
_RECIPE_WORDS = (
    ("unboxing", r"جعبه[ ‌]?گشایی|unbox"),
    ("before_after", r"قبل( و |/|\s)+بعد|before.?after"),
    ("testimonial", r"نظر[ ‌]?مشتری|رضایت|testimonial|review|نقد و بررسی|مصاحبه"),
    ("slideshow", r"اسلاید|slideshow|عکس[ ‌]?ها|photos?|گالری"),
    ("sale", r"حراج|تخفیف|فروش[ ‌]?ویژه|شگفت|پیشنهاد ویژه|sale|discount|% ?off|off\b|\d+ ?(٪|%|درصد)"),
)


def digits(text: str) -> str:
    return (text or "").translate(_FA)


def parse_prompt(prompt: str, *, assets: list[dict] | None = None) -> dict:
    """The deterministic brief. `assets` (describe dicts) only help to guess the recipe/platform when the words do not say."""
    raw = digits(prompt or "")
    low = raw.lower()
    brief: dict = {"recipe": "", "platform": "", "duration": 0, "pace": "", "title": "", "subtitle": "", "cta": "", "discount": 0,
                   "captions": None, "music": None, "background": "", "background_ref": "", "look": "", "hook": "", "notes": [], "matched": []}

    for key, pattern in _PLAT_WORDS:
        if re.search(pattern, low):
            brief["platform"] = key
            brief["matched"].append("پلتفرم")
            break
    for key, pattern in _RECIPE_WORDS:
        if re.search(pattern, low):
            brief["recipe"] = key
            brief["matched"].append("نوعِ ویدیو")
            break

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ثانیه|ثانیه‌ای|sec|seconds?|s\b)", low)
    if m:
        brief["duration"] = max(5, min(180, int(float(m.group(1)))))
        brief["matched"].append("مدت")
    elif re.search(r"نیم[ ‌]?دقیقه", low):
        brief["duration"] = 30
        brief["matched"].append("مدت")
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:دقیقه|min)", low)
        if m:
            brief["duration"] = max(5, min(180, int(float(m.group(1)) * 60)))
            brief["matched"].append("مدت")

    m = re.search(r"(\d{1,2})\s*(?:٪|%|درصد)", raw)
    if m:
        brief["discount"] = max(1, min(95, int(m.group(1))))
        brief["matched"].append("درصدِ تخفیف")

    if re.search(r"سریع|تند|پرانرژی|هیجان|پر[ ‌]?شور|fast|energetic|punchy|dynamic", low):
        brief["pace"] = "fast"
    elif re.search(r"آرام|لوکس|ملایم|سینمایی|کند|calm|slow|luxury|elegant|cinematic", low):
        brief["pace"] = "slow"
    brief["pace_explicit"] = bool(brief["pace"])
    if brief["pace"]:
        brief["matched"].append("ریتم")

    if re.search(r"بدون[ ‌]زیرنویس|زیرنویس نه|no captions", low):
        brief["captions"] = False
    elif re.search(r"زیرنویس|captions?|subtitle", low):
        brief["captions"] = True
    if re.search(r"بدون[ ‌]موسیقی|بی[ ‌]?موسیقی|no music", low):
        brief["music"] = False
    elif re.search(r"موسیقی|آهنگ|music|beat|ضرب", low):
        brief["music"] = True

    # the background behind the speaker: «پس‌زمینه را محو کن» · «پس‌زمینه ساده/سفید/رنگی» · nothing said = left as it is
    if re.search(r"(?:پس[ ‌]?زمینه|بک[ ‌]?گراند|background).{0,24}(?:محو|بلر|مات|blur)|(?:محو|بلر|blur).{0,16}(?:پس[ ‌]?زمینه|بک[ ‌]?گراند|background)", low):
        brief["background"] = "blur"
        brief["matched"].append("پس‌زمینه")
    elif re.search(r"(?:پس[ ‌]?زمینه|بک[ ‌]?گراند|background).{0,24}(?:عکس|تصویر|photo|image|picture)|(?:عکس|تصویر|photo|image|picture).{0,16}(?:پس[ ‌]?زمینه|بک[ ‌]?گراند|background)", low):
        brief["background"] = "image"                       # replaced with a picture (the picture itself comes from the panel's choice or from the images picked)
        brief["matched"].append("پس‌زمینه")
    elif re.search(r"(?:پس[ ‌]?زمینه|بک[ ‌]?گراند|background).{0,24}(?:ساده|سفید|تیره|رنگی|عوض|تعویض|جایگزین|plain|solid|replace)", low):
        brief["background"] = "color"
        brief["matched"].append("پس‌زمینه")

    if re.search(r"سینمایی|cinematic", low):
        brief["look"] = "cinematic"
    elif re.search(r"گرم|warm|golden|طلایی", low):
        brief["look"] = "golden_hour"
    elif re.search(r"شاداب|پررنگ|vivid|colorful|رنگی", low):
        brief["look"] = "vivid"
    elif re.search(r"سیاه[ ‌]?و[ ‌]?سفید|bw|black and white", low):
        brief["look"] = "bw"

    q = re.search(r"[«“\"]([^»”\"]{3,60})[»”\"]", raw)
    if q:
        brief["title"] = q.group(1).strip()
        brief["matched"].append("عنوان")
    t = re.search(r"(?:عنوان|تیتر|title)\s*[:：]\s*([^\n.،,]{3,60})", raw, re.I)
    if t and not brief["title"]:
        brief["title"] = t.group(1).strip()
        brief["matched"].append("عنوان")
    c = re.search(r"(?:دعوت به|شعار|cta|call to action)\s*[:：]\s*([^\n.،,]{3,60})", raw, re.I)
    if c:
        brief["cta"] = c.group(1).strip()

    # nothing said → guess from the footage
    kinds = [a.get("kind") for a in (assets or [])]
    if not brief["recipe"]:
        if kinds and all(k == "image" for k in kinds if k != "audio") and kinds.count("image") >= 2:
            brief["recipe"] = "slideshow"
        elif brief["discount"]:
            brief["recipe"] = "sale"
        else:
            brief["recipe"] = "product_showcase"
    if not brief["platform"]:
        brief["platform"] = "reels"
        brief["notes"].append("پلتفرم گفته نشد؛ ریلز (۹:۱۶) در نظر گرفته شد.")
    return brief


def looks_like_talking_video(assets: list[dict], an: dict) -> bool:
    """One long video with a person talking in it (and no other footage): a talk, a lesson, an interview, a product explained to the camera.
    The product recipes would cut it into 2-second shots; this one is polished, not re-cut."""
    videos = [a for a in assets if a.get("kind") == "video"]
    others = [a for a in assets if a.get("kind") == "image"]
    if len(videos) != 1 or others:
        return False
    row = (an or {}).get("by_ref", {}).get(videos[0]["ref"]) or {}
    dur = float(row.get("duration") or videos[0].get("duration") or 0)
    speech = sum(e - s for s, e in row.get("spans", []))
    return dur >= 20.0 and speech >= 0.45 * dur


_CONNECTORS = frozenset("با و از در به برای که را تا یا بر این آن یک چه چی ولی اما + - — – : ، ؛".split())
#: ≤ 2-letter Persian words that really end a title (anything else ending a title that short is a word cut in half)
_SHORT_WORDS = frozenset("تو من ما او آن دو سه نو آب بد بر به در از تا یا را که چه هر هم ده بی کن شو رو نه کم پر مو پا دل سر جا".split())
#: words that can never start the «name» taken from a prompt (the kind of video, the platform, the length, the verbs of the request)
_NOT_A_NAME = frozenset("""
با در به و که را تا از ولی اما برای درباره ثانیه ثانیه‌ای دقیقه دقیقه‌ای سریع آرام ریلز ریل استوری ویدیو ویدئو فیلم کلیپ پست بساز بسازید بسازین درست کن
کنید لطفا لطفاً یک این آن همین معرفی تبلیغ ترویج پروموشن حراج تخفیف فروش جعبه‌گشایی جعبه گشایی قبل بعد اسلایدشو اسلاید نظر مشتری مصاحبه محصول برند اپ
اپلیکیشن برنامه فروشگاه کالا تیک‌تاک تیکتاک شورتس یوتیوب آپارات اینستاگرام تدوین سینمایی جذاب حرفه‌ای عکس عکس‌ها گالری
make create a an the for about promote promoting reel story video short post
""".split())
_LEAD = re.compile(
    r"(?:معرفیِ?|تبلیغِ?|ترویجِ?|پروموشنِ?|درباره(?:ٔ|ی)?|برای|جعبه[ ‌]?گشاییِ?|promote|promoting|about|for)\s+"
    r"(?:(?:محصولِ?|برندِ?|اپلیکیشنِ?|اپِ?|برنامهٔ?|فروشگاهِ?|کالای?)\s+)?", re.I)
_LABEL_WORD = re.compile(r"(?:عکس|تصویر|اسلاید|ویدیو|ویدئو|پوستر|بنر|کاور|استوری|ریلز|ویدیوی ساخته[‌ ]?شده)", re.I)
#: what the media bin appends after « — » (the kind of the item): «عکس», «اسلاید ۱», «پوستر تبلیغاتی» ...
_LIB_SUFFIX = re.compile(r"(?:عکس|تصویر|اسلاید|ویدیو|ویدئو|پوستر|بنر|کاور|استوری|ریلز)\s*[\d۰-۹]*|پوستر تبلیغاتی|عکس محصول آماده[‌ ]?ی اینستاگرام|بهبود تصویر با حفظ خود محصول|ویدیوی ساخته[‌ ]?شده")
_PERSIAN = re.compile(r"[\u0600-\u06FF]")


def looks_like_label(text: str, raw: str = "") -> bool:
    """A file name or a library label (not a name a person gave): «IMG_2031», «rev_talk_test_1», «عکس ۳», digits only."""
    t = " ".join(str(text or "").split())
    if not t or re.fullmatch(r"[\d۰-۹٠-٩ .:_-]*", t):
        return True
    if re.fullmatch(rf"(?:{_LABEL_WORD.pattern}|video|image|photo|clip|untitled|screenshot|screen ?recording)\s*[\d۰-۹٠-٩ _.-]*", t, re.I):
        return True
    if re.search(r"(?:^|\s)(?:IMG|VID|DSC|MOV|PXL|WA|Screenshot|Screen Recording)[ _-]?\d+", t, re.I):
        return True
    if not _PERSIAN.search(t) and (re.search(r"\d{3,}", t) or "_" in str(raw or "")):
        return True
    return False


def _fit(text: str, limit: int = 34, max_words: int = 6) -> str:
    """At most `limit` characters / `max_words` words, cut between words and, when it must be cut, at a clause boundary
    («… با» / «… و» / «+») - never in the middle of a word and never on a dangling connector."""
    t = " ".join(str(text or "").split()).strip(" +-—–:،,.؛;|/")
    toks = t.split(" ") if t else []
    kept: list[str] = []
    for tok in toks[:max_words]:
        if kept and len(" ".join(kept + [tok])) > limit:
            break
        kept.append(tok)
    if len(kept) < len(toks):                                  # it had to be cut: back up to the last clause boundary
        for i in range(len(kept) - 1, 0, -1):
            if kept[i] in _CONNECTORS:
                kept = kept[:i]
                break
    while kept and (kept[-1] in _CONNECTORS or kept[-1] in "+-—–:،,.؛;|/"):
        kept.pop()
    return " ".join(kept)


def _clean_name(title: str, limit: int = 34) -> str:
    """A name a person gave, out of a library label: «برنامهٔ ورزشی + غذایی با هوش مصنوعی — عکس» → «برنامهٔ ورزشی + غذایی»;
    a file name or a placeholder («IMG_2031.mp4», «ویدیو ۳») gives «»."""
    raw = str(title or "")
    t = re.sub(r"\.(mp4|mov|mkv|avi|webm|jpg|jpeg|png|webp)$", "", raw.strip(), flags=re.I)
    t = re.sub(r"\s*[(（].*?[)）]", " ", t)                      # «(تدوین‌شده)», «(۹:۱۶ …)»
    t = next((p for p in re.split(r"\s*[—–]+\s*", t) if p.strip()), "")      # the library appends « — عکس» / « — اسلاید ۱»: the name is what comes before
    t = t.replace("_", " ")
    t = re.sub(r"(تدوین‌شده)", " ", t)
    t = " ".join(t.split())
    if looks_like_label(t, raw):
        return ""
    if re.search(r"[:：؟?]", t):                                 # «معرفی کاروسل: هزینه‌ها چقدر است؟» → the part before the colon names it
        head = re.split(r"[:：]", t, maxsplit=1)[0].strip()
        if len(head.split()) >= 2 and not looks_like_label(head):
            t = head
    return _fit(t, limit)


def phrase_from_prompt(request: str) -> str:
    """The thing the owner wants the video about, when the sentence names it: «… برای معرفی چغر بساز» → «چغر»."""
    text = digits(request or "")
    for m in _LEAD.finditer(text):
        tail = re.split(r"[.!?؟,،;؛:\n(«»\"“”]", text[m.end():], maxsplit=1)[0]
        name: list[str] = []
        for tok in tail.split():
            bare = tok.strip("ِٔ").lower()
            if bare in _NOT_A_NAME or re.match(r"[\d٪%.]", bare):
                break
            name.append(tok)
            if len(name) >= 4:
                break
        if name and name[0].strip("ِٔ").lower() not in _NOT_A_NAME:
            out = _fit(" ".join(name), 30, 4)
            if out and not looks_like_label(out):
                return out
    return ""


def title_problem(title: str) -> str:
    """Why a title burned into a video looks wrong (a Persian sentence), or «»: a file label, a library suffix, a title that stops in the
    middle of a word or on a connector."""
    t = " ".join(str(title or "").split())
    if not t:
        return ""
    if re.search(r"\.(mp4|mov|mkv|avi|webm|jpe?g|png|webp)\b", t, re.I) or re.search(r"\b\w+_\w+_\w+", t) \
            or re.search(r"(?:^|\s)(?:IMG|VID|DSC|MOV|PXL)[ _-]?\d+", t, re.I):
        return "شبیهِ نامِ فایل است"
    dash = re.search(r"[—–]\s*([^—–]*)$", t)
    if dash:
        tail = dash.group(1).strip()
        if not tail or _LIB_SUFFIX.fullmatch(tail) or (len(t) >= 38 and re.fullmatch(r"[\u0600-\u06FF]{1,2}", tail)):
            return "برچسبِ کتابخانه (مثلاً «— عکس») یا یک بریدگی در تیتر مانده است"
    if re.search(r"\(\s*[\d۰-۹]+\s*[:٫.]\s*[\d۰-۹]+", t):
        return "اندازهٔ قاب (مثلاً «۹:۱۶») در تیتر مانده است"
    stripped = re.sub(r"[\s+\-—–:،,;؛|/]+$", "", t)
    last = stripped.split(" ")[-1] if stripped else ""
    if last in _CONNECTORS or t[-1] in "+-—–":
        return "تیتر روی یک حرفِ ربط یا نشانه تمام می‌شود و ناقص است"
    if len(t) >= 38 and re.fullmatch(r"[\u0600-\u06FF]{1,2}", last) and last not in _SHORT_WORDS:      # a long title ending in a 1-2 letter non-word: the old hard cut at 40 characters
        return "تیتر وسطِ یک کلمه بریده شده است"
    return ""


def pick_name(assets: list[dict], request: str = "", store_name: str = "") -> str:
    """What the video is about: a phrase of the prompt, else a product name from the picked media, else the shop's own name."""
    phrase = phrase_from_prompt(request)
    if phrase:
        return phrase
    for a in assets:
        if a.get("kind") in ("video", "image"):
            name = _clean_name(a.get("title"))
            if name:
                return name
    return _fit(store_name, 30, 4)


def _named(prefix: str, name: str) -> str:
    """«معرفی X» (or «جعبه‌گشایی X») without saying «معرفی» twice."""
    if not name:
        return ""
    return name if name.split()[0].strip("ِٔ") == prefix.split()[0] else f"{prefix} {name}"


def finish_brief(brief: dict, assets: list[dict], *, request: str = "", store_name: str = "") -> dict:
    """Fill every missing field with a sensible default (never overwrites what is set).
    The reel's title is, in this order: what the owner typed (quoted), a phrase of the prompt, a product name from the picked media
    (its library label stripped), the shop's name; never a file/library label and never cut in the middle of a word."""
    b = dict(brief)
    plat = PLATFORMS.get(b.get("platform") or "reels", PLATFORMS["reels"])
    b["platform"] = b.get("platform") if b.get("platform") in PLATFORMS else "reels"
    if b.get("recipe") not in RECIPES:
        b["recipe"] = "product_showcase"
    if not b.get("duration"):
        b["duration"] = plat["target"]
    b["duration"] = max(6, min(plat["max"], int(b["duration"])))
    if b.get("pace") not in ("fast", "normal", "slow"):
        b["pace"] = {"sale": "fast", "unboxing": "normal", "testimonial": "normal", "slideshow": "slow", "before_after": "normal", "polish": "normal"}.get(b["recipe"], "normal" if b["platform"] in ("feed", "youtube") else "fast")
    name = pick_name(assets, request, store_name)
    problem = title_problem(b["title"]) if b.get("title") else ""
    if problem:                                                # a title that is a file label or stops mid-word (a model's, or an old brief's) is replaced
        b["notes"] = list(b.get("notes") or []) + [f"تیترِ «{b['title']}» {problem}؛ تیترِ تازه ساخته شد."]
        b["title"] = ""
    if not b.get("title"):
        if b["recipe"] == "sale":
            b["title"] = f"{b['discount']}٪ تخفیف ویژه" if b.get("discount") else "فروشِ ویژه"
        elif b["recipe"] == "unboxing":
            b["title"] = _named("جعبه‌گشایی", name) or "جعبه‌گشایی"
        elif b["recipe"] == "before_after":
            b["title"] = "قبل و بعد"
        elif b["recipe"] == "testimonial":
            b["title"] = "نظرِ مشتریان"
        elif b["recipe"] == "polish":
            b["title"] = ""
        else:
            b["title"] = _named("معرفی", name) or "معرفیِ محصول"
    if not b.get("cta"):
        b["cta"] = "همین حالا سفارش بده"
    b["subtitle"] = b.get("subtitle") or ""
    return b
