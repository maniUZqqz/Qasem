"""motion_jobs.py (agent): the automatic, idempotent installer of the motion studio toolchain and the `motion.render` handler.

    python -m unittest tests/test_motion_jobs.py        (from the processing folder)

No network, no Windows, no GPU: downloads and the renderer are replaced by fakes (motion_jobs.HOOKS); the data folder is a temp dir.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
import motion_jobs as mj  # noqa: E402


class FakeAgent:
    def __init__(self, data, window_ok=True):
        self.DATA = data
        self.CONFIG = {"site": "https://site.example", "token": "t"}
        self.window_ok = window_ok
        self.logs = []

    def log(self, m, level="INFO"):
        self.logs.append(m)

    def warn(self, m):
        self.logs.append("WARN " + m)

    def download_allowed(self, now=None, window=None):
        return self.window_ok

    def seconds_until_window(self, now=None, window=None):
        return 0 if self.window_ok else 3600


class JobError(RuntimeError):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class FakeJob:
    def __init__(self, work, payload, uid="abc123"):
        self.uid, self.payload, self.timeout_s, self.cancelled = uid, payload, 600, False
        self.dir = os.path.join(work, uid)
        self.inputs = os.path.join(self.dir, "inputs")
        self.outputs = os.path.join(self.dir, "outputs")
        os.makedirs(self.inputs, exist_ok=True)
        os.makedirs(self.outputs, exist_ok=True)
        self.calls = []

    def out(self, name):
        return os.path.join(self.outputs, os.path.basename(name))

    def progress(self, fraction, message="", meta=None):
        self.calls.append((round(fraction, 3), message))


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


class Site:
    """The site's mirror folder + a fetch() that copies from it and counts."""

    def __init__(self, root, version="v1"):
        self.root = root
        self.calls = []
        self.fail = set()
        self.publish(version)

    def publish(self, version):
        make_zip(os.path.join(self.root, "node.zip"), {"node-v20-win-x64/node.exe": "NODE", "node-v20-win-x64/LICENSE": "MIT"})
        make_zip(os.path.join(self.root, "pack-%s.zip" % version), {"render.mjs": "// render " + version, "bundle/index.html": "<html>", "node_modules/x/index.js": "1"})
        make_zip(os.path.join(self.root, "chrome.zip"), {"chrome-headless-shell-win64/chrome-headless-shell.exe": "CHROME"})
        m = {"version": version,
             "pack": {"name": "pack-%s.zip" % version, "size": 1, "sha256": "x"},
             "node": {"name": "node.zip", "size": 1, "sha256": "n" + version},
             "browser": {"name": "chrome.zip", "size": 1, "sha256": "bb"}}
        with open(os.path.join(self.root, "nm-motion-pack.json"), "w") as fh:
            json.dump(m, fh)

    def fetch(self, name, dest, size, sha256):
        self.calls.append(name)
        if name in self.fail:
            raise mj.MotionError("fake download failure of " + name)
        shutil.copyfile(os.path.join(self.root, name), dest)
        return "downloaded"


class MotionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-motion-test-")
        self.data = os.path.join(self.tmp, "data")
        self.mirror = os.path.join(self.tmp, "mirror")
        os.makedirs(self.data)
        os.makedirs(self.mirror)
        self.agent = FakeAgent(self.data)
        self.site = Site(self.mirror)
        self.saved = (dict(mj.HOOKS), dict(mj._STATE), mj.IS_WIN, dict(mj._THREAD), mj._JOBS["n"], dict(mj._AGENT))
        mj.IS_WIN = True                   # so the fake zips' *.exe names are the ones looked for
        mj.HOOKS["fetch"] = self.site.fetch
        self.renders = []
        mj.HOOKS["run"] = self.fake_run
        mj._STATE.update({"state": "checking", "step": "", "progress": 0.0, "message": "", "error": "", "pack_version": "", "node": "", "browser": "", "gl": "", "tested_at": ""})
        mj._THREAD.update({"t": None, "busy": False})
        mj._JOBS["n"] = 0
        mj._AGENT["mod"] = self.agent
        self.gpu = False
        self._has_gpu = mj.has_gpu
        mj.has_gpu = lambda: self.gpu
        self.fail_gl = set()
        self.fail_color = set()

    def tearDown(self):
        mj.HOOKS.update(self.saved[0])
        mj._STATE.clear()
        mj._STATE.update(self.saved[1])
        mj.IS_WIN = self.saved[2]
        mj._THREAD.update(self.saved[3])
        mj._JOBS["n"] = self.saved[4]
        mj._AGENT.update(self.saved[5])
        mj.has_gpu = self._has_gpu
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_run(self, p, job_file, timeout, on_event=None, cancelled=None):
        with open(job_file, encoding="utf-8") as fh:
            job = json.load(fh)
        self.renders.append(job)
        if job.get("gl") in self.fail_gl:
            return {}, "gpu backend failed"
        if job.get("color_space") in self.fail_color:
            return {}, "zscale filter missing"
        if cancelled and cancelled():
            return {}, "cancelled"
        os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
        with open(job["out"], "wb") as fh:
            fh.write(b"X" * 2000)
        if on_event:
            on_event({"ev": "progress", "progress": 0.5, "rendered": 45, "total": 90})
            on_event({"ev": "progress", "progress": 1.0, "stage": "encoding", "rendered": 90, "total": 90})
        return {"ev": "done", "out": job["out"], "bytes": 2000, "width": 540, "height": 960, "fps": 30, "frames": 90}, ""


class ValidatePayload(MotionBase):
    def test_template_ok(self):
        out = mj.validate_payload({"composition": "Template", "props": {"spec": {"style": "x"}}, "scale": 0.5, "crf": 20, "title": "t", "render_id": 3})
        self.assertEqual(out["composition"], "Template")
        self.assertEqual(out["scale"], 0.5)
        self.assertLessEqual(out["max_seconds"], mj.MAX_SECONDS)

    def test_unknown_key_rejected_not_retryable(self):
        with self.assertRaises(mj.MotionError) as cm:
            mj.validate_payload({"composition": "Template", "props": {}, "cmd": "calc.exe"})
        self.assertFalse(cm.exception.retryable)

    def test_bad_values(self):
        for bad in ({"composition": "Evil"}, {"composition": "Template", "props": []}, {"scale": 3}, {"scale": 0.01}, {"crf": 3}, {"scale": "x"}, "nope"):
            with self.assertRaises(mj.MotionError):
                mj.validate_payload(bad)

    def test_user_code_needs_factory_and_size(self):
        with self.assertRaises(mj.MotionError):
            mj.validate_payload({"composition": "User", "user_js": "alert(1)"})
        with self.assertRaises(mj.MotionError):
            mj.validate_payload({"composition": "User", "user_js": "window.__NM_USER_FACTORY=1;" + "x" * mj.MAX_USER_JS})
        ok = mj.validate_payload({"composition": "User", "user_js": "window.__NM_USER_FACTORY=function(){};"})
        self.assertIn("user_js", ok)

    def test_still(self):
        self.assertEqual(mj.validate_payload({"composition": "Template", "props": {}, "still": 5})["still"], 5)


class Installer(MotionBase):
    def test_first_install_then_idempotent(self):
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready", st)
        self.assertEqual(sorted(self.site.calls), sorted(["nm-motion-pack.json", "node.zip", "pack-v1.zip", "chrome.zip"]))
        p = mj.paths(self.agent)
        self.assertTrue(os.path.isfile(p["node"]))                  # flattened: node/node.exe (not node/node-v20-win-x64/node.exe)
        self.assertTrue(os.path.isfile(p["render"]))
        self.assertTrue(os.path.isdir(p["bundle"]))
        self.assertEqual(st["gl"], "swangle")
        self.assertEqual(len(self.renders), 2)                       # the smoke test: ONE small still (GL) + ONE small real video (encoder)
        self.assertTrue(self.renders[0]["still"] >= 0 and self.renders[0]["scale"] <= 0.5)
        self.assertNotIn("still", self.renders[1])
        self.site.calls.clear()
        self.renders.clear()
        again = mj.install(self.agent)                               # a node that is ready only re-reads the manifest
        self.assertEqual(again["state"], "ready")
        self.assertEqual(self.site.calls, ["nm-motion-pack.json"])
        self.assertEqual(self.renders, [])

    def test_survives_a_restart_without_downloading_again(self):
        mj.install(self.agent)
        self.site.calls.clear()
        mj._STATE.update({"state": "checking", "pack_version": ""})   # new process: nothing in memory
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready")
        self.assertEqual(self.site.calls, ["nm-motion-pack.json"], "node, pack and browser are already there (markers match)")

    def test_new_package_is_fetched_only_when_the_site_publishes_it(self):
        mj.install(self.agent)
        self.site.calls.clear()
        self.site.publish("v2")
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready")
        self.assertEqual(st["pack_version"], "v2")
        self.assertIn("pack-v2.zip", self.site.calls)
        self.assertNotIn("chrome.zip", self.site.calls)              # the browser did not change

    def test_browser_download_failure_falls_back_to_edge(self):
        edge = os.path.join(self.tmp, "msedge.exe")
        open(edge, "w").close()
        self.site.fail.add("chrome.zip")
        orig = mj.edge_path
        mj.edge_path = lambda: edge
        try:
            st = mj.install(self.agent)
        finally:
            mj.edge_path = orig
        self.assertEqual(st["state"], "ready", st)
        self.assertEqual(st["browser"], edge)
        self.assertEqual(st["chrome_mode"], "chrome-for-testing")

    def test_failure_is_reported_in_persian_and_retried_later(self):
        self.site.fail.add("pack-v1.zip")
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "failed")
        self.assertIn("pack-v1.zip", st["error"])
        self.site.fail.clear()
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready")

    def test_small_downloads_never_wait_for_the_night_window(self):
        """The whole pack is ~170 MB: like bootstrap.py, only >= 200 MB items wait for the window. A queued render is never claimed by a node
        that is not ready, so the installer must start by itself (the owner: «turn the node on and it works»)."""
        self.agent.window_ok = False
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready", st)

    def test_a_big_package_waits_for_the_download_window_unless_somebody_waits(self):
        self.agent.window_ok = False
        mp = os.path.join(self.mirror, "nm-motion-pack.json")
        with open(mp) as fh:
            m = json.load(fh)
        m["browser"]["size"] = 300 << 20
        with open(mp, "w") as fh:
            json.dump(m, fh)
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "waiting")
        self.assertEqual(self.site.calls, ["nm-motion-pack.json"])        # only the tiny manifest was read
        st = mj.install(self.agent, exempt=True)
        self.assertEqual(st["state"], "ready")

    def test_gpu_backend_is_tried_first_then_software(self):
        self.gpu = True
        self.fail_gl = {"angle"}
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready")
        self.assertEqual(st["gl"], "swangle")
        self.assertEqual([r["gl"] for r in self.renders if "still" in r], ["angle", "swangle"])
        mj._STATE.update({"state": "checking", "pack_version": "", "tested_at": ""})
        self.fail_gl = set()
        self.renders.clear()
        st = mj.install(self.agent)
        self.assertEqual(st["gl"], "angle")
        self.assertTrue(st["gpu"])

    def test_the_encoder_is_proven_with_real_video_and_falls_back_on_colour_handling(self):
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "ready")
        self.assertEqual(st["color_space"], "bt709")
        videos = [r for r in self.renders if str(r["out"]).endswith(".mp4")]
        self.assertEqual(len(videos), 1)
        self.assertTrue(videos[0]["scale"] <= 0.5 and "still" not in videos[0])
        mj._STATE.update({"state": "checking", "pack_version": "", "tested_at": ""})
        self.fail_color = {"bt709"}
        st = mj.install(self.agent)
        self.assertEqual((st["state"], st["color_space"]), ("ready", "default"))

    def test_an_encoder_that_cannot_encode_fails_the_install_with_a_reason(self):
        self.fail_color = {"bt709", "default"}
        st = mj.install(self.agent)
        self.assertEqual(st["state"], "failed")
        self.assertIn("کدگذاری", st["error"])

    def test_zip_slip_is_refused(self):
        bad = os.path.join(self.tmp, "bad.zip")
        make_zip(bad, {"../evil.txt": "x"})
        with self.assertRaises(mj.MotionError):
            mj._safe_extract(bad, os.path.join(self.tmp, "out"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))

    def test_no_install_while_a_render_runs(self):
        mj.install(self.agent)
        self.site.publish("v2")
        self.site.calls.clear()
        mj._JOBS["n"] = 1
        st = mj.install(self.agent)
        self.assertEqual(st["pack_version"], "v1")
        self.assertEqual(self.site.calls, [])


class Caps(MotionBase):
    def test_disabled(self):
        os.environ["NM_MOTION"] = "0"
        try:
            c = mj.caps(self.agent)
        finally:
            del os.environ["NM_MOTION"]
        self.assertFalse(c["motion_render"])
        self.assertEqual(c["motion"]["state"], "disabled")

    def test_caps_start_the_installer_once(self):
        started = []
        orig = mj.start_background
        mj.start_background = lambda agent=None: started.append(1) or mj._THREAD.update({"t": object()})
        try:
            c1 = mj.caps(self.agent)
            c2 = mj.caps(self.agent)
        finally:
            mj.start_background = orig
        self.assertTrue(c1["motion_render"])
        self.assertEqual(c1["motion"]["state"], "checking")
        self.assertEqual(len(started), 1)
        self.assertIn("progress", c2["motion"])

    def test_register(self):
        handlers = {}
        mj.register(handlers, self.agent)
        self.assertIn("motion.render", handlers)

    def test_register_puts_the_feature_into_every_heartbeat_once(self):
        """agent.py makes ONE call; the heartbeat keys come from a wrapper around Capabilities.probe (like multiangle_jobs.py)."""
        class Capabilities:
            def probe(self):
                self.cache = {"agent": "2.99", "kinds": ["echo"]}
                return self.cache

        agent = FakeAgent(self.data)
        agent.Capabilities = Capabilities
        started = []
        orig = mj.start_background
        mj.start_background = lambda a=None: started.append(1) or mj._THREAD.update({"t": object()})
        try:
            handlers = {}
            mj.register(handlers, agent)
            mj.register(handlers, agent)                                    # a second call must not wrap twice
            c = Capabilities()
            out = c.probe()
            same = out is c.cache                                           # the agent hashes cache: the wrapper changes that same dict
            out2 = c.probe()
        finally:
            mj.start_background = orig
        self.assertTrue(out["motion_render"])
        self.assertIn("state", out["motion"])
        self.assertEqual(out["agent"], "2.99")
        self.assertTrue(same)
        self.assertEqual(len(started), 1)
        self.assertTrue(out2["motion_render"])


class Run(MotionBase):
    def setUp(self):
        super().setUp()
        self.agent.JobError = JobError
        self.work = os.path.join(self.tmp, "work")

    def job(self, **payload):
        base = {"composition": "Template", "props": {"spec": {"style": "flat-vector"}}, "scale": 0.5}
        base.update(payload)
        return FakeJob(self.work, base)

    def test_render_happy_path_installs_first_and_answers_out_mp4(self):
        j = self.job()
        meta = mj.run(j, self.agent)
        self.assertEqual(meta["primary"], "out.mp4")
        self.assertTrue(os.path.isfile(j.out("out.mp4")))
        self.assertTrue(os.path.isfile(j.out("motion-render.json")))
        self.assertEqual(meta["frames"], 90)
        self.assertEqual(meta["device"], "cpu", "no usable video card in this fake => the self-test must be able to tell")
        self.assertIn("software", meta["device_note"])
        self.assertTrue(any("کارتِ گرافیک" in m or "کدگذاری" in m for _p, m in j.calls))
        self.assertTrue(all(0 <= p <= 0.98 for p, _m in j.calls))
        job_json = self.renders[-1]
        self.assertEqual(job_json["assets_dir"], j.inputs)
        self.assertTrue(job_json["offline"])                           # nothing but localhost
        self.assertEqual(job_json["composition"], "Template")
        self.assertEqual(job_json["color_space"], "bt709", "a standard yuv420p TV-range file")
        self.assertFalse(os.path.isdir(os.path.join(mj.paths(self.agent)["jobs"], j.uid)), "the job's scratch folder is cleaned")

    def test_user_code_is_written_to_a_file_not_inlined(self):
        j = self.job(composition="User", props={}, user_js="window.__NM_USER_FACTORY=function(){};")
        mj.run(j, self.agent)
        spec = self.renders[-1]
        self.assertEqual(spec["composition"], "User")
        self.assertTrue(spec["user_js"].endswith("user.js"))

    def test_gpu_failure_retries_on_software(self):
        mj.install(self.agent)
        mj._STATE["gl"] = "angle"
        self.fail_gl = {"angle"}
        self.renders.clear()
        j = self.job()
        meta = mj.run(j, self.agent)
        self.assertEqual(meta["gl"], "swangle")
        self.assertEqual([r["gl"] for r in self.renders], ["angle", "swangle"])
        self.assertEqual(meta["device"], "cpu")

    def test_gpu_render_reports_the_card(self):
        mj.install(self.agent)
        mj._STATE["gl"] = "angle"
        meta = mj.run(self.job(), self.agent)
        self.assertEqual((meta["gl"], meta["device"]), ("angle", "gpu"))
        with open(self.job().out("motion-render.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["device"], "gpu")

    def test_invalid_payload_is_a_final_error(self):
        j = self.job(cmd="calc")
        with self.assertRaises(JobError) as cm:
            mj.run(j, self.agent)
        self.assertFalse(cm.exception.retryable)

    def test_install_failure_makes_the_job_fail_with_a_reason(self):
        self.site.fail.add("node.zip")
        with self.assertRaises(JobError) as cm:
            mj.run(self.job(), self.agent)
        self.assertIn("node.zip", str(cm.exception))

    def test_cancel(self):
        mj.install(self.agent)
        j = self.job()
        j.cancelled = True
        with self.assertRaises(JobError) as cm:
            mj.run(j, self.agent)
        self.assertFalse(cm.exception.retryable)

    def test_still(self):
        j = self.job(still=12)
        meta = mj.run(j, self.agent)
        self.assertEqual(meta["primary"], "out.png")


if __name__ == "__main__":
    unittest.main()
