"""ادیتورِ عکس: کارهای سرورِ سایت روی عکسِ واقعی، API، صفِ سرورِ پردازش (بی گره ⇐ «منتظر»، با گره ⇐ آماده)،
ذخیره در محصول/محتوا/کتابخانه، zip، دسترسی."""
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image, ImageDraw
from rest_framework.test import APIClient

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.content.models import GeneratedImage
from apps.products.models import Product, ProductImage
from apps.stores.models import Store

from . import catalog, ops, services
from .models import PhotoAsset, PhotoEdit

User = get_user_model()
REAL_MEDIA = Path(settings.MEDIA_ROOT)


def photo(w=1200, h=900, *, dark=False, cast=0, alpha=False, plain=False, seed=1) -> Image.Image:
    """عکسِ ساختگیِ شبیهِ واقعی: زمینه + کالا (دایره و مستطیل) + بافت + نویز."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.full((h, w), 235.0) if plain else 120 + 70 * np.sin(xx / 97) * np.cos(yy / 71)
    a = np.stack([base, base * 0.95, base * 0.9], axis=2)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.3, h * 0.25, w * 0.62, h * 0.75], fill=(200, 40, 40))
    d.rectangle([w * 0.55, h * 0.4, w * 0.8, h * 0.85], fill=(30, 90, 170))
    arr = np.asarray(img, dtype=np.float32) + rng.normal(0, 3, (h, w, 3))
    if dark:
        arr *= 0.32
    if cast:
        arr[..., 0] += cast
        arr[..., 2] -= cast
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    if alpha:
        out = out.convert("RGBA")
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).ellipse([w * 0.2, h * 0.2, w * 0.8, h * 0.8], fill=255)
        out.putalpha(m)
    return out


def jpeg_file(img: Image.Image, name="p.jpg", fmt="JPEG") -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, fmt, quality=92)
    buf.seek(0)
    buf.name = name
    return buf


def real_photo() -> Path | None:
    """یکی از عکس‌های واقعیِ محصول‌های روی همین سرور (اگر هست)."""
    folder = REAL_MEDIA / "products" / "images"
    for p in sorted(folder.glob("*"))[:40] if folder.is_dir() else []:
        if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.stat().st_size > 20_000:
            try:
                with Image.open(p) as im:
                    if min(im.size) >= 400:
                        return p
            except Exception:  # noqa: BLE001
                continue
    return None


class ServerOpsTests(TestCase):
    """کارهای سبک روی عکس (بی پایگاه‌داده)."""

    def ctx(self, **kw):
        return {"notes": [], "store_name": "فروشگاهِ نمونه", "logo_path": lambda p: None} | kw

    def test_auto_tone_brightens_dark_and_removes_cast(self):
        dark = photo(dark=True)
        before = ops.measure(dark)
        out = ops.op_auto_tone(dark, {"strength": 100}, self.ctx())
        after = ops.measure(out)
        self.assertGreater(after["p50"], before["p50"] + 30)
        self.assertEqual(out.size, dark.size)
        self.assertIn("dark", {f["what"] for f in ops.findings(before)})
        # یک صحنهٔ خاکستری زیرِ نورِ لامپ (زرد): رنگ‌زدگی دیده و کم می‌شود
        g = np.tile(np.linspace(60, 200, 900, dtype=np.float32), (600, 1))
        warm = Image.fromarray(np.clip(np.stack([g + 22, g + 4, g - 24], axis=2), 0, 255).astype(np.uint8), "RGB")
        before = ops.measure(warm)
        self.assertIn("cast", {f["what"] for f in ops.findings(before)})
        after = ops.measure(ops.op_auto_tone(warm, {"strength": 100}, self.ctx()))
        self.assertLess(abs(after["cast_rb"]), abs(before["cast_rb"]) * 0.6)

    def test_crop_formats_have_exact_sizes(self):
        img = photo(1600, 900)
        ctx = self.ctx()
        for fmt, (w, h, _l) in catalog.SOCIAL_FORMATS.items():
            for fit in ("cover", "contain"):
                p = catalog.normalize_params("crop_format", {"format": fmt, "fit": fit})
                out = ops.op_crop_format(img, p, ctx)
                self.assertEqual(out.size, (w, h), (fmt, fit))
        # smart: the product (left-centre) stays in the square crop of a wide photo
        wide = Image.new("RGB", (2000, 800), (240, 240, 240))
        ImageDraw.Draw(wide).ellipse([200, 250, 500, 550], fill=(10, 10, 10))
        out = ops.op_crop_format(wide, catalog.normalize_params("crop_format", {"format": "square"}), ctx)
        self.assertLess(np.asarray(out.convert("L")).min(), 40, "سوژه بیرون از برش ماند")

    def test_contain_keeps_whole_photo_on_blur(self):
        img = photo(1200, 1200)
        out = ops.op_crop_format(img, catalog.normalize_params("crop_format", {"format": "story", "fit": "contain"}),
                                 self.ctx())
        self.assertEqual(out.size, (1080, 1920))
        mid = np.asarray(out)[960, 540]
        self.assertTrue((np.abs(mid.astype(int) - np.asarray(img.resize((1080, 1080)))[540, 540]) < 40).all())

    def test_text_logo_watermark_draw_something(self):
        img = photo(1080, 1080)
        out = ops.op_text(img, catalog.normalize_params("text", {"text": "تخفیفِ ویژهٔ پاییز", "subtext": "۲۵۰٬۰۰۰ تومان"}),
                          self.ctx())
        diff = np.abs(np.asarray(out, dtype=int) - np.asarray(img, dtype=int))
        self.assertGreater(diff[800:].mean(), diff[:300].mean() + 5, "متن پایینِ عکس ننشست")
        logo = Path(tempfile.mkdtemp()) / "logo.png"
        lg = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
        ImageDraw.Draw(lg).rectangle([10, 10, 290, 110], fill=(255, 200, 0, 255))
        lg.save(logo)
        out = ops.op_logo(img, catalog.normalize_params("logo", {"position": "br", "size": 20, "opacity": 100}),
                          self.ctx(logo_path=lambda p: logo))
        corner = np.asarray(out)[1000, 1000]
        self.assertGreater(int(corner[0]), 200)
        self.assertGreater(int(corner[1]), 150)
        with self.assertRaises(ops.OpError):
            ops.op_logo(img, catalog.normalize_params("logo", {}), self.ctx())
        out = ops.op_watermark(img, catalog.normalize_params("watermark", {"mode": "tiled", "opacity": 60}), self.ctx())
        changed = np.abs(np.asarray(out, dtype=int) - np.asarray(img, dtype=int)).sum(axis=2) > 30
        self.assertGreater(changed.mean(), 0.008, "واترمارک روی عکس ننشست")
        self.assertGreater(changed[:540].mean(), 0.003)      # تکرار روی کلِ عکس، نه فقط یک گوشه
        self.assertGreater(changed[540:].mean(), 0.003)
        shutil.rmtree(logo.parent, ignore_errors=True)

    def test_rotate_straighten_and_export_size_cap(self):
        img = photo(1000, 600)
        out = ops.op_rotate(img, catalog.normalize_params("rotate", {"turn": "90"}), self.ctx())
        self.assertEqual(out.size, (600, 1000))
        out = ops.op_rotate(img, catalog.normalize_params("rotate", {"straighten": 5}), self.ctx())
        self.assertLess(out.width, 1000)
        self.assertLess(out.height, 600)
        big = photo(2400, 1800)
        data, fmt = ops.encode(big, "jpeg", 95, max_kb=150)
        self.assertEqual(fmt, "jpeg")
        self.assertLessEqual(len(data), 150 * 1024 * 1.05)
        rgba = photo(400, 300, alpha=True)
        data, fmt = ops.encode(rgba, "png")
        self.assertEqual(Image.open(io.BytesIO(data)).mode, "RGBA")

    def test_every_recipe_normalizes_and_kit_payload_matches_the_kit(self):
        for r in catalog.recipe_list():
            for o in r["operations"]:
                self.assertIn(o["tool"], catalog.tools())
        ops_ = catalog.normalize_operations([dict(o, on=True) for o in catalog.RECIPE_BY_KEY["product_white"]["operations"]])
        node, server = catalog.split(ops_)
        payload = catalog.kit_payload(node, has_server_after=False, final_format="jpeg")
        rec = payload["recipe"]
        store = next(p for p in catalog.kit()["presets"] if p["key"] == "store")["recipe"]
        for k, v in store["adjust"].items():          # همان «عکسِ فروشگاهیِ» خودِ کیت
            self.assertEqual(rec["adjust"][k], v, k)
        self.assertEqual(rec["background"]["color"], "#ffffff")
        self.assertTrue(rec["output"]["square"])
        self.assertEqual(rec["output"]["longEdge"], 2000)
        self.assertAlmostEqual(rec["output"]["padding"], 0.06)
        transparent = catalog.kit_payload(catalog.normalize_operations(
            [{"tool": "kit_background", "params": {"bg": "transparent"}}]), has_server_after=True)
        self.assertEqual(transparent["recipe"]["output"]["format"], "png")
        smart = catalog.kit_payload(catalog.normalize_operations(
            [{"tool": "kit_smart", "params": {"goal": "گرم و روشن"}}, {"tool": "kit_upscale", "params": {"factor": "4"}}]),
            has_server_after=False)
        self.assertEqual(smart["goal"], "گرم و روشن")
        self.assertEqual(smart["recipe"]["output"]["upscale"], 4)
        with self.assertRaises(catalog.CatalogError):
            catalog.normalize_operations([{"tool": "nope"}])
        with self.assertRaises(catalog.CatalogError):
            catalog.normalize_operations([{"tool": "kit_smart", "params": {"goal": " "}}])
        with self.assertRaises(catalog.CatalogError):
            catalog.normalize_operations([{"tool": "crop_format", "params": {"format": "hexagon"}}])
        clamp = catalog.normalize_params("kit_adjust", {"adjust": {"exposure": 99, "bogus": 3, "contrast": 0}})
        self.assertEqual(clamp["adjust"], {"exposure": 4.0})

    def test_kit_catalog_is_the_kits_own(self):
        keys = {p["key"] for p in catalog.kit()["params"]}
        self.assertTrue({"exposure", "dehaze", "noiseLuma", "sharpenMasking", "distortion", "blueSat"} <= keys)
        self.assertEqual(len(catalog.kit()["presets"]), 14)

    def test_real_photo_from_this_server(self):
        p = real_photo()
        if p is None:
            self.skipTest("no real product photo on this machine")
        img = ops.load(p)
        f = ops.measure(img)
        self.assertGreater(f["sharpness"], 0)
        ctx = self.ctx()
        out, export = ops.run(img, catalog.normalize_operations(
            [dict(o, on=True) for o in catalog.RECIPE_BY_KEY["instagram_post"]["operations"] if o["tool"] != "kit_auto"]
            + [{"tool": "text", "params": {"text": "نمونه"}}]), ctx)
        self.assertEqual(out.size, (1080, 1080))
        data, fmt = ops.encode(out, export["format"], export["quality"])
        self.assertEqual(Image.open(io.BytesIO(data)).size, (1080, 1080))


class ApiTestBase(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmphoto-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmphoto-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("photo-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ آزمون")
        self.product = Product.objects.create(store=self.store, name="قهوهٔ ترک", price=200_000)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/photo-editor"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def upload(self, *imgs):
        files = [jpeg_file(img, f"p{i}.jpg") for i, img in enumerate(imgs)]
        r = self.api.post(f"{self.base}/assets/", {"files": files}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        return [a["id"] for a in r.json()["assets"]]

    def node(self, **caps):
        return ComputeNode.objects.create(name="gpu-photo", last_seen=timezone.now(), capabilities={"photo": True} | caps)


class ApiTests(ApiTestBase):
    def test_overview_upload_import_plan(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["node"]["online"])
        self.assertTrue(any(t["key"] == "kit_background" and t["where"] == "node" for t in body["tools"]))
        self.assertTrue(any(t["key"] == "crop_format" and t["where"] == "server" for t in body["tools"]))
        self.assertEqual(len(body["kit"]["params"]), 58)
        ids = self.upload(photo(dark=True), photo(seed=2))
        self.assertEqual(len(ids), 2)
        a = PhotoAsset.objects.get(pk=ids[0])
        self.assertTrue((self.media / a.original).is_file())
        self.assertTrue((self.media / a.thumb).is_file())
        self.assertIn("dark", {f["what"] for f in a.findings})
        # عکسِ محصول ⇐ کتابخانه؛ دوباره‌آوردن همان را برمی‌گرداند
        pi = ProductImage(product=self.product)
        pi.image.save("prod.jpg", File(jpeg_file(photo(seed=3))), save=True)
        r = self.api.get(f"{self.base}/sources/")
        self.assertEqual(r.json()["products"][0]["images"][0]["ref"], f"product_image:{pi.pk}")
        r1 = self.api.post(f"{self.base}/assets/", {"refs": [f"product_image:{pi.pk}"]}, format="json")
        r2 = self.api.post(f"{self.base}/assets/", {"refs": [f"product_image:{pi.pk}"]}, format="json")
        self.assertEqual(r1.json()["assets"][0]["id"], r2.json()["assets"][0]["id"])
        self.assertEqual(r1.json()["assets"][0]["product"], self.product.pk)
        # پیشنهاد: گره خاموش ⇐ کارِ سبکِ سرور تیک دارد، کیت ندارد
        plan = self.api.post(f"{self.base}/plan/", {"asset": ids[0], "recipe": "suggest"}, format="json").json()
        on = {o["tool"]: o["on"] for o in plan["operations"]}
        self.assertTrue(on["auto_tone"])
        self.assertFalse(on["kit_auto"])
        plan = self.api.post(f"{self.base}/plan/", {"asset": ids[0], "recipe": "instagram_post"}, format="json").json()
        on = {o["tool"]: o["on"] for o in plan["operations"]}
        self.assertFalse(on["kit_auto"])
        self.assertTrue(on["auto_tone"], "گره خاموش است ⇐ جایگزینِ سبک باید تیک بخورد")

    def test_server_only_batch_is_ready_at_once_and_can_be_saved_everywhere(self):
        ids = self.upload(photo(dark=True), photo(seed=4))
        ops_ = [{"tool": "auto_tone", "params": {"strength": 80}},
                {"tool": "crop_format", "params": {"format": "portrait", "fit": "cover"}},
                {"tool": "text", "params": {"text": "قهوهٔ تازه"}},
                {"tool": "export", "params": {"format": "webp", "quality": 85}}]
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "recipe": "manual", "operations": ops_}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        batch = r.json()["batch"]
        edits = PhotoEdit.objects.filter(batch=batch)
        self.assertEqual(edits.count(), 2)
        for e in edits:
            self.assertEqual(e.state, "READY", e.error)
            res = self.media / e.files["result"]
            self.assertEqual(res.suffix, ".webp")
            with Image.open(res) as im:
                self.assertEqual(im.size, (1080, 1350))
            self.assertTrue((self.media / e.files["preview"]).is_file())
            self.assertIn("after", e.stats)
        dark_edit = edits.get(asset_id=ids[0])
        self.assertGreater(dark_edit.stats["after"]["p50"], dark_edit.asset.facts["p50"] + 10)
        # ذخیره در محصول، استفاده در محتوا، کتابخانه
        url = f"{self.base}/edits/{dark_edit.pk}"
        r = self.api.post(f"{url}/product/", {"product": self.product.pk, "main": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(ProductImage.objects.get(pk=r.json()["product_image"]["id"]).is_main)
        r = self.api.post(f"{url}/content/", {"product": self.product.pk}, format="json")
        gi = GeneratedImage.objects.get(pk=r.json()["generated_image"]["id"])
        self.assertEqual(gi.kind, "ENHANCED")
        self.assertEqual(gi.metadata["source"], "photo_editor")
        r = self.api.get(f"/api/v1/products/{self.product.pk}/image-studio/")
        self.assertIn(gi.pk, [x["id"] for x in r.json()], "در استودیو تصویر دیده نشد")
        r = self.api.post(f"{url}/library/", {}, format="json")
        lib = PhotoAsset.objects.get(pk=r.json()["asset"]["id"])
        self.assertEqual(lib.source_kind, "edit")
        self.assertEqual((lib.width, lib.height), (1080, 1350))
        # zip ِ همهٔ نتیجه‌ها
        r = self.api.get(f"{self.base}/batches/{batch}/zip/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()), 2)
        # retry ⇐ نسخهٔ تازه با همان کارها
        r = self.api.post(f"{url}/retry/", {}, format="json")
        self.assertEqual(r.json()["new"]["number"], 2)
        # حذف
        self.assertEqual(self.api.delete(f"{url}/").status_code, 204)
        self.assertEqual(self.api.delete(f"{self.base}/assets/{ids[1]}/").status_code, 204)
        self.assertFalse((self.media / f"photoedit/s{self.store.pk}/a{ids[1]}").exists())

    def test_logo_from_store_and_validation_errors(self):
        ids = self.upload(photo())
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "operations": [{"tool": "logo", "params": {}}]},
                          format="json")
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.state, "FAILED")
        self.assertIn("لوگو", e.error)
        lg = io.BytesIO()
        Image.new("RGBA", (200, 80), (255, 0, 0, 255)).save(lg, "PNG")
        self.store.logo.save("logo.png", File(lg), save=True)
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "operations": [{"tool": "logo", "params": {}}]},
                          format="json")
        self.assertEqual(PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"]).state, "READY")
        bad = self.api.post(f"{self.base}/edits/", {"assets": ids, "operations": [{"tool": "kit_smart", "params": {}}]},
                            format="json")
        self.assertEqual(bad.status_code, 400)
        ids2 = self.upload(photo(seed=7))
        heal = [{"tool": "kit_heal", "params": {"spots": [{"x": 0.5, "y": 0.5, "r": 0.02}]}}]
        bad = self.api.post(f"{self.base}/edits/", {"assets": ids + ids2, "operations": heal}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("یک عکس", bad.json()["error"]["message"])

    def test_other_users_cannot_see_the_library(self):
        ids = self.upload(photo())
        stranger = User.objects.create_user("stranger", password="x")
        api = APIClient()
        api.force_authenticate(stranger)
        self.assertEqual(api.get(f"{self.base}/").status_code, 404)
        self.assertEqual(api.get(f"{self.base}/assets/{ids[0]}/").status_code, 404)
        self.assertEqual(api.post(f"{self.base}/edits/", {"assets": ids, "recipe": "quick_fix"}, format="json").status_code, 404)


class NodeQueueTests(ApiTestBase):
    """کارهای کیت ⇐ photo.edit در صف؛ گره خاموش ⇐ «منتظر»؛ گره کار را تمام کند ⇐ مرحلهٔ سرورِ سایت ⇐ آماده."""

    def _finish_on_node(self, job: ComputeJob, node: ComputeNode, *, transparent=False, fail=""):
        job.refresh_from_db()
        got = compute.claim(node)
        self.assertEqual(got.pk, job.pk)
        if fail:
            job.attempts = job.max_attempts
            job.save()
            compute.finish(job, node, False, error=fail)
            return
        src = compute.job_root(job) / job.inputs[job.payload["image"]]
        img = ops.load(src).convert("RGB")
        out = Image.eval(img, lambda v: min(255, v + 25))
        name = "photo-a-edited.png" if transparent else "photo-a-edited.jpg"
        if transparent:
            out = out.convert("RGBA")
        out.save(compute.output_path(job, name))
        compute.output_path(job, "photo-edit.json").write_text(json.dumps(
            {"recipe": job.payload["recipe"], "notes": "نمونه", "usedAi": False}, ensure_ascii=False), encoding="utf-8")
        compute.finish(job, node, True, meta={"primary": name, "engine": "photo"})

    def test_waits_without_node_then_finishes_when_node_answers(self):
        ids = self.upload(photo(seed=5))
        ops_ = [{"tool": "kit_auto"}, {"tool": "kit_upscale", "params": {"factor": "2"}},
                {"tool": "crop_format", "params": {"format": "square"}}]
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "recipe": "manual", "operations": ops_}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.state, "NODE")
        self.assertIn("منتظرِ سرورِ پردازش", e.message)
        job = ComputeJob.objects.get(uid=e.compute_job)
        self.assertEqual(job.kind, "photo.edit")
        self.assertEqual(job.state, "QUEUED")
        self.assertTrue(job.payload["auto"])
        self.assertEqual(job.payload["recipe"]["output"]["upscale"], 2)
        self.assertEqual(job.payload["recipe"]["output"]["format"], "jpeg")   # کارِ سرورِ سایت دنبالش است
        self.assertIn(job.payload["image"], job.inputs)
        # پنل وضعیت را بپرسد: هنوز منتظر
        r = self.api.get(f"{self.base}/edits/?ids={e.pk}")
        self.assertEqual(r.json()["edits"][0]["state"], "NODE")
        # گره روشن می‌شود و کار را تمام می‌کند
        node = self.node()
        self._finish_on_node(job, node)
        r = self.api.get(f"{self.base}/edits/?ids={e.pk}")
        d = r.json()["edits"][0]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual(d["node"], "gpu-photo")
        self.assertEqual(d["kit"]["notes"], "نمونه")
        e.refresh_from_db()
        with Image.open(self.media / e.files["result"]) as im:
            self.assertEqual(im.size, (1080, 1080))   # برشِ سرورِ سایت بعد از خروجیِ گره
        self.assertTrue((self.media / e.files["node"]).is_file())

    def test_node_only_edit_keeps_the_kit_file_and_transparency(self):
        ids = self.upload(photo(seed=6))
        self.node()
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "recipe": "product_transparent", "operations": [
            {"tool": "kit_background", "params": {"bg": "transparent"}}]}, format="json")
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.message, "در صفِ سرورِ پردازش")
        job = ComputeJob.objects.get(uid=e.compute_job)
        self.assertEqual(job.payload["recipe"]["background"]["color"], "transparent")
        self._finish_on_node(job, ComputeNode.objects.get(name="gpu-photo"), transparent=True)
        self.api.get(f"{self.base}/edits/?ids={e.pk}")
        e.refresh_from_db()
        self.assertEqual(e.state, "READY", e.error)
        self.assertTrue(e.files["result"].endswith(".png"))
        with Image.open(self.media / e.files["result"]) as im:
            self.assertEqual(im.mode, "RGBA")

    def test_node_failure_and_cancel(self):
        ids = self.upload(photo(seed=8))
        node = self.node()
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "operations": [{"tool": "kit_auto"}]}, format="json")
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self._finish_on_node(ComputeJob.objects.get(uid=e.compute_job), node, fail="photo service is not reachable")
        self.api.get(f"{self.base}/edits/{e.pk}/")
        e.refresh_from_db()
        self.assertEqual(e.state, "FAILED")
        self.assertIn("not reachable", e.error)
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "operations": [{"tool": "kit_denoise"}]}, format="json")
        e2 = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.api.post(f"{self.base}/edits/{e2.pk}/cancel/", {}, format="json")
        e2.refresh_from_db()
        self.assertEqual(e2.state, "CANCELLED")
        self.assertEqual(ComputeJob.objects.get(uid=e2.compute_job).state, "CANCELLED")

    def test_kit_analysis_round_trip(self):
        ids = self.upload(photo(seed=9))
        r = self.api.post(f"{self.base}/assets/{ids[0]}/analyze/", {}, format="json")
        self.assertEqual(r.json()["asset"]["kit_analysis"]["message"], "منتظرِ سرورِ پردازش")
        a = PhotoAsset.objects.get(pk=ids[0])
        job = ComputeJob.objects.get(uid=a.analysis_job)
        self.assertEqual(job.kind, "photo.analyze")
        node = self.node()
        compute.claim(node)
        compute.output_path(job, "analyze.json").write_text(json.dumps(
            {"stats": {"exposure": 0.1}, "text": "نور کم است.", "auto": {"recipe": {"adjust": {"exposure": 0.4}},
                                                                     "notes": ["نوردهی +۰٫۴"]}}, ensure_ascii=False))
        compute.finish(job, node, True, meta={"primary": "analyze.json"})
        r = self.api.get(f"{self.base}/assets/{ids[0]}/")
        ka = r.json()["asset"]["kit_analysis"]
        self.assertEqual(ka["state"], "READY")
        self.assertEqual(ka["text"], "نور کم است.")
        self.assertEqual(ka["notes"], ["نوردهی +۰٫۴"])
