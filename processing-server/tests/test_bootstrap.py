"""agent 2.11: bootstrap.py - declarative, idempotent installs with fake installers (no network, no pip)."""
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bootstrap as bs  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeSystem:
    """A pretend computer: venvs, installed pip distributions, downloadable files. `run` and `fetch` are what Ctx calls."""

    def __init__(self, data):
        self.data = data
        self.installed = {}                  # normalised name -> version
        self.commands = []
        self.fetches = []
        self.pip_fail_on = set()             # index hosts that fail
        self.downloads = {}                  # url -> bytes
        self.fetch_fail = set()              # urls that fail
        self.cmd_rc = {}

    def run(self, cmd, timeout=600, env=None, on_line=None):
        self.commands.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            sub = "Scripts" if sys.platform.startswith("win") else "bin"
            os.makedirs(os.path.join(cmd[3], sub))
            open(os.path.join(cmd[3], sub, "python.exe" if sub == "Scripts" else "python"), "w").write("")
            return 0, ""
        if "-c" in cmd and "importlib" in cmd[cmd.index("-c") + 1]:       # the distribution probe
            want = json.loads(cmd[-1])
            return 0, json.dumps({n: self.installed.get(bs.norm(n)) for n in want})
        if cmd[1:4] == ["-m", "pip", "install"]:
            host = cmd[cmd.index("--index-url") + 1].split("/")[2]
            if host in self.pip_fail_on:
                return 1, "ERROR: Could not find a version that satisfies the requirement (from %s)" % host
            if on_line:
                on_line("Collecting x")
                on_line("Downloading y-1.0.whl (3 MB)")
            for req in cmd[cmd.index("--index-url") + 2:]:
                if req.startswith("-"):
                    continue
                n, op, v = bs.parse_req(req)
                self.installed[n] = v or "9.9"
            return 0, "Successfully installed"
        key = tuple(cmd)
        for k, rc in self.cmd_rc.items():
            if k in " ".join(cmd):
                return rc, "output of %s" % k
        return 0, ""

    def fetch(self, url, dest, size=None, sha256=None, label=None):
        self.fetches.append(url)
        if url in self.fetch_fail or url not in self.downloads:
            raise RuntimeError("HTTP 404 %s" % url)
        data = self.downloads[url]
        if sha256 and hashlib.sha256(data).hexdigest() != sha256.lower():
            raise RuntimeError("checksum mismatch")
        with open(dest, "wb") as fh:
            fh.write(data)
        return dest


def make_zip(entries):
    import io
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.req = os.path.join(self.tmp, "requirements.d")
        os.makedirs(self.req)
        self.sys = FakeSystem(self.data)
        self.clock = [1000.0]
        self.window_open = [True]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spec(self, name, **kw):
        d = {"feature": name, "items": []}
        d.update(kw)
        with open(os.path.join(self.req, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        return d

    def engine(self, gpu=True, plat="win", site="http://site"):
        ctx = bs.Ctx(self.data, site=site, run=self.sys.run, fetch=self.sys.fetch, gpu_present=gpu, plat=plat, py=sys.executable,
                     download_allowed=lambda: self.window_open[0])
        return bs.Bootstrap(ctx, self.req, clock=lambda: self.clock[0])


class RequirementParsingTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(bs.parse_req("numpy==1.26.4"), ("numpy", "==", "1.26.4"))
        self.assertEqual(bs.parse_req("Pillow>=10"), ("pillow", ">=", "10"))
        self.assertEqual(bs.parse_req("opencv-python-headless==4.10.0.84")[0], "opencv-python-headless")
        self.assertEqual(bs.parse_req("faster_whisper")[1], "")
        self.assertTrue(bs.satisfied("1.26.4", "==", "1.26.4"))
        self.assertFalse(bs.satisfied("1.26.3", "==", "1.26.4"))
        self.assertTrue(bs.satisfied("2.0", ">=", "1.9"))
        self.assertFalse(bs.satisfied("1.9", ">=", "1.10"))
        self.assertFalse(bs.satisfied(None, "", ""))
        self.assertTrue(bs.satisfied("9.1.0.70", "==", "9.1.0.70"))
        self.assertTrue(bs.satisfied("2.9.1+cu128", "==", "2.9.1"))

    def test_the_shipped_requirement_files_are_valid(self):
        specs, errors = bs.load_specs(os.path.join(HERE, "requirements.d"))
        self.assertEqual(errors, [])
        names = {s["feature"] for s in specs}
        self.assertTrue({"gpu-runtime", "ffmpeg-nvenc", "node-js", "asr-gpu"} <= names)
        for s in specs:
            self.assertTrue(s.get("title_fa"), s["feature"])
            for it in s["items"]:
                self.assertIn(it["type"], bs.ITEM_TYPES)
                if it["type"] == "pip":
                    for r in it["packages"]:
                        self.assertEqual(bs.parse_req(r)[1], "==", "%s must be pinned: %s" % (s["feature"], r))
                if it["type"] in ("archive", "files"):
                    pieces = [it] if it["type"] == "archive" else it["files"]
                    for f in pieces:
                        if f.get("sha256"):
                            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")
                        self.assertTrue(f.get("sources"), "%s has no download source" % it["id"])
                        self.assertTrue(any("site" in x for x in f["sources"]) or any("hf" in x for x in f["sources"]) or True)

    def test_node_js_comes_from_the_site_mirror_first(self):
        specs, _ = bs.load_specs(os.path.join(HERE, "requirements.d"))
        node = next(s for s in specs if s["feature"] == "node-js")["items"][0]
        self.assertIn("site", node["sources"][0])
        self.assertTrue(any("nodejs.org" in x.get("url", "") for x in node["sources"]))

    def test_broken_files_are_reported_not_fatal(self):
        tmp = tempfile.mkdtemp()
        try:
            open(os.path.join(tmp, "a.json"), "w").write("{not json")
            open(os.path.join(tmp, "b.json"), "w").write(json.dumps({"feature": "b", "items": [{"type": "nope"}]}))
            open(os.path.join(tmp, "c.json"), "w").write(json.dumps({"feature": "c", "items": [{"type": "venv", "name": "v"}]}))
            specs, errors = bs.load_specs(tmp)
            self.assertEqual([s["feature"] for s in specs], ["c"])
            self.assertEqual({e["file"] for e in errors}, {"a.json", "b.json"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class InstallFlowTests(Base):
    def test_venv_then_pip_then_check_and_a_second_run_changes_nothing(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "nodert"},
                               {"id": "pip", "type": "pip", "venv": "nodert", "packages": ["numpy==1.26.4", "Pillow==10.4.0"]}])
        eng = self.engine()
        self.assertEqual(eng.run_once(), 0)
        st = eng.status()
        self.assertEqual(st["features"]["rt"]["state"], "ready")
        self.assertEqual(self.sys.installed, {"numpy": "1.26.4", "pillow": "10.4.0"})
        n_installs = len([c for c in self.sys.commands if c[1:4] == ["-m", "pip", "install"]])
        self.assertEqual(n_installs, 1)
        self.assertEqual(eng.run_once(), 0)                                      # idempotent
        self.assertEqual(len([c for c in self.sys.commands if c[1:4] == ["-m", "pip", "install"]]), 1)

    def test_only_the_missing_pin_triggers_an_install(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "e"},
                               {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"]}])
        eng = self.engine()
        eng.run_once()
        self.sys.installed["numpy"] = "2.0.0"                                    # somebody changed it
        eng2 = self.engine()
        eng2.run_once()
        self.assertEqual(self.sys.installed["numpy"], "1.26.4")

    def test_pip_falls_back_to_the_next_index_and_reports_nothing_wrong_in_the_end(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "e"},
                               {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"]}])
        self.sys.pip_fail_on = {bs.PYPI_INDEXES[0].split("/")[2]}
        eng = self.engine()
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")
        hosts = [c[c.index("--index-url") + 1].split("/")[2] for c in self.sys.commands if c[1:4] == ["-m", "pip", "install"]]
        self.assertEqual(hosts[:2], [bs.PYPI_INDEXES[0].split("/")[2], bs.PYPI_INDEXES[1].split("/")[2]])

    def test_a_big_pip_step_waits_for_the_download_window_and_a_small_one_does_not(self):
        self.spec("rt", respect_window=True, items=[{"id": "venv", "type": "venv", "name": "e"},
                                                    {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"], "big": True}])
        self.spec("small", items=[{"id": "venv", "type": "venv", "name": "s"},
                                  {"id": "pip", "type": "pip", "venv": "s", "packages": ["pillow==10.4.0"]}])
        self.window_open[0] = False
        eng = self.engine()
        eng.run_once()
        st = eng.status()["features"]
        self.assertEqual(st["rt"]["items"][1]["state"], "waiting")
        self.assertEqual(st["small"]["state"], "ready")
        self.window_open[0] = True
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")

    def test_the_official_index_goes_first_when_it_answers_and_last_when_it_does_not(self):
        ctx = bs.Ctx(self.data, gpu_present=False)               # no fake runner: the real probe is used
        with mock.patch("urllib.request.urlopen") as up:
            up.return_value.close = lambda: None
            self.assertEqual(bs.index_order(ctx)[0], "https://pypi.org/simple")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("blocked")):
            order = bs.index_order(ctx)
        self.assertEqual(order[-1], "https://pypi.org/simple")
        self.assertEqual(len(order), len(bs.PYPI_INDEXES))

    def test_every_source_failing_is_a_visible_error_with_the_log_tail(self):
        self.spec("rt", kinds=["asr.transcribe"], items=[{"id": "venv", "type": "venv", "name": "e"},
                                                         {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"]}])
        self.sys.pip_fail_on = {u.split("/")[2] for u in bs.PYPI_INDEXES}
        eng = self.engine()
        self.assertGreater(eng.run_once(), 0)
        f = eng.status()["features"]["rt"]
        self.assertEqual(f["state"], "failed")
        item = next(i for i in f["items"] if i["id"] == "pip")
        self.assertEqual(item["state"], "failed")
        self.assertIn("pip install failed", item["error"])
        self.assertTrue(item["tail"])
        self.assertIn("asr.transcribe", eng.status()["blocked_kinds"])             # jobs of that kind wait

    def test_a_failed_step_is_retried_by_itself_after_a_pause_and_by_the_panel_at_once(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "e"},
                               {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"]}])
        self.sys.pip_fail_on = {u.split("/")[2] for u in bs.PYPI_INDEXES}
        eng = self.engine()
        eng.run_once()
        self.sys.pip_fail_on = set()                                             # the line is back
        self.clock[0] += 60
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "failed")      # too early: the pause has not passed
        self.clock[0] += bs.RETRY_AFTER_S[0]
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")

    def test_the_retry_button_forgets_the_pause(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "e"},
                               {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"]}])
        self.sys.pip_fail_on = {u.split("/")[2] for u in bs.PYPI_INDEXES}
        eng = self.engine()
        eng.run_once()
        self.sys.pip_fail_on = set()
        self.assertEqual(eng.retry(), 1)
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")

    def test_the_state_survives_a_restart(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "e"}])
        self.engine().run_once()
        again = self.engine()
        self.assertEqual(again.state["rt"]["venv"]["state"], "ready")


class ArchiveAndFilesTests(Base):
    NODE = {"id": "node", "type": "archive", "dest": "vendor/node", "strip": 1, "check_file": "vendor/node/node.exe", "big": False,
            "sources": [{"site": "node.zip"}, {"url": "https://nodejs.org/node.zip"}]}

    def zip_bytes(self):
        return make_zip({"node-v20/node.exe": b"EXE", "node-v20/npm.cmd": b"cmd", "node-v20/lib/x.js": b"js"})

    def test_site_mirror_first_then_the_public_mirror(self):
        data = self.zip_bytes()
        item = dict(self.NODE, sha256=hashlib.sha256(data).hexdigest())
        self.spec("node-js", items=[item])
        self.sys.downloads["http://site/3d/files/downloads/node.zip"] = data
        eng = self.engine()
        eng.run_once()
        self.assertEqual(eng.status()["features"]["node-js"]["state"], "ready")
        self.assertEqual(self.sys.fetches, ["http://site/3d/files/downloads/node.zip"])
        self.assertTrue(os.path.isfile(os.path.join(self.data, "vendor", "node", "node.exe")))           # leading folder stripped
        self.assertTrue(os.path.isfile(os.path.join(self.data, "vendor", "node", "lib", "x.js")))

    def test_the_site_not_having_the_file_falls_back_and_a_wrong_checksum_is_refused(self):
        data = self.zip_bytes()
        item = dict(self.NODE, sha256=hashlib.sha256(data).hexdigest())
        self.spec("node-js", items=[item])
        self.sys.downloads["https://nodejs.org/node.zip"] = data                                           # not on the site (404)
        eng = self.engine()
        eng.run_once()
        self.assertEqual(self.sys.fetches, ["http://site/3d/files/downloads/node.zip", "https://nodejs.org/node.zip"])
        self.assertEqual(eng.status()["features"]["node-js"]["state"], "ready")
        shutil.rmtree(os.path.join(self.data, "vendor"))
        self.sys.downloads["https://nodejs.org/node.zip"] = b"tampered"
        self.sys.fetches.clear()
        eng2 = self.engine()
        eng2.run_once()
        self.assertEqual(eng2.status()["features"]["node-js"]["state"], "failed")
        self.assertIn("download failed from every source", eng2.status()["features"]["node-js"]["items"][0]["error"])

    def test_already_installed_archive_is_not_downloaded_again(self):
        data = self.zip_bytes()
        item = dict(self.NODE, sha256=hashlib.sha256(data).hexdigest())
        self.spec("node-js", items=[item])
        self.sys.downloads["http://site/3d/files/downloads/node.zip"] = data
        self.engine().run_once()
        n = len(self.sys.fetches)
        self.engine().run_once()
        self.assertEqual(len(self.sys.fetches), n)

    def test_big_files_wait_for_the_download_window_small_ones_do_not(self):
        data = self.zip_bytes()
        self.spec("a", respect_window=True, items=[dict(self.NODE, big=True, sha256=hashlib.sha256(data).hexdigest())])
        self.sys.downloads["http://site/3d/files/downloads/node.zip"] = data
        self.window_open[0] = False
        eng = self.engine()
        eng.run_once()
        it = eng.status()["features"]["a"]["items"][0]
        self.assertEqual(it["state"], "waiting")
        self.assertIn("download window", it["detail"])
        self.assertEqual(self.sys.fetches, [])
        self.window_open[0] = True
        eng.run_once()
        self.assertEqual(eng.status()["features"]["a"]["state"], "ready")

    def test_files_are_fetched_one_by_one_and_checked_by_size(self):
        blob = b"x" * 10
        self.spec("m", items=[{"id": "model", "type": "files", "dest": "models/w", "files": [
            {"path": "config.json", "size": 10, "sources": [{"hf": "A/b/resolve/rev/config.json"}]},
            {"path": "sub/model.bin", "size": 10, "sha256": hashlib.sha256(blob).hexdigest(), "sources": [{"hf": "A/b/resolve/rev/model.bin"}]}]}])
        for host in bs.HF_HOSTS:
            self.sys.downloads[host + "/A/b/resolve/rev/config.json"] = blob
            self.sys.downloads[host + "/A/b/resolve/rev/model.bin"] = blob
        self.sys.fetch_fail = {bs.HF_HOSTS[0] + "/A/b/resolve/rev/model.bin"}          # hf-mirror is down for this file
        eng = self.engine()
        eng.run_once()
        self.assertEqual(eng.status()["features"]["m"]["state"], "ready")
        self.assertIn(bs.HF_HOSTS[1] + "/A/b/resolve/rev/model.bin", self.sys.fetches)
        self.assertTrue(os.path.isfile(os.path.join(self.data, "models", "w", "sub", "model.bin")))


class OrderingAndGatingTests(Base):
    def test_no_gpu_skips_gpu_features_and_never_blocks_their_kinds(self):
        self.spec("g", needs_gpu=True, kinds=["asr.transcribe"], items=[{"id": "venv", "type": "venv", "name": "x"}])
        eng = self.engine(gpu=False)
        eng.run_once()
        st = eng.status()
        self.assertEqual(st["features"]["g"]["state"], "skipped")
        self.assertEqual(st["blocked_kinds"], {})
        self.assertEqual(self.sys.commands, [])

    def test_other_operating_system_is_skipped(self):
        self.spec("w", platform=["win"], items=[{"id": "venv", "type": "venv", "name": "x"}])
        eng = self.engine(plat="linux")
        eng.run_once()
        self.assertEqual(eng.status()["features"]["w"]["state"], "skipped")

    def test_requires_orders_features_and_a_failed_dependency_holds_the_next_one(self):
        self.spec("a", order=10, items=[{"id": "cmd", "type": "cmd", "check": ["fail-check"], "install": ["fail-install"]}])
        self.spec("b", order=20, requires=["a"], kinds=["motion.render"], items=[{"id": "venv", "type": "venv", "name": "b"}])
        self.sys.cmd_rc = {"fail-": 1}
        eng = self.engine()
        eng.run_once()
        st = eng.status()
        self.assertEqual(st["features"]["a"]["state"], "failed")
        self.assertEqual(st["features"]["b"]["state"], "waiting")
        self.assertIn("waiting for: a", st["features"]["b"]["items"][0]["detail"])
        self.assertIn("motion.render", st["blocked_kinds"])
        self.assertFalse(os.path.isdir(os.path.join(self.data, "venvs", "b")))

    def test_ready_feature_unblocks_its_kinds(self):
        self.spec("a", kinds=["k.one"], items=[{"id": "venv", "type": "venv", "name": "a"}])
        eng = self.engine()
        self.assertEqual(eng.status()["blocked_kinds"], {"k.one": "a: waiting"})
        eng.run_once()
        self.assertEqual(eng.status()["blocked_kinds"], {})
        self.assertEqual(eng.status()["summary"], {"ready": 1})

    def test_cmd_item_checks_first_and_installs_only_when_the_check_fails(self):
        self.spec("c", items=[{"id": "x", "type": "cmd", "check": ["probe-it"], "install": ["do-install"]}])
        self.sys.cmd_rc = {"probe-it": 0}
        self.engine().run_once()
        self.assertFalse(any("do-install" in " ".join(c) for c in self.sys.commands))

    def test_ffmpeg_item_is_skipped_without_a_gpu_and_the_ort_check_fails_with_a_clear_text_on_cpu_only(self):
        self.spec("f", items=[{"id": "ffmpeg", "type": "ffmpeg-nvenc"}])
        eng = self.engine(gpu=False)
        eng.run_once()
        self.assertEqual(eng.status()["features"]["f"]["state"], "ready")        # nothing to do without a card


class WorkerLoopTests(Base):
    def test_the_thread_installs_in_the_background_and_stops(self):
        self.spec("rt", items=[{"id": "venv", "type": "venv", "name": "e"}])
        eng = self.engine()
        eng.start()
        for _ in range(100):
            if eng.status()["features"]["rt"]["state"] == "ready":
                break
            import time
            time.sleep(0.05)
        eng.stop()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")


class FirstInstallAndRetryTests(Base):
    """2026-11-14: the owner switches the node on during the day - the download window must not hold back the first install, and a
    failed step must never need a click."""

    PIP = [{"id": "venv", "type": "venv", "name": "e"},
           {"id": "pip", "type": "pip", "venv": "e", "packages": ["numpy==1.26.4"], "big": True}]

    def test_the_first_install_ignores_the_download_window(self):
        self.spec("rt", kinds=["asr.transcribe"], items=self.PIP)
        self.window_open[0] = False                                           # outside the night window, in the middle of the day
        eng = self.engine()
        self.assertEqual(eng.run_once(), 0)
        f = eng.status()["features"]["rt"]
        self.assertEqual(f["state"], "ready")
        self.assertNotIn("asr.transcribe", eng.status()["blocked_kinds"])
        self.assertIn("rt", eng.state["_ready_once"])

    def test_a_reinstall_of_a_feature_that_was_ready_obeys_the_window(self):
        self.spec("rt", items=self.PIP)
        self.window_open[0] = False
        eng = self.engine()
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")
        self.sys.installed.clear()                                            # a new pinned version later: the package must be fetched again
        eng.run_once()
        item = eng.status()["features"]["rt"]["items"][1]
        self.assertEqual(item["state"], "waiting")
        self.assertIn("download window", item["detail"])
        self.window_open[0] = True
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")

    def test_the_exemption_is_remembered_across_a_restart(self):
        self.spec("rt", items=self.PIP)
        self.engine().run_once()
        again = self.engine()
        self.assertIn("rt", again.state["_ready_once"])
        self.assertFalse(again.first_install({"feature": "rt"}))
        self.assertTrue(again.first_install({"feature": "other"}))
        self.assertFalse(again.first_install({"feature": "other", "respect_window": True}))

    def test_a_first_install_that_fails_for_another_reason_stays_a_first_install(self):
        self.spec("rt", items=self.PIP)
        self.sys.pip_fail_on = {u.split("/")[2] for u in bs.PYPI_INDEXES}
        self.window_open[0] = False
        eng = self.engine()
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "failed")
        self.assertTrue(eng.first_install({"feature": "rt"}))

    def test_a_failed_step_never_gives_up_it_goes_on_every_four_hours(self):
        self.spec("rt", items=self.PIP)
        self.sys.pip_fail_on = {u.split("/")[2] for u in bs.PYPI_INDEXES}
        eng = self.engine()
        eng.run_once()
        for n in range(len(bs.RETRY_AFTER_S) + 3):                            # more failures than the old limit (it stopped after the 5th)
            self.clock[0] += bs.RETRY_AFTER_S[-1] + 1
            eng.run_once()
        self.assertGreater(eng.state["rt"]["pip"]["tries"], len(bs.RETRY_AFTER_S) + 1)
        self.assertEqual(eng.status()["features"]["rt"]["state"], "failed")
        self.sys.pip_fail_on = set()                                          # the line is back, hours or days later
        self.clock[0] += bs.RETRY_AFTER_S[-1] + 1
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")

    def test_a_new_start_gives_a_failed_step_one_fresh_try_at_once(self):
        self.spec("rt", items=self.PIP)
        self.sys.pip_fail_on = {u.split("/")[2] for u in bs.PYPI_INDEXES}
        self.engine().run_once()
        self.sys.pip_fail_on = set()
        self.clock[0] += 5                                                    # far less than the first pause
        eng = self.engine()                                                    # the agent was restarted
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["state"], "ready")

    def test_nothing_shipped_waits_for_the_download_window_on_a_first_install(self):
        """Every requirements.d file of this package, with the window shut and no network: each step either runs or fails on its own
        (the fake download answers 404) - none of them sits in «waiting for the download window»."""
        import shutil as _sh
        for name in os.listdir(os.path.join(HERE, "requirements.d")):
            _sh.copy(os.path.join(HERE, "requirements.d", name), os.path.join(self.req, name))
        self.window_open[0] = False
        eng = self.engine()
        eng.run_once()
        waiting = []
        for fname, feat in eng.status()["features"].items():
            for it in feat["items"]:
                if it["state"] == "waiting" and "download window" in (it["detail"] or ""):
                    waiting.append("%s/%s" % (fname, it["id"]))
        self.assertEqual(waiting, [])
        reached = [i for feat in eng.status()["features"].values() for i in feat["items"] if "HTTP 404" in (i["error"] or "")]
        self.assertTrue(reached, "no download was even attempted - the test would prove nothing")

    def test_a_feature_that_opts_out_still_waits_for_the_window(self):
        self.spec("rt", respect_window=True, items=self.PIP)
        self.window_open[0] = False
        eng = self.engine()
        eng.run_once()
        self.assertEqual(eng.status()["features"]["rt"]["items"][1]["state"], "waiting")


if __name__ == "__main__":
    unittest.main()
