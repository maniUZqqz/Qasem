"""agent.py voice handlers against a fake PersianAiKit Voice server (stdlib only; runs on Windows and Linux).

    python -m unittest tests/test_agent_voice.py        (from the processing folder)

Covers voice.clone (consent, per-clip verdicts, rebuild deletes the old copy), voice.tts with a cloned voice
(strict: no Piper fallback, VOICE_MISSING, restore from the recordings), the setup message when the Python
voice service is missing, and that a non-retryable failure is reported as such to the site.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))   # never the real data folder
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import agent  # noqa: E402


def wav(seconds=1.0, rate=22050):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


class Kit:
    """State of the fake kit."""

    def __init__(self):
        self.voices = {}
        self.gateway = True
        self.pocket = True
        self.calls = []

    def reset(self):
        self.__init__()


KIT = Kit()


class KitHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _route(self, method):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
        body = self._body()
        KIT.calls.append((method, u.path))
        if method == "GET" and u.path == "/api/voice/engines":
            return self._send(200, {"engines": [{"id": "piper", "available": True},
                                                {"id": "pocket", "available": KIT.pocket and KIT.gateway}],
                                    "gateway": KIT.gateway, "error": None if KIT.gateway else "سرویسِ صدا نصب نیست"})
        if method == "DELETE" and parts[:3] == ["api", "voice", "voices"]:
            if KIT.voices.pop(parts[3], None) is None:
                return self._send(404, {"error": "صدای «%s» پیدا نشد." % parts[3]})
            return self._send(200, {"removed": True})
        if method == "POST" and u.path == "/api/voice/clone":
            b = json.loads(body.decode("utf-8"))
            if b.get("consent") is not True:
                return self._send(400, {"error": "بدونِ رضایتِ صاحبِ صدا نمی‌شود"})
            vid, i = b["name"], 2
            while vid in KIT.voices:
                vid, i = "%s-%d" % (b["name"], i), i + 1
            KIT.voices[vid] = {"clips": [], "meta": b}
            return self._send(200, {"id": vid, "name": b["name"], "consent": True})
        if method == "POST" and u.path == "/api/voice/clone/clip":
            if q.get("voice") not in KIT.voices:
                return self._send(404, {"error": "صدا پیدا نشد."})
            if body[:4] != b"RIFF":
                return self._send(400, {"error": "فایل WAV نیست"})
            if q.get("index") == "2":
                return self._send(200, {"ok": False, "message": "جمله با متن جور نبود — همان متن را بخوانید.",
                                        "heard": "چیز دیگر", "wer": 0.8})
            KIT.voices[q["voice"]]["clips"].append(q["index"])
            n = len(KIT.voices[q["voice"]]["clips"])
            return self._send(200, {"ok": True, "message": "خوب بود ✓", "heard": q.get("text"), "wer": 0.0,
                                    "snr": 41.0, "seconds": 3.1, "clips": n, "minutes": round(n * 3.1 / 60, 1)})
        if method == "GET" and parts[:3] == ["api", "voice", "voices"] and parts[-1] == "sample":
            v = KIT.voices.get(parts[3])
            if v is None:
                return self._send(404, {"error": "پیدا نشد"})
            return self._send(200, wav(4), "audio/wav")
        if method == "POST" and u.path == "/api/voice/tts":
            b = json.loads(body.decode("utf-8"))
            if not KIT.gateway:
                return self._send(503, {"error": "سرویسِ صدا نصب نیست"})
            if b.get("voice") and b["voice"] not in KIT.voices:
                return self._send(404, {"error": "صدای «%s» پیدا نشد." % b["voice"]})
            return self._send(200, wav(2), "audio/wav", {"X-Voice-Engine": "pocket", "X-Voice-Check": "0.08",
                                                         "X-Seed": "42"})
        if method == "POST" and u.path == "/api/tts":
            return self._send(200, wav(2), "audio/wav")
        return self._send(404, {"error": "چنین مسیری نیست."})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")


class FakeSite:
    def __init__(self, payload=None, inputs=None, kind="voice.tts"):
        self.payload, self.inputs, self.kind = payload or {}, inputs or {}, kind
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


class AgentVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), KitHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        os.environ["NM_VOICE_URL"] = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.tmp = tempfile.mkdtemp(prefix="nm-agent-voice-")
        agent.WORK = os.path.join(cls.tmp, "work")
        agent.LOGS = os.path.join(cls.tmp, "logs")
        agent.CONFIG = {"name": "TEST-NODE"}
        agent.VOICE_ROOT = os.path.join(cls.tmp, "Voice")          # no real kit files here

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        KIT.reset()

    def job(self, payload, inputs=None, kind="voice.tts"):
        site = FakeSite(payload, inputs, kind)
        j = agent.Job(site, {"uid": "t%08x" % id(site), "kind": kind, "payload": payload})
        j.fetch()
        return j, site

    def clone_payload(self, **extra):
        return {"name": "nm-s1-v7", "person": "علی", "purpose": "ویدیو", "sample_text": "سلام",
                "consent": {"given": True, "text": "رضایت دارم", "at": "2026-10-24T10:00:00"},
                "clips": [{"file": "clip_%04d.wav" % i, "index": i, "text": "جملهٔ %d" % i} for i in (1, 2, 3)],
                **extra}

    def clips(self):
        return {"clip_%04d.wav" % i: wav(3) for i in (1, 2, 3)}

    # ---------------------------------------------------------------- voice.clone
    def test_clone_builds_the_voice_and_reports_every_clip(self):
        j, _site = self.job(self.clone_payload(), self.clips(), "voice.clone")
        meta = agent.h_voice_clone(j)
        self.assertTrue(meta["ready"])
        self.assertEqual(meta["voice_id"], "nm-s1-v7")
        out = json.load(open(j.out("clone.json"), encoding="utf-8"))
        self.assertEqual([c["index"] for c in out["clips"]], [1, 2, 3])
        self.assertEqual([c["ok"] for c in out["clips"]], [True, False, True])
        self.assertIn("جور نبود", out["clips"][1]["message"])
        self.assertEqual(out["accepted"], 2)
        self.assertEqual(out["check"], 0.08)
        self.assertTrue(os.path.getsize(j.out("ref.wav")) > 44 and os.path.getsize(j.out("sample.wav")) > 44)
        self.assertEqual(KIT.voices["nm-s1-v7"]["meta"]["person"], "علی")

    def test_clone_refuses_without_consent(self):
        j, _ = self.job(self.clone_payload(consent={"given": False}), self.clips(), "voice.clone")
        with self.assertRaises(agent.JobError) as ctx:
            agent.h_voice_clone(j)
        self.assertFalse(ctx.exception.retryable)
        self.assertFalse(any(c[1] == "/api/voice/clone" for c in KIT.calls), "nothing may reach the kit without consent")

    def test_rebuild_replaces_the_old_copy(self):
        KIT.voices["nm-s1-v7"] = {"clips": ["9"], "meta": {}}
        j, _ = self.job(self.clone_payload(), self.clips(), "voice.clone")
        meta = agent.h_voice_clone(j)
        self.assertEqual(meta["voice_id"], "nm-s1-v7", "a rebuild must not become nm-s1-v7-2")
        self.assertIn(("DELETE", "/api/voice/voices/nm-s1-v7"), KIT.calls)

    def test_all_clips_rejected_is_a_result_not_a_crash(self):
        p = self.clone_payload(clips=[{"file": "clip_0002.wav", "index": 2, "text": "x"}])
        j, _ = self.job(p, {"clip_0002.wav": wav(3)}, "voice.clone")
        meta = agent.h_voice_clone(j)
        self.assertFalse(meta["ready"])
        self.assertNotIn("nm-s1-v7", KIT.voices, "a voice with no accepted clip is removed again")

    # ---------------------------------------------------------------- voice.tts
    def test_cloned_voice_speaks(self):
        KIT.voices["nm-s1-v7"] = {"clips": ["1"], "meta": {}}
        j, _ = self.job({"text": "سلام", "voice": "nm-s1-v7", "engine": "pocket", "clone": True, "strict": True,
                         "out": "speech.wav"})
        meta = agent.h_voice_tts(j)
        self.assertEqual(meta["primary"], "speech.wav")
        self.assertEqual(meta["engine"], "voice:pocket")
        self.assertEqual(meta["check"], 0.08)
        self.assertNotIn(("POST", "/api/tts"), KIT.calls)

    def test_missing_cloned_voice_is_voice_missing_never_piper(self):
        j, _ = self.job({"text": "سلام", "voice": "nm-gone", "clone": True, "strict": True})
        with self.assertRaises(agent.VoiceMissing) as ctx:
            agent.h_voice_tts(j)
        self.assertIn("VOICE_MISSING", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)
        self.assertNotIn(("POST", "/api/tts"), KIT.calls, "a cloned voice must never fall back to Piper")

    def test_missing_voice_is_rebuilt_from_the_recordings(self):
        restore = {"name": "nm-s1-v7", "person": "علی", "purpose": "ویدیو", "consent": {"given": True, "text": "x"},
                   "clips": [{"file": "clip_0001.wav", "index": 1, "text": "جمله"}]}
        j, _ = self.job({"text": "سلام", "voice": "nm-s1-v7", "clone": True, "strict": True, "restore": restore},
                        {"clip_0001.wav": wav(3)})
        meta = agent.h_voice_tts(j)
        self.assertTrue(meta["restored"])
        self.assertEqual(meta["voice_id"], "nm-s1-v7")
        self.assertTrue(os.path.getsize(j.out("speech.wav")) > 44)

    def test_service_not_installed_gives_the_setup_instruction(self):
        KIT.gateway = False
        os.environ["NM_VOICE_AUTOSETUP"] = "0"
        try:
            j, _ = self.job({"text": "سلام", "voice": "nm-s1-v7", "clone": True})
            with self.assertRaises(agent.JobError) as ctx:
                agent.h_voice_tts(j)
        finally:
            os.environ.pop("NM_VOICE_AUTOSETUP", None)
        self.assertIn("Setup-Voice.bat", str(ctx.exception))
        self.assertIn("نصب نیست", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)

    def test_auto_setup_needs_the_kit_files(self):
        KIT.gateway = False
        j, _ = self.job({"text": "سلام", "voice": "nm-s1-v7", "clone": True})
        with self.assertRaises(agent.JobError) as ctx:
            agent.h_voice_tts(j)
        self.assertIn("git pull", str(ctx.exception))

    def test_installed_but_stopped_service_is_started(self):
        KIT.gateway = False
        os.makedirs(os.path.dirname(agent.voice_venv_python()), exist_ok=True)
        open(agent.voice_venv_python(), "w").close()
        model = os.path.join(agent.VOICE_ROOT, "models", "tts", "pocket-fa", "flow_lm_step.onnx.data")
        os.makedirs(os.path.dirname(model), exist_ok=True)
        open(model, "w").close()
        started = []
        real = agent.start_voice_gateway
        agent.start_voice_gateway = lambda tick=None: (started.append(1), setattr(KIT, "gateway", True))
        try:
            self.assertTrue(agent.voice_clone_installed())
            self.assertTrue(agent.ensure_voice_service())
        finally:
            agent.start_voice_gateway = real
            shutil.rmtree(agent.VOICE_ROOT, ignore_errors=True)
        self.assertEqual(started, [1])

    def test_non_strict_natural_voice_still_falls_back_to_piper(self):
        j, _ = self.job({"text": "سلام", "voice": "mana", "engine": "pocket"})
        KIT.gateway = False
        meta = agent.h_voice_tts(j)
        self.assertEqual(meta["engine"], "voice:piper")

    def test_piper_voice_goes_to_piper(self):
        j, _ = self.job({"text": "سلام", "voice": "piper:fa_IR-gyro-medium"})
        self.assertEqual(agent.h_voice_tts(j)["engine"], "voice:piper")
        self.assertNotIn(("POST", "/api/voice/tts"), KIT.calls)

    # ---------------------------------------------------------------- the whole job, as the site sees it
    def test_run_job_reports_voice_missing_as_not_retryable(self):
        site = FakeSite({"text": "سلام", "voice": "nm-gone", "clone": True, "strict": True})
        agent.run_job(site, {"uid": "run-missing", "kind": "voice.tts", "payload": site.payload})
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        self.assertFalse(finish["ok"])
        self.assertIn("VOICE_MISSING", finish["error"])
        self.assertIs(finish["meta"]["retryable"], False)

    def test_run_job_clone_uploads_its_outputs(self):
        site = FakeSite(self.clone_payload(), self.clips(), "voice.clone")
        agent.run_job(site, {"uid": "run-clone", "kind": "voice.clone", "payload": site.payload})
        finish = [d for p, d in site.posts if p.endswith("/finish/")][-1]
        self.assertTrue(finish["ok"], finish)
        self.assertEqual(site.uploads, [["file_clone.json", "file_ref.wav", "file_sample.wav"]])


if __name__ == "__main__":
    unittest.main()
