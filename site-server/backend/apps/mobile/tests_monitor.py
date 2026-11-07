import json

from apps.compute.models import ComputeJob, ComputeNode
from apps.jobs.models import Job

from . import monitor
from .models import MobileActionLog, MobileSettings
from .tests_base import BASE, MobileTestCase


class SummaryTests(MobileTestCase):
    def test_summary_shape_and_no_secrets(self):
        node = ComputeNode.objects.create(name="گره آزمون", capabilities={"gpu": "RTX 3060", "voice": True, "ollama": True})
        ComputeJob.objects.create(kind="voice.asr", state=ComputeJob.State.FAILED, error="boom " * 100)
        ComputeJob.objects.create(kind="echo", state=ComputeJob.State.QUEUED)
        Job.objects.create(store=self.store, type=Job.Type.VIDEO_GENERATION, state=Job.State.FAILED, error="رندر شکست خورد")
        Job.objects.create(store=self.store, type=Job.Type.VIDEO_GENERATION, state=Job.State.WAITING_APPROVAL)
        c = self.device_client()
        r = c.get(BASE + "monitor/summary/")
        self.assertEqual(r.status_code, 200)
        d = r.data
        self.assertEqual(set(d), {"generated_at", "health", "nodes", "queue", "failures", "ai", "disk", "mobile", "actions"})
        self.assertIn(d["health"]["status"], ("ok", "degraded", "down"))
        self.assertEqual({c["name"] for c in d["health"]["checks"]}, {"database", "queue", "compute", "disk"})
        self.assertEqual(d["nodes"][0]["name"], "گره آزمون")
        self.assertEqual(d["nodes"][0]["gpu"], "RTX 3060")
        self.assertEqual((d["queue"]["compute"]["queued"], d["queue"]["jobs"]["waiting_approval"]), (1, 1))
        self.assertEqual({f["kind"] for f in d["failures"]}, {"job", "compute_job"})
        self.assertLessEqual(max(len(f["error"]) for f in d["failures"]), 200)
        self.assertIn("percent_used", d["disk"])
        self.assertEqual({a["action"] for a in d["actions"]}, monitor.ACTION_KEYS)
        blob = json.dumps(d, default=str)
        self.assertNotIn(node.token, blob)              # node tokens never leave the server
        for needle in ("api_key", "AI_API_KEY", "enroll_key", "password"):
            self.assertNotIn(needle, blob)

    def test_unknown_values_are_null_not_invented(self):
        d = self.device_client().get(BASE + "monitor/summary/").data
        if d["queue"]["celery"] is None:                 # no Redis in the test runner => unknown, honestly
            self.assertIsNone(d["queue"]["celery"])
        self.assertEqual(d["nodes"], [])
        self.assertFalse([c for c in d["health"]["checks"] if c["name"] == "compute"][0]["ok"])
        self.assertIn(d["health"]["status"], ("degraded", "ok", "down"))

    def test_staff_only(self):
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(BASE + "monitor/summary/").status_code, 401)
        self.assertEqual(self.panel_client(self.plain).get(BASE + "monitor/summary/").status_code, 403)


class ActionTests(MobileTestCase):
    def act(self, client, action, target=None, **params):
        return client.post(BASE + "monitor/actions/", {"action": action, "target": target, "params": params}, format="json")

    def test_unknown_and_dangerous_actions_are_refused(self):
        c = self.device_client()
        for bad in ("shell.run", "service.restart", "systemctl", "compute_node.delete", "user.delete", ""):
            r = self.act(c, bad)
            self.assertIn(r.status_code, (400,), bad)
        self.assertEqual(self.act(c, "service.restart").data["error"]["code"], "unknown_action")
        self.assertNotIn("restart", " ".join(monitor.ACTION_KEYS))
        self.assertNotIn("shell", " ".join(monitor.ACTION_KEYS))

    def test_compute_job_cancel_retry_and_audit_with_user_and_device(self):
        c = self.device_client()
        queued = ComputeJob.objects.create(kind="echo", state=ComputeJob.State.QUEUED)
        r = self.act(c, "compute_job.cancel", str(queued.uid))
        self.assertEqual(r.status_code, 200)
        queued.refresh_from_db()
        self.assertEqual(queued.state, "CANCELLED")
        self.assertEqual(self.act(c, "compute_job.cancel", str(queued.uid)).data["error"]["code"], "bad_state")
        failed = ComputeJob.objects.create(kind="echo", state=ComputeJob.State.FAILED, error="x", attempts=3)
        self.assertEqual(self.act(c, "compute_job.retry", str(failed.uid)).status_code, 200)
        failed.refresh_from_db()
        self.assertEqual((failed.state, failed.attempts, failed.error), ("QUEUED", 0, ""))
        running = ComputeJob.objects.create(kind="echo", state=ComputeJob.State.RUNNING)
        self.assertEqual(self.act(c, "compute_job.retry", str(running.uid)).data["error"]["code"], "bad_state")
        self.assertEqual(self.act(c, "compute_job.cancel", "not-a-uuid").data["error"]["code"], "target_not_found")
        rows = MobileActionLog.objects.filter(action="compute_job.cancel")
        self.assertEqual(rows.count(), 3)
        ok_row = rows.filter(ok=True).get()
        self.assertEqual((ok_row.user, ok_row.device.name), (self.staff, "گوشی آزمون"))
        self.assertEqual(ok_row.target, str(queued.uid))
        log = c.get(BASE + "monitor/actions/").data
        self.assertGreaterEqual(log["count"], 6)
        self.assertEqual(log["results"][0]["user"], "marketer")

    def test_node_disable_enable(self):
        node = ComputeNode.objects.create(name="n1")
        c = self.device_client()
        self.act(c, "compute_node.disable", node.pk)
        node.refresh_from_db()
        self.assertFalse(node.enabled)
        self.act(c, "compute_node.enable", node.pk)
        node.refresh_from_db()
        self.assertTrue(node.enabled)
        self.assertEqual(self.act(c, "compute_node.disable", 9999).data["error"]["code"], "target_not_found")
        self.assertEqual(self.act(c, "compute_node.disable").data["error"]["code"], "missing_fields")

    def test_job_cancel_goes_through_nm_cancellation(self):
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_GENERATION, state=Job.State.PROCESSING)
        c = self.device_client()
        self.assertEqual(self.act(c, "job.cancel", job.pk).status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.CANCELLED)
        self.assertEqual(self.act(c, "job.cancel", job.pk).data["error"]["code"], "bad_state")

    def test_sms_pause_resume_and_ai_reset(self):
        c = self.device_client()
        self.act(c, "sms.pause")
        self.assertFalse(MobileSettings.get().sms_enabled)
        self.act(c, "sms.resume")
        self.assertTrue(MobileSettings.get().sms_enabled)
        self.assertEqual(self.act(c, "ai.reset_circuit").status_code, 200)

    def test_actions_need_staff(self):
        self.assertEqual(self.act(self.panel_client(self.plain), "sms.pause").status_code, 403)
        self.assertTrue(MobileSettings.get().sms_enabled)


class ComputeQueueFieldsTests(MobileTestCase):
    """The phone's monitor still works with the durable queue's new job fields and kinds (compute-r1)."""

    def test_phone_retry_resets_the_queue_bookkeeping(self):
        from datetime import timedelta

        from django.utils import timezone

        c = self.device_client()
        old = timezone.now() - timedelta(days=2)
        failed = ComputeJob.objects.create(kind="echo", state=ComputeJob.State.FAILED, error="x", attempts=2, lost_count=5,
                                           queued_at=old, waited_s=9.0, run_s=3.0)
        r = c.post(BASE + "monitor/actions/", {"action": "compute_job.retry", "target": str(failed.uid)}, format="json")
        self.assertEqual(r.status_code, 200)
        failed.refresh_from_db()
        self.assertEqual((failed.state, failed.lost_count, failed.waited_s, failed.run_s), ("QUEUED", 0, None, None))
        self.assertGreater(failed.queued_at, old + timedelta(days=1))

    def test_summary_and_cancel_work_with_parked_and_matting_jobs(self):
        c = self.device_client()
        ComputeJob.objects.create(kind="wait.node", state=ComputeJob.State.QUEUED, payload={"capability": "comfyui", "ref": {"model": "jobs.Job", "id": 0}})
        ComputeJob.objects.create(kind="photo.matting", state=ComputeJob.State.FAILED, error="x")
        waiting = ComputeJob.objects.create(kind="photo.matting", state=ComputeJob.State.QUEUED, payload={"model": "isnet"})
        r = c.get(BASE + "monitor/summary/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["queue"]["compute"]["queued"], 2)
        r = c.post(BASE + "monitor/actions/", {"action": "compute_job.cancel", "target": str(waiting.uid)}, format="json")
        self.assertEqual(r.status_code, 200)
        waiting.refresh_from_db()
        self.assertEqual(waiting.state, "CANCELLED")
