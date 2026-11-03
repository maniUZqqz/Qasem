"""ادیتورِ عکس — سه حالتِ خودکار / نیمه‌خودکار (دستور) / دستی: برشِ دلخواه، منحنی، کارهای انتخاب‌شدهٔ کیت به‌صورتِ
قابل‌ویرایش، پیش‌نمایشِ دقیقِ سرورِ سایت، دلیلِ هر کار. هیچ هوشِ مصنوعیِ واقعی صدا زده نمی‌شود (گرهٔ ساختگی)."""
import json
import urllib.parse

import numpy as np
from PIL import Image

from apps.compute import services as compute
from apps.compute.models import ComputeJob
from apps.stores.models import Store

from . import catalog, ops
from .models import PhotoEdit
from .tests import ApiTestBase, photo


class CatalogModeTests(ApiTestBase):
    def test_recipes_are_grouped_into_the_three_modes(self):
        modes = {r["key"]: r["mode"] for r in catalog.recipe_list()}
        self.assertEqual(modes["smart"], "prompt")
        self.assertEqual(modes["manual"], "manual")
        for key in ("suggest", "instagram_post", "story", "product_white", "enhance", "banner", "quick_fix", "brand"):
            self.assertEqual(modes[key], "auto", key)
        body = self.api.get(f"{self.base}/").json()
        self.assertEqual({r["key"]: r["mode"] for r in body["recipes"]}["smart"], "prompt")

    def test_crop_rect_is_a_server_tool_with_clamped_bounds(self):
        t = catalog.tools()["crop_rect"]
        self.assertEqual(t["where"], "server")
        p = catalog.normalize_params("crop_rect", {"x": 10, "y": 5, "w": 50, "h": 40})
        out = ops.op_crop_rect(photo(1000, 800), p, {"notes": []})
        self.assertEqual(out.size, (500, 320))
        # فراتر از لبه ⇐ در عکس می‌ماند و کمتر از ۸ پیکسل نمی‌شود
        p = catalog.normalize_params("crop_rect", {"x": 90, "y": 90, "w": 100, "h": 100})
        out = ops.op_crop_rect(photo(1000, 800), p, {"notes": []})
        self.assertLessEqual(out.size[0], 100)
        self.assertGreaterEqual(min(out.size), 8)
        # کلِ عکس ⇐ همان عکس
        img = photo(300, 200)
        self.assertIs(ops.op_crop_rect(img, catalog.normalize_params("crop_rect", {}), {"notes": []}), img)

    def test_curve_is_normalised_and_reaches_the_kit(self):
        c = catalog.normalize_curve({"rgb": [[255, 255], [0, 0], [128, 170], [128, 99]], "red": [[0, 0], [255, 255]],
                                     "zzz": [[0, 0], [9, 9]], "blue": "x"})
        self.assertEqual(c, {"rgb": [[0.0, 0.0], [128.0, 170.0], [255.0, 255.0]]})   # خطِ راست و ناشناخته دور ریخته
        ops_ = catalog.normalize_operations([{"tool": "kit_adjust", "params": {"adjust": {"exposure": 0.3},
                                                                              "curve": {"rgb": [[0, 10], [255, 240]]}}}])
        node, server = catalog.split(ops_)
        payload = catalog.kit_payload(node, has_server_after=False, final_format="jpeg")
        self.assertEqual(payload["recipe"]["adjust"], {"exposure": 0.3})
        self.assertEqual(payload["recipe"]["curve"], {"rgb": [[0.0, 10.0], [255.0, 240.0]]})
        # فقط منحنی (بی لغزنده) هم کاری است
        only = catalog.normalize_operations([{"tool": "kit_adjust", "params": {"curve": {"red": [[0, 0], [100, 130], [255, 255]]}}}])
        self.assertEqual(len(only), 1)

    def test_kit_recipe_becomes_editable_steps_and_round_trips(self):
        recipe = {"preset": "warm",
                  "adjust": {"exposure": 0.4, "shadows": 25, "temperature": 12, "redSat": -15, "sharpen": 40, "nonsense": 9},
                  "curve": {"rgb": [[0, 8], [255, 245]]},
                  "spots": [{"x": 0.2, "y": 0.3, "r": 0.02}],
                  "background": {"remove": True, "method": "quick", "color": "#ffffff", "shadow": 20, "cleanup": -1},
                  "output": {"format": "jpeg", "square": True, "padding": 0.08, "longEdge": 1800, "upscale": 2}}
        steps = catalog.steps_from_kit_recipe(recipe)
        tools_ = [s["tool"] for s in steps]
        self.assertEqual(tools_.count("kit_adjust"), 5, tools_)      # نور، رنگ، رنگ‌به‌رنگ، جزئیات + منحنی
        for t in ("kit_preset", "kit_heal", "kit_background", "kit_square", "kit_upscale"):
            self.assertIn(t, tools_)
        self.assertTrue(all(s["reason"] and s["on"] and s["title"] for s in steps))
        self.assertNotIn("nonsense", json.dumps(steps))
        # دوباره به کیت می‌رود و همان نسخه را می‌سازد (بی هوشِ مصنوعی)
        clean = catalog.normalize_operations([{"tool": s["tool"], "params": s["params"]} for s in steps])
        node, _server = catalog.split(clean)
        again = catalog.kit_payload(node, has_server_after=False, final_format="jpeg")["recipe"]
        self.assertEqual(again["adjust"], {"exposure": 0.4, "shadows": 25.0, "temperature": 12.0, "redSat": -15.0, "sharpen": 40.0})
        self.assertEqual(again["preset"], "warm")
        self.assertTrue(again["output"]["square"])
        self.assertEqual(again["output"]["upscale"], 2)
        self.assertEqual(again["background"]["method"], "quick")
        # خاموش کردنِ یک گام ⇒ آن لغزنده‌ها نمی‌روند
        off = [{"tool": s["tool"], "params": s["params"], "on": s["group"] != "light"} for s in steps]
        node, _ = catalog.split(catalog.normalize_operations(off))
        self.assertNotIn("exposure", catalog.kit_payload(node, has_server_after=False)["recipe"]["adjust"])
        self.assertEqual(catalog.steps_from_kit_recipe(None), [])
        self.assertEqual(catalog.steps_from_kit_recipe({"adjust": {}}), [])


class PreviewApiTests(ApiTestBase):
    def preview(self, asset, operations):
        return self.api.post(f"{self.base}/preview/", {"asset": asset, "operations": operations}, format="json")

    def test_exact_server_preview_runs_without_a_node_and_reports_skipped_kit_tools(self):
        (aid,) = self.upload(photo(1600, 1000, seed=21))
        r = self.preview(aid, [{"tool": "crop_rect", "params": {"x": 0, "y": 0, "w": 50, "h": 50}},
                               {"tool": "text", "params": {"text": "قهوهٔ تازه", "position": "bottom"}},
                               {"tool": "kit_adjust", "params": {"adjust": {"exposure": 0.5}}},
                               {"tool": "export", "params": {"format": "png"}}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        info = json.loads(urllib.parse.unquote(r["X-Preview-Info"]))
        self.assertEqual(info["skipped"], ["تنظیمِ دستیِ حرفه‌ای (Camera Raw)"])
        self.assertEqual(info["size"], [640, 400])          # ۱۲۸۰ پیکسل ⇐ نیمه
        import io
        with Image.open(io.BytesIO(r.content)) as im:
            self.assertEqual(im.size, (640, 400))
            bottom = np.asarray(im.convert("L"), dtype=np.float32)[-60:].mean()
        plain = self.preview(aid, [{"tool": "crop_rect", "params": {"x": 0, "y": 0, "w": 50, "h": 50}}])
        with Image.open(io.BytesIO(plain.content)) as im2:
            plain_bottom = np.asarray(im2.convert("L"), dtype=np.float32)[-60:].mean()
        self.assertNotAlmostEqual(bottom, plain_bottom, delta=1.0, msg="متن/سایه روی پیش‌نمایش نیامد")
        self.assertEqual(PhotoEdit.objects.count(), 0, "پیش‌نمایش نسخه نمی‌سازد")

    def test_preview_errors_and_access(self):
        (aid,) = self.upload(photo(seed=22))
        r = self.preview(aid, [{"tool": "text", "params": {}}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("متن", r.json()["error"]["message"])
        self.assertEqual(self.preview(999999, []).status_code, 404)
        r = self.preview(aid, [{"tool": "logo", "params": {"source": "store"}}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("لوگو", r.json()["error"]["message"])
        # صاحبِ فروشگاهی دیگر نمی‌تواند
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user("intruder", password="x")
        self.api.force_authenticate(other)
        self.assertIn(self.preview(aid, []).status_code, (403, 404))
        self.assertIsNotNone(Store.objects.get(pk=self.store.pk))


class ReasonsAndChosenTests(ApiTestBase):
    def test_reasons_travel_with_the_edit_and_chosen_steps_appear_after_the_node_answers(self):
        (aid,) = self.upload(photo(seed=23))
        node = self.node()
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "smart", "operations": [
            {"tool": "kit_smart", "params": {"goal": "گرم و روشن"}, "reason": "دستورِ شما"},
            {"tool": "export", "params": {"format": "jpeg"}}]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.operations[0]["reason"], "دستورِ شما")
        self.assertEqual(r.json()["edits"][0]["chosen"], [], "تا برنگشته چیزی انتخاب نشده")
        job = ComputeJob.objects.get(uid=e.compute_job)
        self.assertEqual(job.payload["goal"], "گرم و روشن")
        # گره (ساختگی): هوشِ مصنوعی این لغزنده‌ها را انتخاب کرده
        got = compute.claim(node)
        self.assertEqual(got.pk, job.pk)
        src = compute.job_root(job) / job.inputs[job.payload["image"]]
        ops.load(src).convert("RGB").save(compute.output_path(job, "photo-a-edited.jpg"))
        chosen_recipe = {"adjust": {"temperature": 20, "exposure": 0.3, "vibrance": 15}, "preset": "warm"}
        compute.output_path(job, "photo-edit.json").write_text(json.dumps(
            {"goal": "گرم و روشن", "recipe": chosen_recipe, "notes": ["گرم‌تر شد"], "usedAi": True}, ensure_ascii=False),
            encoding="utf-8")
        compute.finish(job, node, True, meta={"primary": "photo-a-edited.jpg", "engine": "photo"})
        d = self.api.get(f"{self.base}/edits/?ids={e.pk}").json()["edits"][0]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual(d["kit"]["usedAi"], True)
        chosen = d["chosen"]
        self.assertTrue(any(s["tool"] == "kit_preset" for s in chosen))
        light = next(s for s in chosen if s["tool"] == "kit_adjust" and s["group"] == "light")
        self.assertEqual(light["params"]["adjust"], {"exposure": 0.3})
        self.assertEqual(d["operations"][0]["reason"], "دستورِ شما")
        # پیگیری: «گرم‌ترش کن» ⇐ کارهای انتخاب‌شده + هدفِ تازه؛ هر دو به کیت می‌روند (کیت از نسخهٔ فعلی ادامه می‌دهد)
        follow = [{"tool": s["tool"], "params": s["params"]} for s in chosen] + \
                 [{"tool": "kit_smart", "params": {"goal": "گرم‌ترش کن"}}]
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "smart", "operations": follow}, format="json")
        e2 = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        job2 = ComputeJob.objects.get(uid=e2.compute_job)
        self.assertEqual(job2.payload["goal"], "گرم‌ترش کن")
        self.assertEqual(job2.payload["recipe"]["adjust"]["temperature"], 20)
        self.assertEqual(job2.payload["recipe"]["preset"], "warm")

    def test_plan_for_suggest_still_carries_reasons(self):
        (aid,) = self.upload(photo(dark=True, seed=24))
        plan = self.api.post(f"{self.base}/plan/", {"asset": aid, "recipe": "suggest"}, format="json").json()
        self.assertTrue(all(o["reason"] for o in plan["operations"]))
        # «اعمال» با دلیل ⇐ در نسخه می‌ماند
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "suggest", "operations": [
            {"tool": o["tool"], "params": o["params"], "on": o["on"], "reason": o["reason"]} for o in plan["operations"]]},
                          format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()["edits"][0]
        self.assertEqual(d["state"], "READY")
        self.assertTrue(all(o["reason"] for o in d["operations"]))
