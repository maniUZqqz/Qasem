"""crawl21.run - the node side of the 21st.dev crawler: robots.txt rules, the crawl loop (with a fake Playwright), the agent handler, the install list and the
automatic install wiring. No browser, no network."""
import atexit
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-crawl21-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import crawl21_jobs as C  # noqa: E402

_DIRS = []


def tmpdir(prefix="c21n-"):
    d = tempfile.mkdtemp(prefix=prefix)
    _DIRS.append(d)
    return d


atexit.register(lambda: [shutil.rmtree(d, True) for d in _DIRS + [os.environ.get("NM_DATA", "")] if d])

ROBOTS = """User-agent: *
Content-Signal: ai-train=no, search=yes, ai-input=yes
Allow: /
Allow: /api/og/
Disallow: /api/
Disallow: /r/
Disallow: /preview/
Disallow: /auth/
User-agent: GPTBot
Allow: /r/
"""


def _open(path):
    import io
    with open(path, encoding="utf-8") as fh:
        return io.StringIO(fh.read())


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _dump(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


class RobotsTests(unittest.TestCase):
    def test_same_rules_as_the_site(self):
        r = C.Robots(ROBOTS)
        for ok in ("https://21st.dev/@a/components/b", "https://21st.dev/@a/components/b.md", "https://21st.dev/", "https://21st.dev/api/og/x", "/@a/components/b"):
            self.assertTrue(r.allowed(ok), ok)
        for no in ("https://21st.dev/r/a/b", "https://21st.dev/api/x", "https://21st.dev/preview/z", "https://21st.dev/auth/in"):
            self.assertFalse(r.allowed(no), no)
        self.assertTrue(r.allowed("https://21st.dev/r/a/b", ua="GPTBot"))
        self.assertFalse(C.Robots("", ok=False).allowed("https://21st.dev/"))
        self.assertTrue(C.Robots("User-agent: *\nDisallow: /a/\nAllow: /a/b").allowed("/a/b"))
        self.assertFalse(C.Robots("User-agent: *\nDisallow: /*.json$").allowed("/x.json"))

    def test_only_21st_urls_are_checked_by_the_gate(self):
        self.assertTrue(C.is_21st("https://21st.dev/x"))
        self.assertTrue(C.is_21st("https://www.21st.dev/"))
        self.assertFalse(C.is_21st("https://cdn.example.com/a.js"))
        self.assertFalse(C.is_21st("https://21st.dev.evil.example/x"))


class Resp:
    def __init__(self, status, text=""):
        self.status, self._t = status, text

    def text(self):
        return self._t


class FakePage:
    def __init__(self, ctx):
        self.ctx, self.url = ctx, ""

    def route(self, pattern, fn):
        self.ctx.gates.append(fn)

    def goto(self, url, **kw):
        self.ctx.visited.append(url)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        return {"title": "Marquee", "demo": {"file": "Usage.tsx", "code": "import x from 'y'"}, "text": "t"}

    def close(self):
        pass


class FakeCtx:
    def __init__(self, pages_md):
        self.md, self.visited, self.requests, self.gates = pages_md, [], [], []
        self.request = self

    def get(self, url, **kw):
        self.requests.append(url)
        if url.endswith("robots.txt"):
            return Resp(200, ROBOTS)
        key = url.replace("https://21st.dev", "")
        return Resp(*self.md[key]) if key in self.md else Resp(404)

    def new_page(self):
        return FakePage(self)


class FakeBrowser:
    def __init__(self, ctx):
        self.ctx, self.closed = ctx, False

    def new_context(self, **kw):
        self.kw = kw
        return self.ctx

    def close(self):
        self.closed = True


class FakePW:
    def __init__(self, ctx, fail=()):
        self.ctx, self.fail, self.tried = ctx, set(fail), []
        self.browser = FakeBrowser(ctx)
        self.chromium = self

    def launch(self, channel=None, headless=True):
        self.tried.append(channel)
        if channel in self.fail:
            raise RuntimeError("not installed: %s" % channel)
        return self.browser

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CrawlTests(unittest.TestCase):
    def run_crawl(self, ids, md, fail=(), payload=None, **kw):
        ctx = FakeCtx(md)
        pw = FakePW(ctx, fail)
        out = os.path.join(tmpdir(), "results.json")
        prog = []
        with mock.patch("time.sleep", lambda s: None):
            res = C.crawl({"ids": ids, "delay_s": 1.0, **(payload or {})}, out, progress=lambda f, m: prog.append((f, m)), say=lambda m: None, sync_playwright=lambda: pw)
        self.assertEqual(json.load(_open(out)), res)
        return res, ctx, pw, prog

    def test_edge_first_then_chrome_then_chromium(self):
        res, _ctx, pw, _ = self.run_crawl(["a/b"], {"/@a/components/b.md": (200, "# B\n- License: mit")}, fail=("msedge",))
        self.assertEqual(pw.tried, ["msedge", "chrome"])
        self.assertEqual(res["browser"], "chrome")
        res2, _c, pw2, _ = self.run_crawl(["a/b"], {}, fail=("msedge", "chrome"))
        self.assertEqual(pw2.tried, ["msedge", "chrome", None])
        self.assertEqual(res2["browser"], "chromium")
        broken = FakePW(FakeCtx({}), fail=("msedge", "chrome", None))
        with self.assertRaises(RuntimeError):
            C.launch_browser(broken)

    def test_md_and_demo_come_back_and_only_allowed_urls_are_opened(self):
        res, ctx, pw, prog = self.run_crawl(["acme/hero", "zed/card"], {"/@acme/components/hero.md": (200, "# Hero\n- License: mit\n"), "/@zed/components/card.md": (404, "")})
        self.assertEqual([r["ok"] for r in res["results"]], [True, True])                           # card: صفحه خوانده شد حتی اگر .md نبود
        self.assertTrue(res["results"][0]["md"].startswith("# Hero"))
        self.assertIn("import", res["results"][0]["page"]["demo"]["code"])
        self.assertEqual(ctx.visited, ["https://21st.dev/@acme/components/hero", "https://21st.dev/@zed/components/card"])
        self.assertTrue(all(not any(bad in u for bad in ("/r/", "/api/", "/preview/")) for u in ctx.requests + ctx.visited))
        self.assertEqual(prog[-1][0], 1.0)
        self.assertTrue(pw.browser.closed)
        self.assertIn("NMarketingBot", pw.browser.kw["user_agent"])
        self.assertEqual(res["count"], 2)

    def test_the_route_gate_aborts_disallowed_and_heavy_requests(self):
        _res, ctx, _pw, _ = self.run_crawl(["a/b"], {})
        gate = ctx.gates[0]
        calls = []

        def route(url, rtype):
            r = mock.Mock()
            r.request.url, r.request.resource_type = url, rtype
            r.abort.side_effect = lambda: calls.append("abort")
            r.continue_.side_effect = lambda: calls.append("continue")
            gate(r)
        route("https://21st.dev/api/components", "xhr")
        route("https://21st.dev/r/a/b", "fetch")
        route("https://21st.dev/@a/components/b", "document")
        route("https://cdn.21st.dev/x.png", "image")
        route("https://cdn.example.com/lib.js", "script")
        self.assertEqual(calls, ["abort", "abort", "continue", "abort", "continue"])

    def test_robots_refusal_and_unreadable_robots_and_ids_are_validated(self):
        res, ctx, _pw, _ = self.run_crawl(["acme/ok"], {}, payload={"robots": "User-agent: *\nDisallow: /@acme/\n"})
        self.assertEqual(res["results"][0]["error"], "robots")
        self.assertEqual(ctx.visited, [])
        res, ctx, _pw, _ = self.run_crawl(["../etc/passwd", "a b/c", "x/y"] + ["ok/%d" % i for i in range(60)], {})
        self.assertEqual(res["count"], C.MAX_IDS)                                                   # بد را می‌اندازد و سقف دارد
        self.assertFalse(any("passwd" in u or " " in u for u in ctx.visited))

    def test_403_four_times_stops_the_crawl(self):
        ctx = FakeCtx({})
        ctx.get = lambda url, **kw: Resp(200, ROBOTS) if url.endswith("robots.txt") else Resp(403)
        pw = FakePW(ctx)
        out = os.path.join(tmpdir(), "r.json")
        with mock.patch("time.sleep", lambda s: None):
            res = C.crawl({"ids": ["a/%d" % i for i in range(20)]}, out, say=lambda m: None, sync_playwright=lambda: pw)
        self.assertLess(res["count"], 20)
        self.assertTrue(all(not r["ok"] for r in res["results"]))


class FakeJob:
    def __init__(self, payload, tmp):
        self.payload, self.dir, self.timeout_s, self.cancelled = payload, tmp, 600, False
        self.progress_calls = []

    def out(self, name):
        os.makedirs(os.path.join(self.dir, "outputs"), exist_ok=True)
        return os.path.join(self.dir, "outputs", name)

    def progress(self, f, m="", meta=None):
        self.progress_calls.append((f, m))


class FakeAgent:
    class JobError(RuntimeError):
        def __init__(self, message, retryable=True):
            super().__init__(message)
            self.retryable = retryable

    class Cancelled(Exception):
        pass

    def __init__(self, data):
        self.DATA, self.HANDLERS = data, {}


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.data = tmpdir("c21n-data-")
        self.agent = FakeAgent(self.data)

    def test_install_registers_the_kind(self):
        C.install(self.agent)
        self.assertIn("crawl21.run", self.agent.HANDLERS)

    def test_empty_ids_is_a_final_error_and_missing_environment_waits(self):
        job = FakeJob({"ids": []}, tmpdir())
        with self.assertRaises(FakeAgent.JobError) as cm:
            C.run(job, self.agent)
        self.assertFalse(cm.exception.retryable)
        job = FakeJob({"ids": ["a/b"]}, tmpdir())
        with mock.patch.object(C, "venv_python", return_value=""):
            with self.assertRaises(FakeAgent.JobError) as cm:
                C.run(job, self.agent)
        self.assertTrue(str(cm.exception).startswith("DOWNLOADING:"))

    def test_the_handler_runs_the_worker_in_the_venv_and_returns_meta(self):
        job = FakeJob({"ids": ["acme/hero"], "robots": ROBOTS}, tmpdir())
        out = job.out("results.json")

        class Proc:
            returncode = 0
            stdout = iter(["PROGRESS 0.500 1 / 2  a/b\n", "PROGRESS 1.000 2 / 2  c/d\n"])

            def poll(self):
                return 0

            def wait(self):
                return 0

        def popen(cmd, **kw):
            self.cmd = cmd
            _dump({"results": [], "browser": "msedge", "count": 1, "ok": 1, "seconds": 3.2}, out)
            return Proc()
        with mock.patch.object(C, "venv_python", return_value="/venv/python"), mock.patch("subprocess.Popen", popen), mock.patch("time.sleep", lambda s: None):
            meta = C.run(job, self.agent)
        self.assertEqual(self.cmd[:2], ["/venv/python", os.path.abspath(C.__file__)])
        self.assertEqual(self.cmd[2], "--worker")
        self.assertEqual(json.load(_open(self.cmd[3]))["ids"], ["acme/hero"])
        self.assertEqual((meta["primary"], meta["engine"], meta["device_note"]), ("results.json", "playwright", "browser: msedge"))

    def test_worker_failure_surfaces_the_tail_of_its_output(self):
        job = FakeJob({"ids": ["a/b"]}, tmpdir())

        class Proc:
            returncode = 3
            stdout = iter(["Traceback...\n", "RuntimeError: no browser\n"])

            def poll(self):
                return 3
        with mock.patch.object(C, "venv_python", return_value="/venv/python"), mock.patch("subprocess.Popen", lambda cmd, **kw: Proc()), mock.patch("time.sleep", lambda s: None):
            with self.assertRaises(FakeAgent.JobError) as cm:
                C.run(job, self.agent)
        self.assertIn("exit 3", str(cm.exception))


class CommandLineTests(unittest.TestCase):
    def test_check_reports_missing_playwright_and_missing_browser_and_installs_as_a_last_resort(self):
        with mock.patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            self.assertEqual(C.check(say=lambda m: None), 2)
        with mock.patch.object(C, "check", side_effect=[3, 0]) as chk, mock.patch.object(C, "install_browser", return_value=0) as inst:
            self.assertEqual(C.main(["x", "--check"]), 0)
        self.assertEqual((chk.call_count, inst.call_count), (2, 1))
        with mock.patch.object(C, "check", return_value=0), mock.patch.object(C, "install_browser") as inst:
            self.assertEqual(C.main(["x", "--check"]), 0)
        inst.assert_not_called()

    def test_install_browser_tries_the_mirrors_in_order(self):
        envs = []

        def run(cmd, env=None, **kw):
            envs.append(env.get("PLAYWRIGHT_DOWNLOAD_HOST"))
            return mock.Mock(returncode=0 if len(envs) == 3 else 1, stdout="x")
        with mock.patch("subprocess.run", run):
            self.assertEqual(C.install_browser(say=lambda m: None), 0)
        self.assertEqual(envs[0], None)
        self.assertTrue(all(e and "npmmirror" in e for e in envs[1:]))

    def test_manual_run_reads_ids_from_a_file(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        f.write("acme/hero\nnot valid\nzed/card\n")
        f.close()
        out = f.name + ".json"
        with mock.patch.object(C, "crawl", return_value={"ok": 2, "count": 2, "browser": "msedge"}) as cr:
            self.assertEqual(C.main(["x", "--run", f.name, out]), 0)
        self.assertEqual(cr.call_args[0][0]["ids"], ["acme/hero", "zed/card"])


class InstallListTests(unittest.TestCase):
    def spec(self):
        return json.load(_open(os.path.join(HERE, "requirements.d", "crawl21.json")))

    def test_the_feature_file_installs_everything_by_itself_and_keeps_the_kind_waiting(self):
        s = self.spec()
        self.assertEqual((s["feature"], s["kinds"], s["platform"]), ("crawl21", ["crawl21.run"], ["win"]))
        kinds = [i["type"] for i in s["items"]]
        self.assertEqual(kinds, ["venv", "pip", "cmd"])
        pip = s["items"][1]
        self.assertTrue(all("==" in p for p in pip["packages"]))                                    # نسخه‌ها پین‌شده
        cmd = s["items"][2]
        self.assertIn("--check", cmd["check"])
        self.assertIn("--install-browser", cmd["install"])
        self.assertIn("{VENVPY:crawl21}", cmd["check"][0])
        self.assertEqual(s["items"][0]["name"], "crawl21")
        self.assertTrue(s["title_fa"])

    def test_the_agent_registers_the_module_with_one_guarded_block_and_the_bootstrap_reads_the_file(self):
        src = _read(os.path.join(HERE, "agent.py"))
        self.assertIn('__import__("crawl21_jobs").install(sys.modules[__name__])', src)
        i = src.index('__import__("crawl21_jobs")')
        self.assertIn("try:", src[i - 400:i])
        self.assertIn("except Exception", src[i:i + 300])                                           # ماژولِ خراب هرگز عامل را نمی‌خواباند
        import bootstrap
        specs, errors = bootstrap.load_specs(os.path.join(HERE, "requirements.d")) if hasattr(bootstrap, "load_specs") else ([], [])
        if specs:
            self.assertFalse(errors)
            self.assertIn("crawl21", [x["feature"] for x in specs])

    def test_the_module_is_standard_library_only_at_import_time(self):
        src = _read(os.path.join(HERE, "crawl21_jobs.py"))
        top = src.split("def launch_browser")[0]
        self.assertNotIn("import playwright", top)
        self.assertNotIn("from playwright", top)


if __name__ == "__main__":
    unittest.main()
