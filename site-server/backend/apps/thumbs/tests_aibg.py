"""پس‌زمینهٔ هوش مصنوعی: گرافِ FLUX، انتخابِ مدل از توانایی‌های گره، صفِ ماندگار (گره خاموش/روشن)، تامنیلِ منتظر که خودش کامل می‌شود."""
from unittest import mock

from django.utils import timezone

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.photoedit import inpaint_graph as ig
from apps.photoedit import services as photo
from apps.photoedit.models import PhotoAsset

from . import aibg, hooks, services
from . import formats as F
from .models import Thumbnail
from .tests_api import SPEC, ThumbsApiBase


def node(online: bool = True, caps=None, name="gpu-thumb") -> ComputeNode:
    return ComputeNode.objects.create(name=name, last_seen=timezone.now() if online else None, capabilities=caps if caps is not None else aibg.fake_caps())


class GraphTests(ThumbsApiBase):
    def test_graph_is_valid_for_checkpoint_and_unet_models(self):
        caps_ckpt = {"comfy_models": {"checkpoints": ["FLUX.1 [dev] FP8.safetensors"], "unet": []}}
        caps_unet = {"comfy_models": {"checkpoints": [], "unet": ["flux1-dev-fp8.safetensors"], "clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
                                      "vae": ["ae.safetensors"]}}
        for caps in (caps_ckpt, caps_unet):
            choice = aibg.txt2img_choice(caps)
            g = aibg.build_graph(choice, "a bright studio backdrop", 7, (1344, 768))
            with mock.patch.dict(ig.OUTPUTS, {"EmptyLatentImage": 1}):
                self.assertEqual(ig.validate(g), [], caps)
            self.assertEqual(g["23"]["inputs"]["width"], 1344)
            self.assertEqual(g["20"]["inputs"]["text"], "a bright studio backdrop")
            self.assertEqual(g["24"]["inputs"]["seed"], 7)
            self.assertIn("SaveImage", aibg.required_nodes(choice))

    def test_fill_only_node_is_rejected_with_a_clear_message(self):
        with self.assertRaises(ig.GraphError) as cm:
            aibg.txt2img_choice({"comfy_models": {"checkpoints": ["FLUX.1-Fill-dev.safetensors"], "unet": []}})
        self.assertIn("FLUX", str(cm.exception))
        # Fill و dev کنار هم ⇒ dev انتخاب می‌شود
        c = aibg.txt2img_choice({"comfy_models": {"checkpoints": ["FLUX.1-Fill-dev.safetensors", "FLUX.1 [dev] FP8.safetensors"], "unet": []}})
        self.assertEqual(c["ckpt"], "FLUX.1 [dev] FP8.safetensors")

    def test_unreported_node_assumes_owner_checkpoint(self):
        c = aibg.txt2img_choice({})
        self.assertEqual(c["ckpt"], ig.DEFAULT_DEV_CKPT)
        self.assertTrue(c["assumed"])

    def test_sizes_are_multiples_of_16_and_cover_every_format(self):
        for fmt in F.FORMATS:
            w, h = aibg.SIZES[fmt]
            self.assertEqual((w % 16, h % 16), (0, 0), fmt)
            self.assertLessEqual(w * h, 1_200_000)

    def test_prompt_resolution(self):
        p, info = aibg.resolve_prompt(self.store, preset="neon_city", colors=["#126F85", "#163F75"])
        self.assertIn("cyberpunk", p)
        self.assertIn("colour palette of", p)
        self.assertIn("no text", p)
        p, _ = aibg.resolve_prompt(self.store, style="cinema_poster")
        self.assertIn("cinematic", p)
        p, info = aibg.resolve_prompt(self.store, text="یک باشگاهِ شلوغ", style="neon")          # مترجم زیرِ آزمون نیست
        self.assertIn("cyberpunk", p)
        self.assertTrue(info["note"])
        p, info = aibg.resolve_prompt(self.store, prompt_en="warm sunrise over mountains", style="neon")
        self.assertTrue(p.startswith("warm sunrise over mountains"))
        self.assertTrue(hooks.ASCII_PROMPT.match(p.split(", no text")[0]))
        self.assertEqual(aibg.color_words(["#126F85"]), "deep teal")

    def test_every_style_and_preset_prompt_is_ascii_without_people_or_text(self):
        for k, text in list(hooks.BG_PROMPTS.items()) + [(k, v[1]) for k, v in aibg.PRESETS.items()]:
            self.assertTrue(hooks.ASCII_PROMPT.match(text), k)
        for k in hooks.BG_PROMPTS:
            self.assertIn("no people", hooks.bg_prompt(k))


class QueueTests(ThumbsApiBase):
    def test_no_comfy_node_registered(self):
        out = aibg.availability()
        self.assertFalse(out["possible"])
        r = self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("ComfyUI", r.json()["error"]["message"])

    def test_offline_node_parks_the_job_instead_of_failing(self):
        node(online=False)
        self.assertTrue(aibg.availability()["possible"])
        self.assertFalse(aibg.availability()["online"])
        r = self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        job = r.json()["jobs"][0]
        self.assertEqual(job["state"], "QUEUED")
        self.assertEqual(job["message"], photo.WAIT_NODE)
        st = self.api.get(f"{self.base}/backgrounds/{job['job']}/").json()
        self.assertEqual(st["state"], "QUEUED")
        self.assertIn("منتظرِ سرورِ پردازش", st["message"])
        j = ComputeJob.objects.get(uid=job["job"])
        self.assertEqual(j.kind, "comfy.graph")
        self.assertEqual(j.origin, aibg.ORIGIN)
        self.assertEqual(j.payload["x_thumbbg"]["size"], [1344, 768])
        self.assertIn("SaveImage", {n["class_type"] for n in j.payload["graph"].values()})

    def test_online_flow_creates_a_library_asset_once(self):
        n = node()
        r = self.api.post(f"{self.base}/backgrounds/", {"preset": "pastel_paper", "format": "story", "use_brand": True}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        uid = r.json()["jobs"][0]["job"]
        self.assertIn("pastel", r.json()["prompt"])
        job = ComputeJob.objects.get(uid=uid)
        aibg.finish_for_test(job, n)
        st = self.api.get(f"{self.base}/backgrounds/{uid}/").json()
        self.assertEqual(st["state"], "READY", st)
        aid = st["asset"]["id"]
        asset = PhotoAsset.objects.get(pk=aid)
        self.assertEqual((asset.width, asset.height), (768, 1344))
        self.assertEqual(asset.source_ref, f"thumbbg:{uid}")
        again = self.api.get(f"{self.base}/backgrounds/{uid}/").json()
        self.assertEqual(again["asset"]["id"], aid)
        self.assertEqual(PhotoAsset.objects.filter(source_ref=f"thumbbg:{uid}").count(), 1)

    def test_failed_job_has_a_persian_reason(self):
        n = node()
        uid = self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json").json()["jobs"][0]["job"]
        aibg.finish_for_test(ComputeJob.objects.get(uid=uid), n, error="CUDA out of memory (oom)")
        st = self.api.get(f"{self.base}/backgrounds/{uid}/").json()
        self.assertEqual(st["state"], "FAILED")
        self.assertIn("حافظهٔ کارتِ گرافیک", st["error"])

    def test_cancel(self):
        node(online=False)
        uid = self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json").json()["jobs"][0]["job"]
        self.assertTrue(self.api.delete(f"{self.base}/backgrounds/{uid}/").json()["cancelled"])
        self.assertEqual(self.api.get(f"{self.base}/backgrounds/{uid}/").json()["state"], "CANCELLED")

    def test_limit_of_active_jobs(self):
        node(online=False)
        for _ in range(aibg.MAX_ACTIVE):
            self.assertEqual(self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json").status_code, 201)
        r = self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("پس‌زمینه", r.json()["error"]["message"])

    def test_node_missing_core_nodes_is_reported(self):
        node(caps={"comfyui": True, "comfy_nodes": ["KSampler"], "comfy_models": {"checkpoints": [ig.DEFAULT_DEV_CKPT], "unet": []}})
        r = self.api.post(f"{self.base}/backgrounds/", {"preset": "studio_light", "format": "youtube"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("نودهای ComfyUI", r.json()["error"]["message"])


class WaitingThumbnailTests(ThumbsApiBase):
    SPEC_AI = {**SPEC, "background": {"kind": "ai"}}

    def test_thumbnail_waits_then_completes_by_itself(self):
        n = node()
        body = self.render(self.SPEC_AI, ai={"preset": "studio_light"})
        item = body["items"][0]
        self.assertEqual(item["state"], "WAITING_BG")
        self.assertTrue(item["bg_job"])
        t = Thumbnail.objects.get(pk=item["id"])
        draft = (self.media / t.files["png"]).read_bytes()
        self.assertTrue(draft.startswith(b"\x89PNG"))                    # پیش‌نویس با پس‌زمینهٔ خودکار آماده است
        job = ComputeJob.objects.get(uid=item["bg_job"])
        self.assertIn("studio", job.payload["x_thumbbg"]["prompt"])
        # هنوز تمام نشده: وضعیت همان می‌ماند
        self.assertFalse(services.refresh(t))
        self.assertEqual(Thumbnail.objects.get(pk=t.pk).state, "WAITING_BG")
        # گره کار را تمام می‌کند؛ پنل (یا کارِ Celery) فقط می‌پرسد و تامنیل کامل می‌شود
        aibg.finish_for_test(job, n)
        got = self.api.get(f"{self.base}/items/{t.pk}/").json()
        self.assertEqual(got["state"], "READY", got)
        self.assertEqual(got["spec"]["background"]["kind"], "ai")
        self.assertIsNotNone(got["spec"]["background"]["asset"])
        self.assertEqual(got["spec"]["background"]["job"], "")
        final = (self.media / Thumbnail.objects.get(pk=t.pk).files["png"]).read_bytes()
        self.assertNotEqual(draft, final)
        names = [layer["name"] for layer in got["layers"]]
        self.assertIn("پس‌زمینه (عکس)", names)

    def test_list_endpoint_nudges_waiting_items(self):
        n = node()
        item = self.render(self.SPEC_AI)["items"][0]
        aibg.finish_for_test(ComputeJob.objects.get(uid=item["bg_job"]), n)
        listed = self.api.get(f"{self.base}/items/").json()["items"]
        self.assertEqual(listed[0]["state"], "READY")

    def test_node_failure_falls_back_with_a_warning(self):
        n = node()
        item = self.render(self.SPEC_AI)["items"][0]
        aibg.finish_for_test(ComputeJob.objects.get(uid=item["bg_job"]), n, error="ComfyUI unavailable (refused)")
        got = self.api.get(f"{self.base}/items/{item['id']}/").json()
        self.assertEqual(got["state"], "READY")
        self.assertEqual(got["spec"]["background"]["kind"], "auto")
        self.assertTrue(any("ComfyUI" in w for w in got["warnings"]), got["warnings"])

    def test_no_node_at_all_still_renders_with_auto_background(self):
        item = self.render(self.SPEC_AI)["items"][0]
        self.assertEqual(item["state"], "READY")
        self.assertTrue(any("پس‌زمینهٔ هوش مصنوعی ممکن نشد" in w for w in item["warnings"]))
        self.assertEqual(item["spec"]["background"]["kind"], "auto")

    def test_offline_node_keeps_the_thumbnail_waiting_without_losing_it(self):
        node(online=False)
        item = self.render(self.SPEC_AI)["items"][0]
        self.assertEqual(item["state"], "WAITING_BG")
        got = self.api.get(f"{self.base}/items/{item['id']}/").json()
        self.assertEqual(got["state"], "WAITING_BG")
        self.assertIn("منتظرِ سرورِ پردازش", got["message"])
        # بعد از روشن‌شدنِ گره همان کار (که از قبل در صف بود) انجام می‌شود
        n = ComputeNode.objects.get()
        n.last_seen = timezone.now()
        n.save()
        aibg.finish_for_test(ComputeJob.objects.get(uid=item["bg_job"]), n)
        self.assertEqual(self.api.get(f"{self.base}/items/{item['id']}/").json()["state"], "READY")

    def test_ready_background_asset_can_be_reused_across_variants(self):
        n = node()
        uid = self.api.post(f"{self.base}/backgrounds/", {"preset": "luxury_dark", "format": "youtube"}, format="json").json()["jobs"][0]["job"]
        aibg.finish_for_test(ComputeJob.objects.get(uid=uid), n, size=(1344, 768))
        aid = self.api.get(f"{self.base}/backgrounds/{uid}/").json()["asset"]["id"]
        body = self.render({**SPEC, "background": {"kind": "ai", "asset": aid}}, variants=2)
        for it in body["items"]:
            self.assertEqual(it["state"], "READY")
            self.assertIn("پس‌زمینه (عکس)", [layer["name"] for layer in it["layers"]])


class SelfTestSpecTests(ThumbsApiBase):
    def test_selftest_spec_and_check(self):
        from . import selftest

        n = node()
        spec = selftest.spec(n.capabilities)
        self.assertEqual(spec["kind"], "comfy.graph")
        self.assertEqual(spec["expect"]["size"], list(selftest.SIZE))
        job = compute.enqueue(spec["kind"], spec["payload"], {}, store=None, origin=spec["origin"], require_online=False, timeout_s=spec["timeout_s"], dedupe=False)
        aibg.finish_for_test(job, n, size=selftest.SIZE)
        job.refresh_from_db()
        ok, msg = selftest.check(job)
        self.assertTrue(ok, msg)
        flat = compute.enqueue(spec["kind"], dict(spec["payload"], x_n=1), {}, store=None, origin=spec["origin"], require_online=False, dedupe=False)
        aibg.finish_for_test(flat, n, size=selftest.SIZE, flat=True)
        flat.refresh_from_db()
        ok, msg = selftest.check(flat)
        self.assertFalse(ok)
        self.assertIn("خالی", msg)
        wrong = compute.enqueue(spec["kind"], dict(spec["payload"], x_n=2), {}, store=None, origin=spec["origin"], require_online=False, dedupe=False)
        aibg.finish_for_test(wrong, n, size=(320, 320))
        wrong.refresh_from_db()
        self.assertFalse(selftest.check(wrong)[0])


class SelfTestAutoTests(ThumbsApiBase):
    """اجرای خودکارِ آزمون: گره روشن شد ⇒ بدونِ هیچ کارِ دستی آزموده می‌شود و نتیجه در پنل می‌آید."""

    def test_no_comfy_node_nothing_enqueued_and_status_says_why(self):
        from . import selftest

        out = selftest.auto_step()
        self.assertEqual(out["action"], "skip")
        self.assertFalse(ComputeJob.objects.filter(origin=selftest.ORIGIN).exists())
        self.assertEqual(selftest.status()["state"], "none")

    def test_fill_only_model_is_reported_not_enqueued(self):
        from . import selftest

        node(caps={"comfyui": True, "comfy_models": {"checkpoints": ["FLUX.1-Fill-dev.safetensors"], "unet": []}})
        out = selftest.auto_step()
        self.assertEqual(out["action"], "skip")
        self.assertIn("FLUX", out["why"])

    def test_offline_node_job_is_parked_then_judged_and_retested(self):
        from datetime import timedelta

        from . import selftest

        n = node(online=False)
        first = selftest.auto_step()
        self.assertEqual(first["action"], "enqueued")
        self.assertEqual(selftest.auto_step()["action"], "wait")                  # دوباره صف نمی‌گذارد
        self.assertEqual(selftest.status()["state"], "waiting")
        self.assertEqual(ComputeJob.objects.filter(origin=selftest.ORIGIN).count(), 1)
        # گره روشن شد و کار را کرد
        job = selftest.latest()
        aibg.finish_for_test(job, n, size=selftest.SIZE)
        out = selftest.auto_step()
        self.assertEqual(out, {"action": "idle", "ok": True})
        st = selftest.status()
        self.assertEqual(st["state"], "ok")
        self.assertIn("قبول", st["message"])
        job.refresh_from_db()
        self.assertTrue(job.result["selftest"]["ok"])                              # نتیجه روی خودِ کار ذخیره شد (در «صفِ پردازش» دیده می‌شود)
        # هفته‌ای یک بار دوباره
        later = timezone.now() + timedelta(seconds=selftest.RETEST_OK_S + 60)
        self.assertEqual(selftest.auto_step(now=later)["action"], "enqueued")
        self.assertEqual(ComputeJob.objects.filter(origin=selftest.ORIGIN).count(), 2)

    def test_failed_selftest_is_visible_and_retried_after_six_hours(self):
        from datetime import timedelta

        from . import selftest

        n = node()
        selftest.auto_step()
        aibg.finish_for_test(selftest.latest(), n, error="Value not in list: ckpt_name")
        st = selftest.status()
        self.assertEqual(st["state"], "failed")
        self.assertIn("رد شد", st["message"])
        self.assertEqual(selftest.auto_step()["action"], "idle")
        self.assertEqual(selftest.auto_step(now=timezone.now() + timedelta(hours=7))["action"], "enqueued")

    def test_overview_carries_the_selftest_line_and_beat_is_registered(self):
        from django.conf import settings

        from . import selftest, tasks

        node(online=False)
        selftest.auto_step()
        body = self.api.get(f"{self.base}/").json()
        self.assertEqual(body["ai_background"]["selftest"]["state"], "waiting")
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["thumbs-selftest"]["task"], "apps.thumbs.tasks.selftest_when_online")
        self.assertEqual(tasks.selftest_when_online()["action"], "wait")


class SelfTestCommandTests(ThumbsApiBase):
    def test_command_enqueues_waits_and_reports(self):
        from io import StringIO

        from django.core.management import call_command

        from . import selftest

        n = node()
        out = StringIO()
        call_command("thumbs_selftest", stdout=out)
        job = selftest.latest()
        self.assertEqual(job.origin, selftest.ORIGIN)
        self.assertIn("در صف", out.getvalue())
        # دوباره صدا زدن، تا وقتی کارِ قبلی باز است، کارِ تازه نمی‌گذارد
        aibg.finish_for_test(job, n, size=selftest.SIZE)
        out = StringIO()
        call_command("thumbs_selftest", no_enqueue=True, stdout=out)
        self.assertIn("قبول", out.getvalue())


class CentralSelfTestTests(ThumbsApiBase):
    """ثبتِ آزمونِ «thumbs_bg» در آزمونِ پذیرشِ خودکارِ سرورِ پردازش (apps.compute.selftests)."""

    def test_registered_available_build_and_check(self):
        from apps.compute.models import SelfTestRun
        from apps.compute.selftests import REGISTRY, Ctx, load_all

        from . import selftest

        load_all()
        self.assertIn("thumbs_bg", REGISTRY)
        t = REGISTRY["thumbs_bg"]
        self.assertEqual(t.kind, "comfy.graph")
        self.assertTrue(t.optional and t.gpu_required)
        self.assertIn("comfy_flux", t.after)
        # گره‌ای که ComfyUI ندارد: «ردشده» با علتِ فارسی، نه «رد»
        bare = node(caps={"kinds": ["comfy.graph"]}, name="gpu-bare")
        self.assertFalse(t.available(bare)[0])
        self.assertTrue(t.available(bare)[1])
        # گرهٔ درست: ساختِ کارِ واقعی و سنجشِ خروجی
        n = node()
        self.assertTrue(t.available(n)[0])
        run = SelfTestRun.objects.create(node=n, trigger="manual")
        ctx = Ctx(n, run, {})
        spec = t.build(ctx)
        self.assertEqual(spec.kind, "comfy.graph")
        self.assertEqual(spec.payload["x_thumbbg"]["size"], list(selftest.SIZE))
        job = compute.enqueue(spec.kind, spec.payload, {}, store=None, origin="selftest-thumbbg-central", require_online=False, dedupe=False)
        aibg.finish_for_test(job, n, size=selftest.SIZE)
        job.refresh_from_db()
        v = t.check(ctx, job)
        self.assertTrue(v.ok, v.detail)
        # مدلِ FLUX dev نیست (فقط Fill): ساخت None می‌دهد و علتِ فارسی روی نتیجه می‌ماند
        fill = node(caps={"comfyui": True, "comfy_models": {"checkpoints": ["FLUX.1-Fill-dev.safetensors"], "unet": []}}, name="gpu-fill")
        res = SelfTestRun.objects.create(node=fill, trigger="manual")
        from apps.compute.models import SelfTestResult
        row = SelfTestResult.objects.create(run=res, key="thumbs_bg", label="x", started_at=timezone.now())
        self.assertIsNone(t.build(Ctx(fill, res, {}, result=row)))
        self.assertTrue((row.extra or {}).get("why"))

