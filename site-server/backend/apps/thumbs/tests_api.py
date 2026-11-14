"""API ِ تامنیل‌ساز: پیش‌نمایش، ساختِ نسخه‌های A/B، تاریخچه، ویرایش، دانلود، باز کردن در ادیتورِ عکس، فایل لایه‌دار، دسترسی."""
import base64
import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files import File
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.photoedit import psd
from apps.photoedit.models import PhotoAsset
from apps.products.models import Product, ProductImage
from apps.stores.models import Membership, Store

from . import fixtures, services
from .styles import STYLES
from . import formats as F
from .models import IdeaSet, Thumbnail

User = get_user_model()

SPEC = {"format": "youtube", "style": "face_text", "content": {"title": "*۷* اشتباهِ ورزشکارهای تازه‌کار", "subtitle": "قبل از شروع ببینید", "badge": "ویژه"}}


def png_file(img: Image.Image, name="subject.png") -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    buf.name = name
    return buf


class ThumbsApiBase(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmthumbs-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmthumbs-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("thumbs-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", target_audience="مربی‌های باشگاه", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/thumbnails"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def upload_subject(self, img=None, name="subject.png") -> int:
        r = self.api.post(f"{self.base}/library/upload/", {"files": [png_file(img or fixtures.person(), name)]}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["assets"][0]["id"]

    def render(self, spec=None, **extra):
        r = self.api.post(f"{self.base}/render/", {"spec": spec or SPEC, **extra}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()


class OverviewAndPreviewTests(ThumbsApiBase):
    def test_overview_lists_everything_the_page_needs(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual({f["key"] for f in body["formats"]}, set(F.FORMATS))
        self.assertEqual({s["key"] for s in body["styles"]}, set(STYLES))
        self.assertGreaterEqual(len(body["styles"]), 15)
        self.assertEqual(body["brand"]["colors"], ["#126f85", "#163f75"])
        self.assertEqual(body["brand"]["store_name"], "چغر")
        self.assertFalse(body["ai_background"]["possible"])            # هیچ گرهٔ ComfyUI ثبت نیست
        self.assertTrue(body["ai_background"]["message"])
        self.assertEqual(body["items"], [])
        self.assertTrue(any(f["key"] == "lalezar" for f in body["fonts"]))
        sizes = {f["key"]: (f["width"], f["height"]) for f in body["formats"]}
        self.assertEqual(sizes["story"], (1080, 1920))

    def test_preview_returns_a_small_jpeg_with_layers(self):
        r = self.api.post(f"{self.base}/preview/", {"spec": SPEC}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["image"].startswith("data:image/jpeg;base64,"))
        img = Image.open(io.BytesIO(base64.b64decode(body["image"].split(",", 1)[1])))
        self.assertEqual(img.size, F.scaled(F.get("youtube"), 720 / 1280))
        self.assertEqual(img.size[0], 720)
        self.assertTrue(any(layer["kind"] == "text" for layer in body["layers"]))
        self.assertEqual(Thumbnail.objects.count(), 0)               # پیش‌نمایش چیزی ذخیره نمی‌کند

    def test_preview_bad_input_is_a_persian_error(self):
        r = self.api.post(f"{self.base}/preview/", {"spec": {"format": "x", "style": "face_text"}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("قالب", r.json()["error"]["message"])
        r = self.api.post(f"{self.base}/preview/", {"spec": {"format": "youtube", "style": "nope"}}, format="json")
        self.assertIn("سبک", r.json()["error"]["message"])

    def test_style_sample_and_moodboard(self):
        r = self.api.get(f"{self.base}/styles/neon/sample.jpg?fmt=story")
        self.assertEqual(r.status_code, 200)
        data = b"".join(r.streaming_content)
        self.assertEqual(Image.open(io.BytesIO(data)).size[0], 560)
        self.assertEqual(self.api.get(f"{self.base}/styles/zzz/sample.jpg").status_code, 404)
        # <img src> سرآیندِ Authorization ندارد: نمونهٔ ساختگیِ سبک بدونِ ورود هم باز می‌شود (وگرنه در پنل همهٔ تصویرها ۴۰۱ می‌شد)
        anon = APIClient().get(f"{self.base}/styles/neon/sample.jpg?fmt=story&brand=1")
        self.assertEqual(anon.status_code, 200)
        self.assertEqual(anon["Content-Type"], "image/jpeg")
        self.assertEqual(APIClient().get(f"{self.base}/").status_code, 401)               # بقیهٔ API همچنان بسته است
        r = self.api.get(f"{self.base}/moodboard/")
        self.assertEqual(r.status_code, 200)
        arch = r.json()["archetypes"]
        self.assertGreaterEqual(len(arch), 10)
        self.assertIn("/styles/", arch[0]["sample"])

    def test_ideas_endpoint_without_ai(self):
        r = self.api.post(f"{self.base}/ideas/", {"topic": "برنامهٔ ورزشی", "format": "youtube", "ai": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["via"], "rules")
        self.assertGreaterEqual(len(body["ideas"]), 4)
        self.assertEqual(IdeaSet.objects.filter(store=self.store).count(), 1)
        # هوش مصنوعی روشن، ولی زیرِ آزمون در دسترس نیست ⇒ همان فرمول‌ها + پیامِ روشن
        r = self.api.post(f"{self.base}/ideas/", {"topic": "یوگا"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ai"]["tried"])
        self.assertEqual(r.json()["via"], "rules")
        self.assertEqual(self.api.post(f"{self.base}/ideas/", {"topic": ""}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/ideas/", {"topic": "a", "format": "zz"}, format="json").status_code, 400)

    def test_ideas_for_a_product(self):
        p = Product.objects.create(store=self.store, name="دمبل ۵ کیلویی", price=900_000)
        r = self.api.post(f"{self.base}/ideas/", {"product": p.pk, "format": "ig_portrait", "ai": False, "use_price": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(any("دمبل" in i["title"] for i in r.json()["ideas"]))
        self.assertEqual(self.api.post(f"{self.base}/ideas/", {"product": 99999, "ai": False}, format="json").status_code, 404)


class RenderAndHistoryTests(ThumbsApiBase):
    def test_render_three_variants_and_history(self):
        sid = self.upload_subject()
        spec = {**SPEC, "subject": {"asset": sid}}
        body = self.render(spec, variants=3)
        items = body["items"]
        self.assertEqual([i["variant"] for i in items], ["A", "B", "C"])
        self.assertEqual(len({i["batch"] for i in items}), 1)
        self.assertEqual(len({i["style"] for i in items}), 2)             # A و B همان سبک، C سبکِ دیگر
        for it in items:
            self.assertEqual(it["state"], "READY")
            t = Thumbnail.objects.get(pk=it["id"])
            for kind in ("png", "jpg", "thumb"):
                self.assertTrue((self.media / t.files[kind]).is_file(), kind)
            with Image.open(self.media / t.files["png"]) as im:
                self.assertEqual(im.size, (1280, 720))
            self.assertLessEqual((self.media / t.files["jpg"]).stat().st_size, 2000 * 1024)
            self.assertTrue(it["layers"])
        hist = self.api.get(f"{self.base}/items/").json()["items"]
        self.assertEqual(len(hist), 3)
        self.assertEqual(hist[0]["id"], items[-1]["id"])
        one = self.api.get(f"{self.base}/items/{items[0]['id']}/").json()
        self.assertEqual(one["spec"]["subject"]["asset"], sid)
        self.assertEqual(one["spec"]["content"]["title"], "*۷* اشتباهِ ورزشکارهای تازه‌کار")
        self.assertEqual(self.api.get(f"{self.base}/items/?before={items[1]['id']}").json()["items"][0]["id"], items[0]["id"])

    def test_every_format_gets_its_exact_size(self):
        for fmt, f in F.FORMATS.items():
            body = self.render({**SPEC, "format": fmt, "style": "minimal_luxury"})
            t = Thumbnail.objects.get(pk=body["items"][0]["id"])
            with Image.open(self.media / t.files["png"]) as im:
                self.assertEqual(im.size, f.size, fmt)

    def test_patch_rerenders_in_place_and_changes_files(self):
        body = self.render()
        item = body["items"][0]
        before = self.api.get(f"{self.base}/items/{item['id']}/").json()["urls"]["png"]
        r = self.api.patch(f"{self.base}/items/{item['id']}/", {"title": "نسخهٔ دوم", "spec": {"style": "neon", "content": {"title": "عنوانِ تازه"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        self.assertEqual(out["style"], "neon")
        self.assertEqual(out["title"], "نسخهٔ دوم")
        self.assertEqual(out["spec"]["content"]["title"], "عنوانِ تازه")
        self.assertEqual(out["spec"]["content"]["subtitle"], "قبل از شروع ببینید")      # فیلدهای دیگر دست‌نخورده
        self.assertNotEqual(out["urls"]["png"], before)
        self.assertEqual(Thumbnail.objects.count(), 1)
        self.assertEqual(self.api.patch(f"{self.base}/items/{item['id']}/", {"spec": {"style": "zzz"}}, format="json").status_code, 400)

    def test_delete_removes_files(self):
        item = self.render()["items"][0]
        t = Thumbnail.objects.get(pk=item["id"])
        folder = self.media / t.dir_rel
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.api.delete(f"{self.base}/items/{item['id']}/").status_code, 204)
        self.assertFalse(folder.exists())
        self.assertEqual(self.api.get(f"{self.base}/items/{item['id']}/").status_code, 404)

    def test_download_png_jpg_and_zip(self):
        body = self.render(variants=2)
        a = body["items"][0]
        r = self.api.get(f"{self.base}/items/{a['id']}/download/?fmt=png")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertTrue(b"".join(r.streaming_content).startswith(b"\x89PNG"))
        r = self.api.get(f"{self.base}/items/{a['id']}/download/")
        self.assertEqual(r["Content-Type"], "image/jpeg")
        r = self.api.get(f"{self.base}/batches/{body['batch']}/zip/")
        self.assertEqual(r.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertEqual(len(names), 4)
        self.assertEqual(self.api.get(f"{self.base}/batches/nothing/zip/").status_code, 404)

    def test_open_in_photo_editor_is_idempotent(self):
        item = self.render()["items"][0]
        r = self.api.post(f"{self.base}/items/{item['id']}/editor/")
        self.assertEqual(r.status_code, 201, r.content)
        aid = r.json()["asset"]["id"]
        self.assertIn(f"/photo-editor?asset={aid}", r.json()["url"])
        asset = PhotoAsset.objects.get(pk=aid)
        self.assertEqual((asset.width, asset.height), (1280, 720))
        self.assertEqual(asset.store_id, self.store.pk)
        again = self.api.post(f"{self.base}/items/{item['id']}/editor/")
        self.assertEqual(again.json()["asset"]["id"], aid)
        self.assertEqual(PhotoAsset.objects.filter(source_ref__startswith="thumb:").count(), 1)
        # بعد از ویرایش، عکسِ تازه (نه کهنه) باز می‌شود
        self.api.patch(f"{self.base}/items/{item['id']}/", {"spec": {"style": "neon"}}, format="json")
        third = self.api.post(f"{self.base}/items/{item['id']}/editor/")
        self.assertNotEqual(third.json()["asset"]["id"], aid)

    def test_layered_file_has_separate_layers(self):
        sid = self.upload_subject()
        item = self.render({**SPEC, "subject": {"asset": sid}})["items"][0]
        r = self.api.get(f"{self.base}/items/{item['id']}/layers/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.content.startswith(b"8BPS"))
        parsed = psd.read_psd(r.content)
        names = [layer["name"] for layer in parsed["layers"]]
        self.assertGreaterEqual(len(names), 6)
        self.assertIn("عنوان", names)
        self.assertIn("سوژه", names)

    def test_subject_alpha_becomes_a_cutout_layer_and_photo_mode_does_not(self):
        sid = self.upload_subject()
        t = Thumbnail.objects.get(pk=self.render({**SPEC, "subject": {"asset": sid}})["items"][0]["id"])
        self.assertIn("سوژه", [layer["name"] for layer in t.notes["layers"]])
        t2 = Thumbnail.objects.get(pk=self.render({**SPEC, "subject": {"asset": sid, "mode": "photo"}})["items"][0]["id"])
        self.assertIn("عکسِ سوژه", [layer["name"] for layer in t2.notes["layers"]])
        self.assertNotIn("سوژه", [layer["name"] for layer in t2.notes["layers"]])

    def test_missing_asset_is_a_warning_not_a_crash(self):
        body = self.render({**SPEC, "subject": {"asset": 987654}})
        self.assertEqual(body["items"][0]["state"], "READY")
        self.assertTrue(any("پیدا نشد" in w for w in body["items"][0]["warnings"]))

    def test_store_logo_and_brand_colors_are_used(self):
        logo = Path(self.media) / "logo.png"
        Image.new("RGBA", (400, 160), (20, 120, 140, 255)).save(logo)
        self.store.logo.name = "logo.png"
        self.store.save()
        item = self.render()["items"][0]
        names = [layer["name"] for layer in item["layers"]]
        self.assertTrue("لوگو" in names or "نشانِ برند" in names, names)       # بدونِ عکسِ سوژه، لوگو به‌صورتِ «نشانِ برند» در قلبِ طرح می‌آید
        self.assertEqual(item["palette"]["primary"], "#126f85")

    def test_variant_cap_and_history_cap(self):
        body = self.render(variants=99)
        self.assertEqual(len(body["items"]), 6)
        with mock.patch.object(services, "MAX_ITEMS_PER_STORE", 6):
            r = self.api.post(f"{self.base}/render/", {"spec": SPEC}, format="json")
            self.assertEqual(r.status_code, 400)
            self.assertIn("پر است", r.json()["error"]["message"])

    def test_product_photo_into_library_then_render(self):
        prod = Product.objects.create(store=self.store, name="قهوه", price=1000)
        pi = ProductImage(product=prod)
        buf = io.BytesIO()
        fixtures.scene().save(buf, "JPEG")
        buf.seek(0)
        pi.image.save("p.jpg", File(buf), save=True)
        r = self.api.post(f"{self.base}/library/import/", {"ref": f"product_image:{pi.pk}"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        aid = r.json()["asset"]["id"]
        lib = self.api.get(f"{self.base}/library/").json()["assets"]
        self.assertIn(aid, [a["id"] for a in lib])
        body = self.render({**SPEC, "style": "product_hero", "subject": {"asset": aid, "mode": "photo"}})
        self.assertEqual(body["items"][0]["state"], "READY")
        ov = self.api.get(f"{self.base}/").json()
        self.assertEqual(ov["products"][0]["image_ref"], f"product_image:{pi.pk}")
        self.assertEqual(self.api.post(f"{self.base}/library/import/", {"ref": "product_image:99999"}, format="json").status_code, 400)

    def test_upload_without_files_is_an_error(self):
        r = self.api.post(f"{self.base}/library/upload/", {}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_cutout_of_transparent_image_is_immediate(self):
        sid = self.upload_subject()
        r = self.api.post(f"{self.base}/cutout/", {"asset": sid, "model": "rvm"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["state"], "ready")
        self.assertEqual(self.api.post(f"{self.base}/cutout/", {"asset": 12345}, format="json").status_code, 404)
        self.assertEqual(self.api.post(f"{self.base}/cutout/", {"asset": sid, "model": "x"}, format="json").status_code, 400)


class AccessTests(ThumbsApiBase):
    def test_stranger_cannot_see_the_store(self):
        other = APIClient()
        other.force_authenticate(User.objects.create_user("stranger", password="x"))
        self.assertEqual(other.get(f"{self.base}/").status_code, 404)
        self.assertEqual(other.post(f"{self.base}/render/", {"spec": SPEC}, format="json").status_code, 404)

    def test_viewer_reads_but_cannot_write(self):
        v = User.objects.create_user("viewer", password="x")
        Membership.objects.create(store=self.store, user=v, role="VIEWER")
        c = APIClient()
        c.force_authenticate(v)
        self.assertEqual(c.get(f"{self.base}/").status_code, 200)
        self.assertEqual(c.post(f"{self.base}/preview/", {"spec": SPEC}, format="json").status_code, 200)
        self.assertEqual(c.post(f"{self.base}/render/", {"spec": SPEC}, format="json").status_code, 403)
        self.assertEqual(c.post(f"{self.base}/ideas/", {"topic": "x"}, format="json").status_code, 403)

    def test_content_manager_can_write(self):
        m = User.objects.create_user("cm", password="x")
        Membership.objects.create(store=self.store, user=m, role="CONTENT")
        c = APIClient()
        c.force_authenticate(m)
        self.assertEqual(c.post(f"{self.base}/render/", {"spec": SPEC}, format="json").status_code, 201)

    def test_items_of_other_stores_are_invisible(self):
        item = self.render()["items"][0]
        other_owner = User.objects.create_user("o2", password="x")
        other_store = Store.objects.create(owner=other_owner, name="دیگری")
        c = APIClient()
        c.force_authenticate(other_owner)
        self.assertEqual(c.get(f"/api/v1/stores/{other_store.pk}/thumbnails/items/{item['id']}/").status_code, 404)
        self.assertEqual(c.delete(f"/api/v1/stores/{other_store.pk}/thumbnails/items/{item['id']}/").status_code, 404)
