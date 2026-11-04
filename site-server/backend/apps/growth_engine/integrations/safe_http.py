"""Outbound HTTP for the Growth Engine: the one place that knows how to talk to a stranger's website.

Everything that reaches out to a lead's own site (contact extraction, form analysis, form
submission) goes through ``SafeFetcher``. It enforces, in this order, for every request and every
redirect hop:

1. **Only http/https, only ordinary ports** (80, 443, 8080, 8443).
2. **SSRF guard.** The host is resolved by us; if ANY address is not a public one (private,
   loopback, link-local, CGNAT, reserved, multicast) the request is refused. The request is then sent
   **to the address we checked** (Host header and TLS SNI carry the name), so a DNS answer that changes
   between "check" and "connect" cannot redirect us into the internal network.
3. **robots.txt** of the host (our own token ``NMarketingBot`` and ``*``). 4xx = allowed, 401/403 =
   disallowed, 5xx / unreachable = treated as disallowed (the conservative reading of RFC 9309).
4. **Per-host spacing** (default 2 s between two requests to one host, shared by all threads).
5. **Timeouts, a response-size cap, HTML-only bodies**, and a clear User-Agent.
6. **Retries for GET only** (timeouts, 429/502/503/504, honouring a capped Retry-After). A POST is
   attempted **once**: a timed-out POST may have been delivered, so repeating it could send twice.

It never logs in, never solves anything, never runs JavaScript. Redirects are followed only within
the same site (same host ignoring ``www.``/scheme/port).
"""
from __future__ import annotations

import codecs
import ipaddress
import logging
import re
import socket
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from apps.growth_engine.core import conf

logger = logging.getLogger(__name__)

# outcomes (stable strings: stored in extraction logs and shown in the panel)
OK = "ok"
HTTP_ERROR = "http_error"
TIMEOUT = "timeout"
CONNECT_ERROR = "connect_error"
TLS_ERROR = "tls_error"
DNS_ERROR = "dns_error"
SSRF_BLOCKED = "ssrf_blocked"
BLOCKED_PORT = "blocked_port"
BAD_URL = "bad_url"
ROBOTS_BLOCKED = "robots_blocked"
ROBOTS_UNAVAILABLE = "robots_unavailable"
REDIRECT_OFFSITE = "redirect_offsite"
REDIRECT_LOOP = "redirect_loop"
TOO_LARGE = "too_large"
NON_HTML = "non_html"

OUTCOME_LABELS = {
    OK: "دریافت شد", HTTP_ERROR: "پاسخ خطا از سایت", TIMEOUT: "سایت جواب نداد (زمان تمام شد)", CONNECT_ERROR: "اتصال به سایت برقرار نشد",
    TLS_ERROR: "گواهیِ امنیتیِ سایت معتبر نیست", DNS_ERROR: "نشانیِ سایت پیدا نشد", SSRF_BLOCKED: "آدرس به شبکهٔ داخلی اشاره می‌کرد؛ مسدود شد",
    BLOCKED_PORT: "پورتِ غیرمعمول؛ مسدود شد", BAD_URL: "آدرس معتبر نیست", ROBOTS_BLOCKED: "robots.txt سایت اجازه نمی‌دهد",
    ROBOTS_UNAVAILABLE: "robots.txt خوانده نشد؛ برای احتیاط رد شد", REDIRECT_OFFSITE: "به سایتِ دیگری هدایت شد؛ دنبال نشد",
    REDIRECT_LOOP: "هدایت‌های پشت‌سرهم زیاد بود", TOO_LARGE: "صفحه بیش از حد بزرگ بود", NON_HTML: "صفحه HTML نبود",
}

HTML_TYPES = ("text/html", "application/xhtml+xml")
_RETRY_STATUS = {429, 502, 503, 504}
_BACKOFF = (1.0, 3.0)
_MAX_RETRY_AFTER = 10.0
ROBOTS_MAX_BYTES = 500_000


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0  # HTTP status; 0 = no response
    outcome: str = BAD_URL
    text: str = ""
    content_type: str = ""
    headers: dict = field(default_factory=dict)
    bytes_read: int = 0
    elapsed_ms: int = 0
    redirects: list[str] = field(default_factory=list)
    location: str = ""  # Location header of the last 3xx (POST responses)
    error: str = ""
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome == OK

    @property
    def label(self) -> str:
        return self.error or OUTCOME_LABELS.get(self.outcome, self.outcome)


# --------------------------------------------------------------------------- pieces


class DomainThrottle:
    """Minimum spacing between requests to one host, safe across threads (the slot is reserved under a lock)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self._clock, self._sleep = clock, sleep
        self._next_free: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, delay: float) -> float:
        if delay <= 0:
            return 0.0
        with self._lock:
            now = self._clock()
            ready = self._next_free.get(host, now)
            wait = max(0.0, ready - now)
            self._next_free[host] = now + wait + delay
        if wait:
            self._sleep(wait)
        return wait


GLOBAL_THROTTLE = DomainThrottle()


def default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    return sorted(addresses, key=lambda a: ":" in a)  # IPv4 first: the server may have no IPv6 route


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_global and not ip.is_multicast)


def _same_site(a: str, b: str) -> bool:
    def key(u: str) -> str:
        host = (urlsplit(u).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    return key(a) == key(b)


def _detect_charset(content_type: str, head: bytes) -> str:
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I) or re.search(rb"charset=[\"']?([\w-]+)", head[:3000], re.I)
    if match:
        name = match.group(1)
        name = name.decode("ascii", "ignore") if isinstance(name, bytes) else name
        try:
            return codecs.lookup(name).name
        except LookupError:
            pass
    return "utf-8"


def _decode(body: bytes, content_type: str) -> str:
    return body.decode(_detect_charset(content_type, body), errors="replace")


@dataclass
class _Target:
    scheme: str
    host: str
    port: int
    ip: str
    path_query: str

    @property
    def request_url(self) -> str:
        ip = f"[{self.ip}]" if ":" in self.ip else self.ip
        return f"{self.scheme}://{ip}:{self.port}{self.path_query}"

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"


class _Refused(Exception):
    def __init__(self, outcome: str, message: str = ""):
        self.outcome, self.message = outcome, message


# --------------------------------------------------------------------------- the fetcher


class SafeFetcher:
    """One instance per job run: it caches robots.txt for the hosts it meets."""

    def __init__(
        self,
        *,
        resolver: Callable[[str, int], Sequence[str]] | None = None,
        transport: httpx.BaseTransport | None = None,
        throttle: DomainThrottle | None = None,
        sleep: Callable[[float], None] = time.sleep,
        respect_robots: bool = True,
    ):
        self._resolver = resolver or default_resolver
        self._transport = transport
        self._throttle = throttle or GLOBAL_THROTTLE
        self._sleep = sleep
        self._respect_robots = respect_robots
        self._robots: dict[tuple, tuple[robotparser.RobotFileParser | None, str]] = {}
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------ plumbing
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            timeout = httpx.Timeout(conf.get("HTTP_READ_TIMEOUT"), connect=conf.get("HTTP_CONNECT_TIMEOUT"))
            self._client = httpx.Client(
                transport=self._transport or httpx.HTTPTransport(retries=0), timeout=timeout, follow_redirects=False, verify=True
            )
        return self._client

    def _prepare(self, url: str) -> _Target:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise _Refused(BAD_URL, "آدرس معتبر نیست.") from exc
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower().strip(".")
        if scheme not in ("http", "https") or not host:
            raise _Refused(BAD_URL, "فقط آدرس http و https پذیرفته می‌شود.")
        if not host.isascii():
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise _Refused(BAD_URL, "نام دامنه معتبر نیست.") from exc
        port = port or (443 if scheme == "https" else 80)
        allow_private = conf.get("HTTP_ALLOW_PRIVATE")
        if port not in conf.get("HTTP_ALLOWED_PORTS") and not allow_private:
            raise _Refused(BLOCKED_PORT)
        try:
            ipaddress.ip_address(host.strip("[]"))
            addresses = [host.strip("[]")]
        except ValueError:
            try:
                addresses = list(self._resolver(host, port))
            except OSError as exc:
                raise _Refused(DNS_ERROR) from exc
        if not addresses:
            raise _Refused(DNS_ERROR)
        if not allow_private and not all(is_public_ip(a) for a in addresses):
            raise _Refused(SSRF_BLOCKED)
        path_query = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return _Target(scheme=scheme, host=host, port=port, ip=addresses[0], path_query=path_query)

    def _headers(self, target: _Target, *, referer: str | None = None, extra: Mapping | None = None) -> dict:
        headers = {
            "Host": target.host_header,
            "User-Agent": conf.get("HTTP_USER_AGENT"),
            "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.5,*/*;q=0.1",
            "Accept-Language": "fa,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        headers.update(extra or {})
        return headers

    def _send(self, method: str, target: _Target, *, html_only: bool, max_bytes: int, referer=None, data=None, files=None) -> FetchResult:
        """One request, no retries, no redirects. Never raises for network problems."""
        assert method in ("GET", "POST"), "the Growth Engine only ever issues GET and POST"
        result = FetchResult(url=target.request_url, final_url=f"{target.scheme}://{target.host_header}{target.path_query}")
        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        started = time.monotonic()
        try:
            with self._http().stream(
                method, target.request_url, headers=self._headers(target, referer=referer), extensions=extensions, data=data, files=files
            ) as response:
                result.status = response.status_code
                result.headers = {k.lower(): v for k, v in response.headers.items()}
                result.content_type = result.headers.get("content-type", "")
                result.location = result.headers.get("location", "")
                if 300 <= response.status_code < 400:
                    result.outcome = OK
                    return result
                if html_only and 200 <= response.status_code < 300 and not any(t in result.content_type.lower() for t in HTML_TYPES):
                    result.outcome = NON_HTML
                    return result
                chunks, total, truncated = [], 0, False
                for chunk in response.iter_bytes():
                    if total + len(chunk) > max_bytes:
                        chunks.append(chunk[: max_bytes - total])
                        total, truncated = max_bytes, True
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                body = b"".join(chunks)
                result.bytes_read = total
                result.text = _decode(body, result.content_type)
                result.outcome = TOO_LARGE if truncated and html_only else (OK if 200 <= response.status_code < 300 else HTTP_ERROR)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            result.outcome = TIMEOUT
        except httpx.ConnectError as exc:
            result.outcome = TLS_ERROR if re.search(r"CERTIFICATE|SSL", str(exc), re.I) else CONNECT_ERROR
        except httpx.HTTPError as exc:
            result.outcome = TLS_ERROR if re.search(r"CERTIFICATE|SSL", str(exc), re.I) else CONNECT_ERROR
            logger.info("growth http error %s on %s", type(exc).__name__, target.host)
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    def _get_with_retries(self, target: _Target, *, html_only: bool, max_bytes: int) -> FetchResult:
        retries = int(conf.get("HTTP_RETRIES"))
        attempt = 0
        while True:
            self._throttle.wait(target.host, conf.get("HTTP_DOMAIN_DELAY"))
            result = self._send("GET", target, html_only=html_only, max_bytes=max_bytes)
            attempt += 1
            result.attempts = attempt
            transient = result.outcome in (TIMEOUT, CONNECT_ERROR) or result.status in _RETRY_STATUS
            if not transient or attempt > retries:
                return result
            pause = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
            retry_after = result.headers.get("retry-after", "")
            if retry_after.isdigit():
                pause = min(float(retry_after), _MAX_RETRY_AFTER)
            self._sleep(pause)

    # ------------------------------------------------------------------ robots.txt
    def robots_allows(self, url: str) -> tuple[bool, str]:
        """(allowed, state) - state: ok | none (no file) | disallow_all | unavailable | off."""
        if not self._respect_robots:
            return True, "off"
        parts = urlsplit(url)
        key = ((parts.scheme or "").lower(), (parts.hostname or "").lower(), parts.port)
        if key not in self._robots:
            self._robots[key] = self._load_robots(f"{parts.scheme}://{parts.netloc}/robots.txt")
        parser, state = self._robots[key]
        if state in ("unavailable", "disallow_all"):
            return False, state
        if parser is None:
            return True, state
        token = conf.get("HTTP_ROBOTS_TOKEN")
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return parser.can_fetch(token, path) and parser.can_fetch("*", path), state

    def _load_robots(self, robots_url: str) -> tuple[robotparser.RobotFileParser | None, str]:
        result = self._fetch(robots_url, check_robots=False, html_only=False, max_bytes=ROBOTS_MAX_BYTES)
        status = result.status
        if result.outcome in (SSRF_BLOCKED, BLOCKED_PORT, BAD_URL, DNS_ERROR):
            return None, "unavailable"
        if status in (401, 403):
            return None, "disallow_all"
        if 400 <= status < 500:
            return None, "none"
        if result.outcome == OK and 200 <= status < 300:
            parser = robotparser.RobotFileParser()
            parser.parse(result.text.splitlines())
            return parser, "ok"
        return None, "unavailable"  # 5xx, timeouts, connection problems: do not guess

    # ------------------------------------------------------------------ public API
    def get_page(self, url: str) -> FetchResult:
        """GET an HTML page: robots-checked, throttled, retried, same-site redirects only."""
        return self._fetch(url, check_robots=True, html_only=True, max_bytes=conf.get("HTTP_MAX_BYTES"))

    def post_form(self, url: str, fields: Sequence[tuple[str, str]] | Mapping[str, str], *, multipart: bool = False, referer: str | None = None) -> FetchResult:
        """POST a form ONCE (never retried). ``url`` is checked against robots.txt first.

        A 3xx answer is not followed with a POST; if it points inside the same site, one GET reads the
        page it lands on (so the caller can look for a thank-you message)."""
        pairs = list(fields.items()) if isinstance(fields, Mapping) else list(fields)
        try:
            target = self._prepare(url)
        except _Refused as refused:
            return FetchResult(url=url, final_url=url, outcome=refused.outcome, error=refused.message)
        if self._respect_robots:
            allowed, state = self.robots_allows(url)
            if not allowed:
                outcome = ROBOTS_UNAVAILABLE if state == "unavailable" else ROBOTS_BLOCKED
                return FetchResult(url=url, final_url=url, outcome=outcome)
        self._throttle.wait(target.host, conf.get("HTTP_DOMAIN_DELAY"))
        if multipart:
            kwargs = {"files": [(name, (None, value)) for name, value in pairs]}
        else:
            merged: dict[str, list[str]] = {}
            for name, value in pairs:
                merged.setdefault(name, []).append(value)
            kwargs = {"data": {k: (v[0] if len(v) == 1 else v) for k, v in merged.items()}}
        result = self._send("POST", target, html_only=False, max_bytes=conf.get("HTTP_MAX_BYTES"), referer=referer, **kwargs)
        result.url = url
        result.final_url = url
        result.attempts = 1
        if result.ok and 300 <= result.status < 400 and result.location:
            landing = urljoin(url, result.location)
            if _same_site(url, landing):
                follow = self._fetch(landing, check_robots=True, html_only=True, max_bytes=conf.get("HTTP_MAX_BYTES"))
                result.text, result.final_url = follow.text, follow.final_url or landing
        elif result.ok:
            result.final_url = url
        return result

    # ------------------------------------------------------------------ the redirect loop
    def _fetch(self, url: str, *, check_robots: bool, html_only: bool, max_bytes: int) -> FetchResult:
        redirects: list[str] = []
        current = url
        origin = url
        for _ in range(int(conf.get("HTTP_MAX_REDIRECTS")) + 1):
            try:  # first of all: is this address even allowed to be contacted? (its robots.txt comes after)
                target = self._prepare(current)
            except _Refused as refused:
                return FetchResult(url=url, final_url=current, outcome=refused.outcome, error=refused.message, redirects=redirects)
            if check_robots and self._respect_robots:
                allowed, state = self.robots_allows(current)
                if not allowed:
                    outcome = ROBOTS_UNAVAILABLE if state == "unavailable" else ROBOTS_BLOCKED
                    return FetchResult(url=url, final_url=current, outcome=outcome, redirects=redirects)
            result = self._get_with_retries(target, html_only=html_only, max_bytes=max_bytes)
            result.url, result.final_url, result.redirects = url, current, redirects
            if 300 <= result.status < 400 and result.location:
                nxt = urljoin(current, result.location)
                if not _same_site(origin, nxt):
                    result.outcome, result.final_url, result.error = REDIRECT_OFFSITE, nxt, f"هدایت به {urlsplit(nxt).hostname}"
                    return result
                redirects.append(nxt)
                current = nxt
                continue
            return result
        return FetchResult(url=url, final_url=current, outcome=REDIRECT_LOOP, redirects=redirects)
