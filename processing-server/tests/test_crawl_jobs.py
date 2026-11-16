"""crawl_jobs.py (the customer finder's node half), without a real browser and without the internet: a local web server stands in for the sites,
a fake renderer stands in for Playwright.

    python tests/test_crawl_jobs.py
"""
import gzip
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")

import crawl_jobs as CJ  # noqa: E402

PAGES = {
    "/": '<html lang="fa"><head><title>باشگاه</title></head><body><h1>باشگاه آرمان</h1><p>باشگاه بدنسازی تهران، مربی‌های مجرب و برنامه‌های تمرینی اختصاصی برای همهٔ سطح‌ها</p>'
         '<nav><a href="/contact">تماس با ما</a><a href="/about">درباره ما</a><a href="/blog/1">وبلاگ</a><a href="https://other.example/x">بیرون</a></nav></body></html>',
    "/contact": '<html><body><h1>تماس</h1><a href="tel:+989121234567">۰۹۱۲</a><script type="application/ld+json">{"@type":"Gym","telephone":"021"}</script><script>var x=1</script></body></html>',
    "/about": "<html><body>درباره‌ی ما: ما سال‌هاست کار می‌کنیم و مربی‌های زیادی داریم که شاگردان را راهنمایی می‌کنند.</body></html>",
    "/shell/": '<html><head><title>app</title></head><body><div id="root"></div><script src="/a.js"></script><script>1</script></body></html>',
    "/redirect": None,
    "/offsite": None,
    "/private": None,
    "/blocked/": "<html><body>blocked by robots</body></html>",
}
ROBOTS = "User-agent: *\nDisallow: /blocked/\n"


class H(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):  # noqa: N802
        H.hits.append(self.path)
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            return self._send(200, ROBOTS, "text/plain")
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/contact")
            self.end_headers()
            return
        if path == "/offsite":
            self.send_response(302)
            self.send_header("Location", "http://example.org/x")
            self.end_headers()
            return
        body = PAGES.get(path)
        if body is None:
            return self._send(404, "nope", "text/html")
        return self._send(200, body, "text/html; charset=utf-8")

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        return


class FakeJob:
    def __init__(self, payload):
        self.payload = payload
        self.dir = tempfile.mkdtemp(prefix="nm-job-")
        self.progress_calls = []

    def out(self, name):
        return os.path.join(self.dir, name)

    def progress(self, f, m=""):
        self.progress_calls.append((f, m))


class CrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def fetcher(self):
        return CJ.Fetcher(delay=0.0, allow_private=True)

    # -- guards
    def test_private_addresses_are_refused_by_default(self):
        with self.assertRaises(ValueError) as ctx:
            CJ.resolve_public("127.0.0.1", 80)
        self.assertEqual(str(ctx.exception), "ssrf_blocked")
        with self.assertRaises(ValueError):
            CJ.resolve_public("192.168.1.10", 80)
        self.assertTrue(CJ.resolve_public("93.184.216.34", 80))
        strict = CJ.Fetcher(delay=0.0)
        got = strict.get_page(self.base + "/")
        self.assertEqual(got["outcome"], "robots_unavailable")  # the very first thing, robots.txt, could not be asked: nothing was fetched

    def test_ports_other_than_web_ones_are_refused(self):
        f = CJ.Fetcher(delay=0.0)
        r = f._raw("http://93.184.216.34:22/")
        self.assertEqual(r["outcome"], "blocked_port")

    def test_robots_txt_is_obeyed(self):
        f = self.fetcher()
        ok, _ = f.allowed(self.base + "/blocked/x")
        self.assertFalse(ok)
        got = f.get_page(self.base + "/blocked/")
        self.assertEqual(got["outcome"], "robots_blocked")
        self.assertTrue(f.allowed(self.base + "/contact")[0])

    def test_redirects_stay_on_the_site(self):
        f = self.fetcher()
        ok = f.get_page(self.base + "/redirect")
        self.assertEqual(ok["outcome"], "ok")
        self.assertTrue(ok["final_url"].endswith("/contact"))
        off = f.get_page(self.base + "/offsite")
        self.assertEqual(off["outcome"], "redirect_offsite")

    def test_per_host_spacing(self):
        slept = []
        clock = [0.0]
        f = CJ.Fetcher(delay=2.0, allow_private=True, sleep=lambda s: slept.append(s), clock=lambda: clock[0])
        f._wait("a.example")
        f._wait("a.example")
        f._wait("b.example")
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 2.0)

    # -- reading
    def test_classify_and_pick_pages(self):
        links = [{"url": "/contact", "text": "تماس با ما"}, {"url": "/about", "text": "درباره ما"}, {"url": "/blog/1", "text": "وبلاگ"},
                 {"url": "https://other.example/contact", "text": "contact"}, {"url": "/file.pdf", "text": "تماس"}, {"url": "mailto:a@b.ir", "text": "تماس"}]
        chosen = CJ.pick_pages(links, "https://x.ir/", 5)
        self.assertEqual([c for _u, c in chosen], ["contact", "about"])
        self.assertTrue(all(u.startswith("https://x.ir") for u, _c in chosen))
        self.assertEqual(CJ.classify("https://x.ir/contact-us", ""), "contact")
        self.assertEqual(CJ.classify("https://x.ir/p/1", "پشتیبانی"), "support")
        self.assertEqual(CJ.classify("https://x.ir/shop", "فروشگاه"), "")

    def test_shell_detection(self):
        self.assertTrue(CJ.looks_like_shell(PAGES["/shell/"]))
        self.assertFalse(CJ.looks_like_shell(PAGES["/"]))

    def test_clean_html_keeps_jsonld_and_caps_size(self):
        cleaned = CJ.clean_html(PAGES["/contact"], 10_000)
        self.assertIn("ld+json", cleaned)
        self.assertNotIn("var x=1", cleaned)
        self.assertLessEqual(len(CJ.clean_html("<p>" + "ا" * 50_000 + "</p>", 5_000).encode("utf-8")), 5_000)

    # -- whole sites
    def test_crawl_static_site_reads_home_contact_about_only(self):
        H.hits.clear()
        rows = CJ.crawl_sites([{"id": 7, "url": self.base + "/"}], {"render": "never", "max_pages_per_site": 5, "allow_private": True}, fetcher=self.fetcher(), renderer=lambda items: {})
        self.assertEqual(rows[0]["id"], 7)
        self.assertEqual(rows[0]["status"], "ok")
        kinds = [p["kind"] for p in rows[0]["pages"]]
        self.assertEqual(kinds, ["home", "contact", "about"])
        self.assertNotIn("/blog/1", H.hits)
        self.assertIn("tel:", rows[0]["pages"][1]["html"])

    def test_js_shell_goes_to_the_renderer_and_its_contact_pages_too(self):
        asked = []

        def renderer(items):
            asked.append([i["url"] for i in items])
            out = {}
            for i in items:
                if i["url"].endswith("/shell/"):
                    out[i["key"]] = {"key": i["key"], "final_url": i["url"], "status": 200, "html": "<html><body><h1>باشگاه جاوا</h1><p>09125550000</p></body></html>",
                                     "links": [{"url": i["url"].replace("/shell/", "/contact"), "text": "تماس با ما"}]}
                else:
                    out[i["key"]] = {"key": i["key"], "final_url": i["url"], "status": 200, "html": "<html><body>info@js-gym.ir</body></html>", "links": []}
            return out

        rows = CJ.crawl_sites([{"id": 1, "url": self.base + "/shell/"}], {"render": "auto", "max_pages_per_site": 3, "allow_private": True}, fetcher=self.fetcher(), renderer=renderer)
        row = rows[0]
        self.assertEqual(row["status"], "ok")
        self.assertTrue(all(p["rendered"] for p in row["pages"]))
        self.assertIn("09125550000", row["pages"][0]["html"])
        self.assertEqual(len(asked), 2)  # one batch for the home page, one for the contact page

    def test_js_shell_without_a_browser_is_reported_not_faked(self):
        rows = CJ.crawl_sites([{"id": 1, "url": self.base + "/shell/"}], {"render": "auto", "max_pages_per_site": 3, "allow_private": True}, fetcher=self.fetcher(), renderer=lambda items: {})
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn(rows[0]["reason"], ("render_unavailable", "render_failed"))
        self.assertTrue(rows[0]["pages"])  # the shell itself is returned so the site can tell what it was

    def test_robots_blocked_site_is_reported(self):
        rows = CJ.crawl_sites([{"id": 3, "url": self.base + "/blocked/"}], {"render": "never", "allow_private": True}, fetcher=self.fetcher(), renderer=lambda items: {})
        self.assertEqual(rows[0]["reason"], "robots_blocked")
        self.assertEqual(rows[0]["pages"][0]["html"], "")

    def test_run_writes_the_gz_output_and_reports_progress(self):
        job = FakeJob({"sites": [{"id": 1, "url": self.base + "/"}], "render": "never", "max_pages_per_site": 3})
        orig = CJ.Fetcher
        CJ.Fetcher = lambda delay=2.0, allow_private=False, **kw: orig(delay=0.0, allow_private=True)
        try:
            meta = CJ.run(job, None, "crawl.run")
        finally:
            CJ.Fetcher = orig
        self.assertEqual(meta["primary"], "pages.jsonl.gz")
        self.assertEqual(meta["sites"], 1)
        with gzip.open(job.out("pages.jsonl.gz"), "rt", encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        self.assertEqual(rows[0]["status"], "ok")
        self.assertTrue(job.progress_calls)

    def test_render_kind_forces_the_browser(self):
        self.assertEqual(CJ._opts({"render": "never"}, "crawl.render")["render"], "always")
        self.assertEqual(CJ._opts({"render": "bogus"}, "crawl.run")["render"], "auto")
        self.assertEqual(CJ._opts({"max_pages_per_site": 99}, "crawl.run")["max_pages_per_site"], 10)

    # -- registration
    def test_register_adds_handlers_caps_and_background_kinds(self):
        class Caps:
            def probe(self):
                return {"gpu": "x"}

        class Agent:
            BACKGROUND_KINDS = ("ollama.pull",)
            Capabilities = Caps

        handlers = {}
        self.assertTrue(CJ.register(handlers, Agent))
        self.assertEqual(set(handlers), set(CJ.KINDS))
        self.assertTrue(set(CJ.KINDS) <= set(Agent.BACKGROUND_KINDS))
        caps = Caps().probe()
        self.assertTrue(caps["crawl"])
        self.assertIn("crawl_ready", caps)
        CJ.register({}, Agent)  # registering twice does not wrap twice
        self.assertTrue(Agent.Capabilities.probe._crawl)

    def test_requirements_file_is_valid_and_lists_the_render_kinds(self):
        with open(os.path.join(PROC, "requirements.d", "crawl.json"), encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertEqual(spec["feature"], "crawl")
        self.assertIn("crawl.render", spec["kinds"])
        self.assertTrue(any(i["type"] == "pip" and any(p.startswith("playwright==") for p in i["packages"]) for i in spec["items"]))
        self.assertTrue(all(i["type"] in ("venv", "pip", "cmd") for i in spec["items"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
