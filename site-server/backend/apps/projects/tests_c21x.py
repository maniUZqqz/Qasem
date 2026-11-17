# -*- coding: utf-8 -*-
"""21st.dev کامل: خزندهٔ مؤدب (robots، نقشهٔ سایت، تلاشِ مجدد، ازسرگیری)، فیلترِ مجوز، منبعِ کد (نمونهٔ استفاده + مخزنِ عمومی)، تبدیلِ React/Tailwind به قطعهٔ امن
(پاک‌سازی، راست‌به‌چپ، شکاف‌ها)، بلوکِ c21 در سایت‌ساز، خطِ تبدیل، کارِ گرهٔ GPU (crawl21.run) و پیشنهاد به AI.

شبکه، git و مرورگر واقعی صدا زده نمی‌شوند (همه تزریق‌پذیرند)؛ آزمونِ «node واقعی» فقط اگر /opt/nm-c21 نصب باشد اجرا می‌شود.
"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import mock, skipUnless

from django.test import SimpleTestCase, override_settings

from apps.projects.builder import (ai_context, c21_convert as CV, c21_crawl as CR, c21_embed as EM, c21_node as ND, c21_pipeline as PL, c21_source as SRC, c21st, render as R,
                                   styles as S)
from apps.projects.builder.clean import clean_doc, new_block
from apps.projects.tests_builder import Base
from services import safenet

ROBOTS_21ST = """# 21st
User-agent: *
Content-Signal: ai-train=no, search=yes, ai-input=yes
Allow: /
Allow: /api/og/
Disallow: /api/
Disallow: /r/
Disallow: /auth/
Disallow: /sign-in
Disallow: /admin/
Disallow: /preview/
Disallow: /community/bookmarks/

User-agent: GPTBot
Allow: /community/
Allow: /r/

Sitemap: https://21st.dev/sitemap.xml
"""
SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://21st.dev</loc></url>
<url><loc>https://21st.dev/@acme/components/hero-one</loc><lastmod>2026-11-01T00:00:00Z</lastmod></url>
<url><loc>https://21st.dev/@acme/components/price-table</loc><lastmod>2026-11-02T00:00:00Z</lastmod></url>
<url><loc>https://21st.dev/@zed/components/nice-card</loc><lastmod>2026-11-03T00:00:00Z</lastmod></url>
<url><loc>https://21st.dev/@acme/library/acme-ui</loc><lastmod>2026-11-01T00:00:00Z</lastmod></url>
<url><loc>https://21st.dev/community/components/s/hero</loc></url>
</urlset>"""
CATEGORY = "# Hero\n\n- [Hero One](https://21st.dev/@acme/components/hero-one.md) — by Acme\n"
LIBRARY = """# Acme UI

> Blocks.

- Owner: [Acme](https://21st.dev/@acme)
- Components: 2
- Website: https://acme.example
- GitHub: https://github.com/acme/acme-ui.git

## Components

- [Hero One](https://21st.dev/@acme/components/hero-one.md)
- [Price Table](https://21st.dev/@acme/components/price-table.md)
"""


def md(title, lic, lib="[Acme UI](https://21st.dev/@acme/library/acme-ui)", tags="Hero, Pricing Section"):
    return ("# %s\n\n> About %s.\n\n- Author: [Acme](https://21st.dev/@acme)\n- Library: %s\n- License: %s\n- Tags: %s\n- npm dependencies: lucide-react\n- Live preview: x\n"
            % (title, title.lower(), lib, lic, tags))


def png_bytes():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (1200, 630), (30, 120, 160)).save(b, "PNG")
    return b.getvalue()


class Fake:
    """safenet.get ِ ساختگی: نشانی ⇒ متن/بایت یا FetchError؛ همهٔ درخواست‌ها ثبت می‌شود."""

    def __init__(self, routes):
        self.routes, self.calls = dict(routes), []

    def __call__(self, url, **kw):
        self.calls.append(url)
        path = url.replace("https://21st.dev", "")
        v = self.routes.get(path)
        if isinstance(v, list):                       # پاسخ‌های پشت‌سرهم (برای تلاشِ مجدد)
            v = v.pop(0) if len(v) > 1 else v[0]
        if v is None:
            raise safenet.FetchError("سایت جواب 404 داد.", "http_404")
        if isinstance(v, safenet.FetchError):
            raise v
        body = v if isinstance(v, bytes) else v.encode("utf-8")
        return safenet.Fetched(url=url, status=200, content_type="text/plain", body=body)


def session(routes, **kw):
    sl = []
    kw.setdefault("delay", 1.2)
    s = CR.Session(fetch=Fake({"/robots.txt": ROBOTS_21ST, **routes}), sleep=sl.append, clock=lambda: len(sl) * 100.0, jitter=0, **kw)
    s.sleeps = sl
    return s


class DataDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="c21x-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._ov = override_settings(NM_DATA_DIR=self.tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        c21st._cache.update(mtime=0.0, rows=[])
        CV._CACHE.clear()


class RobotsTests(SimpleTestCase):
    def test_longest_match_allow_wins_ties_and_groups(self):
        r = CR.Robots(ROBOTS_21ST)
        for ok in ("/", "/@a/components/b", "/@a/components/b.md", "/community/components/s/hero.md", "/og/component/a/b", "/api/og/x", "/sitemap.xml"):
            self.assertTrue(r.allowed("https://21st.dev" + ok), ok)
        for no in ("/r/a/b", "/api/components", "/preview/x", "/auth/login", "/sign-in", "/admin/", "/community/bookmarks/x"):
            self.assertFalse(r.allowed("https://21st.dev" + no), no)
        self.assertTrue(r.allowed("https://21st.dev/r/a/b", ua="GPTBot"))                       # گروهِ خودش را دارد؛ ما GPTBot نیستیم
        self.assertFalse(r.allowed("https://21st.dev/r/a/b", ua="NMarketingBot"))
        self.assertTrue(CR.Robots("User-agent: *\nDisallow: /a/\nAllow: /a/b").allowed("/a/b"))  # بلندترین تطبیق
        self.assertFalse(CR.Robots("User-agent: *\nDisallow: /*.json$").allowed("/x/y.json"))
        self.assertTrue(CR.Robots("User-agent: *\nDisallow:\n").allowed("/anything"))
        self.assertFalse(CR.Robots("", ok=False).allowed("/"))                                  # robots.txt خوانده نشد ⇒ محتاطانه ممنوع
        self.assertEqual(CR.Robots("User-agent: *\nCrawl-delay: 5\n").crawl_delay(), 5.0)

    def test_session_refuses_forbidden_paths_without_sending_anything(self):
        s = session({})
        for path in ("/r/a/b", "/api/x", "/preview/y"):
            with self.assertRaises(safenet.FetchError) as cm:
                s.get("https://21st.dev" + path)
            self.assertEqual(cm.exception.code, "robots")
        self.assertEqual([u for u in s.fetch.calls if "/r/" in u or "/api/" in u or "/preview/" in u], [])
        self.assertEqual(s.refused, ["/r/a/b", "/api/x", "/preview/y"])

    def test_unreadable_robots_means_nothing_is_fetched_and_404_means_allowed(self):
        bad = CR.Session(fetch=Fake({"/robots.txt": safenet.FetchError("x", "timeout")}), sleep=lambda s: None)
        with self.assertRaises(safenet.FetchError):
            bad.get("https://21st.dev/@a/components/b.md")
        self.assertEqual(bad.fetch.calls.count("https://21st.dev/robots.txt"), CR.CONNECT_RETRIES + 1)          # چند بار تلاش، بعد محتاطانه
        flaky = CR.Session(fetch=Fake({"/robots.txt": [safenet.FetchError("x", "timeout"), safenet.FetchError("x", "http_503"), ROBOTS_21ST], "/a.md": "# a"}), sleep=lambda s: None, delay=0)
        self.assertTrue(flaky.get("https://21st.dev/a.md").text)                                  # گذرا بود ⇒ ادامه
        gone = CR.Session(fetch=Fake({}), sleep=lambda s: None)                                   # 404 = «robots.txt ندارد»
        self.assertTrue(gone.load_robots().ok)

    def test_rate_limit_retries_backoff_and_403_stop(self):
        s = session({"/x.md": [safenet.FetchError("m", "http_429"), safenet.FetchError("m", "http_503"), "# ok"]})
        self.assertEqual(s.get("https://21st.dev/x.md").text, "# ok")
        self.assertEqual(s.requests, 3)
        self.assertEqual(s.sleeps.count(2.0) + s.sleeps.count(6.0), 2)                         # صبرِ فزاینده
        flaky = session({"/y.md": [safenet.FetchError("m", "connect"), safenet.FetchError("m", "timeout"), safenet.FetchError("m", "connect"), "# y"]})
        self.assertEqual(flaky.get("https://21st.dev/y.md").text, "# y")                       # قطعِ اتصال: زود و با صبرِ کم دوباره
        self.assertEqual(flaky.requests, 4)
        self.assertLessEqual(max(x for x in flaky.sleeps if x < 5), 3.0)
        dead = session({"/z.md": safenet.FetchError("m", "connect")})
        with self.assertRaises(safenet.FetchError):
            dead.get("https://21st.dev/z.md")
        self.assertEqual(dead.requests, CR.CONNECT_RETRIES + 1)
        paced = session({"/a.md": "# a", "/b.md": "# b"})
        paced.get("https://21st.dev/a.md")
        paced.get("https://21st.dev/b.md")
        self.assertTrue(any(abs(x - 1.2) < 1e-6 or 0 < x <= 1.2 for x in paced.sleeps) or paced.sleeps == [])
        deny = session({"/c.md": safenet.FetchError("m", "http_403")})
        with self.assertRaises(safenet.FetchError):
            deny.get("https://21st.dev/c.md")
        with self.assertRaises(safenet.FetchError):
            deny.get("https://21st.dev/c.md")
        with self.assertRaises(safenet.FetchError):
            deny.get("https://21st.dev/c.md")
        with self.assertRaises(CR.CrawlBlocked):
            deny.get("https://21st.dev/c.md")


class ParsingTests(SimpleTestCase):
    def test_sitemap_library_and_tags(self):
        sm = CR.parse_sitemap(SITEMAP)
        self.assertEqual([c for c, _m in sm["components"]], ["acme/hero-one", "acme/price-table", "zed/nice-card"])
        self.assertEqual(sm["libraries"], [("acme/acme-ui", "2026-11-01T00:00:00Z")])
        lib = CR.parse_library_md(LIBRARY, "acme/acme-ui")
        self.assertEqual(lib["github"], "https://github.com/acme/acme-ui")                      # .git برداشته شد
        self.assertEqual(lib["component_ids"], ["acme/hero-one", "acme/price-table"])
        self.assertEqual(CR.library_id_of("[Magic UI](https://21st.dev/@dillionverma/library/magic-ui)"), "dillionverma/magic-ui")
        self.assertEqual(CR.parse_library_md("# X\n- GitHub: https://evil.example/x/y\n", "o/x")["github"], "")
        self.assertEqual(CR.tag_slug("Pricing Section"), "pricing-section")
        self.assertIn("pricing-section", CR.infer_cats({"id": "a/b", "title": "T", "tags": ["Pricing Section"]}))
        self.assertIn("hero", CR.infer_cats({"id": "a/hero-9", "title": "Super", "tags": []}))

    def test_licence_filter_only_open_licences_are_usable(self):
        for lic in ("mit", "MIT", "MIT-0", "apache-2.0", "bsd-3-clause", "isc", "cc0", "unlicense"):
            self.assertTrue(c21st.is_permissive(lic), lic)
        for lic in ("no-license", "unknown", "", "gpl-3.0", "proprietary", "cc-by-nc"):
            self.assertFalse(c21st.is_permissive(lic), lic)


class CrawlTurnTests(DataDirMixin, SimpleTestCase):
    def routes(self):
        routes = {"/sitemap.xml": SITEMAP, "/community/components/s/hero.md": CATEGORY, "/@acme/library/acme-ui.md": LIBRARY,
                  "/@acme/components/hero-one.md": md("Hero One", "mit"), "/@acme/components/price-table.md": md("Price Table", "no-license"),
                  "/@zed/components/nice-card.md": md("Nice Card", "apache-2.0", lib=""), "/og/component/acme/hero-one": png_bytes(), "/og/component/zed/nice-card": png_bytes()}
        return routes

    def test_one_turn_enumerates_everything_then_resumes_and_stays_polite(self):
        s = session(self.routes())
        st = CR.run_turn(session=s, categories=["hero"], max_seconds=10 ** 6, detail_limit=2, preview_limit=5)
        self.assertEqual(st["total"], 3)
        self.assertEqual(st["libraries"], 1)
        rows = {r["id"]: r for r in c21st.load()}
        self.assertEqual(rows["acme/hero-one"]["license"], "mit")
        self.assertTrue(rows["acme/hero-one"]["usable"])
        self.assertEqual(rows["acme/hero-one"]["library_id"], "acme/acme-ui")
        self.assertIn("hero", rows["acme/hero-one"]["cats"])
        self.assertFalse(st["finished"])
        self.assertGreaterEqual(st["remaining"], 1)                                             # detail_limit=2 ⇒ یکی مانده
        self.assertTrue(rows["acme/hero-one"].get("preview"))
        self.assertTrue(CR.preview_path("acme/hero-one").is_file())
        from PIL import Image
        self.assertEqual(Image.open(CR.preview_path("acme/hero-one")).width, CR.PREVIEW_W)      # کوچک‌شده
        st2 = CR.run_turn(session=s, categories=["hero"], max_seconds=10 ** 6, detail_limit=50, preview_limit=5)
        self.assertTrue(st2["finished"])
        rows = {r["id"]: r for r in c21st.load()}
        self.assertFalse(rows["acme/price-table"]["usable"])                                    # no-license ⇒ فقط کاتالوگ
        self.assertTrue(rows["zed/nice-card"]["usable"])
        self.assertNotIn("preview", rows["acme/price-table"])                                   # برای بی‌مجوز تصویر هم نمی‌گیریم
        self.assertEqual(st2["usable"], 2)
        self.assertEqual([u for u in s.fetch.calls if "/r/" in u or "/api/" in u or "/preview/" in u], [])
        self.assertEqual(s.fetch.calls.count("https://21st.dev/sitemap.xml"), 1)                # نقشه فقط یک بار (ازسرگیری)
        self.assertTrue(st2["robots_ok"])
        self.assertIn("/r/", st2["robots_disallow"])

    def test_blocked_server_stops_the_turn_and_hands_over_to_the_node(self):
        routes = self.routes()
        routes["/@acme/components/hero-one.md"] = safenet.FetchError("m", "http_403")
        routes["/@acme/components/price-table.md"] = safenet.FetchError("m", "http_403")
        routes["/@zed/components/nice-card.md"] = safenet.FetchError("m", "http_403")
        with mock.patch.object(CR, "STOP_AFTER_FORBIDDEN", 2):
            st = CR.run_turn(session=session(routes), categories=[], max_seconds=10 ** 6, detail_limit=50)
        self.assertTrue(st["blocked"])
        self.assertFalse(st["finished"])

    def test_unreadable_robots_crawls_nothing(self):
        s = CR.Session(fetch=Fake({"/robots.txt": safenet.FetchError("x", "timeout")}), sleep=lambda x: None)
        st = CR.run_turn(session=s, categories=[], max_seconds=100)
        self.assertFalse(st["robots_ok"])
        self.assertEqual(set(s.fetch.calls), {"https://21st.dev/robots.txt"})                    # فقط robots.txt (چند بار تلاش)؛ هیچ صفحهٔ دیگری نه


class SourceTests(SimpleTestCase):
    PAGE = ('<div><p class="x">How <!-- -->Hero<!-- --> is used: the demo&#x27;s code.</p><p class="font-mono">Usage.tsx</p><pre class="p"><code>'
            '<span>import</span> { Hero } from &quot;@/components/ui/hero-one&quot;\n<span>export default</span> function Demo() { return &lt;Hero title=&quot;Hi&quot; /&gt; }</code></pre></div>')

    def test_demo_is_read_from_the_public_page_only(self):
        d = SRC.parse_demo(self.PAGE)
        self.assertEqual(d["file"], "Usage.tsx")
        self.assertIn('<Hero title="Hi" />', d["code"])
        self.assertEqual(d["imports"], ["@/components/ui/hero-one"])
        self.assertEqual(SRC.parse_demo("<pre>just text</pre>"), {})
        self.assertEqual(SRC.parse_demo(""), {})

    def make_repo(self, lic="MIT License\n\nPermission is hereby granted, free of charge, to any person\nCopyright (c) 2025 Acme Co\n"):
        d = Path(tempfile.mkdtemp(prefix="c21-repo-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "registry" / "acme").mkdir(parents=True)
        (d / "registry" / "acme" / "hero-one.tsx").write_text("export function HeroOne(){ return <section><h1>Hi</h1></section> }", encoding="utf-8")
        (d / "apps" / "web" / "demo").mkdir(parents=True)
        (d / "apps" / "web" / "demo" / "hero-one.tsx").write_text("demo", encoding="utf-8")
        (d / "node_modules" / "x").mkdir(parents=True)
        (d / "node_modules" / "x" / "hero-one.tsx").write_text("no", encoding="utf-8")
        if lic:
            (d / "LICENSE").write_text(lic, encoding="utf-8")
        return d

    def test_repo_lookup_prefers_the_registry_file_and_skips_demos_and_node_modules(self):
        repo = self.make_repo()
        idx = SRC.index_repo(repo)
        self.assertEqual(sorted(idx["hero-one"]), ["apps/web/demo/hero-one.tsx", "registry/acme/hero-one.tsx"])
        self.assertEqual(SRC.find_component(idx, "hero-one"), "registry/acme/hero-one.tsx")
        self.assertEqual(SRC.find_component(idx, "missing"), "")
        self.assertEqual(SRC.find_component(idx, "other", ["@/components/ui/hero-one"]), "registry/acme/hero-one.tsx")

    def test_repo_licence_detection(self):
        self.assertEqual(SRC.detect_license(self.make_repo())["spdx"], "MIT")
        self.assertIn("Acme Co", SRC.detect_license(self.make_repo())["copyright"])
        self.assertEqual(SRC.detect_license(self.make_repo("Apache License\nVersion 2.0, January 2004"))["spdx"], "Apache-2.0")
        self.assertEqual(SRC.detect_license(self.make_repo("All rights reserved. Do not copy."))["spdx"], "")
        self.assertEqual(SRC.detect_license(self.make_repo(lic=""))["spdx"], "")
        self.assertTrue(SRC.is_permissive_spdx("MIT"))
        self.assertFalse(SRC.is_permissive_spdx(""))
        self.assertFalse(SRC.is_permissive_spdx("GPL-3.0"))

    def test_bundle_maps_the_demo_import_to_the_found_file(self):
        repo = self.make_repo()
        demo = SRC.parse_demo(self.PAGE)
        b = SRC.bundle_from_repo(repo, "registry/acme/hero-one.tsx", "hero-one", demo, license_info={"spdx": "MIT", "copyright": "c", "file": "LICENSE"}, repo_url="https://github.com/a/b", commit="abc")
        self.assertEqual(b["aliases"], {"@/components/ui/hero-one": str(repo / "registry/acme/hero-one.tsx")})
        self.assertEqual(b["source"]["license"], "MIT")
        self.assertEqual(b["source"]["commit"], "abc")
        self.assertTrue(b["source"]["demo"])
        self.assertIn(str(repo), b["roots"][0] if b["roots"] else str(repo))
        fb = SRC.bundle_from_repo(repo, "registry/acme/hero-one.tsx", "hero-one", {}, license_info={}, repo_url="u", commit="c")
        self.assertIn("HeroOne", fb["entry"]["code"])                                          # نمونه نبود: خودِ قطعه بی‌props
        self.assertFalse(fb["source"]["demo"])


class SanitizeTests(SimpleTestCase):
    def test_dangerous_markup_is_removed_and_slots_are_made(self):
        html = ('<div id="c21-root"><section class="a b" onclick="x()" style="color:red;background:url(//evil/x.png);position:fixed;left:3px">'
                '<script>alert(1)</script><iframe src="//e"></iframe><h2>Hello <b>world</b>!</h2><a href="javascript:alert(1)" class="btn">Go</a>'
                '<img src="https://cdn.example/x.png" alt="A cat" class="rounded" width="32"><video src="x"></video><p>Hello</p><p>Hello</p>'
                '<form action="/post"><input type="email" name="e" value="x"><button>Send</button></form></section></div>')
        out = CV.sanitize(html, "nbc21-xabc")
        t = out["template"]
        for bad in ("<script", "alert(", "onclick", "<iframe", "javascript:", "evil", "<video", "action=", "name=", "href=\"https", "src=\"https"):
            self.assertNotIn(bad, t, bad)
        self.assertIn("{{T0}}", t)
        self.assertEqual(out["texts"][:2], ["Hello", "world"])                                  # متنِ آمیخته: «Hello» و «world» شکلِ جدا
        self.assertEqual(out["texts"].count("Hello"), 1)                                         # متنِ تکراری یک شکاف می‌گیرد
        self.assertEqual(out["images"], [{"alt": "A cat"}])
        self.assertEqual(out["links"], ["#"])
        self.assertIn('data-nbi="0"', t)
        self.assertIn('data-nbl="0"', t)
        self.assertIn("inset-inline-start:3px", t)                                              # left ⇒ منطقی
        self.assertNotIn("url(", t)
        self.assertIn('type="button"', t)
        self.assertIn("readonly", t)
        self.assertNotIn("<form", t)
        self.assertIn("dropped <video>", out["warnings"])

    def test_only_the_dangerous_class_token_is_dropped(self):
        t = CV.sanitize("<div id='c21-root'><p class=\"flex p-4 bg-[url(https://evil/x.png)] text-sm\">Hi</p></div>", "nbc21-x")["template"]
        self.assertIn('class="flex p-4 text-sm"', t)
        self.assertNotIn("evil", t)

    def test_svg_is_kept_with_scoped_ids_and_no_external_refs(self):
        html = ('<div id="c21-root"><svg viewBox="0 0 24 24" fill="none" onload="x()"><defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
                '<path d="M0 0h24" fill="url(#g)" stroke="currentColor"/><use href="//evil/x.svg#a"/><foreignObject><p>x</p></foreignObject></svg></div>')
        t = CV.sanitize(html, "nbc21-xabc")["template"]
        self.assertIn("<svg", t)
        self.assertIn('fill="url(#xabc-g)"', t)
        self.assertIn('id="xabc-g"', t)
        for bad in ("onload", "<use", "foreignObject", "evil"):
            self.assertNotIn(bad, t)

    def test_css_checks_and_limits(self):
        self.assertEqual(CV.check_css(".a{color:red}"), ".a{color:red}")
        for bad in ("@import 'x';.a{}", ".a{background:url(https://x/y.png)}", ".a{color:red", ".a{x:expression(1)}"):
            with self.assertRaises(CV.ConvertError):
                CV.check_css(bad)
        self.assertEqual(CV.check_css(".a{background:url(#g)}"), ".a{background:url(#g)}")
        self.assertEqual(CV.check_css(".a{scroll-behavior:smooth}"), ".a{scroll-behavior:smooth}")           # «behavior» ِ ویژگیِ مجاز، نه «behavior:» ِ IE
        with self.assertRaises(CV.ConvertError):
            CV.check_css("." + "a" * (CV.MAX_CSS + 5))
        self.assertTrue(CV.key_for("a/b").startswith("x") and len(CV.key_for("a/b")) == 10)
        self.assertEqual(CV.scope_for("xabc"), "nbc21-xabc")

    def test_text_slot_limit_keeps_the_rest_static(self):
        html = "<div id='c21-root'>%s</div>" % "".join("<p>t%d</p>" % i for i in range(CV.MAX_TEXTS + 5))
        out = CV.sanitize(html, "nbc21-x")
        self.assertEqual(len(out["texts"]), CV.MAX_TEXTS)
        self.assertIn(">t%d<" % (CV.MAX_TEXTS + 1), out["template"])


class FakeNode:
    """subprocess.run ِ ساختگی برای convert.mjs: HTML/CSS ثابت می‌نویسد."""

    def __init__(self, html="<div id=\"c21-root\"><section class=\"flex p-4\"><h2>Big title</h2><p>Some text</p><a href=\"/x\" class=\"btn\">Go</a><img src=\"https://x/y.png\" alt=\"pic\" class=\"w-full\"></section></div>",
                 css=".nbc21-x .flex{display:flex}.nbc21-x .p-4{padding:1rem}", ok=True, error="x"):
        self.html, self.css, self.ok, self.error, self.jobs = html, css, ok, error, []

    def __call__(self, cmd, **kw):
        job = json.loads(Path(cmd[-2]).read_text(encoding="utf-8"))
        self.jobs.append(job)
        out = {"ok": True, "html": self.html, "css": self.css.replace("nbc21-x", job["scope"]), "warnings": []} if self.ok else {"ok": False, "error": self.error}
        Path(cmd[-1]).write_text(json.dumps(out), encoding="utf-8")
        return mock.Mock(returncode=0, stderr="", stdout="")


class ConvertAndEmbedTests(DataDirMixin, Base):
    def convert(self, cid="acme/hero-one", node=None, **kw):
        node = node or FakeNode()
        rec = CV.convert_bundle(cid, {"entry": {"path": "Usage.tsx", "code": "export default () => null"}, "files": {}, "aliases": {"@/c": "/x"}, "roots": ["/r"],
                                      "source": {"kind": "upstream", "repo": "https://github.com/a/b", "license": "MIT"}}, meta={"title": "Hero One", "license": "mit", "author": "Acme", "library": "Acme UI",
                                                                                                                              "cats": ["hero"], **kw}, runner=node)
        CV.save_record(rec)
        return rec, node

    def test_convert_stores_a_scoped_record_and_passes_the_bundle_to_node(self):
        rec, node = self.convert()
        self.assertEqual(node.jobs[0]["scope"], rec["scope"])
        self.assertEqual(node.jobs[0]["aliases"], {"@/c": "/x"})
        self.assertEqual(node.jobs[0]["roots"], ["/r"])
        self.assertTrue(rec["css"].startswith(".%s " % rec["scope"]))
        self.assertEqual(rec["texts"], ["Big title", "Some text", "Go"])
        self.assertEqual(rec["images"], [{"alt": "pic"}])
        self.assertEqual(CV.load_index()["acme/hero-one"]["key"], rec["key"])
        self.assertEqual(CV.get_record(rec["key"])["license"], "mit")
        self.assertIsNone(CV.load_record("../../etc/passwd"))
        self.assertTrue(CV.remove_record("acme/hero-one"))
        self.assertIsNone(CV.load_record(rec["key"]))

    def test_untrusted_code_runs_in_a_cage_clean_env_no_network_and_no_secrets(self):
        seen = {}

        def runner(cmd, **kw):
            seen.update(cmd=cmd, **kw)
            Path(cmd[-1]).write_text(json.dumps({"ok": True, "html": "<div id=\"c21-root\"><p>x</p></div>", "css": ".nbc21-x p{margin:0}"}), encoding="utf-8")
            return mock.Mock(returncode=0, stderr="")
        with mock.patch.dict(os.environ, {"SECRET_KEY": "s3cret", "API_KEY_21ST": "k", "AWS_SECRET_ACCESS_KEY": "z"}):
            CV.run_node({"scope": "nbc21-x"}, runner=runner)
        self.assertEqual(set(seen["env"]), set(CV.SAFE_ENV))
        self.assertNotIn("s3cret", json.dumps(seen["env"]))
        self.assertTrue(seen["cmd"][-3].endswith("convert.mjs"))
        self.assertEqual(os.path.basename(seen["cmd"][-3]), "convert.mjs")
        with mock.patch.object(CV, "_net_isolation", return_value=["/usr/bin/unshare", "-n"]), mock.patch.object(CV.os, "geteuid", return_value=1000):
            CV.run_node({"scope": "nbc21-x"}, runner=runner)
        self.assertEqual(seen["cmd"][:2], ["/usr/bin/unshare", "-n"])                              # بی‌شبکه
        self.assertNotIn("preexec_fn", seen)                                                       # غیرِ root: کاری با کاربر نمی‌کند
        with mock.patch.object(CV.os, "geteuid", return_value=0), mock.patch.object(CV.os, "chown") as chown, mock.patch.object(CV, "_net_isolation", return_value=[]):
            CV.run_node({"scope": "nbc21-x"}, runner=runner)
        self.assertIs(seen["preexec_fn"], CV._drop_privileges)                                     # کاربرِ nobody
        self.assertEqual(chown.call_args[0][1:], (65534, 65534))
        with mock.patch.object(CV.os, "geteuid", return_value=0), mock.patch.object(CV.os, "chown"), mock.patch.object(CV, "_net_isolation", return_value=["/usr/bin/unshare", "-n", "-S", "65534", "-G", "65534"]):
            seen.pop("preexec_fn", None)
            CV.run_node({"scope": "nbc21-x"}, runner=runner)
        self.assertNotIn("preexec_fn", seen)                                                       # unshare خودش nobody می‌شود
        with mock.patch.dict(os.environ, {"NM_C21_RUN_AS": "root"}), mock.patch.object(CV.os, "geteuid", return_value=0):
            self.assertFalse(CV._drop_ok())

    def test_conversion_errors_are_reported_not_stored(self):
        for node in (FakeNode(ok=False, error="cannot resolve @/x"), FakeNode(html="<div id=\"c21-root\"></div>"), FakeNode(css=".a{background:url(//e/x.png)}")):
            with self.assertRaises(CV.ConvertError):
                self.convert(node=node)
        self.assertEqual(CV.load_index(), {})
        with self.assertRaises(CV.ConvertError):                                                  # بی‌جعبه‌ابزار و بی‌runner ِ تزریقی
            with mock.patch.object(CV, "TOOLCHAIN", Path("/nonexistent")):
                CV.run_node({})

    def render_block(self, rec, canvas=False, **props):
        base = EM.default_props(rec)
        base.update(props)
        doc = clean_doc({"v": 1, "blocks": [new_block("c21", **base)]}, "page")
        return R.render_doc(doc, R.Ctx(canvas=canvas, theme={})), doc

    def test_block_renders_text_escaped_links_images_css_once_and_edit_marks_only_on_canvas(self):
        rec, _ = self.convert()
        out, doc = self.render_block(rec)
        self.assertIn('class="%s"' % rec["scope"], out.html)
        self.assertIn("Big title", out.html)
        self.assertNotIn("data-nb-edit", out.html)                                                 # فقط روی بوم
        self.assertNotIn("data-nbt", out.html)
        self.assertNotIn("<img", out.html)                                                         # تصویرِ انتخاب‌نشده در سایتِ نهایی نمی‌آید
        self.assertIn('href="#"', out.html)
        self.assertIn(rec["css"], out.css)
        self.assertEqual(out.css.count(rec["css"]), 1)
        kinds = {w["kind"] for w in out.warnings}
        self.assertIn("media", kinds)
        self.assertIn("sample", kinds)                                                             # متن‌های نمونه هنوز عوض نشده
        canvas, _ = self.render_block(rec, canvas=True)
        self.assertIn('data-nb-edit="texts.0.v"', canvas.html)
        evil, _ = self.render_block(rec, texts=[{"v": "<script>alert(1)</script> {{ x }} {% y %}"}, {"v": "ok"}, {"v": "Go"}], links=[{"u": "javascript:alert(1)"}])
        self.assertNotIn("<script", evil.html)
        self.assertNotIn("alert(1)</", evil.html)
        self.assertNotIn("{{ x }}", evil.html)
        self.assertNotIn("javascript:", evil.html)
        self.assertIn("<!-- 21st.dev: acme/hero-one | MIT | https://github.com/a/b", out.html)           # اعلامِ مبدأ و مجوز در خروجی
        self.assertNotIn("-->", EM.attribution({"id": "a/b", "license": "x --> <script>", "source": {}}).replace("<!-- 21st.dev: ", "").rsplit(" -->", 1)[0])
        self.assertEqual(EM.used_in_html(out.html), [rec["key"]])
        self.assertEqual(EM.used_in_html("<div class='nbc21-x123456789'>"), ["x123456789"])
        self.assertEqual(EM.used_in_html("<div class='nbc-hero'>"), [])

    def test_deleted_rows_render_nothing_and_unknown_ref_is_blank(self):
        rec, _ = self.convert()
        out, _ = self.render_block(rec, texts=[{"v": "Only"}])
        self.assertIn("Only", out.html)
        self.assertNotIn("Some text", out.html)
        ghost, _ = self.render_block(rec, ref="x000000000")
        self.assertEqual(ghost.html.strip(), "")
        gc, _ = self.render_block(rec, canvas=True, ref="x000000000")
        self.assertIn("نیست", gc.html)

    def test_clean_doc_keeps_the_rows_and_drops_junk(self):
        rec, _ = self.convert()
        b = new_block("c21", ref=rec["key"], texts=[{"v": "a", "evil": "x"}] * 3, links=[{"u": "javascript:1"}], images=[{"src": "https://x/y.png", "alt": "z"}], other="x")
        doc = clean_doc({"v": 1, "blocks": [b]}, "page")
        p = doc["blocks"][0]["props"]
        self.assertEqual(p["texts"][0], {"v": "a"})
        self.assertNotIn("other", p)
        self.assertNotIn("javascript", json.dumps(p["links"]))
        self.assertEqual(clean_doc({"v": 1, "blocks": [new_block("c21", texts=[{"v": "t"}] * 90)]}, "page")["blocks"][0]["props"]["texts"].__len__(), 60)

    def test_ai_roundtrip_keeps_the_c21_block_and_merges_a_text_edit(self):
        from apps.projects.builder import importer
        rec, _ = self.convert()
        doc = clean_doc({"v": 1, "blocks": [new_block("c21", **EM.default_props(rec))]}, "page")
        ctx = self.ctx()
        out = R.render_doc(doc, ctx)
        same, rep = importer.import_html(out.html, R.page_css(out.css), doc, ctx, "page")
        self.assertEqual(same["blocks"][0]["type"], "c21")
        self.assertEqual(same["blocks"][0]["props"]["ref"], rec["key"])
        self.assertEqual(rep["custom"], 0)
        changed = out.html.replace(">Big title<", ">عنوانِ تازه<", 1)
        self.assertNotEqual(changed, out.html)
        new, rep = importer.import_html(changed, R.page_css(out.css), doc, ctx, "page")
        self.assertEqual(new["blocks"][0]["type"], "c21")
        self.assertEqual(new["blocks"][0]["props"]["texts"][0]["v"], "عنوانِ تازه")
        self.assertEqual(rep["custom"], 0)

    def test_catalog_lists_c21_as_a_hidden_fixed_block(self):
        from apps.projects.builder.catalog import BLOCKS, catalog_json
        spec = BLOCKS["c21"]
        self.assertTrue(spec["hidden"] and spec["root"])
        self.assertTrue(all(f.get("fixed") for f in spec["fields"] if f["kind"] == "items"))
        self.assertTrue([b for b in catalog_json()["blocks"] if b["type"] == "c21"][0]["hidden"])

    def test_preview_and_block_api_use_the_project_theme_and_refuse_rtl_failures(self):
        rec, _ = self.convert()
        p = self.project("c21-api")
        base = "/api/v1/studio/projects/%s/builder/c21/%s/" % (p.slug, rec["key"])
        d = self.c.get(base + "preview/", {"style": "ux-vaporwave"}).json()
        self.assertIn(rec["scope"], d["html"])
        self.assertIn("--st-card-bg", d["base_css"])
        self.assertEqual(d["license"], "mit")
        blk = self.c.get(base + "block/").json()["block"]
        self.assertEqual(blk["type"], "c21")
        self.assertEqual(blk["props"]["ref"], rec["key"])
        self.assertEqual(len(blk["props"]["texts"]), 3)
        self.assertEqual(self.c.get("/api/v1/studio/projects/%s/builder/c21/x000000000/block/" % p.slug).status_code, 404)
        rec["rtl"] = {"status": "fail"}
        CV.save_record(rec)
        self.assertEqual(self.c.get(base + "block/").status_code, 409)

    def test_catalog_api_flags_insertable_and_serves_the_preview_image(self):
        rec, _ = self.convert()
        rows = [{"id": "acme/hero-one", "title": "Hero One", "detail": True, "usable": True, "license": "mit", "cats": ["hero"], "preview": True, "conv": {"state": "ok", "key": rec["key"]}},
                {"id": "acme/other", "title": "Other", "detail": True, "usable": False, "license": "no-license", "cats": ["hero"]}]
        c21st.save(rows)
        CR.make_preview(png_bytes(), CR.preview_path("acme/hero-one"))
        d = self.c.get("/api/v1/studio/c21st/?insertable=1").json()
        self.assertEqual([i["id"] for i in d["items"]], ["acme/hero-one"])
        self.assertTrue(d["items"][0]["insertable"] and d["items"][0]["preview"])
        self.assertEqual(d["items"][0]["conv_key"], rec["key"])
        self.assertEqual(d["insertable"], 1)
        both = self.c.get("/api/v1/studio/c21st/").json()
        self.assertEqual(both["total"], 2)
        self.assertEqual(both["items"][0]["id"], "acme/hero-one")                                 # قابلِ درج‌ها اول
        img = self.c.get("/api/v1/studio/c21st/image/acme/hero-one/")
        self.assertEqual((img.status_code, img["Content-Type"]), (200, "image/webp"))
        self.assertEqual(self.c.get("/api/v1/studio/c21st/image/acme/none/").status_code, 404)
        self.assertEqual(self.c.get("/api/v1/studio/c21st/image/..%2F..%2Fx/y/").status_code, 404)
        st = self.c.get("/api/v1/studio/c21st/pipeline/").json()
        self.assertEqual(st["pipeline"]["converted"], 1)
        with mock.patch.object(CV, "toolchain_ready", return_value=False):
            self.assertEqual(self.c.post("/api/v1/studio/c21st/convert/").status_code, 409)


class PipelineTests(DataDirMixin, SimpleTestCase):
    HERO = "export function HeroOne(){ return <section className='p-4'><h1>Hi</h1></section> }"

    def git_runner(self, lic="MIT License\nPermission is hereby granted, free of charge,\nCopyright (c) 2025 Acme"):
        outer = self

        def run(cmd, **kw):
            args = cmd[1:]
            if args[0] == "clone":
                dest = Path(args[-1])
                (dest / "registry").mkdir(parents=True)
                (dest / "registry" / "hero-one.tsx").write_text(outer.HERO, encoding="utf-8")
                if lic:
                    (dest / "LICENSE").write_text(lic, encoding="utf-8")
            return mock.Mock(returncode=0, stdout="deadbeef\n", stderr="")
        return run

    def seed(self):
        c21st.save([{"id": "acme/hero-one", "title": "Hero One", "detail": True, "usable": True, "license": "mit", "cats": ["hero"], "library_id": "acme/acme-ui"},
                    {"id": "acme/no-file", "title": "No File", "detail": True, "usable": True, "license": "mit", "cats": [], "library_id": "acme/acme-ui"},
                    {"id": "acme/closed", "title": "Closed", "detail": True, "usable": False, "license": "no-license", "cats": [], "library_id": "acme/acme-ui"}])
        CR.save_libs({"acme/acme-ui": {"id": "acme/acme-ui", "github": "https://github.com/acme/acme-ui", "detail": True, "component_ids": ["acme/hero-one", "acme/no-file", "acme/closed"]}})

    def runner_for(self, node, git):
        def runner(cmd, **kw):
            return git(cmd, **kw) if cmd[0] == "git" else node(cmd, **kw)
        return runner

    def page(self):
        return {"/@acme/components/hero-one": SourceTests.PAGE}

    def test_licensed_component_with_public_source_is_converted_others_are_not(self):
        self.seed()
        node = FakeNode()
        s = session(self.page())
        st = PL.run(session=s, runner=self.runner_for(node, self.git_runner()), rtl=False)
        self.assertEqual((st["converted"], st["no_source"]), (1, 1))
        rows = {r["id"]: r for r in c21st.load()}
        self.assertEqual(rows["acme/hero-one"]["conv"]["state"], "ok")
        self.assertEqual(rows["acme/no-file"]["conv"]["state"], "no-source")
        self.assertNotIn("conv", rows["acme/closed"])                                              # مجوزِ بسته هرگز تبدیل نمی‌شود
        rec = CV.get_record(rows["acme/hero-one"]["conv"]["key"])
        self.assertEqual(rec["source"]["license"], "MIT")
        self.assertEqual(rec["source"]["commit"], "deadbeef")
        self.assertEqual(node.jobs[0]["aliases"]["@/components/ui/hero-one"].endswith("registry/hero-one.tsx"), True)
        self.assertFalse(list(PL.repos_dir().iterdir()))                                           # مخزن پاک شد
        self.assertEqual([u for u in s.fetch.calls if "/r/" in u or "/api/" in u], [])
        self.assertTrue(ND.load_demo("acme/hero-one")["code"].startswith("import"))                # نمونه ذخیره شد
        again = PL.run(session=s, runner=self.runner_for(node, self.git_runner()), rtl=False)
        self.assertEqual((again["converted"], again["failed"]), (0, 0))                            # تمام‌شده‌ها دوباره کار نمی‌شوند

    def test_rtl_verdict_reaches_the_catalogue_row_and_a_failure_hides_the_component(self):
        self.seed()
        node = FakeNode()
        key = CV.key_for("acme/hero-one")

        def fake_apply(keys, **kw):
            rec = CV.load_record(keys[0])
            rec["rtl"] = {"status": "fail"}
            CV.save_record(rec)
            return {keys[0]: {"status": "fail"}}
        with mock.patch("apps.projects.builder.c21_rtl.apply", fake_apply):
            PL.run(session=session(self.page()), runner=self.runner_for(node, self.git_runner()), rtl=True)
        row = {r["id"]: r for r in c21st.load()}["acme/hero-one"]
        self.assertEqual((row["conv"]["state"], row["conv"]["key"], row["conv"]["rtl"]), ("ok", key, "fail"))
        self.assertFalse(c21st.insertable(row))                                                    # سرریز در راست‌به‌چپ ⇒ از «قابلِ درج» بیرون

    def test_repo_with_non_open_licence_blocks_every_component(self):
        self.seed()
        st = PL.run(session=session(self.page()), runner=self.runner_for(FakeNode(), self.git_runner(lic="All rights reserved")), rtl=False)
        self.assertEqual(st["converted"], 0)
        rows = {r["id"]: r for r in c21st.load()}
        self.assertEqual(rows["acme/hero-one"]["conv"]["state"], "license")
        self.assertEqual(CV.load_index(), {})

    def test_failures_are_recorded_and_retried_only_after_a_week(self):
        self.seed()
        st = PL.run(session=session(self.page()), runner=self.runner_for(FakeNode(ok=False, error="cannot resolve @/x"), self.git_runner()), rtl=False)
        self.assertEqual(st["failed"], 1)
        rows = {r["id"]: r for r in c21st.load()}
        self.assertIn("cannot resolve", rows["acme/hero-one"]["conv"]["error"])
        self.assertEqual(PL._candidates({r["id"]: r for r in c21st.load()}, CR.load_libs()["acme/acme-ui"], time.time()), [])
        later = time.time() + PL.RETRY_FAILED_AFTER_S + 10
        self.assertEqual([r["id"] for r in PL._candidates({r["id"]: r for r in c21st.load()}, CR.load_libs()["acme/acme-ui"], later)], ["acme/hero-one"])

    def test_clone_failure_is_recorded_and_bad_urls_are_refused(self):
        self.seed()
        bad = mock.Mock(returncode=128, stdout="", stderr="fatal: repository not found")
        st = PL.run(session=session(self.page()), runner=self.runner_for(FakeNode(), lambda cmd, **kw: bad), rtl=False)
        self.assertEqual(st["converted"], 0)
        self.assertIn("clone", {r["id"]: r for r in c21st.load()}["acme/hero-one"]["conv"]["error"])
        with self.assertRaises(CV.ConvertError):
            PL.clone_repo("https://evil.example/a/b", Path(self.tmp) / "x")
        with self.assertRaises(CV.ConvertError):
            PL.clone_repo("https://github.com/a/b;rm -rf", Path(self.tmp) / "y")

    def test_pipeline_waits_while_the_crawl_is_writing_the_catalog(self):
        self.seed()
        c21st._save_state({"running": True, "running_at": time.time()})
        self.assertEqual(PL.run(session=session({}), runner=self.runner_for(FakeNode(), self.git_runner()), rtl=False)["deferred"], "crawl-running")
        c21st._save_state({"running": False})
        PL._save({"running": True, "running_at": time.time()})
        self.assertEqual(CR.run_turn(session=session({}), max_seconds=1)["deferred"], "pipeline-running")

    def test_api_code_path_converts_after_the_owner_fetched_the_code(self):
        c21st.save([{"id": "acme/hero-one", "title": "Hero One", "detail": True, "usable": True, "license": "mit", "cats": [], "author_name": "Acme", "library": "x"}])
        (c21st.root() / "code").mkdir(parents=True)
        (c21st.root() / "code" / "acme__hero-one.json").write_text(json.dumps({"files": [{"path": "hero-one.tsx", "content": self.HERO}]}), encoding="utf-8")
        node = FakeNode()
        rec = PL.convert_from_api_code("acme/hero-one", session=session(self.page()), runner=node)
        self.assertEqual(rec["source"]["kind"], "api")
        self.assertIn("@/components/ui/hero-one", node.jobs[0]["files"])
        with self.assertRaises(CV.ConvertError):
            PL.convert_from_api_code("acme/none", runner=node)


class NodeJobTests(DataDirMixin, Base):
    def test_payload_robots_and_ingest_of_node_results(self):
        c21st.save([{"id": "acme/hero-one", "title": "Hero One", "detail": False, "cats": []}])
        pay = ND.build_payload(["acme/hero-one"], ROBOTS_21ST)
        self.assertEqual(pay["urls"], ["https://21st.dev/@acme/components/hero-one"])
        self.assertEqual(pay["want"], "md,page")
        self.assertGreaterEqual(pay["delay_s"], 1.0)
        self.assertEqual(ND.pick_ids(5), ["acme/hero-one"])
        got = ND.ingest_results([{"id": "acme/hero-one", "ok": True, "md": md("Hero One", "mit"), "page": {"demo": {"file": "Usage.tsx", "code": "import x from '@/a'\nexport default 1"}}},
                                 {"id": "bad id!", "ok": True}, {"id": "acme/x", "ok": False, "error": "robots"}])
        self.assertEqual((got["details"], got["demos"], got["failed"]), (1, 1, 1))
        row = c21st.by_id("acme/hero-one")
        self.assertTrue(row["detail"] and row["usable"])
        self.assertEqual(row["library_id"], "acme/acme-ui")
        self.assertEqual(ND.load_demo("acme/hero-one")["imports"], ["@/a"])
        self.assertEqual(ND.pick_ids(5), [])                                                       # حالا چیزی برای گرفتن نیست (مجوز آزاد، ولی تبدیل‌شده/نمونه دارد)... یا فقط تبدیل مانده
        self.assertEqual(ND.ingest_results(None)["rows"], 0)

    def test_enqueue_is_durable_routes_only_to_agents_that_advertise_the_kind_and_collect_ingests(self):
        from apps.compute import services as SV
        from apps.compute.models import ComputeJob, ComputeNode
        c21st.save([{"id": "acme/hero-one", "title": "Hero One", "detail": False, "cats": []}])
        old = ComputeNode.objects.create(name="old-node", capabilities={"agent": "2.10", "kinds": ["echo"], "comfyui": True})
        new = ComputeNode.objects.create(name="new-node", capabilities={"agent": "2.27", "kinds": ["echo", ND.KIND], "comfyui": True})
        job = ND.enqueue_batch()                                                                   # گرهٔ خاموش هم کافی است: کار در صفِ ماندگار می‌ماند
        self.assertEqual((job.kind, job.state), (ND.KIND, ComputeJob.State.QUEUED))
        self.assertEqual(SV.capability_for(ND.KIND), "any")
        self.assertFalse(SV.kind_unsupported(new, job))
        self.assertTrue(SV.kind_unsupported(old, job))                                             # عاملِ قدیمی هرگز کارِ ناشناخته نمی‌گیرد؛ کار در صفِ ماندگار می‌ماند
        self.assertTrue(SV._kinds_q(new))
        self.assertEqual(ComputeJob.objects.filter(SV._kinds_q(old), kind=ND.KIND).count(), 1)     # از نظرِ پیشوند به همه می‌رسد ولی kind_unsupported نگهش می‌دارد
        self.assertIsNone(SV.claim(old))
        self.assertEqual(SV.claim(new).uid, job.uid)
        self.assertEqual(ND.state()["pending"][0]["uid"], str(job.uid))
        job.refresh_from_db()
        out = SV.output_path(job, "results.json")
        out.write_text(json.dumps({"results": [{"id": "acme/hero-one", "ok": True, "md": md("Hero One", "mit"), "page": {"demo": {"file": "Usage.tsx", "code": "import x from '@/a'\nexport default 1"}}}]}), encoding="utf-8")
        job.state = ComputeJob.State.COMPLETED
        job.save()
        self.assertEqual(ND.collect()["details"], 1)
        self.assertEqual(ND.state()["pending"], [])
        self.assertTrue(c21st.by_id("acme/hero-one")["usable"])
        self.assertIsNone(ND.enqueue_batch())                                                      # دیگر چیزی برای خزش نیست

    def test_refresh_hands_the_crawl_to_the_node_when_the_server_cannot_reach_21st_and_collect_keeps_it_filled(self):
        """سرور به 21st.dev نمی‌رسد (robots.txt خوانده نشد) ⇒ کارِ گره در صفِ ماندگار؛ نتیجه که جمع شد دستهٔ بعدی؛ سرورِ سالم ⇒ هیچ کاری به گره داده نمی‌شود."""
        from apps.compute.models import ComputeJob, ComputeNode
        from apps.projects import tasks as T
        c21st.save([{"id": "acme/hero-%d" % i, "title": "Hero %d" % i, "detail": False, "cats": []} for i in range(120)])
        ComputeNode.objects.create(name="gpu", capabilities={"agent": "2.28", "kinds": ["echo", ND.KIND]})
        jobs = lambda: ComputeJob.objects.filter(kind=ND.KIND).count()  # noqa: E731
        with mock.patch.object(CR, "run_turn", return_value={"blocked": False, "robots_ok": True, "finished": False}), mock.patch.object(T.c21st_refresh, "apply_async") as again:
            T.c21st_refresh(force=True)
        self.assertEqual(jobs(), 0)                                                                # سرورِ سالم: خودش می‌خزد
        self.assertEqual(again.call_args.kwargs["countdown"], 30)
        with mock.patch.object(CR, "run_turn", return_value={"blocked": False, "robots_ok": False, "finished": False}), mock.patch.object(T.c21st_refresh, "apply_async") as again:
            T.c21st_refresh(force=True)
        self.assertEqual(jobs(), 1)                                                                # robots.txt خوانده نشد ⇒ کارِ گره
        self.assertEqual(again.call_args.kwargs["countdown"], 600)                                 # و سرور ده دقیقه بعد دوباره امتحان می‌کند
        with mock.patch.object(CR, "run_turn", return_value={"blocked": True, "robots_ok": True, "finished": False}), mock.patch.object(T.c21st_refresh, "apply_async") as again:
            T.c21st_refresh(force=True)
        self.assertEqual(jobs(), 2)                                                                # ۴۰۳ هم همان
        again.assert_not_called()
        # collect: مسیرِ گره فعال ⇒ پر نگه می‌دارد (سقفِ ۴ کارِ منتظر)؛ سرورِ سالم ⇒ پر نمی‌کند
        c21st._save_state({"robots_ok": False, "finished": False})
        T.c21_node_collect()
        T.c21_node_collect()
        T.c21_node_collect()
        self.assertEqual(jobs(), ND.MAX_PENDING)
        T.c21_node_collect()
        self.assertEqual(jobs(), ND.MAX_PENDING)
        ComputeJob.objects.filter(kind=ND.KIND).delete()
        st = ND.state()
        st["pending"] = []
        ND._save(st)
        c21st._save_state({"robots_ok": True, "blocked": False, "finished": False})
        T.c21_node_collect()
        self.assertEqual(jobs(), 0)
        c21st._save_state({"robots_ok": False, "finished": True})
        T.c21_node_collect()
        self.assertEqual(jobs(), 0)

    def test_selftest_passes_only_with_real_page_data(self):
        from apps.compute.selftests import crawl21 as ST
        good = {"browser": "msedge", "results": [{"id": ST.PROBE, "ok": True, "md": "# Marquee\n- License: mit\n", "page": {"demo": {"code": "import { cn } from 'x'"}}}]}
        self.assertTrue(ST.judge(good)[0])
        for bad in (None, {"results": []}, {"results": [{"id": ST.PROBE, "ok": False, "error": "robots"}]},
                    {"results": [{"id": ST.PROBE, "ok": True, "md": "nope", "page": {}}]}, {"results": [{"id": ST.PROBE, "ok": True, "md": "# M\nLicense: mit", "page": {"demo": {"code": "text"}}}]}):
            self.assertFalse(ST.judge(bad)[0])
        spec = ST.build(None)
        self.assertEqual(spec.kind, "crawl21.run")
        self.assertEqual(spec.payload["ids"], [ST.PROBE])
        node = type("N", (), {"capabilities": {"kinds": ["echo"]}})()
        self.assertFalse(ST._available(node)[0])
        node.capabilities = {"kinds": ["crawl21.run"]}
        self.assertTrue(ST._available(node)[0])
        from apps.compute import selftests as REG
        t = REG.load_all()["crawl21"]
        self.assertEqual(t.needs_features, ("crawl21",))
        self.assertTrue(t.optional)


class AiC21Tests(DataDirMixin, Base):
    def test_converted_components_reach_the_model_few_and_bounded_and_css_is_attached(self):
        node = FakeNode()
        recs = []
        for i, (cid, title) in enumerate((("acme/hero-one", "Hero One"), ("acme/price-table", "Price Table"), ("acme/third", "Third Thing"), ("acme/fourth", "Fourth Thing"))):
            rec = CV.convert_bundle(cid, {"entry": {"path": "u.tsx", "code": "x"}, "files": {}, "roots": [], "source": {}}, meta={"title": title, "license": "mit", "cats": ["hero"] if i == 0 else ["pricing-section"]}, runner=node)
            CV.save_record(rec)
            recs.append(rec)
        p = ai_context.build("ux-vaporwave", "صفحهٔ فرود با hero و price", "home")
        self.assertLessEqual(len(p["c21"]), ai_context.MAX_C21)
        self.assertEqual(p["c21"][0]["id"], "acme/hero-one")
        self.assertEqual(p["c21"][0]["class"], recs[0]["scope"])
        self.assertIn("nbc21-", p["c21"][0]["html"])
        self.assertNotIn("{{T", p["c21"][0]["html"])
        self.assertLessEqual(len(json.dumps(p, ensure_ascii=False, separators=(",", ":"))), ai_context.MAX_CHARS)
        self.assertEqual(p["stats"]["c21"], len(p["c21"]))
        pinned = ai_context.build("", "", "home", refs21=["acme/fourth"])
        self.assertEqual(pinned["c21"][0]["id"], "acme/fourth")                                    # سنجاق‌شده اول
        self.assertNotIn("inspiration", pinned)                                                    # قطعهٔ تبدیل‌شده «الهام» نیست؛ HTML آماده است
        css = ai_context.attach_css(p["c21"][0]["html"], "body{}")
        self.assertIn(recs[0]["css"], css)
        self.assertEqual(ai_context.attach_css(p["c21"][0]["html"], css), css)                     # دوبار نمی‌چسبد
        small = ai_context.build("ux-vaporwave", "hero price", "home", max_chars=2500)
        self.assertLessEqual(len(json.dumps(small, ensure_ascii=False, separators=(",", ":"))), 2500)

    def test_without_converted_components_the_prompt_is_unchanged(self):
        p = ai_context.build("ux-vaporwave", "hero", "home")
        self.assertNotIn("c21", p)
        self.assertEqual(p["stats"]["c21"], 0)


@skipUnless(os.path.isdir("/opt/nm-c21/node_modules/esbuild"), "جعبه‌ابزارِ /opt/nm-c21 نصب نیست")
class RealToolchainTests(DataDirMixin, Base):
    """همان convert.mjs ِ واقعی (esbuild + Tailwind v4 + postcss) روی یک قطعهٔ کوچک: بی‌مرورگر، بی‌اینترنت.
    (پوشهٔ موقتِ آزمون 0700 ِ root است و کاربرِ nobody به آن نمی‌رسد؛ پس این‌جا بدونِ تغییرِ کاربر؛ قفسِ کامل را sandbox_try / آزمونِ بالا می‌سنجد.)"""

    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"NM_C21_RUN_AS": "root"})
        p.start()
        self.addCleanup(p.stop)
    DEMO = ("import { Button } from '@/components/ui/button';\nimport { motion } from 'framer-motion';\nimport { Star } from 'lucide-react';\n"
            "export default function Demo() { return (<motion.section initial={{opacity:0}} animate={{opacity:1}} className=\"ml-4 pl-2 text-left flex gap-2 bg-primary text-primary-foreground "
            "left-0 absolute rounded-l-md p-4\"><h2 className=\"text-2xl font-bold\">Pricing</h2><Button className=\"mr-2\">Buy <Star /></Button><img src=\"https://x/y.png\" alt=\"logo\" "
            "className=\"size-8\" /></motion.section>); }")

    def test_real_conversion_is_scoped_rtl_logical_static_and_site_themed(self):
        rec = CV.convert_bundle("test/real", {"entry": {"path": "Demo.tsx", "code": self.DEMO}, "files": {}, "roots": [], "source": {"kind": "test"}}, meta={"title": "Real", "license": "mit"})
        css, tpl = rec["css"], rec["template"]
        self.assertIn(".%s " % rec["scope"], css)
        for physical in ("margin-left", "padding-left", "text-align:left", "border-top-left-radius", "left:0"):
            self.assertNotIn(physical, css.replace(" ", ""))
        for logical in ("margin-inline-start", "padding-inline-start", "text-align:start", "border-start-start-radius", "inset-inline-start"):
            self.assertIn(logical, css.replace(" ", ""))
        self.assertNotIn("opacity:0", tpl)                                                         # framer-motion ⇒ عنصرِ ساکن، نه پنهان
        self.assertNotIn("<script", tpl)
        self.assertIn("var(--brand", css)                                                          # رنگ‌های shadcn به پوستهٔ سایت وصل است
        self.assertNotIn("@import", css)
        self.assertNotIn("url(http", css)
        self.assertEqual(rec["images"], [{"alt": "logo"}])
        self.assertIn("Pricing", rec["texts"])
        self.assertIn("<svg", tpl)                                                                 # آیکونِ lucide
        self.assertLess(len(css), CV.MAX_CSS)

    def test_unresolvable_import_is_a_clear_error(self):
        with self.assertRaises(CV.ConvertError) as cm:
            CV.convert_bundle("test/bad", {"entry": {"path": "D.tsx", "code": "import X from '@/components/nothing-here';\nexport default () => <X/>"}, "files": {}, "roots": []})
        self.assertIn("cannot resolve", str(cm.exception))
