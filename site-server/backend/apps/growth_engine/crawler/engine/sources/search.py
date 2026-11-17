"""Web search result pages as a source: Brave (and, with the owner's key, Brave's official API), Bing, DuckDuckGo (HTML), Mojeek - whichever answers from where the server is.

What was tested from the Iranian server (2026-11-16 and 2026-11-17; details in docs/growth-engine/modules/crawler.md):

    Brave (search.brave.com) the ONLY engine that answers a Persian local-business query with relevant results (20 per page) and understands
                            ``site:instagram.com``. It rate-limits an address hard: the first request after a pause is answered, the next
                            ones get HTTP 403 for many minutes (and every request made while blocked prolongs the block). So it is asked
                            slowly (``delay`` below) and, at the first «blocked» answer, left alone for ``COOLDOWN_MIN`` minutes (shared by all runs)
    Bing ................... answers, but for Persian queries (and ``site:``) with music pages and prayers: only used for ENGLISH queries
    DuckDuckGo (html/lite)  HTTP 202 «anomaly» page (a bot check) - skipped, retried after the cooldown
    Mojeek / Ecosia / Qwant / Yep / Kagi  HTTP 403;  Google, Yandex: «turn on JavaScript» / captcha;  Startpage, Yahoo: timeout;  public SearXNG: 429

So the engine list is an ordered list of adapters; each is asked in turn, a «blocked / captcha / empty» answer is recorded with a cooldown
(the panel shows the engine health) and the next one is tried. With the owner's Brave API key (the Growth Engine's provider settings) the
official API is used first: no page is scraped and the plan's own limits apply.

Rules: a handful of queries per run (``max_search_queries``), 25 s between two requests to Brave, an honest User-Agent, results are only ever
READ as links + titles + snippets - nothing is opened except what the plan later asks for (and that is robots.txt-checked). A result that is a
marketplace / a news site / a directory / an article or list («بهترین ... در تهران») is dropped; an Instagram profile is kept as an Instagram page.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.integrations import safe_http as sh

from ... import presets
from .. import place, textnorm
from ..candidates import Found
from .base import RetryLater, SourceContext, TaskSpec

SOURCE = "search"
ENGINE_DELAY = 6.0
MAX_RESULTS_PER_QUERY = 20
COOLDOWN_MIN = 30
STATE_KEY = "crawler_engines"

#: result hosts that are never a business's own site (marketplaces, social, encyclopedias, news, video, code ...)
BLOCKED_HOSTS = {
    "digikala.com", "torob.com", "divar.ir", "sheypoor.com", "basalam.com", "emalls.ir", "wikipedia.org", "wikiwand.com", "wikimedia.org",
    "aparat.com", "youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com", "linkedin.com", "pinterest.com", "tiktok.com", "telegram.org",
    "t.me", "github.com", "medium.com", "reddit.com", "quora.com", "bing.com", "microsoft.com", "google.com", "duckduckgo.com", "genius.com",
    "spotify.com", "shazam.com", "musixmatch.com", "isna.ir", "irna.ir", "tasnimnews.com", "farsnews.ir", "khabaronline.ir", "tripadvisor.com",
    "booking.com", "snapp.ir", "tapsi.ir", "digiato.com", "zoomit.ir", "namnak.com", "telewebion.com", "namava.ir", "filimo.com", "eitaa.com",
    "rubika.ir", "ble.ir", "bale.ai", "sapp.ir", "gap.im", "soroush-hamrah.com", "apple.com", "play.google.com", "cafebazaar.ir", "myket.ir",
    "snappfood.ir", "blogfa.com", "mihanblog.com", "persianblog.ir", "rozblog.com", "blogger.com", "wordpress.com", "tumblr.com",
}
#: pages that LIST many businesses; they are followed by the directory source instead of being taken as one business
DIRECTORY_HOSTS = {"badanfit.ir": "badanfit", "gymcenter.ir": "gymcenter"}
_IG_RESERVED = {"p", "reel", "reels", "explore", "accounts", "stories", "tv", "direct", "about", "legal", "web", "developer", "directory", "locations", "tags"}


@dataclass
class Hit:
    url: str
    title: str
    snippet: str
    engine: str


# --------------------------------------------------------------------------- result-page parsers


def unwrap_bing(href: str) -> str:
    href = unescape(href)
    m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", href)
    if m:
        b = m.group(1)
        b += "=" * (-len(b) % 4)
        try:
            return base64.urlsafe_b64decode(b).decode("utf-8", "replace")
        except (ValueError, UnicodeError):
            return href
    return href


def parse_bing(html: str) -> list[Hit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: list[Hit] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a") or li.find("a", href=True)
        if not a or not a.get("href"):
            continue
        snippet = li.select_one(".b_caption p, p")
        hits.append(Hit(unwrap_bing(a["href"]), nz.normalize_text(a.get_text(" ", strip=True)), nz.normalize_text(snippet.get_text(" ", strip=True)) if snippet else "", "bing"))
    return hits


def parse_duckduckgo(html: str) -> list[Hit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: list[Hit] = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if "uddg=" in href:
            href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
        box = a.find_parent(class_=re.compile("result"))
        snippet = box.select_one(".result__snippet") if box else None
        hits.append(Hit(href, nz.normalize_text(a.get_text(" ", strip=True)), nz.normalize_text(snippet.get_text(" ", strip=True)) if snippet else "", "duckduckgo"))
    return hits


def parse_mojeek(html: str) -> list[Hit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: list[Hit] = []
    for li in soup.select("ul.results-standard li"):
        a = li.select_one("a.title") or li.select_one("h2 a") or li.find("a", href=True)
        if not a or not a.get("href"):
            continue
        sn = li.select_one("p.s")
        hits.append(Hit(a["href"], nz.normalize_text(a.get_text(" ", strip=True)), nz.normalize_text(sn.get_text(" ", strip=True)) if sn else "", "mojeek"))
    return hits


def _text(node) -> str:
    return nz.normalize_text(node.get_text(" ", strip=True)) if node is not None else ""


def parse_brave(html: str) -> list[Hit]:
    """Brave's result page: every organic result is a ``div.snippet[data-type=web]`` with its real address in the first absolute link, the title in
    ``.title`` and the description in ``.snippet-description`` / ``.content``. Tracking links (``/go/...``) are ignored: only absolute addresses count."""
    soup = BeautifulSoup(html, "html.parser")
    boxes = soup.select('div.snippet[data-type="web"]') or soup.select("#results div.snippet")
    hits: list[Hit] = []
    for box in boxes:
        a = box.select_one('a[href^="http"]')
        if a is None:
            continue
        title = _text(box.select_one(".title, .snippet-title, .search-snippet-title")) or _text(a)
        desc = box.select_one(".snippet-description, .generic-snippet .content, .content, .description")
        snippet = _text(desc)
        if not snippet:
            snippet = nz.normalize_text(_text(box).replace(title, "", 1))[:300]
        hits.append(Hit(a["href"], title, snippet, "brave"))
    return hits


def parse_brave_api(text: str) -> list[Hit]:
    try:
        rows = (((json.loads(text) or {}).get("web") or {}).get("results")) or []
    except ValueError:
        return []
    return [Hit(str(r.get("url") or ""), nz.normalize_text(str(r.get("title") or "")), nz.normalize_text(str(r.get("description") or "")), "brave_api")
            for r in rows if isinstance(r, dict) and r.get("url")]


#: ``fa``: answers a Persian query with relevant results · ``site_op``: understands ``site:instagram.com`` · ``delay``: seconds between two requests
ENGINES = {
    "brave_api": {"label": "Brave (کلیدِ API)", "url": "https://api.search.brave.com/res/v1/web/search", "params": lambda q: {"q": q, "count": "20", "search_lang": "fa", "country": "ir"},
                  "parse": parse_brave_api, "fa": True, "site_op": True, "delay": 1.2, "needs_key": True},
    "brave": {"label": "Brave", "url": "https://search.brave.com/search", "params": lambda q: {"q": q, "source": "web"}, "parse": parse_brave, "fa": True, "site_op": True, "delay": 25.0},
    "bing": {"label": "Bing", "url": "https://www.bing.com/search", "params": lambda q: {"q": q, "setlang": "en", "count": "20"}, "parse": parse_bing, "fa": False, "site_op": False, "delay": ENGINE_DELAY},
    "duckduckgo": {"label": "DuckDuckGo", "url": "https://html.duckduckgo.com/html/", "params": lambda q: {"q": q, "kl": "ir-fa"}, "parse": parse_duckduckgo, "fa": True, "site_op": True, "delay": ENGINE_DELAY},
    "mojeek": {"label": "Mojeek", "url": "https://www.mojeek.com/search", "params": lambda q: {"q": q}, "parse": parse_mojeek, "fa": True, "site_op": False, "delay": ENGINE_DELAY},
}
DEFAULT_ORDER = ("brave_api", "brave", "bing", "duckduckgo", "mojeek")
USER_ENGINES = ("bing", "duckduckgo", "mojeek", "brave")  # what a mission's ``search_engines`` may name


def looks_blocked(status: int, body: str) -> str:
    """'' when the page is a normal result page, else a short reason (anomaly / captcha / forbidden ...)."""
    low = (body or "")[:6000].lower()
    if status in (202, 403, 429):
        return f"HTTP {status}"
    if "anomaly" in low or "captcha" in low or "unusual traffic" in low or "g-recaptcha" in low:
        return "captcha / bot check"
    return ""


# --------------------------------------------------------------------------- engine health: cooldowns shared by every run


def brave_api_key() -> str:
    """The owner's Brave Search API key from the Growth Engine's provider settings (never logged, never returned)."""
    from apps.growth_engine.discovery.models import ProviderConfig

    row = ProviderConfig.objects.filter(provider="brave").first()
    return str((row.secrets or {}).get("api_key") or "") if row and row.enabled else ""


def _state_row():
    from apps.growth_engine.discovery.models import ProviderConfig

    row, _ = ProviderConfig.objects.get_or_create(provider=STATE_KEY)
    return row


def cooldowns() -> dict[str, dict]:
    """``{engine: {"until": ISO time, "reason": text}}`` of the engines that are resting right now."""
    from apps.growth_engine.discovery.models import ProviderConfig

    row = ProviderConfig.objects.filter(provider=STATE_KEY).first()
    out: dict[str, dict] = {}
    now = timezone.now()
    for engine, info in ((row.config or {}).get("cooldown") or {}).items() if row else []:
        try:
            until = datetime.fromisoformat(str(info.get("until")))
        except (TypeError, ValueError):
            continue
        if until > now:
            out[engine] = {"until": until.isoformat(timespec="seconds"), "reason": str(info.get("reason") or "")}
    return out


def start_cooldown(engine: str, reason: str, minutes: int = COOLDOWN_MIN) -> None:
    row = _state_row()
    config = dict(row.config or {})
    cool = dict(config.get("cooldown") or {})
    cool[engine] = {"until": (timezone.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "reason": reason[:120]}
    config["cooldown"] = {k: v for k, v in cool.items() if k in ENGINES}
    row.config = config
    row.save(update_fields=["config", "updated_at"])


def save_probe(engines: dict) -> dict:
    row = _state_row()
    config = dict(row.config or {})
    config.update({"at": timezone.now().isoformat(timespec="seconds"), "engines": engines})
    row.config = config
    row.save(update_fields=["config", "updated_at"])
    return config


HTML_ACCEPT = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}


def run_query(ctx: SourceContext, engine_key: str, query: str) -> tuple[list[Hit], str]:
    """(hits, problem). ``problem`` is '' on success. A blocked answer (403 / 429 / 202 / captcha) puts the engine to rest for ``COOLDOWN_MIN`` minutes (for every run)."""
    spec = ENGINES[engine_key]
    api = bool(spec.get("needs_key"))
    if api:
        key = brave_api_key()
        if not key:
            return [], "کلیدِ API وارد نشده"
        headers = {"X-Subscription-Token": key, "Accept": "application/json"}
    else:
        headers = HTML_ACCEPT  # the fetcher's default «Accept: application/json» is for APIs; a result page is HTML
    result = ctx.web.api(spec["url"], spec["params"](query), ttl_hours=24, delay=spec["delay"], retries=0, max_bytes=2_000_000, headers=headers)
    if api:
        if result.status in (401, 403):
            return [], "کلیدِ API پذیرفته نشد"
        if result.status == 429:
            start_cooldown(engine_key, "HTTP 429 (سهمیه)")
            return [], "سهمیهٔ API تمام یا پرتکرار شد"
        if result.outcome != sh.OK:
            return [], result.label
        hits = parse_brave_api(result.text)
        return hits[:MAX_RESULTS_PER_QUERY], "" if hits else "نتیجه‌ای نبود"
    blocked = looks_blocked(result.status, result.text if result.outcome == sh.OK else "")
    if blocked:
        start_cooldown(engine_key, blocked)
        return [], blocked
    if result.outcome != sh.OK:
        return [], result.label
    hits = spec["parse"](result.text)
    return hits[:MAX_RESULTS_PER_QUERY], "" if hits else "نتیجه‌ای نبود"


def usable_engines(spec: dict, *, persian: bool, site_op: bool) -> tuple[list[str], dict[str, str]]:
    """(engines to ask now, in order · why each other one is not asked). Resting engines and engines that cannot answer this kind of query are left out."""
    asked = [e for e in (spec.get("search_engines") or []) if e in ENGINES]
    order = asked or list(DEFAULT_ORDER)
    resting = cooldowns()
    chosen: list[str] = []
    skipped: dict[str, str] = {}
    for key in order:
        meta = ENGINES[key]
        if meta.get("needs_key") and not brave_api_key():
            continue
        if persian and not meta["fa"]:
            skipped[key] = "برای پرسِ فارسی نتیجهٔ درست نمی‌دهد"
        elif site_op and not meta["site_op"]:
            skipped[key] = "عملگرِ site: را نمی‌فهمد"
        elif key in resting:
            skipped[key] = f"در استراحت تا {timezone.localtime(datetime.fromisoformat(resting[key]['until'])).strftime('%H:%M')} ({resting[key]['reason']})"
        else:
            chosen.append(key)
    return chosen, skipped


# --------------------------------------------------------------------------- relevance & classification


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def blocked_host(host: str) -> bool:
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS) or textnorm.is_foreign_site(host)


def instagram_handle(url: str) -> str:
    parts = urlsplit(url)
    if host_of(url) not in ("instagram.com", "instagr.am"):
        return ""
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) == 1 and segs[0].lower() not in _IG_RESERVED and re.fullmatch(r"[A-Za-z0-9._]{1,30}", segs[0]):
        return segs[0].lower()
    return ""


def relevant(hit: Hit, *, words: list[str], city: str, city_en: str = "") -> bool:
    """A result is relevant when its title / snippet / address names the KIND of business (or a query word) and the place (or is a .ir site)."""
    hay = nz.normalize_text(f"{hit.title} {hit.snippet} {unquote(hit.url)}").casefold()
    kind_ok = bool(textnorm.name_has_word(hay, [w for w in words if w]))  # a Latin word counts only as a whole word («pt» is not in «script»)
    city_ok = (nz.normalize_text(city).casefold() in hay if city else True) or bool(city_en and city_en.casefold() in hay)
    iran_ok = host_of(hit.url).endswith(".ir") or "ایران" in hay or "iran" in hay
    return kind_ok and (city_ok or iran_ok)


def relevant_instagram(hit: Hit, *, words: list[str], cities: list[str]) -> bool:
    """An Instagram profile found by a hashtag / location query: its title or bio line must name the kind of business (the query's words) and must NOT
    name another city than the asked ones. (A profile whose title names no city at all is kept: where it is, its own page says later.)"""
    hay = nz.normalize_text(f"{hit.title} {hit.snippet}").casefold()
    if not textnorm.name_has_word(hay, [w for w in words if w]):
        return False
    named = place.address_cities(f"{hit.title} {hit.snippet}", street_filter=False)
    wanted = {place.canonical_city(c) for c in cities if c}
    return not (named and wanted and not (set(named) & wanted))


_TITLE_SPLIT = re.compile(r"\s*[|\-–—•·»«:]\s*")
_FOLLOWERS = re.compile(r"([\d][\d.,]*\s*[KkMm]?)\s+(?:Followers|دنبال‌کننده|فالوور)", re.I)
_POSTS = re.compile(r"([\d][\d.,]*)\s+(?:Posts|پست)", re.I)


def name_from_title(title: str, host: str) -> str:
    """«باشگاه آرمان | تهران - بدنسازی» -> «باشگاه آرمان». Falls back to the host."""
    parts = [p for p in _TITLE_SPLIT.split(nz.normalize_text(title)) if p and len(p) >= 3]
    if parts:
        return parts[0][:120]
    return host


def count_of(text: str) -> int | None:
    """«1,234» -> 1234 · «12.5K» -> 12500 · «1.2M» -> 1200000 (a public counter of an Instagram profile as the search engine shows it)."""
    raw = nz.to_ascii_digits(text or "").replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KkMm]?)", raw)
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()])


def instagram_numbers(hit: Hit) -> dict:
    """The public follower / post counters the engine shows in an Instagram result («1,234 Followers, 56 Following, 78 Posts»). Only what is printed there."""
    out: dict = {}
    m = _FOLLOWERS.search(hit.snippet or "") or _FOLLOWERS.search(hit.title or "")
    if m and count_of(m.group(1)) is not None:
        out["followers"] = count_of(m.group(1))
    p = _POSTS.search(hit.snippet or "")
    if p and count_of(p.group(1)) is not None:
        out["posts"] = count_of(p.group(1))
    return out


def evidence_city(hit: Hit, city: str) -> tuple[str, str]:
    """(city, city_src) of an Instagram hit. A city NAMED in its title / snippet is evidence (a Shiraz coach's «شیراز📍»); a profile that names no city at all has NO
    city (the query's city is only what was asked for, not where the page is)."""
    named = place.address_cities(f"{hit.title} {hit.snippet}", street_filter=False)
    if named:
        wanted = place.canonical_city(city)
        return (wanted if wanted in named else named[0]), "evidence"
    return "", ""


TRAINER_WORDS = ("مربی", "کوچ", "coach", "trainer", "pt")
BUSINESS_WORDS = ("باشگاه", "مجموعه", "سالن", "استودیو", "club", "gym", "studio", "center", "centre")


def is_individual_page(name: str, handle: str = "") -> bool:
    """An independent coach's own page: the page's NAME (its title line) says «coach / trainer» and does not say it is a club, a studio or a gym. (A handle says little:
    «ava.gym_» and «fitness_marzi» are people's pages.)"""
    return bool(textnorm.name_has_word(name, TRAINER_WORDS)) and not textnorm.name_has_word(name, BUSINESS_WORDS)


def hit_to_found(hit: Hit, *, types: list[str], city: str, query: str, individual_ok: bool = True) -> Found | None:
    host = host_of(hit.url)
    if not host:
        return None
    handle = instagram_handle(hit.url)
    if handle:
        name = nz.normalize_text(re.sub(r"\(@[^)]*\)|•.*$|Instagram.*$", "", hit.title)).strip(" -–|") or handle
        found_city, city_src = evidence_city(hit, city)
        signals = {"serp": {"engine": hit.engine, "query": query, "title": hit.title[:160], "snippet": hit.snippet[:240]}, "ig_from_search": True}
        numbers = instagram_numbers(hit)
        if numbers:
            signals["ig"] = {**numbers, "from": "search"}
        if "personal_trainer" in types and is_individual_page(name, handle):
            signals["individual"] = True  # an independent coach's own page: handled as personal data (see ``finalize.INDIVIDUAL_TAG``)
            if not individual_ok:
                return None
        return Found(name=name[:120], source=SOURCE, ref=f"search:{hit.engine}:instagram.com/{handle}", url=hit.url, types=list(types), city=found_city, city_src=city_src,
                     instagram=handle, signals=signals)
    if blocked_host(host) or host in DIRECTORY_HOSTS or textnorm.looks_like_listing_page(hit.title, hit.url):
        return None
    root = f"{urlsplit(hit.url).scheme or 'https'}://{urlsplit(hit.url).netloc}"
    return Found(
        name=name_from_title(hit.title, host), source=SOURCE, ref=f"search:{hit.engine}:{host}", url=hit.url, types=list(types), city=city, website=root,
        signals={"serp": {"engine": hit.engine, "query": query, "title": hit.title[:160], "snippet": hit.snippet[:240]}},
    )


# --------------------------------------------------------------------------- planning & running


#: well-known cities in the spelling the engines understand for an English query («gym tehran» works from here where «باشگاه تهران» does not)
CITY_EN = {
    "تهران": "tehran", "اصفهان": "isfahan", "مشهد": "mashhad", "شیراز": "shiraz", "تبریز": "tabriz", "کرج": "karaj", "قم": "qom", "اهواز": "ahvaz", "رشت": "rasht",
    "همدان": "hamedan", "کرمان": "kerman", "یزد": "yazd", "ارومیه": "urmia", "اراک": "arak", "ساری": "sari", "قزوین": "qazvin", "بندرعباس": "bandar abbas", "زاهدان": "zahedan",
    "کرمانشاه": "kermanshah", "گرگان": "gorgan", "سنندج": "sanandaj", "اردبیل": "ardabil", "بوشهر": "bushehr", "خرم‌آباد": "khorramabad", "زنجان": "zanjan", "سمنان": "semnan",
}


def build_queries(spec: dict, limit: int) -> list[dict]:
    """Per city, in this order: each type's first Persian term, its first English term (+ the city in English), the second Persian terms, the keywords.
    The cities share the query budget (round-robin), so with four cities each one gets its turn - the first city never uses it all up."""
    seen: set[str] = set()
    cities = [c for c in spec.get("cities", []) if c] or [""]
    types = [presets.get_type(t) for t in spec.get("business_types", []) if presets.get_type(t)]

    def for_city(city: str) -> list[dict]:
        out: list[dict] = []
        city_en = CITY_EN.get(place.canonical_city(city), "")

        def add(query: str, keys: list[str], words: list[str], lang: str = "fa") -> None:
            q = nz.normalize_text(query)
            if q and q not in seen:
                seen.add(q)
                out.append({"query": q, "city": city, "city_en": city_en, "types": keys, "words": words, "lang": lang})

        for bt in types:
            if bt.terms_fa:
                add(f"{bt.terms_fa[0]} {city}", [bt.key], [*bt.words, *bt.terms_fa])
            if bt.terms_en and city_en:
                add(f"{bt.terms_en[0]} {city_en}", [bt.key], [*bt.words, *bt.terms_en], "en")
        for bt in types:
            for term in bt.terms_fa[1:2]:
                add(f"{term} {city}", [bt.key], [*bt.words, *bt.terms_fa])
        for kw in (spec.get("keywords") or [])[:4]:
            add(f"{kw} {city}", [t.key for t in types], [kw, *[w for t in types for w in t.words]])
        return out

    groups = [for_city(city) for city in cities]
    merged: list[dict] = []
    for i in range(max((len(g) for g in groups), default=0)):
        merged += [g[i] for g in groups if i < len(g)]
    return merged[:max(limit, 2 * len(cities))]


def plan(spec: dict) -> list[TaskSpec]:
    limit = int((spec.get("budget") or {}).get("max_search_queries") or 6)
    return [
        TaskSpec(source=SOURCE, kind="query", key=f"search:{nz.search_key(q['query'])}", priority=30, label=f"جست‌وجوی وب: «{q['query']}»" + (" (پرسِ انگلیسی)" if q.get("lang") == "en" else ""), params=q)
        for q in build_queries(spec, limit)
    ]


def ask(ctx: SourceContext, query: str, *, persian: bool, site_op: bool) -> tuple[list[Hit], str, dict[str, str]]:
    """Ask the usable engines one after another until one answers. Returns (hits, the engine that answered, {engine: why it did not})."""
    order, problems = usable_engines(ctx.spec, persian=persian, site_op=site_op)
    for key in order:
        if ctx.stop():
            raise RetryLater("متوقف شد.", 5)
        got, problem = run_query(ctx, key, query)
        if problem:
            problems[key] = problem
            ctx.log("warn", f"موتورِ جست‌وجوی {ENGINES[key]['label']}: {problem}")
            continue
        return got, key, problems
    return [], "", problems


_TOLD: dict = {}


def say_no_hits(ctx: SourceContext, what: str, problems: dict) -> None:
    """Log that a query got nothing. The reasons of the engines are long and the same for every query of a run (a blocked engine rests 30 minutes), so they are written
    out once per run (as a warning); later queries get one short line."""
    why = "؛ ".join(f"{ENGINES[k]['label']}: {v}" for k, v in problems.items()) or "هیچ موتوری در دسترس نبود"
    key = (getattr(ctx.run, "pk", 0), str(getattr(ctx.run, "queued_at", "")), why)
    if key not in _TOLD:
        _TOLD[key] = True
        ctx.log("warn", f"{what}: نتیجه‌ای نیامد ({why}). برای پرسش‌های بعدیِ همین اجرا این دلیل دوباره نوشته نمی‌شود.")
    else:
        ctx.log("info", f"{what}: نتیجه‌ای نیامد (همان دلیلِ بالا).")


def execute(task, ctx: SourceContext) -> dict:
    p = task.params
    persian = p.get("lang", "fa") == "fa" and bool(re.search(r"[\u0600-\u06ff]", p["query"]))
    hits, used, problems = ask(ctx, p["query"], persian=persian, site_op="site:" in p["query"])
    if not hits:
        say_no_hits(ctx, f"جست‌وجوی «{p['query']}»{' (پرسِ انگلیسی)' if p.get('lang') == 'en' else ''}", problems)
        return {"engine": "", "problems": problems, "results": 0, "note": "هیچ موتورِ جست‌وجویی نتیجهٔ قابل‌استفاده نداد"}
    out = take_hits(ctx, p, hits, used)
    ctx.log("info", f"جست‌وجو «{p['query']}»{' (پرسِ انگلیسی)' if p.get('lang') == 'en' else ''} ({ENGINES[used]['label']}): {len(hits)} نتیجه، {out['relevant']} مرتبط، {out['dropped'] + out['listings']} نامرتبط یا مقاله/فهرست کنار گذاشته شد.")
    return {"engine": used, "problems": problems, "results": len(hits), **out}


def take_hits(ctx: SourceContext, p: dict, hits: list[Hit], used: str) -> dict:
    """Turn the hits of one query into candidates (shared by the web search and the Instagram hashtag / location discovery)."""
    kept = new = dropped = dirs = lists = 0
    for hit in hits:
        host = host_of(hit.url)
        is_ig = bool(instagram_handle(hit.url))
        if host in DIRECTORY_HOSTS and relevant(hit, words=p["words"], city=p.get("city", ""), city_en=p.get("city_en", "")):
            wanted = {place.canonical_city(c) for c in ctx.cities()}
            its_city = place.city_of_url(hit.url)
            if its_city and wanted and its_city not in wanted:  # «badanfit.ir/gym-hub.php?city=isfahan» found while searching for Tehran: another city's list
                ctx.log("info", f"فهرستِ {host} برای «{its_city}» است، نه شهرهای این مأموریت؛ دنبال نشد.")
            elif ctx.spec.get("sources", {}).get("directory", True):
                ctx.add_tasks([TaskSpec(source="directory", kind="list", key=f"dir:{hit.url[:300]}", priority=25, label=f"فهرستِ {host}",
                                        params={"url": hit.url, "directory": DIRECTORY_HOSTS[host], "types": p["types"], "city": its_city or p.get("city", "")})])
                dirs += 1
            continue
        ok = (relevant_instagram(hit, words=p["words"], cities=list(ctx.cities())) if is_ig
              else relevant(hit, words=p["words"], city=p.get("city", ""), city_en=p.get("city_en", "")))
        if not ok:
            dropped += 1
            continue
        if not is_ig and textnorm.looks_like_listing_page(hit.title, hit.url):
            lists += 1
            continue
        f = hit_to_found(hit, types=p["types"], city=p.get("city", ""), query=p["query"], individual_ok=bool(ctx.spec.get("include_individuals", True)))
        if f is None:
            dropped += 1
            continue
        _, created = ctx.emit(f)
        kept += 1
        new += 1 if created else 0
    return {"relevant": kept, "dropped": dropped, "listings": lists, "new_candidates": new, "directories": dirs}


# --------------------------------------------------------------------------- engine health (for the panel and the self-test)


def probe(web, queries: tuple[str, ...] = ("gym tehran",)) -> dict:
    """Ask every engine that is not resting one small query and say what came back. A resting engine is not asked (every request made while an engine blocks us prolongs its block)."""
    out: dict[str, dict] = {}
    resting = cooldowns()
    for key, spec in ENGINES.items():
        if spec.get("needs_key") and not brave_api_key():
            continue
        if key in resting:
            until = timezone.localtime(datetime.fromisoformat(resting[key]["until"])).strftime("%H:%M")
            out[key] = {"label": spec["label"], "ok": False, "results": 0, "message": f"در استراحت تا {until} ({resting[key]['reason']})", "resting": True}
            continue
        try:
            headers = {"X-Subscription-Token": brave_api_key(), "Accept": "application/json"} if spec.get("needs_key") else HTML_ACCEPT
            result = web.api(spec["url"], spec["params"](queries[0]), ttl_hours=0, delay=spec["delay"], retries=0, max_bytes=2_000_000, headers=headers)
        except Exception as exc:  # noqa: BLE001 - a probe never raises
            out[key] = {"label": spec["label"], "ok": False, "results": 0, "message": f"{type(exc).__name__}"}
            continue
        blocked = "" if spec.get("needs_key") else looks_blocked(result.status, result.text if result.outcome == sh.OK else "")
        if blocked:
            start_cooldown(key, blocked)
            out[key] = {"label": spec["label"], "ok": False, "results": 0, "message": blocked}
            continue
        if result.outcome != sh.OK:
            out[key] = {"label": spec["label"], "ok": False, "results": 0, "message": result.label}
            continue
        hits = spec["parse"](result.text)
        out[key] = {"label": spec["label"], "ok": bool(hits), "results": len(hits), "message": "" if hits else "نتیجه‌ای نبود"}
    return out
