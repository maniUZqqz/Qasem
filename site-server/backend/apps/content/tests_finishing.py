"""After the segments: the finishing pass, sound by default, product-only scenes.

The pipeline-level half of services/tests_enhance.py: that the video job
publishes the enhanced file and keeps the raw one, hands over to the voice job
without a click, and renders a coffee scene without the hand its script asked
for.
"""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.jobs.models import Job
from apps.products.models import Product, ProductImage
from apps.stores.models import Store
from services.video.enhance import EnhanceResult

from .models import VideoScene, VideoScript
from .tasks import _start_auto_voice, generate_video_task
from .tests import anchor_via

TEMP_MEDIA = tempfile.mkdtemp(prefix="upmarket-finishing-test-media-")
ON = {**settings.UPMARKET_AI, "VIDEO_ENHANCE": True, "VIDEO_AUTO_VOICE": True}


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class FinishingPipelineTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("bob", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Coffee Shop")
        self.product = Product.objects.create(store=self.store, name="قهوه")
        image_dir = Path(TEMP_MEDIA) / "products" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / "mug.png").write_bytes(b"fakepng")
        image = ProductImage(product=self.product)
        image.image.name = "products/images/mug.png"
        image.save()
        self.script = VideoScript.objects.create(store=self.store, product=self.product, total_duration=10)
        VideoScene.objects.create(
            script=self.script, index=1, duration=5, transition="NEW_SCENE", narration="قهوه ما",
            visual_prompt="A steaming red mug of coffee on a wooden table, warm light",
            motion_prompt="slow push-in towards the coffee cup",
        )
        VideoScene.objects.create(
            script=self.script, index=2, duration=5, transition="CONTINUE", narration="همین حالا",
            visual_prompt="The same coffee cup, now with a hand reaching for it, warm lighting continues",
            motion_prompt="slow push-in on the smiling face",
            state={"characters": ["hand"], "objects": ["coffee cup"]},
        )

    def _run(self):
        out_dir = Path(TEMP_MEDIA) / "generated" / "videos" / f"script_{self.script.id}"
        prompts = []

        def fake_generate(workflow, dest, filename=None, timeout=None):
            prompts.append(workflow["10"]["inputs"]["text"])
            Path(dest).mkdir(parents=True, exist_ok=True)
            path = Path(dest) / filename
            path.write_bytes(b"fakemp4")
            return path

        def fake_extract(video, out):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"png")
            return Path(out)

        def fake_concat(paths, out):
            Path(out).write_bytes(b"raw")
            return Path(out)

        def fake_enhance(source, out, cfg=None):
            Path(out).write_bytes(b"hd")
            return EnhanceResult(ok=True, path=Path(out), applied=["interpolate_mci", "upscale"],
                                 before={"width": 832, "height": 480, "fps": 16.0},
                                 after={"width": 1280, "height": 720, "fps": 32.0})

        patches = [
            patch("apps.content.tasks.ComfyUIClient"),
            patch("apps.content.tasks.extract_last_frame", side_effect=fake_extract),
            patch("apps.content.tasks.concat_videos", side_effect=fake_concat),
            patch("services.video.enhance.enhance", side_effect=fake_enhance),
            patch("apps.content.tasks.video_anchor.apply", side_effect=anchor_via(fake_extract)),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        client = mocks[0].return_value
        client.upload_image.return_value = "uploaded.png"
        client.generate.side_effect = fake_generate
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_GENERATION, mode=Job.Mode.AUTO)
        generate_video_task.apply(args=(job.id, self.script.id))
        job.refresh_from_db()
        self.script.refresh_from_db()
        return job, out_dir, prompts

    @override_settings(UPMARKET_AI=ON)
    @patch("apps.jobs.services.dispatch_job", return_value=None)
    def test_publishes_the_enhanced_file_keeps_the_raw_and_starts_the_voice(self, dispatch):
        job, out_dir, _ = self._run()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertTrue(self.script.final_video.name.endswith("final_hd.mp4"))
        self.assertTrue((out_dir / "final.mp4").exists(), "the raw original is kept")
        enhance = self.script.finishing["enhance"]
        self.assertTrue(enhance["ok"])
        self.assertTrue(enhance["source"].endswith("final.mp4"))
        voice_job = Job.objects.get(type=Job.Type.VOICE_GENERATION, context__script_id=self.script.id)
        self.assertTrue(voice_job.context["auto"])
        self.assertTrue(self.script.finishing["voice"]["started"])
        self.assertEqual(self.script.finishing["voice"]["job_id"], voice_job.id)
        self.assertTrue(dispatch.called)

    @override_settings(UPMARKET_AI={**ON, "VIDEO_ENHANCE": False})
    @patch("apps.jobs.services.dispatch_job", return_value=None)
    def test_enhancement_off_publishes_the_raw_file(self, dispatch):
        job, _, _ = self._run()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertTrue(self.script.final_video.name.endswith("final.mp4"))
        self.assertFalse(self.script.finishing["enhance"]["ok"])

    @override_settings(UPMARKET_AI=ON)
    @patch("apps.jobs.services.dispatch_job", return_value=None)
    def test_a_coffee_scene_is_rendered_without_the_hand(self, dispatch):
        job, _, prompts = self._run()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(len(prompts), 2)
        second = prompts[1]
        self.assertIn("product only, no people", second)
        self.assertNotIn("hand reaching", second)
        self.assertNotIn("smiling face", second)
        self.assertNotIn("faces the camera", second)
        segment = self.script.segments.get(index=2)
        self.assertEqual(segment.scene_state.get("characters"), [])

    @override_settings(UPMARKET_AI=ON)
    @patch("apps.jobs.services.dispatch_job", return_value=None)
    def test_the_shops_speaker_flag_still_allows_a_person(self, dispatch):
        VideoScene.objects.filter(script=self.script, index=2).update(speaker_on_camera=True)
        job, _, prompts = self._run()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertNotIn("product only, no people", prompts[1])


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class AutoVoiceTests(APITestCase):
    def setUp(self):
        user = User.objects.create_user("carol", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=user, name="S")
        product = Product.objects.create(store=self.store, name="قهوه")
        self.script = VideoScript.objects.create(store=self.store, product=product)
        VideoScene.objects.create(script=self.script, index=1, duration=5, visual_prompt="mug",
                                  narration="سلام")

    @override_settings(UPMARKET_AI={**settings.UPMARKET_AI, "VIDEO_AUTO_VOICE": False})
    def test_off_means_off(self):
        self.assertFalse(_start_auto_voice(self.script, None)["started"])
        self.assertFalse(Job.objects.filter(type=Job.Type.VOICE_GENERATION).exists())

    @override_settings(UPMARKET_AI=ON)
    def test_no_narration_no_voice_job(self):
        self.script.scenes.update(narration="")
        result = _start_auto_voice(self.script, None)
        self.assertFalse(result["started"])
        self.assertFalse(Job.objects.filter(type=Job.Type.VOICE_GENERATION).exists())

    @override_settings(UPMARKET_AI=ON)
    @patch("apps.jobs.services.dispatch_job", return_value=None)
    def test_a_running_voice_job_is_not_doubled(self, dispatch):
        first = _start_auto_voice(self.script, None)
        Job.objects.filter(id=first["job_id"]).update(state=Job.State.RUNNING)
        second = _start_auto_voice(self.script, None)
        self.assertFalse(second["started"])
        self.assertEqual(second["job_id"], first["job_id"])
