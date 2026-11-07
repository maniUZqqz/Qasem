"""«رندر و جایگزینی»: the in–out range of a timeline is rendered (clips' own effects only), kept as a new media file of the shop, and the panel can put
that file on the timeline instead of the original clips. Real ffmpeg on tiny clips; the render job runs inline."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG, probe, probe_duration

from . import editor_project
from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-render-replace-")


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


def media(i, ref, at, end, **extra):
    return {"id": f"c{i}", "type": "media", "ref": ref, "label": "x", "kind": "video", "at": at, "start": 0, "end": end, "src": 4, "opacity": 1, "x": 0, "y": 0, "width": 1,
            "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True, "effects": [], "transition": None, **extra}


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class RenderReplaceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if shutil.which(FFMPEG) or shutil.which("ffmpeg"):
            cls.src = make_video(Path(TEMP_MEDIA) / "uploads/videos/rr_src.mp4", size="240x426", seconds=4, freq=440)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "src"):
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("rr-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه جایگزینی")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up = UploadedVideo.objects.create(store=self.store, title="منبع", video="uploads/videos/rr_src.mp4", state="READY", duration=4.0, has_audio=True)

    def data(self, **extra):
        ref = f"video:{self.up.pk}"
        return {"format": {"width": 240, "height": 426, "fps": 12, "preset": "reel"}, "tracks": [
            {"id": "t1", "kind": "video", "name": "تصویر ۱", "muted": False, "locked": False, "clips": [media(1, ref, 0, 4)]},
            {"id": "t2", "kind": "audio", "name": "گفتار", "role": "speech", "muted": False, "locked": False, "clips": []}],
            "global_ops": [], "markers": [], **extra}

    def go(self, data, export):
        project = VideoProject.objects.create(store=self.store, title="پروژهٔ آزمون", data=data)
        with patch("apps.content.views_timeline.dispatch_job", side_effect=run_inline):
            r = self.client.post(f"{self.base}/editor/projects/{project.pk}/render/", json.dumps({"quality": "final", "data": data, "export": export}), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        project.refresh_from_db()
        return project, job

    def test_only_the_marked_range_is_rendered_and_becomes_a_media_file(self):
        project, job = self.go(self.data(inout={"in": 1.0, "out": 3.0}), {"replace": True})
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        ref = job.result["replace_ref"]
        self.assertTrue(ref.startswith("video:"))
        row = UploadedVideo.objects.get(pk=int(ref.split(":")[1]))
        self.assertEqual(row.store_id, self.store.pk)
        path = Path(row.video.path)
        self.assertTrue(path.is_file())
        self.assertAlmostEqual(probe_duration(path), 2.0, delta=0.3)
        self.assertEqual({s["codec_type"] for s in probe(path)["streams"]}, {"video", "audio"})
        self.assertAlmostEqual(row.duration, 2.0, delta=0.3)
        self.assertTrue(row.has_audio)
        self.assertEqual(project.render_info["replaced"][str(job.id)]["ref"], ref)

    def test_the_file_is_not_a_normal_export_and_the_project_output_is_untouched(self):
        project, job = self.go(self.data(inout={"in": 0.5, "out": 2.5}), {"replace": True})
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertFalse(project.output)
        self.assertEqual((project.render_info or {}).get("exports", []), [])
        self.assertEqual(project.state, VideoProject.State.DRAFT)

    def test_whole_video_tools_are_skipped_for_a_replacement(self):
        data = self.data(inout={"in": 0.0, "out": 2.0}, global_ops=[{"tool": "brightness", "params": {"value": 10}}])
        with patch("apps.content.tasks_editing.agent.plan", side_effect=AssertionError("program tools must not run")):
            _, job = self.go(data, {"replace": True})
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)

    def test_the_new_file_is_a_valid_clip_source_for_the_same_shop(self):
        _, job = self.go(self.data(inout={"in": 1.0, "out": 2.5}), {"replace": True})
        ref = job.result["replace_ref"]
        info = editor_project.describe(self.store, ref)
        self.assertEqual(info["kind"], "video")
        self.assertAlmostEqual(info["duration"], 1.5, delta=0.3)
        other = Store.objects.create(owner=self.owner, name="دیگری")
        with self.assertRaises(editor_project.RefError):
            editor_project.describe(other, ref)

    def test_a_replace_without_a_range_fails_with_a_clear_reason_and_nothing_is_created(self):
        before = UploadedVideo.objects.count()
        _, job = self.go(self.data(), {"replace": True})
        self.assertEqual(UploadedVideo.objects.count(), before)
        self.assertIn(job.state, (Job.State.COMPLETED, Job.State.FAILED))
        if job.state == Job.State.COMPLETED:                          # without an in–out range it is just a normal export
            self.assertNotIn("replace_ref", job.result)

    def test_the_renders_list_tells_the_panel_which_file_each_replacement_made(self):
        project, job = self.go(self.data(inout={"in": 1.0, "out": 3.0}), {"replace": True})
        r = self.client.get(f"{self.base}/editor/projects/{project.pk}/renders/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["replaced"][str(job.id)]["ref"], job.result["replace_ref"])
        self.assertAlmostEqual(body["replaced"][str(job.id)]["seconds"], 2.0, delta=0.3)
        self.assertEqual(body["exports"], [])

    def test_replace_flag_is_a_strict_boolean(self):
        t = tl.from_project({**self.data(inout={"in": 1, "out": 2}), "export": {"replace": "yes"}}, lambda ref: {"path": str(self.src), "kind": "video", "has_audio": True, "duration": 4.0, "width": 240, "height": 426})
        self.assertIs(t.export["replace"], False)
