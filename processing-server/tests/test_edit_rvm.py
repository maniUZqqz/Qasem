"""agent 2.5: Robust Video Matting on the node - the pure rules (downsample ratio, which Python, the manifest), the model fetch from
the site (lazy, checked, resumable through nm_fetch), the heartbeat's engine + cache report, Update.bat's small-model step, and -
when numpy + onnxruntime and the real 14 MB model are on this machine - the real model on a real clip: state carried, matte video
the right size, cancel stops the model, the model fetched by the first job.

    python -m unittest tests/test_edit_rvm.py        (from the processing folder; the real-model tests skip themselves otherwise)
The real model is looked for in $NM_RVM_TEST_MODEL, then in the site's mirror folder (data/up3d/downloads) next to this checkout.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
os.environ["NM_SMALL_MODELS"] = "0"
import agent  # noqa: E402
import download_models as dm  # noqa: E402
import edit_jobs  # noqa: E402
import edit_render  # noqa: E402
import edit_rvm  # noqa: E402
import update  # noqa: E402

FF = edit_render.ffmpeg_exe(agent)
try:
    import numpy as np  # noqa: E402
    import onnxruntime  # noqa: E402,F401
    HAVE_ORT = True
except Exception:  # noqa: BLE001
    HAVE_ORT = False


def rd(path, mode="rb"):
    with open(path, mode) as fh:
        return fh.read()


def wr(path, data=b"x"):
    with open(path, "wb") as fh:
        fh.write(data)


def real_model():
    for cand in (os.environ.get("NM_RVM_TEST_MODEL", ""),
                 os.path.join(os.path.dirname(PROC), "data", "up3d", "downloads", edit_rvm.MODEL_FILE),
                 "/var/www/NM/upmarket/data/up3d/downloads/" + edit_rvm.MODEL_FILE):
        if cand and os.path.isfile(cand):
            try:
                if edit_rvm.verified(cand):
                    return cand
            except Exception:  # noqa: BLE001
                pass
    return None


MODEL = real_model()


class FakeSite(BaseHTTPRequestHandler):
    """The site as the node sees it: the downloads folder ({site}/3d/files/downloads/<name>) and the job progress endpoint
    (which can answer {"cancel": true} after N reports, like the real one)."""
    files = {}
    gets = []
    progress_posts = 0
    cancel_after = 0

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/octet-stream"):
        if isinstance(body, (dict, list)):
            body, ctype = json.dumps(body).encode(), "application/json"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        name = self.path.split("?")[0].rsplit("/", 1)[-1]
        if self.path.startswith("/3d/files/downloads/") and name in self.files:
            type(self).gets.append(name)
            return self._send(200, self.files[name])
        self._send(404, {"error": "no"})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/progress/"):
            type(self).progress_posts += 1
            cancel = self.cancel_after and type(self).progress_posts >= self.cancel_after
            return self._send(200, {"ok": True, "cancel": bool(cancel)})
        self._send(200, {})

    def do_PUT(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(200, {})


class Harness:
    """agent.* pointed at the fake site with a temp data folder (what edit_jobs / edit_rvm see)."""

    def __init__(self, files=None, cancel_after=0):
        FakeSite.files = files or {}
        FakeSite.gets = []
        FakeSite.progress_posts = 0
        FakeSite.cancel_after = cancel_after
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.tmp = tempfile.mkdtemp(prefix="nm-rvm-node-")
        self.patches = [
            mock.patch.object(agent, "DATA", self.tmp), mock.patch.object(agent, "WORK", os.path.join(self.tmp, "work")),
            mock.patch.object(agent, "CONFIG", {"name": "TEST-NODE", "token": "tok", "site": self.base}),
            mock.patch.object(agent, "site_base", lambda: self.base), mock.patch.object(agent, "MANAGER", None),
        ]
        for p in self.patches:
            p.start()

    def close(self):
        for p in self.patches:
            p.stop()
        self.srv.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def job(self, uid, payload):
        job = agent.Job(agent.Site(self.base, "tok"), {"uid": uid, "kind": "edit.matte", "payload": payload})
        shutil.rmtree(job.dir, ignore_errors=True)
        os.makedirs(job.inputs, exist_ok=True)
        os.makedirs(job.outputs, exist_ok=True)
        return job


def make_clip(path, seconds=2, size="160x120", rate=25):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d:duration=%s" % (size, rate, seconds), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", path], check=True, stdin=subprocess.DEVNULL, capture_output=True)


def frames_and_size(path):
    out = subprocess.run([FF, "-hide_banner", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"], stdin=subprocess.DEVNULL, capture_output=True).stderr.decode(
        "utf-8", "replace")
    w, h = edit_rvm.probe_size(FF, path)
    import re

    n = re.findall(r"frame=\s*(\d+)", out)
    return (int(n[-1]) if n else 0), w, h


class PureRulesTests(unittest.TestCase):
    def test_the_downsample_ratio_follows_the_resolution_like_the_models_own_guidance(self):
        table = {(320, 240): 1.0, (512, 512): 1.0, (640, 360): 0.75, (404, 720): 0.667, (720, 404): 0.667, (1280, 720): 0.375,
                 (1920, 1080): 0.25, (2160, 3840): 0.125, (3840, 2160): 0.125, (7680, 4320): 0.125}
        for (w, h), want in table.items():
            self.assertEqual(edit_rvm.downsample_ratio(w, h), want, (w, h))
            # the network always sees a long side in the 256-512 band (or the whole small picture)
            seen = max(w, h) * edit_rvm.downsample_ratio(w, h)
            if max(w, h) <= 4096:
                self.assertTrue(seen <= 520 and (seen >= 240 or max(w, h) < 256), (w, h, seen))

    def test_the_matte_video_gets_even_sides(self):
        self.assertEqual(edit_rvm.even_size(405, 721), (404, 720))
        self.assertEqual(edit_rvm.even_size(1, 1), (2, 2))

    def test_the_manifest_is_the_one_place_that_knows_the_model_and_the_downloader_picks_it_up_by_default(self):
        item = edit_rvm.manifest_item()
        self.assertEqual((item["package"], item["kind"], item["size"]), (edit_rvm.PACKAGE, "file", 14975696))
        self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(item["urls"][0].startswith("{SITE}/3d/files/downloads/"), "the site's mirror is tried first")
        self.assertTrue(all(u.endswith("/" + edit_rvm.MODEL_FILE) for u in item["urls"]))
        self.assertTrue(item["dest"].endswith("\\" + edit_rvm.MODEL_FILE) and "{MODELS}" in item["dest"])
        self.assertFalse(item.get("optional"), "not optional: the agent's start-up download and Download-Models.bat bring it by themselves")
        groups = [g for g in dm.load_manifests() if g["_file"] == edit_rvm.MANIFEST_NAME]
        self.assertEqual(len(groups), 1)
        rows = dm.plan(groups, [], [])
        self.assertEqual([it["id"] for _g, it in rows], [edit_rvm.MANIFEST_ID], "in the default set")
        self.assertEqual(len(dm.plan(groups, [edit_rvm.PACKAGE], [])), 1, "and by its package name")
        self.assertIn("GPL-3.0", groups[0]["license_note"])
        # where the downloader puts it is where the node looks for it
        ctx = dm.Context(interactive=False, check=True)
        self.assertEqual(os.path.normcase(os.path.normpath(ctx.expand(item["dest"]))),
                         os.path.normcase(os.path.normpath(edit_rvm.model_file(dm.NM_HOME))))

    def test_the_site_mirror_matches_the_manifest_when_it_is_on_this_machine(self):
        if MODEL is None:
            self.skipTest("the mirrored model is not on this machine")
        self.assertEqual(os.path.getsize(MODEL), edit_rvm.manifest_item()["size"])
        self.assertTrue(edit_rvm.verified(MODEL))


class WhichPythonTests(unittest.TestCase):
    def setUp(self):
        edit_rvm._PY_CACHE.clear()
        self.tmp = tempfile.mkdtemp(prefix="nm-rvm-py-")
        self.pys = {}
        for name in ("agent", "voice", "other"):
            p = os.path.join(self.tmp, name, "python")
            os.makedirs(os.path.dirname(p))
            open(p, "w").close()
            self.pys[name] = p

    def tearDown(self):
        edit_rvm._PY_CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def probe(self, answers):
        return lambda py, timeout=90: answers[os.path.basename(os.path.dirname(py))]

    def test_a_python_with_a_gpu_provider_beats_a_cpu_only_one_and_one_without_onnxruntime_is_skipped(self):
        answers = {"agent": {"error": "No module named 'onnxruntime'"}, "voice": {"ort": "1.20", "np": "2.0", "providers": ["CPUExecutionProvider"]},
                   "other": {"ort": "1.23", "np": "2.0", "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"]}}
        with mock.patch.object(edit_rvm, "candidate_pythons", lambda a=None: list(self.pys.values())), \
                mock.patch.object(edit_rvm, "probe_python", self.probe(answers)):
            py, info = edit_rvm.find_python()
            self.assertEqual(py, self.pys["other"])
            self.assertEqual(edit_rvm.status(None)["provider"], "CUDA")
            answers["other"] = {"error": "x"}
            edit_rvm._PY_CACHE.clear()
            py, info = edit_rvm.find_python()
            self.assertEqual(py, self.pys["voice"])
            self.assertEqual(edit_rvm.status(None)["provider"], "CPU")

    def test_no_python_with_onnxruntime_says_so_and_rvm_can_be_switched_off(self):
        answers = {k: {"error": "No module named 'numpy'"} for k in self.pys}
        with mock.patch.object(edit_rvm, "candidate_pythons", lambda a=None: list(self.pys.values())), \
                mock.patch.object(edit_rvm, "probe_python", self.probe(answers)):
            py, why = edit_rvm.find_python()
            self.assertIsNone(py)
            self.assertIn("numpy + onnxruntime", why)
            st = edit_rvm.status(None)
            self.assertEqual((st["runtime"], st["model"]), (False, False))
            with mock.patch.dict(os.environ, {"NM_RVM": "0"}):
                self.assertEqual(edit_rvm.find_python()[0], None)
                self.assertFalse(edit_rvm.enabled())

    def test_the_owners_python_comes_first_and_the_agents_venvs_are_looked_at(self):
        data = tempfile.mkdtemp(prefix="nm-rvm-venv-")
        try:
            for rel in ("venvs/moss/Scripts/python.exe", "venvs/sfx/bin/python"):
                p = os.path.join(data, *rel.split("/"))
                os.makedirs(os.path.dirname(p))
                open(p, "w").close()
            fake = mock.Mock(DATA=data, voice_venv_python=lambda: os.path.join(data, "none"))
            with mock.patch.dict(os.environ, {"NM_RVM_PYTHON": self.pys["other"]}):
                cands = edit_rvm.candidate_pythons(fake)
            self.assertEqual(cands[0], self.pys["other"])
            self.assertEqual(cands[1], sys.executable)
            self.assertTrue(any(c.endswith(os.path.join("venvs", "moss", "Scripts", "python.exe")) for c in cands))
            self.assertTrue(any(c.endswith(os.path.join("venvs", "sfx", "bin", "python")) for c in cands))
        finally:
            shutil.rmtree(data, ignore_errors=True)

    @unittest.skipUnless(HAVE_ORT, "numpy + onnxruntime are not in this Python")
    def test_the_real_probe_of_this_python(self):
        info = edit_rvm.probe_python(sys.executable)
        self.assertNotIn("error", info)
        self.assertIn("CPUExecutionProvider", info["providers"])


class FetchTests(unittest.TestCase):
    """The model comes from the site (checked, resumable through nm_fetch); a wrong or missing file says why."""

    BYTES = os.urandom(300_000)

    def setUp(self):
        edit_rvm._SHA_OK.clear()
        self.item = {"id": edit_rvm.MANIFEST_ID, "urls": ["{SITE}/3d/files/downloads/" + edit_rvm.MODEL_FILE], "dest": "x", "size": len(self.BYTES),
                     "sha256": hashlib.sha256(self.BYTES).hexdigest()}
        self.patch = mock.patch.object(edit_rvm, "manifest_item", lambda path=None: self.item)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_the_first_job_fetches_it_from_the_site_once_and_checks_it(self):
        h = Harness({edit_rvm.MODEL_FILE: self.BYTES})
        try:
            say = []
            path = edit_rvm.ensure_model(agent, say.append)
            self.assertEqual(path, edit_rvm.model_file(h.tmp))
            self.assertEqual(rd(path), self.BYTES)
            self.assertTrue(edit_rvm.verified(path))
            self.assertEqual(FakeSite.gets, [edit_rvm.MODEL_FILE])
            self.assertTrue(say and say[0].startswith("model|"))
            self.assertFalse(os.path.exists(path + ".lazy") or os.path.exists(path + ".lazy.part"))
            self.assertEqual(edit_rvm.ensure_model(agent), path)
            self.assertEqual(FakeSite.gets, [edit_rvm.MODEL_FILE], "the second job downloads nothing")
        finally:
            h.close()

    def test_a_file_with_the_wrong_checksum_is_refused_and_not_kept(self):
        h = Harness({edit_rvm.MODEL_FILE: self.BYTES[:-1] + b"X"})
        try:
            with self.assertRaises(edit_rvm.Unavailable) as ctx:
                edit_rvm.ensure_model(agent, stall=5)
            self.assertIn("could not be fetched", str(ctx.exception))
            self.assertFalse(os.path.exists(edit_rvm.model_file(h.tmp)))
        finally:
            h.close()

    def test_a_site_without_the_file_is_a_clear_reason_not_a_crash(self):
        h = Harness({})
        try:
            with self.assertRaises(edit_rvm.Unavailable) as ctx:
                edit_rvm.ensure_model(agent, stall=5)
            self.assertIn("404", str(ctx.exception))
        finally:
            h.close()

    def test_a_node_that_does_not_know_its_site_has_nothing_to_fetch_from(self):
        h = Harness({edit_rvm.MODEL_FILE: self.BYTES})
        try:
            with mock.patch.object(agent, "site_base", side_effect=RuntimeError("no site")):
                with self.assertRaises(edit_rvm.Unavailable) as ctx:
                    edit_rvm.ensure_model(agent)
            self.assertIn("no download address", str(ctx.exception))
        finally:
            h.close()

    def test_the_model_token_is_never_sent_to_another_host(self):
        import nm_fetch

        self.item["urls"] = ["https://example.invalid/m.onnx"]
        seen = {}

        def fake_fetch(url, dest, headers=None, **kw):
            seen["headers"] = headers
            raise nm_fetch.FetchError("down")

        h = Harness({})
        try:
            with mock.patch.object(nm_fetch, "fetch", fake_fetch):
                with self.assertRaises(edit_rvm.Unavailable):
                    edit_rvm.ensure_model(agent)
            self.assertEqual(seen["headers"], {})
        finally:
            h.close()


class HeartbeatTests(unittest.TestCase):
    """caps.edit: which matting engine can work, and which originals are cached."""

    def setUp(self):
        self.h = Harness()
        edit_render._CAPS["state"] = None

    def tearDown(self):
        edit_render._CAPS["state"] = None
        self.h.close()

    def caps(self, runtime, model):
        st = {"runtime": runtime, "model": model, "provider": "CUDA" if runtime else "", "ort": "1.23.2" if runtime else ""}
        with mock.patch.object(edit_rvm, "status", lambda a=None, probe=True: st), mock.patch.object(edit_rvm, "have_model", lambda root: model):
            edit_render._CAPS["state"] = None
            return edit_render.caps(agent, wait=True)

    def test_the_engine_is_rvm_when_the_runtime_and_the_model_are_here(self):
        c = self.caps(True, True)
        self.assertEqual((c["matte"], c["matte_engine"]), (True, "rvm"))
        self.assertEqual(c["rvm"], {"runtime": True, "model": True, "provider": "CUDA", "ort": "1.23.2"})
        self.assertNotIn("rvm_probe", c)

    def test_with_the_runtime_but_no_model_the_first_job_fetches_it(self):
        c = self.caps(True, False)
        self.assertEqual((c["matte"], c["matte_engine"]), (True, "rvm-pending"))

    def test_without_a_runtime_only_the_old_path_counts(self):
        c = self.caps(False, False)
        self.assertEqual((c["matte"], c["matte_engine"]), (False, ""))
        birefnet = agent.kit_dir(*edit_render.MATTE_MODEL_REL)
        os.makedirs(os.path.dirname(birefnet))
        wr(birefnet)
        c = self.caps(False, False)
        self.assertEqual((c["matte"], c["matte_engine"]), (True, "birefnet"))
        c = self.caps(True, False)
        self.assertEqual(c["matte_engine"], "birefnet", "the old model that is already here wins until RVM is on disk")
        c = self.caps(True, True)
        self.assertEqual(c["matte_engine"], "rvm")

    def test_the_cache_report_names_the_originals_most_recent_first_and_skips_half_files(self):
        folder = edit_render.cache_dir(agent)
        shas = [hashlib.sha256(bytes([i])).hexdigest() for i in range(3)]
        for i, sha in enumerate(shas):
            p = os.path.join(folder, sha + ".mp4")
            wr(p, b"v")
            os.utime(p, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
        wr(os.path.join(folder, "f" * 64 + ".mp4.part"), b"p")
        wr(os.path.join(folder, "notes.txt"), b"n")
        self.assertEqual(edit_render.cache_listing(agent), [s[:16] for s in reversed(shas)])
        self.assertEqual(len(edit_render.cache_listing(agent, limit=2)), 2)
        c = self.caps(False, False)
        self.assertEqual(c["cache"], [s[:16] for s in reversed(shas)])


class UpdateBatTests(unittest.TestCase):
    """Update.bat also brings the 14 MB model from the site (never fatal)."""

    BYTES = os.urandom(200_000)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nm-rvm-upd-")
        os.makedirs(os.path.join(self.root, "downloads"))
        self.data = tempfile.mkdtemp(prefix="nm-rvm-upd-data-")
        item = {"id": edit_rvm.MANIFEST_ID, "dest": "{MODELS}\\video-matting\\" + edit_rvm.MODEL_FILE, "size": len(self.BYTES),
                "sha256": hashlib.sha256(self.BYTES).hexdigest()}
        with open(os.path.join(self.root, "downloads", edit_rvm.MANIFEST_NAME), "w") as fh:
            json.dump({"items": [item]}, fh)
        self.env = mock.patch.dict(os.environ, {"NM_SMALL_MODELS": "1", "NM_DATA": self.data})
        self.env.start()
        self.dest = os.path.join(self.data, "models", "video-matting", edit_rvm.MODEL_FILE)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def test_the_model_arrives_with_the_update_and_is_not_fetched_twice(self):
        h = Harness({edit_rvm.MODEL_FILE: self.BYTES})
        lines = []
        try:
            update.fetch_small_models(self.root, h.base, lines.append)
            self.assertEqual(rd(self.dest), self.BYTES, lines)
            update.fetch_small_models(self.root, h.base, lines.append)
            self.assertEqual(FakeSite.gets, [edit_rvm.MODEL_FILE])
            self.assertTrue(any("already here" in ln for ln in lines))
        finally:
            h.close()

    def test_a_site_that_cannot_give_it_is_a_note_not_an_error(self):
        h = Harness({})
        lines = []
        try:
            update.fetch_small_models(self.root, h.base, lines.append, stall=5)
            self.assertFalse(os.path.exists(self.dest))
            self.assertTrue(any(ln.startswith("NOTE:") and "tries again" in ln for ln in lines), lines)
        finally:
            h.close()

    def test_it_can_be_switched_off_and_a_folder_without_the_manifest_is_fine(self):
        h = Harness({edit_rvm.MODEL_FILE: self.BYTES})
        try:
            with mock.patch.dict(os.environ, {"NM_SMALL_MODELS": "0"}):
                update.fetch_small_models(self.root, h.base, lambda m: None)
            self.assertEqual(FakeSite.gets, [])
            os.remove(os.path.join(self.root, "downloads", edit_rvm.MANIFEST_NAME))
            update.fetch_small_models(self.root, h.base, lambda m: None)
            self.assertEqual(FakeSite.gets, [])
        finally:
            h.close()


@unittest.skipUnless(HAVE_ORT and MODEL and FF, "needs numpy + onnxruntime, the real RVM model (the site's mirror) and ffmpeg")
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        edit_rvm._PY_CACHE.clear()
        cls.tmp = tempfile.mkdtemp(prefix="nm-rvm-real-")
        cls.clip = os.path.join(cls.tmp, "clip.mp4")
        make_clip(cls.clip, seconds=2, size="160x120", rate=25)
        cls.model_bytes = rd(MODEL)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_state_is_carried_from_frame_to_frame_and_changes_the_answer(self):
        rng = np.random.default_rng(3)
        frames = [(rng.random((120, 160, 3)) * 255).astype(np.uint8) for _ in range(4)]
        m = edit_rvm.Matter(MODEL, "cpu")
        self.assertEqual([r.shape for r in m.rec], [(1, 1, 1, 1)] * 4, "the state starts empty")
        a = m.step(frames[0])
        self.assertEqual((a.dtype, a.shape), (np.uint8, (120, 160)))
        self.assertEqual(m.rec[0].shape[0:2], (1, 16), "after one frame the state is the network's own")
        carried = None
        for f in frames[1:]:
            carried = m.step(f)
        fresh = edit_rvm.Matter(MODEL, "cpu").step(frames[3])
        self.assertFalse(np.array_equal(carried, fresh), "the same frame gives another matte once the state of earlier frames is in")
        stateless = edit_rvm.Matter(MODEL, "cpu", stateful=False)
        for f in frames[1:]:
            last = stateless.step(f)
        self.assertTrue(np.array_equal(last, fresh), "a stateless matter forgets everything, like a per-frame model")

    def test_warming_up_settles_the_state_on_the_first_frame(self):
        rng = np.random.default_rng(4)
        f = (rng.random((120, 160, 3)) * 255).astype(np.uint8)
        a, b = edit_rvm.Matter(MODEL, "cpu"), edit_rvm.Matter(MODEL, "cpu")
        b.warm(f, 2)
        self.assertFalse(np.array_equal(a.step(f), b.step(f)))

    def test_the_job_makes_a_matte_video_of_the_right_size_with_the_state_carried(self):
        h = Harness()
        try:
            dest = edit_rvm.model_file(h.tmp)
            os.makedirs(os.path.dirname(dest))
            shutil.copy(MODEL, dest)
            job = h.job("t-rvm", {"video": "clip.mp4", "fps": 10, "duration": 2.0, "size": [160, 120]})
            shutil.copy(self.clip, os.path.join(job.inputs, "clip.mp4"))
            with mock.patch.object(edit_rvm, "find_python", lambda agent=None, probe=True: (sys.executable, {"ort": "t", "providers": ["CPUExecutionProvider"]})):
                meta = edit_jobs.run_matte(job, agent)
            self.assertEqual((meta["primary"], meta["model"], meta["provider"]), ("matte.mp4", "rvm-mobilenetv3", "CPU"))
            self.assertEqual(meta["frames"], 20, "2 s at 10 per second")
            self.assertEqual(meta["ratio"], 1.0, "a 160x120 picture is not downsampled")
            n, w, hh = frames_and_size(job.out("matte.mp4"))
            self.assertEqual((n, w, hh), (20, 160, 120))
            self.assertGreaterEqual(FakeSite.progress_posts, 2, "progress is reported while it runs")
        finally:
            h.close()

    def test_a_clip_bigger_than_the_network_likes_is_downsampled_by_its_resolution(self):
        h = Harness()
        try:
            dest = edit_rvm.model_file(h.tmp)
            os.makedirs(os.path.dirname(dest))
            shutil.copy(MODEL, dest)
            big = os.path.join(self.tmp, "big.mp4")
            make_clip(big, seconds=1, size="720x404", rate=10)
            job = h.job("t-rvm-big", {"video": "big.mp4", "fps": 5, "duration": 1.0})          # no size in the payload: it is read from the clip
            shutil.copy(big, os.path.join(job.inputs, "big.mp4"))
            with mock.patch.object(edit_rvm, "find_python", lambda agent=None, probe=True: (sys.executable, {"ort": "t", "providers": ["CPUExecutionProvider"]})):
                meta = edit_jobs.run_matte(job, agent)
            self.assertEqual((meta["ratio"], meta["frames"]), (0.667, 5))
            self.assertEqual(frames_and_size(job.out("matte.mp4"))[1:], (720, 404))
        finally:
            h.close()

    def test_the_first_job_fetches_the_model_from_the_site_when_it_is_missing(self):
        h = Harness({edit_rvm.MODEL_FILE: self.model_bytes})
        try:
            self.assertFalse(edit_rvm.have_model(h.tmp))
            job = h.job("t-rvm-lazy", {"video": "clip.mp4", "fps": 5, "duration": 2.0, "size": [160, 120]})
            shutil.copy(self.clip, os.path.join(job.inputs, "clip.mp4"))
            with mock.patch.object(edit_rvm, "find_python", lambda agent=None, probe=True: (sys.executable, {"ort": "t", "providers": ["CPUExecutionProvider"]})):
                meta = edit_jobs.run_matte(job, agent)
            self.assertEqual(meta["model"], "rvm-mobilenetv3")
            self.assertEqual(FakeSite.gets, [edit_rvm.MODEL_FILE])
            self.assertTrue(edit_rvm.have_model(h.tmp) and edit_rvm.verified(edit_rvm.model_file(h.tmp)))
        finally:
            h.close()

    def test_cancelling_from_the_site_stops_the_model_process(self):
        h = Harness(cancel_after=3)
        procs = []
        real = subprocess.Popen

        def spy(*a, **k):
            p = real(*a, **k)
            procs.append((a[0], p))
            return p

        try:
            dest = edit_rvm.model_file(h.tmp)
            os.makedirs(os.path.dirname(dest))
            shutil.copy(MODEL, dest)
            long_clip = os.path.join(self.tmp, "long.mp4")
            make_clip(long_clip, seconds=30, size="320x240", rate=25)
            job = h.job("t-rvm-cancel", {"video": "long.mp4", "fps": 25, "duration": 30.0, "size": [320, 240]})
            shutil.copy(long_clip, os.path.join(job.inputs, "long.mp4"))
            with mock.patch.object(edit_rvm, "find_python", lambda agent=None, probe=True: (sys.executable, {"ort": "t", "providers": ["CPUExecutionProvider"]})), \
                    mock.patch.object(edit_rvm.subprocess, "Popen", spy):
                with self.assertRaises(agent.Cancelled):
                    edit_jobs.run_matte(job, agent)
            mine = [p for cmd, p in procs if edit_rvm.__file__.replace(".pyc", ".py") in " ".join(str(c) for c in cmd)]
            self.assertTrue(mine, "the model process was started")
            for p in mine:
                self.assertIsNotNone(p.poll(), "and it is stopped")
        finally:
            h.close()


class FallbackTests(unittest.TestCase):
    """RVM that cannot start leaves the old BiRefNet path in charge, with the reason - or says what is needed."""

    def setUp(self):
        self.h = Harness()
        if FF:
            self.clip = os.path.join(self.h.tmp, "c.mp4")
            make_clip(self.clip, seconds=1, size="160x120", rate=10)

    def tearDown(self):
        self.h.close()

    @unittest.skipUnless(FF, "ffmpeg is not installed")
    def test_without_any_python_for_it_and_without_the_old_model_the_job_says_both_needs(self):
        job = self.h.job("t-fb1", {"video": "c.mp4", "fps": 6, "duration": 1.0, "size": [160, 120]})
        shutil.copy(self.clip, os.path.join(job.inputs, "c.mp4"))
        with mock.patch.object(edit_rvm, "find_python", lambda agent=None, probe=True: (None, "no Python on this computer has numpy + onnxruntime (test)")):
            with self.assertRaises(agent.JobError) as ctx:
                edit_jobs.run_matte(job, agent)
        text = str(ctx.exception)
        self.assertIn("photo-background", text)
        self.assertIn("RVM: no Python on this computer has numpy + onnxruntime", text)
        self.assertFalse(ctx.exception.retryable)

    @unittest.skipUnless(FF, "ffmpeg is not installed")
    def test_nm_rvm_zero_keeps_the_old_path_and_says_why(self):
        job = self.h.job("t-fb2", {"video": "c.mp4", "fps": 6, "duration": 1.0, "size": [160, 120]})
        shutil.copy(self.clip, os.path.join(job.inputs, "c.mp4"))
        with mock.patch.dict(os.environ, {"NM_RVM": "0"}):
            with self.assertRaises(agent.JobError) as ctx:
                edit_jobs.run_matte(job, agent)
        self.assertIn("NM_RVM=0", str(ctx.exception))

    @unittest.skipUnless(FF, "ffmpeg is not installed")
    def test_a_model_that_cannot_be_fetched_falls_back_to_the_old_path(self):
        job = self.h.job("t-fb3", {"video": "c.mp4", "fps": 6, "duration": 1.0, "size": [160, 120]})
        shutil.copy(self.clip, os.path.join(job.inputs, "c.mp4"))
        with mock.patch.object(edit_rvm, "find_python", lambda agent=None, probe=True: (sys.executable, {})):
            with self.assertRaises(agent.JobError) as ctx:                         # the site has no model file (404) and BiRefNet is not installed
                with mock.patch.object(edit_rvm, "manifest_item", lambda path=None: {"id": "x", "urls": ["{SITE}/3d/files/downloads/none.onnx"], "size": 5, "sha256": "0" * 64}):
                    edit_jobs.run_matte(job, agent)
        self.assertIn("photo-background", str(ctx.exception))
        self.assertIn("could not be fetched", str(ctx.exception))


class SiteAndNodeAgree(unittest.TestCase):
    def test_the_agent_version_was_raised_for_this_work(self):
        self.assertGreaterEqual(tuple(int(x) for x in agent.VERSION.split(".")), (2, 13))

    def test_the_diagnostic_names_the_engine(self):
        self.assertIn("video matting (RVM)", rd(os.path.join(PROC, "agent.py"), "r"))


if __name__ == "__main__":
    unittest.main()
