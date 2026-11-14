"""ایده‌پردازیِ تامنیل: «موضوع یا محصول» ⇒ عنوان‌های قلاب‌دار + مفهومِ تصویری + سبکِ پیشنهادی + دستورِ پس‌زمینه.

دو مسیر، همیشه به این ترتیب:

1. **هوش مصنوعی** از مسیریابِ پروژه (لوکال روی سرورِ پردازش ⇄ متیس، به ترتیبِ تنظیمِ مالک). خروجی JSON است و سخت‌گیرانه وارسی می‌شود
   (سبکِ ناشناخته، عددِ قیمت/درصدِ ساختگی، متنِ بلند، دستورِ انگلیسیِ خراب ⇒ دور ریخته می‌شود).
2. **فرمول‌های آمادهٔ فارسی** (``hooks.rule_ideas``) وقتی هوش مصنوعی در دسترس نیست (متیس ۴۰۲، گره خاموش، سیاستِ داده…) یا ایده‌های معتبرِ
   کافی نیاورد. در این حالت پیام می‌گوید چرا؛ هر بار که هوش مصنوعی برگردد همان مسیرِ اول دوباره امتحان می‌شود.

هیچ مسیری عددِ آماری، قیمت یا ادعای تأییدنشده نمی‌سازد (جزئیات: ``hooks``).
"""
from __future__ import annotations

import json
import logging
import re

from . import archetypes, hooks, palette, phrases, typo
from .render import CONTENT_LIMITS
from .styles import STYLES

logger = logging.getLogger(__name__)

AI_TIMEOUT = 150
MAX_IDEAS = 8
#: واژه‌هایی که بدونِ حضور در متنِ کاربر/محصول نباید در عنوان بیایند (ادعای ساختگی)
RISKY = ("درصد", "تومان", "ریال", "تخفیف", "رایگان", "تضمین", "٪", "%", "$", "€")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


class AIUnavailable(RuntimeError):
    """هوش مصنوعی جواب نداد؛ متنِ فارسی برای کاربر."""


# ───────────────────────────── واقعیت‌های فروشگاه / محصول

def facts_of(store, product=None) -> dict:
    prof = getattr(store, "profile", None)
    f = {
        "store": store.name, "business": store.business_type or "", "about": (store.description or "")[:240],
        "audience": store.target_audience or "", "tone": (getattr(prof, "tone", "") or getattr(prof, "brand_voice", "") or "") if prof else "",
    }
    if product is not None:
        f["product"] = {"name": product.name, "short": (product.short_description or product.description or "")[:240], "brand": product.brand or ""}
    return f


def price_text(product) -> str:
    """قیمتِ واقعیِ محصول به‌صورتِ «۱٬۲۵۰٬۰۰۰ تومان» (فقط اگر قیمت دارد)."""
    from services.imaging.text_overlay import format_price_fa

    try:
        return format_price_fa(product.price, product.currency) if product is not None and product.price else ""
    except Exception:  # noqa: BLE001
        return ""


# ───────────────────────────── پرسش از هوش مصنوعی

def _prompt(topic: str, fmt_title: str, styles: list[str], facts: dict, count: int, number, other: str) -> str:
    style_lines = "\n".join(f"- {k}: {STYLES[k].title} — {STYLES[k].short}" for k in styles)
    src = json.dumps({k: v for k, v in facts.items() if v}, ensure_ascii=False)
    return (
        "You are a senior Persian-language thumbnail and cover designer / copywriter for a small online business. "
        "The owner needs thumbnail ideas: short, curiosity-driven Persian hook titles plus a visual concept and the best layout style.\n\n"
        f"Topic (Persian): «{topic}»\n"
        f"Platform: {fmt_title}\n"
        f"Known facts about the business (use ONLY these; do not invent anything): {src}\n"
        + (f"The owner wants a list-style number: {number}\n" if number else "")
        + (f"Compare against: «{other}»\n" if other else "")
        + f"\nAvailable layout styles (key — meaning):\n{style_lines}\n\n"
        "Rules: every title is natural Persian, 2 to 7 words, no emoji, Persian digits. NEVER invent prices, discounts, percentages, statistics, "
        "guarantees, results, testimonials or claims that are not in the facts above; if the topic has none, write curiosity or benefit-free hooks. "
        "Mark the single most important word of each title with asterisks like *word*. Use a different style for each idea when possible. "
        "'bg_prompt_en' is an ENGLISH image-generation prompt for the background only (no text, no people, no logos) that fits the style and topic. "
        "'concept' is one Persian sentence describing the visual.\n"
        f"Give exactly {count} ideas. Reply with ONLY this JSON: "
        '{"ideas": [{"title": "", "subtitle": "", "kicker": "", "number": "", "badge": "", "style": "<one of the keys>", "concept": "", "bg_prompt_en": "", "mood": ""}]}'
    )


def _default_ask(store, prompt: str) -> tuple[dict, dict]:
    """⇒ (JSON، {via, model, label}). هر شکستی ⇒ AIUnavailable(دلیلِ فارسی). زیرِ آزمون هیچ‌وقت شبکه صدا نمی‌زند."""
    from django.conf import settings

    from apps.photoedit import translate

    if getattr(settings, "IS_TEST", False):
        raise AIUnavailable("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from services.ai import gateway
        from services.ai.priority import TEXT
        from services.ai.router import TASK_REASONING, models_for

        provider = gateway.text_provider(store, kind=TEXT)
        parsed, _row = recorded_json_call(
            store=store, task_type=AIRequest.TaskType.REASONING, prompt_id="thumb_ideas", prompt_version="1", provider=provider,
            models=models_for(TASK_REASONING), prompt=prompt, system="You output strict JSON only.",
            validate=lambda d: (isinstance(d, dict) and isinstance(d.get("ideas"), list) and bool(d["ideas"]), ["ideas خالی است"]),
            validation_message="ایده‌ها ناقص بود")
        info = translate._describe(provider)
    except Exception as exc:  # noqa: BLE001 — متیسِ بی‌اعتبار (۴۰۲)، گرهٔ خاموش، سیاستِ داده، پیکربندی…
        raise AIUnavailable(hooks.reason_from_exception(exc, translate.explain(exc))) from exc
    return parsed, (info or {})


# ───────────────────────────── وارسیِ جوابِ هوش مصنوعی

def _fa(text) -> str:
    return typo.to_fa_digits(typo.clean(text))


def _risky(text: str, source: str) -> bool:
    return any(w in text and w not in source for w in RISKY)


def clean_ai_ideas(parsed, *, fmt: str, source_text: str) -> list[dict]:
    """JSON ِ خام ⇒ ایده‌های وارسی‌شده (ایده‌ای که عنوانش بد است دور ریخته می‌شود؛ فیلدِ بدِ دیگر خالی می‌شود)."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ideas"), list):
        return []
    pref = hooks.preferred_styles(fmt)
    out: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(parsed["ideas"][:MAX_IDEAS * 2]):
        if not isinstance(raw, dict):
            continue
        title = _fa(raw.get("title"))
        title = _EMOJI.sub("", title).strip()
        words = typo.plain(title).split()
        if not (2 <= len(words) <= 10) or len(typo.plain(title)) > 70 or _risky(title, source_text):
            continue
        key = typo.plain(title)
        if key in seen:
            continue
        seen.add(key)
        style = raw.get("style") if raw.get("style") in STYLES else pref[i % len(pref)]

        def field(name, limit):
            v = _EMOJI.sub("", _fa(raw.get(name))).strip()
            if len(v) > limit:                                   # سقفِ حرف: روی مرزِ واژه، نه وسطِ کلمه (و روی واژهٔ ناتمام هم نه)
                v = phrases.clip(v, 999, limit)[0]
            return "" if _risky(v, source_text) else v

        number = re.sub(r"\D", "", typo.clean(raw.get("number")).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))[:2]
        badge = field("badge", CONTENT_LIMITS["badge"])
        if re.search(r"[0-9۰-۹]", badge) and badge not in source_text:
            badge = ""
        prompt_en = typo.clean(raw.get("bg_prompt_en"))[:260]
        if not prompt_en or not hooks.ASCII_PROMPT.match(prompt_en):
            prompt_en = hooks.bg_prompt(style)
        elif "no text" not in prompt_en.lower():
            prompt_en += hooks.BG_SUFFIX
        out.append({
            "title": title, "subtitle": field("subtitle", 60), "kicker": field("kicker", 24), "number": hooks.fa_digits(number) if number else "",
            "badge": badge, "tagline": "", "credits": "", "cta": "", "label_a": "", "label_b": "", "style": style,
            "formula": "ai", "formula_label": "پیشنهادِ هوش مصنوعی", "source": "ai", "concept": field("concept", 220) or hooks.CONCEPTS.get(style, ""),
            "bg_prompt_en": prompt_en, "mood": raw.get("mood") if raw.get("mood") in palette.MOODS else "",
        })
    return out


# ───────────────────────────── جمع‌بندی

def decorate(idea: dict, idx: int, fmt: str) -> dict:
    """سبک/قالب و «spec ِ آماده» را به ایده اضافه می‌کند تا پنل با یک کلیک اعمالش کند."""
    sd = STYLES[idea["style"]]
    content = {k: idea.get(k, "") for k in CONTENT_LIMITS}
    colors = {"mood": idea.get("mood") or ""}
    out = dict(idea)
    out.update({"id": f"i{idx + 1}", "style_title": sd.title, "format": fmt, "needs_second": sd.needs_second,
                "spec_patch": {"format": fmt, "style": idea["style"], "content": content, "colors": colors}})
    return out


def ideate(store, topic: str, *, product=None, fmt: str = "youtube", count: int = 6, number=None, other: str = "", use_ai: bool = True,
           variation: int = 0, ask=None, use_price: bool = False) -> dict:
    """⇒ {via, ai:{tried, ok, label, reason}, message, ideas[], format, topic}. ``ask`` تزریق‌پذیر است (آزمون)."""
    from . import formats as F

    topic = typo.clean(topic)[:300]
    if not topic and product is not None:
        topic = product.name
    if not typo.plain(topic):
        raise ValueError("موضوع را بنویسید یا یک محصول انتخاب کنید.")
    fmt_obj = F.get(fmt)
    count = max(2, min(MAX_IDEAS, int(count or 6)))
    facts = facts_of(store, product)
    source_text = " ".join([topic, other, json.dumps(facts, ensure_ascii=False)])
    prod_info = None
    if product is not None:
        prod_info = {"name": product.name, "short": product.short_description or "", "price_text": price_text(product) if use_price else ""}
    rules = hooks.rule_ideas(topic, fmt=fmt, count=count, product=prod_info, audience=store.target_audience or "", store_name=store.name,
                             number=number, other=other, variation=variation)
    ai_info = {"tried": False, "ok": False, "label": "", "reason": ""}
    ideas: list[dict] = []
    if use_ai:
        ai_info["tried"] = True
        styles = list(hooks.preferred_styles(fmt)) + [k for k in STYLES if k not in hooks.preferred_styles(fmt)]
        styles = [k for k in styles if k in STYLES][:10]
        try:
            ask_fn = ask or _default_ask
            parsed, info = ask_fn(store, _prompt(topic, fmt_obj.title, styles, facts, count, hooks.fa_digits(number) if number else "", other))
            ideas = clean_ai_ideas(parsed, fmt=fmt, source_text=source_text)
            ai_info.update(ok=bool(ideas), label=str((info or {}).get("label") or ""))
            if not ideas:
                ai_info["reason"] = "هوش مصنوعی جوابِ قابل‌استفاده نداد."
        except AIUnavailable as exc:
            ai_info["reason"] = hooks.fit_text(str(exc), 300)
        except Exception as exc:  # noqa: BLE001 — هیچ خطایی نباید ایده‌ها را بخواباند
            logger.exception("thumbs.ideation: AI path crashed")
            ai_info["reason"] = hooks.fit_text(f"خطای پیش‌بینی‌نشده در هوش مصنوعی: {exc}", 300)
    via = "rules"
    if ideas:
        via = "ai"
        if len(ideas) < min(3, count):
            have = {typo.plain(i["title"]) for i in ideas}
            ideas += [r for r in rules if typo.plain(r["title"]) not in have][: count - len(ideas)]
            via = "mixed"
        ideas = ideas[:count]
    else:
        ideas = rules
    if not ideas:
        raise ValueError("از این موضوع ایده‌ای ساخته نشد؛ موضوع را کمی بیشتر توضیح بدهید.")
    for i in ideas:
        if not i.get("mood"):
            i["mood"] = ""
    ideas = [decorate(i, n, fmt) for n, i in enumerate(ideas)]
    if via == "ai":
        message = "ایده‌ها را هوش مصنوعی نوشت" + (f" ({ai_info['label']})" if ai_info["label"] else "") + "؛ همه را پیش از استفاده ویرایش کنید."
    elif via == "mixed":
        message = "چند ایده از هوش مصنوعی آمد و بقیه از فرمول‌های آمادهٔ فارسی تکمیل شد."
    elif use_ai:
        message = ("هوش مصنوعی در دسترس نبود، برای همین از فرمول‌های آمادهٔ فارسی استفاده شد"
                   + (f" ({ai_info['reason']})" if ai_info["reason"] else "") + ". وقتی هوش مصنوعی برگردد همین دکمه پیشنهادهای هوشمند می‌دهد.")
    else:
        message = "ایده‌ها از فرمول‌های آمادهٔ فارسی ساخته شد (هوش مصنوعی خاموش بود)."
    return {"topic": topic, "format": fmt, "via": via, "ai": ai_info, "message": message, "ideas": ideas}


def moodboard(sample_url) -> list[dict]:
    return archetypes.public(sample_url)
