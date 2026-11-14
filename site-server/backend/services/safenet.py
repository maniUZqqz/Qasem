"""Safe outbound GET for features that fetch things a user (or a catalogue) points at: images, web pages, markdown, JSON.

What it guarantees (the same rules as the growth engine's ``SafeFetcher``, but for any content type and with no robots.txt logic of its own):

* only http / https on ordinary ports (80, 443, 8080, 8443);
* SSRF guard: the host is resolved HERE and refused unless every address is public; the request is then sent to the address that was
  checked (Host header + TLS SNI carry the name), so DNS cannot be switched between «check» and «connect»;
* every redirect hop is checked again (at most ``MAX_HOPS``);
* a hard size cap while streaming and a timeout; a clear, honest User-Agent;
* nothing is ever logged with a query string (it may carry a key).

``get(url, ...)`` returns ``Fetched``; every failure is a ``FetchError`` whose message is Persian and safe to show.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

_UA_BASE = "NMarketingBot/1.0"


def user_agent() -> str:
    """Honest and descriptive; open catalogues (Wikimedia, 21st.dev) ask bots to say who they are, and reject anonymous ones.
    The contact is the site's own address (``NM_BOT_CONTACT`` or ``PUBLIC_BASE_URL``), never a person."""
    contact = (os.environ.get("NM_BOT_CONTACT") or os.environ.get("PUBLIC_BASE_URL") or "").strip()
    return f"{_UA_BASE} (+{contact}; reference and catalogue reader)" if contact else f"{_UA_BASE} (reference and catalogue reader)"


ALLOWED_PORTS = (80, 443, 8080, 8443)
MAX_HOPS = 4
DEFAULT_TIMEOUT = 20.0


class FetchError(Exception):
    """Persian message for the user; ``code`` is a stable key for tests / logs."""

    def __init__(self, message: str, code: str = "fetch"):
        super().__init__(message)
        self.message, self.code = message, code


@dataclass
class Fetched:
    url: str
    status: int
    content_type: str
    body: bytes
    headers: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        enc = "utf-8"
        ct = self.content_type.lower()
        if "charset=" in ct:
            enc = ct.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(enc, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    return sorted(addresses, key=lambda a: ":" in a)          # IPv4 first: the server may have no IPv6 route


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_global and not ip.is_multicast)


def redact(url: str) -> str:
    """The URL without its query string (safe for logs and messages)."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def _prepare(url: str, resolver):
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError as exc:
        raise FetchError("نشانی معتبر نیست.", "bad_url") from exc
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower().strip(".")
    if scheme not in ("http", "https") or not host:
        raise FetchError("فقط نشانیِ http یا https پذیرفته می‌شود.", "bad_url")
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise FetchError("نامِ دامنه معتبر نیست.", "bad_url") from exc
    port = port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise FetchError("این درگاه (port) پذیرفته نمی‌شود.", "bad_port")
    try:
        ipaddress.ip_address(host.strip("[]"))
        addresses = [host.strip("[]")]
    except ValueError:
        try:
            addresses = list((resolver or default_resolver)(host, port))
        except OSError as exc:
            raise FetchError("نشانی پیدا نشد (DNS).", "dns") from exc
    if not addresses:
        raise FetchError("نشانی پیدا نشد (DNS).", "dns")
    if not all(is_public_ip(a) for a in addresses):
        raise FetchError("این نشانی به شبکهٔ داخلی اشاره می‌کند و باز نمی‌شود.", "ssrf")
    path_query = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return scheme, host, port, addresses[0], path_query


def get(url: str, *, max_bytes: int = 2_000_000, accept: str = "*/*", timeout: float = DEFAULT_TIMEOUT, headers: dict | None = None,
        resolver=None, transport: httpx.BaseTransport | None = None, allow_status=(200,)) -> Fetched:
    """GET ``url`` safely; follows at most ``MAX_HOPS`` redirects (each one re-checked). Status outside ``allow_status`` ⇒ FetchError(http_<n>)."""
    current = url
    started = time.monotonic()
    client = httpx.Client(transport=transport or httpx.HTTPTransport(retries=0), timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
                          follow_redirects=False, verify=True)
    try:
        for _hop in range(MAX_HOPS + 1):
            scheme, host, port, ip, path_query = _prepare(current, resolver)
            default = 443 if scheme == "https" else 80
            host_header = host if port == default else f"{host}:{port}"
            ip_s = f"[{ip}]" if ":" in ip else ip
            req_url = f"{scheme}://{ip_s}:{port}{path_query}"
            hdrs = {"Host": host_header, "User-Agent": user_agent(), "Accept": accept, "Accept-Language": "fa,en;q=0.8"}
            hdrs.update(headers or {})
            ext = {"sni_hostname": host} if scheme == "https" else {}
            try:
                with client.stream("GET", req_url, headers=hdrs, extensions=ext) as resp:
                    status = resp.status_code
                    if 300 <= status < 400 and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    ctype = resp.headers.get("content-type", "")
                    chunks, total = [], 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError("فایل بزرگ‌تر از سقفِ مجاز است.", "too_large")
                        chunks.append(chunk)
                        if time.monotonic() - started > timeout * 3:
                            raise FetchError("دریافت خیلی طول کشید.", "timeout")
                    if status not in allow_status:
                        raise FetchError(f"سایت جواب {status} داد.", f"http_{status}")
                    return Fetched(url=redact(current), status=status, content_type=ctype, body=b"".join(chunks),
                                   headers={k.lower(): v for k, v in resp.headers.items()})
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
                raise FetchError("سایت به‌موقع جواب نداد.", "timeout") from exc
            except httpx.HTTPError as exc:
                raise FetchError("اتصال به سایت برقرار نشد.", "connect") from exc
        raise FetchError("ریدایرکت‌ها بیش از حد بود.", "redirects")
    finally:
        client.close()
