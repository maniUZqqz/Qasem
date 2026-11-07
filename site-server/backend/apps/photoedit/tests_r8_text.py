"""دورِ ۸: متنِ عمودی، تراز دوطرفه، تورفتگیِ خطِ اول و متن روی مسیر (سمتِ سرور). بی شبکه، بی هوش مصنوعی."""
import numpy as np
from django.test import SimpleTestCase

from . import layers, textlayer

W = 1000


def text_layer(**kw):
    base = {"id": "base", "type": "base"}
    t = {"id": "t1", "type": "text", "text": "HELLO", "size": 0.08, "color": "#ffffff", "cx": 0.5, "cy": 0.5, "font": "vazirmatn", "weight": 700,
         "align": "left", "dir": "ltr", "stroke": None, "shadow": None} | kw
    return layers.normalize_layers([base, t])[1]


def ink(tile):
    a = np.asarray(tile)[..., 3]
    ys, xs = np.where(a > 40)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int((a > 40).sum())) if len(xs) else None


class VerticalTextTests(SimpleTestCase):
    def test_vertical_lines_helper(self):
        self.assertEqual(textlayer.vertical_lines("ABCD"), ["A", "B", "C", "D"])
        self.assertEqual(textlayer.vertical_lines("A B"), ["A", "", "B"])
        self.assertEqual(textlayer.vertical_lines("A\nB"), ["A", "", "", "B"])
        self.assertEqual(textlayer.vertical_lines("سَلام"), ["سَ", "ل", "ا", "م"], "نشانه‌ها به حرفِ خودشان می‌چسبند")
        self.assertEqual(len(textlayer.vertical_lines("x" * 500)), textlayer.MAX_LINES)

    def test_vertical_layer_is_tall_and_lines_are_characters(self):
        lay = text_layer(vertical=True)
        self.assertTrue(lay["vertical"])
        lo = textlayer.layout(lay, W)
        self.assertEqual(lo["lines"], ["H", "E", "L", "L", "O"])
        tile, _pivot = textlayer.render_text(lay, W)
        l, t, r, b, _n = ink(tile)
        self.assertGreater(b - t, 2.5 * (r - l), "ارتفاع بسیار بیشتر از پهنا")
        flat = textlayer.render_text(text_layer(), W)[0]
        fl, ft, fr, fb, _m = ink(flat)
        self.assertGreater(fr - fl, 2.5 * (fb - ft))


class JustifyIndentTests(SimpleTestCase):
    TXT = "aa bb cc dd ee ff gg hh ii jj kk ll"
    # همهٔ حرف‌ها بالارو (ascender) تا بالای خطِ اول تمامِ پهنای آن را نشان بدهد
    TALL = "bbb hhh ddd kkk lll fff bbb hhh ddd kkk lll fff bbb hhh"

    @staticmethod
    def first_line_extent(tile):
        a = np.asarray(tile)[..., 3]
        ys, _xs = np.where(a > 40)
        band = a[int(ys.min()):int(ys.min() + 0.12 * (ys.max() - ys.min()))]
        xs = np.where(band > 40)[1]
        return int(xs.min()), int(xs.max())

    def test_justify_widens_all_lines_but_the_last_to_the_block(self):
        kw = {"text": self.TALL, "width": 0.28, "size": 0.04}
        plain = textlayer.render_text(text_layer(**kw), W)[0]
        just = textlayer.render_text(text_layer(justify=True, **kw), W)[0]
        pl, pr = self.first_line_extent(plain)
        jl, jr = self.first_line_extent(just)
        self.assertGreater(jr - jl, pr - pl + 20, "تراز دوطرفه پهن‌تر شد")
        self.assertAlmostEqual(jr - jl, 0.28 * W, delta=12)

    def test_justify_is_off_for_vertical_and_without_width(self):
        a = textlayer.render_text(text_layer(text=self.TXT), W)[0]
        b = textlayer.render_text(text_layer(text=self.TXT, justify=True), W)[0]
        self.assertEqual(a.size, b.size)
        self.assertEqual(ink(a), ink(b))

    def test_indent_moves_only_the_first_line(self):
        kw = {"text": "aa bb cc dd ee ff gg hh ii jj kk ll", "width": 0.25, "size": 0.04}
        base = textlayer.render_text(text_layer(**kw), W)[0]
        ind = textlayer.render_text(text_layer(indent=1.5, **kw), W)[0]
        # ردیف‌های بالا (خطِ اول) به راست رفته‌اند؛ ردیف‌های پایین همان‌اند
        ab, ai = np.asarray(base)[..., 3], np.asarray(ind)[..., 3]
        top = slice(0, ab.shape[0] // 4)
        bot = slice(3 * ab.shape[0] // 4, ab.shape[0])
        lb = int(np.where(ab[top] > 40)[1].min())
        li = int(np.where(ai[top] > 40)[1].min())
        self.assertGreaterEqual(li - lb, int(1.5 * 0.04 * W * 0.8))
        self.assertEqual(int(np.where(ab[bot] > 40)[1].min()), int(np.where(ai[bot] > 40)[1].min()))


class TextOnPathTests(SimpleTestCase):
    def path(self, pts, closed=False):
        return {"closed": closed, "pts": [{"x": x, "y": y, "hi": None, "ho": None} for x, y in pts]}

    def test_normalization_keeps_two_points_and_drops_one(self):
        ok = text_layer(tpath=self.path([(-0.2, 0), (0.2, 0.1)], closed=True))
        self.assertEqual(len(ok["tpath"]["pts"]), 2)
        self.assertFalse(ok["tpath"]["closed"], "مسیرِ متن همیشه باز است")
        self.assertIsNone(text_layer(tpath=self.path([(0, 0)]))["tpath"])
        self.assertIsNone(text_layer()["tpath"])
        lay = text_layer(vertical=1, justify="x", indent=99)
        self.assertEqual((lay["vertical"], lay["justify"], lay["indent"]), (True, False, 3.0))

    def test_straight_horizontal_path_keeps_the_text_flat(self):
        flat, _ = textlayer.render_text(text_layer(), W)
        onp, pv = textlayer.render_text(text_layer(tpath=self.path([(-0.3, 0), (0.3, 0)])), W)
        self.assertEqual((pv[0], pv[1]), (onp.width / 2, onp.height / 2), "محور = مرکزِ تایل")
        a, b = ink(flat), ink(onp)
        self.assertAlmostEqual(b[2] - b[0], a[2] - a[0], delta=4)
        self.assertAlmostEqual(b[3] - b[1], a[3] - a[1], delta=4)
        self.assertGreater(b[4], 0.8 * a[4], "جوهر از دست نرفت")

    def test_vertical_path_stands_the_text_up(self):
        onp, _ = textlayer.render_text(text_layer(tpath=self.path([(0, -0.3), (0, 0.3)])), W)
        l, t, r, b, n = ink(onp)
        self.assertGreater(b - t, 1.8 * (r - l), "متن روی مسیرِ عمودی ایستاده است")
        self.assertGreater(n, 200)

    def test_arc_path_bends_the_text(self):
        pts = [(0.3 * np.cos(a), -0.3 * np.sin(a) + 0.15) for a in np.linspace(np.pi, 0, 9)]
        onp, pv = textlayer.render_text(text_layer(text="HELLO WORLD", tpath=self.path([(float(x), float(y)) for x, y in pts])), W)
        flat, _ = textlayer.render_text(text_layer(text="HELLO WORLD"), W)
        a, b = ink(flat), ink(onp)
        self.assertGreater(b[3] - b[1], 2 * (a[3] - a[1]), "ارتفاعِ جعبه به‌خاطرِ قوس زیاد شد")
        self.assertEqual((pv[0], pv[1]), (onp.width / 2, onp.height / 2))

    def test_degenerate_paths_return_the_original_tile(self):
        tile, _pv = textlayer.render_text(text_layer(), W)
        same, pv = textlayer.path_tile(tile, [(0.0, 0.0), (0.0, 0.0)])
        self.assertEqual(same.size, tile.size)
        self.assertEqual(pv, (tile.width / 2, tile.height / 2))
