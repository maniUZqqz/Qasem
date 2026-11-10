# -*- coding: utf-8 -*-
"""دسترسیِ راه‌دور به سرورهای پردازش (۱۴۰۵/۰۸/۱۹): ثبتِ کلیدِ تونل، وضعیت، دستورهای ثابت."""
import json
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import remote as R
from .models import ComputeNode, ComputeNodeLog

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHk0aX6q4wq2Pp0kq0uYfQ7n3m9Wl1y8b2Xc5d6e7f8g nm-node:test"


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "admin.pub").write_text("ssh-ed25519 AAAAADMIN admin@vps\n")
        (self.tmp / "host.pub").write_text("ssh-ed25519 AAAAHOSTKEY root@vps\n")
        self.patches = [
            mock.patch.object(R, "AUTH_KEYS", self.tmp / "tunnel" / "authorized_keys"),
            mock.patch.object(R, "ADMIN_KEY", self.tmp / "admin"),
            mock.patch.object(R, "KNOWN_HOSTS", self.tmp / "known_hosts"),
            mock.patch.object(R, "HOST_KEY_PUB", self.tmp / "host.pub"),
            # a real tunnel on this server (22200+pk) must not make a test node look connected: port 1+pk has nothing
            mock.patch.object(R, "PORT_BASE", 1),
        ]
        for p in self.patches:
            p.start()
        self.settings_ctx = override_settings(NM_DATA_DIR=self.tmp / "data")
        self.settings_ctx.enable()
        self.node = ComputeNode.objects.create(name="DESKTOP-TEST")

    def tearDown(self):
        self.settings_ctx.disable()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_sshd(self):
        """یک «سرِ تونل» ِ ساختگی روی پورتِ این گره که مثلِ sshd ِ ویندوز سلام می‌کند."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def serve():
            srv.settimeout(0.2)
            while not stop.is_set():
                try:
                    c, _ = srv.accept()
                except OSError:
                    continue
                c.sendall(b"SSH-2.0-OpenSSH_for_Windows_9.8\r\n")
                c.close()
            srv.close()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        p = mock.patch.object(R, "PORT_BASE", port - self.node.pk)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(stop.set)
        return port


class EnrollTests(_Base):
    def test_the_key_may_only_open_its_own_port_on_localhost(self):
        out = R.enroll(self.node, KEY, "QQz", home=r"C:\N\processing-server")
        line = R.AUTH_KEYS.read_text().strip()
        self.assertTrue(line.startswith('restrict,port-forwarding,permitlisten="127.0.0.1:%d" ssh-ed25519 ' % R.listen_port(self.node)))
        self.assertTrue(line.endswith("nm-node:DESKTOP-TEST"))
        self.assertEqual(out["listen_port"], R.listen_port(self.node))
        self.assertEqual(out["user"], "nmtunnel")
        self.assertEqual(out["admin_pubkey"], "ssh-ed25519 AAAAADMIN admin@vps")
        self.assertEqual(out["known_hosts"], "87.107.160.17 ssh-ed25519 AAAAHOSTKEY")
        info = R.load(self.node)
        self.assertEqual(info["user"], "QQz")
        self.assertEqual(info["home"], r"C:\N\processing-server")

    def test_enrolling_again_replaces_only_this_nodes_line(self):
        R.AUTH_KEYS.parent.mkdir(parents=True)
        R.AUTH_KEYS.write_text('restrict,port-forwarding,permitlisten="127.0.0.1:22299" ssh-ed25519 AAAAOTHER nm-node:OTHER\n')
        R.enroll(self.node, KEY, "QQz")
        R.enroll(self.node, KEY.replace("Hk0", "Zz9"), "QQz")
        lines = R.AUTH_KEYS.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("nm-node:OTHER", lines[0])
        self.assertIn("Zz9", lines[1])

    def test_bad_keys_and_user_names_are_refused(self):
        for bad in ("", "ssh-rsa AAAAB3Nza", KEY + "\nssh-ed25519 AAAA x", 'command="sh" ' + KEY):
            with self.assertRaises(R.RemoteError, msg=bad):
                R.enroll(self.node, bad, "QQz")
        for bad in ("", "a b", "x;rm", "QQz\"", "..\\x"):
            with self.assertRaises(R.RemoteError, msg=bad):
                R.enroll(self.node, KEY, bad)
        self.assertFalse(R.AUTH_KEYS.exists())


class StateAndControlTests(_Base):
    def test_state_before_and_after_enrolling(self):
        self.assertFalse(R.state(self.node)["enrolled"])
        R.enroll(self.node, KEY, "QQz")
        st = R.state(self.node)
        self.assertTrue(st["enrolled"])
        self.assertFalse(st["tunnel_up"])
        self.fake_sshd()
        R.enroll(self.node, KEY, "QQz")          # the port follows PORT_BASE
        st = R.state(self.node)
        self.assertTrue(st["tunnel_up"])
        self.assertTrue(st["banner"].startswith("SSH-2.0-OpenSSH_for_Windows"))

    def test_control_runs_the_fixed_command_over_the_tunnel(self):
        self.fake_sshd()
        R.enroll(self.node, KEY, "QQz")
        R.mark_started(self.node, "update", "admin")
        done = subprocess.CompletedProcess([], 0, b"stopped\nupdated\nstarted\n", b"")
        with mock.patch.object(R.subprocess, "run", return_value=done) as run:
            row = R.control(self.node, "update", "admin")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("BatchMode=yes", cmd)
        self.assertEqual(cmd[cmd.index("-l") + 1], "QQz")
        self.assertEqual(cmd[cmd.index("-p") + 1], str(R.listen_port(self.node)))
        self.assertEqual(cmd[-1], R.CONTROL + " update")
        self.assertEqual(row["exit_code"], 0)
        self.assertFalse(R.last(self.node)["running"])
        self.assertIn("updated", R.last(self.node)["output"])
        self.assertTrue(ComputeNodeLog.objects.filter(node=self.node, message__startswith="remote update").exists())

    def test_one_command_at_a_time_and_only_known_ones(self):
        self.fake_sshd()
        R.enroll(self.node, KEY, "QQz")
        with self.assertRaises(R.RemoteError):
            R.mark_started(self.node, "format c:", "admin")
        R.mark_started(self.node, "status", "admin")
        with self.assertRaises(R.RemoteError):
            R.mark_started(self.node, "stop", "admin")

    def test_no_command_when_the_tunnel_is_down(self):
        R.enroll(self.node, KEY, "QQz")
        with self.assertRaises(R.RemoteError):
            R.mark_started(self.node, "status", "admin")


class ViewTests(_Base):
    def test_enroll_needs_the_node_token(self):
        c = APIClient()
        self.assertEqual(c.post("/api/v1/compute/remote/enroll/", {"pubkey": KEY, "user": "QQz"}, format="json").status_code, 401)
        c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        r = c.post("/api/v1/compute/remote/enroll/", {"pubkey": KEY, "user": "QQz"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["listen_port"], R.listen_port(self.node))
        self.assertEqual(c.post("/api/v1/compute/remote/enroll/", {"pubkey": "bad", "user": "QQz"}, format="json").status_code, 400)
        self.assertEqual(c.get("/api/v1/compute/remote/check/").json()["tunnel_up"], False)

    def test_control_is_for_staff_and_queues_the_task(self):
        User = get_user_model()
        plain = User.objects.create_user("plain-r", password="x")
        staff = User.objects.create_user("staff-r", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(plain)
        self.assertEqual(c.post("/api/v1/compute/nodes/%d/control/" % self.node.pk, {"action": "status"}, format="json").status_code, 403)
        c.force_authenticate(staff)
        self.assertEqual(c.post("/api/v1/compute/nodes/%d/control/" % self.node.pk, {"action": "status"}, format="json").status_code, 409)
        self.fake_sshd()
        R.enroll(self.node, KEY, "QQz")
        self.assertTrue(c.get("/api/v1/compute/nodes/%d/remote/" % self.node.pk).json()["tunnel_up"])
        with mock.patch("apps.compute.tasks.remote_control.apply_async") as queued:
            r = c.post("/api/v1/compute/nodes/%d/control/" % self.node.pk, {"action": "restart"}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(queued.call_args.kwargs["args"], [self.node.pk, "restart", "staff-r"])
        self.assertEqual(queued.call_args.kwargs["queue"], "ai")
        self.assertTrue(R.last(self.node)["running"])
        r = c.post("/api/v1/compute/nodes/%d/control/" % self.node.pk, {"action": "rm -rf"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("ناشناخته", json.loads(r.content)["error"])           # only the fixed commands, never a shell line
