"""What people are talking about right now. §6 of `ایده‌ها پنل.md`.

**Where these actually come from, and what we refuse to pretend.**

§6 asks about «ترندهای ایرانی» and «ترندهای خارجی», and also about what is
trending *on Instagram and TikTok*. The first two are obtainable: Google
publishes a daily-trends RSS feed per country, meant to be fetched, and the
shop's configured web search can expand any topic. The third is not: Instagram
and TikTok trending data is behind partner APIs nobody gets by asking, and the
scraping alternatives break weekly and get the scraper blocked.

So this module fetches what it can fetch and `available()` says plainly which
sources are live. A page that showed «ترندهای اینستاگرام» filled with numbers
derived from a Google feed would be a fabrication a shop makes decisions on.

**A trend has a clock.** Every row carries when it was seen, and `is_stale`
answers honestly after that. «این هفته ترند است» about something from eleven
days ago is worse than saying nothing — the shop films a video for a moment
that has passed.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from xml.etree import ElementTree

import requests

from .web import HEADERS, TIMEOUT, WebSearchNotConfigured, search_web

logger = logging.getLogger(__name__)

#: Google's own daily-trends feed. A published RSS endpoint, not a scrape — it
#: exists to be fetched and does not break when their markup changes.
RSS = "https://trends.google.com/trending/rss"

#: The regions §6 names: home, and abroad for ideas that travel.
REGIONS = {
    "IR": "ایران",
    "US": "آمریکا",
    "TR": "ترکیه",
    "AE": "امارات",
}

#: After this a trend is history, and presenting it as current makes a shop film
#: for a moment that has passed.
FRESH_FOR = timedelta(hours=36)

#: Platforms §6 asks about that we cannot honestly measure, and why. Shown to
#: the shop rather than silently omitted, so nobody assumes we checked.
UNAVAILABLE = {
    "instagram": (
        "اینستاگرام داده‌ی ترند را فقط به شرکای رسمی می‌دهد. هر عددی که اینجا "
        "نشان می‌دادیم حدس بود."
    ),
    "tiktok": (
        "تیک‌تاک هم همین‌طور، و در ایران هم فیلتر است. ترندهایش را نداریم."
    ),
}

_TAG = re.compile(r"<[^>]+>")


class TrendsUnavailable(Exception):
    """No trend source answered. Different from "nothing is trending"."""


def _clean(text: str | None) -> str:
    return _TAG.sub("", text or "").strip()


def fetch_region(region: str = "IR", limit: int = 20) -> list[dict]:
    """Today's rising searches in one country.

    Returns rows, never raises for an empty result: a country with nothing
    notable today is a real answer and should not look like a broken feed.
    """
    if region not in REGIONS:
        raise ValueError(f"Unknown region {region!r}")

    try:
        response = requests.get(
            RSS, params={"geo": region}, headers=HEADERS, timeout=TIMEOUT,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except (requests.RequestException, ElementTree.ParseError) as exc:
        raise TrendsUnavailable(
            f"ترندهای {REGIONS[region]} گرفته نشد: {exc}"
        ) from exc

    namespace = "{https://trends.google.com/trending/rss}"
    rows = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        if not title:
            continue
        traffic = _clean(item.findtext(f"{namespace}approx_traffic"))
        picture = item.findtext(f"{namespace}picture") or ""
        related = [
            _clean(news.findtext("{*}news_item_title"))
            for news in item.findall(f"{namespace}news_item")
        ]
        rows.append({
            "title": title,
            "region": region,
            "region_title": REGIONS[region],
            # Google's own wording ("20K+"), kept verbatim rather than parsed
            # into a number we would then have to defend.
            "traffic": traffic,
            "image": picture,
            "context": [r for r in related if r][:3],
            "source": "google_trends",
        })
        if len(rows) >= limit:
            break
    return rows


def fetch(regions: list[str] | None = None, limit: int = 20) -> dict:
    """Several regions at once. One failing does not lose the others."""
    wanted = [r for r in (regions or ["IR"]) if r in REGIONS] or ["IR"]
    found, problems = [], []
    for region in wanted:
        try:
            found += fetch_region(region, limit=limit)
        except TrendsUnavailable as exc:
            logger.info("Trend fetch failed for %s: %s", region, exc)
            problems.append(str(exc))
    return {"trends": found, "problems": problems}


def expand(topic: str, limit: int = 5) -> list[dict]:
    """What is being written about this topic, through the configured search.

    Optional by design. Trends without context are still usable — «پاییز» tells
    a clothing shop something on its own — so a shop with no search provider
    configured loses the detail, not the feature.
    """
    try:
        return search_web(topic, limit=limit)
    except (WebSearchNotConfigured, requests.RequestException) as exc:
        logger.info("Could not expand trend %r: %s", topic, exc)
        return []


def available() -> list[dict]:
    """Which sources are live, and which are not and why.

    Listed rather than hidden: a shop that cannot see Instagram trends should
    know we did not check, not conclude that nothing is happening there.
    """
    from django.conf import settings

    provider = settings.UPMARKET_RESEARCH.get("WEB_SEARCH_PROVIDER")
    rows = [
        {
            "key": "google_trends",
            "title": "ترندهای جست‌وجو (گوگل)",
            "live": True,
            "note": f"ایران و {len(REGIONS) - 1} کشور دیگر، روزانه",
        },
        {
            "key": "web_search",
            "title": "جست‌وجوی وب",
            "live": bool(provider),
            "note": (
                f"از طریق {provider}" if provider
                else "تنظیم نشده — ترندها بدون جزئیات نشان داده می‌شوند"
            ),
        },
    ]
    rows += [
        {"key": key, "title": key.title(), "live": False, "note": note}
        for key, note in UNAVAILABLE.items()
    ]
    return rows
