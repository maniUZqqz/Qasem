"""Tracking and background removal through a (fake) processing node - and without one: the site's jobs `track_task` / `matte_task`,
their endpoints, the fallback to the site's own OpenCV, the exact «what is needed» message when matting cannot run, the stored matte
and a render that uses it."""
import http.server
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.compute.models import ComputeNode
from apps.jobs.models import Job
from apps.stores.models import Store
from services.video.ffmpeg import FFMPEG, probe

from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video
from .tests_node_render import DATA, HAVE_FFMPEG, HAVE_NODE_CODE, MEDIA, FakeNode

if HAVE_NODE_CODE:
    import agent
    import edit_render


class StubPhotoKit:
    """Just enough of PersianAiKit Photo for the matte job: upload a frame, 'remove the background', give the mask back, delete."""

    def __init__(self, mask_png):
        self.seen = {"docs": 0, "masks": 0}
        outer = self
        png = open(mask_png, "rb").read()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                body = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/health":
                    return self._send(200, {"background": {"ai": {"installed": True, "enabled": True, "canRun": True}}})
                if re.match(r"^/api/docs/d\d+/mask$", self.path):
                    outer.seen["masks"] += 1
                    return self._send(200, png, "image/png")
                self._send(404, {})

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path.startswith("/api/docs?"):
                    outer.seen["docs"] += 1
                    return self._send(200, {"id": "d%d" % outer.seen["docs"]})
                self._send(200, {"seconds": 0.1})

            def do_DELETE(self):
                self._send(200, {"ok": True})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def stop(self):
        self.srv.shutdown()


@override_settings(MEDIA_ROOT=MEDIA, NM_DATA_DIR=Path(DATA))
class NodeToolsTests(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.moving = None
        if not (HAVE_FFMPEG and HAVE_NODE_CODE):
            return
        try:
            import cv2  # noqa: F401
            import numpy as np
        except Exception:  # noqa: BLE001
            return
        root = Path(MEDIA)
        rng = np.random.default_rng(9)
        W, H, N, FPS = 320, 240, 60, 15
        bg = (rng.random((H, W)) * 60 + 40).astype(np.uint8)
        patch = (rng.random((40, 40)) * 200 + 30).astype(np.uint8)
        (root / "uploads/videos").mkdir(parents=True, exist_ok=True)
        cls.moving = root / "uploads/videos/nt_move.mp4"
        proc = subprocess.Popen([FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                                 "-pix_fmt", "yuv420p", str(cls.moving)], stdin=subprocess.PIPE)
        for i in range(N):
            x, y = 40 + i * 3, 100 + int(15 * math.sin(i / 8))
            f = bg.copy()
            f[y:y + 40, x:x + 40] = patch
            proc.stdin.write(f.tobytes())
        proc.stdin.close()
        proc.wait()
        cls.plain = make_video(root / "uploads/videos/nt_plain.mp4", seconds=4, size="320x240")
        cls.red = make_video(root / "uploads/videos/nt_red.mp4", seconds=4, size="320x240", audio=False)
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=25:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.red)],
                       check=True, stdin=subprocess.DEVNULL)

    def setUp(self):
        if self.moving is None:
            self.skipTest("ffmpeg، OpenCV یا کدِ سرورِ پردازش نیست")
        self.owner = User.objects.create_user("nt-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="ابزارها روی گره")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up = UploadedVideo.objects.create(store=self.store, title="متحرک", video="uploads/videos/nt_move.mp4", state="READY", duration=4.0, has_audio=False)
        self.plain_up = UploadedVideo.objects.create(store=self.store, title="ساده", video="uploads/videos/nt_plain.mp4", state="READY", duration=4.0, has_audio=True)
        self.nodes = []
        self.node_tmp = tempfile.mkdtemp(prefix="nm-fake-node-")
        edit_render._CAPS["state"] = None

    def tearDown(self):
        for n in self.nodes:
            n.stop_flag.set()
        for n in self.nodes:
            n.join(10)
        shutil.rmtree(self.node_tmp, ignore_errors=True)
        edit_render._CAPS["state"] = None

    def start_node(self, caps_edit, **kw):
        caps = {"ffmpeg": True, "edit": caps_edit}
        ComputeNode.objects.create(name="gpu-fake", token="fake-tok", last_seen=timezone.now(), capabilities=caps)
        fake = FakeNode(self.live_server_url, "fake-tok", self.node_tmp, caps=caps, **kw)
        fake.start()
        self.nodes.append(fake)
        return fake

    def post(self, path, body):
        return self.client.post(self.base + path, json.dumps(body), content_type="application/json")

    def job_of(self, r):
        self.assertEqual(r.status_code, 202, r.content)
        return Job.objects.get(pk=r.json()["job_id"])

    TRACK = {"s0": 0.0, "s1": 3.0, "region": {"x": 40 / 320, "y": 100 / 240, "w": 40 / 320, "h": 40 / 240}, "fps": 15}

    # ------------------------------------------------------------------ tracking
    def test_tracking_runs_on_the_node_when_it_can_and_follows_the_patch(self):
        self.start_node({"v": 1, "render": True, "track": True})
        job = self.job_of(self.post("/editor/track/", {"ref": f"video:{self.up.pk}", **self.TRACK}))
        self.assertEqual(job.state, "COMPLETED", job.error)
        r = job.result
        self.assertTrue(r["engine"].startswith("node:"), r["engine"])
        self.assertGreaterEqual(len(r["samples"]), 35)
        self.assertEqual(r["samples"][0]["s"], 0.0)
        self.assertGreater(r["samples"][-1]["x"] - r["samples"][0]["x"], 0.3, "the path moved right")

    def test_tracking_falls_back_to_the_site_when_the_node_has_no_opencv(self):
        self.start_node({"v": 1, "render": True, "track": False})
        job = self.job_of(self.post("/editor/track/", {"ref": f"video:{self.up.pk}", **self.TRACK}))
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual(job.result["engine"], "server")
        self.assertGreaterEqual(len(job.result["samples"]), 35)

    def test_tracking_without_any_node_runs_on_the_site(self):
        job = self.job_of(self.post("/editor/track/", {"ref": f"video:{self.up.pk}", **self.TRACK}))
        self.assertEqual((job.state, job.result["engine"]), ("COMPLETED", "server"))

    def test_tracking_refuses_nonsense_with_a_sentence(self):
        self.assertEqual(self.post("/editor/track/", {"ref": f"video:{self.up.pk}", "s0": 2, "s1": 2.1, "region": self.TRACK["region"]}).status_code, 400)
        self.assertEqual(self.post("/editor/track/", {"ref": "video:9999", **self.TRACK}).status_code, 400)
        self.assertEqual(self.post("/editor/track/", {"ref": f"video:{self.up.pk}", "s0": 0, "s1": 3, "region": {"x": "a"}}).status_code, 400)
        other = Store.objects.create(owner=User.objects.create_user("nt-other", password="x"), name="دیگری")
        self.client.force_login(other.owner)
        self.assertIn(self.client.post(f"/api/v1/stores/{self.store.pk}/editor/track/", json.dumps({"ref": f"video:{self.up.pk}", **self.TRACK}),
                                       content_type="application/json").status_code, (403, 404))

    # ------------------------------------------------------------------ matte
    def test_matte_without_a_node_says_exactly_what_is_needed(self):
        st = self.client.get(f"{self.base}/editor/matte/status/").json()
        self.assertFalse(st["ok"])
        for word in ("photo-background", "BiRefNet", "روشن نیست", "دانلود نمی‌شود", "Robust Video Matting"):
            self.assertIn(word, st["message"], word)
        self.assertEqual(self.post("/editor/mattes/", {"ref": f"video:{self.plain_up.pk}", "s0": 0, "s1": 3}).status_code, 503)

    def test_a_node_without_the_model_is_not_offered_the_job(self):
        self.start_node({"v": 1, "render": True, "matte": False})
        st = self.client.get(f"{self.base}/editor/matte/status/").json()
        self.assertFalse(st["ok"])
        self.assertIn("آماده ندارد", st["message"])
        self.assertIn("photo-background", st["message"])

    def test_matte_goes_to_the_node_is_kept_and_cuts_the_picture(self):
        mask = Path(self.node_tmp) / "mask.png"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=0.1", "-vf", "drawbox=x=0:y=0:w=80:h=120:color=white:t=fill,format=gray",
                        "-frames:v", "1", str(mask)], check=True, stdin=subprocess.DEVNULL)
        kit = StubPhotoKit(mask)
        model = Path(self.node_tmp) / "tools" / "PersianAiKit" / "Photo" / "models" / "background"
        model.mkdir(parents=True, exist_ok=True)
        (model / "birefnet-lite.onnx").write_bytes(b"fake")
        try:
            self.start_node({"v": 1, "render": True, "matte": True}, extra_patches=[mock.patch.object(agent, "service_url", lambda key: kit.url)])
            st = self.client.get(f"{self.base}/editor/matte/status/").json()
            self.assertTrue(st["ok"], st)
            job = self.job_of(self.post("/editor/mattes/", {"ref": f"video:{self.plain_up.pk}", "s0": 0.5, "s1": 2.5, "fps": 6}))
            self.assertEqual(job.state, "COMPLETED", job.error)
            key = job.result["key"]
            self.assertEqual((kit.seen["docs"], kit.seen["masks"]), (12, 12), "12 frames: 2 s at 6 per second")
            rows = self.client.get(f"{self.base}/editor/mattes/").json()["mattes"]
            self.assertEqual([r["key"] for r in rows], [key])
            self.assertEqual((rows[0]["ref"], rows[0]["s0"]), (f"video:{self.plain_up.pk}", 0.5))
            up_red = UploadedVideo.objects.create(store=self.store, title="قرمز", video="uploads/videos/nt_red.mp4", state="READY", duration=4.0, has_audio=False)
            data = {"format": {"width": 320, "height": 240, "fps": 25}, "export": {"preset": "draft", "where": "server"}, "tracks": [
                {"kind": "video", "clips": [{"ref": f"video:{up_red.pk}", "at": 0, "start": 0, "end": 2, "fit": "stretch"}]},
                {"kind": "video", "clips": [{"ref": f"video:{self.plain_up.pk}", "at": 0, "start": 0.5, "end": 2.5, "fit": "stretch", "matte": {"key": key}}]}]}
            r = self.client.post(f"{self.base}/editor/projects/", json.dumps({"title": "m", "data": data}), content_type="application/json")
            self.assertEqual(r.status_code, 201, r.content)
            self.assertTrue(r.json()["check"]["ok"], r.json()["check"])
            pid = r.json()["project"]["id"]
            r = self.client.post(f"{self.base}/editor/projects/{pid}/render/", json.dumps({"quality": "final", "data": data}), content_type="application/json")
            rj = Job.objects.get(pk=r.json()["job_id"])
            self.assertEqual(rj.state, "COMPLETED", rj.error)
            out = Path(MEDIA) / VideoProject.objects.get(pk=pid).render_info["rel"]

            size = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
            W, H = int(size["width"]), int(size["height"])      # the draft preset scales the 320x240 project up

            def px(fx):
                return subprocess.run([FFMPEG, "-v", "error", "-ss", "1.0", "-i", str(out), "-vf", f"crop=1:1:{int(W * fx)}:{H // 2},format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"],
                                      capture_output=True, stdin=subprocess.DEVNULL).stdout

            right = px(0.9)
            self.assertTrue(right[0] > 180 and right[1] < 80, f"the right half shows the red clip below: {list(right)}")
            left = px(0.3)
            self.assertFalse(left[0] > 180 and left[1] < 80 and left[2] < 80, f"the left half shows the matted clip, not red: {list(left)}")
            self.assertEqual(self.client.delete(f"{self.base}/editor/mattes/{key}/").status_code, 204)
            check = self.client.get(f"{self.base}/editor/projects/{pid}/").json()["check"]
            self.assertFalse(check["ok"])
            self.assertIn("مات", check["error"])
        finally:
            kit.stop()
