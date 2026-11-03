"""agent.py `ollama.pull` (the panel's «دانلود مدل») against a fake Ollama server and a fake site (stdlib only).

    python -m unittest tests/test_agent_ollama_pull.py        (from the processing folder; runs on Windows and Linux)

Covers: percent / MB / speed reported to the site, resume after a broken stream (Ollama keeps the partial bytes, the
agent asks again), fatal errors that must not be retried (disk full, unknown model), the site's allow-list (fail closed)
and the tag format check, cancel, "already installed", reading the installed models from Ollama's folder while the
server is off, and that a download does not need a model to be loaded.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))   # never the real data folder
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import agent  # noqa: E402

TOTAL = 3000          # bytes of the fake model's big layer (the real one is gigabytes; only the ratios matter)
STEP = 500


class Ollama:
    """State of the fake Ollama: installed models, bytes already on disk per tag (the -partial files) and a failure plan."""

    def __init__(self):
        self.models = {"qwq:32b"}
        self.partial = {}            # tag -> bytes already downloaded (survives a dropped stream, like Ollama's -partial files)
        self.plan = []               # per /api/pull call: "ok" | "drop" | "disk" | "missing" | "http404"
        self.pulls = []              # (tag, first completed value sent) per call
        self.tags_ok = True

    def reset(self):
        self.__init__()


OL = Ollama()


class OllamaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            if not OL.tags_ok:
                return self._json(500, {"error": "boom"})
            return self._json(200, {"models": [{"name": m} for m in sorted(OL.models)]})
        self._json(404, {"error": "no"})

    def _line(self, obj):
        data = (json.dumps(obj) + "\n").encode("utf-8")
        self.wfile.write(("%x\r\n" % len(data)).encode() + data + b"\r\n")
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        if self.path != "/api/pull":
            return self._json(404, {"error": "no"})
        tag = body.get("model") or body.get("name")
        mode = OL.plan.pop(0) if OL.plan else "ok"
        OL.pulls.append([tag, None, body.get("stream")])
        if mode == "http404":
            return self._json(404, {"error": "pull model manifest: file does not exist"})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self._line({"status": "pulling manifest"})
        if mode == "missing":
            return self._line({"error": "pull model manifest: file does not exist"})
        done = OL.partial.get(tag, 0)
        first = True
        while done < TOTAL:
            if mode == "disk" and done >= STEP:
                return self._line({"error": "write /models/blobs/sha256-x-partial: no space left on device"})
            if mode == "drop" and done >= 2 * STEP:
                OL.partial[tag] = done
                self.close_connection = True          # the connection dies without «success»
                return
            if mode == "stall" and done >= STEP:
                OL.partial[tag] = done
                self.close_connection = True
                return
            done = min(TOTAL, done + STEP)
            OL.partial[tag] = done
            row = {"status": "pulling sha256:aaaa", "digest": "sha256:aaaa", "total": TOTAL, "completed": done}
            if first:
                OL.pulls[-1][1] = done
                first = False
            self._line(row)
            time.sleep(0.01)
        self._line({"status": "pulling sha256:bbbb", "digest": "sha256:bbbb", "total": 100, "completed": 100})
        self._line({"status": "verifying sha256 digest"})
        self._line({"status": "writing manifest"})
        self._line({"status": "removing any unused layers"})
        OL.models.add(tag)
        self._line({"status": "success"})
        self.wfile.write(b"0\r\n\r\n")


class FakeSite:
    def __init__(self, payload=None, allowed=("gemma3:12b", "qwen3:14b"), cancel_after=None, list_fails=False):
        self.payload = payload or {}
        self.allowed, self.cancel_after, self.list_fails = list(allowed), cancel_after, list_fails
        self.posts, self.gets = [], []

    def get_json(self, path, timeout=30):
        self.gets.append(path)
        if self.list_fails:
            raise agent.SiteError("site unreachable")
        return {"tags": {t: {"size_mb": 8000} for t in self.allowed}}

    def post(self, path, data=None, timeout=60):
        self.posts.append((path, data))
        n = sum(1 for p, d in self.posts if p.endswith("/progress/"))
        return {"cancel": bool(self.cancel_after is not None and n > self.cancel_after)}

    def download(self, path, dest, timeout=600, attempts=5):
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr("payload.json", json.dumps({"payload": self.payload, "timeout_s": 600}))

    def upload(self, path, files, timeout=1800, attempts=4):
        return {"ok": True}

    def progress_meta(self):
        return [d["meta"] for p, d in self.posts if p.endswith("/progress/") and d and d.get("meta")]


class OllamaPullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        os.environ["NM_OLLAMA_URL"] = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.tmp = tempfile.mkdtemp(prefix="nm-agent-pull-")
        agent.WORK = os.path.join(cls.tmp, "work")
        agent.LOGS = os.path.join(cls.tmp, "logs")
        agent.CONFIG = {"name": "TEST-NODE"}
        os.environ["NM_PULL_REPORT_S"] = "0"                                  # report every line to the fake site
        cls._pause, cls._tries = agent._pull_pause, os.environ.get("NM_PULL_TRIES")
        agent._pull_pause = lambda tracker, seconds: tracker.report(force=True)     # no real waiting between attempts

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NM_PULL_REPORT_S", None)
        agent._pull_pause = cls._pause
        if cls._tries is None:
            os.environ.pop("NM_PULL_TRIES", None)
        else:
            os.environ["NM_PULL_TRIES"] = cls._tries
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        OL.reset()
        os.environ.pop("NM_PULL_TRIES", None)

    def job(self, tag="gemma3:12b", site=None, **payload):
        site = site or FakeSite()
        body = {"tag": tag, "expected_bytes": TOTAL + 100, **payload}
        site.payload = body
        j = agent.Job(site, {"uid": "p%08x" % id(site), "kind": "ollama.pull", "payload": body})
        j.fetch()
        return j, site

    # ---------------------------------------------------------------- the happy path
    def test_downloads_and_reports_percent_mb_and_speed(self):
        j, site = self.job()
        meta = agent.h_ollama_pull(j)
        self.assertEqual(meta["tag"], "gemma3:12b")
        self.assertEqual(meta["attempts"], 1)
        self.assertIn("gemma3:12b", OL.models)
        rows = site.progress_meta()
        self.assertTrue(rows, "no live progress was sent to the site")
        downloading = [r for r in rows if r["phase"] == "downloading"]
        self.assertTrue(downloading)
        self.assertTrue(all(r["kind"] == "pull" and r["tag"] == "gemma3:12b" for r in rows))
        self.assertEqual(rows[-1]["done"], TOTAL + 100)                    # both layers
        self.assertEqual(rows[-1]["total"], TOTAL + 100)
        dones = [r["done"] for r in rows]
        self.assertEqual(dones, sorted(dones), "progress went backwards")
        fractions = [d["progress"] for p, d in site.posts if p.endswith("/progress/")]
        self.assertTrue(all(0 < f <= 0.98 for f in fractions), fractions)
        out = json.load(open(j.out("pull.json"), encoding="utf-8"))
        self.assertEqual(out["tag"], "gemma3:12b")
        self.assertIn("gemma3:12b", out["models"])
        self.assertEqual(OL.pulls[0][2], True)                              # it streamed

    # ---------------------------------------------------------------- resume
    def test_a_broken_stream_is_asked_again_and_continues_from_the_partial_bytes(self):
        OL.plan = ["drop", "ok"]
        j, site = self.job()
        meta = agent.h_ollama_pull(j)
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(len(OL.pulls), 2)
        # the second stream started from what the first one had already written (Ollama's -partial files), not from zero
        self.assertEqual(OL.pulls[1][1], 3 * STEP)
        self.assertIn("gemma3:12b", OL.models)
        phases = [r["phase"] for r in site.progress_meta()]
        self.assertIn("retry", phases)
        retry = [r for r in site.progress_meta() if r["phase"] == "retry"][0]
        self.assertEqual(retry["attempt"], 1)
        # bytes reported never dropped while retrying
        dones = [r["done"] for r in site.progress_meta()]
        self.assertEqual(dones, sorted(dones))

    def test_a_stream_that_never_gets_anywhere_gives_up_with_a_clear_reason(self):
        OL.plan = ["stall"] * 20
        OL.partial["gemma3:12b"] = 0
        os.environ["NM_PULL_TRIES"] = "30"
        j, _site = self.job()
        # the fake stalls after the first bytes every time; progress is made on attempt 1 only, then nothing
        with self.assertRaises(agent.JobError) as cm:
            agent.h_ollama_pull(j)
        self.assertEqual(cm.exception.retryable, False)
        self.assertIn("NO_PROGRESS", str(cm.exception))
        self.assertIn("|", str(cm.exception))                                # the Persian half for the panel
        self.assertLessEqual(len(OL.pulls), 8)

    # ---------------------------------------------------------------- fatal errors are not retried
    def test_disk_full_is_fatal_and_not_retried(self):
        OL.plan = ["disk"]
        j, _site = self.job()
        with self.assertRaises(agent.JobError) as cm:
            agent.h_ollama_pull(j)
        self.assertIn("DISK_FULL", str(cm.exception))
        self.assertFalse(cm.exception.retryable)
        self.assertEqual(len(OL.pulls), 1)

    def test_a_model_the_registry_does_not_have_is_fatal(self):
        for plan in ("missing", "http404"):
            OL.reset()
            OL.plan = [plan]
            j, _site = self.job()
            with self.assertRaises(agent.JobError) as cm:
                agent.h_ollama_pull(j)
            self.assertIn("NOT_FOUND", str(cm.exception), plan)
            self.assertFalse(cm.exception.retryable)
            self.assertEqual(len(OL.pulls), 1, plan)

    # ---------------------------------------------------------------- the allow-list
    def test_a_tag_that_is_not_on_the_sites_list_is_never_pulled(self):
        site = FakeSite(allowed=("qwen3:14b",))
        j, _ = self.job("gemma3:12b", site=site)
        with self.assertRaises(agent.JobError) as cm:
            agent.h_ollama_pull(j)
        self.assertIn("NOT_ALLOWED", str(cm.exception))
        self.assertFalse(cm.exception.retryable)
        self.assertEqual(OL.pulls, [])
        self.assertEqual(site.gets, ["/api/v1/compute/ollama/pullable/"])

    def test_when_the_site_cannot_be_asked_nothing_is_pulled(self):
        site = FakeSite(list_fails=True)
        j, _ = self.job("gemma3:12b", site=site)
        with self.assertRaises(agent.JobError) as cm:
            agent.h_ollama_pull(j)
        self.assertIn("NOT_ALLOWED", str(cm.exception))
        self.assertEqual(OL.pulls, [])

    def test_bad_tags_are_refused_before_anything_else(self):
        bad = ["gemma3:12b; rm -rf /", "../evil:1", "-oops:1", "no-colon", "a b:c", "x:y:z", "", "http://evil/x:1", "a//b:c",
               "gemma3:12b\n", "gemma3:12b&calc"]
        for tag in bad:
            self.assertFalse(agent.valid_pull_tag(tag), repr(tag))
            if tag.strip() != tag or not tag:           # the handler strips the payload first (a trailing newline is harmless)
                continue
            j, site = self.job(tag)
            with self.assertRaises(agent.JobError) as cm:
                agent.h_ollama_pull(j)
            self.assertIn("BAD_TAG", str(cm.exception), repr(tag))
            self.assertEqual(site.gets, [], "the site was asked about %r" % tag)
        self.assertEqual(OL.pulls, [])
        for good in ("gemma3:12b", "qwen3:14b", "qwq:32b", "qwen3-coder:30b", "library/gemma3:12b", "Dorna2:Q4_K_M"):
            self.assertTrue(agent.valid_pull_tag(good), good)
        # a host-qualified name (two slashes) is never accepted: only «model:tag» and «namespace/model:tag»
        self.assertFalse(agent.valid_pull_tag("hf.co/org/model:Q4_K_M"))

    def test_ollama_not_running_and_not_startable_says_so_at_once(self):
        old = os.environ["NM_OLLAMA_URL"]
        os.environ["NM_OLLAMA_URL"] = "http://127.0.0.1:9"                 # nothing listens
        try:
            j, _site = self.job()
            with self.assertRaises(agent.JobError) as cm:
                agent.h_ollama_pull(j)
        finally:
            os.environ["NM_OLLAMA_URL"] = old
        self.assertIn("OLLAMA_DOWN", str(cm.exception))
        self.assertIn("|", str(cm.exception))
        self.assertFalse(cm.exception.retryable)
        self.assertEqual(OL.pulls, [])

    # ---------------------------------------------------------------- cancel / already installed
    def test_cancel_from_the_panel_stops_the_download(self):
        site = FakeSite(cancel_after=2)
        j, _ = self.job(site=site)
        with self.assertRaises(agent.Cancelled):
            agent.h_ollama_pull(j)
        self.assertNotIn("gemma3:12b", OL.models)
        self.assertTrue(agent.PULL_LOCK.acquire(blocking=False), "the download lock was left taken")
        agent.PULL_LOCK.release()

    def test_a_model_that_is_already_installed_is_not_downloaded_again(self):
        OL.models.add("gemma3:12b")
        j, _site = self.job()
        meta = agent.h_ollama_pull(j)
        self.assertEqual(meta["attempts"], 0)
        self.assertEqual(OL.pulls, [])

    # ---------------------------------------------------------------- the node's own bookkeeping
    def test_installed_models_are_read_from_the_ollama_folder_when_the_server_is_off(self):
        root = os.path.join(self.tmp, "ollama-models")
        for rel in ("registry.ollama.ai/library/qwen3/14b", "registry.ollama.ai/library/qwq/32b",
                    "registry.ollama.ai/library/llava/latest", "registry.ollama.ai/someone/dorna/q4",
                    "hf.co/org/repo/Q4_K_M"):
            path = os.path.join(root, "manifests", *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write("{}")
        os.makedirs(os.path.join(root, "manifests", "registry.ollama.ai", "library", "empty-dir"), exist_ok=True)
        names = agent.ollama_models_on_disk(root)
        self.assertEqual(sorted(names), sorted(["qwen3:14b", "qwq:32b", "llava:latest", "someone/dorna:q4", "hf.co/org/repo:Q4_K_M"]))
        self.assertEqual(agent.ollama_models_on_disk(os.path.join(self.tmp, "nowhere")), [])

    def test_the_agent_says_it_can_pull_and_lists_the_disk_models_when_ollama_is_down(self):
        root = os.path.join(self.tmp, "ollama-models2")
        path = os.path.join(root, "manifests", "registry.ollama.ai", "library", "gemma3", "12b")
        os.makedirs(os.path.dirname(path))
        open(path, "w").write("{}")
        old_url, old_models = os.environ.get("NM_OLLAMA_URL"), os.environ.get("OLLAMA_MODELS")
        os.environ["NM_OLLAMA_URL"] = "http://127.0.0.1:9"                 # nothing listens: Ollama is "off"
        os.environ["OLLAMA_MODELS"] = root
        try:
            caps = agent.Capabilities("TEST-NODE", 1).probe()
        finally:
            os.environ["NM_OLLAMA_URL"] = old_url
            if old_models is None:
                os.environ.pop("OLLAMA_MODELS", None)
            else:
                os.environ["OLLAMA_MODELS"] = old_models
        self.assertIs(caps["ollama_pull"], True)
        self.assertFalse(caps["ollama"])
        self.assertEqual(caps["ollama_models"], ["gemma3:12b"])
        self.assertEqual(caps["ollama_models_source"], "disk")

    def test_a_download_prepares_nothing_and_runs_in_the_background(self):
        # no model is loaded by a download: it must not free ComfyUI / audio memory or demand a running service
        class Boom:
            def __getattr__(self, name):
                raise AssertionError("prepare_for touched %s" % name)
        self.assertIsNone(agent.ServiceManager.prepare_for(Boom(), "ollama.pull", True))
        self.assertIn("ollama.pull", agent.BACKGROUND_KINDS)
        self.assertIs(agent.HANDLERS["ollama.pull"], agent.h_ollama_pull)

    def test_two_downloads_do_not_run_at_once(self):
        order = []
        OL.plan = ["ok", "ok"]
        results = {}

        def run(tag):
            j, _ = self.job(tag)
            order.append(("start", tag))
            results[tag] = agent.h_ollama_pull(j)
            order.append(("end", tag))

        t1 = threading.Thread(target=run, args=("gemma3:12b",))
        t2 = threading.Thread(target=run, args=("qwen3:14b",))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(30)
        t2.join(30)
        self.assertEqual(sorted(results), ["gemma3:12b", "qwen3:14b"])
        self.assertEqual(len(OL.pulls), 2)
        # strictly one after the other: the first pull call finished all its bytes before the second began
        self.assertEqual(OL.pulls[0][0], "gemma3:12b")


if __name__ == "__main__":
    unittest.main()
