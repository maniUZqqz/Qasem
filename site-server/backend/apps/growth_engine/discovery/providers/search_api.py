"""Optional search-engine providers that use an OFFICIAL, keyed API (never a scraped result page):

* Brave Search API        - ``https://api.search.brave.com/res/v1/web/search``       (header ``X-Subscription-Token``)
* Google Programmable Search JSON API - ``https://www.googleapis.com/customsearch/v1``  (``key`` + ``cx``)

Both are OFF until the operator pastes a key in the panel; the key lives only in the database (``ProviderConfig.secrets``),
is sent only to its own API host, is never logged and is never returned to the browser. A daily request cap protects the
free quota. The plan's terms (and whether it allows keeping results) are the operator's to check - the panel says so.

A search result is a WEBSITE, not a verified business: the candidate is the site's root address with the page title as a name,
the snippet is kept as evidence. Aggregators, social networks and marketplaces are never turned into leads (``BLOCKED_HOSTS``) -
in particular nothing from Basalam, Digikala, Torob, Divar or Instagram.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from apps.growth_engine.integrations import safe_http as sh

from .base import Candidate, ProviderContext, ProviderError, SearchProvider, SearchQuery, sanitize

#: hosts (and everything under them) that are never a business's own site
BLOCKED_HOSTS = (
    "instagram.com", "facebook.com", "fb.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "youtu.be", "tiktok.com",
    "pinterest.com", "telegram.me", "t.me", "wa.me", "whatsapp.com", "eitaa.com", "ble.ir", "bale.ai", "rubika.ir", "aparat.com",
    "digikala.com", "basalam.com", "torob.com", "divar.ir", "sheypoor.com", "emalls.ir", "zoodfood.com", "snappfood.ir",
    "wikipedia.org", "wikimedia.org", "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "yelp.com", "tripadvisor.com",
    "amazon.com", "ebay.com", "aliexpress.com", "alibaba.com", "etsy.com", "blogfa.com", "blogger.com", "medium.com",
    "wordpress.com", "tumblr.com", "reddit.com", "quora.com", "github.com", "mihanblog.com", "persianblog.ir", "rozblog.com",
)
_TITLE_SPLIT = re.compile(r"\s*[|–—»«:•·]\s*|\s+-\s+")


def host_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().strip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_blocked(host: str) -> bool:
    return any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_HOSTS)


def name_from_title(title: str, host: str) -> str:
    """The business-like head of a result title ("فروشگاه رها | لباس زنانه" -> "فروشگاه رها"); the host when there is none."""
    title = re.sub(r"\s+", " ", title or "").strip()
    head = next((p for p in _TITLE_SPLIT.split(title) if len(p.strip()) >= 3), title)
    return (head or host)[:120]


def candidates_from_results(results: list[dict], *, provider: str, category: str, city: str, seen: set[str]) -> list[Candidate]:
    """``results`` = ``[{"title", "url", "snippet"}]`` in the engine's order -> one candidate per allowed host (``seen`` is shared)."""
    out: list[Candidate] = []
    for item in results:
        url = str(item.get("url") or "")
        host = host_of(url)
        if not host or is_blocked(host) or host in seen:
            continue
        seen.add(host)
        parts = urlsplit(url)
        candidate = Candidate(
            name=name_from_title(str(item.get("title") or ""), host), external_id=host, source_ref=f"search:{provider}:{host}"[:200],
            source_url=url[:500], category=category[:120], city=city, website=f"{parts.scheme}://{host}/",
            extra={"title": str(item.get("title") or "")[:200], "snippet": str(item.get("snippet") or "")[:400], "from_search": True},
        )
        out.append(sanitize(candidate))
    return out


def _json(result, what: str):
    try:
        return json.loads(result.text)
    except ValueError as exc:
        raise ProviderError("bad_response", f"پاسخِ {what} قابل‌خواندن نبود.", retryable=True) from exc


class _KeyedSearch(SearchProvider):
    kind = "search"
    needs_key = True
    max_results_limit = 30
    per_page = 10
    default_daily_cap = 20

    def settings_schema(self) -> list[dict]:
        return [{"name": "daily_cap", "label": "حداکثر درخواست در روز", "type": "int", "default": self.default_daily_cap,
                 "help": "برای اینکه سهمیهٔ رایگانِ شما تمام نشود. هر صفحهٔ نتیجه یک درخواست حساب می‌شود."}]

    def pages_for(self, max_results: int) -> int:
        return max(1, -(-int(max_results) // self.per_page))

    def search_text(self, query: SearchQuery) -> str:
        return " ".join(p for p in (query.category.strip(), query.city.strip()) if p)

    def daily_cap(self, settings: dict) -> int:
        try:
            return max(1, min(1000, int((settings or {}).get("daily_cap") or self.default_daily_cap)))
        except (TypeError, ValueError):
            return self.default_daily_cap


class BraveProvider(_KeyedSearch):
    key = "brave"
    label = "جست‌وجوی Brave (با کلیدِ API)"
    description = "نتیجه‌های وب برای یک عبارتِ جست‌وجو، از راهِ API رسمیِ Brave. تا وقتی کلید ندهید خاموش است."
    secret_fields = (("api_key", "کلیدِ API برِیو"),)
    attribution = "نتایج: Brave Search API"
    attribution_url = "https://brave.com/search/api/"
    license_note = "شرایطِ پلنِ Brave شما (از جمله اجازهٔ نگهداریِ نتیجه‌ها) با خودِ شماست؛ این برنامه فقط نشانیِ سایتِ نتیجه‌ها را به‌عنوان لیدِ احتمالی ذخیره می‌کند."
    source_provider = "brave_search"
    per_page = 20
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def fetch(self, query: SearchQuery, ctx: ProviderContext) -> list[Candidate]:
        api_key = (ctx.secrets or {}).get("api_key", "")
        if not api_key:
            raise ProviderError("no_key", "کلیدِ API برِیو وارد نشده است.")
        text = self.search_text(query)
        if not text:
            raise ProviderError("query_required", "عبارتِ جست‌وجو را بنویسید.")
        seen: set[str] = set()
        out: list[Candidate] = []
        for page in range(self.pages_for(query.max_results)):
            if ctx.cancelled():
                raise ProviderError("cancelled", "متوقف شد.")
            ctx.note_request(self.key)
            result = ctx.fetcher.get_api(
                self.endpoint, params={"q": text, "count": str(self.per_page), "offset": str(page), "search_lang": "fa"},
                headers={"X-Subscription-Token": api_key}, delay=1.2, retries=1, backoff=(3.0,),
            )
            if result.status in (401, 403):
                raise ProviderError("bad_key", "کلیدِ API برِیو پذیرفته نشد؛ آن را دوباره از پنلِ Brave کپی کنید.")
            if result.status == 429:
                raise ProviderError("quota", "سهمیهٔ جست‌وجوی Brave تمام یا پرتکرار شد؛ بعداً دوباره امتحان کنید.", retryable=True)
            if result.outcome != sh.OK:
                raise ProviderError("service_busy", f"Brave جواب نداد ({result.label}).", retryable=True)
            rows = ((_json(result, "Brave").get("web") or {}).get("results")) or []
            if not rows:
                break
            out.extend(candidates_from_results(
                [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("description")} for r in rows if isinstance(r, dict)],
                provider=self.key, category=query.category, city=query.city, seen=seen,
            ))
            if len(out) >= query.max_results:
                break
        return out[: query.max_results]


class GoogleCseProvider(_KeyedSearch):
    key = "google_cse"
    label = "جست‌وجوی گوگل (Programmable Search، با کلید)"
    description = "نتیجه‌های موتورِ جست‌وجوی سفارشیِ شما از راهِ API رسمیِ گوگل (روزی ۱۰۰ درخواستِ رایگان). تا وقتی کلید و شناسهٔ موتور ندهید خاموش است."
    secret_fields = (("api_key", "کلیدِ API گوگل"), ("cx", "شناسهٔ موتورِ جست‌وجو (cx)"))
    attribution = "نتایج: Google Programmable Search"
    attribution_url = "https://developers.google.com/custom-search/v1/overview"
    license_note = "شرایطِ استفاده از API گوگل با خودِ شماست؛ این برنامه فقط نشانیِ سایتِ نتیجه‌ها را به‌عنوان لیدِ احتمالی ذخیره می‌کند."
    source_provider = "google_cse"
    per_page = 10
    endpoint = "https://www.googleapis.com/customsearch/v1"
    default_daily_cap = 50

    def fetch(self, query: SearchQuery, ctx: ProviderContext) -> list[Candidate]:
        api_key, cx = (ctx.secrets or {}).get("api_key", ""), (ctx.secrets or {}).get("cx", "")
        if not api_key or not cx:
            raise ProviderError("no_key", "کلیدِ API و شناسهٔ موتورِ جست‌وجو (cx) هر دو لازم است.")
        text = self.search_text(query)
        if not text:
            raise ProviderError("query_required", "عبارتِ جست‌وجو را بنویسید.")
        seen: set[str] = set()
        out: list[Candidate] = []
        for page in range(self.pages_for(query.max_results)):
            if ctx.cancelled():
                raise ProviderError("cancelled", "متوقف شد.")
            ctx.note_request(self.key)
            result = ctx.fetcher.get_api(
                self.endpoint, params={"key": api_key, "cx": cx, "q": text, "num": str(self.per_page), "start": str(1 + page * self.per_page), "lr": "lang_fa"},
                delay=1.2, retries=1, backoff=(3.0,),
            )
            if result.status in (400, 401, 403):
                reason = ""
                try:
                    reason = str(((_json(result, "گوگل").get("error") or {}).get("errors") or [{}])[0].get("reason") or "")
                except ProviderError:
                    pass
                if reason in ("dailyLimitExceeded", "rateLimitExceeded", "quotaExceeded") or result.status == 429:
                    raise ProviderError("quota", "سهمیهٔ روزانهٔ API گوگل تمام شد؛ فردا دوباره امتحان کنید.", retryable=True)
                raise ProviderError("bad_key", "کلید یا شناسهٔ موتورِ گوگل پذیرفته نشد (یا این API برای حسابِ شما فعال نیست).")
            if result.status == 429:
                raise ProviderError("quota", "سهمیهٔ API گوگل تمام یا پرتکرار شد؛ بعداً دوباره امتحان کنید.", retryable=True)
            if result.outcome != sh.OK:
                raise ProviderError("service_busy", f"گوگل جواب نداد ({result.label}).", retryable=True)
            rows = _json(result, "گوگل").get("items") or []
            if not rows:
                break
            out.extend(candidates_from_results(
                [{"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet")} for r in rows if isinstance(r, dict)],
                provider=self.key, category=query.category, city=query.city, seen=seen,
            ))
            if len(out) >= query.max_results:
                break
        return out[: query.max_results]
