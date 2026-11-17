# -*- coding: utf-8 -*-
"""اتصالِ پایدار به 21st.dev از اینترنتِ ایران (خزندهٔ c21_crawl).

مسئله (۱۱/۱۶، سنجیده روی همین سرور): ۲۱st.dev دو نشانیِ IP دارد؛ از ایران هر اتصالِ TCP فقط گاهی (حدودِ یک از شش) در یک ثانیه برقرار می‌شود و بقیه
تا زمان‌سنج می‌مانند. ``safenet.get`` برای هر درخواست یک اتصالِ تازه به **اولین** نشانی می‌زند و ده ثانیه صبر می‌کند ⇒ خزش ساعتی ~۸ صفحه جلو می‌رفت.
چاره‌ی این ماژول (همان رفتارِ مؤدبانه، فقط هوشمندانه‌تر):

* **اتصالِ هم‌زمانِ چندتایی (hedged)**: چند اتصالِ TCP هم‌زمان به همهٔ نشانی‌ها؛ اولی که برقرار شد برنده است و بقیه بسته می‌شوند. هر دور ``CONNECT_TIMEOUT`` ثانیه،
  تا ``ROUNDS`` دور (بسته‌های SYN هستند؛ بارِ واقعی روی سرورِ مقصد نیست).
* **Keep-Alive**: یک اتصال برای همهٔ درخواست‌های پیاپی (HTTP/1.1) تا قطع شود؛ قطع شد ⇒ یک بار اتصالِ تازه و همان درخواست دوباره (GET بی‌اثر است).
* همان نگهبانی‌های ``safenet``: فقط نشانی‌های عمومی (SSRF)، فقط https روی ۴۴۳، سقفِ حجم، ریدایرکتِ هم‌میزبان (۴ گام)، User-Agent صادق، ریدایرکتِ میزبانِ دیگر ⇒ ``safenet.get``.
* ⇒ ``Fetched`` و ``FetchError`` (همان کدها: ``connect``، ``timeout``، ``http_<n>``) پس ``c21_crawl.Session`` بی‌تغییر کار می‌کند.
"""
from __future__ import annotations

import gzip
import http.client
import io
import queue
import socket
import ssl
import threading
import time
import zlib
from urllib.parse import urljoin, urlsplit

from services import safenet

CONNECT_TIMEOUT = 4.0          # ثانیه برای هر دورِ اتصال
ROUNDS = 4                     # حداکثر دورِ اتصال در یک درخواست
PARALLEL = 6                   # اتصال‌های هم‌زمان در هر دور (بین نشانی‌ها پخش می‌شود)
IO_TIMEOUT = 25.0              # خواندن/نوشتن روی اتصالِ برقرار
IDLE_MAX_S = 45.0              # اتصالِ بیکارتر از این دوباره باز می‌شود (سرورِ مقصد معمولاً زودتر می‌بندد)
HOSTS = ("21st.dev",)          # فقط این میزبان‌ها از این راه می‌روند؛ بقیه ⇒ safenet.get

_lock = threading.Lock()
_conns: dict[str, "_Conn"] = {}


def _race_connect(addresses: list[str], port: int, *, parallel: int, timeout: float, rounds: int, deadline: float, connect=socket.create_connection) -> socket.socket | None:
    """⇒ سوکتِ برقرارشده یا None. اتصال‌های هم‌زمان؛ برندهٔ هر دور بقیه را بی‌اثر می‌کند."""
    for _r in range(rounds):
        left = deadline - time.monotonic()
        if left <= 0.3:
            break
        tmo = min(timeout, left)
        q: queue.Queue = queue.Queue()
        stop = threading.Event()

        def attempt(ip):
            try:
                s = connect((ip, port), timeout=tmo)
            except OSError:
                q.put(None)
                return
            if stop.is_set():
                s.close()
                return
            q.put(s)

        n = max(1, min(parallel, 12))
        for i in range(n):
            threading.Thread(target=attempt, args=(addresses[i % len(addresses)],), daemon=True).start()
        got, seen = None, 0
        while seen < n:
            try:
                s = q.get(timeout=tmo + 1.0)
            except queue.Empty:
                break
            seen += 1
            if s is not None:
                got = s
                break
        stop.set()
        if got is not None:
            def drain(count=n - seen):
                for _ in range(count):
                    try:
                        x = q.get(timeout=tmo + 1.0)
                    except queue.Empty:
                        return
                    if x is not None:
                        x.close()
            threading.Thread(target=drain, daemon=True).start()
            return got
    return None


class _Conn:
    """یک اتصالِ Keep-Alive به یک میزبان."""

    def __init__(self, host: str):
        self.host = host
        self.http: http.client.HTTPSConnection | None = None
        self.used_at = 0.0
        self.lock = threading.Lock()

    def close(self) -> None:
        if self.http is not None:
            try:
                self.http.close()
            except OSError:
                pass
        self.http = None

    def open(self, addresses: list[str], deadline: float, connect_race=None) -> None:
        self.close()
        sock = (connect_race or _race_connect)(addresses, 443, parallel=PARALLEL, timeout=CONNECT_TIMEOUT, rounds=ROUNDS, deadline=deadline)
        if sock is None:
            raise safenet.FetchError("اتصال به سایت برقرار نشد.", "connect")
        try:
            sock.settimeout(max(5.0, min(IO_TIMEOUT, deadline - time.monotonic() + 8.0)))
            tls = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        except (OSError, ssl.SSLError) as exc:
            try:
                sock.close()
            except OSError:
                pass
            raise safenet.FetchError("اتصال امن به سایت برقرار نشد.", "connect") from exc
        tls.settimeout(IO_TIMEOUT)
        c = http.client.HTTPSConnection(self.host, 443, timeout=IO_TIMEOUT)
        c.sock = tls
        self.http = c
        self.used_at = time.monotonic()


def _decode(body: bytes, enc: str, max_bytes: int) -> bytes:
    enc = (enc or "").lower()
    if enc in ("", "identity"):
        return body
    try:
        if enc == "gzip":
            return _bounded(gzip.GzipFile(fileobj=io.BytesIO(body)), max_bytes)
        if enc == "deflate":
            d = zlib.decompressobj()
            out = d.decompress(body, max_bytes + 1)
            if len(out) > max_bytes:
                raise safenet.FetchError("فایل بزرگ‌تر از سقفِ مجاز است.", "too_large")
            return out
    except (OSError, zlib.error, EOFError) as exc:
        raise safenet.FetchError("پاسخِ فشرده خراب بود.", "fetch") from exc
    return body


def _bounded(fh, max_bytes: int) -> bytes:
    out = fh.read(max_bytes + 1)
    if len(out) > max_bytes:
        raise safenet.FetchError("فایل بزرگ‌تر از سقفِ مجاز است.", "too_large")
    return out


def _request(conn: _Conn, path: str, headers: dict, max_bytes: int, deadline: float, addresses: list[str]):
    """یک GET روی اتصالِ نگه‌داشته؛ قطع شده بود ⇒ یک بار اتصالِ تازه. ⇒ (status, headers, body)."""
    for attempt in (0, 1):
        fresh = False
        if conn.http is None or time.monotonic() - conn.used_at > IDLE_MAX_S:
            conn.open(addresses, deadline)
            fresh = True
        try:
            conn.http.request("GET", path, headers=headers)
            resp = conn.http.getresponse()
            chunks, total = [], 0
            wire_cap = max_bytes * 4 + 4096                                   # فشرده بزرگ‌تر از این هم نمی‌خوانیم
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > wire_cap:
                    conn.close()
                    raise safenet.FetchError("فایل بزرگ‌تر از سقفِ مجاز است.", "too_large")
                chunks.append(chunk)
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            if hdrs.get("connection", "").lower() == "close" or resp.will_close:
                conn.close()
            else:
                conn.used_at = time.monotonic()
            return resp.status, hdrs, _decode(b"".join(chunks), hdrs.get("content-encoding", ""), max_bytes)
        except (socket.timeout, TimeoutError) as exc:
            conn.close()
            if attempt == 0 and not fresh:
                continue
            raise safenet.FetchError("سایت به‌موقع جواب نداد.", "timeout") from exc
        except (http.client.HTTPException, OSError, ssl.SSLError) as exc:
            conn.close()
            if attempt == 0 and not fresh:
                continue                                                    # اتصالِ کهنه بود؛ تازه بساز
            raise safenet.FetchError("اتصال به سایت برقرار نشد.", "connect") from exc
    raise safenet.FetchError("اتصال به سایت برقرار نشد.", "connect")


def _resolve(host: str, port: int, resolver=None) -> list[str]:
    """نگهبانِ SSRF: همهٔ نشانی‌ها باید عمومی باشند (همان قاعدهٔ safenet)؛ IPv4 اول."""
    try:
        addrs = list((resolver or safenet.default_resolver)(host, port))
    except OSError as exc:
        raise safenet.FetchError("نشانی پیدا نشد (DNS).", "dns") from exc
    if not addrs:
        raise safenet.FetchError("نشانی پیدا نشد (DNS).", "dns")
    if not all(safenet.is_public_ip(a) for a in addrs):
        raise safenet.FetchError("این نشانی به شبکهٔ داخلی اشاره می‌کند و باز نمی‌شود.", "ssrf")
    return [a for a in addrs if ":" not in a] or addrs


def reset() -> None:
    """بستنِ همهٔ اتصال‌های نگه‌داشته (آزمون و پایانِ نوبت)."""
    with _lock:
        for c in _conns.values():
            c.close()
        _conns.clear()


def get(url: str, *, max_bytes: int = 2_000_000, accept: str = "*/*", timeout: float = 30.0, headers: dict | None = None, resolver=None, allow_status=(200,)) -> safenet.Fetched:
    """همان امضای ``safenet.get``. میزبانِ غیر از HOSTS یا نشانیِ غیر-https ⇒ ``safenet.get``."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in HOSTS or (parts.port not in (None, 443)):
        return safenet.get(url, max_bytes=max_bytes, accept=accept, timeout=min(timeout, 30.0), headers=headers, resolver=resolver, allow_status=allow_status)
    deadline = time.monotonic() + max(8.0, timeout)
    current = url
    for _hop in range(safenet.MAX_HOPS + 1):
        cur = urlsplit(current)
        host, port = (cur.hostname or "").lower(), 443
        path_query = (cur.path or "/") + (f"?{cur.query}" if cur.query else "")
        addrs = _resolve(host, port, resolver)
        hdrs = {"Host": host, "User-Agent": safenet.user_agent(), "Accept": accept, "Accept-Language": "fa,en;q=0.8", "Accept-Encoding": "gzip", "Connection": "keep-alive"}
        hdrs.update(headers or {})
        with _lock:
            conn = _conns.setdefault(host, _Conn(host))
        with conn.lock:
            status, rh, body = _request(conn, path_query, hdrs, max_bytes, deadline, addrs)
        if 300 <= status < 400 and rh.get("location"):
            current = urljoin(current, rh["location"])
            nxt = urlsplit(current)
            if (nxt.hostname or "").lower() not in HOSTS or nxt.scheme != "https":
                return safenet.get(current, max_bytes=max_bytes, accept=accept, timeout=20.0, headers=headers, resolver=resolver, allow_status=allow_status)
            continue
        if status not in allow_status:
            raise safenet.FetchError(f"سایت جواب {status} داد.", f"http_{status}")
        return safenet.Fetched(url=safenet.redact(current), status=status, content_type=rh.get("content-type", ""), body=body, headers=rh)
    raise safenet.FetchError("ریدایرکت‌ها بیش از حد بود.", "redirects")
