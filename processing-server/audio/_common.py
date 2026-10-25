"""Shared scaffolding of the GPU audio workers (MOSS-TTS, MOSS-SoundEffect).

Each worker is a tiny local HTTP server started by agent.py inside its own virtual environment
(venvs\\<name>, made by Download-Models.bat). The port opens at once and the model loads in the background,
so the agent can tell "still loading" (GET /health -> status "loading") from "broken" ("error").

    GET  /health   {"engine", "status": loading|ready|error, "error", "device", "load_seconds", "busy"}
    POST /run      JSON job -> JSON result; the audio is written to body["out"] (a path on this computer)

--fake runs the same protocol without torch or models (a sine wave instead of a voice): for tests and for a
first smoke check on a node. --parent-pid makes the worker exit with the agent, so VRAM is never left held by
a worker nobody controls. Standard library only, apart from what load() imports.
"""
import argparse
import json
import math
import os
import struct
import sys
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class WorkerError(Exception):
    """A failure the agent passes on as is: status 400 (bad request) / 500 / 507 (out of GPU memory)."""

    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status


def parent_alive(pid):
    if not pid:
        return True
    if sys.platform.startswith("win"):
        import ctypes

        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259                   # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def write_wav(path, samples, rate):
    """float samples (list or 1-D sequence, -1..1) -> 16-bit mono WAV, without numpy."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples))


def fake_tone(seconds, rate=24000, freq=220.0):
    n = int(max(0.1, float(seconds)) * rate)
    return [0.2 * math.sin(2 * math.pi * freq * i / rate) for i in range(n)]


def is_oom(exc):
    text = "%s %s" % (type(exc).__name__, exc)
    return "OutOfMemory" in text or "out of memory" in text.lower()


class Worker:
    """Subclass: name, load(args) -> None (sets up self.*), run(body) -> dict, fake_run(body) -> dict."""

    name = "worker"

    def __init__(self, args):
        self.args = args
        self.status = "loading"
        self.error = ""
        self.device = ""
        self.load_seconds = None
        self.busy = 0
        self.lock = threading.Lock()

    def start_loading(self):
        def target():
            t0 = time.time()
            try:
                if self.args.fake:
                    time.sleep(float(os.environ.get("NM_FAKE_LOAD_S", "0.2")))
                    self.device = "fake"
                else:
                    self.load(self.args)
                self.status = "ready"
            except Exception as e:  # noqa: BLE001 - reported through /health
                self.status = "error"
                self.error = "%s: %s" % (type(e).__name__, e)
                traceback.print_exc()
            self.load_seconds = round(time.time() - t0, 1)
            print("[%s] %s in %ss %s" % (self.name, self.status, self.load_seconds, self.error), flush=True)
        threading.Thread(target=target, daemon=True).start()

    def health(self):
        return {"engine": self.name, "status": self.status, "error": self.error, "device": self.device,
                "load_seconds": self.load_seconds, "busy": self.busy, "pid": os.getpid()}

    def handle(self, body):
        if self.status == "loading":
            raise WorkerError("model is still loading", 503)
        if self.status == "error":
            raise WorkerError("model failed to load: " + self.error, 500)
        out = body.get("out")
        if not out:
            raise WorkerError("'out' (output path) is required", 400)
        with self.lock:
            self.busy += 1
            try:
                return self.fake_run(body) if self.args.fake else self.run(body)
            except WorkerError:
                raise
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                if is_oom(e):
                    self.free_memory()
                    raise WorkerError("GPU out of memory: %s" % str(e)[:300], 507)
                raise WorkerError("%s: %s" % (type(e).__name__, str(e)[:500]), 500)
            finally:
                self.busy -= 1

    def free_memory(self):
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    # subclasses
    def load(self, args):  # pragma: no cover - needs a GPU
        raise NotImplementedError

    def run(self, body):  # pragma: no cover - needs a GPU
        raise NotImplementedError

    def fake_run(self, body):
        seconds = float(body.get("seconds") or 1.5)
        write_wav(body["out"], fake_tone(seconds), 24000)
        return {"ok": True, "seconds": seconds, "sample_rate": 24000, "fake": True}


def serve(worker_cls, default_port, extra_args=None):
    ap = argparse.ArgumentParser(description="UpMarket GPU audio worker: %s" % worker_cls.name)
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--home", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="the processing folder (models\\ and vendor\\ live there)")
    ap.add_argument("--parent-pid", type=int, default=0)
    ap.add_argument("--fake", action="store_true", help="no models: answer with a test tone (tests, smoke check)")
    for args, kwargs in extra_args or []:
        ap.add_argument(*args, **kwargs)
    args = ap.parse_args()
    worker = worker_cls(args)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):
            sys.stdout.write("[%s] %s\n" % (worker.name, fmt % a))

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/health":
                return self._send(200, worker.health())
            return self._send(404, {"error": "unknown path"})

        def do_POST(self):
            if self.path.split("?")[0] != "/run":
                return self._send(404, {"error": "unknown path"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if not isinstance(body, dict):
                    raise WorkerError("JSON object expected", 400)
                return self._send(200, worker.handle(body))
            except WorkerError as e:
                return self._send(e.status, {"error": str(e)})
            except ValueError as e:
                return self._send(400, {"error": "bad JSON: %s" % e})

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    worker.start_loading()

    def watchdog():
        while True:
            time.sleep(5)
            if not parent_alive(args.parent_pid):
                print("[%s] the agent (pid %s) is gone - exiting to free the GPU" % (worker.name, args.parent_pid), flush=True)
                os._exit(0)
    if args.parent_pid:
        threading.Thread(target=watchdog, daemon=True).start()
    print("[%s] listening on http://%s:%d (%s)" % (worker.name, args.host, args.port, "fake" if args.fake else "models"),
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
