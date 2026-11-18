"""What went wrong with a proxy, said in Persian, without a single secret in it.

A ``requests`` / ``httpx`` error quotes the URL it was asking for - and for Telegram the URL contains the bot token - so the
exception text is NEVER shown or logged by this layer. The only things that reach a message are the proxy's own NAME (chosen by
the owner) and ``host:port`` (an address, not a secret), plus a stable ``kind`` key.

``EgressError`` is a ``requests.RequestException``: every call site that already catches that keeps working, and a site that wants the
reason asks ``egress.reason(exc)``.
"""
from __future__ import annotations

import re
import socket

import requests

from . import socks

KINDS = {
    "refused": "اتصال به پراکسی برقرار نشد",
    "timeout": "پراکسی به‌موقع جواب نداد",
    "dns": "نشانیِ پراکسی پیدا نشد",
    "auth": "پراکسی نام کاربری یا رمز را نپذیرفت",
    "denied": "پراکسی اتصال را مجاز ندانست",
    "tunnel": "پراکسی به مقصد وصل نشد",
    "protocol": "پاسخِ پراکسی قابل‌فهم نبود",
    "tls": "اتصالِ امن به پراکسی برقرار نشد",
    "failed": "پراکسی وصل نشد",
}


class EgressError(requests.RequestException):
    """A proxy-level failure. ``str(exc)`` is the safe Persian message."""

    def __init__(self, kind: str, message: str, *, service: str = "", proxy_name: str = ""):
        super().__init__(message)
        self.kind, self.message, self.service, self.proxy_name = kind, message, service, proxy_name

    def __str__(self) -> str:
        return self.message


class EgressTimeout(EgressError, requests.exceptions.Timeout):
    """A proxy that did not answer in time. Also a ``requests.Timeout``, so a call site that treats timeouts specially still does."""


def _where(route) -> str:
    return f"«{route.name}» ({route.host}:{route.port})" if route.name else f"({route.host}:{route.port})"


def message_for(kind: str, route, *, status: int | None = None, target: str = "", detail: str = "") -> str:
    where = _where(route)
    if kind == "refused":
        return (f"اتصال به پراکسی {where} برقرار نشد (پورت بسته است یا برنامهٔ VPN/پراکسی روشن نیست). "
                "نشانی و پورت را بررسی کنید.")
    if kind == "timeout":
        return (f"پراکسی {where} به‌موقع جواب نداد؛ نشانی را بررسی کنید، مطمئن شوید نوعِ آن (http یا socks5) با پورتش می‌خواند "
                "و بعداً دوباره امتحان کنید.")
    if kind == "dns":
        return f"نشانیِ پراکسی {where} پیدا نشد (DNS)؛ نامِ میزبان را بررسی کنید."
    if kind == "auth":
        return f"پراکسی {where} نامِ کاربری یا رمز را نپذیرفت (۴۰۷)؛ ورودی‌ها را بررسی کنید."
    if kind == "denied":
        return f"پراکسی {where} این اتصال را مجاز نکرد" + (f" (پاسخ {status})." if status else ".")
    if kind == "tunnel":
        to = f" ({target})" if target else ""
        return f"پراکسی {where} نتوانست به مقصد{to} وصل شود" + (f" (پاسخ {status})." if status else ".")
    if kind == "tls":
        return f"اتصالِ امن (TLS) به پراکسی {where} برقرار نشد؛ نوعِ پراکسی را بررسی کنید (http یا https؟)."
    if kind == "protocol":
        return (f"پاسخِ پراکسی {where} قابل‌فهم نبود؛ نوعِ آن را بررسی کنید "
                "(http، https، socks5 یا socks5h) و مطمئن شوید پورت مالِ همان نوع است.")
    return f"پراکسی {where} وصل نشد" + (f": {detail}" if detail else ".")


def socks_message(exc: socks.SocksError, route, target: str = "") -> tuple[str, str]:
    """(kind, Persian message) of a failed SOCKS handshake."""
    where = _where(route)
    kind = exc.kind
    if kind == "auth":
        return "auth", f"پراکسی {where} نامِ کاربری یا رمز را نپذیرفت؛ ورودی‌ها را بررسی کنید."
    if kind == "closed":
        return "protocol", f"پراکسی {where} اتصال را وسطِ دست‌دادن بست؛ مطمئن شوید پورت مالِ SOCKS5 است."
    if kind == "dns":
        return "dns_target", "نامِ سایتِ مقصد روی این سرور پیدا نشد (DNS)؛ نوعِ پراکسی را socks5h بگذارید تا خودِ پراکسی نام را پیدا کند."
    if kind == "protocol":
        return "protocol", message_for("protocol", route)
    to = f" ({target})" if target else ""
    return "tunnel", f"پراکسی {where} نتوانست به مقصد{to} وصل شود: {exc.detail or kind}."


def _chain(exc: BaseException):
    seen = set()
    stack = [exc]
    while stack:
        item = stack.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        stack.extend([item.__cause__, item.__context__])
        for arg in getattr(item, "args", ()):  # urllib3 MaxRetryError(reason=...) and friends
            if isinstance(arg, BaseException):
                stack.append(arg)
        reason = getattr(item, "reason", None)
        if isinstance(reason, BaseException):
            stack.append(reason)


def classify(exc: BaseException, route, target: str = "", plain_http: bool = False) -> tuple[str, str] | None:
    """(kind, Persian message) when ``exc`` is a failure of the PROXY itself; None when it is an ordinary error of the destination
    (a 404, a slow site, a certificate problem) that the caller reports in its own words.

    ``plain_http``: the request was an ``http://`` one through an HTTP proxy - there is no tunnel, the only peer is the proxy, so a
    connection that is dropped or answered with nonsense is the proxy's (with a CONNECT tunnel it may be the destination's)."""
    items = list(_chain(exc))
    for item in items:
        if isinstance(item, socks.SocksError):
            return socks_message(item, route, target)
    text = " ".join(str(i) for i in items).lower()
    if plain_http and not route.is_socks and not any(isinstance(i, (socket.timeout, TimeoutError)) for i in items):
        dropped = any(type(i).__name__ in ("RemoteDisconnected", "BadStatusLine", "ConnectionResetError", "ConnectionAbortedError", "ProtocolError")
                      for i in items) or "connection aborted" in text or "connection reset" in text
        if dropped and not any(isinstance(i, ConnectionRefusedError) for i in items):
            return "protocol", message_for("protocol", route)
    tunnel = re.search(r"tunnel connection failed:?\s*(\d{3})", text)
    if tunnel:
        code = int(tunnel.group(1))
        if code == 407:
            return "auth", message_for("auth", route)
        if code in (401, 403):
            return "denied", message_for("denied", route, status=code)
        return "tunnel", message_for("tunnel", route, status=code, target=target)
    is_proxy_error = any(
        isinstance(i, requests.exceptions.ProxyError) or type(i).__name__ in ("ProxyError", "ProxySchemeUnknown", "ProxyConnectionError")
        for i in items)
    refused = any(isinstance(i, ConnectionRefusedError) for i in items) or "connection refused" in text
    dns = any(isinstance(i, socket.gaierror) for i in items) or "name or service not known" in text or "getaddrinfo failed" in text \
        or "nodename nor servname" in text
    timed_out = any(isinstance(i, (socket.timeout, TimeoutError, requests.exceptions.ConnectTimeout)) for i in items) \
        or any(type(i).__name__ in ("ConnectTimeoutError", "ConnectTimeout") for i in items)
    tls = ("wrong version number" in text) or ("ssl" in text and is_proxy_error)
    if is_proxy_error or isinstance(exc, requests.exceptions.ConnectTimeout) or _is_connect_stage(items) or (timed_out and _in_tunnel(items)):
        if re.search(r"\b407\b", text) and "proxy" in text:
            return "auth", message_for("auth", route)
        if tls:
            return "tls", message_for("tls", route)
        if refused:
            return "refused", message_for("refused", route)
        if dns:
            return "dns", message_for("dns", route)
        if timed_out:
            return "timeout", message_for("timeout", route)
        if is_proxy_error:
            if "remote end closed" in text or "invalid" in text or "bad status line" in text or "badstatusline" in text:
                return "protocol", message_for("protocol", route)
            return "failed", message_for("failed", route)
        if timed_out:
            return "timeout", message_for("timeout", route)
    return None


def _in_tunnel(items) -> bool:
    """Did the failure happen while the CONNECT tunnel to the proxy was being set up? (urllib3 / http.client frames say so.) At that stage
    the only peer is the proxy, so even a plain «read timed out» is the proxy's."""
    for item in items:
        tb = getattr(item, "__traceback__", None)
        while tb is not None:
            if tb.tb_frame.f_code.co_name in ("_tunnel", "_prepare_proxy"):
                return True
            tb = tb.tb_next
    return False


def _is_connect_stage(items) -> bool:
    """A failure to even OPEN a connection - with a proxy in the way, the only connection opened is the one to the proxy."""
    return any(type(i).__name__ in ("NewConnectionError", "ConnectError", "ConnectTimeout", "ConnectTimeoutError") for i in items)


def from_exception(exc: BaseException, route, url: str = "") -> EgressError | None:
    """An ``EgressError`` for a proxy-level failure, or None."""
    from urllib.parse import urlsplit

    try:
        target = urlsplit(url).hostname or ""
    except ValueError:
        target = ""
    got = classify(exc, route, target, plain_http=(url or "").lower().startswith("http://"))
    if got is None:
        return None
    kind, message = got
    cls = EgressTimeout if kind == "timeout" else EgressError
    return cls(kind, message, service=route.service, proxy_name=route.name)
