"""نوبت ۵ ادیتور عکس: لایهٔ نقاشی (paint layer) — نرمال‌سازی، ترکیب، API ذخیره/خواندن، پاک‌سازی، پیش‌تنظیم. بی شبکه و بی هوش مصنوعی."""
import io
import os
import time
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from . import layers
from .models import PhotoProject
from .tests import ApiTestBase, photo
from .tests_pro import base_layer, png_bytes


def paint_layer(pid="p1", rev=1, **kw):
    d = {"id": "pl", "type": "image", "src": {"kind": "paint", "id": pid, "rev": rev}, "cx": 0.9, "cy": 0.1, "w": 0.2, "rot": 40}
    d.update(kw)
    return d


class PaintNormalizeTests(SimpleTestCase):
    def test_paint_src_is_full_canvas_and_clean(self):
        out = layers.normalize_layers([base_layer(), paint_layer(flip_h=True, fx={"shadow": {"color": "#000000", "opacity": 1}})])
        pl = out[1]
        self.assertEqual(pl["src"], {"kind": "paint", "id": "p1", "rev": 1})
        self.assertEqual((pl["cx"], pl["cy"], pl["w"], pl["rot"]), (0.5, 0.5, 1.0, 0))
        self.assertFalse(pl["flip_h"] or pl["flip_v"])
        self.assertIsNone(pl["fx"])
        self.assertEqual(layers.paint_ids(out), {"p1"})

    def test_bad_ids_rejected_and_garbage_rev_is_zero(self):
        with self.assertRaises(layers.LayerError):
            layers.normalize_layers([base_layer(), paint_layer(pid="BAD ID")])
        out = layers.normalize_layers([base_layer(), paint_layer(rev="x")])
        self.assertEqual(out[1]["src"]["rev"], 0)

    def test_preset_layers_drop_paint_layers(self):
        out = layers.preset_layers([base_layer(), paint_layer(), {"id": "t1", "type": "text", "text": "سلام"}])
        self.assertEqual([l["type"] for l in out], ["text"])


class PaintComposeTests(SimpleTestCase):
    def test_paint_raster_is_composited_resized_and_respects_opacity_and_mask(self):
        base = Image.new("RGB", (80, 60), (10, 20, 30))
        paint = Image.new("RGBA", (40, 30), (0, 0, 0, 0))            # نصفِ اندازهٔ بوم؛ باید کشیده شود
        for x in range(20, 40):
            for y in range(30):
                paint.putpixel((x, y), (255, 0, 0, 255))
        ctx = {"notes": [], "paint_path": lambda project, pid: self.path}
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            self.path = Path(td) / "paint-p1.png"
            paint.save(self.path)
            lst = layers.normalize_layers([base_layer(), paint_layer()])
            out = layers.compose(base, lst, ctx, project=7)
            self.assertEqual(out.getpixel((70, 30)), (255, 0, 0))     # نیمهٔ راست قرمز
            self.assertEqual(out.getpixel((10, 30)), (10, 20, 30))    # نیمهٔ چپ: همان عکس
            lst2 = layers.normalize_layers([base_layer(), paint_layer(opacity=0.5)])
            half = layers.compose(base, lst2, {"notes": [], "paint_path": lambda p, i: self.path}, project=7).getpixel((70, 30))
            self.assertAlmostEqual(half[0], (255 + 10) / 2, delta=3)
            # ماسکِ خطی: همه جا نیمه‌شفاف نمی‌شود ولی لایه بی‌نقص ترکیب می‌شود
            lst3 = layers.normalize_layers([base_layer(), paint_layer(visible=False)])
            self.assertEqual(layers.compose(base, lst3, {"notes": [], "paint_path": lambda p, i: self.path}, project=7).getpixel((70, 30)), (10, 20, 30))

    def test_missing_paint_file_is_noted_not_fatal(self):
        base = Image.new("RGB", (30, 20), (1, 2, 3))
        ctx = {"notes": [], "paint_path": lambda project, pid: None}
        out = layers.compose(base, layers.normalize_layers([base_layer(), paint_layer()]), ctx, project=1)
        self.assertEqual(out.getpixel((5, 5)), (1, 2, 3))
        self.assertTrue(any("نقاشی" in n for n in ctx["notes"]))


class PaintApiTests(ApiTestBase):
    def project(self):
        (aid,) = self.upload(photo(320, 240))
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": "پروژهٔ نقاشی", "data": {}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]

    def test_put_get_delete_keeps_alpha_and_clamps_size(self):
        p = self.project()
        pid = p["id"]
        img = Image.new("RGBA", (3000, 1500), (0, 0, 0, 0))
        img.putpixel((10, 10), (255, 0, 0, 128))
        r = self.api.put(f"{self.base}/projects/{pid}/paints/p1/", png_bytes(img), content_type="image/png")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["w"], r.json()["h"]), (2048, 1024))
        got = self.api.get(f"{self.base}/projects/{pid}/paints/p1/")
        self.assertEqual(got.status_code, 200)
        im = Image.open(io.BytesIO(got.content))
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.getpixel((0, 0))[3], 0, "آلفای شفاف حفظ می‌شود")
        proj = self.api.get(f"{self.base}/projects/{pid}/").json()["project"]
        self.assertEqual(list(proj["paints"]), ["p1"])
        self.assertIn("/media/", proj["paints"]["p1"])
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/paints/BAD ID/", b"x", content_type="image/png").status_code, 400)
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/paints/p2/", b"not an image", content_type="image/png").status_code, 400)
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/paints/p2/", b"", content_type="image/png").status_code, 400)
        self.assertEqual(self.api.delete(f"{self.base}/projects/{pid}/paints/p1/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/projects/{pid}/paints/p1/").status_code, 404)

    def test_gc_keeps_referenced_and_drops_old_unreferenced(self):
        p = self.project()
        pid = p["id"]
        small = Image.new("RGBA", (40, 30), (1, 2, 3, 255))
        for name in ("keep", "drop", "fresh"):
            self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/paints/{name}/", png_bytes(small), content_type="image/png").status_code, 200)
        lay = [base_layer(), paint_layer(pid="keep")]
        self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay}}, format="json")
        d = self.media / PhotoProject.objects.get(pk=pid).dir_rel
        self.assertTrue((d / "paint-fresh.png").is_file(), "فایلِ تازه نباید پاک شود")
        old = time.time() - 3600
        for n in ("keep", "drop", "fresh"):
            os.utime(d / f"paint-{n}.png", (old, old))
        self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay}}, format="json")
        self.assertTrue((d / "paint-keep.png").is_file())
        self.assertFalse((d / "paint-drop.png").is_file())
        self.assertFalse((d / "paint-fresh.png").is_file())

    def test_project_save_accepts_paint_layer_and_other_user_gets_404(self):
        p = self.project()
        pid = p["id"]
        lay = [base_layer(), paint_layer()]
        r = self.api.put(f"{self.base}/projects/{pid}/", {"data": {"layers": lay}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        saved = r.json()["project"]["data"]["layers"][1]
        self.assertEqual(saved["src"]["kind"], "paint")
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from apps.stores.models import Store

        other = get_user_model().objects.create_user("intruder-r5", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}/projects/{pid}/paints/p1/").status_code, 404)
        self.assertEqual(c.put(f"{self.base}/projects/{pid}/paints/p1/", b"x", content_type="image/png").status_code, 404)

    def test_end_to_end_server_render_uses_the_uploaded_paint(self):
        from . import services

        p = self.project()
        pid = p["id"]
        paint = Image.new("RGBA", (320, 240), (0, 0, 0, 0))
        for x in range(160, 320):
            for y in range(240):
                paint.putpixel((x, y), (0, 255, 0, 255))
        self.assertEqual(self.api.put(f"{self.base}/projects/{pid}/paints/p1/", png_bytes(paint), content_type="image/png").status_code, 200)
        proj = PhotoProject.objects.select_related("asset", "store").get(pk=pid)
        ctx = services.server_ctx(proj.store)
        base = Image.new("RGB", (320, 240), (50, 50, 50))
        out = layers.compose(base, layers.normalize_layers([base_layer(), paint_layer()]), ctx, project=pid)
        self.assertEqual(out.getpixel((300, 100)), (0, 255, 0))
        self.assertEqual(out.getpixel((20, 100)), (50, 50, 50))
        self.assertFalse(any("نقاشی" in n for n in ctx["notes"]), ctx["notes"])
