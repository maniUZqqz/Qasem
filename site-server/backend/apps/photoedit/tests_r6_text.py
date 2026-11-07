"""نوبت ۶ ادیتور عکس: ویژگی‌های متن — زیرخط، خط‌خوردگی، حروفِ بزرگ و متنِ خمیده (warp). بی شبکه."""
import numpy as np
from django.test import SimpleTestCase

from . import layers, textlayer


def txt(**kw):
    d = {"id": "t1", "type": "text", "text": "Hello World", "size": 0.1, "color": "#ffffff", "font": "vazirmatn", "weight": 700, "align": "center",
         "dir": "ltr", "line_height": 1.3, "letter_spacing": 0, "width": 0, "stroke": None, "shadow": None, "box": None}
    d.update(kw)
    return d


def norm(**kw):
    return layers.normalize_layers([{"id": "base", "type": "base"}, txt(**kw)])[1]


def alpha(tile):
    return np.asarray(tile.getchannel("A")).astype(np.float64)


class TextNormalizeTests(SimpleTestCase):
    def test_defaults_and_garbage(self):
        n = norm()
        self.assertEqual((n["underline"], n["strike"], n["caps"], n["warp"]), (False, False, False, None))
        self.assertEqual(norm(warp={"style": "zzz", "amount": 1})["warp"], None)
        self.assertEqual(norm(warp={"style": "arc", "amount": 0})["warp"], None)
        self.assertEqual(norm(warp={"style": "arc", "amount": 9})["warp"], {"style": "arc", "amount": 1.0})
        self.assertEqual(norm(warp={"style": "wave", "amount": -0.4})["warp"], {"style": "wave", "amount": -0.4})
        self.assertTrue(norm(underline=True, strike=True, caps=1)["caps"])


class TextRenderTests(SimpleTestCase):
    W = 1000

    def render(self, **kw):
        tile, pivot = textlayer.render_text(norm(**kw), self.W)
        return tile, pivot

    def test_underline_and_strike_add_pixels_below_and_through(self):
        base, _ = self.render(text="ABC", size=0.12)
        ul, _ = self.render(text="ABC", size=0.12, underline=True)
        st, _ = self.render(text="ABC", size=0.12, strike=True)
        a0, a1, a2 = alpha(base), alpha(ul), alpha(st)
        self.assertEqual(a0.shape, a1.shape)
        self.assertGreater(a1.sum(), a0.sum() * 1.02, "زیرخط پیکسل اضافه می‌کند")
        self.assertGreater(a2.sum(), a0.sum() * 1.02, "خط‌خوردگی پیکسل اضافه می‌کند")
        diff_ul = np.argwhere((a1 > 0) & (a0 == 0))
        diff_st = np.argwhere((a2 > 0) & (a0 == 0))
        self.assertGreater(diff_ul[:, 0].mean(), diff_st[:, 0].mean() + 5, "زیرخط پایین‌تر از خط‌خوردگی است")
        # خطِ زیرین یک ردیفِ پیوسته و تقریباً به پهنای متن است
        rows = (a1 > 0).sum(axis=1)
        self.assertGreater(rows.max(), 0.5 * a1.shape[1] * 0.4)

    def test_caps_matches_uppercase_text_and_ignores_persian(self):
        lo, _ = self.render(text="shop sale", caps=True)
        up, _ = self.render(text="SHOP SALE")
        self.assertTrue(np.array_equal(np.asarray(lo), np.asarray(up)))
        fa_a, _ = self.render(text="حراج ویژه", dir="rtl")
        fa_b, _ = self.render(text="حراج ویژه", dir="rtl", caps=True)
        self.assertTrue(np.array_equal(np.asarray(fa_a), np.asarray(fa_b)), "حروفِ بزرگ فارسی را تغییر نمی‌دهد")
        lines = textlayer.layout(norm(text="abc", caps=True), self.W)
        self.assertEqual(lines["lines"], ["ABC"])
        given = textlayer.layout(norm(text="abc", lines=["abc", "def"], caps=True), self.W)
        self.assertEqual(given["lines"], ["ABC", "DEF"])

    def test_warp_adds_symmetric_margin_keeps_pivot_centered_and_never_clips(self):
        base, p0 = self.render(text="WAVE TEXT", size=0.1)
        for style in textlayer.WARP_STYLES:
            for amount in (0.8, -0.8):
                w, p1 = self.render(text="WAVE TEXT", size=0.1, warp={"style": style, "amount": amount})
                extra = textlayer.warp_extra(style, amount, 0.1 * self.W, base.height)
                self.assertEqual(w.size, (base.width, base.height + 2 * extra), (style, amount))
                self.assertAlmostEqual(p1[1], p0[1] + extra, delta=1e-6)
                a = alpha(w)
                self.assertEqual(a[0].sum() + a[-1].sum(), 0, f"{style} {amount}: متن بریده شد")

    def test_arc_lifts_the_middle_and_sign_flips_it(self):
        def centroid(tile, x0, x1):
            a = alpha(tile)[:, x0:x1]
            ys = np.arange(a.shape[0])[:, None]
            return float((a * ys).sum() / max(1.0, a.sum()))

        plain, _ = self.render(text="ARC ARC ARC", size=0.1)
        up, _ = self.render(text="ARC ARC ARC", size=0.1, warp={"style": "arc", "amount": 0.9})
        down, _ = self.render(text="ARC ARC ARC", size=0.1, warp={"style": "arc", "amount": -0.9})
        extra_u = (up.height - plain.height) // 2
        extra_d = (down.height - plain.height) // 2
        w = plain.width
        mid = (int(w * 0.42), int(w * 0.58))
        edge = (int(w * 0.04), int(w * 0.2))
        shift_up = (centroid(up, *mid) - extra_u) - (centroid(up, *edge) - extra_u)
        shift_down = (centroid(down, *mid) - extra_d) - (centroid(down, *edge) - extra_d)
        self.assertLess(shift_up, -5, "قوسِ مثبت: وسطِ متن بالاتر از کناره‌هاست")
        self.assertGreater(shift_down, 5, "قوسِ منفی: وسطِ متن پایین‌تر از کناره‌هاست")

    def test_bulge_makes_the_middle_taller_and_rise_slopes(self):
        plain, _ = self.render(text="BULGE", size=0.15)
        b, _ = self.render(text="BULGE", size=0.15, warp={"style": "bulge", "amount": 0.9})

        def height_at(tile, x):
            col = alpha(tile)[:, x] > 20
            ys = np.where(col)[0]
            return int(ys.max() - ys.min()) if len(ys) else 0

        w = plain.width
        self.assertGreater(height_at(b, w // 2), height_at(plain, w // 2) * 1.15)
        r, _ = self.render(text="RISE RISE", size=0.1, warp={"style": "rise", "amount": 0.8})
        a = alpha(r)
        ys = np.arange(a.shape[0])[:, None]
        left = (a[:, : a.shape[1] // 4] * ys).sum() / max(1.0, a[:, : a.shape[1] // 4].sum())
        right = (a[:, -a.shape[1] // 4:] * ys).sum() / max(1.0, a[:, -a.shape[1] // 4:].sum())
        self.assertGreater(left - right, 5, "شیبِ مثبت: سمتِ راست بالاتر است")

    def test_warp_params_formula_is_the_documented_one(self):
        import numpy as np

        u = np.array([-1.0, 0.0, 1.0])
        dy, s = textlayer.warp_params("arc", 0.5, u, 100)
        self.assertTrue(np.allclose(dy, [0, -70, 0]) and np.allclose(s, 1))
        dy, s = textlayer.warp_params("bulge", 1.0, u, 100)
        self.assertTrue(np.allclose(s, [1, 1.7, 1]) and np.allclose(dy, 0))
        dy, _ = textlayer.warp_params("rise", 1.0, u, 100)
        self.assertTrue(np.allclose(dy, [100, 0, -100]))
        dy, _ = textlayer.warp_params("wave", 1.0, np.array([-1.0, -0.5, 0.0, 0.5]), 100)
        self.assertTrue(np.allclose(dy, [0, 70, 0, -70], atol=1e-9))

    def test_tile_watermark_with_warp_still_renders(self):
        tile, pivot = self.render(text="SALE", size=0.05, tile={"angle": 20, "gap": 1.5}, warp={"style": "wave", "amount": 0.5})
        self.assertGreater(alpha(tile).sum(), 0)
