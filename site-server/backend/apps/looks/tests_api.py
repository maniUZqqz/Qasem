"""API ِ «سبک تصویر» زیرِ /api/v1/looks/: فهرستِ ۱۱۶ سبک با نمونهٔ رنگی، فیلتر، جزئیات، تم‌ها، compose (سبکِ نامناسب ⇒ توضیحِ فارسی)، پیشنهاد، نمونه‌ها."""
from __future__ import annotations

import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.stores.models import Membership, Store

from . import compose, library, samples, schema

User = get_user_model()
BASE = "/api/v1/looks"


class LooksApiBase(TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="nmlooks-data-"))
        self.override = override_settings(NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("looks-api-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه", business_type="پوشاک و مد", target_audience="جوان‌ها",
                                          colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.data, ignore_errors=True)


class ListAndDetailTests(LooksApiBase):
    def test_all_116_looks_and_24_themes_are_listed_with_swatches(self):
        r = self.api.get(f"{BASE}/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["count"], body["total"]), (116, 116))
        self.assertEqual(len(body["styles"]), 116)
        self.assertEqual(len(body["themes"]), 24)
        self.assertEqual({g["key"] for g in body["groups"]}, set(schema.GROUPS))
        self.assertEqual({k["key"] for k in body["kinds"]}, set(compose.KINDS))
        self.assertEqual(sum(1 for k in body["kinds"] if k["product_preserving"]), 2)
        for s in body["styles"]:
            self.assertTrue(s["name_fa"] and s["description_fa"] and s["palette"], s["key"])
            self.assertEqual(s["preview_url"], f"{BASE}/{s['key']}/preview.svg")
            self.assertIsNone(s["sample_url"])
            self.assertIsInstance(s["product_safe"], bool)
            self.assertNotIn("image_positive", s, "دستورها فقط در جزئیات می‌آیند")
        self.assertEqual(body["samples"], {"total": 116, "done": 0, "pending": 116})

    def test_filters_and_search(self):
        q = lambda s: self.api.get(f"{BASE}/?{s}").json()  # noqa: E731
        self.assertEqual([s["key"] for s in q("q=lego")["styles"]], ["toy_brick_3d"])
        self.assertEqual([s["key"] for s in q("q=Lego-like%20bricks")["styles"]], ["toy_brick_3d"])
        self.assertIn("painterly_pastoral", [s["key"] for s in q("q=%DA%98%DB%8C%D8%A8%D9%84%DB%8C")["styles"]])        # ژیبلی
        craft = q("group=craft")
        self.assertTrue(craft["count"] and all(s["group"] == "craft" for s in craft["styles"]))
        safe = q("product_safe=1")
        self.assertEqual({s["key"] for s in safe["styles"]}, {k for k, v in library.STYLES.items() if v["product_safe"]})
        self.assertEqual(q("product_safe=0")["count"], 116 - safe["count"])
        self.assertTrue(q("ad_fit=story")["count"] and q("realism=realistic")["count"])
        self.assertEqual(q("q=zzzz-nothing")["count"], 0)

    def test_kind_marks_which_looks_are_usable_for_it(self):
        poster = self.api.get(f"{BASE}/?kind=POSTER").json()
        self.assertTrue(all(s["usable"] for s in poster["styles"]))
        shot = self.api.get(f"{BASE}/?kind=PRODUCT_SHOT").json()
        self.assertEqual(sum(1 for s in shot["styles"] if s["usable"]), sum(1 for v in library.STYLES.values() if v["product_safe"]))
        self.assertTrue(all(s["usable"] == s["product_safe"] for s in shot["styles"]))
        self.assertIn("پوستر", shot["refusal_example_fa"])
        bad = self.api.get(f"{BASE}/?kind=NOPE")
        self.assertEqual(bad.status_code, 400)

    def test_detail_has_prompts_and_per_kind_verdicts(self):
        d = self.api.get(f"{BASE}/anime_90s_cel/").json()
        self.assertTrue(d["image_positive"] and d["image_negative"] and d["video_positive"] and d["scene_fragments"] is not None)
        self.assertEqual(d["kinds"]["POSTER"], {"ok": True})
        self.assertFalse(d["kinds"]["PRODUCT_SHOT"]["ok"])
        self.assertEqual(d["kinds"]["PRODUCT_SHOT"]["code"], "look_changes_product")
        self.assertIn(d["name_fa"], d["kinds"]["PRODUCT_SHOT"]["message_fa"])
        self.assertEqual(self.api.get(f"{BASE}/nope/").status_code, 404)

    def test_themes_endpoints(self):
        t = self.api.get(f"{BASE}/themes/").json()["themes"]
        self.assertEqual(len(t), 24)
        d = self.api.get(f"{BASE}/themes/{t[0]['key']}/").json()
        self.assertEqual(set(d["roles"]), set(schema.PALETTE_ROLES))
        self.assertTrue(d["prompt_fragment"])
        self.assertEqual(self.api.get(f"{BASE}/themes/nope/").status_code, 404)

    def test_login_is_required_for_data_but_not_for_swatches(self):
        anon = APIClient()
        self.assertIn(anon.get(f"{BASE}/").status_code, (401, 403))
        self.assertIn(anon.post(f"{BASE}/compose/", {"look": "noir_bw"}, format="json").status_code, (401, 403))
        r = anon.get(f"{BASE}/pixel_art_16bit/preview.svg")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("image/svg+xml"))
        self.assertIn("public", r["Cache-Control"])
        self.assertEqual(ET.fromstring(r.content).tag.split("}")[-1], "svg")
        self.assertEqual(anon.get(f"{BASE}/nope/preview.svg").status_code, 404)

    def test_every_look_has_a_served_swatch(self):
        anon = APIClient()
        for key in library.STYLES:
            r = anon.get(f"{BASE}/{key}/preview.svg")
            self.assertEqual(r.status_code, 200, key)
            self.assertTrue(r.content.startswith(b"<svg"), key)

    def test_any_store_member_reads_without_write_permission(self):
        viewer = User.objects.create_user("looks-viewer", password="x")
        Membership.objects.create(store=self.store, user=viewer, role=Membership.Role.VIEWER)
        c = APIClient()
        c.force_authenticate(viewer)
        self.assertEqual(c.get(f"{BASE}/").status_code, 200)
        self.assertEqual(c.get(f"{BASE}/suggest/?store={self.store.pk}").status_code, 200)
        stranger = User.objects.create_user("looks-stranger", password="x")
        s = APIClient()
        s.force_authenticate(stranger)
        self.assertEqual(s.get(f"{BASE}/").status_code, 200, "کتابخانه برای هر کاربرِ واردشده خواندنی است")
        self.assertEqual(s.get(f"{BASE}/suggest/?store={self.store.pk}").status_code, 404, "فروشگاهِ دیگران پیدا نمی‌شود")
        self.assertEqual(s.post(f"{BASE}/compose/", {"look": "noir_bw", "kind": "POSTER", "store": self.store.pk}, format="json").status_code, 404)


class ComposeCheckSuggestTests(LooksApiBase):
    def test_compose_for_a_poster_and_for_a_safe_product_shot(self):
        r = self.api.post(f"{BASE}/compose/", {"look": "anime_90s_cel", "kind": "POSTER", "theme": "warm_sunset", "store": self.store.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        c = r.json()
        self.assertTrue(c["positive"] and c["negative"] and c["palette"] and not c["scene_only"])
        self.assertEqual(c["brand_colors"], ["#126F85", "#163F75"])
        r = self.api.post(f"{BASE}/compose/", {"look": "noir_bw", "kind": "PRODUCT_SHOT"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["scene_only"])

    def test_an_illustrated_look_on_a_product_preserving_kind_is_refused_in_persian(self):
        for kind in ("PRODUCT_SHOT", "ENHANCED"):
            r = self.api.post(f"{BASE}/compose/", {"look": "claymation_stopmotion", "kind": kind}, format="json")
            self.assertEqual(r.status_code, 400)
            err = r.json()["error"]
            self.assertEqual(err["code"], "look_changes_product")
            self.assertIn("پوستر", err["message"])
            self.assertIn(library.STYLES["claymation_stopmotion"]["name_fa"], err["message"])
            c = self.api.get(f"{BASE}/check/?look=claymation_stopmotion&kind={kind}").json()
            self.assertEqual((c["ok"], c["code"]), (False, "look_changes_product"))
        self.assertEqual(self.api.get(f"{BASE}/check/?look=claymation_stopmotion&kind=POSTER").json(), {"ok": True})

    def test_bad_input(self):
        self.assertEqual(self.api.post(f"{BASE}/compose/", {"look": "nope", "kind": "POSTER"}, format="json").json()["error"]["code"], "unknown_look")
        self.assertEqual(self.api.post(f"{BASE}/compose/", {"look": "noir_bw", "kind": "X"}, format="json").json()["error"]["code"], "bad_kind")
        self.assertEqual(self.api.post(f"{BASE}/compose/", {"look": "noir_bw", "kind": "POSTER", "theme": "zzz"}, format="json").json()["error"]["code"], "unknown_theme")
        self.assertEqual(self.api.get(f"{BASE}/check/?look=nope&kind=POSTER").status_code, 404)

    def test_suggest_uses_only_the_stores_own_profile(self):
        s = self.api.get(f"{BASE}/suggest/?store={self.store.pk}").json()
        self.assertTrue(s["matched"])
        self.assertEqual(s["looks"][0]["business"], "fashion")
        self.assertTrue(all(x["reason_fa"] for x in s["looks"]))
        self.assertEqual(self.api.get(f"{BASE}/suggest/").status_code, 400)


class SamplesApiTests(LooksApiBase):
    def test_sample_image_is_404_until_made_then_served_and_listed(self):
        anon = APIClient()
        self.assertEqual(anon.get(f"{BASE}/noir_bw/sample.jpg").status_code, 404)
        from PIL import Image

        samples.root().mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (120, 80, 40)).save(samples.root() / "noir_bw.jpg", "JPEG")
        samples.save_index({"noir_bw": {"file": "noir_bw.jpg", "hash": samples.prompt_hash("noir_bw")}})
        r = anon.get(f"{BASE}/noir_bw/sample.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(anon.get(f"{BASE}/nope/sample.jpg").status_code, 404)
        body = self.api.get(f"{BASE}/").json()
        row = next(s for s in body["styles"] if s["key"] == "noir_bw")
        self.assertTrue(row["sample_url"].startswith(f"{BASE}/noir_bw/sample.jpg?v="))
        self.assertEqual(body["samples"]["done"], 1)

    def test_samples_status_and_manual_queue_is_for_staff_only(self):
        st = self.api.get(f"{BASE}/samples/").json()
        self.assertEqual((st["total"], st["done"], st["pending"]), (116, 0, 116))
        self.assertFalse(st["possible"])
        self.assertTrue(st["message"])
        self.assertEqual(st["selftest"]["state"], "none")
        self.assertEqual(self.api.post(f"{BASE}/samples/", {}, format="json").status_code, 403)
        staff = User.objects.create_user("looks-staff", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        r = c.post(f"{BASE}/samples/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)               # هیچ گرهٔ ComfyUI ثبت نیست ⇒ صفِ خالی با علتِ فارسی
        self.assertEqual(r.json()["queued"], [])
        self.assertTrue(r.json()["skipped"])
