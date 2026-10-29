"""agent.py 1.7 GPU audio engines, without a GPU: the real worker scripts run in --fake mode (a test tone instead of
a voice), ACE-Step's API is faked here, the site is faked as in test_agent_voice.py.

    python tests\\test_agent_audio.py
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)
import agent  # noqa: E402


def wav(seconds=1.0, rate=22050):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Ace:
    tasks = {}
    fail = False
    calls = []


class AceHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def wrap(self, data):
        return {"data": data, "code": 200, "error": None, "timestamp": 1, "extra": None}

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, self.wrap({"status": "ok", "service": "ACE-Step API"}))
        if self.path.startswith("/v1/audio"):
            return self._send(200, wav(2.0, 48000), "audio/wav")
        self._send(404, {"error": "?"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode() or "{}")
        Ace.calls.append((self.path, body))
        if self.path == "/release_task":
            Ace.tasks["t1"] = 0
            return self._send(200, self.wrap({"task_id": "t1", "status": "queued"}))
        if self.path == "/query_result":
            Ace.tasks["t1"] += 1
            if Ace.fail:
                return self._send(200, self.wrap([{"task_id": "t1", "status": 2, "result": "boom"}]))
            if Ace.tasks["t1"] < 2:
                return self._send(200, self.wrap([{"task_id": "t1", "status": 0, "result": ""}]))
            res = json.dumps([{"file": "/v1/audio?path=%2Ftmp%2Fa.wav", "status": 1,
                               "metas": {"bpm": 96, "duration": body and 30}}])
            return self._send(200, self.wrap([{"task_id": "t1", "status": 1, "result": res}]))
        self._send(404, {"error": "?"})


class FakeSite:
    def __init__(self, payload=None, inputs=None):
        self.payload, self.inputs = payload or {}, inputs or {}
        self.posts, self.uploads = [], []

    def post(self, path, data=None, timeout=60):
        self.posts.append((path, data))
        return {"cancel": False}

    def download(self, path, dest, timeout=600, attempts=5):
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr("payload.json", json.dumps({"payload": self.payload, "timeout_s": 600}))
            for name, data in self.inputs.items():
                z.writestr("inputs/" + name, data)

    def upload(self, path, files, timeout=1800, attempts=4):
        self.uploads.append(sorted(files))
        return {"ok": True}


class Proc:
    def __init__(self, alive=True):
        self.alive = alive
        self.pid = 4242

    def poll(self):
        return None if self.alive else 0


class AgentAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="nm-agent-audio-")
        cls.ports = {"moss": free_port(), "sfx": free_port()}
        cls.workers = []
        env = dict(os.environ, NM_FAKE_LOAD_S="0.5", PYTHONIOENCODING="utf-8")
        for key, script in (("moss", "moss_tts_server.py"), ("sfx", "moss_sfx_server.py")):
            log = open(os.path.join(cls.tmp, "%s.log" % key), "w")
            cls.workers.append(subprocess.Popen(
                [sys.executable, os.path.join(PROC, "audio", script), "--fake", "--port", str(cls.ports[key]),
                 "--parent-pid", str(os.getpid())], stdout=log, stderr=subprocess.STDOUT, env=env))
        cls.ace = ThreadingHTTPServer(("127.0.0.1", 0), AceHandler)
        threading.Thread(target=cls.ace.serve_forever, daemon=True).start()
        os.environ["NM_MOSS_URL"] = "http://127.0.0.1:%d" % cls.ports["moss"]
        os.environ["NM_SFX_URL"] = "http://127.0.0.1:%d" % cls.ports["sfx"]
        os.environ["NM_MUSIC_URL"] = "http://127.0.0.1:%d" % cls.ace.server_address[1]
        for key in cls.ports:
            deadline = time.time() + 20
            while time.time() < deadline and not agent.listening(agent.service_url(key), 0.5):
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        for p in cls.workers:
            p.kill()
            p.wait()
        cls.ace.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="nm-home-", dir=self.tmp)
        voices = os.path.join(self.home, "tools", "PersianAiKit", "Voice", "voice", "voices")
        os.makedirs(voices)
        with open(os.path.join(voices, "voices.json"), "w", encoding="utf-8") as fh:
            json.dump([{"id": "mana", "file": "mana-cc0.wav", "gender": "زن"},
                       {"id": "arash", "file": "piper-ganji.wav", "gender": "مرد"}], fh)
        open(os.path.join(voices, "mana-cc0.wav"), "wb").write(wav(3))
        open(os.path.join(voices, "piper-ganji.wav"), "wb").write(wav(3))
        for name, value in {"HERE": self.home, "WORK": os.path.join(self.home, "work"),
                            "LOGS": os.path.join(self.home, "logs"),
                            "VOICE_ROOT": os.path.join(self.home, "tools", "PersianAiKit", "Voice")}.items():
            p = mock.patch.object(agent, name, value)
            p.start()
            self.addCleanup(p.stop)
        agent.CONFIG = {"name": "TEST-NODE"}
        agent.AUDIO_USE.clear()
        agent.AUDIO_BUSY.clear()
        Ace.tasks, Ace.fail, Ace.calls = {}, False, []
        p = mock.patch.object(agent, "MANAGER", None)
        p.start()
        self.addCleanup(p.stop)

    def install(self, *keys):
        for key in keys:
            eng = agent.AUDIO_ENGINES[key]
            for f in eng["files"]:
                path = os.path.join(self.home, *f.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "wb").close()
            py = agent.audio_venv_python(key)
            os.makedirs(os.path.dirname(py), exist_ok=True)
            open(py, "wb").close()
            open(os.path.join(os.path.dirname(os.path.dirname(py)), ".nm-pip-venv-%s.json" % eng["venv"]), "w").write("{}")

    def job(self, kind, payload, inputs=None):
        site = FakeSite(payload, inputs)
        j = agent.Job(site, {"uid": "a%08x" % id(site), "kind": kind, "payload": payload})
        j.fetch()
        return j, site

    def manager(self, running=()):
        with mock.patch.object(agent, "find_comfy_start", lambda: None):
            m = agent.ServiceManager()
        calls = []
        state = set(running)
        m.running = lambda key: key in state
        m.start = lambda key, wait=True, tick=None: (calls.append(("start", key)), state.add(key), True)[-1]
        m.stop = lambda key: (calls.append(("stop", key)), state.discard(key), True)[-1]
        m.unload_ollama = lambda: calls.append(("unload_ollama",)) or True
        m.free_comfy = lambda: calls.append(("free_comfy",)) or True
        return m, calls

    # ------------------------------------------------------------ install state, routing
    def test_engine_for_kind(self):
        self.assertEqual(agent.audio_engine_for("voice.sfx"), "sfx")
        self.assertEqual(agent.audio_engine_for("voice.music"), "music")
        self.assertEqual(agent.audio_engine_for("voice.tts", {"engine": "moss-fa"}), "moss")
        self.assertEqual(agent.audio_engine_for("voice.clone", {"engine": "moss-fa"}), "moss")
        self.assertIsNone(agent.audio_engine_for("voice.tts", {"engine": "pocket"}))
        self.assertIsNone(agent.audio_engine_for("comfy.graph"))

    def test_missing_models_say_run_download_models(self):
        self.assertFalse(agent.audio_installed("moss"))
        m, calls = self.manager()
        with self.assertRaises(agent.JobError) as ctx:
            m.prepare_audio("moss", True)
        msg = str(ctx.exception)
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("MODELS_MISSING", msg)
        self.assertIn("Download-Models.bat --only moss-tts", msg)
        self.assertIn("نصب نیست", msg)
        self.assertEqual(calls, [], "nothing is started or freed for a job that cannot run")
        self.install("moss")
        self.assertTrue(agent.audio_installed("moss"))
        self.assertTrue(m.startable("moss"))
        self.assertFalse(m.startable("sfx"))

    def test_switching_frees_the_gpu(self):
        self.install("moss", "sfx")
        m, calls = self.manager(running={"sfx"})
        m.prepare_audio("moss", True)
        self.assertEqual(calls, [("unload_ollama",), ("free_comfy",), ("stop", "sfx"), ("start", "moss")])
        calls.clear()
        m.prepare_audio("moss", True)
        self.assertEqual(calls, [], "an engine already running is reused")

    def test_without_auto_switch_the_vram_decides(self):
        self.install("sfx")
        m, calls = self.manager()
        with mock.patch.object(agent, "vram_mb", lambda: (11000, 12288)):
            with self.assertRaises(agent.JobError) as ctx:
                m.prepare_audio("sfx", False)
        self.assertIn("auto-switch", str(ctx.exception))
        with mock.patch.object(agent, "vram_mb", lambda: (500, 12288)):
            m.prepare_audio("sfx", False)
        self.assertEqual(calls, [("start", "sfx")], "auto-switch off: nothing else is unloaded")

    def test_video_and_text_jobs_stop_the_audio_engines(self):
        self.install("moss")
        with mock.patch.object(agent, "find_comfy_start", lambda: None):
            m = agent.ServiceManager()
        stopped = []
        m.procs["moss"] = Proc()
        m.stop = lambda key: stopped.append(key) or True
        m.unload_ollama = lambda: True
        m.free_comfy = lambda: True
        m.running = lambda key: True
        m.prepare_for("comfy.graph", True)
        self.assertEqual(stopped, ["moss"])
        agent.AUDIO_BUSY["moss"] = 1
        stopped.clear()
        m.prepare_for("ollama.generate", True)
        self.assertEqual(stopped, [], "an engine in the middle of a job is not stopped")

    def test_idle_engines_are_reaped(self):
        with mock.patch.object(agent, "find_comfy_start", lambda: None):
            m = agent.ServiceManager()
        stopped = []
        m.stop = lambda key: stopped.append(key) or True
        m.procs["sfx"] = Proc()
        agent.AUDIO_USE["sfx"] = time.time()
        m.reap_audio(60)
        self.assertEqual(stopped, [])
        agent.AUDIO_USE["sfx"] = time.time() - 120
        m.reap_audio(60)
        self.assertEqual(stopped, ["sfx"])

    def test_prepare_for_uses_the_payload(self):
        self.install("moss")
        m, calls = self.manager()
        m.prepare_for("voice.tts", True, payload={"engine": "moss-fa"})
        self.assertIn(("start", "moss"), calls)
        self.assertNotIn(("start", "voice"), calls, "MOSS speech does not need the .NET voice kit")

    # ------------------------------------------------------------ handlers against the real workers (--fake)
    def test_moss_speaks_with_a_kit_voice(self):
        j, _ = self.job("voice.tts", {"text": "سلام دنیا", "engine": "moss-fa", "voice": "mana", "out": "speech.wav"})
        meta = agent.h_voice_tts(j)
        self.assertEqual(meta["engine"], "voice:moss-fa")
        self.assertEqual(meta["license"], "Apache-2.0")
        with wave.open(j.out("speech.wav")) as w:
            self.assertGreater(w.getnframes(), 0)

    def test_moss_speaks_with_an_attached_reference(self):
        j, _ = self.job("voice.tts", {"text": "سلام", "engine": "moss-fa", "reference": "moss_ref.wav", "clone": True},
                        {"moss_ref.wav": wav(12)})
        meta = agent.h_voice_tts(j)
        self.assertEqual(meta["voice"], "clone")

    def test_unknown_voice_and_no_fallback(self):
        j, _ = self.job("voice.tts", {"text": "سلام", "engine": "moss-fa", "voice": "nobody"})
        with self.assertRaises(agent.JobError):
            agent.h_voice_tts(j)
        j, _ = self.job("voice.tts", {"text": "سلام", "engine": "moss-fa", "voice": "mana"})
        with mock.patch.dict(os.environ, {"NM_MOSS_URL": "http://127.0.0.1:%d" % free_port()}):
            with mock.patch.object(agent, "audio_ready", side_effect=agent.JobError("not reachable")):
                with mock.patch.object(agent, "kit_request") as kit:
                    with self.assertRaises(agent.JobError):
                        agent.h_voice_tts(j)
                    kit.assert_not_called()

    def test_moss_clone_needs_consent_and_makes_a_sample(self):
        clips = [{"file": "clip_0001.wav", "index": 1, "text": "x", "in_reference": True}]
        j, _ = self.job("voice.clone", {"engine": "moss-fa", "name": "nm-s1-v2", "clips": clips, "reference": "moss_ref.wav",
                                        "consent": {"given": False}}, {"moss_ref.wav": wav(12)})
        with self.assertRaises(agent.JobError) as ctx:
            agent.h_voice_clone(j)
        self.assertFalse(ctx.exception.retryable)
        j, _ = self.job("voice.clone", {"engine": "moss-fa", "name": "nm-s1-v2", "clips": clips, "reference": "moss_ref.wav",
                                        "consent": {"given": True, "text": "رضایت"}, "sample_text": "سلام"},
                        {"moss_ref.wav": wav(12)})
        meta = agent.h_voice_clone(j)
        self.assertTrue(meta["ready"])
        out = json.load(open(j.out("clone.json"), encoding="utf-8"))
        self.assertEqual(out["engine"], "moss-fa")
        self.assertEqual(out["voice_id"], "nm-s1-v2")
        self.assertTrue(out["clips"][0]["ok"])
        self.assertTrue(os.path.getsize(j.out("sample.wav")) > 44 and os.path.getsize(j.out("ref.wav")) > 44)

    def test_sound_effect(self):
        j, _ = self.job("voice.sfx", {"prompt": "light rain on a window", "seconds": 45})
        meta = agent.h_voice_sfx(j)
        self.assertEqual(meta["seconds"], 30.0, "MOSS-SoundEffect makes at most 30 s")
        self.assertEqual(meta["license"], "Apache-2.0")
        self.assertTrue(os.path.getsize(j.out("sfx.wav")) > 44)
        j, _ = self.job("voice.sfx", {"prompt": ""})
        with self.assertRaises(agent.JobError):
            agent.h_voice_sfx(j)

    def test_music_through_the_ace_step_api(self):
        j, _ = self.job("voice.music", {"prompt": "calm acoustic guitar, warm", "seconds": 30, "bpm": 90})
        with mock.patch.object(agent.time, "sleep", lambda s: None):
            meta = agent.h_voice_music(j)
        self.assertEqual(meta["engine"], "audio:acestep")
        self.assertEqual(meta["bpm"], 96)
        release = [b for p, b in Ace.calls if p == "/release_task"][0]
        self.assertEqual(release["lyrics"], "[Instrumental]")
        self.assertFalse(release["thinking"], "no 5Hz language model on a 12 GB card")
        self.assertEqual(release["audio_duration"], 30)
        self.assertEqual(release["bpm"], 90)
        self.assertTrue(os.path.getsize(j.out("music.wav")) > 1000)
        Ace.fail = True
        j, _ = self.job("voice.music", {"prompt": "x", "seconds": 20})
        with mock.patch.object(agent.time, "sleep", lambda s: None):
            with self.assertRaises(agent.JobError):
                agent.h_voice_music(j)

    # ------------------------------------------------------------ the whole job, as the site sees it
    def test_run_job_reports_missing_models_as_final(self):
        site = FakeSite({"prompt": "rain", "seconds": 5})
        with mock.patch.object(agent, "MANAGER", self.manager()[0]):
            agent.run_job(site, {"uid": "sfx-missing", "kind": "voice.sfx", "payload": site.payload})
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        self.assertFalse(finish["ok"])
        self.assertIn("MODELS_MISSING", finish["error"])
        self.assertIs(finish["meta"]["retryable"], False)

    def test_run_job_sound_effect_uploads_its_output(self):
        self.install("sfx")
        site = FakeSite({"prompt": "footsteps on wood", "seconds": 3})
        m, calls = self.manager(running={"sfx"})
        with mock.patch.object(agent, "MANAGER", m):
            agent.run_job(site, {"uid": "sfx-ok", "kind": "voice.sfx", "payload": site.payload})
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        self.assertTrue(finish["ok"], finish)
        self.assertEqual(site.uploads, [["file_sfx.wav"]])


if __name__ == "__main__":
    unittest.main()
