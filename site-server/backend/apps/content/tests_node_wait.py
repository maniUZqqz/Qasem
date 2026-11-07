"""Round 5 × the durable processing-server queue (apps.compute.park): features that need the node WAIT instead of failing.
Nothing here talks to a real node or a real AI: the compute app and the model are faked."""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import captions
from services.editing.director import drafts as drafts_mod
from services.editing.director import projectops as ops
from services.tests_director import fake_ctx, run_tool, with_clip

from . import tasks_director, tasks_editing
from .models import DirectorDraft

WAIT = {"node": False, "local": False, "ok": False, "waiting": True, "message": captions.WAITING_TEXT}
OFF = {"node": False, "local": False, "ok": False, "waiting": False, "message": captions.OFFLINE_MESSAGE}
ON = {"node": True, "local": False, "ok": True, "waiting": False, "message": ""}


class CaptionStatusTests(SimpleTestCase):
    def test_registered_but_off_means_waiting_not_impossible(self):
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("apps.compute.services.known_nodes", return_value=[object()]), \
                patch.object(captions, "_local_ready", return_value=False):
            st = captions.status()
        self.assertFalse(st["ok"])
        self.assertTrue(st["waiting"])
        self.assertEqual(st["message"], captions.WAITING_TEXT)
        self.assertTrue(st["message"].startswith("در صف"))

    def test_no_server_on_record_stays_the_old_offline_message(self):
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("apps.compute.services.known_nodes", return_value=[]), \
                patch.object(captions, "_local_ready", return_value=False):
            st = captions.status()
        self.assertFalse(st["waiting"])
        self.assertEqual(st["message"], captions.OFFLINE_MESSAGE)

    def test_online_or_local_is_simply_ok(self):
        with patch("apps.compute.services.online_nodes", return_value=[object()]), patch.object(captions, "_local_ready", return_value=False):
            st = captions.status()
        self.assertTrue(st["ok"])
        self.assertFalse(st["waiting"])

    def test_the_waiting_error_carries_the_park_flag(self):
        exc = captions.waiting_error()
        self.assertEqual(exc.node_waiting, "voice")
        from apps.compute import park

        self.assertEqual(park._flag_of(exc), "voice")

    def test_transcribe_with_a_registered_off_server_raises_the_waiting_error(self):
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("apps.compute.services.known_nodes", return_value=[object()]), \
                patch.object(captions, "_local_ready", return_value=False):
            with self.assertRaises(captions.CaptionsUnavailable) as cm:
                captions.transcribe_wav("/nonexistent.wav")
        self.assertEqual(cm.exception.node_waiting, "voice")

    def test_transcribe_when_the_queue_parks_the_job_raises_the_waiting_error(self):
        from apps.compute import services as compute

        with patch("apps.compute.services.online_nodes", return_value=[object()]), patch("apps.compute.services.enqueue", return_value=object()), \
                patch("apps.compute.services.wait", side_effect=compute.NodeWaiting("x", "voice")) as w:
            with self.assertRaises(captions.CaptionsUnavailable) as cm:
                captions.transcribe_wav("/nonexistent.wav")
        self.assertEqual(cm.exception.node_waiting, "voice")
        self.assertTrue(w.call_args.kwargs.get("patient"))
        self.assertEqual(w.call_args.kwargs.get("park_after_s"), 120)


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


class CaptionsApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("nw-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه انتظار")
        self.client.force_login(self.owner)

    def test_the_view_queues_instead_of_503_when_the_server_is_only_off(self):
        from .models import UploadedVideo

        up = UploadedVideo.objects.create(store=self.store, title="v", video="uploads/videos/x.mp4", state="READY", duration=10.0, has_audio=True)
        body = {"ref": f"video:{up.pk}", "start": 0, "end": 5, "at": 0, "speed": 1}
        with patch("services.editing.captions.status", return_value=WAIT), patch("apps.content.views_editor_pro.dispatch_job", side_effect=run_inline), \
                patch("apps.compute.park.gate", return_value=True) as gate, \
                patch("apps.content.editor_project.describe", return_value={"kind": "video", "has_audio": True, "path": "/x.mp4", "duration": 10.0}):
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/editor/captions/", json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        gate.assert_called_once()
        self.assertEqual(gate.call_args.args[1], "voice")
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertNotEqual(job.state, Job.State.FAILED, "a parked job is not a failed job")

    def test_with_no_server_on_record_it_is_still_503(self):
        from .models import UploadedVideo

        up = UploadedVideo.objects.create(store=self.store, title="v", video="uploads/videos/x.mp4", state="READY", duration=10.0, has_audio=True)
        body = {"ref": f"video:{up.pk}", "start": 0, "end": 5, "at": 0, "speed": 1}
        with patch("services.editing.captions.status", return_value=OFF), \
                patch("apps.content.editor_project.describe", return_value={"kind": "video", "has_audio": True, "path": "/x.mp4", "duration": 10.0}):
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/editor/captions/", json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 503)

    def test_translation_parks_when_the_ai_has_no_path_but_a_node_is_on_record(self):
        parked = {}

        def fake_park(job, exc):
            parked["exc"] = exc
            return True
        boom = RuntimeError("no ai")
        boom.node_waiting = "ollama"
        from services.editing import translate

        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"what": "translate"})
        with patch.object(translate, "_ask", side_effect=boom), patch("apps.compute.park.maybe_park", side_effect=fake_park):
            out = tasks_editing.translate_captions_task.run(job.id, "en", [{"id": "a", "text": "سلام"}])
        self.assertEqual(out, {"waiting": "node"})
        self.assertIs(parked["exc"], boom)
        job.refresh_from_db()
        self.assertNotEqual(job.state, Job.State.FAILED)


class DirectorFillTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("nf-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه کارگردان")

    def variant(self, ok=False, message=captions.WAITING_TEXT, tool="add_captions", draft_id=7, on=True):
        return {"key": "a", "draft_id": draft_id, "plan": [
            {"id": "s1", "tool": "add_clip", "ok": True, "message": "", "on": True},
            {"id": "s2", "tool": tool, "ok": ok, "message": message, "on": on, "params": {"clip": "all", "style": "pop"}, "why": "x", "title": "t"}]}

    def test_only_steps_that_failed_because_the_server_is_off_are_queued(self):
        got = tasks_director.node_pending([self.variant()])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["draft"], 7)
        self.assertEqual([s["id"] for s in got[0]["steps"]], ["s2"])
        self.assertEqual(set(got[0]["steps"][0]), {"id", "tool", "params", "on", "why"})
        self.assertEqual(tasks_director.node_pending([self.variant(message="گفتاری پیدا نشد")]), [], "another reason: not the server's fault")
        self.assertEqual(tasks_director.node_pending([self.variant(ok=True)]), [])
        self.assertEqual(tasks_director.node_pending([self.variant(on=False)]), [], "the owner switched it off")
        self.assertEqual(tasks_director.node_pending([self.variant(tool="add_title")]), [], "not a node step")
        self.assertEqual(len(tasks_director.node_pending([self.variant(tool="remove_fillers")])), 1)
        self.assertEqual(len(tasks_director.node_pending([self.variant(tool="add_voiceover", message="در صف — منتظرِ روشن شدنِ سرورِ پردازش: گویندگی")])), 1)

    def draft(self):
        p = with_clip("video:3", start=0, end=6)
        plan = [{"id": "s2", "tool": "add_captions", "ok": False, "skipped": False, "message": captions.WAITING_TEXT, "on": True, "params": {"clip": "all", "style": "pop"}}]
        p["director"] = {"run": "r1", "variant": "a", "brief": {"platform": "reels"}, "plan": plan, "critique": {"score": 70}}
        return drafts_mod.create(self.store, run="r1", job_id=None, key="a", title="پیش‌نویس", data=p, score=70, length=ops.project_length(p))

    def fill_job(self, draft):
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"what": "director_fill"})
        items = [{"draft": draft.pk, "steps": [{"id": "s2", "tool": "add_captions", "params": {"clip": "all", "style": "pop"}, "on": True, "why": ""}]}]
        return job, {"items": items}

    def test_when_the_server_is_back_the_captions_are_added_to_the_unopened_draft_and_the_plan_says_so(self):
        d = self.draft()
        job, payload = self.fill_job(d)
        with patch("apps.compute.park.gate", return_value=False), patch.object(tasks_director, "store_ctx", return_value=fake_ctx()):
            out = tasks_director.director_fill_task.run(job.id, payload)
        self.assertTrue(out["ok"], out)
        d.refresh_from_db()
        texts = [t for t in d.data["tracks"] if t["kind"] == "text" and t["clips"]]
        self.assertTrue(texts, "caption lines were added")
        step = d.data["director"]["plan"][0]
        self.assertTrue(step["ok"])
        self.assertIn("filled_at", d.data["director"])
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED)
        self.assertGreaterEqual(job.result["filled"], 1)

    def test_while_the_server_is_off_the_job_parks_and_the_draft_is_untouched(self):
        d = self.draft()
        before = json.dumps(d.data, sort_keys=True)
        job, payload = self.fill_job(d)
        with patch("apps.compute.park.gate", return_value=True) as gate:
            out = tasks_director.director_fill_task.run(job.id, payload)
        self.assertEqual(out, {"waiting": "node"})
        self.assertEqual(gate.call_args.args[1], "voice")
        d.refresh_from_db()
        self.assertEqual(json.dumps(d.data, sort_keys=True), before)

    def test_an_opened_draft_is_never_touched(self):
        from django.utils import timezone

        d = self.draft()
        d.promoted_at = timezone.now()
        d.save()
        before = json.dumps(d.data, sort_keys=True)
        job, payload = self.fill_job(d)
        with patch("apps.compute.park.gate", return_value=False), patch.object(tasks_director, "store_ctx", return_value=fake_ctx()):
            tasks_director.director_fill_task.run(job.id, payload)
        d.refresh_from_db()
        self.assertEqual(json.dumps(d.data, sort_keys=True), before)

    def test_if_a_step_still_cannot_run_the_draft_is_kept_and_the_gap_is_reported(self):
        d = self.draft()
        job, payload = self.fill_job(d)
        with patch("apps.compute.park.gate", return_value=False), patch.object(tasks_director, "store_ctx", return_value=fake_ctx(words=lambda ref, a, b: [])):
            tasks_director.director_fill_task.run(job.id, payload)
        job.refresh_from_db()
        self.assertEqual(job.result["still_missing"], 1)
        self.assertEqual(job.result["filled"], 0)

    def test_the_vision_critique_waits_for_a_model_and_then_lands_on_the_draft(self):
        d = self.draft()
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"what": "director_vision"})
        body = {"draft": d.pk, "request": "ویدیو بساز", "brief": {"platform": "reels"}}
        with patch("apps.compute.park.gate", return_value=True) as gate:
            self.assertEqual(tasks_director.director_vision_task.run(job.id, body), {"waiting": "node"})
        self.assertEqual(gate.call_args.args[1], "ollama")
        parsed = {"scores": {"hook": 4}, "issues": [{"what": "تاریک", "fix": "روشن‌تر"}], "verdict": "خوب"}
        with patch("apps.compute.park.gate", return_value=False), patch.object(tasks_director, "preview_reviewer", return_value=lambda project: ["Zm9v"]), \
                patch("services.editing.director.ai.vision_review", return_value=(parsed, {"via": "node"})):
            out = tasks_director.director_vision_task.run(job.id, body)
        self.assertTrue(out["ok"])
        d.refresh_from_db()
        self.assertEqual(d.data["director"]["critique"]["vision"]["verdict"], "خوب")
        self.assertEqual(d.data["director"]["critique"]["score"], 70, "the rest of the critique is kept")

    def test_a_failed_vision_review_completes_quietly_with_the_reason(self):
        d = self.draft()
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"what": "director_vision"})
        with patch("apps.compute.park.gate", return_value=False), patch.object(tasks_director, "preview_reviewer", return_value=lambda project: ["Zm9v"]), \
                patch("services.editing.director.ai.vision_review", return_value=(None, {"error": "مدل جواب نداد"})):
            out = tasks_director.director_vision_task.run(job.id, {"draft": d.pk, "request": "x", "brief": {}})
        self.assertFalse(out["ok"])
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED)
        self.assertIn("جواب نداد", job.result["reason"])


class DirectorTaskQueuesFillTests(SimpleTestCase):
    def test_queue_fill_creates_a_follow_up_job_and_tells_the_owner(self):
        """`_queue_fill` is what director_task calls after saving the drafts."""
        calls = []

        class FakeJob:
            def __init__(self, **kw):
                self.id = 900 + len(calls)
                calls.append(kw)

        class FakeObjects:
            @staticmethod
            def create(**kw):
                return FakeJob(**kw)

        class FakeJobCls:
            Type = Job.Type
            objects = FakeObjects
        result = {"primary": "a", "brief": {}, "variants": [{"key": "a", "draft_id": 5, "critique": {}, "plan": [
            {"id": "s2", "tool": "add_captions", "ok": False, "on": True, "message": captions.WAITING_TEXT, "params": {}}]}]}
        final = {"degraded": []}
        with patch.object(tasks_director, "Job", FakeJobCls), patch.object(tasks_director, "dispatch_job", return_value=None) as d:
            tasks_director._queue_fill(type("J", (), {"id": 1})(), object(), {"asr": True, "options": {"use_ai": True, "preview": True}, "prompt": "p"}, result, final)
        self.assertEqual(d.call_count, 2, "one fill job + one vision job")
        self.assertEqual(final["waiting_node"]["steps"], 1)
        self.assertIn("waiting_vision", final)
        self.assertTrue(any("سرورِ پردازش" in x for x in final["degraded"]))

    def test_without_pending_steps_and_without_ai_nothing_is_queued(self):
        result = {"primary": "a", "brief": {}, "variants": [{"key": "a", "draft_id": 5, "critique": {}, "plan": [{"id": "s1", "tool": "add_clip", "ok": True, "on": True, "message": ""}]}]}
        with patch.object(tasks_director, "dispatch_job") as d:
            tasks_director._queue_fill(type("J", (), {"id": 1})(), object(), {"asr": True, "options": {"use_ai": False}}, result, {"degraded": []})
        d.assert_not_called()
