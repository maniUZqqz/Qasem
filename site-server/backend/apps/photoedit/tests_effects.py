"""نوبت ۴: جعبهٔ فیلترها (effects.py + API). بی شبکه، بی هوش مصنوعی، بی مدلِ تازه."""
import io
import re
from pathlib import Path

import cv2
import numpy as np
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import effects
from .models import PhotoAsset
from .tests import ApiTestBase


def textured(w=240, h=180, seed=1):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.stack([x * 255 // w, y * 255 // h, (x + y) * 127 // (w + h) + 40], axis=2).astype(np.float32)
    base += rng.normal(0, 14, base.shape)
    base[h // 3: 2 * h // 3, w // 3: 2 * w // 3] = (200, 60, 50)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def bbox_mask(img, box):
    m = Image.new("L", img.size, 0)
    m.paste(255, box)
    return m


def lap_var(img):
    g = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def png(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    b.seek(0)
    b.name = "image.png"
    return b


class EffectsCoreTests(SimpleTestCase):
    def test_every_effect_runs_changes_the_image_and_keeps_the_contract(self):
        src = textured()
        framed = np.asarray(src).copy()
        framed[:30, :, 3] = 0                                # سبک‌های لایه از روی آلفا کار می‌کنند ⇒ لبهٔ شفاف لازم است
        framed[:, :30, 3] = 0
        framed = Image.fromarray(framed, "RGBA")
        mask = bbox_mask(src, (90, 60, 150, 120))
        n = 0
        for eid, e in effects.REGISTRY.items():
            im = framed if e.group.startswith(("سبکِ لایه", "تبدیلِ لایه")) else src
            out, _ef = effects.run(eid, im, {}, mask if e.needs_mask else None)
            self.assertEqual(out.mode, "RGBA", eid)
            if e.kind == "layer":
                self.assertEqual(out.size, src.size, eid)
                diff = float(np.abs(np.asarray(out).astype(int) - np.asarray(im).astype(int)).mean())
                self.assertGreater(diff, 0.05, f"{eid} تصویر را عوض نکرد")
            else:
                self.assertGreaterEqual(min(out.size), 4, eid)
            n += 1
        self.assertGreaterEqual(n, 50)

    def test_catalog_shape_and_persian(self):
        cat = effects.catalog()
        self.assertEqual(len(cat), len(effects.REGISTRY))
        for e in cat:
            self.assertTrue(re.search(r"[؀-ۿ]", e["title"]), e["id"])
            self.assertIn(e["kind"], ("layer", "photo"))
            for p in e["params"]:
                self.assertTrue(re.search(r"[؀-ۿ]", p["title"]), (e["id"], p["key"]))
                self.assertIn(p["type"], ("range", "select", "color", "bool", "stops"))
                if p["type"] == "range":
                    self.assertLessEqual(p["min"], p["default"])
                    self.assertLessEqual(p["default"], p["max"], (e["id"], p["key"]))
                if p["type"] == "select":
                    self.assertIn(p["default"], [o[0] for o in p["options"]])
        self.assertEqual(len({e["id"] for e in cat}), len(cat))

    def test_frontend_registry_matches_server_ids(self):
        ts = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "content" / "photo" / "pro" / "menu" / "effects.ts"
        if not ts.is_file():
            self.skipTest("فایلِ فرانت کنارِ بک‌اند نیست")
        ids = set(re.findall(r'\{ id: "([a-z_]+)", menu:', ts.read_text(encoding="utf-8")))
        self.assertEqual(ids, set(effects.REGISTRY), "شناسهٔ فیلترها در فرانت و سرور یکی نیست")

    def test_params_are_clamped_and_garbage_falls_back(self):
        e = effects.REGISTRY["gaussian_blur"]
        self.assertEqual(effects._clean_params(e, {"radius": 99999})["radius"], 60)
        self.assertEqual(effects._clean_params(e, {"radius": "abc"})["radius"], 6)
        self.assertEqual(effects._clean_params(e, None)["radius"], 6)
        self.assertEqual(effects._clean_params(effects.REGISTRY["motion_blur"], {"angle": -50})["angle"], 0)
        self.assertEqual(effects._clean_params(effects.REGISTRY["wave"], {"axis": "zzz"})["axis"], "h")
        self.assertEqual(effects._clean_params(effects.REGISTRY["photo_filter"], {"color": "red"})["color"], "#ec8a00")
        with self.assertRaises(effects.EffectError):
            effects.run("no_such", textured(), {})
        with self.assertRaises(effects.EffectError):
            effects.run("gaussian_blur", Image.new("RGBA", (2, 2)), {})

    def test_mask_limits_the_effect_to_the_selection(self):
        src = textured()
        out, _ = effects.run("invert", src, {}, bbox_mask(src, (0, 0, 120, 180)))
        a, b = np.asarray(src).astype(int), np.asarray(out).astype(int)
        self.assertEqual(int(np.abs(a[:, 130:, :3] - b[:, 130:, :3]).max()), 0)           # سمتِ راست دست‌نخورده
        self.assertGreater(float(np.abs(a[:, :110, :3] - b[:, :110, :3]).mean()), 40)     # سمتِ چپ وارونه

    def test_alpha_is_preserved_by_color_effects(self):
        arr = np.asarray(textured()).copy()
        arr[:, :60, 3] = 0
        out, _ = effects.run("posterize", Image.fromarray(arr, "RGBA"), {"levels": 3})
        self.assertEqual(int(np.asarray(out)[:, :60, 3].max()), 0)

    def test_blur_really_blurs_and_sharpen_really_sharpens(self):
        src = textured()
        blurred, _ = effects.run("gaussian_blur", src, {"radius": 5})
        sharp, _ = effects.run("unsharp_mask", blurred, {"amount": 300, "radius": 2})
        self.assertLess(lap_var(blurred), lap_var(src) * 0.6)
        self.assertGreater(lap_var(sharp), lap_var(blurred) * 1.5)

    def test_remove_object_needs_a_selection_and_fills_it(self):
        arr = np.full((150, 200, 4), 255, np.uint8)
        arr[..., :3] = (90, 140, 200)
        arr[60:80, 90:110, :3] = (255, 0, 0)
        im = Image.fromarray(arr, "RGBA")
        with self.assertRaises(effects.EffectError) as cm:
            effects.run("remove_object", im, {})
        self.assertIn("انتخاب", str(cm.exception))
        out, _ = effects.run("remove_object", im, {}, bbox_mask(im, (88, 58, 112, 82)))
        px = np.asarray(out)[70, 100, :3].astype(int)
        self.assertLess(int(np.abs(px - np.array([90, 140, 200])).max()), 25)

    def test_photo_kind_effects(self):
        src = textured(300, 200)
        o, _ = effects.run("image_size", src, {"width": 150, "keep": True})
        self.assertEqual(o.size, (150, 100))
        o, _ = effects.run("image_size", src, {"width": 100, "height": 40, "keep": False})
        self.assertEqual(o.size, (100, 40))
        self.assertEqual(effects._clean_params(effects.REGISTRY["image_size"], {"width": 5000, "height": 5000})["width"], effects.MAX_SIDE)   # سقف سمتِ سرور
        o, _ = effects.run("canvas_size", src, {"width": 400, "height": 300, "anchor": "tl", "transparent": True})
        self.assertEqual(o.size, (400, 300))
        arr = np.asarray(o)
        self.assertEqual(int(arr[10, 10, 3]), 255)
        self.assertEqual(int(arr[250, 350, 3]), 0)
        o, _ = effects.run("canvas_size", src, {"width": 400, "height": 300, "anchor": "br", "transparent": True})
        self.assertEqual(int(np.asarray(o)[5, 5, 3]), 0)
        self.assertEqual(int(np.asarray(o)[295, 395, 3]), 255)
        o, _ = effects.run("canvas_size", src, {"width": 100, "height": 100, "anchor": "mc"})
        self.assertEqual(o.size, (100, 100))
        padded = Image.new("RGBA", (200, 160), (255, 255, 255, 255))
        padded.paste(Image.new("RGBA", (80, 60), (10, 50, 90, 255)), (50, 40))
        o, _ = effects.run("trim", padded, {"basis": "tl", "tol": 5})
        self.assertEqual(o.size, (80, 60))
        o, _ = effects.run("rotate_free", src, {"angle": 30, "expand": True, "transparent": True})
        self.assertGreater(o.width, 300)
        o, _ = effects.run("content_aware_scale", textured(200, 120), {"width_pct": 80, "height_pct": 100})
        self.assertEqual(o.size, (160, 120))
        o, _ = effects.run("content_aware_scale", textured(120, 100), {"width_pct": 100, "height_pct": 90})
        self.assertEqual(o.size, (120, 90))


class EffectsApiTests(ApiTestBase):
    def test_catalog_preview_apply_and_permissions(self):
        r = self.api.get(f"{self.base}/effects/")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()["effects"]), 44)
        src = textured(1400, 1000)
        r = self.api.post(f"{self.base}/effects/preview/", {"effect": "gaussian_blur", "params": '{"radius": 8}', "image": png(src)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r["Content-Type"], "image/png")
        im = Image.open(io.BytesIO(r.content))
        self.assertLessEqual(max(im.size), 900)
        self.assertEqual(r["X-Result-Size"], f"{im.width}x{im.height}")
        before = PhotoAsset.objects.count()
        r = self.api.post(f"{self.base}/effects/apply/", {"effect": "gaussian_blur", "params": '{"radius": 8}', "image": png(src), "title": "محو"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content[:300])
        j = r.json()
        self.assertEqual((j["kind"], j["blend"], j["size"]), ("layer", "normal", [1400, 1000]))
        self.assertTrue(j["asset"]["url"].startswith("/media/"))
        self.assertEqual(PhotoAsset.objects.count(), before + 1)
        self.assertEqual(PhotoAsset.objects.get(pk=j["asset"]["id"]).source_ref, "fx:gaussian_blur")
        r = self.api.post(f"{self.base}/effects/apply/", {"effect": "invert", "image": png(src), "mask": png(bbox_mask(src, (0, 0, 700, 1000)).convert("RGB"))}, format="multipart")
        self.assertEqual(r.status_code, 201)
        r = self.api.post(f"{self.base}/effects/apply/", {"effect": "image_size", "params": '{"width": 700}', "image": png(src)}, format="multipart")
        self.assertEqual((r.json()["kind"], r.json()["size"]), ("photo", [700, 500]))
        for bad in ({"effect": "nope", "image": png(src)}, {"effect": "invert"}, {"effect": "remove_object", "image": png(src)}):
            r = self.api.post(f"{self.base}/effects/apply/", bad, format="multipart")
            self.assertEqual(r.status_code, 400, bad)
            self.assertTrue(re.search(r"[؀-ۿ]", r.json()["error"]["message"]))
        r = self.api.post(f"{self.base}/effects/apply/", {"effect": "invert", "params": "{bad", "image": png(src)}, format="multipart")
        self.assertEqual(r.status_code, 400)
        other = get_user_model().objects.create_user("intruder4", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}/effects/").status_code, 404)
        self.assertEqual(c.post(f"{self.base}/effects/apply/", {"effect": "invert", "image": png(src)}, format="multipart").status_code, 404)
