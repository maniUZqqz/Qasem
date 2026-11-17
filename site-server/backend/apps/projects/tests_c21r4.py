# -*- coding: utf-8 -*-
"""اصلاحاتِ دورِ چهارمِ بازبینی (۱۱/۱۷) روی «منبع‌های طراحی + 21st.dev»:

* قطعهٔ 21st در «هنوز نمونه است» پیش از انتشار می‌آید (قیمت‌ها و ادعاهای ساختگیِ دیگران بی‌هشدار منتشر نمی‌شد)؛ حتی فارسی‌شده؛ تا کاربر متن را عوض نکرده؛
* پیامِ دکمهٔ «فارسی‌سازی با AI» وقتی AI نیست دروغ نمی‌گوید (چیزی در صف نمی‌ماند)؛
* خوانایی: رنگ‌های oklch()/color-mix() هم سنجیده می‌شوند (مرورگرِ واقعی، اگر باشد) + حاشیهٔ ایمنیِ طرح؛
* «بخشِ صفحه» فقط برای بخشِ واقعی؛ مجوزِ نمایش‌داده‌شده = مجوزِ مخزن؛ جست‌وجوی منبع‌ها با ی/ک عربی؛
* چیدمانِ بخش برای قطعه‌های آمادهٔ c_hero_* / c_cta_* / c_faq_*؛ توضیحِ آزمونِ خودکارِ سبک‌ها زنده است.
مرورگر و AI ِ واقعی صدا زده نمی‌شوند مگر آزمونی که صریحاً «اگر مرورگر بود» می‌گوید.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from apps.projects import c21_api
from apps.projects.builder import (c21_contrast as CC, c21_convert as CV, c21_embed as EM, c21_rtl, c21_translate as TR, c21st, chagher_draft as D, render as R, styles as S,
                                   theme as T, variants as V)
from apps.projects.builder.clean import clean_doc, new_block
from apps.projects.builder.styles import uiux
from apps.projects.tests_builder import API, Base
from apps.projects.tests_c21x import DataDirMixin, FakeNode
from apps.projects.models import Page

PRICING_HTML = ('<div id="c21-root"><section class="p-4"><h2>Simple pricing for teams of every size</h2><p>Pro</p><p>$7 / mo</p><p>Get started</p>'
                '<a href="#">Buy</a><p>We are a SEC registered investment advisor</p><p>Pricing</p></section></div>')


def render(doc, canvas=False):
    return R.render_doc(clean_doc(doc, "page"), R.Ctx(canvas=canvas, target="page", theme=T.default_theme()["colors"]))


def sample_texts(out):
    return [w["text"] for w in out.warnings if w.get("kind") == "sample"]


class C21Base(DataDirMixin):
    def convert(self, cid="acme/pricing-x", html=PRICING_HTML, title="Pricing", license_="mit", source_license="MIT", cats=("pricing-section",)):
        rec = CV.convert_bundle(cid, {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [],
                                      "source": {"kind": "upstream", "repo": "https://github.com/acme/ui", "license": source_license}},
                                meta={"title": title, "license": license_, "author": "Acme", "library": "Acme UI", "cats": list(cats)}, runner=FakeNode(html=html))
        CV.save_record(rec)
        return rec

    def block(self, rec, fa=False, texts=None):
        b = c21_api._block_for(rec, fa, False)["block"]
        if texts is not None:
            b["props"]["texts"] = [{"v": t} for t in texts]
        return b


# ───────────────────────────── ۱) «هنوز نمونه است» برای قطعهٔ 21st

class SampleGuardTests(C21Base, SimpleTestCase):
    def test_untouched_component_lists_prices_and_foreign_copy(self):
        rec = self.convert()
        out = render({"v": 1, "blocks": [self.block(rec)]})
        got = sample_texts(out)
        self.assertEqual(len(got), 2, got)                                          # یک هشدار برای قیمت/عدد، یکی برای متنِ نمونه
        self.assertTrue(any("$7 / mo" in t and "قیمت" in t for t in got), got)
        self.assertTrue(any("نمونهٔ 21st" in t for t in got), got)

    def test_persian_translated_component_is_still_a_sample_until_the_owner_edits_it(self):
        """قلبِ بازبینی: متنِ فارسی‌شده با فرهنگ‌لغت (یا AI) دیگر با متنِ اصلی یکی نیست، ولی هنوز حرفِ دیگران است."""
        rec = self.convert()
        b = self.block(rec, fa=True)
        texts = [t["v"] for t in b["props"]["texts"]]
        self.assertIn("شروع کنید", texts)                                           # فرهنگ‌لغت اعمال شد
        self.assertNotEqual(texts, rec["texts"])
        self.assertTrue(sample_texts(render({"v": 1, "blocks": [b]})), "فارسی‌شده ⇒ باز هم نمونه")
        self.assertTrue(b["props"]["seed"])

    def test_editing_some_texts_keeps_the_rest_flagged_and_editing_all_clears_it(self):
        rec = self.convert()
        b = self.block(rec)
        b["props"]["texts"][0]["v"] = "برنامهٔ ورزشی برای مربی‌های باشگاه"          # فقط تیتر عوض شد
        left = sample_texts(render({"v": 1, "blocks": [b]}))
        self.assertTrue(left and all("برنامهٔ ورزشی" not in t for t in left), left)
        for t in b["props"]["texts"]:
            if EM.meaningful(t["v"]):
                t["v"] = "متنِ خودِ مربی برای این بخش"
        self.assertEqual(sample_texts(render({"v": 1, "blocks": [b]})), [])

    def test_one_word_ui_labels_are_not_samples_but_numbers_are(self):
        self.assertFalse(EM.meaningful("Pro"))
        self.assertFalse(EM.meaningful("ماه"))
        self.assertFalse(EM.meaningful(""))
        self.assertTrue(EM.meaningful("$7 / mo"))
        self.assertTrue(EM.meaningful("99.98%"))
        self.assertTrue(EM.meaningful("Simple pricing for teams"))
        rec = self.convert("acme/labels", '<div id="c21-root"><section><h2>Pro</h2><p>Free</p></section></div>')
        self.assertEqual(sample_texts(render({"v": 1, "blocks": [self.block(rec)]})), [], "فقط برچسب‌های تک‌واژه‌ای ⇒ نمونهٔ ساختگی نیست")

    def test_old_blocks_without_a_seed_compare_with_the_original_and_its_dictionary_translation(self):
        rec = self.convert()
        b = self.block(rec)
        b["props"].pop("seed", None)
        self.assertTrue(sample_texts(render({"v": 1, "blocks": [b]})))
        tr, _n = TR.apply_dictionary(rec["texts"])
        b["props"]["texts"] = [{"v": t} for t in tr]
        self.assertTrue(sample_texts(render({"v": 1, "blocks": [b]})))
        b["props"]["texts"] = [{"v": "کاملاً متنِ خودمان است" if EM.meaningful(t) else t} for t in rec["texts"]]
        self.assertEqual(sample_texts(render({"v": 1, "blocks": [b]})), [])

    def test_the_canvas_lists_it_too_and_deleted_rows_never_warn(self):
        rec = self.convert()
        b = self.block(rec)
        self.assertTrue(sample_texts(render({"v": 1, "blocks": [b]}, canvas=True)), "فهرستِ کنارِ ویرایشگر (از رندرِ بوم) مثلِ بلوک‌های خودمان")
        for t in b["props"]["texts"]:
            t["v"] = ""
        self.assertEqual(sample_texts(render({"v": 1, "blocks": [b]})), [])
        self.assertEqual(sample_texts(render({"v": 1, "blocks": [b]}, canvas=True)), [])

    def test_seed_survives_clean_doc_and_is_hidden_in_the_form(self):
        rec = self.convert()
        b = self.block(rec)
        again = clean_doc({"v": 1, "blocks": [b]}, "page")["blocks"][0]
        self.assertEqual(again["props"]["seed"], b["props"]["seed"])
        from apps.projects.builder.catalog import catalog_json
        spec = next(x for x in catalog_json()["blocks"] if x["type"] == "c21")
        self.assertTrue(next(f for f in spec["fields"] if f["key"] == "seed")["hidden"])

    def test_seed_is_capped_and_stays_in_the_field_limit(self):
        self.assertLessEqual(len(EM.seed_of(["متنِ شمارهٔ %d" % i for i in range(400)])), 1000)
        self.assertEqual(EM.seed_of([]), "")


class SampleGuardEndpointTests(C21Base, Base):
    """همان مسیرِ پنل: POST .../builder/check/ باید بلوکِ 21st را هم ببیند (پیش‌تر ۰ یافته بود)."""

    def test_publish_check_lists_the_inserted_component_like_a_built_in_pricing_block(self):
        rec = self.convert()
        p = self.project()
        pg = Page.objects.create(project=p, title="صفحهٔ اصلی", slug="", kind="home", body_html="", in_menu=False, order=10)
        got = self.c.get("/api/v1/studio/projects/%s/builder/c21/%s/block/" % (p.slug, rec["key"]), {"fa": 1})
        self.assertEqual(got.status_code, 200)
        r = self.c.post(API % p.slug + "check/", {"target": "page", "page": pg.pk, "doc": {"v": 1, "blocks": [got.json()["block"]]}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        found = [f for f in r.json()["findings"] if f["type"] == "c21" and f["kind"] == "sample"]
        self.assertGreaterEqual(len(found), 2, r.json())
        self.assertTrue(any("$7" in f["text"] for f in found))
        # بلوکِ آمادهٔ خودمان همان‌طور که بود
        base = self.c.post(API % p.slug + "check/", {"target": "page", "page": pg.pk, "doc": {"v": 1, "blocks": [new_block("c_price_three_tier")]}}, format="json").json()
        self.assertTrue(base["findings"])
        # متنِ خودِ کاربر ⇒ هیچ
        b = got.json()["block"]
        for t in b["props"]["texts"]:
            if EM.meaningful(t["v"]):
                t["v"] = "متنِ خودمان"
        none = self.c.post(API % p.slug + "check/", {"target": "page", "page": pg.pk, "doc": {"v": 1, "blocks": [b]}}, format="json").json()
        self.assertFalse([f for f in none["findings"] if f["type"] == "c21" and f["kind"] == "sample"], none)


# ───────────────────────────── ۲) پیامِ «فارسی‌سازی با AI»

class TranslateMessageTests(DataDirMixin, SimpleTestCase):
    def test_message_never_promises_a_queue_that_does_not_exist(self):
        def boom(system, user):
            raise RuntimeError("HTTP 402 insufficient credit")
        got, info = TR.ai_translate(["Hello there friend", "Build faster than ever"], complete=boom)
        self.assertEqual(got, ["Hello there friend", "Build faster than ever"])
        self.assertFalse(info["ok"])
        self.assertFalse(info.get("queued"))
        self.assertNotIn("در صف ماند", info["message"])
        self.assertIn("در صف نمی‌ماند", info["message"])
        self.assertIn("دوباره", info["message"])
        self.assertRegex(info["message"], r"[آ-ی]")

    def test_nothing_is_parked_on_disk(self):
        from apps.ai_engine import parking

        def boom(system, user):
            raise RuntimeError("HTTP 402 insufficient credit")
        TR.ai_translate(["Hello there friend"], complete=boom)
        self.assertEqual(list(parking._dir().glob("*.json")), [], "ترجمهٔ درجا پارک نمی‌شود؛ پیامش هم همین را می‌گوید")

    def test_unavailable_error_carries_a_short_reason_for_callers_without_a_queue(self):
        from apps.ai_engine import parking
        un = parking.unavailable_from(RuntimeError("HTTP 402 insufficient credit"))
        if un is None:
            self.skipTest("مسیریابِ AI این خطا را «در دسترس نبودن» نمی‌داند")
        self.assertTrue(un.reason)
        self.assertNotIn("در صف ماند", un.reason)
        self.assertIn("در صف ماند", str(un), "پیامِ پیشنهادهای ساختِ صفحه (که واقعاً پارک می‌شوند) همان است که بود")


# ───────────────────────────── ۳) مجوزِ نمایش‌داده‌شده

class LicenseTests(C21Base, SimpleTestCase):
    def test_effective_license_follows_the_repository_licence_file(self):
        self.assertEqual(c21st.effective_license("mit", "Apache-2.0"), "Apache-2.0")
        self.assertEqual(c21st.effective_license("MIT", "Apache 2.0"), "Apache 2.0")
        self.assertEqual(c21st.effective_license("Apache-2.0", "apache 2.0"), "Apache-2.0", "املای دیگرِ همان مجوز ⇒ عوض نمی‌شود")
        self.assertEqual(c21st.effective_license("mit", "MIT"), "mit", "املای کاتالوگ می‌ماند وقتی یکی‌اند")
        self.assertEqual(c21st.effective_license("mit", ""), "mit")
        self.assertEqual(c21st.effective_license("", "ISC"), "ISC")
        self.assertEqual(c21st.effective_license("mit", "GPL-3.0"), "mit", "مجوزِ نا‌آزادِ مخزن جایگزین نمی‌شود (اصلاً تبدیل نمی‌شد)")

    def test_record_card_preview_and_html_comment_agree(self):
        rec = self.convert(license_="mit", source_license="Apache-2.0")
        self.assertEqual(rec["license"], "Apache-2.0")
        self.assertIn("Apache-2.0", EM.attribution(rec))
        saved = CV.load_record(rec["key"])
        self.assertEqual(saved["license"], "Apache-2.0")
        row = {"id": rec["id"], "title": "Pricing", "detail": True, "usable": True, "license": "mit", "cats": ["pricing-section"], "conv": {"state": "ok", "key": rec["key"]}}
        c21st.save([row])
        self.assertEqual(c21st.public(c21st.load()[0])["license"], "Apache-2.0", "کارتِ کاتالوگ هم همین را نشان می‌دهد")
        self.assertEqual(EM.preview_page(rec["key"])["license"], "Apache-2.0")

    def test_old_records_are_repaired_on_load_and_by_relicense_all(self):
        rec = self.convert(license_="mit", source_license="MIT")
        raw = json.loads(CV.record_path(rec["key"]).read_text(encoding="utf-8"))
        raw["source"]["license"] = "Apache-2.0"                       # رکوردِ قدیمی: مجوزِ کاتالوگ MIT، مخزن Apache
        raw["license"] = "mit"
        CV.record_path(rec["key"]).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        CV._CACHE.clear()
        fixed = CV.load_record(rec["key"])
        self.assertEqual((fixed["license"], fixed["license_catalog"]), ("Apache-2.0", "mit"))
        self.assertEqual(CV.relicense_all(), 1)
        self.assertEqual(CV.load_index()[rec["id"]]["license"], "Apache-2.0")
        self.assertEqual(CV.relicense_all(), 0, "بار دوم چیزی برای عوض‌کردن نیست")


# ───────────────────────────── ۴) «بخشِ صفحه» فقط برای بخشِ واقعی

class SectionClassificationTests(SimpleTestCase):
    def kind(self, title, chars=300, height=600, cats=()):
        return c21_rtl.classify({"chars": chars, "height": height}, {"title": title, "cats": list(cats), "images": []})[0]

    def test_the_reviewers_widgets_are_not_sections_even_when_tall(self):
        for title in ("Label", "Select", "Separator", "Radio Group", "Color Picker", "Timer", "Vote Tally", "YouTube Video Player", "Tabs", "Table", "Conversation List",
                      "Dynamic Island", "Command Search", "Pointer", "Terminal", "Thinking", "Edge Blur", "Task Steps", "Activity Empty State"):
            self.assertEqual(self.kind(title, chars=400, height=1400), "widget", title)

    def test_real_landing_sections_are_sections(self):
        for title, cats in (("Banner Tiers Pricing Table", ["pricing-section"]), ("FAQ Tabs Card", ["accordion"]), ("FAQ Two Column", ["accordion"]), ("Feature Grid Spotlight Cards", ["features"]),
                            ("Comparison Section", ["features"]), ("Changelog", []), ("Hero Section", ["hero"]), ("Footer Big", ["footer"]), ("Testimonials Marquee", ["testimonials"]),
                            ("Sticky Header", ["navigation"]), ("Timeline", ["landing-page"])):
            self.assertEqual(self.kind(title, chars=200, height=500, cats=cats), "section", title)

    def test_empty_named_sections_and_short_unnamed_ones_are_widgets(self):
        self.assertEqual(self.kind("Pricing", chars=12, height=90), "widget")
        self.assertEqual(self.kind("Something Else", chars=400, height=120), "widget")
        self.assertEqual(self.kind("Something Else", chars=400, height=600), "section", "نامِ ابزارک ندارد و واقعاً بلند و پرمتن است")
        self.assertEqual(self.kind("Something Else", chars=400, height=600, cats=["ai-chat"]), "widget", "گفت‌وگوی AI ابزارکِ برنامه است")

    def test_browser_script_reports_the_component_height_not_the_page_height(self):
        src = (Path(__file__).resolve().parents[3] / "deploy" / "c21" / "rtl_check.py").read_text(encoding="utf-8")
        self.assertIn("nbc21-host", src.split("height = page.evaluate(")[1][:260])
        self.assertNotIn("height = page.evaluate('document.documentElement.scrollHeight')", src)


# ───────────────────────────── ۵) خوانایی: حاشیهٔ ایمنی و رنگ‌های oklch()

class ReadabilityRound4Tests(SimpleTestCase):
    def test_a_context_whose_worst_text_is_under_the_margin_is_not_clean(self):
        ok = {"hard": 0, "soft": 0, "n": 5, "worst": 6.0}
        dim = {"hard": 0, "soft": 2, "n": 5, "worst": 2.9}              # «Search…» ۲٫۸۹:۱ روی سایبرپانک
        plan = CC.make_plan({"tl": dim, "td": ok, "il": ok, "id": ok})["plan"]
        self.assertEqual(plan["dark"], "theme")
        self.assertEqual(plan["light"], "light", "روی روشن: جزیرهٔ روشن (نه پوسته‌ای که متنِ کم‌رنگ دارد)")
        borderline = {"hard": 0, "soft": 0, "n": 5, "worst": 3.45}
        self.assertEqual(CC.make_plan({"tl": borderline, "td": ok, "il": ok, "id": ok})["plan"]["light"], "theme", "۳٫۴۵ ≥ حاشیه ⇒ همان پوسته")
        self.assertEqual(CC.make_plan({"tl": ok, "td": ok, "il": ok, "id": ok})["plan"], {"light": "theme", "dark": "theme"})
        self.assertGreater(CC.PLAN_MIN, CC.HARD)

    def test_missing_worst_keeps_the_old_behaviour(self):
        old = {"hard": 0, "soft": 0, "n": 3}
        self.assertEqual(CC.make_plan({"tl": old, "td": old, "il": old, "id": old})["ok"], True)
        self.assertEqual(CC.make_plan({"tl": {"hard": 1, "soft": 0, "n": 3}, "td": old, "il": old, "id": old})["plan"]["light"], "light")

    def test_check_version_is_bumped_so_stored_records_are_measured_again(self):
        self.assertGreaterEqual(c21_rtl.CHECK_VERSION, 5)
        self.assertGreaterEqual(CC.CONTRAST_VERSION, 2)

    @unittest.skipUnless(c21_rtl.available()[0], "Playwright/Chromium نیست")
    def test_real_browser_sees_oklch_and_color_mix_text(self):
        """بازبینیِ دورِ ۴: متنِ text-neutral-300 (= oklch) در سنجشِ rgb-فقط نادیده می‌ماند؛ حالا باید با رنگِ درستش گزارش شود."""
        with tempfile.TemporaryDirectory(prefix="c21r4-") as d:
            html = ('<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fff"><p style="color:oklch(0.87 0 0);font-size:16px">light oklch text</p>'
                    '<p style="color:color-mix(in srgb,#000 70%,#fff);font-size:16px">mixed text</p><p style="color:rgb(10,20,30)">plain rgb text</p></body>')
            Path(d, "t~tl.html").write_text(html, encoding="utf-8")
            env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or c21_rtl.DEFAULT_BROWSERS)
            subprocess.run([os.environ.get("NM_C21_PLAYWRIGHT_PY") or c21_rtl.DEFAULT_PY, str(c21_rtl.SCRIPT), d, str(Path(d, "rtl.json"))], capture_output=True, text=True, env=env, timeout=240)
            data = json.loads(Path(d, "t~tl.json").read_text(encoding="utf-8"))
            items = {it["text"]: it for it in data["items"]}
            self.assertIn("light oklch text", items, "متنِ oklch باید دیده شود")
            self.assertAlmostEqual(items["light oklch text"]["color"][0], 212, delta=3)
            self.assertIn("mixed text", items)
            self.assertAlmostEqual(items["mixed text"]["color"][0], 77, delta=4)
            self.assertEqual(items["plain rgb text"]["color"][:3], [10, 20, 30])
            m = CC.measure(data["items"], Path(d, "t~tl.png"))
            self.assertEqual(m["hard"], 1, m)                                   # فقط متنِ روشن (۱٫۴۸:۱) نامرئی است
            self.assertTrue(any("light oklch" in s["text"] for s in m["samples"]), m)


# ───────────────────────────── ۶) جست‌وجوی منبع‌ها با ی/ک عربی

class FoldSearchTests(SimpleTestCase):
    def test_arabic_and_persian_letters_find_the_same_rows(self):
        from apps.projects.design_sources_api import _styles_extra         # نامِ فارسیِ سبک‌ها همان‌جا به جست‌وجو اضافه می‌شود
        a, b = uiux.search("styles", "ويپور", limit=5, extra=_styles_extra), uiux.search("styles", "ویپور", limit=5, extra=_styles_extra)
        self.assertTrue(b, "پایه: «ویپور» Vaporwave را می‌یابد")
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])
        self.assertEqual(uiux.count("styles", "ويپور", None, _styles_extra), uiux.count("styles", "ویپور", None, _styles_extra))
        self.assertGreaterEqual(uiux.count("styles", "ويپور", None, _styles_extra), 1)
        # حرف‌های دیگر: «ك» ِ عربی در کلیدواژه‌های فارسیِ مخزن‌های دیگر هم یکی می‌شود
        self.assertEqual(uiux.count("styles", "شيشه", None, _styles_extra), uiux.count("styles", "شیشه", None, _styles_extra))
        self.assertEqual(uiux.count("fonts", "كلاسيك"), uiux.count("fonts", "کلاسیک"))

    def test_fold_handles_digits_zwnj_diacritics_and_case(self):
        self.assertEqual(uiux.fold("قلم‌ها"), "قلم ها")
        self.assertEqual(uiux.fold("۸۹ سبک"), "89 سبک")
        self.assertEqual(uiux.fold("٨٩"), "89")
        self.assertEqual(uiux.fold("كِتاب"), "کتاب")
        self.assertEqual(uiux.fold("Glass"), "glass")
        self.assertEqual(uiux.fold(None), "")

    def test_english_and_persian_queries_still_work(self):
        self.assertTrue(uiux.search("styles", "glassmorphism", limit=3))
        self.assertEqual(uiux.count("styles", ""), len(uiux.rows("styles")))


# ───────────────────────────── ۷) چیدمانِ بخش برای قطعه‌های آماده

class PartVariantTests(SimpleTestCase):
    PARTS = {"c_hero_center_glow": "hero", "c_hero_stats_bar": "hero", "c_cta_center_box": "cta", "c_faq_two_col": "faq", "c_faq_cards_grid": "faq"}

    def test_every_part_has_the_same_layout_keys_as_its_base_block(self):
        for part, base in self.PARTS.items():
            self.assertEqual(V.base_of(part), base)
            self.assertEqual(set(V.VARIANTS[part][1]), set(V.VARIANTS[base][1]), part)
            for key in V.VARIANTS[part][1]:
                css = V.css_for(part, key)
                self.assertIn(".nbv-" + key, css, (part, key))
                self.assertTrue(css.count("{") == css.count("}") and "@R@" not in css and "@W@" not in css and "@I@" not in css and "@C@" not in css, (part, key))
        self.assertEqual(V.base_of("hero"), "hero")

    def test_parts_get_the_variant_field_and_clean_doc_keeps_it(self):
        from apps.projects.builder.catalog import BLOCKS
        for part in self.PARTS:
            self.assertIn("variant", [f["key"] for f in BLOCKS[part]["fields"]], part)
        doc = clean_doc({"v": 1, "blocks": [new_block("c_hero_center_glow", variant="card"), new_block("c_hero_center_glow", variant="nope")]}, "page")
        self.assertEqual(doc["blocks"][0]["props"].get("variant"), "card")
        self.assertNotIn("variant", doc["blocks"][1]["props"], "کلیدِ ناشناخته دور ریخته می‌شود")

    def test_render_adds_the_class_and_only_the_used_css(self):
        out = render({"v": 1, "blocks": [new_block("c_hero_center_glow", variant="card")]})
        self.assertIn("nbv-card", out.html)
        self.assertIn(".nbc-hero-center-glow.nbv-card", out.css)
        self.assertNotIn(".nbv-aurora", out.css)
        plain = render({"v": 1, "blocks": [new_block("c_hero_center_glow")]})
        self.assertNotIn("nbv-", plain.html)

    def test_applying_a_style_layout_reaches_the_ready_parts(self):
        doc = {"v": 1, "blocks": [new_block("c_hero_center_glow"), new_block("c_cta_center_box"), new_block("c_faq_two_col"), new_block("c_steps_horizontal")]}
        st = next(k for k in S.ORDER if (S.STYLES[k].get("sections") or {}).get("hero") and (S.STYLES[k].get("sections") or {}).get("cta") and (S.STYLES[k].get("sections") or {}).get("faq"))
        sections = S.STYLES[st]["sections"]
        out = S.apply_to_doc(clean_doc(doc, "page"), st)["blocks"]
        self.assertEqual(out[0]["props"].get("variant"), sections["hero"])
        self.assertEqual(out[1]["props"].get("variant"), sections["cta"])
        self.assertEqual(out[2]["props"].get("variant"), sections["faq"])
        self.assertNotIn("variant", out[3]["props"])                           # قطعه‌ای که چیدمانِ جایگزین ندارد دست نمی‌خورد

    def test_the_owners_draft_is_no_longer_the_same_hero_in_every_style(self):
        """بازبینی: «با هر ۸۹ سبک سربرگ همیشه وسط‌چین است». حالا چیدمانِ سربرگِ پیش‌نویسِ چغر بین سبک‌ها فرق دارد."""
        nav, page, foot = D.blocks()
        doc = clean_doc({"v": 1, "blocks": page}, "page")
        seen = {}
        for st in S.ORDER:
            blocks = S.apply_to_doc(doc, st)["blocks"]
            seen[st] = tuple((b["type"], b["props"].get("variant", "")) for b in blocks if b["type"] in ("c_hero_center_glow", "c_cta_center_box", "c_faq_two_col"))
        self.assertGreaterEqual(len({v[0] for v in seen.values()}), 5, "دست‌کم ۵ چیدمانِ سربرگِ متفاوت")
        self.assertGreaterEqual(len(set(seen.values())), 12, "ترکیبِ سربرگ + دعوت + پرسش‌ها هم متنوع است")

    def test_variant_css_is_scoped_and_safe(self):
        for part in self.PARTS:
            for key in V.VARIANTS[part][1]:
                css = V.css_for(part, key)
                self.assertNotIn("<", css)
                self.assertNotIn("url(", css)
                self.assertNotIn("@import", css)


# ───────────────────────────── ۸) توضیحِ آزمونِ خودکار

class SelftestDescribeTests(SimpleTestCase):
    def test_site_styles_render_describes_the_live_counts(self):
        from apps.compute import selftests
        selftests.load_all()
        d = selftests.REGISTRY["site_styles_render"].describe
        self.assertNotIn("۱۴ سبک × ۴۹", d)
        self.assertIn(str(len(S.ORDER)).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")), d)
