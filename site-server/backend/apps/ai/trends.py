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
        _, created = Trend.objects.get_or_create(
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
        rows = rows.filter(region__in=regions)
    return list(rows[:limit])


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


def suggest(store, *, regions=None, job=None) -> dict:
    """Ideas for this shop, from the trends that are live right now."""
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from apps.products.models import Product
    from services.ai.gateway import text_provider
    from services.ai.router import TASK_REASONING, models_for

    trends = current(regions)
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
    TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN).delete()
    TrendIdea.objects.bulk_create(kept)

    return {
        "ideas": list(
            TrendIdea.objects.filter(store=store, state=TrendIdea.State.OPEN)
            .select_related("trend", "product")
        ),
        "dropped": dropped,
        "note": (
            f"{dropped} پیشنهاد کنار گذاشته شد چون ربطش به فروشگاه شما روشن نبود."
            if dropped else ""
        ),
    }
