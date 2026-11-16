"""خلقِ هوشمند: «شخصیت را فارسی توصیف کن» ⇒ چند ایدهٔ دیداری (هر کدام یک سندِ کامل) ⇒ انتخاب ⇒ برگهٔ مدل.

* **قاعده‌محور (همیشه کار می‌کند):** واژه‌های فارسیِ توصیف (مربی، دختر، موی بلند، عینک، هدبند، دمبل، «قرمز»، «چیبی» ...) به ویژگی‌های کتابخانه نگاشت می‌شوند و چهار ایده با
  سبک‌ها و حال‌وهواهای مختلف ساخته می‌شود. رنگ‌های برندِ فروشگاه پیش‌فرض‌اند مگر رنگی را صریح بگویید.
* **هوش مصنوعی (اگر در دسترس باشد):** مدل فقط **ویژگی‌های کتابخانه** (از فهرستِ بسته) را پیشنهاد می‌دهد، نه تصویر؛ جوابش با ``doc.normalize`` پاک‌سازی می‌شود.
  متیس بی‌اعتبار (۴۰۲)، گرهٔ خاموش یا زمانِ آزمون ⇒ همان قاعده‌محور و یک جملهٔ فارسیِ دلیل.
* هیچ ایده‌ای شخصیتِ واقعی، چهرهٔ آدمِ واقعی یا شخصیتِ نام‌دارِ دیگران نیست؛ ویژگی‌ها فقط از کتابخانهٔ «اصل» می‌آیند.
"""
from __future__ import annotations

import re
from typing import Callable

from apps.mascot.engine import brand as B

from .engine import doc as D

COLOUR_WORDS: dict[str, str] = {
    "فیروزه": "#126f85", "سرمه": "#163f75", "آبی": "#2f7fd1", "قرمز": "#d94a3d", "سبز": "#2e9e5b", "زرد": "#e8a22b", "نارنجی": "#f26b21", "بنفش": "#8a4fd1",
    "صورتی": "#e0568f", "مشکی": "#1f2430", "سیاه": "#1f2430", "سفید": "#ffffff", "خاکستری": "#6b7280", "قهوه": "#8a5a2c", "طلایی": "#d6a21d",
}
ROLE_WORDS = {"coach": ("مربی", "ورزش", "باشگاه", "تمرین", "بدنساز"), "shopkeeper": ("فروشنده", "فروشگاه", "مغازه"), "cook": ("آشپز", "غذا", "سرآشپز"), "courier": ("پیک", "ارسال", "پست‌چی"),
              "advisor": ("مشاور", "راهنما", "کارشناس", "پشتیبان")}
HAIR_WORDS = [("موبلند", "long"), ("موکوتاه", "short"), ("موفر", "curly"), ("بدون مو", "none"), ("کچل", "none"), ("تراشیده", "buzz"), ("موی بلند", "long"), ("مو بلند", "long"), ("فر", "curly"), ("سیخ", "spikes"), ("دم‌اسبی", "ponytail"),
              ("دم اسبی", "ponytail"), ("گیس", "bun"), ("بافت", "bun"), ("موی کوتاه", "short"), ("مو کوتاه", "short"), ("باب", "bob")]
HAT_WORDS = [("کلاه آشپز", "chef"), ("بافتنی", "beanie"), ("هدبند", "headband"), ("کلاه لبه", "cap"), ("کپ", "cap"), ("کلاه بلند", "tophat"), ("کلاه", "cap")]
OUTFIT_WORDS = [("هودی", "hoodie"), ("رکابی", "tank"), ("گرمکن", "track"), ("ورزشی", "jersey"), ("کت", "suit"), ("رسمی", "suit"), ("تی‌شرت", "tshirt"), ("تیشرت", "tshirt")]
BOTTOM_WORDS = [("شلوارک", "shorts"), ("دامن", "skirt"), ("گرمکن", "joggers"), ("شلوار", "pants")]
PROP_WORDS = [("دمبل", "dumbbell"), ("هالتر", "barbell"), ("گوشی", "phone"), ("تبلت", "tablet"), ("کیف", "bag"), ("بلندگو", "megaphone"), ("نقشه", "map"), ("کلید", "key"),
              ("برگه", "clipboard"), ("تابه", "pan"), ("بسته", "box"), ("مشعل", "torch")]
BODY_WORDS = [("لاغر", "slim"), ("باریک", "slim"), ("عضل", "athletic"), ("ورزشکار", "athletic"), ("قوی", "athletic"), ("چاق", "round"), ("تپل", "round"), ("گرد", "round")]
STYLE_WORDS = [("چیبی", "chibi"), ("بامزه", "chibi"), ("کودکانه", "chibi"), ("عروسکی", "chibi"), ("استیکر", "sticker"), ("آدمک", "stick"), ("چوبی", "stick"), ("مینیمال", "flat"),
               ("ساده", "flat"), ("فلت", "flat")]
SKIN_WORDS = [("روشن", 0), ("گندمی", 2), ("برنزه", 3), ("تیره", 5), ("سبزه", 3)]

TITLES = ["ساده و مدرن", "بامزه (گردِ کوچک)", "استیکرِ خط‌دور", "ورزشی و پرانرژی"]


def parse_traits(description: str) -> dict:
    """توصیفِ فارسی ⇒ ویژگی‌های سند (فقط آن‌چه گفته شده). کلیدهای ``_colours``/``_expression``/``_role`` اضافه‌اند."""
    t = " ".join(str(description or "").replace("‌", "‌").split())
    out: dict = {}
    for words, key in ((HAIR_WORDS, "hair"), (HAT_WORDS, "hat"), (OUTFIT_WORDS, "outfit"), (BOTTOM_WORDS, "bottoms"), (PROP_WORDS, "prop"), (BODY_WORDS, "body"), (STYLE_WORDS, "style")):
        for w, v in words:
            if w in t:
                out[key] = v
                break
    if "عینک" in t:
        out["extra"] = "glasses"
    elif "کوله" in t:
        out["extra"] = "backpack"
    elif "پیش‌بند" in t or "پیشبند" in t:
        out["extra"] = "apron"
    elif "ماسک" in t:
        out["extra"] = "mask"
    if "شال" in t:
        out["neck"] = "scarf"
    elif "کراوات" in t:
        out["neck"] = "tie"
    elif "پاپیون" in t:
        out["neck"] = "bowtie"
    if "ریش" in t:
        out["beard"] = True
    if "کک" in t:
        out["freckles"] = True
    if re.search(r"دختر|خانم|زن\b|بانو", t):
        out.setdefault("hair", "long")
        out["blush"] = True
    if re.search(r"پسر|آقا|مرد\b", t):
        out.setdefault("hair", "short")
    if "چشم درشت" in t or "چشم‌درشت" in t:
        out["eye_style"] = "big"
    if "خندان" in t or "شاد" in t:
        out["eye_style"] = out.get("eye_style", "happy")
        out["_expression"] = "happy"
    for word, idx in SKIN_WORDS:
        if f"پوست {word}" in t or f"پوستِ {word}" in t:
            out["skin"] = D.SKIN_PRESETS[idx]
    for words, role in ROLE_WORDS.items():
        if any(w in t for w in role):
            out["_role"] = words
            break
    cols = []
    for w, hx in COLOUR_WORDS.items():
        m = re.search(rf"(\w+)?\s*{w}\w*", t)
        if m:
            cols.append((t.find(w), hx, w))
    cols.sort()
    out["_colours"] = [(w, hx) for _, hx, w in cols]
    return out


def _doc_for(role: str, brand: list[str], name: str, traits: dict, *, logo: bool, tweak: dict) -> dict:
    from . import services as S

    base = S.new_doc(role, brand, name, style=traits.get("style", "flat"), logo=logo)
    for k, v in traits.items():
        if not k.startswith("_") and k in D.DEFAULTS:
            base[k] = v
    return D.normalize({**base, **tweak}, name=name)


def _colour_targets(description: str) -> dict:
    """«لباس قرمز»، «موی مشکی» ... ⇒ {کلید: رنگ}."""
    t = str(description or "")
    out: dict = {}
    for word, hx in COLOUR_WORDS.items():
        for target, key in (("لباس", "top"), ("تی‌شرت", "top"), ("تیشرت", "top"), ("هودی", "top"), ("مو", "hair_colour"), ("شلوار", "bottom"), ("کفش", "shoes"), ("کلاه", "hat_colour"),
                            ("شال", "neck_colour"), ("هدبند", "hat_colour"), ("عینک", "extra_colour")):
            if re.search(rf"{target}\w*\s*(?:ی\s*)?{word}", t) or re.search(rf"{word}\w*\s+{target}", t):
                out[key] = hx
    return out


def rule_options(store, description: str, brand: list[str], *, logo: bool, n: int = 4) -> list[dict]:
    traits = parse_traits(description)
    role = traits.get("_role") or "coach"
    colours = _colour_targets(description)
    name = store.name
    variants = [
        {"style": "flat", "title": TITLES[0], "why": "رنگ‌های تخت و تمیز؛ برای پست و سایت مناسب است."},
        {"style": "chibi", "title": TITLES[1], "why": "سرِ بزرگ و چشمِ درشت؛ دوست‌داشتنی‌تر و برای استیکر و استوری عالی است.", "tweak": {"eye_style": "big", "blush": True}},
        {"style": "sticker", "title": TITLES[2], "why": "خطِ دورِ پررنگ و حاشیهٔ سفید؛ روی هر زمینه‌ای از پس‌زمینه جدا می‌شود.", "tweak": {"outfit": "hoodie" if role != "coach" else "jersey"}},
        {"style": "flat", "title": TITLES[3], "why": "یک حالتِ پرانرژی‌تر با لباس و وسیلهٔ دیگر.", "tweak": {"outfit": "track", "bottoms": "joggers", "prop": "dumbbell" if role == "coach" else "none", "body": "athletic"}},
    ]
    out = []
    for v in variants[:n]:
        tw = dict(v.get("tweak") or {})
        for k in list(tw):
            if k in traits and not k.startswith("_"):
                tw.pop(k)                                # چیزی که کاربر گفته از ایده‌ی پیش‌فرض مهم‌تر است
        style = traits.get("style") or v["style"]
        if "style" in traits and len(out) > 0:
            style = v["style"]                           # سبکِ گفته‌شده فقط در ایدهٔ اول، بقیه تنوع
        doc = _doc_for(role, brand, name, {**traits, "style": style}, logo=logo, tweak=tw)
        for k, hx in colours.items():
            doc[k] = hx
        out.append({"title": v["title"], "why": v["why"], "doc": D.normalize(doc, name=name), "source": "rule", "role": role})
    return out


# ───────────────────────────── هوش مصنوعی

SYSTEM = ("You help a brand design a cartoon mascot from a short Persian description. Reply with ONE JSON object only. "
          "You may ONLY choose values from the given option lists (never invent new values, never describe a real person or a famous character). "
          "Give 4 different concepts. Colours are #rrggbb. Titles and reasons are short natural Persian.")


def _schema() -> str:
    opts = {k: list(v) for k, v in D.CHOICES.items() if k not in ("logo",)}
    return ('{"concepts": [{"title": str, "why": str, "traits": {' + ", ".join(f'"{k}": one of {v}' for k, v in opts.items()) + ', "skin": "#rrggbb", "hair_colour": "#rrggbb", "top": "#rrggbb", "bottom": "#rrggbb", '
            '"blush": bool, "freckles": bool, "beard": bool}}]}')


def build_prompt(store, description: str, brand: list[str]) -> str:
    return (f"Brand: {store.name}\nBusiness: {getattr(store, 'business_type', '')}\nBrand colours: {', '.join(brand) or 'none'}\nPersian description of the character:\n{description.strip()[:600]}\n"
            f"Return JSON of this shape: {_schema()}")


def _valid(d) -> tuple[bool, list[str]]:
    ok = isinstance(d, dict) and isinstance(d.get("concepts"), list) and len(d["concepts"]) >= 1
    return ok, [] if ok else ["concepts خالی است"]


def default_ask(store, prompt: str):
    from apps.ideabank import ai as IA
    from django.conf import settings

    if getattr(settings, "IS_TEST", False):
        raise IA.AIUnavailable("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")

    def go():
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from apps.photoedit import translate
        from services.ai import gateway
        from services.ai.priority import TEXT
        from services.ai.router import TASK_REASONING, models_for

        provider = gateway.text_provider(store, kind=TEXT)
        parsed, _row = recorded_json_call(store=store, task_type=AIRequest.TaskType.REASONING, prompt_id="brandchar_concepts", prompt_version="1", provider=provider,
                                          models=models_for(TASK_REASONING), prompt=prompt, system=SYSTEM, validate=_valid, validation_message="ایده‌های شخصیت ناقص بود")
        return parsed, (translate._describe(provider) or {})

    try:
        return IA.run_bounded(("concepts", getattr(store, "pk", 0) or 0), go)
    except IA.AIUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IA.AIUnavailable(IA.reason_text(exc)) from exc


def generate(store, description: str, *, logo: bool = False, n: int = 4, use_ai: bool = True, ask: Callable | None = None) -> dict:
    """⇒ {options[{title، why، doc، source}]، source: ai|rule، note}. همیشه دست‌کم یک ایده برمی‌گرداند."""
    from . import services as S

    description = " ".join(str(description or "").split())[:600]
    brand = S.brand_colours(store)
    rule = rule_options(store, description, brand, logo=logo, n=n)
    note = ""
    if not use_ai:
        return {"options": rule, "source": "rule", "note": "ساخته‌شده با قاعده‌های فارسی (بدونِ هوش مصنوعی)."}
    try:
        prompt = build_prompt(store, description, brand)
        parsed = ask(store, prompt) if ask is not None else default_ask(store, prompt)[0]
    except Exception as exc:  # noqa: BLE001
        reason = getattr(exc, "args", [""])[0] or str(exc) or exc.__class__.__name__
        return {"options": rule, "source": "rule", "note": f"هوش مصنوعی در دسترس نبود ({str(reason)[:200]}). ایده‌ها با قاعده‌های فارسی ساخته شد؛ بعداً دوباره امتحان کنید."}
    options = []
    base_traits = parse_traits(description)
    role = base_traits.get("_role") or "coach"
    for item in (parsed.get("concepts") or [])[:n] if isinstance(parsed, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get("traits"), dict):
            continue
        traits = {k: v for k, v in item["traits"].items() if k in D.DEFAULTS and k != "layers"}
        doc = _doc_for(role, brand, store.name, {**base_traits, **{k: v for k, v in traits.items() if k in D.CHOICES}}, logo=logo, tweak={k: v for k, v in traits.items() if k in D.COLOUR_KEYS or k in D.BOOLS})
        options.append({"title": str(item.get("title") or "ایده")[:60], "why": str(item.get("why") or "")[:200], "doc": doc, "source": "ai", "role": role})
    if not options:
        return {"options": rule, "source": "rule", "note": "پاسخِ مدل قابلِ‌استفاده نبود؛ ایده‌ها با قاعده‌های فارسی ساخته شد."}
    for r in rule:                                     # اگر مدل کمتر از n ایده داد، با ایده‌های قاعده‌محور کامل شود
        if len(options) >= n:
            break
        options.append(r)
    return {"options": options[:n], "source": "ai", "note": note}
