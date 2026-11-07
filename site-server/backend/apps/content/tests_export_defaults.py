"""A final render with NO export settings used to crash («'NoneType' object has no attribute 'codec'» in `encode_args`) as soon as the timeline was heavy enough to be
rendered in slices (found while preparing the Chagher reels, which were then rendered at draft quality). Now missing settings fall back to sensible defaults:
the project's own size and fps, H.264 + AAC in an MP4, and the platform's export preset when the Director knows the platform."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import export
from services.editing import timeline as tl
from services.editing.director import drafts as drafts_mod
from services.video.ffmpeg import FFMPEG, probe

from .models import UploadedVideo, VideoProject
from .tests_editor_modes import make_video
from .tests_render_memory import many_clip_timeline

TEMP = tempfile.mkdtemp(prefix="nm-export-defaults-")
HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


def streams(path):
    return {s["codec_type"]: s for s in probe(path)["streams"]}


def fps_of(path):
    num, _, den = streams(path)["video"]["r_frame_rate"].partition("/")
    return float(num) / float(den or 1)


class DefaultsUnitTests(SimpleTestCase):
    def timeline(self):
        data = {"format": {"width": 480, "height": 854, "fps": 25, "preset": "reel"}, "tracks": [{"id": "t", "kind": "video", "name": "v", "clips": []}], "global_ops": []}
        t = tl.from_project({**data, "tracks": [{"id": "t", "kind": "video", "name": "v", "clips": [{"id": "c", "type": "media", "ref": "x", "label": "x", "kind": "image", "at": 0, "start": 0, "end": 2,
                                                                                                 "src": 0, "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover",
                                                                                                 "fade_in": 0, "fade_out": 0, "audio_on": False, "has_audio": False, "effects": [], "transition": None}]}]},
                           lambda ref: {"path": "/x.png", "kind": "image", "has_audio": False, "duration": 0.0, "width": 480, "height": 854})
        return t

    def test_default_spec_is_the_projects_own_size_and_fps_h264_and_aac(self):
        spec = export.default_spec(self.timeline())
        self.assertEqual((spec.codec, spec.short_side, spec.fps), ("h264", None, None))
        self.assertEqual(spec.audio_kbps, 160)
        self.assertEqual(spec.crf, export.QUALITY["high"][0])

    def test_a_known_platform_adds_its_preset(self):
        spec = export.default_spec(self.timeline(), "whatsapp")
        self.assertEqual(spec.short_side, 540)
        self.assertEqual(spec.max_kbps, 1800)
        self.assertEqual(export.default_spec(self.timeline(), "no-such-platform").short_side, None, "an unknown hint changes nothing")

    def test_platform_hint_comes_from_the_directors_brief(self):
        for platform, preset in (("reels", "reels"), ("story", "reels"), ("shorts", "reels"), ("tiktok", "tiktok"), ("feed", "feed"), ("square", "feed"), ("youtube", "youtube")):
            self.assertEqual(export.preset_hint({"director": {"brief": {"platform": platform}}}), preset, platform)
        self.assertEqual(export.preset_hint({}), "")
        self.assertEqual(export.preset_hint({"director": None}), "")
        self.assertEqual(export.preset_hint({"director": {"brief": {"platform": "mars"}}}), "")
        self.assertEqual(export.preset_hint(None), "")

    def test_default_export_completes_without_overriding_the_shop(self):
        self.assertEqual(export.default_export(None, "reels"), {"preset": "reels"})
        self.assertEqual(export.default_export({}, ""), {})
        self.assertEqual(export.default_export({"preset": "telegram", "fps": 24}, "reels"), {"preset": "telegram", "fps": 24}, "the shop's own preset wins")
        self.assertEqual(export.default_export({"fps": 24}, "reels"), {"fps": 24, "preset": "reels"}, "partly set: the preset is added, fps stays")
        self.assertEqual(export.default_export("junk", "feed"), {"preset": "feed"})


@override_settings(MEDIA_ROOT=TEMP)
class FinalRenderWithoutSettingsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "d.mp4", size="320x180", seconds=3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")

    def check_mp4(self, path, *, fps=12, short=None):
        s = streams(path)
        self.assertEqual(s["video"]["codec_name"], "h264")
        self.assertEqual(s["audio"]["codec_name"], "aac")
        self.assertAlmostEqual(fps_of(path), fps, delta=0.6)
        if short:
            self.assertEqual(min(s["video"]["width"], s["video"]["height"]), short)
        else:
            self.assertEqual((s["video"]["width"], s["video"]["height"]), (320, 240), "the project's own size (the editor never goes below 240 px)")

    def test_no_settings_in_slices_this_was_the_crash(self):
        t = many_clip_timeline(self.src, n=8)
        out = export.render(t, Path(TEMP) / "a.mp4", quality="final", slice_budget=1)
        self.check_mp4(out)

    def test_no_settings_in_one_go(self):
        t = many_clip_timeline(self.src, n=4)
        out = export.render(t, Path(TEMP) / "b.mp4", quality="final", slice_budget=0)
        self.check_mp4(out)

    def test_empty_settings_dict_is_the_same_as_none(self):
        t = many_clip_timeline(self.src, n=8)
        self.check_mp4(export.render(t, Path(TEMP) / "c.mp4", quality="final", export={}, slice_budget=1))

    def test_partly_set_fps_only(self):
        t = many_clip_timeline(self.src, n=8)
        for budget, name in ((1, "e1"), (0, "e2")):
            out = export.render(t, Path(TEMP) / f"{name}.mp4", quality="final", export={"fps": 24}, slice_budget=budget)
            self.check_mp4(out, fps=24)

    def test_partly_set_quality_only_and_where_only(self):
        t = many_clip_timeline(self.src, n=8)
        self.check_mp4(export.render(t, Path(TEMP) / "f1.mp4", quality="final", export={"quality": "small"}, slice_budget=1))
        self.check_mp4(export.render(t, Path(TEMP) / "f2.mp4", quality="final", export={"where": "server"}, slice_budget=1))

    def test_partly_set_preset_only(self):
        t = many_clip_timeline(self.src, n=8)
        out = export.render(t, Path(TEMP) / "g.mp4", quality="final", export={"preset": "whatsapp"}, slice_budget=1)
        self.check_mp4(out, fps=30, short=540)       # the preset says 30 fps

    def test_draft_still_works_without_settings(self):
        t = many_clip_timeline(self.src, n=8)
        out = export.render(t, Path(TEMP) / "h.mp4", quality="draft", slice_budget=1)
        self.assertEqual(streams(out)["video"]["codec_name"], "h264")


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


@override_settings(MEDIA_ROOT=TEMP)
class DirectorDraftFinalRenderTests(TestCase):
    """The Director's draft → «open in manual» → «خروجیِ نهایی» with nothing set in the Export tab."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "uploads/videos/dd.mp4", size="240x426", seconds=4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("dd-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه پیش‌نویس")
        self.client.force_login(self.owner)
        self.up = UploadedVideo.objects.create(store=self.store, title="منبع", video="uploads/videos/dd.mp4", state="READY", duration=4.0, has_audio=True)

    def data(self, platform="whatsapp", n=6):
        ref = f"video:{self.up.pk}"
        clips = [{"id": f"c{i}", "type": "media", "ref": ref, "label": "x", "kind": "video", "at": round(i * 0.6, 3), "start": (i % 3) * 0.5, "end": (i % 3) * 0.5 + 0.6, "src": 4,
                  "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True,
                  "effects": [], "transition": None} for i in range(n)]
        d = {"format": {"width": 240, "height": 426, "fps": 12, "preset": "reel"}, "tracks": [{"id": "t1", "kind": "video", "name": "v", "clips": clips},
                                                                                            {"id": "t2", "kind": "audio", "name": "g", "role": "speech", "clips": []}], "global_ops": []}
        if platform:
            d["director"] = {"run": "r", "variant": "a", "brief": {"platform": platform}, "plan": []}
        return d

    def final(self, project, body=None):
        payload = {"quality": "final", **(body or {})}
        with patch("apps.content.views_timeline.dispatch_job", side_effect=run_inline), patch.object(export, "CHUNK_BUDGET", 1):
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/editor/projects/{project.pk}/render/", json.dumps(payload), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        project.refresh_from_db()
        return job

    def test_a_promoted_director_draft_renders_final_with_no_export_settings(self):
        draft = drafts_mod.create(self.store, run="r", job_id=None, key="a", title="پیش‌نویس", data=self.data(), score=70, length=3.6)
        project = drafts_mod.promote(draft)
        self.assertEqual((project.data.get("export") or {}).get("preset"), "whatsapp", "the platform becomes the project's export preset when it is opened")
        job = self.final(project)
        self.assertEqual(job.result["preset"], "whatsapp")
        out = Path(TEMP) / job.result["output"].replace("/media/", "", 1)
        s = streams(out)
        self.assertEqual(min(s["video"]["width"], s["video"]["height"]), 540)
        self.assertEqual(s["audio"]["codec_name"], "aac")
        self.assertEqual(project.state, VideoProject.State.READY)

    def test_even_an_unpromoted_project_without_any_export_block_renders_final(self):
        project = VideoProject.objects.create(store=self.store, title="بی‌تنظیم", data=self.data(platform=""))
        self.assertFalse((project.data or {}).get("export"))
        job = self.final(project)
        out = Path(TEMP) / job.result["output"].replace("/media/", "", 1)
        s = streams(out)
        self.assertEqual((s["video"]["width"], s["video"]["height"]), (240, 426), "the project's own size")
        self.assertEqual(s["video"]["codec_name"], "h264")

    def test_the_platform_is_used_even_when_the_project_was_saved_before_promotion_filled_it(self):
        project = VideoProject.objects.create(store=self.store, title="قدیمی", data=self.data(platform="whatsapp"))
        self.assertFalse((project.data or {}).get("export"))
        job = self.final(project)
        self.assertEqual(job.result["preset"], "whatsapp")

    def test_partly_set_export_block_through_the_api(self):
        project = VideoProject.objects.create(store=self.store, title="نیمه", data=self.data(platform=""))
        job = self.final(project, {"export": {"fps": 24}})
        out = Path(TEMP) / job.result["output"].replace("/media/", "", 1)
        self.assertAlmostEqual(fps_of(out), 24, delta=0.6)

    def test_the_shops_own_preset_beats_the_directors_platform(self):
        data = self.data(platform="whatsapp")
        data["export"] = {"preset": "telegram"}
        project = VideoProject.objects.create(store=self.store, title="انتخابِ مالک", data=data)
        job = self.final(project)
        self.assertEqual(job.result["preset"], "telegram")
