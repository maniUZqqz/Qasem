"""Fake platform servers for tests - real HTTP on localhost, no mocks.

The adapters make real `requests` calls, so the honest test is a real server
that speaks each platform's wire format. `FakePlatform` records every request
and answers from a table of canned responses, which lets a test assert both
what the adapter *sent* (path, body, auth) and what it *did* with the answer.

Used only by tests (and by the connect-page "try it" check in development).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakePlatform:
    """`with FakePlatform(responses) as fake: ... fake.url ... fake.requests`.

    `responses` maps a path *suffix* (e.g. "sendMessage") to either a dict
    (200 JSON), a `(status, dict)` tuple, or a callable `(request) -> same`.
    A `bytes` value is sent raw as `image/png`. The first suffix that matches wins;
    unmatched paths answer 404 `{}`.
    """

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                return

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                record = {
                    "method": self.command, "path": self.path, "body": body,
                    "headers": {k: v for k, v in self.headers.items()},
                }
                outer.requests.append(record)
                status, payload = 404, {}
                for suffix, answer in outer.responses.items():
                    if self.path.split("?")[0].endswith(suffix):
                        value = answer(record) if callable(answer) else answer
                        status, payload = value if isinstance(value, tuple) else (200, value)
                        break
                if isinstance(payload, bytes):
                    data, ctype = payload, "image/png"
                else:
                    data, ctype = json.dumps(payload, ensure_ascii=False).encode(), "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]
