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


def finish_brief(brief: dict, assets: list[dict]) -> dict:
    """Fill every missing field with a sensible default (never overwrites what is set)."""
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
    first = next((a for a in assets if a.get("kind") in ("video", "image")), None)
    name = _clean_name(first.get("title") if first else "")
    if not b.get("title"):
        if b["recipe"] == "sale":
            b["title"] = f"{b['discount']}٪ تخفیف ویژه" if b.get("discount") else "فروشِ ویژه"
        elif b["recipe"] == "unboxing":
            b["title"] = f"جعبه‌گشایی {name}".strip()
        elif b["recipe"] == "before_after":
            b["title"] = "قبل و بعد"
        elif b["recipe"] == "testimonial":
            b["title"] = "نظرِ مشتریان"
        elif b["recipe"] == "polish":
            b["title"] = ""
        else:
            b["title"] = f"معرفی {name}".strip() if name else "معرفیِ محصول"
    if not b.get("cta"):
        b["cta"] = "همین حالا سفارش بده"
    b["subtitle"] = b.get("subtitle") or ""
    return b


def _clean_name(title: str) -> str:
    t = re.sub(r"\.(mp4|mov|mkv|jpg|jpeg|png|webp)$", "", str(title or ""), flags=re.I)
    t = re.sub(r"(تدوین‌شده|\(.*?\)|[-_]+)", " ", t)
    t = re.sub(r"\b(IMG|VID|MOV|DSC|PXL)[ _]?\d+\b", " ", t, flags=re.I)
    t = " ".join(t.split())
    return "" if re.fullmatch(r"[\d ]*", t) else t[:40]
