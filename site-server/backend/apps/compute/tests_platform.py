# -*- coding: utf-8 -*-
"""پلتفرمِ گره (۱۴۰۵/۰۸/۲۱): نوبت‌دهیِ عادلانه، راهروی سبک، نوعِ پشتیبانی‌شده، نصبِ خودکار، به‌روزرسانیِ خودکار، پذیرشِ نتیجهٔ
گرهٔ قطع‌شده، آزمونِ خودکار (اجرا، سنجش، بازگرداندنِ کارهای ناموفق) و APIِ پنل."""
import json
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import autopilot, sched
from . import commands as C
from . import services as SV
from .models import ComputeJob, ComputeNode, ComputeSettings, NodeAuto, RequeueRecord, SelfTestResult, SelfTestRun
from .selftests import REGISTRY, Verdict, docs_loader, load_all, png, runner
from .selftests import bootstrap as bootstrap_selftest
from .selftests import requeue as requeue_mod

LATEST = {"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb", "size": 1, "built": "x"}


def models_caps():
    """What an agent that has the model catalog reports in caps["models"]: every package installed, disk known, nothing failing."""
    from . import auto_models, model_packages as MP
    pk = {k: {"installed": True, "total_mb": int(c.get("size_mb") or 0), "in_comfyui": 0} for k, c in MP.catalog().items()}
    return {"packages": pk, "disk_mb": {"comfyui": 90000, "models": 90000}, "auto": {"states": {p: "installed" for p in auto_models.wanted()}}}


def mk_node(name="gpu-p", **caps):
    base = {"agent": "2.11", "kinds": ["echo", "comfy.graph", "comfy.profile", "ollama.generate", "ollama.chat", "voice.tts", "voice.asr",
                                      "photo.matting", "edit.render", "selftest.gpu", "selftest.ffmpeg", "asr.transcribe", "voice.sfx",
                                      "edit.track", "node.models", "ollama.pull", "node.update", "node.bench", "photo.edit"],
            "comfyui": True, "ollama": True, "voice": True, "ffmpeg": True, "commands": list(C.ACTIONS),
            "code": {"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"}, "started_at": 1000}
    base.update(caps)
    return ComputeNode.objects.create(name=name, capabilities=base, last_seen=timezone.now())


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-platform-test-"))
        self.ctx = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True)
        self.ctx.enable()
        self.patch_latest = mock.patch.object(autopilot.U, "latest", return_value=dict(LATEST))
        self.patch_latest.start()
        self.node = mk_node()

    def tearDown(self):
        self.patch_latest.stop()
        self.ctx.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def job(self, kind="ollama.generate", priority=100, **kw):
        return SV.enqueue(kind, kw.pop("payload", {"n": kw.get("n", 0), "k": kind}), dedupe=False, require_online=False, priority=priority,
                          **{k: v for k, v in kw.items() if k != "n"})

    def finish_ok(self, job, outputs=None, meta=None, node=None):
        """The node's side: write the outputs and end the job."""
        for name, data in (outputs or {}).items():
            SV.output_path(job, name).write_bytes(data)
        job.refresh_from_db()
        job.claimed_at = job.claimed_at or timezone.now() - timedelta(seconds=3)
        job.state = ComputeJob.State.RUNNING
        job.node = node or self.node
        job.save()
        return SV.finish(job, node or self.node, True, meta=meta or {})


class SchedulerTests(_Base):
    def test_classes(self):
        wan = self.job("comfy.profile", payload={"profile": "wan22-480p-short"})
        flux = self.job("comfy.profile", payload={"profile": "flux-product-fast"})
        text = self.job("ollama.generate")
        pull = self.job("ollama.pull", payload={"tag": "x"})
        self.assertEqual(sched.job_class(wan, self.node), "long")
        self.assertEqual(sched.job_class(flux, self.node), "medium")
        self.assertEqual(sched.job_class(text, self.node), "short")
        self.assertEqual(sched.job_class(pull, self.node), "download")
        video_graph = self.job("comfy.graph", payload={"graph": {"1": {"class_type": "WanImageToVideo"}}})
        self.assertEqual(sched.job_class(video_graph, self.node), "long")
        slow_text = self.job("ollama.generate", payload={"x": 1}, timeout_s=7200)
        self.assertEqual(sched.job_class(slow_text, self.node), "long")

    def test_learned_average_beats_the_default(self):
        self.node.stats = {"ollama.generate": {"seconds": 400.0, "n": 5}}
        self.node.save()
        self.assertEqual(sched.job_class(self.job("ollama.generate"), self.node), "medium")

    def test_a_long_job_does_not_block_thirty_short_ones(self):
        wan = self.job("comfy.profile", payload={"profile": "wan22-480p-short"})            # queued FIRST
        shorts = [self.job("ollama.generate", payload={"i": i}) for i in range(30)]
        got = []
        for _ in range(5):
            j = SV.claim(self.node)
            got.append(j)
        self.assertTrue(all(j.kind == "ollama.generate" for j in got))
        self.assertNotIn(wan.pk, [j.pk for j in got])
        self.assertEqual([j.pk for j in got], [s.pk for s in shorts[:5]])                    # oldest short first

    def test_after_a_burst_of_shorts_the_long_job_gets_its_turn(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"short_burst": 3})
        wan = self.job("comfy.profile", payload={"profile": "wan22-480p-short"})
        for i in range(10):
            self.job("ollama.generate", payload={"i": i})
        kinds = [SV.claim(self.node).kind for _ in range(5)]
        self.assertEqual(kinds, ["ollama.generate"] * 3 + ["comfy.profile", "ollama.generate"])
        self.assertEqual(NodeAuto.of(self.node).short_streak, 1)
        wan.refresh_from_db()
        self.assertEqual(wan.state, "CLAIMED")

    def test_a_long_job_waiting_over_two_hours_goes_first(self):
        wan = self.job("comfy.profile", payload={"profile": "wan22-480p-short"})
        ComputeJob.objects.filter(pk=wan.pk).update(queued_at=timezone.now() - timedelta(hours=3))
        for i in range(3):
            self.job("ollama.generate", payload={"i": i})
        self.assertEqual(SV.claim(self.node).pk, wan.pk)

    def test_lower_priority_number_always_wins(self):
        self.job("comfy.profile", priority=10, payload={"profile": "wan22-480p-short"})
        self.job("ollama.generate", priority=50)
        self.assertEqual(SV.claim(self.node).kind, "comfy.profile")

    def test_downloads_run_only_when_nothing_else_waits(self):
        pull = self.job("ollama.pull", payload={"tag": "qwen3:8b"})
        text = self.job("ollama.generate")
        self.assertEqual(SV.claim(self.node).pk, text.pk)
        self.assertIsNone(SV.claim(self.node), "the node is busy with the text job: the download keeps waiting")
        ComputeJob.objects.filter(pk=text.pk).update(state=ComputeJob.State.COMPLETED, finished_at=timezone.now())
        self.assertEqual(SV.claim(self.node).pk, pull.pk)

    def test_engine_stickiness_avoids_needless_model_swaps(self):
        NodeAuto.objects.update_or_create(node=self.node, defaults={"last_engine": "ollama"})
        a = self.job("echo", payload={"i": 1})
        b = self.job("ollama.generate", payload={"i": 2})
        c = self.job("ollama.generate", payload={"i": 3})
        del a
        order = [SV.claim(self.node).pk for _ in range(3)]
        self.assertEqual(order[:2], [b.pk, c.pk])

    def test_progress_by_kind(self):
        q = self.job("ollama.generate")
        done = self.job("echo")
        self.finish_ok(done)
        p = sched.progress_by_kind()
        self.assertEqual(p["kinds"]["ollama.generate"]["queued"], 1)
        self.assertEqual(p["kinds"]["echo"]["done"], 1)
        self.assertEqual(p["totals"]["queued"], 1)
        self.assertEqual(p["percent"], 50)
        del q


class LaneAndKindTests(_Base):
    def test_the_light_lane_gets_only_gpu_neutral_kinds(self):
        self.job("comfy.profile", payload={"profile": "wan22-480p-short"})
        self.job("ollama.generate")
        self.assertIsNone(SV.claim(self.node, lane="light"))
        echo = self.job("echo")
        self.assertEqual(SV.claim(self.node, lane="light").pk, echo.pk)

    def test_an_agent_without_the_kind_list_gets_only_the_kinds_it_always_had(self):
        old = mk_node("old-agent", agent="2.10", kinds=None)
        old.capabilities.pop("kinds")
        old.save()
        new_kind = self.job("selftest.gpu", node=old.name)
        legacy = self.job("ollama.generate", node=old.name)
        got = SV.claim(old)
        self.assertEqual(got.pk, legacy.pk)
        self.assertIsNone(SV.claim(old))
        new_kind.refresh_from_db()
        self.assertEqual(new_kind.state, "QUEUED")                 # waits in the durable queue, never fails

    def test_an_agent_with_the_list_gets_new_kinds_and_not_unknown_ones(self):
        known = self.job("selftest.gpu", node=self.node.name)
        unknown = self.job("motion.render", node=self.node.name)
        self.assertEqual(SV.claim(self.node).pk, known.pk)
        self.assertIsNone(SV.claim(self.node))
        unknown.refresh_from_db()
        self.assertEqual(unknown.state, "QUEUED")
        self.node.capabilities["kinds"] = self.node.capabilities["kinds"] + ["motion.render"]
        self.node.save()
        self.assertTrue(SV.kind_unsupported(self.node, unknown) is False)

    def test_http_relay_kinds_follow_the_agents_relay_list(self):
        j = self.job("voice.http", payload={"method": "GET", "path": "/x"})
        self.node.capabilities["http_relays"] = ["voice"]
        self.node.save()
        self.assertFalse(SV.kind_unsupported(self.node, j))
        self.node.capabilities["http_relays"] = []
        self.assertTrue(SV.kind_unsupported(self.node, j))

    def test_a_kind_whose_feature_is_still_installing_waits(self):
        j = self.job("asr.transcribe", node=self.node.name)
        self.node.capabilities["bootstrap"] = {"blocked_kinds": {"asr.transcribe": "asr-gpu: installing"}, "features": {}}
        self.node.save()
        self.assertIsNone(SV.claim(self.node))
        self.node.capabilities["bootstrap"] = {"blocked_kinds": {}, "features": {}}
        self.node.save()
        self.assertEqual(SV.claim(self.node).pk, j.pk)


class OrphanAdoptionTests(_Base):
    def api(self, node):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Node " + node.token)
        return c

    def lose_the_node(self, job):
        """The node vanished mid-job: the lease ran out and the site put the job back in the queue."""
        job.refresh_from_db()
        ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1))
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(hours=1))
        SV.requeue_stale()
        job.refresh_from_db()
        return job

    def test_a_result_finished_during_a_dead_line_is_accepted_when_the_same_node_returns(self):
        job = self.job("ollama.generate")
        claimed = SV.claim(self.node)
        self.assertEqual(claimed.pk, job.pk)
        job = self.lose_the_node(job)
        self.assertEqual((job.state, job.node_id, job.last_node_name), ("QUEUED", None, self.node.name))
        c = self.api(self.node)
        SV.output_path(job, "ollama.json").write_bytes(b"{}")
        r = c.post("/api/v1/compute/jobs/%s/finish/" % job.uid, {"ok": True, "meta": {"device": "cuda"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        job.refresh_from_db()
        self.assertEqual(job.state, "COMPLETED")
        self.assertEqual(job.node_id, self.node.pk)
        self.assertEqual(job.result["meta"]["device"], "cuda")

    def test_progress_after_the_line_returns_keeps_the_job_alive_instead_of_aborting_it(self):
        job = self.job("ollama.generate")
        SV.claim(self.node)
        self.lose_the_node(job)
        r = self.api(self.node).post("/api/v1/compute/jobs/%s/progress/" % job.uid, {"progress": 0.5, "message": "x"}, format="json")
        self.assertEqual(r.status_code, 200)
        job.refresh_from_db()
        self.assertEqual((job.state, job.node_id), ("RUNNING", self.node.pk))

    def test_another_node_cannot_take_over_and_a_claimed_job_is_not_stolen(self):
        job = self.job("ollama.generate")
        SV.claim(self.node)
        other = mk_node("other")
        self.lose_the_node(job)
        r = self.api(other).post("/api/v1/compute/jobs/%s/finish/" % job.uid, {"ok": True}, format="json")
        self.assertEqual(r.status_code, 403)
        again = SV.claim(other)                                   # somebody else took it meanwhile
        self.assertEqual(again.pk, job.pk)
        r = self.api(self.node).post("/api/v1/compute/jobs/%s/finish/" % job.uid, {"ok": True}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_cancelled_job_is_not_revived(self):
        job = self.job("ollama.generate")
        SV.claim(self.node)
        self.lose_the_node(job)
        SV.cancel(job, "کاربر لغو کرد")
        r = self.api(self.node).post("/api/v1/compute/jobs/%s/progress/" % job.uid, {"progress": 0.5}, format="json")
        self.assertEqual(r.status_code, 403)


class AutopilotTests(_Base):
    def old_node(self, **kw):
        n = mk_node("old", agent="2.10", code={"version": "2.10", "id": "aaaaaaaaaaaaaaaa"}, **kw)
        return n

    def test_new_package_and_an_idle_node_get_the_update_command_by_themselves(self):
        n = self.old_node()
        self.assertTrue(autopilot.update_wanted(n)[0])
        sent = autopilot.send_update(n)
        self.assertEqual(sent["action"], "update")
        self.assertEqual(sent["by"], "به‌روزرسانیِ خودکار")
        self.assertEqual(NodeAuto.of(n).update_tries, 1)
        self.assertIsNone(autopilot.send_update(n))               # not twice in a row

    def test_the_setting_turns_it_off(self):
        n = self.old_node()
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_update": False})
        self.assertFalse(autopilot.update_wanted(n)[0])
        self.assertIsNone(autopilot.send_update(n))
        self.assertFalse(autopilot.should_withhold(n))

    def test_up_to_date_node_is_left_alone(self):
        self.assertFalse(autopilot.update_wanted(self.node)[0])

    def test_no_new_job_is_given_to_an_out_of_date_node_until_it_updated(self):
        n = self.old_node()
        j = self.job("echo", node="old")
        self.assertIsNone(SV.claim(n))                            # withheld
        self.assertEqual(C.state(n)["last"]["action"], "update")  # ... and the update command went out
        j.refresh_from_db()
        self.assertEqual(j.state, "QUEUED")
        n.capabilities.update(agent="2.11", code={"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"})
        n.save()
        self.assertEqual(SV.claim(n).pk, j.pk)

    def test_a_busy_node_finishes_its_job_first(self):
        n = self.old_node()
        running = self.job("ollama.generate", node="old")
        ComputeJob.objects.filter(pk=running.pk).update(state="RUNNING", node=n, claimed_at=timezone.now())
        self.job("echo", node="old")
        self.assertIsNone(SV.claim(n))
        self.assertEqual(C.state(n)["last"], {})                  # no command while a job runs
        ComputeJob.objects.filter(pk=running.pk).update(state="COMPLETED")
        self.assertIsNone(SV.claim(n))
        self.assertEqual(C.state(n)["last"]["action"], "update")

    def test_a_node_that_cannot_be_updated_is_not_starved_forever(self):
        n = self.old_node()
        j = self.job("echo", node="old")
        auto = NodeAuto.of(n)
        auto.update_pkg, auto.update_tries = LATEST["id"], autopilot.MAX_AUTO_TRIES
        auto.save()
        self.assertFalse(autopilot.should_withhold(n))
        self.assertEqual(SV.claim(n).pk, j.pk)

    def test_a_node_that_does_not_know_the_update_command_still_gets_work(self):
        n = self.old_node()
        n.capabilities["commands"] = ["status"]
        n.save()
        self.assertFalse(autopilot.update_wanted(n)[0])

    def test_new_agent_version_starts_one_acceptance_run(self):
        self.node.capabilities["agent"] = "2.12"
        self.node.save()
        with mock.patch.object(runner, "start_run") as sr:
            autopilot.on_heartbeat(self.node)
            autopilot.on_heartbeat(self.node)                       # same version again: nothing
        self.assertEqual(sr.call_count, 1)
        self.assertEqual(sr.call_args[0][1], "version")
        self.node.capabilities["agent"] = "2.13"
        self.node.save()
        with mock.patch.object(runner, "start_run") as sr:
            autopilot.on_heartbeat(self.node)
        self.assertEqual(sr.call_count, 1)

    def test_the_first_heartbeat_of_an_old_agent_makes_no_run_the_updated_agent_gets_one_clean_run(self):
        """The owner's night: the node is switched on with agent 2.10, the site updates it by itself, and the run is made for the NEW
        version - not a report full of «failed» for the old agent that is being replaced a few seconds later."""
        n = self.old_node()
        autopilot.on_heartbeat(n)                                   # first heartbeat: still 2.10, update is coming
        self.assertEqual(SelfTestRun.objects.count(), 0)
        self.assertEqual(NodeAuto.of(n).last_selftest_key, "")      # not marked as handled
        self.assertEqual(autopilot.send_update(n)["action"], "update")
        autopilot.on_heartbeat(n)                                   # still 2.10 while it downloads: still no run
        self.assertEqual(SelfTestRun.objects.count(), 0)
        n.capabilities.update(agent="2.11", code={"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"})
        n.save()
        autopilot.on_heartbeat(n)                                   # back as 2.11
        runs = list(SelfTestRun.objects.filter(node=n))
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0].agent_version, runs[0].trigger, runs[0].state), ("2.11", "version", "RUNNING"))

    def test_a_run_made_for_the_old_version_is_replaced_when_the_new_version_arrives(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_update": False})
        n = self.old_node()
        autopilot.on_heartbeat(n)                                   # the site is not allowed to update it: a run for 2.10 starts
        old = SelfTestRun.objects.get(node=n)
        self.assertEqual(old.agent_version, "2.10")
        old_jobs = list(ComputeJob.objects.filter(origin="selftest"))
        n.capabilities.update(agent="2.11", code={"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"})
        n.save()
        autopilot.on_heartbeat(n)
        old.refresh_from_db()
        self.assertEqual(old.state, "ABORTED")
        self.assertIn("نسخهٔ عاملِ سرور عوض شد", old.note)
        self.assertTrue(all(r.final for r in old.results.all()))
        self.assertTrue(all(ComputeJob.objects.get(pk=j.pk).final for j in old_jobs))
        new = runner.active_run(n)
        self.assertNotEqual(new.pk, old.pk)
        self.assertEqual(new.agent_version, "2.11")
        self.assertEqual(SelfTestRun.objects.filter(node=n, state="RUNNING").count(), 1)

    def test_the_manual_button_also_replaces_a_run_of_a_version_that_is_gone(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_update": False})
        n = self.old_node()
        old = runner.start_run(n, "manual")
        self.assertEqual(runner.start_run(n, "manual").pk, old.pk)       # same version: the running one is returned
        n.capabilities.update(agent="2.11", code={"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"})
        n.save()
        new = runner.start_run(n, "manual")
        self.assertNotEqual(new.pk, old.pk)
        self.assertEqual(new.agent_version, "2.11")

    def test_a_run_that_sent_the_update_command_itself_is_left_to_finish(self):
        """update_flow sent «update» and waits for the agent: the agent coming back with a new version must not abort that very run."""
        n = self.node
        run = runner.start_run(n, "manual")
        SelfTestResult.objects.filter(run=run, key="update_flow").update(state="WAITING", extra={"cmd_id": 7, "action": "update"})
        n.capabilities.update(agent="2.12", code={"version": "2.12", "id": "cccccccccccccccccccc"})
        n.save()
        with mock.patch.object(autopilot.U, "latest", return_value={"version": "2.12", "id": "cccccccccccccccccccc", "size": 1, "built": "x"}):
            autopilot.on_heartbeat(n)
            self.assertEqual(SelfTestRun.objects.filter(node=n).count(), 1)
            self.assertEqual(runner.start_run(n, "manual").pk, run.pk)
            self.assertEqual(NodeAuto.of(n).last_selftest_key, "")      # not handled yet: the next heartbeat after the run makes the new one
            SelfTestResult.objects.filter(run=run).update(state="PASSED", extra={})
            runner.finish_run(run)
            autopilot.on_heartbeat(n)
        runs = SelfTestRun.objects.filter(node=n).order_by("pk")
        self.assertEqual(runs.count(), 2)
        self.assertEqual(runs.last().agent_version, "2.12")

    def test_the_nightly_run_waits_for_a_pending_update_and_keeps_its_day(self):
        n = self.old_node()
        today = "2026-11-13"
        due = lambda node, cfg, now=None: today if node.pk == n.pk else ""        # noqa: E731
        with mock.patch.object(autopilot, "nightly_due", side_effect=due), mock.patch.object(runner, "start_run") as sr,                 mock.patch.object(runner, "advance_all", return_value={}):
            autopilot.tick()
            sr.assert_not_called()
            self.assertEqual(NodeAuto.of(n).last_nightly, "")
            n.capabilities.update(agent="2.11", code={"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"})
            n.save()
            autopilot.tick()
        self.assertEqual(sr.call_count, 1)
        self.assertEqual(sr.call_args[0][1], "nightly")
        self.assertEqual(NodeAuto.of(n).last_nightly, today)

    def test_the_setting_turns_the_version_trigger_off(self):
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_selftest": False})
        with mock.patch.object(runner, "start_run") as sr:
            autopilot.on_heartbeat(self.node)
        sr.assert_not_called()

    def test_nightly_run_once_per_tehran_day_at_the_set_time(self):
        cfg = ComputeSettings.get()
        cfg.nightly_time = "03:30"
        cfg.save()
        # 00:10 UTC = 03:40 Tehran
        at = timezone.now().replace(hour=0, minute=10, second=0, microsecond=0)
        self.assertTrue(autopilot.nightly_due(self.node, cfg, at))
        early = at.replace(hour=23, minute=0) - timedelta(days=1)        # 02:30 Tehran
        self.assertEqual(autopilot.nightly_due(self.node, cfg, early), "")
        with mock.patch.object(runner, "start_run") as sr, mock.patch.object(runner, "advance_all", return_value={}), \
                mock.patch.object(autopilot.SV, "tehran_now", lambda now=None: at + timedelta(hours=3, minutes=30)):
            autopilot.tick(at)
            autopilot.tick(at)
        self.assertEqual(sr.call_count, 1)
        self.assertEqual(sr.call_args[0][1], "nightly")

    def test_maintenance_task_runs_the_autopilot(self):
        from .tasks import maintenance

        with mock.patch.object(autopilot, "tick", return_value={"updates": 0}) as t:
            out = maintenance()
        self.assertTrue(t.called)
        self.assertIn("autopilot", out)


class SelfTestRunTests(_Base):
    """The whole acceptance run with a pretend node that finishes the jobs it is given."""

    def setUp(self):
        super().setUp()
        load_all()
        self.node.capabilities.update({
            "gpu": "RTX 3060", "ollama_models": ["qwen3:8b", "qwq:32b", "qwen3-vl:30b"], "photo_matting": True,
            "matting_runtime": {"ok": True, "gpu": True, "providers": ["Dml"]},
            "matting_models": {"u2netp": {"state": "installed"}}, "audio": {"moss": True, "sfx": True, "music": True},
            "edit": {"render": True, "nvenc": {"h264": True}}, "comfy_profiles": ["flux-product-fast", "wan22-480p-short"],
            "bootstrap": {"summary": {"ready": 2}, "blocked_kinds": {}, "features": {"gpu-runtime": {"state": "ready", "title": "x", "items": []}}},
            "outbox": {"pending": 0}, "net": {"offline_s": 0}, "lanes": {"light": 1}, "models": models_caps()})
        self.node.save()

    def run_jobs(self, run, handler):
        """Let the pretend node answer every queued selftest job once; returns how many it did."""
        n = 0
        node = ComputeNode.objects.get(pk=self.node.pk)
        for r in run.results.filter(state__in=["QUEUED", "WAITING", "RUNNING"]).exclude(job_uid=None):
            job = ComputeJob.objects.get(uid=r.job_uid)
            if job.final or SV.job_blocked(node, job):               # the real site never hands a blocked kind to the node
                continue
            out, meta = handler(job)
            self.finish_ok(job, out, meta)
            n += 1
        return n

    def answer_command(self):
        """The pretend agent: takes the panel command that was sent (update / restart), says it is done and comes back with a newer start time."""
        n = ComputeNode.objects.get(pk=self.node.pk)
        last = C.state(n).get("last") or {}
        if last.get("state") in ("sent", "running"):
            C.report(n, last["id"], "running")
            C.report(n, last["id"], "done", True, "ok")
            n.capabilities["started_at"] = int(timezone.now().timestamp()) + 5
            n.save()

    def drive(self, run, handler, rounds=8):
        # the pretend agent «restarts» at once (answer_command) and the clock never moves in a test: the three minutes a freshly started
        # agent is given to start its installer are not waited for here (they have tests of their own)
        with mock.patch.object(runner, "YOUNG_AGENT_S", -1000), mock.patch.object(bootstrap_selftest, "YOUNG_AGENT_S", -1000):
            for _ in range(rounds):
                runner.advance(run)
                run.refresh_from_db()
                if run.state != "RUNNING":
                    break
                self.run_jobs(run, handler)
                self.answer_command()
        run.refresh_from_db()
        return run

    @staticmethod
    def good(job):
        k, p = job.kind, job.payload or {}
        if k == "echo":
            return {"echo.json": json.dumps({"node": "gpu-p"}).encode()}, {}
        if k == "selftest.gpu":
            return {"gpu.json": json.dumps({"visible": True, "name": "RTX 3060", "vram_total_mb": 12288, "driver": "560.1", "driver_ok": True,
                                            "envs": {"moss-tts": {"torch": {"torch": "2.9", "cuda": True}}},
                                            "ffmpeg": {"nvenc_h264": True, "path": "ffmpeg"}}).encode()}, {"device": "cuda"}
        if k == "selftest.ffmpeg":
            return {"ffmpeg.json": json.dumps({"nvenc_h264": True, "encode_seconds": 0.4, "size": 9000, "nvdec": {"ok": True}, "version": "7.1"}).encode(),
                    "nvenc.mp4": b"x" * 9000}, {"device": "nvenc"}
        if k == "ollama.generate":
            if p.get("images"):
                return {"ollama.json": json.dumps({"response": "Red"}).encode()}, {"device": "cuda"}
            if "design:" in str(p.get("prompt") or ""):        # آزمونِ «سایت‌ساز: سبک و قطعه در حالتِ AI» (selftests/site_styles.py): مدل HTMLِ قطعه‌دار می‌دهد
                html = ('<section class="nb-section nbc nbc-hero-center-glow"><div class="nb-wrap"><h1>با چغر چغر تر شو</h1>'
                        '<p>دستیار هوش مصنوعیِ مربی‌ها؛ پیش‌نویسِ برنامه را می‌سازد و تصمیمِ نهایی با مربی است.</p></div></section>')
                return {"ollama.json": json.dumps({"response": html, "eval_count": 60, "eval_duration": 2000000000}).encode()}, {"device": "cuda"}
            return {"ollama.json": json.dumps({"response": "چغر، دستیارِ هوشمندِ مربی‌های ورزشی، برنامهٔ هر ورزشکار را سریع پیش‌نویس می‌کند.", "eval_count": 20, "eval_duration": 1000000000}).encode()}, {"device": "cuda"}
        if k == "comfy.profile":
            import io
            import os

            from PIL import Image
            noisy = Image.frombytes("RGB", (256, 256), os.urandom(256 * 256 * 3)).resize((512, 512))
            b = io.BytesIO()
            noisy.save(b, "PNG")
            return {"o.png": b.getvalue()}, {"device": "cuda"}
        if k == "photo.matting":
            from PIL import Image
            import io
            m = Image.new("L", (64, 64), 0)
            for x in range(20, 44):
                for y in range(20, 44):
                    m.putpixel((x, y), 255)
            b = io.BytesIO()
            m.save(b, "PNG")
            return {"mask.png": b.getvalue(), "cutout.png": b"png" * 100}, {"device": "directml"}
        if k == "edit.render":
            return {"render.mp4": b"v" * 9000}, {"encoder": "NVENC H.264", "device": "nvenc"}
        if k == "voice.tts":
            import io
            import wave
            b = io.BytesIO()
            with wave.open(b, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\0\0" * 32000)
            return {"speech.wav": b.getvalue()}, {"device": "cuda" if p.get("engine") == "moss-fa" else ""}
        if k == "voice.asr":
            return {"asr.json": json.dumps({"text": "سلام با چغر چغرتر شو چغر برنامه ورزشی و غذایی هر ورزشکار را در کمتر از یک دقیقه پیش نویس می کند"}).encode()}, {}
        if k == "asr.transcribe":
            return {"transcript.json": json.dumps({"text": "سلام. با چغر، چغرتر شو. چغر برنامهٔ ورزشی و غذاییِ هر ورزشکار را در کمتر از یک دقیقه پیش‌نویس می‌کند.", "words": [1]}).encode()}, {"device": "cuda", "compute_type": "float16"}
        if k == "voice.sfx":
            import io
            import wave
            b = io.BytesIO()
            with wave.open(b, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\0\0" * 40000)
            return {"sfx.wav": b.getvalue()}, {"device": "cuda"}
        if k == "node.models":
            return {"models.json": json.dumps({"result": "started", "status": {"running": True}}).encode()}, {}
        if k == "comfy.graph":
            # آزمونِ «thumbs_bg» (تامنیل‌ساز › پس‌زمینهٔ هوش مصنوعی)؛ فقط وقتی اپِ apps.thumbs نصب است ثبت می‌شود: یک گرادیانِ ۵۱۲×۵۱۲
            import io

            import numpy as np
            from PIL import Image
            h = w = int((p.get("x_thumbbg") or {}).get("size", [512])[0])
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            arr = np.stack([60 + 150 * xx / w, 40 + 120 * yy / h, 160 - 90 * xx / w], axis=2).clip(0, 255).astype(np.uint8)
            b = io.BytesIO()
            Image.fromarray(arr).save(b, "PNG")
            return {"thumbbg_00001_.png": b.getvalue()}, {"primary": "thumbbg_00001_.png", "engine": "comfyui", "device": "cuda"}
        raise AssertionError("unexpected kind " + k)

    def test_a_good_node_passes_everything_and_the_report_says_so(self):
        run = runner.start_run(self.node, "manual", by="staff")
        keys = {r.key for r in run.results.all()}
        self.assertTrue({"echo", "gpu", "ffmpeg_nvenc", "ollama_text", "ollama_vision", "comfy_flux", "matting", "tts_piper", "tts_moss",
                         "asr_vosk", "asr_gpu", "edit_render", "bootstrap", "net", "update_flow"} <= keys)
        self.assertNotIn("comfy_wan", keys)                                                      # deep only
        run = self.drive(run, self.good)
        rows = {r.key: r for r in run.results.all()}
        bad = {k: (r.state, r.detail) for k, r in rows.items() if r.state not in ("PASSED", "SKIPPED")}
        self.assertEqual(bad, {})
        self.assertEqual(run.state, "FINISHED")
        js = runner.run_json(run)
        self.assertTrue(js["summary"]["ok"])
        self.assertEqual(rows["gpu"].device, "cuda")
        self.assertEqual(rows["ffmpeg_nvenc"].device, "nvenc")
        self.assertEqual(rows["matting"].device, "directml")
        self.assertTrue(rows["comfy_flux"].artifacts and rows["comfy_flux"].artifacts[0]["media"] == "image")
        self.assertIn("توکن", rows["ollama_text"].detail)
        self.assertEqual(rows["update_flow"].state, "PASSED")
        ids = [r.job_uid for r in run.results.all() if r.job_uid]
        self.assertTrue(all(ComputeJob.objects.get(uid=u).origin == "selftest" for u in ids))
        self.assertTrue(all(ComputeJob.objects.get(uid=u).node_wanted == "gpu-p" for u in ids))

    def test_one_run_at_a_time_per_node(self):
        a = runner.start_run(self.node, "manual")
        b = runner.start_run(self.node, "nightly")
        self.assertEqual(a.pk, b.pk)

    def test_a_gpu_test_that_ran_on_the_cpu_fails_with_the_reason(self):
        def handler(job):
            out, meta = self.good(job)
            if job.kind == "ollama.generate" and not (job.payload or {}).get("images"):
                meta = {"device": "cpu", "device_note": "none of the model fits in VRAM"}
            return out, meta
        run = self.drive(runner.start_run(self.node, "manual"), handler)
        r = run.results.get(key="ollama_text")
        self.assertEqual(r.state, "FAILED")
        self.assertIn("روی پردازنده", r.detail)
        self.assertIn("fits in VRAM", r.detail)
        self.assertEqual(r.device, "cpu")
        self.assertFalse(runner.run_json(run)["summary"]["ok"])

    def test_mixed_device_passes_with_a_warning(self):
        def handler(job):
            out, meta = self.good(job)
            if job.kind == "ollama.generate" and not (job.payload or {}).get("images"):
                meta = {"device": "mixed", "device_note": "qwq:32b: 40% in VRAM", "device_warning": "بخشی از کار روی پردازنده بود"}
            return out, meta
        run = self.drive(runner.start_run(self.node, "manual"), handler)
        r = run.results.get(key="ollama_text")
        self.assertEqual(r.state, "PASSED")
        self.assertIn("پردازنده", r.warning)

    def test_what_the_node_cannot_do_is_skipped_not_failed(self):
        self.node.capabilities.update(comfyui=False, startable={}, photo_matting=False, audio={"moss": False, "sfx": False, "music": False},
                                      ollama_models=[], edit={"render": False, "why": "ffmpeg not found"})
        self.node.save()
        run = self.drive(runner.start_run(self.node, "manual"), self.good)
        rows = {r.key: r for r in run.results.all()}
        for key in ("comfy_flux", "matting", "tts_moss", "ollama_text", "ollama_vision", "edit_render"):
            self.assertEqual(rows[key].state, "SKIPPED", key)
        self.assertIn("ComfyUI", rows["comfy_flux"].detail)
        self.assertEqual(rows["gpu"].state, "PASSED")

    def test_a_failed_prerequisite_skips_what_depends_on_it(self):
        def handler(job):
            if job.kind == "voice.tts" and job.payload.get("engine") == "piper":
                return {"speech.wav": b"not a wav"}, {}
            return self.good(job)
        run = self.drive(runner.start_run(self.node, "manual"), handler)
        rows = {r.key: r for r in run.results.all()}
        self.assertEqual(rows["tts_piper"].state, "FAILED")
        self.assertEqual(rows["asr_vosk"].state, "SKIPPED")
        self.assertIn("پیش‌نیاز", rows["asr_vosk"].detail)
        self.assertEqual(rows["asr_gpu"].state, "SKIPPED")

    def test_a_failed_job_shows_its_error(self):
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        r = run.results.get(key="gpu")
        job = ComputeJob.objects.get(uid=r.job_uid)
        job.state, job.error = "FAILED", "RuntimeError: nvidia-smi crashed"
        job.save()
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "FAILED")
        self.assertIn("nvidia-smi crashed", r.detail)

    def test_bad_gpu_report_names_the_problem(self):
        def handler(job):
            if job.kind == "selftest.gpu":
                return {"gpu.json": json.dumps({"visible": True, "name": "RTX 3060", "driver": "470.1", "driver_ok": False,
                                                "envs": {"moss-tts": {"torch": {"torch": "2.9.1+cpu", "cuda": False}}},
                                                "ffmpeg": {"nvenc_h264": False, "path": "C:/ffmpeg.exe"}}).encode()}, {}
            return self.good(job)
        run = self.drive(runner.start_run(self.node, "manual"), handler)
        r = run.results.get(key="gpu")
        self.assertEqual(r.state, "FAILED")
        self.assertIn("torch", r.detail)
        self.assertIn("درایور", r.detail)
        self.assertIn("NVENC", r.detail)

    def test_missing_nvenc_is_a_visible_failure(self):
        def handler(job):
            if job.kind == "selftest.ffmpeg":
                return {"ffmpeg.json": json.dumps({"nvenc_h264": False, "nvenc_error": "no capable devices"}).encode(), "nvenc.mp4": b"x" * 9000}, {"device": "cpu"}
            return self.good(job)
        run = self.drive(runner.start_run(self.node, "manual"), handler)
        r = run.results.get(key="ffmpeg_nvenc")
        self.assertEqual(r.state, "FAILED")
        self.assertIn("no capable devices", r.detail)

    def test_install_in_progress_waits_then_failed_install_is_reported_with_the_tail(self):
        self.node.capabilities["bootstrap"] = {
            "summary": {"installing": 1}, "blocked_kinds": {"asr.transcribe": "asr-gpu: installing"},
            "features": {"asr-gpu": {"title": "تشخیص گفتار روی کارت", "state": "installing", "items": [{"id": "pip", "state": "installing"}]}}}
        self.node.save()
        run = runner.start_run(self.node, "manual")
        for _ in range(3):
            runner.advance(run)
        asr = run.results.get(key="asr_gpu")
        self.assertIn(asr.state, ("PENDING", "QUEUED", "WAITING"))
        boot = run.results.get(key="bootstrap")
        self.assertEqual(boot.state, "WAITING")
        self.assertIn("در حالِ نصب", boot.detail)
        self.node.capabilities["bootstrap"]["features"]["asr-gpu"] = {
            "title": "تشخیص گفتار روی کارت", "state": "failed",
            "items": [{"id": "pip", "state": "failed", "error": "pip install failed on every source", "tail": ["x"]}]}
        self.node.save()
        run = self.drive(run, self.good, rounds=6)
        boot = run.results.get(key="bootstrap")
        self.assertEqual(boot.state, "FAILED")
        self.assertIn("pip install failed", boot.detail)
        asr = run.results.get(key="asr_gpu")
        self.assertEqual(asr.state, "FAILED")
        self.assertIn("نصبِ", asr.detail)
        job = ComputeJob.objects.get(uid=asr.job_uid)
        self.assertEqual(job.state, "CANCELLED")

    def test_an_old_agent_gets_a_clear_message_for_new_kinds(self):
        self.node.capabilities.pop("kinds")
        self.node.capabilities["agent"] = "2.10"
        self.node.save()
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        gpu_row = run.results.get(key="gpu")
        ComputeJob.objects.filter(uid=gpu_row.job_uid).update(queued_at=timezone.now() - timedelta(minutes=10))
        SelfTestResult.objects.filter(pk=gpu_row.pk).update(started_at=timezone.now() - timedelta(minutes=10))
        runner.advance(run)
        gpu_row.refresh_from_db()
        self.assertEqual(gpu_row.state, "FAILED")
        self.assertIn("به‌روزرسانی", gpu_row.detail)

    def test_bootstrap_never_passes_before_the_new_agent_has_reported_its_installs(self):
        """The agent starts its installer about 70 s after it starts: until then «automatic install: pass» would be a lie."""
        self.node.capabilities.pop("bootstrap")
        self.node.save()
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        b = run.results.get(key="bootstrap")
        self.assertEqual(b.state, "WAITING")
        self.assertNotIn("چیزی برای نصبِ خودکار ندارد", b.detail)
        old = dict(b.extra)
        old["absent_since"] = (timezone.now() - timedelta(minutes=7)).isoformat()      # it never reported in all that time
        SelfTestResult.objects.filter(pk=b.pk).update(extra=old)
        runner.advance(run)
        b.refresh_from_db()
        self.assertEqual(b.state, "FAILED")
        self.assertIn("راه نینداخت", b.detail)

    def test_an_empty_install_list_is_a_failure_not_a_pass(self):
        self.node.capabilities["bootstrap"] = {"summary": {}, "blocked_kinds": {}, "features": {}, "errors": ["x.json: broken"]}
        self.node.save()
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        b = run.results.get(key="bootstrap")
        self.assertEqual(b.state, "FAILED")
        self.assertIn("requirements.d", b.detail)

    def test_a_freshly_started_agent_with_everything_ready_still_gets_a_moment(self):
        self.node.capabilities["started_at"] = int(time.time()) - 20
        self.node.save()
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        self.assertEqual(run.results.get(key="bootstrap").state, "WAITING")
        gpu_row = run.results.get(key="gpu")
        self.assertEqual(gpu_row.state, "WAITING")
        self.assertIsNone(gpu_row.job_uid)                       # no job was sent into an environment that is not there yet
        self.node.capabilities["started_at"] = int(time.time()) - 600
        self.node.save()
        runner.advance(run)
        self.assertEqual(run.results.get(key="bootstrap").state, "PASSED")
        gpu_row.refresh_from_db()
        self.assertEqual(gpu_row.state, "QUEUED")
        self.assertTrue(gpu_row.job_uid)

    def test_tests_that_rely_on_an_install_wait_for_it_instead_of_running_or_skipping(self):
        feats = self.node.capabilities["bootstrap"]["features"]
        feats["gpu-runtime"]["state"] = "installing"
        feats["ffmpeg-nvenc"] = {"title": "ffmpeg با NVENC", "state": "installing", "items": []}
        feats["asr-gpu"] = {"title": "تشخیص گفتار روی کارت", "state": "waiting", "items": []}
        self.node.save()
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        runner.advance(run)
        for key in ("gpu", "ffmpeg_nvenc", "matting", "edit_render"):
            r = run.results.get(key=key)
            self.assertEqual(r.state, "WAITING", key)
            self.assertIsNone(r.job_uid, key)
            self.assertIn("منتظرِ پایانِ نصب", r.detail, key)
        for name in feats:
            feats[name]["state"] = "ready"
        self.node.save()
        runner.advance(run)
        for key in ("gpu", "ffmpeg_nvenc", "matting", "edit_render"):
            r = run.results.get(key=key)
            self.assertIn(r.state, ("QUEUED", "RUNNING", "PASSED"), key)
            self.assertTrue(r.job_uid, key)

    def test_tests_an_agent_predates_wait_while_the_update_is_coming_and_fail_clearly_when_it_is_not(self):
        self.node.capabilities.update(agent="2.10", code={"version": "2.10", "id": "aaaaaaaaaaaaaaaa"})
        self.node.capabilities.pop("kinds")
        self.node.save()
        self.assertTrue(autopilot.update_wanted(self.node)[0])
        run = runner.start_run(self.node, "manual")
        runner.advance(run)
        for key in ("bootstrap", "net", "gpu", "ffmpeg_nvenc"):
            r = run.results.get(key=key)
            self.assertEqual(r.state, "WAITING", key)
            self.assertIn("منتظرِ به‌روزرسانیِ خودکار", r.detail, key)
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_update": False})      # nobody will update it now
        runner.advance(run)
        for key in ("bootstrap", "net", "gpu"):
            r = run.results.get(key=key)
            self.assertEqual(r.state, "FAILED", key)
            self.assertIn("«به‌روزرسانی» را بزنید", r.detail, key)

    def test_a_job_the_agent_does_not_know_waits_while_an_update_is_coming(self):
        kinds = [k for k in self.node.capabilities["kinds"] if k != "selftest.ffmpeg"]
        self.node.capabilities.update(kinds=kinds, code={"version": "2.11", "id": "aaaaaaaaaaaaaaaa"})        # a different build: update is due
        self.node.save()
        run = runner.start_run(self.node, "manual")
        for _ in range(2):
            runner.advance(run)
        r = run.results.get(key="ffmpeg_nvenc")
        self.assertTrue(r.job_uid)
        ComputeJob.objects.filter(uid=r.job_uid).update(queued_at=timezone.now() - timedelta(minutes=10))
        SelfTestResult.objects.filter(pk=r.pk).update(started_at=timezone.now() - timedelta(minutes=10))
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "WAITING")
        self.assertIn("منتظرِ به‌روزرسانیِ خودکار", r.detail)
        self.assertFalse(ComputeJob.objects.get(uid=r.job_uid).final)
        ComputeSettings.objects.update_or_create(pk=1, defaults={"auto_update": False})
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "FAILED")
        self.assertIn("«به‌روزرسانی» را بزنید", r.detail)

    def test_the_run_is_aborted_when_the_node_stays_off(self):
        run = runner.start_run(self.node, "manual")
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(hours=2))
        runner.advance(run)
        run.refresh_from_db()
        self.assertEqual(run.state, "ABORTED")
        self.assertTrue(all(r.final for r in run.results.all()))

    def test_rerun_one_test_resets_it_and_the_ones_that_were_skipped_because_of_it(self):
        def broken(job):
            if job.kind == "voice.tts" and job.payload.get("engine") == "piper":
                return {"speech.wav": b"bad"}, {}
            return self.good(job)
        run = self.drive(runner.start_run(self.node, "manual"), broken)
        self.assertEqual(run.results.get(key="tts_piper").state, "FAILED")
        runner.rerun(run, "tts_piper")
        run = self.drive(run, self.good)
        rows = {r.key: r for r in run.results.all()}
        self.assertEqual(rows["tts_piper"].state, "PASSED")
        self.assertEqual(rows["asr_vosk"].state, "PASSED")
        self.assertEqual(run.state, "FINISHED", {r.key: (r.state, (r.detail or "")[:80]) for r in run.results.all() if not r.final})

    def test_deep_run_includes_the_long_tests(self):
        run = runner.start_run(self.node, "deep", deep=True)
        keys = {r.key for r in run.results.all()}
        self.assertTrue({"comfy_wan", "music"} <= keys)
        self.assertTrue(all(REGISTRY[k].optional for k in ("comfy_wan", "music")))

    def test_the_update_flow_after_an_update_records_before_and_after(self):
        n = self.node
        n.capabilities.update(agent="2.11", code={"version": "2.11", "id": "bbbbbbbbbbbbbbbbbbbb"})
        n.save()
        C.request(n, "update", "x")
        C._write(n, {"pending": None, "last": {**C.state(n)["last"], "state": "done", "ok": True, "finished_at": timezone.now().isoformat()}})
        run = SelfTestRun.objects.create(node=n, trigger="version")
        r = SelfTestResult.objects.create(run=run, key="update_flow", label="x", state="PENDING")
        v = REGISTRY["update_flow"].virtual(runner.Ctx(n, run, {}, result=r))
        self.assertTrue(v.ok, v.detail)
        self.assertIn("به‌روزرسانی", v.detail)

    def test_the_update_flow_by_a_manual_run_sends_the_command_and_waits_for_the_agent_to_return(self):
        n = self.node
        run = SelfTestRun.objects.create(node=n, trigger="manual")
        r = SelfTestResult.objects.create(run=run, key="update_flow", label="x", state="PENDING")
        t = REGISTRY["update_flow"]
        v = t.virtual(runner.Ctx(n, run, {}, result=r))
        self.assertTrue(v.wait)
        extra = v.extra
        self.assertEqual(extra["action"], "restart")                      # nothing to update: a restart proves the way back
        self.assertEqual(C.state(n)["last"]["action"], "restart")
        r.extra = extra
        r.save()
        v = t.virtual(runner.Ctx(n, run, {}, result=r))
        self.assertTrue(v.wait)                                            # command not answered yet
        cid = extra["cmd_id"]
        self.assertTrue(C.report(n, cid, "running"))
        self.assertTrue(C.report(n, cid, "done", True, "ok"))
        n.capabilities["started_at"] = int(timezone.now().timestamp()) + 5     # the agent restarted
        n.save()
        v = t.virtual(runner.Ctx(n, run, {}, result=r))
        self.assertTrue(v.ok, v.detail)
        self.assertEqual(v.extra["after"]["agent"], "2.11")

    def test_the_update_flow_fails_when_the_agent_never_comes_back(self):
        n = self.node
        run = SelfTestRun.objects.create(node=n, trigger="manual")
        r = SelfTestResult.objects.create(run=run, key="update_flow", label="x", state="PENDING")
        v = REGISTRY["update_flow"].virtual(runner.Ctx(n, run, {}, result=r))
        r.extra = dict(v.extra, sent_at=(timezone.now() - timedelta(minutes=20)).isoformat())
        r.save()
        v = REGISTRY["update_flow"].virtual(runner.Ctx(n, run, {}, result=r))
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        self.assertIn("برنگشت", v.detail)


class RequeueTests(_Base):
    def failed_job(self, kind, payload, error, state="FAILED", **kw):
        j = self.job(kind, payload=payload, **kw)
        ComputeJob.objects.filter(pk=j.pk).update(state=state, error=error, finished_at=timezone.now() - timedelta(hours=3), origin=kw.get("origin", "audio_studio"))
        j.refresh_from_db()
        return j

    def test_node_reasons_versus_real_errors(self):
        a = self.failed_job("voice.tts", {"engine": "moss-fa"}, "JobError: MOSS-TTS is not installed on this node")
        b = self.failed_job("voice.tts", {"engine": "moss-fa"}, "RuntimeError: text is empty")
        c = self.failed_job("comfy.graph", {"g": 1}, "", state="CANCELLED")
        d = self.failed_job("comfy.graph", {"g": 2}, "کاربر از پنل لغو کرد (admin).", state="CANCELLED")
        e = self.failed_job("ollama.generate", {"p": 1}, "RuntimeError: ollama service is not reachable at http://127.0.0.1:11434: timed out")
        self.assertTrue(requeue_mod.node_reason(a))
        self.assertFalse(requeue_mod.node_reason(b))
        self.assertTrue(requeue_mod.node_reason(c))
        self.assertFalse(requeue_mod.node_reason(d))
        self.assertTrue(requeue_mod.node_reason(e))

    def test_a_graph_comfyui_rejected_as_invalid_is_a_real_error_but_a_missing_model_file_is_a_node_reason(self):
        invalid = self.failed_job("comfy.graph", {"g": 1}, 'RuntimeError: ComfyUI rejected the graph (HTTP 400): {"error": {"type": "prompt_no_outputs", '
                                  '"message": "Prompt has no outputs"}, "node_errors": {}}')
        broken = self.failed_job("comfy.graph", {"g": 2}, "RuntimeError: ComfyUI rejected the graph (HTTP 400): {\"error\": {\"type\": "
                                 "\"prompt_outputs_failed_validation\", \"details\": \"Exception when validating node: '8'\"}}")
        no_model = self.failed_job("comfy.graph", {"g": 3}, "RuntimeError: ComfyUI rejected the graph (HTTP 400): Value not in list: "
                                   "ckpt_name: 'flux1-dev.safetensors' not in []")
        real_shape = self.failed_job("comfy.graph", {"g": 6}, 'RuntimeError: ComfyUI rejected the graph (HTTP 400): {"error": {"type": "prompt_outputs_failed_validation", '
                                     '"message": "Prompt outputs failed validation", "details": "", "extra_info": {}}, "node_errors": {"4": {"errors": [{"type": '
                                     '"value_not_in_list", "message": "Value not in list", "details": "ckpt_name: \'x.safetensors\' not in []"}]}}}')
        down = self.failed_job("comfy.graph", {"g": 4}, "RuntimeError: ComfyUI is not reachable at http://127.0.0.1:8188: refused")
        slow = self.failed_job("comfy.graph", {"g": 5}, "RuntimeError: ComfyUI is running but did not answer within 120 s (a read timeout)")
        self.assertFalse(requeue_mod.node_reason(invalid))
        self.assertFalse(requeue_mod.node_reason(broken))
        self.assertTrue(requeue_mod.node_reason(no_model))
        self.assertTrue(requeue_mod.node_reason(down))
        self.assertTrue(requeue_mod.node_reason(slow))
        got = {j.pk for j in requeue_mod.candidates(("comfy.graph",))}
        self.assertTrue(requeue_mod.node_reason(real_shape))               # the real body of «the checkpoint is not on this node»
        self.assertEqual(got, {no_model.pk, real_shape.pk, down.pk, slow.pk})

    def test_a_passed_moss_test_brings_the_failed_voice_overs_back_once_or_twice_only(self):
        voices = [self.failed_job("voice.tts", {"engine": "moss-fa", "text": "t%d" % i, "out": "speech.wav"}, "JobError: MOSS-TTS is not installed")
                  for i in range(7)]
        piper = self.failed_job("voice.tts", {"engine": "piper", "text": "p"}, "JobError: voice service is not running")
        real = self.failed_job("voice.tts", {"engine": "moss-fa", "text": "x"}, "RuntimeError: text is empty")
        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        test = REGISTRY["tts_moss"] if "tts_moss" in REGISTRY else (load_all() and REGISTRY["tts_moss"])
        out = requeue_mod.requeue_after_pass(run, test)
        self.assertEqual(out["retried"], 7)
        for v in voices:
            v.refresh_from_db()
            self.assertEqual(v.state, "QUEUED")
        piper.refresh_from_db()
        real.refresh_from_db()
        self.assertEqual(piper.state, "FAILED")                  # not MOSS
        self.assertEqual(real.state, "FAILED")                   # a real error
        self.assertEqual(RequeueRecord.objects.count(), 7)
        for v in voices:                                          # fail them again, requeue again, then enough
            ComputeJob.objects.filter(pk=v.pk).update(state="FAILED", error="not installed", finished_at=timezone.now())
        self.assertEqual(requeue_mod.requeue_after_pass(run, test)["retried"], 7)
        for v in voices:
            ComputeJob.objects.filter(pk=v.pk).update(state="FAILED", error="not installed", finished_at=timezone.now())
        self.assertEqual(requeue_mod.requeue_after_pass(run, test)["retried"], 0)

    def test_finishing_a_run_requeues_after_each_passed_test_when_the_setting_is_on(self):
        load_all()
        j = self.failed_job("comfy.profile", {"profile": "flux-product-fast", "prompt": "a"}, "ComfyUI is not running on this node")
        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        SelfTestResult.objects.create(run=run, key="comfy_flux", label="x", state="PASSED")
        ComputeSettings.objects.update_or_create(pk=1, defaults={"requeue_after_pass": False})
        runner.finish_run(run)
        j.refresh_from_db()
        self.assertEqual(j.state, "FAILED")
        ComputeSettings.objects.update_or_create(pk=1, defaults={"requeue_after_pass": True})
        run2 = SelfTestRun.objects.create(node=self.node, trigger="manual")
        SelfTestResult.objects.create(run=run2, key="comfy_flux", label="x", state="PASSED")
        runner.finish_run(run2)
        j.refresh_from_db()
        self.assertEqual(j.state, "QUEUED")
        self.assertEqual(run2.requeued["comfy_flux"]["retried"], 1)

    def test_selftest_jobs_themselves_are_never_requeued(self):
        j = self.failed_job("echo", {"a": 1}, "site unreachable", origin="selftest")
        self.assertEqual(requeue_mod.candidates(("echo",)), [])
        del j


class DocsLoaderTests(_Base):
    def test_blocks_in_docs_become_selftests(self):
        d = Path(tempfile.mkdtemp(prefix="nm-selftest-docs-"))
        try:
            (d / "motion.md").write_text("""# motion
متن
```json
{"key": "Motion-Render", "label": "رندرِ موشن", "kind": "motion.render", "payload": {"scene": "intro"}, "timeout_s": 600,
 "requires": {"kinds": ["motion.render"]}, "requeue_kinds": ["motion.render"],
 "check": {"outputs_min": 1, "output_ext": [".mp4"], "min_bytes": 100, "json_file": "result.json", "json_has": ["frames"], "forbid_device": ["cpu"]}}
```
```json
{"oops": 1}
```
""", encoding="utf-8")
            (d / "README.md").write_text("```json\n{\"key\":\"readme\",\"kind\":\"x\",\"payload\":{}}\n```", encoding="utf-8")
            with override_settings(NM_SELFTEST_DOCS=str(d)):
                done = docs_loader.register_all()
            self.assertEqual(done, ["motion_render"])
            self.assertNotIn("readme", REGISTRY)
            t = REGISTRY.pop("motion_render")
            self.assertEqual(t.kind, "motion.render")
            self.assertEqual(t.requeue, {"kinds": ("motion.render",)})
            ok, why = t.available(self.node)
            self.assertFalse(ok)
            self.assertIn("motion.render", why)
            self.node.capabilities["kinds"].append("motion.render")
            self.assertTrue(t.available(self.node)[0])
            job = self.job("motion.render")
            SV.output_path(job, "out.mp4").write_bytes(b"x" * 500)
            SV.output_path(job, "result.json").write_bytes(b'{"frames": 60}')
            self.finish_ok(job, meta={"device": "cuda"})
            job.refresh_from_db()
            ctx = runner.Ctx(self.node, None, {})
            self.assertTrue(t.check(ctx, job).ok)
            SV.output_path(job, "result.json").write_bytes(b'{"nothing": 1}')
            self.assertFalse(t.check(ctx, job).ok)
        finally:
            shutil.rmtree(d, ignore_errors=True)
            REGISTRY.pop("motion_render", None)


class ApiTests(_Base):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff = User.objects.create_user("staff-p", password="x", is_staff=True)
        self.plain = User.objects.create_user("plain-p", password="x")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)

    def test_only_staff(self):
        p = APIClient()
        p.force_authenticate(self.plain)
        for method, url in (("get", "/api/v1/compute/selftests/"), ("post", "/api/v1/compute/selftests/run/"), ("get", "/api/v1/compute/progress/"),
                            ("post", "/api/v1/compute/nodes/%d/bootstrap/" % self.node.pk)):
            self.assertEqual(getattr(p, method)(url).status_code, 403, url)

    def test_overview_catalog_settings_progress_and_node_blocks(self):
        r = self.c.get("/api/v1/compute/selftests/").json()
        keys = [t["key"] for t in r["catalog"]]
        self.assertIn("gpu", keys)
        self.assertIn("comfy_wan", keys)
        self.assertEqual(r["settings"]["auto_update"], True)
        node = r["nodes"][0]
        self.assertEqual(node["name"], "gpu-p")
        self.assertIsNone(node["run"])
        self.assertIn("auto", node)
        self.assertIn("percent", r["progress"])

    def test_start_run_rerun_and_detail(self):
        r = self.c.post("/api/v1/compute/selftests/run/", {"node": self.node.pk}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        body = r.json()
        self.assertFalse(body["already_running"])
        self.assertEqual(body["trigger"], "manual")
        again = self.c.post("/api/v1/compute/selftests/run/", {"node": self.node.pk}, format="json").json()
        self.assertTrue(again["already_running"])
        self.assertEqual(again["id"], body["id"])
        d = self.c.get("/api/v1/compute/selftests/%d/" % body["id"]).json()
        self.assertTrue(d["results"])
        self.assertTrue(any(x["key"] == "echo" for x in d["results"]))
        rr = self.c.post("/api/v1/compute/selftests/%d/rerun/" % body["id"], {"key": "echo"}, format="json")
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(self.c.post("/api/v1/compute/selftests/%d/rerun/" % body["id"], {"key": "nope"}, format="json").status_code, 404)
        h = self.c.get("/api/v1/compute/selftests/history/?node=%d" % self.node.pk).json()
        self.assertEqual(len(h["runs"]), 1)

    def test_start_needs_an_online_node(self):
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.c.post("/api/v1/compute/selftests/run/", {"node": self.node.pk}, format="json").status_code, 409)

    def test_settings_roundtrip(self):
        r = self.c.post("/api/v1/compute/settings/", {"auto_update": False, "nightly_time": "04:15", "short_burst": 5, "requeue_after_pass": False},
                        format="json").json()
        self.assertEqual((r["auto_update"], r["nightly_time"], r["short_burst"], r["requeue_after_pass"]), (False, "04:15", 5, False))
        self.assertEqual(self.c.post("/api/v1/compute/settings/", {"nightly_time": "25:99"}, format="json").status_code, 400)
        self.assertEqual(self.c.post("/api/v1/compute/settings/", {"short_burst": 0}, format="json").status_code, 400)
        again = self.c.get("/api/v1/compute/settings/").json()
        self.assertEqual(again["auto_update"], False)

    def test_bootstrap_retry_is_a_node_command_and_needs_a_new_agent(self):
        r = self.c.post("/api/v1/compute/nodes/%d/bootstrap/" % self.node.pk)
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(C.state(self.node)["last"]["action"], "bootstrap")
        old = mk_node("old-b", agent="2.10")
        old.capabilities["commands"] = ["status", "update", "restart", "build", "logs"]
        old.save()
        self.assertEqual(self.c.post("/api/v1/compute/nodes/%d/bootstrap/" % old.pk).status_code, 409)

    def test_autostart_switch_reaches_the_node_with_the_next_heartbeat(self):
        self.assertEqual(self.c.post("/api/v1/compute/nodes/%d/autostart/" % self.node.pk, {"enabled": False}, format="json").json(),
                         {"autostart_wanted": False})
        nc = APIClient()
        nc.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        hb = nc.post("/api/v1/compute/heartbeat/", {}, format="json").json()
        self.assertEqual(hb["desired"]["autostart"], False)
        self.assertTrue(hb["lanes"])
        node = [n for n in self.c.get("/api/v1/compute/nodes/").json() if n["name"] == "gpu-p"][0]
        self.assertIn("gpu_info", node)

    def test_claim_with_a_lane_and_the_device_in_the_queue_rows(self):
        nc = APIClient()
        nc.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        echo = self.job("echo")
        self.job("comfy.profile", payload={"profile": "wan22-480p-short"})
        got = nc.post("/api/v1/compute/claim/", {"lane": "light"}, format="json").json()
        self.assertEqual(got["job"]["uid"], str(echo.uid))
        self.assertTrue(got["lanes"])
        SV.finish(ComputeJob.objects.get(pk=echo.pk), self.node, True, meta={"device": "cpu", "device_note": "x", "device_warning": "w",
                                                                              "gpu": {"util_max": 3, "series": [[0, 1, 2]]}})
        row = self.c.get("/api/v1/compute/queue/?state=done").json()["jobs"][0]
        self.assertEqual(row["device"], "cpu")
        self.assertEqual(row["device_warning"], "w")
        self.assertEqual(row["gpu"]["util_max"], 3)

    def test_heartbeat_with_a_new_version_starts_a_run_by_itself(self):
        nc = APIClient()
        nc.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        caps = dict(self.node.capabilities, agent="2.12")
        r = nc.post("/api/v1/compute/heartbeat/", caps, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SelfTestRun.objects.filter(node=self.node, trigger="version").count(), 1)
        nc.post("/api/v1/compute/heartbeat/", caps, format="json")
        self.assertEqual(SelfTestRun.objects.filter(node=self.node).count(), 1)

    def test_progress_endpoint(self):
        self.job("ollama.generate")
        r = self.c.get("/api/v1/compute/progress/").json()
        self.assertEqual(r["kinds"]["ollama.generate"]["queued"], 1)
        self.assertTrue(r["kinds"]["ollama.generate"]["label"])

    def test_the_job_package_can_be_resumed_with_a_range_request(self):
        nc = APIClient()
        nc.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        job = self.job("echo")
        got = nc.post("/api/v1/compute/claim/", {}, format="json").json()["job"]
        url = "/api/v1/compute/jobs/%s/package/" % got["uid"]
        full = b"".join(nc.get(url).streaming_content)
        self.assertGreater(len(full), 100)
        part = nc.get(url, HTTP_RANGE="bytes=40-")
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part["Content-Range"], "bytes 40-%d/%d" % (len(full) - 1, len(full)))
        self.assertEqual(b"".join(part.streaming_content), full[40:])
        self.assertEqual(nc.get(url, HTTP_RANGE="bytes=%d-" % len(full)).status_code, 416)
        self.assertEqual(nc.get(url, HTTP_RANGE="bytes=0-").status_code, 200)                 # from the start = the whole file
        self.assertEqual(nc.get(url, HTTP_RANGE="bytes=1-5").status_code, 200)                # only open-ended ranges are served
        self.assertEqual(job.pk, ComputeJob.objects.get(uid=got["uid"]).pk)


class ReportDevicesTests(_Base):
    """گزارش: هر کارِ تمام‌شده روی کارت بود یا پردازنده؛ افتادن روی پردازنده با علت."""

    def done(self, kind, meta, n=0):
        j = self.job(kind=kind, payload={"n": n, "k": kind})
        self.finish_ok(j, {"o.json": b"{}"}, meta=meta)
        return j

    def test_the_devices_are_counted_per_kind_and_a_cpu_fallback_is_listed_with_its_reason(self):
        from . import views_report

        self.done("ollama.generate", {"device": "cuda"}, 1)
        self.done("ollama.generate", {"device": "cuda"}, 2)
        self.done("ollama.generate", {"device": "mixed", "device_warning": "بخشی از مدل روی پردازنده رفت"}, 3)
        self.done("edit.render", {"device": "nvenc"}, 4)
        self.done("echo", {}, 5)                                     # بدونِ گزارشِ دستگاه (عاملِ قدیمی)
        out = views_report._devices_section(views_report.parse_range({}, timezone.now()))
        self.assertEqual(out["counted"], 4)
        self.assertEqual(out["without_device"], 1)
        self.assertEqual(out["by_device"], {"cuda": 2, "mixed": 1, "nvenc": 1})
        kinds = {k["kind"]: k for k in out["by_kind"]}
        self.assertEqual(kinds["ollama.generate"]["devices"], {"cuda": 2, "mixed": 1})
        self.assertEqual(len(out["fallbacks"]), 1)
        self.assertIn("بخشی از مدل", out["fallbacks"][0]["warning"])
        self.assertFalse(out["truncated"])

    def test_the_report_api_carries_the_devices_section(self):
        User = get_user_model()
        staff = User.objects.create_user("staff-r", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        self.done("ollama.generate", {"device": "cuda"})
        body = c.get("/api/v1/compute/report/").json()
        self.assertEqual(body["devices"]["by_device"], {"cuda": 1})

    def test_the_queue_row_and_detail_show_the_device_the_job_used(self):
        from . import queue as QV

        j = self.done("ollama.generate", {"device": "cpu", "device_note": "همه‌ی لایه‌ها روی CPU", "device_warning": "باید روی کارت می‌بود",
                                          "gpu": {"util_max": 4, "samples": 3}})
        j.refresh_from_db()
        d = QV.device_of(j)
        self.assertEqual(d["device"], "cpu")
        self.assertEqual(d["device_warning"], "باید روی کارت می‌بود")
        self.assertEqual(d["gpu"]["util_max"], 4)


class SiteContentSelfTests(_Base):
    """پیوندِ docs/selftests ِ ویژگی‌های دیگر: محتوای چغر (شناسهٔ ۳۴) و تامنیل‌ساز."""

    def setUp(self):
        super().setUp()
        from apps.stores.models import Store

        self.user = get_user_model().objects.create_user("owner-c", password="x")
        self.store = Store.objects.create(id=34, owner=self.user, name="chagher-test")
        load_all()

    def verdict(self, started_ago_s=0):
        from .selftests import Ctx
        from .selftests.chagher_content import virtual

        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        res = SelfTestResult.objects.create(run=run, key="chagher_content", label="x", started_at=timezone.now() - timedelta(seconds=started_ago_s))
        return virtual(Ctx(self.node, run, {}, result=res))

    def park(self):
        from .park import PARK_KIND

        return ComputeJob.objects.create(kind=PARK_KIND, payload={"task": "x"}, origin="park", store=self.store, state=ComputeJob.State.QUEUED)

    def test_registered_and_optional(self):
        self.assertIn("chagher_content", REGISTRY)
        self.assertTrue(REGISTRY["chagher_content"].optional)
        from django.apps import apps as django_apps
        # «تامنیل‌ساز» وصلهٔ جداست: بدونِ اپِ apps.thumbs چیزی ثبت نمی‌شود، با آن «thumbs_bg» ثبت می‌شود
        self.assertEqual("thumbs_bg" in REGISTRY, django_apps.is_installed("apps.thumbs"))

    def test_multiangle_is_skipped_on_a_node_that_does_not_know_it_and_judged_on_its_checks_otherwise(self):
        self.assertIn("multiangle", REGISTRY)
        t = REGISTRY["multiangle"]
        self.assertFalse(t.available(self.node)[0])
        self.node.capabilities["kinds"] = self.node.capabilities["kinds"] + ["multiangle.selftest"]
        self.assertTrue(t.available(self.node)[0])
        job = self.job("multiangle.selftest", payload={"selftest": True})
        ok = {"ok": True, "checks": [{"name": "runtime", "ok": True}, {"name": "models", "ok": True}]}
        self.finish_ok(job, {"selftest.json": json.dumps(ok).encode()})
        job.refresh_from_db()
        from .selftests import Ctx
        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        v = t.check(Ctx(self.node, run, {}), job)
        self.assertTrue(v.ok, v.detail)
        bad = {"ok": False, "checks": [{"name": "models", "ok": False, "detail": "missing u2net"}]}
        SV.output_path(job, "selftest.json").write_bytes(json.dumps(bad).encode())
        v = t.check(Ctx(self.node, run, {}), job)
        self.assertFalse(v.ok)
        self.assertIn("models", v.detail)

    def test_nothing_parked_passes(self):
        self.assertTrue(self.verdict().ok)

    def test_parked_jobs_are_waited_for_then_reported(self):
        self.park()
        v = self.verdict(started_ago_s=60)
        self.assertTrue(v.wait and not v.ok)
        v = self.verdict(started_ago_s=21 * 60)
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        self.assertIn("منتظرِ گره", v.detail)

    def test_the_moss_dtype_error_must_not_come_back(self):
        ComputeJob.objects.create(kind="voice.tts", payload={}, origin="x", store=self.store, state=ComputeJob.State.FAILED,
                                  error="RuntimeError: expected mat1 and mat2 to have the same dtype", finished_at=timezone.now())
        v = self.verdict()
        self.assertFalse(v.ok)
        self.assertIn("dtype", v.detail)

