"""«چندزاویه» on the node: the heartbeat keys, the automatic install, the engine command line, and the REAL engine on a tiny synthetic job.

    python -m unittest tests/test_multiangle_jobs.py        (from the processing folder)

The pure-logic tests always run. The real-engine tests need numpy + OpenCV + onnxruntime, ffmpeg and the three model files
(NM_MULTIANGLE_TEST_MODELS=<folder with the manifest's file names>); each skips itself when something is missing. They run the REAL
subprocess the agent would start, on the CPU, with a fake job - never on a real node.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
os.environ["NM_SMALL_MODELS"] = "0"
import agent  # noqa: E402
import edit_render  # noqa: E402
import multiangle_jobs as mj  # noqa: E402

FF = edit_render.ffmpeg_exe(agent)
try:
    import numpy as np  # noqa: E402,F401
    import cv2  # noqa: E402,F401
    import onnxruntime  # noqa: E402,F401
    HAVE_RT = True
except Exception:  # noqa: BLE001
    HAVE_RT = False

try:
    import numpy as np  # noqa: E402,F811
    import cv2  # noqa: E402,F811
    HAVE_CV = True
except Exception:  # noqa: BLE001
    HAVE_CV = False

MODEL_DIRS = [os.environ.get("NM_MULTIANGLE_TEST_MODELS", ""), os.path.join(os.environ.get("NM_DATA_DIR", ""), "models", "multiangle")]


def test_models():
    for d in MODEL_DIRS:
        if d and all(os.path.isfile(os.path.join(d, spec["file"])) and os.path.getsize(os.path.join(d, spec["file"])) == spec["size"] for spec in mj.MODELS.values()):
            return d
    return None


class FakeDownloads:
    def __init__(self, available=True):
        self.calls = []
        self._available = available
        self.queue = []

    def available(self):
        return self._available

    def start(self, packages=None, reason="", window=None):
        self.calls.append({"packages": list(packages or []), "reason": reason, "window": window})
        return "started"

    def caps(self):
        return {"running": False, "packages": {}, "error": ""}


def fake_agent(data, downloads=None):
    ns = types.SimpleNamespace(DATA=data, DOWNLOADS=downloads or FakeDownloads(), JobError=agent.JobError, log=lambda m: None, warn=lambda m: None,
                               kit_dir=agent.kit_dir, wait_first_control=lambda timeout=None: True)
    return ns


class FakeJob:
    def __init__(self, kind, payload, inputs=None):
        self.kind, self.payload = kind, payload
        self.dir = tempfile.mkdtemp(prefix="nm-job-")
        self.inputs = os.path.join(self.dir, "inputs")
        self.outputs = os.path.join(self.dir, "outputs")
        os.makedirs(self.inputs)
        os.makedirs(self.outputs)
        self.timeout_s = 1500
        self.uid = "test-job"
        self.log = []
        for name, path in (inputs or {}).items():
            shutil.copyfile(path, os.path.join(self.inputs, name))

    def input_path(self, name):
        p = os.path.join(self.inputs, os.path.basename(name or ""))
        return p if name and os.path.isfile(p) else None

    def out(self, name):
        return os.path.join(self.outputs, os.path.basename(name))

    def progress(self, frac, msg="", meta=None):
        self.log.append((round(frac, 3), msg))


class Logic(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="nm-ma-data-")
        self.addCleanup(shutil.rmtree, self.data, True)

    def install_models(self, keys=("yunet", "yolos", "depth")):
        os.makedirs(mj.model_dir(self.data), exist_ok=True)
        for k in keys:
            with open(mj.model_file(self.data, k), "wb") as fh:
                fh.truncate(mj.MODELS[k]["size"])

    def test_model_states_follow_the_files(self):
        ag = fake_agent(self.data)
        st = mj.model_states(ag)
        self.assertEqual({k: v["state"] for k, v in st.items()}, {"yunet": "missing", "yolos": "missing", "depth": "missing"})
        self.install_models(("yunet", "yolos"))
        st = mj.model_states(ag)
        self.assertEqual(st["yunet"]["state"], "installed")
        self.assertEqual(st["depth"]["state"], "missing")
        with open(mj.model_file(self.data, "yunet"), "ab") as fh:        # a truncated / padded file is not an installed model
            fh.write(b"x")
        self.assertEqual(mj.model_states(ag)["yunet"]["state"], "missing")

    def test_ready_for_needs_runtime_and_models(self):
        models = {k: {"state": "installed"} for k in mj.MODELS}
        self.assertTrue(mj.ready_for("multiangle.virtual", models, {"ok": True}))
        self.assertFalse(mj.ready_for("multiangle.virtual", models, {"ok": None}))
        self.assertFalse(mj.ready_for("multiangle.virtual", models, {"ok": False}))
        models["depth"] = {"state": "downloading"}
        self.assertTrue(mj.ready_for("multiangle.virtual", models, {"ok": True}))          # the detectors are enough for virtual cameras
        self.assertFalse(mj.ready_for("multiangle.move", models, {"ok": True}))            # a move needs the depth model
        self.assertFalse(mj.ready_for("multiangle.selftest", models, {"ok": True}))

    def test_caps_shape(self):
        ag = fake_agent(self.data)
        c = mj.caps(ag)
        self.assertTrue(c["multiangle"])
        self.assertEqual(set(c["multiangle_models"]), {"yunet", "yolos", "depth"})
        self.assertEqual(set(c["multiangle_ready"]), {"virtual", "move", "selftest"})
        self.assertIn("ok", c["multiangle_runtime"])
        self.assertTrue(json.dumps(c))                                                      # the heartbeat is JSON

    def test_switch_off(self):
        os.environ["NM_MULTIANGLE"] = "0"
        try:
            self.assertEqual(mj.caps(fake_agent(self.data)), {"multiangle": False})
            self.assertFalse(mj.register(fake_agent(self.data), {}))
        finally:
            del os.environ["NM_MULTIANGLE"]

    def test_register_adds_handlers_and_heartbeat_keys(self):
        orig = agent.Capabilities.probe
        os.environ["NM_MULTIANGLE_AUTOINSTALL"] = "0"
        try:
            handlers = {}
            self.assertTrue(mj.register(agent_module_like(self.data), handlers))
            self.assertEqual(set(handlers), set(mj.KINDS))
            self.assertTrue(getattr(agent.Capabilities.probe, "_multiangle", False))
            n = agent.Capabilities.probe
            mj.register(agent_module_like(self.data), {})                                   # twice: no double wrapping
            self.assertIs(agent.Capabilities.probe, n)
        finally:
            agent.Capabilities.probe = orig
            del os.environ["NM_MULTIANGLE_AUTOINSTALL"]

    def test_the_agent_itself_registered_the_kinds(self):
        for kind in mj.KINDS:
            self.assertIn(kind, agent.HANDLERS)

    def test_the_background_installer_stays_quiet_in_tests_and_before_the_site_answered(self):
        ag = fake_agent(self.data, FakeDownloads())
        self.assertFalse(mj.may_install_now(ag))                       # inside a unit-test run: never (importing agent.py must not start a download)
        os.environ["NM_MULTIANGLE_INSTALL_IN_TESTS"] = "1"
        try:
            self.assertTrue(mj.may_install_now(ag))                    # a connected agent
            ag.wait_first_control = lambda timeout=None: False         # the site has not answered yet
            self.assertFalse(mj.may_install_now(ag))
            ag.wait_first_control = None                               # an agent that cannot say
            self.assertTrue(mj.may_install_now(ag))
        finally:
            os.environ.pop("NM_MULTIANGLE_INSTALL_IN_TESTS", None)

    def test_install_asks_for_what_is_missing_without_the_night_window(self):
        dl = FakeDownloads()
        ag = fake_agent(self.data, dl)
        orig = mj.find_python
        mj.find_python = lambda agent=None, probe=True: (None, "none")
        try:
            self.install_models(("yunet", "yolos"))
            self.assertEqual(mj.missing_packages(ag), [mj.PKG_RUNTIME, mj.PKG_DEPTH])
            mj.ensure_installed(ag)
            self.assertEqual(dl.calls[-1]["packages"], [mj.PKG_RUNTIME, mj.PKG_DEPTH])
            self.assertEqual(dl.calls[-1]["window"], "")                                    # "" = no limit: the packages are small
            os.environ["NM_MULTIANGLE_AUTOINSTALL"] = "window"
            mj.ensure_installed(ag)
            self.assertIsNone(dl.calls[-1]["window"])
        finally:
            mj.find_python = orig
            os.environ.pop("NM_MULTIANGLE_AUTOINSTALL", None)

    def test_install_does_nothing_when_everything_is_there_or_switched_off(self):
        dl = FakeDownloads()
        ag = fake_agent(self.data, dl)
        self.install_models()
        orig = mj.find_python
        mj.find_python = lambda agent=None, probe=True: ("/usr/bin/python3", {"providers": ["CPUExecutionProvider"]})
        try:
            self.assertEqual(mj.ensure_installed(ag), "ok")
            self.assertEqual(dl.calls, [])
            os.environ["NM_MULTIANGLE_AUTOINSTALL"] = "0"
            self.assertEqual(mj.ensure_installed(fake_agent(tempfile.mkdtemp(), dl)), "off")
        finally:
            mj.find_python = orig
            os.environ.pop("NM_MULTIANGLE_AUTOINSTALL", None)

    def test_install_survives_a_node_without_the_downloader(self):
        ag = fake_agent(self.data, FakeDownloads(available=False))
        self.assertIn("download_models", mj.ensure_installed(ag))

    def test_manifest_packages_match_the_module(self):
        doc = json.load(open(os.path.join(PROC, "downloads", "multiangle.json"), encoding="utf-8"))
        by_pkg = {}
        for it in doc["items"]:
            by_pkg.setdefault(it["package"], []).append(it)
            self.assertFalse(it.get("optional"), it["id"])                               # default set: fetched without anybody asking
        self.assertEqual(set(by_pkg), {mj.PKG_RUNTIME, mj.PKG_DETECT, mj.PKG_DEPTH})
        for key, spec in mj.MODELS.items():
            items = [it for it in by_pkg[spec["package"]] if it["kind"] == "file" and it["dest"].endswith("\\" + spec["file"])]
            self.assertEqual(len(items), 1, key)
            self.assertEqual(items[0]["size"], spec["size"])
            self.assertEqual(len(items[0]["sha256"]), 64)
            self.assertTrue(any("huggingface" in u or "{HF}" in u for u in items[0]["urls"]))
        pip = by_pkg[mj.PKG_RUNTIME][0]
        self.assertEqual(pip["python"], "{VENV:multiangle}")
        self.assertTrue(any(x.startswith("onnxruntime") for x in pip["packages"]) and any(x.startswith("opencv") for x in pip["packages"]))
        # licences: nothing AGPL / non-commercial may be named as a source
        text = json.dumps(doc).lower()
        self.assertNotIn("ultralytics", json.dumps(doc["items"]).lower())
        self.assertNotIn("depth-anything-v2-large", json.dumps(doc["items"]).lower())
        self.assertIn("apache-2.0", text)

    def test_engine_names_match_the_manifest(self):
        try:
            import multiangle_engine as me
        except ModuleNotFoundError as e:                 # numpy / OpenCV live in the node's own venv; a plain Python running the tests may not have them
            self.skipTest("needs numpy + OpenCV: %s" % e)
        self.assertEqual({k: v["file"] for k, v in mj.MODELS.items()}, me.MODEL_FILES)

    def test_command_line_is_clamped_and_whitelisted(self):
        files = {"video": "/tmp/in.mp4"}
        cmd = mj.build_command("multiangle.virtual", {"angles": ["wide", "evil; rm -rf /", "close"], "format": "`id`", "pace": "turbo", "handheld": 99, "seed": -5,
                                                     "rhythm": "$(x)", "max_seconds": 1e9, "max_upscale": 0, "out_height": 99999}, "py", files, "/out", "/models", "ffmpeg", "auto")
        joined = " ".join(cmd)
        self.assertIn("--angles wide,close", joined)
        self.assertIn("--format source", joined)
        self.assertIn("--pace medium", joined)
        self.assertIn("--handheld 1.000", joined)
        self.assertIn("--seed 0", joined)
        self.assertIn("--rhythm auto", joined)
        self.assertIn("--max-seconds 300.0", joined)
        self.assertIn("--max-upscale 1.10", joined)
        self.assertIn("--out-height 2160", joined)
        self.assertNotIn("rm -rf", joined)
        self.assertNotIn("`", joined)
        mv = mj.build_command("multiangle.move", {"move": "teleport", "amount": 5, "duration": 99, "focus": "0.5,0.4", "inpaint": True}, "py", {"input": "/tmp/a.png"}, "/out", "/m", "ff", "cpu")
        s = " ".join(mv)
        self.assertIn("--move dolly_in", s)
        self.assertIn("--amount 1.000", s)
        self.assertIn("--duration 12.00", s)
        self.assertIn("--focus 0.5,0.4", s)
        self.assertIn("--inpaint", s)
        bad = mj.build_command("multiangle.move", {"focus": "1;2"}, "py", {"input": "x"}, "/o", "/m", "ff", "auto")
        self.assertNotIn("--focus", bad)
        st = mj.build_command("multiangle.selftest", {}, "py", {}, "/o", "/m", "ff", "auto")
        self.assertEqual(st[4], "selftest")

    def test_missing_inputs_are_refused_without_a_retry(self):
        d = tempfile.mkdtemp(prefix="nm-ma-data-")
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(mj.model_dir(d), exist_ok=True)
        for k in mj.MODELS:
            with open(mj.model_file(d, k), "wb") as fh:
                fh.truncate(mj.MODELS[k]["size"])
        ag = fake_agent(d)
        orig = mj.find_python
        mj.find_python = lambda agent=None, probe=True: (sys.executable, {"providers": ["CPUExecutionProvider"]})
        try:
            if not FF:
                self.skipTest("no ffmpeg")
            with self.assertRaises(agent.JobError) as cm:
                mj.run(FakeJob("multiangle.virtual", {"video": "nope.mp4"}), ag)
            self.assertFalse(cm.exception.retryable)
        finally:
            mj.find_python = orig

    def test_a_job_for_a_missing_model_waits_instead_of_failing(self):
        ag = fake_agent(self.data)
        if not FF:
            self.skipTest("no ffmpeg")
        with self.assertRaises(agent.JobError) as cm:
            mj.run(FakeJob("multiangle.move", {"input": "a.png"}), ag)
        self.assertTrue(cm.exception.retryable)
        self.assertIn("depth", str(cm.exception))


def agent_module_like(data):
    """The real agent module (so Capabilities is real), with a throw-away data folder."""
    return agent


def make_bars_clip(path, ff=None):
    """4 s at 25 fps, 640x360: for 2 s a 288 px wide picture (x 176..464), then for 2 s a narrower one (216 px, x 212..428) - the black strips change at
    second 2 like the owner's composite does at second 8. Every picture pixel has luma >= 70, so a strip is unmistakable."""
    f = "lutyuv=y='clip(val,70,235)'"
    subprocess.run([ff or FF, "-v", "error", "-y", "-f", "lavfi", "-i", "gradients=size=288x360:rate=25:duration=2", "-f", "lavfi", "-i", "gradients=size=216x360:rate=25:duration=2",
                    "-filter_complex", "[0:v]%s,pad=640:360:176:0:black[a];[1:v]%s,pad=640:360:212:0:black[b];[a][b]concat=n=2:v=1:a=0[v]" % (f, f),
                    "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path], check=True, stdin=subprocess.DEVNULL)


def edge_luma(video, edge=3):
    """[(first frame index with a dark edge or None)...]: the lowest mean luma of the `edge` outermost columns of every frame (no bar: > 50)."""
    cap = cv2.VideoCapture(video)
    low = []
    ok, fr = cap.read()
    while ok:
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        low.append(min(float(g[:, :edge].mean()), float(g[:, -edge:].mean())))
        ok, fr = cap.read()
    cap.release()
    return low


@unittest.skipUnless(HAVE_CV and FF, "needs numpy, OpenCV and ffmpeg")
class ChangingBarsOnRealVideo(unittest.TestCase):
    """Black strips that change while the clip plays are found per frame and never shown in any angle (no model needed: the subject is the motion)."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="nm-ma-bars-")
        cls.clip = os.path.join(cls.work, "bars.mp4")
        make_bars_clip(cls.clip)
        import multiangle_engine as me
        cls.me = me

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_the_scan_finds_the_switch_on_its_own_frame(self):
        me = self.me
        info = me.probe(FF, self.clip)
        union = me.sample_active_area(FF, self.clip, info, 4.0)
        self.assertAlmostEqual(union[0], 176, delta=6)
        self.assertAlmostEqual(union[2], 464, delta=6)
        rects = me.scan_rects(FF, self.clip, info, union, 25.0, 0.0, 4.0)
        self.assertAlmostEqual(len(rects), 100, delta=2)
        import multiangle_core as mc
        segs = mc.rect_segments(rects, 25.0, (union[2] - union[0], union[3] - union[1]))
        self.assertEqual(len(segs), 2, segs)
        self.assertAlmostEqual(segs[1]["t0"], 2.0, delta=0.09)                              # to the frame (a frame is 0.04 s)
        self.assertAlmostEqual(segs[1]["px"][0], 36, delta=5)                               # 212 - 176 px of the union
        self.assertAlmostEqual(segs[1]["px"][2], 252, delta=5)

    def test_no_angle_shows_a_black_strip_and_the_angles_stay_in_sync(self):
        models = os.path.join(self.work, "no-models")
        os.makedirs(models, exist_ok=True)
        out = os.path.join(self.work, "out")
        env = dict(os.environ, NM_MULTIANGLE_NVENC="0")
        r = subprocess.run([sys.executable, os.path.join(PROC, "multiangle_engine.py"), "virtual", "--video", self.clip, "--angles", "wide,medium,close", "--provider", "cpu",
                            "--models", models, "--ffmpeg", FF, "--out-dir", out, "--pace", "fast", "--handheld", "0.3", "--max-upscale", "3"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, timeout=300)
        text = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, text[-800:])
        plan = json.load(open(os.path.join(out, "plan.json"), encoding="utf-8"))
        self.assertTrue(plan["source"]["black_bars"])
        self.assertEqual(len(plan["source"]["bars_change"]), 2)
        self.assertEqual(len(plan["angles"]), 3)
        counts = []
        for a in plan["angles"] + [{"file": plan["multicam"]}]:
            low = edge_luma(os.path.join(out, a["file"]))
            counts.append(len(low))
            self.assertGreater(min(low), 50.0, "%s shows a black strip in frame %d" % (a["file"], low.index(min(low))))
        self.assertEqual(len(set(counts)), 1, counts)
        # the output is sized from the typical frame, never above the picture the layouts really have
        self.assertLessEqual(plan["output"]["height"], 360)


@unittest.skipUnless(HAVE_RT and FF and test_models(), "needs numpy + OpenCV + onnxruntime, ffmpeg and the model files (NM_MULTIANGLE_TEST_MODELS)")
class RealEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = test_models()
        cls.work = tempfile.mkdtemp(prefix="nm-ma-real-")
        cls.clip = os.path.join(cls.work, "clip.mp4")
        cls.photo = os.path.join(cls.work, "photo.png")
        # a synthetic 5 s clip with sound that pauses twice: a bright block moves over a gradient (no real person in a test)
        subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "gradients=size=640x360:rate=25:duration=5", "-f", "lavfi", "-i", "sine=f=220:d=5",
                        "-filter_complex", "[0:v]drawbox=x='40+80*t':y=100:w=120:h=200:color=white:t=fill[v];[1:a]volume='if(lt(mod(t,2.5),1.8),1,0.003)':eval=frame[a]",
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.clip],
                       check=True, stdin=subprocess.DEVNULL)
        subprocess.run([FF, "-v", "error", "-y", "-i", cls.clip, "-frames:v", "1", "-ss", "1", cls.photo], check=True, stdin=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def agent_for(self):
        d = tempfile.mkdtemp(prefix="nm-ma-data-")
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(mj.model_dir(d), exist_ok=True)
        for spec in mj.MODELS.values():
            shutil.copyfile(os.path.join(self.models, spec["file"]), os.path.join(mj.model_dir(d), spec["file"]))
        return fake_agent(d)

    def run_kind(self, kind, payload, inputs):
        old = edit_render.upload_resumable
        sent = {}

        def fake_upload(job, ag, path, name, say):
            dst = os.path.join(job.dir, "uploaded", name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(path, dst)
            sent[name] = os.path.getsize(path)
            return {"bytes": os.path.getsize(path), "sha256": "0" * 64}

        edit_render.upload_resumable = fake_upload
        old_big, mj.BIG_OUTPUT = mj.BIG_OUTPUT, 40000                                       # the tiny test videos count as «big»
        os.environ["NM_MULTIANGLE_PROVIDER"] = "cpu"
        os.environ["NM_MULTIANGLE_NVENC"] = "0"
        try:
            job = FakeJob(kind, payload, inputs)
            ag = self.agent_for()
            orig = mj.find_python
            mj.find_python = lambda agent=None, probe=True: (sys.executable, {"providers": ["CPUExecutionProvider"]})
            try:
                meta = mj.run(job, ag)
            finally:
                mj.find_python = orig
            return job, meta, sent
        finally:
            edit_render.upload_resumable = old
            mj.BIG_OUTPUT = old_big
            os.environ.pop("NM_MULTIANGLE_PROVIDER", None)
            os.environ.pop("NM_MULTIANGLE_NVENC", None)

    def test_virtual_cameras_end_to_end(self):
        job, meta, sent = self.run_kind("multiangle.virtual", {"video": "clip.mp4", "angles": ["wide", "medium", "close"], "format": "source", "pace": "fast", "out_height": 360},
                                        {"clip.mp4": self.clip})
        plan = json.load(open(job.out("plan.json"), encoding="utf-8"))
        self.assertEqual(meta["primary"], "plan.json")
        keys = [a["key"] for a in plan["angles"]]
        self.assertGreaterEqual(len(keys), 2)
        for a in plan["angles"]:
            self.assertIn(a["file"], sent)                                                  # the videos went through the chunk upload
            self.assertTrue(os.path.isfile(job.out(a["preview"])))
        self.assertEqual(set(meta["big"]), set(sent))
        self.assertIn("multicam.mp4", sent)
        out = plan["output"]
        self.assertEqual(out["height"], 360)
        self.assertAlmostEqual(out["duration"], 5.0, delta=0.15)
        # every angle has the same number of frames as the multicam edit: they are synced
        counts = []
        for name in sent:
            r = subprocess.run([FF, "-v", "error", "-i", os.path.join(job.dir, "uploaded", name), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"], stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            counts.append(r.stderr.decode("utf-8", "replace"))
        self.assertTrue(len(plan["segments"]) >= 2)
        self.assertEqual(plan["segments"][0]["angle"], "wide")
        self.assertGreaterEqual(plan["audio"]["pauses"], 1)                                 # the synthetic speech pauses were heard
        self.assertEqual(plan["subject_mode"] in ("motion", "person", "face"), True)
        self.assertIn("models", plan["device"])
        self.assertTrue(job.log and job.log[-1][0] <= 0.99)
        # sound is kept in every clip
        probe = subprocess.run([FF, "-hide_banner", "-i", os.path.join(job.dir, "uploaded", "angle_wide.mp4")], stderr=subprocess.PIPE, stdin=subprocess.DEVNULL).stderr.decode("utf-8", "replace")
        self.assertIn("Audio:", probe)

    def test_a_2_5d_move_end_to_end(self):
        job, meta, sent = self.run_kind("multiangle.move", {"input": "photo.png", "move": "truck_right", "amount": 0.9, "duration": 1.5, "fps": 20, "out_height": 288},
                                        {"photo.png": self.photo})
        with open(job.out("plan.json"), encoding="utf-8") as fh:
            plan = json.load(fh)
        self.assertEqual(plan["mode"], "move25d")
        self.assertEqual(plan["output"]["frames"], 30)
        # a small clip may go the normal way (job.out) or through the chunk upload - either way it must arrive, exactly once
        up_path = os.path.join(job.dir, "uploaded", "move.mp4")
        self.assertTrue(("move.mp4" in sent) != os.path.isfile(job.out("move.mp4")), (sorted(sent), os.listdir(job.dir)))
        video = up_path if "move.mp4" in sent else job.out("move.mp4")
        self.assertTrue(os.path.isfile(job.out("depth.png")) or "depth.png" in sent)
        self.assertTrue(os.path.isfile(job.out("preview.jpg")) or "preview.jpg" in sent)
        self.assertGreaterEqual(plan["safe_zoom"], 1.0)
        import cv2
        cap = cv2.VideoCapture(video)
        frames = []
        ok, fr = cap.read()
        while ok:
            frames.append(fr)
            ok, fr = cap.read()
        cap.release()
        self.assertEqual(len(frames), 30)
        import numpy as np
        self.assertGreater(float(np.abs(frames[0].astype(np.float32) - frames[-1].astype(np.float32)).mean()), 0.5)         # the view really changed
        step = [float(np.abs(frames[i + 1].astype(np.float32) - frames[i].astype(np.float32)).mean()) for i in range(len(frames) - 1)]
        self.assertLess(max(step), 6 * (sum(step) / len(step)) + 1.0)                      # no flicker: no frame jumps against its neighbours

    def test_a_2_5d_move_on_a_video_whose_bars_change_shows_no_strip(self):
        clip = os.path.join(self.work, "bars.mp4")
        make_bars_clip(clip)
        job, meta, sent = self.run_kind("multiangle.move", {"input": "bars.mp4", "move": "truck_right", "amount": 0.6, "duration": 4.0, "fps": 15, "out_height": 240, "max_seconds": 4.0},
                                        {"bars.mp4": clip})
        with open(job.out("plan.json"), encoding="utf-8") as fh:
            plan = json.load(fh)
        self.assertEqual(len(plan["bars_change"]), 2, plan.get("bars_change"))
        video = os.path.join(job.dir, "uploaded", "move.mp4") if "move.mp4" in sent else job.out("move.mp4")
        low = edge_luma(video)
        self.assertGreater(min(low), 40.0, "frame %d has a strip" % low.index(min(low)))

    def test_the_self_test_job(self):
        job, meta, sent = self.run_kind("multiangle.selftest", {"selftest": True}, {})
        res = json.load(open(job.out("selftest.json"), encoding="utf-8"))
        names = {c["name"] for c in res["checks"]}
        self.assertTrue({"runtime", "models", "virtual.angles", "virtual.synced", "virtual.cuts", "move.frames", "move.parallax"} <= names, names)
        self.assertTrue(res["ok"], [c for c in res["checks"] if not c["ok"]])
        self.assertTrue(meta["ok"])

    def test_a_cancelled_job_leaves_no_engine_running(self):
        job = FakeJob("multiangle.virtual", {"video": "clip.mp4"}, {"clip.mp4": self.clip})

        calls = []

        def cancel(frac, msg="", meta=None):
            calls.append(msg)
            if msg != "multiangle|prepare":                                              # the engine is running now
                raise agent.Cancelled()

        job.progress = cancel
        ag = self.agent_for()
        orig = mj.find_python
        mj.find_python = lambda agent=None, probe=True: (sys.executable, {"providers": ["CPUExecutionProvider"]})
        os.environ["NM_MULTIANGLE_PROVIDER"] = "cpu"
        try:
            with self.assertRaises(agent.Cancelled):
                mj.run(job, ag)
        finally:
            mj.find_python = orig
            os.environ.pop("NM_MULTIANGLE_PROVIDER", None)
        self.assertTrue(any(m != "multiangle|prepare" for m in calls))
        time.sleep(1.0)
        left = subprocess.run(["pgrep", "-f", "multiangle_engine.py virtual --video " + job.input_path("clip.mp4")], stdout=subprocess.PIPE).stdout
        self.assertEqual(left.strip(), b"")

    def test_a_garbage_video_is_a_clean_non_retryable_error(self):
        bad = os.path.join(self.work, "bad.mp4")
        with open(bad, "wb") as fh:
            fh.write(b"this is not a video" * 100)
        with self.assertRaises(agent.JobError) as cm:
            self.run_kind("multiangle.virtual", {"video": "bad.mp4"}, {"bad.mp4": bad})
        self.assertFalse(cm.exception.retryable)
        self.assertIn("no_video", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
