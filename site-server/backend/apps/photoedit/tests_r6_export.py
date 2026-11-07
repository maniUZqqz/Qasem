"""نوبت ۶ ادیتور عکس: خروجی با قالب‌های دیگر (TIFF، GIF، PDF، BMP) و فایلِ لایه‌دارِ PSD. بی شبکه، بی هوش مصنوعی."""
import io
from urllib.parse import unquote

import numpy as np
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import exportfmt, layers, psd
from .tests import ApiTestBase, photo
from .tests_pro import base_layer, png_bytes
from .tests_r5 import paint_layer


def solid(w, h, c):
    return Image.new("RGBA", (w, h), c)


class PsdWriterTests(SimpleTestCase):
    def test_roundtrip_layers_positions_names_opacity_blend_hidden_and_merged(self):
        merged = Image.new("RGB", (40, 30), (10, 20, 30))
        a = psd.PsdLayer("عکس", solid(40, 30, (10, 20, 30, 255)))
        b = psd.PsdLayer("لایهٔ قرمز", solid(12, 8, (255, 0, 0, 200)), x=5, y=7, opacity=0.5, blend="multiply")
        c = psd.PsdLayer("hidden", solid(4, 4, (0, 255, 0, 255)), x=30, y=20, visible=False, blend="screen")
        raw = psd.write_psd((40, 30), merged, [a, b, c])
        back = psd.read_psd(raw)
        self.assertEqual(back["size"], (40, 30))
        self.assertEqual([l["name"] for l in back["layers"]], ["عکس", "لایهٔ قرمز", "hidden"])
        lb = back["layers"][1]
        self.assertEqual((lb["x"], lb["y"], lb["w"], lb["h"]), (5, 7, 12, 8))
        self.assertAlmostEqual(lb["opacity"], 0.5, delta=0.01)
        self.assertEqual((lb["blend"], back["layers"][2]["blend"]), ("multiply", "screen"))
        self.assertEqual([l["visible"] for l in back["layers"]], [True, True, False])
        self.assertEqual(tuple(lb["rgba"][0, 0]), (255, 0, 0, 200))
        self.assertTrue(np.array_equal(back["merged"][..., 0], np.full((30, 40), 10)))

    def test_pillow_opens_the_merged_image(self):
        merged = Image.new("RGB", (64, 48), (200, 100, 50))
        raw = psd.write_psd((64, 48), merged, [psd.PsdLayer("L", solid(10, 10, (1, 2, 3, 255)))])
        im = Image.open(io.BytesIO(raw))
        self.assertEqual(im.format, "PSD")
        self.assertEqual(im.size, (64, 48))
        self.assertEqual(im.convert("RGB").getpixel((5, 5)), (200, 100, 50))

    def test_alpha_merged_is_flattened_on_white_and_bad_size_rejected(self):
        m = Image.new("RGBA", (6, 6), (255, 0, 0, 0))
        raw = psd.write_psd((6, 6), m, [])
        self.assertEqual(Image.open(io.BytesIO(raw)).convert("RGB").getpixel((1, 1)), (255, 255, 255))
        with self.assertRaises(ValueError):
            psd.write_psd((0, 5), m, [])
        with self.assertRaises(ValueError):
            psd.read_psd(b"nope")

    def test_every_blend_mode_has_a_key(self):
        self.assertEqual(set(psd.BLEND_KEYS), set(layers.BLEND_MODES))
        self.assertEqual(len(set(psd.BLEND_KEYS.values())), len(psd.BLEND_KEYS))


class ConvertTests(SimpleTestCase):
    def test_every_format_opens_with_the_right_size_and_type(self):
        img = Image.new("RGBA", (120, 80), (255, 0, 0, 255))
        img.paste((0, 0, 255, 128), (60, 0, 120, 80))
        for fmt, pil in (("tiff", "TIFF"), ("gif", "GIF"), ("bmp", "BMP"), ("png", "PNG"), ("jpeg", "JPEG"), ("webp", "WEBP")):
            data = exportfmt.convert(img, fmt)
            im = Image.open(io.BytesIO(data))
            self.assertEqual((im.format, im.size), (pil, (120, 80)), fmt)
        pdf = exportfmt.convert(img, "pdf")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(Image.open(io.BytesIO(exportfmt.convert(img, "gif"))).mode, "P")
        self.assertEqual(Image.open(io.BytesIO(exportfmt.convert(img, "tiff"))).mode, "RGBA", "TIFF شفافیت را نگه می‌دارد")
        self.assertEqual(Image.open(io.BytesIO(exportfmt.convert(img, "png"))).mode, "RGBA")
        flat = Image.open(io.BytesIO(exportfmt.convert(img, "bmp"))).convert("RGB")
        r, g, b = flat.getpixel((90, 10))
        self.assertTrue(abs(r - 127) <= 2 and abs(g - 127) <= 2 and b == 255, "نیمه‌شفافِ آبی روی سفید پخته می‌شود")
        with self.assertRaises(exportfmt.ExportError):
            exportfmt.convert(img, "psd")
        with self.assertRaises(exportfmt.ExportError):
            exportfmt.convert(img, "exe")

    def test_transparent_is_flattened_on_white_for_formats_without_alpha(self):
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        for fmt in ("gif", "bmp", "jpeg"):
            px = Image.open(io.BytesIO(exportfmt.convert(img, fmt))).convert("RGB").getpixel((5, 5))
            self.assertTrue(all(v > 240 for v in px), (fmt, px))


class LayerRasterTests(SimpleTestCase):
    def test_masks_are_baked_and_non_pixel_layers_skipped(self):
        base = Image.new("RGB", (60, 40), (10, 10, 10))
        lst = layers.normalize_layers([
            base_layer(),
            {"id": "adj", "type": "adjust", "adjust": {"exposure": 0.3}},
            {"id": "r", "type": "shape", "shape": "rect", "cx": 0.5, "cy": 0.5, "w": 1.0, "h": 1.0, "fill": {"type": "solid", "color": "#ff0000", "opacity": 1},
             "mask": {"type": "linear", "p0": [0, 0.5], "p1": [1, 0.5], "invert": False}},
        ])
        out = layers.layer_rasters(base, lst, {"notes": []}, project=0)
        self.assertEqual([r["layer"]["id"] for r in out], ["base", "r"])
        t = out[1]["tile"]
        self.assertGreater(int(t[20, 2, 3]), 200)            # سمتِ چپ دیده می‌شود
        self.assertLess(int(t[20, -3, 3]), 30)               # سمتِ راست با ماسک پنهان شد


class ExportApiTests(ApiTestBase):
    def project(self, layers_):
        (aid,) = self.upload(photo(320, 240))
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": "پروژهٔ خروجی", "data": {"layers": layers_}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]

    def test_every_format_downloads_and_psd_has_the_layers(self):
        text = {"id": "t1", "type": "text", "name": "تیتر", "text": "SALE", "size": 0.12, "color": "#ffffff", "cx": 0.5, "cy": 0.3, "underline": True}
        shape = {"id": "s1", "type": "shape", "name": "کادر", "shape": "rect", "cx": 0.5, "cy": 0.7, "w": 0.3, "h": 0.2, "fill": {"type": "solid", "color": "#0000ff", "opacity": 1}, "opacity": 0.8}
        p = self.project([base_layer(), shape, text, paint_layer(pid="pp1", name="نقاشی")])
        pid = p["id"]
        pnt = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
        pnt.paste((0, 255, 0, 255), (0, 0, 32, 48))
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/paints/pp1/", png_bytes(pnt), content_type="image/png").status_code, 200)
        for fmt, mime in (("tiff", "image/tiff"), ("pdf", "application/pdf"), ("gif", "image/gif"), ("bmp", "image/bmp"), ("png", "image/png"), ("jpeg", "image/jpeg"), ("webp", "image/webp")):
            r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt={fmt}")
            self.assertEqual(r.status_code, 200, (fmt, r.content[:200]))
            self.assertEqual(r["Content-Type"], mime)
            self.assertIn("attachment", r["Content-Disposition"])
            self.assertTrue(len(r.content) > 200, fmt)
        r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt=psd")
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r["Content-Type"], "image/vnd.adobe.photoshop")
        back = psd.read_psd(r.content)
        names = [l["name"] for l in back["layers"]]
        self.assertEqual(len(names), 4, names)
        self.assertIn("کادر", names)
        self.assertIn("تیتر", names)
        self.assertEqual(Image.open(io.BytesIO(r.content)).size, tuple(back["size"]))
        shape_l = next(l for l in back["layers"] if l["name"] == "کادر")
        self.assertAlmostEqual(shape_l["opacity"], 0.8, delta=0.01)
        self.assertEqual(int(shape_l["rgba"][5, 5, 2]), 255)
        paint_l = next(l for l in back["layers"] if l["name"] == "نقاشی")
        W = back["size"][0]
        self.assertEqual(tuple(paint_l["rgba"][10, 10]), (0, 255, 0, 255))
        self.assertEqual(int(paint_l["rgba"][10, W - 10, 3]), 0)
        self.assertIsInstance(unquote(r["X-Export-Notes"]), str)

    def test_bad_format_missing_project_and_other_user(self):
        p = self.project([base_layer()])
        pid = p["id"]
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/export/?fmt=exe").status_code, 400)
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/export/").status_code, 400)
        self.assertEqual(self.api.get(f"{self.base}/projects/999999/export/?fmt=pdf").status_code, 404)
        r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt=jpeg&quality=60")
        self.assertEqual(r.status_code, 200)
        other = get_user_model().objects.create_user("intruder-r6", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}/projects/{pid}/export/?fmt=pdf").status_code, 404)


class PsdGuardTests(SimpleTestCase):
    def test_psd_refuses_huge_projects_before_allocating(self):
        from unittest import mock

        frame = Image.new("RGB", (1000, 1000), (9, 9, 9))
        lst = [base_layer()] + [{"id": f"i{k}", "type": "image", "src": {"kind": "logo"}} for k in range(1)]
        with mock.patch.object(exportfmt, "PSD_MAX_PIXELS", 500_000):
            with self.assertRaises(exportfmt.ExportError) as cm:
                exportfmt.psd_bytes(frame, frame, lst, {"notes": []}, 0)
        self.assertIn("خیلی بزرگ", str(cm.exception))

    def test_joined_writer_matches_the_documented_layout(self):
        merged = Image.new("RGB", (16, 12), (1, 2, 3))
        raw = psd.write_psd((16, 12), merged, [psd.PsdLayer("a", solid(16, 12, (4, 5, 6, 255))), psd.PsdLayer("b", solid(3, 3, (7, 8, 9, 100)), x=2, y=2)])
        back = psd.read_psd(raw)
        self.assertEqual([l["name"] for l in back["layers"]], ["a", "b"])
        self.assertEqual(tuple(back["layers"][1]["rgba"][0, 0]), (7, 8, 9, 100))
        self.assertEqual(tuple(back["merged"][0, 0]), (1, 2, 3))
        self.assertEqual(Image.open(io.BytesIO(raw)).size, (16, 12))
