"""agent 2.12: up3d_jobs.py - the 3D video engine (Blender / Cycles) as the compute job `up3d.render`.

A stand-in Blender (a tiny script that speaks the engine's UP3D: protocol) lets the whole handler run for real without Blender or a GPU:
package mode (the self-test path), the GPU rules, cancel, the site-job mode (through a fake 3D worker), the service take-over, the
declarative install file. A real Blender run is optional: UP3D_TEST_REAL_BLENDER=/path/to/blender (CPU, a few seconds).

    python -m unittest tests/test_up3d_jobs.py        (from the processing folder; Linux, the stand-in is a shell script)
"""
import io
import json
import os
import shutil
import stat
import struct
import sys
import tempfile
import types
import unittest
import zipfile
import zlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import agent  # noqa: E402
import bootstrap  # noqa: E402
import up3d_jobs  # noqa: E402

WIN = sys.platform.startswith("win")


def png_bytes(w=8, h=8, gray=120):
    raw = b"".join(b"\x00" + bytes([gray]) * w for _ in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


FAKE_ENGINE = r'''
import json, os, sys, struct, zlib
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opt = {}
i = 0
while i < len(args):
    if args[i].startswith("--"):
        opt[args[i][2:]] = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else "1"
        i += 2
    else:
        i += 1
out = opt["out"]
os.makedirs(out, exist_ok=True)
def png(gray=120, w=8, h=8):
    raw = b"".join(b"\x00" + bytes([gray]) * w for _ in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
dev = os.environ.get("FAKE_DEVICE", "OPTIX")
print("UP3D:STAGE render", flush=True)
mode = opt.get("mode", "render")
if mode == "contact":
    for n in (1, 2):
        open(os.path.join(out, "contact_%04d.png" % (n * 10)), "wb").write(png(100 + n * 20))
        print("UP3D:PROGRESS %d 2" % n, flush=True)
elif mode == "render":
    os.makedirs(os.path.join(out, "frames"), exist_ok=True)
    for n in range(1, 5):
        open(os.path.join(out, "frames", "f_%04d.png" % n), "wb").write(png(80 + n * 10))
        print("UP3D:PROGRESS %d 4" % n, flush=True)
if os.environ.get("FAKE_SLOW"):
    import time; time.sleep(30)
rep = {"device": {"type": dev, "name": "Fake RTX 3060" if dev != "CPU" else "", "note": "no gpu" if dev == "CPU" else ""},
       "denoiser": "OPTIX" if dev == "OPTIX" else "OPENIMAGEDENOISE", "sec_per_frame": 1.5, "render_seconds": 3.0,
       "frames_rendered": 4, "frames_expected": 4, "look": {"view": "AgX", "look": "AgX - Medium High Contrast"},
       "require_gpu_env": os.environ.get("UP3D_REQUIRE_GPU", "")}
json.dump(rep, open(os.path.join(out, "engine_report.json"), "w"))
'''


class FakeJob:
    def __init__(self, tmp, payload, files=None):
        self.uid = "abcdef12-0000-0000-0000-000000000000"
        self.payload = payload
        self.timeout_s = 600
        self.inputs = os.path.join(tmp, "inputs")
        self.outputs = os.path.join(tmp, "outputs")
        os.makedirs(self.inputs, exist_ok=True)
        os.makedirs(self.outputs, exist_ok=True)
        for name, data in (files or {}).items():
            with open(os.path.join(self.inputs, name), "wb") as fh:
                fh.write(data)
        self.cancelled = False
        self.site = types.SimpleNamespace(base="http://127.0.0.1:9", token="tok")
        self.log = []

    def input_path(self, name):
        p = os.path.join(self.inputs, os.path.basename(name or ""))
        return p if os.path.isfile(p) else None

    def out(self, name):
        return os.path.join(self.outputs, os.path.basename(name))

    def progress(self, frac, msg="", meta=None):
        self.log.append((frac, msg, meta))
        if self.cancelled:
            raise agent.Cancelled()


def package_zip(profile=None, extra=None):
    comp = {"format": "up3d.compiled/1", "fps": 24, "frame_start": 1, "frame_end": 4, "resolution": [64, 64],
            "profile": profile or {"id": "standard", "engine": "CYCLES", "recommended": "gpu", "frame_step": 1}}
    comp.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("compiled.json", json.dumps(comp))
        z.writestr("inputs/note.txt", "x")
    return buf.getvalue()


@unittest.skipIf(WIN, "the stand-in Blender is a shell script")
class PackageMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="up3d-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shim = os.path.join(self.tmp, "fake-blender")
        eng = os.path.join(self.tmp, "fake_engine.py")
        with open(eng, "w") as fh:
            fh.write(FAKE_ENGINE)
        with open(shim, "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, eng))
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC)
        self.old = {k: os.environ.get(k) for k in ("UP3D_BLENDER", "UP3D_DATA", "UP3D_FFMPEG", "FAKE_DEVICE", "UP3D_REQUIRE_GPU")}
        os.environ["UP3D_BLENDER"] = shim
        os.environ["UP3D_DATA"] = os.path.join(self.tmp, "up3d-data")
        os.environ.pop("FAKE_DEVICE", None)
        self.addCleanup(self.restore)
        self.agent = types.SimpleNamespace(DATA=self.tmp, JobError=agent.JobError, Cancelled=agent.Cancelled, gpu=None, MANAGER=None,
                                           CONFIG={"name": "TEST-NODE"}, log=lambda *a, **k: None, warn=lambda *a, **k: None,
                                           blender_path=lambda: shim)

    def restore(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_job(self, payload, zipped=None):
        job = FakeJob(self.tmp, payload, {"package.zip": zipped or package_zip()})
        return job, up3d_jobs.run(job, self.agent)

    def test_contact_render_on_the_gpu(self):
        job, meta = self.run_job({"package": "package.zip", "mode": "contact", "extra": ["--count", "2"]})
        names = sorted(os.listdir(job.outputs))
        self.assertIn("engine_report.json", names)
        self.assertEqual(len([n for n in names if n.startswith("contact_")]), 2)
        self.assertEqual(meta["device"], "cuda")
        self.assertIn("OPTIX", meta["device_note"])
        self.assertEqual(meta["denoiser"], "OPTIX")
        self.assertEqual(meta["colour"], "AgX / AgX - Medium High Contrast")
        self.assertNotIn("device_warning", meta)
        self.assertTrue(any("frame" in (m or "") or "stage" in (m or "") for _f, m, _x in job.log))

    def test_gpu_class_profile_sets_require_gpu_and_cpu_is_a_warning(self):
        os.environ["FAKE_DEVICE"] = "CPU"
        job, meta = self.run_job({"package": "package.zip", "mode": "contact"})
        rep = json.load(open(os.path.join(job.outputs, "engine_report.json")))
        self.assertEqual(rep["require_gpu_env"], "1")                  # a GPU-class render must not fall back silently
        self.assertEqual(meta["device"], "cpu")
        self.assertIn("device_warning", meta)

    def test_cpu_profile_and_opt_out_do_not_require_gpu(self):
        job, _meta = self.run_job({"package": "package.zip", "mode": "contact"},
                                  package_zip({"id": "preview", "engine": "CYCLES", "recommended": "cpu"}))
        self.assertEqual(json.load(open(os.path.join(job.outputs, "engine_report.json")))["require_gpu_env"], "")
        self.setUp()
        job, _meta = self.run_job({"package": "package.zip", "mode": "contact", "require_gpu": False})
        self.assertEqual(json.load(open(os.path.join(job.outputs, "engine_report.json")))["require_gpu_env"], "")

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_render_mode_makes_the_mp4_and_a_poster(self):
        job, meta = self.run_job({"package": "package.zip", "mode": "render"})
        names = sorted(os.listdir(job.outputs))
        self.assertIn("render.mp4", names)
        self.assertIn("first_frame.png", names)
        self.assertEqual(meta["primary"], "render.mp4")
        self.assertEqual(meta["frames"], 4)
        self.assertEqual(open(job.out("render.mp4"), "rb").read()[4:8], b"ftyp")

    def test_missing_package_and_missing_blender_are_clear(self):
        job = FakeJob(self.tmp, {"package": "nope.zip"}, {"package.zip": package_zip()})
        with self.assertRaises(agent.JobError) as cm:
            up3d_jobs.run(job, self.agent)
        self.assertFalse(cm.exception.retryable)
        self.agent.blender_path = lambda: None
        os.environ["UP3D_BLENDER"] = os.path.join(self.tmp, "no-such-blender")
        job = FakeJob(self.tmp, {"package": "package.zip"}, {"package.zip": package_zip()})
        with self.assertRaises(agent.JobError) as cm:
            up3d_jobs.run(job, self.agent)
        self.assertIn("DOWNLOADING", str(cm.exception))                 # the site retries it later: the install is still running

    def test_cancel_stops_the_engine(self):
        os.environ["FAKE_SLOW"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_SLOW", None)
        job = FakeJob(self.tmp, {"package": "package.zip", "mode": "contact"}, {"package.zip": package_zip()})
        job.cancelled = True
        with self.assertRaises(Exception):
            up3d_jobs.run(job, self.agent)

    def test_unsafe_package_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "x")
            z.writestr("compiled.json", "{}")
        job = FakeJob(self.tmp, {"package": "package.zip"}, {"package.zip": buf.getvalue()})
        with self.assertRaises(RuntimeError):
            up3d_jobs.run(job, self.agent)


class SiteJobMode(unittest.TestCase):
    """payload.up3d_job: the 3D section's own worker protocol, through a fake worker."""

    class FakeWorker:
        def __init__(self, claimed, last):
            self.claimed, self.last, self.caps = claimed, last, {"gpu": ["OPTIX:RTX"]}

        def run_one(self):
            return {"id": 36} if self.claimed else None

    def run_with(self, claimed, last):
        tmp = tempfile.mkdtemp(prefix="up3d-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        ag = types.SimpleNamespace(DATA=tmp, JobError=agent.JobError, Cancelled=agent.Cancelled, gpu=None, MANAGER=None,
                                   CONFIG={"name": "N"}, log=lambda *a, **k: None, warn=lambda *a, **k: None, blender_path=lambda: __file__)
        job = FakeJob(tmp, {"up3d_job": 36})
        old = up3d_jobs._make_worker
        up3d_jobs._make_worker = lambda *a, **k: (self.FakeWorker(claimed, last), "k")
        try:
            return up3d_jobs.run(job, ag)
        finally:
            up3d_jobs._make_worker = old

    def test_done(self):
        meta = self.run_with(True, {"ok": True, "seconds": 12.5, "files": ["render.mp4"]})
        self.assertEqual(meta["result"], "done")
        self.assertEqual(meta["up3d_job"], 36)

    def test_nothing_to_do_is_not_an_error(self):
        meta = self.run_with(False, None)
        self.assertIn("nothing to do", meta["result"])

    def test_failed_3d_job_is_reported_not_retried(self):
        meta = self.run_with(True, {"ok": False, "error": "scene broken"})
        self.assertTrue(meta["up3d_failed"])
        self.assertIn("scene broken", meta["result"])

    def test_taken_back_by_the_site(self):
        meta = self.run_with(True, {"ok": False, "released": "handoff"})
        self.assertIn("handoff", meta["result"])

    def test_cancelled_compute_job_keeps_the_3d_job(self):
        with self.assertRaises(agent.Cancelled):
            self.run_with(True, {"ok": False, "released": "cancelled"})

    def test_bad_payload(self):
        tmp = tempfile.mkdtemp(prefix="up3d-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        ag = types.SimpleNamespace(DATA=tmp, JobError=agent.JobError, Cancelled=agent.Cancelled, gpu=None, MANAGER=None,
                                   CONFIG={"name": "N"}, log=lambda *a, **k: None, warn=lambda *a, **k: None, blender_path=lambda: __file__)
        with self.assertRaises(agent.JobError):
            up3d_jobs.run(FakeJob(tmp, {"nothing": 1}), ag)


class WiredIntoTheAgent(unittest.TestCase):
    def test_handler_kind_version_and_code_file(self):
        self.assertIn("up3d.render", agent.HANDLERS)
        self.assertIn("up3d.render", sorted(agent.HANDLERS))                        # what caps["kinds"] advertises
        self.assertIn("up3d_jobs.py", agent.CODE_FILES)
        major, minor = (int(x) for x in agent.VERSION.split(".")[:2])
        self.assertGreaterEqual((major, minor), (2, 11))           # the platform agent (bootstrap, outbox, lanes) this module builds on

    def test_the_separate_3d_worker_service_is_not_started(self):
        sm = agent.ServiceManager()
        self.assertFalse(sm.startable("worker3d"))
        self.assertFalse(sm.start("worker3d", wait=False))
        self.assertNotIn("worker3d", [k for k, v in sm.startable_map().items() if v])
        started = []
        sm.start = lambda key, *a, **k: started.append(key) or True
        with mock.patch.object(agent, "blender_path", lambda: __file__):
            sm.default_boot({})                    # the first-boot default: Blender exists, the panel decided nothing
        self.assertNotIn("worker3d", started)

    def test_install_file_is_valid_and_complete(self):
        specs, errors = bootstrap.load_specs(os.path.join(PROC, "requirements.d"))
        self.assertEqual(errors, [])
        by = {s["feature"]: s for s in specs}
        spec = by["blender-3d"]
        self.assertEqual(spec["kinds"], ["up3d.render"])                          # jobs wait in the site's queue until Blender is ready
        self.assertTrue(spec["needs_gpu"])
        blender = next(i for i in spec["items"] if i["id"] == "blender")
        self.assertEqual(blender["type"], "archive")
        self.assertRegex(blender["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(blender["sources"], [{"site": "blender-windows.zip"}])
        self.assertEqual(blender["check_file"], "vendor/blender/blender.exe")
        gpu = next(i for i in spec["items"] if i["id"] == "gpu")
        self.assertEqual(gpu["type"], "cmd")
        self.assertIn("probe_gpu.py", " ".join(gpu["check"]))
        pres = by["blender-3d-presenters"]
        self.assertEqual(pres["requires"], ["blender-3d"])
        self.assertEqual(pres["kinds"], [])                                        # presenter data never blocks a render
        self.assertTrue(os.path.isfile(os.path.join(PROC, "up3d", "probe_gpu.py")))

    def test_hdri_files_travel_with_the_node_code(self):
        d = os.path.join(PROC, "assets", "hdri")
        for name in ("studio_small_09", "photo_studio_loft_hall", "venice_sunset", "kloofendal_48d_partly_cloudy_puresky"):
            p = os.path.join(d, name + ".hdr")
            self.assertTrue(os.path.isfile(p), name)
            self.assertEqual(open(p, "rb").read(10), b"#?RADIANCE")


class ProbeScript(unittest.TestCase):
    def test_messages_and_exit_codes(self):
        import importlib
        probe = importlib.import_module("up3d.probe_gpu")
        self.assertEqual(probe.main([]), 3)
        self.assertEqual(probe.main([os.path.join(tempfile.gettempdir(), "no-blender-here")]), 3)
        orig = probe.probe
        try:
            probe.probe = lambda exe, timeout=240: ({"version": "4.5.14", "devices": []}, "")
            self.assertEqual(probe.main([__file__]), 2)
            probe.probe = lambda exe, timeout=240: ({"version": "4.5.14", "devices": [{"type": "CUDA", "name": "RTX"}, {"type": "OPTIX", "name": "RTX"}]}, "")
            self.assertEqual(probe.main([__file__]), 0)
        finally:
            probe.probe = orig


@unittest.skipUnless(os.environ.get("UP3D_TEST_REAL_BLENDER") and not WIN, "set UP3D_TEST_REAL_BLENDER=/path/to/blender")
class RealBlender(unittest.TestCase):
    def test_probe_sees_blender(self):
        import importlib
        probe = importlib.import_module("up3d.probe_gpu")
        info, err = probe.probe(os.environ["UP3D_TEST_REAL_BLENDER"])
        self.assertIsNotNone(info, err)
        self.assertTrue(info["version"].startswith("4."))


if __name__ == "__main__":
    unittest.main()
