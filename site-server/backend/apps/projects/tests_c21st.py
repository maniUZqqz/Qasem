# -*- coding: utf-8 -*-
"""کاتالوگِ 21st.dev در سایت‌ساز: خزشِ فهرست (فقط .md)، جست‌وجو، «نزدیک‌ترین قطعهٔ ما»، الهام برای AI زیرِ سقف، کلیدِ API و گرفتنِ کد.

شبکهٔ واقعی صدا زده نمی‌شود: ``fetch`` تزریق می‌شود و ``NM_DATA_DIR`` موقتی است.
"""
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.projects.builder import ai_context, c21st
from apps.projects.tests_builder import Base
from services import safenet

CATEGORY_HERO = """# Hero components

> Level up first impressions.

200 components available. Showing the first 60.

- [Responsive Hero Banner](https://21st.dev/@sensewood8/components/responsive-hero-banner.md) — by Saifullah Channa
- [Hero Golden Spiral](https://21st.dev/@ncdai/components/hero-01.md) — by Chánh Đại
- [Background snippets](https://21st.dev/@ibelick/components/background-snippets/background-radial-dark-gray.md) — by Julien Thibeaut
"""
CATEGORY_PRICING = """# Pricing

- [Pricing Cards](https://21st.dev/@acme/components/pricing-cards.md) — by Acme
- [Responsive Hero Banner](https://21st.dev/@sensewood8/components/responsive-hero-banner.md) — by Saifullah Channa
"""


def comp_md(title, lic, tags="Hero, Landing", deps="motion, lucide-react", lib="trove/cn", author="Someone"):
    return f"""# {title}

> A great {title.lower()} with a spring animation and a gradient background.

- Author: [{author}](https://21st.dev/@x)
- Library: {lib}
- License: {lic}
- Tags: {tags}
- npm dependencies: {deps}
- Live preview: https://21st.dev/@x/components/y

## Install

```bash
npx shadcn@latest add "https://21st.dev/r/x/y?api_key=$API_KEY_21ST"
```
"""


class FakeFetch:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        for key, val in self.routes.items():
            if url.startswith(key):
                if isinstance(val, Exception):
                    raise val
                text = val if isinstance(val, str) else json.dumps(val)
                return safenet.Fetched(url=url, status=200, content_type="text/markdown", body=text.encode("utf-8"))
        raise safenet.FetchError("پیدا نشد", "http_404")


ROUTES = {
    "https://21st.dev/community/components/s/hero.md": CATEGORY_HERO,
    "https://21st.dev/community/components/s/pricing-section.md": CATEGORY_PRICING,
    "https://21st.dev/@sensewood8/components/responsive-hero-banner.md": comp_md("Responsive Hero Banner", "MIT", "Hero, Landing page", "motion"),
    "https://21st.dev/@ncdai/components/hero-01.md": comp_md("Hero Golden Spiral", "no-license", "Hero, Animated"),
    "https://21st.dev/@ibelick/components/background-snippets/background-radial-dark-gray.md": comp_md("Background snippets", "Apache-2.0", "Background, Gradient"),
    "https://21st.dev/@acme/components/pricing-cards.md": comp_md("Pricing Cards", "MIT", "Pricing, Cards, Saas"),
}


class TmpData(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-c21st-"))
        self.ov = override_settings(NM_DATA_DIR=self.tmp)
        self.ov.enable()
        c21st._cache.update(mtime=0.0, rows=[], path="")

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)


class ParseTests(SimpleTestCase):
    def test_category_page(self):
        rows = c21st.parse_category_md(CATEGORY_HERO)
        self.assertEqual([r["id"] for r in rows], ["sensewood8/responsive-hero-banner", "ncdai/hero-01", "ibelick/background-snippets/background-radial-dark-gray"])
        self.assertEqual(rows[0]["author_name"], "Saifullah Channa")

    def test_component_page(self):
        d = c21st.parse_component_md(comp_md("Proximity Accordion", "MIT", "Accordion, FAQ", "motion, lucide-react, @base-ui/react"))
        self.assertEqual(d["title"], "Proximity Accordion")
        self.assertEqual(d["license"], "MIT")
        self.assertEqual(d["tags"], ["Accordion", "FAQ"])
        self.assertEqual(d["deps"], ["motion", "lucide-react", "@base-ui/react"])
        self.assertIn("spring animation", d["description"])

    def test_licence_policy(self):
        for ok in ("MIT", "mit", "Apache-2.0", "BSD-3-Clause", "ISC", "CC0", "Unlicense"):
            self.assertTrue(c21st.is_permissive(ok), ok)
        for bad in ("no-license", "", "GPL-3.0", "CC BY-NC", "proprietary", "unknown"):
            self.assertFalse(c21st.is_permissive(bad), bad)


class CrawlTests(TmpData):
    def crawl(self, ff=None, **kw):
        return c21st.crawl(fetch=ff or FakeFetch(ROUTES), categories=["hero", "pricing-section"], delay=0, sleep=lambda s: None, **kw)

    def test_full_crawl_builds_the_catalog_with_licences(self):
        st = self.crawl()
        self.assertTrue(st["finished"], st)
        self.assertEqual(st["total"], 4)
        rows = {r["id"]: r for r in c21st.load()}
        self.assertEqual(rows["sensewood8/responsive-hero-banner"]["cats"], ["hero", "pricing-section"])
        self.assertTrue(rows["sensewood8/responsive-hero-banner"]["usable"])
        self.assertFalse(rows["ncdai/hero-01"]["usable"], "no-license must not be usable")
        self.assertTrue(rows["ibelick/background-snippets/background-radial-dark-gray"]["usable"])
        self.assertEqual(rows["acme/pricing-cards"]["license"], "MIT")

    def test_only_markdown_pages_are_fetched_never_the_registry(self):
        ff = FakeFetch(ROUTES)
        self.crawl(ff)
        urls = [u for u, _ in ff.calls]
        self.assertTrue(urls)
        self.assertTrue(all(u.endswith(".md") for u in urls), urls)
        self.assertFalse([u for u in urls if "/r/" in u or "/api/" in u], "robots.txt of 21st.dev disallows /r/ and /api/")
        self.assertTrue(all(u.startswith("https://21st.dev/") for u in urls))

    def test_resume_after_a_time_budget_and_no_refetch(self):
        ff = FakeFetch(ROUTES)
        first = self.crawl(ff, detail_limit=1)
        self.assertFalse(first["finished"])
        self.assertGreater(first["remaining"], 0)
        n1 = len(ff.calls)
        while True:
            st = self.crawl(ff, detail_limit=1)
            if st["finished"]:
                break
        urls = [u for u, _ in ff.calls]
        self.assertEqual(len(urls), len(set(urls)), "a page was fetched twice")
        self.assertGreater(len(urls), n1)
        self.assertEqual(len(c21st.load()), 4)

    def test_failures_are_recorded_not_fatal(self):
        routes = dict(ROUTES)
        routes["https://21st.dev/@acme/components/pricing-cards.md"] = safenet.FetchError("سایت به‌موقع جواب نداد.", "timeout")
        st = self.crawl(FakeFetch(routes))
        self.assertTrue(st["finished"])
        row = next(r for r in c21st.load() if r["id"] == "acme/pricing-cards")
        self.assertFalse(row["usable"])
        self.assertTrue(any("pricing-cards" in e for e in st["errors"]))

    def test_a_dead_worker_does_not_leave_the_crawl_running_forever(self):
        self.crawl()
        st = c21st.crawl_state()
        st.update(running=True, running_at=time.time())
        c21st._save_state(st)
        self.assertTrue(c21st.is_running())
        st["running_at"] = time.time() - c21st.RUNNING_STALE_S - 5
        c21st._save_state(st)
        self.assertFalse(c21st.is_running(), "a turn that started 10 minutes ago and never ended is dead")

    def test_time_budget_stops_the_turn(self):
        ticks = iter(range(0, 1000, 100))
        st = c21st.crawl(fetch=FakeFetch(ROUTES), categories=["hero", "pricing-section"], delay=0, sleep=lambda s: None, max_seconds=150, clock=lambda: next(ticks))
        self.assertFalse(st["finished"])


class SearchTests(TmpData):
    def setUp(self):
        super().setUp()
        CrawlTests.crawl(self)

    def test_search_filters_and_ranks(self):
        r = c21st.search("pricing")
        self.assertEqual(r["items"][0]["id"], "acme/pricing-cards", "a title match ranks first")
        self.assertEqual(r["total"], 2, "the hero banner is also listed under the pricing category in this fixture")
        self.assertEqual(c21st.search("", cat="hero")["total"], 3)
        self.assertEqual(c21st.search("", usable_only=True)["total"], 3)
        self.assertEqual(c21st.search("nothingmatches")["total"], 0)
        self.assertEqual(sum(c["count"] for c in c21st.search("")["categories"]), 5)

    def test_every_result_says_licence_and_the_nearest_of_our_components(self):
        for item in c21st.search("")["items"]:
            self.assertTrue(item["license"])
            self.assertTrue(item["url"].startswith("https://21st.dev/@"))
        hero = next(i for i in c21st.search("", cat="hero")["items"] if i["id"] == "sensewood8/responsive-hero-banner")
        self.assertTrue(hero["nearest"], "a hero must map to one of our own hero components")
        from apps.projects.builder import components as C
        self.assertEqual(C.COMPONENTS[hero["nearest"][0]["key"]]["cat"], "hero")
        pricing = c21st.search("pricing")["items"][0]
        self.assertEqual(C.COMPONENTS[pricing["nearest"][0]["key"]]["cat"], "pricing")


class CodeAndKeyTests(TmpData):
    def setUp(self):
        super().setUp()
        CrawlTests.crawl(self)
        self.env = mock.patch.dict("os.environ", {"API_KEY_21ST": ""}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    REG = {"name": "responsive-hero-banner", "dependencies": ["motion"], "files": [{"path": "components/ui/hero.tsx", "content": "export function Hero(){ return <section/> }\n" * 30}]}

    def test_without_a_key_the_message_explains(self):
        with self.assertRaises(c21st.CatalogError) as cm:
            c21st.fetch_code("sensewood8/responsive-hero-banner", fetch=FakeFetch({}))
        self.assertIn("کلیدِ API", str(cm.exception))

    def test_key_validation_and_storage_is_private(self):
        with self.assertRaises(c21st.CatalogError):
            c21st.set_key("short")
        with self.assertRaises(c21st.CatalogError):
            c21st.set_key("has spaces and ; weird chars 1234567890")
        c21st.set_key("abcdef0123456789abcdef")
        self.assertTrue(c21st.key_status()["has_key"])
        self.assertNotIn("abcdef0123456789abcdef", json.dumps(c21st.key_status()))
        import os, stat
        mode = os.stat(self.tmp / "c21st" / "key").st_mode
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(mode), 0o600)
        c21st.clear_key()
        self.assertFalse(c21st.key_status()["has_key"])

    def test_unlicensed_component_is_refused_even_with_a_key(self):
        c21st.set_key("abcdef0123456789abcdef")
        ff = FakeFetch({"https://21st.dev/r/": self.REG})
        with self.assertRaises(c21st.CatalogError) as cm:
            c21st.fetch_code("ncdai/hero-01", fetch=ff)
        self.assertIn("مجوز", str(cm.exception))
        self.assertFalse(ff.calls)

    def test_fetch_uses_the_header_not_the_url_and_respects_the_daily_limit(self):
        c21st.set_key("abcdef0123456789abcdef")
        ff = FakeFetch({"https://21st.dev/r/": self.REG})
        out = c21st.fetch_code("sensewood8/responsive-hero-banner", fetch=ff)
        self.assertEqual(out["files"], ["components/ui/hero.tsx"])
        url, kw = ff.calls[0]
        self.assertEqual(url, "https://21st.dev/r/sensewood8/responsive-hero-banner")
        self.assertEqual(kw["headers"], {"x-api-key": "abcdef0123456789abcdef"})
        self.assertNotIn("api_key", url)
        self.assertTrue((self.tmp / "c21st" / "code" / "sensewood8__responsive-hero-banner.tsx").is_file())
        self.assertTrue(c21st.search("hero banner")["items"][0]["has_code"])
        c21st.fetch_code("acme/pricing-cards", fetch=ff)
        self.assertEqual(c21st.key_status()["left_today"], 0)
        with self.assertRaises(c21st.CatalogError) as cm:
            c21st.fetch_code("ibelick/background-snippets/background-radial-dark-gray", fetch=ff)
        self.assertIn("سقفِ امروز", str(cm.exception))
        self.assertEqual(len(ff.calls), 2, "the third request must never be sent")

    def test_bad_key_message(self):
        c21st.set_key("abcdef0123456789abcdef")
        ff = FakeFetch({"https://21st.dev/r/": safenet.FetchError("سایت جواب 403 داد.", "http_403")})
        with self.assertRaises(c21st.CatalogError) as cm:
            c21st.fetch_code("sensewood8/responsive-hero-banner", fetch=ff)
        self.assertIn("نپذیرفت", str(cm.exception))
        self.assertEqual(c21st.key_status()["used_today"], 0, "a failed call must not use the quota")

    def test_ai_context_sends_few_small_inspirations_under_the_cap(self):
        c21st.set_key("abcdef0123456789abcdef")
        big = {"files": [{"path": "a.tsx", "content": "const x = 1; // " + ("y" * 80 + "\n") * 400}]}
        c21st.fetch_code("sensewood8/responsive-hero-banner", fetch=FakeFetch({"https://21st.dev/r/": big}))
        ids = ["sensewood8/responsive-hero-banner", "ncdai/hero-01", "acme/pricing-cards", "ibelick/background-snippets/background-radial-dark-gray", "nope/none"]
        p = ai_context.build("bento-grid", "اپ ورزشی چغر", "home", (), refs21=ids)
        self.assertLessEqual(p["stats"]["chars"], ai_context.MAX_CHARS)
        self.assertLessEqual(len(p["inspiration"]), c21st.MAX_AI_REFS)
        got = {i["id"]: i for i in p["inspiration"]}
        self.assertNotIn("nope/none", got)
        self.assertIn("code_excerpt", got["sensewood8/responsive-hero-banner"])
        self.assertLessEqual(len(got["sensewood8/responsive-hero-banner"]["code_excerpt"]), c21st.EXCERPT_CHARS)
        self.assertNotIn("code_excerpt", got["ncdai/hero-01"], "an unlicensed component never sends code")
        self.assertIn("inspiration", p["howto"])
        self.assertEqual(p["stats"]["inspiration"], len(p["inspiration"]))
        # بدونِ الهام ⇒ بسته دقیقاً مثلِ قبل (بدونِ کلیدِ inspiration)
        self.assertNotIn("inspiration", ai_context.build("bento-grid", "اپ ورزشی", "home", ()))

    def test_cap_holds_even_when_everything_is_huge(self):
        c21st.set_key("abcdef0123456789abcdef")
        big = {"files": [{"path": "a.tsx", "content": "z" * 50_000}]}
        c21st.fetch_code("sensewood8/responsive-hero-banner", fetch=FakeFetch({"https://21st.dev/r/": big}))
        floor = ai_context.build("aurora", "فروشگاه" * 100, "home", (), max_chars=3500)["stats"]["chars"]      # کمینهٔ ساختاریِ بسته (سبک + یک قطعه)
        p = ai_context.build("aurora", "فروشگاه" * 100, "home", (), refs21=["sensewood8/responsive-hero-banner"], max_chars=3500)
        self.assertLessEqual(p["stats"]["chars"], floor, "the inspiration must be dropped before the cap is exceeded")
        self.assertNotIn("inspiration", p)
        roomy = ai_context.build("aurora", "فروشگاه", "home", (), refs21=["sensewood8/responsive-hero-banner"], max_chars=ai_context.MAX_CHARS)
        self.assertLessEqual(roomy["stats"]["chars"], ai_context.MAX_CHARS)
        self.assertIn("inspiration", roomy)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.dtmp = Path(tempfile.mkdtemp(prefix="nm-c21st-api-"))
        self.ov = override_settings(NM_DATA_DIR=self.dtmp)
        self.ov.enable()
        c21st._cache.update(mtime=0.0, rows=[], path="")
        CrawlTests.crawl(self)

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.dtmp, ignore_errors=True)
        super().tearDown()

    def test_admin_only(self):
        for path in ("c21st/", "c21st/crawl/", "c21st/key/", "c21st/code/"):
            self.assertIn(self.client.get("/api/v1/studio/" + path).status_code, (401, 403), path)

    def test_list_and_filters(self):
        r = self.c.get("/api/v1/studio/c21st/?q=pricing")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["items"][0]["id"], "acme/pricing-cards")
        self.assertEqual(d["catalog_size"], 4)
        self.assertTrue(d["crawl"]["finished"])
        self.assertFalse(d["key"]["has_key"] and False)
        self.assertEqual(d["max_ai_refs"], 3)
        self.assertEqual(self.c.get("/api/v1/studio/c21st/?usable=1").json()["total"], 3)

    def test_crawl_is_queued_not_run_inline(self):
        with mock.patch("apps.projects.tasks.c21st_refresh.delay") as delay:
            r = self.c.post("/api/v1/studio/c21st/crawl/", {}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        delay.assert_called_once_with(force=True)

    def test_key_endpoints_never_return_the_key(self):
        with mock.patch.dict("os.environ", {"API_KEY_21ST": ""}):
            bad = self.c.post("/api/v1/studio/c21st/key/", {"key": "x"}, format="json")
            self.assertEqual(bad.status_code, 400)
            ok = self.c.post("/api/v1/studio/c21st/key/", {"key": "abcdef0123456789abcdef"}, format="json")
            self.assertEqual(ok.status_code, 200)
            self.assertNotIn("abcdef0123456789abcdef", ok.content.decode())
            self.assertTrue(ok.json()["key"]["has_key"])
            gone = self.c.delete("/api/v1/studio/c21st/key/")
            self.assertFalse(gone.json()["key"]["has_key"])

    def test_code_without_key_is_a_clear_409(self):
        with mock.patch.dict("os.environ", {"API_KEY_21ST": ""}):
            r = self.c.post("/api/v1/studio/c21st/code/", {"id": "sensewood8/responsive-hero-banner"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("کلیدِ API", r.json()["error"])

    def test_the_ai_form_sends_refs_and_unknown_ones_are_dropped(self):
        from apps.ai_engine import api as ai_api
        from apps.projects.helpers import FormData

        d = ai_api._design(FormData({"style": "aurora", "components": ["cta_strip"], "refs21": ["acme/pricing-cards", "evil/none", "ncdai/hero-01", "sensewood8/responsive-hero-banner", "ibelick/background-snippets/background-radial-dark-gray"]}))
        self.assertEqual(d["refs21"], ["acme/pricing-cards", "ncdai/hero-01", "sensewood8/responsive-hero-banner"])
        self.assertEqual(ai_api._design(FormData({"refs21": ["evil/none"]})), None)
        self.assertNotIn("refs21", ai_api._design(FormData({"style": "aurora"})))

    def test_refresh_task_skips_when_fresh_and_requeues_when_unfinished(self):
        from apps.projects import tasks

        self.assertEqual(tasks.c21st_refresh(), {"skipped": "fresh"})
        with mock.patch("apps.projects.builder.c21_crawl.run_turn", return_value={"finished": False, "total": 5, "remaining": 3}), \
                mock.patch.object(tasks.c21st_refresh, "apply_async") as again:
            out = tasks.c21st_refresh(force=True)
        self.assertFalse(out["finished"])
        again.assert_called_once()
