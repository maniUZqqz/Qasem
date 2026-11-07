"""دورِ ۸ ادیتور عکس: برچسب/پیوندِ لایه، سبک‌ها (PhotoPreset با kind="style")، شکل‌های مسیر. بی شبکه، بی هوش مصنوعی."""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import layers, services
from .tests import ApiTestBase

BASE = {"id": "base", "type": "base"}


class LabelAndLinkTests(SimpleTestCase):
    def norm(self, **kw):
        t = {"id": "t1", "type": "text", "text": "x", "cx": 0.5, "cy": 0.5} | kw
        return layers.normalize_layers([BASE, t])[1]

    def test_label_and_link_are_kept(self):
        lay = self.norm(label="green", link="k1abc2")
        self.assertEqual((lay["label"], lay["link"]), ("green", "k1abc2"))

    def test_bad_label_and_link_are_dropped(self):
        lay = self.norm(label="pink", link="Bad Link!")
        self.assertNotIn("label", lay)
        self.assertNotIn("link", lay)
        self.assertNotIn("label", self.norm())

    def test_base_never_gets_label_or_link(self):
        out = layers.normalize_layers([dict(BASE, label="red", link="k1"), {"id": "t1", "type": "text", "text": "x"}])
        self.assertNotIn("label", out[0])
        self.assertNotIn("link", out[0])

    def test_shapes_and_images_keep_them_too(self):
        out = layers.normalize_layers([BASE, {"id": "s1", "type": "shape", "shape": "rect", "label": "blue", "link": "k9"}])
        self.assertEqual((out[1]["label"], out[1]["link"]), ("blue", "k9"))


class LibraryShapePathTests(SimpleTestCase):
    """شکل‌های آماده همان لایهٔ شکلِ path‌اند: باید از وارسیِ سرور بگذرند و کشیده شوند."""

    def poly(self, n, star=False):
        import math

        pts = []
        for i in range(n * (2 if star else 1)):
            a = (i / (n * (2 if star else 1))) * 2 * math.pi - math.pi / 2
            r = 0.5 if (not star or i % 2 == 0) else 0.22
            pts.append({"x": 0.5 + math.cos(a) * r, "y": 0.5 + math.sin(a) * r, "hi": None, "ho": None})
        return {"closed": True, "pts": pts}

    def test_star_and_polygon_paths_pass_and_render(self):
        for path in (self.poly(6), self.poly(5, star=True)):
            out = layers.normalize_layers([BASE, {"id": "s1", "type": "shape", "shape": "path", "path": path, "cx": 0.5, "cy": 0.5, "w": 0.3, "h": 0.3,
                                                  "fill": {"type": "solid", "color": "#e11d48", "opacity": 1}}])
            self.assertEqual(out[1]["shape"], "path")
            self.assertEqual(len(out[1]["path"]["pts"]), len(path["pts"]))
            img = layers.compose(Image.new("RGB", (400, 400), (255, 255, 255)), out, {"notes": [], "store_name": "x", "logo_path": lambda p: None, "mask_path": lambda pid, mid: None, "scale": 1.0})
            px = img.getpixel((200, 200))
            self.assertLess(px[1], 120, "وسطِ شکل با رنگِ قرمز پر شده")


class NormalizeStyleTests(SimpleTestCase):
    GOOD = {"target": "text", "props": {"color": "#fbbf24", "weight": 800, "stroke": {"w": 0.05, "color": "#7c4a03"}, "fx": {"shadow": None, "glow": None, "stroke": None}}}

    def test_keeps_known_keys_drops_the_rest(self):
        out = services.normalize_style_data({"target": "shape", "props": {"fill": {"type": "solid", "color": "#fff", "opacity": 1}, "evil": 1, "src": {"kind": "asset"}, "id": "x"}})
        self.assertEqual(out["target"], "shape")
        self.assertEqual(set(out["props"]), {"fill"})

    def test_bad_shapes_are_refused(self):
        for bad in (None, [1], {"target": "text"}, {"target": "laser", "props": {"color": "#fff"}}, {"target": "any", "props": {"evil": 1}}, {"target": "any", "props": []}):
            with self.assertRaises(services.PhotoError, msg=repr(bad)):
                services.normalize_style_data(bad)

    def test_size_cap(self):
        with self.assertRaises(services.PhotoError):
            services.normalize_style_data({"target": "text", "props": {"font": "x" * 20_000}})

    def test_routes_by_kind(self):
        self.assertIn("props", services.normalize_by_kind("style", self.GOOD))


class StyleApiTests(ApiTestBase):
    def test_create_list_patch_delete_and_apply_is_refused(self):
        r = self.api.post(f"{self.base}/presets/", {"name": " طلایی ", "kind": "style", "data": NormalizeStyleTests.GOOD}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        p = r.json()["preset"]
        self.assertEqual((p["name"], p["kind"]), ("طلایی", "style"))
        self.assertEqual(p["data"]["props"]["weight"], 800)
        self.assertEqual(len(self.api.get(f"{self.base}/presets/").json()["presets"]), 1)
        r2 = self.api.patch(f"{self.base}/presets/{p['id']}/", {"data": {"target": "any", "props": {"opacity": 0.5}}}, format="json")
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r2.json()["preset"]["data"]["props"], {"opacity": 0.5})
        self.assertEqual(self.api.patch(f"{self.base}/presets/{p['id']}/", {"data": {"props": {}}}, format="json").status_code, 400)
        (aid,) = self.upload(Image.new("RGB", (80, 60), (30, 30, 30)))
        ra = self.api.post(f"{self.base}/presets/{p['id']}/apply/", {"assets": [aid]}, format="json")
        self.assertEqual(ra.status_code, 400)
        self.assertIn("سبک", ra.json()["error"]["message"])
        self.assertEqual(self.api.delete(f"{self.base}/presets/{p['id']}/").status_code, 204)

    def test_bad_style_is_400(self):
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "بد", "kind": "style", "data": {"target": "text"}}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "بد", "kind": "style"}, format="json").status_code, 400)

    def test_other_users_store_is_isolated(self):
        r = self.api.post(f"{self.base}/presets/", {"name": "من", "kind": "style", "data": NormalizeStyleTests.GOOD}, format="json")
        pid = r.json()["preset"]["id"]
        other = get_user_model().objects.create_user("intruder-r8s", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertIn(c.patch(f"{self.base}/presets/{pid}/", {"name": "هک"}, format="json").status_code, (403, 404))
        self.assertIn(c.delete(f"{self.base}/presets/{pid}/").status_code, (403, 404))
