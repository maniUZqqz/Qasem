"""شخصیتِ برند، نیمهٔ «گفتار»: نام، کهن‌الگو (۱۲ تا)، لحن (۵ لغزنده)، ارزش‌ها، واژه‌های بگو/نگو، شعارها، سیاستِ ایموجی، سلام و خداحافظی، جمله‌های نمونه و صدا.

دو چیز در این‌جا هست:
  * ``normalize`` — دادهٔ ورودی را کران‌دار و امن می‌کند (هر فهرست سقف دارد؛ جمله‌های «ادعادار» با نگهبانِ ماسکوت برداشته می‌شود).
  * ``draft`` — پیش‌نویسِ **قاعده‌محور** از پروفایلِ فروشگاه و (برای فروشگاه‌هایی که ``docs/<برند>/brand-facts-fa.md`` دارند) از همان واقعیت‌های تأییدشده.
    هیچ قیمت، آمار، نتیجه یا نظرِ مشتری ساخته نمی‌شود؛ هر واقعیت منبع دارد. جادوگرِ هوش مصنوعی (``persona_ai``) روی همین پایه کار می‌کند و اگر در دسترس نبود همین پیش‌نویس می‌ماند.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from apps.mascot.engine import copy_guard

# ------------------------------------------------------------------ کهن‌الگوها

#: کلید ⇒ نام و توضیحِ فارسی + لحنِ پیشنهادی [رسمی، شوخ، پرانرژی، مفصل، صمیمی] (۰..۱۰۰) + ارزش‌ها و واژه‌های پیشنهادی (همه عمومی و بی‌ادعا)
ARCHETYPES: dict[str, dict] = {
    "innocent": {"fa": "ساده‌دل", "en": "Innocent", "about": "خوش‌بین، صادق و ساده؛ دنیا را جای خوبی می‌بیند و چیزِ پیچیده نمی‌گوید.",
                 "tone": [30, 35, 50, 25, 80], "values": ["صداقت", "سادگی", "امید"], "do": ["ساده", "روشن", "شروعِ تازه"], "dont": ["پیچیده", "ترس"]},
    "everyman": {"fa": "رفیق (آدمِ معمولی)", "en": "Everyman", "about": "همراهِ همه؛ بی‌ادا و همدل، مثلِ یک همکار یا دوستِ خوب حرف می‌زند.",
                 "tone": [25, 40, 45, 30, 85], "values": ["همدلی", "بی‌تکلفی", "هم‌دوشی"], "do": ["با هم", "راحت", "ساده"], "dont": ["تحکم", "تکبر"]},
    "hero": {"fa": "قهرمان", "en": "Hero", "about": "جسور و پشتکاردار؛ مخاطب را به برداشتنِ قدمِ بعدی تشویق می‌کند.",
             "tone": [35, 20, 80, 25, 60], "values": ["پشتکار", "شجاعت", "انضباط"], "do": ["بزن بریم", "قدمِ بعدی", "ادامه بده"], "dont": ["بهانه", "تسلیم"]},
    "caregiver": {"fa": "مراقب", "en": "Caregiver", "about": "مهربان و پشتیبان؛ اول گوش می‌دهد و بعد راه نشان می‌دهد.",
                  "tone": [35, 20, 35, 40, 95], "values": ["مراقبت", "اعتماد", "صبوری"], "do": ["کنارتم", "قدم‌به‌قدم", "اشکالی ندارد"], "dont": ["سرزنش", "عجله"]},
    "explorer": {"fa": "کاشف", "en": "Explorer", "about": "کنجکاو و مستقل؛ مسیرهای تازه را امتحان می‌کند و می‌گوید چه پیدا کرده.",
                 "tone": [30, 40, 70, 35, 65], "values": ["کنجکاوی", "آزادی", "تجربه"], "do": ["امتحان کن", "کشف", "مسیرِ تازه"], "dont": ["همیشه همین", "تکراری"]},
    "rebel": {"fa": "یاغی", "en": "Outlaw", "about": "قاعده‌شکن و رک؛ کلیشه را کنار می‌گذارد ولی بی‌احترامی نمی‌کند.",
              "tone": [15, 60, 80, 15, 50], "values": ["جسارت", "اصالت", "تغییر"], "do": ["جور دیگر", "رک بگم", "کلیشه نه"], "dont": ["مثلِ همه", "محافظه‌کار"]},
    "magician": {"fa": "جادوگر (تحول‌ساز)", "en": "Magician", "about": "تحول‌ساز؛ چیزِ سخت را ساده نشان می‌دهد، بی‌آن‌که وعدهٔ نتیجه بدهد.",
                 "tone": [40, 30, 60, 30, 65], "values": ["نوآوری", "سادگیِ پشتِ پیچیدگی", "الهام"], "do": ["ببین چه ساده", "ایدهٔ تازه"], "dont": ["معجزه", "تضمین"]},
    "lover": {"fa": "دلبر (صمیمی)", "en": "Lover", "about": "گرم و نزدیک؛ با احساس و ظرافت حرف می‌زند و مخاطب را خاص می‌بیند.",
              "tone": [30, 35, 45, 40, 95], "values": ["صمیمیت", "ظرافت", "توجه"], "do": ["دوستت دارم", "برایت", "با دقت"], "dont": ["سرد", "رسمیِ خشک"]},
    "jester": {"fa": "شوخ‌طبع", "en": "Jester", "about": "بامزه و بازیگوش؛ حالِ مخاطب را خوب می‌کند، ولی مسخره‌اش نمی‌کند.",
               "tone": [10, 90, 85, 20, 85], "values": ["شادی", "بازیگوشی", "سبک‌بالی"], "do": ["خنده", "باحال", "بازی"], "dont": ["تمسخر", "طعنهٔ تلخ"]},
    "sage": {"fa": "حکیم (راهنمای دانا)", "en": "Sage", "about": "دانا و راهنما؛ روشن توضیح می‌دهد، منبع می‌گوید و تصمیمِ نهایی را به خودِ مخاطب می‌سپارد.",
             "tone": [45, 20, 40, 35, 70], "values": ["دانایی", "شفافیت", "دقت"], "do": ["توضیح", "نکته", "راهنما"], "dont": ["ادعای بی‌منبع", "مطلق‌گویی"]},
    "ruler": {"fa": "فرمانروا (رهبر)", "en": "Ruler", "about": "مطمئن و منظم؛ کنترل و ثبات می‌دهد و صریح راهنمایی می‌کند.",
              "tone": [75, 10, 45, 40, 40], "values": ["نظم", "اعتبار", "مسئولیت"], "do": ["مسئولیت", "برنامه", "نظم"], "dont": ["شلختگی", "تزلزل"]},
    "creator": {"fa": "خلاق (سازنده)", "en": "Creator", "about": "ایده‌پرداز و سازنده؛ از ساختنِ چیزِ تازه ذوق می‌کند و مخاطب را به ساختن دعوت می‌کند.",
                "tone": [35, 55, 65, 40, 70], "values": ["خلاقیت", "ساختن", "اصالت"], "do": ["بساز", "ایده", "طراحی"], "dont": ["کپی", "قالبیِ خشک"]},
}
ARCHETYPE_ORDER = tuple(ARCHETYPES)

#: لغزنده‌ها: کلید ⇒ (فارسیِ ۰، فارسیِ ۱۰۰). مقدارِ ۵۰ = وسط.
TONE_SLIDERS: dict[str, tuple[str, str, str]] = {
    "formality": ("رسمیت", "محاوره‌ای و راحت", "رسمی و مؤدب"),
    "humor": ("شوخ‌طبعی", "جدی", "بامزه"),
    "energy": ("انرژی", "آرام", "پرانرژی"),
    "detail": ("تفصیل", "کوتاه و فشرده", "مفصل و توضیحی"),
    "warmth": ("گرمی", "بی‌طرف", "صمیمی و گرم"),
}
TONE_KEYS = tuple(TONE_SLIDERS)

EMOJI_POLICIES = {"none": "بدونِ ایموجی", "rare": "کم (حداکثر یکی در پیام)", "moderate": "متوسط (۱ تا ۳ تا)", "lots": "پرایموجی"}
ADDRESS = {"to": "«تو» (صمیمی)", "shoma": "«شما» (محترمانه)"}

LIMITS = {"name": 60, "tagline": 120, "summary": 600, "values": 6, "value_len": 60, "words": 14, "word_len": 40, "catch": 8, "catch_len": 100, "greeting": 160, "signoff": 160,
          "samples": 8, "sample_len": 200, "audience": 160, "situation": 40}
SITUATIONS = ("greeting", "explain", "reply_question", "invite", "thanks", "apology", "signoff", "reminder")
SITUATION_FA = {"greeting": "سلام و خوشامد", "explain": "توضیحِ یک نکته", "reply_question": "پاسخ به پرسش", "invite": "دعوت به قدمِ بعدی", "thanks": "تشکر",
                "apology": "عذرخواهی", "signoff": "خداحافظی", "reminder": "یادآوری"}

DEFAULT_VOICE = {"voice_id": "", "speed": 1.0, "gender": ""}


def _s(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _clean_list(v: Any, max_items: int, max_len: int, *, guard: bool = False) -> list[str]:
    out: list[str] = []
    for x in (v if isinstance(v, (list, tuple)) else []):
        t = _s(x, max_len)
        if not t or t in out:
            continue
        if guard and [f for f in copy_guard.check_text(t) if f["code"] in copy_guard.BLOCKING]:
            continue                                         # شعار و جمله‌ی «ادعادار» نمی‌ماند
        out.append(t)
        if len(out) >= max_items:
            break
    return out


def empty() -> dict:
    return normalize({})


def normalize(data: dict | None, *, guard: bool = True) -> dict:
    """سندِ شخصیتِ گفتار: کلیدهای ناشناخته می‌افتند؛ فهرست‌ها سقف دارند؛ شعار و جملهٔ نمونه از نگهبانِ ادعا می‌گذرد (``guard=False`` فقط برای آزمون)."""
    d = dict(data or {})
    arch = d.get("archetype") if d.get("archetype") in ARCHETYPES else "everyman"
    sec = d.get("secondary") if d.get("secondary") in ARCHETYPES and d.get("secondary") != arch else ""
    tone_in = d.get("tone") if isinstance(d.get("tone"), dict) else {}
    base = ARCHETYPES[arch]["tone"]
    tone = {}
    for i, k in enumerate(TONE_KEYS):
        try:
            tone[k] = max(0, min(100, int(round(float(tone_in.get(k, base[i]))))))
        except (TypeError, ValueError):
            tone[k] = base[i]
    samples = []
    for row in (d.get("sample_lines") or [])[:LIMITS["samples"]]:
        if not isinstance(row, dict):
            continue
        text = _s(row.get("text"), LIMITS["sample_len"])
        if not text or (guard and [f for f in copy_guard.check_text(text) if f["code"] in copy_guard.BLOCKING]):
            continue
        sit = row.get("situation") if row.get("situation") in SITUATIONS else "explain"
        samples.append({"situation": sit, "text": text})
    voice_in = d.get("voice") if isinstance(d.get("voice"), dict) else {}
    try:
        speed = max(0.6, min(1.6, float(voice_in.get("speed", 1.0))))
    except (TypeError, ValueError):
        speed = 1.0
    greeting = _s(d.get("greeting"), LIMITS["greeting"])
    signoff = _s(d.get("signoff"), LIMITS["signoff"])
    if guard:
        if copy_guard.check_text(greeting) and [f for f in copy_guard.check_text(greeting) if f["code"] in copy_guard.BLOCKING]:
            greeting = ""
        if copy_guard.check_text(signoff) and [f for f in copy_guard.check_text(signoff) if f["code"] in copy_guard.BLOCKING]:
            signoff = ""
    return {
        "name": _s(d.get("name"), LIMITS["name"]), "archetype": arch, "secondary": sec, "tagline": _s(d.get("tagline"), LIMITS["tagline"]),
        "summary": _s(d.get("summary"), LIMITS["summary"]), "audience": _s(d.get("audience"), LIMITS["audience"]), "tone": tone,
        "values": _clean_list(d.get("values"), LIMITS["values"], LIMITS["value_len"]), "do_words": _clean_list(d.get("do_words"), LIMITS["words"], LIMITS["word_len"]),
        "dont_words": _clean_list(d.get("dont_words"), LIMITS["words"], LIMITS["word_len"]),
        "catchphrases": _clean_list(d.get("catchphrases"), LIMITS["catch"], LIMITS["catch_len"], guard=guard),
        "emoji": d.get("emoji") if d.get("emoji") in EMOJI_POLICIES else "rare", "address": d.get("address") if d.get("address") in ADDRESS else "to",
        "greeting": greeting, "signoff": signoff, "sample_lines": samples,
        "voice": {"voice_id": _s(voice_in.get("voice_id"), 60), "speed": round(speed, 2), "gender": voice_in.get("gender") if voice_in.get("gender") in ("male", "female") else ""},
    }


def filled_score(p: dict) -> dict:
    """«چقدر کامل است؟» برای صفحهٔ نمای کلی: {done, total, missing[]}."""
    checks = [("name", "نام"), ("summary", "توصیفِ کوتاه"), ("values", "ارزش‌ها"), ("do_words", "واژه‌های «بگو»"), ("dont_words", "واژه‌های «نگو»"),
              ("catchphrases", "شعار یا جملهٔ امضا"), ("greeting", "سلام"), ("signoff", "خداحافظی"), ("sample_lines", "جمله‌های نمونه")]
    missing = [label for key, label in checks if not p.get(key)]
    return {"done": len(checks) - len(missing), "total": len(checks), "missing": missing}


# ------------------------------------------------------------------ لحن به کلمه

def tone_words(tone: dict) -> list[str]:
    """لغزنده‌ها ⇒ چند عبارتِ فارسیِ کوتاه (فقط آن‌هایی که از وسط دورند)."""
    out = []
    for k, (label, lo, hi) in TONE_SLIDERS.items():
        v = int(tone.get(k, 50))
        if v >= 68:
            out.append(hi)
        elif v <= 32:
            out.append(lo)
    return out


# ------------------------------------------------------------------ واقعیت‌های برند (فقط از سند)

#: برندهایی که مستنداتِ واقعیتشان در مخزن است. کلید = بخشی از نامِ فروشگاه. هر ردیف: (متن، منبع). متن‌ها **عیناً** از سند آمده‌اند و آزمون این را می‌سنجد.
BRAND_FACT_FILES = {"چغر": "docs/chagher/brand-facts-fa.md"}

CHAGHER = {
    "name": "مربیِ چغر",
    "archetype": "sage", "secondary": "everyman",
    "tagline": "با چغر چغر تر شو",
    "summary": "همکارِ مربی‌ها: صمیمی ولی حرفه‌ای، کوتاه و بی‌اغراق. پیش‌نویسِ برنامه می‌دهد و تصمیمِ نهایی را به مربی می‌سپارد.",
    "audience": "مربی‌های باشگاه و مربی‌های شخصی؛ ورزشکارِ شخصی",
    "tone": {"formality": 40, "humor": 25, "energy": 55, "detail": 25, "warmth": 75},
    "values": ["شفافیت: پیش‌نویس را پیش‌نویس بگو", "تصمیمِ نهایی با مربی است", "کوتاه و بی‌اغراق", "صمیمی ولی حرفه‌ای"],
    "do_words": ["پیش‌نویس", "مربی", "برنامهٔ ورزشی", "برنامهٔ غذایی", "در کمتر از یک دقیقه", "با چغر چغر تر شو"],
    "dont_words": ["تضمین", "معجزه", "جایگزینِ مربی", "درمان", "بهترین", "نظرِ مشتریِ ساختگی"],
    "catchphrases": ["با چغر چغر تر شو"],
    "emoji": "rare", "address": "to",
    "greeting": "سلام! من همکارِ مربی‌هام؛ بگو چه برنامه‌ای می‌خواهی.",
    "signoff": "پیش‌نویس آماده است؛ تصمیمِ نهایی با مربی. با چغر چغر تر شو.",
    "sample_lines": [
        {"situation": "greeting", "text": "سلام! بگو برنامهٔ چه کسی را پیش‌نویس کنیم؟"},
        {"situation": "explain", "text": "پیش‌نویسِ برنامه در کمتر از یک دقیقه آماده می‌شود؛ بعدش مربی ویرایشش می‌کند."},
        {"situation": "explain", "text": "من دستیارِ هوش مصنوعیِ مربی‌ها هستم، نه جایگزینِ مربی."},
        {"situation": "invite", "text": "قدمِ بعدی؟ پیش‌نویس را ببین و برای مربی بفرست."},
        {"situation": "reply_question", "text": "این را مربی تأیید می‌کند؛ من فقط پیش‌نویس می‌دهم."},
        {"situation": "signoff", "text": "با چغر چغر تر شو."},
    ],
    "sources": [
        {"fact": "شعار «با چغر چغر تر شو»", "source": "brand-facts-fa.md §۱"},
        {"fact": "دستیارِ هوش مصنوعیِ مربی‌ها؛ برنامه را پیش‌نویس می‌کند؛ جایگزینِ مربی نیست", "source": "brand-facts-fa.md §۱"},
        {"fact": "پیش‌نویس در کمتر از یک دقیقه", "source": "brand-facts-fa.md §۲، §۴"},
        {"fact": "لحن: صمیمی ولی حرفه‌ای، کوتاه و بدونِ اغراق؛ مثلِ همکارِ مربی", "source": "brand-facts-fa.md §۴"},
        {"fact": "«پیش‌نویس» را همیشه بگو؛ تصمیمِ نهایی با مربی است", "source": "brand-facts-fa.md §۴"},
        {"fact": "بدونِ وعدهٔ پزشکی، تضمینِ نتیجه، «جایگزینِ مربی»، نظرِ مشتریِ ساختگی", "source": "brand-facts-fa.md §۴"},
        {"fact": "مخاطب: مربی‌های باشگاه و مربی‌های شخصی (اصلی)؛ ورزشکارِ شخصی (فرعی)", "source": "brand-facts-fa.md §۱"},
    ],
    "colours": ["#126F85", "#163F75"],
}


def facts_for(store_name: str) -> dict | None:
    name = (store_name or "").strip()
    if name and "چغر" in name:
        return CHAGHER
    return None


def facts_text(root: Path | None = None) -> str:
    """متنِ کاملِ سندِ واقعیت‌های چغر (برای آزمونِ «هیچ چیزِ ساختگی»)؛ خالی اگر فایل در دسترس نبود."""
    candidates = []
    if root is not None:
        candidates.append(root / BRAND_FACT_FILES["چغر"])
    here = Path(__file__).resolve()
    for up in (3, 4):
        try:
            candidates.append(here.parents[up] / BRAND_FACT_FILES["چغر"])
        except IndexError:
            pass
    for p in candidates:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


# ------------------------------------------------------------------ پیش‌نویسِ قاعده‌محور

#: کلیدواژه (در نوعِ کسب‌وکار/توضیح/لحن) ⇒ کهن‌الگو؛ اولین تطبیقِ بیشترین وزن
_ARCH_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sage", ("مربی", "آموزش", "مشاوره", "دانش", "کتاب", "دوره", "coach", "teach", "consult")),
    ("hero", ("ورزش", "باشگاه", "تناسب", "بدنسازی", "gym", "fitness", "sport")),
    ("caregiver", ("سلامت", "مراقبت", "کودک", "پزشک", "دارو", "طب", "care", "health")),
    ("creator", ("طراحی", "هنر", "صنایع", "دست‌ساز", "دستساز", "گرافیک", "design", "craft")),
    ("explorer", ("سفر", "گردشگری", "کوه", "طبیعت", "travel", "outdoor")),
    ("lover", ("زیبایی", "آرایش", "عطر", "گل", "هدیه", "beauty", "gift")),
    ("jester", ("سرگرمی", "بازی", "کافه", "game", "fun")),
    ("ruler", ("حقوقی", "مالی", "بانک", "بیمه", "خودرو", "لوکس", "legal", "finance")),
    ("magician", ("فناوری", "نرم‌افزار", "اپ", "هوش مصنوعی", "tech", "software", "ai")),
]


def pick_archetype(*texts: str) -> tuple[str, str]:
    blob = " ".join(t for t in texts if t).lower()
    scores: dict[str, int] = {}
    for arch, words in _ARCH_KEYWORDS:
        scores[arch] = sum(1 for w in words if w in blob)
    ranked = [a for a, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s > 0]
    first = ranked[0] if ranked else "everyman"
    second = ranked[1] if len(ranked) > 1 else ("everyman" if first != "everyman" else "")
    return first, second


def draft(store: Any) -> dict:
    """پیش‌نویسِ شخصیتِ گفتار برای یک فروشگاه — بدونِ هوش مصنوعی. ⇒ {persona, sources[], notes[], origin}. چیزی از خود اضافه نمی‌شود: فقط نام، توضیح و لحنِ ثبت‌شده
    (یا واقعیت‌های تأییدشدهٔ سند) + عبارت‌های عمومیِ بی‌ادعا از کهن‌الگو."""
    facts = facts_for(getattr(store, "name", ""))
    prof = getattr(store, "profile", None) if hasattr(store, "profile") else None
    notes: list[str] = []
    if facts is not None:
        p = normalize({k: facts[k] for k in facts if k not in ("sources", "colours")})
        notes.append("پیش‌نویس فقط از واقعیت‌های تأییدشدهٔ سندِ برند ساخته شد؛ هر جمله منبع دارد. اگر چیزی را قبول ندارید، ویرایشش کنید.")
        return {"persona": p, "sources": list(facts["sources"]), "notes": notes, "origin": "facts"}
    name = _s(getattr(store, "name", ""), 50)
    biz = _s(getattr(store, "business_type", ""), 100)
    desc = _s(getattr(store, "description", ""), 400)
    aud = _s(getattr(store, "target_audience", ""), 160)
    tone_txt = _s(getattr(prof, "tone", "") or getattr(prof, "brand_voice", "") or "", 100) if prof else ""
    arch, sec = pick_archetype(biz, desc, tone_txt, name)
    a = ARCHETYPES[arch]
    sources = []
    if name:
        sources.append({"fact": f"نامِ فروشگاه: {name}", "source": "پروفایلِ فروشگاه"})
    if biz:
        sources.append({"fact": f"نوعِ کسب‌وکار: {biz}", "source": "پروفایلِ فروشگاه"})
    if aud:
        sources.append({"fact": f"مخاطب: {aud}", "source": "پروفایلِ فروشگاه"})
    if tone_txt:
        sources.append({"fact": f"لحنِ ثبت‌شده: {tone_txt}", "source": "پروفایلِ برند"})
    tone = list(a["tone"])
    low = tone_txt.lower()
    for kw, idx, delta in (("رسمی", 0, 30), ("صمیمی", 0, -25), ("شوخ", 1, 35), ("جدی", 1, -25), ("پرانرژی", 2, 25), ("آرام", 2, -25), ("کوتاه", 3, -20), ("مفصل", 3, 25)):
        if kw in low:
            tone[idx] = max(0, min(100, tone[idx] + delta))
    nm = f"شخصیتِ {name}" if name else "شخصیتِ برند"
    summary = f"{a['about']}" + (f" برای {aud}." if aud else "")
    p = normalize({
        "name": nm, "archetype": arch, "secondary": sec, "tagline": "", "summary": summary, "audience": aud, "tone": dict(zip(TONE_KEYS, tone)),
        "values": a["values"], "do_words": a["do"], "dont_words": a["dont"] + ["تضمین", "بهترین"], "catchphrases": [], "emoji": "rare", "address": "to",
        "greeting": f"سلام! من {nm.replace('شخصیتِ ', '')} هستم؛ بگو چه کمکی از دستم برمی‌آید؟" if name else "سلام! چه کمکی از دستم برمی‌آید؟",
        "signoff": "هر وقت خواستی، همین‌جا هستم.",
        "sample_lines": [{"situation": "greeting", "text": "سلام! بگو چه کمکی از دستم برمی‌آید؟"}, {"situation": "invite", "text": "قدمِ بعدی را با هم برمی‌داریم؟"},
                         {"situation": "signoff", "text": "هر وقت خواستی، همین‌جا هستم."}],
    })
    notes.append("این پیش‌نویسِ قاعده‌محور است: فقط از نام، نوعِ کسب‌وکار، مخاطب و لحنِ ثبت‌شدهٔ شما و عبارت‌های عمومیِ کهن‌الگو ساخته شد. شعار و واقعیتِ برند را خودتان بنویسید.")
    if not (biz or desc or tone_txt):
        notes.append("پروفایلِ فروشگاه تقریباً خالی است؛ هرچه آن‌جا کامل‌تر باشد، پیش‌نویس دقیق‌تر می‌شود.")
    return {"persona": p, "sources": sources, "notes": notes, "origin": "rule"}


_NUM = re.compile(r"\d")


def diff_keys(a: dict, b: dict) -> list[str]:
    return [k for k in b if a.get(k) != b.get(k)]
