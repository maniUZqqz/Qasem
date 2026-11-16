"""Latin-script words inside Persian text: say them the way an Iranian would.

A voice engine given «Instagram» either spells it letter by letter or reads it
with English phonetics, and neither is what an Iranian listener expects. Three
tiers, in order:

1. a lexicon of the English words, brands and app words that actually occur in
   Persian marketing copy (``LATIN_WORDS``: lower-case English -> Persian
   spelling that the pronunciation lexicon / letter rules read correctly);
2. acronyms (two to five capital letters, «GPS», «HIIT») -> letter names;
3. a rough English-spelling -> Persian-sound transliteration for everything
   else. It is deliberately modest and the caller is told (``is_guess``) so the
   panel can list the word under «مشکل‌دار» for the owner to fix once.
"""
from __future__ import annotations

import re

from . import phones as P

#: English / brand word (lower case) -> Persian written form.
LATIN_WORDS: dict[str, str] = {
    # apps and companies
    "instagram": "اینستاگرام", "telegram": "تلگرام", "whatsapp": "واتساپ",
    "youtube": "یوتیوب", "google": "گوگل", "facebook": "فیس‌بوک", "twitter": "توییتر",
    "tiktok": "تیک‌تاک", "linkedin": "لینکدین", "snapchat": "اسنپ‌چت", "aparat": "آپارات",
    "apple": "اپل", "iphone": "آیفون", "ipad": "آی‌پد", "android": "اندروید", "ios": "آی‌او‌اس",
    "samsung": "سامسونگ", "xiaomi": "شیائومی", "huawei": "هواوی", "windows": "ویندوز",
    "microsoft": "مایکروسافت", "amazon": "آمازون", "netflix": "نتفلیکس", "spotify": "اسپاتیفای",
    "zoom": "زوم", "skype": "اسکایپ", "chatgpt": "چت‌جی‌پی‌تی", "openai": "اوپن‌ای‌آی",
    "digikala": "دیجی‌کالا", "snapp": "اسنپ", "divar": "دیوار", "chagher": "چغر",
    "nmarketing": "ان‌ام‌مارکتینگ", "upmarket": "آپ‌مارکت",
    # brands (kept in step with services/audio/lexicon.py)
    "nike": "نایکی", "adidas": "آدیداس", "puma": "پوما", "sony": "سونی", "lg": "ال‌جی",
    "philips": "فیلیپس", "bosch": "بوش", "zara": "زارا", "casio": "کاسیو", "rolex": "رولکس",
    "reebok": "ریباک", "dyson": "دایسون", "xbox": "ایکس‌باکس", "playstation": "پلی‌استیشن",
    # app / web words
    "app": "اپ", "apps": "اپ‌ها", "application": "اپلیکیشن", "application": "اپلیکیشن",
    "online": "آنلاین", "offline": "آفلاین", "link": "لینک", "site": "سایت",
    "website": "وب‌سایت", "web": "وب", "email": "ایمیل", "e-mail": "ایمیل", "mail": "میل",
    "password": "پسورد", "login": "لاگین", "logout": "لاگ‌اوت", "sign": "ساین", "up": "آپ",
    "download": "دانلود", "upload": "آپلود", "install": "اینستال", "update": "آپدیت",
    "profile": "پروفایل", "account": "اکانت", "follow": "فالو", "follower": "فالوور",
    "followers": "فالوورها", "like": "لایک", "likes": "لایک‌ها", "comment": "کامنت",
    "comments": "کامنت‌ها", "share": "شیر", "story": "استوری", "stories": "استوری‌ها",
    "reels": "ریلز", "reel": "ریل", "post": "پست", "posts": "پست‌ها", "page": "پیج",
    "live": "لایو", "direct": "دایرکت", "dm": "دایرکت", "bio": "بایو", "hashtag": "هشتگ",
    "channel": "کانال", "group": "گروه", "chat": "چت", "message": "مسیج", "video": "ویدیو",
    "audio": "آدیو", "photo": "عکس", "image": "ایمیج", "story": "استوری",
    "ok": "اوکی", "okay": "اوکی", "wifi": "وای‌فای", "wi-fi": "وای‌فای", "bluetooth": "بلوتوث",
    "internet": "اینترنت", "network": "نتورک", "server": "سرور", "code": "کد", "qr": "کیوآر",
    "pdf": "پی‌دی‌اف", "ai": "هوش مصنوعی", "id": "آیدی", "vip": "وی‌آی‌پی", "pro": "پرو",
    "plus": "پلاس", "premium": "پریمیوم", "free": "فری", "gift": "گیفت", "sale": "سیل",
    "off": "آف", "new": "نیو", "best": "بست", "top": "تاپ", "mini": "مینی", "max": "مکس",
    "smart": "اسمارت", "digital": "دیجیتال", "design": "دیزاین", "brand": "برند",
    "marketing": "مارکتینگ", "store": "استور", "shop": "شاپ", "market": "مارکت",
    "service": "سرویس", "support": "ساپورت", "team": "تیم", "manager": "منیجر",
    "business": "بیزینس", "startup": "استارتاپ", "plan": "پلن", "package": "پکیج",
    "pack": "پک", "level": "لول", "star": "استار", "mode": "مود", "stop": "استاپ",
    "start": "استارت", "play": "پلی", "pause": "پاز", "next": "نکست", "back": "بک",
    "home": "هوم", "menu": "منو", "setting": "ستینگ", "settings": "ستینگ", "search": "سرچ",
    "notification": "نوتیفیکیشن", "version": "ورژن", "beta": "بتا", "demo": "دمو",
    "feedback": "فیدبک", "trend": "ترند", "viral": "وایرال", "content": "کانتنت",
    "creator": "کریتور", "influencer": "اینفلوئنسر", "blog": "بلاگ", "podcast": "پادکست",
    "studio": "استودیو", "style": "استایل", "look": "لوک", "model": "مدل", "stock": "استوک",
    # fitness / health
    "fitness": "فیتنس", "workout": "ورکاوت", "gym": "جیم", "coach": "کوچ",
    "coaching": "کوچینگ", "trainer": "ترینر", "training": "تریینینگ", "diet": "دایت",
    "cardio": "کاردیو", "yoga": "یوگا", "pilates": "پیلاتس", "crossfit": "کراس‌فیت",
    "hiit": "هیت", "bmi": "بی‌ام‌آی", "kcal": "کیلوکالری", "calorie": "کالری",
    "calories": "کالری", "protein": "پروتئین", "vitamin": "ویتامین", "omega": "امگا",
    "squat": "اسکوات", "deadlift": "ددلیفت", "plank": "پلانک", "bench": "بنچ",
    "press": "پرس", "pushup": "شنا", "pull-up": "بارفیکس", "pullup": "بارفیکس",
    "dumbbell": "دمبل", "barbell": "هالتر", "treadmill": "تردمیل", "set": "ست",
    "rep": "تکرار", "reps": "تکرار", "warmup": "گرم‌کردن", "cooldown": "سردکردن",
    "bulk": "بالک", "cut": "کات", "lean": "لین", "fat": "فت", "body": "بادی",
    "health": "هلث", "healthy": "هلثی", "motivation": "موتیویشن", "challenge": "چالش",
    "goal": "گل", "run": "ران", "running": "رانینگ", "swim": "سویم", "bike": "بایک",
    # titles / small words
    "dr": "دکتر", "mr": "آقای", "mrs": "خانم", "ms": "خانم", "vs": "در برابر",
    "etc": "و غیره", "and": "اند", "of": "آو", "the": "د", "for": "فور", "to": "تو",
    "by": "بای", "with": "ویت", "in": "این", "on": "آن", "is": "ایز", "hi": "های",
    "hello": "هلو", "bye": "بای", "thanks": "تنکس", "thank": "تنک", "you": "یو",
    "yes": "یس", "no": "نو", "pm": "پی‌ام", "am": "ای‌ام",
    # currencies spelled
    "usd": "دلار", "eur": "یورو", "irr": "ریال", "irt": "تومان",
}

LETTER_NAMES = {
    "a": "ای", "b": "بی", "c": "سی", "d": "دی", "e": "ای", "f": "اف", "g": "جی",
    "h": "اچ", "i": "آی", "j": "جی", "k": "کی", "l": "ال", "m": "ام", "n": "ان",
    "o": "او", "p": "پی", "q": "کیو", "r": "آر", "s": "اس", "t": "تی", "u": "یو",
    "v": "وی", "w": "دبلیو", "x": "ایکس", "y": "وای", "z": "زد",
}

_VOWELS_EN = set("aeiouy")


def spell_letters(token: str) -> str:
    """«GPS» -> «جی پی اس»; digits inside stay for the number pass."""
    out = []
    for ch in token:
        if ch.lower() in LETTER_NAMES:
            out.append(LETTER_NAMES[ch.lower()])
        elif ch.isdigit():
            out.append(ch)
    return " ".join(out)


# ------------------------------------------------------------- transliteration

_DIGRAPHS = [
    ("tch", "C"), ("sch", "sk"), ("ough", "o"), ("igh", "Ay"), ("sh", "S"), ("ch", "C"),
    ("th", "t"), ("ph", "f"), ("ck", "k"), ("gh", ""), ("kn", "n"), ("wr", "r"),
    ("wh", "v"), ("qu", "kv"), ("ng", "ng"), ("ee", "i"), ("ea", "i"), ("oo", "u"),
    ("ou", "ow"), ("ow", "o"), ("oa", "o"), ("ai", "ey"), ("ay", "ey"), ("ei", "ey"),
    ("ey", "i"), ("au", "o"), ("aw", "o"), ("oi", "oy"), ("oy", "oy"), ("ie", "i"),
    ("ue", "u"), ("dg", "j"), ("ps", "ps"),
]
_SINGLE = {
    "a": "a", "b": "b", "c": "k", "d": "d", "e": "e", "f": "f", "g": "g", "h": "h",
    "i": "i", "j": "j", "k": "k", "l": "l", "m": "m", "n": "n", "o": "o", "p": "p",
    "q": "k", "r": "r", "s": "s", "t": "t", "u": "a", "v": "v", "w": "v", "x": "ks",
    "y": "i", "z": "z",
}


def english_to_pn(word: str) -> str:
    """Rough English spelling -> PN. Good enough to be understood, not to be proud of."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    out: list[str] = []
    i = 0
    n = len(w)
    while i < n:
        for dg, rep in _DIGRAPHS:
            if w.startswith(dg, i):
                if dg in ("kn", "wr", "wh") and i != 0:
                    continue
                out.append(rep)
                i += len(dg)
                break
        else:
            ch = w[i]
            nxt = w[i + 1] if i + 1 < n else ""
            if ch == "c" and nxt in "eiy":
                out.append("s")
            elif ch == "g" and nxt in "eiy" and i + 2 < n + 1 and w[i:i + 3] not in ("get", "gir", "gif"):
                out.append("j")
            elif ch == "e" and i == n - 1 and n > 2 and w[i - 1] not in _VOWELS_EN:
                pass  # silent final e: "make", "fine"
            elif ch == "y" and i == n - 1 and n > 2:
                out.append("i")
            elif ch == "y" and i == 0:
                out.append("y")
            elif ch == "u" and i == 0:
                out.append("A" if nxt in "nps" else "yu")
            elif ch == "x":
                out.extend(["k", "s"])
            else:
                if _SINGLE[ch]:
                    out.append(_SINGLE[ch])
            i += 1
    pn = "".join(out)
    # collapse doubled consonants the way Persian speakers do
    pn = re.sub(r"([bdfgklmnprstvz])\1+", r"\1", pn)
    pn = pn.replace("ks", "ks")
    # keep only valid PN (drop anything the table produced that PN lacks)
    cleaned = []
    for t in _safe_parse(pn):
        cleaned.append(t)
    return "".join(cleaned)


def _safe_parse(pn: str) -> list[str]:
    toks: list[str] = []
    i = 0
    while i < len(pn):
        if pn[i] == "o" and pn[i + 1:i + 2] == "w":
            toks.append("ow")
            i += 2
            continue
        ch = pn[i]
        if ch in "aeoAiu" or ch in P.CONSONANTS:
            toks.append(ch)
        i += 1
    return toks


def transliterate(word: str) -> str:
    """Latin word -> Persian script with the short vowels written (see phones.to_respelling)."""
    pn = english_to_pn(word)
    return P.to_respelling(P.parse(pn)) if pn else ""


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*|[A-Za-z]+")


def speak_latin(token: str) -> tuple[str, bool]:
    """-> (Persian text, is_guess). ``is_guess`` is True only for tier 3."""
    raw = token.strip("-'’")
    low = raw.lower().replace("’", "'")
    if low in LATIN_WORDS:
        return LATIN_WORDS[low], False
    if low.endswith("'s") and low[:-2] in LATIN_WORDS:
        return LATIN_WORDS[low[:-2]], False
    if "-" in low:
        parts = [speak_latin(p) for p in low.split("-") if p]
        return " ".join(p[0] for p in parts), any(p[1] for p in parts)
    letters = re.sub(r"[^A-Za-z]", "", raw)
    has_digit = any(c.isdigit() for c in raw)
    if has_digit and letters:
        # model numbers: A52, S23, 4K, 5G -> letter names + number
        pieces = re.findall(r"[A-Za-z]+|\d+", raw)
        spoken = []
        for p in pieces:
            spoken.append(p if p.isdigit() else spell_letters(p))
        return " ".join(spoken), False
    if letters.isupper() and 2 <= len(letters) <= 5:
        return spell_letters(letters), False
    if len(letters) == 1:
        return spell_letters(letters), False
    return transliterate(letters), True
