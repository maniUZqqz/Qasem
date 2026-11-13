"""abagram_jobs.py (the Instagram reader of the node), without Instagram, without a browser and without internet:
a fake Abagram HTTP server stands in for the service, fake `run`/`popen` stand in for pip and the process, and one test
starts the REAL vendored Abagram (node mode) on synthetic saved pages when this Python has its requirements.

    python tests/test_abagram_jobs.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))   # never the real data folder
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")

import abagram_jobs as AJ  # noqa: E402

TOKEN = "t" * 48


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def post_row(code, taken_at=1_700_000_000, kind="reel", likes=500, comments=20, views=9000, caption="تمرین #بدنسازی", music=None):
    return {"code": code, "id": "1" + code, "kind": kind, "taken_at": taken_at, "caption": caption, "hashtags": ["بدنسازی"],
            "likes": likes, "comments": comments, "views": views, "likes_hidden": False, "comments_disabled": False, "pinned": False,
            "music": music, "items_count": 1, "width": 1080, "height": 1920, "paid_partnership": False}


def page_doc(name, n=3, private=False):
    return {"format": "nm-ig-page", "version": 1, "username": name,
            "profile": {"username": name, "user_id": "77", "full_name": "نمونه", "biography": "ساختگی", "followers": 1000, "following": 10,
                        "posts": 50, "is_private": private, "is_verified": False, "is_business": True, "category": "Gym",
                        "fetched_at": "2026-11-10T08:00:00+00:00"},
            "posts": [post_row("%s%d" % (name[:3].upper(), i), taken_at=1_700_000_000 - i * 3600) for i in range(n)],
            "fetched_at": "2026-11-10T08:00:00+00:00"}


class FakeAbagram:
    """Speaks the part of Abagram's API the node uses. `script[name]` = 'ok' | an outcome kind ('challenge', 'not_found', ...)."""

    def __init__(self, token=TOKEN, signed_in=True, script=None):
        self.token, self.signed_in = token, signed_in
        self.script = script or {}
        self.calls = []
        self.run, self.state, self.pending, self.current, self.outcome = 0, "idle", 0, None, None
        self.busy_posts = 0
        self.never_finish = False
        self.proxy = ""
        self.cooldown = None
        self.used = {"hour": 0, "day": 0}
        self.limits = {"pages_hour": 30, "pages_day": 150}
        self.docs = {}
        self.reach = {"ok": True, "status": 200, "ms": 5, "via": "direct"}
        self.restart_asked = 0
        self.server = None

    def status(self):
        if self.state == "running":
            if self.never_finish or self.pending > 0:
                self.pending -= 1
                return self._status(busy=True)
            kind = self.script.get(self.current, "ok")
            self.outcome = {"kind": kind}
            self.state = "success" if kind == "ok" else "failed"
        return self._status()

    def _status(self, busy=False):
        return {"run": self.run, "state": self.state, "busy": busy, "outcome": self.outcome, "queue": {"signed_in": self.signed_in},
                "prefs": {"proxy": self.proxy, "show_browser": False}, "session": {"username": "demo_account"} if self.signed_in else None,
                "budget": {"limits": self.limits, "used": {"page": dict(self.used)}, "cooldown": self.cooldown}}

    def start(self, port=0):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                if self.headers.get("X-Igs-Token") != fake.token:
                    self._send(401, {"detail": "login"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                fake.calls.append(("GET", self.path, None))
                path = self.path.split("?")[0]
                if path == "/api/status":
                    return self._send(200, fake.status())
                if path.startswith("/api/trend/"):
                    name = path.rsplit("/", 1)[1]
                    doc = fake.docs.get(name)
                    return self._send(200, doc) if doc else self._send(404, {"detail": "none"})
                self._send(404, {})

            def do_POST(self):
                if not self._auth():
                    return
                if self.headers.get("X-Igs") != "1":
                    return self._send(403, {"detail": "missing header"})
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
                fake.calls.append(("POST", self.path, body))
                if self.path == "/api/profile":
                    if fake.busy_posts > 0:
                        fake.busy_posts -= 1
                        return self._send(409, {"detail": "busy"})
                    fake.run += 1
                    fake.state, fake.pending, fake.current, fake.outcome = "running", 1, body["username"], None
                    return self._send(200, {"ok": True, "run": fake.run})
                if self.path == "/api/cancel":
                    fake.state = "cancelled"
                    return self._send(200, {"ok": True})
                if self.path == "/api/prefs":
                    fake.proxy = body.get("values", {}).get("proxy", fake.proxy)
                    return self._send(200, {"proxy": fake.proxy})
                if self.path == "/api/health/test":
                    return self._send(200, fake.reach)
                if self.path == "/api/admin/restart":
                    fake.restart_asked += 1
                    return self._send(200, {"ok": True})
                self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def client(self):
        return AJ.Client(self.port, self.token, timeout=5)

    def posted(self, path):
        return [c for c in self.calls if c[0] == "POST" and c[1] == path]


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def run_scrape(fake, names, **kw):
    clock = kw.pop("clock", None) or Clock()
    kw.setdefault("pace", (20, 60))
    kw.setdefault("rng", __import__("random").Random(7))
    batch = AJ.scrape(fake.client(), names, sleep=clock.sleep, clock=clock.time, **kw)
    return batch, clock


class ScrapeTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeAbagram().start()
        for n in ("alpha_fit", "beta_gym", "gamma_coach", "delta_run"):
            self.fake.docs[n] = page_doc(n)

    def tearDown(self):
        self.fake.stop()

    def test_happy_path_reads_pages_and_normalizes(self):
        batch, clock = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach"])
        self.assertEqual(batch["format"], "nm-ig-batch")
        self.assertIsNone(batch["stopped"])
        self.assertEqual([a["username"] for a in batch["accounts"]], ["alpha_fit", "beta_gym", "gamma_coach"])
        self.assertEqual(len(batch["posts"]), 9)
        one = batch["posts"][0]
        self.assertEqual(one["account"], "alpha_fit")
        for gone in ("mentions", "thumb", "items", "tagged", "location"):
            self.assertNotIn(gone, one)
        self.assertEqual(batch["accounts"][0]["followers"], 1000)
        self.assertEqual({v["status"] for v in batch["per_account"].values()}, {"ok"})
        self.assertEqual(batch["not_read"], [])

    def test_a_fresh_read_is_asked_for_and_only_the_profile_page_is_opened(self):
        run_scrape(self.fake, ["alpha_fit", "beta_gym"], fresh=True)
        posts = self.fake.posted("/api/profile")
        self.assertEqual([p[2] for p in posts], [{"username": "alpha_fit", "fresh": True}, {"username": "beta_gym", "fresh": True}])
        # nothing else of Instagram is asked: no followers, no details, no downloads
        asked = {c[1].split("?")[0] for c in self.fake.calls if c[0] == "POST"}
        self.assertEqual(asked, {"/api/profile"})

    def test_pauses_are_randomized_and_within_the_pace(self):
        batch, clock = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach", "delta_run"], pace=(30, 90))
        pauses = []                              # the sleeps are cut in steps of at most 15 s; the 2 s polls are separate
        cur = 0.0
        for s in clock.sleeps:
            if s == 2:
                if cur:
                    pauses.append(cur)
                    cur = 0.0
                continue
            cur += s
        if cur:
            pauses.append(cur)
        self.assertEqual(len(pauses), 3, pauses)
        for p in pauses:
            self.assertGreaterEqual(p, 30 - 0.01)
            self.assertLessEqual(p, 90 + 0.01)
        self.assertGreater(len({round(p, 3) for p in pauses}), 1, "the pauses must not all be equal")

    def test_pace_never_goes_below_fifteen_seconds(self):
        batch, clock = run_scrape(self.fake, ["alpha_fit", "beta_gym"], pace=(1, 2))
        self.assertGreaterEqual(sum(s for s in clock.sleeps if s != 2), 15 - 0.01)

    def test_stops_at_a_challenge_and_asks_nothing_more(self):
        self.fake.script["beta_gym"] = "challenge"
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach"])
        self.assertEqual(batch["stopped"]["code"], "challenge")
        self.assertEqual([a["username"] for a in batch["accounts"]], ["alpha_fit"])
        self.assertEqual(batch["not_read"], ["gamma_coach"])
        self.assertEqual([p[2]["username"] for p in self.fake.posted("/api/profile")], ["alpha_fit", "beta_gym"])

    def test_every_limit_kind_stops_the_run(self):
        for kind, code in (("rate_limit", "limit"), ("cooldown", "limit"), ("budget", "budget"), ("session_invalid", "not_signed_in"),
                           ("automated", "challenge")):
            with self.subTest(kind=kind):
                fake = FakeAbagram(script={"alpha_fit": kind}).start()
                fake.docs.update(self.fake.docs)
                try:
                    batch, _ = run_scrape(fake, ["alpha_fit", "beta_gym"])
                    self.assertEqual(batch["stopped"]["code"], code)
                    self.assertEqual(len(fake.posted("/api/profile")), 1)
                    self.assertEqual(batch["posts"], [])
                finally:
                    fake.stop()

    def test_not_found_and_private_are_skipped_not_stopped(self):
        self.fake.script["alpha_fit"] = "not_found"
        self.fake.docs["beta_gym"] = page_doc("beta_gym", private=True)
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach"])
        self.assertIsNone(batch["stopped"])
        self.assertEqual(batch["per_account"]["alpha_fit"]["status"], "not_found")
        self.assertEqual(batch["per_account"]["beta_gym"]["status"], "private")
        self.assertEqual(batch["per_account"]["gamma_coach"]["status"], "ok")
        self.assertEqual([a["username"] for a in batch["accounts"]], ["gamma_coach"])

    def test_one_line_failure_goes_on_two_in_a_row_stop(self):
        self.fake.script.update(alpha_fit="network", beta_gym="ok")
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach"])
        self.assertIsNone(batch["stopped"])
        self.assertEqual(batch["per_account"]["alpha_fit"]["status"], "failed")
        self.fake.script.update(alpha_fit="network", beta_gym="timeout", gamma_coach="ok")
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach"])
        self.assertEqual(batch["stopped"]["code"], "unreachable")
        self.assertEqual(batch["not_read"], ["gamma_coach"])

    def test_not_signed_in_asks_nothing(self):
        self.fake.signed_in = False
        batch, _ = run_scrape(self.fake, ["alpha_fit"])
        self.assertEqual(batch["stopped"]["code"], "not_signed_in")
        self.assertEqual(self.fake.posted("/api/profile"), [])

    def test_cooldown_and_full_budget_ask_nothing(self):
        clock = Clock()
        self.fake.cooldown = {"until": clock.now + 600, "reason": "wait"}
        batch, _ = run_scrape(self.fake, ["alpha_fit"], clock=clock)
        self.assertEqual(batch["stopped"]["code"], "limit")
        self.fake.cooldown = None
        self.fake.used = {"hour": 28, "day": 40}              # 30 - 28 - margin(6) < 0
        batch, _ = run_scrape(self.fake, ["alpha_fit"], clock=clock)
        self.assertEqual(batch["stopped"]["code"], "budget")
        self.assertEqual(self.fake.posted("/api/profile"), [])

    def test_the_page_budget_caps_the_number_of_pages(self):
        self.fake.used = {"hour": 14, "day": 20}              # room = (30-14-6)//2 = 5
        self.assertEqual(AJ.page_room(AJ.summarize_status(self.fake.status())), 5)
        self.fake.used = {"hour": 20, "day": 20}              # room = (30-20-6)//2 = 2
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach", "delta_run"], max_accounts=10)
        self.assertEqual(len(self.fake.posted("/api/profile")), 2)
        self.assertEqual(batch["not_read"], ["gamma_coach", "delta_run"])

    def test_max_accounts_is_respected_and_capped(self):
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym", "gamma_coach", "delta_run"], max_accounts=2)
        self.assertEqual(len(batch["accounts"]), 2)
        self.assertEqual(batch["not_read"], ["gamma_coach", "delta_run"])

    def test_busy_service_waits_then_reads(self):
        self.fake.busy_posts = 2
        batch, _ = run_scrape(self.fake, ["alpha_fit"])
        self.assertEqual(len(batch["accounts"]), 1)

    def test_busy_service_that_stays_busy_stops(self):
        self.fake.busy_posts = 10 ** 6
        batch, _ = run_scrape(self.fake, ["alpha_fit", "beta_gym"])
        self.assertEqual(batch["stopped"]["code"], "busy")

    def test_a_read_that_never_ends_is_cancelled(self):
        self.fake.never_finish = True
        batch, _ = run_scrape(self.fake, ["alpha_fit"], timeout_s=30)
        self.assertEqual(len(self.fake.posted("/api/cancel")), 1)
        self.assertEqual(batch["per_account"]["alpha_fit"]["status"], "failed")

    def test_service_down_is_a_stop_not_a_crash(self):
        self.fake.stop()
        batch = AJ.scrape(AJ.Client(self.fake.port, TOKEN, timeout=1), ["alpha_fit"], sleep=lambda s: None)
        self.assertEqual(batch["stopped"]["code"], "service_down")

    def test_wrong_key_is_service_down_not_data(self):
        batch = AJ.scrape(AJ.Client(self.fake.port, "x" * 48, timeout=2), ["alpha_fit"], sleep=lambda s: None)
        self.assertEqual(batch["stopped"]["code"], "service_down")

    def test_bad_names_are_dropped(self):
        self.assertEqual(AJ.clean_accounts(["@Alpha_Fit", "alpha_fit", "bad name", "../x", "", None, "a" * 40, "ok.page"]), ["alpha_fit", "ok.page"])
        batch, _ = run_scrape(self.fake, ["bad name", "../x"])
        self.assertEqual(batch["stopped"]["code"], "no_accounts")

    def test_music_travels_with_the_post(self):
        doc = page_doc("alpha_fit", n=1)
        doc["posts"][0]["music"] = {"kind": "music", "title": "آهنگ", "artist": "هنرمند"}
        self.fake.docs["alpha_fit"] = doc
        batch, _ = run_scrape(self.fake, ["alpha_fit"])
        self.assertEqual(batch["posts"][0]["music"]["title"], "آهنگ")


class FakeJob:
    def __init__(self, payload, out_dir):
        self.payload, self.dir, self.progress_log, self.cancel_after = payload, out_dir, [], None

    def out(self, name):
        os.makedirs(self.dir, exist_ok=True)
        return os.path.join(self.dir, name)

    def progress(self, fraction, message="", meta=None):
        self.progress_log.append((fraction, message))
        if self.cancel_after is not None and len(self.progress_log) > self.cancel_after:
            raise Cancelled()


class Cancelled(Exception):
    pass


class FakeAgent:
    def __init__(self, root):
        self.HERE = os.path.join(root, "code")
        self.DATA = os.path.join(root, "data")
        self.CONFIG = {"name": "TEST-NODE", "token": "tok", "site": "http://site.invalid"}
        self.lines = []
        self.HANDLERS = {}
        self.BACKGROUND_KINDS = ("ollama.pull",)
        self.SITE_LOG = type("L", (), {"add": lambda s, level, msg: self.lines.append((level, msg))})()
        for d in (self.HERE, self.DATA):
            os.makedirs(d, exist_ok=True)

    def log(self, msg, level="INFO"):
        self.lines.append((level, msg))

    def warn(self, msg):
        self.lines.append(("WARNING", msg))

    def site_base(self):
        return self.CONFIG["site"]


class FakeSvc:
    def __init__(self, fake=None, problem=None):
        self.fake, self._problem = fake, problem

    def client(self):
        return self.fake.client() if self.fake else None

    def problem(self):
        return self._problem

    def report(self):
        return {"state": "up" if self.fake else "installing", "ready": self.fake is not None}

    def test_reach(self):
        return {"ok": True}


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-abagram-test-")
        self.agent = FakeAgent(self.tmp)
        self.fake = FakeAbagram().start()
        for n in ("alpha_fit", "beta_gym"):
            self.fake.docs[n] = page_doc(n)

    def tearDown(self):
        self.fake.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_scrape_writes_the_batch_and_reports_meta(self):
        job = FakeJob({"accounts": ["alpha_fit", "beta_gym"], "max_accounts": 2, "pace_s": [15, 16], "store_id": 34, "run_id": 5, "seed": 1},
                      os.path.join(self.tmp, "out"))
        meta = AJ.run_scrape(job, self.agent, service=FakeSvc(self.fake), sleep=lambda s: None)
        self.assertEqual(meta["primary"], "ig_batch.json")
        self.assertEqual(meta["accounts_read"], 2)
        self.assertEqual(meta["posts"], 6)
        self.assertIsNone(meta["stopped"])
        batch = json.load(open(job.out("ig_batch.json"), encoding="utf-8"))
        self.assertEqual((batch["store_id"], batch["run_id"], batch["node"]), (34, 5, "TEST-NODE"))
        self.assertGreater(len(job.progress_log), 3)
        self.assertLessEqual(max(f for f, _ in job.progress_log), 1.0)

    def test_run_scrape_without_a_service_is_a_stop_not_a_failure(self):
        job = FakeJob({"accounts": ["alpha_fit"]}, os.path.join(self.tmp, "out"))
        meta = AJ.run_scrape(job, self.agent, service=FakeSvc(None, problem="installing"), sleep=lambda s: None)
        self.assertEqual(meta["stopped"]["code"], "installing")
        self.assertEqual(meta["posts"], 0)
        self.assertTrue(os.path.isfile(job.out("ig_batch.json")))

    def test_cancel_stops_the_browser_run_too(self):
        job = FakeJob({"accounts": ["alpha_fit", "beta_gym"], "pace_s": [15, 16]}, os.path.join(self.tmp, "out"))
        job.cancel_after = 4
        with self.assertRaises(Cancelled):
            AJ.run_scrape(job, self.agent, service=FakeSvc(self.fake), sleep=lambda s: None)
        self.assertEqual(len(self.fake.posted("/api/cancel")), 1)
        self.assertFalse(AJ.SCRAPE_LOCK.locked(), "the lock must be released after a cancel")

    def test_health_reports_and_reads_one_page_only_when_ready(self):
        job = FakeJob({"test_connection": True, "read": "alpha_fit"}, os.path.join(self.tmp, "out"))
        svc = FakeSvc(self.fake)
        svc.report = lambda: {"state": "up", "ready": True}
        meta = AJ.run_health(job, self.agent, service=svc, sleep=lambda s: None)
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["read"]["accounts_read"], 1)
        job2 = FakeJob({"read": "alpha_fit"}, os.path.join(self.tmp, "out2"))
        svc2 = FakeSvc(self.fake)
        svc2.report = lambda: {"state": "up", "ready": False, "problem": "not_signed_in"}
        meta2 = AJ.run_health(job2, self.agent, service=svc2, sleep=lambda s: None)
        self.assertEqual(meta2["read"]["skipped"], "not_signed_in")

    def test_register_adds_kinds_background_and_wraps_probe_once(self):
        class Caps:
            def probe(self):
                return {"agent": "x"}
        self.agent.Capabilities = Caps
        AJ.register(self.agent)
        AJ.register(self.agent)
        self.assertIn("ig.scrape", self.agent.HANDLERS)
        self.assertIn("ig.health", self.agent.HANDLERS)
        self.assertIn("ig.scrape", self.agent.BACKGROUND_KINDS)
        self.assertIn("ollama.pull", self.agent.BACKGROUND_KINDS)
        with mock.patch.object(AJ.Service, "ensure_thread", lambda s: None):
            caps = Caps().probe()
        self.assertTrue(caps["instagram"])
        self.assertIn("abagram", caps)
        self.assertEqual(caps["agent"], "x")
        self.assertEqual(self.agent.BACKGROUND_KINDS.count("ig.scrape"), 1)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-abagram-install-")
        self.agent = FakeAgent(self.tmp)
        self.layout = AJ.Layout(self.agent.HERE, self.agent.DATA)
        os.makedirs(self.layout.code)
        open(os.path.join(self.layout.code, "app.py"), "w").write("# app\n")
        open(self.layout.lock, "w").write("fastapi==0.141.1\n")
        self.cmds = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def runner(self, pip_codes=(0,), import_ok=True):
        pip_codes = list(pip_codes)

        def run(cmd, **kw):
            self.cmds.append(cmd)
            if cmd[1:3] == ["-m", "venv"]:
                os.makedirs(os.path.dirname(self.layout.py), exist_ok=True)
                open(self.layout.py, "w").write("")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "pip" in cmd:
                code = pip_codes.pop(0) if pip_codes else 0
                return subprocess.CompletedProcess(cmd, code, "out", "boom" if code else "")
            if cmd[1] == "-c":
                return subprocess.CompletedProcess(cmd, 0 if import_ok else 1, "", "")
            raise AssertionError(cmd)
        return run

    def pips(self):
        return [c for c in self.cmds if "pip" in c]

    def test_first_install_makes_the_venv_then_installs_and_writes_the_marker(self):
        with mock.patch.object(AJ, "pack_fits", lambda: False):
            out = AJ.install(self.layout, self.agent, run=self.runner())
        self.assertEqual(out, "installed")
        self.assertTrue(os.path.isfile(self.layout.marker))
        self.assertEqual(len(self.pips()), 1)
        self.assertIn("--index-url", self.pips()[0])
        self.assertIn(AJ.INDEX_URLS[0], self.pips()[0])

    def test_second_call_does_nothing(self):
        with mock.patch.object(AJ, "pack_fits", lambda: False):
            AJ.install(self.layout, self.agent, run=self.runner())
            self.cmds.clear()
            out = AJ.install(self.layout, self.agent, run=self.runner())
        self.assertEqual(out, "ready")
        self.assertEqual(self.pips(), [])

    def test_a_changed_lock_file_installs_again(self):
        with mock.patch.object(AJ, "pack_fits", lambda: False):
            AJ.install(self.layout, self.agent, run=self.runner())
            open(self.layout.lock, "w").write("fastapi==0.142.0\n")
            self.cmds.clear()
            out = AJ.install(self.layout, self.agent, run=self.runner())
        self.assertEqual(out, "installed")
        self.assertEqual(len(self.pips()), 1)

    def test_broken_imports_install_again(self):
        with mock.patch.object(AJ, "pack_fits", lambda: False):
            AJ.install(self.layout, self.agent, run=self.runner())
            self.cmds.clear()
            out = AJ.install(self.layout, self.agent, run=self.runner(import_ok=False))
        self.assertEqual(out, "installed")

    def test_a_failing_source_falls_through_to_the_next(self):
        with mock.patch.object(AJ, "pack_fits", lambda: False):
            out = AJ.install(self.layout, self.agent, run=self.runner(pip_codes=(1, 1, 0)))
        self.assertEqual(out, "installed")
        urls = [c[c.index("--index-url") + 1] for c in self.pips()]
        self.assertEqual(urls, list(AJ.INDEX_URLS))

    def test_the_official_index_goes_first_when_it_answers_and_last_when_it_is_blocked(self):
        class Resp:
            def close(self):
                pass
        self.assertEqual(AJ.index_order(urlopen=lambda req, timeout=None: Resp()), list(AJ.INDEX_URLS))

        def blocked(req, timeout=None):
            raise OSError("filtered")
        order = AJ.index_order(urlopen=blocked)
        self.assertEqual(order[-1], "https://pypi.org/simple")
        self.assertEqual(sorted(order), sorted(AJ.INDEX_URLS))
        self.assertEqual(AJ.INDEX_URLS[0], "https://pypi.org/simple")
        self.assertEqual(AJ.index_order(probe=False), list(AJ.INDEX_URLS), "a fake pip never meets the network")

    def test_every_source_failing_is_a_clear_error(self):
        with mock.patch.object(AJ, "pack_fits", lambda: False):
            with self.assertRaises(AJ.InstallError) as cm:
                AJ.install(self.layout, self.agent, run=self.runner(pip_codes=(1, 1, 1)))
        self.assertEqual(cm.exception.code, "pip_failed")
        self.assertFalse(os.path.isfile(self.layout.marker))

    def test_the_sites_wheel_pack_is_tried_first_and_pip_never_touches_the_internet_for_it(self):
        def fetch(agent, name, dest, say):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zipfile.ZipFile(dest, "w") as z:
                z.writestr("fastapi-0.141.1-py3-none-any.whl", b"x")
            return True
        with mock.patch.object(AJ, "pack_fits", lambda: True):
            out = AJ.install(self.layout, self.agent, run=self.runner(), fetch=fetch)
        self.assertEqual(out, "installed")
        first = self.pips()[0]
        self.assertIn("--no-index", first)
        self.assertIn(self.layout.wheelhouse, first)
        self.assertNotIn("--index-url", first)

    def test_a_missing_pack_on_the_site_falls_back_to_the_indexes(self):
        with mock.patch.object(AJ, "pack_fits", lambda: True):
            AJ.install(self.layout, self.agent, run=self.runner(), fetch=lambda *a: False)
        self.assertIn("--index-url", self.pips()[0])

    def test_a_pack_that_fails_in_pip_falls_back_to_the_indexes(self):
        def fetch(agent, name, dest, say):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zipfile.ZipFile(dest, "w") as z:
                z.writestr("a.whl", b"x")
            return True
        with mock.patch.object(AJ, "pack_fits", lambda: True):
            out = AJ.install(self.layout, self.agent, run=self.runner(pip_codes=(1, 0)), fetch=fetch)
        self.assertEqual(out, "installed")
        self.assertEqual(len(self.pips()), 2)
        self.assertIn("--index-url", self.pips()[1])

    def test_missing_vendored_code_is_reported(self):
        os.remove(os.path.join(self.layout.code, "app.py"))
        with self.assertRaises(AJ.InstallError) as cm:
            AJ.install(self.layout, self.agent, run=self.runner())
        self.assertEqual(cm.exception.code, "code_missing")

    def test_pip_environment_cannot_be_redirected_by_the_computer(self):
        env = AJ.pip_env(self.layout, {"PIP_INDEX_URL": "http://evil", "PIP_CONFIG_FILE": "x", "KEEP": "1"})
        self.assertNotIn("PIP_INDEX_URL", env)
        self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)
        self.assertEqual(env["KEEP"], "1")

    def test_zip_with_a_path_that_leaves_the_folder_is_refused(self):
        z = os.path.join(self.tmp, "bad.zip")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("../escape.txt", b"x")
        with self.assertRaises(AJ.InstallError):
            AJ.unpack_zip(z, os.path.join(self.tmp, "dest"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.txt")))


class BrowserAndProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-abagram-browser-")
        self.layout = AJ.Layout(os.path.join(self.tmp, "code"), os.path.join(self.tmp, "data"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_edge_is_found_first(self):
        env = {"ProgramFiles(x86)": r"C:\PF86", "NM_ABAGRAM_FORCE_BROWSER_SEARCH": "1"}
        edge = os.path.join(r"C:\PF86", "Microsoft", "Edge", "Application", "msedge.exe")
        found = AJ.find_browser(self.layout, env, exists=lambda p: p == edge)
        self.assertEqual(found["channel"], "msedge")

    def test_chrome_when_no_edge_and_the_pack_when_neither(self):
        env = {"ProgramFiles": r"C:\PF", "NM_ABAGRAM_FORCE_BROWSER_SEARCH": "1"}
        chrome = os.path.join(r"C:\PF", "Google", "Chrome", "Application", "chrome.exe")
        self.assertEqual(AJ.find_browser(self.layout, env, exists=lambda p: p == chrome)["channel"], "chrome")
        self.assertEqual(AJ.find_browser(self.layout, env, exists=lambda p: False), {})
        pack = os.path.join(self.layout.browser_dir, "chrome-win64")
        os.makedirs(pack)
        open(os.path.join(pack, "chrome.exe"), "w").write("")
        found = AJ.find_browser(self.layout, env, exists=lambda p: False)
        self.assertEqual(found["exe"], os.path.join(pack, "chrome.exe"))

    def test_the_pack_can_be_preferred(self):
        pack = os.path.join(self.layout.browser_dir, "chrome-win")
        os.makedirs(pack)
        open(os.path.join(pack, "chrome.exe"), "w").write("")
        env = {"NM_ABAGRAM_BROWSER": "chromium"}
        self.assertEqual(AJ.find_browser(self.layout, env)["name"], "chromium")

    def test_proxy_parsing_only_local_addresses(self):
        p = AJ.parse_proxy_server
        self.assertEqual(p("127.0.0.1:10809"), "http://127.0.0.1:10809")
        self.assertEqual(p("localhost:8080"), "http://127.0.0.1:8080")
        self.assertEqual(p("http=127.0.0.1:10809;https=127.0.0.1:10809;socks=127.0.0.1:10808"), "http://127.0.0.1:10809")
        self.assertEqual(p("203.0.113.5:8080"), "")                  # a remote proxy of the computer is never reused
        self.assertEqual(p("user:pw@127.0.0.1:1"), "")
        self.assertEqual(p(""), "")

    def test_system_proxy_hint_from_the_registry(self):
        class Key:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

        def fake_reg(enabled, server):
            return type("R", (), {"HKEY_CURRENT_USER": 1, "OpenKey": lambda self, h, p: Key(),
                                  "QueryValueEx": lambda self, k, n: (enabled if n == "ProxyEnable" else server, 1)})()
        self.assertEqual(AJ.system_proxy_hint(fake_reg(1, "127.0.0.1:10809")), "http://127.0.0.1:10809")
        self.assertEqual(AJ.system_proxy_hint(fake_reg(0, "127.0.0.1:10809")), "")

    def test_the_owners_own_choice_wins(self):
        self.assertEqual(AJ.wanted_proxy(self.layout, {"NM_ABAGRAM_PROXY": "socks5://127.0.0.1:1080"}), ("socks5://127.0.0.1:1080", "env"))
        os.makedirs(self.layout.root)
        open(self.layout.proxy_file, "w").write("http://127.0.0.1:7890\n")
        self.assertEqual(AJ.wanted_proxy(self.layout, {}), ("http://127.0.0.1:7890", "file"))

    def test_masking_never_shows_a_password(self):
        self.assertEqual(AJ.mask_proxy("http://user:secret@127.0.0.1:10809"), "http://127.0.0.1:10809")
        self.assertEqual(AJ.mask_proxy("nonsense"), "")

    def test_port_choice_keeps_the_remembered_port(self):
        self.assertEqual(AJ.choose_port(8800, is_free=lambda p: True), 8800)
        self.assertEqual(AJ.choose_port(8800, is_free=lambda p: p != 8800 and p >= 8795), 8795)
        self.assertEqual(AJ.choose_port(None, is_free=lambda p: True), AJ.PORT_RANGE[0])
        with self.assertRaises(AJ.InstallError):
            AJ.choose_port(None, is_free=lambda p: False)


class FakeProc:
    _next = 4000

    def __init__(self, fake=None, die=False):
        FakeProc._next += 1
        self.pid = FakeProc._next
        self.fake, self.code = fake, (1 if die else None)

    def poll(self):
        return self.code

    def terminate(self):
        self.code = 0

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-abagram-svc-")
        self.agent = FakeAgent(self.tmp)
        self.layout = AJ.Layout(self.agent.HERE, self.agent.DATA)
        os.makedirs(self.layout.code)
        open(os.path.join(self.layout.code, "app.py"), "w").write("# app\n")
        open(self.layout.lock, "w").write("x==1\n")
        self.fakes, self.envs = [], []
        self.t = Clock()

    def tearDown(self):
        for f in self.fakes:
            f.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def popen(self, signed_in=False):
        def popen(cmd, cwd=None, env=None, **kw):
            self.envs.append((cmd, cwd, env, kw))
            fake = FakeAbagram(token=env["IGS_API_TOKEN"], signed_in=signed_in).start(int(env["IGS_PORT"]))
            self.fakes.append(fake)
            self.last_fake = fake
            return FakeProc(fake)
        return popen

    def service(self, **kw):
        svc = AJ.Service(self.agent, layout=self.layout, say=lambda m: None, run=subprocess.run, popen=kw.get("popen") or self.popen(),
                         clock=self.t.time)
        svc._installed = lambda: True
        svc.browser = {}
        return svc

    def tick(self, svc):
        with mock.patch.object(AJ, "ensure_browser", lambda *a, **k: svc.browser), mock.patch.object(AJ, "choose_port", lambda p, **k: p or free_port()):
            svc.tick()

    def test_start_up_poll_and_report(self):
        svc = self.service()
        self.tick(svc)
        self.assertEqual(svc.state, "up")
        rep = svc.report()
        self.assertEqual(rep["problem"], "not_signed_in")
        self.assertFalse(rep["ready"])
        self.assertEqual(rep["url"], "http://127.0.0.1:%d/" % svc.port)
        self.assertEqual(rep["open_with"], "Open-Abagram.bat")
        self.assertNotIn(svc.token, json.dumps(rep), "the key must never be in the node report")
        cmd, cwd, env, kw = self.envs[0]
        self.assertEqual(cwd, self.layout.code)
        self.assertEqual(cmd[1], "app.py")
        self.assertEqual(env["IGS_NODE_MODE"], "1")
        self.assertEqual(env["IGS_HOST"], "127.0.0.1")
        self.assertGreaterEqual(len(env["IGS_API_TOKEN"]), 32)
        self.assertEqual(env["IGS_DATA"], self.layout.data)
        info = AJ.read_json(self.layout.service_file)
        self.assertEqual((info["port"], info["token"]), (svc.port, svc.token))

    def test_signed_in_service_is_ready(self):
        svc = self.service(popen=self.popen(signed_in=True))
        self.tick(svc)
        rep = svc.report()
        self.assertTrue(rep["ready"])
        self.assertEqual(rep["account"], "demo_account")
        self.assertIsNone(rep["problem"])

    def test_the_browser_choice_reaches_the_service(self):
        svc = self.service()
        svc.browser = {"channel": "msedge", "path": "x", "name": "edge"}
        self.tick(svc)
        self.assertEqual(self.envs[0][2]["IGS_BROWSER_CHANNEL"], "msedge")
        self.assertNotIn("IGS_BROWSER_EXE", self.envs[0][2])
        self.assertEqual(svc.report()["browser"], {"name": "edge", "channel": "msedge"})

    def test_a_dead_service_is_started_again_and_counted(self):
        svc = self.service()
        self.tick(svc)
        first_port = svc.port
        self.last_fake.stop()
        svc.proc.code = 1
        self.tick(svc)
        self.assertEqual(svc.state, "up")
        self.assertEqual(len(self.envs), 2)
        self.assertEqual(svc.port, first_port, "the address the owner bookmarked stays the same")
        self.assertEqual(svc.report()["restarts_last_hour"], 1)

    def test_a_restart_loop_is_held_back(self):
        svc = self.service()
        for _ in range(AJ.MAX_RESTARTS_PER_HOUR + 3):
            self.tick(svc)
            svc.proc.code = 1
            self.fakes[-1].stop()
            self.t.now += 30
        self.assertLessEqual(len(self.envs), AJ.MAX_RESTARTS_PER_HOUR + 2)
        self.assertEqual(svc.error_code, "restart_loop")

    def test_the_system_proxy_is_set_once_when_abagram_has_none(self):
        svc = self.service(popen=self.popen(signed_in=True))
        with mock.patch.object(AJ, "wanted_proxy", lambda layout, env=None: ("http://127.0.0.1:10809", "system")):
            self.tick(svc)
            self.tick(svc)
        self.assertEqual(self.last_fake.proxy, "http://127.0.0.1:10809")
        self.assertEqual(len(self.last_fake.posted("/api/prefs")), 1)
        self.assertEqual(svc.report()["proxy"], "http://127.0.0.1:10809")

    def test_a_proxy_the_owner_set_in_abagram_is_never_replaced(self):
        svc = self.service(popen=self.popen(signed_in=True))
        self.tick(svc)
        self.last_fake.proxy = "socks5://127.0.0.1:1080"
        with mock.patch.object(AJ, "wanted_proxy", lambda layout, env=None: ("http://127.0.0.1:10809", "system")):
            self.tick(svc)
        self.assertEqual(self.last_fake.proxy, "socks5://127.0.0.1:1080")
        self.assertEqual(self.last_fake.posted("/api/prefs"), [])

    def test_reach_is_tested_once_an_hour_and_an_unreachable_line_is_the_problem(self):
        svc = self.service(popen=self.popen(signed_in=True))
        self.tick(svc)
        self.last_fake.reach = {"ok": False, "status": None, "ms": 12000, "via": "direct", "error": "ConnectTimeout"}
        self.t.now += AJ.REACH_EVERY_S + 1
        self.tick(svc)
        self.assertEqual(svc.report()["problem"], "unreachable")
        n = len(self.last_fake.posted("/api/health/test"))
        self.tick(svc)
        self.assertEqual(len(self.last_fake.posted("/api/health/test")), n, "no second test within the hour")

    def test_cooldown_is_a_problem_with_an_end_time(self):
        svc = self.service(popen=self.popen(signed_in=True))
        self.tick(svc)
        self.last_fake.cooldown = {"until": self.t.now + 900, "reason": "wait"}
        self.tick(svc)
        rep = svc.report()
        self.assertEqual(rep["problem"], "cooldown")
        self.assertEqual(rep["cooldown_until"], int(self.t.now + 900))

    def test_an_already_running_service_is_adopted_not_started_twice(self):
        fake = FakeAbagram(signed_in=True).start()
        self.fakes.append(fake)
        AJ.write_json(self.layout.service_file, {"port": fake.port, "token": TOKEN, "pid": os.getpid(), "code_stamp": AJ.code_stamp(self.layout)})
        svc = self.service()
        self.tick(svc)
        self.assertEqual(svc.state, "up")
        self.assertEqual(self.envs, [], "no second process")
        self.assertEqual(svc.port, fake.port)
        self.assertTrue(svc.report()["ready"])

    def test_updated_code_restarts_an_idle_service(self):
        svc = self.service(popen=self.popen(signed_in=True))
        self.tick(svc)
        open(os.path.join(self.layout.code, "ig_new.py"), "w").write("# new\n")
        self.tick(svc)
        self.assertEqual(self.last_fake.restart_asked, 1)

    def test_install_failure_is_visible_and_retried_later(self):
        svc = AJ.Service(self.agent, layout=self.layout, say=lambda m: None, popen=self.popen(), clock=self.t.time)
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise AJ.InstallError("pip_failed", "no package source worked")
        with mock.patch.object(AJ, "install", boom), mock.patch.object(AJ, "venv_ready", lambda *a, **k: False):
            svc.tick()
            self.assertEqual(svc.state, "error")
            self.assertEqual(svc.report()["problem"], "install_error")
            self.assertEqual(svc.report()["error_code"], "pip_failed")
            svc.tick()
            self.assertEqual(len(calls), 1, "not retried at once")
            self.t.now += AJ.RETRY_INSTALL_S[0] + 1
            svc.tick()
            self.assertEqual(len(calls), 2)
        warned = [m for lvl, m in self.agent.lines if lvl == "WARNING"]
        self.assertEqual(len(warned), 1, "one panel-log line per distinct problem")
        self.assertIn("آباگرام", warned[0])

    def test_installing_state_is_reported(self):
        svc = AJ.Service(self.agent, layout=self.layout, say=lambda m: None, popen=self.popen(), clock=self.t.time)
        self.assertEqual(svc.report()["problem"], "installing")
        self.assertFalse(svc.report()["installed"])


class FakeBootstrap:
    """The part of bootstrap.Bootstrap the supervisor reads (specs + item_state)."""

    def __init__(self, items=None, managed=True):
        self.specs = [{"feature": "abagram"}] if managed else [{"feature": "other"}]
        self.items = items or {}

    def item_state(self, feature, item_id):
        return self.items.get(item_id, {"state": "idle"})


class InstallListTests(unittest.TestCase):
    """The node's install list (requirements.d/abagram.json, agent 2.11) runs Abagram's installation through abagram_jobs' command line;
    the supervisor mirrors it and never installs in parallel."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-abagram-ilist-")
        self.agent = FakeAgent(self.tmp)
        self.layout = AJ.Layout(self.agent.HERE, self.agent.DATA)
        self.t = Clock()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def svc(self):
        return AJ.Service(self.agent, layout=self.layout, say=lambda m: None, popen=None, clock=self.t.time)

    # ---- the requirements.d file
    def test_the_shipped_file_is_valid_and_every_command_exists(self):
        import bootstrap as bs
        specs, errors = bs.load_specs(os.path.join(PROC, "requirements.d"))
        self.assertEqual(errors, [])
        spec = next(s for s in specs if s["feature"] == AJ.FEATURE)
        self.assertTrue(spec["title_fa"])
        self.assertEqual(spec["platform"], ["win"])
        self.assertEqual(spec["kinds"], ["ig.scrape"], "only the reading waits; ig.health must still answer so the self-test sees the state")
        self.assertEqual([i["id"] for i in spec["items"]], ["packages", "browser"])
        for item in spec["items"]:
            self.assertEqual(item["type"], "cmd")
            for key in ("check", "install"):
                self.assertEqual(item[key][:2], ["{PY}", "{HERE}/abagram_jobs.py"])
                self.assertIn(item[key][2], AJ.CLI_COMMANDS)
                self.assertTrue(callable(getattr(AJ, AJ.CLI_COMMANDS[item[key][2]])))

    def test_the_lock_file_and_the_file_in_requirements_d_are_both_shipped_in_the_update(self):
        self.assertTrue(os.path.isfile(os.path.join(PROC, "abagram", "requirements-node.lock.txt")))
        self.assertTrue(os.path.isfile(os.path.join(PROC, "requirements.d", "abagram.json")))

    def test_the_real_install_engine_installs_through_the_commands_and_then_stops_blocking_the_kind(self):
        import bootstrap as bs
        specs_dir = os.path.join(self.tmp, "req.d")
        os.makedirs(specs_dir)
        shutil.copy(os.path.join(PROC, "requirements.d", "abagram.json"), specs_dir)
        state = {"packages": False, "browser": False}
        calls = []

        def fake_run(cmd, timeout=600, env=None, on_line=None):
            calls.append(list(cmd))
            self.assertTrue(cmd[1].endswith("abagram_jobs.py"), cmd)
            word = cmd[2]
            what = word.split("-", 1)[1]
            if word.startswith("check-"):
                return (0 if state[what] else 1), ("%s: %s" % (what, state[what]))
            state[what] = True
            return 0, "%s: installed" % what

        ctx = bs.Ctx(os.path.join(self.tmp, "nodedata"), run=fake_run, py="PYTHON", gpu_present=True, plat="win")
        eng = bs.Bootstrap(ctx, specs_dir)
        before = eng.status()
        self.assertEqual(before["features"]["abagram"]["state"], "waiting")
        self.assertIn("ig.scrape", before["blocked_kinds"], "until it is ready the reading waits in the site's queue")
        self.assertEqual(eng.run_once(), 0)
        after = eng.status()
        self.assertEqual(after["features"]["abagram"]["state"], "ready")
        self.assertNotIn("ig.scrape", after["blocked_kinds"])
        installs = [c[2] for c in calls if c[2].startswith("install-")]
        self.assertEqual(installs, ["install-packages", "install-browser"])
        n = len(calls)
        self.assertEqual(eng.run_once(), 0)
        self.assertEqual([c[2] for c in calls[n:]], ["check-packages", "check-browser"], "a second pass only checks - idempotent")

    def test_a_failing_install_is_shown_with_its_reason_and_retried_by_the_engine(self):
        import bootstrap as bs
        specs_dir = os.path.join(self.tmp, "req.d")
        os.makedirs(specs_dir)
        shutil.copy(os.path.join(PROC, "requirements.d", "abagram.json"), specs_dir)

        def fake_run(cmd, timeout=600, env=None, on_line=None):
            if cmd[2].startswith("check-"):
                return 1, "no"
            return 1, "FAILED (pip_failed): no package source worked (https://pypi.org/simple)"

        eng = bs.Bootstrap(bs.Ctx(os.path.join(self.tmp, "nodedata"), run=fake_run, py="PYTHON", gpu_present=True, plat="win"), specs_dir)
        self.assertEqual(eng.run_once(), 2)
        f = eng.status()["features"]["abagram"]
        self.assertEqual(f["state"], "failed")
        self.assertIn("pip_failed", f["items"][0]["error"])
        self.assertIn("ig.scrape", eng.status()["blocked_kinds"])

    # ---- the supervisor mirrors the install list
    def test_while_the_install_list_installs_the_supervisor_waits_and_never_installs(self):
        self.agent.BOOTSTRAP = FakeBootstrap({"packages": {"state": "installing", "detail": "installing ..."}})
        svc = self.svc()

        def never(*a, **k):
            raise AssertionError("the supervisor must not install while the install list manages Abagram")
        with mock.patch.object(AJ, "install", never):
            svc.tick()
        self.assertEqual(svc.state, "installing")
        rep = svc.report()
        self.assertEqual(rep["problem"], "installing")
        self.assertEqual(rep["step"], "installing ...")

    def test_a_failed_install_list_item_becomes_the_install_error_of_the_report(self):
        self.agent.BOOTSTRAP = FakeBootstrap({"packages": {"state": "failed", "error": "FAILED (pip_failed): no package source worked"}})
        svc = self.svc()
        svc.tick()
        rep = svc.report()
        self.assertEqual(rep["problem"], "install_error")
        self.assertEqual(rep["error_code"], "pip_failed")
        self.assertIn("no package source worked", rep["error"])

    def test_without_an_install_list_entry_the_supervisor_installs_by_itself(self):
        for boot in (None, FakeBootstrap(managed=False)):
            self.agent.BOOTSTRAP = boot
            svc = self.svc()
            calls = []
            with mock.patch.object(AJ, "install", lambda *a, **k: calls.append(1) or "installed"), \
                    mock.patch.object(AJ, "venv_ready", lambda *a, **k: False), \
                    mock.patch.object(AJ, "ensure_browser", lambda *a, **k: {"channel": "msedge", "name": "edge"}), \
                    mock.patch.object(AJ.Service, "_ensure_running", lambda s: None), mock.patch.object(AJ.Service, "_poll", lambda s: None):
                svc.tick()
            self.assertEqual(calls, [1], "own install path (the install list is absent)")

    # ---- the command line the install list runs
    def run_cli(self, fn, *a):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn(*a)
        return rc, buf.getvalue()

    def test_check_commands_answer_with_their_exit_code(self):
        with mock.patch.object(AJ, "venv_ready", lambda *a, **k: True):
            self.assertEqual(self.run_cli(AJ.cli_check_packages, self.layout)[0], 0)
        with mock.patch.object(AJ, "venv_ready", lambda *a, **k: False):
            self.assertEqual(self.run_cli(AJ.cli_check_packages, self.layout)[0], 1)
        with mock.patch.object(AJ, "find_browser", lambda *a, **k: {"name": "edge"}):
            self.assertEqual(self.run_cli(AJ.cli_check_browser, self.layout)[0], 0)
        with mock.patch.object(AJ, "find_browser", lambda *a, **k: {}):
            self.assertEqual(self.run_cli(AJ.cli_check_browser, self.layout)[0], 1)

    def test_install_packages_says_why_it_failed(self):
        def boom(*a, **k):
            raise AJ.InstallError("pip_failed", "no package source worked")
        with mock.patch.object(AJ, "install", boom):
            rc, out = self.run_cli(AJ.cli_install_packages, self.layout)
        self.assertEqual(rc, 1)
        self.assertIn("FAILED (pip_failed): no package source worked", out)
        with mock.patch.object(AJ, "install", lambda *a, **k: "installed"):
            rc, out = self.run_cli(AJ.cli_install_packages, self.layout)
        self.assertEqual((rc, "packages: installed" in out), (0, True))

    def test_install_browser_without_any_browser_names_the_way_out(self):
        with mock.patch.object(AJ, "ensure_browser", lambda *a, **k: {}):
            rc, out = self.run_cli(AJ.cli_install_browser, self.layout)
        self.assertEqual(rc, 1)
        self.assertIn("no_browser", out)
        self.assertIn(AJ.CHROMIUM_PACK, out)
        with mock.patch.object(AJ, "ensure_browser", lambda *a, **k: {"name": "edge"}):
            self.assertEqual(self.run_cli(AJ.cli_install_browser, self.layout)[0], 0)

    def test_the_site_address_and_token_come_from_node_json_in_the_data_folder(self):
        AJ.write_json(os.path.join(self.agent.DATA, "node.json"), {"site": "https://nm.example/", "token": "TOK"})
        shim = AJ.SiteShim(self.layout)
        self.assertEqual(shim.site_base(), "https://nm.example")
        self.assertEqual(shim.CONFIG["token"], "TOK")

    def test_main_runs_the_named_command_with_the_nodes_layout(self):
        seen = []
        with mock.patch.object(AJ, "_layout_from_here", lambda: self.layout), \
                mock.patch.object(AJ, "cli_check_packages", lambda layout: seen.append(layout) or 0):
            self.assertEqual(AJ.main(["check-packages"]), 0)
        self.assertEqual(seen, [self.layout])


class RealAbagramTests(unittest.TestCase):
    """The vendored Abagram itself, in node mode, on synthetic saved pages (no browser: fresh=False serves from disk)."""

    @classmethod
    def setUpClass(cls):
        try:
            import fastapi  # noqa: F401
            import playwright  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("this Python lacks Abagram's requirements (fastapi, uvicorn, playwright)")
        code = os.path.join(PROC, "abagram")
        if not os.path.isfile(os.path.join(code, "app.py")):
            raise unittest.SkipTest("abagram/ is not here")
        cls.tmp = tempfile.mkdtemp(prefix="nm-abagram-real-")
        sys.path.insert(0, os.path.join(code, "tests"))
        from nm_fixture import post, write_page
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        for name in ("real_one", "real_two"):
            write_page(cls.tmp, name, [post("%s%d" % (name[5:8].upper(), i), age_h=5 + i, likes=100 * (i + 1)) for i in range(5)],
                       prof={"username": name, "user_id": "5%d" % len(name), "full_name": "ساختگی", "biography": "", "followers": 4000,
                             "following": 5, "posts": 20, "is_private": False, "is_verified": False, "is_business": False, "category": "",
                             "fetched_at": stamp})
            sec = os.path.join(cls.tmp, "posts", "p_%s.json" % name)
            d = json.load(open(sec, encoding="utf-8"))
            d["fetched_at"] = stamp
            json.dump(d, open(sec, "w", encoding="utf-8"), ensure_ascii=False)
        os.makedirs(os.path.join(cls.tmp, "profile"), exist_ok=True)
        open(os.path.join(cls.tmp, "session.json"), "w").write(json.dumps({"username": "demo_account", "user_id": "1", "saved_at": stamp}))
        cls.port = free_port()
        env = dict(os.environ, PYTHONUTF8="1", IGS_PORT=str(cls.port), IGS_HOST="127.0.0.1", IGS_DATA=cls.tmp, IGS_API_TOKEN=TOKEN,
                   IGS_NODE_MODE="1", IGS_AUTH="0", IGS_NO_BROWSER="1")
        cls.proc = subprocess.Popen([sys.executable, "app.py"], cwd=code, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.client = AJ.Client(cls.port, TOKEN, timeout=10)
        for _ in range(80):
            try:
                cls.client.status()
                break
            except AJ.ServiceDown:
                time.sleep(0.25)
        else:
            cls.proc.kill()
            raise unittest.SkipTest("the vendored Abagram did not start here")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_status_summary_and_signed_in(self):
        s = AJ.summarize_status(self.client.status())
        self.assertTrue(s["signed_in"])
        self.assertEqual(s["pages_hour"][1], 30)

    def test_full_scrape_through_the_real_engine(self):
        batch = AJ.scrape(self.client, ["real_one", "real_two"], fresh=False, pace=(15, 16), sleep=lambda s: time.sleep(0.01 if s != 2 else 0.2))
        self.assertIsNone(batch["stopped"], batch)
        self.assertEqual([a["username"] for a in batch["accounts"]], ["real_one", "real_two"])
        self.assertEqual(len(batch["posts"]), 10)
        self.assertEqual(batch["accounts"][0]["followers"], 4000)
        self.assertEqual(self.client.get("/api/trend/never_read")[0], 404)

    def test_the_door_is_closed_without_the_key(self):
        bad = AJ.Client(self.port, "z" * 48, timeout=5)
        with self.assertRaises(AJ.ServiceDown):
            bad.status()


class AgentWiringTests(unittest.TestCase):
    """agent.py itself: the one guarded line registered the kinds, and a broken module can never stop the agent."""

    def test_agent_registers_the_kinds_and_reports_abagram(self):
        import agent
        self.assertIn("ig.scrape", agent.HANDLERS)
        self.assertIn("ig.health", agent.HANDLERS)
        self.assertIn("ig.scrape", agent.BACKGROUND_KINDS)
        self.assertIn("ollama.pull", agent.BACKGROUND_KINDS)
        self.assertTrue(getattr(agent.Capabilities.probe, "_abagram_wrapped", False))
        caps = agent.Capabilities("test", 1)
        with mock.patch.object(AJ.Service, "ensure_thread", lambda s: None), mock.patch.object(agent, "gpu_names", lambda: []),                 mock.patch.object(agent, "listening", lambda *a, **k: False):
            out = caps.probe()
        self.assertTrue(out["instagram"])
        self.assertIn("problem", out["abagram"])
        self.assertEqual(out["agent"], agent.VERSION)
        json.dumps(out["abagram"])                       # the report must be plain JSON

    def test_the_site_capability_for_the_kinds_is_instagram(self):
        # the node advertises caps["instagram"]; the site maps ig.* to that capability (apps/compute/models.py)
        self.assertEqual(AJ.caps_for.__name__, "caps_for")


if __name__ == "__main__":
    unittest.main()
