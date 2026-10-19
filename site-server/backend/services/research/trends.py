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

#: The regions §6 names: home, and abroad for ideas that travel. Europe was
#: added after the owner's example («الان انقلاب مسمون‌ها در فرانسه ترنده»):
#: fashion and food trends usually show up in FR/GB/DE searches first.
REGIONS = {
    "IR": "ایران",
    "US": "آمریکا",
    "GB": "انگلیس",
    "FR": "فرانسه",
    "DE": "آلمان",
    "TR": "ترکیه",
    "AE": "امارات",
}

#: Pseudo-regions. ``ALL`` = every country above, grouped («جهانی»);
#: ``IG`` = Instagram, read indirectly from dated articles (see fetch_instagram).
ALL = "ALL"
INSTAGRAM = "IG"
REGION_TITLES = {**REGIONS, INSTAGRAM: "اینستاگرام", ALL: "جهانی"}

#: After this a trend is history, and presenting it as current makes a shop film
#: for a moment that has passed.
FRESH_FOR = timedelta(hours=36)

#: Platforms §6 asks about that we cannot honestly measure, and why. Shown to
#: the shop rather than silently omitted, so nobody assumes we checked.
UNAVAILABLE = {
    "instagram": (
        "آمارِ خودِ اینستاگرام (تعدادِ پست/بازدیدِ هشتگ) را فقط شرکای رسمی می‌گیرند و "
        "سایتِ اینستاگرام از این سرور هم باز نمی‌شود. هیچ عددی از اینستاگرام نشان نمی‌دهیم."
    ),
    "tiktok": (
        "تیک‌تاک هم همین‌طور، و در ایران هم فیلتر است. ترندهایش را نداریم."
    ),
}

#: Searches for the indirect Instagram source: (query, hl, gl).
INSTAGRAM_QUERIES = (
    ("ترند اینستاگرام", "fa", "IR"),
    ("چالش اینستاگرام", "fa", "IR"),
    ("Instagram trend", "en-US", "US"),
    ("trending reels", "en-US", "US"),
    ("viral TikTok Instagram trend", "en-GB", "GB"),
)
#: Older than this, an article about "what is trending" is history.
INSTAGRAM_MAX_AGE_DAYS = 7
_TREND_WORDS = re.compile(
    r"ترند|وایرال|چالش|ریلز|هشتگ|trend|viral|reel|challenge|hashtag|#", re.I,
)
_HASHTAG = re.compile(r"#([\w\u0600-\u06FF]{2,40})")

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

    return parse_rss(response.content, region, limit=limit)


def parse_rss(content: bytes | str, region: str, limit: int = 20) -> list[dict]:
    """Google daily-trends RSS → rows, with the news headlines that explain
    *why* each search is rising (``ht:news_item`` title/url/source)."""
    root = content if isinstance(content, ElementTree.Element) else ElementTree.fromstring(content)
    namespace = "{https://trends.google.com/trending/rss}"
    rows = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        if not title:
            continue
        traffic = _clean(item.findtext(f"{namespace}approx_traffic"))
        picture = item.findtext(f"{namespace}picture") or ""
        news = []
        for node in item.findall(f"{namespace}news_item"):
            headline = _clean(node.findtext(f"{namespace}news_item_title"))
            if not headline:
                continue
            news.append({
                "title": headline,
                "url": (node.findtext(f"{namespace}news_item_url") or "").strip(),
                "source": _clean(node.findtext(f"{namespace}news_item_source")),
            })
        rows.append({
            "title": title,
            "region": region,
            "region_title": REGION_TITLES.get(region, region),
            # Google's own wording ("20K+"), kept verbatim rather than parsed
            # into a number we would then have to defend.
            "traffic": traffic,
            "image": picture,
            "context": news[:4],
            "source": "google_trends",
        })
        if len(rows) >= limit:
            break
    return rows


def fetch_instagram(limit: int = 15) -> list[dict]:
    """Best-effort «ترندِ اینستاگرام», honestly labelled.

    There is no public Instagram trending API, and instagram.com is not
    reachable from this server. What *is* reachable: dated articles and videos
    *about* what is trending on Instagram/Reels, through Google News' published
    RSS search (and the configured web search, when there is one). Each row is
    one such headline with its publisher, date and link; hashtags are taken only
    from the headline text itself. No view or post counts — we do not have them.
    """
    from datetime import datetime, timezone as dt_timezone

    from .web import google_news, web_search_configured

    cutoff = datetime.now(dt_timezone.utc) - timedelta(days=INSTAGRAM_MAX_AGE_DAYS)
    rows, seen, errors = [], set(), []
    for query, hl, gl in INSTAGRAM_QUERIES:
        try:
            found = google_news(query, hl=hl, gl=gl, limit=15)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{query}: {exc}")
            continue
        for item in found:
            published = item.get("published")
            if not published:
                continue
            try:
                when = datetime.fromisoformat(published)
            except ValueError:
                continue
            if when < cutoff:
                continue
            title = item["title"]
            if not _TREND_WORDS.search(title):
                continue
            key = title.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "title": title[:200],
                "region": INSTAGRAM,
                "region_title": REGION_TITLES[INSTAGRAM],
                "traffic": "",
                "image": "",
                "context": [{
                    "title": title, "url": item.get("url", ""),
                    "source": item.get("publisher", ""), "published": published,
                    "hashtags": _HASHTAG.findall(title)[:5], "query": query,
                }],
                "source": "instagram_news",
                "published": published,
            })
    if web_search_configured():
        for query in ("ترند اینستاگرام این هفته", "instagram trending reels this week"):
            try:
                for item in search_web(query, limit=5):
                    if item.get("title") and item["title"].lower()[:80] not in seen:
                        seen.add(item["title"].lower()[:80])
                        rows.append({
                            "title": item["title"][:200], "region": INSTAGRAM,
                            "region_title": REGION_TITLES[INSTAGRAM], "traffic": "",
                            "image": "", "source": "instagram_web",
                            "context": [{"title": item.get("snippet", "")[:200], "url": item.get("url", ""),
                                         "source": item.get("source", ""), "query": query}],
                        })
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{query}: {exc}")
    rows.sort(key=lambda r: r.get("published") or "", reverse=True)
    if not rows and errors:
        raise TrendsUnavailable("منبعِ غیرمستقیمِ اینستاگرام جواب نداد: " + "؛ ".join(errors)[:300])
    return rows[:limit]


def expand_regions(regions: list[str] | None) -> list[str]:
    """``ALL`` → every country; unknown keys dropped; IR when nothing is left."""
    wanted = list(regions or ["IR"])
    if ALL in wanted:
        wanted = list(REGIONS) + [r for r in wanted if r == INSTAGRAM]
    out = [r for r in dict.fromkeys(wanted) if r in REGIONS or r == INSTAGRAM]
    return out or ["IR"]


def fetch(regions: list[str] | None = None, limit: int = 20) -> dict:
    """Several regions at once. One failing does not lose the others."""
    wanted = expand_regions(regions)
    found, problems = [], []
    for region in wanted:
        try:
            if region == INSTAGRAM:
                found += fetch_instagram(limit=limit)
            else:
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
    from .web import web_search_configured

    from django.conf import settings

    provider = settings.UPMARKET_RESEARCH.get("WEB_SEARCH_PROVIDER")
    configured = web_search_configured()
    rows = [
        {
            "key": "google_trends",
            "title": "ترندهای جست‌وجو (گوگل)",
            "live": True,
            "note": (
                f"{len(REGIONS)} کشور ({'، '.join(REGIONS.values())})، روزانه، "
                "با تیترِ خبرهایی که دلیلِ ترند شدن را نشان می‌دهند"
            ),
        },
        {
            "key": "instagram_news",
            "title": "اینستاگرام (غیرمستقیم)",
            "live": True,
            "note": (
                f"از تیترِ مقاله‌ها و ویدیوهای {INSTAGRAM_MAX_AGE_DAYS} روزِ اخیر درباره‌ی ترندهای "
                "اینستاگرام/ریلز (جست‌وجوی خبرِ گوگل). داده‌ی خودِ اینستاگرام نیست؛ "
                "عددِ بازدید یا پست نشان نمی‌دهیم."
            ),
        },
        {
            "key": "web_search",
            "title": "جست‌وجوی وب",
            "live": configured,
            "note": (
                f"از طریق {provider}" if configured
                else "تنظیم نشده (SearXNG یا Brave) — ترندها بدونِ جست‌وجوی تکمیلی نشان داده می‌شوند"
            ),
        },
    ]
    rows += [
        {"key": key, "title": {"instagram": "آمارِ مستقیمِ اینستاگرام", "tiktok": "TikTok"}.get(key, key.title()),
         "live": False, "note": note}
        for key, note in UNAVAILABLE.items()
    ]
    return rows
