"""Model catalog on the node: the curated ComfyUI / Hugging Face manifests, the downloader's catalog features (`needs`, `aliases`,
licence classes, --catalog, --status) and the automatic mode (model_auto.py). Stdlib only; Windows and Linux.

    python -m unittest tests/test_model_catalog_node.py        (from the processing folder)

No internet: the downloads go to a local fake Hugging Face; the automatic mode runs on a fake DownloadManager and a fake clock.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))   # never the real data folder
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
import download_models as dm  # noqa: E402
import model_auto as ma  # noqa: E402

NEW = ["image.json", "upscale.json", "control.json", "depth.json", "video-extra.json"]
GB = 2 ** 30


# ───────────────────────────────────────────── the real manifests

class RealManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups = dm.load_manifests()
        cls.by_file = {g["_file"]: g for g in cls.groups}
        cls.info = dm.package_info(cls.groups)

    def test_all_manifests_load_and_the_new_ones_are_there(self):
        for name in NEW:
            self.assertIn(name, self.by_file, name)
            self.assertTrue(self.by_file[name]["items"], name)
        for name in ("voice.json", "video.json", "matting.json", "photo.json"):
            self.assertIn(name, self.by_file)

    def test_package_info_for_every_new_package(self):
        want = {"flux-schnell", "flux-dev", "flux-common", "flux-fill", "sdxl-base", "sdxl-realvis", "esrgan-x4plus", "ultrasharp-4x",
                "nmkd-siax-4x", "face-restore", "codeformer", "controlnet-union-sdxl", "controlnet-union-flux", "ipadapter-sdxl",
                "depth-anything-v2-small", "wan22-ti2v-5b", "ltx-video-distilled", "frame-interp"}
        self.assertLessEqual(want, set(self.info))
        for pk in want:
            row = self.info[pk]
            self.assertTrue(row["title_fa"] and row["note_fa"] and row["license"], pk)
            self.assertIn(row["license_class"], dm.LICENSE_CLASSES)
            self.assertGreater(row["size"], 0, pk)
            self.assertTrue(row["optional"], pk)

    def test_non_open_never_in_the_default_set_or_all(self):
        default = {(it.get("package") or it["id"]) for _g, it in dm.plan(self.groups, [], [])}
        every = {(it.get("package") or it["id"]) for _g, it in dm.plan(self.groups, [], [], everything=True)}
        for pk, row in self.info.items():
            if pk in NEW_PACKAGES:
                self.assertNotIn(pk, default, "%s must never be downloaded by default" % pk)
            if row["license_class"] != "open":
                self.assertNotIn(pk, every, "--all must not take %s (%s)" % (pk, row["license_class"]))
                self.assertFalse(row["auto"], pk)
        self.assertIn("depth-anything-v2-small", every)       # --all still takes the open optional ones
        self.assertIn("esrgan-x4plus", every)

    def test_only_a_package_also_takes_what_it_needs(self):
        rows = dm.plan(self.groups, ["flux-schnell"], [])
        pk = {(it.get("package") or it["id"]) for _g, it in rows}
        self.assertEqual(pk, {"flux-schnell", "flux-common"})
        rows = dm.plan(self.groups, ["ipadapter-sdxl"], [])
        self.assertEqual({(it.get("package")) for _g, it in rows}, {"ipadapter-sdxl", "sdxl-base", "nodes-ipadapter-plus"})
        skipped = {it.get("package") for _g, it in dm.plan(self.groups, ["flux-schnell"], ["flux-common"])}
        self.assertEqual(skipped, {"flux-schnell"})                      # --skip still wins over `needs`

    def test_pinned_urls_sizes_and_hashes(self):
        for name in NEW:
            for it in self.by_file[name]["items"]:
                if it["kind"] == "file":
                    self.assertTrue(re.match(r"^\{HF\}/.+/resolve/[0-9a-f]{40}/", it["urls"][0]), it["id"])
                    self.assertTrue(re.match(r"^[0-9a-f]{64}$", it["sha256"]), it["id"])
                    self.assertGreater(it["size"], 0)
                else:
                    self.assertTrue(re.match(r"^[0-9a-f]{40}$", it["ref"]), it["id"])

    def test_catalog_json_and_list_show_every_group(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dm.main(["--catalog"]), 0)
        data = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(data["version"], dm.VERSION)
        self.assertIn("flux-schnell", data["packages"])
        self.assertEqual(data["packages"]["flux-schnell"]["needs"], ["flux-common"])
        self.assertEqual(data["packages"]["flux-dev"]["license_class"], "noncommercial")
        # --list (no ComfyUI on this machine: it still lists the packages) mentions each new group and the licence tags
        out = io.StringIO()
        env = {"NM_COMFY_DIR": os.path.join(tempfile.gettempdir(), "no-such-comfy"), "NM_HOME": tempfile.mkdtemp(prefix="nm-list-")}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            self.assertEqual(dm.main(["--list"]), 0)
        text = out.getvalue()
        for g in ("[image]", "[upscale]", "[control]", "[depth]", "[video-extra]"):
            self.assertIn(g, text)
        for tag in ("NON-COMMERCIAL", "LICENCE CONDITIONS", "open licence", "needs:flux-common", "12GB:offload"):
            self.assertIn(tag, text)
        shutil.rmtree(env["NM_HOME"], ignore_errors=True)


NEW_PACKAGES = {"flux-schnell", "flux-dev", "flux-common", "flux-fill", "flux-kontext", "sdxl-base", "sdxl-realvis", "zimage-turbo",
                "esrgan-x4plus", "ultrasharp-4x", "nmkd-siax-4x", "face-restore", "codeformer", "controlnet-union-sdxl",
                "controlnet-union-flux", "ipadapter-sdxl", "nodes-ipadapter-plus", "depth-anything-v2-small", "wan22-ti2v-5b",
                "ltx-video-distilled", "frame-interp"}


# ───────────────────────────────────────────── downloads against a fake Hugging Face

COMMON = {"t5.bin": os.urandom(5000), "clipl.bin": os.urandom(700)}
SCHNELL = os.urandom(9000)
DEV = os.urandom(8000)


class Net:
    files = {}
    hits = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        Net.hits[path] = Net.hits.get(path, 0) + 1
        data = Net.files.get(path)
        if data is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng == "bytes=0-0":
            self.send_response(206)
            self.send_header("Content-Range", "bytes 0-0/%d" % len(data))
            self.send_header("Content-Length", "1")
            self.end_headers()
            self.wfile.write(data[:1])
            return
        start = int(rng[6:].split("-")[0] or 0) if rng and rng.startswith("bytes=") else 0
        chunk = data[start:]
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(data) - 1, len(data)))
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)


def item(pkg, slug, repo, rel, data, dest, **extra):
    return dict({"id": "%s:%s" % (pkg, slug), "package": pkg, "kind": "file", "optional": True,
                 "urls": ["{HF}/%s/resolve/%s/%s" % (repo, "a" * 40, rel)], "dest": dest, "size": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}, **extra)


class CatalogDownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="nm-cat-")
        self.comfy = os.path.join(self.home, "ComfyUI")
        os.makedirs(os.path.join(self.comfy, "custom_nodes"))
        os.makedirs(os.path.join(self.comfy, "models", "checkpoints"))
        for name, value in {"NM_HOME": os.path.join(self.home, "data"), "MANIFEST_DIR": os.path.join(self.home, "downloads"),
                            "LOGS": os.path.join(self.home, "data", "logs"),
                            "LOG_PATH": os.path.join(self.home, "data", "logs", "download-models.log"),
                            "STATE_PATH": os.path.join(self.home, "data", "logs", "download-state.json"),
                            "LOCAL_CFG": os.path.join(self.home, "data", "downloads-local.json"),
                            "CACHE_DIR": os.path.join(self.home, "data", "cache"),
                            "HF_DEFAULT": self.base + "/hf", "HF_FALLBACK": self.base + "/mirror", "SAFETY_MARGIN": 0}.items():
            p = mock.patch.object(dm, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"NM_COMFY_DIR": self.comfy})
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(dm.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(dm.MANIFEST_DIR)
        os.makedirs(dm.NM_HOME)
        Net.files = {"/hf/o/enc/resolve/%s/%s" % ("a" * 40, k): v for k, v in COMMON.items()}
        Net.files["/hf/o/schnell/resolve/%s/s.bin" % ("a" * 40)] = SCHNELL
        Net.files["/hf/o/dev/resolve/%s/d.bin" % ("a" * 40)] = DEV
        Net.hits = {}
        C = "{COMFYUI}\\models\\"
        doc = {"group": "image", "title": "t", "packages": {"flux-common": "enc", "flux-schnell": "s", "flux-dev": "d"},
               "package_info": {
                   "flux-common": {"display": "image", "license_class": "open", "needs": [], "auto": False},
                   "flux-schnell": {"display": "image", "license_class": "open", "needs": ["flux-common"], "auto": True, "priority": 11},
                   "flux-dev": {"display": "image", "license_class": "noncommercial", "needs": ["flux-common"], "auto": True},
                   "weird": {"license_class": "nonsense", "auto": True}},
               "items": [item("flux-common", "t5", "o/enc", "t5.bin", COMMON["t5.bin"], C + "text_encoders\\t5.bin"),
                         item("flux-common", "clip", "o/enc", "clipl.bin", COMMON["clipl.bin"], C + "text_encoders\\clipl.bin"),
                         item("flux-schnell", "s", "o/schnell", "s.bin", SCHNELL, C + "diffusion_models\\s.bin"),
                         item("flux-dev", "d", "o/dev", "d.bin", DEV, C + "diffusion_models\\flux1-dev-fp8-e4m3fn.safetensors",
                              aliases=["FLUX.1 [dev] FP8.safetensors"]),
                         {"id": "weird:x", "package": "weird", "kind": "file", "urls": ["{HF}/o/enc/resolve/%s/t5.bin" % ("a" * 40)],
                          "dest": C + "x\\w.bin", "size": 5000, "sha256": hashlib.sha256(COMMON["t5.bin"]).hexdigest()},
                         {"id": "nodes:code", "package": "nodes-x", "kind": "git", "url": "https://github.com/o/ComfyUI_X", "ref": "b" * 40,
                          "dest": "{COMFYUI}\\custom_nodes\\ComfyUI_X", "size": 1000, "optional": True,
                          "aliases": ["comfyui_x_by_hand"]}]}
        with open(os.path.join(dm.MANIFEST_DIR, "image.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        self.groups = dm.load_manifests(dm.MANIFEST_DIR)
        self.ctx = dm.Context(interactive=False)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = dm.main(list(argv) + ["--manifests", dm.MANIFEST_DIR])
        return code, out.getvalue()

    def models(self, *parts):
        return os.path.join(self.comfy, "models", *parts)

    def test_only_a_package_downloads_it_and_what_it_needs_then_skips_on_rerun(self):
        code, _out = self.run_main("--only", "flux-schnell", "--yes")
        self.assertEqual(code, 0)
        for rel, data in (("text_encoders/t5.bin", COMMON["t5.bin"]), ("text_encoders/clipl.bin", COMMON["clipl.bin"]),
                          ("diffusion_models/s.bin", SCHNELL)):
            with open(self.models(*rel.split("/")), "rb") as fh:
                self.assertEqual(fh.read(), data, rel)
        self.assertFalse(os.path.exists(self.models("diffusion_models", "flux1-dev-fp8-e4m3fn.safetensors")))
        hits = dict(Net.hits)
        code, out = self.run_main("--only", "flux-schnell", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(Net.hits, hits, "a second run downloads nothing")

    def test_alias_in_another_folder_counts_as_installed(self):
        before = dm.package_status(self.groups, self.ctx)
        self.assertFalse(before["flux-dev"]["installed"])
        with open(self.models("checkpoints", "FLUX.1 [dev] FP8.safetensors"), "wb") as fh:
            fh.write(b"already on this computer")
        self.ctx = dm.Context(interactive=False)
        after = dm.package_status(self.groups, self.ctx)
        self.assertTrue(after["flux-dev"]["installed"])
        self.assertEqual(after["flux-dev"]["have_in_comfyui"], 1)
        self.assertFalse(after["flux-schnell"]["installed"])
        code, out = self.run_main("--only", "flux-dev", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(Net.hits.get("/hf/o/dev/resolve/%s/d.bin" % ("a" * 40), 0), 0, "nothing was fetched for the alias")

    def test_git_item_installed_by_hand_under_another_name_is_not_touched(self):
        st = dm.package_status(self.groups, self.ctx)
        self.assertFalse(st["nodes-x"]["installed"])
        by_hand = os.path.join(self.comfy, "custom_nodes", "ComfyUI_X_By_Hand")
        os.makedirs(by_hand)
        with open(os.path.join(by_hand, "__init__.py"), "w") as fh:
            fh.write("# mine\n")
        st = dm.package_status(self.groups, dm.Context(interactive=False))
        self.assertTrue(st["nodes-x"]["installed"])
        res = dm.do_git(next(it for g in self.groups for it in g["items"] if it["kind"] == "git"), self.ctx, dm.State())
        self.assertEqual(res, "skipped")
        self.assertFalse(os.path.exists(os.path.join(self.comfy, "custom_nodes", "ComfyUI_X")))

    def test_all_takes_open_optional_packages_but_never_noncommercial_ones(self):
        every = {it.get("package") for _g, it in dm.plan(self.groups, [], [], everything=True)}
        self.assertTrue({"flux-common", "flux-schnell"} <= every)
        self.assertNotIn("flux-dev", every)
        named = {it.get("package") for _g, it in dm.plan(self.groups, ["flux-dev"], [], everything=True)}
        self.assertIn("flux-dev", named)                                   # asked for by name it comes

    def test_an_unknown_licence_class_is_the_cautious_one(self):
        info = dm.package_info(self.groups)
        self.assertEqual(info["weird"]["license_class"], "noncommercial")
        self.assertFalse(info["weird"]["auto"])
        self.assertEqual(info["flux-dev"]["license_class"], "noncommercial")
        self.assertFalse(info["flux-dev"]["auto"], "auto in the manifest is ignored for a non-open licence")
        self.assertTrue(info["flux-schnell"]["auto"])

    def test_status_reports_disk_and_the_flags_the_auto_mode_needs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dm.main(["--status", "--manifests", dm.MANIFEST_DIR]), 0)
        data = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertIsInstance(data["disk"]["data_free"], int)
        self.assertIsInstance(data["disk"]["comfy_free"], int)
        row = data["packages"]["flux-schnell"]
        self.assertEqual((row["license_class"], row["auto"], row["needs"], row["priority"]), ("open", True, ["flux-common"], 11))
        self.assertEqual(data["packages"]["flux-dev"]["license_class"], "noncommercial")
        self.assertGreater(row["bytes_missing"], 0)

    def test_the_downloader_disk_check_still_stops_a_download_that_does_not_fit(self):
        with mock.patch.object(dm.shutil, "disk_usage", lambda p: mock.Mock(free=1000)), mock.patch.object(dm, "SAFETY_MARGIN", 10 ** 6):
            code, out = self.run_main("--only", "flux-schnell", "--yes")
        self.assertEqual(code, 3)
        self.assertIn("NOT ENOUGH DISK SPACE", out)
        self.assertFalse(os.path.exists(self.models("diffusion_models", "s.bin")))


# ───────────────────────────────────────────── the automatic mode

def row(installed=False, missing=0, license_class="open", needs=(), optional=True):
    return {"installed": installed, "bytes_missing": 0 if installed else missing, "bytes_total": missing, "license_class": license_class,
            "needs": list(needs), "optional": optional, "auto": True}


CFG = {"enabled": True, "packages": ["flux-schnell", "esrgan", "depth", "rife"], "reserve_gb": 25, "big_mb": 1536}
ROWS = {"flux-common": row(missing=5 * GB), "flux-schnell": row(missing=11 * GB, needs=["flux-common"]),
        "esrgan": row(missing=64 * 2 ** 20), "depth": row(missing=190 * 2 ** 20), "rife": row(missing=110 * 2 ** 20)}


class PlanTests(unittest.TestCase):
    def test_small_start_at_once_big_wait_for_the_night(self):
        res = ma.plan(ROWS, CFG, 93 * GB)
        self.assertEqual(res["small"], ["esrgan", "depth", "rife"])
        self.assertEqual(res["big"], ["flux-schnell"])
        self.assertEqual(set(res["states"].values()), {"pending"})

    def test_nothing_without_the_switch_or_without_knowing_the_disk(self):
        self.assertEqual(ma.plan(ROWS, dict(CFG, enabled=False), 93 * GB), {"small": [], "big": [], "states": {}})
        self.assertEqual(ma.plan(ROWS, None, 93 * GB), {"small": [], "big": [], "states": {}})
        res = ma.plan(ROWS, CFG, None)
        self.assertEqual((res["small"], res["big"]), ([], []))
        self.assertEqual(set(res["states"].values()), {"no_disk"})

    def test_the_reserve_and_the_needs_are_part_of_the_budget(self):
        # 40 GB free, 25 GB reserved => 15 GB: FLUX + its 5 GB encoders (16 GB) do not fit, the small ones do
        res = ma.plan(ROWS, CFG, 40 * GB)
        self.assertEqual(res["states"]["flux-schnell"], "no_disk")
        self.assertEqual(res["small"], ["esrgan", "depth", "rife"])
        self.assertEqual(res["big"], [])
        # 42 GB free => 17 GB budget: it fits (16 GB) and leaves ~1 GB: the small ones then do fit too
        res = ma.plan(ROWS, CFG, 42 * GB)
        self.assertEqual(res["big"], ["flux-schnell"])
        self.assertEqual(res["small"], ["esrgan", "depth", "rife"])
        # every package is budgeted in order: the first one takes the room, the next ones are skipped, not half-started
        tight = ma.plan(ROWS, CFG, 25 * GB + 16 * GB + 100 * 2 ** 20)
        self.assertEqual(tight["states"]["flux-schnell"], "pending")
        self.assertEqual(tight["states"]["esrgan"], "pending")
        self.assertEqual(tight["states"]["depth"], "no_disk")

    def test_a_shared_need_is_counted_once(self):
        rows = dict(ROWS, ltx=row(missing=4 * GB, needs=["flux-common"]))
        cfg = dict(CFG, packages=["flux-schnell", "ltx"])
        res = ma.plan(rows, cfg, 25 * GB + 20 * GB)            # 20 GB: FLUX 11 + encoders 5 + LTX 4 (encoders counted once)
        self.assertEqual(res["states"], {"flux-schnell": "pending", "ltx": "pending"})

    def test_installed_unknown_license_and_active_packages_are_left_alone(self):
        rows = dict(ROWS, esrgan=row(installed=True), depth=row(missing=100, license_class="noncommercial"))
        rows["rife"] = row(missing=10, needs=["flux-nc"])
        rows["flux-nc"] = row(missing=10, license_class="restricted")
        cfg = dict(CFG, packages=["esrgan", "depth", "rife", "ghost", "flux-schnell"])
        res = ma.plan(rows, cfg, 200 * GB, active={"flux-schnell"})
        self.assertEqual(res["states"], {"esrgan": "installed", "depth": "blocked_license", "rife": "blocked_license",
                                         "ghost": "unknown_package", "flux-schnell": "active"})
        self.assertEqual((res["small"], res["big"]), ([], []))

    def test_three_failures_rest_for_a_day(self):
        now = 1_000_000.0
        fails = {"esrgan": {"n": 3, "at": now - 3600}}
        self.assertEqual(ma.plan(ROWS, CFG, 93 * GB, fails, now)["states"]["esrgan"], "failed")
        self.assertEqual(ma.plan(ROWS, CFG, 93 * GB, fails, now + 25 * 3600)["states"]["esrgan"], "pending")
        self.assertEqual(ma.plan(ROWS, CFG, 93 * GB, {"esrgan": {"n": 2, "at": now}}, now)["states"]["esrgan"], "pending")

    def test_free_bytes_is_the_smaller_drive(self):
        self.assertEqual(ma.free_bytes_of({"disk": {"data_free": 50 * GB, "comfy_free": 10 * GB}}), 10 * GB)
        self.assertEqual(ma.free_bytes_of({"disk": {"data_free": 50 * GB, "comfy_free": None}}), 50 * GB)
        self.assertIsNone(ma.free_bytes_of({"disk": {}}))
        self.assertIsNone(ma.free_bytes_of(None))

    def test_normalize_cleans_what_the_site_sends(self):
        got = ma.normalize({"enabled": 1, "packages": ["Flux-Schnell", "flux-schnell", "../evil", "ok_pkg", "", 5], "reserve_gb": "7",
                            "big_mb": 99999999})
        self.assertEqual(got, {"enabled": True, "packages": ["flux-schnell", "ok_pkg", "5"], "reserve_gb": 7, "big_mb": 100000})
        self.assertEqual(ma.normalize({"reserve_gb": 1})["reserve_gb"], 5)
        self.assertIsNone(ma.normalize("x"))
        self.assertIsNone(ma.normalize(None))


class FakeManager:
    def __init__(self, rows, disk=None, running=False, progress=None):
        self.rows, self.disk, self._running, self.pr = rows, disk or {"data_free": 93 * GB, "comfy_free": 93 * GB}, running, progress
        self.queue, self.waiting, self.calls = [], set(), []

    def available(self):
        return True

    def refresh(self, force=False):
        return {"packages": self.rows, "disk": self.disk}

    def running(self):
        return self._running

    def downloading(self, p):
        return False

    def waiting_for(self, p):
        return p in self.waiting

    def progress(self):
        return self.pr

    def start(self, packages=None, reason="", window=None):
        self.calls.append((list(packages), window, reason))
        return "started"


class TickTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nm-auto-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        ma._mem.update(cfg=None, loaded=False, last=0.0, born=0.0, force=False, report=None)
        with open(os.path.join(self.dir, ma.CONFIG_FILE), "w", encoding="utf-8") as fh:
            json.dump(CFG, fh)

    def tick(self, mgr, now=10_000.0, night="02:00-07:00"):
        return ma.tick(mgr, night=night, now=now, data_dir=self.dir)

    def test_small_first_then_big_with_the_night_window(self):
        mgr = FakeManager(dict(ROWS))
        self.assertEqual(self.tick(mgr), ["esrgan", "depth", "rife"])
        self.assertEqual(mgr.calls, [(["esrgan", "depth", "rife"], None, "automatic: needed by an enabled feature")])
        # the small ones are installed now: the next look (10 minutes later) starts the big one - parked for the night window
        rows = dict(ROWS, esrgan=row(installed=True), depth=row(installed=True), rife=row(installed=True))
        mgr2 = FakeManager(rows)
        self.assertEqual(self.tick(mgr2, now=10_000.0 + 700), ["flux-schnell"])
        self.assertEqual(mgr2.calls[0][0:2], (["flux-schnell"], "02:00-07:00"))

    def test_rate_limited_and_one_run_at_a_time(self):
        mgr = FakeManager(dict(ROWS))
        self.assertIsNotNone(self.tick(mgr))
        self.assertIsNone(self.tick(mgr, now=10_100.0), "looked a moment ago")
        busy = FakeManager(dict(ROWS), running=True)
        ma._mem.update(last=0.0)
        self.assertIsNone(self.tick(busy, now=20_000.0))
        self.assertEqual(busy.calls, [])

    def test_waiting_packages_are_not_asked_again(self):
        mgr = FakeManager(dict(ROWS))
        mgr.waiting = {"flux-schnell"}
        mgr.rows = dict(ROWS, esrgan=row(installed=True), depth=row(installed=True), rife=row(installed=True))
        self.assertIsNone(self.tick(mgr))
        self.assertEqual(mgr.calls, [])

    def test_disk_that_cannot_hold_it_means_no_start_and_a_reason_for_the_panel(self):
        mgr = FakeManager(dict(ROWS), disk={"data_free": 26 * GB, "comfy_free": 90 * GB})
        self.assertEqual(self.tick(mgr), ["esrgan", "depth", "rife"])      # 26 GB free - 25 GB reserve = 1 GB: only the small ones fit
        states = ma._mem["report"]["states"]
        self.assertEqual(states["flux-schnell"], "no_disk")
        self.assertEqual(ma._mem["report"]["free_mb"], 26 * 1024)
        starved = FakeManager(dict(ROWS), disk={"data_free": 24 * GB, "comfy_free": 90 * GB})
        ma._mem.update(last=0.0)
        self.assertIsNone(self.tick(starved, now=50_000.0))               # below the reserve: nothing at all is started
        self.assertEqual(starved.calls, [])
        self.assertEqual(set(ma._mem["report"]["states"].values()), {"no_disk"})

    def test_failures_are_counted_per_package_from_the_finished_run(self):
        pr = {"state": "failed", "started": 111.0, "packages": ["esrgan", "depth"], "failed": [{"package": "esrgan", "id": "e:1", "reason": "sha256 mismatch"}]}
        for n in range(3):
            pr = dict(pr, started=111.0 + n)
            mgr = FakeManager(dict(ROWS), progress=pr)
            self.tick(mgr, now=10_000.0 + n * 700)
        state = json.load(open(os.path.join(self.dir, ma.STATE_FILE), encoding="utf-8"))
        self.assertEqual(state["fails"]["esrgan"]["n"], 3)
        self.assertNotIn("depth", state["fails"])
        mgr = FakeManager(dict(ROWS), progress=pr)
        self.tick(mgr, now=10_000.0 + 4 * 700)
        self.assertEqual(ma._mem["report"]["states"]["esrgan"], "failed")
        self.assertEqual(ma._mem["report"]["why"]["esrgan"], "sha256 mismatch")
        self.assertNotIn("esrgan", mgr.calls[0][0])

    def test_without_a_config_or_switched_off_nothing_happens(self):
        os.remove(os.path.join(self.dir, ma.CONFIG_FILE))
        mgr = FakeManager(dict(ROWS))
        self.assertIsNone(self.tick(mgr))
        with open(os.path.join(self.dir, ma.CONFIG_FILE), "w", encoding="utf-8") as fh:
            json.dump(dict(CFG, enabled=False), fh)
        self.assertIsNone(self.tick(mgr, now=99_999.0))
        self.assertEqual(mgr.calls, [])

    def test_a_broken_manager_never_raises(self):
        class Boom(FakeManager):
            def refresh(self, force=False):
                raise RuntimeError("status failed")
        logs = []
        self.assertIsNone(ma.tick(Boom({}), night="", now=10_000.0, data_dir=self.dir, log=logs.append))
        self.assertTrue(any("status failed" in x for x in logs))

    def test_absorb_stores_the_sites_block_and_reports_a_change_once(self):
        d = tempfile.mkdtemp(prefix="nm-absorb-")
        self.addCleanup(shutil.rmtree, d, True)
        ans = {"ok": True, "models_auto": {"enabled": True, "packages": ["flux-schnell"], "reserve_gb": 30, "big_mb": 1536}}
        self.assertTrue(ma.absorb(ans, d))
        self.assertFalse(ma.absorb(ans, d), "unchanged: no write, no re-plan")
        saved = ma.load(d)
        self.assertEqual((saved["packages"], saved["reserve_gb"]), (["flux-schnell"], 30))
        self.assertFalse(ma.absorb({"ok": True}, d), "an older site sends no block: the saved copy stays")
        self.assertFalse(ma.absorb(None, d))
        self.assertEqual(ma.load(d)["packages"], ["flux-schnell"])

    def test_report_marks_what_the_manager_is_doing(self):
        ma._mem.update(cfg=dict(CFG), loaded=True, report={"enabled": True, "reserve_gb": 25, "states": {"esrgan": "pending"}})
        mgr = FakeManager({})
        mgr.waiting = {"flux-schnell"}
        mgr.queue = ["depth"]
        rep = ma.report(mgr)
        self.assertEqual(rep["states"]["flux-schnell"], "waiting_window")
        self.assertEqual(rep["states"]["depth"], "queued")
        self.assertEqual(rep["states"]["esrgan"], "pending")
        self.assertEqual(rep["wanted"], 4)


if __name__ == "__main__":
    unittest.main()
