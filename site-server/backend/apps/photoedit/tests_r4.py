"""نوبت ۴ ادیتور عکس: تنظیماتِ فروشگاه (پیش‌فرضِ هوش مصنوعی)، سبکِ برند در طراحِ خودکار و طراحیِ گروهی. بی شبکه و بی هوشِ مصنوعیِ واقعی."""
import io
import zipfile

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import brand, batch, services
from .designer import build, engine, qa, recipes
from .models import PhotoDesign, PhotoDesignBatch
from .tests_designer import DesignerBase, FakeVision, patch_ai, product_photo

PLAN_REPLY = {"recipe": "product_ad", "mood": "light", "copy": {"headline": "کفشِ سبک"}, "grade": {}, "text_zone": "auto", "extra_steps": [],
              "notes": "یک جمله"}


class BrandCleanTests(SimpleTestCase):
    def test_clean_drops_garbage_and_clamps(self):
        b = brand.clean({"colors": ["#FF0000", "red", "#ff0000", "#00ff00", "#0000ff", "#111111", "#222222", "#333333"], "heading_font": "no-such",
                         "body_font": "vazirmatn", "tone": "  گرم   و  صمیمی " * 30, "logo": {"mode": "asset", "asset": "x", "position": "nowhere", "size": 9}})
        self.assertEqual(b["colors"], ["#ff0000", "#00ff00", "#0000ff", "#111111", "#222222"])
        self.assertEqual(b["heading_font"], "")
        self.assertEqual(b["body_font"], "vazirmatn")
        self.assertLessEqual(len(b["tone"]), brand.TONE_MAX)
        self.assertEqual(b["logo"]["mode"], "store")           # شناسهٔ نامعتبرِ عکس ⇒ به لوگوی فروشگاه برمی‌گردد
        self.assertEqual(b["logo"]["position"], "")
        self.assertEqual(b["logo"]["size"], brand.SIZE_MAX)
        self.assertEqual(brand.clean("garbage"), brand.empty_brand())
        self.assertFalse(brand.is_set(brand.empty_brand()))
        self.assertTrue(brand.is_set(brand.clean({"tone": "رسمی"})))


class SettingsApiTests(DesignerBase):
    def test_defaults_put_and_persistence(self):
        r = self.api.get(f"{self.base}/settings/")
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertFalse(j["ai_assist"], "پیش‌فرضِ تازه: خاموش (تصمیمِ مالک ۱۴۰۵/۰۸/۱۶)")
        self.assertEqual((j["smart_offline"], j["matting_model"]), ("ask", "rvm"))
        self.assertFalse(j["brand_set"])
        self.assertEqual(j["ai_cost"]["normal"], 4)           # ۱ برنامه‌ریز + ۳ نقد
        self.assertEqual(j["ai_cost"]["fast"], 1)
        r = self.api.put(f"{self.base}/settings/", {"ai_assist": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ai_assist"])
        self.assertTrue(self.api.get(f"{self.base}/settings/").json()["ai_assist"])
        r = self.api.put(f"{self.base}/settings/", {"smart_offline": "queue", "matting_model": "isnet"}, format="json")
        self.assertEqual((r.json()["smart_offline"], r.json()["matting_model"]), ("queue", "isnet"))
        self.assertEqual(self.api.put(f"{self.base}/settings/", {"smart_offline": "maybe"}, format="json").status_code, 400)
        self.assertEqual(self.api.put(f"{self.base}/settings/", {"matting_model": "gpt"}, format="json").status_code, 400)
        r = self.api.put(f"{self.base}/settings/", {"brand": {"colors": ["#aa0000"], "tone": "صمیمی", "logo": {"position": "tr", "size": 0.2}}}, format="json")
        j = r.json()
        self.assertTrue(j["brand_set"])
        self.assertTrue(j["ai_assist"], "ذخیرهٔ برند پیش‌فرضِ هوش مصنوعی را به‌هم نمی‌زند")
        self.assertEqual(j["brand"]["colors"], ["#aa0000"])
        self.assertEqual(self.api.put(f"{self.base}/settings/", {"ai_assist": "yes"}, format="json").status_code, 400)
        self.assertIn("settings", self.api.get(f"{self.base}/designer/").json())

    def test_other_user_gets_404(self):
        other = get_user_model().objects.create_user("intruder2", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}/settings/").status_code, 404)
        self.assertEqual(c.put(f"{self.base}/settings/", {"ai_assist": False}, format="json").status_code, 404)


class AiDefaultTests(DesignerBase):
    def test_design_without_explicit_flag_follows_store_default(self):
        asset = self.asset()
        d = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ"})
        self.assertFalse(d.options["use_ai"], "پیش‌فرضِ تازه: خاموش")
        PhotoDesign.objects.all().update(state="READY")
        brand.save(self.store, {"ai_assist": True})
        d2 = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ"})
        self.assertTrue(d2.options["use_ai"])
        PhotoDesign.objects.all().update(state="READY")
        brand.save(self.store, {"ai_assist": False})
        d2 = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ"})
        self.assertFalse(d2.options["use_ai"])
        PhotoDesign.objects.all().update(state="READY")                                       # سقفِ دو طراحیِ هم‌زمان مانع نشود
        d3 = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ", "use_ai": True})       # تیکِ همان بار برنده است
        self.assertTrue(d3.options["use_ai"])

    def test_off_default_makes_no_ai_call(self):
        brand.save(self.store, {"ai_assist": False})
        asset = self.asset()
        fake = FakeVision()
        with patch_ai(fake):
            d = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ", "recipe": "product_ad", "variants": 1})
            engine.run(d.pk)
        self.assertEqual(fake.calls, [])
        self.assertEqual(PhotoDesign.objects.get(pk=d.pk).state, "READY")


class BrandInDesignTests(DesignerBase):
    def test_brand_colors_fonts_logo_are_used_and_override_works(self):
        asset = self.asset()
        logo_asset = self.asset(title="لوگوی برند")
        brand.save(self.store, {"brand": {"colors": ["#0a7a3c"], "heading_font": "vazirmatn", "logo": {"mode": "asset", "asset": logo_asset.pk, "position": "tr", "size": 0.2}}})
        kit = brand.effective(self.store, {})
        self.assertEqual(kit["colors"], ["#0a7a3c"])
        plan = self.make(asset, "product_ad", has_logo=True, copy={"headline": "کفشِ سبک", "price": "۴۵۰ هزار تومان"})
        b = build.build(asset, plan, user=self.owner, kit=kit)
        self.assertEqual(b["palette"]["accent"], "#0a7a3c")
        logos = [l for l in b["state"]["layers"] if l.get("src", {}).get("kind") == "asset" and l["name"] == "لوگو"]
        self.assertEqual(len(logos), 1, [l["name"] for l in b["state"]["layers"]])
        self.assertEqual(logos[0]["src"]["asset"], logo_asset.pk)
        self.assertAlmostEqual(logos[0]["w"], 0.2, places=3)
        self.assertGreater(logos[0]["cx"], 0.5)                       # tr = سمتِ راست
        self.assertLess(logos[0]["cy"], 0.5)
        titles = [l for l in b["state"]["layers"] if l["type"] == "text"]
        self.assertTrue(any(l.get("font") == "vazirmatn" for l in titles), [(l.get("name"), l.get("font")) for l in titles])
        # بازنویسیِ همین طراحی: رنگ و موقعیتِ لوگو عوض می‌شود و بقیه از سبکِ ذخیره‌شده می‌ماند
        kit2 = brand.effective(self.store, {"brand": {"colors": ["#aa00aa"], "logo": {"position": "bl"}}})
        self.assertEqual(kit2["colors"], ["#aa00aa"])
        self.assertEqual(kit2["logo"]["position"], "bl")
        self.assertEqual(kit2["logo"]["asset"], logo_asset.pk)
        self.assertEqual(kit2["heading_font"], "vazirmatn")
        self.assertIsNone(brand.effective(self.store, {"use_brand": False}))

    def test_tone_reaches_the_planner_prompt_only_with_ai(self):
        brand.save(self.store, {"brand": {"tone": "گرم، صمیمی و کوتاه"}})
        asset = self.asset()
        fake = FakeVision(PLAN_REPLY)
        with patch_ai(fake):
            d = engine.create(self.store, self.owner, asset, {"prompt": "تبلیغ", "recipe": "product_ad", "variants": 1, "use_ai": True, "quality": "fast"})
            engine.run(d.pk)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("گرم، صمیمی و کوتاه", fake.calls[0]["prompt"])
        d = PhotoDesign.objects.create(store=self.store, asset=asset, created_by=self.owner, prompt="تبلیغ", recipe="product_ad", quality="fast",
                                       options={"variants": 1, "use_ai": True, "use_brand": False})
        fake2 = FakeVision(PLAN_REPLY)
        with patch_ai(fake2):
            engine.run(d.pk)
        self.assertNotIn("گرم، صمیمی", fake2.calls[0]["prompt"])


class BatchTests(DesignerBase):
    def three(self):
        return [self.asset(title=f"عکسِ {i}").pk for i in range(3)]

    def test_validation_and_caps(self):
        ids = self.three()
        for bad in ({"assets": ids}, {"assets": [], "prompt": "x"}, {"assets": [99999], "prompt": "x"}):
            r = self.api.post(f"{self.base}/designer/batches/", bad, format="json")
            self.assertEqual(r.status_code, 400, bad)
        many = [self.asset(title=f"m{i}").pk for i in range(batch.MAX_PHOTOS_AI + 1)]
        with self.assertRaises(batch.BatchError) as cm:
            batch.create(self.store, self.owner, {"assets": many, "prompt": "x", "use_ai": True})
        self.assertIn(str(batch.MAX_PHOTOS_AI), str(cm.exception))
        b = batch.create(self.store, self.owner, {"assets": many, "prompt": "x", "use_ai": False})        # بدونِ هوش مصنوعی سقف بالاتر است
        self.assertEqual(len(b.assets), batch.MAX_PHOTOS_AI + 1)
        with self.assertRaises(batch.BatchError) as cm:
            batch.create(self.store, self.owner, {"assets": ids, "prompt": "x", "use_ai": False})
        self.assertIn("دیگر", str(cm.exception))

    def test_full_run_review_zip_without_ai(self):
        ids = self.three()
        fake = FakeVision()
        with patch_ai(fake):
            r = self.api.post(f"{self.base}/designer/batches/", {"assets": ids, "recipe": "product_ad", "prompt": "تبلیغ", "use_ai": False,
                                                                  "copy": {"headline": "کفشِ سبک"}}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            bid = r.json()["batch"]["id"]
        self.assertEqual(fake.calls, [], "طراحیِ گروهیِ بی‌هوش‌مصنوعی هیچ فراخوانی نمی‌زند")
        j = self.api.get(f"{self.base}/designer/batches/{bid}/").json()["batch"]
        self.assertEqual(j["state"], "READY", j)
        self.assertEqual((j["done"], j["total"], j["progress"]), (3, 3, 1.0))
        self.assertEqual([it["asset"]["id"] for it in j["items"]], ids)
        for it in j["items"]:
            self.assertEqual(it["design"]["state"], "READY")
            self.assertTrue(it["design"]["preview"].startswith("/media/"), it)
        self.assertEqual(PhotoDesign.objects.filter(batch_id=bid).count(), 3)
        self.assertTrue(all(d.quality == "fast" and d.options["variants"] == 1 for d in PhotoDesign.objects.filter(batch_id=bid)))
        # طراحی‌های گروهی در فهرستِ طراحی‌های یک عکس نمی‌آیند
        self.assertEqual(len(self.api.get(f"{self.base}/designer/designs/?asset={ids[0]}").json()["designs"]), 0)
        r = self.api.get(f"{self.base}/designer/batches/{bid}/zip/")
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertEqual(len(z.namelist()), 3)
        self.assertTrue(all(n.endswith(".jpg") for n in z.namelist()))
        r = self.api.get(f"{self.base}/designer/batches/{bid}/zip/?assets={ids[0]},{ids[2]}")
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()), 2)
        # فهرست
        self.assertEqual(self.api.get(f"{self.base}/designer/batches/").json()["batches"][0]["id"], bid)
        # یکی را در ویرایشگر باز کن (همان apply ِ طراحِ خودکار)
        did = j["items"][1]["design"]["id"]
        r = self.api.post(f"{self.base}/designer/designs/{did}/apply/", {"variant": 0}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        # حذف ⇒ طراحی‌ها و فایل‌ها پاک
        dirs = [self.media / d.dir_rel for d in PhotoDesign.objects.filter(batch_id=bid)]
        self.assertEqual(self.api.delete(f"{self.base}/designer/batches/{bid}/").status_code, 204)
        self.assertEqual(PhotoDesign.objects.filter(batch_id=bid).count(), 0)
        self.assertFalse(any(p.exists() for p in dirs))

    def test_ai_is_one_planner_call_per_photo_and_no_critic(self):
        ids = self.three()[:2]
        fake = FakeVision(PLAN_REPLY, PLAN_REPLY)
        with patch_ai(fake):
            b = batch.create(self.store, self.owner, {"assets": ids, "prompt": "تبلیغ", "use_ai": True})
            batch.run(b.pk)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(PhotoDesignBatch.objects.get(pk=b.pk).state, "READY")

    def test_failure_of_one_photo_does_not_stop_the_rest(self):
        ids = self.three()
        b = batch.create(self.store, self.owner, {"assets": ids, "recipe": "product_ad", "prompt": "x", "use_ai": False})
        real = engine.run
        calls = {"n": 0}

        def flaky(pk):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real(pk)

        from unittest import mock

        with mock.patch.object(engine, "run", flaky):
            batch.run(b.pk)
        b.refresh_from_db()
        self.assertEqual(b.state, "READY")                          # دو تا ساخته شد، یکی نه
        self.assertEqual(b.done, 3)
        self.assertIn("1 عکس ناموفق", b.message)

    def test_cancel_and_other_user(self):
        ids = self.three()
        b = PhotoDesignBatch.objects.create(store=self.store, created_by=self.owner, recipe="product_ad", prompt="x", assets=ids, options={"use_ai": False})
        r = self.api.post(f"{self.base}/designer/batches/{b.pk}/", {"action": "cancel"}, format="json")
        self.assertEqual(r.json()["batch"]["state"], "CANCELLED")
        batch.run(b.pk)                                             # لغوشده دوباره اجرا نمی‌شود
        self.assertEqual(PhotoDesign.objects.filter(batch=b).count(), 0)
        other = get_user_model().objects.create_user("intruder3", password="x")
        Store.objects.create(owner=other, name="دیگری")
        c = APIClient()
        c.force_authenticate(other)
        for url in (f"{self.base}/designer/batches/", f"{self.base}/designer/batches/{b.pk}/", f"{self.base}/designer/batches/{b.pk}/zip/"):
            self.assertEqual(c.get(url).status_code, 404, url)


class MattingTests(DesignerBase):
    def test_quality_gate(self):
        import numpy as np

        from . import matting

        def blob(x0, y0, x1, y1, h=100, w=100):
            a = np.zeros((h, w), np.float32)
            a[y0:y1, x0:x1] = 1.0
            return a

        self.assertTrue(matting.quality(blob(30, 30, 70, 80))[0])
        self.assertFalse(matting.quality(blob(0, 0, 3, 3))[0])               # خیلی کوچک
        self.assertFalse(matting.quality(np.ones((100, 100), np.float32))[0])  # همهٔ عکس
        fuzz = np.full((100, 100), 0.5, np.float32)
        fuzz[40:60, 40:60] = 1.0
        self.assertFalse(matting.quality(fuzz)[0])                            # نیمه‌شفافِ سرگردان
        self.assertFalse(matting.quality(None)[0])

    def test_busy_background_uses_cpu_model_then_falls_back(self):
        import numpy as np
        from unittest import mock

        from . import matting
        from .designer import matte

        rng = np.random.default_rng(2)
        busy = Image.fromarray((rng.random((700, 900, 3)) * 255).astype(np.uint8))
        a = np.zeros((700, 900), np.float32)
        a[200:560, 300:620] = 1.0
        with mock.patch.object(matting, "available", lambda: True), mock.patch.object(matting, "alpha", lambda img, passes=3: a):
            m = matte.compute(busy, [0.3, 0.3, 0.7, 0.8])
        self.assertTrue(m["ok"])
        self.assertEqual(m["method"], "cpu-model")
        self.assertIn("آدم", m["note"])
        self.assertEqual(m["mask"].shape, (700, 900))
        self.assertGreater(m["mask"][380, 460], 200)
        self.assertEqual(m["mask"][10, 10], 0)
        # مدل چیزی پیدا نکند ⇒ همان GrabCut ِ قبلی
        with mock.patch.object(matting, "available", lambda: True), mock.patch.object(matting, "alpha", lambda img, passes=3: np.zeros((700, 900), np.float32)):
            m2 = matte.compute(busy, [0.3, 0.3, 0.7, 0.8])
        self.assertEqual(m2["method"], "grabcut-box")
        # مدل نباشد ⇒ باز هم همان
        with mock.patch.object(matting, "available", lambda: False):
            self.assertEqual(matte.compute(busy, [0.3, 0.3, 0.7, 0.8])["method"], "grabcut-box")

    def test_real_model_smoke_if_present(self):
        import os
        import numpy as np
        from unittest import mock
        from pathlib import Path

        from . import matting

        live = "/var/www/NM/upmarket/data/up3d/downloads/rvm_mobilenetv3_fp32.onnx"
        if not (matting.model_path() or Path(live).is_file()):
            self.skipTest("مدلِ جداسازی روی این ماشین نیست")
        with mock.patch.dict(os.environ, {"NM_PHOTO_MATTE_MODEL": str(matting.model_path() or live)}):
            self.assertTrue(matting.available())
            img = Image.fromarray((np.random.default_rng(0).random((300, 400, 3)) * 255).astype(np.uint8))
            a = matting.alpha(img, passes=1)
        self.assertEqual(a.shape, (300, 400))
        self.assertTrue(0.0 <= float(a.min()) and float(a.max()) <= 1.0)
