# -*- coding: utf-8 -*-
"""«صبحِ مالک» روی مرزِ سایت (۱۴۰۵/۰۸/۲۳): گره با عاملِ 2.10 روشن می‌شود ⇒ سایت خودش به‌روزرسانی می‌فرستد و تا آن موقع کار نمی‌دهد ⇒ عاملِ تازه
با نصبِ در حالِ انجام برمی‌گردد ⇒ یک اجرای آزمونِ پذیرش برای نسخهٔ تازه ساخته می‌شود ⇒ کارهایی که ویژگی‌شان هنوز نصب می‌شود منتظر می‌مانند و بقیه
کار می‌گیرند ⇒ با پایانِ نصب کارهای منتظر (موشن، سه‌بعدی، رونویسی، آباگرام) خودشان می‌روند ⇒ کارهای «منتظرِ روشن شدنِ گره» بیدار می‌شوند.
(نسخهٔ سرتاسریِ همین با عاملِ واقعی: tests_e2e_node.py، اختیاری.)  و آزمون‌های پذیرشِ ویرایشگرِ عکس (selftests/photo_edit.py)."""
import io
import json
import os
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import autopilot, park
from . import commands as C
from . import readiness
from . import services as SV
from .models import ComputeJob, ComputeNode, ComputeSettings, NodeAuto, SelfTestRun
from .selftests import runner
from .selftests import bootstrap as bootstrap_selftest
from .tests_platform import LATEST, SelfTestRunTests, _Base, mk_node

#: what the owner's node REALLY reported on 2026-11-13 (agent 2.10; trimmed): no "kinds" list, no "bootstrap" block, no "started_at"
OLD_CAPS = {
    "agent": "2.10", "commands": ["status", "update", "restart", "build", "logs"], "hostname": "DESKTOP-EAFBTGQ",
    "platform": "Windows-10-10.0.26200-SP0", "slots": 1, "data_dir": "C:\\Users\\QQz\\NMarketing-data",
    "code": {"version": "2.10", "id": "1f328a7e5b9b7143"}, "comfyui": True, "photo": True, "ollama": True, "video": False, "voice": False,
    "gpu": "NVIDIA GeForce RTX 3060, 12288 MiB", "blender": True, "photo_matting": True, "ffmpeg": True,
    "ollama_models": ["qwen3:8b", "qwq:32b", "qwen3-vl:30b", "qwen3-coder:30b"], "auto_switch": True,
    "startable": {"ollama": True, "comfyui": True, "photo": True}, "managed": {"ollama": "external", "comfyui": "agent"},
}

NEW_KINDS = ["echo", "comfy.graph", "comfy.profile", "ollama.generate", "ollama.chat", "voice.tts", "voice.asr", "voice.music", "photo.matting", "photo.edit",
             "photo.analyze", "edit.render", "edit.matte", "selftest.gpu", "selftest.ffmpeg", "asr.transcribe", "voice.sfx", "node.models", "node.update",
             "multiangle.selftest", "up3d.render", "motion.render", "ig.health", "ig.scrape"]


class OwnersMorningTests(_Base):
    """The beat task of every minute is autopilot.tick(); the node's side is the real HTTP API (heartbeat / claim)."""

    def setUp(self):
        super().setUp()
        ComputeNode.objects.all().delete()
        self.node = ComputeNode.objects.create(name="morning", capabilities=dict(OLD_CAPS), last_seen=timezone.now())
        self.api = APIClient()
        self.auth = {"HTTP_AUTHORIZATION": "Node " + self.node.token}

    def heartbeat(self, caps):
        res = self.api.post("/api/v1/compute/heartbeat/", caps, format="json", **self.auth)
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.node.refresh_from_db()
        return res.json()

    def claim_all(self):
        """The node takes work until the site has none for it; the kinds it was given."""
        kinds = []
        for _ in range(40):
            res = self.api.post("/api/v1/compute/claim/", {}, format="json", **self.auth)
            self.assertEqual(res.status_code, 200)
            job = res.json().get("job")
            if not job:
                break
            kinds.append(job["kind"])
        return kinds

    def new_caps(self, **over):
        caps = {"agent": LATEST["version"], "commands": list(C.ACTIONS), "kinds": list(NEW_KINDS), "code": {"version": LATEST["version"], "id": LATEST["id"][:16]},
                "started_at": int(timezone.now().timestamp()), "hostname": "DESKTOP-EAFBTGQ", "slots": 1, "comfyui": True, "photo": True, "ollama": True,
                "gpu": "NVIDIA GeForce RTX 3060, 12288 MiB", "ffmpeg": True, "auto_switch": True, "startable": {"ollama": True, "comfyui": True, "photo": True},
                "multiangle": True, "multiangle_ready": {"virtual": True, "move": True, "selftest": True}, "instagram": True,
                "ollama_models": ["qwen3:8b", "qwen3-vl:30b"], "bootstrap": {"summary": {"installing": 3, "ready": 2}, "features": {},
                "blocked_kinds": {"asr.transcribe": "asr-gpu: installing", "up3d.render": "blender-3d: installing"}},
                "motion": {"state": "installing"}, "motion_render": True}
        caps.update(over)
        return caps

    def queue_parked_work(self):
        out = {}
        for kind in ("echo", "photo.edit", "comfy.profile", "motion.render", "up3d.render", "asr.transcribe", "ig.scrape"):
            out[kind] = self.job(kind, payload={"parked": kind})
        return out

    def test_the_whole_morning_at_the_site_boundary(self):
        jobs = self.queue_parked_work()
        self.assertTrue(self.node.online)

        # 1. agent 2.10 asks for work: the site holds everything back and sends the update command by itself (once)
        self.assertTrue(autopilot.update_wanted(self.node)[0])
        self.assertEqual(self.claim_all(), [], "an out-of-date node must get no work before it has updated")
        cmd = C.state(self.node)["last"]
        self.assertEqual((cmd["action"], cmd["by"]), ("update", "به‌روزرسانیِ خودکار"))
        self.assertEqual(self.heartbeat(dict(OLD_CAPS)).get("command", {}).get("action"), "update")      # ... and it reaches the node in the heartbeat
        sent = NodeAuto.of(self.node).update_tries
        autopilot.tick()                                                                                 # the beat task, a minute later: not twice
        self.assertEqual(NodeAuto.of(self.node).update_tries, sent)

        # 2. the node updates, restarts and reports in as the new agent while its installs are still running
        C.report(self.node, cmd["id"], "running")
        C.report(self.node, cmd["id"], "done", True, "ok")
        self.heartbeat(self.new_caps())
        self.assertFalse(autopilot.update_wanted(self.node)[0], "the site still thinks the node is out of date")
        run = SelfTestRun.objects.get(node=self.node)
        self.assertEqual((run.trigger, run.agent_version), ("version", LATEST["version"]))
        self.assertEqual(SelfTestRun.objects.filter(node=self.node).count(), 1, "one run, for the NEW version only")
        self.heartbeat(self.new_caps())
        self.assertEqual(SelfTestRun.objects.filter(node=self.node).count(), 1, "the same version again must not start a second run")

        # 3. work that needs a feature that is still installing waits; everything else flows
        got = self.claim_all()
        self.assertTrue({"echo", "photo.edit", "comfy.profile", "ig.scrape"} <= set(got), got)
        for waiting in ("motion.render", "up3d.render", "asr.transcribe"):
            self.assertNotIn(waiting, got, "%s was handed out while its feature is still being installed" % waiting)
            self.assertEqual(ComputeJob.objects.get(pk=jobs[waiting].pk).state, "QUEUED")

        # 4. the installs finish (reported in the next heartbeat): the waiting jobs go out by themselves
        self.heartbeat(self.new_caps(bootstrap={"summary": {"ready": 5}, "features": {}, "blocked_kinds": {}}, motion={"state": "ready"}))
        later = self.claim_all()                                   # (the acceptance run's own jobs of these kinds go out too)
        self.assertTrue({"asr.transcribe", "motion.render", "up3d.render"} <= set(later), later)
        for kind in ("motion.render", "up3d.render", "asr.transcribe"):
            self.assertEqual(ComputeJob.objects.get(pk=jobs[kind].pk).state, "CLAIMED", "%s parked before the update did not go out" % kind)

    def test_jobs_parked_while_the_node_was_off_wake_when_it_is_back(self):
        """(The acceptance run of the new version is switched off here: its jobs rightly take the node's one slot first - parked work is woken
        one job per free slot, see park._free_slots - so with the run active the parked jobs follow when it has finished.)"""
        from apps.jobs.models import Job
        from apps.stores.models import Store
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_selftest": False})

        user = get_user_model().objects.create_user("morning-owner", "m@x.io", "pw")
        store = Store.objects.create(owner=user, name="morning-shop")
        self.node.last_seen = timezone.now() - timedelta(hours=20)
        self.node.save()
        rows = []
        for cap in ("ollama", "comfyui"):
            row = Job.objects.create(store=store, type=Job.Type.IMAGE_GENERATION, state="QUEUED")
            ComputeJob.objects.create(kind=park.PARK_KIND, state="QUEUED", queued_at=timezone.now(), timeout_s=0, request_hash="",
                                      payload={"capability": cap, "task": "t", "args": [row.pk], "kwargs": {}, "ref": {"model": "jobs.Job", "id": row.pk}})
            rows.append(row)
        with mock.patch.object(park, "_dispatch", return_value=True) as dispatch:
            self.assertEqual(park.wake_parked(), 0, "the node is off: nothing is woken")
            self.heartbeat(self.new_caps(bootstrap={"summary": {"ready": 5}, "features": {}, "blocked_kinds": {}}, motion={"state": "ready"}))
            woken = park.wake_parked()
            woken += park.wake_parked()
        self.assertEqual(woken, 2, "both parked jobs are woken once the node answers")
        self.assertEqual(dispatch.call_count, 2)
        self.assertFalse(ComputeJob.objects.filter(kind=park.PARK_KIND, state="QUEUED").exists())

    def test_the_download_window_is_part_of_what_the_site_tells_the_node(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "window", "download_window": "02:00-07:00"})
        res = self.heartbeat(self.new_caps())
        self.assertEqual(res["downloads"]["mode"], "window")
        self.assertEqual(res["downloads"]["window"], "02:00-07:00")
        ComputeSettings.objects.update_or_create(pk=1, defaults={"download_mode": "now"})
        self.assertEqual(self.heartbeat(self.new_caps())["downloads"]["mode"], "now")

    def test_the_readiness_report_names_what_waits_for_what(self):
        self.queue_parked_work()
        rows = {r["key"]: r for r in readiness.node_rows(self.node)}
        self.assertEqual(rows["node_agent"]["state"], "info")
        self.assertIn("دستورِ به‌روزرسانی", rows["node_agent"]["detail"])
        queue = rows["node_queue"]
        self.assertEqual(set(queue["needs_update"]), {"motion.render", "up3d.render", "asr.transcribe", "ig.scrape"})
        self.assertEqual(set(queue["ready"]), {"echo", "photo.edit", "comfy.profile"})
        self.heartbeat(self.new_caps())
        rows = {r["key"]: r for r in readiness.node_rows(self.node)}
        self.assertEqual(rows["node_agent"]["state"], "ok")
        self.assertEqual(set(rows["node_queue"]["installing"]), {"motion.render", "up3d.render", "asr.transcribe"})


class PhotoSelfTestTests(_Base):
    """selftests/photo_edit.py: the photo editors have an acceptance test (auto edit + analysis) like every other feature."""

    run_jobs = SelfTestRunTests.run_jobs
    answer_command = SelfTestRunTests.answer_command
    drive = SelfTestRunTests.drive

    def setUp(self):
        super().setUp()
        self.node.capabilities.update({"photo": True, "kinds": self.node.capabilities["kinds"] + ["photo.analyze"], "bootstrap": {
            "summary": {"ready": 1}, "blocked_kinds": {}, "features": {}}})
        self.node.save()

    @staticmethod
    def picture(flat=False):
        from PIL import Image
        b = io.BytesIO()
        (Image.new("RGB", (128, 128), (200, 30, 30)) if flat else Image.frombytes("RGB", (128, 128), os.urandom(128 * 128 * 3))).save(b, "PNG")
        return b.getvalue()

    def run_photo(self, handler):
        run = runner.start_run(self.node, "manual", only=["photo_edit", "photo_analyze"])
        run = self.drive(run, handler)
        return {r.key: r for r in run.results.all()}

    def test_a_working_photo_service_passes_both(self):
        def good(job):
            if job.kind == "photo.edit":
                self.assertEqual(job.payload["recipe"]["output"]["format"], "png")
                return {"selftest-edited.png": self.picture()}, {}
            return {"analyze.json": json.dumps({"exposure": 0.4, "faces": 0}).encode()}, {}
        rows = self.run_photo(good)
        self.assertEqual((rows["photo_edit"].state, rows["photo_analyze"].state), ("PASSED", "PASSED"), {k: r.detail for k, r in rows.items()})
        self.assertIn("128×128", rows["photo_edit"].detail)

    def test_an_empty_or_flat_picture_and_an_empty_analysis_fail_with_the_reason(self):
        def bad(job):
            if job.kind == "photo.edit":
                return {"selftest-edited.png": self.picture(flat=True)}, {}
            return {"analyze.json": b"{}"}, {}
        rows = self.run_photo(bad)
        self.assertEqual(rows["photo_edit"].state, "FAILED")
        self.assertIn("تک‌رنگ", rows["photo_edit"].detail)
        self.assertEqual(rows["photo_analyze"].state, "FAILED")

    def test_no_picture_at_all_is_a_failure(self):
        rows = self.run_photo(lambda job: ({"note.txt": b"x"} if job.kind == "photo.edit" else {"analyze.json": b"{\"a\": 1}"}, {}))
        self.assertEqual(rows["photo_edit"].state, "FAILED")
        self.assertIn("هیچ تصویری", rows["photo_edit"].detail)

    def test_a_node_without_the_photo_service_is_skipped_not_failed(self):
        self.node.capabilities.update({"photo": False, "startable": {}})
        self.node.save()
        run = runner.start_run(self.node, "manual", only=["photo_edit"])
        run = self.drive(run, lambda job: self.fail("no job may be sent"))
        row = run.results.get(key="photo_edit")
        self.assertEqual(row.state, "SKIPPED")
        self.assertIn("ویرایشگرِ عکس", row.detail)

    def test_only_the_analysis_is_optional(self):
        from .selftests import REGISTRY, load_all
        load_all()
        self.assertFalse(REGISTRY["photo_edit"].optional)
        self.assertTrue(REGISTRY["photo_analyze"].optional)
        self.assertEqual(REGISTRY["photo_edit"].kind, "photo.edit")
