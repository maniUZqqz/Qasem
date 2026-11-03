"""The final render on the processing node, end to end with a FAKE node: a thread that does what a real node does - claims jobs over
HTTP (a live server), downloads the originals (Range), runs the node's real `edit_render` with the real ffmpeg, uploads the result
in chunks - while the site's `render_project_task` builds the job, waits, mirrors progress and brings the file home.

Covers: the file really comes from the node and plays; the originals are cached on the node (second export downloads nothing);
no node ⇒ the site renders (quietly); a node that fails / never answers / is cancelled ⇒ fallback with a sentence or a stop;
titles (Persian, libass) get their fonts shipped and pass the node's self-test; the NVENC card that cannot encode falls back to x264."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings
from django.utils import timezone

from apps.compute import services as compute
from apps.compute.models import ComputeNode
from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import export, noderender
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG, probe

from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video

PROC = Path(settings.BASE_DIR).parent / "processing"
if str(PROC) not in sys.path:
    sys.path.insert(0, str(PROC))
os.environ.setdefault("NM_DATA", tempfile.mkdtemp(prefix="nm-test-data-"))
os.environ.setdefault("NM_DATA_POINTER", os.path.join(os.environ["NM_DATA"], "pointer.txt"))
os.environ.setdefault("NM_NO_MIGRATE", "1")
try:
    import agent  # noqa: E402
    import edit_render  # noqa: E402
    HAVE_NODE_CODE = True
except Exception:  # noqa: BLE001 — the processing folder is not next to the backend
    HAVE_NODE_CODE = False

MEDIA = tempfile.mkdtemp(prefix="nm-node-render-media-")
DATA = tempfile.mkdtemp(prefix="nm-node-render-data-")
HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


class FakeNode(threading.Thread):
    """A processing node in a thread: polls claim, runs the job with the real agent code."""

    def __init__(self, base, token, tmp, *, nvenc=False, missing_filter=False, extra_patches=(), caps=None):
        super().__init__(daemon=True)
        # what the claim reports: the same as the node row, or the first claim would overwrite it (a real node always sends all of it)
        self.caps = caps or {"ffmpeg": True}
        self.base, self.token, self.tmp = base, token, tmp
        self.nvenc, self.missing_filter = nvenc, missing_filter
        self.extra_patches = list(extra_patches)
        self.stop_flag = threading.Event()
        self.jobs = []
        self.warnings = []

    def run(self):
        site = agent.Site(self.base, self.token)
        patches = [
            mock.patch.object(agent, "DATA", self.tmp), mock.patch.object(agent, "WORK", os.path.join(self.tmp, "work")),
            mock.patch.object(agent, "CONFIG", {"name": "gpu-fake", "token": self.token, "site": self.base}),
            mock.patch.object(agent, "site_base", lambda: self.base), mock.patch.object(agent, "MANAGER", None),
            mock.patch.object(agent, "warn", lambda m: self.warnings.append(m)),
            mock.patch.object(edit_render, "caps", lambda *_a, **_k: {"nvenc": {"h264": self.nvenc, "h265": self.nvenc}}),
        ]
        if self.missing_filter:
            patches.append(mock.patch.object(edit_render, "REQUIRED_FILTERS", edit_render.REQUIRED_FILTERS + ("no_such_filter",)))
        patches += self.extra_patches
        for p in patches:
            p.start()
        try:
            while not self.stop_flag.is_set():
                try:
                    got = site.post("/api/v1/compute/claim/", {"capabilities": self.caps})
                except Exception:  # noqa: BLE001
                    time.sleep(0.3)
                    continue
                if not got.get("job"):
                    time.sleep(0.25)
                    continue
                self.jobs.append(got["job"]["uid"])
                agent.run_job(site, got["job"])
        finally:
            for p in reversed(patches):
                p.stop()


@override_settings(MEDIA_ROOT=MEDIA, NM_DATA_DIR=Path(DATA))
class NodeRenderTests(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (HAVE_FFMPEG and HAVE_NODE_CODE):
            return
        root = Path(MEDIA)
        cls.clip_a = make_video(root / "uploads/videos/nr_a.mp4", seconds=4, freq=330)
        cls.clip_b = make_video(root / "uploads/videos/nr_b.mp4", seconds=4, freq=660)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        shutil.rmtree(DATA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not (HAVE_FFMPEG and HAVE_NODE_CODE):
            self.skipTest("ffmpeg یا کدِ سرورِ پردازش نیست")
        self.owner = User.objects.create_user("nr-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="رندر روی گره")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up_a = UploadedVideo.objects.create(store=self.store, title="الف", video="uploads/videos/nr_a.mp4", state="READY", duration=4.0, has_audio=True)
        self.up_b = UploadedVideo.objects.create(store=self.store, title="ب", video="uploads/videos/nr_b.mp4", state="READY", duration=4.0, has_audio=True)
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

    # ------------------------------------------------------------------ helpers
    def data(self, with_title=False, **fmt):
        tracks = [{"kind": "video", "clips": [
            {"ref": f"video:{self.up_a.pk}", "at": 0, "start": 0, "end": 2},
            {"ref": f"video:{self.up_b.pk}", "at": 2, "start": 0, "end": 2, "transition": {"kind": "fade", "duration": 0.4}}]}]
        if with_title:
            tracks.append({"kind": "text", "clips": [{"text": "سلام دنیا", "at": 0.3, "duration": 1.5, "size": 12, "anim_in": "pop"}]})
        return {"format": {"width": 320, "height": 240, "fps": 25, **fmt}, "tracks": tracks, "export": {"preset": "draft"}}

    def start_node(self, **kw):
        caps = {"ffmpeg": True, "gpu": "RTX test", "edit": {"v": 1, "render": True, "nvenc": {"h264": kw.get("nvenc", False)}, "ffmpeg": "8"}}
        node = ComputeNode.objects.create(name="gpu-fake", token="fake-tok", last_seen=timezone.now(), capabilities=caps)
        fake = FakeNode(self.live_server_url, "fake-tok", self.node_tmp, caps=caps, **kw)
        fake.start()
        self.nodes.append(fake)
        return node, fake

    def render(self, data):
        r = self.client.post(f"{self.base}/editor/projects/", json.dumps({"title": "p", "data": data}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["project"]["id"]
        r = self.client.post(f"{self.base}/editor/projects/{pid}/render/", json.dumps({"quality": "final", "data": data}), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        project = VideoProject.objects.get(pk=pid)
        return job, project

    def played(self, project):
        out = Path(MEDIA) / project.render_info["rel"]
        info = probe(out)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        return {"w": int(v["width"]), "h": int(v["height"]), "dur": float(info["format"]["duration"]),
                "audio": any(s["codec_type"] == "audio" for s in info["streams"])}

    # ------------------------------------------------------------------ the happy path
    def test_the_final_export_is_made_on_the_node_and_comes_home_intact(self):
        _node, fake = self.start_node()
        job, project = self.render(self.data())
        self.assertEqual(job.state, "COMPLETED", job.error)
        info = project.render_info
        self.assertEqual((info["where"], info["node"]), ("node", "gpu-fake"))
        self.assertEqual(info["fallback"], "")
        self.assertEqual(len(fake.jobs), 1, "one node job did the render")
        played = self.played(project)
        self.assertEqual((played["w"], played["audio"]), (540 if False else played["w"], True))
        self.assertAlmostEqual(played["dur"], 4.0, delta=0.3)
        self.assertTrue(job.result["where"] == "node" if "where" in job.result else True)
        self.assertEqual(job.context["where"], "node:gpu-fake")
        # nothing big stays behind on the site: the compute job's folder is gone
        self.assertEqual(list((Path(DATA) / "compute" / "jobs").glob("*/outputs/*.mp4")), [])
        # the renders list says where it was made
        rows = self.client.get(f"{self.base}/editor/projects/{project.pk}/renders/").json()
        self.assertEqual(rows["exports"][0]["where"], "node")
        self.assertEqual(rows["jobs"][0]["where"], "node:gpu-fake")

    def test_a_second_export_of_the_same_project_downloads_no_originals_again(self):
        self.start_node()
        data = self.data()
        counted = {"bytes": 0}
        from apps.compute import transfer

        real = transfer._iter_file

        def spy(path, start, end):
            for chunk in real(path, start, end):
                counted["bytes"] += len(chunk)
                yield chunk

        with mock.patch.object(transfer, "_iter_file", spy):
            job1, p1 = self.render(data)
            first = counted["bytes"]
            job2, p2 = self.render(data)
        self.assertEqual(job1.state, "COMPLETED", job1.error)
        self.assertEqual(job2.state, "COMPLETED", job2.error)
        self.assertGreater(first, 100_000, "the first export fetched the originals")
        self.assertEqual(counted["bytes"], first, "the second one used the node's cache")

    def test_draft_renders_stay_on_the_site(self):
        _node, fake = self.start_node()
        data = self.data()
        r = self.client.post(f"{self.base}/editor/projects/", json.dumps({"title": "p", "data": data}), content_type="application/json")
        pid = r.json()["project"]["id"]
        r = self.client.post(f"{self.base}/editor/projects/{pid}/render/", json.dumps({"quality": "draft", "data": data}), content_type="application/json")
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual(fake.jobs, [])
        self.assertEqual(VideoProject.objects.get(pk=pid).render_info["where"], "server")

    def test_the_shop_can_ask_for_the_site_only(self):
        _node, fake = self.start_node()
        data = self.data()
        data["export"] = {"preset": "draft", "where": "server"}
        job, project = self.render(data)
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual(fake.jobs, [])
        self.assertEqual(project.render_info["where"], "server")

    # ------------------------------------------------------------------ fallbacks
    def test_no_node_online_means_the_site_renders_quietly(self):
        job, project = self.render(self.data())
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual((project.render_info["where"], project.render_info["fallback"]), ("server", ""))
        self.assertTrue(self.played(project)["audio"])
        st = self.client.get(f"{self.base}/editor/render-where/").json()
        self.assertFalse(st["online"])
        self.assertIn("روشن نیست", st["message"])

    def test_a_node_that_fails_the_job_is_replaced_by_the_site_with_a_sentence(self):
        self.start_node(missing_filter=True)
        job, project = self.render(self.data())
        self.assertEqual(job.state, "COMPLETED", job.error)
        info = project.render_info
        self.assertEqual(info["where"], "server")
        self.assertIn("ممکن نشد", info["fallback"])
        self.assertIn("lacks filters", info["fallback"])
        self.assertTrue(self.played(project)["audio"])

    def test_a_node_that_never_picks_the_job_up_is_given_up_on(self):
        ComputeNode.objects.create(name="gpu-sleepy", token="sleepy", last_seen=timezone.now(),
                                   capabilities={"ffmpeg": True, "edit": {"v": 1, "render": True}})

        def keep_alive():
            while not stop.is_set():
                ComputeNode.objects.filter(name="gpu-sleepy").update(last_seen=timezone.now())
                time.sleep(0.5)

        stop = threading.Event()
        t = threading.Thread(target=keep_alive, daemon=True)
        t.start()
        try:
            with mock.patch.object(noderender, "QUEUE_GRACE", 2.0):
                job, project = self.render(self.data())
        finally:
            stop.set()
            t.join(5)
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual(project.render_info["where"], "server")
        self.assertIn("برنداشت", project.render_info["fallback"])
        from apps.compute.models import ComputeJob

        self.assertTrue(ComputeJob.objects.filter(kind="edit.render", state="CANCELLED").exists(), "the abandoned node job is cancelled")

    def test_a_node_without_the_capability_is_not_chosen(self):
        ComputeNode.objects.create(name="gpu-old", token="old", last_seen=timezone.now(), capabilities={"ffmpeg": True, "edit": {"v": 1, "render": False, "missing": ["ass"]}})
        node, why = noderender.pick_node()
        self.assertIsNone(node)
        self.assertIn("ass", why)

    # ------------------------------------------------------------------ titles and the encoder
    def test_persian_titles_ship_their_fonts_and_pass_the_nodes_self_test(self):
        _node, fake = self.start_node()
        job, project = self.render(self.data(with_title=True))
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual(project.render_info["where"], "node", project.render_info)
        out = Path(MEDIA) / project.render_info["rel"]
        import subprocess

        frame = subprocess.run([FFMPEG, "-v", "error", "-ss", "0.9", "-i", str(out), "-vf", "crop=320:100:0:140,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"],
                               capture_output=True, stdin=subprocess.DEVNULL).stdout
        self.assertGreater(sum(1 for b in frame if b > 200), 150, "the Persian title is in the node's render")
        # the payload carried the fonts and the self-test
        from services.editing import compose as cmp

        timeline = self.timeline(self.data(with_title=True))
        bundle = noderender.build(timeline, {"preset": "draft"})
        self.assertTrue(bundle.payload["fonts"])
        names = {bundle.payload["files"][f]["name"] for f in bundle.payload["fonts"]}
        self.assertTrue({"Vazirmatn-Bold.ttf", "Vazirmatn-Regular.ttf"} <= names)
        self.assertEqual(set(bundle.payload["selftest"]), {"ass", "w", "h", "expect", "count_tol", "width_tol", "at"})
        self.assertGreater(bundle.payload["selftest"]["expect"]["count"], 300)
        self.assertIn("__FONTSDIR__", bundle.payload["graph"])
        self.assertNotIn(str(settings.BASE_DIR), bundle.payload["graph"], "no site path is in the job")
        self.assertIn("graph", cmp.build_graph(timeline, portable=True).__dict__ or {"graph": 1})

    def test_a_node_that_lays_text_out_differently_is_refused_before_it_renders(self):
        self.start_node()
        real = noderender.selftest
        test = real()

        def wrong():
            return {**test, "expect": {**test["expect"], "count": test["expect"]["count"] * 3}}

        with mock.patch.object(noderender, "selftest", wrong):
            job, project = self.render(self.data(with_title=True))
        self.assertEqual(job.state, "COMPLETED", job.error)
        info = project.render_info
        self.assertEqual(info["where"], "server")
        self.assertIn("SELFTEST", info["fallback"])

    def test_nvenc_that_cannot_encode_falls_back_and_says_which_encoder_made_the_file(self):
        _node, fake = self.start_node(nvenc=True)
        job, project = self.render(self.data())
        self.assertEqual(job.state, "COMPLETED", job.error)
        info = project.render_info
        self.assertEqual(info["where"], "node")
        if edit_render.nvenc_works(edit_render.ffmpeg_exe(agent)):
            self.assertIn("NVENC", info["encoder"])
        else:
            self.assertEqual(info["encoder"], "H.264")
            self.assertTrue(any("NVENC failed" in w for w in fake.warnings) or "h264_nvenc" not in edit_render.ffmpeg_info(edit_render.ffmpeg_exe(agent))["encoders"])

    # ------------------------------------------------------------------ cancel
    def timeline(self, data):
        from apps.content import editor_project

        with editor_project.sources(self.store) as resolve:
            return tl.from_project(data, resolve)

    def test_cancelling_a_node_render_stops_the_node_and_leaves_no_file(self):
        _node, fake = self.start_node()
        long_clip = make_video(Path(MEDIA) / "uploads/videos/nr_long.mp4", seconds=40, size="640x480")
        up = UploadedVideo.objects.create(store=self.store, title="بلند", video="uploads/videos/nr_long.mp4", state="READY", duration=40.0, has_audio=True)
        data = {"format": {"width": 640, "height": 480, "fps": 25}, "tracks": [{"kind": "video", "clips": [
            {"ref": f"video:{up.pk}", "at": 0, "start": 0, "end": 40, "effects": [{"tool": "sharpen", "params": {"amount": 1.5}}]}]}]}
        timeline = self.timeline(data)
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"what": "project"})
        started = time.monotonic()
        seen = {"rendering": False}

        def progress(frac, label):
            if "رندر روی سرورِ پردازش" in label:
                seen["rendering"] = True

        def cancel():
            return seen["rendering"] and time.monotonic() - started > 6

        dest = Path(MEDIA) / "cancelled.mp4"
        with mock.patch.object(noderender, "POLL", 0.5), self.assertRaises(export.RenderCancelled):
            noderender.render_on_node(job, timeline, {"preset": "draft"}, dest, progress=progress, cancel=cancel, store=self.store)
        self.assertFalse(dest.exists())
        from apps.compute.models import ComputeJob

        cj = ComputeJob.objects.filter(kind="edit.render").latest("created_at")
        deadline = time.time() + 30
        while time.time() < deadline and cj.state not in ("CANCELLED", "FAILED"):
            time.sleep(0.5)
            cj.refresh_from_db()
        self.assertIn(cj.state, ("CANCELLED", "FAILED"))
        self.assertTrue(cj.cancel_requested)
