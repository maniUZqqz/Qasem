"""دورِ ۸: فیلترهای تازه — رنگِ انتخابی (CMYK)، تُن HDR، نقطه‌نقطه، پوستری با خطِ لبه، ساتن، نورپردازیِ چندتایی. بی شبکه، بی هوش مصنوعی."""
import numpy as np
from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from . import effects

NEW = ("selective_color", "hdr_toning", "pointillize", "poster_edges", "satin", "lighting_multi")


def noise(w=120, h=90, seed=1):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (h, w, 4), dtype=np.uint8) | np.array([0, 0, 0, 255], np.uint8), "RGBA")


def patches():
    img = Image.new("RGBA", (90, 30), (128, 128, 128, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 29, 29], fill=(220, 40, 40, 255))      # قرمز
    d.rectangle([30, 0, 59, 29], fill=(40, 60, 220, 255))     # آبی
    d.rectangle([60, 0, 89, 29], fill=(15, 15, 15, 255))      # تقریباً سیاه
    return img


def arr(img):
    return np.asarray(img.convert("RGBA")).astype(int)


class NewEffectsTests(SimpleTestCase):
    def test_all_registered_and_run_with_defaults(self):
        for eid in NEW:
            self.assertIn(eid, effects.REGISTRY, eid)
            out, e = effects.run(eid, noise(), {})
            self.assertEqual(out.size, (120, 90), eid)
            self.assertEqual(out.mode, "RGBA", eid)

    def test_selective_color_changes_only_its_range(self):
        src = patches()
        out = arr(effects.run("selective_color", src, {"range": "reds", "cyan": 100, "relative": False})[0])
        s = arr(src)
        self.assertGreater(np.abs(out[10, 10, :3] - s[10, 10, :3]).sum(), 60, "قرمز عوض شد")
        self.assertLessEqual(np.abs(out[10, 40, :3] - s[10, 40, :3]).sum(), 4, "آبی دست‌نخورده")
        self.assertLessEqual(np.abs(out[10, 70, :3] - s[10, 70, :3]).sum(), 6, "سیاه دست‌نخورده")
        zero = arr(effects.run("selective_color", src, {"range": "reds", "cyan": 0, "magenta": 0, "yellow": 0, "black": 0})[0])
        self.assertLessEqual(np.abs(zero - s).max(), 1, "همه صفر ⇒ بی‌تغییر")

    def test_selective_color_blacks_and_cyan_direction(self):
        src = patches()
        out = arr(effects.run("selective_color", src, {"range": "blacks", "black": -100, "relative": True})[0])
        self.assertGreater(out[10, 70, :3].sum(), arr(src)[10, 70, :3].sum() + 10, "سیاه‌ها روشن‌تر")
        blue = arr(effects.run("selective_color", src, {"range": "blues", "yellow": 100, "relative": False})[0])
        self.assertLess(blue[10, 40, 2], arr(src)[10, 40, 2], "زردِ بیشتر در آبی ⇒ آبی کمتر")

    def test_hdr_toning_lifts_shadows(self):
        a = np.full((120, 160, 3), 25, np.uint8)
        a[:, 80:] = 235
        a[40:80, 20:60] = 8
        src = Image.fromarray(a, "RGB").convert("RGBA")
        out = arr(effects.run("hdr_toning", src, {"compress": 80, "detail": 160})[0])
        self.assertGreater(out[60, 40, :3].mean(), arr(src)[60, 40, :3].mean(), "سایهٔ عمیق روشن‌تر")
        self.assertEqual(out.shape, arr(src).shape)

    def test_pointillize_background_and_dots(self):
        src = Image.new("RGBA", (200, 200), (200, 30, 30, 255))
        out = arr(effects.run("pointillize", src, {"size": 18, "bg": "white"})[0])
        white = (out[..., :3].min(axis=2) > 245).mean()
        red = ((out[..., 0] > 150) & (out[..., 1] < 90)).mean()
        self.assertGreater(white, 0.02, "بینِ نقطه‌ها زمینهٔ سفید دیده می‌شود")
        self.assertGreater(red, 0.4, "بیشترِ سطح نقطه‌هایی به رنگِ تصویر است")
        black = arr(effects.run("pointillize", src, {"size": 18, "bg": "black"})[0])
        self.assertGreater((black[..., :3].max(axis=2) < 10).mean(), 0.02)
        self.assertTrue(np.array_equal(arr(effects.run("pointillize", src, {"seed": 5})[0]), arr(effects.run("pointillize", src, {"seed": 5})[0])), "با دانهٔ یکسان یکسان")

    def test_poster_edges_levels_and_lines(self):
        out = arr(effects.run("poster_edges", noise(160, 120), {"levels": 3, "edge": 0})[0])
        for c in range(3):
            self.assertLessEqual(len(np.unique(out[..., c])), 3, "فقط ۳ سطح")
        a = np.zeros((100, 100, 3), np.uint8)
        a[:, 50:] = 255
        lined = arr(effects.run("poster_edges", Image.fromarray(a, "RGB"), {"levels": 2, "edge": 100, "width": 3})[0])
        self.assertLess(lined[50, 49:53, :3].min(), 130, "روی لبه خطِ تیره افتاد")
        self.assertGreater(lined[50, 80, :3].min(), 240)

    def test_satin_shades_inside_without_touching_alpha(self):
        img = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([20, 20, 140, 140], fill=(240, 240, 240, 255))
        out = effects.run("satin", img, {"opacity": 80, "distance": 12, "size": 10, "angle": 30})[0]
        self.assertTrue(np.array_equal(arr(out)[..., 3], arr(img)[..., 3]), "آلفا دست‌نخورده")
        self.assertGreater(np.abs(arr(out)[..., :3] - arr(img)[..., :3]).sum(), 5000, "داخلِ شکل سایه‌روشن خورد")
        none = effects.run("satin", img, {"opacity": 0})[0]
        self.assertTrue(np.array_equal(arr(none), arr(img)))

    def test_lighting_multi(self):
        src = Image.new("RGBA", (200, 150), (140, 140, 140, 255))
        out = arr(effects.run("lighting_multi", src, {"ambient": 0, "power1": 100, "x1": 15, "y1": 15, "power2": 0, "relief": 0, "radius": 60})[0])
        self.assertGreater(out[20, 25, :3].mean(), out[130, 180, :3].mean() + 40, "نزدیکِ نور روشن‌تر از دورتر")
        flat = arr(effects.run("lighting_multi", src, {"ambient": 100, "power1": 0, "power2": 0, "power3": 0, "relief": 0})[0])
        self.assertLessEqual(np.abs(flat - arr(src)).max(), 1, "فقط نورِ محیطِ کامل ⇒ بی‌تغییر")
        warm = arr(effects.run("lighting_multi", src, {"ambient": 0, "power1": 0, "power2": 100, "x2": 50, "y2": 50, "color2": "#ff0000", "radius": 100, "relief": 0})[0])
        self.assertGreater(warm[75, 100, 0], warm[75, 100, 2] + 30, "نورِ قرمز")
        textured = arr(effects.run("lighting_multi", noise(), {"relief": 100, "power1": 100})[0])
        self.assertEqual(textured.shape, (90, 120, 4))
