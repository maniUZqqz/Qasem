"""nm_fetch.py - the downloader every big download goes through: resume, growing waits, 30-minute patience, size + sha256.
A local server plays the flaky site (cuts the connection, answers 503, ignores Range, serves wrong bytes); nothing real is used.

    python tests\\test_nm_fetch.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)
import nm_fetch  # noqa: E402

BLOB = os.urandom(700 * 1024)
SHA = hashlib.sha256(BLOB).hexdigest()


class S:
    """What the fake site does (reset by every test)."""
    body = BLOB
    cut_after = None          # send only this many bytes of a response, then close (a reset in the middle)
    cuts_left = 0             # how many responses to cut
    fail_status = None        # answer this HTTP status ...
    fails_left = 0            # ... for this many requests
    ignore_range = False
    corrupt_first = False     # the first complete body has a flipped byte
    served = 0
    log = []


def reset():
    S.body, S.cut_after, S.cuts_left, S.fail_status, S.fails_left = BLOB, None, 0, None, 0
    S.ignore_range, S.corrupt_first, S.served, S.log = False, False, 0, []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        S.log.append((self.path, self.headers.get("Range"), self.headers.get("Authorization")))
        if self.path.startswith("/api/v1/compute/downloads/"):
            return self._json({"name": "x.zip", "size": len(BLOB), "sha256": SHA})
        if S.fails_left > 0:
            S.fails_left -= 1
            return self._json({"detail": "down"}, S.fail_status or 503)
        if "gone" in self.path:
            return self._json({"detail": "no"}, 404)
        body = S.body
        start, code = 0, 200
        rng = self.headers.get("Range")
        if rng and not S.ignore_range:
            a, _, b = rng.replace("bytes=", "").partition("-")
            start = int(a)
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % len(body))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = int(b) if b else len(body) - 1
            if rng == "bytes=0-0":
                chunk, code = body[0:1], 206
                self.send_response(206)
                self.send_header("Content-Range", "bytes 0-0/%d" % len(body))
                self.send_header("Content-Length", "1")
                self.end_headers()
                self.wfile.write(chunk)
                return
            code = 206
            chunk = body[start:end + 1]
        else:
            chunk = body
        if S.corrupt_first and S.served == 0 and code == 200:
            chunk = bytes([chunk[0] ^ 0xFF]) + chunk[1:]
        S.served += 1
        self.send_response(code)
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, start + len(chunk) - 1, len(body)))
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        if S.cuts_left > 0 and S.cut_after is not None and len(chunk) > S.cut_after:
            S.cuts_left -= 1
            self.wfile.write(chunk[:S.cut_after])
            self.wfile.flush()
            self.close_connection = True
            self.connection.close()
            return
        self.wfile.write(chunk)

    def _json(self, obj, code=200):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Clock:
    """Fake time: sleeping advances it (so a 30-minute patience is tested in no time)."""

    def __init__(self):
        self.t = 1000.0
        self.waits = []

    def sleep(self, s):
        self.waits.append(s)
        self.t += s

    def now(self):
        return self.t


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        reset()
        self.tmp = tempfile.mkdtemp(prefix="nm-fetch-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dest = os.path.join(self.tmp, "sub", "file.zip")
        self.clock = Clock()
        self.lines = []

    def go(self, url="/file.zip", **kw):
        kw.setdefault("sleep", self.clock.sleep)
        kw.setdefault("clock", self.clock.now)
        return nm_fetch.fetch(self.base + url, self.dest, out=self.lines.append, **kw)

    def content(self):
        with open(self.dest, "rb") as fh:
            return fh.read()

    def test_plain_download_is_verified_and_a_second_run_does_nothing(self):
        self.assertEqual(self.go(size=len(BLOB), sha256=SHA), "downloaded")
        self.assertEqual(self.content(), BLOB)
        self.assertFalse(os.path.exists(self.dest + ".part"))
        n = len(S.log)
        self.assertEqual(self.go(size=len(BLOB), sha256=SHA), "skipped")
        self.assertEqual(len(S.log), n, "a complete, verified file is not fetched again")

    def test_resumes_after_every_cut_with_range(self):
        S.cut_after, S.cuts_left = 100 * 1024, 4
        self.assertEqual(self.go(size=len(BLOB), sha256=SHA), "downloaded")
        self.assertEqual(self.content(), BLOB)
        ranges = [r for _p, r, _a in S.log if r]
        self.assertEqual(ranges[:4], ["bytes=%d-" % (i * 100 * 1024) for i in range(1, 5)],
                         "every new connection continues exactly where the last one stopped")
        self.assertTrue(any("connection problem" in ln for ln in self.lines))

    def test_survives_the_site_being_down_for_a_while_with_growing_waits(self):
        S.fail_status, S.fails_left = 503, 6
        self.assertEqual(self.go(size=len(BLOB), sha256=SHA), "downloaded")
        self.assertEqual(self.content(), BLOB)
        self.assertEqual(self.clock.waits, [3, 6, 12, 24, 48, 60])
        self.assertGreaterEqual(len(self.clock.waits), 6)

    def test_gives_up_only_after_the_stall_budget_and_keeps_what_arrived(self):
        # 50 KB are already there, then the site is gone for good
        S.fail_status, S.fails_left = 503, 10 ** 6
        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        with open(self.dest + ".part", "wb") as fh:
            fh.write(BLOB[:50 * 1024])
        with self.assertRaises(nm_fetch.FetchError) as cm:
            self.go(size=len(BLOB), sha256=SHA, stall=1800)
        self.assertIn("no progress for 30 minutes", str(cm.exception))
        self.assertGreaterEqual(sum(self.clock.waits), 1800 - 60)
        self.assertLessEqual(sum(self.clock.waits), 1800 + 1)
        self.assertEqual(os.path.getsize(self.dest + ".part"), 50 * 1024, "what arrived is kept for the next run")
        self.assertFalse(os.path.exists(self.dest))

    def test_progress_restarts_the_patience_clock(self):
        """Twenty resets in a row, each after some bytes: the total waiting is far above `stall`, yet it finishes."""
        blob = os.urandom(40 * 1024)
        S.body, S.cut_after, S.cuts_left = blob, 1024, 25
        self.assertEqual(self.go(size=len(blob), stall=120), "downloaded")
        self.assertEqual(self.content(), blob)

    def test_404_is_final_and_not_retried(self):
        with self.assertRaises(nm_fetch.FetchError) as cm:
            self.go("/gone")
        self.assertIn("HTTP 404", str(cm.exception))
        self.assertEqual(self.clock.waits, [])

    def test_a_site_that_ignores_range_starts_again(self):
        S.cut_after, S.cuts_left, S.ignore_range = 100 * 1024, 1, True
        self.assertEqual(self.go(size=len(BLOB), sha256=SHA), "downloaded")
        self.assertEqual(self.content(), BLOB)

    def test_wrong_checksum_is_fetched_again_and_a_bad_server_is_reported(self):
        S.corrupt_first = True
        self.assertEqual(self.go(size=len(BLOB), sha256=SHA), "downloaded")
        self.assertEqual(self.content(), BLOB)
        self.assertTrue(any("checksum does not match" in ln for ln in self.lines))
        self.assertTrue([n for n in os.listdir(os.path.dirname(self.dest)) if ".bad-" in n], "the bad copy is kept, not deleted")
        os.remove(self.dest)
        S.body = BLOB[:-1] + bytes([BLOB[-1] ^ 1])               # the site's file is not what the checksum says
        with self.assertRaises(nm_fetch.FetchError) as cm:
            self.go(size=len(BLOB), sha256=SHA)
        self.assertIn("checksum is wrong again", str(cm.exception))
        self.assertFalse(os.path.exists(self.dest))

    def test_a_different_file_than_expected_is_refused(self):
        with self.assertRaises(nm_fetch.FetchError) as cm:
            self.go(size=len(BLOB) + 5)
        self.assertIn("different file", str(cm.exception))

    def test_unfinished_copy_written_straight_into_the_file_is_continued(self):
        """curl -C - (the old worker-3d.bat) wrote into the final name: 'file.zip' that is only half there."""
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest, "wb") as fh:
            fh.write(BLOB[:300000])
        self.assertEqual(self.go(sha256=SHA), "downloaded")                 # size unknown: asked from the site
        self.assertEqual(self.content(), BLOB)
        self.assertIn("bytes=300000-", [r for _p, r, _a in S.log if r])
        self.assertTrue(any("continuing the unfinished copy" in ln for ln in self.lines))

    def test_complete_file_without_known_size_is_not_downloaded_again(self):
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest, "wb") as fh:
            fh.write(BLOB)
        self.assertEqual(self.go(), "skipped")
        self.assertEqual([r for _p, r, _a in S.log if r], ["bytes=0-0"], "only the 1-byte size probe")

    def test_a_part_that_is_already_everything_just_finishes(self):
        os.makedirs(os.path.dirname(self.dest))
        with open(self.dest + ".part", "wb") as fh:
            fh.write(BLOB)
        self.assertEqual(self.go(sha256=SHA), "downloaded")
        self.assertEqual(self.content(), BLOB)

    def test_command_line_site_file_uses_the_sites_size_and_checksum(self):
        out = []
        env = {"NM_SITE": self.base, "NM_TOKEN": "TOK"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.addCleanup(lambda: [os.environ.pop(k) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()) as buf:
            rc = nm_fetch.main(["site-file", "file.zip", self.dest, "--stall", "30"])
        out = buf.getvalue()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.content(), BLOB)
        self.assertIn("downloaded and verified", out)
        self.assertEqual([a for p, _r, a in S.log if p.startswith("/api/v1/compute/downloads/")], ["Node TOK"])
        self.assertEqual(nm_fetch.main(["site-file", "gone", os.path.join(self.tmp, "g.zip"), "--stall", "5"]), 1)


if __name__ == "__main__":
    unittest.main()
