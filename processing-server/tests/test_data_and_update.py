"""Agent 2.0: the data folder outside the code (nm_data.py), moving older copies' downloads into it, and the in-place
update from the site (update.py) - with fake folder trees and a local fake site; nothing real is touched.

    python tests\\test_data_and_update.py
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))      # never the real data folder
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
import nm_data  # noqa: E402
import update  # noqa: E402

AGENT_HEAD = '#!/usr/bin/env python3\n"""UpMarket processing node (GPU machine agent)."""\nVERSION = "%s"\n'


def write(path, text="x", mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:       # byte-exact on Windows too
        fh.write(text)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def readf(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def jload(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ═════════════════════════════════════════════ where the data folder is

class DataRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-root-")
        self.code = os.path.join(self.tmp, "Main V5", "processing-server")
        write(os.path.join(self.code, "agent.py"), AGENT_HEAD % "2.0")
        self.env = mock.patch.dict(os.environ, {"NM_DATA": "", "NM_DATA_POINTER": os.path.join(self.tmp, "ptr", "data-root.txt")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_order_env_then_local_file_then_pointer_then_default(self):
        with mock.patch.object(nm_data, "find_old_installs", lambda code=None, data=None, extra=(): []), \
                mock.patch("os.path.expanduser", lambda p: p.replace("~", os.path.join(self.tmp, "home"))):
            self.assertEqual(nm_data.data_root(self.code), os.path.join(self.tmp, "home", "NMarketing-data"))
            nm_data.remember(os.path.join(self.tmp, "remembered"))
            self.assertEqual(nm_data.configured(self.code), (os.path.join(self.tmp, "remembered"), os.environ["NM_DATA_POINTER"]))
            write(os.path.join(self.code, "nm-data.txt"), "# my folder\n..\\..\\mine\n" if nm_data.IS_WIN else "# my folder\n../../mine\n")
            self.assertEqual(nm_data.data_root(self.code), os.path.normpath(os.path.join(self.tmp, "mine")))
            with mock.patch.dict(os.environ, {"NM_DATA": os.path.join(self.tmp, "env")}):
                self.assertEqual(nm_data.data_root(self.code), os.path.join(self.tmp, "env"))

    def test_default_follows_the_drive_of_older_downloads(self):
        old = os.path.join(self.tmp, "old")
        os.makedirs(os.path.join(old, "models"))
        with mock.patch.object(nm_data, "IS_WIN", True), \
                mock.patch("os.path.expanduser", lambda p: "C:\\Users\\QQz" if p == "~" else p), \
                mock.patch.object(nm_data, "_drive", lambda p: "D:" if p.startswith(old) else "C:"):
            self.assertEqual(nm_data.default_root(self.code, [old]), "D:\\NMarketing-data")
            self.assertEqual(nm_data.default_root(self.code, []), os.path.join("C:\\Users\\QQz", "NMarketing-data"))

    def test_agent_and_downloader_use_the_data_folder(self):
        data = os.path.join(self.tmp, "the data")
        out = subprocess.run([sys.executable, "-c", (
            "import json, agent, download_models as dm\n"
            "print(json.dumps([agent.DATA, agent.LOGS, agent.WORK, agent.VOICE_ROOT, agent.audio_venv_python('moss'),\n"
            "  agent.kit_dir('Photo', 'app'), dm.NM_HOME, dm.MANIFEST_DIR, dm.Context(interactive=False).expand('{MODELS}'),\n"
            "  dm.Context(interactive=False).expand('{VENV:moss-tts}')]))")],
            cwd=PROC, capture_output=True, text=True, env=dict(os.environ, NM_DATA=data, PYTHONPATH=PROC, NM_HOME=""))
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout.strip().splitlines()[-1])
        d = os.path.abspath(data)
        self.assertEqual(got[0], d)
        for p in got[1:6] + got[6:7] + got[8:]:
            self.assertTrue(p.startswith(d), p)
        self.assertEqual(got[7], os.path.join(PROC, "downloads"), "the manifests ship with the code")


# ═════════════════════════════════════════════ moving older copies

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-mig-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.desk = os.path.join(self.tmp, "Desktop", "N")
        self.v3 = os.path.join(self.desk, "Main V3", "processing-server")
        self.v4 = os.path.join(self.desk, "Main V4", "processing-server")
        self.new = os.path.join(self.desk, "Main V5", "processing-server")
        self.data = os.path.join(self.tmp, "NMarketing-data")
        t_old, t_new = time.time() - 86400 * 10, time.time() - 86400
        for root, ver, t in ((self.v3, "1.8", t_old), (self.v4, "1.9", t_new)):
            write(os.path.join(root, "agent.py"), AGENT_HEAD % ver)
            write(os.path.join(root, "tools", "PersianAiKit", "Voice", "voice", "gateway.py"), "old gateway")
        # V4: the newest copy, everything the owner downloaded
        v4 = self.v4
        write(os.path.join(v4, "node.json"), json.dumps({"site": "http://s", "token": "TOKEN-V4", "name": "QQZ-PC"}), t_new)
        write(os.path.join(v4, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors"), "big model")
        write(os.path.join(v4, "python312", "python.exe"), "py")
        cfg = "home = %s\ninclude-system-site-packages = false\nversion = 3.12.10\nexecutable = %s\ncommand = %s -m venv %s\n" % (
            os.path.join(v4, "python312"), os.path.join(v4, "python312", "python.exe"),
            os.path.join(v4, "python312", "python.exe"), os.path.join(v4, "venvs", "moss-tts"))
        write(os.path.join(v4, "venvs", "moss-tts", "pyvenv.cfg"), cfg)
        sp = os.path.join(v4, "venvs", "moss-tts", "Lib", "site-packages")
        write(os.path.join(sp, "__editable__.nano.pth"), os.path.join(v4, "vendor", "ACE-Step-1.5", "nano") + "\n")
        write(os.path.join(sp, "torch", "__init__.py"), "# torch")
        write(os.path.join(v4, "venvs", "moss-tts", ".nm-pip-venv-moss-tts.json"), '{"spec": "x"}')
        dest_key = os.path.normcase(os.path.abspath(os.path.join(v4, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors")))
        write(os.path.join(v4, "logs", "download-state.json"), json.dumps({dest_key: {"size": 9, "mtime": 1, "sha256": "ab"},
                                                                          "snapshot:x@y": {"siblings": []}}))
        write(os.path.join(v4, "services.json"), '{"comfyui": {"start": "\\"C:\\\\c\\\\run_nvidia_gpu.bat\\""}}')
        kit = os.path.join(v4, "tools", "PersianAiKit")
        write(os.path.join(kit, "Voice", "app", "PersianAiKit.Voice.Server.exe"), "exe")
        write(os.path.join(kit, "Voice", "models", "piper", "piper.exe"), "piper")
        write(os.path.join(kit, "Voice", "data", "voices", "my-shop-voice.json"), "MY CLONED VOICE")
        write(os.path.join(kit, "Voice", "voice", ".venv", "pyvenv.cfg"), "home = C:\\Python312\n")
        write(os.path.join(kit, "Video", "tools", "ffmpeg", "bin", "ffmpeg.exe"), "ff")
        write(os.path.join(kit, "Voice", "voice", "__pycache__", "g.pyc"), "c")
        # V3: older; has the same models (they stay) and Blender, which V4 never got
        write(os.path.join(self.v3, "node.json"), json.dumps({"site": "http://s", "token": "TOKEN-V3", "name": "QQZ-PC"}), t_old)
        write(os.path.join(self.v3, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors"), "older model")
        write(os.path.join(self.v3, "vendor", "blender", "blender.exe"), "blender")
        for root in (self.v3, self.v4):
            os.utime(root, (t_old, t_old))
        # the new copy: code only
        write(os.path.join(self.new, "agent.py"), AGENT_HEAD % "2.0")
        write(os.path.join(self.new, "tools", "PersianAiKit", "Voice", "voice", "gateway.py"), "NEW gateway")
        write(os.path.join(self.new, "tools", "PersianAiKit", "Voice", "Run-Server.bat"), "@echo off")
        write(os.path.join(self.tmp, "Desktop", "unrelated", "agent.py"), "print('another program')")
        os.makedirs(os.path.join(self.tmp, "Desktop", "unrelated", "models"))
        pats = [os.path.join(self.tmp, "Desktop", "*"), os.path.join(self.tmp, "Desktop", "*", "*"),
                os.path.join(self.tmp, "Desktop", "*", "*", "*")]
        p = mock.patch.object(nm_data, "search_patterns", lambda code=None: pats)
        p.start()
        self.addCleanup(p.stop)
        self.env = mock.patch.dict(os.environ, {"NM_DATA": self.data})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_finds_older_copies_newest_first_and_ignores_other_programs(self):
        found = nm_data.find_old_installs(self.new, self.data)
        self.assertEqual(found, [self.v4, self.v3])

    def test_moves_instead_of_downloading_and_keeps_the_identity(self):
        lines = []
        root, res = nm_data.prepare(self.new, out=lines.append, sizes=False)
        d = self.data
        self.assertEqual(root, d)
        self.assertEqual(jload(os.path.join(d, "node.json"))["token"], "TOKEN-V4", "the node keeps its identity")
        self.assertEqual(readf(os.path.join(d, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors")), "big model")
        self.assertTrue(os.path.isfile(os.path.join(d, "vendor", "blender", "blender.exe")), "what only V3 had comes too")
        self.assertTrue(os.path.isfile(os.path.join(d, "python312", "python.exe")))
        self.assertTrue(os.path.isfile(os.path.join(d, "services.json")))
        kit = os.path.join(d, "tools", "PersianAiKit")
        self.assertTrue(os.path.isfile(os.path.join(kit, "Voice", "app", "PersianAiKit.Voice.Server.exe")))
        self.assertEqual(readf(os.path.join(kit, "Voice", "data", "voices", "my-shop-voice.json")), "MY CLONED VOICE")
        self.assertTrue(os.path.isfile(os.path.join(kit, "Video", "tools", "ffmpeg", "bin", "ffmpeg.exe")))
        self.assertTrue(os.path.isfile(os.path.join(kit, "Voice", "voice", ".venv", "pyvenv.cfg")))
        self.assertEqual(readf(os.path.join(kit, "Voice", "voice", "gateway.py")), "NEW gateway",
                         "the kit's source comes from the new code")
        self.assertFalse(os.path.exists(os.path.join(kit, "Voice", "voice", "__pycache__")))
        # moved, not copied: gone from V4; V4's code and V3's duplicates stay; nothing deleted
        self.assertFalse(os.path.exists(os.path.join(self.v4, "models")))
        self.assertFalse(os.path.exists(os.path.join(self.v4, "venvs")))
        self.assertTrue(os.path.isfile(os.path.join(self.v4, "agent.py")))
        self.assertEqual(readf(os.path.join(self.v4, "tools", "PersianAiKit", "Voice", "voice", "gateway.py")), "old gateway")
        self.assertEqual(readf(os.path.join(self.v3, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors")),
                         "older model")
        self.assertTrue(os.path.isfile(os.path.join(self.v3, "node.json")))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "Desktop", "unrelated", "models")), "another program is never touched")
        # the moved Python environment points at its new place
        cfg = readf(os.path.join(d, "venvs", "moss-tts", "pyvenv.cfg"))
        self.assertIn("home = %s" % os.path.join(d, "python312"), cfg)
        self.assertNotIn(self.v4, cfg)
        pth = readf(os.path.join(d, "venvs", "moss-tts", "Lib", "site-packages", "__editable__.nano.pth"))
        self.assertTrue(pth.startswith(os.path.join(d, "vendor")), pth)
        # sha256 already checked: remembered under the new path
        state = jload(os.path.join(d, "logs", "download-state.json"))
        new_key = os.path.normcase(os.path.abspath(os.path.join(d, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors")))
        self.assertIn(new_key, state)
        self.assertIn("snapshot:x@y", state)
        text = "\n".join(lines)
        self.assertIn("moved  models", text)
        self.assertIn("re-pointed", text)
        self.assertIn("stay in the older copy", text)
        self.assertTrue(all(ord(c) < 128 for c in text.replace(self.tmp, "")), "console text stays ASCII")
        # a second start moves nothing and prints nothing about it
        lines2 = []
        _root, res2 = nm_data.prepare(self.new, out=lines2.append, sizes=False)
        self.assertEqual(res2["moved"], [])
        self.assertFalse([ln for ln in lines2 if "moved" in ln])

    def test_never_copies_across_drives_and_reports_busy_folders(self):
        real = os.rename

        def rename(src, dst):
            if src.endswith("models"):
                e = OSError("The system cannot move the file to a different disk drive")
                e.winerror = 17
                raise e
            if src.endswith("venvs"):
                raise PermissionError(32, "The process cannot access the file because it is being used by another process")
            return real(src, dst)
        lines = []
        with mock.patch.object(nm_data.os, "rename", rename), mock.patch.object(nm_data.shutil, "copytree") as ct, \
                mock.patch.object(nm_data.shutil, "move") as mv:
            _root, res = nm_data.prepare(self.new, out=lines.append, sizes=False)
        ct.assert_not_called()
        mv.assert_not_called()
        self.assertIn(os.path.join(self.v4, "models"), res["other_drive"])
        self.assertIn(os.path.join(self.v4, "venvs"), res["busy"])
        self.assertTrue(os.path.isfile(os.path.join(self.v4, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors")))
        self.assertTrue(os.path.isfile(os.path.join(self.data, "node.json")), "everything else still moves")
        text = "\n".join(lines)
        self.assertIn("OTHER DRIVE", text)
        self.assertIn("IN USE", text)

    @unittest.skipUnless(nm_data.IS_WIN, "Windows locks open files")
    def test_really_open_file_keeps_its_folder_in_place_on_windows(self):
        fh = open(os.path.join(self.v4, "venvs", "moss-tts", "pyvenv.cfg"), encoding="utf-8")
        try:
            _root, res = nm_data.prepare(self.new, out=lambda m: None, sizes=False)
        finally:
            fh.close()
        self.assertIn(os.path.join(self.v4, "venvs"), res["busy"])
        self.assertTrue(os.path.isfile(os.path.join(self.v4, "venvs", "moss-tts", "pyvenv.cfg")))
        self.assertTrue(os.path.isfile(os.path.join(self.data, "models", "moss-tts", "MOSS-TTS-Realtime", "model.safetensors")))
        _root, res = nm_data.prepare(self.new, out=lambda m: None, sizes=False)     # next start, nothing open any more
        self.assertTrue(os.path.isfile(os.path.join(self.data, "venvs", "moss-tts", "pyvenv.cfg")), "moved on the next start")

    def test_legacy_layout_when_the_data_folder_is_the_code_folder(self):
        with mock.patch.dict(os.environ, {"NM_DATA": self.v4}):
            _root, res = nm_data.prepare(self.v4, out=lambda m: None)
        self.assertEqual(res["moved"], [])
        self.assertTrue(os.path.isdir(os.path.join(self.v4, "models")))


# ═════════════════════════════════════════════ update from the site

class Site:
    manifest = None
    zip_bytes = b""
    corrupt = False
    hits = []
    token = "TOK"


class SiteHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        Site.hits.append(self.path)
        if self.headers.get("Authorization") != "Node " + Site.token:
            return self._send(401, b'{"detail": "bad token"}')
        if self.path.startswith("/api/v1/compute/update/package/"):
            body = Site.zip_bytes
            if Site.corrupt:
                body = body[:-10] + b"0123456789"
            return self._send(200, body, "application/zip")
        if self.path.startswith("/api/v1/compute/update/"):
            return self._send(200, json.dumps(Site.manifest).encode())
        return self._send(404, b"{}")

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_package(files, version):
    """What the site serves (apps.compute.updates): processing-server/<path> + a manifest with every sha256."""
    buf = io.BytesIO()
    rows = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in sorted(files.items()):
            data = data.encode() if isinstance(data, str) else data
            z.writestr("processing-server/" + path, data)
            rows.append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    raw = buf.getvalue()
    cid = hashlib.sha256("".join("%s\0%d\0%s\n" % (r["path"], r["size"], r["sha256"]) for r in rows).encode()).hexdigest()
    return raw, {"version": version, "agent": version, "id": cid, "zip_sha256": hashlib.sha256(raw).hexdigest(),
                 "zip_size": len(raw), "url": "/api/v1/compute/update/package/", "files": rows, "built": "now"}


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), SiteHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nm-upd-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.code = os.path.join(self.tmp, "processing-server")
        self.data = os.path.join(self.tmp, "data")
        self.old = {"agent.py": AGENT_HEAD % "1.9", "START.bat": "@echo off\r\nold\r\n", "site.json": '{"site": "http://mine"}',
                    "audio/_common.py": "old = 1\n", "downloads/old.json": "{}"}
        for p, t in self.old.items():
            write(os.path.join(self.code, *p.split("/")), t)
        write(os.path.join(self.data, "node.json"), json.dumps({"site": self.base, "token": Site.token, "name": "n"}))
        write(os.path.join(self.data, "models", "keep.bin"), "MODEL")
        self.env = mock.patch.dict(os.environ, {"NM_DATA": self.data, "NM_SITE": "", "NM_TOKEN": "", "NM_AUTO_UPDATE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        Site.corrupt, Site.hits = False, []
        self.new = {"agent.py": AGENT_HEAD % "2.0", "START.bat": "@echo off\r\nnew\r\n", "site.json": '{"site": "http://site"}',
                    "audio/_common.py": "old = 1\n", "update.py": "VERSION = '1.0'\n", "nm_data.py": "x = 1\n"}
        Site.zip_bytes, Site.manifest = build_package(self.new, "2.0")
        p = mock.patch.object(update.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def read(self, rel):
        return readf(os.path.join(self.code, *rel.split("/")))

    def run_update(self, **kw):
        lines = []
        rc = update.run(out=lines.append, root=self.code, **kw)
        return rc, lines

    def test_plan_skips_identical_files_and_keeps_the_local_site_json(self):
        write_, retire = update.plan(Site.manifest, self.code)
        self.assertEqual(sorted(f["path"] for f in write_), ["START.bat", "agent.py", "nm_data.py", "update.py"])
        self.assertEqual(retire, [])

    def test_update_in_place_with_backup_and_untouched_data(self):
        rc, lines = self.run_update()
        self.assertEqual(rc, 0, lines)
        self.assertEqual(self.read("agent.py"), AGENT_HEAD % "2.0")
        self.assertEqual(self.read("START.bat"), "@echo off\r\nnew\r\n")
        self.assertEqual(self.read("site.json"), '{"site": "http://mine"}', "this computer's site.json wins")
        self.assertEqual(self.read("downloads/old.json"), "{}", "a file that is not ours stays")
        self.assertEqual(readf(os.path.join(self.data, "models", "keep.bin")), "MODEL")
        ver = jload(os.path.join(self.code, ".nm-version.json"))
        self.assertEqual((ver["version"], ver["id"]), ("2.0", Site.manifest["id"]))
        st = jload(os.path.join(self.data, "updates", "state.json"))
        backup = st["pending"]["backup"]
        self.assertTrue(backup.startswith(os.path.join(self.data, "updates")))
        self.assertEqual(readf(os.path.join(backup, "files", "agent.py")), AGENT_HEAD % "1.9")
        self.assertIn("Updated to version 2.0", "\n".join(lines))
        self.assertTrue(any(h.startswith("/api/v1/compute/update/package/?zip=") for h in Site.hits))
        n = len(Site.hits)
        rc, lines = self.run_update(auto=True)
        self.assertEqual(rc, 0)
        self.assertIn("up to date", "\n".join(lines))
        self.assertEqual(len(Site.hits), n + 1, "an up-to-date folder downloads only the manifest")

    def test_bad_checksum_changes_nothing(self):
        Site.corrupt = True
        rc, lines = self.run_update()
        self.assertEqual(rc, 1)
        self.assertIn("checksum mismatch", "\n".join(lines))
        for p, t in self.old.items():
            self.assertEqual(self.read(p), t, p)
        self.assertFalse(os.path.exists(os.path.join(self.code, ".nm-version.json")))
        rc, lines = self.run_update(auto=True)
        self.assertEqual(rc, 0, "START.bat never stops because of an update problem")

    def test_a_file_that_does_not_match_its_manifest_entry_changes_nothing(self):
        bad = dict(Site.manifest)
        bad["files"] = [dict(f, sha256="0" * 64) if f["path"] == "update.py" else f for f in Site.manifest["files"]]
        Site.manifest = bad
        rc, lines = self.run_update()
        self.assertEqual(rc, 1)
        self.assertIn("does not match its checksum", "\n".join(lines))
        self.assertEqual(self.read("agent.py"), AGENT_HEAD % "1.9")
        self.assertFalse(os.path.exists(os.path.join(self.code, "update.py")))

    def test_broken_update_is_rolled_back_after_two_stops(self):
        self.run_update()
        with mock.patch.object(update, "HERE", self.code):
            out = []
            update.agent_exited(out.append)
            self.assertEqual(self.read("agent.py"), AGENT_HEAD % "2.0", "one stop is tried again")
            update.agent_exited(out.append)
        self.assertEqual(self.read("agent.py"), AGENT_HEAD % "1.9", "two stops: the previous code is back")
        self.assertEqual(self.read("START.bat"), "@echo off\r\nold\r\n")
        self.assertFalse(os.path.exists(os.path.join(self.code, "update.py")), "files the update added are taken out")
        self.assertFalse(os.path.exists(os.path.join(self.code, ".nm-version.json")))
        self.assertIn("putting the previous code back", "\n".join(out))
        rc, lines = self.run_update(auto=True)
        self.assertIn("rolled back on this computer before", "\n".join(lines))
        self.assertEqual(self.read("agent.py"), AGENT_HEAD % "1.9", "START.bat does not apply it again by itself")
        rc, lines = self.run_update()
        self.assertEqual(self.read("agent.py"), AGENT_HEAD % "2.0", "Update.bat by hand may try it again")

    def test_confirmed_update_and_restart_flag_are_not_crashes(self):
        self.run_update()
        self.assertTrue(update.confirm())
        update.request_restart()
        out = []
        update.agent_exited(out.append)
        self.assertIn("Restarting the node on the updated code", "\n".join(out))
        update.agent_exited(out.append)
        update.agent_exited(out.append)
        self.assertEqual(self.read("agent.py"), AGENT_HEAD % "2.0")

    def test_files_dropped_from_the_package_are_retired_into_the_backup(self):
        self.run_update()
        newer = dict(self.new)
        newer.pop("nm_data.py")
        newer["agent.py"] = AGENT_HEAD % "2.1"
        Site.zip_bytes, Site.manifest = build_package(newer, "2.1")
        rc, lines = self.run_update()
        self.assertEqual(rc, 0, lines)
        self.assertFalse(os.path.exists(os.path.join(self.code, "nm_data.py")))
        backup = jload(os.path.join(self.data, "updates", "state.json"))["pending"]["backup"]
        self.assertTrue(os.path.isfile(os.path.join(backup, "retired", "nm_data.py")), "moved aside, not deleted")

    def test_not_registered_and_unreachable_site(self):
        os.remove(os.path.join(self.data, "node.json"))
        rc, lines = self.run_update()
        self.assertEqual(rc, 1)
        self.assertIn("not registered", "\n".join(lines))
        write(os.path.join(self.data, "node.json"), json.dumps({"site": "http://127.0.0.1:9", "token": "T"}))
        rc, lines = self.run_update(auto=True)
        self.assertEqual(rc, 0)
        self.assertIn("Update check skipped", "\n".join(lines))
        write(os.path.join(self.data, "node.json"), json.dumps({"site": self.base, "token": "WRONG"}))
        rc, lines = self.run_update()
        self.assertEqual(rc, 1)
        self.assertIn("did not accept this node's token", "\n".join(lines))

    @unittest.skipUnless(nm_data.IS_WIN, "needs cmd.exe")
    def test_start_bat_keeps_working_when_an_update_replaces_it_while_it_runs(self):
        """cmd.exe reads a .bat line by line from a byte offset: replacing it while it runs normally executes garbage.
        START.bat's blocks are read in one go and every jump goes to a label, so it lands in the new file correctly."""
        d = os.path.join(self.tmp, "bat")
        os.makedirs(d)
        shutil.copy(os.path.join(PROC, "START.bat"), os.path.join(d, "START.bat"))
        pad_b = "rem " + "b" * 700 + "\r\n"
        b = ("@echo off\r\n" + pad_b + ":prepare\r\n(\r\n  echo B-PREPARE-MUST-NOT-RUN\r\n  exit /b 9\r\n)\r\n:loop\r\n(\r\n"
             '  python "%~dp0agent.py"\r\n  python "%~dp0update.py" --agent-exited\r\n  goto loop\r\n)\r\n')
        c = "@echo off\r\n" + "rem c\r\n" * 3 + ":loop\r\n(\r\n  echo C-LOOP-REACHED\r\n  exit /b 0\r\n)\r\n"
        write(os.path.join(d, "b.txt"), b)
        write(os.path.join(d, "c.txt"), c)
        write(os.path.join(d, "update.py"), (
            "import os, shutil, sys\nh = os.path.dirname(os.path.abspath(__file__))\n"
            "if '--auto' in sys.argv:\n    shutil.copy(os.path.join(h, 'b.txt'), os.path.join(h, 'START.bat'))\n"
            "    print('UPDATED-START-BAT')\n"))
        write(os.path.join(d, "agent.py"), (
            "import os, shutil, sys\nh = os.path.dirname(os.path.abspath(__file__))\n"
            "if '--prepare' in sys.argv:\n    print('PREPARED'); sys.exit(0)\n"
            "open(os.path.join(h, 'runs.txt'), 'a').write('run\\n')\n"
            "shutil.copy(os.path.join(h, 'c.txt'), os.path.join(h, 'START.bat'))\nprint('AGENT-RAN'); sys.exit(75)\n"))
        out = subprocess.run(["cmd.exe", "/c", os.path.join(d, "START.bat")], cwd=d, capture_output=True, text=True,
                             timeout=120, stdin=subprocess.DEVNULL, env=dict(os.environ, NM_AUTO_UPDATE="", NM_COMFY_BAT=""))
        text = out.stdout + out.stderr
        for want in ("PREPARED", "UPDATED-START-BAT", "AGENT-RAN", "C-LOOP-REACHED"):
            self.assertIn(want, text, text)
        self.assertNotIn("B-PREPARE-MUST-NOT-RUN", text)
        self.assertNotIn("is not recognized", text, text)
        self.assertEqual(readf(os.path.join(d, "runs.txt")).count("run"), 1)
        self.assertEqual(out.returncode, 0, text)

    def test_unsafe_paths_in_a_manifest_are_refused(self):
        for bad in ("../evil.py", "C:/x.py", "/etc/x", "a//b"):
            with self.assertRaises(update.UpdateError):
                update.safe_join(self.code, bad)


if __name__ == "__main__":
    unittest.main()
