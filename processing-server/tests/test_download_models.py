"""download_models.py against a local fake internet (stdlib only; Windows and Linux).

    python tests\\test_download_models.py
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import download_models as dm  # noqa: E402

BIG = os.urandom(300_000)
SMALL = b"hello model"


def zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("repo-abc123/README.md", "code")
        z.writestr("repo-abc123/pkg/mod.py", "x = 1\n")
        z.writestr("repo-abc123/requirements.txt", "numpy==2.1.0\n")
    return buf.getvalue()


class Net:
    files = {}
    flaky = set()
    log = []
    hits = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        Net.log.append((path, self.headers.get("Range")))
        Net.hits[path] = Net.hits.get(path, 0) + 1
        if path.startswith("/hf/api/models/org/snap/revision/"):
            body = json.dumps({"sha": "rev1", "siblings": [
                {"rfilename": "a.bin", "size": len(BIG), "lfs": {"sha256": hashlib.sha256(BIG).hexdigest(), "size": len(BIG)}},
                {"rfilename": "cfg/config.json", "size": len(SMALL)},
                {"rfilename": "skip.md", "size": 3}]}).encode()
            return self._send(200, body, "application/json")
        if path.startswith("/simple/"):
            name = path.strip("/").split("/")[-1]
            page = {"numpy": "numpy-2.1.0-cp312-cp312-win_amd64.whl", "torch": "torch-2.9.1+cu128-cp312-cp312-win_amd64.whl"}
            if name in page:
                return self._send(200, ("<a>%s</a>" % page[name]).encode(), "text/html")
            return self._send(404, b"", "text/html")
        data = Net.files.get(path)
        if data is None:
            return self._send(404, b"nope", "text/plain")
        rng = self.headers.get("Range")
        start = 0
        if rng and rng.startswith("bytes="):
            a = rng[6:].split("-")[0]
            start = int(a or 0)
            if start >= len(data) and len(data):
                return self._send(416, b"", "text/plain", {"Content-Range": "bytes */%d" % len(data)})
            chunk = data[start:] if not rng.endswith("-0") else data[start:start + 1]
            if rng == "bytes=0-0":
                chunk = data[:1]
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, start + len(chunk) - 1, len(data)))
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            body = chunk
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            body = data
        if path in Net.flaky and Net.hits[path] == 1:
            self.wfile.write(body[: len(body) // 3])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(body)

    def _send(self, code, body, ctype, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


class DownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="nm-dl-")
        for name, value in {"NM_HOME": self.home, "MANIFEST_DIR": os.path.join(self.home, "downloads"),
                            "LOGS": os.path.join(self.home, "logs"),
                            "LOG_PATH": os.path.join(self.home, "logs", "download-models.log"),
                            "STATE_PATH": os.path.join(self.home, "logs", "download-state.json"),
                            "LOCAL_CFG": os.path.join(self.home, "downloads-local.json"),
                            "CACHE_DIR": os.path.join(self.home, "downloads-cache"),
                            "HF_DEFAULT": self.base + "/hf", "HF_FALLBACK": self.base + "/mirror",
                            "CODELOAD": self.base + "/codeload", "SAFETY_MARGIN": 0}.items():
            p = mock.patch.object(dm, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(dm.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(dm.MANIFEST_DIR)
        Net.files = {"/hf/org/m/resolve/r1/big.bin": BIG, "/mirror/org/m/resolve/r1/only-mirror.bin": SMALL,
                     "/hf/org/snap/resolve/rev1/a.bin": BIG, "/hf/org/snap/resolve/rev1/cfg/config.json": SMALL,
                     "/codeload/o/repo/zip/abc123": zip_bytes(), "/empty": b""}
        Net.flaky, Net.log, Net.hits = set(), [], {}
        self.ctx = dm.Context(interactive=False)
        self.state = dm.State()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def manifest(self, items, group="voice", name="voice.json"):
        with open(os.path.join(dm.MANIFEST_DIR, name), "w", encoding="utf-8") as fh:
            json.dump({"group": group, "title": "t", "items": items}, fh)

    def file_item(self, path="big.bin", data=BIG, **extra):
        return dict({"id": "voice:" + path, "package": "moss-tts", "kind": "file",
                     "urls": ["{HF}/org/m/resolve/r1/" + path], "dest": "{MODELS}\\m\\" + path,
                     "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}, **extra)

    # ------------------------------------------------------------ files
    def test_download_verify_and_skip_on_rerun(self):
        it = self.file_item()
        self.assertEqual(dm.do_file(it, self.ctx, self.state), "downloaded")
        dest = self.ctx.expand(it["dest"])
        self.assertEqual(open(dest, "rb").read(), BIG)
        self.assertTrue(dest.startswith(os.path.join(self.home, "models")))
        n = len(Net.log)
        self.assertEqual(dm.do_file(it, self.ctx, dm.State()), "skipped")
        self.assertEqual(len(Net.log), n, "a verified file must not be fetched again")

    def test_resume_from_part(self):
        it = self.file_item()
        dest = self.ctx.expand(it["dest"])
        os.makedirs(os.path.dirname(dest))
        open(dest + ".part", "wb").write(BIG[:100_000])
        dm.do_file(it, self.ctx, self.state)
        self.assertEqual(open(dest, "rb").read(), BIG)
        self.assertIn(("/hf/org/m/resolve/r1/big.bin", "bytes=100000-"), Net.log)

    def test_flaky_connection_is_retried_and_resumed(self):
        Net.flaky.add("/hf/org/m/resolve/r1/big.bin")
        it = self.file_item()
        dm.do_file(it, self.ctx, self.state)
        self.assertEqual(open(self.ctx.expand(it["dest"]), "rb").read(), BIG)
        self.assertTrue(any(r and r.startswith("bytes=") for p, r in Net.log if p.endswith("big.bin")))

    def test_sha_mismatch_keeps_the_file_and_fails(self):
        it = self.file_item(sha256="0" * 64)
        with self.assertRaises(dm.Fail) as ctx:
            dm.do_file(it, self.ctx, self.state)
        self.assertIn("sha256 mismatch", ctx.exception.reason)
        folder = os.path.dirname(self.ctx.expand(it["dest"]))
        self.assertTrue(any(".bad-" in n for n in os.listdir(folder)), "the bad download is renamed, never deleted")

    def test_existing_wrong_file_is_set_aside_not_deleted(self):
        it = self.file_item()
        dest = self.ctx.expand(it["dest"])
        os.makedirs(os.path.dirname(dest))
        open(dest, "wb").write(b"x" * len(BIG))          # right size, wrong content
        dm.do_file(it, self.ctx, self.state)
        self.assertEqual(open(dest, "rb").read(), BIG)
        self.assertTrue(any(".bad-" in n for n in os.listdir(os.path.dirname(dest))))

    def test_hf_falls_back_to_the_mirror_and_next_url(self):
        it = self.file_item("only-mirror.bin", SMALL)
        self.assertEqual(dm.do_file(it, self.ctx, self.state), "downloaded")
        it2 = self.file_item("big.bin", BIG, urls=[self.base + "/missing.bin", "{HF}/org/m/resolve/r1/big.bin"])
        it2["id"] = "x2"
        it2["dest"] = "{MODELS}\\other\\big.bin"
        self.assertEqual(dm.do_file(it2, self.ctx, self.state), "downloaded")

    def test_zero_byte_file(self):
        it = {"id": "e", "kind": "file", "urls": [self.base + "/empty"], "dest": "{MODELS}\\e\\__init__.py", "size": 0,
              "sha256": hashlib.sha256(b"").hexdigest()}
        dm.do_file(it, self.ctx, self.state)
        self.assertEqual(os.path.getsize(self.ctx.expand(it["dest"])), 0)

    def test_wrong_size_on_server_is_reported(self):
        it = self.file_item(size=123)
        with self.assertRaises(dm.Fail) as ctx:
            dm.do_file(it, self.ctx, self.state)
        self.assertIn("manifest says", ctx.exception.reason)

    # ------------------------------------------------------------ snapshot, git
    def test_hf_snapshot_with_globs(self):
        it = {"id": "snap", "kind": "hf_snapshot", "repo": "org/snap", "revision": "rev1",
              "files": ["*.bin", "cfg/*"], "dest": "{MODELS}\\snap"}
        self.assertEqual(dm.do_snapshot(it, self.ctx, self.state), "downloaded")
        root = self.ctx.expand(it["dest"])
        self.assertEqual(open(os.path.join(root, "a.bin"), "rb").read(), BIG)
        self.assertEqual(open(os.path.join(root, "cfg", "config.json"), "rb").read(), SMALL)
        self.assertFalse(os.path.exists(os.path.join(root, "skip.md")))

    def test_git_without_git_uses_the_commit_zip(self):
        it = {"id": "code", "kind": "git", "url": "https://github.com/o/repo", "ref": "abc123",
              "dest": "{NM_HOME}\\vendor\\repo"}
        with mock.patch.object(dm.shutil, "which", lambda name: None):
            self.assertEqual(dm.do_git(it, self.ctx, self.state), "downloaded")
            dest = self.ctx.expand(it["dest"])
            self.assertEqual(open(os.path.join(dest, "pkg", "mod.py")).read(), "x = 1\n")
            self.assertEqual(open(os.path.join(dest, ".nm-ref")).read(), "abc123")
            self.assertEqual(dm.do_git(it, self.ctx, self.state), "skipped")

    def test_git_never_touches_a_foreign_folder(self):
        it = {"id": "code", "kind": "git", "url": "https://github.com/o/repo", "ref": "abc123",
              "dest": "{NM_HOME}\\vendor\\repo"}
        dest = self.ctx.expand(it["dest"])
        os.makedirs(dest)
        open(os.path.join(dest, "mine.txt"), "w").write("keep")
        with mock.patch.object(dm.shutil, "which", lambda name: None):
            with self.assertRaises(dm.Fail):
                dm.do_git(it, self.ctx, self.state)
        self.assertEqual(open(os.path.join(dest, "mine.txt")).read(), "keep")

    # ------------------------------------------------------------ pip
    def test_pip_tries_mirrors_and_remembers_success(self):
        venv = os.path.join(self.home, "venvs", "x")
        py = os.path.join(venv, "Scripts" if dm.IS_WIN else "bin", "python.exe" if dm.IS_WIN else "python")
        os.makedirs(os.path.dirname(py))
        open(py, "w").close()
        calls = []

        def fake_run(cmd, label="", env=None, cwd=None):
            calls.append(cmd)
            self.assertTrue(env["PIP_CACHE_DIR"].startswith(self.home), "one shared pip cache under the node folder")
            return 1 if len(calls) == 1 else 0
        it = {"id": "venv-x", "kind": "pip", "python": "{VENV:x}", "python_version": "3.12",
              "packages": ["numpy==2.1.0", "torch==2.9.1+cu128"], "index_urls": ["https://pypi.org/simple"],
              "extra_index_urls": ["https://download.pytorch.org/whl/cu128"],
              "mirror_extra_index_urls": ["https://mirror.sjtu.edu.cn/pytorch-wheels/cu128"],
              "find_links_mirrors": ["https://mirrors.aliyun.com/pytorch-wheels/cu128/"]}
        with mock.patch.object(dm, "run_cmd", fake_run), mock.patch.object(dm, "python_version_of", lambda exe: ("3.12", exe)):
            self.assertEqual(dm.do_pip(it, self.ctx, self.state, ["https://mirror-pypi.runflare.com/simple"]), "downloaded")
            self.assertEqual(len(calls), 2)
            self.assertIn("https://pypi.org/simple", calls[0])
            self.assertIn("https://mirror-pypi.runflare.com/simple", calls[1])
            self.assertIn("https://mirror.sjtu.edu.cn/pytorch-wheels/cu128", calls[1])
            self.assertIn("--find-links", calls[1])
            self.assertEqual(dm.do_pip(it, self.ctx, self.state), "skipped")
            self.assertEqual(len(calls), 2, "a finished pip item is not run again")

    def test_pip_venv_needs_a_matching_python(self):
        it = {"id": "venv-y", "kind": "pip", "python": "{VENV:y}", "python_version": "3.12", "packages": ["numpy"]}
        with mock.patch.object(dm, "find_python", lambda spec: None):
            with self.assertRaises(dm.Fail) as ctx:
                dm.do_pip(it, self.ctx, self.state)
        self.assertIn("python312", ctx.exception.hint)

    # ------------------------------------------------------------ placeholders, selection
    def test_placeholders(self):
        open(os.path.join(self.home, "site.json"), "w").write('{"site": "http://example:8040/"}')
        comfy = os.path.join(self.home, "ComfyUI")
        os.makedirs(os.path.join(comfy, "custom_nodes"))
        with mock.patch.dict(os.environ, {"NM_COMFY_DIR": comfy}):
            ctx = dm.Context(interactive=False)
            self.assertEqual(ctx.expand("{SITE}/x"), "http://example:8040/x")
            self.assertEqual(ctx.expand("{COMFYUI}"), comfy)
            self.assertTrue(ctx.expand("{VENV:moss}").endswith(os.path.join("venvs", "moss")))
            self.assertEqual(ctx.expand("{MODELS}"), os.path.join(self.home, "models"))
        with mock.patch.dict(os.environ, {"NM_COMFY_DIR": "", "NM_COMFY_BAT": ""}):
            with self.assertRaises(dm.Unresolved):
                dm.Context(interactive=False, check=True).expand("{COMFYUI}\\custom_nodes")

    def test_selection(self):
        g = {"group": "voice"}
        it = {"id": "moss-tts:MOSS-TTS-Realtime/model.safetensors", "package": "moss-tts"}
        self.assertTrue(dm.selected(it, "voice", ["voice"], []))
        self.assertTrue(dm.selected(it, "voice", ["moss-tts"], []))
        self.assertFalse(dm.selected(it, "voice", ["video"], []))
        self.assertFalse(dm.selected(it, "voice", [], ["moss-tts"]))
        self.assertFalse(dm.selected(it, g["group"], [], [it["id"]]))

    # ------------------------------------------------------------ main
    def test_main_end_to_end_and_rerun(self):
        self.manifest([self.file_item(), {"id": "code", "package": "c", "kind": "git", "url": "https://github.com/o/repo",
                                          "ref": "abc123", "dest": "{NM_HOME}\\vendor\\repo"}])
        self.manifest([{"id": "snap", "kind": "hf_snapshot", "repo": "org/snap", "revision": "rev1", "files": ["*.bin"],
                        "dest": "{MODELS}\\snap"}], group="video", name="video.json")
        with mock.patch.object(dm.shutil, "which", lambda name: None):
            self.assertEqual(dm.main(["--yes"]), 0)
            n = len(Net.log)
            self.assertEqual(dm.main(["--yes"]), 0)
            self.assertEqual(len(Net.log), n, "second run downloads nothing")
            self.assertEqual(dm.main(["--yes", "--only", "video"]), 0)
        log = open(dm.LOG_PATH, encoding="utf-8").read()
        self.assertIn("skipped (already complete): 3", log)

    def test_main_reports_failures_and_keeps_going(self):
        self.manifest([{"id": "gone", "kind": "file", "urls": [self.base + "/nothing"], "dest": "{MODELS}\\g", "size": 5},
                       self.file_item()])
        self.assertEqual(dm.main(["--yes"]), 2)
        self.assertTrue(os.path.isfile(self.ctx.expand(self.file_item()["dest"])))
        log = open(dm.LOG_PATH, encoding="utf-8").read()
        self.assertIn("FAILED   gone", log)
        self.assertIn("do  :", log)

    def test_disk_check_stops_before_downloading(self):
        self.manifest([self.file_item()])
        fake = mock.Mock(free=10)
        with mock.patch.object(dm.shutil, "disk_usage", lambda p: fake):
            self.assertEqual(dm.main(["--yes"]), 3)
        self.assertFalse(Net.log, "nothing may be downloaded when the disk is too small")

    def test_check_mode(self):
        self.manifest([self.file_item(), {"id": "gone", "kind": "file", "urls": [self.base + "/nothing"],
                                          "dest": "{MODELS}\\g", "size": 5},
                       {"id": "venv-x", "kind": "pip", "python": "{VENV:x}",
                        "packages": ["numpy==2.1.0", "torch==2.9.1+cu128"], "index_urls": [self.base + "/simple"],
                        "estimate_mb": 10}])
        self.assertEqual(dm.main(["--check"]), 2)
        log = open(dm.LOG_PATH, encoding="utf-8").read()
        self.assertIn("OK   ", log)
        self.assertIn("FAIL", log)
        self.assertIn("all 2 packages listed", log)
        self.assertFalse(os.path.exists(os.path.join(self.home, "models")), "--check downloads nothing")

    def test_list_mode(self):
        self.manifest([self.file_item()])
        self.assertEqual(dm.main(["--list"]), 0)
        self.assertIn("will download", open(dm.LOG_PATH, encoding="utf-8").read())

    # ------------------------------------------------------------ 1.1: never twice, status for the panel
    def comfy(self):
        comfy = os.path.join(self.home, "ComfyUI")
        os.makedirs(os.path.join(comfy, "custom_nodes"))
        os.makedirs(os.path.join(comfy, "models", "unet"))
        return comfy

    def test_extra_model_paths_yaml(self):
        comfy = self.comfy()
        other = os.path.join(self.home, "D_models")
        os.makedirs(os.path.join(other, "wan"))
        open(os.path.join(other, "wan", "wan2.2_big.safetensors"), "wb").write(b"x" * 10)
        yaml = ("# my models\nother:\n    base_path: %s\n    is_default: true\n    diffusion_models: |\n"
                "        wan\n        unet\n    vae: vae/\n" % other.replace("\\", "/"))
        with open(os.path.join(comfy, "extra_model_paths.yaml"), "w", encoding="utf-8") as fh:
            fh.write(yaml)
        roots = dm.parse_extra_model_paths(os.path.join(comfy, "extra_model_paths.yaml"))
        self.assertIn(os.path.normpath(os.path.join(other, "wan")), roots)
        self.assertIn(os.path.normpath(os.path.join(other, "vae")), roots)
        it = {"id": "v:wan", "package": "wan22-flf", "kind": "file", "urls": [self.base + "/nothing"],
              "dest": "{COMFYUI}\\models\\diffusion_models\\wan2.2_big.safetensors", "size": 999}
        with mock.patch.dict(os.environ, {"NM_COMFY_DIR": comfy}):
            ctx = dm.Context(interactive=False)
            self.assertEqual(dm.do_file(it, ctx, self.state), "skipped")
            self.assertEqual(dm.status_of(it, ctx), "have (ComfyUI)")
        self.assertFalse(any(p == "/nothing" for p, _r in Net.log), "a model ComfyUI can load is never downloaded")

    def test_same_file_for_two_items_is_fetched_once(self):
        a = self.file_item()
        b = dict(self.file_item(), id="voice:copy", dest="{MODELS}\\other\\big.bin")
        self.manifest([a, b])
        self.assertEqual(dm.main(["--yes"]), 0)
        hits = [p for p, _r in Net.log if p.endswith("big.bin")]
        self.assertEqual(len(hits), 1, "the second item is linked, not downloaded")
        self.assertEqual(open(self.ctx.expand(b["dest"]), "rb").read(), BIG)

    def test_status_json_and_status_file(self):
        opt = dict(self.file_item("only-mirror.bin", SMALL), id="fx:small", package="fx", optional=True)
        self.manifest([self.file_item(), opt])
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            self.assertEqual(dm.main(["--status"]), 0)
        st = json.loads(out.getvalue())
        self.assertFalse(st["packages"]["moss-tts"]["installed"])
        self.assertEqual(st["packages"]["moss-tts"]["bytes_missing"], len(BIG))
        self.assertTrue(st["packages"]["fx"]["optional"])
        status_file = os.path.join(self.home, "status.json")
        self.assertEqual(dm.main(["--yes", "--status-file", status_file]), 0)
        done = json.load(open(status_file, encoding="utf-8"))
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["packages"], ["moss-tts"], "an optional package is not in the default set")
        self.assertEqual(done["bytes_done"], len(BIG))
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            dm.main(["--status"])
        self.assertTrue(json.loads(out.getvalue())["packages"]["moss-tts"]["installed"])
        self.assertFalse(os.path.exists(dm.lock_path()), "the lock is released at the end")

    def test_one_download_at_a_time(self):
        self.manifest([self.file_item()])
        os.makedirs(dm.LOGS, exist_ok=True)
        json.dump({"pid": os.getppid()}, open(dm.lock_path(), "w"))
        self.assertEqual(dm.main(["--yes"]), 4)
        self.assertFalse(Net.log, "nothing is downloaded while another run holds the lock")
        json.dump({"pid": 999999}, open(dm.lock_path(), "w"))      # a dead process: the lock is taken over
        self.assertEqual(dm.main(["--yes"]), 0)


if __name__ == "__main__":
    unittest.main()
