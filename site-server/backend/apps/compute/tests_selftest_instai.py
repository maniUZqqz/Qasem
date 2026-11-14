# -*- coding: utf-8 -*-
"""The «InstAI on this PC» entry in the node acceptance run (`selftests/instai.py`): registered, optional, skipped (never failed) when the folder is not
there, waiting while InstAI updates / starts / has not run its own self-test yet, failed with the reason when the update broke or InstAI's own self-test has
failures, passed with a warning when something of InstAI still waits. The agent's report (caps["instai"], made by processing/instai_jobs.py) is all it reads."""
from django.test import TestCase
from django.utils import timezone

from .models import ComputeNode, SelfTestResult, SelfTestRun
from .selftests import REGISTRY, load_all, runner
from .selftests import instai as T

S = SelfTestResult.State


def rep(**kw):
    base = {"found": True, "dir": r"C:\Users\QQz\Desktop\Instai-main\V2\Instai-main", "version": "0.14.0", "github": "0.14.0", "has_updater": True, "running": True,
            "state": "ok", "message_fa": "InstAI به‌روز است و کار می‌کند", "selftest": {"state": "sound", "ok": 11, "warn": 0, "fail": 0, "pending": 0, "failing": [], "waiting": [], "warning": []}}
    base.update(kw)
    return base


def node_with(report, agent=None, name="gpu-instai"):
    caps = {"agent": agent or (T.MIN_AGENT if T.MIN_AGENT[:1].isdigit() else "9.9"), "kinds": ["echo"]}
    if report is not None:
        caps["instai"] = report
    return ComputeNode.objects.create(name=name, capabilities=caps, last_seen=timezone.now())


class Registration(TestCase):
    def setUp(self):
        load_all()

    def test_it_is_registered_optional_and_virtual(self):
        t = REGISTRY["instai"]
        self.assertTrue(t.optional)
        self.assertIsNotNone(t.virtual)
        self.assertEqual(t.group, "system")
        self.assertEqual(t.min_agent, T.MIN_AGENT)

    def test_an_agent_that_does_not_report_instai_is_skipped_with_the_reason(self):
        ok, why = REGISTRY["instai"].available(node_with(None, name="no-report"))
        self.assertFalse(ok)
        self.assertIn("instai_jobs.py", why)
        self.assertEqual(REGISTRY["instai"].available(node_with(rep()))[0], True)


class Verdicts(TestCase):
    def test_no_folder_or_the_switch_off_is_a_skip_not_a_failure(self):
        for state in ("not_found", "disabled"):
            v = T.evaluate(rep(state=state, found=False, message_fa=""))
            self.assertTrue(v.skip and not v.ok, state)
            self.assertTrue(v.detail)

    def test_updating_and_starting_wait(self):
        for state in ("updating", "starting"):
            v = T.evaluate(rep(state=state, running=False))
            self.assertTrue(v.wait, state)
            self.assertIn("0.14.0", v.detail)
        self.assertTrue(T.evaluate(rep(state="whatever")).wait)

    def test_a_running_instai_with_a_newer_github_passes_with_a_warning_that_says_what_happens(self):
        v = T.evaluate(rep(state="waiting_running", version="0.8.0", github="0.14.0", has_updater=False))
        self.assertTrue(v.ok and "قدیمی" in v.detail)
        self.assertIn("0.14.0", v.warning)
        self.assertIn("STOP.bat", v.warning)

    def test_a_failed_update_fails_with_the_updaters_own_words(self):
        v = T.evaluate(rep(state="failed", last_update={"ok": False, "tail": "GitHub answered HTTP 403"}))
        self.assertFalse(v.ok)
        self.assertIn("HTTP 403", v.detail)
        self.assertIn("دوباره تلاش", v.detail)

    def test_up_to_date_but_not_running_fails_with_the_one_thing_to_do(self):
        v = T.evaluate(rep(state="current", running=False))
        self.assertFalse(v.ok)
        self.assertIn("START.bat", v.detail)

    def test_instai_runs_but_its_own_selftest_has_not_run_yet_waits(self):
        v = T.evaluate(rep(selftest=None))
        self.assertTrue(v.wait)
        self.assertIn("آزمونِ خودکارِ خودش", v.detail)

    def test_a_clean_report_passes_with_persian_digits(self):
        v = T.evaluate(rep())
        self.assertTrue(v.ok and not v.warning, v.detail)
        self.assertIn("۱۱ سالم", v.detail)
        self.assertEqual(v.extra["selftest"]["state"], "sound")

    def test_a_failing_check_of_instai_fails_and_names_it(self):
        v = T.evaluate(rep(selftest={"state": "problems", "ok": 7, "warn": 1, "fail": 2, "pending": 1, "failing": ["ffmpeg", "comfyui"], "waiting": ["nvenc"], "warning": ["disk"]}))
        self.assertFalse(v.ok)
        self.assertIn("ffmpeg", v.detail)
        self.assertIn("comfyui", v.detail)

    def test_waiting_checks_or_warnings_pass_with_a_warning_naming_them(self):
        v = T.evaluate(rep(selftest={"state": "waiting", "ok": 8, "warn": 0, "fail": 0, "pending": 2, "failing": [], "waiting": ["ollama_run", "comfyui"], "warning": []}))
        self.assertTrue(v.ok)
        self.assertIn("ollama_run", v.warning)
        w = T.evaluate(rep(selftest={"state": "attention", "ok": 9, "warn": 1, "fail": 0, "pending": 0, "failing": [], "waiting": [], "warning": ["disk"]}))
        self.assertTrue(w.ok)
        self.assertIn("disk", w.warning)


class InTheRun(TestCase):
    """Through the real runner: a node that is online, one step."""

    def run_for(self, report):
        load_all()
        node = node_with(report)
        run = runner.start_run(node, trigger="manual", only=["instai"])
        r = run.results.get(key="instai")
        runner.advance(run)
        r.refresh_from_db()
        return r

    def test_a_healthy_instai_passes(self):
        self.assertEqual(self.run_for(rep()).state, S.PASSED)

    def test_no_folder_is_skipped_and_a_starting_instai_waits(self):
        self.assertEqual(self.run_for(rep(state="not_found", found=False)).state, S.SKIPPED)

    def test_a_starting_instai_waits(self):
        self.assertEqual(self.run_for(rep(state="starting", running=False)).state, S.WAITING)

    def test_a_failed_update_fails_the_entry_only(self):
        r = self.run_for(rep(state="failed", last_update={"tail": "no space left"}))
        self.assertEqual(r.state, S.FAILED)
        self.assertIn("no space left", r.detail)
