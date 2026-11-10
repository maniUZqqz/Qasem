# -*- coding: utf-8 -*-
"""«دستورها» ِ سرورِ پردازش از پنل (۱۴۰۵/۰۸/۱۹): پنل ⇐ heartbeat ⇐ عامل ⇐ گزارش."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import commands as C
from .models import ComputeNode, ComputeNodeLog


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = override_settings(NM_DATA_DIR=self.tmp)
        self.ctx.enable()
        self.node = ComputeNode.objects.create(
            name="gpu-cmd", last_seen=timezone.now(),
            capabilities={"agent": "2.10", "commands": list(C.ACTIONS)})
        User = get_user_model()
        self.staff = User.objects.create_user("staff-cmd", password="x", is_staff=True)
        self.plain = User.objects.create_user("plain-cmd", password="x")

    def tearDown(self):
        self.ctx.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)


class FlowTests(_Base):
    def test_panel_to_heartbeat_to_report(self):
        last = C.request(self.node, "update", "staff-cmd")
        self.assertEqual(last["state"], "sent")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        hb = c.post("/api/v1/compute/heartbeat/", {}, format="json").json()
        self.assertEqual(hb["command"], {"id": last["id"], "action": "update"})
        self.assertTrue(c.post("/api/v1/compute/commands/%s/" % last["id"], {"state": "running"}, format="json").json()["ok"])
        self.assertNotIn("command", c.post("/api/v1/compute/heartbeat/", {}, format="json").json())   # taken: not again
        self.assertEqual(C.state(self.node)["last"]["state"], "running")
        r = c.post("/api/v1/compute/commands/%s/" % last["id"], {"state": "done", "ok": True, "output": "updated\nrestarting"},
                   format="json")
        self.assertTrue(r.json()["ok"])
        st = C.state(self.node)
        self.assertEqual(st["last"]["state"], "done")
        self.assertTrue(st["last"]["ok"])
        self.assertIn("restarting", st["last"]["output"])
        self.assertFalse(st["busy"])
        self.assertTrue(ComputeNodeLog.objects.filter(node=self.node, message__startswith="command update").exists())

    def test_a_report_for_another_command_is_ignored(self):
        C.request(self.node, "status")
        self.assertFalse(C.report(self.node, "nope", "done", True, "x"))
        self.assertEqual(C.state(self.node)["last"]["state"], "sent")

    def test_one_at_a_time_known_ones_only(self):
        with self.assertRaises(C.CommandError):
            C.request(self.node, "format c:")
        C.request(self.node, "status")
        with self.assertRaises(C.CommandError):
            C.request(self.node, "restart")

    def test_offline_or_old_agents_are_told_why(self):
        self.node.last_seen = timezone.now() - timedelta(minutes=10)
        self.node.save()
        with self.assertRaisesRegex(C.CommandError, "خاموش"):
            C.request(self.node, "status")
        self.node.last_seen = timezone.now()
        self.node.capabilities = {"agent": "2.9"}
        self.node.save()
        self.assertFalse(C.state(self.node)["supported"])
        with self.assertRaisesRegex(C.CommandError, "START.bat"):
            C.request(self.node, "status")
        self.node.capabilities = {"agent": "2.10", "commands": ["status"]}
        self.assertTrue(C.supported(self.node))           # 2.10 > 2.9 as numbers, not as text

    def test_an_untaken_command_expires(self):
        C.request(self.node, "status")
        data = C._read(self.node)
        data["pending"]["at"] = (timezone.now() - timedelta(hours=1)).isoformat()
        C._write(self.node, data)
        self.assertIsNone(C.pending_for(self.node))
        self.assertEqual(C.state(self.node)["last"]["state"], "expired")
        C.request(self.node, "status")                    # and a new one may be sent


class ViewTests(_Base):
    def test_staff_only_and_node_token_only(self):
        c = APIClient()
        c.force_authenticate(self.plain)
        self.assertEqual(c.get("/api/v1/compute/nodes/%d/commands/" % self.node.pk).status_code, 403)
        c.force_authenticate(self.staff)
        st = c.get("/api/v1/compute/nodes/%d/commands/" % self.node.pk).json()
        self.assertTrue(st["supported"])
        self.assertEqual([a["key"] for a in st["actions"]], list(C.ACTIONS))
        r = c.post("/api/v1/compute/nodes/%d/commands/" % self.node.pk, {"action": "restart"}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(r.json()["last"]["by"], "staff-cmd")
        self.assertEqual(c.post("/api/v1/compute/nodes/%d/commands/" % self.node.pk, {"action": "status"}, format="json").status_code, 409)
        anon = APIClient()
        self.assertEqual(anon.post("/api/v1/compute/commands/%s/" % r.json()["last"]["id"], {"state": "done"}, format="json").status_code, 401)
