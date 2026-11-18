"""Raw TCP through a proxy (Telegram's MTProto client, Telethon): CONNECT and SOCKS5 against the fake proxies of ``fakes.py``."""
from __future__ import annotations

import asyncio
import collections
import logging
import socket
from unittest import skipUnless

from services import egress
from services.egress import tunnel

from . import fakes
from .tests import SECRET, EgressCase

try:
    import telethon  # noqa: F401
    HAVE_TELETHON = True
except Exception:  # noqa: BLE001
    HAVE_TELETHON = False

DC = "149.154.167.51"            # a Telegram data-centre address; the fake proxy connects to its own target whatever is asked


def ask(sock: socket.socket) -> bytes:
    """Speak plain HTTP over a tunnel (the fake target answers HTTP) and return the body."""
    sock.sendall(b"GET /json HTTP/1.0\r\nHost: dc\r\n\r\n")
    data = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    sock.close()
    return data


class OpenSocketTests(EgressCase):
    def test_a_socket_through_an_http_proxy_uses_connect(self):
        route = egress.Route("telegram", 1, "VPN دفتر", "http", "127.0.0.1", self.http.port)
        self.assertIn(b"203.0.113.7", ask(tunnel.open_socket(route, DC, 443, timeout=5)))
        self.assertEqual(self.http.connects, [f"{DC}:443"])

    def test_a_socket_through_socks5_gets_the_address_or_the_name(self):
        route = egress.Route("telegram", 1, "VPN", "socks5h", "127.0.0.1", self.socks.port)
        self.assertIn(b"203.0.113.7", ask(tunnel.open_socket(route, DC, 443, timeout=5)))
        ask(tunnel.open_socket(route, "dc.telegram.org", 443, timeout=5))
        self.assertEqual(self.socks.connects, [(DC, 443), ("dc.telegram.org", 443)])
        self.assertEqual([e[3] for e in self.socks.events], [1, 3])                       # ATYP 1 = an IPv4 address, 3 = a name

    def test_the_login_is_sent_and_a_wrong_one_is_said_in_persian(self):
        self.http.credentials = ("ali", SECRET)
        good = egress.Route("telegram", 1, "VPN", "http", "127.0.0.1", self.http.port, "ali", SECRET)
        self.assertIn(b"203.0.113.7", ask(tunnel.open_socket(good, DC, 443, timeout=5)))
        bad = egress.Route("telegram", 1, "VPN", "http", "127.0.0.1", self.http.port, "ali", "wrong")
        with self.assertRaises(egress.EgressError) as ctx:
            tunnel.open_socket(bad, DC, 443, timeout=5)
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertNotIn("wrong", str(ctx.exception))
        self.socks.credentials = ("ali", SECRET)
        bad_socks = egress.Route("telegram", 1, "VPN", "socks5h", "127.0.0.1", self.socks.port, "ali", "wrong")
        with self.assertRaises(egress.EgressError) as ctx:
            tunnel.open_socket(bad_socks, DC, 443, timeout=5)
        self.assertEqual(ctx.exception.kind, "auth")

    def test_a_dead_proxy_a_refusing_proxy_and_a_hanging_proxy_are_named(self):
        dead = egress.Route("telegram", 1, "VPN", "http", "127.0.0.1", fakes.closed_port())
        with self.assertRaises(egress.EgressError) as ctx:
            tunnel.open_socket(dead, DC, 443, timeout=3)
        self.assertEqual(ctx.exception.kind, "refused")
        self.assertIn("برقرار نشد", str(ctx.exception))
        deny = fakes.HttpProxy(self.target.port, reject=True)
        self.addCleanup(deny.stop)
        with self.assertRaises(egress.EgressError) as ctx:
            tunnel.open_socket(egress.Route("telegram", 1, "VPN", "http", "127.0.0.1", deny.port), DC, 443, timeout=3)
        self.assertEqual(ctx.exception.kind, "denied")
        down = fakes.HttpProxy(fakes.closed_port())
        self.addCleanup(down.stop)
        with self.assertRaises(egress.EgressError) as ctx:
            tunnel.open_socket(egress.Route("telegram", 1, "VPN", "http", "127.0.0.1", down.port), DC, 443, timeout=3)
        self.assertEqual(ctx.exception.kind, "tunnel")
        silent = fakes.SilentServer()
        self.addCleanup(silent.stop)
        with self.assertRaises(egress.EgressTimeout):
            tunnel.open_socket(egress.Route("telegram", 1, "VPN", "http", "127.0.0.1", silent.port), DC, 443, timeout=1)
        refusing = fakes.SocksProxy(self.target.port, fail_reply=5)
        self.addCleanup(refusing.stop)
        with self.assertRaises(egress.EgressError) as ctx:
            tunnel.open_socket(egress.Route("telegram", 1, "VPN", "socks5h", "127.0.0.1", refusing.port), DC, 443, timeout=3)
        self.assertEqual(ctx.exception.kind, "tunnel")


@skipUnless(HAVE_TELETHON, "Telethon is not installed")
class TelethonTests(EgressCase):
    LOGGERS = collections.defaultdict(lambda: logging.getLogger("telethon-test"))

    def test_direct_means_telethon_is_left_alone(self):
        self.assertEqual(egress.telethon_kwargs("telegram"), {})
        from apps.mobile import telegram_provider

        client = telegram_provider.TelethonBackend(1, "hash", None)._client()
        self.assertIsNone(client._proxy)

    def test_a_routed_telegram_makes_the_mtproto_connection_leave_through_the_proxy(self):
        self.route("telegram")
        kwargs = egress.telethon_kwargs("telegram")
        self.assertEqual(set(kwargs), {"connection", "proxy"})
        conn = kwargs["connection"](DC, 443, 2, loggers=self.LOGGERS, proxy=kwargs["proxy"])

        async def go():
            sock = await conn._proxy_connect(timeout=5)
            self.assertEqual(sock.getblocking(), False)              # what asyncio.open_connection(sock=...) needs
            reader, writer = await asyncio.open_connection(sock=sock)
            writer.write(b"GET /json HTTP/1.0\r\nHost: dc\r\n\r\n")
            await writer.drain()
            data = await reader.read(65536)
            writer.close()
            return data

        self.assertIn(b"203.0.113.7", asyncio.run(go()))
        self.assertEqual(self.http.connects, [f"{DC}:443"])

    def test_a_routed_telegram_through_socks5h(self):
        self.route("telegram", scheme="socks5h")
        kwargs = egress.telethon_kwargs("telegram")
        conn = kwargs["connection"](DC, 443, 2, loggers=self.LOGGERS, proxy=kwargs["proxy"])
        sock = asyncio.run(conn._proxy_connect(timeout=5))
        sock.setblocking(True)
        self.assertIn(b"203.0.113.7", ask(sock))
        self.assertEqual(self.socks.connects, [(DC, 443)])

    def test_the_account_client_is_built_with_the_route(self):
        from apps.mobile import telegram_provider

        self.route("telegram")
        client = telegram_provider.TelethonBackend(1, "hash", None)._client()
        self.assertTrue(client._proxy)
        self.assertEqual(client._connection.__name__, "EgressConnection")

    def test_a_broken_proxy_is_said_in_persian_and_reaches_the_user_sentence(self):
        from apps.mobile import telegram_provider

        self.route("telegram", port=fakes.closed_port())
        kwargs = egress.telethon_kwargs("telegram")
        conn = kwargs["connection"](DC, 443, 2, loggers=self.LOGGERS, proxy=kwargs["proxy"])
        with self.assertRaises(egress.EgressError) as ctx:
            asyncio.run(conn._proxy_connect(timeout=3))
        self.assertEqual(ctx.exception.kind, "refused")
        self.assertIsInstance(ctx.exception, OSError)                                        # Telethon retries on OSError
        self.assertEqual(telegram_provider._nice(ctx.exception), str(ctx.exception))
        self.assertIn("پراکسی", telegram_provider._nice(ctx.exception))
        self.assertEqual(telegram_provider._nice(RuntimeError("x")), "خطای تلگرام (RuntimeError).")
