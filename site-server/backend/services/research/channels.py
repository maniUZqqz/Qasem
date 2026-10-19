"""«کجا بفروشم؟» — is this product sold on Digikala / Basalam / Torob, and how.

For one of the shop's products, each marketplace is searched by the product's
name and only the listings that :mod:`product_match` accepts as the same or a
substitute product are counted. From those, real numbers only:

* how many listings and how many distinct sellers;
* the cheapest and the median observed price (toman);
* a demand signal *as the marketplace publishes it* — Basalam's own sales
  counters; Digikala's number of buyer ratings (labelled as ratings, not sales);
* up to three links, so the owner can open and check.

A marketplace that does not answer, or answers with a bot check, is reported
as unavailable with the reason — never as "nobody sells this there".
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from statistics import median

from . import product_match, web

logger = logging.getLogger(__name__)

CHANNELS = ("digikala", "basalam", "torob")
LABELS = {"digikala": "دیجی‌کالا", "basalam": "باسلام", "torob": "ترب"}
HOME = {
    "digikala": "https://seller.digikala.com/",
    "basalam": "https://vendor.basalam.com/",
    "torob": "https://panel.torob.com/",
}
SEARCH_LIMIT = 20


def _search(channel: str, query: str) -> list[dict]:
    return web.SOURCES[channel](query, SEARCH_LIMIT)


def presence(channel: str, name: str, our_price: float | None) -> dict:
    """One product on one marketplace."""
    out = {"channel": channel, "label": LABELS[channel], "query": name, "ok": False}
    try:
        rows = _search(channel, name)
    except Exception as exc:  # noqa: BLE001 — each marketplace is optional
        out["error"] = str(exc)[:200]
        return out
    out["ok"] = True
    out["results"] = len(rows)
    relevant = []
    for row in rows:
        result = product_match.match_product(
            name, row.get("title", ""), our_price=our_price,
            their_price=row.get("price_toman"),
        )
        if result.verdict != "different":
            relevant.append({**row, "match": result.verdict, "score": result.score})
    prices = sorted(r["price_toman"] for r in relevant if r.get("price_toman"))
    sellers = {r.get("seller") for r in relevant if r.get("seller")}
    out.update({
        "relevant": len(relevant),
        "same": sum(1 for r in relevant if r["match"] == "same"),
        "sellers": len(sellers),
        "min_price": prices[0] if prices else None,
        "median_price": int(median(prices)) if prices else None,
        "max_price": prices[-1] if prices else None,
        "links": [
            {"title": r["title"][:120], "url": r.get("url", ""), "price_toman": r.get("price_toman"),
             "seller": r.get("seller", "")}
            for r in sorted(relevant, key=lambda r: -r["score"])[:3]
        ],
    })
    if channel == "basalam":
        out["demand"] = {
            "kind": "sales",
            "label": "فروشِ ثبت‌شده در باسلام",
            "total": sum(int(r.get("sales_count") or 0) for r in relevant),
            "week": sum(int(r.get("sales_count_week") or 0) for r in relevant),
        }
    elif channel == "digikala":
        out["demand"] = {
            "kind": "ratings",
            "label": "تعدادِ امتیازِ خریداران در دیجی‌کالا (نه تعدادِ فروش)",
            "total": sum(int(r.get("rating_count") or 0) for r in relevant),
        }
    if our_price and out["median_price"]:
        out["our_vs_median_percent"] = round(
            (float(our_price) - out["median_price"]) / out["median_price"] * 100, 1
        )
    return out


def check_products(products, channels=CHANNELS, workers: int = 6) -> dict:
    """``{product_id: {channel: presence}}`` for several products at once.

    ``products`` are objects with ``pk``, ``name`` and ``price``.
    """
    jobs = [(p, c) for p in products for c in channels]
    results: dict[int, dict[str, dict]] = {p.pk: {} for p in products}

    def run(pair):
        product, channel = pair
        price = float(product.price) if getattr(product, "price", None) else None
        return product.pk, channel, presence(channel, product.name, price)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for pk, channel, row in pool.map(run, jobs):
            results[pk][channel] = row
    return results
