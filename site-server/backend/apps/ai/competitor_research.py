"""Automatic competitor work: crawl their site, find new ones, decide «رقیب کالایی».

Manual entry stays exactly as it was; this module adds three things on top.

1. :func:`save_crawl` — products read from a competitor's own site
   (:mod:`services.research.shop_crawler`) become ``CompetitorProduct`` rows
   with ``source="سایت خودشان"``; a re-crawl updates the same rows by URL.
2. :func:`discover` — for the shop's own products, Digikala and Basalam are
   searched and the *sellers* of matching listings are proposed as competitors.
   Nothing is saved until the owner presses «افزودن» (:func:`add_suggestion`).
3. :func:`match_competitor` — every competitor product is compared with the
   shop's products by :mod:`services.research.product_match` (the replaceable
   «رقیب کالایی» logic). Confident pairs set ``matches``; borderline ones are
   sent to the model for a yes/no **when it is reachable**, and its answer is
   stored next to the heuristic, never instead of it.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from django.utils import timezone

from services.research import product_match, web

from . import research_llm
from .competitor_models import Competitor, CompetitorProduct

logger = logging.getLogger(__name__)

SOURCE_SITE = "سایت خودشان"
SOURCE_LABEL = {"digikala": "دیجی‌کالا", "basalam": "باسلام", "torob": "ترب"}
MARKETPLACE_HOSTS = ("digikala.com", "basalam.com", "torob.com", "divar.ir", "snappshop.ir")

#: How many borderline pairs one model call may judge.
LLM_BATCH = 15


def _store_products(store):
    from apps.products.models import Product

    return list(Product.objects.filter(store=store).only("id", "name", "price", "brand"))


def is_marketplace_url(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    return any(host == h or host.endswith("." + h) for h in MARKETPLACE_HOSTS)


# ---------------------------------------------------------------- matching


def match_competitor(competitor: Competitor, *, use_llm: bool = False, job=None) -> dict:
    """Re-run «رقیب کالایی» for every product of this competitor.

    A ``matches`` the owner set by hand (``raw["matches_manual"]``) is never
    overwritten. Returns the per-competitor verdict plus what the model did.
    """
    ours = _store_products(competitor.store)
    rows = list(competitor.products.all())
    borderline = []
    for row in rows:
        result = product_match.best_match(ours, row.name, row.price_toman)
        match = result.as_dict()
        previous = (row.raw or {}).get("match") or {}
        # Keep an earlier model answer if it was about the same pair.
        if (
            (previous.get("llm") or {}).get("v") == LLM_VERSION
            and previous.get("our_product_id") == match["our_product_id"]
        ):
            match["llm"] = previous["llm"]
        raw = dict(row.raw or {})
        raw["match"] = match
        row.raw = raw
        if not raw.get("matches_manual"):
            llm_same = (match.get("llm") or {}).get("same") is True
            row.matches_id = match["our_product_id"] if (result.confident or llm_same) else None
        row.save(update_fields=["raw", "matches", "updated_at"])
        if match["verdict"] == "maybe" and "llm" not in match:
            borderline.append(row)

    llm_note = ""
    if use_llm and borderline:
        llm_note = confirm_with_llm(competitor, borderline, ours, job=job)
    verdict = product_match.classify_competitor(
        [(r.raw or {}).get("match") for r in competitor.products.all()]
    )
    verdict["llm"] = llm_note
    return verdict


LLM_SYSTEM = (
    "You classify how a competitor's listing relates to a shop's own product. "
    "Answer with one JSON object only. Never guess a fact that is not in the "
    "listing names and prices."
)

#: Bumped when the question changes, so older answers are asked again.
LLM_VERSION = 2


def _llm_prompt(pairs: list[dict]) -> str:
    return (
        "For each pair choose exactly one relation of THEIRS to OURS:\n"
        "- same: the same item (same kind, and same size/model when given).\n"
        "- substitute: a different brand/variant a buyer looking for OURS would "
        "buy INSTEAD (same need, same category).\n"
        "- complement: something used WITH ours or to make/serve it (a machine, "
        "a tool, an accessory, packaging). NOT a substitute.\n"
        "- unrelated: anything else.\n"
        "Example: OURS coffee beans, THEIRS coffee grinder -> complement.\n"
        "Pairs (prices in toman, may be null):\n"
        + json.dumps(pairs, ensure_ascii=False)
        + '\n\nAnswer exactly: {"answers": [{"i": 1, "relation": '
        '"same|substitute|complement|unrelated", "reason": "short Persian reason"}]}'
    )


def confirm_with_llm(competitor, rows, ours, *, job=None) -> str:
    """Ask the model about borderline pairs; store its answer per row."""
    by_id = {p.pk: p for p in ours}
    pairs, index = [], {}
    for i, row in enumerate(rows[:LLM_BATCH], start=1):
        match = (row.raw or {}).get("match") or {}
        product = by_id.get(match.get("our_product_id"))
        if product is None:
            continue
        pairs.append({
            "i": i, "ours": product.name,
            "ours_price": int(product.price) if product.price else None,
            "theirs": row.name, "theirs_price": row.price_toman,
        })
        index[i] = row
    if not pairs:
        return ""
    try:
        parsed = research_llm.ask_json(
            competitor.store, prompt_id="competitor_match_confirm",
            prompt=_llm_prompt(pairs), system=LLM_SYSTEM, job=job,
            validate=lambda p: (isinstance((p or {}).get("answers"), list), ["answers باید فهرست باشد"]),
        )
    except research_llm.LLMUnavailable as exc:
        return f"مدلِ زبانی در دسترس نبود؛ {len(pairs)} موردِ مرزی فقط با قاعده سنجیده شد. ({exc})"
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM confirm failed for competitor %s: %s", competitor.pk, exc)
        return f"پرسش از مدل ناموفق بود: {str(exc)[:160]}"

    answered = 0
    now = timezone.now().isoformat()
    for answer in parsed.get("answers") or []:
        row = index.get(answer.get("i"))
        if row is None:
            continue
        raw = dict(row.raw or {})
        match = dict(raw.get("match") or {})
        relation = str(answer.get("relation", "")).strip().lower()
        if relation not in ("same", "substitute", "complement", "unrelated"):
            continue
        match["llm"] = {
            "relation": relation,
            "same": relation == "same",
            "substitute": relation == "substitute",
            "reason": str(answer.get("reason", ""))[:300],
            "at": now,
            "v": LLM_VERSION,
        }
        raw["match"] = match
        row.raw = raw
        if match["llm"]["same"] and not raw.get("matches_manual"):
            row.matches_id = match.get("our_product_id")
        row.save(update_fields=["raw", "matches", "updated_at"])
        answered += 1
    return f"مدلِ زبانی {answered} موردِ مرزی را بررسی کرد."


# ---------------------------------------------------------------- crawl → rows


def save_crawl(competitor: Competitor, products: list[dict]) -> dict:
    """Upsert crawled products by URL. Returns counts."""
    now = timezone.now()
    existing = {
        (r.raw or {}).get("url") or r.url: r
        for r in competitor.products.filter(source=SOURCE_SITE)
    }
    created = updated = 0
    for item in products:
        url = item.get("url") or ""
        raw = {
            "url": url, "image": item.get("image", ""), "method": item.get("method", ""),
            "currency_how": item.get("currency_how", ""), "raw_price": item.get("raw_price", ""),
            "in_stock": item.get("in_stock"), "brand": item.get("brand", ""),
            "crawled_at": now.isoformat(),
        }
        short_url = url if len(url) <= 200 else ""
        row = existing.get(url)
        if row is None:
            CompetitorProduct.objects.create(
                competitor=competitor, name=item["name"][:200], url=short_url,
                price_toman=item.get("price_toman"), observed_at=now,
                source=SOURCE_SITE, raw=raw,
            )
            created += 1
        else:
            keep = {k: v for k, v in (row.raw or {}).items() if k in ("match", "matches_manual")}
            row.name = item["name"][:200]
            row.url = short_url
            row.price_toman = item.get("price_toman")
            row.observed_at = now
            row.raw = {**raw, **keep}
            row.save(update_fields=["name", "url", "price_toman", "observed_at", "raw", "updated_at"])
            updated += 1
    if products:
        competitor.analysed_at = now
        competitor.save(update_fields=["analysed_at", "updated_at"])
    return {"created": created, "updated": updated}


# ---------------------------------------------------------------- discovery


def _key(name: str) -> str:
    return product_match.normalize(name).replace(" ", "")


def discover(store, *, max_products: int = 6, per_source: int = 20) -> dict:
    """Sellers of the shop's products on Digikala/Basalam, as suggestions.

    A seller is suggested only when at least one of its listings is accepted
    by ``product_match`` as the same or a substitute product, and the evidence
    (their listing, price, link, score) travels with the suggestion.
    """
    from apps.products.models import Product

    products = list(
        Product.objects.filter(store=store, is_available=True).order_by("-updated_at")[:max_products]
    )
    if not products:
        return {"suggestions": [], "sources": [], "note": "اول محصول اضافه کنید؛ رقیب را از روی محصولِ شما پیدا می‌کنیم."}

    known = set()
    for c in Competitor.objects.filter(store=store):
        known.add(_key(c.name))
        if c.website:
            known.add(c.website.rstrip("/").lower())

    sellers: dict[str, dict] = {}
    sources = []
    for product in products:
        price = float(product.price) if product.price else None
        for source in ("digikala", "basalam"):
            try:
                rows = web.SOURCES[source](product.name, per_source)
                sources.append({"source": source, "query": product.name, "ok": True, "count": len(rows)})
            except Exception as exc:  # noqa: BLE001
                sources.append({"source": source, "query": product.name, "ok": False, "error": str(exc)[:200]})
                continue
            for row in rows:
                seller = (row.get("seller") or "").strip()
                if not seller:
                    continue
                result = product_match.match_product(
                    product.name, row["title"], our_price=price, their_price=row.get("price_toman"),
                )
                if result.verdict == "different":
                    continue
                key = f"{source}:{_key(seller)}"
                entry = sellers.setdefault(key, {
                    "key": key, "name": seller, "platform": source,
                    "platform_label": SOURCE_LABEL[source],
                    "website": row.get("seller_url", ""), "city": row.get("seller_city", ""),
                    "already_added": _key(seller) in known
                    or (row.get("seller_url", "").rstrip("/").lower() in known),
                    "items": [], "our_products": [], "best_score": 0.0,
                })
                entry["items"].append({
                    "name": row["title"][:200], "price_toman": row.get("price_toman"),
                    "url": row.get("url", ""), "our_product_id": product.pk,
                    "our_product_name": product.name, "score": result.score,
                    "verdict": result.verdict, "reason": result.reason,
                    "sales_count": row.get("sales_count"), "rating_count": row.get("rating_count"),
                })
                if product.pk not in entry["our_products"]:
                    entry["our_products"].append(product.pk)
                entry["best_score"] = max(entry["best_score"], result.score)

    suggestions = sorted(
        sellers.values(),
        key=lambda e: (e["already_added"], -len(e["our_products"]), -e["best_score"], -len(e["items"])),
    )
    for entry in suggestions:
        same = sum(1 for i in entry["items"] if i["verdict"] == "same")
        entry["why"] = (
            f"در {entry['platform_label']} {len(entry['items'])} کالای مشابهِ "
            f"{len(entry['our_products'])} محصولِ شما را می‌فروشد"
            + (f" ({same} موردِ آن همان کالاست)" if same else " (کالای جایگزین/مشابه)")
        )
    note = ""
    if not web.web_search_configured():
        note = (
            "جست‌وجوی وبِ عمومی (SearXNG/Brave) تنظیم نشده، پس فروشگاه‌هایی که فقط سایتِ "
            "خودشان را دارند این‌جا پیدا نمی‌شوند؛ آن‌ها را دستی با نشانیِ سایت اضافه کنید و «کرال» بزنید."
        )
    return {"suggestions": suggestions[:30], "sources": sources, "note": note,
            "products_checked": [p.name for p in products]}


def add_suggestion(store, suggestion: dict) -> Competitor:
    """Create the competitor from a suggestion and keep its evidence as products."""
    name = str(suggestion.get("name") or "").strip()[:200]
    if not name:
        raise ValueError("نامِ رقیب خالی است.")
    platform = str(suggestion.get("platform") or "")
    website = str(suggestion.get("website") or "")[:200]
    competitor, created = Competitor.objects.get_or_create(
        store=store, name=name,
        defaults={
            "kind": Competitor.Kind.DIRECT, "website": website,
            "notes": f"پیدا شده به‌طورِ خودکار در {SOURCE_LABEL.get(platform, platform)}.",
        },
    )
    if not created and not competitor.is_active:
        competitor.is_active = True
        competitor.save(update_fields=["is_active", "updated_at"])
    now = timezone.now()
    source = SOURCE_LABEL.get(platform, platform)[:32]
    for item in (suggestion.get("items") or [])[:40]:
        item_name = str(item.get("name") or "").strip()[:200]
        if not item_name:
            continue
        url = str(item.get("url") or "")
        try:
            price = int(item["price_toman"]) if item.get("price_toman") not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        CompetitorProduct.objects.update_or_create(
            competitor=competitor, name=item_name, source=source,
            defaults={
                "url": url if len(url) <= 200 else "", "price_toman": price,
                "observed_at": now, "raw": {"url": url, "platform": platform},
            },
        )
    competitor.analysed_at = now
    competitor.save(update_fields=["analysed_at", "updated_at"])
    match_competitor(competitor)
    return competitor
