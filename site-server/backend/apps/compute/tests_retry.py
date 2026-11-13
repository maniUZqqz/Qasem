"""«پردازشِ دوباره» در صفِ پردازش + «مدل‌های سرورِ پردازش» (همهٔ بسته‌های دانلودی)."""
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs import retry as JR
from apps.jobs.models import Job
from apps.stores.models import Store

from . import model_packages as MP, queue as QV
from .models import ComputeJob, ComputeNode

TMP = tempfile.mkdtemp(prefix="nm-compute-retry-test-")


def _node(name="gpu-1", online=True, **caps):
    c = {"comfyui": True, "ollama": True, "voice": True, "agent": "2.7"}
    c.update(caps)
    return ComputeNode.objects.create(name=name, capabilities=c,
                                      last_seen=timezone.now() if online else timezone.now() - timedelta(hours=1))


def _cj(kind, state="FAILED", **kw):
    return ComputeJob.objects.create(kind=kind, state=state, error="boom" if state == "FAILED" else "",
                                     finished_at=timezone.now(), **kw)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class QueueRetryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("q-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")

    def _owner_job(self, state="FAILED"):
        job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION, state=state,
                                 context={"product_id": 5})
        ctx = dict(job.context)
        ctx["_task"] = {"name": "apps.content.tasks.generate_captions_task", "args": [job.id, 5, ["INSTAGRAM"]],
                        "kwargs": {}}
        Job.objects.filter(pk=job.pk).update(context=ctx)
        job.refresh_from_db()
        return job

    def test_new_compute_job_inside_a_task_gets_job_ref(self):
        JR._local.job_id = 42
        try:
            j = ComputeJob.objects.create(kind="ollama.generate")
        finally:
            JR._local.job_id = None
        self.assertEqual(j.job_ref, 42)
        self.assertIsNone(ComputeJob.objects.create(kind="ollama.generate").job_ref)

    def test_modes(self):
        owner = self._owner_job()
        self.assertEqual(QV.retry_mode(_cj("node.models")), "requeue")
        self.assertEqual(QV.retry_mode(_cj("voice.tts", origin="audio_studio")), "consumer")
        self.assertEqual(QV.retry_mode(_cj("ollama.generate", origin="ollama", job_ref=owner.pk)), "owner")
        self.assertEqual(QV.retry_mode(_cj("ollama.generate", origin="ollama")), "")       # کسی منتظرِ نتیجه نیست
        self.assertEqual(QV.retry_mode(_cj("ollama.generate", state="COMPLETED", job_ref=owner.pk)), "")
        busy = self._owner_job(state="QUEUED")                                               # کارِ اصلی دوباره در جریان است
        self.assertEqual(QV.retry_mode(_cj("comfy.graph", job_ref=busy.pk)), "")

    def test_owner_retry_resends_the_store_job(self):
        owner = self._owner_job()
        cj = _cj("ollama.generate", origin="ollama", job_ref=owner.pk)
        row = QV.listing("failed")["jobs"][0]
        self.assertTrue(row["can_retry"])
        self.assertEqual(row["retry_mode"], "owner")
        self.assertIn("تولید کپشن", row["retry_hint"])
        with mock.patch.object(JR, "retry") as sent:
            job, notice = QV.retry_ex(cj)
        sent.assert_called_once()
        self.assertEqual(sent.call_args[0][0].pk, owner.pk)
        self.assertIn("کارِ اصلی", notice)
        self.assertEqual(job.state, "FAILED")                       # خودِ این ردیف در تاریخچه می‌ماند

    def test_consumer_retry_puts_the_page_row_back_in_waiting(self):
        from apps.ai.models import AudioAsset

        cj = _cj("voice.tts", origin="audio_studio", store=self.store)
        asset = AudioAsset.objects.create(store=self.store, kind="SPEECH", status="FAILED", job_uid=cj.uid,
                                          error="MOSS-TTS: dtype")
        job, notice = QV.retry_ex(cj)
        self.assertEqual(job.state, "QUEUED")
        self.assertEqual(job.attempts, 0)
        self.assertEqual(job.error, "")
        asset.refresh_from_db()
        self.assertEqual(asset.status, "PENDING")
        self.assertEqual(asset.error, "")
        self.assertEqual(notice, QV.RETRY_NOTICE)

    def test_not_retryable_says_why(self):
        cj = _cj("ollama.generate", origin="ollama")
        with self.assertRaises(ValueError) as cm:
            QV.retry_ex(cj)
        self.assertIn("دوباره بزنید", str(cm.exception))

    def test_retry_many_sends_each_owner_once(self):
        owner = self._owner_job()
        _cj("ollama.generate", origin="ollama", job_ref=owner.pk)
        _cj("ollama.generate", origin="ollama", job_ref=owner.pk)
        _cj("node.models")
        _cj("ollama.generate", origin="ollama")
        with mock.patch.object(JR, "retry") as sent:
            out = QV.retry_many("FAILED")
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(out["retried"], 2)                          # کارِ اصلی + node.models
        self.assertEqual(out["skipped"], 2)

    def test_api(self):
        staff = get_user_model().objects.create_user("boss", "b@x.io", "pw", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        cj = _cj("node.models")
        r = c.post(f"/api/v1/compute/queue/{cj.uid}/retry/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["state"], "QUEUED")
        self.assertEqual(r.data["notice"], QV.RETRY_NOTICE)
        r = c.post("/api/v1/compute/queue/retry-failed/", {"state": "FAILED"}, format="json")
        self.assertEqual(r.status_code, 200)
        owner = self._owner_job()
        r = c.get("/api/v1/compute/store-jobs/?state=bad")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["jobs"][0]["id"], owner.pk)
        self.assertTrue(r.data["jobs"][0]["can_retry"])
        self.assertEqual(r.data["jobs"][0]["store"], "چغر")
        with mock.patch.object(JR, "_queue_problem", return_value=""), \
                mock.patch.object(JR, "_resolve") as res:
            res.return_value.apply_async.return_value = mock.Mock(id="t1")
            r = c.post(f"/api/v1/compute/store-jobs/{owner.pk}/retry/")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.data["state"], "QUEUED")
            r = c.post("/api/v1/compute/store-jobs/retry-all/", {"state": "failed"}, format="json")
            self.assertEqual(r.status_code, 200)
        plain = APIClient()
        plain.force_authenticate(self.owner)
        self.assertEqual(plain.get("/api/v1/compute/store-jobs/").status_code, 403)
        self.assertEqual(plain.post("/api/v1/compute/queue/retry-failed/").status_code, 403)


PKG_DIR = Path(tempfile.mkdtemp(prefix="nm-model-pkgs-"))
(PKG_DIR / "downloads").mkdir()
(PKG_DIR / "downloads" / "matting.json").write_text(json.dumps({
    "group": "matting", "packages": {"matting-isnet": "IS-Net general use", "matting-runtime": "onnxruntime-directml"},
    "items": [{"id": "matting:isnet", "package": "matting-isnet", "optional": True, "size": 178648008},
              {"id": "venv-matting", "package": "matting-runtime", "optional": True}]}), encoding="utf-8")
(PKG_DIR / "downloads" / "photo.json").write_text(json.dumps({
    "group": "photo", "items": [{"id": "photo:birefnet-lite", "package": "photo-background", "size": 224005088}]}),
    encoding="utf-8")
(PKG_DIR / "downloads" / "video.json").write_text(json.dumps({
    "group": "video", "packages": {"fun-inp": "Wan Fun-InP"},
    "items": [{"id": "v1", "package": "fun-inp", "optional": True, "size": 4392000000}]}), encoding="utf-8")


@override_settings(NM_PROCESSING_DIR=str(PKG_DIR), NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ModelPackagesTests(TestCase):
    def setUp(self):
        MP._cache.update(key=None, data=None)

    def test_catalog_reads_every_json_package(self):
        cat = MP.catalog()
        self.assertEqual(set(cat), {"matting-isnet", "matting-runtime", "photo-background", "fun-inp"})
        self.assertEqual(cat["matting-isnet"]["size_mb"], 170)
        self.assertTrue(cat["matting-isnet"]["optional"])
        self.assertFalse(cat["photo-background"]["optional"])

    def test_node_status_merges_caps_queue_and_progress(self):
        n = _node(models={"running": True, "progress": {"packages": ["fun-inp"]}, "packages": {
            "matting-isnet": {"installed": False, "optional": True, "total_mb": 170, "missing_mb": 170},
            "photo-background": {"installed": True, "total_mb": 213, "missing_mb": 0},
            "fun-inp": {"installed": False, "total_mb": 4189, "missing_mb": 4189},
            "moss-tts": {"installed": True, "title": "Persian speech", "total_mb": 14781, "missing_mb": 0}}})
        ComputeJob.objects.create(kind="node.models", node_wanted=n.name, message="منتظرِ بازهٔ شبانه",
                                  payload={"action": "download", "packages": ["matting-runtime"]})
        data = MP.for_node(n)
        groups = {g["key"]: {p["key"]: p for p in g["packages"]} for g in data["groups"]}
        self.assertEqual(list(groups), ["video", "voice", "matting"])      # ترتیبِ نمایش: تصویر، ویدیو، بزرگ‌کردن، کنترل، عمق، صدا، حذفِ پس‌زمینه
        m = groups["matting"]
        self.assertEqual(m["photo-background"]["state"], "installed")
        self.assertEqual(m["matting-isnet"]["state"], "missing")
        self.assertIn("IS-Net", m["matting-isnet"]["title"])
        self.assertEqual(m["matting-runtime"]["state"], "queued")
        self.assertEqual(m["matting-runtime"]["queued_text"], "منتظرِ بازهٔ شبانه")
        self.assertEqual(groups["video"]["fun-inp"]["state"], "downloading")
        self.assertEqual(groups["voice"]["moss-tts"]["state"], "installed")    # فقط در گزارشِ گره بود
        self.assertTrue(data["reported"])

    def test_old_node_without_report(self):
        n = _node(online=False)
        data = MP.for_node(n)
        self.assertFalse(data["reported"])
        states = {p["state"] for g in data["groups"] for p in g["packages"]}
        self.assertEqual(states, {"unknown"})

    def test_api_staff_only(self):
        _node()
        staff = get_user_model().objects.create_user("boss2", "b2@x.io", "pw", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        r = c.get("/api/v1/compute/models/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["nodes"][0]["node"]["name"], "gpu-1")
        plain = APIClient()
        plain.force_authenticate(get_user_model().objects.create_user("p", password="x"))
        self.assertEqual(plain.get("/api/v1/compute/models/").status_code, 403)
