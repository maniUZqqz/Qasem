# -*- coding: utf-8 -*-
"""اصلاحاتِ دورِ سومِ بازبینی (۱۱/۱۷) روی «منبع‌های طراحی + 21st.dev»:

* خوانایی قطعه‌های درج‌شده روی پوستهٔ روشن/تیره (جزیرهٔ رنگ، ``dark:`` ِ خودِ قطعه، سنجشِ چهارحالتهٔ مرورگر)، CSSِ ترمیم‌شده (سلکتورِ تودرتو، وسط‌چینِ RTL، ``--card``)،
  نشتِ ``.grid`` ِ سایت به قطعه، «بی‌متن»، «رویِ‌هم‌افتاده»؛
* مارک‌داونِ خامِ نامِ کتابخانه، شمارشِ «قابلِ درج» ≠ «تبدیل‌شده»، پیش‌نمایشِ قطعهٔ بسته ⇒ ۴۰۹؛
* جست‌وجوی فارسی، فارسی‌کردنِ متنِ نمونه (فرهنگ‌لغت + AI با پیامِ فارسی)، نوعِ محصول برای «آژانس مسافرتی/عکاسی»؛
* قلم‌های ترکیبیِ «تک‌فاصله» و «پیکسلی». (لایهٔ بی‌نوعِ استودیوی طراحی و شمارِ سبک‌ها را همزمان خودِ مسیرِ استودیو درست کرد؛ این‌جا نیست.)
مرورگر و شبکه و AI ِ واقعی صدا زده نمی‌شوند (همه تزریق‌پذیرند)؛ سنجشِ واقعیِ مرورگر در ``manage.py c21_recheck`` و browser_checks.
"""
import json
import os
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from apps.projects.builder import (ai_context, c21_contrast as CC, c21_convert as CV, c21_embed as EM, c21_rtl, c21_translate as TR, c21st, styles as S, theme as T)
from apps.projects.builder.styles import fonts_fa
from apps.projects.builder.styles.gen_core import contrast
from apps.projects.tests_builder import Base
from apps.projects.tests_c21x import DataDirMixin, FakeNode

LIGHT = dict(CC.PAGE_COLORS["light"])
DARK = dict(CC.PAGE_COLORS["dark"])


def make_record(key="x123456789", css=None, cid="acme/card", **kw):
    scope = "nbc21-" + key
    rec = {"id": cid, "key": key, "scope": scope, "title": "Card", "description": "", "cats": ["card"], "license": "mit", "author": "Acme", "library": "Acme UI", "url": "",
           "source": {}, "template": '<div class="grid"><h2 data-nbt="0">{{T0}}</h2></div>', "css": css if css is not None else ".%s .grid{display:grid}" % scope, "texts": ["Big title"],
           "links": [], "images": [], "warnings": [], "stats": {}, "rtl": {"status": "ok", "v": 4}, "converted_at": ""}
    rec.update(kw)
    return rec


# ───────────────────────────── CSSِ ترمیم‌شده

class CssRepairTests(SimpleTestCase):
    S = "nbc21-xabc123456"

    def test_nested_variant_selectors_are_joined_back_to_the_element(self):
        s = self.S
        broken = ".%s .hover\\:bg-black .%s :hover{background:#000}" % (s, s)
        self.assertEqual(CV.repair_nested(broken, s), ".%s .hover\\:bg-black:hover{background:#000}" % s)
        triple = "@media (hover:hover){.%s .dark\\:hover\\:bg-white .%s :where(.dark,.dark *) .%s :hover{background:#fff}}" % (s, s, s)
        self.assertEqual(CV.repair_nested(triple, s), "@media (hover:hover){.%s .dark\\:hover\\:bg-white:where(.dark,.dark *):hover{background:#fff}}" % s)
        pseudo = ".%s .before\\:absolute .%s :before{content:'';position:absolute}" % (s, s)
        self.assertIn(".before\\:absolute:before{", CV.repair_nested(pseudo, s))
        attr = ".%s .aria-expanded\\:rotate-180 .%s [aria-expanded=true]{rotate:180deg}" % (s, s)
        self.assertIn(".aria-expanded\\:rotate-180[aria-expanded=true]{", CV.repair_nested(attr, s))

    def test_repair_is_idempotent_and_leaves_normal_rules_alone(self):
        s = self.S
        good = ".%s .flex{display:flex}.%s *,.%s ::before,.%s ::after{box-sizing:border-box}.%s .a,.%s .b{color:red}" % ((s,) * 6)
        self.assertEqual(CV.repair_nested(good, s), good)
        broken = ".%s .x .%s :hover{color:red}" % (s, s)
        once = CV.repair_nested(broken, s)
        self.assertEqual(CV.repair_nested(once, s), once)
        self.assertNotIn(" .%s :hover" % s, once)

    def test_centring_stays_physical_but_other_insets_stay_logical(self):
        css = ".x{inset-inline-start:50%}.y{inset-inline-start:calc(1/2*100%)}.z{inset-inline-end:50%}.w{inset-inline-start:10px}"
        out = CV.fix_css(css, "")
        self.assertIn(".x{left:50%}", out)
        self.assertIn(".y{left:calc(1/2*100%)}", out)
        self.assertIn(".z{right:50%}", out)
        self.assertIn(".w{inset-inline-start:10px}", out)             # ⇒ در RTL آینه می‌شود (درست)

    def test_self_referencing_card_variable_is_dropped(self):
        css = ".s{--background:var(--bg,#fff);--card:var(--card,#fff);--card-foreground:var(--ink,#111827)}"
        out = CV.fix_css(css, "")
        self.assertNotIn("--card:var(--card", out)
        self.assertIn("--card-foreground:var(--ink,#111827)", out)

    def test_records_are_repaired_on_load_and_the_library_loses_its_markdown(self):
        rec = make_record(css=".nbc21-x123456789 .a .nbc21-x123456789 :hover{color:red}", library="[Spectrum UI](https://21st.dev/@a/library/spectrum-ui)", author="[Arihant](https://21st.dev/@a)")
        out = CV.normalize_record(rec)
        self.assertIn(".a:hover{", out["css"])
        self.assertEqual(out["library"], "Spectrum UI")
        self.assertEqual(out["author"], "Arihant")
        self.assertEqual(CV.normalize_record(make_record(library="Plain Lib"))["library"], "Plain Lib")


# ───────────────────────────── جزیره، سنجش و برنامهٔ نمایش

class ContrastPlanTests(SimpleTestCase):
    def test_polarity_follows_text_versus_background(self):
        self.assertEqual(CC.polarity(LIGHT), "light")
        self.assertEqual(CC.polarity(DARK), "dark")
        self.assertEqual(CC.polarity(None), "light")
        self.assertEqual(CC.polarity({"bg": "#ffffff"}), "light")
        self.assertEqual(CC.polarity({"bg": "#101010", "text": "#fafafa"}), "dark")

    def test_island_palettes_are_readable_for_any_brand_colour(self):
        for brand in ("#126f85", "#ffd700", "#0a0a2a", "#ff0000", "#ffffff", "#000000", "not-a-colour"):
            for mode in ("light", "dark"):
                v = CC.island_vars(mode, {"primary": brand})
                self.assertGreaterEqual(contrast(v["--ink"], v["--bg"]), 12, (brand, mode))
                self.assertGreaterEqual(contrast(v["--ink-2"], v["--bg"]), 7, (brand, mode))
                self.assertGreaterEqual(contrast(v["--ink-3"], v["--bg"]), 4.5, (brand, mode))
                self.assertGreaterEqual(contrast(v["--ink-3"], v["--card"]), 4.5, (brand, mode))
                self.assertGreaterEqual(contrast(v["--brand"], v["--bg"]), 4.5, (brand, mode, "متنِ برند روی جزیره"))
                self.assertGreaterEqual(contrast(v["--brand-ink"], v["--brand"]), 4.5, (brand, mode, "متنِ روی دکمهٔ برند"))

    def test_island_css_sits_on_the_root_element_of_the_component(self):
        css = CC.island_css("nbc21-xabc", "dark", LIGHT)
        self.assertTrue(css.startswith(".nbc21-xabc.nbc21-xabc{"))
        self.assertIn("--bg:#0b1020", css)
        self.assertIn("background:var(--bg)", css)
        self.assertNotIn("url(", css)

    def test_dark_variants_are_switched_on_only_for_dark(self):
        css = ".s .dark\\:bg-black:where(.dark,.dark *){background:#000}.s .not-dark\\:x:not(:where(.dark,.dark *)){y:1}"
        self.assertEqual(CC.dark_variants(css, False), css)
        on = CC.dark_variants(css, True)
        self.assertIn(":where(*){background:#000}", on)
        self.assertIn(":not(:where(*)){y:1}", on)                     # not-dark: ⇒ هرگز در پوستهٔ تیره
        self.assertNotIn(":where(.dark", on)

    def test_make_plan_prefers_the_theme_then_the_same_polarity_island(self):
        ok = {"n": 10, "hard": 0, "soft": 0, "worst": 9}
        bad = {"n": 10, "hard": 3, "soft": 0, "worst": 1.1}
        soft = {"n": 10, "hard": 0, "soft": 2, "worst": 3.5}
        # همه‌جا خوانا ⇒ رنگ‌های خودِ سایت
        self.assertEqual(CC.make_plan({"tl": ok, "td": ok, "il": ok, "id": ok})["plan"], {"light": "theme", "dark": "theme"})
        # کارتِ سفیدِ ثابت با متنِ رنگ‌پوسته (مورد: «FAQ Tabs Card»): روی تیره نامرئی ⇒ جزیرهٔ روشن
        p = CC.make_plan({"tl": ok, "td": bad, "il": ok, "id": ok})
        self.assertEqual(p["plan"], {"light": "theme", "dark": "dark"})                # جزیرهٔ هم‌قطب (تیره) اگر خوانا است
        p = CC.make_plan({"tl": ok, "td": bad, "il": ok, "id": bad})
        self.assertEqual(p["plan"], {"light": "theme", "dark": "light"})
        # روی روشن نامرئی، روی تیره درست
        p = CC.make_plan({"tl": bad, "td": ok, "il": bad, "id": ok})
        self.assertEqual(p["plan"], {"light": "dark", "dark": "theme"})
        # نرم (۳ تا ۴٫۵) فقط وقتی که حالتِ بی‌هشدار نباشد
        p = CC.make_plan({"tl": soft, "td": ok, "il": ok, "id": soft})
        self.assertEqual(p["plan"]["light"], "light")
        p = CC.make_plan({"tl": soft, "td": soft, "il": soft, "id": soft})
        self.assertEqual(p["plan"], {"light": "theme", "dark": "theme"})
        self.assertTrue(p["ok"])
        # هیچ‌جا خوانا نیست ⇒ درج‌شدنی نیست
        none = CC.make_plan({"tl": bad, "td": bad, "il": bad, "id": bad})
        self.assertEqual(none["plan"], {"light": "", "dark": ""})
        self.assertFalse(none["ok"])

    def test_plan_for_falls_back_to_the_theme_when_nothing_was_measured(self):
        self.assertEqual(CC.plan_for(make_record(), "dark"), "theme")
        self.assertEqual(CC.plan_for(None, "light"), "theme")
        rec = make_record(contrast={"plan": {"light": "theme", "dark": "light"}})
        self.assertEqual(CC.plan_for(rec, "dark"), "light")
        self.assertEqual(CC.plan_for(rec, "light"), "theme")
        rec = make_record(contrast={"plan": {"light": "", "dark": ""}, "best": {"light": "dark", "dark": "theme"}})
        self.assertEqual(CC.plan_for(rec, "light"), "dark")

    def test_measure_reads_the_real_pixels_behind_each_text(self):
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "a.png"
            Image.new("RGB", (400, 200), (255, 255, 255)).save(png)
            items = [{"text": "visible", "color": [17, 24, 39], "alpha": 1, "large": False, "rects": [[10, 10, 100, 20]]},
                     {"text": "white on white", "color": [255, 255, 255], "alpha": 1, "large": False, "rects": [[10, 50, 100, 20]]},
                     {"text": "soft", "color": [140, 140, 140], "alpha": 1, "large": False, "rects": [[10, 90, 100, 20]]},
                     {"text": "faint", "color": [0, 0, 0], "alpha": 0.01, "large": False, "rects": [[10, 130, 100, 20]]}]
            m = CC.measure(items, png)
            self.assertEqual((m["n"], m["hard"], m["soft"]), (3, 1, 1))      # متنِ نیمه‌شفافِ ۱٪ (ظاهر‌شونده با هاور) شمرده نمی‌شود
            self.assertAlmostEqual(m["worst"], 1.0, delta=0.05)
            self.assertEqual(m["samples"][0]["text"], "white on white")
            self.assertIsNone(CC.measure(items, Path(td) / "missing.png"))


# ───────────────────────────── CSSِ سایت‌ساز برای یک قطعه

class EmbedCssTests(DataDirMixin, SimpleTestCase):
    def test_site_classes_cannot_leak_into_the_component(self):
        CV.save_record(make_record())
        css = EM.css_for(["x123456789"], LIGHT)
        self.assertIn('[class*="nbc21-x"] .grid{grid-template-columns:none;gap:normal}', css)      # `.grid` ِ پایهٔ سایت gap و ستون‌های خودکار می‌داد
        self.assertLess(css.index('[class*="nbc21-x"] .grid'), css.index(".nbc21-x123456789 .grid{display:grid}"))        # قطعه دیرتر و هم‌وزن ⇒ برنده
        self.assertEqual(EM.css_for([], LIGHT), "")

    def test_dark_theme_turns_the_dark_variants_on_and_light_keeps_them_off(self):
        css = ".nbc21-x123456789 .dark\\:text-white:where(.dark,.dark *){color:#fff}"
        CV.save_record(make_record(css=css))
        self.assertIn(":where(*)", EM.css_for(["x123456789"], DARK))
        self.assertNotIn(":where(*)", EM.css_for(["x123456789"], LIGHT))
        self.assertNotIn(":where(*)", EM.css_for(["x123456789"], None))

    def test_the_measured_plan_decides_between_theme_and_island(self):
        rec = make_record(contrast={"plan": {"light": "theme", "dark": "light"}, "ctx": {}})
        CV.save_record(rec)
        dark_css = EM.css_for(["x123456789"], DARK)
        self.assertIn(".nbc21-x123456789.nbc21-x123456789{", dark_css)                 # جزیرهٔ روشن روی پوستهٔ تیره
        self.assertIn("--bg:#ffffff", dark_css)
        self.assertNotIn(".nbc21-x123456789.nbc21-x123456789{", EM.css_for(["x123456789"], LIGHT))
        forced = EM.css_for(["x123456789"], LIGHT, {"x123456789": "dark"})
        self.assertIn("--bg:#0b1020", forced)
        self.assertEqual(EM.css_for(["x123456789"], DARK, {"x123456789": "theme"}).count(".nbc21-x123456789.nbc21-x123456789{"), 0)

    def test_island_brand_colour_stays_readable_for_the_project_brand(self):
        CV.save_record(make_record(contrast={"plan": {"light": "dark", "dark": "dark"}}))
        navy = dict(LIGHT, primary="#0a0a2a")
        css = EM.css_for(["x123456789"], navy)
        brand = [x for x in css.split(";") if x.startswith("--brand:")][0].split(":")[1]
        self.assertGreaterEqual(contrast(brand, "#0b1020"), 4.5)

    def test_ai_mode_css_follows_the_style_of_the_project(self):
        CV.save_record(make_record(contrast={"plan": {"light": "theme", "dark": "light"}}))
        html = '<div class="nbc21-x123456789">x</div>'
        dark_style = next(k for k, st in S.STYLES.items() if CC.polarity(st["theme"]["colors"]) == "dark")
        light_style = next(k for k, st in S.STYLES.items() if CC.polarity(st["theme"]["colors"]) == "light")
        self.assertIn(".nbc21-x123456789.nbc21-x123456789{", ai_context.attach_css(html, "", dark_style))
        self.assertNotIn(".nbc21-x123456789.nbc21-x123456789{", ai_context.attach_css(html, "", light_style))
        self.assertNotIn(".nbc21-x123456789.nbc21-x123456789{", ai_context.attach_css(html, ""))        # بی‌سبک ⇒ روشن

    def test_preview_page_honours_colours_and_mode(self):
        CV.save_record(make_record(contrast={"plan": {"light": "theme", "dark": "dark"}}))
        pv = EM.preview_page("x123456789", colors=DARK, mode="light")
        self.assertIn("--bg:#ffffff", pv["css"])
        self.assertNotIn(".nbc21-x123456789.nbc21-x123456789{", EM.preview_page("x123456789", mode="theme")["css"])
        page = c21_rtl.page_for(pv["css"], pv["html"], DARK)
        self.assertIn("--bg:#0f172a", page)
        self.assertIn("--bg:#f7f8fa", c21_rtl.page_for("", "", None))


# ───────────────────────────── سنجشِ مرورگر (ساختگی) و درج‌شدنی‌بودن

NO_IMG = '<div id="c21-root"><section class="p-4"><h2>Big title</h2><p>Some text</p><a href="/x">Go</a></section></div>'


def _png(path, color, size=(1280, 300)):
    from PIL import Image
    Image.new("RGB", size, color).save(path)


def fake_contrast_browser(spec):
    """subprocess.run ِ ساختگی برای rtl_check.py. spec[key] = {ctx: (text_color, bg, occ)} یا 'tiny'؛ rtl.json + فایل‌های <key>~<ctx>.json/png می‌نویسد."""
    def run(cmd, **kw):
        d = Path(cmd[2])
        res = {}
        for f in sorted(d.glob("*.html")):
            if "~" in f.stem:
                key, ctx = f.stem.split("~")
                s = spec.get(key) or {}
                tc, bg, occ = s.get(ctx, ((17, 24, 39), (255, 255, 255), False))
                _png(d / (f.stem + ".png"), bg)
                items = [{"text": "Pricing for teams", "color": list(tc), "alpha": 1, "large": False, "rects": [[40, 40, 200, 24]], "occ": 1 if occ else 0}]
                chars = 3 if s.get("tiny") else 120
                (d / (f.stem + ".json")).write_text(json.dumps({"items": items, "chars": chars, "height": 320 if not s.get("tiny") else 60}), encoding="utf-8")
            else:
                key = f.stem
                for w in (390, 1280):
                    from PIL import Image, ImageDraw
                    im = Image.new("RGB", (400, 200), (0xf7, 0xf8, 0xfa))
                    ImageDraw.Draw(im).rectangle((10, 10, 300, 120), fill=(20, 20, 20))
                    im.save(d / ("%s-%d.png" % (key, w)))
                res[key] = {"status": "ok", "overflow_390": False, "overflow_1280": False, "rtl": True, "text_390": 40, "text_1280": 40, "visual_390": 1, "visual_1280": 1}
        Path(cmd[3]).write_text(json.dumps(res), encoding="utf-8")
        return mock.Mock(returncode=0, stdout="", stderr="")
    return run


class BrowserContrastGateTests(DataDirMixin, Base):
    def convert(self, cid, title, cats=("pricing-section",)):
        rec = CV.convert_bundle(cid, {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [], "source": {"kind": "upstream", "repo": "https://github.com/acme/ui", "license": "MIT"}},
                                meta={"title": title, "license": "mit", "author": "Acme", "library": "[Acme UI](https://21st.dev/@acme/library/acme-ui)", "cats": list(cats)}, runner=FakeNode(html=NO_IMG))
        CV.save_record(rec)
        rows = c21st.load() + [{"id": cid, "title": title, "detail": True, "usable": True, "license": "mit", "cats": list(cats), "conv": {"state": "ok", "key": rec["key"]}}]
        c21st.save(rows)
        return rec

    def run_checks(self, spec_by_key):
        with mock.patch.object(c21_rtl, "available", return_value=(True, "")):
            return c21_rtl.apply(list(spec_by_key), runner=fake_contrast_browser(spec_by_key))

    def test_four_contexts_choose_theme_island_or_block(self):
        white = (255, 255, 255)
        a = self.convert("acme/safe", "Safe Pricing Table")
        b = self.convert("acme/white-card", "White Card")             # متنِ سفید روی کارتِ سفید فقط روی پوستهٔ تیره (و جزیرهٔ تیره)
        c = self.convert("acme/invisible", "Invisible")
        spec = {a["key"]: {},
                b["key"]: {"td": (white, white, False), "id": (white, white, False)},
                c["key"]: {n: (white, white, False) for n in CC.CTX_NAMES}}
        self.run_checks(spec)
        ra, rb, rc = (CV.load_record(x["key"]) for x in (a, b, c))
        self.assertEqual(ra["contrast"]["plan"], {"light": "theme", "dark": "theme"})
        self.assertEqual(ra["rtl"]["status"], "ok")
        self.assertEqual(rb["contrast"]["plan"], {"light": "theme", "dark": "light"})              # روی تیره: جزیرهٔ روشن
        self.assertEqual(rb["rtl"]["status"], "ok")
        self.assertEqual(rc["rtl"]["status"], "fail")
        self.assertTrue(rc["rtl"]["contrast_fail"])
        self.assertIn("هیچ‌گاه خوانا نمی‌شود", rc["rtl"]["why"])
        rows = {r["id"]: r for r in c21st.load()}
        self.assertTrue(c21st.insertable(rows["acme/safe"]) and c21st.insertable(rows["acme/white-card"]))
        self.assertFalse(c21st.insertable(rows["acme/invisible"]), "نخوانا روی هر دو پوسته ⇒ درج‌شدنی نیست")
        self.assertEqual(c21st.kind_of(rows["acme/safe"]), "section")
        self.assertEqual(ra["rtl"]["v"], c21_rtl.CHECK_VERSION)

    def test_tiny_and_overlapping_components_are_closed_with_a_reason(self):
        tiny = self.convert("acme/badge", "Badge")
        over = self.convert("acme/action-bar", "Action Bar")
        fine = self.convert("acme/hero", "Hero", ("hero",))
        spec = {tiny["key"]: {"tiny": True}, over["key"]: {"tl": ((17, 24, 39), (255, 255, 255), True)}, fine["key"]: {}}
        self.run_checks(spec)
        rt, ro, rf = (CV.load_record(x["key"])["rtl"] for x in (tiny, over, fine))
        self.assertEqual((rt["status"], rt["kind"]), ("fail", "tiny"))
        self.assertIn("بی‌متن", rt["why"])
        self.assertEqual(ro["status"], "fail")
        self.assertEqual(ro["overlap"], 1)
        self.assertIn("روی هم", ro["why"])
        self.assertEqual(rf["status"], "ok")
        # و API ِ درج و پیش‌نمایش هر دو ۴۰۹ می‌دهند و علت را می‌گویند (پیش‌تر پیش‌نمایشِ سایت‌ساز ۲۰۰ می‌داد)
        p = self.project("c21-r3")
        for ep in ("block/", "preview/"):
            r = self.c.get("/api/v1/studio/projects/%s/builder/c21/%s/%s" % (p.slug, tiny["key"], ep))
            self.assertEqual(r.status_code, 409, ep)
            self.assertIn("بی‌متن", json.dumps(r.json(), ensure_ascii=False))
        self.assertEqual(self.c.get("/api/v1/studio/projects/%s/builder/c21/%s/preview/" % (p.slug, fine["key"])).status_code, 200)
        self.assertEqual(self.c.get("/api/v1/studio/c21st/preview/%s/" % tiny["key"]).status_code, 409)

    def test_pipeline_counts_separate_converted_from_insertable(self):
        for i, st in enumerate(("ok", "ok", "fail")):
            rec = self.convert("acme/c%d" % i, "C%d" % i)
            rec["rtl"] = {"status": st, "kind": "section"}
            CV.save_record(rec)
        from apps.projects.c21_api import pipeline_json
        out = pipeline_json()
        self.assertEqual((out["converted"], out["insertable"], out["blocked"]), (3, 2, 1))
        self.assertEqual(out["kinds"], {"section": 2, "widget": 0})
        lst = self.c.get("/api/v1/studio/c21st/", {"insertable": 1}).json()
        self.assertEqual(lst["insertable"], 2)
        self.assertEqual(lst["pipeline"]["insertable"], 2)
        only_sections = self.c.get("/api/v1/studio/c21st/", {"insertable": 1, "kind": "widget"}).json()
        self.assertEqual(only_sections["total"], 0)

    def test_library_is_plain_text_everywhere(self):
        rec = self.convert("acme/lib", "Lib")
        self.assertEqual(CV.load_record(rec["key"])["library"], "Acme UI")
        self.assertEqual(CV.load_index()["acme/lib"]["library"], "Acme UI")
        d = self.c.get("/api/v1/studio/c21st/preview/%s/" % rec["key"]).json()
        self.assertNotIn("](", json.dumps(d, ensure_ascii=False))
        b = self.c.get("/api/v1/studio/c21st/block/%s/" % rec["key"]).json()
        self.assertEqual(b["library"], "Acme UI")


# ───────────────────────────── جست‌وجو و فارسی‌کردنِ متن

class PersianSearchTests(DataDirMixin, SimpleTestCase):
    def seed(self):
        rows = []
        for cid, title, cats, tags in (("a/banner-tiers", "Banner Tiers Pricing Table", ["pricing-section"], ["pricing"]), ("a/faq", "FAQ Accordion", ["accordion"], ["faq"]),
                                       ("a/nav", "Navbar Dock", ["navigation"], []), ("a/btn", "Shiny Button", ["button"], []), ("a/foot", "Footer Links", ["footer"], [])):
            rec = make_record(key="x" + ("%09x" % abs(hash(cid)))[:9], cid=cid)
            rec["title"], rec["cats"] = title, cats
            rec["rtl"] = {"status": "ok", "kind": "section", "v": 4}
            CV.save_record(rec)
            rows.append({"id": cid, "title": title, "detail": True, "usable": True, "license": "mit", "cats": cats, "tags": tags, "description": "",
                         "conv": {"state": "ok", "key": rec["key"]}})
        c21st.save(rows)

    def test_persian_queries_find_english_components(self):
        self.seed()
        self.assertIn("pricing", c21st.expand_query("قیمت"))
        self.assertEqual(c21st.expand_query("pricing"), "pricing")                       # متنِ لاتین دست نمی‌خورد
        ids = lambda q: [i["id"] for i in c21st.search(q, insertable_only=True)["items"]]          # noqa: E731
        self.assertEqual(ids("قیمت")[0], "a/banner-tiers")
        self.assertEqual(ids("پرسش‌های متداول")[0], "a/faq")
        self.assertEqual(ids("منوی بالا")[0], "a/nav")
        self.assertEqual(ids("دکمه")[0], "a/btn")
        self.assertEqual(ids("پایین صفحه فوتر")[0], "a/foot")
        self.assertEqual(ids("چیزِ ناشناخته"), [])
        self.assertIn("pricing", c21st.search("قیمت")["query_en"])

    def test_kind_filter_and_section_first_order(self):
        self.seed()
        rows = c21st.load()
        rec = CV.load_record(rows[0]["conv"]["key"])
        rec["rtl"] = {"status": "ok", "kind": "widget", "v": 4}
        CV.save_record(rec)
        out = c21st.search("", insertable_only=True)
        self.assertEqual(out["items"][-1]["kind"], "widget")                              # بخش‌ها اول، ابزارک‌ها آخر
        self.assertEqual(c21st.search("", insertable_only=True, kind="widget")["total"], 1)
        self.assertEqual(c21st.search("", kind="section")["total"], 4)
        self.assertEqual(out["insertable_sections"], 4)


class TranslateTests(DataDirMixin, Base):
    def test_dictionary_translates_ui_chrome_and_leaves_everything_else(self):
        new, n = TR.apply_dictionary(["Get started", "Pricing", "/ mo", "3 projects", "Starter", "Hirael", "pass@1", "$24", "What is your return policy?", "Unlimited projects"])
        self.assertEqual(new[:4], ["شروع کنید", "قیمت‌ها", "/ ماه", "۳ پروژه"])
        self.assertEqual(new[4], "شروع")
        self.assertEqual(new[5:8], ["Hirael", "pass@1", "$24"])                           # نامِ برند، کد و قیمت دست نمی‌خورد
        self.assertEqual(new[9], "پروژهٔ نامحدود")
        self.assertEqual(n, 7)
        self.assertEqual(TR.fa_text("  GET STARTED!  "), "شروع کنید")
        self.assertIsNone(TR.fa_text("Some long marketing sentence nobody translated"))

    def test_ai_translation_returns_the_same_count_or_falls_back_with_a_persian_reason(self):
        texts = ["Hello there friend", "ok", "Build faster"]
        got, info = TR.ai_translate(texts, complete=lambda s, u: json.dumps({"t": ["سلام دوست من", "باشه"]}, ensure_ascii=False))
        self.assertEqual((got, info["ok"], info["translated"]), (["سلام دوست من", "ok", "باشه"], True, 2))      # «ok» کمتر از سه حرف است ⇒ فرستاده نشد
        got, info = TR.ai_translate(texts, complete=lambda s, u: json.dumps({"t": ["فقط یکی"]}, ensure_ascii=False))
        self.assertEqual(got, texts)
        self.assertFalse(info["ok"])
        self.assertTrue(info["message"])

        def boom(system, user):
            raise RuntimeError("HTTP 402 insufficient credit")
        got, info = TR.ai_translate(texts, complete=boom)
        self.assertEqual(got, texts)                                                      # متیس بی‌اعتبار ⇒ هیچ استثنایی، متنِ اصلی می‌ماند
        self.assertFalse(info["ok"])
        self.assertRegex(info["message"], r"[آ-ی]")
        self.assertEqual(TR.ai_translate(["۱۲۳", "https://x.io/a.png"])[1]["translated"], 0)

    def test_block_endpoint_applies_the_dictionary_and_never_fails_on_ai(self):
        rec = CV.convert_bundle("acme/pricing", {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [], "source": {}},
                                meta={"title": "Pricing", "license": "mit", "author": "A", "library": "L", "cats": ["pricing-section"]},
                                runner=FakeNode(html='<div id="c21-root"><section><h2>Pricing</h2><p>Get started</p><p>A long English sentence for you</p></section></div>'))
        CV.save_record(rec)
        p = self.project("c21-tr")
        base = "/api/v1/studio/projects/%s/builder/c21/%s/block/" % (p.slug, rec["key"])
        plain = [t["v"] for t in self.c.get(base).json()["block"]["props"]["texts"]]
        self.assertEqual(plain[:2], ["Pricing", "Get started"])                           # بی‌پارامتر همان‌طور که بود
        d = self.c.get(base, {"fa": 1}).json()
        self.assertEqual([t["v"] for t in d["block"]["props"]["texts"]][:2], ["قیمت‌ها", "شروع کنید"])
        self.assertEqual(d["translated"], 2)
        down = self.c.post(base, {"ai": True}, format="json")                              # زیرِ آزمون AI ِ واقعی نیست ⇒ پیامِ فارسی، ولی بلوک می‌آید
        self.assertEqual(down.status_code, 200)
        self.assertEqual(down.json()["block"]["props"]["texts"][1]["v"], "شروع کنید")
        self.assertFalse(down.json()["ai"]["ok"])
        with mock.patch.object(TR, "ai_translate", return_value=(["قیمت‌ها", "شروع کنید", "جملهٔ انگلیسیِ بلند برای شما"], {"ok": True, "translated": 1, "message": "۱ متن"})):
            up = self.c.post(base, {"ai": True}, format="json").json()
        self.assertEqual(up["block"]["props"]["texts"][2]["v"], "جملهٔ انگلیسیِ بلند برای شما")
        self.assertEqual(up["translated"], 3)


# ───────────────────────────── نوعِ محصول، لایه‌های استودیو، قلم‌ها

class ProductRowTests(SimpleTestCase):
    def test_travel_agency_and_photography_briefs_get_a_product_row(self):
        hint = lambda b: ai_context.uiux_hints(b, "landing").get("product", {}).get("type", "")      # noqa: E731
        self.assertEqual(hint("آژانس مسافرتی"), "Travel/Tourism Agency")
        self.assertEqual(hint("وب‌سایت برای استودیوی عکاسی"), "Photography Studio")
        self.assertEqual(hint("تور گردشگری"), "Travel/Tourism Agency")
        self.assertEqual(ai_context.section_intents("آژانس مسافرتی")[:2], ["gallery", "pricing"])
        self.assertEqual(ai_context.section_intents("عکاسی")[:2], ["gallery", "features"])


class CompositeFontTests(SimpleTestCase):
    def test_monospace_and_pixel_fonts_are_bundled_with_open_licences(self):
        for key in ("plexmono", "pixelfa"):
            self.assertIn(key, T.FONTS)
            for entry in T.FONTS[key]["files"]:
                self.assertTrue(os.path.isfile(os.path.join(T.FONT_DIR, entry[0])), entry[0])
        self.assertEqual(fonts_fa.persian_font("JetBrains Mono"), "plexmono")
        self.assertEqual(fonts_fa.persian_font("Press Start 2P"), "pixelfa")
        self.assertIn("pixelfa", fonts_fa.DECORATIVE)                                      # متنِ بلند با قلمِ پیکسلی نیست
        self.assertEqual(fonts_fa.persian_pair("Press Start 2P", "Press Start 2P")[1], "vazirmatn")
        for lic in ("LICENSE-fontsource-jetbrains-mono.txt", "LICENSE-fontsource-press-start-2p.txt"):
            self.assertIn("Open Font License", open(os.path.join(T.FONT_DIR, lic), encoding="utf-8").read())
        faces, used = T.font_faces({"font_body": "plexmono", "font_head": "plexmono"})
        self.assertIn("jetbrains-mono-latin-400-normal.woff2", faces)
        self.assertIn("ibm-plex-sans-arabic-arabic-400-normal.woff2", faces)               # فارسی همان قلمِ خوانا
        cov = json.load(open(os.path.join(T.FONT_DIR, "coverage.json"), encoding="utf-8"))["fonts"]
        for key in ("plexmono", "pixelfa"):
            self.assertEqual(cov[key]["missing"], "")

    def test_terminal_and_pixel_styles_use_them(self):
        """بازبینیِ ۱۱/۱۷: «Pixel Art» قلمِ پیکسلی و «Terminal CLI» قلمِ تک‌فاصله نداشت (حروفِ لاتین و رقمِ لاتین حالا از آن‌ها می‌آید؛ فارسی همان قلمِ خوانا)."""
        pair = lambda k: (S.STYLES[k]["theme"]["font_head"], S.STYLES[k]["theme"]["font_body"])      # noqa: E731
        self.assertEqual(pair("ux-pixel-art")[0], "pixelfa")
        self.assertNotIn("pixelfa", pair("ux-pixel-art")[1], "متنِ بلند هرگز پیکسلی نیست")
        self.assertEqual(pair("ux-terminal-cli-mobile"), ("plexmono", "plexmono"))
        self.assertEqual(pair("ux-cyberpunk-ui"), ("plexmono", "plexmono"))


class ClassifyTests(SimpleTestCase):
    def test_sections_widgets_and_tiny(self):
        big = {"chars": 140, "height": 360}
        cl = lambda row, **rec: c21_rtl.classify(row, dict({"title": "", "cats": [], "images": []}, **rec))      # noqa: E731
        self.assertEqual(cl(big, title="Banner Tiers Pricing Table", cats=["pricing-section"]), ("section", ""))
        self.assertEqual(cl(big, title="Hero Section 01", cats=["hero"])[0], "section")
        self.assertEqual(cl(big, title="Kbd", cats=["badge"])[0], "widget", "ویترینِ یک ابزارک بخشِ صفحه نیست")
        self.assertEqual(cl(big, title="Number wheel", cats=["animated"])[0], "widget")
        self.assertEqual(cl(big, title="Gradient Button Row", cats=["cta"])[0], "widget", "دورِ ۴: نامِ ابزارک (Button) بر دستهٔ cta می‌چربد؛ پیش‌تر هر قطعهٔ بلندی «بخش» بود")
        self.assertEqual(cl({"chars": 120, "height": 90}, title="Pricing Table", cats=["pricing-section"])[0], "section", "نامِ بخش (قیمت) بر ارتفاع می‌چربد")
        self.assertEqual(cl({"chars": 200, "height": 1400}, title="Label")[0], "widget", "دورِ ۴: ارتفاعِ ۱۴۰۰ (= ارتفاعِ پنجره) دیگر قطعه را «بخش» نمی‌کند")
        self.assertEqual(cl({"chars": 30, "height": 90}, title="Footer Links", cats=["footer"])[0], "widget", "کوتاه ⇒ ابزارک")
        kind, why = cl({"chars": 3, "height": 60}, title="Badge")
        self.assertEqual(kind, "tiny")
        self.assertIn("بی‌متن", why)
        self.assertEqual(cl({"chars": 3, "height": 60}, title="Gallery", images=[{"alt": "x"}])[0], "widget", "تصویر دارد ⇒ بی‌متن نیست")
        self.assertEqual(cl({}, title="x"), ("", ""), "سنجیده‌نشده")
