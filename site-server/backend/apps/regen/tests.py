"""«بازسازیِ یک تکه»: نقشه، گراف، و کلِ گردشِ API با یک ویدیوی واقعی و یک «سرورِ پردازشِ» شبیه‌سازی‌شده.

سرورِ پردازش این‌جا همان کاری را می‌کند که agent.py با کارِ comfy.graph می‌کند — کار را با compute.claim
می‌گیرد، PNG ِ خروجی‌ها را با نام‌هایی که SaveImage ِ ComfyUI می‌سازد («c0_00001_.png») در پوشهٔ خروجیِ کار
می‌گذارد و compute.finish می‌زند — فقط به‌جای مدل، فریم‌های همان لحظه از منبع را با سوگیریِ رنگ و نرمی می‌دهد.
"""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth.models import User
from django.core.files import File
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.content.models import UploadedVideo
from apps.stores.models import Store
from services.video.regen import media, plan as planmod, stitch
from services.video.regen.selftest import FakeModel, make_clip

from . import services
from .models import RegenSession, RegenVersion

TMP = Path(tempfile.mkdtemp(prefix="nmregen-tests-"))
CLIP = TMP / "clip.mp4"


def setUpModule():
    make_clip(CLIP, fps="16", seconds=4, size="320x192")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def _info(n=300, fps=30.0, w=1280, h=720):
    from fractions import Fraction

    f = Fraction(fps).limit_denominator(1001)
    return {"n_frames": n, "fps": float(f), "fps_num": f.numerator, "fps_den": f.denominator,
            "width": w, "height": h, "time_base": "1/15360", "format_start": 0.0, "video_start": 0.0,
            "frame_pts": [int(round(i * 15360 / float(f))) for i in range(n)]}


class PlanTests(TestCase):
    def test_short_range_is_one_flf_chunk_landing_on_both_neighbours(self):
        p = planmod.make_plan(_info(), 100, 159)            # ۲ ثانیه در ۳۰fps
        self.assertEqual(p["before"], 99)
        self.assertEqual(p["after"], 160)
        self.assertEqual(p["model_fps"], 15.0)             # ۳۰ ⇐ ۱۵ (نزدیک به ۱۶، مقسومِ ۳۰)
        self.assertEqual(p["G"] % 4, 0)
        self.assertEqual(len(p["chunks"]), 1)
        self.assertEqual(p["chunks"][0]["length"], p["G"] + 1)
        self.assertEqual((p["chunks"][0]["length"] - 1) % 4, 0)
        self.assertEqual(len(p["positions"]), 60)
        self.assertTrue(all(0 < s < p["G"] for s in p["positions"]))
        self.assertLess(abs(p["speed"] - 1), 0.1)

    def test_long_range_is_chained_and_every_chunk_fits_the_model(self):
        p = planmod.make_plan(_info(n=900), 100, 699, context=5)   # ۲۰ ثانیه
        self.assertGreater(len(p["chunks"]), 1)
        for c in p["chunks"]:
            self.assertLessEqual(c["length"], 81)
            self.assertEqual((c["length"] - 1) % 4, 0)
        self.assertEqual(p["chunks"][-1]["p1"], p["G"])
        self.assertEqual(p["start_ctx"][-1], 99)
        self.assertEqual(p["end_ctx"][0], 700)
        self.assertEqual(len(p["start_ctx"]), 5)

    def test_fps_choice(self):
        self.assertEqual(planmod.model_fps(30), 15)
        self.assertEqual(planmod.model_fps(60), 15)
        self.assertEqual(planmod.model_fps(32), 16)
        self.assertEqual(planmod.model_fps(25), 16)        # ۱۲٫۵ خیلی دور است ⇐ ۱۶ و درون‌یابی

    def test_edges_and_limits(self):
        p = planmod.make_plan(_info(), 0, 40)              # از اولِ ویدیو: فقط فریمِ انتها
        self.assertFalse(p["has_start"])
        self.assertTrue(p["has_end"])
        with self.assertRaises(planmod.PlanError):
            planmod.make_plan(_info(), 0, 299)             # کلِ ویدیو
        with self.assertRaises(planmod.PlanError):
            planmod.make_plan(_info(n=2000), 10, 1500)     # بیش از ۲۰ ثانیه

    def test_padding_round_trip_is_exact_geometry(self):
        p = planmod.make_plan(_info(w=1920, h=1080), 100, 130)
        frame = (np.random.default_rng(1).random((1080, 1920, 3)) * 255).astype(np.uint8)
        back = stitch.from_model(stitch.to_model(frame, p), p, 1920, 1080)
        self.assertEqual(back.shape, frame.shape)
        # کوچک‌کردن و بزرگ‌کردن جزئیات را می‌برد، ولی جابه‌جایی نباید باشد: میانگینِ بلوک‌ها جفت است
        blocks = lambda img: img.reshape(27, 40, 48, 40, 3).mean(axis=(1, 3))  # noqa: E731
        self.assertLess(np.abs(blocks(back.astype(float)) - blocks(frame.astype(float))).mean(), 2.0)


class GraphTests(TestCase):
    def _check_links(self, graph):
        for nid, node in graph.items():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], graph, f"node {nid} points to missing {value[0]}")

    def test_wan22_graph_chains_chunks_and_saves_each(self):
        p = planmod.make_plan(_info(n=900), 100, 450)
        g = planmod.build_graph(p, prompt="a cat turns its head", seed=5, start_names=["s0.png"], end_names=["e0.png"],
                                prefix="nmregen/t", models={"loras": ["wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
                                                                    "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"]})
        self._check_links(g)
        classes = [n["class_type"] for n in g.values()]
        self.assertEqual(classes.count("WanFirstLastFrameToVideo"), len(p["chunks"]))
        self.assertEqual(classes.count("SaveImage"), len(p["chunks"]))
        self.assertEqual(classes.count("ImageFromBatch"), len(p["chunks"]) - 1)
        flf = [n for n in g.values() if n["class_type"] == "WanFirstLastFrameToVideo"]
        self.assertIn("end_image", flf[-1]["inputs"])
        self.assertNotIn("end_image", flf[0]["inputs"])
        self.assertEqual([n["inputs"]["length"] for n in flf], [c["length"] for c in p["chunks"]])
        ks = [n for n in g.values() if n["class_type"] == "KSamplerAdvanced"]
        self.assertEqual({k["inputs"]["steps"] for k in ks}, {4})
        prefixes = sorted(n["inputs"]["filename_prefix"] for n in g.values() if n["class_type"] == "SaveImage")
        self.assertEqual(prefixes, [f"nmregen/t/c{i}" for i in range(len(p["chunks"]))])

    def test_fallback_lora_and_fun_inp_graph(self):
        p = planmod.make_plan(_info(), 100, 140, engine="wan22_flf")
        g = planmod.build_graph(p, prompt="x", start_names=["s.png"], end_names=["e.png"],
                                models={"loras": ["wan/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"]})
        loras = {n["inputs"]["lora_name"] for n in g.values() if n["class_type"] == "LoraLoaderModelOnly"}
        self.assertEqual(loras, {"wan/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"})
        p2 = planmod.make_plan(_info(), 100, 140, engine="fun_inp_13b", context=5)
        g2 = planmod.build_graph(p2, prompt="x", start_names=[f"s{i}.png" for i in range(5)],
                                 end_names=[f"e{i}.png" for i in range(5)])
        self._check_links(g2)
        classes = [n["class_type"] for n in g2.values()]
        self.assertIn("WanFunInpaintToVideo", classes)
        self.assertIn("CLIPVisionEncode", classes)
        self.assertEqual(classes.count("LoadImage"), 10)
        idx = [n["inputs"]["batch_index"] for n in g2.values() if n["class_type"] == "ImageFromBatch"]
        self.assertTrue(all(i >= 0 for i in idx))              # بی اندیسِ منفی (ComfyUI ِ قدیمی)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class FlowTests(TestCase):
    """کلِ مسیر از API، با ویدیوی واقعی (ffmpeg) و گرهٔ شبیه‌سازی‌شده."""

    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmregen-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmregen-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data)
        self.override.enable()
        self.owner = User.objects.create_user("regen-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ آزمون")
        self.client.force_login(self.owner)
        with open(CLIP, "rb") as fh:
            self.upload = UploadedVideo(store=self.store, title="کلیپ")
            self.upload.video.save("clip.mp4", File(fh), save=True)
        self.node = ComputeNode.objects.create(
            name="gpu-test", last_seen=timezone.now(),
            capabilities={"comfyui": True, "comfy_nodes": ["WanFirstLastFrameToVideo", "WanFunInpaintToVideo"],
                          "comfy_models": {"unet": [planmod.WAN22["high"], planmod.WAN22["low"], planmod.FUN13["unet"]],
                                           "loras": [planmod.WAN22["lora_high"], planmod.WAN22["lora_low"]]}})
        self.base = f"/api/v1/stores/{self.store.pk}/regen"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def _open(self):
        r = self.client.post(f"{self.base}/sessions/", {"source": f"upload:{self.upload.pk}"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["session"]

    def _node_does(self, job_uid, **model_kw):
        """گره: کار را می‌گیرد، «مدل» را اجرا می‌کند، PNGها را بالا می‌فرستد، تمام."""
        job = compute.claim(self.node)
        self.assertIsNotNone(job)
        self.assertEqual(str(job.uid), job_uid)
        self.assertEqual(job.kind, "comfy.graph")
        graph = job.payload["graph"]
        for name in job.payload["uploads"]:          # همان چیزی که agent.py به ComfyUI می‌دهد
            self.assertTrue((compute.job_root(job) / "inputs" / name).is_file())
        v = RegenVersion.objects.get(compute_job=job_uid)
        path, info = services.base_of(v.session, v)
        p = planmod.make_plan(info, v.start_frame, v.end_frame, engine=v.engine, quality=v.quality,
                              context=v.context)
        saves = sorted(n["inputs"]["filename_prefix"] for n in graph.values() if n["class_type"] == "SaveImage")
        self.assertEqual(len(saves), len(p["chunks"]))
        tmp = Path(tempfile.mkdtemp())
        files = FakeModel(path, info, p, **model_kw).render(tmp)
        for chunk, paths in files.items():
            for k, src in enumerate(paths):
                with open(src, "rb") as fh:
                    compute.save_output(job, f"c{chunk}_{k + 1:05d}_.png", fh)
        compute.finish(job, self.node, True, meta={"engine": "comfyui"})
        shutil.rmtree(tmp, ignore_errors=True)

    def test_full_flow_from_api(self):
        overview = self.client.get(f"{self.base}/").json()
        self.assertIn(f"upload:{self.upload.pk}", [s["ref"] for s in overview["sources"]])
        self.assertTrue(any(e["ready"] for e in overview["engines"]))

        s = self._open()
        self.assertEqual(s["state"], "READY", s)
        self.assertEqual(s["info"]["n_frames"], 64)
        self.assertTrue(s["smart_splice"])
        self.assertTrue(s["filmstrip"]["url"])
        # همان ویدیو دوباره ⇐ همان جلسه
        self.assertEqual(self._open()["id"], s["id"])

        r = self.client.get(f"{self.base}/sessions/{s['id']}/frame/", {"n": 20, "w": 160})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertTrue(r.content[:2] == b"\xff\xd8")

        est = self.client.get(f"{self.base}/sessions/{s['id']}/estimate/", {"start": 24, "end": 39}).json()
        self.assertEqual(est["plan"]["count"], 16)
        self.assertGreater(est["estimate"]["total_seconds"], 0)

        r = self.client.post(f"{self.base}/sessions/{s['id']}/versions/",
                             {"start": 24, "end": 39, "prompt": "the ball bounces higher", "seed": 42},
                             content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        v = r.json()["version"]
        self.assertEqual(v["state"], "GENERATING", v)
        self.assertIn("the ball bounces higher", v["model_prompt"])
        self.assertTrue(v["urls"]["frame_before"])

        # یک نسخهٔ هم‌زمان دیگر پذیرفته نمی‌شود
        r2 = self.client.post(f"{self.base}/sessions/{s['id']}/versions/", {"start": 5, "end": 9},
                              content_type="application/json")
        self.assertEqual(r2.status_code, 400)

        job_uid = RegenVersion.objects.get(pk=v["id"]).compute_job
        self._node_does(job_uid)
        v = self.client.get(f"{self.base}/versions/{v['id']}/").json()["version"]
        self.assertEqual(v["state"], "READY", v["error"])
        for key in ("result", "after", "before", "piece", "frame_before", "frame_after"):
            self.assertTrue(v["urls"][key], key)
        self.assertEqual(v["assemble"]["method"], "smart")
        self.assertTrue(all(c["ok"] for c in v["assemble"]["checks"].values()), v["assemble"])
        self.assertIn(v["seams"]["verdict"], ("invisible", "slight"), v["seams"])

        version = RegenVersion.objects.get(pk=v["id"])
        result = services.abs_path(version.files["result"])
        original = services.abs_path(version.session.original)
        self.assertEqual(media.count_frames(result), 64)
        self.assertEqual(media.audio_md5(result), media.audio_md5(original))
        # فریم‌های مدل بعد از چسباندن پاک شدند
        job = ComputeJob.objects.get(uid=version.compute_job)
        self.assertFalse(list((compute.job_root(job) / "outputs").glob("*.png")))

        # قبول ⇐ پایهٔ نسخهٔ بعد و منبعِ تازه در فهرست
        r = self.client.post(f"{self.base}/versions/{v['id']}/accept/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(RegenSession.objects.get(pk=s["id"]).current_id, v["id"])
        sources = self.client.get(f"{self.base}/").json()["sources"]
        self.assertIn(f"regen:{v['id']}", [x["ref"] for x in sources])
        r = self.client.post(f"{self.base}/sessions/{s['id']}/versions/", {"start": 8, "end": 11, "prompt": "x"},
                             content_type="application/json")
        v2 = RegenVersion.objects.get(pk=r.json()["version"]["id"])
        self.assertEqual(v2.base_id, v["id"])
        r = self.client.post(f"{self.base}/versions/{v2.pk}/cancel/")
        self.assertEqual(r.json()["version"]["state"], "CANCELLED")
        self.assertEqual(ComputeJob.objects.get(uid=v2.compute_job).state, "CANCELLED")

        # دور انداختنِ نسخهٔ قبول‌شده ⇐ پایه به اصل برمی‌گردد
        self.client.post(f"{self.base}/versions/{v['id']}/discard/")
        self.assertIsNone(RegenSession.objects.get(pk=s["id"]).current_id)
        self.assertFalse(result.exists())

    def test_node_failure_marks_version_failed(self):
        s = self._open()
        v = self.client.post(f"{self.base}/sessions/{s['id']}/versions/", {"start": 10, "end": 20},
                             content_type="application/json").json()["version"]
        job = compute.claim(self.node)
        job.max_attempts = 1
        job.save(update_fields=["max_attempts"])
        compute.finish(job, self.node, False, error="CUDA out of memory")
        v = self.client.get(f"{self.base}/versions/{v['id']}/").json()["version"]
        self.assertEqual(v["state"], "FAILED")
        self.assertIn("out of memory", v["error"])

    def test_persian_prompt_falls_back_when_no_text_model(self):
        with patch("services.ai.gateway.text_provider", side_effect=RuntimeError("no ollama")):
            prompt, source = services.model_prompt(self.store, "توپ آرام بالا می‌رود")
        self.assertEqual(source, "fallback")
        self.assertIn("توپ", prompt)
        self.assertIn("smooth natural continuous motion", prompt)

    def test_other_shops_cannot_see_or_use_it(self):
        s = self._open()
        other = User.objects.create_user("intruder", password="x")
        Store.objects.create(owner=other, name="دیگری")
        self.client.force_login(other)
        self.assertIn(self.client.get(f"{self.base}/sessions/{s['id']}/").status_code, (403, 404))
        r = self.client.post(f"{self.base}/sessions/", {"source": f"upload:{self.upload.pk}"},
                             content_type="application/json")
        self.assertIn(r.status_code, (403, 404))

    def test_bad_ranges_are_refused(self):
        s = self._open()
        for body in ({"start": 0, "end": 63}, {"start": 30, "end": 20}, {"start": 5}):
            r = self.client.post(f"{self.base}/sessions/{s['id']}/versions/", body, content_type="application/json")
            self.assertEqual(r.status_code, 400, body)
            self.assertTrue(r.json()["error"]["message"])
