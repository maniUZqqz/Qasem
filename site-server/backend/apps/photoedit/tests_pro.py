"""ادیتورِ حرفه‌ای: develop_np (پورتِ کیت)، لایه‌ها و ترکیب، پروژه/ماسک، پیش‌تنظیم و اعمالِ گروهی، پیش‌نمایشِ دقیق (با گرهٔ
ساختگی)، انتخابِ سوژه و یک دورِ کاملِ «پروژه ⇐ ساخت ⇐ نسخهٔ آماده». بی شبکه و بی هوشِ مصنوعی."""
import io
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
from django.core.files import File
from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode

from . import blend, catalog, develop_np, layers, ops, services, textlayer
from .models import PhotoAsset, PhotoEdit, PhotoPreset, PhotoProject
from .tests import ApiTestBase, jpeg_file, photo


def solid(w, h, color):
    return Image.new("RGB", (w, h), color)


def ctx(**kw):
    return {"notes": [], "store_name": "x", "logo_path": lambda p: None, "mask_path": lambda pid, mid: None,
            "scale": 1.0} | kw


def base_layer(**kw):
    return {"id": "base", "type": "base"} | kw


def px(img, x, y):
    return tuple(int(v) for v in np.asarray(img.convert("RGB"))[y, x])


def png_bytes(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


# ═════════════════════════════ develop_np

class DevelopNpTests(SimpleTestCase):
    def grad(self, h=120, w=160):
        g = np.tile(np.linspace(0.02, 0.98, w, dtype=np.float32), (h, 1))
        return np.stack([g, g * 0.8, g * 0.6], axis=2).astype(np.float32)

    def test_neutral_is_identity_and_input_untouched(self):
        a = self.grad()
        b = a.copy()
        out = develop_np.develop(a, {}, None)
        self.assertEqual(float(np.abs(out - a).max()), 0.0)
        out2 = develop_np.develop(a, {"exposure": 1}, None)
        self.assertTrue(np.array_equal(a, b), "ورودی نباید عوض شود")
        self.assertGreater(float(out2.mean()), float(a.mean()))
        self.assertEqual(out2.dtype, np.float32)

    def test_exposure_plus_one_doubles_linear_light(self):
        a = np.full((20, 20, 3), 0.2, np.float32)
        out = develop_np.develop(a, {"exposure": 1}, None)
        expect = (0.2 ** 2.2 * 2) ** (1 / 2.2)
        self.assertAlmostEqual(float(out[5, 5, 0]), expect, delta=0.004)
        dark = develop_np.develop(a, {"exposure": -1}, None)
        self.assertAlmostEqual(float(dark[5, 5, 1]), (0.2 ** 2.2 / 2) ** (1 / 2.2), delta=0.004)

    def test_white_balance_direction(self):
        a = np.full((10, 10, 3), 0.5, np.float32)
        warm = develop_np.develop(a, {"temperature": 60}, None)
        self.assertGreater(float(warm[0, 0, 0]), float(warm[0, 0, 2]) + 0.05)
        cool = develop_np.develop(a, {"temperature": -60}, None)
        self.assertGreater(float(cool[0, 0, 2]), float(cool[0, 0, 0]) + 0.05)
        magenta = develop_np.develop(a, {"tint": 60}, None)
        self.assertLess(float(magenta[0, 0, 1]), float(magenta[0, 0, 0]))
        # روشناییِ کلی ثابت می‌ماند
        lum = lambda p: 0.2126 * p[0, 0, 0] + 0.7152 * p[0, 0, 1] + 0.0722 * p[0, 0, 2]
        self.assertAlmostEqual(float(lum(warm)), 0.5, delta=0.05)

    def test_gains_are_the_kit_formulas(self):
        gb, gg, gr = develop_np.white_balance_gains(0, 0)
        self.assertAlmostEqual(gb, 1.0, places=6)
        self.assertAlmostEqual(gr, 1.0, places=6)
        gb, gg, gr = develop_np.white_balance_gains(100, 0)
        self.assertAlmostEqual(gr / gb, np.exp(1.2), places=5)     # ±۱۰۰ ⇒ نسبتِ ×۳٫۳

    def test_base_lut_monotone_and_curves(self):
        P = develop_np._P({"contrast": 60, "brightness": 20, "blacks": -30, "whites": 30, "levelsGamma": 1.3})
        lut, identity = develop_np.build_base_lut(P)
        self.assertFalse(identity)
        self.assertTrue((np.diff(lut) >= -1e-9).all(), "منحنیِ پایه یکنوا نیست")
        self.assertEqual(len(lut), 4097)
        f = develop_np._spline([[0, 0], [64, 40], [192, 220], [255, 255]])
        y = f(np.linspace(0, 1, 500))
        self.assertTrue((np.diff(y) >= -1e-9).all())
        self.assertAlmostEqual(float(f(np.array([0.0]))[0]), 0.0, places=6)
        self.assertAlmostEqual(float(f(np.array([1.0]))[0]), 1.0, places=6)
        # منحنیِ RGB ِ روشن‌کننده
        a = np.full((8, 8, 3), 0.25, np.float32)
        out = develop_np.develop(a, {}, {"rgb": [[0, 0], [64, 128], [255, 255]]})
        self.assertAlmostEqual(float(out[0, 0, 0]), 128 / 255, delta=0.01)
        red = develop_np.develop(a, {}, {"red": [[0, 0], [64, 128], [255, 255]]})
        self.assertGreater(float(red[0, 0, 0]), float(red[0, 0, 1]) + 0.2)

    def test_levels_blacks_whites(self):
        a = np.full((4, 4, 3), 0.1, np.float32)
        self.assertAlmostEqual(float(develop_np.develop(a, {"levelsBlack": 51}, None)[0, 0, 0]), 0.0, places=4)
        b = np.full((4, 4, 3), 0.9, np.float32)
        self.assertAlmostEqual(float(develop_np.develop(b, {"levelsWhite": 229}, None)[0, 0, 0]), 1.0, places=2)
        dark = develop_np.develop(np.full((4, 4, 3), 0.1, np.float32), {"blacks": -80}, None)
        self.assertLess(float(dark[0, 0, 0]), 0.1)

    def test_saturation_minus100_is_grey_and_plus_boosts(self):
        a = np.zeros((10, 10, 3), np.float32)
        a[..., 0], a[..., 1], a[..., 2] = 0.8, 0.3, 0.2
        g = develop_np.develop(a, {"saturation": -100}, None)
        self.assertLess(float(np.ptp(g[0, 0])), 0.01)
        up = develop_np.develop(a, {"saturation": 50}, None)
        self.assertGreater(float(np.ptp(up[0, 0])), float(np.ptp(a[0, 0])))
        # وایبرنس: رنگِ کم‌اشباع بیشتر از رنگِ پراشباع قوی می‌شود
        low = np.zeros((4, 4, 3), np.float32)
        low[...] = (0.55, 0.5, 0.45)
        high = np.zeros((4, 4, 3), np.float32)
        high[...] = (0.9, 0.2, 0.1)
        dl = float(np.ptp(develop_np.develop(low, {"vibrance": 80}, None)[0, 0])) / float(np.ptp(low[0, 0]))
        dh = float(np.ptp(develop_np.develop(high, {"vibrance": 80}, None)[0, 0])) / float(np.ptp(high[0, 0]))
        self.assertGreater(dl, dh)

    def test_hsl_band_shifts_only_that_colour(self):
        a = np.zeros((6, 6, 3), np.float32)
        a[:, :3] = (0.9, 0.1, 0.1)         # قرمز
        a[:, 3:] = (0.1, 0.1, 0.9)         # آبی
        out = develop_np.develop(a, {"redHue": 80}, None)
        self.assertGreater(float(out[0, 0, 1]), 0.2, "قرمز باید به سمتِ نارنجی برود")
        self.assertTrue(np.allclose(out[:, 3:], a[:, 3:], atol=0.02), "آبی نباید عوض شود")
        sat = develop_np.develop(a, {"redSat": -100}, None)
        self.assertLess(float(np.ptp(sat[0, 0])), float(np.ptp(a[0, 0])))

    def test_highlights_shadows_are_local(self):
        a = np.zeros((120, 160, 3), np.float32)
        a[:, :80] = 0.12
        a[:, 80:] = 0.88
        sh = develop_np.develop(a, {"shadows": 80}, None)
        self.assertGreater(float(sh[60, 20, 0]), 0.12 + 0.03)
        self.assertAlmostEqual(float(sh[60, 140, 0]), 0.88, delta=0.03)
        hl = develop_np.develop(a, {"highlights": -80}, None)
        self.assertLess(float(hl[60, 140, 0]), 0.88 - 0.03)

    def test_clarity_sharpen_denoise_vignette_grain(self):
        rng = np.random.default_rng(3)
        edge = np.full((120, 160, 3), 0.4, np.float32)
        edge[:, 80:] = 0.6
        sharp = develop_np.develop(edge, {"sharpen": 100, "sharpenRadius": 2}, None)
        self.assertGreater(float(sharp.max()), 0.61)                      # overshoot کنارِ لبه
        self.assertLess(float(sharp.min()), 0.39)
        clar = develop_np.develop(edge, {"clarity": 100}, None)
        self.assertGreater(float(np.abs(clar - edge).max()), 0.005)
        tex = develop_np.develop(edge, {"texture": 100}, None)
        self.assertGreater(float(np.abs(tex - edge).max()), 0.005)
        noisy = np.clip(0.5 + rng.normal(0, 0.06, (96, 96, 3)), 0, 1).astype(np.float32)
        den = develop_np.develop(noisy, {"noiseLuma": 80, "noiseColor": 80}, None)
        self.assertLess(float(den.std()), float(noisy.std()) * 0.8)
        flat = np.full((100, 120, 3), 0.5, np.float32)
        v = develop_np.develop(flat, {"vignette": -80}, None)
        self.assertGreater(float(v[50, 60, 0]), float(v[0, 0, 0]) + 0.1)
        vp = develop_np.develop(flat, {"vignette": 80}, None)
        self.assertGreater(float(vp[0, 0, 0]), 0.55)
        g1 = develop_np.develop(flat, {"grain": 60}, None)
        g2 = develop_np.develop(flat, {"grain": 60}, None)
        self.assertGreater(float(g1.std()), 0.003)
        self.assertTrue(np.array_equal(g1, g2), "دانه با بذرِ ثابت است")

    def test_dehaze_lens_and_spots(self):
        hazy = np.clip(0.55 + 0.25 * np.random.default_rng(1).random((90, 120, 3)) * 0.3 + 0.2, 0, 1).astype(np.float32)
        out = develop_np.develop(hazy, {"dehaze": 70}, None)
        self.assertEqual(out.shape, hazy.shape)
        self.assertGreater(float(np.abs(out - hazy).mean()), 0.005)
        fog = develop_np.develop(hazy, {"dehaze": -70}, None)
        self.assertGreater(float(np.abs(fog - hazy).mean()), 0.005)
        a = self.grad()
        d = develop_np.develop(a, {"distortion": 40, "lensVignette": 50}, None)
        self.assertEqual(d.shape, a.shape)
        # لکه: نقطهٔ سیاه روی زمینهٔ سفید پاک می‌شود
        s = np.ones((100, 100, 3), np.float32)
        s[48:53, 48:53] = 0
        healed = develop_np.develop(s, {}, None, spots=[{"x": 0.5, "y": 0.5, "r": 0.06}])
        self.assertGreater(float(healed[50, 50, 0]), 0.9)

    def test_normalize_and_scale(self):
        a = develop_np.normalize_adjust({"exposure": 99, "nope": 5, "contrast": 0, "tint": "x", "texture": 20})
        self.assertEqual(a, {"exposure": 4.0, "texture": 20.0})
        edge = np.full((60, 80, 3), 0.4, np.float32)
        edge[:, 40:] = 0.6
        big = develop_np.develop(edge, {"sharpen": 100, "sharpenRadius": 3}, None, scale=1.0)
        small = develop_np.develop(edge, {"sharpen": 100, "sharpenRadius": 3}, None, scale=0.2)
        self.assertNotEqual(float(big[30, 36, 0]), float(small[30, 36, 0]))
        self.assertTrue(develop_np.is_neutral({}, {}, []))
        self.assertFalse(develop_np.is_neutral({"exposure": 1}))

    def test_memory_aware_big_image_runs(self):
        a = np.full((900, 1400, 3), 0.4, np.float32)
        t = time.time()
        out = develop_np.develop(a, {"exposure": 0.5, "contrast": 20, "vibrance": 30, "highlights": -20, "clarity": 20}, None)
        self.assertEqual(out.shape, a.shape)
        self.assertLess(time.time() - t, 8)


# ═════════════════════════════ blend

def _lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def _clip(c):
    l, n, x = _lum(c), min(c), max(c)
    if n < 0:
        c = [l + (v - l) * l / (l - n) for v in c]
    if x > 1:
        c = [l + (v - l) * (1 - l) / (x - l) for v in c]
    return c


def _setlum(c, l):
    d = l - _lum(c)
    return _clip([v + d for v in c])


def _sat(c):
    return max(c) - min(c)


def _setsat(c, s):
    idx = sorted(range(3), key=lambda i: c[i])
    mn, md, mx = idx
    out = [0.0, 0.0, 0.0]
    if c[mx] > c[mn]:
        out[md] = (c[md] - c[mn]) * s / (c[mx] - c[mn])
        out[mx] = s
    return out


def ref_blend(mode, cb, cs):
    """W3C Compositing Level 1 — نوشتهٔ جدا و اسکالر، برای سنجشِ blend.py."""
    def sep(f):
        return [f(b, s) for b, s in zip(cb, cs)]

    def hardlight(b, s):
        return b * 2 * s if s <= 0.5 else b + (2 * s - 1) - b * (2 * s - 1)

    def softlight(b, s):
        if s <= 0.5:
            return b - (1 - 2 * s) * b * (1 - b)
        d = ((16 * b - 12) * b + 4) * b if b <= 0.25 else b ** 0.5
        return b + (2 * s - 1) * (d - b)

    def dodge(b, s):
        return 0.0 if b == 0 else (1.0 if s == 1 else min(1.0, b / (1 - s)))

    def burn(b, s):
        return 1.0 if b == 1 else (0.0 if s == 0 else 1 - min(1.0, (1 - b) / s))

    if mode == "normal":
        return list(cs)
    if mode == "multiply":
        return sep(lambda b, s: b * s)
    if mode == "screen":
        return sep(lambda b, s: b + s - b * s)
    if mode == "overlay":
        return sep(lambda b, s: hardlight(s, b))
    if mode == "hard-light":
        return sep(hardlight)
    if mode == "soft-light":
        return sep(softlight)
    if mode == "darken":
        return sep(min)
    if mode == "lighten":
        return sep(max)
    if mode == "color-dodge":
        return sep(dodge)
    if mode == "color-burn":
        return sep(burn)
    if mode == "difference":
        return sep(lambda b, s: abs(b - s))
    if mode == "exclusion":
        return sep(lambda b, s: b + s - 2 * b * s)
    if mode == "hue":
        return _setlum(_setsat(list(cs), _sat(cb)), _lum(cb))
    if mode == "saturation":
        return _setlum(_setsat(list(cb), _sat(cs)), _lum(cb))
    if mode == "color":
        return _setlum(list(cs), _lum(cb))
    if mode == "luminosity":
        return _setlum(list(cb), _lum(cs))
    raise AssertionError(mode)


class BlendTests(SimpleTestCase):
    def test_every_mode_matches_the_w3c_reference(self):
        vals = [0.0, 0.1, 0.25, 0.4, 0.5, 0.75, 0.9, 1.0]
        rng = np.random.default_rng(7)
        samples = [(rng.choice(vals, 3).tolist(), rng.choice(vals, 3).tolist()) for _ in range(60)]
        samples += [([0.2, 0.5, 0.8], [0.9, 0.1, 0.4]), ([0.0, 0.0, 0.0], [1.0, 1.0, 1.0]), ([1, 1, 1], [0, 0, 0])]
        for mode in blend.BLEND_MODES:
            cb = np.array([s[0] for s in samples], np.float32)[None]
            cs = np.array([s[1] for s in samples], np.float32)[None]
            got = blend.blend(mode, cb, cs)[0]
            for i, (b, s) in enumerate(samples):
                want = ref_blend(mode, b, s)
                self.assertTrue(np.allclose(got[i], want, atol=2e-5), (mode, b, s, got[i].tolist(), want))

    def test_composite_alpha_formula(self):
        cb = np.array([[[0.8, 0.2, 0.4]]], np.float32)
        cs = np.array([[[0.3, 0.9, 0.1]]], np.float32)
        ab = np.array([[0.6]], np.float32)
        a_s = np.array([[0.5]], np.float32)
        for mode in blend.BLEND_MODES:
            cr, ar = blend.composite(mode, cb, ab, cs, a_s)
            B = np.array(ref_blend(mode, cb[0, 0].tolist(), cs[0, 0].tolist()))
            ar_ref = 0.5 + 0.6 * 0.5
            cr_ref = ((1 - 0.5) * 0.6 * cb[0, 0] + (1 - 0.6) * 0.5 * cs[0, 0] + 0.5 * 0.6 * B) / ar_ref
            self.assertAlmostEqual(float(ar[0, 0]), ar_ref, places=5)
            self.assertTrue(np.allclose(cr[0, 0], cr_ref, atol=2e-5), mode)
        cr, ar = blend.composite("multiply", cb, np.zeros((1, 1), np.float32), cs, a_s)
        self.assertTrue(np.allclose(cr[0, 0], cs[0, 0], atol=1e-6), "روی بومِ شفاف همان رنگِ لایه")


# ═════════════════════════════ وارسیِ لایه‌ها

class LayerNormalizeTests(SimpleTestCase):
    def test_clamps_defaults_and_drops_unknown(self):
        out = layers.normalize_layers([
            base_layer(opacity=7, blend="multiply", junk=1, mask={"type": "radial", "c": [9, -9], "rx": 0, "ry": 99, "feather": 5}),
            {"id": "t1", "type": "text", "text": "x" * 900, "size": 5, "weight": 640, "color": "red", "align": "?", "cx": 99,
             "rot": 99999, "stroke": {"w": 5, "color": "#112233"}, "shadow": {}, "box": {"pad": 99}, "extra": 1},
            {"id": "a1", "type": "adjust", "adjust": {"exposure": 100, "bogus": 3, "contrast": 0}, "blend": "screen"},
        ])
        b, t, a = out
        self.assertEqual(b["opacity"], 1.0)
        self.assertEqual(b["blend"], "multiply")
        self.assertNotIn("junk", b)
        self.assertEqual(b["mask"]["rx"], 0.001)
        self.assertEqual(b["mask"]["ry"], 4)
        self.assertEqual(b["mask"]["feather"], 1)
        self.assertEqual(len(t["text"]), 500)
        self.assertEqual(t["size"], 0.5)
        self.assertEqual(t["weight"], 600)
        self.assertEqual(t["color"], "#ffffff")
        self.assertEqual(t["align"], "center")
        self.assertEqual(t["stroke"], {"w": 0.3, "color": "#112233"})
        self.assertLessEqual(t["cx"], 4)
        self.assertLessEqual(t["rot"], 3600)
        self.assertNotIn("extra", t)
        self.assertEqual(t["box"]["pad"], 2)
        self.assertEqual(a["adjust"], {"exposure": 4.0})
        self.assertEqual(a["blend"], "normal", "لایهٔ تنظیم حالتِ ترکیب ندارد")

    def test_limits_ids_and_base(self):
        with self.assertRaisesRegex(catalog.CatalogError, "لایه"):
            layers.normalize_layers([base_layer()] + [{"id": f"s{i}", "type": "shape"} for i in range(layers.MAX_LAYERS)])
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([base_layer(), {"id": "base", "type": "shape"}])          # شناسهٔ تکراری
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([base_layer(id="BAD ID")])
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([base_layer(), base_layer(id="b2")])                      # دو عکس
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([{"id": "s", "type": "shape"}])                            # بی عکس
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([base_layer(blend="plaid")])
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([base_layer(), {"id": "x", "type": "wizard"}])
        with self.assertRaises(catalog.CatalogError):
            layers.normalize_layers([base_layer(mask={"type": "paint", "id": "../x"})])
        self.assertEqual(layers.normalize_layers([], base="at_most_one"), [])
        self.assertEqual(layers.normalize_layers([{"id": "a", "type": "shape"}], base="at_most_one")[0]["type"], "shape")
        # شکل‌های پیش‌فرض
        s = layers.normalize_layers([base_layer(), {"id": "ln", "type": "shape", "shape": "line"}])[1]
        self.assertTrue(s["stroke"] and s["stroke"]["w"] > 0)

    def test_retouch_and_preset_helpers(self):
        out = layers.normalize_layers([base_layer(), {"id": "r", "type": "retouch", "strokes": [
            {"mode": "heal", "pts": [[0.1, 0.1], [0.2, 0.2], ["x", 1]], "r": 9, "dx": 0.1, "dy": 9},
            {"mode": "clone", "pts": []}]}])
        st = out[1]["strokes"]
        self.assertEqual(len(st), 1)
        self.assertEqual(st[0]["r"], 0.3)
        self.assertEqual(st[0]["dy"], 2)
        self.assertEqual(len(st[0]["pts"]), 3)
        pre = layers.preset_layers([base_layer(), {"id": "r", "type": "retouch"},
                                    {"id": "t", "type": "text", "text": "a", "mask": {"type": "paint", "id": "m1"}},
                                    {"id": "i", "type": "image", "src": {"kind": "logo"}}])
        self.assertEqual([l["type"] for l in pre], ["text", "image"])
        self.assertIsNone(pre[0]["mask"])
        self.assertEqual(layers.mask_ids([{"mask": {"type": "paint", "id": "m9"}}, {"mask": None}, {"mask": {"type": "linear"}}]), {"m9"})


# ═════════════════════════════ ترکیب

class ComposeTests(SimpleTestCase):
    def compose(self, base, lst, **kw):
        c = ctx(**kw)
        norm = layers.normalize_layers(lst)
        return layers.compose(base, norm, c), c

    def test_base_only_is_identity_and_opacity(self):
        img = photo(160, 120)
        out, _ = self.compose(img, [base_layer()])
        self.assertEqual(out.size, img.size)
        self.assertEqual(out.mode, "RGB")
        self.assertTrue(ops.same_image(out, img))
        lst = [base_layer(), {"id": "w", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": 1.5, "h": 1.5,
                              "fill": {"type": "solid", "color": "#0000ff", "opacity": 1}, "opacity": 0.5}]
        out, _ = self.compose(solid(40, 40, (200, 0, 0)), lst)
        r, g, b = px(out, 20, 20)
        self.assertAlmostEqual(r, 100, delta=2)
        self.assertAlmostEqual(b, 128, delta=2)

    def test_hidden_and_order_and_base_alpha(self):
        lst = [{"id": "s", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": 2, "h": 2,
                "fill": {"type": "solid", "color": "#00ff00", "opacity": 1}}, base_layer(),
               {"id": "h", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": 2, "h": 2, "visible": False}]
        # عکسِ پایه شفاف در نیمه‌ای: لایهٔ زیرِ آن از همان‌جا دیده می‌شود
        base = Image.new("RGBA", (40, 40), (255, 0, 0, 255))
        base.paste((0, 0, 0, 0), (0, 0, 20, 40))
        out, _ = self.compose(base, lst)
        self.assertEqual(px(out, 30, 20), (255, 0, 0))
        self.assertEqual(px(out, 5, 20), (0, 255, 0))
        # همهٔ بوم پر است ⇒ RGB
        self.assertEqual(out.mode, "RGB")
        out2, _ = self.compose(base, [base_layer()])
        self.assertEqual(out2.mode, "RGBA")
        self.assertEqual(out2.getpixel((5, 20))[3], 0)

    def test_masks_linear_radial_paint_invert(self):
        red = [{"id": "w", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": 2, "h": 2,
                "fill": {"type": "solid", "color": "#ffffff", "opacity": 1}}]
        base = solid(100, 100, (0, 0, 0))
        out, _ = self.compose(base, [base_layer()] + [dict(red[0], mask={"type": "linear", "p0": [0.5, 0.2], "p1": [0.5, 0.8]})])
        self.assertEqual(px(out, 50, 5)[0], 255)             # پیش از p0 ⇒ کاملِ اثر
        self.assertEqual(px(out, 50, 95)[0], 0)              # پس از p1 ⇒ هیچ
        self.assertAlmostEqual(px(out, 50, 50)[0], 128, delta=6)     # وسط ⇒ نیم
        out, _ = self.compose(base, [base_layer()] + [dict(red[0], mask={"type": "linear", "p0": [0.5, 0.2], "p1": [0.5, 0.8], "invert": True})])
        self.assertEqual(px(out, 50, 5)[0], 0)
        out, _ = self.compose(base, [base_layer()] + [dict(red[0], mask={"type": "radial", "c": [0.5, 0.5], "rx": 0.2, "ry": 0.2, "feather": 0})])
        self.assertEqual(px(out, 50, 50)[0], 255)
        self.assertEqual(px(out, 5, 5)[0], 0)
        out, _ = self.compose(base, [base_layer()] + [dict(red[0], mask={"type": "radial", "c": [0.5, 0.5], "rx": 0.2, "ry": 0.2, "feather": 1, "invert": True})])
        self.assertLessEqual(px(out, 50, 50)[0], 2)
        self.assertEqual(px(out, 2, 2)[0], 255)
        # رنگ‌آمیزی‌شده (PNG) با فایلِ کوچک‌تر ⇒ کشیده می‌شود
        d = Path(tempfile.mkdtemp(prefix="nmphoto-pro-"))
        self.addCleanup(shutil.rmtree, d, True)
        m = Image.new("L", (10, 10), 0)
        m.paste(255, (0, 0, 5, 10))
        m.save(d / "mask-m1.png")
        lay = [base_layer(), dict(red[0], mask={"type": "paint", "id": "m1"})]
        c = ctx(mask_path=lambda pid, mid: d / f"mask-{mid}.png" if mid == "m1" else None)
        out = layers.compose(base, layers.normalize_layers(lay), c, project=1)
        self.assertEqual(px(out, 10, 50)[0], 255)
        self.assertEqual(px(out, 90, 50)[0], 0)
        out, c2 = self.compose(base, [base_layer(), dict(red[0], mask={"type": "paint", "id": "missing"})])
        self.assertEqual(px(out, 90, 50)[0], 255)
        self.assertTrue(any("ماسک" in n for n in c2["notes"]))

    def test_transform_position_scale_rotation_flip(self):
        d = Path(tempfile.mkdtemp(prefix="nmphoto-pro-"))
        self.addCleanup(shutil.rmtree, d, True)
        tile = Image.new("RGB", (100, 50), (255, 0, 0))
        tile.paste((0, 0, 255), (50, 0, 100, 50))          # نیمهٔ چپ قرمز، نیمهٔ راست آبی
        tile.save(d / "t.png")
        lst = [base_layer(), {"id": "i", "type": "image", "src": {"kind": "logo"}, "cx": 0.5, "cy": 0.5, "w": 0.4}]
        base = solid(200, 200, (10, 10, 10))
        c = ctx(logo_path=lambda p: d / "t.png")
        out = layers.compose(base, layers.normalize_layers(lst), c)
        # w=0.4*200=80 px پهنا، 40 px ارتفاع؛ مرکز (100,100)
        self.assertEqual(px(out, 70, 100), (255, 0, 0))
        self.assertEqual(px(out, 130, 100), (0, 0, 255))
        self.assertEqual(px(out, 100, 60), (10, 10, 10))        # بالاتر از لایه
        self.assertEqual(px(out, 50, 100), (10, 10, 10))        # چپ‌تر از لایه
        # قرینهٔ افقی
        lst[1]["flip_h"] = True
        out = layers.compose(base, layers.normalize_layers(lst), c)
        self.assertEqual(px(out, 70, 100), (0, 0, 255))
        self.assertEqual(px(out, 130, 100), (255, 0, 0))
        # جابه‌جایی
        lst[1].update(flip_h=False, cx=0.25, cy=0.75)
        out = layers.compose(base, layers.normalize_layers(lst), c)
        self.assertEqual(px(out, 40, 150), (255, 0, 0))
        self.assertEqual(px(out, 160, 50), (10, 10, 10))
        # چرخشِ ۹۰ درجهٔ ساعتگرد: لایهٔ ۸۰×۴۰ می‌شود ۴۰×۸۰، قرمز بالا، آبی پایین
        lst[1].update(cx=0.5, cy=0.5, rot=90)
        out = layers.compose(base, layers.normalize_layers(lst), c)
        self.assertEqual(px(out, 100, 70), (255, 0, 0))
        self.assertEqual(px(out, 100, 130), (0, 0, 255))
        self.assertEqual(px(out, 70, 100), (10, 10, 10))
        # ۴۵ درجه: گوشهٔ بوم‌نشدهٔ بالا-چپ خالی، قطر پر
        lst[1].update(rot=45, w=0.6)
        out = layers.compose(base, layers.normalize_layers(lst), c)
        self.assertNotEqual(px(out, 100, 100), (10, 10, 10))
        self.assertEqual(px(out, 45, 55), (10, 10, 10))
        # لایه‌ای که بیرونِ بوم است
        lst[1].update(rot=0, cx=3.0)
        out = layers.compose(base, layers.normalize_layers(lst), c)
        self.assertTrue(ops.same_image(out, base))

    def test_image_layer_from_library_asset_and_logo_missing(self):
        d = Path(tempfile.mkdtemp(prefix="nmphoto-pro-"))
        self.addCleanup(shutil.rmtree, d, True)
        Image.new("RGBA", (40, 40), (255, 255, 0, 255)).save(d / "a.png")
        calls = []

        def logo_path(p):
            calls.append(p)
            return d / "a.png" if p.get("source") == "asset" and p.get("asset") == 7 else None

        lst = [base_layer(), {"id": "i", "type": "image", "src": {"kind": "asset", "asset": 7}, "w": 0.5, "cx": .5, "cy": .5},
               {"id": "j", "type": "image", "src": {"kind": "logo"}}]
        c = ctx(logo_path=logo_path)
        out = layers.compose(solid(100, 100, (0, 0, 0)), layers.normalize_layers(lst), c)
        self.assertEqual(px(out, 50, 50), (255, 255, 0))
        self.assertTrue(any(p.get("source") == "store" for p in calls))
        self.assertTrue(any("تصویر" in n for n in c["notes"]), "لوگوی نبوده باید یادداشت شود، نه خطا")

    def test_shapes(self):
        base = solid(200, 100, (0, 0, 0))
        lst = [base_layer(),
               {"id": "r", "type": "shape", "shape": "rect", "cx": 0.25, "cy": 0.5, "w": 0.3, "h": 0.3,
                "fill": {"type": "solid", "color": "#ff0000", "opacity": 1}},
               {"id": "e", "type": "shape", "shape": "ellipse", "cx": 0.75, "cy": 0.5, "w": 0.3, "h": 0.3,
                "fill": {"type": "gradient", "c0": "#ffffff", "c1": "#0000ff", "angle": 0}, "stroke": {"color": "#00ff00", "w": 0.01}}]
        out, _ = self.compose(base, lst)
        self.assertEqual(px(out, 50, 50), (255, 0, 0))
        self.assertEqual(px(out, 50, 5), (0, 0, 0))
        left, right = px(out, 125, 50), px(out, 175, 50)
        self.assertGreater(left[0], right[0] + 60, "گرادیان از سفید به آبی")
        self.assertEqual(px(out, 150, 3), (0, 0, 0))                # بیرونِ بیضی
        self.assertEqual(px(out, 100, 50), (0, 0, 0))               # بینِ دو شکل
        out, _ = self.compose(base, [base_layer(), {"id": "l", "type": "shape", "shape": "line", "cx": .5, "cy": .5, "w": .6, "h": 0,
                                                    "stroke": {"color": "#ff00ff", "w": 0.05}}])
        self.assertEqual(px(out, 100, 50), (255, 0, 255))
        self.assertEqual(px(out, 100, 10), (0, 0, 0))
        rr, _ = self.compose(base, [base_layer(), {"id": "q", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": .6, "h": .6,
                                                   "radius": 1, "fill": {"type": "solid", "color": "#ffffff", "opacity": 1}}])
        self.assertEqual(px(rr, 100, 50), (255, 255, 255))
        self.assertEqual(px(rr, 100 - 59, 50 - 29), (0, 0, 0), "گوشهٔ گردشده")

    # ───── متن
    def test_persian_text_is_shaped_joined_and_rtl(self):
        from scipy import ndimage

        txt = "تخفیف ویژه تا ۵۰٪ برای محصولات تازه"
        lay = layers.normalize_layers([base_layer(), {"id": "t", "type": "text", "text": txt, "size": 0.05, "cx": .5, "cy": .5}])[1]
        tile, pivot = textlayer.render_text(lay, 1200)
        a = np.asarray(tile.getchannel("A"))
        self.assertGreater(int((a > 128).sum()), 500, "جوهری نبود")
        # هر کلمه در جای درست: «تخفیف» راست‌ترین، «تازه» چپ‌ترین (قالبِ ارجاع با همان raqm)
        font = textlayer._font(textlayer.font_path(700), 0.05 * 1200)

        def ink(word):
            im = Image.new("L", tile.size, 0)
            ImageDraw.Draw(im).text((10, tile.height - 20), word, font=font, fill=255, anchor="ls", direction="rtl", language="fa")
            arr = np.asarray(im)
            ys, xs = np.nonzero(arr)
            return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

        import cv2

        pos = {}
        for w in ("تخفیف", "تازه"):
            t = ink(w).astype(np.uint8)
            res = cv2.matchTemplate(a.astype(np.uint8), t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            self.assertGreater(mx, 0.85, w)
            pos[w] = loc[0]
        self.assertGreater(pos["تخفیف"], pos["تازه"] + 200, "ترتیب راست به چپ نیست")
        # اتصالِ حروف: سه «س» پیوسته یک تکه است؛ رسمِ جدا جدا سه تکه
        lay2 = layers.normalize_layers([base_layer(), {"id": "t", "type": "text", "text": "سسس", "size": 0.1}])[1]
        joined, _ = textlayer.render_text(lay2, 800)
        labels, n_joined = ndimage.label(np.asarray(joined.getchannel("A")) > 128)
        self.assertEqual(n_joined, 1)
        naive = Image.new("L", (400, 200), 0)
        f2 = textlayer._font(textlayer.font_path(700), 80)
        x = 10
        for ch in "سسس":
            ImageDraw.Draw(naive).text((x, 120), ch, font=f2, fill=255, anchor="ls", direction="ltr")
            x += int(f2.getlength(ch)) + 30
        self.assertGreaterEqual(ndimage.label(np.asarray(naive) > 128)[1], 3)
        # روی تصویر
        out, _ = self.compose(solid(1200, 400, (30, 30, 30)), [base_layer(), dict(lay, cy=0.5)])
        arr = np.asarray(out.convert("L"))
        self.assertGreater(int((arr > 200).sum()), 800)
        ys, xs = np.nonzero(arr > 200)
        self.assertLess(abs(((xs.min() + xs.max()) / 2) - 600), 12, "متن وسطِ بوم")

    def test_text_options_english_stroke_shadow_box_wrap_tile_rotation(self):
        base = solid(600, 300, (20, 20, 120))
        t = {"id": "t", "type": "text", "text": "Sale 50% off", "size": 0.1, "color": "#ffffff", "cx": .5, "cy": .5}
        out, _ = self.compose(base, [base_layer(), t])
        self.assertGreater((np.asarray(out.convert("L")) > 200).sum(), 400)
        plain = np.asarray(self.compose(base, [base_layer(), t])[0], dtype=int)
        stroke = np.asarray(self.compose(base, [base_layer(), dict(t, stroke={"w": 0.12, "color": "#ff0000"})])[0], dtype=int)
        self.assertGreater(((stroke[..., 0] > 200) & (stroke[..., 1] < 60)).sum(), 100, "استروکِ قرمز")
        shadow = self.compose(base, [base_layer(), dict(t, shadow={"color": "#000000", "opacity": 1, "blur": 0.05, "dx": 0.08, "dy": 0.08})])[0]
        self.assertLess(np.asarray(shadow.convert("L"), dtype=int).min(), np.asarray(base.convert("L"), dtype=int).min())
        box = self.compose(base, [base_layer(), dict(t, box={"color": "#ff8800", "opacity": 1, "pad": 0.4, "radius": 0.2})])[0]
        arr = np.asarray(box, dtype=int)
        self.assertGreater(((arr[..., 0] > 240) & (arr[..., 1] > 100) & (arr[..., 1] < 180) & (arr[..., 2] < 60)).sum(), 2000, "کادرِ پشتِ متن")
        # چرخش
        rot = self.compose(base, [base_layer(), dict(t, rot=90)])[0]
        ys, xs = np.nonzero(np.asarray(rot.convert("L")) > 200)
        self.assertGreater(ys.max() - ys.min(), xs.max() - xs.min(), "متنِ ۹۰ درجه عمودی است")
        # شکستنِ خط با width و lines دستی
        long_text = dict(t, text="one two three four five six seven eight", width=0.4, size=0.06)
        wrapped = self.compose(base, [base_layer(), long_text])[0]
        ys, xs = np.nonzero(np.asarray(wrapped.convert("L")) > 200)
        self.assertLessEqual(xs.max() - xs.min(), 0.4 * 600 + 12)
        self.assertGreater(ys.max() - ys.min(), 40, "چند خط")
        manual = self.compose(base, [base_layer(), dict(t, text="x", lines=["AAA", "BBB", "CCC"])])[0]
        ys, xs = np.nonzero(np.asarray(manual.convert("L")) > 200)
        self.assertGreater(ys.max() - ys.min(), 60)
        # فاصلهٔ حروف
        spaced = self.compose(base, [base_layer(), dict(t, letter_spacing=0.5)])[0]
        ys, xs = np.nonzero(np.asarray(spaced.convert("L")) > 200)
        ys0, xs0 = np.nonzero(np.asarray(self.compose(base, [base_layer(), t])[0].convert("L")) > 200)
        self.assertGreater(xs.max() - xs.min(), xs0.max() - xs0.min() + 40)
        fa_sp = self.compose(base, [base_layer(), dict(t, text="تخفیف ویژه پاییز", letter_spacing=0.4)])[0]
        fa_no = self.compose(base, [base_layer(), dict(t, text="تخفیف ویژه پاییز")])[0]
        w = lambda im: np.ptp(np.nonzero(np.asarray(im.convert("L")) > 200)[1])
        self.assertGreater(w(fa_sp), w(fa_no) + 10)
        # تکرارشونده (واترمارک)
        tiled = self.compose(base, [base_layer(), dict(t, size=0.05, opacity=0.5, tile={"angle": 28, "gap": 1.6})])[0]
        arr = np.asarray(tiled.convert("L"), dtype=int)
        ink = np.abs(arr - np.asarray(base.convert("L"), dtype=int)) > 15
        self.assertGreater(ink[:100].sum(), 100)
        self.assertGreater(ink[200:].sum(), 100)
        self.assertEqual(textlayer.render_text(dict(t, text="   "), 600), None)

    # ───── لایهٔ تنظیم و روتوش
    def test_adjust_layer_with_masks(self):
        base = solid(100, 100, (100, 100, 100))
        adj = {"id": "a", "type": "adjust", "adjust": {"exposure": 1.0}}
        orig = px(base, 5, 5)[0]
        out, _ = self.compose(base, [base_layer(), dict(adj, mask={"type": "linear", "p0": [0.5, 0.2], "p1": [0.5, 0.8]})])
        top, mid, bot = px(out, 50, 5)[0], px(out, 50, 50)[0], px(out, 50, 95)[0]
        self.assertGreater(top, orig + 20)
        self.assertEqual(bot, orig)
        self.assertAlmostEqual(mid, (top + bot) / 2, delta=3)
        glob, _ = self.compose(base, [base_layer(), adj])
        self.assertAlmostEqual(px(glob, 50, 50)[0], top, delta=1)
        half, _ = self.compose(base, [base_layer(), dict(adj, opacity=0.5)])
        self.assertAlmostEqual(px(half, 50, 50)[0], (top + orig) / 2, delta=2)
        rad, _ = self.compose(base, [base_layer(), dict(adj, mask={"type": "radial", "c": [0.5, 0.5], "rx": 0.15, "ry": 0.15, "feather": 0})])
        self.assertGreater(px(rad, 50, 50)[0], orig + 20)
        self.assertEqual(px(rad, 5, 5)[0], orig)
        # تنظیمِ منحنی هم لایه می‌شود؛ لایهٔ تنظیمِ خالی اثری ندارد
        cur, _ = self.compose(base, [base_layer(), {"id": "a", "type": "adjust", "curve": {"rgb": [[0, 0], [100, 200], [255, 255]]}}])
        self.assertGreater(px(cur, 5, 5)[0], 180)
        none, _ = self.compose(base, [base_layer(), {"id": "a", "type": "adjust"}])
        self.assertTrue(ops.same_image(none, base))
        # شعاعیِ بی‌اثرِ فضایی فقط روی ناحیهٔ خودش حساب می‌شود ولی نتیجه همان است
        vig, _ = self.compose(base, [base_layer(), {"id": "a", "type": "adjust", "adjust": {"vignette": -100, "vignetteMidpoint": 0}}])
        self.assertLess(px(vig, 0, 0)[0], px(vig, 50, 50)[0])

    def test_retouch_clone_and_heal(self):
        base = solid(200, 100, (50, 50, 50))
        ImageDraw.Draw(base).ellipse([140, 30, 170, 60], fill=(250, 200, 0))        # نقطهٔ زرد در راست
        # هدف: چپ، (50,45)؛ منبع: ۱۰۰ پیکسل راست‌تر ⇒ dx=0.5 (کسری از W=200)
        stroke = {"mode": "clone", "pts": [[0.25, 0.45]], "r": 0.1, "hardness": 1, "opacity": 1, "dx": 0.5, "dy": 0.0}
        out, _ = self.compose(base, [base_layer(), {"id": "r", "type": "retouch", "strokes": [stroke]}])
        self.assertEqual(px(out, 50, 45), px(base, 150, 45))
        self.assertEqual(px(out, 150, 45), px(base, 150, 45), "منبع دست نمی‌خورد")
        self.assertEqual(px(out, 10, 45), (50, 50, 50), "بیرونِ قلم دست‌نخورده")
        half, _ = self.compose(base, [base_layer(), {"id": "r", "type": "retouch", "opacity": 0.5, "strokes": [stroke]}])
        self.assertAlmostEqual(px(half, 50, 45)[0], (50 + px(base, 150, 45)[0]) / 2, delta=2)
        heal = dict(stroke, mode="heal", hardness=0.8, r=0.08)
        hout, _ = self.compose(base, [base_layer(), {"id": "r", "type": "retouch", "strokes": [heal]}])
        # ترمیم: بافتِ منبع + روشناییِ اطرافِ هدف ⇐ زرد منتقل می‌شود ولی نه با همان شدتِ کلون
        self.assertGreater(px(hout, 50, 45)[0], 60)                       # بافتِ منبع کمی می‌ماند
        self.assertLess(px(hout, 50, 45)[0], px(out, 50, 45)[0] - 40)     # ولی نه با شدتِ کلون: تُنِ اطراف را می‌گیرد
        self.assertEqual(px(hout, 5, 5), (50, 50, 50))
        # آفستِ صفر ⇒ بی‌اثر؛ چند قلمِ هم‌آفست یک گروه‌اند
        z, _ = self.compose(base, [base_layer(), {"id": "r", "type": "retouch", "strokes": [dict(stroke, dx=0)]}])
        self.assertTrue(ops.same_image(z, base))
        two, _ = self.compose(base, [base_layer(), {"id": "r", "type": "retouch", "strokes": [stroke, dict(stroke, pts=[[0.1, 0.45]])]}])
        self.assertEqual(px(two, 20, 45), px(base, 120, 45))

    def test_blend_modes_in_compose(self):
        base = solid(20, 20, (200, 100, 50))
        top = {"id": "s", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": 2, "h": 2,
               "fill": {"type": "solid", "color": "#808080", "opacity": 1}}
        for mode in ("multiply", "screen", "overlay", "soft-light", "difference", "luminosity", "hue", "color-burn"):
            out, _ = self.compose(base, [base_layer(), dict(top, blend=mode)])
            want = ref_blend(mode, [200 / 255, 100 / 255, 50 / 255], [128 / 255] * 3)
            got = [v / 255 for v in px(out, 10, 10)]
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, delta=2 / 255 + 1e-3, msg=mode)

    def test_big_canvas_cap_and_perf(self):
        t = time.time()
        base = photo(1800, 1200)
        lst = [base_layer(), {"id": "a", "type": "adjust", "adjust": {"exposure": 0.3, "contrast": 20}},
               {"id": "t", "type": "text", "text": "تست سرعت", "size": 0.08},
               {"id": "s", "type": "shape", "shape": "ellipse", "w": 0.5, "h": 0.3, "opacity": 0.6, "blend": "overlay"}]
        out, _ = self.compose(base, lst)
        self.assertEqual(out.size, base.size)
        self.assertLess(time.time() - t, 10)


# ═════════════════════════════ ابزارهای ops و catalog

class OpsWiringTests(SimpleTestCase):
    def test_tools_hidden_and_listed(self):
        tools = catalog.tools()
        for k in ("develop", "compose", "perspective"):
            self.assertTrue(tools[k].get("hidden"))
            self.assertEqual(tools[k]["where"], "server")
        self.assertIn("develop", [t["key"] for t in catalog.tool_list()])
        self.assertFalse(any(o["tool"] in ("develop", "compose", "perspective")
                             for r in catalog.RECIPES for o in r["operations"]))

    def test_order_is_kept_and_export_last(self):
        clean = catalog.normalize_operations([
            {"tool": "export", "params": {"format": "png"}},
            {"tool": "resize", "params": {"long_edge": 800}},
            {"tool": "compose", "params": {"layers": [base_layer()]}},
            {"tool": "develop", "params": {"adjust": {"exposure": 1}}},
            {"tool": "kit_auto", "params": {}},
        ])
        self.assertEqual([o["tool"] for o in clean], ["kit_auto", "resize", "compose", "develop", "export"])
        with self.assertRaises(catalog.CatalogError):
            catalog.normalize_operations([{"tool": "compose", "params": {"layers": [{"id": "x", "type": "shape"}]}}])
        p = catalog.normalize_params("perspective", {"tl": [0.1, "x"], "tr": [5, 0]})
        self.assertEqual(p["tl"], [0.1, 0.0])
        self.assertEqual(p["tr"], [2.0, 0.0])
        self.assertEqual(p["br"], [1, 1])

    def test_develop_and_compose_ops_through_run(self):
        img = photo(160, 120)
        c = ctx()
        ops_ = catalog.normalize_operations([
            {"tool": "develop", "params": {"adjust": {"exposure": 0.8, "saturation": 20}, "curve": {}, "spots": []}},
            {"tool": "compose", "params": {"layers": [base_layer(), {"id": "t", "type": "text", "text": "Hi", "size": 0.2}]}}])
        out, _ = ops.run(img, ops_, c)
        self.assertEqual(out.size, img.size)
        self.assertGreater(float(np.asarray(out).mean()), float(np.asarray(img).mean()))
        # شفافیتِ ورودی در develop می‌ماند
        rgba = photo(60, 60, alpha=True)
        o2 = ops.op_develop(rgba, catalog.normalize_params("develop", {"adjust": {"exposure": 1}}), ctx())
        self.assertEqual(o2.mode, "RGBA")
        self.assertEqual(o2.getchannel("A").getextrema(), rgba.getchannel("A").getextrema())

    def test_perspective(self):
        img = Image.new("RGB", (200, 100), (0, 0, 0))
        ImageDraw.Draw(img).polygon([(50, 20), (150, 10), (170, 90), (30, 80)], fill=(255, 255, 255))
        full = catalog.normalize_params("perspective", {})
        self.assertIs(ops.op_perspective(img, full, ctx()), img)
        quad = catalog.normalize_params("perspective", {"tl": [0.25, 0.2], "tr": [0.75, 0.1], "br": [0.85, 0.9], "bl": [0.15, 0.8]})
        out = ops.op_perspective(img, quad, ctx())
        arr = np.asarray(out.convert("L"))
        self.assertGreater(float(arr[3:-3, 3:-3].mean()), 240, "چهارضلعی به مستطیلِ پُر تبدیل می‌شود")
        w, h = out.size
        self.assertGreater(w, 100)


# ═════════════════════════════ API: پروژه و ماسک

class ProjectApiTests(ApiTestBase):
    def project(self, data=None):
        (aid,) = self.upload(photo(320, 240))
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": "پروژهٔ آزمون", "data": data or {}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return aid, r.json()["project"]

    def test_create_save_load_conflict_list_delete(self):
        aid, p = self.project({"adjust": {"exposure": 0.5}, "custom": [1, 2, 3]})
        self.assertEqual(p["rev"], 1)
        self.assertEqual(p["data"]["adjust"], {"exposure": 0.5})
        self.assertEqual(p["masks"], {})
        lay = [base_layer(), {"id": "t1", "type": "text", "text": "سلام", "size": 9, "junk": 1}]
        r = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {"layers": lay, "opaque": {"a": 1}}, "rev": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        q = r.json()["project"]
        self.assertEqual(q["rev"], 2)
        self.assertEqual(q["data"]["layers"][1]["size"], 0.5)
        self.assertNotIn("junk", q["data"]["layers"][1])
        self.assertEqual(q["data"]["opaque"], {"a": 1})
        # ذخیرهٔ کهنه
        r = self.api.patch(f"{self.base}/projects/{p['id']}/", {"data": {"layers": [base_layer()]}, "rev": 1}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "conflict")
        self.assertEqual(r.json()["project"]["rev"], 2)
        # بی rev ⇒ همیشه ذخیره
        r = self.api.put(f"{self.base}/projects/{p['id']}/", {"title": "نامِ تازه"}, format="json")
        self.assertEqual(r.json()["project"]["title"], "نامِ تازه")
        self.assertEqual(r.json()["project"]["rev"], 3)
        self.assertEqual(len(self.api.get(f"{self.base}/projects/{p['id']}/").json()["project"]["data"]["layers"]), 2)
        lst = self.api.get(f"{self.base}/projects/?asset={aid}").json()["projects"]
        self.assertEqual([x["id"] for x in lst], [p["id"]])
        self.assertEqual(self.api.get(f"{self.base}/projects/?asset=999999").json()["projects"], [])
        # دادهٔ نادرست
        bad = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {"layers": [{"id": "x", "type": "shape"}, base_layer(), base_layer(id="b2")]}}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.api.put(f"{self.base}/projects/{p['id']}/", {"data": [1]}, format="json").status_code, 400)
        big = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {"blob": "x" * (2 * 1024 * 1024 + 10)}}, format="json")
        self.assertEqual(big.status_code, 400)
        # عکسِ فروشگاهِ دیگر
        (other,) = self.upload(photo(100, 80, seed=5))
        lay2 = [base_layer(), {"id": "i", "type": "image", "src": {"kind": "asset", "asset": 987654}}]
        self.assertEqual(self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {"layers": lay2}}, format="json").status_code, 400)
        lay3 = [base_layer(), {"id": "i", "type": "image", "src": {"kind": "asset", "asset": other}}]
        self.assertEqual(self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {"layers": lay3}}, format="json").status_code, 200)
        d = self.media / PhotoProject.objects.get(pk=p["id"]).dir_rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.txt").write_text("x")
        self.assertEqual(self.api.delete(f"{self.base}/projects/{p['id']}/").status_code, 204)
        self.assertFalse(d.exists())
        self.assertEqual(self.api.get(f"{self.base}/projects/{p['id']}/").status_code, 404)

    def test_permissions_other_store(self):
        from django.contrib.auth import get_user_model

        from apps.stores.models import Store

        _aid, p = self.project()
        stranger = get_user_model().objects.create_user("stranger", password="x")
        Store.objects.create(owner=stranger, name="دیگری")
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(stranger)
        self.assertIn(c.get(f"{self.base}/projects/{p['id']}/").status_code, (403, 404))

    def test_mask_upload_get_delete_and_gc(self):
        _aid, p = self.project()
        pid = p["id"]
        m = Image.new("L", (3000, 1500), 0)
        r = self.api.put(f"{self.base}/projects/{pid}/masks/m1/", png_bytes(m), content_type="image/png")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["w"], r.json()["h"]), (2048, 1024))
        # multipart + RGB ⇒ خاکستری
        rgb = Image.new("RGB", (40, 30), (255, 255, 255))
        r = self.api.put(f"{self.base}/projects/{pid}/masks/m2/", {"file": jpeg_file(rgb, "m.jpg")}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        got = self.api.get(f"{self.base}/projects/{pid}/masks/m2/")
        self.assertEqual(got.status_code, 200)
        im = Image.open(io.BytesIO(got.content))
        self.assertEqual(im.mode, "L")
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/masks/BAD ID/", b"x", content_type="image/png").status_code, 400)
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/masks/m3/", b"not an image", content_type="image/png").status_code, 400)
        masks = self.api.get(f"{self.base}/projects/{pid}/").json()["project"]["masks"]
        self.assertEqual(sorted(masks), ["m1", "m2"])
        self.assertIn("/media/", masks["m1"])
        # ذخیره: m1 به لایه وصل است، m2 نه — ولی تازه است ⇒ پاک نمی‌شود
        lay = [base_layer(mask={"type": "paint", "id": "m1"})]
        self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay}}, format="json")
        d = self.media / PhotoProject.objects.get(pk=pid).dir_rel
        self.assertTrue((d / "mask-m2.png").is_file(), "ماسکِ تازه نباید پاک شود")
        old = time.time() - 3600
        os.utime(d / "mask-m2.png", (old, old))
        os.utime(d / "mask-m1.png", (old, old))
        self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay}}, format="json")
        self.assertFalse((d / "mask-m2.png").exists(), "ماسکِ کهنهٔ بی‌ارجاع پاک می‌شود")
        self.assertTrue((d / "mask-m1.png").is_file())
        self.assertEqual(self.api.delete(f"{self.base}/projects/{pid}/masks/m1/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/masks/m1/").status_code, 404)

    def test_overview_pro_and_fonts(self):
        body = self.api.get(f"{self.base}/").json()
        self.assertIn("multiply", body["pro"]["blend_modes"])
        self.assertTrue(body["pro"]["fonts"] and body["pro"]["fonts"][0]["key"] == "vazirmatn")
        fonts = self.api.get(f"{self.base}/fonts/").json()["fonts"]
        self.assertEqual(fonts[0]["family"], "Vazirmatn")
        self.assertIn(700, fonts[0]["weights"])
        self.assertTrue(fonts[0]["rtl"])
        self.assertTrue(any(t["key"] == "compose" and t["hidden"] for t in body["tools"]))

    def test_project_to_edit_end_to_end_with_mask_and_text(self):
        """پروژه (ماسک، متن فارسی، لایهٔ تنظیم) ⇐ ساخت با compose ⇐ نسخهٔ آمادهٔ خوانا؛ بی گره."""
        aid, p = self.project()
        pid = p["id"]
        mask = Image.new("L", (64, 48), 0)
        mask.paste(255, (0, 0, 32, 48))
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/masks/mk1/", png_bytes(mask), content_type="image/png").status_code, 200)
        lay = [base_layer(),
               {"id": "adj", "type": "adjust", "adjust": {"exposure": 1.5}, "mask": {"type": "paint", "id": "mk1"}},
               {"id": "tx", "type": "text", "text": "تخفیف ویژه", "size": 0.12, "cx": 0.5, "cy": 0.8, "box": {"color": "#000000", "opacity": 0.6, "pad": 0.3, "radius": 0.3}}]
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay}}, format="json").status_code, 200)
        saved = self.api.get(f"{self.base}/projects/{pid}/").json()["project"]["data"]["layers"]
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "manual", "operations": [
            {"tool": "compose", "params": {"project": pid, "layers": saved}},
            {"tool": "export", "params": {"format": "png"}}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.state, "READY", (e.error, e.message))
        self.assertEqual(e.recipe, "manual")
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        self.assertTrue(any(o["tool"] == "compose" and o["params"]["project"] == pid for o in d["operations"]), "پارامترهای compose برای بازکردنِ نسخه می‌مانند")
        res = Image.open(self.media / e.files["result"]).convert("RGB")
        orig = Image.open(self.media / PhotoAsset.objects.get(pk=aid).original).convert("RGB")
        self.assertEqual(res.size, orig.size)
        a, b = np.asarray(res, dtype=int), np.asarray(orig, dtype=int)
        left, right = a[:100, :120].mean() - b[:100, :120].mean(), a[:100, 200:].mean() - b[:100, 200:].mean()
        self.assertGreater(left, 15, "نیمهٔ چپ با ماسک روشن شد")
        self.assertLess(abs(right), 2, "نیمهٔ راست دست نخورد")
        self.assertGreater(np.abs(a[170:230, 60:260] - b[170:230, 60:260]).mean(), 8, "متن روی عکس نشست")

    def test_edit_rejects_foreign_library_image(self):
        (aid,) = self.upload(photo(200, 150))
        lay = [base_layer(), {"id": "i", "type": "image", "src": {"kind": "asset", "asset": 987654}}]
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "manual", "operations": [
            {"tool": "compose", "params": {"layers": lay}}]}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("کتابخانه", r.json()["error"]["message"])

    def test_preview_scale_and_develop_through_services(self):
        (aid,) = self.upload(photo(2400, 1600))
        asset = PhotoAsset.objects.get(pk=aid)
        data, info = services.preview(asset, [
            {"tool": "develop", "params": {"adjust": {"sharpen": 80, "sharpenRadius": 2, "exposure": 0.4}}},
            {"tool": "compose", "params": {"layers": [base_layer(), {"id": "t", "type": "text", "text": "Pre", "size": 0.1}]}}])
        im = Image.open(io.BytesIO(data))
        self.assertEqual(max(im.size), services.PREVIEW_SIDE_LIVE)
        self.assertEqual(info["skipped"], [])
        # با پیش‌نمایشِ API هم
        r = self.api.post(f"{self.base}/preview/", {"asset": aid, "operations": [
            {"tool": "develop", "params": {"adjust": {"exposure": 1}}}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r["Content-Type"], "image/jpeg")


# ═════════════════════════════ پیش‌تنظیم و اعمالِ گروهی

class PresetApiTests(ApiTestBase):
    DATA = {"adjust": {"exposure": 0.4, "saturation": 15, "bogus": 3}, "curve": {"rgb": [[0, 0], [100, 120], [255, 255]]},
            "kit_auto": True,
            "tools": {"look": {"style": "warm", "strength": 60}, "kit_preset": {"preset": "clean"}, "export": {"x": 1}},
            "layers": [{"id": "lg", "type": "image", "src": {"kind": "logo"}, "cx": 0.85, "cy": 0.9, "w": 0.2},
                       {"id": "tx", "type": "text", "text": "فروشگاه من", "size": 0.05, "cx": 0.5, "cy": 0.94,
                        "mask": {"type": "paint", "id": "zz"}},
                       {"id": "bs", "type": "base"}, {"id": "rt", "type": "retouch", "strokes": []}],
            "output": {"format": "jpeg", "quality": 88, "long_edge": 250}}

    def test_crud_normalisation(self):
        r = self.api.post(f"{self.base}/presets/", {"name": "  برند من  ", "data": self.DATA}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        p = r.json()["preset"]
        self.assertEqual(p["name"], "برند من")
        d = p["data"]
        self.assertEqual(d["adjust"], {"exposure": 0.4, "saturation": 15.0})
        self.assertEqual([l["type"] for l in d["layers"]], ["image", "text"], "عکس و روتوش حذف می‌شود")
        self.assertIsNone(d["layers"][1]["mask"], "ماسکِ رنگ‌آمیزی حذف می‌شود")
        self.assertEqual(sorted(d["tools"]), ["kit_preset", "look"])
        self.assertEqual(d["output"]["long_edge"], 250)
        self.assertEqual(len(self.api.get(f"{self.base}/presets/").json()["presets"]), 1)
        r = self.api.patch(f"{self.base}/presets/{p['id']}/", {"name": "نامِ تازه", "data": {"adjust": {"contrast": 10}}}, format="json")
        self.assertEqual(r.json()["preset"]["name"], "نامِ تازه")
        self.assertEqual(r.json()["preset"]["data"]["adjust"], {"contrast": 10.0})
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "", "data": {}}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "x", "data": [1]}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(f"{self.base}/presets/{p['id']}/", {"name": " "}, format="json").status_code, 400)
        self.assertEqual(self.api.delete(f"{self.base}/presets/{p['id']}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/presets/").json()["presets"], [])
        self.assertEqual(self.api.delete(f"{self.base}/presets/{p['id']}/").status_code, 404)

    def test_operations_node_offline_and_online(self):
        off = services.preset_operations(self.DATA, False)
        tools = [o["tool"] for o in off]
        self.assertEqual(tools, ["develop", "compose", "look", "resize", "export"])
        dev = off[0]["params"]
        self.assertEqual(dev["adjust"]["exposure"], 0.4)
        self.assertIn("rgb", dev["curve"])
        self.assertGreater(len(dev["adjust"]), 2, "فیلترِ «کیت» به لغزنده‌هایش تبدیل می‌شود")
        comp = off[1]["params"]["layers"]
        self.assertEqual([l["type"] for l in comp], ["base", "image", "text"])
        on = services.preset_operations(self.DATA, True)
        tools = [o["tool"] for o in on]
        self.assertEqual(tools, ["kit_auto", "kit_preset", "kit_adjust", "compose", "look", "resize", "export"])
        self.assertEqual(on[-1]["params"]["quality"], 88)
        # بی روکش ⇒ بی compose
        self.assertNotIn("compose", [o["tool"] for o in services.preset_operations({"adjust": {"contrast": 5}}, False)])

    def test_batch_apply_creates_edits_for_each_photo(self):
        ids = self.upload(photo(400, 300), photo(300, 400, seed=2), photo(320, 320, seed=3))
        logo = Image.new("RGBA", (80, 40), (255, 200, 0, 255))
        buf = io.BytesIO()
        logo.save(buf, "PNG")
        self.store.logo.save("logo.png", File(io.BytesIO(buf.getvalue())), save=True)
        r = self.api.post(f"{self.base}/presets/", {"name": "برندِ من", "data": self.DATA}, format="json")
        pid = r.json()["preset"]["id"]
        r = self.api.post(f"{self.base}/presets/{pid}/apply/", {"assets": ids}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(len(body["edits"]), 3)
        self.assertEqual(len({e["batch"] for e in body["edits"]}), 1)
        self.assertEqual(body["node"]["online"], False)
        for e in body["edits"]:
            self.assertEqual(e["state"], "READY", e)
        sizes = {}
        for e in PhotoEdit.objects.filter(batch=body["batch"]):
            with Image.open(self.media / e.files["result"]) as im:
                sizes[e.asset_id] = im.size
                self.assertEqual(max(im.size), 250, "long_edge=250")
        self.assertAlmostEqual(sizes[ids[0]][0] / sizes[ids[0]][1], 4 / 3, delta=0.02)
        self.assertAlmostEqual(sizes[ids[1]][1] / sizes[ids[1]][0], 4 / 3, delta=0.02, msg="همان پیش‌تنظیم روی نسبتِ دیگر هم جا می‌افتد")
        # لوگو گوشهٔ پایین-راست نشسته
        e0 = PhotoEdit.objects.get(batch=body["batch"], asset_id=ids[0])
        with Image.open(self.media / e0.files["result"]) as im:
            w, h = im.size
            self.assertGreater(px(im, int(w * 0.85), int(h * 0.9))[0], 200)
        self.assertEqual(self.api.post(f"{self.base}/presets/{pid}/apply/", {"assets": []}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/presets/999999/apply/", {"assets": ids}, format="json").status_code, 404)
        # گرهٔ آنلاین ⇒ کارِ کیت در صف
        self.node()
        r = self.api.post(f"{self.base}/presets/{pid}/apply/", {"assets": ids[:2]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(all(e["state"] == "NODE" for e in r.json()["edits"]), [e["state"] for e in r.json()["edits"]])
        kit_tools = [o["tool"] for o in r.json()["edits"][0]["operations"]]
        self.assertIn("kit_adjust", kit_tools)
        self.assertIn("compose", kit_tools)


# ═════════════════════════════ پیش‌نمایشِ دقیق و انتخابِ سوژه

class ExactAndSubjectTests(ApiTestBase):
    KIT_OPS = [{"tool": "kit_adjust", "params": {"adjust": {"exposure": 0.5, "sharpen": 50, "sharpenRadius": 2}}},
               {"tool": "kit_background", "params": {}}, {"tool": "text", "params": {"text": "x"}}]

    def test_offline_says_so(self):
        (aid,) = self.upload(photo(400, 300))
        r = self.api.post(f"{self.base}/exact/", {"asset": aid, "operations": self.KIT_OPS}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["online"], False)
        self.assertEqual(r.json()["state"], "OFFLINE")
        self.assertEqual(ComputeJob.objects.filter(origin="photoexact").count(), 0)

    def test_queue_complete_cancel_and_isolation(self):
        (aid,) = self.upload(photo(1600, 1200))
        node = self.node()
        r = self.api.post(f"{self.base}/exact/", {"asset": aid, "operations": self.KIT_OPS, "side": 800}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["online"])
        self.assertEqual(body["state"], "QUEUED")
        self.assertEqual(max(body["size"]), 800)
        self.assertEqual(body["ignored"], [catalog.tools()["kit_background"]["title"]])
        job = ComputeJob.objects.get(uid=body["job"])
        self.assertEqual(job.kind, "photo.edit")
        self.assertEqual(job.origin, "photoexact")
        recipe = job.payload["recipe"]
        self.assertEqual(recipe["adjust"]["exposure"], 0.5)
        self.assertAlmostEqual(recipe["adjust"]["sharpenRadius"], 1.0, places=2)     # ۲ × (۸۰۰ ÷ ۱۶۰۰)
        self.assertEqual(recipe["output"]["format"], "jpeg")
        self.assertEqual(recipe["output"]["quality"], 90)
        st = self.api.get(f"{self.base}/exact/{body['job']}/").json()
        self.assertEqual(st["state"], "QUEUED")
        self.assertIsNone(st["url"])
        # گرهٔ ساختگی
        done = services.exact_finish_for_test(job, node, factor=1.3)
        self.assertEqual(done.state, ComputeJob.State.COMPLETED)
        st = self.api.get(f"{self.base}/exact/{body['job']}/").json()
        self.assertEqual(st["state"], "COMPLETED", st)
        self.assertEqual(st["node"], node.name)
        self.assertIn("/media/", st["url"])
        self.assertEqual(max(st["size"]), 800)
        rel = st["url"].split("?")[0].replace("/media/", "")
        self.assertTrue((self.media / rel).is_file())
        # درخواستِ یکسان ⇐ همان نتیجهٔ کامل (بی کارِ تازه)
        r2 = self.api.post(f"{self.base}/exact/", {"asset": aid, "operations": self.KIT_OPS, "side": 800}, format="json").json()
        self.assertEqual(r2["state"], "COMPLETED")
        # درخواستِ کهنه لغو می‌شود
        r3 = self.api.post(f"{self.base}/exact/", {"asset": aid, "operations": [
            {"tool": "kit_adjust", "params": {"adjust": {"exposure": -0.5}}}]}, format="json").json()
        self.assertEqual(r3["state"], "QUEUED")
        self.assertEqual(self.api.delete(f"{self.base}/exact/{r3['job']}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/exact/{r3['job']}/").json()["state"], "CANCELLED")
        # فقط کارهای سبکِ سرور ⇒ NOOP
        r4 = self.api.post(f"{self.base}/exact/", {"asset": aid, "operations": [{"tool": "text", "params": {"text": "x"}}]}, format="json").json()
        self.assertEqual(r4["state"], "NOOP")
        # کارِ فروشگاهِ دیگر دیده نمی‌شود
        other = ComputeJob.objects.create(kind="photo.edit", origin="photoexact", payload={})
        self.assertEqual(self.api.get(f"{self.base}/exact/{other.uid}/").status_code, 404)
        self.assertEqual(self.api.get(f"{self.base}/exact/00000000-0000-0000-0000-000000000000/").status_code, 404)

    def test_fake_node_command_drives_exact_and_subject(self):
        from django.core.management import call_command

        (aid,) = self.upload(photo(600, 400))
        call_command("photoedit_fake_node", "online", stdout=io.StringIO())
        r = self.api.post(f"{self.base}/exact/", {"asset": aid, "operations": [
            {"tool": "kit_adjust", "params": {"adjust": {"exposure": 0.7}}}]}, format="json").json()
        self.assertEqual(r["state"], "QUEUED", r)
        call_command("photoedit_fake_node", "finish", "--factor", "1.4", stdout=io.StringIO())
        st = self.api.get(f"{self.base}/exact/{r['job']}/").json()
        self.assertEqual(st["state"], "COMPLETED")
        self.assertEqual(st["node"], "gpu-fake")
        s = self.api.post(f"{self.base}/subject/", {"asset": aid}, format="json").json()
        self.assertEqual((s["state"], s["method"]), ("QUEUED", "kit"))
        self.assertEqual(self.api.delete(f"{self.base}/subject/{s['job']}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/subject/{s['job']}/").json()["state"], "CANCELLED")
        s2 = self.api.post(f"{self.base}/subject/", {"asset": aid, "rect": [0.1, 0.1, 0.8, 0.8]}, format="json").json()
        call_command("photoedit_fake_node", "finish", stdout=io.StringIO())
        self.assertEqual(self.api.get(f"{self.base}/subject/{s2['job']}/").json()["state"], "READY")
        # کارِ واقعیِ کاربر (origin دیگر) را برنمی‌دارد
        real = ComputeJob.objects.create(kind="photo.edit", origin="photoedit", payload={"image": "x.jpg"})
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("photoedit_fake_node", "finish", stdout=io.StringIO())
        real.refresh_from_db()
        self.assertEqual(real.state, ComputeJob.State.QUEUED)
        call_command("photoedit_fake_node", "offline", stdout=io.StringIO())
        self.assertFalse(ComputeNode.objects.filter(name="gpu-fake").exists())

    def test_subject_grabcut_fallback_and_alpha(self):
        img = Image.new("RGB", (400, 300), (235, 235, 235))
        d = ImageDraw.Draw(img)
        d.ellipse([130, 70, 280, 230], fill=(180, 30, 30))
        d.ellipse([160, 100, 250, 190], fill=(220, 60, 60))
        (aid,) = self.upload(img)
        r = self.api.post(f"{self.base}/subject/", {"asset": aid}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["state"], body["method"]), ("READY", "grabcut"))
        rel = body["url"].split("?")[0].replace("/media/", "")
        m = np.asarray(Image.open(self.media / rel).convert("L"))
        self.assertEqual(Image.open(self.media / rel).mode, "L")
        h, w = m.shape
        self.assertGreater(int(m[h // 2, w // 2]), 200, "وسطِ سوژه در ماسک")
        self.assertLess(int(m[8, 8]), 40, "گوشهٔ زمینه خارج از ماسک")
        self.assertLessEqual(max(w, h), 512)
        # عکسِ شفاف ⇐ همان آلفا
        al = photo(200, 150, alpha=True)
        (aid2,) = [a["id"] for a in self.api.post(f"{self.base}/assets/", {"files": [jpeg_file(al, "a.png", "PNG")]}, format="multipart").json()["assets"]]
        b2 = self.api.post(f"{self.base}/subject/", {"asset": aid2}, format="json").json()
        self.assertEqual(b2["method"], "alpha")

    def test_subject_with_node_online_uses_kit_job(self):
        (aid,) = self.upload(photo(500, 400))
        node = self.node()
        r = self.api.post(f"{self.base}/subject/", {"asset": aid}, format="json").json()
        self.assertEqual((r["state"], r["method"]), ("QUEUED", "kit"))
        job = ComputeJob.objects.get(uid=r["job"])
        self.assertEqual(job.payload["recipe"]["background"]["color"], "transparent")
        self.assertEqual(job.payload["recipe"]["output"]["format"], "png")
        # گرهٔ ساختگی خروجیِ PNG ِ شفاف می‌دهد
        got = compute.claim(node)
        self.assertEqual(got.pk, job.pk)
        root = compute.job_root(job)
        src = Image.open(root / "inputs" / job.payload["image"]).convert("RGBA")
        a = Image.new("L", src.size, 0)
        ImageDraw.Draw(a).ellipse([src.width * 0.25, src.height * 0.25, src.width * 0.75, src.height * 0.75], fill=255)
        src.putalpha(a)
        name = "subject-edited.png"
        src.save(compute.output_path(job, name))
        compute.finish(job, node, True, meta={"primary": name})
        st = self.api.get(f"{self.base}/subject/{r['job']}/").json()
        self.assertEqual((st["state"], st["method"]), ("READY", "kit"), st)
        rel = st["url"].split("?")[0].replace("/media/", "")
        m = np.asarray(Image.open(self.media / rel))
        self.assertGreater(int(m[m.shape[0] // 2, m.shape[1] // 2]), 250)
        self.assertEqual(int(m[2, 2]), 0)
