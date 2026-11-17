"""رفعِ ایرادهای دورِ دومِ بازبینی (۱۱/۱۷) برای «شخصیتِ برند»:

* نشانیِ دانلودِ هر خروجی (urls.download) از همان مسیری برمی‌آید که کلاینتِ پنل با پیشوندِ /api/v1 صدا می‌زند؛ سرور نشانیِ کامل می‌دهد و پنل پیشوند را می‌بُرد
  (بدونِ برش «/api/v1/api/v1/...» و ۴۰۴ می‌شد) ⇒ این‌جا نشانیِ بُریده‌شده باید با خودِ APIClient (که پیشوند را خودش نمی‌گذارد) دانلود شود؛
* کارتِ ایده وقتی وسیله دارد با ژستی نشان داده می‌شود که وسیله را در دست دارد (ژستِ «سلام» دستِ خالی است)؛
* «کارت»ِ هر شخصیت نیم‌تنهٔ شفافِ پایدار است و با پست/قالب/برگه عوض نمی‌شود؛ با ویرایش کهنه می‌شود و دوباره ساخته می‌شود.
"""
import re

from . import concepts
from .engine import doc as D
from .engine import render as R
from .tests_api import Base


def pay_path(url: str) -> str:
    """همان کاری که apiPath در پنل می‌کند، تا دقیقاً همان مسیری آزموده شود که مرورگر می‌زند."""
    return re.sub(r"^(?:https?://[^/]+)?/api/v1(?=/)", "", url)


class DownloadUrls(Base):
    def test_every_render_kind_downloads_through_its_urls_download(self):
        c = self.make()
        cid = c["id"]
        outs = {
            "sticker": self.api.post(f"{self.base}/characters/{cid}/sticker/", {"pose": "wave", "crop": "bust"}, format="json"),
            "sheet": self.api.post(f"{self.base}/characters/{cid}/sheet/", {}, format="json"),
            "pdf": self.api.post(f"{self.base}/characters/{cid}/sheet-pdf/", {}, format="json"),
            "svg": self.api.post(f"{self.base}/characters/{cid}/svg-file/", {"pose": "stand"}, format="json"),
            "shot": self.api.post(f"{self.base}/characters/{cid}/render/", {"pose": "wave", "size": "ig_square"}, format="json"),
        }
        for kind, r in outs.items():
            with self.subTest(kind=kind):
                self.assertIn(r.status_code, (200, 201), r.content)
                url = r.json()["urls"]["download"]
                self.assertTrue(url.startswith("/api/v1/stores/"), url)
                # مرورگر: baseURL=/api/v1 + مسیرِ بُریده‌شده ⇒ دوباره همان نشانی؛ نه /api/v1/api/v1
                self.assertEqual("/api/v1" + pay_path(url), url)
                self.assertNotIn("/api/v1/api/v1", "/api/v1" + pay_path(url))
                dl = self.api.get(url)
                self.assertEqual(dl.status_code, 200, (kind, url))
                body = b"".join(dl.streaming_content) if getattr(dl, "streaming", False) else dl.content
                self.assertGreater(len(body), 200)

    def test_doubled_prefix_is_a_404_so_the_strip_is_needed(self):
        c = self.make()
        r = self.api.post(f"{self.base}/characters/{c['id']}/sticker/", {"pose": "wave"}, format="json")
        url = r.json()["urls"]["download"]
        self.assertEqual(self.api.get("/api/v1" + url).status_code, 404)


class ConceptPreviewShowsTheProp(Base):
    def test_preview_pose_holds_the_prop(self):
        self.assertEqual(concepts.preview_pose({"prop": "dumbbell"}), "stand")
        self.assertEqual(concepts.preview_pose({"prop": "none"}), "wave")
        self.assertEqual(concepts.preview_pose({}), "wave")

    def test_a_dumbbell_concept_really_draws_the_dumbbell(self):
        doc = D.normalize({"name": "مربی", **D.role_look("coach"), "prop": "dumbbell"})
        _img, info = R.sticker(doc, pose=concepts.preview_pose(doc), expression="happy", height_px=420)
        self.assertEqual(info["prop"], "dumbbell")
        _img, info = R.sticker(doc, pose="wave", expression="happy", height_px=420)
        self.assertEqual(info["prop"], "none", "سلام دستِ خالی است؛ برای همین کارتِ ایده نباید با سلام نشان داده شود")

    def test_concept_items_name_the_prop_in_persian(self):
        r = self.api.post(f"{self.base}/concepts/", {"description": "مربیِ خندانِ موبلند با هدبندِ فیروزه‌ای و دمبل"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        for o in r.json()["options"]:
            self.assertEqual(o["prop"], "dumbbell")
            self.assertEqual(o["prop_fa"], "دمبل")
            self.assertTrue(o["preview"].startswith("data:image/png;base64,"))
        r2 = self.api.post(f"{self.base}/concepts/", {"description": "فروشندهٔ خندان با کلاه"}, format="json")
        plain = [o for o in r2.json()["options"] if o["prop"] == "none"]
        self.assertTrue(plain)
        self.assertEqual(plain[0]["prop_fa"], "")


class StableCover(Base):
    def cover(self, cid):
        return self.api.get(f"{self.base}/characters/{cid}/").json()

    def test_cover_is_the_clean_bust_not_the_newest_render(self):
        cid = self.make()["id"]
        self.assertEqual(self.cover(cid)["cover_kind"], "")
        self.assertIsNone(self.cover(cid)["cover"])
        # فقط یک پستِ پرتزئین ⇒ هنوز «کارتِ پایدار» نیست
        self.assertEqual(self.api.post(f"{self.base}/characters/{cid}/render/", {"pose": "wave", "size": "ig_square", "bubble": {"text": "سلام"}}, format="json").status_code, 201)
        self.assertEqual(self.cover(cid)["cover_kind"], "other")
        r = self.api.post(f"{self.base}/characters/{cid}/cover/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        first = r.json()
        self.assertEqual(first["cover_kind"], "bust")
        self.assertTrue(first["cover"])
        # بعد از رندرِ قالب و پستِ تازه کارت همان می‌ماند
        self.assertEqual(self.api.post(f"{self.base}/characters/{cid}/render/", {"pose": "point_up", "size": "story"}, format="json").status_code, 201)
        self.api.post(f"{self.base}/characters/{cid}/sheet/", {}, format="json")
        again = self.cover(cid)
        self.assertEqual(again["cover_kind"], "bust")
        self.assertEqual(again["cover"], first["cover"])

    def test_cover_goes_stale_after_an_edit_and_is_rebuilt(self):
        cid = self.make()["id"]
        first = self.api.post(f"{self.base}/characters/{cid}/cover/", {}, format="json").json()
        self.assertEqual(first["cover_kind"], "bust")
        r = self.api.patch(f"{self.base}/characters/{cid}/", {"doc": {"top": "#d94a3d"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotEqual(self.cover(cid)["cover_kind"], "bust")
        fresh = self.api.post(f"{self.base}/characters/{cid}/cover/", {}, format="json").json()
        self.assertEqual(fresh["cover_kind"], "bust")
        self.assertNotEqual(fresh["cover"], first["cover"])

    def test_cover_endpoint_is_cached_and_refused_for_strangers(self):
        cid = self.make()["id"]
        a = self.api.post(f"{self.base}/characters/{cid}/cover/", {}, format="json").json()
        b = self.api.post(f"{self.base}/characters/{cid}/cover/", {}, format="json").json()
        self.assertEqual(a["cover"], b["cover"])
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        stranger = APIClient()
        stranger.force_authenticate(get_user_model().objects.create_user("bc-stranger", password="x"))
        self.assertIn(stranger.post(f"{self.base}/characters/{cid}/cover/", {}, format="json").status_code, (403, 404))

    def test_choosing_a_concept_leaves_a_bust_cover(self):
        cid = self.api.post(f"{self.base}/concepts/", {"description": "فروشندهٔ عینکی با کلاه"}, format="json").json()["id"]
        r = self.api.post(f"{self.base}/concepts/{cid}/choose/", {"index": 0}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["character"]["cover_kind"], "bust")
