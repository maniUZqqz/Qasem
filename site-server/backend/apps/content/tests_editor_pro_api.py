"""The «pro» workspace API: catalogue, media analysis (waveform / filmstrip / beats / speech), the exact range preview,
export presets + the render queue (snapshot, one at a time, cancel), and auto-captions (node offline message, a fake node).

Real ffmpeg on tiny clips; no Metis, no real node."""
import fcntl
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import captions
from services.video.ffmpeg import FFMPEG, probe

from . import tasks_editing
from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video, sh

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-editor-pro-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ProWorkspaceApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which(FFMPEG) and not shutil.which("ffmpeg"):
            return
        root = Path(TEMP_MEDIA)
        cls.small = make_video(root / "uploads/videos/pro_small.mp4", seconds=4)
        cls.silent = make_video(root / "uploads/videos/pro_silent.mp4", seconds=3, audio=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "small"):
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("pro-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه ادیتور حرفه‌ای")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up = UploadedVideo.objects.create(store=self.store, title="با صدا", video="uploads/videos/pro_small.mp4", state="READY", duration=4.0, has_audio=True)
        self.mute = UploadedVideo.objects.create(store=self.store, title="بی‌صدا", video="uploads/videos/pro_silent.mp4", state="READY", duration=3.0, has_audio=False)

    def call(self, method, url, body=None):
        fn = getattr(self.client, method)
        if body is None:
            return fn(self.base + url)
        return fn(self.base + url, json.dumps(body), content_type="application/json")

    def data(self, **extra):
        return {"format": {"width": 320, "height": 240, "fps": 25}, "tracks": [
            {"kind": "video", "clips": [
                {"ref": f"video:{self.up.pk}", "at": 0, "start": 0, "end": 2, "kf": {"scale": [{"t": 0, "v": 1, "e": "ease_in"}, {"t": 2, "v": 1.2, "e": "linear"}]}},
                {"ref": f"video:{self.mute.pk}", "at": 2, "start": 0, "end": 2, "transition": {"kind": "circleopen", "duration": 0.6}}]},
            {"kind": "text", "clips": [{"text": "قهوهٔ تازه", "at": 0.5, "duration": 1.5, "size": 9, "anim_in": "pop"}]},
        ], **extra}

    def project(self, **extra):
        r = self.call("post", "/editor/projects/", {"title": "پرو", "data": self.data(**extra)})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]["id"]

    # ------------------------------------------------------------ catalogue
    def test_catalogue_lists_everything_the_panel_draws_its_choosers_from(self):
        c = self.call("get", "/editor/catalogue/").json()
        self.assertGreaterEqual(len(c["color"]["looks"]), 12)
        self.assertTrue({"sliders", "wheels", "curves", "hsl", "looks"} <= set(c["color"]))
        self.assertIn("vazir", [f["key"] for f in c["titles"]["fonts"]])
        self.assertGreaterEqual(len(c["transitions"]["kinds"]), 40)
        self.assertIn("circleopen", [k["key"] for k in c["transitions"]["kinds"]])
        self.assertGreaterEqual(len(c["export"]["presets"]), 8)
        self.assertEqual([e["key"] for e in c["easings"]], ["linear", "ease_in", "ease_out", "ease_in_out", "hold"])
        self.assertIn("multiply", [b["key"] for b in c["blends"]])
        self.assertIn("voice", [e["key"] for e in c["eq"]])
        self.assertTrue(c["ramp_presets"])
        self.assertIn("ok", c["captions"])
        other = User.objects.create_user("pro-intruder", password="x")
        self.client.force_login(other)
        self.assertIn(self.call("get", "/editor/catalogue/").status_code, (403, 404))

    # ------------------------------------------------------------ analysis
    def test_waveform_filmstrip_beats_and_speech_are_served_from_a_cache(self):
        ref = f"video:{self.up.pk}"
        wave = self.call("get", f"/editor/analysis/?ref={ref}&kind=waveform").json()
        self.assertTrue(wave["peaks"] and max(wave["peaks"]) > 0.1)
        self.assertAlmostEqual(wave["duration"], 4.0, delta=0.3)
        strip = self.call("get", f"/editor/analysis/?ref={ref}&kind=filmstrip").json()
        self.assertEqual((strip["h"], strip["count"] >= 3), (56, True))
        self.assertTrue(strip["url"].endswith(".jpg"))
        sprite = Path(TEMP_MEDIA) / strip["url"].split("/media/", 1)[1]
        self.assertTrue(sprite.is_file())
        self.assertEqual(sprite.stat().st_mode & 0o044, 0o044, "the sprite must be readable by the web server")
        self.assertIn("spans", self.call("get", f"/editor/analysis/?ref={ref}&kind=speech").json())
        self.assertIn("beats", self.call("get", f"/editor/analysis/?ref={ref}&kind=beats").json())
        mute_ref = f"video:{self.mute.pk}"
        self.assertEqual(self.call("get", f"/editor/analysis/?ref={mute_ref}&kind=waveform").json()["silent"], True)
        self.assertEqual(self.call("get", f"/editor/analysis/?ref={mute_ref}&kind=beats").status_code, 400)
        self.assertEqual(self.call("get", f"/editor/analysis/?ref={ref}&kind=nonsense").status_code, 400)
        self.assertEqual(self.call("get", "/editor/analysis/?ref=video:9999&kind=waveform").status_code, 404)

    # ------------------------------------------------------------ exact preview
    def test_the_exact_range_preview_is_a_short_low_resolution_render_of_the_real_graph(self):
        pid = self.project()
        r = self.call("post", f"/editor/projects/{pid}/preview/", {"t0": 1.0, "t1": 3.0, "height": 240, "data": self.data()})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        res = job.result
        out = Path(TEMP_MEDIA) / res["url"].split("/media/", 1)[1]
        info = probe(out)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((int(v["width"]), int(v["height"])), (320, 240))
        self.assertAlmostEqual(float(info["format"]["duration"]), 2.0, delta=0.3)
        self.assertEqual(res["size"], "320x240")
        self.assertEqual(self.call("post", f"/editor/projects/{pid}/preview/", {"t0": 3, "t1": 3.01}).status_code, 400)
        self.assertEqual(self.call("post", f"/editor/projects/{pid}/preview/", {"t0": "x", "t1": 3}).status_code, 400)
        self.assertFalse(list((Path(TEMP_MEDIA) / "generated/editing").glob("project_*/snap/preview_*.json")), "snapshots are removed")

    # ------------------------------------------------------------ export + queue
    def test_export_with_a_preset_keeps_a_file_per_export_and_lists_the_queue(self):
        pid = self.project(export={"codec": "h265", "height": 240, "fps": 24, "quality": "small", "audio_kbps": 96})
        r = self.call("post", f"/editor/projects/{pid}/render/", {"quality": "final"})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertEqual(job.progress_step, 100)
        project = VideoProject.objects.get(pk=pid)
        self.assertEqual(project.state, "READY", project.error)
        exports = project.render_info["exports"]
        self.assertEqual(len(exports), 1)
        out = Path(TEMP_MEDIA) / exports[0]["rel"]
        v = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
        self.assertEqual((v["codec_name"], v["r_frame_rate"]), ("hevc", "24/1"))
        self.assertEqual(project.output.name, exports[0]["rel"], "the project output points at the export, no second copy")
        self.assertFalse(list(out.parent.parent.glob("program_*.mp4")), "intermediate renders are deleted")
        # a second export (another preset) is kept next to the first
        r = self.call("post", f"/editor/projects/{pid}/render/", {"quality": "final", "export": {"preset": "draft", "codec": "h264", "height": 240}})
        self.assertEqual(Job.objects.get(pk=r.json()["job_id"]).state, "COMPLETED")
        listing = self.call("get", f"/editor/projects/{pid}/renders/").json()
        self.assertEqual(len(listing["exports"]), 2)
        self.assertEqual([j["state"] for j in listing["jobs"]], ["COMPLETED", "COMPLETED"])
        self.assertTrue(all(not j["active"] and j["percent"] == 100 for j in listing["jobs"]))
        self.assertEqual(listing["jobs"][0]["preset"], "draft")

    def test_export_keeps_only_the_newest_files(self):
        pid = self.project()
        for _ in range(tasks_editing.KEEP_EXPORTS + 1):
            self.assertEqual(Job.objects.get(pk=self.call("post", f"/editor/projects/{pid}/render/", {"quality": "draft"}).json()["job_id"]).state, "COMPLETED")
        files = list((Path(TEMP_MEDIA) / f"generated/editing/project_{pid}/exports").glob("*.mp4"))
        self.assertEqual(len(files), tasks_editing.KEEP_EXPORTS)

    def test_editing_goes_on_while_a_render_is_marked_running_and_the_queue_is_bounded(self):
        pid = self.project()
        VideoProject.objects.filter(pk=pid).update(state="RENDERING")
        self.assertEqual(self.call("put", f"/editor/projects/{pid}/", {"title": "تازه"}).status_code, 200, "no longer blocked by a render")
        for _ in range(3):
            Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.QUEUED, context={"what": "project", "project_id": pid})
        r = self.call("post", f"/editor/projects/{pid}/render/", {"quality": "draft"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("لغو", r.json()["error"]["message"])

    def test_a_render_waiting_for_the_slot_can_be_cancelled(self):
        pid = self.project()
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.CANCELLED, context={"what": "project", "project_id": pid})
        lock = open(tasks_editing._editing_root() / tasks_editing.RENDER_LOCK, "a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)       # somebody else is rendering
            result = tasks_editing.render_project_task(job.id, pid, "draft", "")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        self.assertEqual(result, {"cancelled": True})
        self.assertEqual(VideoProject.objects.get(pk=pid).state, "DRAFT", "a cancelled render leaves the project editable")

    def test_a_bad_project_is_refused_before_any_job_is_made(self):
        pid = self.project()
        bad = self.data()
        bad["tracks"][0]["clips"][0]["ref"] = "video:424242"
        r = self.call("post", f"/editor/projects/{pid}/render/", {"quality": "final", "data": bad})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Job.objects.filter(context__what="project").count(), 0)

    # ------------------------------------------------------------ captions
    def test_captions_say_so_plainly_when_no_node_is_online(self):
        with patch("services.editing.captions.status", return_value={"node": False, "local": False, "ok": False, "message": captions.OFFLINE_MESSAGE}):
            r = self.call("post", "/editor/captions/", {"ref": f"video:{self.up.pk}", "start": 0, "end": 3, "at": 0})
        self.assertEqual(r.status_code, 503)
        self.assertIn("سرور پردازش", r.json()["error"]["message"])
        with patch("services.editing.captions.status", return_value={"node": True, "local": False, "ok": True, "message": ""}):
            self.assertEqual(self.call("post", "/editor/captions/", {"ref": f"video:{self.mute.pk}", "start": 0, "end": 2, "at": 0}).status_code, 400, "no sound, no captions")
            self.assertEqual(self.call("post", "/editor/captions/", {"ref": f"video:{self.up.pk}", "start": 2, "end": 2.1, "at": 0}).status_code, 400)
        self.assertEqual(self.call("get", "/editor/captions/status/").status_code, 200)

    def test_captions_from_a_fake_node_become_timed_caption_clips_with_word_timing(self):
        heard = {"words": [{"w": "قهوهٔ", "s": 0.1, "e": 0.6}, {"w": "تازه", "s": 0.7, "e": 1.1}, {"w": "برای", "s": 1.2, "e": 1.6}, {"w": "شما", "s": 1.7, "e": 2.2}],
                 "text": "قهوهٔ تازه برای شما", "engine": "node"}
        with patch("services.editing.captions.status", return_value={"node": True, "local": False, "ok": True, "message": ""}), \
                patch("services.editing.captions.transcribe_wav", return_value=heard) as fake:
            r = self.call("post", "/editor/captions/", {"ref": f"video:{self.up.pk}", "start": 0, "end": 3, "at": 5.0, "speed": 2.0})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        fake.assert_called_once()
        clips = job.result["clips"]
        self.assertTrue(clips and all(c["caption"] for c in clips))
        self.assertGreaterEqual(clips[0]["at"], 5.0, "placed at the clip's timeline position")
        self.assertLessEqual(max(c["at"] + c["duration"] for c in clips), 5.0 + 1.3, "speed 2 halves the times")
        self.assertEqual([w["w"] for c in clips for w in c["words"]], ["قهوهٔ", "تازه", "برای", "شما"])
        self.assertEqual(job.result["engine"], "node")

    def test_a_node_that_fails_or_hears_nothing_gives_a_persian_error_not_a_stuck_job(self):
        with patch("services.editing.captions.status", return_value={"node": True, "local": False, "ok": True, "message": ""}), \
                patch("services.editing.captions.transcribe_wav", return_value={"words": [], "text": "", "engine": "node"}):
            r = self.call("post", "/editor/captions/", {"ref": f"video:{self.up.pk}", "start": 0, "end": 3, "at": 0})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "FAILED")
        self.assertIn("شنیده", job.error)
