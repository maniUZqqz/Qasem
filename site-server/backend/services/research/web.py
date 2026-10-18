"""
Automated competitor research (Phase 6) — code fetches REAL marketplace data;
the store owner does not have to enter competitor info manually.

Sources (public JSON search APIs, accessible inside Iran without VPN):
- Digikala  — primary (verified working; prices returned in RIALS → converted to Toman)
- Torob     — secondary price-comparison source (may be rate-limited; fails gracefully)

Every fetch is recorded with source, query, timestamp and ok/error status, so
observed facts stay separate from AI conclusions (spec §20).
"""
import logging

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 20


def _rial_to_toman(value):
    try:
        return int(value) // 10
    except (TypeError, ValueError):
        return None


def search_digikala(query: str, limit: int = 8) -> list[dict]:
    response = requests.get(
        "https://api.digikala.com/v1/search/",
        params={"q": query},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    products = response.json().get("data", {}).get("products", [])[:limit]
    items = []
    for product in products:
        price = (product.get("default_variant") or {}).get("price") or {}
        uri = (product.get("url") or {}).get("uri", "")
        items.append(
            {
                "source": "digikala",
                "title": product.get("title_fa", ""),
                "price_toman": _rial_to_toman(price.get("selling_price")),
                "rrp_toman": _rial_to_toman(price.get("rrp_price")),
                "url": f"https://www.digikala.com{uri}" if uri else "",
            }
        )
    return [item for item in items if item["title"]]


def search_torob(query: str, limit: int = 8) -> list[dict]:
    response = requests.get(
        "https://api.torob.com/v4/base-product/search/",
        params={"query": query, "size": limit},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    results = response.json().get("results", [])[:limit]
    items = []
    for product in results:
        items.append(
            {
                "source": "torob",
                "title": product.get("name1", ""),
                "price_toman": _rial_to_toman(product.get("price")),
                "shops": product.get("shop_text", ""),
                "url": (
                    f"https://torob.com{product.get('web_client_absolute_url', '')}"
                    if product.get("web_client_absolute_url")
                    else ""
                ),
            }
        )
    return [item for item in items if item["title"]]


SOURCES = {"digikala": search_digikala, "torob": search_torob}


# ------------------------------------------------------------------ general web
# Competitors are often independent websites, not marketplace listings. We only
# use providers that are MEANT to be queried programmatically, so nothing gets
# blocked: a self-hosted SearXNG instance or the official Brave Search API.
# Direct scraping of Google/competitor sites is deliberately NOT implemented.


class WebSearchNotConfigured(Exception):
    pass


def _search_searxng(query: str, limit: int = 8) -> list[dict]:
    from django.conf import settings

    base = settings.UPMARKET_RESEARCH["SEARXNG_BASE_URL"]
    response = requests.get(
        f"{base}/search",
        params={"q": query, "format": "json", "language": "fa", "safesearch": 1},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    results = response.json().get("results", [])[:limit]
    return [
        {
            "source": "web:searxng",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": (item.get("content") or "")[:300],
            "price_toman": None,
        }
        for item in results
        if item.get("title")
    ]


def _search_brave(query: str, limit: int = 8) -> list[dict]:
    from django.conf import settings

    api_key = settings.UPMARKET_RESEARCH["BRAVE_API_KEY"]
    if not api_key:
        raise WebSearchNotConfigured("BRAVE_API_KEY is not set")
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={**HEADERS, "X-Subscription-Token": api_key, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    results = (response.json().get("web") or {}).get("results", [])[:limit]
    return [
        {
            "source": "web:brave",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": (item.get("description") or "")[:300],
            "price_toman": None,
        }
        for item in results
        if item.get("title")
    ]


def search_web(query: str, limit: int = 8) -> list[dict]:
    """General web search through the configured provider (searxng | brave)."""
    from django.conf import settings

    provider = settings.UPMARKET_RESEARCH["WEB_SEARCH_PROVIDER"]
    if provider == "searxng":
        return _search_searxng(query, limit)
    if provider == "brave":
        return _search_brave(query, limit)
    raise WebSearchNotConfigured(
        "WEB_SEARCH_PROVIDER is not configured (set searxng or brave in .env)"
    )


def research_product(query: str, limit_per_source: int = 8, web_query: str = "") -> dict:
    """Run all sources; failures are recorded, never fatal. Returns real data only."""
    from django.conf import settings

    fetched_at = timezone.now().isoformat()
    sources_report = []
    items = []
    for name, fetcher in SOURCES.items():
        try:
            found = fetcher(query, limit_per_source)
            items.extend(found)
            sources_report.append(
                {"source": name, "query": query, "fetched_at": fetched_at, "ok": True,
                 "count": len(found)}
            )
        except Exception as exc:  # noqa: BLE001 — each source is optional
            logger.warning("Research source %s failed for %r: %s", name, query, exc)
            sources_report.append(
                {"source": name, "query": query, "fetched_at": fetched_at, "ok": False,
                 "error": str(exc)[:300]}
            )

    # general web (competitor sites) — only when a proper provider is configured
    provider = settings.UPMARKET_RESEARCH["WEB_SEARCH_PROVIDER"]
    effective_web_query = web_query or query
    if provider and provider != "none":
        try:
            found = search_web(effective_web_query, limit_per_source)
            items.extend(found)
            sources_report.append(
                {"source": f"web:{provider}", "query": effective_web_query,
                 "fetched_at": fetched_at, "ok": True, "count": len(found)}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Web search (%s) failed for %r: %s", provider, effective_web_query, exc)
            sources_report.append(
                {"source": f"web:{provider}", "query": effective_web_query,
                 "fetched_at": fetched_at, "ok": False, "error": str(exc)[:300]}
            )
    else:
        sources_report.append(
            {"source": "web", "query": effective_web_query, "fetched_at": fetched_at,
             "ok": False, "skipped": True,
             "error": "WEB_SEARCH_PROVIDER تنظیم نشده (searxng یا brave)"}
        )
    return {"fetched_at": fetched_at, "query": query, "sources": sources_report, "items": items}
