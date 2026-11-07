"""نوبت ۶: تبدیلِ لایه (کجی، پرسپکتیو، تاب) — اندازه‌گیریِ هندسی روی یک مستطیلِ آبی روی بومِ شفاف."""
import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from . import effects


def block(w=200, h=160, box=(60, 50, 140, 110)):
    a = np.zeros((h, w, 4), np.uint8)
    a[box[1]:box[3], box[0]:box[2]] = (30, 60, 220, 255)
    return Image.fromarray(a, "RGBA")


def alpha(im):
    return np.asarray(im)[..., 3].astype(np.float64)


def centroid_x(a, rows):
    sub = a[rows]
    xs = np.arange(sub.shape[1])[None, :]
    return float((sub * xs).sum() / max(1.0, sub.sum()))


def width_at(a, y):
    xs = np.where(a[y] > 128)[0]
    return int(xs.max() - xs.min() + 1) if len(xs) else 0


class TransformEffectTests(SimpleTestCase):
    def run_fx(self, eid, **p):
        out, _e = effects.run(eid, block(), p)
        return out

    def test_skew_moves_top_and_bottom_in_opposite_directions_and_keeps_alpha_clean(self):
        out = self.run_fx("skew_layer", ax=30, ay=0)
        a = alpha(out)
        top = centroid_x(a, slice(50, 62))
        bot = centroid_x(a, slice(98, 110))
        self.assertGreater(abs(top - bot), 25, "کجیِ افقی: بالا و پایین جابه‌جا شدند")
        self.assertLess(a[0, 0] + a[-1, -1], 1.0)
        col = np.asarray(out)
        solid = col[a > 250]
        self.assertTrue((np.abs(solid[:, 2].astype(int) - 220) < 6).all(), "رنگِ لایه هاله نگرفت")
        # کجیِ عمودی: چپ و راست
        out2 = self.run_fx("skew_layer", ax=0, ay=25)
        a2 = alpha(out2)
        ys = np.arange(a2.shape[0])[:, None]
        left = float((a2[:, 60:75] * ys).sum() / max(1.0, a2[:, 60:75].sum()))
        right = float((a2[:, 125:140] * ys).sum() / max(1.0, a2[:, 125:140].sum()))
        self.assertGreater(abs(left - right), 20)

    def test_zero_skew_is_identity(self):
        src = alpha(block())
        out = alpha(self.run_fx("skew_layer", ax=0, ay=0))
        self.assertLess(float(np.abs(out - src).max()), 40.0)          # فقط لبهٔ نیم‌پیکسل
        self.assertEqual(int(out[80, 100]), 255)

    def test_perspective_narrows_the_top_edge(self):
        base_w = width_at(alpha(self.run_fx("perspective_layer", top=0, bottom=0, left=0, right=0)), 52)
        out = alpha(self.run_fx("perspective_layer", top=40, bottom=0, left=0, right=0))
        self.assertLess(width_at(out, 52), base_w * 0.8, "لبهٔ بالا باریک شد")
        self.assertGreaterEqual(width_at(out, 107), base_w * 0.9, "لبهٔ پایین همان ماند")
        wide = alpha(self.run_fx("perspective_layer", top=-30, bottom=0, left=0, right=0))
        self.assertGreater(width_at(wide, 52), base_w * 1.1, "مقدارِ منفی لبه را باز می‌کند")

    def test_perspective_side_edges_close_vertically(self):
        out = alpha(self.run_fx("perspective_layer", top=0, bottom=0, left=40, right=0))
        left = float((out[:, 62:70] > 128).sum(axis=0).mean())
        right = float((out[:, 128:136] > 128).sum(axis=0).mean())
        self.assertLess(left, right * 0.85, "لبهٔ چپ کوتاه‌تر شد")
        wide = alpha(self.run_fx("perspective_layer", top=0, bottom=0, left=-30, right=0))
        self.assertGreater(float((wide[:, 62:70] > 128).sum(axis=0).mean()), right * 1.05, "مقدارِ منفی لبهٔ چپ را بلندتر می‌کند")

    def test_warp_arc_lifts_the_middle_and_bulge_grows_it(self):
        def cy(a, x0, x1):
            sub = a[:, x0:x1]
            ys = np.arange(a.shape[0])[:, None]
            return float((sub * ys).sum() / max(1.0, sub.sum()))

        arc = alpha(self.run_fx("warp_layer", style="arc", amount=100))
        self.assertLess(cy(arc, 95, 105) - cy(arc, 62, 72), -4, "وسطِ قوس بالاتر است")
        neg = alpha(self.run_fx("warp_layer", style="arc", amount=-100))
        self.assertGreater(cy(neg, 95, 105) - cy(neg, 62, 72), 4)
        plain = alpha(self.run_fx("warp_layer", style="bulge", amount=0))
        bul = alpha(self.run_fx("warp_layer", style="bulge", amount=100))
        h_plain = int((plain[:, 100] > 128).sum())
        h_bul = int((bul[:, 100] > 128).sum())
        self.assertGreater(h_bul, h_plain * 1.15)

    def test_all_three_are_registered_and_in_the_persian_group(self):
        for eid in ("skew_layer", "perspective_layer", "warp_layer"):
            e = effects.REGISTRY[eid]
            self.assertEqual(e.kind, "layer")
            self.assertTrue(e.group.startswith("تبدیلِ لایه"))


class FillLayerTests(SimpleTestCase):
    def test_fills_cover_the_whole_canvas_and_ignore_the_input(self):
        src = block()
        for eid in ("fill_solid", "fill_gradient", "fill_pattern"):
            out, e = effects.run(eid, src, {})
            a = np.asarray(out)
            self.assertEqual(a.shape, (160, 200, 4), eid)
            self.assertTrue((a[..., 3] == 255).all(), f"{eid}: کلِ بوم پر است")
            self.assertEqual(e.group, "لایهٔ پرکننده")
        out, _ = effects.run("fill_solid", src, {"color": "#336699"})
        self.assertEqual(tuple(np.asarray(out)[10, 10, :3]), (0x33, 0x66, 0x99))

    def test_gradient_presets_and_directions(self):
        src = block()
        a = np.asarray(effects.run("fill_gradient", src, {"preset": "mono", "kind": "linear", "angle": 0})[0]).astype(int)
        self.assertLess(a[80, 2, 0], 20)                      # چپ سیاه
        self.assertGreater(a[80, -3, 0], 235)                 # راست سفید
        rev = np.asarray(effects.run("fill_gradient", src, {"preset": "mono", "kind": "linear", "angle": 0, "reverse": True})[0]).astype(int)
        self.assertGreater(rev[80, 2, 0], 235)
        vert = np.asarray(effects.run("fill_gradient", src, {"preset": "mono", "kind": "linear", "angle": 90})[0]).astype(int)
        self.assertLess(vert[2, 100, 0], 20)
        self.assertGreater(vert[-3, 100, 0], 235)
        rad = np.asarray(effects.run("fill_gradient", src, {"preset": "mono", "kind": "radial"})[0]).astype(int)
        self.assertLess(rad[80, 100, 0], 10)
        self.assertGreater(rad[0, 0, 0], 230)
        custom = np.asarray(effects.run("fill_gradient", src, {"preset": "custom", "c0": "#ff0000", "c1": "#0000ff", "angle": 0})[0]).astype(int)
        self.assertGreater(custom[80, 2, 0], 200)
        self.assertGreater(custom[80, -3, 2], 200)
        for k in effects.GRADIENT_PRESETS:
            self.assertTrue(k in ("custom", "stops") or effects.GRADIENT_PRESETS[k][1][0][0] == 0.0 and effects.GRADIENT_PRESETS[k][1][-1][0] == 1.0, k)

    def test_pattern_has_two_levels_and_transparent_background_option(self):
        out, _ = effects.run("fill_pattern", block(), {"pattern": "stripes", "scale": 20, "fg": "#ffffff", "bg": "#000000"})
        a = np.asarray(out)
        self.assertEqual(set(np.unique(a[..., 0])), {0, 255})
        t, _ = effects.run("fill_pattern", block(), {"pattern": "dots", "transparent_bg": True})
        al = np.asarray(t)[..., 3]
        self.assertTrue(0 < (al == 255).mean() < 0.6 and (al == 0).any())
        for pat in ("stripes", "dots", "grid", "checker", "diamonds", "waves"):
            o, _ = effects.run("fill_pattern", block(), {"pattern": pat})
            self.assertGreater(len(np.unique(np.asarray(o)[..., 0])), 1, pat)
