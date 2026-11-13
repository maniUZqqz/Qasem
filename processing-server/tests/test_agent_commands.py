"""agent 2.10: the panel's commands (status / update / restart / build / logs) through the heartbeat (2026-11-10)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402


class FakeSite:
    def __init__(self):
        self.calls = []

    def post(self, path, data=None, timeout=60):
        self.calls.append((path, dict(data or {})))
        return {"ok": True}

    def states(self):
        return [d.get("state") for _p, d in self.calls]


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "logs"))
        self.patches = [mock.patch.object(agent, "DATA", self.tmp), mock.patch.object(agent, "LOGS", os.path.join(self.tmp, "logs")),
                        mock.patch.dict(agent.CMD, {"seen": set(), "restart": None})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_done(self, site):
        for _ in range(100):
            if "done" in site.states():
                return
            time.sleep(0.05)
        self.fail("no answer: %s" % site.calls)

    def test_the_version_and_caps(self):
        self.assertEqual(agent.VERSION, "2.12")
        self.assertEqual(tuple(agent.COMMANDS), ("status", "update", "restart", "build", "logs", "bootstrap"))

    def test_status_is_acknowledged_then_answered(self):
        site = FakeSite()
        agent.run_command(site, {"id": "c1", "action": "status"})
        self.wait_done(site)
        self.assertEqual(site.calls[0], ("/api/v1/compute/commands/c1/", {"state": "running", "ok": None, "output": ""}))
        path, done = site.calls[-1]
        self.assertTrue(done["ok"])
        self.assertIn("agent v2.12", done["output"])
        self.assertIn("services:", done["output"])

    def test_the_same_command_runs_once(self):
        site = FakeSite()
        agent.run_command(site, {"id": "c2", "action": "logs"})
        self.wait_done(site)
        n = len(site.calls)
        agent.run_command(site, {"id": "c2", "action": "logs"})
        self.assertEqual(len(site.calls), n)

    def test_a_command_done_before_a_restart_is_not_repeated(self):
        with open(os.path.join(self.tmp, "last-command.txt"), "w") as fh:
            fh.write("c3")
        site = FakeSite()
        agent.run_command(site, {"id": "c3", "action": "update"})
        self.assertIsNone(agent.CMD["restart"])
        self.assertEqual(site.states(), ["done"])

    def test_update_and_restart_are_left_to_the_main_loop(self):
        site = FakeSite()
        agent.run_command(site, {"id": "c4", "action": "update"})
        self.assertEqual(agent.CMD["restart"], {"id": "c4", "action": "update"})
        self.assertEqual(site.states(), ["running"])

    def test_logs_include_the_agent_and_service_logs(self):
        with open(os.path.join(self.tmp, "logs", "agent.log"), "w", encoding="utf-8") as fh:
            fh.write("line a\nline b\n")
        with open(os.path.join(self.tmp, "logs", "service-comfyui.log"), "wb") as fh:
            fh.write("old powershell log\r\n".encode("utf-16"))
        ok, out = agent.cmd_logs()
        self.assertTrue(ok)
        self.assertIn("===== agent.log =====", out)
        self.assertIn("line b", out)
        self.assertIn("old powershell log", out)

    def test_update_runs_update_py_auto_in_place(self):
        done = subprocess.CompletedProcess([], 0, b"up to date\n", b"")
        with mock.patch.object(agent.subprocess, "run", return_value=done) as run:
            ok, out = agent.run_update_now()
        self.assertTrue(ok)
        self.assertEqual(run.call_args[0][0][1:], [os.path.join(agent.HERE, "update.py"), "--auto"])
        self.assertIn("up to date", out)

    def test_unknown_commands_answer_with_an_error(self):
        site = FakeSite()
        agent.run_command(site, {"id": "c5", "action": "format"})
        self.wait_done(site)
        self.assertFalse(site.calls[-1][1]["ok"])

    def test_no_remote_access_bits_left_in_the_agent(self):
        self.assertFalse(hasattr(agent, "note_home"))


if __name__ == "__main__":
    unittest.main()
