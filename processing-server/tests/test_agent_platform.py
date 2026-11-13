"""agent 2.11 end to end on the agent module: kinds advertised, device verdict in the finish meta, the outbox on a dead line,
the panel command «bootstrap», autostart application. A fake site stands in for the network."""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402
import outbox as ob  # noqa: E402


class FakeSite:
    """Just enough of agent.Site for run_job: package download, progress, upload, finish. `down` calls fail like a dead line."""

    def __init__(self, payload=None):
        self.payload = payload or {}
        self.down = 0
        self.finished = []
        self.uploaded = {}
        self.progress_calls = []

    def _fail(self):
        if self.down > 0:
            self.down -= 1
            raise agent.SiteError("site unreachable (http://x): <urlopen error [WinError 10060] timed out>")

    def download(self, path, dest, timeout=600, attempts=5):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("payload.json", json.dumps({"payload": self.payload, "timeout_s": 60}))
        with open(dest, "wb") as fh:
            fh.write(b.getvalue())

    def post(self, path, data=None, timeout=60):
        if path.endswith("/progress/"):
            self.progress_calls.append(data)
            return {"cancel": False}
        self._fail()
        if path.endswith("/finish/"):
            self.finished.append(data)
        return {"ok": True}

    def upload(self, path, files, timeout=1800, attempts=8, sleep=None):
        self._fail()
        for k, (name, content) in files.items():
            self.uploaded[name] = content
        return {"ok": True}

    def get_json(self, path, timeout=30):
        self._fail()
        return {"size": 0}

    def _req(self, *a, **kw):
        self._fail()
        return {"size": 0, "complete": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(os.path.join(self.tmp, "logs"))
        self.box = ob.Outbox(os.path.join(self.tmp, "outbox"), agent)
        self.patches = [mock.patch.object(agent, "DATA", self.tmp), mock.patch.object(agent, "WORK", self.work),
                        mock.patch.object(agent, "LOGS", os.path.join(self.tmp, "logs")),
                        mock.patch.object(agent, "OUTBOX", self.box), mock.patch.object(agent, "CONNECT", ob.Connectivity()),
                        mock.patch.object(agent, "MANAGER", None), mock.patch.dict(agent.CONFIG, {"name": "unit"}),
                        mock.patch.dict(agent.CMD, {"seen": set(), "restart": None})]
        for p in self.patches:
            p.start()
        os.makedirs(self.work, exist_ok=True)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_with(self, kind, handler, site=None, payload=None):
        site = site or FakeSite(payload)
        with mock.patch.dict(agent.HANDLERS, {kind: handler}):
            agent.run_job(site, {"uid": "11111111-2222-3333-4444-555555555555", "kind": kind, "payload": payload or {}, "timeout_s": 60})
        return site


class KindsAndCapsTests(unittest.TestCase):
    def test_the_new_modules_registered_their_kinds(self):
        for kind in ("selftest.gpu", "selftest.ffmpeg", "asr.transcribe", "ollama.chat", "ollama.generate", "photo.matting", "edit.render"):
            self.assertIn(kind, agent.HANDLERS, kind)

    def test_ollama_kinds_use_the_streaming_handler(self):
        self.assertIs(agent.HANDLERS["ollama.generate"], agent.h_ollama_stream)
        self.assertIs(agent.HANDLERS["ollama.chat"], agent.h_ollama_stream)

    def test_the_heartbeat_advertises_kinds_lanes_and_relays(self):
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.object(agent, "DATA", tmp), mock.patch.object(agent, "LOGS", tmp):
                caps = agent.Capabilities("unit", 1).probe()
            self.assertEqual(caps["agent"], agent.VERSION)
            self.assertIn("selftest.gpu", caps["kinds"])
            self.assertEqual(caps["kinds"], sorted(caps["kinds"]))
            self.assertEqual(caps["lanes"]["light"], agent.LIGHT_SLOTS)
            self.assertEqual(set(caps["lanes"]["light_kinds"]), set(agent.LIGHT_KINDS))
            self.assertIn("comfy", caps["http_relays"])
            self.assertIn("bootstrap", caps["commands"])
            self.assertIn("autostart", caps)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_light_lane_takes_only_gpu_neutral_kinds(self):
        for kind in agent.LIGHT_KINDS:
            self.assertFalse(agent.gpu.expects_gpu(kind) and kind != "selftest.gpu", kind)
        for heavy in ("comfy.graph", "comfy.profile", "edit.render", "voice.music", "ollama.generate"):
            self.assertNotIn(heavy, agent.LIGHT_KINDS)


class RunJobTests(Base):
    def test_a_finished_job_carries_the_device_verdict_and_leaves_nothing_behind(self):
        def handler(job):
            with open(job.out("r.json"), "w") as fh:
                fh.write("{}")
            return {"primary": "r.json", "device": "cuda", "device_note": "ComfyUI: RTX 3060"}
        site = self.run_with("comfy.graph", handler)
        self.assertEqual(len(site.finished), 1)
        body = site.finished[0]
        self.assertTrue(body["ok"])
        self.assertEqual(body["meta"]["device"], "cuda")
        self.assertEqual(body["meta"]["node"], "unit")
        self.assertEqual(body["meta"]["files"], ["r.json"])
        self.assertIn("r.json", site.uploaded)
        self.assertEqual(self.box.count(), 0)
        self.assertFalse(os.path.isdir(os.path.join(self.work, "11111111-2222-3333-4444-555555555555")))

    def test_a_cpu_fallback_of_a_gpu_job_is_a_visible_warning_with_its_reason(self):
        def handler(job):
            with open(job.out("r.png"), "wb") as fh:
                fh.write(b"x")
            return {"primary": "r.png", "device": "cpu", "device_note": "ComfyUI started with --cpu"}
        with mock.patch.object(agent, "warn") as warn:
            site = self.run_with("comfy.graph", handler)
        meta = site.finished[0]["meta"]
        self.assertEqual(meta["device"], "cpu")
        self.assertIn("--cpu", meta["device_note"])
        self.assertIn("پردازنده", meta["device_warning"])
        self.assertTrue(any("comfy.graph" in str(c) for c in warn.call_args_list))

    def test_gpu_samples_are_recorded_when_nvidia_smi_answers(self):
        seq = [{"util": 5, "vram_used_mb": 1000, "vram_total_mb": 12288, "temp_c": 40, "power_w": 30.0, "name": "RTX"},
               {"util": 95, "vram_used_mb": 9000, "vram_total_mb": 12288, "temp_c": 70, "power_w": 150.0, "name": "RTX"}]
        calls = {"n": 0}

        def snap():
            calls["n"] += 1
            return seq[min(calls["n"] - 1, 1)]

        def handler(job):
            time.sleep(0.2)
            with open(job.out("r.png"), "wb") as fh:
                fh.write(b"x")
            return {"primary": "r.png"}
        real = agent.gpu.GpuSampler
        with mock.patch.object(agent.gpu, "GpuSampler", lambda interval=3.0: real(interval=interval, snap=snap)):
            site = self.run_with("comfy.graph", handler)
        meta = site.finished[0]["meta"]
        self.assertEqual(meta["device"], "cuda")                 # inferred: the card was busy
        self.assertEqual(meta["gpu"]["util_max"], 95)
        self.assertEqual(meta["gpu"]["vram_max_mb"], 9000)

    def test_a_dead_line_at_the_end_keeps_the_result_which_arrives_when_the_line_is_back(self):
        def handler(job):
            with open(job.out("speech.wav"), "wb") as fh:
                fh.write(b"RIFF")
            return {"primary": "speech.wav"}
        site = FakeSite()
        site.down = 0

        def flaky_handler(job):
            r = handler(job)
            site.down = 4                                        # the line drops right after the work is done
            return r
        with mock.patch.object(agent, "warn") as warn:
            self.run_with("voice.sfx", flaky_handler, site=site)
        self.assertEqual(site.finished, [])
        self.assertEqual(self.box.count(), 1)                    # not lost, not failed
        self.assertTrue(any("saved on this computer" in str(c) for c in warn.call_args_list))
        site.down = 0
        done, left = self.box.flush(site)
        self.assertEqual((done, left), (1, 0))
        self.assertEqual(site.uploaded["speech.wav"], b"RIFF")
        self.assertTrue(site.finished[0]["ok"])
        self.assertEqual(site.finished[0]["meta"]["files"], ["speech.wav"])

    def test_a_failed_job_is_reported_through_the_outbox_with_retryable(self):
        def handler(job):
            raise agent.JobError("model not installed", retryable=False)
        site = self.run_with("photo.edit", handler)
        body = site.finished[0]
        self.assertFalse(body["ok"])
        self.assertIn("model not installed", body["error"])
        self.assertEqual(body["meta"]["retryable"], False)

    def test_a_failed_job_report_waits_in_the_outbox_when_the_line_is_down(self):
        def handler(job):
            raise RuntimeError("boom")
        site = FakeSite()
        real_post = site.post

        def post(path, data=None, timeout=60):
            if path.endswith("/finish/"):
                raise agent.SiteError("site unreachable")
            return real_post(path, data, timeout)
        site.post = post
        self.run_with("photo.edit", handler, site=site)
        self.assertEqual(self.box.count(), 1)

    def test_without_the_outbox_module_the_old_path_still_works(self):
        with mock.patch.object(agent, "OUTBOX", None):
            def handler(job):
                with open(job.out("a.txt"), "w") as fh:
                    fh.write("hi")
                return {"primary": "a.txt"}
            site = self.run_with("echo", handler)
        self.assertEqual(site.uploaded["a.txt"], b"hi")
        self.assertTrue(site.finished[0]["ok"])


class CommandAndAutostartTests(Base):
    def test_the_bootstrap_command_retries_the_failed_steps(self):
        fake = mock.Mock()
        fake.retry.return_value = 2
        fake.status.return_value = {"summary": {"failed": 1}, "features": {"asr-gpu": {"state": "failed", "items": [
            {"id": "pip", "state": "failed", "error": "pip install failed"}]}}}
        with mock.patch.object(agent, "BOOTSTRAP", fake):
            ok, out = agent.cmd_bootstrap()
        self.assertTrue(ok)
        self.assertIn("retry asked for 2", out)
        self.assertIn("pip install failed", out)
        with mock.patch.object(agent, "BOOTSTRAP", None):
            self.assertFalse(agent.cmd_bootstrap()[0])

    def test_autostart_is_applied_once_and_the_panel_can_switch_it_off(self):
        calls = []
        with mock.patch.object(agent.autostart_mod, "ensure", lambda here, data, enabled=True, force=False, **kw: calls.append((enabled, force)) or {"state": "registered"}), \
                mock.patch.dict(agent.STATE, {"autostart_applied": None}, clear=False):
            agent.apply_autostart({})
            agent.apply_autostart({})
            agent.apply_autostart({"autostart": False})
            agent.apply_autostart({"autostart": True})
        self.assertEqual(calls, [(True, False), (False, False), (True, True)])


class PackageResumeTests(unittest.TestCase):
    """The job package breaks half-way on a bad line: the next try asks for the rest (Range) and the file is whole at the end."""

    def serve(self, data, honour_range=True, break_first_at=100000):
        import http.server
        import socketserver
        import threading

        seen = {"requests": [], "broke": 0}

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                rng = self.headers.get("Range")
                seen["requests"].append(rng)
                start = 0
                if rng and honour_range:
                    start = int(rng.split("=")[1].rstrip("-"))
                body = data[start:]
                self.send_response(206 if start else 200)
                if start:
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(data) - 1, len(data)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not seen["broke"] and break_first_at:
                    seen["broke"] += 1
                    self.wfile.write(body[:break_first_at])
                    self.wfile.flush()
                    self.connection.shutdown(2)
                    return
                self.wfile.write(body)

        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d" % srv.server_address[1], seen

    def run_download(self, honour_range):
        data = os.urandom(300000)
        base, seen = self.serve(data, honour_range)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        dest = os.path.join(tmp, "package.zip")
        with mock.patch.object(agent.time, "sleep", lambda s: None), mock.patch.object(agent, "warn", lambda *a, **k: None),                 mock.patch.object(agent, "log", lambda *a, **k: None):
            agent.Site(base, "tok").download("/pkg", dest)
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), data)
        self.assertFalse(os.path.exists(dest + ".part"))
        return seen

    def test_a_broken_download_continues_from_where_it_stopped(self):
        seen = self.run_download(True)
        self.assertEqual(len(seen["requests"]), 2)
        self.assertIsNone(seen["requests"][0])
        self.assertRegex(seen["requests"][1], r"^bytes=\d{5,6}-$")

    def test_a_site_that_ignores_range_just_sends_the_whole_file_again(self):
        seen = self.run_download(False)
        self.assertEqual(len(seen["requests"]), 2)


class PortableNodeTests(Base):
    def test_the_unpacked_node_goes_to_the_front_of_path_once(self):
        d = os.path.join(self.tmp, "vendor", "node")
        os.makedirs(d)
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}):
            self.assertEqual(agent.use_portable_node(), "")                 # not unpacked yet: nothing happens
            self.assertEqual(os.environ["PATH"], "/usr/bin")
            exe = os.path.join(d, "node.exe") if os.name == "nt" else os.path.join(d, "bin", "node")
            os.makedirs(os.path.dirname(exe), exist_ok=True)
            open(exe, "w").close()
            folder = agent.use_portable_node()
            self.assertEqual(folder, os.path.dirname(exe))
            agent.use_portable_node()
            self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], folder)
            self.assertEqual(os.environ["PATH"].count(folder), 1)


class VramHandOverTests(unittest.TestCase):
    """Ollama and ComfyUI share one 12 GB card: whoever works next gets the card, with auto-switch on AND off (nothing is started or
    stopped with it off, but the other engine's models are still let go of - otherwise the next engine is pushed onto the CPU)."""

    def manager(self, running):
        m = agent.ServiceManager.__new__(agent.ServiceManager)
        m.running = lambda key: key in running
        m.calls = []
        m.unload_ollama = lambda: m.calls.append("unload_ollama") or True
        m.free_comfy = lambda: m.calls.append("free_comfy") or True
        m.stop_audio = lambda: m.calls.append("stop_audio")
        m.start = lambda key, tick=None, wait=True: m.calls.append("start:" + key)
        return m

    def run_prepare(self, m, kind, auto_switch):
        with mock.patch.object(agent, "vram_mb", lambda: (9000, 12288)), mock.patch.object(agent.gpu, "settle_vram", lambda before, **kw: 4000),                 mock.patch.object(agent.gpu, "free_peers", lambda data, post: ["InstAI"]), mock.patch.object(agent, "log", lambda *a, **k: None):
            return m.prepare_for(kind, auto_switch)

    def test_a_comfy_job_unloads_ollama_models_with_auto_switch_on(self):
        m = self.manager({"ollama", "comfyui"})
        self.run_prepare(m, "comfy.graph", True)
        self.assertEqual(m.calls, ["stop_audio", "unload_ollama"])

    def test_an_ollama_job_frees_comfy_with_auto_switch_on(self):
        m = self.manager({"ollama", "comfyui"})
        self.run_prepare(m, "ollama.generate", True)
        self.assertEqual(m.calls, ["stop_audio", "free_comfy"])

    def test_with_auto_switch_off_the_models_are_still_let_go_of_but_nothing_is_started_or_stopped(self):
        m = self.manager({"ollama", "comfyui"})
        self.run_prepare(m, "comfy.graph", False)
        self.assertEqual(m.calls, ["unload_ollama"])
        m = self.manager({"ollama", "comfyui"})
        self.run_prepare(m, "ollama.chat", False)
        self.assertEqual(m.calls, ["free_comfy"])

    def test_with_auto_switch_off_a_service_that_is_not_running_is_still_an_error(self):
        m = self.manager({"ollama"})
        with self.assertRaises(RuntimeError):
            self.run_prepare(m, "comfy.graph", False)
        self.assertEqual(m.calls, [])

    def test_a_card_that_is_still_full_after_the_hand_over_is_said_out_loud(self):
        m = self.manager({"ollama", "comfyui"})
        said = []
        with mock.patch.object(agent, "warn", lambda msg, *a: said.append(msg)),                 mock.patch.object(agent.gpu, "compute_apps", lambda **kw: [{"pid": 7, "name": "Blender.exe", "vram_mb": 3000}]):
            self.run_prepare(m, "comfy.graph", True)
        self.assertTrue(any("still in use" in x and "Blender.exe (3000 MB)" in x for x in said), said)

    def test_auto_switch_on_starts_the_missing_engine_after_the_hand_over(self):
        m = self.manager({"ollama"})
        self.run_prepare(m, "comfy.graph", True)
        self.assertEqual(m.calls, ["stop_audio", "unload_ollama", "start:comfyui"])


if __name__ == "__main__":
    unittest.main()
