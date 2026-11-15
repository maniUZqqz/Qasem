"""تصویرِ نمونهٔ واقعیِ سبک‌ها: دسته‌های ۱۲تایی در صفِ ماندگار، گرهٔ خاموش، برداشتنِ نتیجه، تصویرِ خراب، دستورِ کهنه، خودآزمون."""
from __future__ import annotations

import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.compute.models import ComputeJob, ComputeNode
from apps.photoedit import inpaint_graph as ig
from apps.thumbs import aibg

from . import compose, library, samples, selftest

User = get_user_model()


def node(online: bool = True, caps=None, name="gpu-looks") -> ComputeNode:
    return ComputeNode.objects.create(name=name, last_seen=timezone.now() if online else None, capabilities=caps if caps is not None else aibg.fake_caps())


class SamplesBase(TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="nmlooks-samples-"))
        self.override = override_settings(NM_DATA_DIR=self.data)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.data, ignore_errors=True)

    def finish_all(self, n=None, **kw):
        n = n or ComputeNode.objects.first()
        for job in ComputeJob.objects.filter(origin=samples.ORIGIN, state=ComputeJob.State.QUEUED).order_by("created_at"):
            samples.finish_for_test(job, n, **kw)


class QueueTests(SamplesBase):
    def test_a_chunk_is_twelve_low_priority_comfy_graph_jobs_with_the_fixed_bottle_subject(self):
        n = node()
        self.assertEqual(len(samples.pending()), 116)
        res = samples.queue_chunk()
        self.assertEqual(len(res["queued"]), 12)
        jobs = list(ComputeJob.objects.filter(origin=samples.ORIGIN))
        self.assertEqual(len(jobs), 12)
        self.assertEqual({j.kind for j in jobs}, {"comfy.graph"})
        self.assertEqual({j.state for j in jobs}, {ComputeJob.State.QUEUED})
        self.assertGreater(min(j.priority for j in jobs), 100, "جلوی کارهای مالک را نمی‌گیرد")
        keys = [j.payload["x_looksample"]["key"] for j in jobs]
        self.assertEqual(len(set(keys)), 12)
        self.assertEqual(set(keys), set(list(library.STYLES)[:12]), "اولین دسته = ۱۲ سبکِ اولِ مرور")
        for j in jobs:
            g = j.payload["graph"]
            with mock.patch.dict(ig.OUTPUTS, {"EmptyLatentImage": 1}):
                self.assertEqual(ig.validate(g), [], j.payload["x_looksample"]["key"])
            text = g["20"]["inputs"]["text"]
            self.assertIn("plain unbranded matte white bottle", text)
            self.assertEqual(g["23"]["inputs"]["width"], samples.SIZE[0])
            self.assertTrue(samples.MIN_STEPS <= g["24"]["inputs"]["steps"] <= samples.MAX_STEPS)
            self.assertTrue(2.0 <= g["21"]["inputs"]["guidance"] <= 5.0)
            self.assertEqual(j.payload["x_looksample"]["hash"], samples.prompt_hash(j.payload["x_looksample"]["key"]))
        self.assertTrue(n.has("comfyui"))

    def test_the_sample_prompt_is_the_look_without_people_or_text_words(self):
        for key in library.STYLES:
            pos, neg, hints = samples.prompt_for(key)
            self.assertTrue(pos.startswith(samples.SUBJECT), key)
            rest = pos[len(samples.SUBJECT):]
            for frag in rest.split(","):
                self.assertIsNone(compose.SUBJECT_FRAGMENT.search(frag), (key, frag))
                self.assertIsNone(compose.TEXT_FRAGMENT.search(frag), (key, frag))
            self.assertIn("text", neg)

    def test_an_offline_node_still_gets_the_chunk_waiting_in_the_durable_queue(self):
        node(online=False)
        res = samples.queue_chunk()
        self.assertEqual(len(res["queued"]), 12)
        self.assertEqual(ComputeJob.objects.filter(origin=samples.ORIGIN, state=ComputeJob.State.QUEUED).count(), 12)
        st = samples.status()
        self.assertTrue(st["possible"])
        self.assertFalse(st["online"])
        self.assertEqual(st["active"], 12)

    def test_no_comfy_node_registered_queues_nothing_and_explains_in_persian(self):
        res = samples.queue_chunk()
        self.assertEqual(res["queued"], [])
        self.assertTrue(res["skipped"])
        self.assertEqual(ComputeJob.objects.count(), 0)
        self.assertEqual(samples.auto_step()["action"], "skip")
        self.assertFalse(samples.status()["possible"])

    def test_a_node_with_only_the_fill_model_cannot_make_samples_and_says_why(self):
        node(caps={"comfyui": True, "comfy_models": {"checkpoints": ["FLUX.1-Fill-dev.safetensors"], "unet": []}, "comfy_nodes": ["KSampler"]})
        res = samples.queue_chunk()
        self.assertEqual(res["queued"], [])
        self.assertIn("FLUX", res["skipped"])

    def test_missing_comfy_nodes_are_reported_and_nothing_is_queued(self):
        node(caps={"comfyui": True, "comfy_nodes": ["KSampler"], "comfy_models": {"checkpoints": [ig.DEFAULT_DEV_CKPT], "unet": []}})
        res = samples.queue_chunk()
        self.assertEqual(res["queued"], [])
        self.assertIn("نودهای ComfyUI", res["skipped"])

    def test_off_switch(self):
        node()
        with mock.patch.dict("os.environ", {"NM_LOOKS_SAMPLES_AUTO": "0"}):
            self.assertEqual(samples.auto_step()["action"], "off")
        self.assertEqual(ComputeJob.objects.count(), 0)


class AutoLoopTests(SamplesBase):
    def test_chunks_follow_each_other_without_anyone_pressing_anything(self):
        n = node()
        first = samples.auto_step()
        self.assertEqual((first["action"], first["queued"]), ("enqueued", 12))
        again = samples.auto_step()
        self.assertEqual(again["action"], "wait", "تا دسته تمام نشده دستهٔ دیگری نمی‌گذارد")
        self.assertEqual(ComputeJob.objects.filter(origin=samples.ORIGIN).count(), 12)
        self.finish_all(n)
        second = samples.auto_step()
        self.assertEqual(sorted(second["stored"]), sorted(list(library.STYLES)[:12]))
        self.assertEqual((second["action"], second["queued"]), ("enqueued", 12))
        self.assertEqual(len(samples.pending()), 116 - 12, "«منتظرِ عکس» یعنی عکس ندارد؛ کارِ در صف هنوز عکس نیست")
        urls = samples.sample_urls()
        self.assertEqual(set(urls), set(list(library.STYLES)[:12]))
        for key in urls:
            p = samples.sample_path(key)
            with Image.open(p) as im:
                self.assertEqual(im.format, "JPEG")
                self.assertLessEqual(im.width, samples.SIZE[0])
        keys2 = [j.payload["x_looksample"]["key"] for j in ComputeJob.objects.filter(origin=samples.ORIGIN, state=ComputeJob.State.QUEUED)]
        self.assertEqual(set(keys2), set(list(library.STYLES)[12:24]))

    def test_harvest_is_idempotent(self):
        n = node()
        samples.queue_chunk(limit=3)
        self.finish_all(n)
        a = samples.harvest()
        b = samples.harvest()
        self.assertEqual(len(a["stored"]), 3)
        self.assertEqual(b, {"stored": [], "failed": []})

    def test_a_flat_picture_is_not_kept_and_is_not_retried_for_hours(self):
        n = node()
        samples.queue_chunk(limit=2)
        self.finish_all(n, flat=True)
        got = samples.harvest()
        self.assertEqual(len(got["failed"]), 2)
        self.assertEqual(samples.sample_urls(), {})
        todo = samples.pending()
        self.assertEqual(len(todo), 116 - 2, "تا چند ساعت دوباره امتحان نمی‌شود")
        idx = samples.load_index()
        for k in got["failed"]:
            idx[k]["failed_at"] = time.time() - (samples.AUTO_RETRY_H + 1) * 3600
        samples.save_index(idx)
        self.assertEqual(len(samples.pending()), 116)

    def test_a_failed_job_is_recorded_not_looped_on(self):
        n = node()
        samples.queue_chunk(limit=1)
        self.finish_all(n, error="out of memory")
        got = samples.harvest()
        self.assertEqual(len(got["failed"]), 1)
        key = got["failed"][0]
        self.assertNotIn(key, samples.pending())
        self.assertIn("out of memory", samples.load_index()[key]["error"])
        self.assertEqual(samples.harvest(), {"stored": [], "failed": []})

    def test_a_changed_prompt_makes_the_old_picture_stale(self):
        n = node()
        samples.queue_chunk(limit=1)
        self.finish_all(n)
        key = samples.harvest()["stored"][0]
        self.assertNotIn(key, samples.pending())
        with mock.patch.object(samples, "SUBJECT", "a plain glass jar on a plain table"):
            self.assertIn(key, samples.pending())
        self.assertIn(key, samples.pending(force=True))

    def test_status_reports_progress_in_persian(self):
        n = node()
        samples.queue_chunk(limit=4)
        self.finish_all(n)
        samples.harvest()
        st = samples.status()
        self.assertEqual((st["total"], st["done"], st["pending"]), (116, 4, 112))
        self.assertTrue(st["message"])
        self.assertEqual(samples.summary()["done"], 4)

    def test_beat_task_runs_both_steps_and_never_raises(self):
        from . import tasks

        out = tasks.step()
        self.assertIn("samples", out)
        self.assertIn("selftest", out)
        with mock.patch.object(samples, "auto_step", side_effect=RuntimeError("boom")):
            out = tasks.step()
        self.assertEqual(out["samples"]["action"], "error")
        self.assertIn("selftest", out)


class SelftestTests(SamplesBase):
    def test_spec_is_a_512_graph_job_and_the_pass_check_is_real(self):
        s = selftest.spec(aibg.fake_caps())
        self.assertEqual(s["kind"], "comfy.graph")
        self.assertEqual(s["payload"]["graph"]["23"]["inputs"]["width"], 512)
        self.assertEqual(s["payload"]["graph"]["23"]["inputs"]["height"], 512)
        self.assertEqual(s["expect"], {"size": [512, 512], "min_bytes": 10_000, "min_std": 6.0})
        self.assertIn("plain unbranded matte white bottle", s["payload"]["graph"]["20"]["inputs"]["text"])
        n = node()
        job = selftest.enqueue()
        self.assertEqual(job.origin, selftest.ORIGIN)
        samples.finish_for_test(job, n, size=(512, 512))
        job.refresh_from_db()
        ok, msg = selftest.check(job)
        self.assertTrue(ok, msg)
        self.assertIn("512×512", msg)

    def test_check_fails_on_flat_wrong_size_or_error(self):
        n = node()
        for kw, word in (({"flat": True}, "یک‌رنگ"), ({"size": (256, 256)}, "اندازه"), ({"error": "boom"}, "ناموفق")):
            job = selftest.enqueue()
            samples.finish_for_test(job, n, **({"size": (512, 512)} | kw))
            job.refresh_from_db()
            ok, msg = selftest.check(job)
            self.assertFalse(ok, kw)
            self.assertIn(word, msg)
            job.delete()

    def test_a_png_of_ten_kilobytes_or_less_fails(self):
        n = node()
        job = selftest.enqueue()
        samples.finish_for_test(job, n, size=(512, 512))
        job.refresh_from_db()
        with mock.patch.object(selftest, "MIN_BYTES", 10 ** 9):
            ok, msg = selftest.check(job)
        self.assertFalse(ok)
        self.assertIn("کوچک", msg)

    def test_auto_step_enqueues_waits_judges_and_retests_later(self):
        n = node()
        a = selftest.auto_step()
        self.assertEqual(a["action"], "enqueued")
        self.assertEqual(selftest.auto_step()["action"], "wait")
        self.assertEqual(selftest.status()["state"], "waiting")
        job = selftest.latest()
        samples.finish_for_test(job, n, size=(512, 512))
        st = selftest.status()
        self.assertEqual(st["state"], "ok", st)
        self.assertEqual(selftest.auto_step()["action"], "idle")
        later = timezone.now() + timedelta(seconds=selftest.RETEST_OK_S + 60)
        self.assertEqual(selftest.auto_step(now=later)["action"], "enqueued")

    def test_the_central_acceptance_registry_knows_the_looks_test(self):
        from apps.compute import selftests

        reg = selftests.load_all(force=True)
        t = reg["looks_sample"]
        self.assertEqual((t.kind, t.group, t.gpu_required, t.optional), ("comfy.graph", "image", True, True))
        self.assertIn("comfy_flux", t.after)
        ok, why = t.available(node(caps={"comfyui": True, "comfy_models": {"checkpoints": [ig.DEFAULT_DEV_CKPT]}}))
        self.assertTrue(ok, why)
        no_comfy = ComputeNode.objects.create(name="cpu-only", capabilities={"photo": True})
        self.assertFalse(t.available(no_comfy)[0])
