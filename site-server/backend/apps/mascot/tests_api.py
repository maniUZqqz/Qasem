"""API ِ ماسکوت: ساخت از نقش و رنگ‌های برند، قفل و نسخه، پیش‌نمایش، رندرِ کَش‌دار (۴ اندازه)، استیکر، برگهٔ مدل، بررسیِ ثبات، نگهبانِ ادعا، دسترسی،
ثبت در کتابخانهٔ ادیتورِ عکس، و کارکردن بدونِ هوش مصنوعی/گره/شبکه."""
import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.photoedit.models import PhotoAsset
from apps.stores.models import Membership, Store

from . import selftest
from .engine import compose, copy_guard, poses, scenes
from .models import Mascot, MascotRender

User = get_user_model()


class MascotApiBase(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmmascot-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmmascot-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("mascot-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", target_audience="مربی‌های باشگاه", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/mascot"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def create(self, **kw):
        r = self.api.post(f"{self.base}/", {"role": "coach", "use_logo": False, **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def render(self, mid, **kw):
        body = {"pose": "thumbs_up", "expression": "happy", "background": "brand", "size": "ig_square", **kw}
        return self.api.post(f"{self.base}/{mid}/render/", body, format="json")


class OverviewAndCreateTests(MascotApiBase):
    def test_overview_lists_everything_the_page_needs(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual({x["key"] for x in b["roles"]}, {"coach", "shopkeeper", "cook", "courier", "advisor"})
        o = b["options"]
        self.assertGreaterEqual(len([p for p in o["poses"] if p["original"]]), 24)
        self.assertEqual(len(o["poses"]), len(poses.POSES))
        self.assertEqual(len(o["expressions"]), 8)
        self.assertEqual(len(o["backgrounds"]), 17)
        self.assertEqual([s["key"] for s in o["sizes"]], ["ig_portrait", "ig_square", "story", "wide"])
        self.assertEqual({t["key"] for t in o["pose_tags"]} >= {"explain", "point", "thumbs_up", "thinking", "cheer", "warn", "exercise"}, True)
        self.assertEqual(b["store"]["colors"], ["#126f85", "#163f75"])
        self.assertFalse(b["store"]["has_logo"])
        self.assertIn("با چغر چغر تر شو", [x["text"] for x in b["lines"]])
        self.assertEqual(b["mascots"], [])
        self.assertTrue(b["notes"])

    def test_create_from_a_role_takes_the_brand_colours(self):
        m = self.create(name="مربی چغر")
        self.assertEqual((m["name"], m["role"], m["role_fa"], m["version"], m["locked"]), ("مربی چغر", "coach", "مربی", 0, False))
        self.assertEqual(m["spec"]["hat"], "headband")
        self.assertEqual(m["spec"]["hat_colour"], "#126f85")
        self.assertEqual(m["spec"]["logo"], "none")                                       # این فروشگاه لوگو ندارد
        self.assertTrue({"limbs", "head", "outline", "hat"} <= {p["role"] for p in m["palette"]})
        self.assertIn("teal headband", m["anchor"])
        self.assertEqual(Mascot.objects.count(), 1)
        ov = self.api.get(f"{self.base}/").json()
        self.assertEqual(ov["mascots"][0]["id"], m["id"])

    def test_unknown_role_falls_back_and_the_limit_is_enforced(self):
        self.assertEqual(self.create(role="zzz")["role"], "coach")
        for _ in range(7):
            self.create()
        r = self.api.post(f"{self.base}/", {"role": "cook"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("حداکثر", r.json()["error"]["message"])

    def test_chest_logo_needs_a_store_logo(self):
        with mock.patch("apps.mascot.services.store_logo", return_value=selftest.synthetic_logo()):
            m = self.api.post(f"{self.base}/", {"role": "coach", "use_logo": True}, format="json").json()
        self.assertEqual(m["spec"]["logo"], "chest")
        self.assertTrue(m["has_logo"])
        r = self.api.patch(f"{self.base}/{m['id']}/", {"spec": {"logo": "chest"}}, format="json")      # حالا لوگو در دسترس نیست
        self.assertEqual(r.json()["spec"]["logo"], "none")


class AccessTests(MascotApiBase):
    def test_roles(self):
        m = self.create()
        viewer = User.objects.create_user("v", password="x")
        Membership.objects.create(store=self.store, user=viewer, role="VIEWER")
        marketer = User.objects.create_user("mk", password="x")
        Membership.objects.create(store=self.store, user=marketer, role="MARKETING")
        support = User.objects.create_user("sp", password="x")
        Membership.objects.create(store=self.store, user=support, role="SUPPORT")
        stranger = User.objects.create_user("st", password="x")
        c = APIClient()
        c.force_authenticate(viewer)
        self.assertEqual(c.get(f"{self.base}/").status_code, 200)                                         # بازدیدکننده می‌بیند
        self.assertEqual(c.get(f"{self.base}/{m['id']}/shots/").status_code, 200)
        self.assertEqual(c.post(f"{self.base}/", {"role": "cook"}, format="json").status_code, 403)       # ولی نمی‌سازد
        self.assertEqual(c.post(f"{self.base}/{m['id']}/render/", {}, format="json").status_code, 403)
        self.assertEqual(c.post(f"{self.base}/{m['id']}/lock/").status_code, 403)
        c.force_authenticate(marketer)
        self.assertEqual(c.post(f"{self.base}/", {"role": "cook", "use_logo": False}, format="json").status_code, 201)   # بازاریابی می‌سازد
        c.force_authenticate(support)
        self.assertEqual(c.get(f"{self.base}/").status_code, 403)                                         # پشتیبانی به محتوا دسترسی ندارد
        c.force_authenticate(stranger)
        self.assertEqual(c.get(f"{self.base}/").status_code, 404)
        c.force_authenticate(None)
        self.assertIn(c.get(f"{self.base}/").status_code, (401, 403))

    def test_another_stores_mascot_is_not_reachable(self):
        m = self.create()
        other_owner = User.objects.create_user("o2", password="x")
        other = Store.objects.create(owner=other_owner, name="دیگری")
        c = APIClient()
        c.force_authenticate(other_owner)
        self.assertEqual(c.get(f"/api/v1/stores/{other.pk}/mascot/{m['id']}/").status_code, 404)
        self.assertEqual(c.post(f"/api/v1/stores/{other.pk}/mascot/{m['id']}/render/", {}, format="json").status_code, 404)


class LockAndVersionTests(MascotApiBase):
    def test_lock_bumps_the_version_and_freezes_the_look(self):
        m = self.create()
        mid = m["id"]
        r = self.api.patch(f"{self.base}/{mid}/", {"name": "مربیِ ما", "spec": {"hat": "cap", "hat_colour": "#d94a3d"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["name"], r.json()["spec"]["hat"], r.json()["spec"]["hat_colour"]), ("مربیِ ما", "cap", "#d94a3d"))
        locked = self.api.post(f"{self.base}/{mid}/lock/").json()
        self.assertEqual((locked["locked"], locked["version"]), (True, 1))
        again = self.api.post(f"{self.base}/{mid}/lock/").json()
        self.assertEqual(again["version"], 1)                                                              # قفلِ دوباره نسخه را بالا نمی‌برد
        r = self.api.patch(f"{self.base}/{mid}/", {"spec": {"hat": "beanie"}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("قفل", r.json()["error"]["message"])
        self.assertEqual(self.api.get(f"{self.base}/{mid}/").json()["spec"]["hat"], "cap")
        self.assertFalse(self.api.post(f"{self.base}/{mid}/unlock/").json()["locked"])
        self.api.patch(f"{self.base}/{mid}/", {"spec": {"hat": "beanie"}}, format="json")
        self.assertEqual(self.api.post(f"{self.base}/{mid}/lock/").json()["version"], 2)

    def test_the_version_is_part_of_every_renders_key(self):
        m = self.create()
        mid = m["id"]
        first = self.render(mid).json()
        self.assertEqual((first["version"], first["locked"]), (0, False))
        self.api.post(f"{self.base}/{mid}/lock/")
        second = self.render(mid).json()                                                                   # همان گزینه‌ها، نسخهٔ تازه ⇒ تصویرِ تازه
        self.assertEqual((second["version"], second["locked"], second["cached"]), (1, True, False))
        self.assertNotEqual(first["id"], second["id"])
        third = self.render(mid)
        self.assertEqual((third.status_code, third.json()["id"], third.json()["cached"]), (200, second["id"], True))
        self.api.post(f"{self.base}/{mid}/unlock/")
        self.api.patch(f"{self.base}/{mid}/", {"spec": {"hat_colour": "#e8a22b"}}, format="json")
        self.api.post(f"{self.base}/{mid}/lock/")
        fourth = self.render(mid).json()                                                                   # ظاهر عوض شده ⇒ باز هم تصویرِ تازه
        self.assertEqual(fourth["version"], 2)
        self.assertEqual(MascotRender.objects.filter(mascot_id=mid, kind="shot").count(), 3)


class RenderTests(MascotApiBase):
    def test_render_is_cached_and_registered_in_the_photo_library(self):
        m = self.create()
        r1 = self.render(m["id"], bubble={"text": "با چغر چغر تر شو", "kind": "say"})
        self.assertEqual(r1.status_code, 201, r1.content)
        b1 = r1.json()
        self.assertFalse(b1["cached"])
        self.assertEqual((b1["width"], b1["height"], b1["kind"]), (1080, 1080, "shot"))
        self.assertTrue(b1["qa"]["ok"])
        self.assertEqual(b1["qa"]["score"], 1.0)
        self.assertTrue(b1["urls"]["png"].endswith(".png"))
        a = PhotoAsset.objects.get(pk=b1["asset"]["id"])
        self.assertEqual((a.store_id, a.source_kind, a.width, a.height), (self.store.pk, "generated", 1080, 1080))
        self.assertTrue(a.source_ref.startswith("mascot:"))
        self.assertTrue((self.media / a.original).is_file())
        with Image.open(self.media / a.original) as im:
            self.assertEqual(im.size, (1080, 1080))
        r2 = self.render(m["id"], bubble={"text": "با چغر چغر تر شو", "kind": "say"})
        self.assertEqual((r2.status_code, r2.json()["id"], r2.json()["cached"]), (200, b1["id"], True))
        self.assertEqual(PhotoAsset.objects.count(), 1)
        self.assertEqual(MascotRender.objects.count(), 1)
        r3 = self.render(m["id"], bubble={"text": "سلام!", "kind": "say"})                                  # متنِ دیگر ⇒ تصویرِ دیگر
        self.assertNotEqual(r3.json()["id"], b1["id"])

    def test_all_four_sizes_and_every_pose_family(self):
        m = self.create()
        for size, (w, h) in {"ig_portrait": (1080, 1350), "ig_square": (1080, 1080), "story": (1080, 1920), "wide": (1920, 1080)}.items():
            b = self.render(m["id"], size=size, pose="point_up").json()
            self.assertEqual((b["width"], b["height"]), (w, h), size)
            self.assertEqual(b["params"]["size"], size)
        for pose in ("thumbs_up", "stop", "curl", "lift", "squat", "wave", "think", "cheer"):
            r = self.render(m["id"], pose=pose, size="ig_square")
            self.assertIn(r.status_code, (200, 201), (pose, r.content))
            self.assertTrue(r.json()["qa"]["ok"], (pose, r.json()["qa"]))

    def test_every_background_and_a_custom_colour(self):
        m = self.create()
        for key in scenes.keys():
            self.assertIn(self.render(m["id"], background=key, size="ig_portrait", pose="wave").status_code, (200, 201), key)
        r = self.render(m["id"], background="#336699", pose="stand")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["params"]["background"], "#336699")

    def test_bad_options_are_refused_in_persian(self):
        m = self.create()
        for key, val, msg in (("size", "huge", "اندازه"), ("pose", "dance", "ژست"), ("expression", "evil", "حالت"), ("background", "mars", "پس‌زمینه"), ("prop", "gun", "وسیله")):
            r = self.render(m["id"], **{key: val})
            self.assertEqual(r.status_code, 400, key)
            self.assertIn(msg, r.json()["error"]["message"])

    def test_works_with_no_ai_no_node_and_no_network(self):
        """متیس اعتبار ندارد و گرهٔ پردازش خاموش است؛ ماسکوت هیچ‌جا به هوش مصنوعی، گره یا شبکه نیاز ندارد."""
        from apps.compute.models import ComputeJob

        m = self.create()

        def no_net(*a, **k):
            raise AssertionError("the mascot must not open a network connection")

        with mock.patch("socket.socket.connect", no_net), mock.patch("socket.create_connection", no_net):
            r = self.render(m["id"], bubble={"text": "سلام!"})
            s = self.api.post(f"{self.base}/{m['id']}/sticker/", {"pose": "thumbs_up"}, format="json")
        self.assertEqual((r.status_code, s.status_code), (201, 201))
        self.assertEqual(ComputeJob.objects.count(), 0)

    def test_a_render_whose_library_photo_was_deleted_is_made_again(self):
        m = self.create()
        first = self.render(m["id"]).json()
        PhotoAsset.objects.filter(pk=first["asset"]["id"]).delete()
        again = self.render(m["id"])
        self.assertEqual((again.status_code, again.json()["cached"]), (201, False))
        self.assertTrue(PhotoAsset.objects.filter(pk=again.json()["asset"]["id"]).exists())


class ClaimGuardTests(MascotApiBase):
    def test_price_statistics_results_testimonials_and_medical_claims_are_refused(self):
        m = self.create()
        for t, code in (("فقط ۵۰۰ هزار تومان", "price"), ("۹۸٪ رضایت", "statistic"), ("نتیجه تضمینی", "result_claim"), ("مشتری‌های ما می‌گویند عالیه", "testimonial"),
                        ("درمان کمردرد", "medical")):
            r = self.render(m["id"], bubble={"text": t})
            self.assertEqual(r.status_code, 422, t)
            err = r.json()["error"]
            self.assertEqual(err["code"], "claims")
            self.assertIn(code, [f["code"] for f in err["found"]])
            self.assertIn("خودم تأیید", err["message"])
        r = self.render(m["id"], caption={"text": "تخفیف ۳۰ درصدی", "position": "top"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(MascotRender.objects.count(), 0)                                                  # هیچ تصویری ساخته نشد

    def test_confirming_the_claim_makes_it_and_records_the_confirmation(self):
        m = self.create()
        r = self.render(m["id"], bubble={"text": "۵۰۰ هزار تومان"}, allow_claims=True)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["params"]["claims_confirmed"])
        ok = self.render(m["id"], bubble={"text": "پیش‌نویسِ برنامه در کمتر از یک دقیقه"}).json()
        self.assertFalse(ok["params"]["claims_confirmed"])

    def test_the_suggested_lines_can_all_be_used_as_they_are(self):
        m = self.create()
        for row in self.api.get(f"{self.base}/").json()["lines"][:5]:
            self.assertEqual(self.render(m["id"], bubble={"text": row["text"]}, pose="stand").status_code, 201, row["text"])

    def test_preview_warns_before_anything_is_made(self):
        m = self.create()
        p = self.api.post(f"{self.base}/{m['id']}/preview/", {"pose": "wave", "bubble": {"text": "۹۸٪ رضایت"}}, format="json").json()
        self.assertEqual([c["code"] for c in p["claims"]], ["statistic"])
        self.assertTrue(p["claims_message"])


class PreviewStickerSheetTests(MascotApiBase):
    def test_preview_is_fast_unsaved_and_can_try_an_unsaved_look(self):
        m = self.create()
        mid = m["id"]
        p = self.api.post(f"{self.base}/{mid}/preview/", {"pose": "wave", "size": "ig_portrait", "background": "gym"}, format="json")
        self.assertEqual(p.status_code, 200, p.content)
        b = p.json()
        self.assertTrue(b["image"].startswith("data:image/jpeg;base64,"))
        self.assertEqual((b["width"], b["height"]), (round(1080 * 0.42), round(1350 * 0.42)))
        self.assertTrue(b["qa"]["ok"])
        other = self.api.post(f"{self.base}/{mid}/preview/", {"pose": "wave", "size": "ig_portrait", "background": "gym", "spec": {"hat_colour": "#8a4fd1", "hat": "cap"}}, format="json").json()
        self.assertNotEqual(other["image"], b["image"])
        self.assertEqual(Mascot.objects.get(pk=mid).spec["hat"], "headband")                                  # چیزی ذخیره نشد
        self.assertEqual((MascotRender.objects.count(), PhotoAsset.objects.count()), (0, 0))

    def test_sticker_is_a_transparent_png_in_the_library(self):
        m = self.create()
        r = self.api.post(f"{self.base}/{m['id']}/sticker/", {"pose": "thumbs_up", "crop": "bust"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        b = r.json()
        self.assertEqual(b["kind"], "sticker")
        a = PhotoAsset.objects.get(pk=b["asset"]["id"])
        self.assertTrue(a.has_alpha)
        self.assertTrue(b["asset"]["has_alpha"])
        with Image.open(self.media / a.original) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.getchannel("A").getpixel((0, 0)), 0)
        again = self.api.post(f"{self.base}/{m['id']}/sticker/", {"pose": "thumbs_up", "crop": "bust"}, format="json")
        self.assertEqual((again.status_code, again.json()["id"]), (200, b["id"]))
        full = self.api.post(f"{self.base}/{m['id']}/sticker/", {"pose": "thumbs_up"}, format="json").json()
        self.assertNotEqual(full["id"], b["id"])
        self.assertTrue(full["qa"]["ok"])
        self.assertEqual(self.api.post(f"{self.base}/{m['id']}/sticker/", {"pose": "dance"}, format="json").status_code, 400)

    def test_model_sheet(self):
        m = self.create(name="مربی چغر")
        r = self.api.post(f"{self.base}/{m['id']}/sheet/", format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["width"], r.json()["height"], r.json()["kind"]), (2000, 1600, "sheet"))
        self.assertEqual(self.api.post(f"{self.base}/{m['id']}/sheet/", format="json").json()["cached"], True)

    def test_consistency_check_covers_every_pose_in_four_sizes_and_is_remembered(self):
        m = self.create()
        with mock.patch.object(selftest, "grid", wraps=selftest.grid) as spy:
            r = self.api.post(f"{self.base}/{m['id']}/check/", format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertTrue(b["ok"], b)
        self.assertEqual((b["poses"], b["sizes"], b["total"], b["passed"]), (len(poses.POSES), 4, len(poses.POSES) * 4, len(poses.POSES) * 4))
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.api.get(f"{self.base}/{m['id']}/").json()["check"]["ok"], True)
        self.api.patch(f"{self.base}/{m['id']}/", {"spec": {"hat_colour": "#8a4fd1"}}, format="json")
        self.assertEqual(self.api.get(f"{self.base}/{m['id']}/").json()["check"], {})                        # ظاهر عوض شد ⇒ بررسی باید دوباره انجام شود


class ShotsTests(MascotApiBase):
    def test_list_get_download_delete(self):
        m = self.create()
        mid = m["id"]
        a = self.render(mid, pose="wave").json()
        b = self.api.post(f"{self.base}/{mid}/sticker/", {}, format="json").json()
        lst = self.api.get(f"{self.base}/{mid}/shots/").json()["items"]
        self.assertEqual([x["id"] for x in lst], [b["id"], a["id"]])
        self.assertEqual([x["id"] for x in self.api.get(f"{self.base}/{mid}/shots/?kind=sticker").json()["items"]], [b["id"]])
        self.assertEqual(self.api.get(f"{self.base}/{mid}/shots/{a['id']}/").json()["params"]["pose"], "wave")
        d = self.api.get(f"{self.base}/{mid}/shots/{a['id']}/download/")
        self.assertEqual(d.status_code, 200)
        self.assertIn("attachment", d["Content-Disposition"])
        body = b"".join(d.streaming_content)
        self.assertEqual(Image.open(io.BytesIO(body)).size, (1080, 1080))
        self.assertEqual(self.api.delete(f"{self.base}/{mid}/shots/{a['id']}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/{mid}/shots/{a['id']}/").status_code, 404)
        self.assertTrue(PhotoAsset.objects.filter(pk=a["asset"]["id"]).exists())                           # عکسِ کتابخانه می‌ماند

    def test_deleting_the_mascot_keeps_the_library_photos(self):
        m = self.create()
        a = self.render(m["id"]).json()
        self.assertEqual(self.api.delete(f"{self.base}/{m['id']}/").status_code, 204)
        self.assertEqual((Mascot.objects.count(), MascotRender.objects.count()), (0, 0))
        self.assertTrue(PhotoAsset.objects.filter(pk=a["asset"]["id"]).exists())
        self.assertEqual(self.api.get(f"{self.base}/{m['id']}/").status_code, 404)

    def test_renders_are_pruned(self):
        from . import services

        m = self.create()
        with mock.patch.object(services, "MAX_RENDERS", 3):
            for i in range(5):
                self.render(m["id"], bubble={"text": f"جمله {i}"}, size="ig_square")
        self.assertEqual(MascotRender.objects.filter(mascot_id=m["id"]).count(), 3)


class GuardUnitTests(TestCase):
    def test_confirmed_claims_are_not_blocked_by_the_service(self):
        from . import services

        opts = services.clean_options({"bubble": {"text": "۹۸٪"}, "allow_claims": True})
        services.check_claims(opts)                                                                         # خطا نمی‌دهد
        with self.assertRaises(services.ClaimsError):
            services.check_claims(services.clean_options({"bubble": {"text": "۹۸٪"}}))
        self.assertEqual(copy_guard.check_text(""), [])
        self.assertEqual(compose.size_of("nope"), (1080, 1350))
