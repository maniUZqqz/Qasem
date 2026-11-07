"""One-shot outputs of the manual editor's export: only the in–out range, a GIF, one still frame, the sound alone.
Real ffmpeg on tiny clips; the render job runs inline (no broker)."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import export as export_module
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG, probe, probe_duration

from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-export-formats-")


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


def streams(path):
    return {s.get("codec_type"): s for s in probe(path).get("streams", [])}


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ExportFormatTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            return
        root = Path(TEMP_MEDIA)
        cls.src = make_video(root / "uploads/videos/ef_src.mp4", size="240x426", seconds=4, freq=440)
        cls.long = root / "long.mp4"
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5:duration=24", "-pix_fmt", "yuv420p", str(cls.long)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "src"):
            self.skipTest("ffmpeg نیست")
        shutil.rmtree(Path(TEMP_MEDIA) / "generated", ignore_errors=True)
        self.owner = User.objects.create_user("ef-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه خروجی")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up = UploadedVideo.objects.create(store=self.store, title="منبع", video="uploads/videos/ef_src.mp4", state="READY", duration=4.0, has_audio=True)

    def project_data(self, **extra):
        return {"format": {"width": 240, "height": 426, "fps": 12, "preset": "reel"}, "tracks": [
            {"id": "t1", "kind": "video", "name": "تصویر ۱", "muted": False, "locked": False, "clips": [
                {"id": "c1", "type": "media", "ref": f"video:{self.up.pk}", "label": "منبع", "kind": "video", "at": 0, "start": 0, "end": 4, "src": 4, "opacity": 1, "x": 0, "y": 0,
                 "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True, "effects": [], "transition": None}]},
            {"id": "t2", "kind": "audio", "name": "گفتار", "role": "speech", "muted": False, "locked": False, "clips": []}],
            "global_ops": [], "markers": [], "inout": None, **extra}

    def render(self, export=None, data=None, quality="final"):
        project = VideoProject.objects.create(store=self.store, title="p", data=data or self.project_data())
        body = {"quality": quality}
        if export is not None:
            body["export"] = export
        with patch("apps.content.views_timeline.dispatch_job", side_effect=run_inline):
            r = self.client.post(f"{self.base}/editor/projects/{project.pk}/render/", json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        project.refresh_from_db()
        path = Path(TEMP_MEDIA) / job.result["output"].replace("/media/", "", 1)
        return project, job.result, path

    # ------------------------------------------------------------ the server helper on its own
    def test_convert_makes_each_kind_from_a_finished_render(self):
        out = Path(TEMP_MEDIA) / "conv"
        out.mkdir(exist_ok=True)
        cut = out / "cut.mp4"
        r = export_module.convert(self.src, cut, "mp4", t0=1.0, t1=3.0)
        self.assertAlmostEqual(probe_duration(cut), 2.0, delta=0.25)
        self.assertEqual(set(streams(cut)), {"video", "audio"})
        self.assertEqual(r["note"], "")
        audio = out / "a.m4a"
        export_module.convert(self.src, audio, "audio", t0=0, t1=2)
        self.assertEqual(set(streams(audio)), {"audio"})
        self.assertAlmostEqual(probe_duration(audio), 2.0, delta=0.3)
        still = out / "f.jpg"
        export_module.convert(self.src, still, "frame", frame_t=1.5)
        from PIL import Image
        with Image.open(still) as im:
            self.assertEqual((im.format, im.size), ("JPEG", (240, 426)))
        gif = out / "g.gif"
        export_module.convert(self.src, gif, "gif", t0=0, t1=2)
        self.assertEqual(streams(gif)["video"]["codec_name"], "gif")
        self.assertAlmostEqual(probe_duration(gif), 2.0, delta=0.3)
        self.assertEqual(streams(gif)["video"]["height"], export_module.GIF_HEIGHT)

    def test_a_gif_is_capped_and_the_person_is_told(self):
        gif = Path(TEMP_MEDIA) / "conv" / "long.gif"
        gif.parent.mkdir(exist_ok=True)
        r = export_module.convert(self.long, gif, "gif")
        self.assertIn("20", r["note"])
        self.assertIn("GIF", r["note"])
        self.assertAlmostEqual(probe_duration(gif), export_module.GIF_MAX_SECONDS, delta=1.0)
        self.assertAlmostEqual(r["cut"], export_module.GIF_MAX_SECONDS, delta=0.01)

    def test_convert_clamps_silly_times_and_fails_with_a_persian_message_on_garbage(self):
        out = Path(TEMP_MEDIA) / "conv"
        out.mkdir(exist_ok=True)
        far = out / "far.jpg"
        export_module.convert(self.src, far, "frame", frame_t=999)
        self.assertGreater(far.stat().st_size, 100)
        junk = out / "junk.mp4"
        junk.write_bytes(b"not a video")
        from services.video.ffmpeg import VideoProcessingError
        with self.assertRaises(VideoProcessingError):
            export_module.convert(junk, out / "x.gif", "gif")

    def test_the_project_cleaner_keeps_only_known_output_kinds(self):
        data = self.project_data(export={"format": "exe", "range": "weird", "frame_t": "7", "preset": "reels", "evil": 1})
        _m, _d, export, _mk, _io = tl._clean_master(data)
        self.assertNotIn("format", export)
        self.assertNotIn("range", export)
        self.assertNotIn("evil", export)
        self.assertEqual(export["frame_t"], 7.0)
        ok = tl._clean_master(self.project_data(export={"format": "gif", "range": "inout"}))[2]
        self.assertEqual((ok["format"], ok["range"]), ("gif", "inout"))

    # ------------------------------------------------------------ through the real endpoint and job
    def test_a_normal_export_is_unchanged_and_becomes_the_project_output(self):
        project, result, path = self.render(export={})
        self.assertTrue(path.suffix == ".mp4" and path.exists())
        self.assertTrue(project.output)
        self.assertEqual((result["format"], result["range"]), ("mp4", "all"))
        self.assertAlmostEqual(probe_duration(path), 4.0, delta=0.4)

    def test_only_the_in_out_range_is_exported_without_replacing_the_project_output(self):
        data = self.project_data(inout={"in": 1.0, "out": 3.0})
        project, result, path = self.render(export={"range": "inout"}, data=data)
        self.assertEqual((result["format"], result["range"]), ("mp4", "inout"))
        self.assertAlmostEqual(probe_duration(path), 2.0, delta=0.35)
        self.assertFalse(project.output, "a trimmed export is not «the» video of the project")
        self.assertEqual(project.render_info["exports"][0]["range"], "inout")
        self.assertEqual(project.state, VideoProject.State.DRAFT)

    def test_range_without_an_in_out_pair_exports_everything(self):
        _p, result, path = self.render(export={"range": "inout"})
        self.assertAlmostEqual(probe_duration(path), 4.0, delta=0.4)
        self.assertEqual(result["range"], "all")

    def test_a_gif_of_the_range(self):
        project, result, path = self.render(export={"format": "gif", "range": "inout"}, data=self.project_data(inout={"in": 0.5, "out": 2.0}))
        self.assertEqual(path.suffix, ".gif")
        self.assertEqual(streams(path)["video"]["codec_name"], "gif")
        self.assertAlmostEqual(probe_duration(path), 1.5, delta=0.35)
        self.assertEqual(result["format"], "gif")
        self.assertFalse(project.output)

    def test_one_still_frame_at_the_chosen_time(self):
        _p, result, path = self.render(export={"format": "frame", "frame_t": 1.25})
        self.assertEqual(path.suffix, ".jpg")
        from PIL import Image
        with Image.open(path) as im:
            self.assertEqual(im.format, "JPEG")
        self.assertEqual((result["format"], result["seconds"]), ("frame", 0.0))

    def test_sound_only(self):
        _p, result, path = self.render(export={"format": "audio"})
        self.assertEqual(path.suffix, ".m4a")
        self.assertEqual(set(streams(path)), {"audio"})
        self.assertAlmostEqual(probe_duration(path), 4.0, delta=0.4)
        self.assertEqual(result["format"], "audio")

    def test_a_later_normal_export_still_becomes_the_project_output_and_old_outputs_are_listed(self):
        project, _r, _p = self.render(export={"format": "frame", "frame_t": 1})
        self.assertFalse(project.output)
        with patch("apps.content.views_timeline.dispatch_job", side_effect=run_inline):
            r = self.client.post(f"{self.base}/editor/projects/{project.pk}/render/", json.dumps({"quality": "final", "export": {}}), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        project.refresh_from_db()
        self.assertTrue(project.output)
        self.assertEqual([e["format"] for e in project.render_info["exports"]], ["mp4", "frame"])
