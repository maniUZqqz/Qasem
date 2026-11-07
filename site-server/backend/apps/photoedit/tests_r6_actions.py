"""نوبت ۶ ادیتور عکس: اکشن‌های ضبط‌شدنی (ذخیره در PhotoPreset با kind="action"). بی شبکه، بی هوش مصنوعی."""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import services
from .tests import ApiTestBase

TEXT = {"id": "t1", "type": "text", "name": "واترمارک", "text": "فروشگاه من", "size": 0.04, "color": "#ffffff", "cx": 0.8, "cy": 0.92}
GOOD = {"steps": [
    {"label": "روشن‌تر", "ops": [{"op": "set", "key": "adjust", "value": {"exposure": 0.3, "contrast": 12}}]},
    {"label": "واترمارک", "ops": [{"op": "add", "layer": TEXT}, {"op": "patch", "ref": "@0", "set": {"opacity": 0.6}}]},
    {"label": "تنظیمِ عکس", "ops": [{"op": "patch", "ref": "base", "set": {"opacity": 0.95}}]},
]}


class NormalizeActionTests(SimpleTestCase):
    def test_good_action_roundtrips_and_layer_is_normalized(self):
        out = services.normalize_action_data(GOOD)
        self.assertEqual([s["label"] for s in out["steps"]], ["روشن‌تر", "واترمارک", "تنظیمِ عکس"])
        lay = out["steps"][1]["ops"][0]["layer"]
        self.assertEqual((lay["type"], lay["text"]), ("text", "فروشگاه من"))
        self.assertNotIn("parent", lay)
        self.assertEqual(out["steps"][1]["ops"][1], {"op": "patch", "ref": "@0", "set": {"opacity": 0.6}})

    def test_pixel_layers_and_reserved_keys_are_refused(self):
        paint = {"id": "p1", "type": "image", "src": {"kind": "paint", "id": "p1", "rev": 3}}
        asset = {"id": "i1", "type": "image", "src": {"kind": "asset", "asset": 5}}
        retouch = {"id": "r1", "type": "retouch", "strokes": []}
        for lay in (paint, asset, retouch):
            with self.assertRaises(services.PhotoError, msg=lay["type"] + str(lay.get("src"))):
                services.normalize_action_data({"steps": [{"label": "x", "ops": [{"op": "add", "layer": lay}]}]})
        for key in ("layers", "fv", "liquify", "bad key!", ""):
            with self.assertRaises(services.PhotoError, msg=key):
                services.normalize_action_data({"steps": [{"label": "x", "ops": [{"op": "set", "key": key, "value": 1}]}]})
        with self.assertRaises(services.PhotoError):
            services.normalize_action_data({"steps": [{"label": "x", "ops": [{"op": "explode"}]}]})
        with self.assertRaises(services.PhotoError):
            services.normalize_action_data({"steps": [{"label": "x", "ops": [{"op": "remove", "ref": "base"}]}]})
        with self.assertRaises(services.PhotoError):
            services.normalize_action_data([1, 2])

    def test_logo_is_allowed_painted_mask_is_dropped_and_protected_patch_keys_ignored(self):
        logo = {"id": "lg", "type": "image", "src": {"kind": "logo"}, "cx": 0.1, "cy": 0.1, "w": 0.2,
                "mask": {"type": "paint", "id": "m1", "invert": False, "rev": 2}}
        out = services.normalize_action_data({"steps": [{"label": "لوگو", "ops": [
            {"op": "add", "layer": logo},
            {"op": "patch", "ref": "@0", "set": {"opacity": 0.5, "id": "evil", "type": "text", "parent": "g", "src": {"kind": "asset", "asset": 1}}},
        ]}]})
        ops = out["steps"][0]["ops"]
        self.assertIsNone(ops[0]["layer"]["mask"])
        self.assertEqual(ops[1]["set"], {"opacity": 0.5})

    def test_limits_and_empty_steps(self):
        many = {"steps": [{"label": str(i), "ops": [{"op": "set", "key": "kitAuto", "value": True}]} for i in range(services.ACTION_MAX_STEPS + 1)]}
        with self.assertRaises(services.PhotoError):
            services.normalize_action_data(many)
        big = {"steps": [{"label": "b", "ops": [{"op": "set", "key": "tools", "value": {"k": "x" * 50_000}}]}]}
        with self.assertRaises(services.PhotoError):
            services.normalize_action_data(big)
        out = services.normalize_action_data({"steps": [{"label": "خالی", "ops": []}, {"label": "یک", "ops": [{"op": "patch", "ref": "base", "set": {"id": "x"}}]}]})
        self.assertEqual(out["steps"], [], "گامِ بی‌عمل (یا فقط کلیدهای ممنوع) ذخیره نمی‌شود")


class ActionApiTests(ApiTestBase):
    def test_create_list_patch_delete_and_apply_is_refused(self):
        r = self.api.post(f"{self.base}/presets/", {"name": "  لوگو و روشن  ", "kind": "action", "data": GOOD}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        p = r.json()["preset"]
        self.assertEqual((p["name"], p["kind"]), ("لوگو و روشن", "action"))
        self.assertEqual(len(p["data"]["steps"]), 3)
        self.assertEqual(len(self.api.get(f"{self.base}/presets/").json()["presets"]), 1)
        # ویرایش با دادهٔ اکشن؛ دادهٔ «پیش‌تنظیم» روی اکشن پذیرفته نمی‌شود
        r2 = self.api.patch(f"{self.base}/presets/{p['id']}/", {"name": "نامِ تازه", "data": {"steps": GOOD["steps"][:1]}}, format="json")
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(len(r2.json()["preset"]["data"]["steps"]), 1)
        self.assertEqual(self.api.patch(f"{self.base}/presets/{p['id']}/", {"data": {"adjust": {"contrast": 10}}}, format="json").status_code, 400)
        # اجرا روی چند عکس (مسیرِ پیش‌تنظیم) برای اکشن ممنوع است
        (aid,) = self.upload(Image.new("RGB", (80, 60), (30, 30, 30)))
        ra = self.api.post(f"{self.base}/presets/{p['id']}/apply/", {"assets": [aid]}, format="json")
        self.assertEqual(ra.status_code, 400)
        self.assertIn("اکشن", ra.json()["error"]["message"])
        self.assertEqual(self.api.delete(f"{self.base}/presets/{p['id']}/").status_code, 204)

    def test_bad_actions_are_400_and_develop_presets_still_work(self):
        bad = {"steps": [{"label": "x", "ops": [{"op": "add", "layer": {"id": "a1", "type": "image", "src": {"kind": "asset", "asset": 1}}}]}]}
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "بد", "kind": "action", "data": bad}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/presets/", {"name": "بد", "kind": "action", "data": {"adjust": {}}}, format="json").status_code, 400)
        r = self.api.post(f"{self.base}/presets/", {"name": "قدیمی", "data": {"adjust": {"contrast": 5}}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["preset"]["kind"], "develop")
        r = self.api.post(f"{self.base}/presets/", {"name": "اکشنِ خالی", "kind": "action"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["preset"]["data"], {"steps": []})

    def test_other_users_store_is_isolated(self):
        r = self.api.post(f"{self.base}/presets/", {"name": "من", "kind": "action", "data": GOOD}, format="json")
        pid = r.json()["preset"]["id"]
        other = get_user_model().objects.create_user("intruder-r6a", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertIn(c.patch(f"{self.base}/presets/{pid}/", {"name": "هک"}, format="json").status_code, (403, 404))
        self.assertIn(c.delete(f"{self.base}/presets/{pid}/").status_code, (403, 404))
