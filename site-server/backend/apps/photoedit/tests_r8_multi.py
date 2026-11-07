"""دورِ ۸: کارهای چندعکسی (شیتِ تماس، HDR، پانوراما، پردازشگر، اکشن)، LUT، تطبیقِ رنگ، انتخابِ آسمان و ناحیهٔ تمرکز. بی شبکه، بی هوش مصنوعی."""
import io
import zipfile

import cv2
import numpy as np
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import colortools, multi
from .models import PhotoAsset
from .tests import ApiTestBase, photo


def scene(w=1300, h=520, seed=3):
    """صحنهٔ پُر از جزئیات (برای دوختنِ پانوراما)"""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 120, np.uint8)
    img = cv2.GaussianBlur(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), (0, 0), 3.0)
    for _ in range(260):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        cv2.circle(img, (int(rng.integers(0, w)), int(rng.integers(0, h))), int(rng.integers(6, 30)), c, -1)
    for _ in range(120):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        p1 = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.line(img, p1, (p1[0] + int(rng.integers(-60, 60)), p1[1] + int(rng.integers(-60, 60))), c, 3)
    return Image.fromarray(img, "RGB")


def png(img: Image.Image) -> SimpleUploadedFile:
    b = io.BytesIO()
    img.save(b, "PNG")
    return SimpleUploadedFile("x.png", b.getvalue(), content_type="image/png")


class ApplyOpsTests(SimpleTestCase):
    def test_set_add_patch_remove_with_refs(self):
        st = {"layers": [{"id": "base", "type": "base", "opacity": 1}], "adjust": {}}
        added: dict = {}
        st = multi.apply_ops(st, [{"op": "set", "key": "adjust", "value": {"exposure": 0.3}},
                                  {"op": "add", "layer": {"id": "zz", "type": "text", "text": "A"}},
                                  {"op": "patch", "ref": "@0", "set": {"opacity": 0.5, "id": "evil", "type": "shape"}},
                                  {"op": "patch", "ref": "base", "set": {"opacity": 0.9}}], added)
        self.assertEqual(st["adjust"], {"exposure": 0.3})
        self.assertEqual(len(st["layers"]), 2)
        t = st["layers"][1]
        self.assertEqual((t["type"], t["opacity"]), ("text", 0.5))
        self.assertNotEqual(t["id"], "evil")
        self.assertEqual(t["id"], added["@0"])
        self.assertEqual(st["layers"][0]["opacity"], 0.9)
        st = multi.apply_ops(st, [{"op": "remove", "ref": "@0"}], added)
        self.assertEqual([l["id"] for l in st["layers"]], ["base"])

    def test_reserved_keys_and_non_portable_layers_are_ignored(self):
        st = {"layers": [{"id": "base", "type": "base"}]}
        st2 = multi.apply_ops(st, [{"op": "set", "key": "layers", "value": []}, {"op": "set", "key": "fv", "value": 9},
                                   {"op": "add", "layer": {"id": "i", "type": "image", "src": {"kind": "asset", "asset": 5}}}], {})
        self.assertEqual(len(st2["layers"]), 1)
        self.assertNotIn("fv", st2)
        self.assertIn("layers", st2)
        st3 = multi.apply_ops(st, [{"op": "add", "layer": {"id": "i", "type": "image", "src": {"kind": "logo"}}}], {})
        self.assertEqual(len(st3["layers"]), 2)

    def test_action_state_starts_from_default(self):
        s = multi.action_state({"steps": [{"label": "x", "ops": [{"op": "set", "key": "turn", "value": 90}]}]})
        self.assertEqual(s["turn"], 90)
        self.assertEqual(s["layers"][0]["id"], "base")
        self.assertEqual(multi.action_state({})["turn"], 0)


class CubeTests(SimpleTestCase):
    def cube(self, f, n=2, header=""):
        rows = []
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    rows.append(" ".join(f"{v:.6f}" for v in f(r / (n - 1), g / (n - 1), b / (n - 1))))
        return (f"TITLE \"t\"\n# c\nLUT_3D_SIZE {n}\n{header}\n" + "\n".join(rows) + "\n").encode()

    def test_identity_lut_keeps_pixels(self):
        lut = colortools.parse_cube(self.cube(lambda r, g, b: (r, g, b), 5))
        src = photo(64, 48, seed=1)
        out = colortools.apply_lut(src, lut)
        d = np.abs(np.asarray(out).astype(int) - np.asarray(src.convert("RGB")).astype(int))
        self.assertLessEqual(int(d.max()), 2)

    def test_invert_lut_and_strength(self):
        lut = colortools.parse_cube(self.cube(lambda r, g, b: (1 - r, 1 - g, 1 - b), 2))
        src = Image.new("RGB", (8, 8), (200, 50, 100))
        inv = colortools.apply_lut(src, lut).getpixel((2, 2))
        for a, b in zip(inv, (55, 205, 155)):
            self.assertAlmostEqual(a, b, delta=2)
        half = colortools.apply_lut(src, lut, 0.5).getpixel((2, 2))
        for a, b in zip(half, (127, 127, 127)):
            self.assertAlmostEqual(a, b, delta=4)
        self.assertEqual(colortools.apply_lut(src, lut, 0).getpixel((2, 2)), (200, 50, 100))

    def test_channel_order_red_changes_fastest(self):
        # فقط کانالِ قرمزِ خروجی = ورودیِ قرمز؛ سبز و آبی ثابت ⇒ سبز و آبیِ تصویر باید ثابت (۰) شوند
        lut = colortools.parse_cube(self.cube(lambda r, g, b: (r, 0.0, 0.0), 3))
        px = colortools.apply_lut(Image.new("RGB", (4, 4), (100, 200, 50)), lut).getpixel((1, 1))
        self.assertAlmostEqual(px[0], 100, delta=2)
        self.assertEqual((px[1], px[2]), (0, 0))

    def test_1d_lut_and_alpha_is_kept(self):
        body = "LUT_1D_SIZE 3\n0 0 0\n0.9 0.9 0.9\n1 1 1\n"
        lut = colortools.parse_cube(body.encode())
        rgba = Image.new("RGBA", (6, 6), (128, 128, 128, 77))
        out = colortools.apply_lut(rgba, lut)
        self.assertEqual(out.mode, "RGBA")
        self.assertEqual(out.getpixel((1, 1))[3], 77)
        self.assertGreater(out.getpixel((1, 1))[0], 200)

    def test_bad_cubes(self):
        for bad in (b"hello", b"LUT_3D_SIZE 2\n0 0 0\n", b"LUT_3D_SIZE 1\n0 0 0\n", b"LUT_3D_SIZE 999\n", b"LUT_3D_SIZE 2\n" + b"a b c\n" * 8):
            with self.assertRaises(colortools.ColorToolError, msg=bad[:20]):
                colortools.parse_cube(bad)
        with self.assertRaises(colortools.ColorToolError):
            colortools.parse_cube(b"x" * (colortools.CUBE_MAX_BYTES + 1))


class MatchColorTests(SimpleTestCase):
    def test_moves_the_mean_toward_the_reference(self):
        rng = np.random.default_rng(1)
        a = np.clip(rng.normal(100, 25, (60, 80, 3)) + np.array([60, 0, -40]), 0, 255).astype(np.uint8)    # گرم
        r = np.clip(rng.normal(120, 25, (60, 80, 3)) + np.array([-50, 10, 60]), 0, 255).astype(np.uint8)   # سرد
        src, ref = Image.fromarray(a, "RGB"), Image.fromarray(r, "RGB")
        out = colortools.match_color(src, ref, 1.0)
        mo, ms, mr = (np.asarray(x).reshape(-1, 3).mean(axis=0) for x in (out, src, ref))
        self.assertLess(np.abs(mo - mr).sum(), np.abs(ms - mr).sum() * 0.35)
        self.assertEqual(np.asarray(colortools.match_color(src, ref, 0.0)).tolist(), np.asarray(src).tolist())
        mid = np.asarray(colortools.match_color(src, ref, 0.5)).reshape(-1, 3).mean(axis=0)
        self.assertLess(np.abs(mid - mr).sum(), np.abs(ms - mr).sum())
        self.assertGreater(np.abs(mid - mr).sum(), np.abs(mo - mr).sum())

    def test_keeps_alpha(self):
        out = colortools.match_color(Image.new("RGBA", (10, 10), (200, 20, 20, 90)), Image.new("RGB", (10, 10), (20, 20, 200)))
        self.assertEqual((out.mode, out.getpixel((2, 2))[3]), ("RGBA", 90))


class AutoMaskTests(SimpleTestCase):
    def sky_scene(self):
        a = np.zeros((300, 400, 3), np.uint8)
        for y in range(120):
            a[y, :] = (60 + y // 3, 130 + y // 3, 235)          # آسمانِ آبی با گرادیان
        rng = np.random.default_rng(2)
        ground = rng.integers(20, 120, (180, 400, 3), dtype=np.uint8)
        ground[..., 1] = np.clip(ground[..., 1] + 60, 0, 255)
        a[120:] = ground
        return Image.fromarray(a, "RGB")

    def test_sky_mask_top_yes_bottom_no(self):
        m = colortools.sky_mask(self.sky_scene())
        h = m.shape[0]
        self.assertGreater(m[: int(h * 0.3)].mean(), 0.85)
        self.assertLess(m[int(h * 0.55):].mean(), 0.05)
        self.assertEqual(m.dtype, np.float32)

    def test_cloudy_sky_is_found_too(self):
        a = np.full((300, 400, 3), 200, np.uint8)
        a[:130] = (215, 218, 224)
        rng = np.random.default_rng(3)
        a[130:] = rng.integers(10, 110, (170, 400, 3), dtype=np.uint8)
        m = colortools.sky_mask(Image.fromarray(a, "RGB"))
        self.assertGreater(m[:80].mean(), 0.8)
        self.assertLess(m[-60:].mean(), 0.1)

    def test_no_sky_is_a_clear_error(self):
        rng = np.random.default_rng(4)
        with self.assertRaises(colortools.ColorToolError) as cm:
            colortools.sky_mask(Image.fromarray(rng.integers(10, 100, (200, 200, 3), dtype=np.uint8), "RGB"))
        self.assertIn("آسمان", str(cm.exception))

    def test_focus_mask_sharp_left_blurry_right(self):
        rng = np.random.default_rng(5)
        a = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
        a[:, 200:] = cv2.GaussianBlur(a[:, 200:], (0, 0), 14)
        m = colortools.focus_mask(Image.fromarray(a, "RGB"))
        self.assertGreater(m[:, :150].mean(), 0.7)
        self.assertLess(m[:, 260:].mean(), 0.15)

    def test_focus_uniform_image_errors(self):
        with self.assertRaises(colortools.ColorToolError):
            colortools.focus_mask(Image.new("RGB", (200, 200), (120, 120, 120)))
        with self.assertRaises(colortools.ColorToolError):
            colortools.mask_bytes("nope", Image.new("RGB", (10, 10)))

    def test_mask_bytes_is_a_gray_png(self):
        data = colortools.mask_bytes("sky", self.sky_scene())
        im = Image.open(io.BytesIO(data))
        self.assertEqual(im.mode, "L")


class MultiApiTests(ApiTestBase):
    def ids(self, n, **kw):
        return [self.upload(photo(160 + 8 * i, 120, seed=10 + i))[0] for i in range(n)]

    def test_contact_sheet(self):
        ids = self.ids(5)
        n0 = PhotoAsset.objects.count()
        r = self.api.post(f"{self.base}/multi/contact-sheet/", {"assets": ids, "cols": 3, "cell": 150, "labels": True}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        a = r.json()["asset"]
        gap = max(4, 150 // 25)
        self.assertEqual((a["width"], a["height"]), (gap + 3 * (150 + gap), gap + 2 * (150 + int(150 * 0.2) + gap)))
        self.assertEqual(PhotoAsset.objects.count(), n0 + 1)
        self.assertIn("شیتِ تماس", a["title"])
        r2 = self.api.post(f"{self.base}/multi/contact-sheet/", {"assets": ids[:2], "cols": 9, "cell": 120, "labels": False, "bg": "#000000"}, format="json")
        self.assertEqual(r2.status_code, 201, r2.content)
        self.assertEqual(r2.json()["asset"]["width"], 4 + 2 * (120 + 4), "ستون‌ها به تعدادِ عکس‌ها بریده می‌شود")

    def test_contact_sheet_errors(self):
        ids = self.ids(1)
        self.assertEqual(self.api.post(f"{self.base}/multi/contact-sheet/", {"assets": []}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/multi/contact-sheet/", {"assets": [ids[0], 999999]}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/multi/contact-sheet/", {"assets": list(range(1, 80))}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/multi/contact-sheet/", {"assets": ["x"]}, format="json").status_code, 400)

    def test_hdr_merge(self):
        base = photo(200, 150, seed=7)
        ids = []
        for k in (0.5, 1.0, 1.6):
            arr = np.clip(np.asarray(base).astype(np.float32) * k, 0, 255).astype(np.uint8)
            ids.append(self.upload(Image.fromarray(arr, "RGB"))[0])
        r = self.api.post(f"{self.base}/multi/merge/", {"assets": ids, "kind": "hdr"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn("HDR", r.json()["asset"]["title"])
        self.assertEqual(self.api.post(f"{self.base}/multi/merge/", {"assets": ids[:1], "kind": "hdr"}, format="json").status_code, 400)
        wide = self.upload(photo(400, 100, seed=2))[0]
        self.assertEqual(self.api.post(f"{self.base}/multi/merge/", {"assets": [ids[0], wide], "kind": "hdr"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/multi/merge/", {"assets": ids, "kind": "zzz"}, format="json").status_code, 400)

    def test_panorama_stitches_overlapping_shots_and_refuses_unrelated(self):
        full = scene()
        a = self.upload(full.crop((0, 0, 700, 520)))[0]
        b = self.upload(full.crop((420, 0, 1120, 520)))[0]
        c = self.upload(full.crop((600, 0, 1300, 520)))[0]
        r = self.api.post(f"{self.base}/multi/merge/", {"assets": [a, b, c], "kind": "panorama"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        w = r.json()["asset"]["width"]
        self.assertGreater(w, 900, "پانوراما از هر عکسِ تکی پهن‌تر شد")
        x, y = self.upload(scene(500, 400, seed=1))[0], self.upload(scene(500, 400, seed=99))[0]
        r2 = self.api.post(f"{self.base}/multi/merge/", {"assets": [x, y], "kind": "panorama"}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertTrue(r2.json()["error"]["message"])

    def test_processor_zip(self):
        ids = self.ids(2)
        r = self.api.post(f"{self.base}/multi/processor/", {"assets": ids, "sizes": [{"w": 100, "h": 100}, {"w": 60, "h": 0}], "fmt": "png", "fit": "contain"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r["Content-Type"], "application/zip")
        self.assertEqual(r["X-File-Count"], "4")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        self.assertEqual(len(names), 4)
        self.assertTrue(all(n.endswith(".png") for n in names))
        dims = sorted(Image.open(io.BytesIO(z.read(n))).size for n in names)
        self.assertIn((60, 45), dims)
        self.assertTrue(all(max(d) <= 100 for d in dims))
        r2 = self.api.post(f"{self.base}/multi/processor/", {"assets": ids[:1], "sizes": [{"w": 80, "h": 80}], "fmt": "jpeg", "fit": "cover"}, format="json")
        self.assertEqual(r2.status_code, 200)
        im = Image.open(io.BytesIO(zipfile.ZipFile(io.BytesIO(r2.content)).read(zipfile.ZipFile(io.BytesIO(r2.content)).namelist()[0])))
        self.assertEqual(im.size, (80, 80))

    def test_processor_errors(self):
        ids = self.ids(1)
        for body in ({"assets": ids, "sizes": []}, {"assets": ids, "sizes": [{"w": 5, "h": 5}]}, {"assets": ids, "sizes": [{"w": 100, "h": 0}], "fmt": "tga"},
                     {"assets": ids, "sizes": [{"w": 100, "h": 0}], "fit": "cover"}, {"assets": ids, "sizes": [{"w": 100 + i, "h": 0} for i in range(9)]},
                     {"assets": [], "sizes": [{"w": 100, "h": 0}]}, {"assets": ids, "sizes": [{"w": "x", "h": 0}]}):
            self.assertEqual(self.api.post(f"{self.base}/multi/processor/", body, format="json").status_code, 400, body)

    def test_action_runs_on_one_photo_and_creates_a_new_one(self):
        action = {"steps": [{"label": "روشن", "ops": [{"op": "set", "key": "adjust", "value": {"exposure": 0.4}}]},
                            {"label": "متن", "ops": [{"op": "add", "layer": {"id": "t1", "type": "text", "name": "واترمارک", "text": "SALE", "size": 0.1, "color": "#ffffff", "cx": 0.5, "cy": 0.5}}]}]}
        pr = self.api.post(f"{self.base}/presets/", {"name": "اکشنِ آزمون", "kind": "action", "data": action}, format="json").json()["preset"]["id"]
        (aid,) = self.upload(Image.new("RGB", (240, 160), (40, 40, 40)))
        n0 = PhotoAsset.objects.count()
        r = self.api.post(f"{self.base}/multi/action/", {"preset": pr, "asset": aid}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        new = r.json()["asset"]
        self.assertEqual(PhotoAsset.objects.count(), n0 + 1)
        self.assertIn("اکشنِ آزمون", new["title"])
        with open(multi.services.abs_path(PhotoAsset.objects.get(pk=new["id"]).original), "rb") as fh:
            px = np.asarray(Image.open(io.BytesIO(fh.read())).convert("RGB"))
        self.assertGreater(int(px.mean()), 45, "روشن‌تر شد")
        self.assertGreater(int(px.max()), 200, "متنِ سفید نشست")
        self.assertEqual(self.api.post(f"{self.base}/multi/action/", {"preset": 99999, "asset": aid}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/multi/action/", {"preset": pr, "asset": 99999}, format="json").status_code, 404)

    def test_select_auto_returns_a_mask(self):
        a = np.zeros((200, 300, 3), np.uint8)
        a[:90] = (80, 150, 240)
        a[90:] = np.random.default_rng(1).integers(10, 120, (110, 300, 3), dtype=np.uint8)
        (aid,) = self.upload(Image.fromarray(a, "RGB"))
        r = self.api.post(f"{self.base}/select/auto/", {"asset": aid, "kind": "sky"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(Image.open(io.BytesIO(r.content)).mode, "L")
        (flat,) = self.upload(Image.new("RGB", (100, 100), (90, 90, 90)))
        r2 = self.api.post(f"{self.base}/select/auto/", {"asset": flat, "kind": "focus"}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/select/auto/", {"asset": aid, "kind": "x"}, format="json").status_code, 400)

    def test_lut_and_match_color_api(self):
        (aid,) = self.upload(Image.new("RGB", (60, 40), (200, 50, 100)))
        (ref,) = self.upload(Image.new("RGB", (60, 40), (20, 60, 220)))
        rows = [f"{1 - r:.4f} {1 - g:.4f} {1 - b:.4f}" for b in (0, 1) for g in (0, 1) for r in (0, 1)]
        cube = ("LUT_3D_SIZE 2\n" + "\n".join(rows) + "\n").encode()
        r = self.api.post(f"{self.base}/color/lut/", {"asset": aid, "lut": SimpleUploadedFile("inv.cube", cube), "strength": "1"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIn("LUT", r.json()["asset"]["title"])
        bad = self.api.post(f"{self.base}/color/lut/", {"asset": aid, "lut": SimpleUploadedFile("x.cube", b"nope")}, format="multipart")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/color/lut/", {"asset": aid}, format="multipart").status_code, 400)
        m = self.api.post(f"{self.base}/color/match/", {"asset": aid, "reference": ref, "strength": 1}, format="json")
        self.assertEqual(m.status_code, 201, m.content)
        self.assertEqual(self.api.post(f"{self.base}/color/match/", {"asset": aid, "reference": aid}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/color/match/", {"asset": aid, "reference": 99999}, format="json").status_code, 404)

    def test_other_users_store_is_isolated(self):
        ids = self.ids(2)
        other = get_user_model().objects.create_user("intruder-r8m", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        for path, body in (("multi/contact-sheet/", {"assets": ids}), ("multi/merge/", {"assets": ids, "kind": "hdr"}), ("multi/processor/", {"assets": ids, "sizes": [{"w": 100, "h": 0}]}),
                           ("select/auto/", {"asset": ids[0], "kind": "sky"}), ("color/match/", {"asset": ids[0], "reference": ids[1]})):
            self.assertIn(c.post(f"{self.base}/{path}", body, format="json").status_code, (403, 404), path)
