"""صفِ سرورهای پردازش: گرفتنِ اتمیِ کار، تکرارنشدنِ کارِ یکسان، برگشتِ کارِ گرهٔ خاموش، پروتکلِ HTTP."""
import io
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import services as SV
from .models import ComputeJob, ComputeNode

TMP = tempfile.mkdtemp(prefix="nm-compute-test-")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeQueueTests(TestCase):
    def setUp(self):
        self.a = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True}, last_seen=timezone.now())
        self.b = ComputeNode.objects.create(name="gpu-2", capabilities={"comfyui": True}, last_seen=timezone.now())

    def test_enqueue_requires_online_capable_node(self):
        ComputeNode.objects.update(last_seen=timezone.now() - timedelta(minutes=10))
        with self.assertRaises(SV.ComputeUnavailable):
            SV.enqueue("comfy.graph", {"graph": {}})
        self.a.last_seen = timezone.now()
        self.a.save()
        job = SV.enqueue("comfy.graph", {"graph": {"1": {}}})
        self.assertEqual(job.state, "QUEUED")

    def test_claim_is_exclusive_between_two_nodes(self):
        job = SV.enqueue("comfy.graph", {"graph": {"1": {}}})
        got = [SV.claim(self.a), SV.claim(self.b)]
        claimed = [g for g in got if g is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].pk, job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "CLAIMED")
        self.assertEqual(job.attempts, 1)

    def test_identical_request_reuses_completed_output(self):
        job = SV.enqueue("comfy.graph", {"graph": {"1": {"seed": 5}}})
        SV.claim(self.a)
        SV.output_path(job, "out.png").write_bytes(b"png")
        SV.finish(job, self.a, True, meta={"primary": "out.png"})
        again = SV.enqueue("comfy.graph", {"graph": {"1": {"seed": 5}}})
        self.assertEqual(again.pk, job.pk, "همان درخواست دوباره پردازش شد")
        other = SV.enqueue("comfy.graph", {"graph": {"1": {"seed": 6}}})
        self.assertNotEqual(other.pk, job.pk)
        self.a.refresh_from_db()
        self.assertEqual(self.a.jobs_done, 1)

    def test_capability_routing(self):
        self.b.capabilities = {"photo": True}
        self.b.save()
        photo = SV.enqueue("photo.edit", {"auto": True})
        self.assertIsNone(SV.claim(self.a), "گرهٔ بی‌photo نباید کارِ عکس بگیرد")
        self.assertEqual(SV.claim(self.b).pk, photo.pk)

    def test_node_wanted(self):
        job = SV.enqueue("comfy.graph", {"graph": {}}, node="gpu-2")
        self.assertIsNone(SV.claim(self.a))
        self.assertEqual(SV.claim(self.b).pk, job.pk)

    def test_stale_claim_is_requeued_then_failed(self):
        job = SV.enqueue("comfy.graph", {"graph": {"x": 1}})
        job.lease_s = 1
        job.save()
        SV.claim(self.a)
        ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=5))
        self.assertEqual(SV.requeue_stale(), 1)
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED")
        self.assertIsNone(job.node)
        SV.claim(self.b)
        ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=5))
        SV.requeue_stale()
        job.refresh_from_db()
        self.assertEqual(job.state, "FAILED")

    def test_completed_job_without_outputs_is_not_reused(self):
        job = SV.enqueue("comfy.graph", {"graph": {"1": {"seed": 9}}})
        SV.claim(self.a)
        SV.finish(job, self.a, True)  # گره «تمام شد» گفت ولی چیزی بارگذاری نکرد
        job.refresh_from_db()
        self.assertEqual(job.state, "COMPLETED")
        again = SV.enqueue("comfy.graph", {"graph": {"1": {"seed": 9}}})
        self.assertNotEqual(again.pk, job.pk, "کارِ بی‌خروجی نباید به‌جای پردازشِ تازه برگردد")

    def test_stale_job_with_cancel_requested_is_cancelled_not_requeued(self):
        job = SV.enqueue("comfy.graph", {"graph": {"x": 3}})
        job.lease_s = 1
        job.save()
        SV.claim(self.a)
        SV.cancel(job)
        ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=5))
        SV.requeue_stale()
        job.refresh_from_db()
        self.assertEqual(job.state, "CANCELLED")
        self.assertIsNone(SV.claim(self.b))

    def test_package_is_built_once(self):
        job = SV.enqueue("comfy.graph", {"graph": {"x": 4}})
        first = SV.package(job)
        stamp = first.stat().st_mtime_ns
        self.assertEqual(SV.package(job).stat().st_mtime_ns, stamp)
        self.assertFalse(list(first.parent.glob("package.*.tmp")))

    def test_summary_counts_only_true_flags(self):
        self.a.capabilities = {"comfyui": True, "slots": 2, "comfy_nodes": ["LoadImage"], "gpu": "RTX", "photo": False}
        self.a.save()
        caps = SV.summary()["capabilities"]
        self.assertEqual(caps.get("comfyui"), 2)
        for key in ("slots", "comfy_nodes", "gpu", "photo"):
            self.assertNotIn(key, caps)

    def test_failure_retries_once_on_any_node(self):
        job = SV.enqueue("comfy.graph", {"graph": {"x": 2}})
        SV.claim(self.a)
        SV.finish(job, self.a, False, "boom")
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED")
        SV.claim(self.b)
        SV.finish(job, self.b, False, "boom again")
        job.refresh_from_db()
        self.assertEqual(job.state, "FAILED")
        self.assertIn("boom again", job.error)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeConcurrencyTests(TransactionTestCase):
    """دو گره هم‌زمان کار می‌گیرند — هر کار دقیقاً به یکی (UPDATE ِ شرطی). با تراکنشِ واقعی، نه TestCase."""

    def test_claim_concurrent_threads_never_double_assign(self):
        a = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True}, last_seen=timezone.now())
        b = ComputeNode.objects.create(name="gpu-2", capabilities={"comfyui": True}, last_seen=timezone.now())
        for i in range(8):
            SV.enqueue("comfy.graph", {"graph": {"n": i}})
        results = []
        lock = threading.Lock()

        def worker(node):
            from django.db import OperationalError, connection

            try:
                for _ in range(200):
                    try:
                        j = SV.claim(node)
                    except OperationalError:  # SQLite «database is locked» زیرِ فشارِ دو نخ
                        time.sleep(0.01)
                        continue
                    if j is None:
                        break
                    with lock:
                        results.append((node.name, j.pk))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        pks = [pk for _, pk in results]
        self.assertEqual(len(pks), 8)
        self.assertEqual(len(set(pks)), 8, "یک کار به دو گره داده شد")
        self.assertEqual(ComputeJob.objects.filter(state="CLAIMED").count(), 8)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeProtocolTests(TestCase):
    def setUp(self):
        self.node = ComputeNode.objects.create(name="gpu-1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        self.staff = get_user_model().objects.create_user("boss", "b@x.io", "pw", is_staff=True)

    def test_full_round_trip(self):
        r = self.c.post("/api/v1/compute/heartbeat/", {"comfyui": True, "gpu": "RTX 3060"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.node.refresh_from_db()
        self.assertTrue(self.node.online)
        job = SV.enqueue("echo", {"sleep": 0})
        r = self.c.post("/api/v1/compute/claim/", {}, format="json")
        self.assertEqual(r.data["job"]["uid"], str(job.uid))
        r = self.c.get(f"/api/v1/compute/jobs/{job.uid}/package/")
        self.assertEqual(r.status_code, 200)
        r = self.c.post(f"/api/v1/compute/jobs/{job.uid}/progress/", {"progress": 0.5, "message": "half"}, format="json")
        self.assertFalse(r.data["cancel"])
        r = self.c.post(f"/api/v1/compute/jobs/{job.uid}/upload/", {"file_echo": io.BytesIO(b"{}")}, format="multipart")
        self.assertEqual(r.status_code, 200)
        r = self.c.post(f"/api/v1/compute/jobs/{job.uid}/finish/", {"ok": True, "meta": {"primary": "file_echo"}}, format="json")
        self.assertEqual(r.data["state"], "COMPLETED")
        job.refresh_from_db()
        self.assertEqual(job.outputs()[0]["name"], "file_echo")

    def test_other_node_cannot_touch_my_job(self):
        other = ComputeNode.objects.create(name="gpu-2")
        job = SV.enqueue("echo", {}, require_online=False)
        SV.claim(self.node)
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION="Node " + other.token)
        r = c2.post(f"/api/v1/compute/jobs/{job.uid}/finish/", {"ok": True}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_submit_rejects_bad_input_and_cleans_temp(self):
        import glob
        import tempfile

        staff = APIClient()
        staff.force_authenticate(self.staff)
        r = staff.post("/api/v1/compute/submit/", {"kind": "echo", "payload": "[1, 2]"})
        self.assertEqual(r.status_code, 400)
        r = staff.post("/api/v1/compute/submit/", {"kind": "echo", "payload": "{}", "timeout": "abc"})
        self.assertEqual(r.status_code, 400)
        before = set(glob.glob(tempfile.gettempdir() + "/nm-submit-*"))
        r = staff.post("/api/v1/compute/submit/", {"kind": "echo", "payload": "{}", "dedupe": "0",
                                                   "image": io.BytesIO(b"x")}, format="multipart")
        self.assertEqual(r.status_code, 503, "گره‌ای آنلاین نیست")
        self.assertEqual(set(glob.glob(tempfile.gettempdir() + "/nm-submit-*")) - before, set())

    def test_anonymous_cannot_read_outputs(self):
        job = SV.enqueue("echo", {}, require_online=False)
        SV.output_path(job, "echo.json").write_bytes(b"{}")
        r = APIClient().get(f"/api/v1/compute/jobs/{job.uid}/outputs/echo.json")
        self.assertEqual(r.status_code, 401)
        staff = APIClient()
        staff.force_authenticate(self.staff)
        self.assertEqual(staff.get(f"/api/v1/compute/jobs/{job.uid}/outputs/echo.json").status_code, 200)

    def test_bad_token_rejected(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Node nope")
        self.assertEqual(c.post("/api/v1/compute/heartbeat/", {}, format="json").status_code, 401)

    def test_staff_endpoints_need_staff(self):
        anon = APIClient()
        self.assertIn(anon.get("/api/v1/compute/nodes/").status_code, (401, 403))
        staff = APIClient()
        staff.force_authenticate(self.staff)
        r = staff.post("/api/v1/compute/nodes/", {"name": "gpu-9"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["token"])
        r = staff.get("/api/v1/compute/nodes/%s/start.bat" % r.data["id"])
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"NM_TOKEN", r.content)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeLogsAndSettingsTests(TestCase):
    def setUp(self):
        self.node = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True}, last_seen=timezone.now())
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        self.staff = APIClient()
        self.staff.force_authenticate(get_user_model().objects.create_user("boss2", "b2@x.io", "pw", is_staff=True))

    def test_node_log_roundtrip(self):
        r = self.c.post("/api/v1/compute/log/", {"lines": [{"level": "error", "message": "ComfyUI died", "ts": "2026-10-18T10:00:00Z"},
                                                           {"level": "info", "message": ""}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["saved"], 1)
        r = self.staff.get(f"/api/v1/compute/nodes/{self.node.pk}/logs/")
        self.assertEqual(r.data["lines"][0]["message"], "ComfyUI died")
        self.assertEqual(r.data["lines"][0]["level"], "ERROR")
        self.assertEqual(self.staff.get("/api/v1/compute/nodes/").data[0]["last_error"], "ComfyUI died")

    def test_log_retention(self):
        from .models import ComputeNodeLog
        self.c.post("/api/v1/compute/log/", {"lines": [{"level": "info", "message": f"m{i}"} for i in range(200)]}, format="json")
        for _ in range(2):
            self.c.post("/api/v1/compute/log/", {"lines": [{"level": "info", "message": f"n{i}"} for i in range(200)]}, format="json")
        self.assertEqual(ComputeNodeLog.objects.filter(node=self.node).count(), 500)

    def test_settings_route_image_video_node(self):
        from services.comfyui import remote
        self.assertEqual(remote.node_name("agent://any"), "")
        r = self.staff.post("/api/v1/compute/settings/", {"image_video_node": "gpu-1"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(remote.node_name("agent://any"), "gpu-1")
        self.assertEqual(remote.node_name("agent://gpu-2"), "gpu-2", "نامِ صریح در env می‌چربد")
        r = self.staff.post("/api/v1/compute/settings/", {"image_video_node": "nope"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.staff.post("/api/v1/compute/settings/", {"image_video_node": ""}, format="json")
        self.assertEqual(remote.node_name("agent://any"), "")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeEnrollTests(TestCase):
    def test_enroll_with_site_key_creates_node_and_is_idempotent(self):
        from .models import ComputeSettings
        key = ComputeSettings.get().enroll_key
        c = APIClient()
        r = c.post("/api/v1/compute/enroll/", {"key": key, "name": "GPU-PC 1"}, format="json")
        self.assertEqual(r.status_code, 201)
        token = r.data["token"]
        self.assertEqual(r.data["name"], "GPU-PC1")
        r = c.post("/api/v1/compute/enroll/", {"key": key, "hostname": "GPU-PC1"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["token"], token, "همان کامپیوتر = همان گره و همان توکن")
        c.credentials(HTTP_AUTHORIZATION="Node " + token)
        self.assertEqual(c.post("/api/v1/compute/heartbeat/", {"comfyui": True}, format="json").status_code, 200)

    def test_enroll_wrong_key_or_disabled_node(self):
        from .models import ComputeSettings
        c = APIClient()
        self.assertEqual(c.post("/api/v1/compute/enroll/", {"key": "nope", "name": "x"}, format="json").status_code, 403)
        ComputeNode.objects.create(name="off", enabled=False)
        r = c.post("/api/v1/compute/enroll/", {"key": ComputeSettings.get().enroll_key, "name": "off"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_staff_can_rotate_enroll_key(self):
        from .models import ComputeSettings
        staff = APIClient()
        staff.force_authenticate(get_user_model().objects.create_user("boss3", "b3@x.io", "pw", is_staff=True))
        before = ComputeSettings.get().enroll_key
        r = staff.post("/api/v1/compute/settings/", {"rotate_enroll_key": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.data["enroll_key"], before)
        self.assertEqual(r.data["image_video_node"], "", "چرخاندنِ کلید مسیر را عوض نمی‌کند")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeDesiredServicesTests(TestCase):
    def setUp(self):
        self.node = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True}, last_seen=timezone.now())
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        self.staff = APIClient()
        self.staff.force_authenticate(get_user_model().objects.create_user("boss4", "b4@x.io", "pw", is_staff=True))

    def test_desired_services_reach_the_node_in_heartbeat_and_claim(self):
        r = self.staff.post(f"/api/v1/compute/nodes/{self.node.pk}/desired/",
                            {"services": {"ollama": False, "comfyui": True}, "auto_switch": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["desired"], {"ollama": False, "comfyui": True})
        self.assertFalse(r.data["auto_switch"])
        hb = self.c.post("/api/v1/compute/heartbeat/", {}, format="json").data
        self.assertEqual(hb["desired"], {"ollama": False, "comfyui": True})
        self.assertFalse(hb["auto_switch"])
        cl = self.c.post("/api/v1/compute/claim/", {}, format="json").data
        self.assertIsNone(cl["job"])
        self.assertEqual(cl["desired"], {"ollama": False, "comfyui": True})
        # None = «دست نزن» کلید را حذف می‌کند
        r = self.staff.post(f"/api/v1/compute/nodes/{self.node.pk}/desired/", {"services": {"ollama": None}}, format="json")
        self.assertEqual(r.data["desired"], {"comfyui": True})

    def test_desired_rejects_unknown_service(self):
        r = self.staff.post(f"/api/v1/compute/nodes/{self.node.pk}/desired/", {"services": {"tor": True}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_node_json_exposes_resources_and_managed(self):
        self.c.post("/api/v1/compute/heartbeat/", {"comfyui": True, "ram_total_mb": 32000, "ram_free_mb": 9000,
                                                   "vram_used_mb": 7000, "vram_total_mb": 12288,
                                                   "managed": {"comfyui": "agent", "ollama": "external"}}, format="json")
        n = self.staff.get("/api/v1/compute/nodes/").data[0]
        self.assertEqual(n["resources"]["vram_total_mb"], 12288)
        self.assertEqual(n["managed"]["ollama"], "external")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ComputeStartableRoutingTests(TestCase):
    """سرویس خاموش است ولی عامل می‌تواند روشنش کند ⇒ با سوئیچِ خودکار، کار پذیرفته می‌شود (گره خودش سوئیچ می‌کند)."""

    def setUp(self):
        self.node = ComputeNode.objects.create(
            name="gpu-s", last_seen=timezone.now(), auto_switch=True,
            capabilities={"comfyui": False, "ollama": True, "startable": {"comfyui": True, "ollama": True}})

    def test_startable_counts_as_capable_when_auto_switch_is_on(self):
        self.assertTrue(self.node.has("comfyui"))
        self.assertEqual([n.name for n in SV.online_nodes("comfyui")], ["gpu-s"])
        job = SV.enqueue("comfy.graph", {"graph": {"1": {}}})
        self.assertIsNotNone(job.pk)

    def test_claim_gives_the_job_to_a_node_that_can_start_the_service(self):
        job = SV.enqueue("comfy.graph", {"graph": {"2": {}}})
        self.assertEqual(SV.claim(self.node).pk, job.pk)

    def test_claim_skips_it_when_auto_switch_is_off(self):
        SV.enqueue("comfy.graph", {"graph": {"3": {}}}, require_online=False)
        self.node.auto_switch = False
        self.node.save()
        self.assertIsNone(SV.claim(self.node))

    def test_startable_is_ignored_when_auto_switch_is_off(self):
        self.node.auto_switch = False
        self.node.save()
        self.assertFalse(self.node.has("comfyui"))
        self.assertTrue(self.node.has("ollama"))
        with self.assertRaises(SV.ComputeUnavailable):
            SV.enqueue("comfy.graph", {"graph": {"1": {}}})
