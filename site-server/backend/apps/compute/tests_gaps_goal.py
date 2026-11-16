# -*- coding: utf-8 -*-
"""هدفِ کلی («با روشن‌کردنِ سرورِ پردازش همه‌چیز خودکار نصب، اجرا و آزموده شود»): آزمونِ خودکار با روشن‌شدنِ گره و «کارهای مالک» (ردیفِ InstAI از آزمونِ «instai» می‌خواند).

بدونِ گرهٔ واقعی: گره و جوابش ساختگی‌اند.
"""
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import autopilot, owner_steps
from .models import ComputeNode, SelfTestResult, SelfTestRun


class PresenceTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-presence-"))
        self.ov = override_settings(NM_DATA_DIR=self.tmp)
        self.ov.enable()
        self.node = ComputeNode.objects.create(name="n1", capabilities={"agent": "2.24"}, last_seen=timezone.now() - timedelta(hours=20))

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_sight_of_an_offline_node_remembers_since_when(self):
        self.assertFalse(autopilot.note_presence(self.node))
        st = json.loads((self.tmp / "node-online-state.json").read_text(encoding="utf-8"))
        rec = st[str(self.node.pk)]
        self.assertFalse(rec["online"])
        self.assertLess(rec["since"], timezone.now().timestamp() - 3600 * 19, "the outage starts at last_seen, not at the first check")

    def test_coming_back_after_a_real_outage_fires_once(self):
        self.assertFalse(autopilot.note_presence(self.node))
        self.node.last_seen = timezone.now()
        self.node.save()
        self.assertTrue(autopilot.note_presence(self.node), "off for 20 h then on ⇒ test everything")
        self.assertFalse(autopilot.note_presence(self.node), "only once per outage")

    def test_a_short_blip_does_not_count(self):
        self.node.last_seen = timezone.now()
        self.node.save()
        self.assertFalse(autopilot.note_presence(self.node))           # online, remembered
        self.node.last_seen = timezone.now() - timedelta(minutes=3)
        self.node.save()
        self.assertFalse(autopilot.note_presence(self.node))           # offline (3 min)
        self.node.last_seen = timezone.now()
        self.node.save()
        self.assertFalse(autopilot.note_presence(self.node), "three minutes is a network blip, not a power-on")

    def test_tick_starts_an_online_run_for_the_updated_node(self):
        self.assertFalse(autopilot.note_presence(self.node))
        self.node.last_seen = timezone.now()
        self.node.save()
        with mock.patch("apps.compute.selftests.runner.start_run") as start, mock.patch("apps.compute.autopilot.update_wanted", return_value=(False, "")), \
                mock.patch("apps.compute.autopilot.send_update", return_value=None), mock.patch("apps.compute.selftests.runner.advance_all", return_value={}),                 mock.patch("apps.compute.autopilot.nightly_due", return_value=""):
            out = autopilot.tick()
        start.assert_called_once()
        self.assertEqual(start.call_args[0][1], "online")
        self.assertEqual(out["online"], 1)

    def test_tick_waits_for_a_pending_update_first(self):
        self.assertFalse(autopilot.note_presence(self.node))
        self.node.last_seen = timezone.now()
        self.node.save()
        with mock.patch("apps.compute.selftests.runner.start_run") as start, mock.patch("apps.compute.autopilot.update_wanted", return_value=(True, "x")), \
                mock.patch("apps.compute.autopilot.send_update", return_value=None), mock.patch("apps.compute.selftests.runner.advance_all", return_value={}),                 mock.patch("apps.compute.autopilot.nightly_due", return_value=""):
            autopilot.tick()
        start.assert_not_called()


class OwnerStepsTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-owner-"))
        self.ov = override_settings(NM_DATA_DIR=self.tmp)
        self.ov.enable()
        U = get_user_model()
        self.staff = U.objects.create_user("os-staff", password="x", is_staff=True)
        self.user = U.objects.create_user("os-user", password="x")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_lists_every_manual_step_with_a_state_and_how(self):
        d = owner_steps.build()
        keys = [s["key"] for s in d["steps"]]
        for want in ("node_on", "instai_fresh", "ig_login", "metis_credit", "c21st_key", "chagher_facts", "remotion_licence"):
            self.assertIn(want, keys)
        for s in d["steps"]:
            self.assertIn(s["state"], ("ok", "todo", "wait", "unknown"))
            self.assertTrue(s["title"] and s["how"] and s["detail"])
        self.assertEqual(d["total"], len(keys))

    def test_node_step_follows_the_live_node(self):
        self.assertEqual(next(s for s in owner_steps.build()["steps"] if s["key"] == "node_on")["state"], "unknown")
        node = ComputeNode.objects.create(name="gpu1", capabilities={"agent": "2.24"}, last_seen=timezone.now() - timedelta(hours=30))
        row = next(s for s in owner_steps.build()["steps"] if s["key"] == "node_on")
        self.assertEqual(row["state"], "todo")
        self.assertIn("30 ساعت", row["detail"].replace("۳۰", "30"))
        node.last_seen = timezone.now()
        node.save()
        self.assertEqual(next(s for s in owner_steps.build()["steps"] if s["key"] == "node_on")["state"], "ok")

    def test_instai_step_is_a_manual_zip_until_the_node_agent_has_the_neighbour(self):
        with mock.patch.object(owner_steps, "_instai_auto", return_value=False):
            row = next(s for s in owner_steps.build()["steps"] if s["key"] == "instai_fresh")
        self.assertEqual(row["state"], "todo")
        self.assertIn("ZIP", row["title"])
        self.assertIn("START.bat", row["how"])
        self.assertNotIn("کارِ دستی لازم نیست", row["how"], "never promise automation the agent does not have")

    @mock.patch.object(owner_steps, "_instai_auto", return_value=True)
    def test_instai_step_follows_the_selftest_result(self, _auto):
        node = ComputeNode.objects.create(name="gpu2", capabilities={"agent": "2.24"}, last_seen=timezone.now())
        run = SelfTestRun.objects.create(node=node, trigger="online")
        SelfTestResult.objects.create(run=run, key="instai", label="x", state="FAILED", detail="پوشهٔ InstAI یک ZIPِ قدیمی است")
        row = next(s for s in owner_steps.build()["steps"] if s["key"] == "instai_fresh")
        self.assertEqual(row["state"], "todo")
        self.assertIn("ZIPِ قدیمی", row["detail"])
        SelfTestResult.objects.filter(run=run, key="instai").update(state="WAITING", detail="InstAI در حالِ به‌روزرسانی است")
        row = next(s for s in owner_steps.build()["steps"] if s["key"] == "instai_fresh")
        self.assertEqual(row["state"], "wait", "an update in progress is not a task for the owner")
        SelfTestResult.objects.filter(run=run, key="instai").update(state="PASSED", detail="InstAI 0.12.0 روشن است")
        self.assertEqual(next(s for s in owner_steps.build()["steps"] if s["key"] == "instai_fresh")["state"], "ok")
        row = next(s for s in owner_steps.build()["steps"] if s["key"] == "instai_fresh")
        self.assertIn("کارِ دستی لازم نیست", row["how"])

    def test_decision_steps_close_with_the_owner_tick_only(self):
        row = next(s for s in owner_steps.build()["steps"] if s["key"] == "chagher_facts")
        self.assertEqual(row["state"], "wait")
        self.assertTrue(row["markable"])
        live = next(s for s in owner_steps.build()["steps"] if s["key"] == "instai_fresh")
        self.assertFalse(live["markable"], "a live-checked step cannot be ticked by hand")
        owner_steps.set_mark("chagher_facts", True)
        self.assertEqual(next(s for s in owner_steps.build()["steps"] if s["key"] == "chagher_facts")["state"], "ok")
        owner_steps.set_mark("chagher_facts", False)
        self.assertEqual(next(s for s in owner_steps.build()["steps"] if s["key"] == "chagher_facts")["state"], "wait")
        with self.assertRaises(KeyError):
            owner_steps.set_mark("nope", True)

    def test_api_is_staff_only_and_posts_marks(self):
        self.assertIn(APIClient().get("/api/v1/compute/owner-steps/").status_code, (401, 403))
        u = APIClient()
        u.force_authenticate(self.user)
        self.assertEqual(u.get("/api/v1/compute/owner-steps/").status_code, 403)
        r = self.c.get("/api/v1/compute/owner-steps/")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.c.post("/api/v1/compute/owner-steps/", {"key": "remotion_licence", "done": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(next(s for s in r.json()["steps"] if s["key"] == "remotion_licence")["state"], "ok")
        self.assertEqual(self.c.post("/api/v1/compute/owner-steps/", {"key": "zzz", "done": True}, format="json").status_code, 404)

    def test_a_broken_live_check_does_not_break_the_list(self):
        with mock.patch.object(owner_steps, "_metis", side_effect=RuntimeError("boom")):
            defs = owner_steps.definitions()
        self.assertTrue(defs)
        with mock.patch("apps.compute.owner_steps._latest_selftest", side_effect=RuntimeError("db down")), mock.patch.object(owner_steps, "_instai_auto", return_value=True):
            d = owner_steps.build()
        self.assertTrue(any(s["key"] == "instai_fresh" and s["state"] == "unknown" for s in d["steps"]))
