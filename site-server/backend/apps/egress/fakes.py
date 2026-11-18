"""Local fakes for the proxy tests: nothing here (or in the tests that use it) touches the real internet.

* ``Target``      - plays the «foreign service» (api.telegram.org, graph.facebook.com, an IP-echo site ...): a tiny HTTP(S) server that records
                    what it served;
* ``HttpProxy``   - an HTTP proxy: forwards absolute-URI requests and tunnels ``CONNECT``; optional Basic login; ALWAYS connects to the
                    ``Target`` whatever host was asked for, and records what it was asked for (that is how a test proves «this call
                    left through the proxy» and «that one did not»);
* ``SocksProxy``  - the same for SOCKS5 (RFC 1928 / 1929), recording the destination NAME it received (socks5h) or the address (socks5);
* ``make_cert``   - a throw-away self-signed certificate (openssl CLI) so a CONNECT / SOCKS tunnel carries real TLS.
"""
from __future__ import annotations

import json
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
from base64 import b64decode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOSTS = ("api.telegram.org", "graph.facebook.com", "api.search.brave.com", "graph.instagram.com", "news.google.com",
         "ipinfo.test", "web.whatsapp.com", "www.google.com", "www.facebook.com", "www.bing.com", "duckduckgo.com",
         "api.openai.com", "api.elevenlabs.io", "nominatim.openstreetmap.org", "overpass-api.de", "www.instagram.com")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def closed_port() -> int:
    """A port nothing listens on (bound and released a moment ago)."""
    return free_port()


def make_cert(directory: str, names=HOSTS) -> tuple[str, str] | None:
    """(cert.pem, key.pem) for the given DNS names, or None when the openssl CLI is missing."""
    if not shutil.which("openssl"):
        return None
    cert, key = f"{directory}/cert.pem", f"{directory}/key.pem"
    san = ",".join(f"DNS:{n}" for n in names)
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2",
             "-subj", "/CN=egress-test", "-addext", f"subjectAltName={san}"],
            check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None
    return cert, key


# ------------------------------------------------------------------------------------------------ the foreign service

class Target:
    """What the fake proxies connect to. ``self.requests`` = [(method, path, host_header, body)]."""

    def __init__(self, cert: tuple[str, str] | None = None):
        self.requests: list[tuple[str, str, str, bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, self.headers.get("Host", ""), body))
                path = self.path.split("?")[0]
                if path.endswith("/getMe"):
                    data = {"ok": True, "result": {"id": 1, "username": "testbot", "first_name": "Test"}}
                elif path.endswith("/sendMessage"):
                    data = {"ok": True, "result": {"message_id": 7}}
                elif path.endswith("/json") or path == "/":
                    data = {"ip": "203.0.113.7", "country": "Germany", "country_code": "DE", "city": "Berlin", "org": "AS64500 Test Net",
                            "path": path, "host": self.headers.get("Host", "")}
                elif path.endswith("/messages"):
                    data = {"messages": [{"id": "wamid.TEST1"}]}
                elif "/v20.0/" in path:
                    data = {"display_phone_number": "+98 912 000 0000", "verified_name": "Test"}
                elif path.endswith("/missing"):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                else:
                    data = {"ok": True, "path": path, "host": self.headers.get("Host", "")}
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_HEAD = _answer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.tls = cert is not None
        if cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert[0], cert[1])
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path="/") -> str:
        return f"{'https' if self.tls else 'http'}://127.0.0.1:{self.port}{path}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


# ------------------------------------------------------------------------------------------------ shared helpers

def _pipe(a: socket.socket, b: socket.socket, idle: float = 20.0) -> None:
    pair = (a, b)
    try:
        while True:
            ready, _, _ = select.select(pair, [], [], idle)
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Base:
    def __init__(self, upstream_port: int | None, handler_cls):
        self.upstream_port = upstream_port
        self.events: list[tuple] = []
        self.server = _Server(("127.0.0.1", 0), handler_cls)
        self.server.owner = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def upstream(self) -> socket.socket:
        return socket.create_connection(("127.0.0.1", self.upstream_port), timeout=5)


# ------------------------------------------------------------------------------------------------ HTTP proxy

class _HttpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        owner: HttpProxy = self.server.owner
        try:
            line = self.rfile.readline(65536).decode("latin-1").strip()
            if not line:
                return
            method, target, _version = line.split(" ", 2)
            headers = {}
            while True:
                h = self.rfile.readline(65536).decode("latin-1")
                if h in ("\r\n", "\n", ""):
                    break
                k, _, v = h.partition(":")
                headers[k.strip().lower()] = v.strip()
            if owner.credentials and not owner.login_ok(headers.get("proxy-authorization", "")):
                owner.events.append(("denied", method, target))
                self.wfile.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="t"\r\n'
                                 b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                return
            if owner.upstream_port is None or owner.reject:
                owner.events.append(("refused", method, target))
                self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            try:
                up = owner.upstream()
            except OSError:
                owner.events.append(("upstream-down", method, target))
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            with up:
                if method == "CONNECT":
                    owner.events.append(("connect", target))
                    self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    self.wfile.flush()
                    _pipe(self.connection, up)
                    return
                # absolute-URI request: forward it as an ordinary one to the target
                owner.events.append(("forward", method, target))
                length = int(headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                path = target
                if "://" in target:
                    path = "/" + target.split("://", 1)[1].split("/", 1)[1] if "/" in target.split("://", 1)[1] else "/"
                head = f"{method} {path} HTTP/1.0\r\n" + "".join(
                    f"{k}: {v}\r\n" for k, v in headers.items() if not k.startswith("proxy-") and k != "connection")
                up.sendall(head.encode("latin-1") + b"Connection: close\r\n\r\n" + body)
                while True:
                    chunk = up.recv(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (OSError, ValueError):
            return


class HttpProxy(_Base):
    def __init__(self, upstream_port: int | None, credentials: tuple[str, str] | None = None, reject: bool = False):
        self.credentials, self.reject = credentials, reject
        super().__init__(upstream_port, _HttpHandler)

    def login_ok(self, header: str) -> bool:
        if not header.lower().startswith("basic "):
            return False
        try:
            user, _, password = b64decode(header.split(" ", 1)[1]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return (user, password) == self.credentials

    @property
    def connects(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "connect"]

    @property
    def forwards(self) -> list[tuple[str, str]]:
        return [(e[1], e[2]) for e in self.events if e[0] == "forward"]


# ------------------------------------------------------------------------------------------------ SOCKS5 proxy

class _SocksHandler(socketserver.BaseRequestHandler):
    def _recv(self, n):
        data = b""
        while len(data) < n:
            chunk = self.request.recv(n - len(data))
            if not chunk:
                raise OSError("closed")
            data += chunk
        return data

    def handle(self):
        owner: SocksProxy = self.server.owner
        try:
            first = self._recv(2)
            if first[0] != 5:                       # not SOCKS5 (e.g. an HTTP request sent to this port): hang up
                owner.events.append(("not-socks", first))
                return
            methods = self._recv(first[1])
            if owner.credentials:
                if 2 not in methods:
                    self.request.sendall(b"\x05\xff")
                    return
                self.request.sendall(b"\x05\x02")
                _, ulen = self._recv(2)
                user = self._recv(ulen)
                plen = self._recv(1)[0]
                password = self._recv(plen)
                if (user.decode(), password.decode()) != owner.credentials:
                    owner.events.append(("denied",))
                    self.request.sendall(b"\x01\x01")
                    return
                self.request.sendall(b"\x01\x00")
            else:
                self.request.sendall(b"\x05\x00")
            _ver, cmd, _rsv, atyp = self._recv(4)
            if atyp == 1:
                host = socket.inet_ntoa(self._recv(4))
            elif atyp == 3:
                host = self._recv(self._recv(1)[0]).decode()
            else:
                host = socket.inet_ntop(socket.AF_INET6, self._recv(16))
            port = int.from_bytes(self._recv(2), "big")
            owner.events.append(("connect", host, port, atyp))
            if owner.fail_reply:
                self.request.sendall(bytes([5, owner.fail_reply, 0, 1]) + b"\x00" * 6)
                return
            try:
                up = owner.upstream()
            except OSError:
                self.request.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)
                return
            with up:
                self.request.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
                _pipe(self.request, up)
        except OSError:
            return


class SocksProxy(_Base):
    def __init__(self, upstream_port: int | None, credentials: tuple[str, str] | None = None, fail_reply: int = 0):
        self.credentials, self.fail_reply = credentials, fail_reply
        super().__init__(upstream_port, _SocksHandler)

    @property
    def connects(self) -> list[tuple[str, int]]:
        return [(e[1], e[2]) for e in self.events if e[0] == "connect"]


class SilentServer:
    """Accepts connections and never answers (a proxy that hangs)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.held = []
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.held.append(conn)

    def stop(self):
        self.sock.close()
        for c in self.held:
            c.close()


def tmpdir() -> str:
    return tempfile.mkdtemp(prefix="nm-egress-test-")
