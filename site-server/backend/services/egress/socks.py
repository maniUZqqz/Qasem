"""A small SOCKS5 client (RFC 1928 + RFC 1929 user/password), with no third-party package.

Why it is here: a V2Ray / Xray client that the owner may run on this server offers a SOCKS port (127.0.0.1:10808 and the like),
and ``requests`` / ``httpx`` can speak SOCKS only when ``PySocks`` / ``socksio`` are installed. Those are not on the server, and
«install a package» is exactly the kind of step this feature must not leave behind. So the handshake lives here (about sixty
lines) and is plugged into both libraries:

* ``requests`` - ``SocksAdapter`` (an urllib3 pool manager whose connections are opened through the proxy);
* ``httpx``    - ``httpx_transport`` (an httpcore network backend that opens its sockets through the proxy).

``socks5`` resolves the destination name on this machine (and sends the address); ``socks5h`` sends the NAME to the proxy, which
resolves it there. In Iran the second is almost always what is wanted: the local resolver lies about filtered sites.
"""
from __future__ import annotations

import ipaddress
import socket
import struct

CONNECT_TIMEOUT = 15.0

_REPLY = {
    1: ("general", "خطای کلیِ پراکسی"),
    2: ("denied", "پراکسی این اتصال را مجاز نکرد"),
    3: ("unreachable", "شبکهٔ مقصد از پراکسی در دسترس نیست"),
    4: ("unreachable", "میزبانِ مقصد از پراکسی در دسترس نیست"),
    5: ("target_refused", "مقصد اتصال را نپذیرفت"),
    6: ("ttl", "زمانِ اتصال در پراکسی تمام شد"),
    7: ("protocol", "پراکسی این دستور را نمی‌شناسد"),
    8: ("protocol", "پراکسی این نوعِ نشانی را نمی‌شناسد"),
}


class SocksError(OSError):
    """The SOCKS handshake failed. ``kind`` is a stable key; ``code`` the SOCKS reply code when there is one."""

    def __init__(self, kind: str, message: str = "", code: int | None = None):
        super().__init__(message or kind)
        self.kind, self.code, self.detail = kind, code, message


def _recv(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise SocksError("closed", "پراکسی اتصال را وسطِ دست‌دادن بست")
        data += chunk
    return data


def connect(
    proxy_host: str, proxy_port: int, dest_host: str, dest_port: int, *, username: str = "", password: str = "",
    remote_dns: bool = True, timeout: float | None = None, source_address=None, socket_options=None,
) -> socket.socket:
    """A TCP socket to ``dest_host:dest_port`` opened THROUGH the SOCKS5 proxy. Raises ``SocksError`` for a failed handshake and
    ``OSError`` (refused, timeout, DNS of the proxy's own name) when the proxy itself cannot be reached."""
    timeout = CONNECT_TIMEOUT if timeout is None or not isinstance(timeout, (int, float)) else float(timeout)
    sock = socket.create_connection((proxy_host, int(proxy_port)), timeout, source_address)
    try:
        for level, option, value in socket_options or ():
            sock.setsockopt(level, option, value)
        sock.settimeout(timeout)
        user, pw = username.encode("utf-8"), password.encode("utf-8")
        methods = b"\x00\x02" if user else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        version, method = _recv(sock, 2)
        if version != 5:
            raise SocksError("protocol", "پاسخِ پراکسی SOCKS نبود")
        if method == 0x02:
            if not user or len(user) > 255 or len(pw) > 255:
                raise SocksError("auth", "نامِ کاربری یا رمزِ پراکسی نادرست است")
            sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pw)]) + pw)
            _, status = _recv(sock, 2)
            if status != 0:
                raise SocksError("auth", "پراکسی نامِ کاربری یا رمز را نپذیرفت")
        elif method == 0xFF:
            raise SocksError("auth", "پراکسی هیچ‌کدام از روش‌های ورود را نپذیرفت")
        elif method != 0x00:
            raise SocksError("protocol", "روشِ ورودِ ناشناختهٔ پراکسی")

        dest_host = (dest_host or "").strip("[]")
        try:
            ip = ipaddress.ip_address(dest_host)
            request = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        except ValueError:
            if remote_dns:
                name = dest_host.encode("idna")
                if len(name) > 255:
                    raise SocksError("protocol", "نامِ میزبان بیش از حد بلند است") from None
                request = b"\x03" + bytes([len(name)]) + name
            else:
                try:
                    infos = socket.getaddrinfo(dest_host, dest_port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                except OSError:        # the DESTINATION's name did not resolve on this machine (not the proxy's fault: say so)
                    raise SocksError("dns", "نامِ سایت روی این سرور پیدا نشد؛ با socks5h بگذارید تا خودِ پراکسی آن را پیدا کند") from None
                ip = ipaddress.ip_address(sorted((i[4][0] for i in infos), key=lambda a: ":" in a)[0])
                request = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        sock.sendall(b"\x05\x01\x00" + request + struct.pack(">H", int(dest_port)))
        version, reply, _reserved, atyp = _recv(sock, 4)
        if version != 5:
            raise SocksError("protocol", "پاسخِ پراکسی SOCKS نبود")
        if reply != 0:
            kind, text = _REPLY.get(reply, ("general", "خطای ناشناختهٔ پراکسی"))
            raise SocksError(kind, text, code=reply)
        skip = {1: 4, 4: 16}.get(atyp)
        if atyp == 3:
            skip = _recv(sock, 1)[0]
        if skip is None:
            raise SocksError("protocol", "پاسخِ پراکسی قابل‌فهم نبود")
        _recv(sock, skip + 2)
        sock.settimeout(None)
        return sock
    except BaseException:
        sock.close()
        raise


# ----------------------------------------------------------------------------------------------- requests (urllib3)

def _options(route) -> dict:
    return {
        "host": route.host, "port": route.port, "username": route.username, "password": route.password,
        "remote_dns": route.scheme != "socks5",
    }


def _build_adapter_classes():
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
    from urllib3.poolmanager import PoolManager
    from requests.adapters import HTTPAdapter

    class _Mixin:
        def __init__(self, *args, _socks_options=None, **kwargs):
            self._socks_options = _socks_options or {}
            super().__init__(*args, **kwargs)

        def _new_conn(self):
            opts = self._socks_options
            try:
                return connect(
                    opts["host"], opts["port"], self.host, self.port, username=opts.get("username", ""),
                    password=opts.get("password", ""), remote_dns=opts.get("remote_dns", True), timeout=self.timeout,
                    source_address=self.source_address, socket_options=self.socket_options,
                )
            except socket.timeout as exc:
                raise ConnectTimeoutError(self, "Connection to the SOCKS proxy timed out") from exc
            except OSError as exc:        # SocksError is an OSError too: it travels in __cause__ and the egress layer reads its kind
                raise NewConnectionError(self, "Failed to establish a new connection through the SOCKS proxy") from exc

    class _HTTPConn(_Mixin, HTTPConnection):
        pass

    class _HTTPSConn(_Mixin, HTTPSConnection):
        pass

    class _HTTPPool(HTTPConnectionPool):
        ConnectionCls = _HTTPConn

    class _HTTPSPool(HTTPSConnectionPool):
        ConnectionCls = _HTTPSConn

    class _Manager(PoolManager):
        def __init__(self, socks_options, num_pools=10, headers=None, **pool_kw):
            pool_kw["_socks_options"] = socks_options
            super().__init__(num_pools, headers, **pool_kw)
            self.pool_classes_by_scheme = {"http": _HTTPPool, "https": _HTTPSPool}

    class Adapter(HTTPAdapter):
        def __init__(self, socks_options, **kwargs):
            self._socks_options = socks_options
            super().__init__(**kwargs)

        def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
            self.poolmanager = _Manager(self._socks_options, num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)

    return Adapter


_ADAPTER = None


def requests_adapter(route):
    """An ``HTTPAdapter`` that opens every connection through the route's SOCKS5 proxy (mount it for http:// and https://)."""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = _build_adapter_classes()
    return _ADAPTER(_options(route))


# ----------------------------------------------------------------------------------------------- httpx (httpcore)

def httpx_transport(route, verify=True):
    """An ``httpx.HTTPTransport`` whose sockets are opened through the route's SOCKS5 proxy (``verify``: True, or a CA bundle path)."""
    import httpcore
    import httpx
    from httpcore._backends.sync import SyncStream

    opts = _options(route)

    class _Backend(httpcore.SyncBackend):
        def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            source = (local_address, 0) if local_address else None
            try:
                sock = connect(opts["host"], opts["port"], host, port, username=opts["username"], password=opts["password"],
                               remote_dns=opts["remote_dns"], timeout=timeout, source_address=source, socket_options=socket_options)
            except socket.timeout as exc:
                raise httpcore.ConnectTimeout(exc) from exc
            except OSError as exc:        # SocksError included: kept as __cause__ for the egress layer
                raise httpcore.ConnectError(exc) from exc
            return SyncStream(sock)

    transport = httpx.HTTPTransport(trust_env=False)
    transport._pool = httpcore.ConnectionPool(
        ssl_context=httpx.create_ssl_context(verify=verify, trust_env=False), max_connections=20, max_keepalive_connections=10,
        keepalive_expiry=5.0, http1=True, http2=False, network_backend=_Backend(),
    )
    return transport
