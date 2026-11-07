"""photo.matting از سمتِ سایت: توانایی و ردیفِ کار، نگه‌داشتنِ کار تا نصب شدنِ مدل، وضعیت، دانلودِ زمان‌بندی‌شده، API."""
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import matting, queue as QV, services as SV
from .models import ComputeJob, ComputeNode, capability_for

TMP = tempfile.mkdtemp(prefix="nm-compute-matting-test-")


def caps(models=None, runtime=True, agent="2.7", **extra):
    c = {"agent": agent, "photo_matting": True,
         "matting_runtime": {"ok": runtime, "providers": ["Dml", "CPU"] if runtime else []},
         "matting_models": {k: {"state": "missing", "size_mb": matting.MODELS[k]["mb"]} for k in matting.ORDER}}
    for k, st in (models or {}).items():
        c["matting_models"][k] = st if isinstance(st, dict) else {"state": st}
    c.update(extra)
    return c


def node(name="gpu-1", online=True, **kw):
    return ComputeNode.objects.create(name=name, capabilities=caps(**kw),
                                      last_seen=timezone.now() if online else timezone.now() - timedelta(hours=2))


def photo_file():
    p = Path(TMP) / "in.jpg"
    p.write_bytes(b"\xff\xd8fake-jpeg")
    return str(p)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class MattingQueueTests(TestCase):
    def test_the_kind_has_its_own_capability_not_the_photo_kit(self):
        self.assertEqual(capability_for("photo.matting"), "photo_matting")
        self.assertEqual(capability_for("photo.edit"), "photo")
        self.assertEqual(capability_for("photo.analyze"), "photo")

    def test_waits_for_the_model_and_runs_when_it_arrives(self):
        n = node(models={"u2netp": "installed"})
        job = matting.request("isnet", photo_file(), name="a.jpg")
        self.assertEqual(job.state, "QUEUED")
        self.assertIn("منتظرِ دانلودِ مدل", job.message)
        self.assertIsNone(SV.claim(n), "isnet is not installed: the job must wait, not fail")
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts), ("QUEUED", 0))
        row = QV.listing("waiting")["jobs"][0]
        self.assertEqual(row["wait_reason"], "model")
        self.assertIn("منتظرِ دانلودِ مدل", row["status_text"])
        # the heartbeat now says it is installed
        n.capabilities = caps(models={"u2netp": "installed", "isnet": {"state": "installed", "size_mb": 170}})
        n.save()
        got = SV.claim(n)
        self.assertEqual(got.pk, job.pk)

    def test_runtime_not_ready_keeps_the_job_queued_with_its_own_text(self):
        n = node(models={"u2netp": "installed"}, runtime=False)
        job = matting.request("u2netp", photo_file(), name="b.jpg")
        self.assertIsNone(SV.claim(n))
        self.assertIn("محیطِ اجرا", job.message)
        n.capabilities = caps(models={"u2netp": "installed"}, runtime=None)
        n.save()
        self.assertIsNone(SV.claim(n), "still probing = not yet")
        n.capabilities = caps(models={"u2netp": "installed"}, runtime=True)
        n.save()
        self.assertEqual(SV.claim(n).pk, job.pk)

    def test_text_says_runtime_when_the_model_is_there_but_the_environment_is_not(self):
        node(models={"u2netp": "installed"}, runtime=False)
        matting.request("u2netp", photo_file(), name="c.jpg")
        row = QV.listing("waiting")["jobs"][0]
        self.assertEqual(row["wait_reason"], "model")
        self.assertIn("محیطِ اجرا", row["status_text"])

    def test_a_node_without_the_capability_never_gets_it_even_with_the_photo_kit_up(self):
        old = ComputeNode.objects.create(name="old", capabilities={"photo": True, "agent": "2.6"}, last_seen=timezone.now())
        with self.assertRaises(matting.MattingError) as ctx:
            matting.request("u2netp", photo_file(), name="d.jpg")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("Update.bat", str(ctx.exception))
        job = SV.enqueue_durable("photo.edit", {"x": 1}, dedupe=False)
        self.assertEqual(SV.claim(old).pk, job.pk, "ordinary photo jobs still go to the photo-kit node")
        n = node("new", models={"u2netp": "installed"})
        job2 = matting.request("u2netp", photo_file(), name="e.jpg")
        self.assertIsNone(SV.claim(old), "photo.matting is not a photo.* job for the old node")
        self.assertEqual(SV.claim(n).pk, job2.pk)

    def test_other_jobs_are_not_blocked_by_the_matting_rule(self):
        n = node(models={})
        n.capabilities = {**n.capabilities, "photo": True}
        n.save()
        job = SV.enqueue_durable("photo.edit", {"y": 2}, dedupe=False)
        self.assertEqual(SV.claim(n).pk, job.pk)

    def test_dedupe_and_cancel_work_like_every_other_job(self):
        n = node(models={"u2netp": "installed"})
        a = matting.request("u2netp", photo_file(), name="f.jpg")
        SV.claim(n)
        SV.output_path(a, "cutout.png").write_bytes(b"png")
        SV.output_path(a, "mask.png").write_bytes(b"png")
        SV.finish(a, n, True, meta={"primary": "cutout.png"})
        b = matting.request("u2netp", photo_file(), name="f.jpg")
        self.assertEqual(b.pk, a.pk, "same photo + same model = the finished result is reused")
        self.assertEqual(set(matting.result(a)), {"cutout", "mask", "info"})
        c = matting.request("isnet", photo_file(), name="f.jpg")
        SV.cancel(c)
        c.refresh_from_db()
        self.assertEqual(c.state, "CANCELLED")

    def test_bad_input_is_refused_in_persian(self):
        node()
        with self.assertRaises(matting.MattingError) as ctx:
            matting.request("nope", photo_file())
        self.assertIn("مدلِ", str(ctx.exception))


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class MattingStatusTests(TestCase):
    def test_best_state_over_the_nodes_and_where_it_is_ready(self):
        node("gpu-1", models={"u2netp": "installed", "isnet": {"state": "downloading", "progress": 0.4}})
        node("gpu-2", online=False, models={"u2netp": "installed", "birefnet-lite": {"state": "failed", "error": "sha256 mismatch"}})
        st = matting.status()
        m = st["models"]
        self.assertEqual((m["u2netp"]["state"], m["u2netp"]["installed_on"], m["u2netp"]["ready_on"]), ("installed", ["gpu-1", "gpu-2"], ["gpu-1"]))
        self.assertTrue(m["u2netp"]["ready_now"])
        self.assertEqual((m["isnet"]["state"], m["isnet"]["progress"]), ("downloading", 0.4))
        self.assertEqual((m["birefnet-lite"]["state"], m["birefnet-lite"]["error"]), ("failed", "sha256 mismatch"))
        self.assertFalse(m["birefnet-lite"]["ready_now"])
        self.assertTrue(st["node_online"] and st["runtime"]["ok"])
        self.assertEqual(m["u2netp"]["license"], "Apache-2.0")

    def test_no_capable_node_says_what_to_do(self):
        st = matting.status()
        self.assertFalse(st["node_online"])
        self.assertEqual(st["models"]["isnet"]["state"], "missing")
        self.assertIn("در انتظارِ دانلود", st["models"]["isnet"]["state_label"])
        ComputeNode.objects.create(name="old", capabilities={"agent": "2.6"}, last_seen=timezone.now())
        st = matting.status()
        self.assertEqual(st["needs_update"], ["old"])
        self.assertIn("Update.bat", st["message"])

    def test_the_model_table_matches_the_node_side_names(self):
        self.assertEqual(list(matting.MODELS), ["u2netp", "isnet", "birefnet-lite"])
        self.assertEqual(matting.MODELS["birefnet-lite"]["package"], "photo-background", "BiRefNet-lite is the photo kit's own file: never downloaded twice")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class MattingDownloadTests(TestCase):
    def test_download_goes_to_a_node_as_a_scheduled_node_models_job_with_the_right_packages(self):
        n = node(models={}, runtime=True)
        job = matting.start_download(["isnet", "birefnet-lite"], when={"mode": "window"})
        self.assertEqual(job.kind, "node.models")
        self.assertEqual(job.payload["packages"], ["matting-isnet", "photo-background"])
        self.assertEqual((job.node_wanted, job.category), (n.name, "download"))
        self.assertTrue(job.window, "the nightly window is the default for big downloads")

    def test_the_runtime_package_is_added_only_when_no_python_on_the_node_has_onnxruntime(self):
        node("a", models={}, runtime=False)
        job = matting.start_download(["u2netp"], when={"mode": "now"})
        self.assertEqual(job.payload["packages"], ["matting-runtime", "matting-u2netp"])
        ComputeNode.objects.all().delete()
        node("b", models={}, runtime=True)
        self.assertEqual(matting.start_download(["u2netp"], when={"mode": "now"}).payload["packages"], ["matting-u2netp"])

    def test_errors(self):
        with self.assertRaises(matting.MattingError):
            matting.start_download([])
        node()
        with self.assertRaises(matting.MattingError):
            matting.start_download(["nope"])
        with self.assertRaises(matting.MattingError) as ctx:
            matting.start_download(["u2netp"], node="ghost")
        self.assertEqual(ctx.exception.status, 404)
        ComputeNode.objects.all().delete()
        with self.assertRaises(matting.MattingError):
            matting.start_download(["u2netp"])

    def test_test_job_waits_for_the_model(self):
        n = node(models={})
        job = matting.start_test("u2netp")
        self.assertEqual((job.kind, job.payload), ("photo.matting", {"model": "u2netp", "bench": True}))
        self.assertIsNone(SV.claim(n))
        n.capabilities = caps(models={"u2netp": "installed"})
        n.save()
        self.assertEqual(SV.claim(n).pk, job.pk)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class MattingApiTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(get_user_model().objects.create_user("boss", "b@x.io", "pw", is_staff=True))

    def test_only_staff(self):
        plain = APIClient()
        plain.force_authenticate(get_user_model().objects.create_user("pleb", "p@x.io", "pw"))
        for url in ("/api/v1/compute/matting/",):
            self.assertEqual(plain.get(url).status_code, 403)
        self.assertEqual(plain.post("/api/v1/compute/matting/download/", {"models": ["u2netp"]}, format="json").status_code, 403)

    def test_status_download_and_test(self):
        node(models={"u2netp": "installed"})
        r = self.c.get("/api/v1/compute/matting/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["models"]["u2netp"]["state"], "installed")
        r = self.c.post("/api/v1/compute/matting/download/", {"models": ["isnet"], "when": {"mode": "at", "time": "03:30"}}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.data["job"]["wait_reason"], "scheduled")
        r = self.c.post("/api/v1/compute/matting/download/", {"models": ["nope"]}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/v1/compute/matting/test/", {"model": "isnet"}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.data["job"]["kind"], "photo.matting")
        self.assertEqual(self.c.post("/api/v1/compute/matting/test/", {"model": "x"}, format="json").status_code, 400)
        ComputeNode.objects.all().delete()
        self.assertEqual(self.c.post("/api/v1/compute/matting/test/", {"model": "isnet"}, format="json").status_code, 503)
