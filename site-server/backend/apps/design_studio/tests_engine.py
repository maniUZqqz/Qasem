"""موتورِ چیدمان و متن: ارقام و قیمت، شکستنِ خطِ فارسی، Auto Layout (پشته، ردیف، شبکهٔ راست‌به‌چپ، hug/fill، max_w)، وارسیِ صحنه، رنگ و نگهبانِ عدد."""
from django.test import SimpleTestCase

from . import colors, fonts, guard, layout, scene, typeset


class TypesetTests(SimpleTestCase):
    def test_digits_and_prices_are_shown_as_stored(self):
        self.assertEqual(typeset.digits("۱۲ ab 3", "en"), "12 ab 3")
        self.assertEqual(typeset.digits("12 ab 3", "fa"), "۱۲ ab ۳")
        self.assertEqual(typeset.price_text(600000, "IRT"), "۶۰۰٬۰۰۰ تومان")
        self.assertEqual(typeset.price_text(600000, "IRT", "en"), "600,000 تومان")
        self.assertEqual(typeset.price_text(0, "IRT", zero_label="فعلاً بدونِ هزینه"), "فعلاً بدونِ هزینه")
        self.assertEqual(typeset.price_text(None), "")
        self.assertEqual(typeset.price_text(1234.5, "USD", "en"), "1,234.5 دلار")

    def test_persian_text_wraps_to_the_width_and_aligns_right(self):
        lay = typeset.layout_text("چغر دستیار هوش مصنوعیِ مربی‌هاست و برنامه می‌نویسد", size=20, w=140, lh=1.5)
        self.assertGreater(lay["n"], 1)
        self.assertTrue(all(ln["w"] <= 140.1 for ln in lay["lines"]))
        self.assertTrue(all(ln["rtl"] for ln in lay["lines"]))
        for ln in lay["lines"]:                                     # راست‌چین: لبهٔ راستِ خط = لبهٔ راستِ جعبه
            self.assertAlmostEqual(ln["x"] + ln["w"], 140, delta=0.1)
        self.assertAlmostEqual(lay["h"], lay["line_h"] * lay["n"], places=3)

    def test_shrink_then_ellipsis_and_max_lines(self):
        text = "کلمه " * 80
        lay = typeset.layout_text(text, size=20, w=200, h=60, shrink=0.0)
        self.assertTrue(lay["truncated"])
        self.assertTrue(lay["lines"][-1]["t"].endswith("…"))
        shrunk = typeset.layout_text("عنوانی نسبتاً بلند برای جا شدن در یک خط", size=40, w=120, h=60, shrink=0.6, max_lines=1)
        self.assertTrue(shrunk["shrunk"] or shrunk["truncated"])
        two = typeset.layout_text(text, size=16, w=150, max_lines=2)
        self.assertEqual(two["n"], 2)
        self.assertTrue(two["truncated"])

    def test_latin_text_is_left_aligned_and_mixed_text_keeps_rtl_base(self):
        en = typeset.layout_text("Hello world of design", size=18, w=300)
        self.assertFalse(en["lines"][0]["rtl"])
        self.assertAlmostEqual(en["lines"][0]["x"], 0, places=3)
        mixed = typeset.layout_text("سفارش ۵۰ عددی Chagher", size=18, w=300)
        self.assertTrue(mixed["lines"][0]["rtl"])

    def test_justify_stretches_all_but_the_last_line(self):
        lay = typeset.layout_text("این یک متنِ آزمایشی است که باید در چند خط شکسته شود و ترازِ دوطرفه بگیرد تا خط‌ها پر شوند", size=16, w=170, justify=True)
        self.assertGreater(lay["n"], 2)
        first = lay["lines"][0]
        self.assertTrue(first.get("words"))
        self.assertAlmostEqual(min(w["x"] for w in first["words"]), 0, delta=0.2)
        self.assertAlmostEqual(max(w["x"] + w["w"] for w in first["words"]), 170, delta=0.2)
        self.assertFalse(lay["lines"][-1].get("words"))

    def test_measure_is_scale_invariant(self):
        a = typeset.measure("سلام دنیا", "vazirmatn", 400, 10)
        b = typeset.measure("سلام دنیا", "vazirmatn", 400, 40)
        self.assertAlmostEqual(b / a, 4.0, places=3)


class LayoutTests(SimpleTestCase):
    def solve(self, root, width=600, **kw):
        return layout.solve(root, width, ctx=layout.Ctx(prefix="t", **kw))

    def test_vertical_stack_pads_gaps_and_fills_width(self):
        root = {"t": "frame", "dir": "v", "pad": 20, "gap": 10, "fill": "#fff", "children": [{"t": "rect", "h": 30, "fill": "#111"}, {"t": "rect", "h": 50, "fill": "#222"}]}
        els, (w, h) = self.solve(root, 400)
        self.assertEqual((w, h), (400, 20 + 30 + 10 + 50 + 20))
        r1, r2 = els[1], els[2]
        self.assertEqual((r1["x"], r1["y"], r1["w"], r1["h"]), (20, 20, 360, 30))
        self.assertEqual((r2["y"], r2["h"]), (60, 50))

    def test_row_is_right_to_left_and_fill_children_share_the_rest(self):
        root = {"t": "frame", "dir": "h", "gap": 10, "children": [{"t": "rect", "w": 100, "h": 40, "fill": "#111"}, {"t": "rect", "w": "fill", "h": 40, "fill": "#222"},
                                                                  {"t": "rect", "w": "fill", "h": 40, "fill": "#333", "grow": 3}]}
        els, _ = self.solve(root, 600)
        a, b, c = els[0], els[1], els[2]
        self.assertEqual(a["x"] + a["w"], 600)                         # اولی چسبیده به راست
        self.assertLess(b["x"], a["x"])
        free = 600 - 100 - 20
        self.assertAlmostEqual(b["w"], free * 1 / 4, places=2)
        self.assertAlmostEqual(c["w"], free * 3 / 4, places=2)
        self.assertAlmostEqual(c["x"], 0, places=2)

    def test_ltr_row_starts_from_the_left(self):
        root = {"t": "frame", "dir": "h", "rtl": False, "gap": 4, "children": [{"t": "rect", "w": 50, "h": 10}, {"t": "rect", "w": 50, "h": 10}]}
        els, _ = self.solve(root, 300, rtl=False)
        self.assertEqual(els[0]["x"], 0)
        self.assertEqual(els[1]["x"], 54)

    def test_grid_fills_columns_from_the_right_and_rows_take_the_tallest(self):
        kids = [{"t": "rect", "h": 40 + 10 * (i % 2), "fill": "#abc"} for i in range(5)]
        root = {"t": "frame", "dir": "grid", "cols": 3, "gap": 12, "children": kids}
        els, (w, h) = self.solve(root, 600)
        col_w = (600 - 24) / 3
        self.assertAlmostEqual(els[0]["w"], col_w, places=2)
        self.assertAlmostEqual(els[0]["x"], 600 - col_w, places=2)       # اولین کارت: بالا-راست
        self.assertAlmostEqual(els[2]["x"], 0, places=2)
        self.assertEqual(els[3]["y"], els[0]["y"] + 50 + 12)            # ردیفِ دوم زیرِ بلندترین
        self.assertEqual(h, 50 + 12 + 50)

    def test_hug_text_and_wrapping_height(self):
        root = {"t": "frame", "dir": "v", "align": "start", "children": [{"t": "text", "text": "کوتاه", "size": 20, "w": "hug"},
                                                       {"t": "text", "text": "یک متنِ بلند که باید در عرضِ کم چند خط شود و ارتفاعش بیشتر از یک خط باشد", "size": 20, "w": "fill"}]}
        els, (w, h) = self.solve(root, 220)
        short, long_ = els[0], els[1]
        self.assertLess(short["w"], 100)
        self.assertGreater(long_["h"], 2 * 20 * 1.5 - 1)
        self.assertEqual(h, short["h"] + long_["h"])

    def test_max_width_children_are_centered(self):
        root = {"t": "frame", "dir": "v", "children": [{"t": "frame", "dir": "v", "max_w": 300, "w": "fill", "fill": "#eee", "children": [{"t": "rect", "h": 10}]}]}
        els, _ = self.solve(root, 800)
        box = els[0]
        self.assertEqual(box["w"], 300)
        self.assertEqual(box["x"], 250)

    def test_absolute_children_do_not_take_part_in_the_flow_and_behind_goes_first(self):
        root = {"t": "frame", "dir": "z", "children": [{"t": "rect", "w": 100, "h": 100, "fill": "#111", "id": "a"},
                                                       {"t": "rect", "w": 40, "h": 40, "fill": "#f00", "abs": {"x": 5, "y": 6}, "behind": True, "id": "glow"}]}
        els, (w, h) = self.solve(root, 300)
        self.assertEqual(h, 100)
        ids = [e["id"] for e in els]
        glow = next(e for e in els if e["w"] == 40)
        self.assertEqual((glow["x"], glow["y"]), (5, 6))
        self.assertLess(els.index(glow), els.index(next(e for e in els if e["w"] == 100 and e["h"] == 100)))

    def test_vertical_space_between_and_grow(self):
        root = {"t": "frame", "dir": "v", "h": 300, "justify": "between", "children": [{"t": "rect", "h": 20}, {"t": "rect", "h": 20}, {"t": "rect", "h": 20}]}
        els, _ = self.solve(root, 100)
        self.assertEqual([e["y"] for e in els], [0, 140, 280])
        grow = {"t": "frame", "dir": "v", "h": 200, "children": [{"t": "rect", "h": 20}, {"t": "rect", "h": "fill", "grow": 1}]}
        els2, _ = self.solve(grow, 100)
        self.assertEqual(els2[1]["h"], 180)

    def test_node_ids_and_boxes_are_recorded_and_hidden_nodes_skipped(self):
        ctx = layout.Ctx(prefix="z")
        root = {"t": "frame", "dir": "v", "id": "root", "children": [{"t": "rect", "h": 10, "id": "keep"}, {"t": "rect", "h": 10, "id": "gone", "hidden": True}]}
        els, _ = layout.solve(root, 100, ctx=ctx)
        self.assertEqual(len(els), 1)
        self.assertIn("keep", ctx.boxes)
        self.assertNotIn("gone", ctx.boxes)

    def test_unknown_node_type_and_huge_depth_raise(self):
        with self.assertRaises(layout.LayoutError):
            layout.solve({"t": "frame", "children": [{"t": "blob"}]}, 100)
        deep: dict = {"t": "rect", "h": 1}
        for _ in range(40):
            deep = {"t": "frame", "children": [deep]}
        with self.assertRaises(layout.LayoutError):
            layout.solve(deep, 100)


class SceneTests(SimpleTestCase):
    def test_clean_element_drops_junk_and_clamps(self):
        e = scene.clean_element({"id": "a1", "type": "text", "x": 5, "y": 6, "w": 50, "h": 10, "text": "سلام\x00 دنیا  ", "size": 9999, "color": "red", "weight": 999, "evil": "x",
                                 "link": {"url": "javascript:alert(1)"}})
        self.assertEqual(e["text"], "سلام دنیا")
        self.assertEqual(e["size"], 2000)
        self.assertEqual(e["color"], "#000000")
        self.assertEqual(e["weight"], 800)
        self.assertNotIn("evil", e)
        self.assertNotIn("link", e)
        self.assertIsNone(scene.clean_element({"id": "bad id!", "type": "rect"}))
        self.assertIsNone(scene.clean_element({"id": "x", "type": "script"}))
        ok = scene.clean_element({"id": "l", "type": "rect", "x": 0, "y": 0, "w": 5, "h": 5, "link": {"url": "https://example.com"}, "fill": "#fff"})
        self.assertEqual(ok["link"], {"url": "https://example.com"})
        self.assertEqual(ok["fill"], "#ffffff")

    def test_overrides_and_extras_apply_after_the_template(self):
        base = [scene.rect("r", 0, 0, 10, 10, "#111111"), scene.text("t", 0, 0, 50, 10, "قدیمی", size=5, ph=True)]
        out = scene.apply_overrides(base, {"t": {"text": "تازه", "x": 3, "bogus": 1}, "r": {"hidden": True}}, [{"id": "x1", "type": "rect", "x": 1, "y": 1, "w": 2, "h": 2, "fill": "#fff"}])
        self.assertEqual(out[1]["text"], "تازه")
        self.assertEqual(out[1]["x"], 3)
        self.assertFalse(out[1]["ph"])
        self.assertNotIn("bogus", out[1])
        self.assertEqual(out[-1]["id"], "x1")
        page = scene.finalize_page({"id": "p", "w": 100, "h": 100, "elements": out})
        self.assertEqual([e["id"] for e in page["elements"]], ["t", "x1"])               # عنصرِ مخفی حذف شد
        self.assertIn("lay", page["elements"][0])

    def test_finalize_converts_digits_and_dedups_ids(self):
        page = scene.finalize_page({"id": "p", "w": 100, "h": 100, "elements": [scene.text("a", 0, 0, 50, 10, "قیمت 5000"), scene.text("a", 0, 20, 50, 10, "دوم")]}, digits_mode="fa")
        self.assertEqual(page["elements"][0]["text"], "قیمت ۵۰۰۰")
        self.assertEqual(len({e["id"] for e in page["elements"]}), 2)


class ColorAndGuardTests(SimpleTestCase):
    def test_contrast_helpers(self):
        self.assertAlmostEqual(colors.contrast("#000000", "#ffffff"), 21.0, places=1)
        fixed = colors.ensure_contrast("#bbbbbb", "#ffffff")
        self.assertGreaterEqual(colors.contrast(fixed, "#ffffff"), 4.5)
        self.assertEqual(colors.on_color("#126f85"), "#ffffff")

    def test_role_palette_from_brand_and_look(self):
        p = colors.role_palette(["#126f85", "#163f75", "#dbe6ff", "#f7faff", "#1b2b45"])
        self.assertEqual(p["primary"], "#126f85")
        self.assertGreaterEqual(colors.contrast(p["text"], p["bg"]), 4.5)
        self.assertGreaterEqual(colors.contrast(p["muted"], p["bg"]), 4.5)
        look = {"palette": ["#0b1026", "#26408b", "#6c5ce7", "#ffb86b", "#04060f", "#dde6ff"]}
        q = colors.role_palette(["#126f85"], look)
        self.assertEqual(q["primary"], "#26408b")
        dark = colors.role_palette(["#126f85"], dark=True)
        self.assertLess(colors.luminance(dark["bg"]), 0.1)

    def test_guard_finds_invented_numbers_across_digit_systems(self):
        allowed = guard.corpus_numbers("۶۰۰٬۰۰۰ تومان", "بیش از 1,300 حرکت", "۵۰ توکن")
        self.assertEqual(guard.unsupported("قیمت 600000 است", allowed), set())
        self.assertEqual(guard.unsupported("۱۳۰۰ حرکت", allowed), set())
        self.assertEqual(guard.unsupported("رضایتِ ۹۸ درصد", allowed), {"98"})
        self.assertEqual(guard.unsupported("گام ۳ از ۴", allowed), set())        # عددِ یک‌رقمی آزاد است


class FontTests(SimpleTestCase):
    def test_fonts_have_licences_and_files(self):
        cat = fonts.catalogue()
        keys = {f["key"] for f in cat}
        self.assertTrue({"vazirmatn", "estedad"} <= keys)
        for f in cat:
            self.assertEqual(f["license"], "SIL OFL 1.1")
            self.assertTrue(f["weights"], f["key"])
            self.assertIn("Copyright", fonts.license_text(f["key"]))
        files = fonts.license_files({"vazirmatn", "estedad", "nope"})
        self.assertTrue(any(n.startswith("fonts/") and n.endswith(".ttf") for n in files))
        self.assertTrue(any(n.startswith("licenses/") for n in files))
        self.assertEqual(fonts.clean("nope"), "vazirmatn")
