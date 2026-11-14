"""instai_jobs.py (InstAI as a neighbour of the node): finding the folder, reading its state, updating an old folder by itself, starting it once, never touching a
running InstAI, backing off after a failure - all on temporary folders, a fake health server and a fake GitHub (a local HTTP server); nothing of the real machine is touched.

    python tests/test_instai_jobs.py
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")

import instai_jobs as IJ  # noqa: E402

OLD_BAT = "@echo off\r\ncd /d %~dp0\r\n.venv\\Scripts\\python.exe scripts\\bootstrap.py\r\n"
NEW_BAT = OLD_BAT + ".venv\\Scripts\\python.exe scripts\\self_update.py\r\n"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_instai(parent, version="0.8.0", bat=OLD_BAT, updater=False, port=None, selftest=None):
    """A folder that looks like InstAI to the markers (manage.py, instai/settings.py, VERSION)."""
    os.makedirs(os.path.join(parent, "instai"), exist_ok=True)
    for rel, text in (("manage.py", "# manage\n"), (os.path.join("instai", "settings.py"), "# settings\n"), ("VERSION", version + "\n"), ("START.bat", bat)):
        with open(os.path.join(parent, rel), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    if updater:
        os.makedirs(os.path.join(parent, "scripts"), exist_ok=True)
        with open(os.path.join(parent, "scripts", "self_update.py"), "w", encoding="utf-8") as fh:
            fh.write('"""InstAI self-update (test copy)"""\n')
    if port:
        with open(os.path.join(parent, ".env"), "w", encoding="utf-8") as fh:
            fh.write("INSTAI_PORT=%d\n" % port)
    if selftest:
        os.makedirs(os.path.join(parent, "data", "selftest"), exist_ok=True)
        with open(os.path.join(parent, "data", "selftest", "pc.json"), "w", encoding="utf-8") as fh:
            json.dump(selftest, fh)
    return parent


class Health(BaseHTTPRequestHandler):
    version = "0.8.0"

    def do_GET(self):
        body = json.dumps({"ok": True, "version": Health.version, "workers": 1}).encode()
        self.send_response(200 if self.path == "/api/health" else 404)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-instai-test-")
        self.home = os.path.join(self.tmp, "home")
        self.desk = os.path.join(self.home, "Desktop")
        os.makedirs(self.desk)
        self.env = {"USERPROFILE": self.home}
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def health_server(self, version="0.8.0"):
        Health.version = version
        port = free_port()
        srv = ThreadingHTTPServer(("127.0.0.1", port), Health)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.servers.append(srv)
        return port

    def service(self, **kw):
        env = dict(self.env, **kw)
        return IJ.Service(os.path.join(self.tmp, "nmdata"), env=env)


class Finding(Base):
    def test_the_owners_layout_is_found_three_levels_down(self):
        d = make_instai(os.path.join(self.desk, "Instai-main", "V2", "Instai-main"))
        self.assertEqual(IJ.find_folders(self.env), [d])
        self.assertTrue(IJ.is_instai_dir(d))
        self.assertFalse(IJ.is_instai_dir(os.path.join(self.desk, "Instai-main")))

    def test_only_folders_with_instai_in_the_name_are_searched_and_too_deep_is_ignored(self):
        make_instai(os.path.join(self.desk, "Other", "Thing"))                        # looks like InstAI inside, but the name never says so
        make_instai(os.path.join(self.desk, "instai", "a", "b", "c", "d"))             # deeper than three levels
        self.assertEqual(IJ.find_folders(self.env), [])

    def test_the_variable_wins_and_the_highest_version_is_the_default(self):
        old = make_instai(os.path.join(self.desk, "Instai-old"), "0.8.0")
        new = make_instai(os.path.join(self.desk, "Instai-new"), "0.12.1")
        self.assertEqual(IJ.find_folders(self.env), [new, old])
        self.assertEqual(IJ.find_folders(dict(self.env, NM_INSTAI_DIR=old))[0], old)
        self.assertEqual(IJ.find_folders(self.env, remembered=old)[0], old)            # the remembered one is kept while it is still InstAI

    def test_nothing_found(self):
        self.assertEqual(IJ.find_folders(self.env), [])
        svc = self.service()
        self.assertEqual(svc.tick(), "not_found")
        r = svc.report()
        self.assertFalse(r["found"])
        self.assertEqual(r["state"], "not_found")
        self.assertIn("پیدا نشد", r["message_fa"])


class Looking(Base):
    def test_a_running_server_a_missing_updater_and_the_own_selftest_are_read(self):
        port = self.health_server("0.8.0")
        d = make_instai(os.path.join(self.desk, "Instai-main"), port=port, selftest={"summary": {"state": "waiting", "ok": 5, "warn": 1, "fail": 0, "pending": 3},
                        "checks": [{"key": "disk", "verdict": "warn"}, {"key": "comfyui", "verdict": "pending"}, {"key": "ffmpeg", "verdict": "ok"}], "version": "0.14.0", "finished_at": "2026-11-14T10:00:00"})
        i = IJ.inspect_folder(d)
        self.assertTrue(i["running"] and i["running_version"] == "0.8.0" and i["workers"] == 1)
        self.assertFalse(i["start_bat_has_updater"])
        self.assertEqual(i["version"], "0.8.0")
        self.assertEqual(i["selftest"]["state"], "waiting")
        self.assertEqual(i["selftest"]["warning"], ["disk"])
        self.assertEqual(i["selftest"]["waiting"], ["comfyui"])
        d2 = make_instai(os.path.join(self.desk, "Instai-two"), bat=NEW_BAT, updater=True, port=free_port())
        j = IJ.inspect_folder(d2)
        self.assertTrue(j["start_bat_has_updater"] and j["updater_script"] and not j["running"] and j["selftest"] is None)

    def test_a_broken_report_file_is_not_a_crash(self):
        d = make_instai(os.path.join(self.desk, "Instai-main"))
        os.makedirs(os.path.join(d, "data", "selftest"))
        with open(os.path.join(d, "data", "selftest", "pc.json"), "w") as fh:
            fh.write("{not json")
        self.assertIsNone(IJ.own_selftest(d))


class Updating(Base):
    def fake_update(self, calls, ok=True):
        def update(folder):
            calls.append(folder)
            if ok:
                with open(os.path.join(folder, "START.bat"), "w", newline="") as fh:
                    fh.write(NEW_BAT)
                with open(os.path.join(folder, "VERSION"), "w") as fh:
                    fh.write("0.14.0\n")
            return {"ok": ok, "code": 0 if ok else 1, "tail": "updated InstAI v0.8.0 -> v0.14.0" if ok else "could not download the update", "seconds": 1.2}
        return update

    def test_an_old_folder_is_updated_by_itself_and_started_once(self):
        d = make_instai(os.path.join(self.desk, "Instai-main", "V2", "Instai-main"), "0.8.0", port=free_port())
        svc, calls, started = self.service(), [], []
        st = svc.tick(now=1000.0, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0")
        self.assertEqual(calls, [d])
        self.assertEqual(started, [d])
        self.assertEqual(st, "starting")
        r = svc.report()
        self.assertTrue(r["found"] and r["has_updater"] and r["version"] == "0.14.0" and r["github"] == "0.14.0")
        self.assertEqual(r["last_update"]["from"], "0.8.0")
        self.assertEqual(r["last_update"]["to"], "0.14.0")
        # the next looks: nothing to update, InstAI was started already (not again), and after the grace period without an answer it is "current", not "dead"
        svc.tick(now=1200.0, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(started), 1)
        self.assertEqual(svc.tick(now=1000.0 + IJ.STARTING_GRACE_S + 5, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0"), "current")

    def test_a_running_instai_is_never_touched(self):
        port = self.health_server("0.8.0")
        make_instai(os.path.join(self.desk, "Instai-main"), "0.8.0", port=port)
        svc, calls = self.service(), []
        st = svc.tick(now=1.0, update=self.fake_update(calls), start=lambda f: True, get_remote=lambda: "0.14.0")
        self.assertEqual(st, "waiting_running")
        self.assertEqual(calls, [])
        self.assertIn("قدیمی", svc.report()["message_fa"])
        # a folder that CAN update itself, GitHub is newer, still running: waits too
        d = make_instai(os.path.join(self.desk, "Instai-ok"), "0.13.0", bat=NEW_BAT, updater=True, port=port)
        svc2 = self.service(NM_INSTAI_DIR=d)
        self.assertEqual(svc2.tick(now=1.0, update=self.fake_update(calls), start=lambda f: True, get_remote=lambda: "0.14.0"), "waiting_running")
        self.assertEqual(calls, [])

    def test_a_folder_that_is_up_to_date_is_left_alone_and_started_when_it_is_off(self):
        d = make_instai(os.path.join(self.desk, "Instai-main"), "0.14.0", bat=NEW_BAT, updater=True, port=free_port())
        svc, calls, started = self.service(), [], []
        st = svc.tick(now=1.0, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0")
        self.assertEqual(calls, [])
        self.assertEqual(started, [d])
        self.assertEqual(st, "starting")
        svc.tick(now=2.0, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0")
        self.assertEqual(len(started), 1, "stopped by the owner later: not started again until the node starts the next time")
        # GitHub unreachable: no verdict about "newer", nothing happens
        svc3 = self.service()
        self.assertEqual(svc3.tick(now=1.0, update=self.fake_update(calls), start=lambda f: True, get_remote=lambda: ""), "starting")
        self.assertEqual(calls, [])

    def test_a_failed_update_waits_and_tries_again_with_a_growing_pause(self):
        d = make_instai(os.path.join(self.desk, "Instai-main"), "0.8.0", port=free_port())
        svc, calls, started = self.service(), [], []
        kw = dict(update=self.fake_update(calls, ok=False), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0")
        self.assertEqual(svc.tick(now=100.0, **kw), "failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(started, [])
        self.assertIn("could not download", svc.report()["message_fa"])
        self.assertEqual(svc.tick(now=100.0 + 60, **kw), "failed")
        self.assertEqual(len(calls), 1, "not before the pause is over")
        svc.tick(now=100.0 + IJ.RETRY_UPDATE_S[0] + 1, **kw)
        self.assertEqual(len(calls), 2)
        self.assertEqual(svc.failures, 2)
        self.assertGreater(svc.next_try - (100.0 + IJ.RETRY_UPDATE_S[0] + 1), IJ.RETRY_UPDATE_S[0])      # the second pause is longer
        # it works the third time: the failures are forgotten
        ok_kw = dict(kw, update=self.fake_update(calls, ok=True))
        svc.tick(now=svc.next_try + 1, **ok_kw)
        self.assertEqual(svc.failures, 0)
        self.assertEqual(started, [d])
        self.assertEqual(IJ.inspect_folder(d)["start_bat_has_updater"], True)

    def test_the_switches(self):
        d = make_instai(os.path.join(self.desk, "Instai-main"), "0.8.0")
        calls, started = [], []
        off = self.service(NM_INSTAI_SYNC="0")
        self.assertEqual(off.tick(now=1.0, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0"), "disabled")
        self.assertEqual((calls, started), ([], []))
        self.assertFalse(off.report()["sync"])
        nostart = self.service(NM_INSTAI_START="0")
        nostart.tick(now=1.0, update=self.fake_update(calls), start=lambda f: started.append(f) or True, get_remote=lambda: "0.14.0")
        self.assertEqual(calls, [d])
        self.assertEqual(started, [])


class GitHub(Base):
    def github(self, files):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                key = self.path.split("/main/", 1)[-1]
                body = files.get(key)
                self.send_response(200 if body is not None else 404)
                self.end_headers()
                if body is not None:
                    self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", free_port()), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.servers.append(srv)
        return "http://127.0.0.1:%d" % srv.server_port

    def test_the_remote_version_is_read_and_garbage_is_ignored(self):
        base = self.github({"VERSION": b"0.14.0\n"})
        os.environ["NM_INSTAI_RAW"] = base
        try:
            self.assertEqual(IJ.remote_version(), "0.14.0")
        finally:
            os.environ.pop("NM_INSTAI_RAW")
        base = self.github({"VERSION": b"<html>blocked</html>"})
        os.environ["NM_INSTAI_RAW"] = base
        try:
            self.assertEqual(IJ.remote_version(), "")
        finally:
            os.environ.pop("NM_INSTAI_RAW")
        os.environ["NM_INSTAI_RAW"] = "http://127.0.0.1:9"
        try:
            self.assertEqual(IJ.remote_version(), "")                                 # no server: empty, never an exception
        finally:
            os.environ.pop("NM_INSTAI_RAW")

    def test_the_updater_script_of_an_old_folder_is_fetched_checked_and_really_run(self):
        script = ('"""InstAI self-update (test copy)"""\nimport os, sys\nroot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n'
                  'open(os.path.join(root, "START.bat"), "w").write("self_update.py\\n")\nopen(os.path.join(root, "VERSION"), "w").write("0.14.0\\n")\nprint("updated InstAI v0.8.0 -> v0.14.0")\nsys.exit(10)\n')
        os.environ["NM_INSTAI_RAW"] = self.github({"scripts/self_update.py": script.encode()})
        try:
            d = make_instai(os.path.join(self.desk, "Instai-main"), "0.8.0")
            self.assertFalse(os.path.exists(os.path.join(d, "scripts", "self_update.py")))
            res = IJ.run_update(d)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["code"], 10)
            self.assertIn("0.14.0", res["tail"])
            self.assertTrue(IJ.inspect_folder(d)["start_bat_has_updater"])
            self.assertEqual(IJ.inspect_folder(d)["version"], "0.14.0")
        finally:
            os.environ.pop("NM_INSTAI_RAW")

    def test_a_wrong_or_broken_script_is_never_put_into_the_folder(self):
        for body in (b"print('hello')\n", b'"""InstAI self-update"""\ndef broken(:\n'):
            os.environ["NM_INSTAI_RAW"] = self.github({"scripts/self_update.py": body})
            try:
                d = make_instai(os.path.join(self.tmp, "x%d" % len(body)), "0.8.0")
                ok, why = IJ.ensure_updater_script(d)
                self.assertFalse(ok)
                self.assertTrue(why)
                self.assertFalse(os.path.exists(os.path.join(d, "scripts", "self_update.py")))
                self.assertFalse(IJ.run_update(d)["ok"])
            finally:
                os.environ.pop("NM_INSTAI_RAW")
        os.environ["NM_INSTAI_RAW"] = "http://127.0.0.1:9"                           # GitHub down
        try:
            d = make_instai(os.path.join(self.tmp, "y"), "0.8.0")
            ok, why = IJ.ensure_updater_script(d)
            self.assertFalse(ok)
            self.assertIn("could not be downloaded", why)
        finally:
            os.environ.pop("NM_INSTAI_RAW")


class Starting(Base):
    def test_start_runs_start_bat_without_a_browser_and_a_pause_and_only_on_windows(self):
        d = make_instai(os.path.join(self.desk, "Instai-main"))
        self.assertFalse(IJ.start_instai(d, popen=lambda *a, **k: self.fail("must not run off Windows")) if not IJ.IS_WIN else False)
        got = {}
        old = IJ.IS_WIN
        IJ.IS_WIN = True
        try:
            self.assertTrue(IJ.start_instai(d, popen=lambda cmd, **k: got.update(cmd=cmd, **k)))
        finally:
            IJ.IS_WIN = old
        self.assertEqual(got["cmd"], ["cmd", "/c", "START.bat"])
        self.assertEqual(got["cwd"], d)
        self.assertEqual(got["env"]["INSTAI_NO_BROWSER"], "1")
        self.assertEqual(got["env"]["INSTAI_NO_PAUSE"], "1")
        self.assertEqual(got["creationflags"] & 0x08000000, 0x08000000)

    def test_a_failing_popen_is_reported_not_raised(self):
        d = make_instai(os.path.join(self.desk, "Instai-main"))
        old = IJ.IS_WIN
        IJ.IS_WIN = True
        try:
            def boom(*a, **k):
                raise OSError("no cmd")
            self.assertFalse(IJ.start_instai(d, popen=boom))
        finally:
            IJ.IS_WIN = old


class Registering(Base):
    def test_the_report_rides_on_the_heartbeat_and_the_wrap_is_idempotent(self):
        calls = []

        class Caps:
            def probe(self):
                calls.append(1)
                return {"agent": "x"}

        agent = SimpleNamespace(Capabilities=Caps, warn=lambda m: None)
        IJ._SERVICE["svc"] = self.service()
        try:
            IJ.register(agent)
            IJ.register(agent)
            caps = Caps().probe()
            self.assertEqual(calls, [1], "wrapped once")
            self.assertEqual(caps["agent"], "x")
            self.assertIn("instai", caps)
            self.assertEqual(caps["instai"]["state"], "not_found")
            self.assertIn("message_fa", caps["instai"])
            self.assertIsNone(IJ._SERVICE["svc"].thread, "under the test runner the heartbeat never starts the real supervisor")
        finally:
            IJ._SERVICE["svc"] = None

    def test_the_markers_of_the_earlier_wrappers_survive(self):
        """abagram_jobs.py marks its wrap with _abagram_wrapped and its tests (and its own idempotence check) read that mark off agent.Capabilities.probe: this wrap sits on top."""
        class Caps:
            def probe(self):
                return {"agent": "x"}

        Caps.probe._abagram_wrapped = True
        agent = SimpleNamespace(Capabilities=Caps, warn=lambda m: None)
        IJ._SERVICE["svc"] = self.service()
        try:
            IJ.register(agent)
            self.assertTrue(getattr(Caps.probe, "_abagram_wrapped", False), "the Instagram reader's mark is still on the probe")
            self.assertTrue(getattr(Caps.probe, "_instai_wrapped", False))
            self.assertEqual(Caps.probe.__name__, "probe", "update_wrapper keeps the name")
        finally:
            IJ._SERVICE["svc"] = None

    def test_a_broken_report_never_stops_the_heartbeat(self):
        class Caps:
            def probe(self):
                return {"agent": "x"}

        warns = []
        agent = SimpleNamespace(Capabilities=Caps, warn=warns.append)
        with mock.patch.object(IJ, "get_service", side_effect=RuntimeError("boom")):
            IJ.register(agent)
            self.assertEqual(Caps().probe(), {"agent": "x"})
        self.assertTrue(warns)


if __name__ == "__main__":
    unittest.main(verbosity=1)
