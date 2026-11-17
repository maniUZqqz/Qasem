"""Web search result pages as a source: Bing, DuckDuckGo (HTML), Mojeek - whichever answers from where the server is.

What was tested from the Iranian server on 2026-11-16 (details in docs/growth-engine/modules/crawler.md):

    Bing .................. answers with a normal result page (10 results); for Persian local-business queries its ranking is
                            erratic from this address, so EVERY result is checked for relevance before it is used
    DuckDuckGo (html/lite)  HTTP 202 «anomaly» page (a bot check) - skipped automatically, retried on the next run
    Mojeek ................ a captcha page - skipped automatically
    Brave / Ecosia / Yep .. HTTP 403;  Google: a «turn on JavaScript» page;  Startpage: timeout

So the engine list is an ordered list of adapters; each is asked in turn, a «blocked / captcha / empty» answer is recorded (the
panel shows the engine health) and the next one is tried. No paid API is used; a Brave / Google key the owner already stored in
the Growth Engine's provider settings keeps working through the existing discovery tab and is not duplicated here.

Rules: a handful of queries per run (``max_search_queries``), at least 6 s between two requests to an engine, an honest User-Agent,
results are only ever READ as links + titles + snippets - nothing is opened except what the plan later asks for (and that is
robots.txt-checked). A result that is a marketplace / a social network (other than an Instagram profile) / a news site is dropped.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, quote, unquote, urlsplit

from bs4 import BeautifulSoup

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.integrations import safe_http as sh

from ... import presets
from .. import extras, place, textnorm
from ..candidates import Found
from .base import RetryLater, SourceContext, TaskSpec

SOURCE = "search"
ENGINE_DELAY = 6.0
MAX_RESULTS_PER_QUERY = 12

#: result hosts that are never a business's own site (marketplaces, social, encyclopedias, news, video, code ...)
BLOCKED_HOSTS = {
    "digikala.com", "torob.com", "divar.ir", "sheypoor.com", "basalam.com", "emalls.ir", "wikipedia.org", "wikiwand.com", "wikimedia.org",
    "aparat.com", "youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com", "linkedin.com", "pinterest.com", "tiktok.com", "telegram.org",
    "t.me", "github.com", "medium.com", "reddit.com", "quora.com", "bing.com", "microsoft.com", "google.com", "duckduckgo.com", "genius.com",
    "spotify.com", "shazam.com", "musixmatch.com", "isna.ir", "irna.ir", "tasnimnews.com", "farsnews.ir", "khabaronline.ir", "tripadvisor.com",
    "booking.com", "snapp.ir", "tapsi.ir", "digiato.com", "zoomit.ir", "namnak.com", "telewebion.com", "namava.ir", "filimo.com", "eitaa.com",
    "rubika.ir", "ble.ir", "bale.ai", "sapp.ir", "gap.im", "soroush-hamrah.com", "apple.com", "play.google.com", "cafebazaar.ir", "myket.ir",
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


ENGINES = {
    "bing": {"label": "Bing", "url": "https://www.bing.com/search", "params": lambda q: {"q": q, "setlang": "fa", "count": "20"}, "parse": parse_bing},
    "duckduckgo": {"label": "DuckDuckGo", "url": "https://html.duckduckgo.com/html/", "params": lambda q: {"q": q, "kl": "ir-fa"}, "parse": parse_duckduckgo},
    "mojeek": {"label": "Mojeek", "url": "https://www.mojeek.com/search", "params": lambda q: {"q": q}, "parse": parse_mojeek},
}
DEFAULT_ORDER = ("bing", "duckduckgo", "mojeek")


def looks_blocked(status: int, body: str) -> str:
    """'' when the page is a normal result page, else a short reason (anomaly / captcha / forbidden ...)."""
    low = (body or "")[:6000].lower()
    if status in (202, 403, 429):
        return f"HTTP {status}"
    if "anomaly" in low or "captcha" in low or "unusual traffic" in low or "g-recaptcha" in low:
        return "captcha / bot check"
    return ""


def run_query(ctx: SourceContext, engine_key: str, query: str) -> tuple[list[Hit], str]:
    """(hits, problem). ``problem`` is '' on success."""
    spec = ENGINES[engine_key]
    result = ctx.web.api(spec["url"], spec["params"](query), ttl_hours=24, delay=ENGINE_DELAY, retries=0, max_bytes=2_000_000)
    if result.outcome != sh.OK:
        return [], result.label
    blocked = looks_blocked(result.status, result.text)
    if blocked:
        return [], blocked
    hits = spec["parse"](result.text)
    return hits[:MAX_RESULTS_PER_QUERY], "" if hits else "نتیجه‌ای نبود"


# --------------------------------------------------------------------------- relevance & classification


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def blocked_host(host: str) -> bool:
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS) or textnorm.is_media_host(host)


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


_TITLE_SPLIT = re.compile(r"\s*[|\-–—•·»«:]\s*")


def name_from_title(title: str, host: str) -> str:
    """«باشگاه آرمان | تهران - بدنسازی» -> «باشگاه آرمان». Falls back to the host."""
    parts = [p for p in _TITLE_SPLIT.split(nz.normalize_text(title)) if p and len(p) >= 3]
    if parts:
        return parts[0][:120]
    return host


def hit_to_found(hit: Hit, *, types: list[str], city: str, query: str) -> Found | None:
    host = host_of(hit.url)
    if not host:
        return None
    handle = instagram_handle(hit.url)
    if handle:
        name = nz.normalize_text(re.sub(r"\(@[^)]*\)|•.*$|Instagram.*$", "", hit.title)).strip(" -–|") or handle
        return Found(name=name[:120], source=SOURCE, ref=f"search:{hit.engine}:instagram.com/{handle}", url=hit.url, types=list(types), city=city, instagram=handle,
                     signals={"serp": {"engine": hit.engine, "query": query, "title": hit.title[:160], "snippet": hit.snippet[:240]}, "ig_from_search": True})
    if blocked_host(host) or host in DIRECTORY_HOSTS:
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

        def add(query: str, keys: list[str], words: list[str]) -> None:
            q = nz.normalize_text(query)
            if q and q not in seen:
                seen.add(q)
                out.append({"query": q, "city": city, "city_en": city_en, "types": keys, "words": words})

        for bt in types:
            if bt.terms_fa:
                add(f"{bt.terms_fa[0]} {city}", [bt.key], [*bt.words, *bt.terms_fa])
            if bt.terms_en and city_en:
                add(f"{bt.terms_en[0]} {city_en}", [bt.key], [*bt.words, *bt.terms_en])
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
        TaskSpec(source=SOURCE, kind="query", key=f"search:{nz.search_key(q['query'])}", priority=30, label=f"جست‌وجوی وب: «{q['query']}»", params=q)
        for q in build_queries(spec, limit)
    ]


def execute(task, ctx: SourceContext) -> dict:
    p = task.params
    order = [e for e in (ctx.spec.get("search_engines") or DEFAULT_ORDER) if e in ENGINES]
    problems: dict[str, str] = {}
    hits: list[Hit] = []
    used = ""
    for key in order:
        if ctx.stop():
            raise RetryLater("متوقف شد.", 5)
        got, problem = run_query(ctx, key, p["query"])
        if problem:
            problems[key] = problem
            ctx.log("warn", f"موتورِ جست‌وجوی {ENGINES[key]['label']}: {problem}")
            continue
        hits, used = got, key
        break
    if not hits:
        return {"engine": "", "problems": problems, "results": 0, "note": "هیچ موتورِ جست‌وجویی نتیجهٔ قابل‌استفاده نداد"}
    kept = new = dropped = dirs = 0
    for hit in hits:
        host = host_of(hit.url)
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
        if not relevant(hit, words=p["words"], city=p.get("city", ""), city_en=p.get("city_en", "")):
            dropped += 1
            continue
        f = hit_to_found(hit, types=p["types"], city=p.get("city", ""), query=p["query"])
        if f is None:
            dropped += 1
            continue
        _, created = ctx.emit(f)
        kept += 1
        new += 1 if created else 0
    ctx.log("info", f"جست‌وجو «{p['query']}» ({ENGINES[used]['label']}): {len(hits)} نتیجه، {kept} مرتبط، {dropped} نامرتبط کنار گذاشته شد.")
    return {"engine": used, "problems": problems, "results": len(hits), "relevant": kept, "dropped": dropped, "new_candidates": new, "directories": dirs}


# --------------------------------------------------------------------------- engine health (for the panel and the self-test)


def probe(web, queries: tuple[str, ...] = ("gym tehran",)) -> dict:
    """Ask every engine one small query and say what came back. Costs three requests."""
    out: dict[str, dict] = {}
    for key, spec in ENGINES.items():
        try:
            result = web.api(spec["url"], spec["params"](queries[0]), ttl_hours=0, delay=ENGINE_DELAY, retries=0, max_bytes=2_000_000)
        except Exception as exc:  # noqa: BLE001 - a probe never raises
            out[key] = {"label": spec["label"], "ok": False, "results": 0, "message": f"{type(exc).__name__}"}
            continue
        if result.outcome != sh.OK:
            out[key] = {"label": spec["label"], "ok": False, "results": 0, "message": result.label}
            continue
        blocked = looks_blocked(result.status, result.text)
        hits = [] if blocked else spec["parse"](result.text)
        out[key] = {"label": spec["label"], "ok": bool(hits), "results": len(hits), "message": blocked or ("" if hits else "نتیجه‌ای نبود")}
    return out
