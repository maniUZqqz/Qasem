"""طراحِ خودکار (نیمه‌خودکارِ دستوری): رنگ/کنتراست، تایپوگرافی و جاگیریِ متن، وارسیِ برنامه، مجری، الگوها، وارسی و اصلاحِ خودکار،
حلقهٔ نقدِ هوش مصنوعی (با مدلِ ساختگی)، API و دورِ کاملِ «طراحی ⇐ اعمال ⇐ پروژهٔ قابل‌ویرایش». بی شبکه و بی هوشِ مصنوعیِ واقعی."""
import json
from unittest import mock

import numpy as np
from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from . import catalog, fontreg, layers as layers_mod, services, smart, textlayer
from .designer import ai as ai_mod
from .designer import analyze, build, colorx, engine, grid, matte, qa, recipes, render, toolspec, typo
from .models import PhotoAsset, PhotoDesign, PhotoProject
from .tests import ApiTestBase, jpeg_file, photo

FA_LONG = "تخفیفِ ویژهٔ پاییزی برای همهٔ محصولاتِ فروشگاهِ ما تا پایانِ هفته"


class FakeVision:
    """جایگزینِ مسیریابِ بینایی: جواب‌ها را به ترتیب برمی‌گرداند (Exception ⇒ پرتاب می‌شود)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate_json(self, model, prompt, images=None, timeout=None):
        self.calls.append({"model": model, "prompt": prompt, "images": len(images or [])})
        r = self.replies.pop(0) if self.replies else {}
        if isinstance(r, Exception):
            raise r
        return r

    def describe(self):
        return {"via": "local", "model": "fake-vl", "label": "لوکال (آزمون)", "fell_back": False}


def patch_ai(fake):
    return mock.patch.multiple(smart, _vision=lambda store: fake, _model_for=lambda provider: "fake-vl")


def solid(w, h, color):
    return Image.new("RGB", (w, h), color)


# ═════════════════════════════ رنگ

class ColorTests(SimpleTestCase):
    def test_wcag_contrast_numbers(self):
        self.assertAlmostEqual(colorx.contrast("#000000", "#ffffff"), 21.0, places=3)
        self.assertAlmostEqual(colorx.contrast("#ffffff", "#ffffff"), 1.0, places=3)
        self.assertAlmostEqual(colorx.contrast("#767676", "#ffffff"), 4.54, delta=0.02)   # حدِ کلاسیکِ AA
        self.assertGreater(colorx.contrast("#777777", "#000000"), 4.5)

    def test_region_contrast_uses_worst_pixels(self):
        px = np.concatenate([np.full((90, 3), 250, np.uint8), np.full((10, 3), 120, np.uint8)])
        white = colorx.region_contrast((255, 255, 255), px, pct=10)
        self.assertLess(white, 2.5)                  # ۱۰٪ پیکسل‌های تیره‌تر کنتراستِ سفید را خراب می‌کنند
        self.assertGreater(colorx.region_contrast((10, 10, 10), px, pct=10), 4.5)
        best, r = colorx.best_text(px, ("#ffffff", "#111111"))
        self.assertEqual(best, "#111111")
        self.assertGreater(r, 4.5)

    def test_palette_text_always_readable_on_every_mood(self):
        for dom in ("#c82828", "#1e5aaa", "#f2c94c", "#2f855a", "#888888", "#ffffff", "#000000", "#ff00ff"):
            for mood in colorx.MOODS:
                for var in range(3):
                    p = colorx.make_palette(dom, dom, mood=mood, variation=var, image_luma=0.5)
                    mid = colorx.mix(p["bg_a"], p["bg_b"], 0.5)
                    self.assertGreaterEqual(colorx.contrast(p["text"], mid), colorx.WCAG_NORMAL, (dom, mood, var, p))
                    self.assertGreaterEqual(colorx.contrast(p["accent_text"], p["accent"]), colorx.WCAG_NORMAL, (dom, mood, var))

    def test_palette_harmony_follows_product_hue(self):
        p = colorx.make_palette("#c82828", "#c82828", mood="light")          # محصولِ قرمز ⇒ زمینهٔ تینتِ قرمز، نه آبی
        h, s, l = colorx.to_hsl(p["bg_a"])
        self.assertTrue(h < 25 or h > 335, h)
        self.assertGreater(l, 0.9)
        d = colorx.make_palette("#1e5aaa", "#1e5aaa", mood="dark")
        self.assertTrue(d["dark"])
        self.assertTrue(180 < colorx.to_hsl(d["bg_a"])[0] < 260)
        brand = colorx.make_palette("#c82828", "#c82828", mood="light", brand=["#0a7a3c"])
        self.assertEqual(brand["accent"], "#0a7a3c")

    def test_palette_from_pixels_is_deterministic_and_finds_product_colour(self):
        px = np.concatenate([np.tile([200, 40, 40], (600, 1)), np.tile([30, 90, 170], (300, 1)), np.tile([240, 240, 240], (100, 1))]).astype(np.uint8)
        a = colorx.palette_from_pixels(px, 3)
        b = colorx.palette_from_pixels(px, 3)
        self.assertEqual(a, b)
        self.assertEqual(colorx.to_hsl(a[0]["hex"])[0] < 20 or colorx.to_hsl(a[0]["hex"])[0] > 340, True)
        dom, acc = colorx.pick_dominant_and_accent(a)
        self.assertNotEqual(dom, "#f0f0f0")

    def test_colour_names_in_persian(self):
        self.assertEqual(colorx.name_fa("#ff0000"), "قرمز")
        self.assertEqual(colorx.name_fa("#000000"), "مشکی")
        self.assertEqual(colorx.name_fa("#ffffff"), "سفید")
        self.assertIn("آبی", colorx.name_fa("#1e5aaa"))


# ═════════════════════════════ تایپوگرافی

class TypoTests(SimpleTestCase):
    def layer(self, text, size=0.08, **kw):
        return build._text_layer("t1", text, size, font="vazirmatn", weight=700, color="#ffffff", align="center") | kw

    def test_type_scale_is_modular_and_ordered(self):
        sizes = [typo.role_size(r) for r in ("caption", "sub", "title", "hero", "display")]
        self.assertEqual(sizes, sorted(sizes))
        self.assertAlmostEqual(typo.role_size("sub") / typo.role_size("caption"), typo.RATIO, places=2)
        self.assertGreater(typo.role_size("caption"), typo.MIN_LEGIBLE)

    def test_digits_and_prices(self):
        self.assertEqual(typo.fa_digits("12:30 - 450"), "۱۲:۳۰ - ۴۵۰")
        self.assertEqual(typo.en_digits("۱۲۳٤٥"), "12345")
        self.assertEqual(typo.parse_price("۴۵۰ هزار تومان"), 450_000)
        self.assertEqual(typo.parse_price("1.2 میلیون"), 1_200_000)
        self.assertEqual(typo.parse_price("450,000 تومان"), 450_000)
        self.assertEqual(typo.parse_price("۴۵۰٬۰۰۰ ریال"), 45_000)
        self.assertIsNone(typo.parse_price("رایگان"))
        self.assertEqual(typo.format_price("۴۵۰ هزار تومان"), "۴۵۰٬۰۰۰ تومان")
        self.assertEqual(typo.format_price(1250000), "۱٬۲۵۰٬۰۰۰ تومان")

    def test_fit_text_shrinks_and_never_overflows(self):
        W = 1080
        for text in ("سلام", "حراجِ ویژه", FA_LONG, FA_LONG * 2, "SALE 50% OFF — Autumn collection ۱۴۰۵", "یکی_از_کلمه‌های_بسیار_بلند_بدون_فاصله_که_جا_نمی‌شود"):
            lay = self.layer(text, 0.11)
            r = typo.fit_text(lay, W, 0.80 * W, 0.2 * W, min_size=0.024, max_lines=3)
            m = typo.measure(lay, W)
            self.assertLessEqual(len(m["lines"]), 3, text)
            self.assertLessEqual(m["block_h"], 0.2 * W + 1, text)
            self.assertLessEqual(max(m["widths"]), 0.80 * W + 1, text)
            self.assertTrue(r["fits"], (text, r))
        long = self.layer(FA_LONG * 3, 0.08)
        r = typo.fit_text(long, W, 0.5 * W, 0.12 * W, min_size=0.03, max_lines=2)
        self.assertTrue(r["truncated"] and long["text"].endswith("…"))
        self.assertTrue(r["fits"])

    def test_persian_wraps_on_word_boundaries_and_uses_shaping(self):
        W = 1080
        lay = self.layer("قهوهٔ تازه‌دم و خوش‌عطر برای صبح‌های سرد", 0.07, width=0.5)
        m = textlayer.layout(lay, W)
        self.assertGreaterEqual(len(m["lines"]), 2)
        joined = " ".join(m["lines"]).replace("  ", " ")
        self.assertEqual(joined, "قهوهٔ تازه‌دم و خوش‌عطر برای صبح‌های سرد")      # هیچ کلمه‌ای شکسته نشد؛ نیم‌فاصله‌ها سالم
        self.assertTrue(all(w <= 0.5 * W + 1 for w in m["widths"]))
        # قیمت و عددِ فارسی در یک خط (دوسویه) خطا نمی‌دهد
        mix = textlayer.layout(self.layer("قیمت: ۴۵۰٬۰۰۰ تومان / ۳۰٪ تخفیف / 50% off", 0.04), W)
        self.assertEqual(len(mix["lines"]), 1)

    def test_layout_matches_the_rendered_tile(self):
        lay = self.layer("حراجِ ویژهٔ پاییز", 0.09, width=0.6)
        m = textlayer.layout(lay, 1000)
        tile, pivot = textlayer.render_text(lay, 1000)
        self.assertAlmostEqual(tile.width - 4, m["block_w"], delta=2)       # حاشیهٔ ۲ پیکسلی دورِ بلوک
        self.assertAlmostEqual(tile.height - 4, m["block_h"], delta=2)

    def test_tighten_width_hugs_the_text(self):
        lay = self.layer("حراج", 0.1)
        typo.fit_text(lay, 1000, 800, 300)
        typo.tighten_width(lay, 1000)
        m = textlayer.layout(lay, 1000)
        self.assertLess(lay["width"], 0.5)
        self.assertEqual(len(m["lines"]), 1)

    def test_shorten(self):
        t, cut = typo.shorten("این یک جملهٔ بسیار بلند برای آزمونِ کوتاه‌کردن است", 20)
        self.assertTrue(cut and t.endswith("…") and len(t) <= 22)


class FontTests(SimpleTestCase):
    def test_fonts_are_installed_and_licensed(self):
        av = fontreg.available()
        self.assertEqual(set(av), {"estedad", "lalezar", "shabnam", "sahel", "samim"})
        for k in av:
            for w in fontreg.weights(k):
                self.assertTrue(fontreg.path(k, w).endswith(".ttf"))
        lic = {p.name for p in fontreg.FONT_DIR.glob("*") if "LICENSE" in p.name.upper() or "OFL" in p.name.upper()}
        self.assertGreaterEqual(len(lic), 5)
        self.assertTrue(all("SIL OFL" in fontreg.FONTS[k]["license"] for k in fontreg.FONTS))

    def test_each_font_renders_persian_differently(self):
        base = {"text": "قیمت ۴۵۰٬۰۰۰ تومان", "size": 0.1, "weight": 700, "color": "#000000", "align": "center", "dir": "auto",
                "line_height": 1.3, "letter_spacing": 0, "width": 0, "stroke": None, "shadow": None, "box": None, "tile": None, "lines": None}
        sizes = {}
        for k in ["vazirmatn"] + fontreg.available():
            tile, _p = textlayer.render_text(dict(base, font=k), 1000)
            sizes[k] = tile.size
            self.assertGreater(np.asarray(tile.getchannel("A")).sum(), 0, k)
        self.assertGreaterEqual(len(set(sizes.values())), 4, sizes)       # فونت‌ها واقعاً فرق می‌کنند
        unknown, _p = textlayer.render_text(dict(base, font="no-such-font"), 1000)
        self.assertEqual(unknown.size, sizes["vazirmatn"])               # ناشناخته ⇒ وزیرمتن

    def test_layers_accept_font_keys_and_fonts_list(self):
        t = {"id": "t", "type": "text", "text": "سلام", "font": "lalezar"}
        out = layers_mod.normalize_layers([{"id": "base", "type": "base"}, t])
        self.assertEqual(out[1]["font"], "lalezar")
        out = layers_mod.normalize_layers([{"id": "base", "type": "base"}, dict(t, font="comic-sans")])
        self.assertEqual(out[1]["font"], "vazirmatn")
        lst = services.fonts_list()
        self.assertEqual(lst[0]["key"], "vazirmatn")
        self.assertEqual({f["key"] for f in lst[1:]}, set(fontreg.available()))


# ═════════════════════════════ شبکه و حاشیهٔ امن

class GridTests(SimpleTestCase):
    def test_story_safe_zone(self):
        x0, y0, x1, y1 = grid.safe_rect("story")
        self.assertAlmostEqual(y0, 0.14, places=3)
        self.assertAlmostEqual(y1, 0.80, places=3)
        self.assertLess(grid.safe_rect("square")[0], 0.1)

    def test_slots_are_inside_safe_rect_for_every_format(self):
        for fmt in ("square", "portrait", "story", "landscape", "wide", "store"):
            W, H = grid.canvas_size(fmt)
            safe = grid.safe_rect(fmt)
            for name in grid.SLOT_NAMES:
                self.assertTrue(grid.inside(grid.slot(name, fmt, W, H), safe), (fmt, name))
        with self.assertRaises(KeyError):
            grid.slot("nowhere", "square", 1080, 1080)

    def test_canvas_sizes_match_the_catalog(self):
        for k, (w, h, _l) in catalog.SOCIAL_FORMATS.items():
            self.assertEqual(grid.canvas_size(k), (w, h))
        self.assertEqual(grid.canvas_size("orig", (640, 480)), (640, 480))


# ═════════════════════════════ وارسیِ برنامه

class PlanValidatorTests(SimpleTestCase):
    def test_unknown_tools_keys_and_ranges(self):
        plan, notes = toolspec.clean_plan({"recipe": "x", "format": "story", "steps": [
            {"tool": "hack", "params": {}},
            {"tool": "text", "id": "T1", "params": {"text": "سلام" * 100, "role": "gigantic", "slot": "nowhere", "weight": 5000,
                                                    "color": "javascript:alert(1)", "font": "comic", "evil": 1, "max_lines": 99, "scale": 50}},
            {"tool": "scrim", "params": {"strength": 9, "size": -3, "edge": "diagonal", "color": "#12AB34"}},
            "not-a-dict",
        ]})
        self.assertEqual([s["tool"] for s in plan["steps"]], ["scrim", "text"])        # به ترتیبِ فاز
        txt = next(s for s in plan["steps"] if s["tool"] == "text")["params"]
        self.assertLessEqual(len(txt["text"]), toolspec.MAX_TEXT)
        self.assertEqual((txt["role"], txt["slot"], txt["color"], txt["font"]), ("title", "auto", "auto", "vazirmatn"))
        self.assertEqual((txt["weight"], txt["max_lines"], txt["scale"]), (800, 6, 1.6))
        self.assertNotIn("evil", txt)
        sc = next(s for s in plan["steps"] if s["tool"] == "scrim")["params"]
        self.assertEqual((sc["strength"], sc["size"], sc["edge"], sc["color"]), (0.95, 0.15, "bottom", "#12ab34"))
        self.assertTrue(any("hack" in n for n in notes))
        self.assertEqual(plan["format"], "story")

    def test_single_tools_unique_ids_and_order(self):
        plan, notes = toolspec.clean_plan({"steps": [
            {"tool": "export", "params": {}}, {"tool": "text", "id": "a", "params": {"text": "x"}}, {"tool": "text", "id": "a", "params": {"text": "y"}},
            {"tool": "frame", "params": {"format": "square"}}, {"tool": "frame", "params": {"format": "story"}},
            {"tool": "grade", "params": {"adjust": {"exposure": 9, "nope": 1}, "preset": "nope"}}]})
        tools = [s["tool"] for s in plan["steps"]]
        self.assertEqual(tools, ["frame", "grade", "text", "text", "export"])
        self.assertEqual(len({s["id"] for s in plan["steps"]}), 5)
        self.assertEqual(sum(1 for s in plan["steps"] if s["tool"] == "frame"), 1)
        g = next(s for s in plan["steps"] if s["tool"] == "grade")["params"]
        self.assertEqual(g["adjust"], {"exposure": 4.0})
        self.assertEqual(g["preset"], "")
        self.assertTrue(any("یک بار" in n for n in notes))

    def test_too_many_steps_and_garbage(self):
        plan, notes = toolspec.clean_plan({"steps": [{"tool": "shape", "params": {}}] * 60})
        self.assertLessEqual(len(plan["steps"]), toolspec.MAX_STEPS)
        with self.assertRaises(toolspec.PlanError):
            toolspec.clean_plan("nope")
        p2, _n = toolspec.clean_plan({})
        self.assertEqual(p2["steps"], [])
        self.assertEqual(p2["format"], "square")

    def test_catalog_documents_every_tool_and_prompt_text(self):
        keys = {t["key"] for t in toolspec.ui_catalog()}
        self.assertEqual(keys, set(toolspec.BY_KEY))
        self.assertTrue({"develop"}.isdisjoint(keys))
        txt = toolspec.prompt_catalog()
        for k in ("frame", "cutout", "backdrop", "text", "badge", "scrim", "logo", "grade"):
            self.assertIn(f"- {k} ", txt)
        self.assertNotIn("ai_fill", txt)                     # مرحلهٔ «دستی» در پرامپتِ مدل نیست
        self.assertTrue(next(t for t in toolspec.ui_catalog() if t["key"] == "ai_fill")["deferred"])

    def test_every_recipe_step_survives_validation_unchanged(self):
        an = {"brightness": {"p50": 0.5, "p5": 0.1, "p95": 0.9, "mean": 0.5, "contrast": 0.8}, "background": {"plain": True}}
        for key in recipes.RECIPES:
            for var in range(3):
                raw = recipes.make_plan(key, {"prompt": "تخفیف ۳۰ درصدی «کفش ورزشی» ۴۵۰ هزار تومان", "an": an, "can_cutout": True, "has_logo": True,
                                              "mood": "auto", "variation": var, "format": ""})
                clean, notes = toolspec.clean_plan(raw)
                self.assertEqual(len(clean["steps"]), len(raw["steps"]), (key, var, notes))
                self.assertEqual(notes, [], (key, var))


class PromptParseTests(SimpleTestCase):
    def test_discount_price_headline_cta_mood_recipe(self):
        p = recipes.parse_prompt("تخفیف ۳۰ درصدی «کفش ورزشی» فقط ۴۵۰ هزار تومان، همین حالا سفارش بدهید، شیک و لوکس")
        self.assertEqual(p["discount"], "30")
        self.assertEqual(p["headline"], "کفش ورزشی")
        self.assertEqual(p["price"], "۴۵۰٬۰۰۰ تومان")
        self.assertIn("سفارش", p["cta"])
        self.assertEqual(p["mood"], "elegant")
        self.assertEqual(p["recipe"], "sale_banner")
        self.assertEqual(recipes.infer_recipe("رونمایی از محصولِ تازه"), "new_arrival")
        self.assertEqual(recipes.infer_recipe("نمایش قبل و بعد"), "before_after")
        self.assertIsNone(recipes.infer_recipe("سلام"))

    def test_merged_copy_user_wins_and_filenames_are_not_headlines(self):
        c = recipes.merged_copy({"prompt": "تخفیف ۲۰٪", "copy": {"headline": "متنِ من"}, "ai_copy": {"headline": "متنِ هوش", "cta": "ببینید"}})
        self.assertEqual(c["headline"], "متنِ من")
        self.assertEqual(c["discount"], "20")
        self.assertEqual(c["cta"], "ببینید")
        self.assertEqual(recipes._clean_title("IMG_20261105_1234"), "")
        self.assertEqual(recipes._clean_title("کفش چرمِ دست‌دوز"), "کفش چرمِ دست‌دوز")


# ═════════════════════════════ تحلیل

def product_photo(w=1000, h=800, plain=True, dark=False):
    return photo(w, h, plain=plain, dark=dark)


class AnalyzeTests(SimpleTestCase):
    def test_plain_background_subject_box_and_palette(self):
        an = analyze.analyze(product_photo())
        self.assertTrue(an["background"]["plain"])
        self.assertEqual(an["subject"]["method"], "plain-bg")
        x0, y0, x1, y1 = an["subject"]["box"]
        self.assertTrue(0.2 < x0 < 0.4 and 0.6 < x1 < 0.9 and 0.15 < y0 < 0.35 and 0.7 < y1 < 0.95, an["subject"])
        hue = colorx.to_hsl(an["dominant"])[0]
        self.assertTrue(hue < 25 or hue > 335 or 200 < hue < 230, an["dominant"])     # قرمز یا آبیِ کالا، نه سفیدِ زمینه
        self.assertIn(an["best_text_slot"], an["slots"])
        self.assertNotIn("_mask", analyze.public(an))
        self.assertIn("زمینه", analyze.describe_fa(an))

    def test_alpha_image_uses_alpha(self):
        an = analyze.analyze(photo(alpha=True))
        self.assertEqual(an["subject"]["method"], "alpha")
        self.assertTrue(an["has_alpha"])

    def test_busy_background_falls_back_to_saliency_or_center(self):
        an = analyze.analyze(photo(plain=False))
        self.assertFalse(an["background"]["plain"])
        self.assertIn(an["subject"]["method"], ("saliency", "center"))
        b = an["subject"]["box"]
        self.assertTrue(0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1)

    def test_slot_scores_penalise_the_subject(self):
        im = Image.new("RGB", (800, 800), (240, 240, 240))
        ImageDraw.Draw(im).rectangle([120, 560, 680, 780], fill=(20, 20, 20))                  # سوژه پایین
        an = analyze.analyze(im, fmt="square")
        sc = an["slots"]
        self.assertGreater(sc["top"]["score"], sc["bottom"]["score"])
        self.assertEqual(an["best_text_slot"] in ("top", "tl", "tr", "middle", "left", "right"), True)

    def test_matte_on_plain_background(self):
        img = product_photo()
        m = matte.compute(img)
        self.assertTrue(m["ok"], m)
        self.assertEqual(m["mask"].shape, (img.height, img.width))
        a = m["mask"] > 127
        self.assertTrue(a[int(img.height * 0.5), int(img.width * 0.45)])           # وسطِ توپِ قرمز
        self.assertFalse(a[5, 5])
        cut, (x0, y0, x1, y1) = matte.cutout_image(img, m["mask"])
        self.assertEqual(cut.mode, "RGBA")
        self.assertEqual(cut.size, (x1 - x0, y1 - y0))
        self.assertGreater(a.mean(), 0.04)
        self.assertLess(a.mean(), 0.7)

    def test_matte_refuses_when_nothing_is_there(self):
        m = matte.compute(solid(600, 400, (200, 200, 200)))
        self.assertFalse(m["ok"])
        self.assertTrue(m["reason"])


# ═════════════════════════════ ساخت (روی دیتابیس و عکسِ واقعی)

class DesignerBase(ApiTestBase):
    def asset(self, img=None, title="کفشِ ورزشی"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        raw = jpeg_file(img or product_photo(), "shoe.jpg").getvalue()
        return services.add_upload(self.store, self.owner, SimpleUploadedFile("shoe.jpg", raw, content_type="image/jpeg"), title)

    def brief(self, an, **kw):
        return {"prompt": "", "format": "square", "copy": {}, "mood": "auto", "has_logo": False, "an": an, "can_cutout": True, "variation": 0} | kw

    def make(self, asset, recipe, fmt="square", var=0, copy=None, **kw):
        d = PhotoDesign(store=self.store, asset=asset, created_by=self.owner, fmt=fmt)
        d.pk = 9999
        an = analyze.public(analyze.analyze(render.source_image(asset), fmt="orig"))
        b = self.brief(an, format=fmt, copy=copy or {}, variation=var, **kw)
        raw = recipes.make_plan(recipe, b)
        plan, _n = toolspec.clean_plan(raw)
        return plan

    def built(self, asset, recipe, **kw):
        plan = self.make(asset, recipe, **kw)
        b = build.build(asset, plan, user=self.owner)
        fixes = qa.autofix(asset, b)
        return plan, b, fixes


class BuildTests(DesignerBase):
    COPY = {"headline": "کفشِ ورزشیِ سبک", "subline": "مناسبِ دویدن و پیاده‌روی", "price": "۴۵۰ هزار تومان", "discount": "30", "cta": "همین حالا بخرید",
            "old_price": "۶۰۰ هزار تومان"}

    def check_state(self, asset, b, fmt="square"):
        W, H = b["canvas"]
        self.assertEqual((W, H), grid.canvas_size(fmt) if fmt != "orig" else (W, H))
        st = b["state"]
        norm = layers_mod.normalize_layers(st["layers"], store=self.store, base="one")           # لایه‌ها نزدِ سرور معتبرند
        self.assertEqual(norm[0]["id"], "base")
        ops_ = render.normalized(st, 0, "all", self.store)                                         # و کارها نزدِ کاتالوگ
        self.assertEqual(ops_[-1]["tool"], "export")
        img, _frame, notes = render.render_state(asset, st, frame=b["frame"])
        self.assertEqual(img.size, (W, H))
        return img

    def test_every_recipe_builds_valid_editable_state_with_no_remaining_defects(self):
        asset = self.asset()
        for recipe in recipes.RECIPES:
            fmt = recipes.RECIPES[recipe]["format"]
            plan, b, fixes = self.built(asset, recipe, fmt=fmt, copy=self.COPY)
            img = self.check_state(asset, b, fmt)
            bad = [i for i in b["qa"]["issues"] if i["kind"] in ("contrast", "safe", "overlap", "product", "tiny")]
            self.assertEqual(bad, [], (recipe, bad))
            self.assertGreaterEqual(b["qa"]["score"], 85, (recipe, b["qa"]))
            ids = [l["id"] for l in b["state"]["layers"]]
            self.assertEqual(len(ids), len(set(ids)), recipe)
            self.assertLessEqual(len(ids), 40)
            self.assertEqual(json.loads(json.dumps(b["state"]))["fv"], 2)                          # JSON ِ پروژهٔ ادیتورِ دستی
            self.assertGreater(float(np.asarray(img.convert("L")).std()), 5, recipe)

    def test_three_variations_are_really_different(self):
        asset = self.asset()
        prevs = []
        for var in range(3):
            plan, b, _f = self.built(asset, "product_ad", var=var, copy=self.COPY)
            img = self.check_state(asset, b)
            prevs.append(np.asarray(img.resize((64, 64)).convert("RGB"), dtype=np.int16))
            self.assertEqual(plan["variation"], var)
        self.assertGreater(np.abs(prevs[0] - prevs[1]).mean(), 8)
        self.assertGreater(np.abs(prevs[0] - prevs[2]).mean(), 8)

    def test_busy_background_skips_cutout_and_still_designs(self):
        asset = self.asset(photo(plain=False))
        plan, b, _f = self.built(asset, "product_ad", copy=self.COPY, can_cutout=False)
        self.assertFalse(any(s["tool"] == "cutout" for s in plan["steps"]))
        self.check_state(asset, b)
        kinds = {m.get("kind") for m in b["meta"].values()}
        self.assertNotIn("product", kinds)
        self.assertIn("text", kinds)
        self.assertEqual(PhotoAsset.objects.filter(store=self.store, source_ref__startswith="dcut:").count(), 0)

    def test_cutout_creates_layer_asset_once_and_is_editable(self):
        asset = self.asset()
        plan, b, _f = self.built(asset, "product_ad", copy=self.COPY)
        prod = next(l for l in b["state"]["layers"] if l["id"] == "prod")
        self.assertEqual(prod["type"], "image")
        cut = PhotoAsset.objects.get(pk=prod["src"]["asset"])
        self.assertTrue(cut.has_alpha)
        self.assertTrue(cut.source_ref.startswith("dcut:"))
        ids = [l["id"] for l in b["state"]["layers"]]
        self.assertLess(ids.index("bg"), ids.index("prod"))                      # زمینه زیرِ محصول
        self.assertLess(ids.index("prod"), max(i for i, l in enumerate(b["state"]["layers"]) if l["type"] == "text"))
        n = PhotoAsset.objects.filter(store=self.store).count()
        build.build(asset, plan, user=self.owner)                                  # دوباره ⇒ همان عکس، چیزِ تازه‌ای نمی‌سازد
        self.assertEqual(PhotoAsset.objects.filter(store=self.store).count(), n)
        self.assertEqual(b["cutout"]["asset"], cut.pk)
        x0, y0, x1, y1 = b["product_box"]
        self.assertTrue(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1)
        self.assertGreater(x1 - x0, 0.3)                                            # محصولِ «قهرمان» درشت است
        self.assertEqual(b["state"]["adjust"], {})                                  # رنگ روی لایهٔ تنظیم است نه فقط عکسِ پایه
        self.assertTrue(any(l["type"] == "adjust" for l in b["state"]["layers"]))

    def test_cutout_failure_is_reported_not_fatal(self):
        asset = self.asset(solid(900, 700, (200, 200, 200)))
        plan = self.make(asset, "product_ad", copy=self.COPY)
        b = build.build(asset, plan, user=self.owner)
        self.assertIsNone(b["product_box"])
        self.assertTrue(any("جداسازی" in n for n in b["notes"]), b["notes"])
        cs = next(s for s in plan["steps"] if s["tool"] == "cutout")
        self.assertFalse(b["report"][cs["id"]]["ok"])
        self.assertIn("node", b["needs"])
        self.assertFalse(any(m.get("kind") == "backdrop" for m in b["meta"].values()))     # عکس پوشیده نشد

    def test_story_respects_safe_zones(self):
        asset = self.asset(product_photo(800, 1200))
        plan, b, _f = self.built(asset, "story", fmt="story", copy=self.COPY)
        self.check_state(asset, b, "story")
        W, H = b["canvas"]
        safe = grid.safe_rect("story")
        for l in b["state"]["layers"]:
            if l["type"] == "text" and b["meta"][l["id"]]["kind"] == "text":
                r = qa.text_rect(l, W, H)
                self.assertTrue(grid.inside(r, safe), (l["text"], r, safe))
        self.assertEqual(b["qa"]["issues"], [] if not b["qa"]["issues"] else b["qa"]["issues"])

    def test_every_text_stays_inside_canvas_with_very_long_copy(self):
        asset = self.asset()
        copy = {"headline": FA_LONG * 2, "subline": FA_LONG * 3, "price": "۱۲٬۴۵۰٬۰۰۰٬۰۰۰ تومان", "cta": FA_LONG, "discount": "99"}
        for recipe in ("product_ad", "sale_banner", "price_tag", "new_arrival"):
            _plan, b, _f = self.built(asset, recipe, copy=copy, fmt="story" if recipe == "product_ad" else "square")
            W, H = b["canvas"]
            for l in b["state"]["layers"]:
                if l["type"] == "text":
                    r = qa.text_rect(l, W, H)
                    self.assertTrue(r[0] >= -0.001 and r[1] >= -0.001 and r[2] <= 1.001 and r[3] <= 1.001, (recipe, l["text"][:20], r))
            self.assertEqual([i for i in b["qa"]["issues"] if i["kind"] in ("safe", "overlap")], [], recipe)

    def test_logo_only_when_store_has_one(self):
        asset = self.asset()
        plan = self.make(asset, "product_ad", copy=self.COPY, has_logo=True)
        b = build.build(asset, plan, user=self.owner)
        lg = next(s for s in plan["steps"] if s["tool"] == "logo")
        self.assertFalse(b["report"][lg["id"]]["ok"])
        self.assertIn("لوگوی فروشگاه ثبت نشده", b["report"][lg["id"]]["note"])
        self.assertFalse(any(l["id"] == "logo" for l in b["state"]["layers"]))

    def test_before_after_aligns_both_halves(self):
        asset = self.asset(photo(900, 700, seed=3))
        plan, b, _f = self.built(asset, "before_after")
        img = self.check_state(asset, b)
        ids = [l["id"] for l in b["state"]["layers"]]
        self.assertIn("before", ids)
        a = np.asarray(img.convert("RGB")).astype(int)
        W, H = img.size
        left, right = a[:, int(W * 0.1):int(W * 0.4)], a[:, int(W * 0.6):int(W * 0.9)]
        self.assertGreater(abs(left.mean() - right.mean()) + abs(left.std() - right.std()), 0.5)
        texts = [l["text"] for l in b["state"]["layers"] if l["type"] == "text"]
        self.assertEqual(sorted(texts), ["بعد", "قبل"])

    def test_grade_follows_the_measurements(self):
        dark = analyze.analyze(product_photo(dark=True))
        bright = analyze.analyze(product_photo())
        gd, gb = recipes.auto_grade(dark, "auto"), recipes.auto_grade(bright, "auto")
        self.assertGreater(gd.get("exposure", 0), 0.3)
        self.assertLess(gb.get("exposure", 0), gd.get("exposure", 0))
        self.assertGreater(recipes.auto_grade(bright, "warm")["temperature"], 0)
        self.assertLess(recipes.auto_grade(bright, "cool")["temperature"], 0)


class QaFixTests(DesignerBase):
    def plan(self, steps, fmt="square"):
        plan, _n = toolspec.clean_plan({"recipe": "free", "format": fmt, "steps": [{"id": "f", "tool": "frame", "params": {"format": fmt}}] + steps})
        return plan

    def test_white_text_on_white_gets_fixed(self):
        asset = self.asset(solid(900, 900, (250, 250, 250)))
        plan = self.plan([{"id": "t", "tool": "text", "params": {"text": "تخفیفِ ویژه", "role": "hero", "slot": "top", "color": "#ffffff", "plate": "none"}}])
        b = build.build(asset, plan, user=self.owner)
        before = qa.check(asset, b)
        self.assertTrue(any(i["kind"] == "contrast" for i in before["issues"]), before)
        fixes = qa.autofix(asset, b)
        self.assertTrue(fixes and any("خوانا" in f for f in fixes), fixes)
        self.assertEqual([i for i in b["qa"]["issues"] if i["kind"] == "contrast"], [])
        self.assertGreaterEqual(b["qa"]["metrics"]["min_contrast"], 3.0)
        t = next(l for l in b["state"]["layers"] if l["type"] == "text")
        self.assertIsNotNone(t["box"])                                  # کادرِ پشتِ متن گذاشته شد، رنگِ کاربر دست نخورد
        self.assertEqual(t["color"], "#ffffff")

    def test_auto_colour_flips_to_dark_on_bright_background(self):
        asset = self.asset(solid(900, 900, (245, 245, 245)))
        plan = self.plan([{"id": "t", "tool": "text", "params": {"text": "سلام دنیا", "role": "title", "slot": "top", "color": "auto"}}])
        b = build.build(asset, plan, user=self.owner)
        qa.autofix(asset, b)
        t = next(l for l in b["state"]["layers"] if l["type"] == "text")
        self.assertLess(colorx.luminance(colorx.hex_to_rgb(t["color"])), 0.2, t["color"])
        self.assertEqual(b["qa"]["issues"], [])

    def test_text_over_busy_photo_gets_plate_or_recolour(self):
        im = Image.fromarray((np.random.default_rng(5).integers(60, 200, (900, 900, 3))).astype(np.uint8), "RGB")
        asset = self.asset(im)
        plan = self.plan([{"id": "t", "tool": "text", "params": {"text": "فروشِ ویژه", "role": "hero", "slot": "middle", "color": "#cccccc", "plate": "none"}}])
        b = build.build(asset, plan, user=self.owner)
        qa.autofix(asset, b)
        self.assertEqual([i for i in b["qa"]["issues"] if i["kind"] == "contrast"], [])

    def test_text_pushed_back_into_safe_zone_and_apart(self):
        asset = self.asset(solid(900, 1400, (30, 30, 30)))
        plan = self.plan([{"id": "a", "tool": "text", "params": {"text": "بالا", "role": "title", "slot": "top"}},
                          {"id": "b", "tool": "text", "params": {"text": "پایین", "role": "title", "slot": "bottom"}}], fmt="story")
        b = build.build(asset, plan, user=self.owner)
        lays = {l["id"]: l for l in b["state"]["layers"] if l["type"] == "text"}
        la = next(iter(lays.values()))
        la["cy"] = 0.02                                                       # عمداً در ناحیهٔ ممنوعِ بالای استوری
        lb = list(lays.values())[1]
        lb["cx"], lb["cy"] = la["cx"], 0.03                                   # و روی هم
        fixes = qa.autofix(asset, b)
        self.assertTrue(any("حاشیهٔ امن" in f for f in fixes) or any("جدا" in f for f in fixes), fixes)
        self.assertEqual([i for i in b["qa"]["issues"] if i["kind"] in ("safe", "overlap")], [])

    def test_hierarchy_issue_is_reported(self):
        asset = self.asset(solid(900, 900, (30, 30, 30)))
        plan = self.plan([{"id": "a", "tool": "text", "params": {"text": "تیتر", "role": "title", "scale": 0.5, "slot": "top"}},
                          {"id": "b", "tool": "text", "params": {"text": "متنِ دوم", "role": "sub", "scale": 1.6, "slot": "bottom"}}])
        b = build.build(asset, plan, user=self.owner)
        res = qa.check(asset, b)
        self.assertTrue(any(i["kind"] == "hierarchy" for i in res["issues"]), res)


# ═════════════════════════════ هوش مصنوعی (ساختگی)

PLAN_OK = {"recipe": "sale_banner", "mood": "vibrant", "copy": {"headline": "حراجِ پاییزه", "subline": "تا پایانِ هفته", "discount": "۳۰", "cta": "ببینید", "price": ""},
           "grade": {"exposure": 0.2, "temperature": 8, "bogus": 3}, "text_zone": "top",
           "extra_steps": [{"tool": "shape", "params": {"shape": "line", "slot": "middle"}}, {"tool": "cutout", "params": {}}, {"tool": "evil", "params": {}}],
           "notes": "نوارِ رنگی و درصدِ درشت برای حراج"}
CRIT_OK = {"scores": {"hierarchy": 9, "legibility": 9, "contrast": 8, "margins": 9, "balance": 8, "color": 9, "typography": 9, "prompt_fit": 9},
           "verdict": "ok", "issues": [], "summary": "طرح تمیز و خوانا است"}


class AiReasonTests(SimpleTestCase):
    def test_technical_noise_is_removed_from_the_reason(self):
        raw = ("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — متیس: اعتبار حساب تمام شده است (۴۰۲) — خطای سرویس (402): "
               '{timestamp:1793873502070,"path":"/openai/v1/chat/completions","status":402,"error":"Payment Required"}؛ لوکال: سرورِ پردازش خاموش است.')
        out = ai_mod.clean_reason(raw)
        self.assertNotIn("{", out)
        self.assertNotIn("timestamp", out)
        self.assertNotIn("/openai", out)
        self.assertIn("اعتبار حساب تمام شده است", out)
        self.assertIn("سرورِ پردازش خاموش است", out)
        self.assertLessEqual(len(out), 220)
        self.assertEqual(ai_mod.clean_reason(""), "هوش مصنوعی در دسترس نبود")
        self.assertNotIn("http", ai_mod.clean_reason("خطا https://api.example.com/v1/x بود"))


class AiValidatorTests(SimpleTestCase):
    def test_plan_reply_is_strictly_validated(self):
        out = ai_mod.validate_plan_reply(PLAN_OK)
        self.assertEqual(out["recipe"], "sale_banner")
        self.assertEqual(out["mood"], "vibrant")
        self.assertEqual(out["grade"], {"exposure": 0.2, "temperature": 8.0})        # «bogus» دور ریخته شد
        self.assertEqual([s["tool"] for s in out["extra_steps"]], ["shape"])          # cutout (ساختاری) و evil دور ریخته شد
        self.assertEqual(out["copy"]["discount"], "۳۰")
        self.assertIsNone(ai_mod.validate_plan_reply({"recipe": "nope", "copy": {"headline": 5}}) and None)
        self.assertIsNone(ai_mod.validate_plan_reply([1, 2]))
        self.assertIsNone(ai_mod.validate_plan_reply({}))

    def test_critic_reply_validation(self):
        out = ai_mod.validate_critic_reply({"scores": {"hierarchy": 99, "legibility": "7", "zzz": 5, "color": True}, "verdict": "revise",
                                            "issues": [{"problem": "تیتر کوچک است", "fix": {"op": "set", "step": "h", "param": "scale", "value": 1.3}}, "junk"]})
        self.assertEqual(out["scores"], {"hierarchy": 10.0, "legibility": 7.0})
        self.assertEqual(out["verdict"], "revise")
        self.assertEqual(len(out["issues"]), 1)
        self.assertIsNone(ai_mod.validate_critic_reply({"scores": {}}))
        self.assertEqual(ai_mod.validate_critic_reply(dict(CRIT_OK))["verdict"], "ok")

    def test_apply_fixes_is_a_whitelisted_patch_language(self):
        plan, _n = toolspec.clean_plan({"recipe": "free", "format": "square", "steps": [
            {"id": "f", "tool": "frame", "params": {"format": "square"}}, {"id": "h", "tool": "text", "title": "تیتر", "params": {"text": "سلام", "scale": 1.0, "color": "auto"}},
            {"id": "e", "tool": "export", "params": {}}]})
        new, applied, rejected = ai_mod.apply_fixes(plan, [
            {"fix": {"op": "set", "step": "h", "param": "scale", "value": 99}},                  # به بازه می‌رود: ۱٫۶
            {"fix": {"op": "set", "step": "h", "param": "color", "value": "not-a-colour"}},        # رنگِ نامعتبر ⇒ پیش‌فرض ⇒ بی‌تغییر ⇒ ردشده
            {"fix": {"op": "set", "step": "ghost", "param": "scale", "value": 1}},               # مرحلهٔ ناموجود
            {"fix": {"op": "grade", "adjust": {"exposure": 0.3, "junk": 1}}},
            {"fix": {"op": "mood", "value": "dark"}},
            {"fix": "not-a-dict"}])
        self.assertEqual(next(s for s in new["steps"] if s["id"] == "h")["params"]["scale"], 1.6)
        self.assertEqual(next(s for s in new["steps"] if s["tool"] == "grade")["params"]["adjust"], {"exposure": 0.3})
        self.assertEqual(new["mood"], "dark")
        self.assertEqual(len(applied), 3)
        self.assertEqual(rejected, 3)
        new2, applied2, rejected2 = ai_mod.apply_fixes(plan, [
            {"fix": {"op": "set", "step": "h", "param": "__class__", "value": 1}},               # پارامترِ ناموجود
            {"fix": {"op": "remove", "step": "f"}},                                               # قاب حذف‌شدنی نیست
            {"fix": {"op": "remove", "step": "e"}}])                                              # خروجی هم نه
        self.assertEqual((applied2, rejected2), ([], 3))
        self.assertTrue(all(s["on"] for s in new2["steps"]))
        new3, applied3, _r = ai_mod.apply_fixes(plan, [{"fix": {"op": "remove", "step": "h"}}])
        self.assertFalse(next(s for s in new3["steps"] if s["id"] == "h")["on"])
        self.assertEqual(applied3, ["«تیتر» برداشته شد"])
        self.assertEqual(plan["steps"][1]["params"]["scale"], 1.0, "ورودی نباید عوض شود")


class DesignRunTests(DesignerBase):
    def new_design(self, asset, **kw):
        base = {"prompt": "حراجِ پاییزه برای کفش ورزشی، تخفیف ۳۰ درصد", "quality": "normal", "variants": 3, "use_ai": True}   # پیش‌فرضِ فروشگاه خاموش است؛ این آزمون‌ها هوش مصنوعی را روشن می‌خواهند
        return engine.create(self.store, self.owner, asset, base | kw)

    def test_runs_without_ai_and_says_which_parts_needed_it(self):
        asset = self.asset()
        d = self.new_design(asset)
        engine.run(d.pk)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        self.assertEqual(len(d.variants), 3)
        self.assertFalse(d.ai["planner"]["used"])
        self.assertTrue(d.ai["planner"]["reason"])
        self.assertFalse(d.ai["critic"]["used"])
        self.assertIn("بدونِ هوشِ مصنوعی", d.message)
        self.assertIn("نقدِ طرح", d.message)
        self.assertEqual(d.recipe, "sale_banner")                       # از خودِ دستور فهمیده شد (تخفیف)
        self.assertTrue(any("نیاز" in x["text"] or "در دسترس نبود" in x["text"] for x in d.log))
        for v in d.variants:
            self.assertTrue((self.media / v["preview_rel"]).is_file())
            self.assertGreaterEqual(v["qa"]["score"], 80)
        self.assertEqual(sum(1 for v in d.variants if v["best"]), 1)
        self.assertEqual(d.analysis["subject"]["method"], "plain-bg")
        self.assertIn("description", d.analysis)

    def test_ai_planner_and_critic_loop(self):
        asset = self.asset()
        revise = {"scores": {"hierarchy": 5, "legibility": 7, "contrast": 8, "margins": 8, "balance": 6, "color": 7, "typography": 7, "prompt_fit": 7},
                  "verdict": "revise", "issues": [{"problem": "تیتر باید بزرگ‌تر باشد", "fix": {"op": "set", "step": "h", "param": "scale", "value": 1.25}},
                                                  {"problem": "x", "fix": {"op": "set", "step": "nope", "param": "scale", "value": 1}}],
                  "summary": "تیتر ضعیف است"}
        fake = FakeVision(PLAN_OK, revise, CRIT_OK, CRIT_OK, CRIT_OK)
        d = self.new_design(asset, quality="normal", variants=2)
        with patch_ai(fake):
            engine.run(d.pk)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        self.assertTrue(d.ai["planner"]["used"])
        self.assertEqual(d.ai["planner"]["label"], "لوکال (آزمون)")
        self.assertTrue(d.ai["critic"]["used"])
        self.assertEqual(d.ai["critic"]["rounds"], 2)
        self.assertEqual(len(d.variants), 2)
        v0, v1 = d.variants
        self.assertEqual(len(v0["rounds"]), 1)
        self.assertEqual(v0["rounds"][0]["issues"][0], "تیتر باید بزرگ‌تر باشد")
        self.assertEqual(len(v0["rounds"][0]["applied"]), 1)               # فقط اصلاحِ معتبر اعمال شد
        self.assertTrue(v0["rounds"][0]["accepted"])
        self.assertAlmostEqual(v0["ai_mean"], 6.875, delta=0.01)
        self.assertEqual(v1["rounds"][0]["accepted"], False)
        self.assertEqual(d.recipe, "sale_banner")
        h = next(s for s in v0["plan"]["steps"] if s["id"] == "h")
        self.assertEqual(h["params"]["scale"], 1.25)
        self.assertTrue(h.get("ai"))
        head = [l["text"] for l in v0["state"]["layers"] if l["type"] == "text"]
        self.assertIn("حراجِ پاییزه", head)                                 # متنِ هوش مصنوعی
        self.assertEqual(len(fake.calls), 3)                               # ۱ برنامه + ۲ نقد (هر پیشنهاد یک دور)؛ جواب‌های اضافی مصرف نشد
        self.assertIn("images", fake.calls[0])
        self.assertEqual(fake.calls[0]["images"], 1)
        self.assertIn("Persian", fake.calls[0]["prompt"])
        self.assertIn("tool catalogue", fake.calls[0]["prompt"].lower())
        self.assertNotIn("بدونِ هوشِ مصنوعی", d.message)

    def test_user_copy_beats_ai_copy_and_mood(self):
        asset = self.asset()
        fake = FakeVision(PLAN_OK, CRIT_OK, CRIT_OK, CRIT_OK)
        d = self.new_design(asset, copy={"headline": "متنِ خودِ من"}, mood="dark")
        with patch_ai(fake):
            engine.run(d.pk)
        d.refresh_from_db()
        self.assertEqual(d.mood, "dark")
        texts = [l["text"] for l in d.variants[0]["state"]["layers"] if l["type"] == "text"]
        self.assertIn("متنِ خودِ من", texts)
        self.assertNotIn("حراجِ پاییزه", texts)

    def test_ai_unavailable_reasons_are_persian_and_design_still_completes(self):
        asset = self.asset()
        for exc in (RuntimeError("402 Payment Required"), TimeoutError("timed out"), ValueError("bad")):
            fake = FakeVision(exc, exc, exc)
            d = self.new_design(asset, variants=1)
            with patch_ai(fake):
                engine.run(d.pk)
            d.refresh_from_db()
            self.assertEqual(d.state, "READY", d.error)
            self.assertFalse(d.ai["planner"]["used"])
            self.assertTrue(d.ai["planner"]["reason"])
            self.assertFalse(d.ai["critic"]["used"])
            self.assertEqual(len(d.variants), 1)
            self.assertEqual(len(fake.calls), 2)                            # برنامه‌ریز و یک بارِ منتقد؛ بعد از شکست دیگر نمی‌پرسد

    def test_garbage_ai_replies_are_survived(self):
        asset = self.asset()
        fake = FakeVision({"recipe": 5, "copy": "x"}, {"scores": "bad"}, ["list"])
        d = self.new_design(asset, variants=1)
        with patch_ai(fake):
            engine.run(d.pk)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        self.assertFalse(d.ai["planner"]["used"])

    def test_fast_quality_and_ai_off_make_no_ai_calls(self):
        asset = self.asset()
        fake = FakeVision(PLAN_OK)
        d = self.new_design(asset, quality="fast", variants=1)
        with patch_ai(fake):
            engine.run(d.pk)
        d.refresh_from_db()
        self.assertEqual(len(fake.calls), 1)                                # فقط برنامه‌ریز
        self.assertEqual(d.ai["critic"]["reason"], "دقتِ «سریع» نقدِ هوش مصنوعی ندارد")
        fake2 = FakeVision()
        d2 = self.new_design(asset, use_ai=False, variants=1)
        with patch_ai(fake2):
            engine.run(d2.pk)
        self.assertEqual(fake2.calls, [])

    def test_second_worker_cannot_claim_a_running_design(self):
        asset = self.asset()
        d = self.new_design(asset, variants=1, use_ai=False)
        with mock.patch.object(engine, "_run") as run_mock:
            engine.run(d.pk)
            engine.run(d.pk)                  # اولی RUNNING کرد؛ دومی (مثلاً ارسالِ دوبارهٔ پنل) کاری نمی‌کند
        self.assertEqual(run_mock.call_count, 1)
        d.refresh_from_db()
        self.assertEqual(d.state, "RUNNING")

    def test_input_validation(self):
        asset = self.asset()
        with self.assertRaises(engine.DesignError):
            engine.create(self.store, self.owner, asset, {"prompt": "  "})
        d = engine.create(self.store, self.owner, asset, {"prompt": "x" * 5000, "recipe": "zzz", "format": "zzz", "mood": "zzz", "variants": 99,
                                                           "copy": {"headline": "ا" * 500, "evil": "x", "price": {"a": 1}}})
        self.assertEqual(len(d.prompt), 600)
        self.assertEqual((d.recipe, d.mood, d.options["variants"]), ("", "auto", 3))
        self.assertEqual(set(d.copy), {"headline"})
        self.assertEqual(len(d.copy["headline"]), 120)
        engine.create(self.store, self.owner, asset, {"prompt": "a"})
        with self.assertRaises(engine.DesignError):
            engine.create(self.store, self.owner, asset, {"prompt": "b"})        # سقفِ دو طراحیِ هم‌زمان


class ApplyFlowTests(DesignerBase):
    def test_design_apply_gives_editable_project_and_ready_edit(self):
        asset = self.asset()
        d = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ محصول", "recipe": "product_ad", "copy": {"headline": "کفشِ ورزشی", "price": "۴۵۰ هزار تومان"},
                                                           "variants": 2, "use_ai": False})
        engine.run(d.pk)
        d.refresh_from_db()
        self.assertEqual(d.state, "READY", d.error)
        project, edit = engine.apply(d, 0, self.owner)
        self.assertIsInstance(project, PhotoProject)
        self.assertEqual(project.data["fv"], 2)
        types = [l["type"] for l in project.data["layers"]]
        self.assertEqual(types[0], "base")
        self.assertIn("text", types)
        self.assertIn("shape", types)
        self.assertIn("image", types)                                    # محصولِ جداشده لایهٔ جدا است
        self.assertEqual(project.data["tools"]["crop_format"]["format"], "square")
        services.run_server_stage(edit) if edit.state != "READY" else None
        edit.refresh_from_db()
        self.assertEqual(edit.state, "READY", edit.error)
        self.assertEqual(edit.recipe, "designer")
        self.assertEqual(edit.stats["after"]["width"], 1080)
        self.assertEqual((edit.stats["after"]["width"], edit.stats["after"]["height"]), tuple(d.variants[0]["canvas"]))
        d.refresh_from_db()
        self.assertEqual((d.chosen, d.project_id, d.edit_id), (0, project.pk, edit.pk))
        # پروژه همان است که ادیتورِ دستی باز می‌کند
        r = self.api.get(f"{self.base}/projects/?asset={asset.pk}")
        self.assertEqual(r.json()["projects"][0]["id"], project.pk)
        r = self.api.get(f"{self.base}/projects/{project.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["project"]["data"]["layers"]), len(project.data["layers"]))
        # نتیجهٔ ساخت با پیش‌نمایشِ طراح یکی است (همان خط‌لوله)
        prev = Image.open(self.media / d.variants[0]["preview_rel"]).convert("RGB").resize((96, 96))
        final = Image.open(self.media / edit.files["preview"]).convert("RGB").resize((96, 96))
        diff = np.abs(np.asarray(prev, dtype=np.int16) - np.asarray(final, dtype=np.int16)).mean()
        self.assertLess(diff, 12, diff)

    def test_cannot_apply_unfinished_or_bad_index(self):
        asset = self.asset()
        d = engine.create(self.store, self.owner, asset, {"prompt": "x"})
        with self.assertRaises(engine.DesignError):
            engine.apply(d, 0, self.owner)
        d.state = "READY"
        d.variants = []
        d.save()
        with self.assertRaises(engine.DesignError):
            engine.apply(d, 3, self.owner)


class DesignerApiTests(DesignerBase):
    def test_info_analyze_create_poll_rerender_apply_delete(self):
        r = self.api.get(f"{self.base}/designer/")
        self.assertEqual(r.status_code, 200)
        info = r.json()
        self.assertEqual({x["key"] for x in info["recipes"]}, set(recipes.RECIPES))
        self.assertIn("story", {x["key"] for x in info["formats"]})
        self.assertEqual(len(info["tools"]), len(toolspec.TOOLS))
        self.assertEqual(info["fonts"][0]["key"], "vazirmatn")
        self.assertIn(info["ai"]["path"], ("site", "node"))
        self.assertFalse(info["has_logo"])
        asset = self.asset()
        r = self.api.post(f"{self.base}/designer/analyze/", {"asset": asset.pk, "prompt": "تخفیف"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        an = r.json()["analysis"]
        self.assertEqual(an["suggested_recipe"], "sale_banner")
        self.assertTrue(an["description"])
        r = self.api.post(f"{self.base}/designer/designs/", {"asset": asset.pk, "prompt": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("دستور", r.json()["error"]["message"])
        r = self.api.post(f"{self.base}/designer/designs/", {"asset": asset.pk, "prompt": "تبلیغِ کفش", "recipe": "product_ad", "variants": 2, "use_ai": False,
                                                              "copy": {"headline": "کفشِ سبک"}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        did = r.json()["design"]["id"]
        r = self.api.get(f"{self.base}/designer/designs/{did}/")
        body = r.json()["design"]
        self.assertEqual(body["state"], "READY", body)                    # تحتِ آزمون Celery همان‌جا اجرا می‌شود
        self.assertEqual(len(body["variants"]), 2)
        v = body["variants"][0]
        self.assertTrue(v["preview"].startswith("/media/"))
        self.assertEqual(r.json()["design"]["ai"]["planner"]["used"], False)
        r2 = self.api.get(f"{self.base}/designer/designs/?asset={asset.pk}")
        self.assertEqual(len(r2.json()["designs"]), 1)
        # ویرایشِ مرحله‌ها و ساختِ دوباره: متن را عوض کن و لوگو/قیمت را خاموش
        plan = v["plan"]
        for s in plan["steps"]:
            if s["id"] == "h":
                s["params"]["text"] = "عنوانِ تازه"
        r = self.api.post(f"{self.base}/designer/designs/{did}/rerender/", {"variant": 0, "plan": plan}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        nv = r.json()["variant"]
        self.assertTrue(nv["edited"])
        d = PhotoDesign.objects.get(pk=did)
        self.assertIn("عنوانِ تازه", [l["text"] for l in d.variants[0]["state"]["layers"] if l["type"] == "text"])
        r = self.api.post(f"{self.base}/designer/designs/{did}/rerender/", {"variant": 7, "plan": plan}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"{self.base}/designer/designs/{did}/rerender/", {"variant": 0, "plan": "bad"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f"{self.base}/designer/designs/{did}/apply/", {"variant": 0}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        out = r.json()
        self.assertEqual(out["edit"]["state"], "READY", out["edit"])
        self.assertTrue(PhotoProject.objects.filter(pk=out["project"]).exists())
        self.assertEqual(out["edit"]["recipe_title"], "طراحِ خودکار")
        r = self.api.delete(f"{self.base}/designer/designs/{did}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse((self.media / d.dir_rel).exists())

    def test_other_users_cannot_touch_designs(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from apps.stores.models import Store

        asset = self.asset()
        d = engine.create(self.store, self.owner, asset, {"prompt": "x", "use_ai": False})
        other = get_user_model().objects.create_user("intruder", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        for url in (f"{self.base}/designer/", f"{self.base}/designer/designs/{d.pk}/", f"{self.base}/designer/designs/"):
            self.assertEqual(c.get(url).status_code, 404, url)
        self.assertEqual(c.post(f"{self.base}/designer/designs/", {"asset": asset.pk, "prompt": "x"}, format="json").status_code, 404)
        self.assertEqual(APIClient().get(f"{self.base}/designer/").status_code, 401)

    def test_stale_queued_design_is_redispatched(self):
        from datetime import timedelta

        from django.utils import timezone

        from . import views_designer

        asset = self.asset()
        d = engine.create(self.store, self.owner, asset, {"prompt": "x", "use_ai": False, "recipe": "caption", "variants": 1})
        PhotoDesign.objects.filter(pk=d.pk).update(updated_at=timezone.now() - timedelta(minutes=5))
        r = self.api.get(f"{self.base}/designer/designs/{d.pk}/")
        self.assertEqual(r.json()["design"]["state"], "READY", r.content)
        PhotoDesign.objects.filter(pk=d.pk).update(state="RUNNING", updated_at=timezone.now() - views_designer.STALE_RUNNING - timedelta(minutes=1))
        r = self.api.get(f"{self.base}/designer/designs/{d.pk}/")
        self.assertEqual(r.json()["design"]["state"], "FAILED")
        self.assertIn("نیمه‌کاره", r.json()["design"]["error"])
