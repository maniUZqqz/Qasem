"""How the crawler talks to the web: polite, cached, budgeted.

Everything goes through the Growth Engine's ``SafeFetcher`` (SSRF guard, robots.txt, per-host spacing, retries, size cap, an honest
User-Agent). This module adds what a long crawl needs on top:

* longer read timeouts for the few slow public APIs (Overpass answers in 20-60 s),
* a per-run ``domain_delay`` (the minimum seconds between two requests to one host),
* **a page cache** (``FetchCache``; bodies are gzip files under ``<data>/crawl_cache``): the same URL is never downloaded twice within
  its time-to-live - a resumed run, a second run of the same mission and two seeds that lead to one page all share it,
* **budgets** (requests, bytes, seconds): when one is used up the run stops fetching and finishes with what it has, and says so.

Page fetches (``page``) are checked against robots.txt. ``api`` fetches (OpenStreetMap, a search engine's result page, a
documented JSON API) are not: robots.txt governs the crawling of a site's pages, and those endpoints publish their own usage rules,
which the sources below keep to (a handful of requests, long pauses).
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.utils import timezone

from apps.growth_engine.core import conf
from apps.growth_engine.integrations import safe_http as sh

from ..models import FetchCache

logger = logging.getLogger(__name__)

PAGE_TTL_H = 24 * 7
API_TTL_H = 24 * 3
SERP_TTL_H = 24
MAX_CACHE_BYTES = 300 * 1024 * 1024
CACHE_BODY_LIMIT = 2_000_000


class BudgetExceeded(Exception):
    """A budget (requests / bytes / seconds) is used up: stop fetching, finish with what there is."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass
class Budget:
    max_requests: int = 600
    max_bytes: int = 80_000_000
    max_seconds: int = 1500
    started: float = field(default_factory=time.monotonic)
    requests: int = 0
    bytes: int = 0
    cache_hits: int = 0
    failures: int = 0
    per_host: dict = field(default_factory=dict)

    @classmethod
    def from_spec(cls, spec: Mapping | None, *, used: Mapping | None = None) -> "Budget":
        spec = spec or {}
        budget = cls(
            max_requests=int(spec.get("max_requests") or 600), max_bytes=int(spec.get("max_bytes") or 80_000_000),
            max_seconds=int(spec.get("max_seconds") or 1500),
        )
        for name in ("requests", "bytes", "cache_hits", "failures"):
            setattr(budget, name, int((used or {}).get(name, 0)))
        budget.per_host = dict((used or {}).get("per_host") or {})
        budget.started = time.monotonic() - float((used or {}).get("seconds", 0))
        return budget

    @property
    def seconds(self) -> float:
        return time.monotonic() - self.started

    def check(self) -> None:
        if self.requests >= self.max_requests:
            raise BudgetExceeded("requests", f"سقفِ تعدادِ درخواست‌ها ({self.max_requests}) پر شد.")
        if self.bytes >= self.max_bytes:
            raise BudgetExceeded("bytes", "سقفِ حجمِ دریافت پر شد.")
        if self.seconds >= self.max_seconds:
            raise BudgetExceeded("seconds", f"سقفِ زمانِ اجرا ({self.max_seconds // 60} دقیقه) پر شد.")

    def snapshot(self) -> dict:
        return {"requests": self.requests, "bytes": self.bytes, "cache_hits": self.cache_hits, "failures": self.failures,
                "seconds": int(self.seconds), "per_host": dict(sorted(self.per_host.items(), key=lambda kv: -kv[1])[:30])}


class CrawlFetcher(sh.SafeFetcher):
    """``SafeFetcher`` with a configurable read timeout and a per-run minimum delay between two requests to one host."""

    def __init__(self, *, read_timeout: float | None = None, domain_delay: float | None = None, **kwargs):
        super().__init__(**kwargs)
        self.read_timeout = read_timeout
        self.domain_delay = domain_delay

    def _timeout(self) -> httpx.Timeout:
        # the direct client AND the clients bound to a proxy (egress) share this read timeout
        return httpx.Timeout(self.read_timeout or conf.get("HTTP_READ_TIMEOUT"), connect=conf.get("HTTP_CONNECT_TIMEOUT"))

    def _get_with_retries(self, target, *, html_only, max_bytes, extra_headers=None, delay=None, retries=None, backoff=None):
        return super()._get_with_retries(
            target, html_only=html_only, max_bytes=max_bytes, extra_headers=extra_headers,
            delay=self.domain_delay if delay is None else delay, retries=retries, backoff=backoff,
        )


# --------------------------------------------------------------------------- the cache


def cache_dir() -> Path:
    path = Path(getattr(settings, "NM_DATA_DIR", Path(settings.BASE_DIR) / "data")) / "crawl_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(method: str, url: str) -> str:
    return hashlib.sha1(f"{method}\n{url}".encode()).hexdigest()


def cache_get(method: str, url: str) -> sh.FetchResult | None:
    row = FetchCache.objects.filter(url_key=_key(method, url), expires_at__gt=timezone.now()).first()
    if row is None:
        return None
    text = ""
    if row.path:
        try:
            with gzip.open(row.path, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
        except (OSError, EOFError):
            return None
    return sh.FetchResult(
        url=url, final_url=row.final_url or url, status=row.status, outcome=row.outcome, text=text, content_type=row.content_type,
        bytes_read=row.size,
    )


def cache_put(method: str, url: str, result: sh.FetchResult, ttl_hours: float) -> None:
    if result.outcome != sh.OK or result.status != 200 or not result.text or len(result.text) > CACHE_BODY_LIMIT:  # a «202 anomaly / bot check» page is not an answer to keep
        return
    key = _key(method, url)
    path = cache_dir() / key[:2]
    path.mkdir(parents=True, exist_ok=True)
    file = path / f"{key}.gz"
    try:
        with gzip.open(file, "wb", compresslevel=5) as fh:
            fh.write(result.text.encode("utf-8"))
    except OSError:
        logger.warning("crawl cache: could not write %s", file)
        return
    now = timezone.now()
    FetchCache.objects.update_or_create(
        url_key=key,
        defaults={
            "url": url[:600], "status": result.status, "content_type": result.content_type[:120], "final_url": (result.final_url or "")[:600],
            "path": str(file), "size": result.bytes_read or len(result.text), "outcome": result.outcome, "fetched_at": now,
            "expires_at": now + timedelta(hours=ttl_hours),
        },
    )


def purge_cache(max_bytes: int = MAX_CACHE_BYTES) -> dict:
    """Delete expired entries, then the oldest ones while the cache is over ``max_bytes``. Returns what was removed."""
    removed = 0
    for row in FetchCache.objects.filter(expires_at__lte=timezone.now())[:5000]:
        _drop(row)
        removed += 1
    total = sum(FetchCache.objects.values_list("size", flat=True))
    if total > max_bytes:
        for row in FetchCache.objects.order_by("fetched_at")[:5000]:
            if total <= max_bytes:
                break
            total -= row.size
            _drop(row)
            removed += 1
    return {"removed": removed, "bytes": total}


def _drop(row: FetchCache) -> None:
    try:
        if row.path and os.path.exists(row.path):
            os.remove(row.path)
    except OSError:
        pass
    row.delete()


# --------------------------------------------------------------------------- what the sources use


class WebClient:
    """One per run segment. ``stop()`` is the cooperative cancel / pause check; every fetch consults it and the budget first."""

    def __init__(
        self,
        fetcher: sh.SafeFetcher,
        budget: Budget,
        *,
        stop: Callable[[], bool] | None = None,
        use_cache: bool = True,
        log: Callable[[str, str], None] | None = None,
        heartbeat: Callable[[], None] | None = None,
    ):
        self.fetcher = fetcher
        self.budget = budget
        self.stop = stop or (lambda: False)
        self.use_cache = use_cache
        self.log = log or (lambda level, message: None)
        self.heartbeat = heartbeat
        self._beat_at = 0.0

    # -- internals
    def _gate(self) -> None:
        if self.heartbeat is not None and time.monotonic() - self._beat_at > 15.0:
            self._beat_at = time.monotonic()
            try:
                self.heartbeat()  # a long task (a slow site, many pages) must not look like a dead worker
            except Exception:  # noqa: BLE001
                pass
        if self.stop():
            raise BudgetExceeded("stopped", "متوقف شد.")
        self.budget.check()

    def _account(self, url: str, result: sh.FetchResult, *, cached: bool) -> None:
        if cached:
            self.budget.cache_hits += 1
            return
        from urllib.parse import urlsplit

        host = (urlsplit(url).hostname or "").lower()
        self.budget.requests += 1
        self.budget.bytes += result.bytes_read
        self.budget.per_host[host] = self.budget.per_host.get(host, 0) + 1
        if result.outcome != sh.OK or result.status >= 400:
            self.budget.failures += 1

    # -- public
    def page(self, url: str, *, ttl_hours: float = PAGE_TTL_H) -> sh.FetchResult:
        """An HTML page of someone's site: robots.txt checked, cached."""
        self._gate()
        if self.use_cache:
            hit = cache_get("GET", url)
            if hit is not None:
                self._account(url, hit, cached=True)
                return hit
        result = self.fetcher.get_page(url)
        self._account(url, result, cached=False)
        if self.use_cache:
            cache_put("GET", url, result, ttl_hours)
        return result

    def api(
        self, url: str, params: Mapping[str, str] | None = None, *, ttl_hours: float = API_TTL_H, delay: float | None = None,
        retries: int = 1, backoff=(4.0, 12.0), max_bytes: int | None = None, headers: Mapping[str, str] | None = None,
    ) -> sh.FetchResult:
        """A documented endpoint (map API, search page, JSON API): not robots-checked, cached, always paced."""
        self._gate()
        full = url + (("&" if "?" in url else "?") + urlencode(list((params or {}).items())) if params else "")
        cache_url = sh._redact_url(full)
        if self.use_cache and ttl_hours > 0:
            hit = cache_get("API", cache_url)
            if hit is not None:
                self._account(url, hit, cached=True)
                return hit
        result = self.fetcher.get_api(url, params=params, delay=delay, retries=retries, backoff=backoff, max_bytes=max_bytes, headers=headers)
        self._account(url, result, cached=False)
        if self.use_cache and ttl_hours > 0:
            cache_put("API", cache_url, result, ttl_hours)
        return result

    def close(self) -> None:
        self.fetcher.close()


def make_fetcher(*, read_timeout: float | None = None, domain_delay: float | None = None) -> CrawlFetcher:
    """Tests replace this function to inject an ``httpx.MockTransport`` (nothing real is contacted in a test)."""
    return CrawlFetcher(read_timeout=read_timeout, domain_delay=domain_delay)
