"""agent 2.7: photo.matting - u2netp / IS-Net / BiRefNet-lite on the node (photo_matting.py).

    python -m unittest tests/test_photo_matting.py        (from the processing folder)

The pure-logic tests always run. The real-model tests need numpy + onnxruntime + Pillow and the model files (NM_MATTING_TEST_MODELS=<folder>
or the site's mirror folder); each one skips itself when something is missing. They run the REAL subprocess the agent would start, on
the CPU, with a fake job - never on a real node."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
os.environ["NM_SMALL_MODELS"] = "0"
import agent  # noqa: E402
import photo_matting as pm  # noqa: E402

try:
    import numpy as np  # noqa: E402
    import onnxruntime  # noqa: E402,F401
    from PIL import Image  # noqa: E402
    HAVE_RT = True
except Exception:  # noqa: BLE001
    HAVE_RT = False

MODEL_DIRS = [os.environ.get("NM_MATTING_TEST_MODELS", ""), "/var/www/NM/upmarket/data/up3d/downloads",
              os.path.join(os.path.dirname(PROC), "data", "up3d", "downloads")]


def model_src(key):
    for d in MODEL_DIRS:
        cand = os.path.join(d, pm.MODELS[key]["file"]) if d else ""
        if cand and os.path.isfile(cand) and os.path.getsize(cand) == pm.MODELS[key]["size"]:
            return cand
    return None


def mem_available_mb():
    """MemAvailable of this machine in MB (Linux), or None when unknown (Windows: assume enough)."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return None


#: BiRefNet-lite at 1024 px needs ~6.5 GB of free RAM on the CPU (the site server has 4 GB: it would be OOM-killed there)
NEEDS_MB = {"u2netp": 600, "isnet": 2000, "birefnet-lite": 7000}


def fits(key):
    free = mem_available_mb()
    return free is None or free >= NEEDS_MB[key]


def put_model(data_root, key, src=None):
    """The file where the node keeps it (symlink when the OS allows, else a copy)."""
    dst = pm.model_file(data_root, key)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    src = src or model_src(key)
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError, AttributeError):
        shutil.copyfile(src, dst)
    return dst


class FakeAgent:
    JobError = agent.JobError

    def __init__(self, data, downloads=None):
        self.DATA = data
        self.DOWNLOADS = downloads


class FakeDownloads:
    def __init__(self, running=None, queue=None, error="", progress=None, waiting=None):
        self._c = {"running": bool(running), "error": error, "packages": {}, "waiting": waiting}
        if running:
            self._c["progress"] = {"packages": running, "bytes_done": int(progress[0]), "bytes_total": int(progress[1])}
        self.queue = list(queue or [])

    def caps(self):
        return dict(self._c)


class FakeJob:
    def __init__(self, tmp, payload, image=None, timeout_s=600, cancel_after=None):
        self.payload, self.timeout_s, self.ticks, self.cancel_after = payload, timeout_s, [], cancel_after
        self.inputs = os.path.join(tmp, "inputs")
        self.outputs = os.path.join(tmp, "outputs")
        os.makedirs(self.inputs, exist_ok=True)
        os.makedirs(self.outputs, exist_ok=True)
        if image:
            shutil.copyfile(image, os.path.join(self.inputs, os.path.basename(image)))

    def out(self, name):
        return os.path.join(self.outputs, os.path.basename(name))

    def input_path(self, name):
        p = os.path.join(self.inputs, os.path.basename(name or ""))
        return p if name and os.path.isfile(p) else None

    def progress(self, fraction, message="", meta=None):
        self.ticks.append((fraction, message))
        if self.cancel_after is not None and len(self.ticks) > self.cancel_after:
            raise agent.Cancelled()


def make_photo(path, w=640, h=480):
    Image.fromarray(pm.synthetic_photo(w, h)).save(path)
    return path


# ───────────────────────────────────────────── what never needs a model

class TableAndManifestTests(unittest.TestCase):
    def manifest(self, name):
        with open(os.path.join(PROC, "downloads", name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_three_models_with_the_ids_the_site_uses(self):
        self.assertEqual(list(pm.ORDER), ["u2netp", "isnet", "birefnet-lite"])
        self.assertEqual(set(pm.MODELS), set(pm.ORDER))

    def test_manifest_items_match_the_model_table(self):
        m = self.manifest("matting.json")
        by_pkg = {it["package"]: it for it in m["items"]}
        for key in ("u2netp", "isnet"):
            spec = pm.MODELS[key]
            it = by_pkg[spec["package"]]
            self.assertEqual(it["size"], spec["size"], key)
            self.assertTrue(it["dest"].endswith("\\photo-matting\\" + spec["file"]), it["dest"])
            self.assertRegex(it["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(it.get("optional"), "the three models are fetched on request / by the nightly schedule, not at every start")
            self.assertTrue(it["urls"][0].startswith("{SITE}/3d/files/downloads/"), "the site's own mirror first (GitHub is slow from Iran)")
            self.assertIn(spec["package"], m["packages"])
        p = self.manifest("photo.json")["items"][0]
        self.assertEqual((p["package"], p["size"]), (pm.MODELS["birefnet-lite"]["package"], pm.MODELS["birefnet-lite"]["size"]))
        self.assertTrue(p["urls"][0].startswith("{SITE}/"))
        self.assertTrue(p["dest"].endswith("\\background\\birefnet-lite.onnx"))

    def test_runtime_package_is_a_pip_item_with_aliyun_first_and_pins_the_first_wheel(self):
        it = {i["package"]: i for i in self.manifest("matting.json")["items"]}[pm.RUNTIME_PACKAGE]
        self.assertEqual(it["kind"], "pip")
        self.assertEqual(it["python"], "{VENV:matting}")
        self.assertIn("aliyun", it["index_urls"][0])
        self.assertTrue(it["packages"][0].startswith("onnxruntime-directml=="), "the first pin is what the downloader uses to test a mirror")
        self.assertTrue(it.get("optional"))

    def test_agent_2_7_registers_the_job_kind_and_does_not_start_services_for_it(self):
        self.assertEqual(agent.VERSION, "2.7")
        self.assertIn("photo.matting", agent.HANDLERS)
        self.assertIsNone(agent.ServiceManager.prepare_for(object(), "photo.matting", True),
                          "a matting job must not start the photo kit (.NET) or touch Ollama/ComfyUI")

    def test_model_ids_unknown_models_are_refused_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = FakeJob(tmp, {"model": "nope", "image": "x.png"})
            with self.assertRaises(agent.JobError) as ctx:
                pm.run(job, FakeAgent(tmp))
            self.assertFalse(ctx.exception.retryable)


class StatusTests(unittest.TestCase):
    def test_missing_installed_downloading_queued_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({k: v["state"] for k, v in pm.model_states(FakeAgent(tmp)).items()},
                             {"u2netp": "missing", "isnet": "missing", "birefnet-lite": "missing"})
            os.makedirs(os.path.dirname(pm.model_file(tmp, "u2netp")))
            with open(pm.model_file(tmp, "u2netp"), "wb") as fh:
                fh.truncate(pm.MODELS["u2netp"]["size"])
            with mock.patch.dict(pm.MODELS["isnet"], {"size": 2048}):
                os.makedirs(os.path.dirname(pm.model_file(tmp, "isnet")), exist_ok=True)
                with open(pm.model_file(tmp, "isnet"), "wb") as fh:
                    fh.truncate(1000)                              # half-written: not installed
                self.assertEqual(pm.model_states(FakeAgent(tmp))["isnet"]["state"], "missing")
            st = pm.model_states(FakeAgent(tmp))
            self.assertEqual(st["u2netp"]["state"], "installed")
            dl = FakeDownloads(running=["matting-isnet"], progress=(40, 100), queue=["photo-background"])
            st = pm.model_states(FakeAgent(tmp, dl))
            self.assertEqual((st["isnet"]["state"], st["isnet"]["progress"]), ("downloading", 0.4))
            self.assertEqual(st["birefnet-lite"]["state"], "queued")
            dl = FakeDownloads(waiting={"packages": ["matting-isnet"], "until": "x"})
            self.assertEqual(pm.model_states(FakeAgent(tmp, dl))["isnet"]["state"], "queued", "held for the night window = queued")
            dl = FakeDownloads(error="matting:isnet-general-use: sha256 mismatch")
            st = pm.model_states(FakeAgent(tmp, dl))
            self.assertEqual(st["isnet"]["state"], "failed")
            self.assertIn("sha256", st["isnet"]["error"])

    def test_caps_keys_the_site_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = pm.caps(FakeAgent(tmp))
            self.assertIs(c["photo_matting"], True)
            self.assertEqual(set(c["matting_models"]), set(pm.ORDER))
            self.assertIn("ok", c["matting_runtime"])
            with mock.patch.dict(os.environ, {"NM_MATTING": "0"}):
                self.assertEqual(pm.caps(FakeAgent(tmp)), {"photo_matting": False})

    def test_a_missing_model_is_a_retryable_error_with_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = FakeJob(tmp, {"model": "isnet", "image": "x.png"})
            with self.assertRaises(agent.JobError) as ctx:
                pm.run(job, FakeAgent(tmp))
            self.assertTrue(ctx.exception.retryable)
            self.assertIn("matting-isnet", str(ctx.exception))


class PythonDiscoveryTests(unittest.TestCase):
    def test_no_python_with_onnxruntime_is_a_clear_retryable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pm, "candidate_pythons", return_value=[]), \
                    mock.patch.object(pm, "have_model", return_value=True):
                job = FakeJob(tmp, {"model": "u2netp", "image": "x.png"})
                with self.assertRaises(agent.JobError) as ctx:
                    pm.run(job, FakeAgent(tmp))
            self.assertTrue(ctx.exception.retryable)
            self.assertIn("matting-runtime", str(ctx.exception))

    @unittest.skipUnless(HAVE_RT, "needs numpy + onnxruntime + Pillow")
    def test_finds_this_python_and_prefers_a_gpu_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            py, info = pm.find_python(FakeAgent(tmp))
            self.assertTrue(py)
            self.assertTrue(info["pil"] or info["cv2"])
        fake = {"A": {"ort": "1", "np": "1", "providers": ["CPUExecutionProvider"], "pil": True, "cv2": False},
                "B": {"ort": "1", "np": "1", "providers": ["DmlExecutionProvider", "CPUExecutionProvider"], "pil": True, "cv2": False},
                "C": {"error": "no image library (Pillow or OpenCV)", "ort": "1"}}
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for n in fake:
                paths[n] = os.path.join(tmp, n)
                open(paths[n], "w").close()
            with mock.patch.object(pm, "candidate_pythons", return_value=list(paths.values())), \
                    mock.patch.object(pm, "probe_python", side_effect=lambda py, timeout=90: fake[os.path.basename(py)]):
                pm._PY_CACHE.clear()
                py, info = pm.find_python(FakeAgent(tmp))
            self.assertEqual(os.path.basename(py), "B", "DirectML beats the CPU-only environment; one without an image library never wins")

    def test_switched_off(self):
        with mock.patch.dict(os.environ, {"NM_MATTING": "0"}):
            self.assertEqual(pm.find_python(FakeAgent("x"))[0], None)


# ───────────────────────────────────────────── the real models (CPU, real subprocess, fake job)

@unittest.skipUnless(HAVE_RT, "needs numpy + onnxruntime + Pillow")
class RealModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-matting-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ag = FakeAgent(self.tmp)
        self.photo = make_photo(os.path.join(self.tmp, "photo.png"))

    def run_job(self, key, **payload):
        job = FakeJob(os.path.join(self.tmp, "job"), dict({"model": key, "image": "photo.png"}, **payload), image=self.photo)
        with mock.patch.dict(os.environ, {"NM_MATTING_PROVIDER": "cpu"}):
            meta = pm.run(job, self.ag)
        return job, meta

    def check_outputs(self, job, meta, size):
        self.assertEqual(meta["primary"], "cutout.png")
        rgba = Image.open(job.out("cutout.png"))
        mask = Image.open(job.out("mask.png"))
        self.assertEqual((rgba.mode, rgba.size), ("RGBA", size))
        self.assertEqual((mask.mode, mask.size), ("L", size))
        a = np.asarray(mask, dtype=np.float32) / 255.0
        h, w = a.shape
        self.assertGreater(a[h // 2 - 40:h // 2 + 40, w // 2 - 40:w // 2 + 40].mean(), 0.5, "the subject is kept")
        self.assertLess(a[:40, :40].mean(), 0.4, "the background goes")
        self.assertTrue((np.asarray(rgba)[..., 3] == np.asarray(mask)).all(), "the PNG's alpha IS the mask")
        info = json.load(open(job.out("photo-matting.json"), encoding="utf-8"))
        self.assertEqual(set(info) >= {"model", "seconds", "size", "device"}, True)
        self.assertEqual(info["size"], list(size))
        self.assertEqual(info["device"], "cpu")
        self.assertTrue(job.ticks and job.ticks[0][1].startswith("matting|"))

    def test_u2netp_end_to_end(self):
        src = model_src("u2netp")
        if not src:
            self.skipTest("u2netp.onnx not available")
        put_model(self.tmp, "u2netp", src)
        job, meta = self.run_job("u2netp")
        self.check_outputs(job, meta, (640, 480))
        self.assertEqual(meta["model"], "u2netp")

    def test_feather_and_keep_size_false(self):
        src = model_src("u2netp")
        if not src:
            self.skipTest("u2netp.onnx not available")
        put_model(self.tmp, "u2netp", src)
        big = make_photo(os.path.join(self.tmp, "big.png"), 2400, 1800)
        job = FakeJob(os.path.join(self.tmp, "job2"), {"model": "u2netp", "image": "big.png", "keep_size": False, "feather": 6}, image=big)
        with mock.patch.dict(os.environ, {"NM_MATTING_PROVIDER": "cpu"}):
            meta = pm.run(job, self.ag)
        self.assertEqual(meta["size"], [1600, 1200], "keep_size=false cuts the long side to 1600")
        job3 = FakeJob(os.path.join(self.tmp, "job3"), {"model": "u2netp", "image": "big.png", "keep_size": True}, image=big)
        with mock.patch.dict(os.environ, {"NM_MATTING_PROVIDER": "cpu"}):
            self.assertEqual(pm.run(job3, self.ag)["size"], [2400, 1800])

    def test_a_corrupt_model_file_is_a_normal_error_not_a_retry(self):
        dst = pm.model_file(self.tmp, "u2netp")
        os.makedirs(os.path.dirname(dst))
        with open(dst, "wb") as fh:
            fh.write(os.urandom(pm.MODELS["u2netp"]["size"]))           # the right size, garbage inside
        with self.assertRaises(agent.JobError) as ctx:
            self.run_job("u2netp")
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("خراب", str(ctx.exception))

    def test_missing_photo_in_the_package(self):
        src = model_src("u2netp")
        if not src:
            self.skipTest("u2netp.onnx not available")
        put_model(self.tmp, "u2netp", src)
        job = FakeJob(os.path.join(self.tmp, "job4"), {"model": "u2netp", "image": "nothere.png"})
        with self.assertRaises(agent.JobError) as ctx:
            pm.run(job, self.ag)
        self.assertFalse(ctx.exception.retryable)

    def test_cancel_stops_the_model_process(self):
        sleeper = os.path.join(self.tmp, "sleeper.py")
        with open(sleeper, "w") as fh:
            fh.write("import time\nprint('PHASE loading', flush=True)\ntime.sleep(60)\n")
        with mock.patch.object(pm, "have_model", return_value=True), mock.patch.object(pm, "__file__", sleeper):
            job = FakeJob(os.path.join(self.tmp, "job5"), {"model": "u2netp", "image": "photo.png"}, image=self.photo, cancel_after=1)
            t0 = time.time()
            with self.assertRaises(agent.Cancelled):
                pm.run(job, self.ag)
        self.assertLess(time.time() - t0, 30, "the cancel arrives at the next progress tick (<=5 s) and kills the child")

    def test_the_run_limit_kills_a_stuck_model(self):
        sleeper = os.path.join(self.tmp, "sleeper2.py")
        with open(sleeper, "w") as fh:
            fh.write("import time\ntime.sleep(60)\n")
        with mock.patch.object(pm, "have_model", return_value=True), mock.patch.object(pm, "__file__", sleeper), \
                mock.patch.dict(os.environ, {"NM_MATTING_TIMEOUT_S": "2"}):
            job = FakeJob(os.path.join(self.tmp, "job6"), {"model": "u2netp", "image": "photo.png"}, image=self.photo)
            with self.assertRaises(RuntimeError):
                pm.run(job, self.ag)

    def test_every_installed_model_that_fits_in_ram_passes_the_benchmark_on_the_cpu(self):
        keys = [k for k in pm.ORDER if model_src(k) and fits(k)]
        if not keys:
            self.skipTest("no model available / not enough free RAM")
        for key in keys:
            put_model(self.tmp, key, model_src(key))
        out = subprocess.run([sys.executable, os.path.join(PROC, "photo_matting.py"), "bench", "--data-root", self.tmp, "--provider", "cpu",
                              "--runs", "1", "--json"], stdin=subprocess.DEVNULL, capture_output=True, timeout=900)
        line = [l for l in out.stdout.decode("utf-8", "replace").splitlines() if l.startswith("RESULT ")]
        self.assertTrue(line, out.stderr.decode("utf-8", "replace")[-400:])
        res = json.loads(line[-1][7:])["results"]
        self.assertEqual([r["model"] for r in res], list(pm.ORDER))
        for r in res:
            if r["model"] not in keys:
                self.assertIn("not installed", r["error"])
                continue
            self.assertNotIn("error", r, r)
            self.assertTrue(r["plausible"], r)
            self.assertEqual(r["device"], "cpu")

    def test_bench_as_a_job_returns_timings_and_a_picture(self):
        src = model_src("u2netp")
        if not src:
            self.skipTest("u2netp.onnx not available")
        put_model(self.tmp, "u2netp", src)
        job = FakeJob(os.path.join(self.tmp, "job7"), {"model": "u2netp", "bench": True})
        with mock.patch.dict(os.environ, {"NM_MATTING_PROVIDER": "cpu"}):
            meta = pm.run(job, self.ag)
        self.assertTrue(meta["bench"] and meta["plausible"])
        self.assertTrue(os.path.isfile(job.out("cutout.png")) and os.path.isfile(job.out("photo-matting.json")))

    def test_cli_status_and_runtime_flag(self):
        out = subprocess.run([sys.executable, os.path.join(PROC, "photo_matting.py"), "status", "--data-root", self.tmp],
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        data = json.loads(out.stdout.decode("utf-8"))
        self.assertEqual(set(data["models"]), set(pm.ORDER))
        self.assertTrue(data["python"])
        self.assertEqual(subprocess.call([sys.executable, os.path.join(PROC, "photo_matting.py"), "status", "--runtime-ok", "--data-root", self.tmp],
                                         stdin=subprocess.DEVNULL, timeout=120), 0)


if __name__ == "__main__":
    unittest.main()
