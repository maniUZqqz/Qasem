"""دورِ ۸ ادیتور عکس: قلم‌موی دلخواه (PhotoPreset با kind="brush"). بی شبکه، بی هوش مصنوعی."""
import base64
import io

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import services
from .tests import ApiTestBase


def tip_url(size=24, alpha=200) -> str:
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), (0, 0, 0, alpha)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class NormalizeBrushTests(SimpleTestCase):
    def test_defaults_and_clamping(self):
        out = services.normalize_brush_data({})
        self.assertEqual(out, {"size": 24, "hardness": 0.5, "flow": 1, "spacing": 0.14, "scatter": 0, "kind": "soft", "tip": None})
        out = services.normalize_brush_data({"size": 9999, "hardness": -3, "flow": 0, "spacing": 50, "scatter": 7, "kind": "spray", "color": "#ABCDEF"})
        self.assertEqual((out["size"], out["hardness"], out["flow"], out["spacing"], out["scatter"]), (400, 0, 0.02, 2, 2))
        self.assertEqual((out["kind"], out["color"]), ("spray", "#abcdef"))
        self.assertEqual(services.normalize_brush_data(None)["size"], 24)

    def test_bad_values_are_refused(self):
        for bad in ([1], "x", {"kind": "laser"}, {"size": "abc"}, {"size": float("nan")}, {"color": "red"}, {"tip": "http://evil/x.png"},
                    {"tip": "data:image/svg+xml;base64,AAAA"}, {"tip": 5}):
            with self.assertRaises(services.PhotoError, msg=repr(bad)):
                services.normalize_brush_data(bad)

    def test_tip_size_cap(self):
        ok = tip_url(24)
        self.assertEqual(services.normalize_brush_data({"tip": ok})["tip"], ok)
        huge = "data:image/png;base64," + "A" * (services.BRUSH_MAX_TIP_BYTES + 10)
        with self.assertRaises(services.PhotoError):
            services.normalize_brush_data({"tip": huge})

    def test_by_kind_routes(self):
        self.assertIn("size", services.normalize_by_kind("brush", {"size": 10}))
        self.assertIn("steps", services.normalize_by_kind("action", {"steps": []}))


class BrushApiTests(ApiTestBase):
    def test_create_list_patch_delete_and_apply_is_refused(self):
        body = {"name": " ستاره ", "kind": "brush", "data": {"size": 40, "hardness": 0.2, "flow": 0.8, "spacing": 0.5, "scatter": 0.3, "kind": "soft", "tip": tip_url()}}
        r = self.api.post(f"{self.base}/presets/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        p = r.json()["preset"]
        self.assertEqual((p["name"], p["kind"]), ("ستاره", "brush"))
        self.assertEqual(p["data"]["size"], 40)
        self.assertTrue(p["data"]["tip"].startswith("data:image/png;base64,"))
        self.assertEqual(len(self.api.get(f"{self.base}/presets/").json()["presets"]), 1)
        r2 = self.api.patch(f"{self.base}/presets/{p['id']}/", {"data": {"size": 12, "kind": "hard"}}, format="json")
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual((r2.json()["preset"]["data"]["size"], r2.json()["preset"]["data"]["tip"]), (12, None))
        self.assertEqual(self.api.patch(f"{self.base}/presets/{p['id']}/", {"data": {"kind": "laser"}}, format="json").status_code, 400)
        (aid,) = self.upload(Image.new("RGB", (80, 60), (30, 30, 30)))
        ra = self.api.post(f"{self.base}/presets/{p['id']}/apply/", {"assets": [aid]}, format="json")
        self.assertEqual(ra.status_code, 400)
        self.assertIn("قلم", ra.json()["error"]["message"])
        self.assertEqual(self.api.delete(f"{self.base}/presets/{p['id']}/").status_code, 204)

    def test_bad_brush_is_400_and_empty_brush_gets_defaults(self):
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "بد", "kind": "brush", "data": {"tip": "javascript:alert(1)"}}, format="json").status_code, 400)
        r = self.api.post(f"{self.base}/presets/", {"name": "ساده", "kind": "brush"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["preset"]["data"]["size"], 24)

    def test_other_users_store_is_isolated(self):
        r = self.api.post(f"{self.base}/presets/", {"name": "من", "kind": "brush", "data": {"size": 5}}, format="json")
        pid = r.json()["preset"]["id"]
        other = get_user_model().objects.create_user("intruder-r8b", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertIn(c.patch(f"{self.base}/presets/{pid}/", {"name": "هک"}, format="json").status_code, (403, 404))
        self.assertIn(c.delete(f"{self.base}/presets/{pid}/").status_code, (403, 404))
