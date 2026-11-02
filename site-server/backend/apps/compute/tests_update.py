"""به‌روزرسانیِ کدِ گره از خودِ سایت: ساختِ بسته (بی مدل/venv/node.json)، فهرست و زیپ با توکنِ گره، دسترسی،
«نسخهٔ تازه» در فهرستِ سرورها و کارِ node.update."""
import hashlib
import io
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import services as SV
from . import updates as U
from .models import ComputeJob, ComputeNode

TMP = Path(tempfile.mkdtemp(prefix="nm-update-test-"))
SRC = TMP / "processing"
SHIPPED = {"agent.py": 'VERSION = "2.0"\n# UpMarket processing node\n', "update.py": 'VERSION = "1.0"\n',
           "download_models.py": 'VERSION = "1.2"\n', "nm_data.py": "x = 1\n", "site.json": '{"site": "http://x"}\n',
           "nm_fetch.py": 'VERSION = "1.0"\n', "Update.bat": "@echo off&echo hi\nREM python part\n",
           "START.bat": "@echo off\r\n", "audio/_common.py": "y = 2\n", "downloads/voice.json": "{}\n",
           "tools/PersianAiKit/Voice/voice/gateway.py": "g = 1\n", "tools/PersianAiKit/Voice/Run-Server.bat": "@echo\r\n"}
NEVER = {"node.json": "{}", "services.json": "{}", "logs/agent.log": "l", "venvs/x/pyvenv.cfg": "c", "models/m.bin": "m",
         "vendor/MOSS-TTS/a.py": "v", "agent.py.bak-20261029": "old", "__pycache__/a.cpython-312.pyc": "c",
         "audio/__pycache__/b.pyc": "c", "tools/PersianAiKit/Voice/app/x.exe": "e", "tools/PersianAiKit/Voice/models/m.onnx": "m",
         "tools/PersianAiKit/Voice/data/my-voice.wav": "w", "tools/PersianAiKit/Voice/voice/.venv/pyvenv.cfg": "c",
         "tools/PersianAiKit/Video/tools/ffmpeg/bin/ffmpeg.exe": "f", "python312/python.exe": "p", ".nm-version.json": "{}",
         "pip-cache/x": "x", "work/j/a": "a", "data/worker/x": "x", "downloads-local.json": "{}",
         "START-local.bat": "set NM_COMFY_BAT=C:\\mine\r\n", "Update.bat.part": "x"}


def make_src():
    shutil.rmtree(SRC, ignore_errors=True)
    for rel, text in {**SHIPPED, **NEVER}.items():
        p = SRC / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


@override_settings(NM_DATA_DIR=TMP / "data", NM_PROCESSING_DIR=SRC)
class UpdatePackageTests(TestCase):
    def setUp(self):
        make_src()
        shutil.rmtree(TMP / "data" / "processing-update", ignore_errors=True)
        U._CACHE.update(at=0.0, fp=None, manifest=None)
        self.node = ComputeNode.objects.create(name="gpu-1", capabilities={"agent": "1.9"}, last_seen=timezone.now())
        self.nc = APIClient()
        self.nc.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        self.staff = APIClient()
        self.staff.force_authenticate(get_user_model().objects.create_user("upd", "u@x.io", "pw", is_staff=True))

    def test_package_has_only_code(self):
        m = U.current_manifest()
        self.assertEqual({f["path"] for f in m["files"]}, set(SHIPPED))
        self.assertEqual((m["version"], m["downloader"], m["updater"]), ("2.0", "1.2", "1.0"))
        z = U.build_dir() / m["zip_name"]
        self.assertEqual(hashlib.sha256(z.read_bytes()).hexdigest(), m["zip_sha256"])
        self.assertEqual(z.stat().st_size, m["zip_size"])
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(set(zf.namelist()), {U.PREFIX + p for p in SHIPPED})
            for f in m["files"]:
                self.assertEqual(hashlib.sha256(zf.read(U.PREFIX + f["path"])).hexdigest(), f["sha256"], f["path"])

    def test_rebuilt_only_when_the_code_changes(self):
        m1 = U.current_manifest()
        m2 = U.current_manifest(max_age=0)
        self.assertEqual((m1["id"], m1["zip_name"]), (m2["id"], m2["zip_name"]))
        U._CACHE.update(at=0.0, fp=None, manifest=None)              # another worker process: reads manifest.json
        self.assertEqual(U.current_manifest()["zip_name"], m1["zip_name"])
        time.sleep(0.01)
        (SRC / "agent.py").write_text('VERSION = "2.1"\n# UpMarket processing node\n', encoding="utf-8")
        (SRC / "logs" / "agent.log").write_text("a log line does not make a new package", encoding="utf-8")
        m3 = U.current_manifest(max_age=0)
        self.assertNotEqual(m3["id"], m1["id"])
        self.assertEqual(m3["version"], "2.1")
        self.assertTrue((U.build_dir() / m1["zip_name"]).is_file(), "the previous build stays for a node mid-download")
        self.assertEqual(U.package_path(m1["zip_sha256"]), U.build_dir() / m1["zip_name"])

    def test_node_downloads_manifest_and_zip(self):
        r = self.nc.get("/api/v1/compute/update/")
        self.assertEqual(r.status_code, 200)
        m = r.data
        self.assertNotIn("fingerprint", m)
        r = self.nc.get("/api/v1/compute/update/package/?zip=" + m["zip_sha256"])
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content)
        self.assertEqual(hashlib.sha256(body).hexdigest(), m["zip_sha256"])
        self.assertEqual(int(r["Content-Length"]), m["zip_size"])
        self.assertEqual(self.nc.get("/api/v1/compute/update/package/?zip=" + "0" * 64).status_code, 410)
        r = self.staff.get("/api/v1/compute/update/package/")            # the panel's «دانلودِ بسته»
        self.assertEqual(r.status_code, 200)
        self.assertEqual(zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content))).testzip(), None)

    def test_package_download_resumes_with_range(self):
        m = U.current_manifest()
        url = "/api/v1/compute/update/package/?zip=" + m["zip_sha256"]
        whole = b"".join(self.nc.get(url).streaming_content)
        self.assertEqual(len(whole), m["zip_size"])
        r = self.nc.get(url, HTTP_RANGE="bytes=100-")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r["Content-Range"], "bytes 100-%d/%d" % (len(whole) - 1, len(whole)))
        self.assertEqual(int(r["Content-Length"]), len(whole) - 100)
        self.assertEqual(whole[:100] + b"".join(r.streaming_content), whole, "the two halves make the zip")
        r = self.nc.get(url, HTTP_RANGE="bytes=-50")
        self.assertEqual((r.status_code, b"".join(r.streaming_content)), (206, whole[-50:]))
        r = self.nc.get(url, HTTP_RANGE="bytes=10-19")
        self.assertEqual((r.status_code, b"".join(r.streaming_content)), (206, whole[10:20]))
        r = self.nc.get(url, HTTP_RANGE="bytes=%d-" % len(whole))
        self.assertEqual((r.status_code, r["Content-Range"]), (416, "bytes */%d" % len(whole)))
        r = self.nc.get(url, HTTP_RANGE="nonsense")
        self.assertEqual((r.status_code, len(b"".join(r.streaming_content))), (200, len(whole)))
        self.assertEqual(r["Accept-Ranges"], "bytes")

    def test_bootstrap_is_public_small_and_follows_the_code(self):
        anon = APIClient()
        info = anon.get("/api/v1/compute/update/bootstrap/?info=1")
        self.assertEqual(info.status_code, 200)
        self.assertNotIn("path", info.data)
        self.assertEqual(info.data["files"], list(U.BOOT_FILES))
        r = anon.get("/api/v1/compute/update/bootstrap/")
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content)
        self.assertEqual(hashlib.sha256(body).hexdigest(), info.data["sha256"])
        self.assertEqual(r["X-NM-SHA256"], info.data["sha256"])
        self.assertEqual(len(body), info.data["size"])
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            self.assertEqual(sorted(zf.namelist()), sorted(U.BOOT_FILES))
            self.assertEqual(zf.read("update.py"), SHIPPED["update.py"].encode())
        self.assertEqual(anon.get("/api/v1/compute/update/bootstrap/", HTTP_RANGE="bytes=5-").status_code, 206)
        again = anon.get("/api/v1/compute/update/bootstrap/?info=1").data
        self.assertEqual(again["sha256"], info.data["sha256"], "same files, same bytes (a stable sha256)")
        time.sleep(0.01)
        (SRC / "nm_fetch.py").write_text('VERSION = "1.1"\n', encoding="utf-8")
        self.assertNotEqual(anon.get("/api/v1/compute/update/bootstrap/?info=1").data["sha256"], info.data["sha256"])

    def test_update_bat_is_public_and_has_crlf(self):
        r = APIClient().get("/api/v1/compute/update/Update.bat")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"@echo off&echo hi\r\nREM python part\r\n")
        self.assertIn('filename="Update.bat"', r["Content-Disposition"])

    def test_downloads_list_gives_size_and_sha256_to_nodes_only(self):
        d = U.downloads_dir()
        shutil.rmtree(TMP / "data" / "up3d", ignore_errors=True)
        d.mkdir(parents=True)
        (d / "real.bin").write_bytes(b"0123456789" * 1000)
        try:
            (d / "alias.zip").symlink_to(d / "real.bin")
        except (OSError, NotImplementedError):
            (d / "alias.zip").write_bytes(b"0123456789" * 1000)
        want = hashlib.sha256(b"0123456789" * 1000).hexdigest()
        r = self.nc.get("/api/v1/compute/downloads/?name=alias.zip")
        self.assertEqual((r.status_code, r.data), (200, {"name": "alias.zip", "size": 10000, "sha256": want}))
        self.assertEqual(self.nc.get("/api/v1/compute/downloads/?name=nothing.zip").status_code, 404)
        self.assertEqual(self.nc.get("/api/v1/compute/downloads/?name=..%2F..%2Fetc%2Fpasswd").status_code, 404)
        self.assertEqual({f["name"] for f in self.staff.get("/api/v1/compute/downloads/").data["files"]}, {"real.bin", "alias.zip"})
        (d / "real.bin").write_bytes(b"x" * 20)
        U.download_info("real.bin")
        self.assertEqual(U.download_info("real.bin")["size"], 20, "a changed file is hashed again")
        self.assertIn(APIClient().get("/api/v1/compute/downloads/?name=real.bin").status_code, (401, 403))

    def test_access(self):
        anon = APIClient()
        self.assertIn(anon.get("/api/v1/compute/update/").status_code, (401, 403))
        self.assertIn(anon.get("/api/v1/compute/update/package/").status_code, (401, 403))
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION="Node nope")
        self.assertEqual(bad.get("/api/v1/compute/update/").status_code, 401)
        user = APIClient()
        user.force_authenticate(get_user_model().objects.create_user("shop", "s@x.io", "pw"))
        self.assertIn(user.get("/api/v1/compute/update/").status_code, (401, 403))
        self.assertIn(user.post(f"/api/v1/compute/nodes/{self.node.pk}/update/").status_code, (401, 403))
        self.assertEqual(self.staff.get("/api/v1/compute/update/").status_code, 200)

    def test_panel_shows_waiting_update_and_queues_node_update(self):
        rows = {n["name"]: n for n in self.staff.get("/api/v1/compute/nodes/").data}
        self.assertEqual(rows["gpu-1"]["agent_latest"], "2.0")
        self.assertTrue(rows["gpu-1"]["update_waiting"])
        self.assertFalse(rows["gpu-1"]["can_remote_update"])
        self.assertEqual(self.staff.post(f"/api/v1/compute/nodes/{self.node.pk}/update/").status_code, 409,
                         "an agent older than 2.0 cannot update itself")
        m = U.current_manifest()
        self.node.capabilities = {"agent": "2.0", "code": {"version": "2.0", "id": m["id"][:16]}}
        self.node.save()
        rows = {n["name"]: n for n in self.staff.get("/api/v1/compute/nodes/").data}
        self.assertFalse(rows["gpu-1"]["update_waiting"], "same package id: nothing waiting")
        self.node.capabilities = {"agent": "2.0", "code": {"version": "2.0", "id": "0123456789abcdef"}}
        self.node.save()
        self.assertTrue({n["name"]: n for n in self.staff.get("/api/v1/compute/nodes/").data}["gpu-1"]["update_waiting"])
        r = self.staff.post(f"/api/v1/compute/nodes/{self.node.pk}/update/")
        self.assertEqual(r.status_code, 202)
        job = ComputeJob.objects.get(uid=r.data["job"])
        self.assertEqual((job.kind, job.node_wanted), ("node.update", "gpu-1"))
        other = ComputeNode.objects.create(name="gpu-2", capabilities={"agent": "2.0"}, last_seen=timezone.now())
        self.assertIsNone(SV.claim(other), "node.update goes only to the node it names")
        self.assertEqual(SV.claim(self.node).pk, job.pk)
        s = self.staff.get("/api/v1/compute/settings/").data
        self.assertEqual(s["package"]["version"], "2.0")
