"""«ایده بساز»: ایده‌های تازهٔ محتوا برای این فروشگاه، با هوش مصنوعی و، وقتی نیست، با فرمول‌های آمادهٔ فارسی.

SOURCE: ported from InstAI:instai/ideabank/agent.py @ 2f8aa90 (idea_generator: یک پرسشِ وارسی‌شده، هدایت با ایده‌های ستاره‌دار، فهرستِ عنوان‌های موجود برای
جلوگیری از تکرار) و از روشِ دومسیرهٔ NM در apps/thumbs/ideation.py (هوش مصنوعی ⇒ وارسی ⇒ فرمول‌ها)، برای ایده‌های محتوای فروشگاه بازنویسی شده.

دو مسیر، همیشه به این ترتیب:

1. **هوش مصنوعی** از مسیریابِ پروژه (لوکال روی سرورِ پردازش ⇄ متیس). خروجی JSON است و سخت‌گیرانه وارسی می‌شود: قالبِ ناشناخته، ادعای ساختگی
   (عدد، قیمت، درصد، آمار، نقلِ قول)، جای‌گیرِ ناشناخته، متنِ خیلی کوتاه یا عنوانِ تکراری ⇒ آن ایده دور ریخته می‌شود.
2. **فرمول‌های آماده** (``formulas.rule_ideas``) وقتی هوش مصنوعی در دسترس نیست (متیس ۴۰۲، گره خاموش، سیاستِ داده…) یا ایده‌ی معتبرِ کافی نیاورد. پیام
   می‌گوید چرا؛ هر بار که هوش مصنوعی برگردد مسیرِ اول دوباره امتحان می‌شود. بانکِ ایده‌های آماده هیچ‌وقت منتظرِ هوش مصنوعی نمی‌ماند.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re

from . import ai, bank, fill, formulas, guard
from .catalog import CATEGORIES, CHANNELS, DEFAULT_CHANNEL, FORMATS

logger = logging.getLogger(__name__)

MAX_IDEAS = 8
LIKED_LIMIT = 6
TITLES_LIMIT = 140
KNOWN_PLACEHOLDERS = set(fill.FALLBACK) | {"فروشگاه"}
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
_HAS_DIGIT = re.compile("[0-9۰-۹٠-٩]")

SYSTEM = (
    "You write short Persian content ideas for ONE specific small online shop (Instagram and Telegram). You answer with a single valid JSON object and "
    "nothing else. You never invent a product, a price, a discount, a percentage, a statistic, a number, a result, a customer quote, an award or any "
    "claim about the shop that is not in the facts you were given."
)


# ───────────────────────────── واقعیت‌های فروشگاه

def default_product_names(store, variation: int = 0, limit: int = 6) -> list[str]:
    """نامِ چند محصولِ خودِ فروشگاه برای وقتی که کاربر نه موضوعی نوشته نه محصولی انتخاب کرده؛ هر بار با ``variation`` چرخیده می‌شود."""
    if not getattr(store, "pk", 0):
        return []
    try:
        from apps.products.models import Product

        names = [str(n).strip() for n in Product.objects.filter(store=store).order_by("pk").values_list("name", flat=True)[:40] if str(n).strip()]
    except Exception:  # noqa: BLE001 — فهرستِ محصول فقط تزئینِ ایده‌هاست
        return []
    names = sorted(dict.fromkeys(names), key=lambda n: bool(_HAS_DIGIT.search(n)))     # نامِ بی‌عدد اول (عدد در نام خودش «ادعا»ی ایده می‌شود)؛ پایدار
    if names and variation:
        shift = variation % len(names)
        names = names[shift:] + names[:shift]
    return names[:limit]


def facts_of(store, product=None, product_names: list[str] | None = None) -> dict:
    prof = getattr(store, "profile", None)
    f = {
        "store": store.name, "business": store.business_type or "", "about": (store.description or "")[:240], "audience": store.target_audience or "",
        "tone": (getattr(prof, "tone", "") or getattr(prof, "brand_voice", "") or "") if prof else "",
    }
    if product is not None:
        f["product"] = {"name": product.name, "short": (product.short_description or product.description or "")[:200], "brand": product.brand or ""}
    elif product_names:
        f["products"] = list(product_names)
    return f


def source_text(store, product, topic: str, instruction: str, facts: list[str], product_names: list[str] | None = None) -> str:
    """متنی که خودِ کاربر/فروشگاه نوشته؛ واژه یا عددی که این‌جاست «ادعای ساختگی» حساب نمی‌شود."""
    return " ".join([topic or "", instruction or "", *facts, json.dumps(facts_of(store, product, product_names), ensure_ascii=False)])


# ───────────────────────────── پرسش از هوش مصنوعی

def build_prompt(*, store, product, category: str, count: int, topic: str, instruction: str, facts: list[str], liked: list[dict],
                 existing_titles: list[str], product_names: list[str] | None = None) -> str:
    cat_line = (f"Category: {CATEGORIES[category]['fa']} — {CATEGORIES[category]['hint']}" if category else
                "Category: mix — give each idea its own category, one of: " + ", ".join(f"{k} ({v['fa']})" for k, v in CATEGORIES.items()))
    shop = json.dumps({k: v for k, v in facts_of(store, product, product_names).items() if v}, ensure_ascii=False)
    ctx = {
        "owner_topic": topic or None, "owner_instruction": instruction or None, "brand_facts_verbatim": facts or None,
        "liked": [{"title": x["filled"]["title"], "logline": x["filled"]["logline"]} for x in liked[:LIKED_LIMIT]] or None,
        "existing_titles": existing_titles[:TITLES_LIMIT] or None,
    }
    ctx = {k: v for k, v in ctx.items() if v}
    return (
        f"Write exactly {count} NEW content ideas for this shop.\n{cat_line}\n\n"
        f"Known facts about the shop (use ONLY these; do not invent anything): {shop}\n"
        f"Context: {json.dumps(ctx, ensure_ascii=False)}\n\n"
        "Rules:\n"
        "- Everything is natural Persian (fa), except JSON keys and the values of format/channel/category.\n"
        "- Every idea differs from the others and from every title in existing_titles. If liked ideas are given, write more in their spirit (not copies).\n"
        "- NEVER write prices, discounts, percentages, statistics, digits, results, guarantees, awards or customer quotes. Where the shop must add real data "
        "(its offer, its policy, a real review) write a bracket slot such as [پیشنهادِ واقعیِ شما] instead of inventing it.\n"
        "- Only calendar occasions with a FIXED Jalali date (Nowruz, Yalda ...), never lunar/religious dates.\n"
        "- No emoji. title: 2-9 words. logline: one sentence saying what the post is. hook: the first sentence of the content, under 15 words. "
        "shoot: what to photograph/film, 1-2 sentences. cta: a short call to action, under 8 words.\n"
        "- You may use these placeholders inside texts when natural: {محصول} {فروشگاه} {مخاطب} {حوزه}.\n"
        f"- format is one of: {', '.join(FORMATS)}. channel is one of: {', '.join(CHANNELS)}.\n"
        'Reply with ONLY this JSON: {"ideas": [{"category": "", "title": "", "logline": "", "hook": "", "shoot": "", "cta": "", "format": "", "channel": "", "tags": [""]}]}'
    )


# ───────────────────────────── وارسیِ جوابِ هوش مصنوعی

def _clean(v) -> str:
    return re.sub(r"\s+", " ", _EMOJI.sub("", str(v or ""))).strip()


def clean_ai_ideas(parsed, *, category: str, source: str, taken: set[str], limit: int = MAX_IDEAS) -> list[dict]:
    """JSON ِ خام ⇒ ایده‌های وارسی‌شده. ایده‌ای که قالبِ ناشناخته، ادعای ساختگی یا جای‌گیرِ ناشناخته دارد، خیلی کوتاه است یا تکراری است دور ریخته می‌شود."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ideas"), list):
        return []
    out: list[dict] = []
    seen = set(taken)
    for raw in parsed["ideas"][: limit * 3]:
        if not isinstance(raw, dict):
            continue
        fmt = _clean(raw.get("format")).lower()
        if fmt not in FORMATS:
            continue                                                 # قالبِ ناشناخته ⇒ دور ریخته (نه حدس‌زدن)
        cat = category or _clean(raw.get("category")).lower()
        if cat not in CATEGORIES:
            cat = "tips"                                             # مدل دسته را ننوشت: دستهٔ عمومی (قالبِ ناشناخته برعکس دور ریخته می‌شود)
        title, logline, hook = _clean(raw.get("title")), _clean(raw.get("logline")), _clean(raw.get("hook"))
        shoot, cta = _clean(raw.get("shoot")), _clean(raw.get("cta"))
        if not (2 <= len(title.split()) <= 12) or len(title) > 100 or len(logline) < 15 or len(hook) < 4:
            continue
        joined = " ".join([title, logline, hook, shoot, cta])
        if not (guard.is_persian(title) and guard.is_persian(logline) and guard.is_persian(hook)):
            continue                                                 # جوابِ انگلیسی/غیرفارسیِ مدل در پنلِ فارسی ذخیره نمی‌شود
        if guard.problems(joined, source):
            continue
        if any(p not in KNOWN_PLACEHOLDERS for p in guard.PLACEHOLDER.findall(joined)):
            continue                                                 # {چیزِ ناشناخته} هیچ‌وقت پر نمی‌شود
        k = bank.title_key(title)
        if k in seen:
            continue
        seen.add(k)
        channel = _clean(raw.get("channel")).lower()
        tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        out.append(bank.normalize({"category": cat, "format": fmt, "channel": channel if channel in CHANNELS else DEFAULT_CHANNEL, "tags": tags[:6],
                                   "title": title, "logline": logline, "hook": hook, "shoot": shoot, "cta": cta}))
        out[-1]["formula"] = "ai"
        if len(out) >= limit:
            break
    return out


# ───────────────────────────── جمع‌بندی

def generate(store, *, category: str = "", count: int = 5, topic: str = "", instruction: str = "", facts: list[str] | None = None, product=None,
             use_ai: bool = True, variation: int = 0, ask=None, ctx: dict | None = None, today: _dt.date | None = None) -> dict:
    """⇒ {via, ai:{tried, ok, label, reason}, message, ideas[] (ذخیره‌نشده), category}. ``ask`` تزریق‌پذیر است (آزمون)."""
    if category and category not in CATEGORIES:
        raise ValueError("دستهٔ نامعتبر است.")
    count = max(1, min(MAX_IDEAS, int(count or 5)))
    topic = _clean(topic)[:200]
    instruction = _clean(instruction)[:500]
    facts = [_clean(f)[:240] for f in (facts or []) if _clean(f)][:5]
    ctx = ctx or fill.context(store, product)
    all_rows = bank.all_ideas(store, ctx, today)
    liked = [r for r in all_rows if r["favorite"] and (not category or r["category"] == category)] or [r for r in all_rows if r["favorite"]]
    taken = bank.existing_titles(store, ctx)
    # عنوان‌های موجودِ همین دسته (و بعد بقیه) برای اینکه مدل تکرار نکند
    titles = [r["filled"]["title"] for r in all_rows if not category or r["category"] == category] + [r["filled"]["title"] for r in all_rows if category and r["category"] != category]
    names = default_product_names(store, variation) if (product is None and not topic) else []
    source = source_text(store, product, topic, instruction, facts, names)

    ai_info = {"tried": False, "ok": False, "label": "", "reason": ""}
    ideas: list[dict] = []
    if use_ai:
        ai_info["tried"] = True
        try:
            prompt = build_prompt(store=store, product=product, category=category, count=count, topic=topic, instruction=instruction, facts=facts,
                                  liked=liked, existing_titles=titles, product_names=names)
            parsed, info = (ask or ai.default_ask)(store, prompt, SYSTEM)
            ideas = clean_ai_ideas(parsed, category=category, source=source, taken=taken, limit=count)
            ai_info.update(ok=bool(ideas), label=str((info or {}).get("label") or ""))
            if not ideas:
                ai_info["reason"] = "هوش مصنوعی جوابِ قابل‌استفاده نداد."
        except ai.AIUnavailable as exc:
            ai_info["reason"] = str(exc)[:300]
        except Exception as exc:  # noqa: BLE001 — هیچ خطایی نباید «ایده بساز» را از کار بیندازد
            logger.exception("ideabank: AI path crashed")
            ai_info["reason"] = f"خطای پیش‌بینی‌نشده در هوش مصنوعی: {exc}"[:300]

    via = "formula"
    if ideas:
        via = "ai"
        if len(ideas) < min(3, count):
            have = set(taken) | {bank.title_key(i["title"]) for i in ideas}
            ideas += formulas.rule_ideas(ctx=ctx, topic=topic, product_name=getattr(product, "name", ""), facts=facts, category=category,
                                         count=count - len(ideas), variation=variation, liked=liked, taken=have, source=source, today=today,
                                         product_names=names)
            via = "mixed"
        ideas = ideas[:count]
    else:
        ideas = formulas.rule_ideas(ctx=ctx, topic=topic, product_name=getattr(product, "name", ""), facts=facts, category=category, count=count,
                                    variation=variation, liked=liked, taken=taken, source=source, today=today, product_names=names)
    if not ideas:
        raise ValueError("برای این درخواست ایدهٔ تازه‌ای نمانده؛ موضوعِ دیگری بنویسید، دستهٔ دیگری را امتحان کنید یا چند واقعیتِ برند اضافه کنید.")

    if via == "ai":
        message = "ایده‌ها را هوش مصنوعی نوشت" + (f" ({ai_info['label']})" if ai_info["label"] else "") + "؛ همه را پیش از انتشار با واقعیتِ فروشگاهتان تطبیق بدهید."
    elif via == "mixed":
        message = "چند ایده از هوش مصنوعی آمد و بقیه از فرمول‌های آمادهٔ فارسی تکمیل شد."
    elif use_ai:
        message = ("هوش مصنوعی در دسترس نبود، برای همین از فرمول‌های آمادهٔ فارسی استفاده شد" + (f" ({ai_info['reason']})" if ai_info["reason"] else "") +
                   ". وقتی هوش مصنوعی برگردد همین دکمه پیشنهادهای هوشمند می‌دهد.")
    else:
        message = "ایده‌ها از فرمول‌های آمادهٔ فارسی ساخته شد (هوش مصنوعی خاموش بود)."
    return {"via": via, "ai": ai_info, "message": message, "ideas": ideas, "category": category, "topic": topic}


def generate_and_save(store, **kw) -> dict:
    """مثلِ ``generate`` ولی ایده‌ها را به‌عنوانِ ایده‌های خودِ فروشگاه ذخیره می‌کند (عنوانِ تکراری رد می‌شود)."""
    result = generate(store, **kw)
    ctx = kw.get("ctx") or fill.context(store, kw.get("product"))
    made = len(result["ideas"])
    saved = bank.add_generated(store, result["ideas"], ctx=ctx)
    result.update(ideas=saved, saved=len(saved), skipped=made - len(saved))
    return result
