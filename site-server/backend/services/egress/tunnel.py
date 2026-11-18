"""A raw TCP socket to ``host:port`` opened THROUGH a route's proxy - for clients that speak their own protocol (Telegram's MTProto).

``requests`` / ``httpx`` have their own proxy support (``core.py``); this is for everything else:

* SOCKS5 / SOCKS5h  - ``socks.connect`` (RFC 1928 / 1929);
* HTTP / HTTPS      - ``CONNECT host:port`` (with ``Proxy-Authorization: Basic`` when the proxy has a login). An «https» proxy is
                      spoken to in plain text here as well (the same as every HTTP-proxy client that does not wrap the proxy hop in TLS).

``telethon_kwargs()`` plugs this into a Telethon ``TelegramClient`` (the caller-ID lookup of ``apps.mobile`` talks MTProto to Telegram's
data centres, which are filtered from Iran exactly like the bot API): ``TelegramClient(..., **egress.telethon_kwargs())``. When «telegram»
is direct it returns ``{}`` and Telethon connects the way it always did. Nothing here needs ``PySocks`` / ``python-socks``.
"""
from __future__ import annotations

import asyncio
import functools
import socket
from base64 import b64encode

from . import errors, socks
from .core import Route, route_for

CONNECT_TIMEOUT = 15.0


class TunnelError(OSError):
    """The HTTP proxy refused the CONNECT (``status`` is its answer)."""

    def __init__(self, status: int, text: str = ""):
        super().__init__(f"proxy answered {status} {text}".strip())
        self.status = status


def _http_connect(route: Route, host: str, port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection((route.host, int(route.port)), timeout)
    try:
        sock.settimeout(timeout)
        head = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        if route.username:
            token = b64encode(f"{route.username}:{route.password}".encode("utf-8")).decode("ascii")
            head += f"Proxy-Authorization: Basic {token}\r\n"
        sock.sendall((head + "\r\n").encode("latin-1"))
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise socks.SocksError("closed", "پراکسی اتصال را وسطِ دست‌دادن بست")
            data += chunk
            if len(data) > 65536:
                raise socks.SocksError("protocol", "پاسخِ پراکسی قابل‌فهم نبود")
        line = data.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split(" ", 2)
        if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
            raise socks.SocksError("protocol", "پاسخِ پراکسی قابل‌فهم نبود")
        status = int(parts[1])
        if status != 200:
            raise TunnelError(status, parts[2] if len(parts) > 2 else "")
        sock.settimeout(None)
        return sock
    except BaseException:
        sock.close()
        raise


def open_socket(route: Route, host: str, port: int, *, timeout: float | None = None) -> socket.socket:
    """A connected TCP socket to ``host:port`` through ``route``. Raises ``EgressError`` (Persian, secret-free) when the PROXY is what failed."""
    timeout = CONNECT_TIMEOUT if timeout is None else float(timeout)
    try:
        if route.is_socks:
            return socks.connect(route.host, int(route.port), host, int(port), username=route.username, password=route.password,
                                 remote_dns=route.scheme != "socks5", timeout=timeout)
        return _http_connect(route, host, int(port), timeout)
    except errors.EgressError:
        raise
    except TunnelError as exc:
        if exc.status == 407:
            raise errors.EgressError("auth", errors.message_for("auth", route), service=route.service, proxy_name=route.name) from None
        kind = "denied" if exc.status in (401, 403) else "tunnel"
        raise errors.EgressError(kind, errors.message_for(kind, route, status=exc.status, target=host), service=route.service,
                                 proxy_name=route.name) from None
    except socks.SocksError as exc:
        kind, message = errors.socks_message(exc, route, host)
        raise errors.EgressError(kind, message, service=route.service, proxy_name=route.name) from None
    except OSError as exc:          # the connection to the proxy itself: refused, timed out, its name did not resolve
        if isinstance(exc, ConnectionRefusedError):
            kind = "refused"
        elif isinstance(exc, (socket.timeout, TimeoutError)):
            kind = "timeout"
        elif isinstance(exc, socket.gaierror):
            kind = "dns"
        else:
            kind = "failed"
        cls = errors.EgressTimeout if kind == "timeout" else errors.EgressError
        raise cls(kind, errors.message_for(kind, route), service=route.service, proxy_name=route.name) from None


# ------------------------------------------------------------------------------------------------ Telethon

def telethon_kwargs(service: str = "telegram") -> dict:
    """Extra keyword arguments for ``telethon.TelegramClient`` so its MTProto connections leave through the route of ``service``
    (``{}`` when that service is direct, which is the default)."""
    route = route_for(service)
    if not route.proxied:
        return {}
    from telethon.network.connection.tcpfull import ConnectionTcpFull

    class EgressConnection(ConnectionTcpFull):
        """Telethon's default transport, with the socket opened through the owner's proxy (Telethon calls ``_proxy_connect`` whenever a
        proxy is set; the tuple passed as ``proxy`` below is only what makes it do so - the real route is read here)."""

        async def _proxy_connect(self, timeout=None, local_addr=None):
            loop = asyncio.get_running_loop()
            sock = await loop.run_in_executor(None, functools.partial(open_socket, route, self._ip, self._port, timeout=timeout or CONNECT_TIMEOUT))
            sock.setblocking(False)
            return sock

    return {"connection": EgressConnection, "proxy": ("egress", route.host, int(route.port))}
