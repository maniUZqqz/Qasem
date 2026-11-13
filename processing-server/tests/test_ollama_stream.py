"""agent 2.11: streamed ollama.generate / ollama.chat against a fake Ollama that streams slowly, loads slowly, stalls or is down."""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ollama_jobs as oj  # noqa: E402


class FakeOllama:
    """Behaviour is set per test: load_delay (silence before the first byte), tokens, token_gap, stall_after (go silent after N
    tokens), status (HTTP error), ps (answer of /api/ps)."""

    def __init__(self, **kw):
        self.cfg = dict(load_delay=0.0, tokens=["سلام", " دنیا", "!"], token_gap=0.0, stall_after=None, status=200, body="",
                        ps={"models": [{"name": "qwen3:8b", "size": 6000000000, "size_vram": 6000000000}]},
                        tags={"models": [{"name": "qwen3:8b", "size": 5200000000}]}, thinking=None)
        self.cfg.update(kw)
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, obj):
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    return self._json(outer.cfg["tags"])
                if self.path == "/api/ps":
                    return self._json(outer.cfg["ps"])
                self.send_error(404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append((self.path, body))
                c = outer.cfg
                time.sleep(c["load_delay"])
                if c["status"] != 200:
                    data = c["body"].encode()
                    self.send_response(c["status"])
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                chat = self.path.endswith("/chat")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def chunk(obj):
                    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
                    self.wfile.flush()
                try:
                    for i, tok in enumerate(c["tokens"]):
                        if c["stall_after"] is not None and i >= c["stall_after"]:
                            time.sleep(30)
                            return
                        o = {"model": body.get("model"), "done": False}
                        if chat:
                            o["message"] = {"role": "assistant", "content": tok}
                        else:
                            o["response"] = tok
                        chunk(o)
                        time.sleep(c["token_gap"])
                    final = {"model": body.get("model"), "done": True, "done_reason": "stop", "total_duration": 5, "load_duration": 3000000000,
                             "prompt_eval_count": 7, "eval_count": len(c["tokens"])}
                    final["message" if chat else "response"] = {"role": "assistant", "content": ""} if chat else ""
                    chunk(final)
                    self.wfile.write(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class StreamTests(unittest.TestCase):
    def test_a_slowly_streamed_generation_is_folded_into_the_plain_answer(self):
        srv = FakeOllama(token_gap=0.15)
        try:
            lines = []
            objs = oj.stream_request(srv.url, "/api/generate", {"model": "m", "prompt": "hi"}, on_line=lines.append)
            self.assertEqual(srv.requests[0][1]["stream"], True)            # always asks for a stream
            out = oj.fold(objs, False)
            self.assertEqual(out["response"], "سلام دنیا!")
            self.assertTrue(out["done"])
            self.assertEqual(out["eval_count"], 3)
            self.assertEqual(len(lines), 4)
        finally:
            srv.close()

    def test_chat_is_folded_into_one_message(self):
        srv = FakeOllama()
        try:
            objs = oj.stream_request(srv.url, "/api/chat", {"model": "m", "messages": [{"role": "user", "content": "x"}]})
            out = oj.fold(objs, True)
            self.assertEqual(out["message"], {"role": "assistant", "content": "سلام دنیا!"})
        finally:
            srv.close()

    def test_a_long_load_before_the_first_byte_is_not_a_failure(self):
        srv = FakeOllama(load_delay=2.5)                    # the model is being read from disk: nothing for 2.5 s
        try:
            ticks = []
            objs = oj.stream_request(srv.url, "/api/generate", {"model": "m"}, first_byte_s=30, idle_s=5, tick=ticks.append)
            self.assertEqual(oj.fold(objs, False)["response"], "سلام دنیا!")
            self.assertTrue(ticks)                          # the caller was told it is still loading (keeps the lease alive)
        finally:
            srv.close()

    def test_silence_before_the_first_byte_longer_than_the_budget_is_a_read_timeout_not_unreachable(self):
        srv = FakeOllama(load_delay=6)
        try:
            with self.assertRaises(oj.OllamaReadTimeout) as cm:
                oj.stream_request(srv.url, "/api/generate", {"model": "m"}, first_byte_s=2, idle_s=2)
            self.assertEqual(cm.exception.phase, "first-byte")
            self.assertIn("still loading", str(cm.exception))
        finally:
            srv.close()

    def test_a_stall_in_the_middle_is_an_idle_timeout(self):
        srv = FakeOllama(stall_after=2)
        try:
            with self.assertRaises(oj.OllamaReadTimeout) as cm:
                oj.stream_request(srv.url, "/api/generate", {"model": "m"}, first_byte_s=5, idle_s=2)
            self.assertEqual(cm.exception.phase, "idle")
        finally:
            srv.close()

    def test_nothing_listening_is_a_connect_error(self):
        with self.assertRaises(oj.OllamaConnectError):
            oj.stream_request("http://127.0.0.1:%d" % free_port(), "/api/generate", {"model": "m"})

    def test_http_errors_are_typed(self):
        srv = FakeOllama(status=404, body='{"error":"model \'zz\' not found"}')
        try:
            with self.assertRaises(oj.OllamaHTTPError) as cm:
                oj.stream_request(srv.url, "/api/generate", {"model": "zz"})
            self.assertEqual(cm.exception.status, 404)
            self.assertIn("not installed", oj.friendly_http(404, cm.exception.body, "zz"))
        finally:
            srv.close()

    def test_cancel_stops_the_stream(self):
        srv = FakeOllama(token_gap=0.3, tokens=["a"] * 50)
        try:
            t0 = time.time()
            n = [0]

            def cancelled():
                return n[0] >= 2
            with self.assertRaises(InterruptedError):
                oj.stream_request(srv.url, "/api/generate", {"model": "m"}, cancelled=cancelled, on_line=lambda o: n.__setitem__(0, n[0] + 1))
            self.assertLess(time.time() - t0, 5)
        finally:
            srv.close()

    def test_the_job_time_limit_ends_a_never_ending_answer(self):
        srv = FakeOllama(token_gap=0.2, tokens=["a"] * 500)
        try:
            with self.assertRaises(oj.OllamaReadTimeout) as cm:
                oj.stream_request(srv.url, "/api/generate", {"model": "m"}, total_s=1.5)
            self.assertEqual(cm.exception.phase, "limit")
        finally:
            srv.close()


class PrepareTests(unittest.TestCase):
    def test_num_ctx_is_chosen_from_the_model_size_and_keep_alive_is_set(self):
        get = lambda url: {"models": [{"name": "qwen3:8b", "size": 5.2e9}]}                 # noqa: E731
        path, body, info = oj.prepare_body({"model": "qwen3:8b", "prompt": "hi"}, "http://x", 12288, get)
        self.assertEqual(path, "/api/generate")
        self.assertGreaterEqual(body["options"]["num_ctx"], 16384)
        self.assertEqual(body["keep_alive"], oj.DEFAULT_KEEP_ALIVE)
        self.assertEqual(info["num_ctx"], body["options"]["num_ctx"])

    def test_the_jobs_own_settings_win(self):
        get = lambda url: {"models": [{"name": "m", "size": 5.2e9}]}                         # noqa: E731
        path, body, _ = oj.prepare_body({"model": "m", "messages": [], "options": {"num_ctx": 2048, "temperature": 0.2}, "keep_alive": 0},
                                        "http://x", 12288, get)
        self.assertEqual(path, "/api/chat")
        self.assertEqual(body["options"]["num_ctx"], 2048)
        self.assertEqual(body["keep_alive"], 0)

    def test_a_model_larger_than_the_card_is_flagged(self):
        get = lambda url: {"models": [{"name": "qwq:32b", "size": 19.9e9}]}                  # noqa: E731
        _p, body, info = oj.prepare_body({"model": "qwq:32b", "prompt": "x"}, "http://x", 12288, get)
        self.assertTrue(info["too_big"])
        self.assertEqual(body["options"]["num_ctx"], 4096)

    def test_a_missing_tags_answer_does_not_block_the_job(self):
        def boom(url):
            raise OSError("down")
        _p, body, info = oj.prepare_body({"model": "m", "prompt": "x"}, "http://x", 12288, boom)
        self.assertNotIn("options", body)
        self.assertEqual(info, {})


class FakeJob:
    def __init__(self, tmp, payload, timeout_s=120):
        self.payload, self.timeout_s, self.cancelled = payload, timeout_s, False
        self.dir = tmp
        self.outputs = os.path.join(tmp, "outputs")
        os.makedirs(self.outputs, exist_ok=True)
        self.said = []

    def out(self, name):
        return os.path.join(self.outputs, name)

    def input_path(self, name):
        return None

    def input_bytes(self, name):
        raise RuntimeError("no inputs")

    def progress(self, frac, msg="", meta=None):
        self.said.append((frac, msg))


class FakeAgent:
    class JobError(RuntimeError):
        def __init__(self, message, retryable=True):
            super().__init__(message)
            self.retryable = retryable

    class Cancelled(Exception):
        pass

    def __init__(self, url, tmp):
        self._url, self.warnings = url, []

    def service_url(self, key):
        return self._url

    def vram_mb(self):
        return 2000, 12288

    def http(self, method, url, data=None, headers=None, timeout=60, raw=False):
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def warn(self, msg):
        self.warnings.append(msg)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_long_generation_writes_ollama_json_like_a_plain_call_and_reports_the_device(self):
        srv = FakeOllama(token_gap=0.2, tokens=["x"] * 12)
        try:
            job = FakeJob(self.tmp, {"model": "qwen3:8b", "prompt": "hello", "stream": False})
            agent = FakeAgent(srv.url, self.tmp)
            oj.PROGRESS_EVERY_S = 0.3
            meta = oj.run(job, agent)
            with open(job.out("ollama.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["response"], "x" * 12)
            self.assertEqual(data["done"], True)
            self.assertEqual(meta["primary"], "ollama.json")
            self.assertEqual(meta["device"], "cuda")
            self.assertTrue(meta["streamed"])
            self.assertGreaterEqual(len([m for _f, m in job.said if "tokens" in m]), 2)       # the site is told while it generates
            self.assertEqual(meta["load_s"], 3.0)
        finally:
            oj.PROGRESS_EVERY_S = 8.0
            srv.close()

    def test_a_partly_offloaded_model_is_reported_as_mixed(self):
        srv = FakeOllama(ps={"models": [{"name": "qwq:32b", "size": 20000, "size_vram": 8000}]})
        try:
            meta = oj.run(FakeJob(self.tmp, {"model": "qwq:32b", "prompt": "x"}), FakeAgent(srv.url, self.tmp))
            self.assertEqual(meta["device"], "mixed")
            self.assertIn("40%", meta["device_note"])
        finally:
            srv.close()

    def test_down_service_says_not_reachable_and_slow_service_does_not(self):
        agent = FakeAgent("http://127.0.0.1:%d" % free_port(), self.tmp)
        with self.assertRaises(FakeAgent.JobError) as cm:
            oj.run(FakeJob(self.tmp, {"model": "m", "prompt": "x"}), agent)
        self.assertIn("not reachable", str(cm.exception))
        srv = FakeOllama(load_delay=8)
        try:
            old = (oj.FIRST_BYTE_S, oj.IDLE_S)
            oj.FIRST_BYTE_S, oj.IDLE_S = 2, 2
            try:
                with self.assertRaises(FakeAgent.JobError) as cm2:
                    oj.run(FakeJob(self.tmp, {"model": "m", "prompt": "x"}), FakeAgent(srv.url, self.tmp))
            finally:
                oj.FIRST_BYTE_S, oj.IDLE_S = old
            self.assertNotIn("not reachable", str(cm2.exception))
            self.assertIn("did not finish in time", str(cm2.exception))
        finally:
            srv.close()

    def test_model_not_found_is_a_clear_message(self):
        srv = FakeOllama(status=404, body='{"error":"model not found"}')
        try:
            with self.assertRaises(FakeAgent.JobError) as cm:
                oj.run(FakeJob(self.tmp, {"model": "zz", "prompt": "x"}), FakeAgent(srv.url, self.tmp))
            self.assertIn("not installed on this node", str(cm.exception))
            self.assertIs(cm.exception.retryable, False)          # asking again will not install the model
        finally:
            srv.close()

    def test_a_cancelled_job_stops(self):
        srv = FakeOllama(token_gap=0.2, tokens=["a"] * 60)
        try:
            job = FakeJob(self.tmp, {"model": "m", "prompt": "x"})
            threading.Timer(0.8, lambda: setattr(job, "cancelled", True)).start()
            with self.assertRaises(FakeAgent.Cancelled):
                oj.run(job, FakeAgent(srv.url, self.tmp))
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
