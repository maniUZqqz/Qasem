"""Turning "this is trending" into "make this, about this product". §6.2

The hard part is not fetching trends. It is that **most trends have nothing to
do with most shops**, and a page that pairs every trend with every product
produces a wall of nonsense a shop stops reading by the third visit.

So the rule here: an idea is kept only if the model can say *why this trend has
anything to do with this shop*, in a sentence a person would accept. `why` is
not decoration — `suggest` drops any idea whose reason is empty or generic,
because a suggestion nobody can justify is noise wearing the costume of insight.

The second rule, from the same place: **the trend is never allowed to become the
product.** A shoe shop riding a football trend is selling shoes with football in
the background; the video is not about football. That is written into the prompt
because it is the failure mode of every trend-jacking tool.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from services.research import trends as source

from .trend_models import Trend, TrendIdea

logger = logging.getLogger(__name__)

#: Fewer, better. A shop reads three ideas and acts on one; it reads twenty and
#: acts on none.
MAX_IDEAS = 6

#: A reason shorter than this is not a reason.
MIN_REASON = 15

#: Answers that are technically sentences and say nothing. Rejected explicitly
#: because a weak model reaches for them when it has no real connection to make.
EMPTY_REASONS = (
    "این ترند محبوب است",
    "مردم به این موضوع علاقه دارند",
    "ترند روز است",
    "می‌تواند بازدید بیاورد",
)


def refresh(regions: list[str] | None = None, limit: int = 20) -> dict:
    """Fetch today's trends and store the ones we have not seen today.

    Sightings are per day, not per fetch: a trend that is still trending this
    afternoon is the same trend as this morning, and a row per refresh would
    turn one story into fourteen.
    """
    payload = source.fetch(regions, limit=limit)
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    stored = 0
    for row in payload["trends"]:
        trend, created = Trend.objects.get_or_create(
            title=row["title"][:200],
            region=row["region"],
            seen_at=today,
            defaults={
                "traffic": row["traffic"][:40],
                "context": row["context"],
                "image": row["image"][:200] if row["image"] else "",
                "source": row["source"],
            },
        )
        if not created and (trend.context != row["context"] or trend.traffic != row["traffic"][:40]):
            # Same story later in the day: newer headlines and traffic win.
            trend.context = row["context"]
            trend.traffic = row["traffic"][:40]
            trend.save(update_fields=["context", "traffic", "updated_at"])
        stored += int(created)

    return {
        "fetched": len(payload["trends"]),
        "new": stored,
        "problems": payload["problems"],
        "sources": source.available(),
    }


def current(regions: list[str] | None = None, limit: int = 40) -> list[Trend]:
    """Trends that are still current. Stale ones are simply not returned."""
    rows = Trend.objects.filter(
        seen_at__gte=timezone.now() - source.FRESH_FOR,
    )
    if regions:
        rows = rows.filter(region__in=source.expand_regions(regions))
    return list(rows[:limit])


# ------------------------------------------------------------ relevance

#: Category words across the languages the trend feeds arrive in (fa/en/fr/de/tr).
#: A French trend about «mode» says nothing to a Persian keyword match unless
#: we know «mode» is «پوشاک». Small on purpose: a wrong mapping is worse than
#: none, and the model (when reachable) does the rest.
LEXICON = {
    "پوشاک و مد": [
        "پوشاک", "لباس", "مد", "فشن", "مانتو", "کفش", "کیف", "شلوار", "پیراهن", "کت", "روسری",
        "fashion", "clothing", "clothes", "dress", "shoes", "sneakers", "outfit",
        "mode", "vetements", "robe", "chaussures", "kleidung", "schuhe", "giyim", "moda",
        "ayakkabi", "elbise", "zara", "nike", "adidas",
    ],
    "قهوه و کافه": [
        "قهوه", "کافه", "اسپرسو", "لاته", "coffee", "cafe", "espresso", "kaffee", "kahve",
        "latte", "barista", "starbucks",
    ],
    "آرایشی و بهداشتی": [
        "آرایش", "آرایشی", "بهداشتی", "پوست", "عطر", "ادکلن", "رژ", "makeup", "beauty",
        "skincare", "cosmetics", "perfume", "parfum", "maquillage", "kosmetik", "parfum",
        "guzellik", "sephora",
    ],
    "موبایل و دیجیتال": [
        "موبایل", "گوشی", "لپتاپ", "هدفون", "دیجیتال", "آیفون", "سامسونگ", "شیائومی",
        "iphone", "samsung", "apple", "phone", "smartphone", "laptop", "headphones", "airpods",
        "pixel", "xiaomi", "handy", "telephone", "telefon", "ios", "android",
    ],
    "خوراکی": [
        "غذا", "خوراکی", "شیرینی", "کیک", "شکلات", "آجیل", "زعفران", "food", "recipe",
        "chocolate", "cake", "pastry", "restaurant", "nourriture", "recette", "essen",
        "yemek", "tarif",
    ],
    "ورزش": [
        "ورزش", "فوتبال", "بدنسازی", "باشگاه", "sport", "football", "soccer", "fitness",
        "gym", "running", "fussball", "futbol", "marathon",
    ],
    "خانه و دکور": [
        "خانه", "دکور", "مبل", "آشپزخانه", "home", "decor", "furniture", "kitchen", "maison",
        "cuisine", "mobel", "kuche", "mobilya", "ikea",
    ],
    "کودک و اسباب‌بازی": [
        "کودک", "بچه", "اسباب", "نوزاد", "kids", "baby", "toy", "toys", "enfant", "jouet",
        "kinder", "spielzeug", "oyuncak", "bebek", "lego",
    ],
    "طلا و زیورآلات": [
        "طلا", "جواهر", "زیورآلات", "گردنبند", "انگشتر", "ساعت", "gold", "jewelry",
        "jewellery", "watch", "bijoux", "montre", "schmuck", "uhr", "altin", "taki",
    ],
}


def _fold(text: str) -> str:
    """normalize + strip Latin accents (café → cafe) for cross-language matching."""
    import unicodedata

    from services.research.product_match import normalize

    text = normalize(text)
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def store_vocabulary(store, products=None) -> dict:
    """Words that describe this shop: its products, tags, brand, category, and
    the lexicon groups those words fall into."""
    from apps.products.models import Product
    from services.research.product_match import STOPWORDS

    products = products if products is not None else list(
        Product.objects.filter(store=store).select_related("category")[:60]
    )
    words: dict[str, str] = {}  # word -> where it came from (product name / group)
    texts = [store.business_type or ""]
    for product in products:
        parts = [product.name, product.brand or ""]
        parts += [str(t) for t in (product.tags or []) if isinstance(t, (str, int))]
        if getattr(product, "category", None) is not None:
            parts.append(product.category.name)
        texts += parts
        for part in parts:
            for token in _fold(part).split():
                if len(token) > 2 and token not in STOPWORDS and not token.isdigit():
                    words.setdefault(token, product.name)
    folded_texts = " " + " ".join(_fold(t) for t in texts) + " "
    groups = []
    for group, members in LEXICON.items():
        folded = [_fold(m) for m in members]
        if any(f" {m} " in folded_texts for m in folded):
            groups.append(group)
            for m in folded:
                words.setdefault(m, f"گروهِ «{group}»")
    return {"words": words, "groups": groups}


def relevance(trend, vocabulary: dict) -> dict:
    """Keyword relevance of one trend to the shop: label, score, reason."""
    words = vocabulary["words"]
    title_tokens = set(_fold(trend.title).split())
    news_tokens = set()
    for item in trend.news:
        news_tokens |= set(_fold(item.get("title", "")).split())
    in_title = sorted(w for w in title_tokens if w in words)
    in_news = sorted(w for w in news_tokens - title_tokens if w in words)
    score = 2 * len(in_title) + len(in_news)
    if score >= 2:
        label, key = "مرتبط با فروشگاهِ شما", "high"
    elif score == 1:
        label, key = "شاید مرتبط", "maybe"
    else:
        label, key = "نامرتبط", "none"
    hits = in_title + in_news
    reason = (
        "واژه‌های مشترک: " + "، ".join(f"«{w}» ({words[w]})" for w in hits[:4])
        if hits else "واژه‌ی مشترکی با محصولات و دسته‌ی فروشگاه ندارد."
    )
    return {"key": key, "label": label, "score": score, "reason": reason, "words": hits[:6],
            "method": "keywords"}


RELEVANCE_JOB_KIND = "trend_relevance"


def stored_llm_relevance(store) -> dict:
    """The last model ranking for this store: ``{trend_id: {...}}``."""
    from apps.jobs.models import Job

    job = (
        Job.objects.filter(store=store, type=Job.Type.MARKET_ANALYSIS, context__kind=RELEVANCE_JOB_KIND)
        .order_by("-created_at").first()
    )
    if job is None:
        return {}
    return {int(k): v for k, v in ((job.result or {}).get("by_trend") or {}).items()}


RELEVANCE_SYSTEM = (
    "You judge whether current search trends are relevant to one specific shop's "
    "products for marketing content. Answer with one JSON object only. Most trends "
    "are NOT relevant to most shops; say so."
)


def rank_with_llm(store, trends, *, job=None) -> dict:
    """Ask the model (only if reachable) how relevant each trend is. Stored."""
    import json

    from apps.jobs.models import Job
    from apps.products.models import Product

    from . import research_llm

    products = list(Product.objects.filter(store=store)[:25])
    payload = [
        {"id": t.pk, "title": t.title, "where": t.region_title,
         "news": [n.get("title", "") for n in t.news[:2]]}
        for t in trends[:30]
    ]
    prompt = (
        f"Shop: {json.dumps({'name': store.name, 'business_type': store.business_type}, ensure_ascii=False)}\n"
        f"Products: {json.dumps([p.name for p in products], ensure_ascii=False)}\n"
        f"Trends: {json.dumps(payload, ensure_ascii=False)}\n\n"
        "For each trend give relevance 0 (none), 1 (weak, content angle only) or 2 "
        "(clear link to these products) and a short Persian reason naming the link.\n"
        'Answer exactly: {"ranking": [{"id": 1, "relevance": 0, "reason": "..."}]}'
    )
    parsed = research_llm.ask_json(
        store, prompt_id="trend_relevance", prompt=prompt, system=RELEVANCE_SYSTEM, job=job,
        validate=lambda p: (isinstance((p or {}).get("ranking"), list), ["ranking باید فهرست باشد"]),
    )
    valid = {t.pk for t in trends}
    by_trend = {}
    for row in parsed.get("ranking") or []:
        try:
            tid = int(row.get("id"))
            level = max(0, min(2, int(row.get("relevance", 0))))
        except (TypeError, ValueError):
            continue
        if tid in valid:
            by_trend[str(tid)] = {"relevance": level, "reason": str(row.get("reason", ""))[:300]}
    record = Job.objects.create(
        store=store, type=Job.Type.MARKET_ANALYSIS, context={"kind": RELEVANCE_JOB_KIND},
    )
    record.mark_completed({"kind": RELEVANCE_JOB_KIND, "by_trend": by_trend,
                           "at": timezone.now().isoformat()})
    return {int(k): v for k, v in by_trend.items()}


def heuristic_idea(store, trend, vocabulary: dict, products) -> TrendIdea | None:
    """A plain template idea when no model is reachable — only for a trend that
    shares real words with the shop, and labelled as a template."""
    rel = relevance(trend, vocabulary)
    if rel["key"] == "none":
        return None
    words = vocabulary["words"]
    named = {words[w] for w in rel["words"] if not words[w].startswith("گروهِ")}
    product = next((p for p in products if p.name in named), None) or (products[0] if products else None)
    if product is None:
        return None
    headline = trend.news[0]["title"] if trend.news else ""
    return TrendIdea(
        store=store, trend=trend, product=product, kind=TrendIdea.Kind.POST,
        idea=(
            f"[قالبِ ساده — بدونِ هوش مصنوعی] یک پست/استوری درباره‌ی «{product.name}» که "
            f"با موضوعِ داغِ «{trend.title}» ({trend.region_title}) شروع شود"
            + (f"؛ خبرِ پشتِ این ترند: «{headline[:120]}»" if headline else "")
            + ". موضوعِ اصلی همچنان محصولِ شماست، ترند فقط زمینه است."
        ),
        why=f"این ترند با فروشگاهِ شما واژه‌ی مشترک دارد — {rel['reason']}",
        hook=f"همه درباره‌ی «{trend.title[:40]}» حرف می‌زنند؛ این هم «{product.name[:40]}»",
    )


IDEA_SYSTEM = (
    "You connect current trends to a specific shop's products for short-form "
    "Persian marketing content. You answer with a single valid JSON object and "
    "nothing else. You never invent a product, a price, or a feature. When a "
    "trend has no honest connection to this shop, you leave it out."
)


def build_idea_prompt(store, products, trends) -> str:
    import json

    dumps = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    profile = getattr(store, "profile", None)

    return (
        "Suggest content this shop should make, based on what is trending.\n\n"
        f"Shop:\n{dumps({'name': store.name, 'business_type': store.business_type, 'tone': getattr(profile, 'tone', ''), 'brand_voice': getattr(profile, 'brand_voice', '')})}\n\n"
        f"Their products:\n{dumps([{'id': p.pk, 'name': p.name, 'description': (p.description or '')[:200]} for p in products])}\n\n"
        f"Trending now:\n{dumps([{'id': t.pk, 'title': t.title, 'where': t.region_title, 'context': t.context} for t in trends])}\n\n"
        "Rules:\n"
        "- At most "
        f"{MAX_IDEAS} ideas. Fewer is better than forced.\n"
        "- Only pair a trend with a product when there is a real connection. "
        "Most trends fit no shop; leaving a trend out is the normal case.\n"
        "- `why` must explain the connection specifically. "
        "\"این ترند محبوب است\" is not a reason and will be thrown away.\n"
        "- The trend is context, never the subject. A shoe shop riding a "
        "football trend is selling shoes with football in the background — the "
        "video is not about football.\n"
        "- `hook` is the first sentence of the content, in Persian, under 15 words.\n"
        "- Everything in Persian except the JSON keys and the enum values.\n\n"
        'Answer exactly: {"ideas": [{"trend_id": 1, "product_id": 2, '
        '"kind": "VIDEO|POST|STORY|CAPTION", "idea": "...", "hook": "...", '
        '"why": "..."}]}'
    )


def _usable(reason: str) -> bool:
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        return False
    return not any(empty in reason for empty in EMPTY_REASONS)


def suggest(store, *, regions=None, job=None, trend_ids=None) -> dict:
    """Ideas for this shop, from the trends that are live right now.

    ``trend_ids`` narrows it to the trends the owner picked («ایده‌ی محتوا» on
    one card); then only that trend's open ideas are replaced. With no model
    reachable, a picked trend that shares words with the shop gets a labelled
    template idea instead of an error.
    """
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from apps.products.models import Product
    from services.ai.gateway import text_provider
    from services.ai.router import TASK_REASONING, models_for

    trends = current(regions)
    if trend_ids:
        wanted = {int(t) for t in trend_ids}
        trends = [t for t in Trend.objects.filter(pk__in=wanted)]
    if not trends:
        return {
            "ideas": [],
            "note": "ترند تازه‌ای نداریم. دکمه‌ی «به‌روزرسانی» را بزنید.",
            "dropped": 0,
        }

    products = list(Product.objects.filter(store=store, is_available=True)[:25])
    if not products:
        return {
            "ideas": [],
            "note": "اول چند محصول اضافه کنید تا بشود برایشان ایده داد.",
            "dropped": 0,
        }

    from . import research_llm

    llm_ok, llm_note = research_llm.status(store) if trend_ids else (True, "")
    if not llm_ok and trend_ids:
        vocabulary = store_vocabulary(store, products)
        made = [i for i in (heuristic_idea(store, t, vocabulary, products) for t in trends) if i]
        TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN, trend__in=trends).delete()
        TrendIdea.objects.bulk_create(made)
        return {
            "ideas": list(
                TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN)
                .select_related("trend", "product")
            ),
            "dropped": len(trends) - len(made),
            "note": (
                "مدلِ زبانی الان در دسترس نیست؛ "
                + ("یک ایده‌ی سادهٔ قالبی ساخته شد." if made else
                   "این ترند واژه‌ی مشترکی با فروشگاهِ شما ندارد، پس ایده‌ای ساخته نشد.")
            ),
        }
    parsed, _ = recorded_json_call(
        job=job,
        store=store,
        task_type=AIRequest.TaskType.REASONING,
        prompt_id="trend_ideas",
        prompt_version="1",
        provider=text_provider(store),
        models=models_for(TASK_REASONING),
        prompt=build_idea_prompt(store, products, trends),
        system=IDEA_SYSTEM,
        validate=lambda parsed: (
            isinstance((parsed or {}).get("ideas"), list),
            ["ideas باید فهرست باشد"],
        ),
        validation_message="مدل فهرست ایده‌ها را برنگرداند",
    )

    by_trend = {t.pk: t for t in trends}
    by_product = {p.pk: p for p in products}
    kept, dropped = [], 0

    for row in (parsed.get("ideas") or [])[: MAX_IDEAS * 2]:
        trend = by_trend.get(row.get("trend_id"))
        idea_text = str(row.get("idea", "")).strip()
        why = str(row.get("why", "")).strip()

        # Three ways an idea is thrown away, and each is a real failure mode:
        # a trend the model invented, an empty idea, and a connection it could
        # not justify.
        if trend is None or not idea_text or not _usable(why):
            dropped += 1
            continue

        kind = str(row.get("kind", "VIDEO")).upper()
        if kind not in TrendIdea.Kind.values:
            kind = TrendIdea.Kind.VIDEO

        kept.append(TrendIdea(
            store=store,
            trend=trend,
            product=by_product.get(row.get("product_id")),
            kind=kind,
            idea=idea_text[:2000],
            why=why[:1000],
            hook=str(row.get("hook", ""))[:300],
        ))
        if len(kept) >= MAX_IDEAS:
            break

    # Replace rather than accumulate: yesterday's open ideas are about trends
    # that have moved on, and a list that only grows is one nobody reads.
    open_ideas = TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN)
    if trend_ids:
        open_ideas = open_ideas.filter(trend__in=trends)
    open_ideas.delete()
    TrendIdea.objects.bulk_create(kept)

    return {
        "ideas": list(
            TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN)
            .select_related("trend", "product")
        ),
        "dropped": dropped,
        "note": (
            f"{dropped} پیشنهاد کنار گذاشته شد چون ربطش به فروشگاه شما روشن نبود."
            if dropped else (
                "مدلِ زبانی برای این ترند(ها) ربطِ قابل‌دفاعی با محصولاتِ شما پیدا نکرد، "
                "پس ایده‌ای نساخت — بهتر از ایده‌ی زورکی است."
                if not kept else ""
            )
        ),
    }
