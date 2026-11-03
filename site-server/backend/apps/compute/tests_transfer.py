"""Large-file transfer for node jobs (transfer.py): ranged downloads of a job's registered files, resumable chunked upload of the
result - offsets, checksums, who may touch what."""
import hashlib
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import services as SV
from . import transfer
from .models import ComputeJob, ComputeNode

TMP = tempfile.mkdtemp(prefix="nm-transfer-test-")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class TransferTests(TestCase):
    def setUp(self):
        self.node = ComputeNode.objects.create(name="gpu-t", token="t-tok", capabilities={"ffmpeg": True, "edit": {"render": True}}, last_seen=timezone.now())
        self.other = ComputeNode.objects.create(name="gpu-o", token="o-tok", capabilities={"ffmpeg": True}, last_seen=timezone.now())
        self.job = SV.enqueue("edit.render", {"graph": "x"}, dedupe=False)
        self.assertEqual(self.job.required_capability, "ffmpeg", "the edit.* kinds are routed by the ffmpeg capability")
        self.src = Path(TMP) / "big.bin"
        self.data = bytes(range(256)) * 4096          # 1 MiB
        self.src.write_bytes(self.data)
        transfer.register_assets(self.job, {"f0": {"path": str(self.src), "size": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest(), "name": "big.bin"}})
        claimed = SV.claim(self.node)
        self.assertEqual(claimed.pk, self.job.pk)
        self.c = APIClient()
        self.base = f"/api/v1/compute/jobs/{self.job.uid}"

    def get(self, path, token="t-tok", **extra):
        return self.c.get(self.base + path, HTTP_AUTHORIZATION=f"Node {token}", **extra)

    def put(self, path, body, token="t-tok"):
        return self.c.generic("PUT", self.base + path, body, content_type="application/octet-stream", HTTP_AUTHORIZATION=f"Node {token}")

    def body(self, r):
        return b"".join(r.streaming_content)

    # ------------------------------------------------------------ download
    def test_whole_file_and_ranges_come_back_exactly(self):
        r = self.get("/files/f0/")
        self.assertEqual((r.status_code, r["Accept-Ranges"], r["X-NM-SHA256"]), (200, "bytes", hashlib.sha256(self.data).hexdigest()))
        self.assertEqual(self.body(r), self.data)
        r = self.get("/files/f0/", HTTP_RANGE="bytes=1000-")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r["Content-Range"], f"bytes 1000-{len(self.data) - 1}/{len(self.data)}")
        self.assertEqual(self.body(r), self.data[1000:])
        r = self.get("/files/f0/", HTTP_RANGE="bytes=10-19")
        self.assertEqual((self.body(r), r["Content-Length"]), (self.data[10:20], "10"))
        r = self.get("/files/f0/", HTTP_RANGE="bytes=-5")
        self.assertEqual(self.body(r), self.data[-5:])
        self.assertEqual(self.get("/files/f0/", HTTP_RANGE=f"bytes={len(self.data)}-").status_code, 416)
        self.assertEqual(self.get("/files/f0/", HTTP_RANGE="bytes=oops").status_code, 416)
        self.assertEqual(self.get("/files/nope/").status_code, 404)

    def test_only_the_node_that_holds_the_job_may_read_or_write(self):
        self.assertEqual(self.get("/files/f0/", token="o-tok").status_code, 403)
        self.assertEqual(self.put("/chunks/render.mp4/?offset=0&total=3", b"abc", token="o-tok").status_code, 403)
        self.assertEqual(self.get("/files/f0/", token="wrong").status_code, 401)
        self.assertEqual(self.c.get(self.base + "/files/f0/").status_code, 401, "no token, no file")

    def test_the_server_path_never_reaches_the_node(self):
        payload = SV.package(self.job)
        import zipfile

        with zipfile.ZipFile(payload) as z:
            self.assertNotIn(str(self.src), z.read("payload.json").decode())

    # ------------------------------------------------------------ upload
    def test_a_resumable_upload_in_chunks_with_a_checksum(self):
        total, sha = len(self.data), hashlib.sha256(self.data).hexdigest()
        q = lambda off: f"?offset={off}&total={total}&sha256={sha}"  # noqa: E731
        self.assertEqual(self.get("/chunks/render.mp4/").json(), {"size": 0, "complete": False, "final_size": 0})
        r = self.put("/chunks/render.mp4/" + q(0), self.data[:300_000])
        self.assertEqual((r.status_code, r.json()), (200, {"size": 300_000, "complete": False}))
        self.assertEqual(self.get("/chunks/render.mp4/").json()["size"], 300_000, "a node that lost its connection asks and continues")
        r = self.put("/chunks/render.mp4/" + q(0 + 100), self.data[100:200])
        self.assertEqual((r.status_code, r.json()["size"]), (409, 300_000), "an out-of-order chunk says where the file really is")
        r = self.put("/chunks/render.mp4/" + q(300_000), self.data[300_000:700_000])
        self.assertEqual(r.json()["size"], 700_000)
        r = self.put("/chunks/render.mp4/" + q(700_000), self.data[700_000:])
        self.assertEqual((r.status_code, r.json()), (200, {"size": total, "complete": True}))
        final = SV.output_path(self.job, "render.mp4")
        self.assertEqual(final.read_bytes(), self.data)
        self.assertFalse(final.with_name("render.mp4.part").exists())
        self.assertTrue(self.get("/chunks/render.mp4/").json()["complete"])

    def test_a_wrong_checksum_throws_the_file_away_and_oversize_is_refused(self):
        total = len(self.data)
        r = self.put(f"/chunks/bad.mp4/?offset=0&total={total}&sha256={'0' * 64}", self.data)
        self.assertEqual((r.status_code, r.json()["error"]), (422, "sha256"))
        self.assertFalse(SV.output_path(self.job, "bad.mp4").exists())
        self.assertEqual(self.get("/chunks/bad.mp4/").json()["size"], 0)
        r = self.put("/chunks/big.mp4/?offset=0&total=10", b"x" * 20)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.put("/chunks/x.mp4/?offset=zero&total=1", b"x").status_code, 400)

    def test_a_restart_from_zero_replaces_a_half_file(self):
        total = 6
        self.put(f"/chunks/r.bin/?offset=0&total={total}", b"abc")
        r = self.put(f"/chunks/r.bin/?offset=0&total={total}", b"abcdef")
        self.assertEqual((r.status_code, r.json()["complete"]), (200, True))
        self.assertEqual(SV.output_path(self.job, "r.bin").read_bytes(), b"abcdef")

    def test_the_finished_job_lists_the_uploaded_file_as_its_output(self):
        self.put("/chunks/render.mp4/?offset=0&total=3", b"abc")
        node = ComputeNode.objects.get(pk=self.node.pk)
        job = ComputeJob.objects.get(pk=self.job.pk)
        SV.finish(job, node, True, meta={"bytes": 3})
        job.refresh_from_db()
        self.assertEqual(job.state, "COMPLETED")
        self.assertEqual([o["name"] for o in job.outputs()], ["render.mp4"])
