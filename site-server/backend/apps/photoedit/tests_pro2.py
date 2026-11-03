"""«pro 2» سمتِ سرور: قرمزیِ چشم، افکتِ لایه (سایه/درخشش/خطِ دور)، گروه و برش (clip)، مسیرِ قلم (pen) ⇒ ماسک و شکلِ path،
نقشهٔ مایع‌سازی (liquify) با فایل و API. همه بی شبکه و بی هوشِ مصنوعی؛ فرمول‌ها با مرجعِ پایتونِ خالص سنجیده می‌شوند."""
import math
import os
import shutil
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from . import catalog, fx as fxmod, layers, liquify, ops, paths, redeye, services
from .models import PhotoAsset, PhotoEdit, PhotoProject
from .tests import ApiTestBase, photo


# ───────────────────────────── کمکی‌ها

def solid(w, h, color):
    return Image.new("RGB", (w, h), color)


def ctx(**kw):
    return {"notes": [], "store_name": "x", "logo_path": lambda p: None, "mask_path": lambda pid, mid: None,
            "scale": 1.0} | kw


def base_layer(**kw):
    return {"id": "base", "type": "base"} | kw


def rect(lid, cx=0.5, cy=0.5, w=0.5, h=0.5, color="#ff0000", fill_opacity=1.0, **kw):
    """مستطیلِ پرِ تک‌رنگ؛ w و h کسری از پهنای بوم اند (h هم). ``opacity`` در kw پیدایی **لایه** است؛ آلفای پر ``fill_opacity``."""
    return {"id": lid, "type": "shape", "shape": "rect", "cx": cx, "cy": cy, "w": w, "h": h,
            "fill": {"type": "solid", "color": color, "opacity": fill_opacity}} | kw


def group(gid, **kw):
    return {"id": gid, "type": "group"} | kw


def compose(base, lst, **kw):
    c = ctx(**kw)
    return layers.compose(base, layers.normalize_layers(lst), c), c


def px(img, x, y):
    return tuple(int(v) for v in np.asarray(img.convert("RGB"))[y, x])


def pxa(img, x, y):
    return tuple(int(v) for v in np.asarray(img.convert("RGBA"))[y, x])


def arr(img):
    return np.asarray(img.convert("RGB"), dtype=int)


def transparent(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def circle_path(cx=0.5, cy=0.5, rx=0.4, ry=0.4):
    """چهار نقطهٔ بزیه (راست، پایین، چپ، بالا) ⇒ دایره/بیضی در یک جعبهٔ نرمال."""
    k = 0.5522847498
    return {"closed": True, "pts": [
        {"x": cx + rx, "y": cy, "hi": [0, -ry * k], "ho": [0, ry * k]},
        {"x": cx, "y": cy + ry, "hi": [rx * k, 0], "ho": [-rx * k, 0]},
        {"x": cx - rx, "y": cy, "hi": [0, ry * k], "ho": [0, -ry * k]},
        {"x": cx, "y": cy - ry, "hi": [-rx * k, 0], "ho": [rx * k, 0]}]}


def square_path(x0=0.25, y0=0.25, x1=0.75, y1=0.75):
    return {"closed": True, "pts": [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]}


def poly_area(pts):
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    return abs(float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))) / 2


# ═════════════════════════════ قرمزیِ چشم

class RedEyeTests(SimpleTestCase):
    SKIN = (200, 150, 130)

    def eye_image(self, w=200, h=200, pupil=(220, 30, 30), pupil_r=6):
        img = Image.new("RGB", (w, h), self.SKIN)
        a = np.asarray(img).copy()
        yy, xx = np.mgrid[0:h, 0:w]
        a[(xx + 0.5 - w / 2) ** 2 + (yy + 0.5 - h / 2) ** 2 <= pupil_r ** 2] = pupil
        return Image.fromarray(a, "RGB")

    def layer(self, **kw):
        return {"id": "re", "type": "redeye", "eyes": [{"x": 0.5, "y": 0.5, "r": 0.05}], "amount": 1.0, "darken": 0.6} | kw

    def test_normalize_schema_and_limits(self):
        out = layers.normalize_layers([base_layer(), {"id": "re", "type": "redeye", "blend": "multiply", "junk": 1, "amount": 9,
                                                      "darken": -1, "eyes": [{"x": 5, "y": -2, "r": 9, "z": 1}, "bad"]}])
        re_ = out[1]
        self.assertEqual(re_["blend"], "normal", "قرمزیِ چشم حالتِ ترکیب ندارد")
        self.assertEqual(re_["amount"], 1.0)
        self.assertEqual(re_["darken"], 0.0)
        self.assertEqual(re_["eyes"], [{"x": 1.0, "y": 0.0, "r": 0.1}])
        self.assertNotIn("junk", re_)
        self.assertEqual(re_["parent"], None)
        self.assertFalse(re_["clip"], "clip برای قرمزیِ چشم همیشه False است")
        d = layers.normalize_layers([base_layer(), {"id": "re", "type": "redeye"}])[1]
        self.assertEqual((d["amount"], d["darken"], d["eyes"]), (1.0, 0.6, []))
        ok = [{"x": 0.1 * (i % 9), "y": 0.5, "r": 0.01} for i in range(16)]
        self.assertEqual(len(layers.normalize_layers([base_layer(), {"id": "re", "type": "redeye", "eyes": ok}])[1]["eyes"]), 16)
        with self.assertRaisesRegex(catalog.CatalogError, "چشم"):
            layers.normalize_layers([base_layer(), {"id": "re", "type": "redeye", "eyes": ok + [{"x": 0.5, "y": 0.5, "r": 0.01}]}])

    def test_red_pupil_becomes_dark_neutral_and_skin_is_untouched(self):
        img = self.eye_image()
        out, _ = compose(img, [base_layer(), self.layer()])
        r, g, b = px(out, 100, 100)
        self.assertLess(max(r, g, b), 40, "مردمکِ قرمز تیره می‌شود")
        self.assertLess(abs(r - g), 6, "و خنثی")
        self.assertLess(abs(g - b), 2)
        # مرجعِ دقیقِ همان پیکسل: R=220, G=B=30, darken=0.6 ⇒ R'=neutral·0.7=21، G'=B'=30·0.76=22.8
        self.assertEqual(px(out, 100, 100), (21, 23, 23))
        a, o = np.asarray(img), np.asarray(out)
        diff = np.abs(a.astype(int) - o.astype(int)).sum(axis=2) > 0
        ys, xs = np.nonzero(diff)
        self.assertGreater(diff.sum(), 80)
        self.assertLess(np.hypot(xs + 0.5 - 100, ys + 0.5 - 100).max(), 7.5, "فقط خودِ مردمک (پوست ratio<1.4 است)")
        # پوستِ درونِ شعاع و بیرونِ کادر
        self.assertEqual(px(out, 100 + 9, 100), self.SKIN)
        self.assertEqual(px(out, 5, 5), self.SKIN)

    def test_amount_darken_opacity_and_empty(self):
        img = self.eye_image()
        zero, _ = compose(img, [base_layer(), self.layer(amount=0)])
        self.assertTrue(ops.same_image(zero, img), "amount=0 بی‌اثر است")
        none, _ = compose(img, [base_layer(), self.layer(eyes=[])])
        self.assertTrue(ops.same_image(none, img))
        half, _ = compose(img, [base_layer(), self.layer(amount=0.5)])
        # m=0.5: R' = 220 + (21−220)·0.5 ≈ 120.7 ؛ G' = 30·(1−0.4·0.6·0.5)=26.4
        r, g, b = px(half, 100, 100)
        self.assertAlmostEqual(r, 220 + (min(220, 30 * 0.7) - 220) * 0.5, delta=1.5)
        self.assertAlmostEqual(g, 30 * (1 - 0.4 * 0.6 * 0.5), delta=1.5)
        flat, _ = compose(img, [base_layer(), self.layer(darken=0)])
        self.assertEqual(px(flat, 100, 100), (30, 30, 30), "darken=0 ⇒ فقط R به خنثی می‌رسد")
        deep, _ = compose(img, [base_layer(), self.layer(darken=1)])
        self.assertEqual(px(deep, 100, 100), (15, 18, 18))
        # پیدایی لایه: وسطِ رنگِ پیشین و رنگِ اصلاح‌شده
        op, _ = compose(img, [base_layer(), self.layer(opacity=0.5)])
        self.assertAlmostEqual(px(op, 100, 100)[0], (220 + 21) / 2, delta=1.5)
        # لایهٔ اول (چیزی زیرش نیست) و پنهان بی‌اثرند
        only, _ = compose(img, [self.layer(), base_layer()])
        self.assertTrue(ops.same_image(only, img))
        hid, _ = compose(img, [base_layer(), self.layer(visible=False)])
        self.assertTrue(ops.same_image(hid, img))

    def test_mask_selects_the_eye(self):
        img = self.eye_image(w=300, h=200)
        a = np.asarray(img).copy()
        yy, xx = np.mgrid[0:200, 0:300]
        for cx in (75, 225):
            a[(xx + 0.5 - cx) ** 2 + (yy + 0.5 - 100) ** 2 <= 36] = (220, 30, 30)
        img = Image.fromarray(a, "RGB")
        eyes = [{"x": 0.25, "y": 0.5, "r": 0.03}, {"x": 0.75, "y": 0.5, "r": 0.03}]
        lay = self.layer(eyes=eyes, mask={"type": "radial", "c": [0.25, 0.5], "rx": 0.08, "ry": 0.08, "feather": 0})
        out, _ = compose(img, [base_layer(), lay])
        self.assertLess(px(out, 75, 100)[0], 40, "چشمِ داخلِ ماسک اصلاح شد")
        self.assertEqual(px(out, 225, 100), (220, 30, 30), "چشمِ بیرونِ ماسک دست نخورد")
        inv, _ = compose(img, [base_layer(), dict(lay, mask=dict(lay["mask"], invert=True))])
        self.assertEqual(px(inv, 75, 100), (220, 30, 30))
        self.assertLess(px(inv, 225, 100)[0], 40)

    def test_formula_matches_pure_python_reference(self):
        rng = np.random.default_rng(7)
        a = rng.integers(0, 256, (100, 120, 3), dtype=np.uint8)
        a[..., 1:] //= 3                      # قرمزی زیاد ⇒ ناحیهٔ عملیاتی بزرگ
        img = Image.fromarray(a, "RGB")
        eye = {"x": 0.45, "y": 0.5, "r": 0.1}
        amount, darken = 0.8, 0.3
        out, _ = compose(img, [base_layer(), self.layer(eyes=[eye], amount=amount, darken=darken)])
        o = np.asarray(out)
        W, H = 120, 100
        box = redeye.eye_box(eye, W, H)
        changed = 0
        worst = 0
        for y in range(H):
            for x in range(W):
                if box[0] <= x < box[2] and box[1] <= y < box[3]:
                    want = redeye.reference_pixel(a[y, x] / 255.0, x + 0.5, y + 0.5, eye, amount, darken, W, H)
                    want = [math.floor(v * 255 + 0.5) for v in want]
                    got = o[y, x].tolist()
                    worst = max(worst, max(abs(g - w) for g, w in zip(got, want)))
                    changed += got != a[y, x].tolist()
                else:
                    self.assertEqual(o[y, x].tolist(), a[y, x].tolist(), f"بیرونِ کادر عوض شد ({x},{y})")
        self.assertLessEqual(worst, 1, "فرمولِ numpy با مرجعِ پایتون یکی نیست")
        self.assertGreater(changed, 100)
        # smoothstep: مرکز m کامل، لبهٔ ۱٫۲r صفر
        self.assertAlmostEqual(float(redeye.smoothstep(0, 1, np.float32(0.5))), 0.5, places=6)
        self.assertEqual(float(redeye.smoothstep(1.4, 2.4, np.float32(1.0))), 0.0)
        self.assertEqual(float(redeye.smoothstep(1.4, 2.4, np.float32(3.0))), 1.0)

    def test_two_eyes_and_edge_of_canvas(self):
        img = Image.new("RGB", (100, 80), (60, 60, 60))
        a = np.asarray(img).copy()
        a[0:6, 0:6] = (230, 20, 20)             # چشم در گوشهٔ بوم
        a[40:46, 60:66] = (230, 20, 20)
        img = Image.fromarray(a, "RGB")
        lay = self.layer(eyes=[{"x": 0.03, "y": 0.04, "r": 0.04}, {"x": 0.63, "y": 0.5375, "r": 0.04}])
        out, _ = compose(img, [base_layer(), lay])
        self.assertLess(px(out, 2, 2)[0], 60)
        self.assertLess(px(out, 62, 42)[0], 60)
        self.assertEqual(px(out, 30, 30), (60, 60, 60))


# ═════════════════════════════ افکتِ لایه

class FxTests(SimpleTestCase):
    W, H = 400, 300

    def white(self):
        return solid(self.W, self.H, (255, 255, 255))

    def layer(self, fx=None, **kw):
        # مستطیلِ قرمزِ ۱۰۰×۶۰ px با مرکزِ (۲۰۰، ۱۵۰) ⇒ x:۱۵۰…۲۵۰ ، y:۱۲۰…۱۸۰
        return rect("r", cx=0.5, cy=0.5, w=0.25, h=0.15, fx=fx, **kw)

    def render(self, fx, base=None, **kw):
        return compose(base or self.white(), [base_layer(), self.layer(fx, **kw)])[0]

    def test_fx_none_and_empty_are_unchanged(self):
        plain = self.render(None)
        for fx in ({}, {"shadow": None, "stroke": None, "glow": None},
                   {"shadow": {"opacity": 0}}, {"stroke": {"w": 0}}, {"glow": {"opacity": 0}}):
            self.assertTrue(ops.same_image(self.render(fx), plain), fx)
        norm = layers.normalize_layers([base_layer(), self.layer({})])[1]
        self.assertIsNone(norm["fx"])
        self.assertIn("fx", norm)

    def test_normalize_fx_schema_clamps_and_types(self):
        fx = {"shadow": {"color": "red", "opacity": 5, "blur": 9, "dx": 9, "dy": -9, "x": 1},
              "stroke": {"w": 5}, "glow": {"color": "#ABCDEF", "size": 9, "blur": -1}}
        n = layers.normalize_layers([base_layer(), self.layer(fx)])[1]["fx"]
        self.assertEqual(n["shadow"], {"color": "#000000", "opacity": 1.0, "blur": 0.2, "dx": 0.5, "dy": -0.5})
        self.assertEqual(n["stroke"], {"color": "#ffffff", "w": 0.05, "opacity": 1.0})
        self.assertEqual(n["glow"], {"color": "#abcdef", "opacity": 0.8, "blur": 0.0, "size": 0.05})
        d = layers.normalize_layers([base_layer(), self.layer({"shadow": {}, "stroke": {}, "glow": {}})])[1]["fx"]
        self.assertEqual(d["shadow"], {"color": "#000000", "opacity": 0.5, "blur": 0.012, "dx": 0.01, "dy": 0.01})
        self.assertEqual(d["stroke"], {"color": "#ffffff", "w": 0.004, "opacity": 1.0})
        self.assertEqual(d["glow"], {"color": "#ffd479", "opacity": 0.8, "blur": 0.02, "size": 0.006})
        # فقط image|text|shape fx دارند
        out = layers.normalize_layers([base_layer(), group("g", fx=fx), {"id": "a", "type": "adjust", "fx": fx}])
        self.assertTrue(all("fx" not in l for l in out))
        again = layers.normalize_layers([base_layer(), self.layer(fx)])
        self.assertEqual(layers.normalize_layers(again), again, "normalize باید خودتوان باشد")

    def test_shadow_offset_opacity_and_direction(self):
        fx = {"shadow": {"color": "#000000", "opacity": 1, "blur": 0, "dx": 0.05, "dy": 0.025}}   # ۲۰ px راست، ۱۰ px پایین
        out = self.render(fx)
        self.assertEqual(px(out, 200, 150), (255, 0, 0), "پیکسل‌های خودِ لایه")
        self.assertEqual(px(out, 260, 150), (0, 0, 0), "سایه: سمتِ راست")
        self.assertEqual(px(out, 175, 185), (0, 0, 0), "سایه: زیرِ لایه")
        self.assertEqual(px(out, 255, 125), (255, 255, 255), "بالای سایه")
        self.assertEqual(px(out, 160, 190), (255, 255, 255), "چپِ سایه")
        # شدتِ نصف ⇒ خاکستری
        half = self.render(dict(fx, shadow=dict(fx["shadow"], opacity=0.5)))
        self.assertAlmostEqual(px(half, 260, 150)[0], 127.5, delta=1.5)
        # dx منفی ⇒ سمتِ چپ
        left = self.render({"shadow": {"color": "#000000", "opacity": 1, "blur": 0, "dx": -0.05, "dy": 0}})
        self.assertEqual(px(left, 140, 150), (0, 0, 0))
        self.assertEqual(px(left, 260, 150), (255, 255, 255))
        # رنگِ سایه
        blue = self.render({"shadow": {"color": "#0000ff", "opacity": 1, "blur": 0, "dx": 0.05, "dy": 0}})
        self.assertEqual(px(blue, 260, 150), (0, 0, 255))

    def test_shadow_blur_is_gaussian_sigma_blur_times_W(self):
        fx = {"shadow": {"color": "#000000", "opacity": 1, "blur": 0.02, "dx": 0.05, "dy": 0.025}}   # σ = 8 px
        out = arr(self.render(fx))
        # لبهٔ راستِ سایه x=۲۷۰ ⇒ حدودِ نصف؛ دورتر از لبه ⇒ صفر
        self.assertTrue(100 <= out[160, 269, 1] <= 160, out[160, 269])
        self.assertGreater(out[160, 300, 1], 250)
        # درونِ سایه (ولی بیرونِ لایه) تیره و یکنواخت‌تر از لبه
        self.assertLess(out[160, 258, 1], 60)
        # تقارنِ گاوسی: افتِ پله‌ای σ=۸ ⇒ مقدار در ۸ px بیرون ≈ ۱۶٪ و در ۸ px درون ≈ ۸۴٪ سایه
        want_out = 255 * (1 - 0.1587)
        want_in = 255 * (1 - 0.8413)
        self.assertAlmostEqual(out[165, 270 + 8, 1], want_out, delta=12)
        self.assertAlmostEqual(out[165, 270 - 8, 1], want_in, delta=12)

    def test_stroke_width_color_and_round_corner(self):
        fx = {"stroke": {"color": "#00ff00", "w": 0.01, "opacity": 1}}      # ۴ px
        out = self.render(fx)
        self.assertEqual(px(out, 148, 150), (0, 255, 0))
        self.assertEqual(px(out, 252, 150), (0, 255, 0))
        self.assertEqual(px(out, 200, 118), (0, 255, 0), "بالا")
        self.assertEqual(px(out, 144, 150), (255, 255, 255), "۶ px بیرون ⇒ سفید")
        self.assertEqual(px(out, 200, 150), (255, 0, 0), "لایه روی خط دور است")
        # هستهٔ elliptical ِ cv2 با r=4 ⇒ نیم‌پهنای ردیف dy برابرِ round(√(16−dy²)) ؛ گوشه‌ها گرد ولی کمی چهارگوش‌تر از دیسکِ ریاضی
        self.assertEqual(px(out, 146, 116), (255, 255, 255), "گوشه گرد است (۴ و ۴ دورتر از لایه)")
        self.assertEqual(px(out, 147, 117), (0, 255, 0), "(۳، ۳) هنوز داخلِ هستهٔ ۹×۹ ِ cv2 است")
        self.assertEqual(px(out, 148, 118), (0, 255, 0))
        # ضخامتِ ۲ برابر ⇒ ۸ px
        wide = self.render({"stroke": {"color": "#00ff00", "w": 0.02, "opacity": 1}})
        self.assertEqual(px(wide, 144, 150), (0, 255, 0))
        self.assertEqual(px(wide, 140, 150), (255, 255, 255))
        # پیدایی نصف
        half = self.render({"stroke": {"color": "#000000", "w": 0.01, "opacity": 0.5}})
        self.assertAlmostEqual(px(half, 148, 150)[0], 127.5, delta=1.5)

    def test_glow_blur_size_opacity(self):
        fx = {"glow": {"color": "#ffd479", "opacity": 0.8, "blur": 0.02, "size": 0.01}}        # دیلیت ۴ px و σ=۸ px
        out = arr(self.render(fx))
        near, mid, far = out[150, 252], out[150, 262], out[150, 330]
        self.assertTrue((far == 255).all())
        self.assertLess(near[2], mid[2], "به لبه که نزدیک‌تر شویم پررنگ‌تر")
        self.assertLess(mid[2], 250)
        # B ِ رنگ ۱۲۱: در لبهٔ دیلیت (x=۲۵۴) آلفا ≈ ۰٫۵·۰٫۸ ⇒ B ≈ 255·0.6 + 121·0.4
        self.assertAlmostEqual(out[150, 254, 2], 255 * 0.6 + 121 * 0.4, delta=14)
        sharp = arr(self.render({"glow": {"color": "#ffd479", "opacity": 0.8, "blur": 0.0, "size": 0.01}}))
        want = 255 * 0.2 + np.array([255, 212, 121]) * 0.8          # آلفای ۰٫۸ از رنگِ درخشش روی سفید
        self.assertTrue(np.abs(sharp[150, 252] - want).max() <= 2, sharp[150, 252])
        self.assertTrue((sharp[150, 258] == 255).all(), "بدون blur درخشش دقیقاً ۴ پیکسل است")

    def test_alpha_math_and_draw_order(self):
        clear = transparent(self.W, self.H)
        fx = {"shadow": {"color": "#000000", "opacity": 0.5, "blur": 0, "dx": 0.05, "dy": 0}}
        out = self.render(fx, base=clear)
        self.assertEqual(out.mode, "RGBA")
        r, g, b, a = pxa(out, 260, 150)
        self.assertEqual((r, g, b), (0, 0, 0))
        self.assertAlmostEqual(a, 127.5, delta=1.01)
        self.assertEqual(pxa(out, 200, 150), (255, 0, 0, 255))
        self.assertEqual(pxa(out, 140, 150)[3], 0)
        # لایهٔ نیمه‌شفاف روی سایه: «over» ِ مستقیم ⇒ a=۱ ، رنگ = ۵۰٪ قرمز + ۵۰٪ سیاه
        lay = rect("r", cx=0.5, cy=0.5, w=0.25, h=0.15, fill_opacity=0.5,
                   fx={"shadow": {"color": "#000000", "opacity": 1, "blur": 0, "dx": 0.025, "dy": 0}})
        out = compose(clear, [base_layer(), lay])[0]
        # سایه از آلفای خودِ لایه ساخته می‌شود (۰٫۵)، پس: a = ۰٫۵ + ۰٫۵·۰٫۵ = ۰٫۷۵ ؛ رنگِ مستقیم = (۲۵۵·۰٫۵)/۰٫۷۵ = ۱۷۰
        r, g, b, a = pxa(out, 200, 150)
        self.assertAlmostEqual(a, 191.6, delta=1.5)
        self.assertAlmostEqual(r, 170, delta=2)
        self.assertEqual((g, b), (0, 0))
        # ترتیبِ رسم: سایه < درخشش < خط دور < لایه
        fx3 = {"shadow": {"color": "#000000", "opacity": 1, "blur": 0, "dx": 0.02, "dy": 0},      # ۸ px
               "stroke": {"color": "#00ff00", "w": 0.01, "opacity": 1},                          # ۴ px
               "glow": {"color": "#ffff00", "opacity": 1, "blur": 0, "size": 0.01}}              # ۴ px
        o = self.render(fx3)
        self.assertEqual(px(o, 252, 150), (0, 255, 0), "خط دور روی درخشش و سایه")
        self.assertEqual(px(o, 256, 150), (0, 0, 0), "فقط سایه")
        o = self.render(dict(fx3, stroke=None))
        self.assertEqual(px(o, 252, 150), (255, 255, 0), "درخشش روی سایه")
        o = self.render(dict(fx3, stroke={"color": "#00ff00", "w": 0.005, "opacity": 1}))      # خط دور ۲ px
        self.assertEqual(px(o, 251, 150), (0, 255, 0))
        self.assertEqual(px(o, 253, 150), (255, 255, 0), "درخشش بیرونِ خط دور")

    def test_fx_rotates_with_layer(self):
        fx = {"shadow": {"color": "#000000", "opacity": 1, "blur": 0, "dx": 0.05, "dy": 0}}     # ۲۰ px در قابِ لایه
        out = self.render(fx, rot=90)
        # لایه ۶۰×۱۰۰ می‌شود (x:۱۷۰…۲۳۰ ، y:۱۰۰…۲۰۰)؛ +x ِ لایه ⇒ پایین
        self.assertEqual(px(out, 200, 150), (255, 0, 0))
        self.assertEqual(px(out, 200, 210), (0, 0, 0), "سایه زیرِ لایهٔ چرخیده")
        self.assertEqual(px(out, 240, 150), (255, 255, 255))
        out = self.render(fx, rot=180)
        self.assertEqual(px(out, 140, 150), (0, 0, 0), "۱۸۰° ⇒ سایه سمتِ چپ")

    def test_fx_on_text_shape_image_and_flip(self):
        base = self.white()
        txt = {"id": "t", "type": "text", "text": "Hello", "size": 0.12, "color": "#ff0000", "cx": 0.5, "cy": 0.5,
               "fx": {"stroke": {"color": "#0000ff", "w": 0.01, "opacity": 1}}}
        with_fx = arr(compose(base, [base_layer(), txt])[0])
        without = arr(compose(base, [base_layer(), dict(txt, fx=None)])[0])
        blue = lambda a: int(((a[..., 2] > 200) & (a[..., 0] < 60)).sum())
        self.assertEqual(blue(without), 0)
        self.assertGreater(blue(with_fx), 300, "خطِ دورِ آبیِ متن")
        # الگوی تکرارشونده + افکت: خطا نمی‌دهد و هم‌اندازهٔ بوم می‌ماند
        tiled = dict(txt, tile={"angle": 28, "gap": 1.6}, size=0.05, fx={"shadow": {"color": "#000000", "opacity": 0.5, "blur": 0.004, "dx": 0.004, "dy": 0.004}})
        out, _ = compose(base, [base_layer(), tiled])
        self.assertEqual(out.size, base.size)
        # عکس: نیمهٔ چپ قرمز، نیمهٔ راست آبی؛ قرینه نباید سایه را قرینه کند
        d = Path(tempfile.mkdtemp(prefix="nmphoto-fx-"))
        self.addCleanup(shutil.rmtree, d, True)
        tile = Image.new("RGB", (100, 50), (255, 0, 0))
        tile.paste((0, 0, 255), (50, 0, 100, 50))
        tile.save(d / "t.png")
        fx = {"shadow": {"color": "#000000", "opacity": 1, "blur": 0, "dx": 0.05, "dy": 0}}
        img_layer = {"id": "i", "type": "image", "src": {"kind": "logo"}, "cx": 0.5, "cy": 0.5, "w": 0.25, "fx": fx}
        for flip in (False, True):
            out, _ = compose(base, [base_layer(), dict(img_layer, flip_h=flip)], logo_path=lambda p: d / "t.png")
            left = (0, 0, 255) if flip else (255, 0, 0)
            self.assertEqual(px(out, 170, 150), left, "قرینه پیش از افکت")
            self.assertEqual(px(out, 260, 150), (0, 0, 0), f"سایه سمتِ راست می‌ماند (flip={flip})")
            self.assertEqual(px(out, 140, 150), (255, 255, 255))
        # شکلِ بیضی و خطِ دور روی شکلِ دارای stroke خودش
        ell = {"id": "e", "type": "shape", "shape": "ellipse", "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2,
               "fill": {"type": "solid", "color": "#ffffff", "opacity": 1}, "fx": {"glow": {"color": "#ff0000", "opacity": 1, "blur": 0, "size": 0.01}}}
        out, _ = compose(solid(self.W, self.H, (0, 0, 0)), [base_layer(), ell])
        self.assertEqual(px(out, 200, 150), (255, 255, 255))
        self.assertEqual(px(out, 200 + 42, 150), (255, 0, 0), "درخششِ ۴ px دورِ بیضی")
        self.assertEqual(px(out, 200 + 50, 150), (0, 0, 0))

    def test_hidden_big_fx_and_perf(self):
        t = time.time()
        base = photo(1800, 1200)
        fx = {"shadow": {"color": "#000000", "opacity": 0.5, "blur": 0.012, "dx": 0.01, "dy": 0.01},
              "stroke": {"color": "#ffffff", "w": 0.004, "opacity": 1},
              "glow": {"color": "#ffd479", "opacity": 0.8, "blur": 0.02, "size": 0.006}}
        lst = [base_layer(), rect("a", w=0.5, h=0.3, fx=fx), {"id": "t", "type": "text", "text": "تست افکت", "size": 0.08, "fx": fx}]
        out, c = compose(base, lst)
        self.assertEqual(out.size, base.size)
        self.assertLess(time.time() - t, 20)
        # لایهٔ خیلی بزرگ (چندبرابرِ بوم) ⇒ افکت نادیده، نه خطا
        huge = {"id": "h", "type": "image", "src": {"kind": "logo"}, "w": 4.0, "cx": 0.5, "cy": 0.5,
                "fx": {"shadow": {"color": "#000000", "opacity": 0.5, "blur": 0.2, "dx": 0.1, "dy": 0.1}}}
        d = Path(tempfile.mkdtemp(prefix="nmphoto-fx-"))
        self.addCleanup(shutil.rmtree, d, True)
        Image.new("RGB", (400, 400), (10, 200, 10)).save(d / "x.png")
        out, c = compose(solid(1000, 800, (0, 0, 0)), [base_layer(), huge], logo_path=lambda p: d / "x.png")
        self.assertTrue(any("افکت" in n for n in c["notes"]))
        self.assertEqual(px(out, 500, 400), (10, 200, 10))

    def test_dilate_disc_is_a_disc(self):
        a = np.zeros((101, 101), np.uint8)
        a[50, 50] = 255
        for r, tol in ((3, 0.2), (8, 0.14), (20, 0.1)):
            d = fxmod.dilate_disc(a, r)
            yy, xx = np.mgrid[0:101, 0:101]
            want = (xx - 50) ** 2 + (yy - 50) ** 2 <= r * r
            sym = (d > 0)
            self.assertGreater((sym & want).sum() / want.sum(), 0.97, r)
            self.assertLess((sym & ~want).sum() / want.sum(), tol, r)
        # r گرد می‌شود: ۰٫۵ ⇒ ۱ ؛ ۰٫۴ ⇒ ۰
        self.assertEqual(int((fxmod.dilate_disc(a, 0.5) > 0).sum()), int((fxmod.dilate_disc(a, 1) > 0).sum()))
        self.assertIs(fxmod.dilate_disc(a, 0.4), a)


# ═════════════════════════════ گروه و بُرش

class GroupTests(SimpleTestCase):
    def test_group_schema_and_validation(self):
        out = layers.normalize_layers([base_layer(), group("g", name="x" * 99, collapsed=1, blend="multiply", opacity=3, junk=1),
                                       rect("c", parent="g", clip=True)])
        g, c = out[1], out[2]
        self.assertEqual((g["type"], g["collapsed"], g["blend"], g["opacity"], g["parent"], g["clip"]), ("group", True, "multiply", 1.0, None, False))
        self.assertEqual(len(g["name"]), 60)
        self.assertNotIn("junk", g)
        self.assertEqual((c["parent"], c["clip"]), ("g", True))
        self.assertNotIn("parent", out[0], "عکسِ پایه والد/clip ندارد")
        self.assertNotIn("clip", out[0])
        self.assertEqual(layers.normalize_layers(out), out)
        D = catalog.CatalogError
        with self.assertRaisesRegex(D, "پیدا نشد"):
            layers.normalize_layers([base_layer(), rect("c", parent="nope")])
        with self.assertRaisesRegex(D, "گروه"):
            layers.normalize_layers([base_layer(), rect("a"), rect("c", parent="a")])         # والد گروه نیست
        with self.assertRaisesRegex(D, "حلقه"):
            layers.normalize_layers([base_layer(), group("a", parent="b"), group("b", parent="a")])
        with self.assertRaisesRegex(D, "حلقه"):
            layers.normalize_layers([base_layer(), group("a", parent="a")])
        with self.assertRaisesRegex(D, "حلقه"):
            layers.normalize_layers([base_layer(), group("a", parent="c"), group("b", parent="a"), group("c", parent="b")])
        with self.assertRaisesRegex(D, "داخلِ گروه"):
            layers.normalize_layers([group("g"), base_layer(parent="g")])
        with self.assertRaises(D):
            layers.normalize_layers([base_layer(), rect("c", parent="BAD ID")])

    def test_depth_limit_four(self):
        chain = [base_layer(), group("g1")] + [group(f"g{i}", parent=f"g{i - 1}") for i in range(2, 5)]
        ok = layers.normalize_layers(chain + [rect("leaf", parent="g4")])
        self.assertEqual(len(ok), 6)
        with self.assertRaisesRegex(catalog.CatalogError, "تودرتو"):
            layers.normalize_layers(chain + [group("g5", parent="g4")])

    def test_limits_80_layers(self):
        lst = [base_layer()] + [rect(f"s{i}") for i in range(layers.MAX_LAYERS - 1)]
        self.assertEqual(len(layers.normalize_layers(lst)), 80)
        with self.assertRaisesRegex(catalog.CatalogError, "80|۸۰|لایه"):
            layers.normalize_layers(lst + [rect("extra")])
        self.assertEqual(layers.MAX_LAYERS, 80)

    def test_mask_ids_see_nested_layers_and_children(self):
        flat = [base_layer(), group("g", mask={"type": "paint", "id": "mg"}),
                rect("c", parent="g", mask={"type": "paint", "id": "mc"})]
        self.assertEqual(layers.mask_ids(layers.normalize_layers(flat)), {"mg", "mc"})
        nested = [{"mask": {"type": "paint", "id": "a"}, "children": [{"mask": {"type": "paint", "id": "b"},
                                                                        "children": [{"mask": {"type": "paint", "id": "c"}}]}]}]
        self.assertEqual(layers.mask_ids(nested), {"a", "b", "c"})

    def test_preset_layers_keep_groups_and_drop_photo_bound_layers(self):
        lst = [base_layer(), {"id": "rt", "type": "retouch"}, {"id": "re", "type": "redeye", "eyes": [{"x": .5, "y": .5, "r": .01}]},
               group("g", mask={"type": "paint", "id": "m1"}), rect("a", parent="g"), rect("b", parent="g", clip=True),
               {"id": "t", "type": "text", "text": "hi", "fx": {"shadow": {"opacity": 0.4}}}]
        pre = layers.preset_layers(lst)
        self.assertEqual([l["id"] for l in pre], ["g", "a", "b", "t"])
        self.assertEqual([l["parent"] for l in pre], [None, "g", "g", None])
        self.assertTrue(pre[2]["clip"])
        self.assertIsNone(pre[0]["mask"], "ماسکِ رنگ‌آمیزی حذف می‌شود")
        self.assertEqual(pre[3]["fx"]["shadow"]["opacity"], 0.4)

    def test_group_isolation_blend_vs_flat(self):
        base = solid(40, 40, (200, 100, 50))
        mult = rect("m", w=2, h=2, color="#808080", blend="multiply")
        flat, _ = compose(base, [base_layer(), mult])
        self.assertAlmostEqual(px(flat, 20, 20)[0], 200 * 128 / 255, delta=1.5)
        # گروهِ ایزوله با حالتِ normal: ضرب فقط با محتوای خودِ گروه (که چیزی ندارد) ⇒ خودِ خاکستری
        iso, _ = compose(base, [base_layer(), group("g"), dict(mult, parent="g")])
        self.assertEqual(px(iso, 20, 20), (128, 128, 128))
        # گروهِ multiply با فرزندِ normal ⇒ همان نتیجهٔ ضربِ مسطح
        as_group, _ = compose(base, [base_layer(), group("g", blend="multiply"), dict(mult, parent="g", blend="normal")])
        for a, b in zip(px(as_group, 20, 20), px(flat, 20, 20)):
            self.assertAlmostEqual(a, b, delta=1)
        # ترتیبِ فهرستیِ گروه و فرزند مهم نیست
        rev, _ = compose(base, [base_layer(), dict(mult, parent="g"), group("g")])
        self.assertTrue(ops.same_image(rev, iso))

    def test_group_opacity_applies_once_to_the_flattened_group(self):
        base = solid(40, 40, (0, 0, 0))
        kids = [rect("r", w=2, h=2, color="#ff0000", parent="g"), rect("b", w=2, h=2, color="#0000ff", parent="g")]
        out, _ = compose(base, [base_layer(), group("g", opacity=0.5)] + kids)
        r, g, b = px(out, 20, 20)
        self.assertAlmostEqual(b, 127.5, delta=1.5)
        self.assertEqual(r, 0, "دو فرزندِ ۵۰٪ جدا نیستند؛ گروه یک بار ۵۰٪ می‌شود")
        flat = [base_layer(), dict(kids[0], parent=None, opacity=0.5), dict(kids[1], parent=None, opacity=0.5)]
        self.assertGreater(px(compose(base, flat)[0], 20, 20)[0], 30, "مسطح: قرمز هم دیده می‌شود")

    def test_hidden_empty_and_nested_groups(self):
        base = photo(80, 60)
        hid, _ = compose(base, [base_layer(), group("g", visible=False), rect("a", parent="g")])
        self.assertTrue(ops.same_image(hid, base), "گروهِ پنهان فرزندانش را پنهان می‌کند")
        child_hidden, _ = compose(base, [base_layer(), group("g"), rect("a", parent="g", visible=False)])
        self.assertTrue(ops.same_image(child_hidden, base))
        empty, _ = compose(base, [base_layer(), group("g")])
        self.assertTrue(ops.same_image(empty, base))
        only_adj, _ = compose(base, [base_layer(), group("g"), {"id": "a", "type": "adjust", "adjust": {"exposure": 1}, "parent": "g"}])
        self.assertTrue(ops.same_image(only_adj, base), "گروهِ فقط-تنظیم چیزی ندارد که تنظیم شود")
        # تودرتو: ۵۰٪ × ۵۰٪ = ۲۵٪ سفید روی سیاه
        black = solid(30, 30, (0, 0, 0))
        nest, _ = compose(black, [base_layer(), group("a", opacity=0.5), group("b", parent="a", opacity=0.5),
                                  rect("w", w=2, h=2, color="#ffffff", parent="b")])
        self.assertAlmostEqual(px(nest, 15, 15)[0], 63.75, delta=1.5)
        # بیرونِ گروه هم بالای گروه
        top, _ = compose(black, [base_layer(), group("a"), rect("w", w=2, h=2, color="#ffffff", parent="a"),
                                 rect("g", w=2, h=2, color="#00ff00", opacity=0.5)])
        self.assertAlmostEqual(px(top, 15, 15)[1], 255, delta=1)
        self.assertAlmostEqual(px(top, 15, 15)[0], 127.5, delta=1.5)

    def test_group_mask(self):
        black = solid(100, 100, (0, 0, 0))
        lst = [base_layer(), group("g", mask={"type": "linear", "p0": [0.2, 0.5], "p1": [0.8, 0.5]}),
               rect("w", w=2, h=2, color="#ffffff", parent="g")]
        out, _ = compose(black, lst)
        self.assertEqual(px(out, 3, 50)[0], 255)
        self.assertEqual(px(out, 96, 50)[0], 0)
        self.assertAlmostEqual(px(out, 50, 50)[0], 127.5, delta=4)
        # ماسکِ فرزند فقط خودش را می‌گیرد
        two = [base_layer(), group("g"), rect("w", w=2, h=2, color="#ffffff", parent="g",
                                              mask={"type": "linear", "p0": [0.2, 0.5], "p1": [0.8, 0.5]}),
               rect("g2", w=2, h=2, color="#00ff00", parent="g", opacity=0.0)]
        o2, _ = compose(black, two)
        self.assertEqual(px(o2, 96, 50), (0, 0, 0))

    def test_adjust_inside_group_acts_on_group_content_only(self):
        base = solid(100, 100, (100, 100, 100))
        right = rect("c", cx=0.75, cy=0.5, w=0.5, h=2, color="#646464", parent="g")       # همرنگِ پایه، نیمهٔ راست
        adj = {"id": "a", "type": "adjust", "adjust": {"exposure": 1.0}, "parent": "g"}
        out, _ = compose(base, [base_layer(), group("g"), right, adj])
        self.assertEqual(px(out, 20, 50)[0], 100, "پایه (بیرونِ محتوای گروه) روشن نشد")
        self.assertGreater(px(out, 80, 50)[0], 125, "محتوای گروه روشن شد")
        flat, _ = compose(base, [base_layer(), dict(right, parent=None), dict(adj, parent=None)])
        self.assertGreater(px(flat, 20, 50)[0], 125, "مسطح: پایه هم روشن می‌شود")
        # تنظیمِ سراسری بعد از گروه پایه را هم می‌گیرد
        after, _ = compose(base, [base_layer(), group("g"), right, dict(adj, parent=None)])
        self.assertGreater(px(after, 20, 50)[0], 125)
        # تنظیمِ شعاعیِ داخلِ گروه با ماسک
        masked = dict(adj, mask={"type": "radial", "c": [0.75, 0.5], "rx": 0.1, "ry": 0.1, "feather": 0})
        o3, _ = compose(base, [base_layer(), group("g"), right, masked])
        self.assertGreater(px(o3, 75, 50)[0], 125)
        self.assertAlmostEqual(px(o3, 95, 90)[0], 100, delta=1)

    def test_redeye_and_retouch_inside_group(self):
        a = np.full((60, 100, 3), 80, np.uint8)
        a[27:33, 47:53] = (230, 20, 20)
        img = Image.fromarray(a, "RGB")
        red_in_group = {"id": "pic", "type": "shape", "shape": "rect", "cx": 0.5, "cy": 0.5, "w": 0.06, "h": 0.06,
                        "fill": {"type": "solid", "color": "#e61414", "opacity": 1}, "parent": "g"}
        re_ = {"id": "re", "type": "redeye", "eyes": [{"x": 0.5, "y": 0.5, "r": 0.04}], "parent": "g"}
        out, _ = compose(img, [base_layer(), group("g"), red_in_group, re_])
        self.assertLess(px(out, 50, 30)[0], 80, "قرمزی داخلِ انباشتگرِ گروه اصلاح شد")

    def test_group_tile_bbox_and_memory_shape(self):
        # گروهی با یک نقطهٔ کوچک در گوشه + ماسکِ شعاعی؛ باید همان نتیجهٔ مسطح باشد
        base = photo(200, 150)
        dot = rect("d", cx=0.9, cy=0.9, w=0.05, h=0.05, color="#00ff00")
        flat, _ = compose(base, [base_layer(), dot])
        grouped, _ = compose(base, [base_layer(), group("g"), dict(dot, parent="g")])
        self.assertTrue(ops.same_image(flat, grouped), "یک فرزندِ normal در گروهِ normal با مسطح یکی است")

    def test_group_perf(self):
        t = time.time()
        base = photo(1800, 1200)
        lst = [base_layer(), group("g1", opacity=0.8), group("g2", parent="g1", blend="overlay"),
               rect("a", w=0.5, h=0.3, parent="g2"), {"id": "t", "type": "text", "text": "تست سرعت", "size": 0.08, "parent": "g1"},
               {"id": "adj", "type": "adjust", "adjust": {"exposure": 0.3}, "parent": "g1"}]
        out, _ = compose(base, lst)
        self.assertEqual(out.size, base.size)
        self.assertLess(time.time() - t, 20)


class ClipTests(SimpleTestCase):
    def base(self):
        return solid(100, 100, (0, 0, 0))

    def target(self, **kw):
        return rect("t", cx=0.5, cy=0.5, w=0.5, h=0.5, color="#0000ff", **kw)          # x,y: ۲۵…۷۵

    def clipped(self, **kw):
        return rect("c", cx=0.5, cy=0.5, w=2, h=2, color="#ff0000", clip=True, **kw)

    def test_clipped_to_target_alpha_not_its_opacity(self):
        out, _ = compose(self.base(), [base_layer(), self.target(opacity=0.3), self.clipped()])
        self.assertEqual(px(out, 50, 50), (255, 0, 0), "پیدایی هدف در بُرش حساب نمی‌شود")
        self.assertEqual(px(out, 10, 10), (0, 0, 0))
        self.assertEqual(px(out, 80, 50), (0, 0, 0))
        free, _ = compose(self.base(), [base_layer(), self.target(), dict(self.clipped(), clip=False)])
        self.assertEqual(px(free, 10, 10), (255, 0, 0))
        # لبهٔ نرم: آلفای هدف (دایره) ⇒ لبه‌های میانی
        ell = {"id": "t", "type": "shape", "shape": "ellipse", "cx": .5, "cy": .5, "w": .6, "h": .6,
               "fill": {"type": "solid", "color": "#0000ff", "opacity": 0.5}}
        out, _ = compose(self.base(), [base_layer(), ell, self.clipped()])
        self.assertAlmostEqual(px(out, 50, 50)[0], 127.5, delta=1.5, msg="آلفای تایلِ هدف = پر با opacity ِ fill")

    def test_target_mask_applies(self):
        mask = {"type": "linear", "p0": [0.25, 0.5], "p1": [0.75, 0.5]}
        out, _ = compose(self.base(), [base_layer(), self.target(mask=mask), self.clipped()])
        self.assertGreater(px(out, 30, 50)[0], 240)
        self.assertLess(px(out, 70, 50)[0], 15)
        want = 255 * (1 - (lambda t: t * t * (3 - 2 * t))((40 + 0.5 - 25) / 50))
        self.assertAlmostEqual(px(out, 40, 50)[0], want, delta=3)
        # ماسکِ خودِ لایهٔ بریده‌شده هم مثلِ همیشه
        m2, _ = compose(self.base(), [base_layer(), self.target(), self.clipped(mask={"type": "linear", "p0": [0.5, 0.2], "p1": [0.5, 0.8], "invert": True})])
        self.assertLess(px(m2, 50, 30)[0], 40)

    def test_ignored_without_target(self):
        out, _ = compose(self.base(), [base_layer(), self.clipped()])
        self.assertEqual(px(out, 10, 10), (255, 0, 0), "لایهٔ اولِ بالای عکس هدف ندارد (عکس هدفِ بُرش نیست)")
        out, _ = compose(self.base(), [base_layer(), {"id": "a", "type": "adjust", "adjust": {"exposure": 1}}, self.clipped()])
        self.assertEqual(px(out, 10, 10), (255, 0, 0), "تنظیم هدف نیست")
        out, _ = compose(self.base(), [self.clipped(), base_layer()])
        self.assertEqual(px(out, 10, 10), (0, 0, 0), "پایین‌ترین لایه، زیرِ عکسِ پایه")
        # هدف باید هم‌خواهر باشد: لایهٔ بالاسریِ گروه به لایهٔ بیرونِ گروه نمی‌چسبد
        out, _ = compose(self.base(), [base_layer(), self.target(), group("g"), dict(self.clipped(), parent="g")])
        self.assertEqual(px(out, 10, 10), (255, 0, 0))

    def test_clip_chain(self):
        t = rect("t", cx=0.5, cy=0.5, w=0.6, h=0.6, color="#0000ff")          # ۲۰…۸۰
        b = rect("b", cx=0.7, cy=0.5, w=0.6, h=0.6, color="#00ff00", clip=True)    # ۴۰…۱۰۰ بریده به t
        c = rect("c", cx=0.5, cy=0.5, w=2, h=2, color="#ff0000", clip=True)       # به b (و پس t) بریده می‌شود
        out, _ = compose(self.base(), [base_layer(), t, b, c])
        self.assertEqual(px(out, 50, 50), (255, 0, 0), "t∩b")
        self.assertEqual(px(out, 30, 50), (0, 0, 255), "فقط t ؛ b و c آنجا نیستند")
        self.assertEqual(px(out, 90, 50), (0, 0, 0), "b خارج از t بریده می‌شود و c هم")
        self.assertEqual(px(out, 50, 10), (0, 0, 0))
        # هدفِ پنهان یا بی‌پیکسل ⇒ بریده‌شده دیده نمی‌شود
        hid, _ = compose(self.base(), [base_layer(), dict(t, visible=False), b, c])
        self.assertEqual(px(hid, 50, 50), (0, 0, 0))
        miss, _ = compose(self.base(), [base_layer(), {"id": "txt", "type": "text", "text": "  "}, self.clipped()])
        self.assertEqual(px(miss, 50, 50), (0, 0, 0), "هدفِ بی‌پیکسل")

    def test_clipped_group_and_group_target(self):
        lst = [base_layer(), self.target(), group("g", clip=True), rect("w", w=2, h=2, color="#ff0000", parent="g")]
        out, _ = compose(self.base(), lst)
        self.assertEqual(px(out, 50, 50), (255, 0, 0))
        self.assertEqual(px(out, 10, 10), (0, 0, 0), "گروه هم به لایهٔ پایین‌تر بریده می‌شود")
        # گروه به‌عنوان هدف: شکلِ گروه = مجموعِ آلفای فرزندان × ماسکِ گروه
        lst = [base_layer(), group("g", mask={"type": "linear", "p0": [0.5, 0.5], "p1": [0.5, 0.5]}),
               rect("s", cx=0.3, cy=0.5, w=0.2, h=0.5, color="#0000ff", parent="g"),
               self.clipped()]
        out, _ = compose(self.base(), lst)
        self.assertEqual(px(out, 30, 50), (255, 0, 0))
        self.assertEqual(px(out, 70, 50), (0, 0, 0))

    def test_clip_with_fx_target_uses_baked_alpha(self):
        t = rect("t", cx=0.5, cy=0.5, w=0.3, h=0.3, color="#0000ff",
                 fx={"stroke": {"color": "#ffffff", "w": 0.05, "opacity": 1}})            # ۵ px
        out, _ = compose(self.base(), [base_layer(), t, self.clipped()])
        self.assertEqual(px(out, 50, 50), (255, 0, 0))
        self.assertEqual(px(out, 33, 50), (255, 0, 0), "خطِ دورِ پخته جزءِ آلفای هدف است")
        self.assertEqual(px(out, 20, 50), (0, 0, 0))


# ═════════════════════════════ مسیرِ قلم

class PathTests(SimpleTestCase):
    def test_square_mask_exact(self):
        m = paths.rasterize_mask(square_path(), 100, 80)
        self.assertEqual(m.shape, (80, 100))
        self.assertEqual(m.dtype, np.float32)
        self.assertAlmostEqual(float(m.sum()), 50 * 40, places=3)
        self.assertEqual(float(m[40, 50]), 1.0)
        self.assertEqual(float(m[5, 5]), 0.0)
        self.assertEqual(float(m[20, 25]), 1.0, "گوشهٔ بالا-چپِ مربع (۲۵،۲۰) داخل است")
        self.assertEqual(float(m[19, 25]), 0.0)
        # لبهٔ غیرِ عددِ درست ⇒ پوششِ جزئی با ۲×۲ نمونه (ضرایبِ ۰٫۲۵)
        half = paths.rasterize_mask(square_path(0.0, 0.0, 0.505, 1.0), 100, 100)
        self.assertAlmostEqual(float(half[50, 50]), 0.5, delta=1e-6)

    def test_curve_area_close_to_analytic_and_handles(self):
        W = H = 300
        m = paths.rasterize_mask({"closed": True, "pts": circle_path(0.5, 0.5, 0.4, 0.4)["pts"]}, W, H)
        self.assertAlmostEqual(float(m.sum()) / (math.pi * 120 ** 2), 1.0, delta=0.005)
        # بیضی در جعبهٔ نامربع: x و y جدا مقیاس می‌شوند
        e = paths.rasterize_mask(circle_path(0.5, 0.5, 0.4, 0.2), 400, 200)
        self.assertAlmostEqual(float(e.sum()) / (math.pi * 160 * 40), 1.0, delta=0.006)
        # دسته‌ها: منحنیِ مکعبیِ P0=(0.1,0.5) ، ho=(0.3,−0.4) ، P3=(0.9,0.5) ، hi=(−0.3,−0.4) (بسته با خطِ راست)
        path = {"closed": True, "pts": [{"x": 0.1, "y": 0.5, "hi": None, "ho": [0.3, -0.4]},
                                        {"x": 0.9, "y": 0.5, "hi": [-0.3, -0.4], "ho": None}]}
        t = np.linspace(0, 1, 4001)
        P = np.array([[0.1, 0.5], [0.4, 0.1], [0.6, 0.1], [0.9, 0.5]]) * 400
        B = ((1 - t) ** 3)[:, None] * P[0] + (3 * (1 - t) ** 2 * t)[:, None] * P[1] + (3 * (1 - t) * t ** 2)[:, None] * P[2] + (t ** 3)[:, None] * P[3]
        want = poly_area(B.tolist())
        got = float(paths.rasterize_mask(path, 400, 400).sum())
        self.assertAlmostEqual(got / want, 1.0, delta=0.01)
        m = paths.rasterize_mask(path, 400, 400)
        self.assertEqual(float(m[int(0.35 * 400), 200]), 1.0, "منحنی بالای وتر است (ho رو به بالا)")
        self.assertEqual(float(m[int(0.65 * 400), 200]), 0.0)
        # بدونِ دسته: خطِ راست ⇒ مساحتِ صفر
        flat = {"closed": True, "pts": [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}]}
        self.assertEqual(float(paths.rasterize_mask(flat, 100, 100).sum()), 0.0)

    def test_flatten_segments_and_closed_open(self):
        sq = square_path()
        closed = paths.flatten(sq, 100, 100)
        self.assertEqual(closed, [(25.0, 25.0), (75.0, 25.0), (75.0, 75.0), (25.0, 75.0)])
        op = paths.flatten(dict(sq, closed=False), 100, 100)
        self.assertEqual(op, closed)
        # بسته: پارهٔ آخر→اول هم منحنی است (ho_last و hi_first)؛ نقطهٔ اول تکرار نمی‌شود
        c = paths.flatten(circle_path(), 100, 100)
        self.assertGreater(len(c), 60)
        self.assertNotEqual(c[0], c[-1])
        o = paths.flatten(dict(circle_path(), closed=False), 100, 100)
        self.assertLess(len(o), len(c), "باز: پارهٔ بستن نیست")
        self.assertEqual(paths.flatten({"closed": True, "pts": []}, 10, 10), [])
        self.assertEqual(paths.flatten({"closed": True, "pts": [{"x": 0.5, "y": 0.5}]}, 10, 10), [(5.0, 5.0)])
        # پر کردنِ بازِ مثلث همان بسته است؛ خطِ دورِ باز پارهٔ بستن ندارد
        tri = {"closed": False, "pts": [{"x": 0.2, "y": 0.8}, {"x": 0.5, "y": 0.2}, {"x": 0.8, "y": 0.8}]}
        a = paths.rasterize_mask(tri, 100, 100)
        b = paths.rasterize_mask(dict(tri, closed=True), 100, 100)
        self.assertTrue(np.array_equal(a, b))
        p_open = paths.flatten(tri, 100, 100)
        s_open = paths.stroke_coverage(p_open, False, 6, 100, 100)
        s_closed = paths.stroke_coverage(p_open, True, 6, 100, 100)
        self.assertEqual(float(s_open[80, 50]), 0.0, "پارهٔ پایین (بستن) در حالتِ باز نیست")
        self.assertEqual(float(s_closed[80, 50]), 1.0)

    def test_nonzero_winding_and_orientation(self):
        star = {"closed": True, "pts": [{"x": 0.5 + 0.45 * math.cos(math.radians(-90 + 144 * i)),
                                         "y": 0.5 + 0.45 * math.sin(math.radians(-90 + 144 * i))} for i in range(5)]}
        m = paths.rasterize_mask(star, 200, 200)
        self.assertEqual(float(m[100, 100]), 1.0, "مرکزِ ستاره (پیچش ۲) با nonzero پر است")
        rev = {"closed": True, "pts": star["pts"][::-1]}
        self.assertTrue(np.array_equal(m, paths.rasterize_mask(rev, 200, 200)), "جهتِ مسیر اثری ندارد")
        eo_hole = paths.fill_polygons([np.array([(0, 0), (100, 0), (100, 100), (0, 100)]),
                                       np.array([(25, 25), (75, 25), (75, 75), (25, 75)])], 100, 100)
        self.assertEqual(float(eo_hole[50, 50]), 1.0, "دو چندضلعیِ هم‌جهت ⇒ اجتماع")
        hole = paths.fill_polygons([np.array([(0, 0), (100, 0), (100, 100), (0, 100)]),
                                    np.array([(25, 25), (25, 75), (75, 75), (75, 25)])], 100, 100)
        self.assertEqual(float(hole[50, 50]), 0.0, "جهتِ مخالف ⇒ پیچشِ صفر (سوراخ)")
        self.assertEqual(float(hole[10, 10]), 1.0)
        # فیگورِ ۸ (دو لپ با جهتِ مخالف) هر دو پر می‌شود
        eight = {"closed": True, "pts": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.9, "y": 0.1}, {"x": 0.1, "y": 0.9}]}
        m8 = paths.rasterize_mask(eight, 100, 100)
        self.assertEqual(float(m8[50, 15]), 1.0)
        self.assertEqual(float(m8[50, 85]), 1.0)

    def test_feather(self):
        sharp = paths.rasterize_mask(square_path(0.2, 0.2, 0.8, 0.8), 100, 100)
        soft = paths.rasterize_mask(square_path(0.2, 0.2, 0.8, 0.8), 100, 100, feather_px=4)
        self.assertEqual(float(sharp[50, 20]), 1.0)
        self.assertTrue(0.3 < float(soft[50, 20]) < 0.7, "روی لبه نیمه")
        self.assertGreater(float(soft[50, 30]), 0.99)
        self.assertLess(float(soft[50, 8]), 0.05)
        self.assertGreater(float(soft[50, 15]), float(soft[50, 8]))
        self.assertAlmostEqual(float(soft.sum()), float(sharp.sum()), delta=40, msg="محوی جرم را حفظ می‌کند")
        self.assertTrue(float(soft.max()) <= 1.0 and float(soft.min()) >= 0.0)

    def test_stroke_polygons_area(self):
        poly = paths.flatten(square_path(), 100, 80)
        for w in (2.0, 5.0, 8.0):
            s = paths.stroke_coverage(poly, True, w, 100, 80)
            # مستطیلِ ۵۰×۴۰ : مساحتِ خطِ دور = ۲Ph + (π−4)h² ، h=w/2
            h = w / 2
            self.assertAlmostEqual(float(s.sum()), 2 * 180 * h + (math.pi - 4) * h * h, delta=0.03 * 360 * h, msg=w)
        line = paths.stroke_coverage([(10, 50), (90, 50)], False, 10, 100, 100)
        self.assertAlmostEqual(float(line.sum()), 80 * 10 + math.pi * 25, delta=4)
        self.assertGreater(float(line[50, 8]), 0.9, "سرِ گرد: ۲ پیکسل پیش از شروعِ خط، داخلِ نیم‌دایره")
        self.assertEqual(float(line[50, 3]), 0.0, "بیرونِ نیم‌دایره (۷ پیکسل پیش از شروع)")

    def test_normalize_path_and_limits(self):
        pts = [{"x": 0.1, "y": 0.2, "hi": [0, 0], "ho": [0.3, -9]}, {"x": 9, "y": "bad"}, "junk"]
        s = layers.normalize_layers([base_layer(), {"id": "p", "type": "shape", "shape": "path", "w": 0.3, "h": 0, "path": {"pts": pts}}])[1]
        self.assertEqual(s["shape"], "path")
        self.assertEqual(s["path"]["closed"], True)
        self.assertEqual(s["path"]["pts"][0], {"x": 0.1, "y": 0.2, "hi": None, "ho": [0.3, -3.0]})
        self.assertEqual(s["path"]["pts"][1], {"x": 3.0, "y": 0.5, "hi": None, "ho": None})
        self.assertEqual(len(s["path"]["pts"]), 2)
        self.assertGreater(s["h"], 0, "ارتفاعِ مسیر صفر نمی‌شود")
        rect_ = layers.normalize_layers([base_layer(), rect("r", path={"pts": pts})])[1]
        self.assertNotIn("path", rect_)
        none = layers.normalize_layers([base_layer(), {"id": "p", "type": "shape", "shape": "path"}])[1]
        self.assertEqual(none["path"], {"closed": True, "pts": []})
        ok = {"closed": False, "pts": [{"x": i / 300, "y": 0.5} for i in range(200)]}
        self.assertEqual(len(layers.normalize_layers([base_layer(), {"id": "p", "type": "shape", "shape": "path", "path": ok}])[1]["path"]["pts"]), 200)
        ok["pts"].append({"x": 0.9, "y": 0.9})
        with self.assertRaisesRegex(catalog.CatalogError, "200"):
            layers.normalize_layers([base_layer(), {"id": "p", "type": "shape", "shape": "path", "path": ok}])
        again = layers.normalize_layers([base_layer(), {"id": "p", "type": "shape", "shape": "path", "path": circle_path()}])
        self.assertEqual(layers.normalize_layers(again), again)

    def path_layer(self, path, **kw):
        return {"id": "p", "type": "shape", "shape": "path", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.25, "path": path,
                "fill": {"type": "solid", "color": "#ff0000", "opacity": 1}, "stroke": None} | kw

    def test_path_shape_layer_placement_scale_and_rotation(self):
        black = solid(200, 200, (0, 0, 0))
        # جعبهٔ ۱۰۰×۵۰ px در مرکزِ (۱۰۰، ۱۰۰): x ۵۰…۱۵۰ ، y ۷۵…۱۲۵
        out, _ = compose(black, [base_layer(), self.path_layer(square_path(0, 0, 1, 1))])
        self.assertEqual(px(out, 60, 80), (255, 0, 0))
        self.assertEqual(px(out, 140, 120), (255, 0, 0))
        self.assertEqual(px(out, 40, 100), (0, 0, 0))
        self.assertEqual(px(out, 100, 70), (0, 0, 0))
        red = (arr(out)[..., 0] > 200)
        self.assertAlmostEqual(float(red.sum()), 100 * 50, delta=120)
        # جابه‌جایی و مقیاس فقط با cx, cy, w, h
        out, _ = compose(black, [base_layer(), self.path_layer(square_path(0, 0, 1, 1), cx=0.25, cy=0.25, w=0.2, h=0.2)])
        self.assertEqual(px(out, 50, 50), (255, 0, 0))
        self.assertEqual(px(out, 50 + 25, 50), (0, 0, 0))
        # مثلثِ رو به بالا ⇒ چرخش ۱۸۰ ⇒ رو به پایین
        tri = {"closed": True, "pts": [{"x": 0, "y": 1}, {"x": 0.5, "y": 0}, {"x": 1, "y": 1}]}
        up, _ = compose(black, [base_layer(), self.path_layer(tri, w=0.5, h=0.5)])
        self.assertEqual(px(up, 100, 60), (255, 0, 0), "نزدیکِ رأس بالا")
        self.assertEqual(px(up, 55, 60), (0, 0, 0), "گوشهٔ بالا-چپِ جعبه بیرونِ مثلث")
        self.assertEqual(px(up, 60, 140), (255, 0, 0), "پایه")
        down, _ = compose(black, [base_layer(), self.path_layer(tri, w=0.5, h=0.5, rot=180)])
        self.assertEqual(px(down, 100, 140), (255, 0, 0))
        self.assertEqual(px(down, 55, 140), (0, 0, 0))
        self.assertEqual(px(down, 60, 60), (255, 0, 0))
        # ۹۰°: جعبهٔ ۱۰۰×۵۰ ⇒ ۵۰×۱۰۰
        rot, _ = compose(black, [base_layer(), self.path_layer(square_path(0, 0, 1, 1), rot=90)])
        self.assertEqual(px(rot, 100, 60), (255, 0, 0))
        self.assertEqual(px(rot, 60, 100), (0, 0, 0))
        # دایره (۴ بزیه) در جعبهٔ نامربع ⇒ بیضی با مساحتِ درست
        ell, _ = compose(black, [base_layer(), self.path_layer(circle_path(0.5, 0.5, 0.5, 0.5), w=0.6, h=0.3)])
        want = math.pi * 60 * 30
        self.assertAlmostEqual(float((arr(ell)[..., 0] > 127).sum()) / want, 1.0, delta=0.02)
        self.assertEqual(px(ell, 100, 100), (255, 0, 0))
        self.assertEqual(px(ell, 100 + 65, 100), (0, 0, 0))

    def test_path_shape_stroke_and_open_fill(self):
        black = solid(200, 200, (0, 0, 0))
        line = {"closed": False, "pts": [{"x": 0, "y": 0.5}, {"x": 1, "y": 0.5}]}
        out, _ = compose(black, [base_layer(), self.path_layer(line, fill=None, stroke={"color": "#0000ff", "w": 0.02})])
        self.assertEqual(px(out, 100, 98), (0, 0, 255), "خطِ ۴ px : ردیف‌های ۹۸ تا ۱۰۱")
        self.assertEqual(px(out, 100, 101), (0, 0, 255))
        self.assertEqual(px(out, 100, 97), (0, 0, 0))
        self.assertEqual(px(out, 100, 102), (0, 0, 0))
        self.assertEqual(px(out, 52, 100), (0, 0, 255), "نزدیکِ سرِ گرد")
        # پرِ مسیرِ باز = بسته ؛ خط دور
        tri = {"closed": False, "pts": [{"x": 0, "y": 1}, {"x": 0.5, "y": 0}, {"x": 1, "y": 1}]}
        out, _ = compose(black, [base_layer(), self.path_layer(tri, w=0.5, h=0.5, stroke={"color": "#00ff00", "w": 0.02})])
        self.assertEqual(px(out, 100, 130), (255, 0, 0), "داخلِ مثلث (پرِ ضمنی)")
        self.assertEqual(px(out, 100, 152), (0, 0, 0), "بیرونِ مثلث و بی خطِ دور (پارهٔ پایین در مسیرِ باز نیست)")
        self.assertEqual(px(out, 100, 149), (255, 0, 0), "پرِ ضمنی تا لبهٔ پایین می‌رسد ولی خطِ دور نیست")
        closed, _ = compose(black, [base_layer(), self.path_layer(dict(tri, closed=True), w=0.5, h=0.5, stroke={"color": "#00ff00", "w": 0.02})])
        self.assertEqual(px(closed, 100, 149), (0, 255, 0), "بسته: پارهٔ بستن هم خط دارد")
        self.assertEqual(px(out, 76, 100)[1], 255, "روی پارهٔ مایل خطِ دورِ سبز")
        # گرادیان و پرکننده‌ی نیمه‌شفاف
        half, _ = compose(solid(100, 100, (0, 0, 0)), [base_layer(), self.path_layer(square_path(0, 0, 1, 1), fill={"type": "solid", "color": "#ffffff", "opacity": 0.5})])
        self.assertAlmostEqual(px(half, 50, 50)[0], 127.5, delta=1.5)
        empty, _ = compose(black, [base_layer(), self.path_layer({"closed": True, "pts": []})])
        self.assertTrue(ops.same_image(empty, black))

    def test_path_with_fx_and_clip(self):
        black = solid(200, 200, (0, 0, 0))
        lay = self.path_layer(square_path(0, 0, 1, 1), fx={"shadow": {"color": "#ffffff", "opacity": 1, "blur": 0, "dx": 0.1, "dy": 0}})
        out, _ = compose(black, [base_layer(), lay])
        self.assertEqual(px(out, 160, 100), (255, 255, 255), "سایهٔ ۲۰ px راست")
        clipper = {"id": "c", "type": "shape", "shape": "rect", "cx": .5, "cy": .5, "w": 2, "h": 2, "clip": True,
                   "fill": {"type": "solid", "color": "#00ff00", "opacity": 1}}
        out, _ = compose(black, [base_layer(), self.path_layer(circle_path(0.5, 0.5, 0.5, 0.5), w=0.5, h=0.5), clipper])
        self.assertEqual(px(out, 100, 100), (0, 255, 0))
        self.assertEqual(px(out, 55, 55), (0, 0, 0), "بیرونِ دایره")


# ═════════════════════════════ سازگاری با رفتار قبلی

class BackCompatTests(SimpleTestCase):
    def old_compose(self, base, lst, c):
        """حلقهٔ تختِ ترکیبِ پیش از «pro 2» (کپی از نسخهٔ قبلی) — مرجعِ «بایت‌به‌بایت»."""
        lst = layers.normalize_layers(lst, base="one")
        W, H = base.size
        acc = np.zeros((H, W, 4), np.uint8)
        state = {"paint": {}, "images": {}, "project": 0}
        first = True
        for layer in lst:
            if not layer["visible"]:
                continue
            t = layer["type"]
            if t == "adjust":
                if not first:
                    layers._apply_adjust(acc, layer, c, state, W, H)
                continue
            if t == "retouch":
                if not first:
                    layers._apply_retouch(acc, layer, c, state, W, H)
                continue
            if t == "base":
                tile, x0, y0 = layers._tile_to_np(base), 0, 0
            elif t == "image":
                r = layers._render_image(layer, c, state, W, H)
                if r is None:
                    continue
                tile, x0, y0 = r
            elif t == "text":
                r = layers._render_text(layer, c, W, H)
                if r is None:
                    continue
                tile, x0, y0 = r
            else:
                r = layers._render_shape(layer, c, W, H)
                if r is None:
                    continue
                tile, x0, y0 = r
            layers._composite_tile(acc, tile, x0, y0, layer["blend"], layer["opacity"], layer.get("mask"), c, state, W, H, first)
            first = False
        return acc

    def test_projects_without_new_features_render_identically(self):
        base = photo(240, 180)
        d = Path(tempfile.mkdtemp(prefix="nmphoto-bc-"))
        self.addCleanup(shutil.rmtree, d, True)
        Image.new("RGBA", (30, 20), (255, 200, 0, 200)).save(d / "l.png")
        lst = [base_layer(),
               {"id": "adj", "type": "adjust", "adjust": {"exposure": 0.4, "contrast": 20}, "mask": {"type": "radial", "c": [.5, .5], "rx": .3, "ry": .3, "feather": .5}},
               rect("r1", cx=0.3, cy=0.4, w=0.3, h=0.2, color="#3366ff", blend="multiply", opacity=0.8, rot=17),
               {"id": "e", "type": "shape", "shape": "ellipse", "cx": .7, "cy": .6, "w": .3, "h": .2, "stroke": {"w": 0.01, "color": "#ffffff"},
                "fill": {"type": "gradient", "c0": "#ff0000", "c1": "#0000ff", "angle": 45}},
               {"id": "t", "type": "text", "text": "سلام Hello", "size": 0.09, "cx": .5, "cy": .75, "shadow": {"opacity": 0.6, "blur": 0.1}},
               {"id": "i", "type": "image", "src": {"kind": "logo"}, "cx": .85, "cy": .15, "w": 0.2, "rot": 10, "flip_h": True},
               {"id": "rt", "type": "retouch", "strokes": [{"mode": "heal", "pts": [[0.2, 0.2]], "r": 0.06, "dx": 0.3, "dy": 0.1}]}]
        c1 = ctx(logo_path=lambda p: d / "l.png")
        c2 = ctx(logo_path=lambda p: d / "l.png")
        want = self.old_compose(base, lst, c1)
        out = layers.compose(base, lst, c2)
        got = np.asarray(out.convert("RGBA"))
        self.assertTrue(np.array_equal(got, want), "ترکیبِ درختیِ تازه باید با حلقهٔ تختِ قبلی بایت‌به‌بایت یکی باشد")
        # فیلدهای تازه با مقدارِ پیش‌فرضِ صریح هم همان‌اند
        extra = [dict(l, **({"parent": None, "clip": False} if l["type"] != "base" else {})) for l in lst]
        for l in extra:
            if l["type"] in ("image", "text", "shape"):
                l["fx"] = None
        out2 = layers.compose(base, extra, ctx(logo_path=lambda p: d / "l.png"))
        self.assertTrue(ops.same_image(out, out2))


# ═════════════════════════════ مایع‌سازی

class LiquifyTests(SimpleTestCase):
    def stripes(self, w=120, h=80):
        a = np.zeros((h, w, 3), np.uint8)
        a[:, 50:60] = (255, 255, 255)
        a[30:36, :, 1] = 200
        return a

    def const_field(self, W, H, dx_px=0.0, dy_px=0.0, gw=8, gh=6):
        f = np.zeros((gh, gw, 2), np.float32)
        f[..., 0], f[..., 1] = dx_px / W, dy_px / H
        return liquify.decode(liquify.encode(f))

    def test_zero_field_is_identity(self):
        a = self.stripes()
        z = liquify.zeros(8, 6)
        self.assertTrue(liquify.is_identity(z))
        img = Image.fromarray(a, "RGB")
        self.assertIs(liquify.apply(img, z), img)
        self.assertIs(liquify.apply(a, z), a)
        # صفرِ کدگذاری‌شده → همان
        self.assertTrue(liquify.is_identity(liquify.decode(liquify.encode(z))))

    def test_constant_field_shifts_content(self):
        a = self.stripes()
        H, W = a.shape[:2]
        f = self.const_field(W, H, dx_px=10, dy_px=0)
        for quality in ("fast", "final"):
            out = liquify.apply(a, f, quality)
            # out(x) = src(x+10) ⇒ رگه از x=۵۰…۶۰ به ۴۰…۵۰ می‌رود
            self.assertTrue(np.array_equal(out[:, 5:W - 15], a[:, 15:W - 5]) or np.abs(out[:, 5:W - 15].astype(int) - a[:, 15:W - 5].astype(int)).max() <= 1, quality)
            self.assertEqual(tuple(out[10, 45]), (255, 255, 255))
            self.assertEqual(tuple(out[10, 55]), (0, 0, 0))
        fy = self.const_field(W, H, dx_px=0, dy_px=-6)
        out = liquify.apply(a, fy)
        # out(y) = src(y−6) ⇒ خطِ افقی (۳۰…۳۶) به ۳۶…۴۲ می‌رود
        self.assertEqual(int(out[39, 10, 1]), 200)
        self.assertEqual(int(out[32, 10, 1]), 0)
        # لبه تکرار می‌شود (clamp)
        edge = liquify.apply(a, self.const_field(W, H, dx_px=40))
        self.assertTrue((edge[:, W - 5:] == a[:, W - 1:W]).all())
        # PIL RGBA ⇒ همان حالت و آلفا حفظ
        rgba = Image.fromarray(np.dstack([a, np.full(a.shape[:2], 255, np.uint8)]), "RGBA")
        o = liquify.apply(rgba, f)
        self.assertEqual(o.mode, "RGBA")
        self.assertEqual(o.getpixel((45, 10)), (255, 255, 255, 255))

    def test_rgba_with_transparency_keeps_colours(self):
        a = np.zeros((40, 60, 4), np.uint8)
        a[:, 20:30] = (255, 0, 0, 255)
        out = liquify.apply(Image.fromarray(a, "RGBA"), self.const_field(60, 40, dx_px=5))
        px_ = out.getpixel((17, 10))
        self.assertEqual(px_, (255, 0, 0, 255))
        edge = out.getpixel((14, 10))
        self.assertEqual(edge[3], 0)

    def test_upsample_is_bilinear_cell_centre(self):
        rng = np.random.default_rng(1)
        f = rng.uniform(-0.05, 0.05, (7, 9, 2)).astype(np.float32)
        up = liquify.upsample(f, 123, 77)
        self.assertLess(float(np.abs(up - cv2.resize(f, (123, 77), interpolation=cv2.INTER_LINEAR)).max()), 1e-6)
        strips = np.concatenate([liquify.upsample_rows(f, 123, 77, 0, 30), liquify.upsample_rows(f, 123, 77, 30, 77)])
        self.assertTrue(np.array_equal(strips, up))

    def test_bloat_pucker_symmetry(self):
        f = liquify.zeros(64, 48)
        liquify.brush_bloat(f, 0.5, 0.5, 0.3, 0.2)
        p = liquify.zeros(64, 48)
        liquify.brush_pucker(p, 0.5, 0.5, 0.3, 0.2)
        self.assertTrue(np.allclose(p, -f))
        self.assertTrue(np.allclose(f[:, ::-1, 0], -f[:, :, 0], atol=1e-7), "dx پادمتقارن حولِ مرکز")
        self.assertTrue(np.allclose(f[::-1, :, 1], -f[:, :, 1], atol=1e-7), "dy پادمتقارن")
        self.assertGreater(float(f[24, 20, 0]), 0, "چپِ مرکز: از راست‌تر می‌خواند")
        self.assertEqual(float(np.abs(f[0, 0]).max()), 0.0, "بیرونِ شعاع صفر")
        # روی دیسک: bloat بزرگ‌ترش می‌کند و مرکز را ثابت می‌گذارد؛ pucker کوچک‌ترش
        W, H = 128, 96
        yy, xx = np.mgrid[0:H, 0:W]
        a = np.zeros((H, W, 3), np.uint8)
        a[(xx + 0.5 - 64) ** 2 + (yy + 0.5 - 48) ** 2 <= 15 ** 2] = 255
        ff = liquify.zeros(64, 48)
        liquify.brush_bloat(ff, 0.5, 0.5, 0.4, 0.5)
        big = liquify.apply(a, liquify.decode(liquify.encode(ff)))
        pp = liquify.zeros(64, 48)
        liquify.brush_pucker(pp, 0.5, 0.5, 0.4, 0.5)
        small = liquify.apply(a, liquify.decode(liquify.encode(pp)))
        area = lambda im: float((im[..., 0] > 127).sum())
        self.assertGreater(area(big), area(a) * 1.15)
        self.assertLess(area(small), area(a) * 0.85)
        for im in (big, small):
            ys, xs = np.nonzero(im[..., 0] > 127)
            self.assertAlmostEqual(float(xs.mean()) + 0.5, 64, delta=0.6)
            self.assertAlmostEqual(float(ys.mean()) + 0.5, 48, delta=0.6)
        # forward warp و reconstruct
        g = liquify.zeros(32, 24)
        liquify.brush_forward(g, 0.5, 0.5, 0.3, 0.1, 0.0)
        self.assertLess(float(g[12, 16, 0]), 0, "محتوا به راست می‌رود ⇒ آفستِ منفی")
        liquify.brush_reconstruct(g, 0.5, 0.5, 0.3, 1.0)
        self.assertLess(float(np.abs(g[12, 16]).max()), 0.005, "بازسازی آفست را تقریباً صفر می‌کند (۰٫۱ → < ۰٫۰۰۵)")

    def test_file_format_roundtrip_and_validation(self):
        rng = np.random.default_rng(3)
        f = rng.uniform(-0.25, 0.25, (5, 7, 2)).astype(np.float32)
        raw = liquify.encode(f)
        self.assertEqual(raw[:4], b"LQF1")
        self.assertEqual(int.from_bytes(raw[4:6], "little"), 7)
        self.assertEqual(int.from_bytes(raw[6:8], "little"), 5)
        self.assertEqual(len(raw), 8 + 5 * 7 * 4)
        self.assertLess(float(np.abs(liquify.decode(raw) - f).max()), 0.25 / 32767 + 1e-7)
        self.assertEqual(liquify.parse_header(raw), (7, 5))
        big = liquify.encode(np.full((2, 2, 2), 9.0, np.float32))
        self.assertAlmostEqual(float(liquify.decode(big).max()), 0.25, places=6, msg="کلمپ به ±۰٫۲۵")
        # مقدارِ بایتی ⇒ آفست: 32767 ⇒ ۰٫۲۵
        one = b"LQF1" + (2).to_bytes(2, "little") + (2).to_bytes(2, "little") + np.array([32767, -32767] * 4, "<i2").tobytes()
        d = liquify.decode(one)
        self.assertAlmostEqual(float(d[0, 0, 0]), 0.25, places=6)
        self.assertAlmostEqual(float(d[0, 0, 1]), -0.25, places=6)
        tmp = Path(tempfile.mkdtemp(prefix="nmphoto-lq-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        liquify.save_field(tmp / "sub" / "liquify.bin", f)
        self.assertTrue(np.allclose(liquify.load_field(tmp / "sub" / "liquify.bin"), f, atol=0.25 / 32767 + 1e-7))
        self.assertEqual(liquify.peek(tmp / "sub" / "liquify.bin"), (7, 5))
        self.assertFalse(list((tmp / "sub").glob("*.part")), "نوشتنِ اتمیک")
        E = liquify.LiquifyError
        for bad in (b"", b"LQF1", b"XXXX" + raw[4:], raw[:-1], raw + b"\0",
                    b"LQF1" + (1).to_bytes(2, "little") + (5).to_bytes(2, "little") + b"\0" * 20,
                    b"LQF1" + (0).to_bytes(2, "little") + (0).to_bytes(2, "little"),
                    b"LQF1" + (2000).to_bytes(2, "little") + (2).to_bytes(2, "little") + b"\0" * 16000,
                    b"\0" * (liquify.MAX_BYTES + 1)):
            with self.assertRaises(E):
                liquify.parse_header(bad)
            with self.assertRaises(E):
                liquify.decode(bad)

    def test_op_in_a_compose_less_pipeline(self):
        tmp = Path(tempfile.mkdtemp(prefix="nmphoto-lq-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        a = self.stripes()
        img = Image.fromarray(a, "RGB")
        H, W = a.shape[:2]
        liquify.save_field(tmp / "liquify.bin", np.stack([np.full((6, 8), 10.0 / W), np.zeros((6, 8))], axis=2))
        spec = catalog.tools()["liquify"]
        self.assertTrue(spec["hidden"])
        self.assertEqual(spec["where"], "server")
        self.assertEqual([p["key"] for p in spec["params"]], ["project"])
        norm = catalog.normalize_operations([{"tool": "liquify", "params": {"project": "7", "x": 1}}, {"tool": "export", "params": {"format": "png"}}])
        self.assertEqual(norm[0], {"tool": "liquify", "params": {"project": 7}})
        got = []
        c = ctx(liquify_path=lambda pid: got.append(pid) or tmp / "liquify.bin")
        out, _ = ops.run(img, norm, c)
        self.assertEqual(got, [7])
        self.assertEqual(tuple(np.asarray(out)[10, 45]), (255, 255, 255))
        self.assertEqual(tuple(np.asarray(out)[10, 55]), (0, 0, 0))
        # فایل نیست ⇒ یادداشت و عکسِ دست‌نخورده
        c = ctx(liquify_path=lambda pid: None)
        out, _ = ops.run(img, norm[:1], c)
        self.assertIs(out, img)
        self.assertTrue(any("مایع" in n for n in c["notes"]))
        c = ctx()
        out, _ = ops.run(img, norm[:1], c)
        self.assertIs(out, img)
        # فایلِ خراب ⇒ یادداشت
        (tmp / "bad.bin").write_bytes(b"nope")
        c = ctx(liquify_path=lambda pid: tmp / "bad.bin")
        out, _ = ops.run(img, norm[:1], c)
        self.assertIs(out, img)
        self.assertTrue(any("خراب" in n for n in c["notes"]))
        # پیش‌نمایش (scale<1) با خطی ؛ خروجیِ کامل با مکعبی — هر دو همان جابه‌جایی
        for scale in (0.5, 1.0):
            c = ctx(liquify_path=lambda pid: tmp / "liquify.bin", scale=scale)
            out, _ = ops.run(img, norm[:1], c)
            self.assertEqual(tuple(np.asarray(out)[10, 45]), (255, 255, 255), scale)


class LiquifyApiTests(ApiTestBase):
    def project(self):
        (aid,) = self.upload(photo(320, 240))
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": "p", "data": {}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return aid, r.json()["project"]

    def field_bytes(self, dx_px=0.0, W=320, H=240, gw=16, gh=12):
        f = np.zeros((gh, gw, 2), np.float32)
        f[..., 0] = dx_px / W
        return liquify.encode(f)

    def put(self, pid, data, **kw):
        return self.api.put(f"{self.base}/projects/{pid}/liquify/", data, content_type="application/octet-stream", **kw)

    def test_put_get_delete_and_validation(self):
        aid, p = self.project()
        pid = p["id"]
        self.assertIsNone(p.get("liquify"), "بی نقشه ⇒ liquify: null")
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/liquify/").status_code, 404)
        raw = self.field_bytes(12)
        r = self.put(pid, raw)
        self.assertEqual(r.status_code, 200, r.content)
        info = r.json()
        self.assertEqual(sorted(info), ["gh", "gw", "rev"])
        self.assertEqual((info["gw"], info["gh"]), (16, 12))
        self.assertAlmostEqual(info["rev"], time.time(), delta=60)
        got = self.api.get(f"{self.base}/projects/{pid}/liquify/")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, raw)
        self.assertEqual(got["Content-Type"], "application/octet-stream")
        d = PhotoProject.objects.get(pk=pid)
        self.assertTrue((self.media / d.dir_rel / "liquify.bin").is_file())
        full = self.api.get(f"{self.base}/projects/{pid}/").json()["project"]
        self.assertEqual(full["liquify"]["rev"], info["rev"])
        self.assertEqual((full["liquify"]["gw"], full["liquify"]["gh"]), (16, 12))
        self.assertIn("liquify.bin?v=", full["liquify"]["url"])
        # rev همیشه صعودی (حتی دو ذخیره در یک ثانیه)
        r2 = self.put(pid, self.field_bytes(-5))
        self.assertGreater(r2.json()["rev"], info["rev"])
        # خطاها
        self.assertEqual(self.put(pid, b"").status_code, 400)
        self.assertEqual(self.put(pid, b"XXXX" + raw[4:]).status_code, 400)
        self.assertEqual(self.put(pid, raw[:-4]).status_code, 400)
        self.assertEqual(self.put(pid, b"LQF1\x01\x00\x01\x00\x00\x00\x00\x00").status_code, 400)
        r = self.put(pid, b"\0" * (liquify.MAX_BYTES + 16))
        self.assertEqual(r.status_code, 413, r.content)
        self.assertEqual(r.json()["error"]["code"], "too_large")
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/liquify/").content, self.field_bytes(-5), "ردِ ذخیره، فایل را نمی‌شکند")
        self.assertEqual(self.put(999999, raw).status_code, 404)
        # حذف
        self.assertEqual(self.api.delete(f"{self.base}/projects/{pid}/liquify/").status_code, 204)
        self.assertEqual(self.api.delete(f"{self.base}/projects/{pid}/liquify/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/liquify/").status_code, 404)
        self.assertIsNone(self.api.get(f"{self.base}/projects/{pid}/").json()["project"]["liquify"])

    def test_gc_keeps_it_and_project_delete_removes_it(self):
        _aid, p = self.project()
        pid = p["id"]
        self.assertEqual(self.put(pid, self.field_bytes(3)).status_code, 200)
        pr = PhotoProject.objects.get(pk=pid)
        f = self.media / pr.dir_rel / "liquify.bin"
        old = time.time() - 7200
        os.utime(f, (old, old))
        (self.media / pr.dir_rel / "mask-zz.png").write_bytes(b"x")
        os.utime(self.media / pr.dir_rel / "mask-zz.png", (old, old))
        lay = [base_layer()]
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay, "liquify": {"rev": "12", "x": 1}}}, format="json").status_code, 200)
        self.assertTrue(f.is_file(), "gc فقط mask-*.png را پاک می‌کند")
        self.assertFalse((self.media / pr.dir_rel / "mask-zz.png").exists())
        self.assertEqual(services.gc_masks(PhotoProject.objects.get(pk=pid)), 0)
        saved = self.api.get(f"{self.base}/projects/{pid}/").json()["project"]
        self.assertEqual(saved["data"]["liquify"], {"rev": 12}, "نشانِ پروژه {rev:int}")
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/", {"data": {"liquify": "junk"}}, format="json").json()["project"]["data"]["liquify"], None)
        self.assertEqual(self.api.delete(f"{self.base}/projects/{pid}/").status_code, 204)
        self.assertFalse(f.exists())

    def test_permissions_other_store(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from apps.stores.models import Store

        _aid, p = self.project()
        self.assertEqual(self.put(p["id"], self.field_bytes(3)).status_code, 200)
        stranger = get_user_model().objects.create_user("stranger2", password="x")
        Store.objects.create(owner=stranger, name="دیگری")
        c = APIClient()
        c.force_authenticate(stranger)
        url = f"{self.base}/projects/{p['id']}/liquify/"
        self.assertIn(c.get(url).status_code, (403, 404))
        self.assertIn(c.put(url, self.field_bytes(1), content_type="application/octet-stream").status_code, (403, 404))
        self.assertIn(c.delete(url).status_code, (403, 404))

    def test_liquify_through_server_ctx_preview_and_edit(self):
        aid, p = self.project()
        pid = p["id"]
        asset = PhotoAsset.objects.get(pk=aid)
        orig = np.asarray(Image.open(self.media / asset.original).convert("RGB"), dtype=int)
        # بدونِ نقشه: ctx مسیر را None می‌دهد ⇒ ساخت بی‌اثر و با یادداشت
        ctx_ = services.server_ctx(asset.store)
        self.assertIsNone(ctx_["liquify_path"](pid))
        self.assertIsNone(ctx_["liquify_path"]("x"))
        self.assertIsNone(ctx_["liquify_path"](999999))
        self.assertEqual(self.put(pid, self.field_bytes(10)).status_code, 200)
        self.assertEqual(Path(ctx_["liquify_path"](pid)).name, "liquify.bin")
        # ساخت: out(x) = src(x+10)
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "manual", "operations": [
            {"tool": "liquify", "params": {"project": pid}}, {"tool": "export", "params": {"format": "png"}}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.state, "READY", (e.error, e.message))
        res = np.asarray(Image.open(self.media / e.files["result"]).convert("RGB"), dtype=int)
        self.assertEqual(res.shape, orig.shape)
        self.assertLessEqual(int(np.abs(res[:, 5:-15] - orig[:, 15:-5]).max()), 2)
        self.assertGreater(int(np.abs(res - orig).max()), 20, "واقعاً جابه‌جا شد")
        # پیش‌نمایشِ دقیقِ سایت هم نقشه را می‌بیند
        data, info = services.preview(asset, [{"tool": "liquify", "params": {"project": pid}}])
        self.assertEqual(info["skipped"], [])
        self.assertFalse(any("مایع" in n for n in info["notes"]))
        # پروژهٔ فروشگاهِ دیگر / نامعتبر ⇒ نقشه نمی‌خورد و یادداشت
        data, info = services.preview(asset, [{"tool": "liquify", "params": {"project": 999999}}])
        self.assertTrue(any("مایع" in n for n in info["notes"]))
