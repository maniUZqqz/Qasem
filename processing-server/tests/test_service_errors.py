"""A local service that IS running but answers slowly is reported as a read timeout («is running but did not answer within N s»),
never as «not reachable» (that is only for refused / unreachable / connect timeouts). Real HTTP servers on localhost: one that sleeps,
and a port nobody listens on."""
import http.server
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402
import edit_jobs  # noqa: E402


class Slow(http.server.BaseHTTPRequestHandler):
    def _go(self):
        time.sleep(3.0)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
        except OSError:
            pass                                   # the client gave up long ago

    do_GET = do_POST = _go

    def log_message(self, *a):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


def dead_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeJob:
    uid = "abcdef123456"
    timeout_s = 60
    cancelled = False

    def __init__(self, folder):
        self.dir = folder

    def input_bytes(self, name):
        return b"x"

    def out(self, name):
        return os.path.join(self.dir, name)

    def progress(self, *a, **k):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(("127.0.0.1", 0), Slow)
        cls.slow = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.dead = "http://127.0.0.1:%d" % dead_port()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-svc-test-")
        self.job = FakeJob(self.tmp)

    def point(self, key, url):
        return mock.patch.dict(os.environ, {agent.SERVICES[key][0]: url})

    def assert_slow(self, text, label=None):
        self.assertIn("is running but did not answer within", text)
        self.assertIn("not a connection failure", text)
        self.assertNotIn("not reachable", text)
        if label:
            self.assertIn(label, text)

    def assert_down(self, text, label=None):
        self.assertIn("is not reachable at", text)
        self.assertNotIn("did not answer", text)
        if label:
            self.assertIn(label, text)


class ClassifierTests(Base):
    def test_classifier(self):
        self.assertTrue(agent.is_read_timeout(socket.timeout("timed out")))
        self.assertTrue(agent.is_read_timeout(TimeoutError("timed out")))
        self.assertFalse(agent.is_read_timeout(urllib.error.URLError(socket.timeout("timed out"))))        # a connect timeout
        self.assertFalse(agent.is_read_timeout(urllib.error.URLError(ConnectionRefusedError(10061, "refused"))))
        self.assertFalse(agent.is_read_timeout(ConnectionRefusedError(10061, "refused")))
        self.assertFalse(agent.is_read_timeout(ConnectionResetError(10054, "reset")))
        self.assertFalse(agent.is_read_timeout(urllib.error.HTTPError("http://x", 500, "boom", {}, None)))
        slow = agent.service_error("x service", "http://x", socket.timeout("timed out"), 30)
        self.assertIsInstance(slow, agent.ServiceTimeout)
        self.assertIsInstance(slow, agent.JobError)
        self.assertIs(agent.service_error("x", "http://x", OSError("refused"), 30).__class__, agent.JobError)
        self.assertIs(agent.service_error("x", "http://x", OSError("refused"), 30, error_cls=RuntimeError).__class__, RuntimeError)


class RelayTests(Base):
    def test_relay_read_timeout_versus_refused(self):
        with self.point("comfyui", self.slow):
            with self.assertRaises(RuntimeError) as cm:
                agent._relay(self.job, "comfyui", "GET", "/prompt", timeout=1)
        self.assert_slow(str(cm.exception), "comfyui service")
        with self.point("comfyui", self.dead):
            with self.assertRaises(RuntimeError) as cm:
                agent._relay(self.job, "comfyui", "GET", "/prompt", timeout=1)
        self.assert_down(str(cm.exception), "comfyui service")

    def test_comfy_run_and_upload_say_what_happened(self):
        graph = {"1": {"inputs": {}}}
        with mock.patch.object(agent, "http", side_effect=socket.timeout("timed out")):
            with self.assertRaises(RuntimeError) as cm:
                agent.comfy_run(graph, self.job)
            self.assert_slow(str(cm.exception), "ComfyUI")
            with self.assertRaises(RuntimeError) as cm:
                agent.comfy_upload("a.png", b"x")
            self.assert_slow(str(cm.exception), "ComfyUI")
        with mock.patch.object(agent, "http", side_effect=urllib.error.URLError(ConnectionRefusedError(10061, "refused"))):
            with self.assertRaises(RuntimeError) as cm:
                agent.comfy_run(graph, self.job)
            self.assert_down(str(cm.exception), "ComfyUI")
            with self.assertRaises(RuntimeError) as cm:
                agent.comfy_upload("a.png", b"x")
            self.assert_down(str(cm.exception), "ComfyUI")
        # a rejected graph is a real answer: it stays «rejected»
        err = urllib.error.HTTPError("http://x/prompt", 400, "bad", {}, None)
        err.read = lambda: b'{"error": {"type": "prompt_no_outputs"}}'
        with mock.patch.object(agent, "http", side_effect=err):
            with self.assertRaises(RuntimeError) as cm:
                agent.comfy_run(graph, self.job)
        self.assertIn("rejected the graph (HTTP 400)", str(cm.exception))


class AudioTests(Base):
    def test_audio_engines(self):
        key = "moss"
        label = agent.AUDIO_ENGINES[key]["label"]
        with self.assertRaises(agent.JobError) as cm:
            agent.audio_run(key, self.slow, {"text": "x"}, 1)
        self.assert_slow(str(cm.exception), label)
        self.assertIsInstance(cm.exception, agent.ServiceTimeout)
        with self.assertRaises(agent.JobError) as cm:
            agent.audio_run(key, self.dead, {"text": "x"}, 1)
        self.assert_down(str(cm.exception), label)
        self.assertNotIsInstance(cm.exception, agent.ServiceTimeout)
        self.assertEqual(agent.AUDIO_BUSY.get(key, 0), 0)                       # the busy counter is always given back


class VoiceTests(Base):
    def test_voice_service(self):
        with self.point("voice", self.slow):
            with self.assertRaises(agent.JobError) as cm:
                agent.kit_request("GET", "/api/voice/engines", timeout=1)
            self.assert_slow(str(cm.exception), "voice service")
        with mock.patch.object(agent, "kit_request", side_effect=agent.ServiceTimeout("voice service is running but did not answer within 20 s")):
            up, pocket, err = agent.voice_engines()
        self.assertEqual((up, pocket), (True, False))
        self.assertIn("did not answer", err)
        with self.point("voice", self.dead):
            with self.assertRaises(agent.JobError) as cm:
                agent.kit_request("GET", "/api/voice/engines", timeout=1)
            self.assert_down(str(cm.exception), "voice service")
            up, pocket, err = agent.voice_engines()
        self.assertEqual((up, pocket), (False, False))
        self.assertIn("not reachable", err)

    def test_a_busy_voice_service_is_waited_for_not_restarted(self):
        """«not reachable» means start it; a read timeout means it is up and busy - never start a second gateway."""
        calls = {"start": 0, "n": 0}

        def engines():
            calls["n"] += 1
            if calls["n"] < 3:
                return True, False, "voice service is running but did not answer within 20 s"
            return True, True, ""

        def start(*a):
            calls["start"] += 1

        with mock.patch.object(agent, "voice_engines", side_effect=engines), \
                mock.patch.object(agent, "voice_clone_installed", return_value=True), \
                mock.patch.object(agent, "start_voice_gateway", side_effect=start), \
                mock.patch.object(agent.time, "sleep", lambda s: None):
            self.assertTrue(agent.ensure_voice_service())
        self.assertEqual(calls["start"], 0)
        down = (False, False, "voice service is not reachable at http://127.0.0.1:5600: refused")
        with mock.patch.object(agent, "voice_engines", return_value=down):
            with self.assertRaises(agent.JobError) as cm:
                agent.ensure_voice_service()
        self.assertIn("not running on this node", str(cm.exception))


class VideoEditorTests(Base):
    def test_video_editor_service(self):
        with self.assertRaises(RuntimeError) as cm:
            agent._video_http(self.slow, "GET", "/api/jobs/1", timeout=1)
        self.assert_slow(str(cm.exception), "video editor service")
        with self.assertRaises(RuntimeError) as cm:
            agent._video_http(self.dead, "GET", "/api/jobs/1", timeout=1)
        self.assert_down(str(cm.exception), "video editor service")
        err = urllib.error.HTTPError("http://x/api", 500, "boom", {}, None)
        with mock.patch.object(agent, "http", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError):               # an answer is passed on as it is
                agent._video_http("http://x", "GET", "/api", timeout=1)

    def test_h_video_edit_reports_a_slow_editor_as_slow(self):
        job = FakeJob(self.tmp)
        job.payload = {"video": "a.mp4"}
        job.input_path = lambda n: "/x/" + n
        with mock.patch.object(agent, "http", side_effect=socket.timeout("timed out")):
            with self.assertRaises(RuntimeError) as cm:
                agent.h_video_edit(job)
        self.assert_slow(str(cm.exception), "video editor service")


class PhotoTests(Base):
    def test_photo_smart_edit_and_health(self):
        with mock.patch.object(agent, "http", side_effect=socket.timeout("timed out")):
            with self.assertRaises(RuntimeError) as cm:
                agent._photo_smart_edit(self.job, "p.jpg", {}, "goal", "stem")
        self.assert_slow(str(cm.exception), "photo service")
        with tempfile.TemporaryDirectory() as d:
            model = os.path.join(d, "model.onnx")
            open(model, "wb").close()
            with mock.patch.object(agent, "kit_dir", return_value=model), mock.patch.object(agent, "http", side_effect=socket.timeout("timed out")):
                ok, why = edit_jobs._photo_ready(agent)
            self.assertFalse(ok)
            self.assert_slow(why, "the photo service")
            refused = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
            with mock.patch.object(agent, "kit_dir", return_value=model), mock.patch.object(agent, "http", side_effect=refused):
                ok, why = edit_jobs._photo_ready(agent)
            self.assertFalse(ok)
            self.assertIn("not reachable", why)


if __name__ == "__main__":
    unittest.main()
