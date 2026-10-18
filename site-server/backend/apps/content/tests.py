import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.jobs.models import Job
from apps.products.models import Product, ProductImage
from apps.stores.models import Store

from .models import Caption, GeneratedImage, VideoScene, VideoScript, VideoSegment
from .tasks import (
    generate_captions_task,
    generate_image_task,
    generate_video_script_task,
    generate_video_task,
    generate_voice_task,
)

TEMP_MEDIA = tempfile.mkdtemp(prefix="upmarket-content-test-media-")

VALID_CAPTIONS = {
    "captions": [
        {
            "platform": "INSTAGRAM",
            "short": "کفش سبک، قدم بلند ✨",
            "medium": "با این کفش اسپرت هر روز راحت بدو!",
            "long": "داستان بلند...",
            "hashtags": ["#کفش", "#running"],
            "cta": "همین حالا سفارش بده",
        },
        {
            "platform": "TELEGRAM",
            "short": "کفش اسپرت رسید",
            "medium": "توضیح تلگرامی",
            "long": "توضیح کامل تلگرام",
            "hashtags": ["#کفش"],
            "cta": "خرید از لینک",
        },
    ]
}

VALID_SCRIPT = {
    "concept": "معرفی کفش در محیط شهری",
    "cta": "همین حالا سفارش بده",
    "scenes": [
        {
            "index": 1,
            "duration": 5,
            "visual_prompt": "Cinematic shot of a sport shoe on wet asphalt at sunrise",
            "motion_prompt": "slow camera orbit",
            "narration": "شروع روزت با یه قدم درست",
            "transition": "NEW_SCENE",
        },
        {
            "index": 2,
            "duration": 5,
            "visual_prompt": "Runner sprinting through a city street wearing the shoe",
            "motion_prompt": "tracking shot",
            "narration": "سبک، راحت، برای هر روزت",
            "transition": "CONTINUE",
        },
    ],
}


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ContentTaskTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش اسپرت")
        self.client.force_authenticate(user=self.user)

    # ---------------- captions ----------------
    @patch("apps.content.tasks.text_provider")
    def test_caption_task_creates_rows(self, mock_provider_cls):
        mock_provider_cls.return_value.generate_json.return_value = (dict(VALID_CAPTIONS), "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION)
        generate_captions_task.apply(
            args=(job.id, self.product.id, ["INSTAGRAM", "TELEGRAM"], "صمیمی", "")
        )
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(Caption.objects.count(), 2)
        insta = Caption.objects.get(platform="INSTAGRAM")
        self.assertIn("کفش سبک", insta.short_text)

    @patch("apps.content.tasks.text_provider")
    def test_caption_missing_platform_fails(self, mock_provider_cls):
        only_insta = {"captions": [VALID_CAPTIONS["captions"][0]]}
        mock_provider_cls.return_value.generate_json.return_value = (only_insta, "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION)
        generate_captions_task.apply(
            args=(job.id, self.product.id, ["INSTAGRAM", "LINKEDIN"], "", "")
        )
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertEqual(Caption.objects.count(), 0)

    @patch("apps.content.views.generate_captions_task")
    def test_caption_endpoint_202(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="x")
        resp = self.client.post(
            f"/api/v1/products/{self.product.id}/captions/",
            {"platforms": ["INSTAGRAM"], "tone": "صمیمی"},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        self.assertEqual(Job.objects.get(id=resp.data["job_id"]).type, Job.Type.CAPTION_GENERATION)

    @patch("apps.content.tasks.text_provider")
    def test_caption_for_generated_image_links_subject(self, mock_provider_cls):
        """beter.md #11: captions are written for a specific content item."""
        generated = GeneratedImage.objects.create(
            store=self.store, product=self.product, kind="POSTER", concept="پوستر طلایی"
        )
        mock_provider_cls.return_value.generate_json.return_value = (dict(VALID_CAPTIONS), "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION)
        generate_captions_task.apply(
            args=(job.id, self.product.id, ["INSTAGRAM", "TELEGRAM"], "", "", generated.id, None)
        )
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        for caption in Caption.objects.all():
            self.assertEqual(caption.about_image_id, generated.id)
        # the model was told what content it is captioning
        prompt = mock_provider_cls.return_value.generate_json.call_args.args[1]
        self.assertIn("پوستر طلایی", prompt)
        self.assertIn("SPECIFIC piece of content", prompt)
        # and the API reports the subject
        resp = self.client.get(f"/api/v1/products/{self.product.id}/captions/")
        self.assertEqual(resp.data[0]["about_image"], generated.id)
        self.assertIn("پوستر", resp.data[0]["about_label"])

    @patch("apps.content.views.generate_captions_task")
    def test_caption_rejects_foreign_image_subject(self, mock_task):
        bob = User.objects.create_user("bob2", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop 2")
        bob_product = Product.objects.create(store=bob_store, name="B2")
        foreign_image = GeneratedImage.objects.create(
            store=bob_store, product=bob_product, kind="POSTER"
        )
        mock_task.delay.return_value = MagicMock(id="x")
        resp = self.client.post(
            f"/api/v1/products/{self.product.id}/captions/",
            {"platforms": ["INSTAGRAM"], "image_id": foreign_image.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "invalid_subject")

    # ---------------- video script ----------------
    @patch("apps.content.tasks.text_provider")
    def test_video_script_task_creates_script_and_scenes(self, mock_provider_cls):
        mock_provider_cls.return_value.generate_json.return_value = (dict(VALID_SCRIPT), "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_SCRIPT)
        generate_video_script_task.apply(args=(job.id, self.product.id, 10, ""))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        script = VideoScript.objects.get(product=self.product)
        self.assertEqual(script.scenes.count(), 2)
        self.assertEqual(script.scenes.first().transition, VideoScene.Transition.NEW_SCENE)
        self.assertEqual(script.total_duration, 10)

    @patch("apps.content.tasks.text_provider")
    def test_video_script_invalid_transition_coerced(self, mock_provider_cls):
        bad = {
            "concept": "c",
            "cta": "x",
            "scenes": [
                {"index": 1, "duration": 5, "visual_prompt": "shot A", "transition": "WHATEVER"},
                {"index": 2, "duration": 5, "visual_prompt": "shot B", "transition": "JUMPCUT"},
            ],
        }
        mock_provider_cls.return_value.generate_json.return_value = (bad, "{}")
        job = Job.objects.create(store=self.store, type=Job.Type.VIDEO_SCRIPT)
        generate_video_script_task.apply(args=(job.id, self.product.id, 10, ""))
        script = VideoScript.objects.get(product=self.product)
        transitions = list(script.scenes.values_list("transition", flat=True))
        self.assertEqual(transitions, ["NEW_SCENE", "CONTINUE"])

    # ---------------- video generation ----------------
    def _make_script_with_image(self):
        image_dir = Path(TEMP_MEDIA) / "products" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / "anchor.png"
        image_path.write_bytes(b"fakepng")
        product_image = ProductImage(product=self.product)
        product_image.image.name = "products/images/anchor.png"
        product_image.save()
        script = VideoScript.objects.create(
            store=self.store, product=self.product, total_duration=10
        )
        for scene in VALID_SCRIPT["scenes"]:
            VideoScene.objects.create(script=script, **scene)
        return script

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_video_generation_pipeline(self, mock_client_cls, mock_extract, mock_concat):
        script = self._make_script_with_image()
        out_dir = Path(TEMP_MEDIA) / "generated" / "videos" / f"script_{script.id}"

        def fake_generate(workflow, dest, filename=None, timeout=None):
            Path(dest).mkdir(parents=True, exist_ok=True)
            path = Path(dest) / filename
            path.write_bytes(b"fakemp4")
            return path

        def fake_extract(video, out):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"fakepng")
            return Path(out)

        def fake_concat(paths, out):
            self.assertEqual(len(paths), 2)
            Path(out).write_bytes(b"finalmp4")
            return Path(out)

        client = mock_client_cls.return_value
        client.upload_image.return_value = "uploaded.png"
        client.generate.side_effect = fake_generate
        mock_extract.side_effect = fake_extract
        mock_concat.side_effect = fake_concat

        # Auto mode: no quality score exists yet, so nothing pauses and the
        # whole video renders in one pass. Safe mode is covered separately —
        # it is the default, and it stops after the first five seconds.
        job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, mode=Job.Mode.AUTO,
        )
        generate_video_task.apply(args=(job.id, script.id))

        job.refresh_from_db()
        script.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(script.status, VideoScript.Status.READY)
        self.assertTrue(script.final_video.name.endswith("final.mp4"))
        statuses = list(script.segments.values_list("status", flat=True))
        self.assertEqual(statuses, [VideoSegment.Status.DONE, VideoSegment.Status.DONE])
        self.assertEqual(client.generate.call_count, 2)
        self.assertTrue((out_dir / "final.mp4").exists())
        # continuity: second segment anchored on previous frame
        second = script.segments.get(index=2)
        self.assertEqual(second.anchor_source, "previous_frame")

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_video_generation_resume_skips_done_segments(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        script = self._make_script_with_image()
        out_dir = Path(TEMP_MEDIA) / "generated" / "videos" / f"script_{script.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "segment_1.mp4").write_bytes(b"old")
        (out_dir / "segment_1_last.png").write_bytes(b"old")
        done = VideoSegment.objects.create(
            script=script, index=1, status=VideoSegment.Status.DONE
        )
        done.video.name = f"generated/videos/script_{script.id}/segment_1.mp4"
        done.last_frame.name = f"generated/videos/script_{script.id}/segment_1_last.png"
        done.save()

        client = mock_client_cls.return_value
        client.upload_image.return_value = "uploaded.png"

        def fake_generate(workflow, dest, filename=None, timeout=None):
            path = Path(dest) / filename
            path.write_bytes(b"fakemp4")
            return path

        client.generate.side_effect = fake_generate
        mock_extract.side_effect = lambda video, out: (
            Path(out).write_bytes(b"png"),
            Path(out),
        )[1]
        mock_concat.side_effect = lambda paths, out: (
            Path(out).write_bytes(b"final"),
            Path(out),
        )[1]

        job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, mode=Job.Mode.AUTO,
        )
        generate_video_task.apply(args=(job.id, script.id))

        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(client.generate.call_count, 1)  # only segment 2 regenerated

    def test_video_generation_requires_product_image(self):
        script = VideoScript.objects.create(store=self.store, product=self.product)
        VideoScene.objects.create(
            script=script, index=1, duration=5, visual_prompt="shot", transition="NEW_SCENE"
        )
        resp = self.client.post(f"/api/v1/video-scripts/{script.id}/generate/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "no_product_image")

    def test_video_script_get_null_before_generation(self):
        # 200 + null (not 404): "no script yet" is a normal state (beter.md #10)
        resp = self.client.get(f"/api/v1/products/{self.product.id}/video-script/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data)

    # ---------------- image studio ----------------
    VALID_IMAGE_DIRECTION = {
        "concept_fa": "پوستر مینیمال با نور طلایی",
        "prompt_en": "advertising poster of a sport shoe, golden light, minimal",
        "negative_en": "blurry, text errors",
    }

    def _image_mocks(self, mock_provider_cls, mock_client_cls):
        mock_provider_cls.return_value.generate_json.return_value = (
            dict(self.VALID_IMAGE_DIRECTION),
            "{}",
        )
        client = mock_client_cls.return_value
        client.upload_image.return_value = "uploaded.png"

        def fake_generate(workflow, dest, filename=None, timeout=None):
            Path(dest).mkdir(parents=True, exist_ok=True)
            path = Path(dest) / (filename or "gen.png")
            path.write_bytes(b"fakepng")
            return path

        client.generate.side_effect = fake_generate
        return client

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_poster_falls_back_to_txt2img_without_photo(self, mock_provider_cls, mock_client_cls):
        client = self._image_mocks(mock_provider_cls, mock_client_cls)
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "POSTER"))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        image = GeneratedImage.objects.get(product=self.product)
        self.assertEqual(image.workflow_version, "flux_txt2img@v1")
        self.assertEqual(image.kind, "POSTER")
        client.upload_image.assert_not_called()

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_poster_edits_real_product_photo_and_draws_text(
        self, mock_provider_cls, mock_client_cls
    ):
        """beter.md #4: the poster must contain OUR product (img2img) with code-drawn text."""
        from PIL import Image as PILImage

        image_dir = Path(TEMP_MEDIA) / "products" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        PILImage.new("RGB", (64, 64), "white").save(image_dir / "p.png")
        product_image = ProductImage(product=self.product)
        product_image.image.name = "products/images/p.png"
        product_image.save()
        self.product.price = 250000
        self.product.save()

        client = self._image_mocks(mock_provider_cls, mock_client_cls)

        def fake_generate_real_png(workflow, dest, filename=None, timeout=None):
            Path(dest).mkdir(parents=True, exist_ok=True)
            path = Path(dest) / (filename or "gen.png")
            PILImage.new("RGB", (416, 608), (30, 30, 60)).save(path)
            return path

        client.generate.side_effect = fake_generate_real_png
        mock_provider_cls.return_value.generate_json.return_value = (
            {**self.VALID_IMAGE_DIRECTION, "headline_fa": "کفش رویایی", "subline_fa": "سبک و راحت"},
            "{}",
        )
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "POSTER"))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        image = GeneratedImage.objects.get(product=self.product)
        self.assertEqual(image.workflow_version, "flux_img_edit@v1")
        self.assertEqual(image.source_image_id, product_image.id)
        client.upload_image.assert_called_once()
        # the stored file is the text-overlaid version, and it records what was drawn
        self.assertIn("_text", image.image.name)
        self.assertEqual(image.metadata["text_overlay"]["headline"], "کفش رویایی")
        badge = image.metadata["text_overlay"]["badge"]
        self.assertTrue(badge.endswith("تومان"))
        # Persian digits, not "250,000" (beter.md v2: posters must look finished)
        self.assertIn("۲۵۰", badge)
        self.assertNotIn("250", badge)
        # the 64x64 snapshot is upscaled to the workflow size before ComfyUI
        # sees it, otherwise img2img inherits the low resolution
        uploaded_path = Path(client.upload_image.call_args.args[0])
        self.assertTrue(uploaded_path.exists(), uploaded_path)
        with PILImage.open(uploaded_path) as prepared:
            self.assertEqual(prepared.size, (832, 1216))

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_enhanced_uses_img_edit_with_source(self, mock_provider_cls, mock_client_cls):
        image_dir = Path(TEMP_MEDIA) / "products" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / "p.png").write_bytes(b"png")
        product_image = ProductImage(product=self.product)
        product_image.image.name = "products/images/p.png"
        product_image.save()

        client = self._image_mocks(mock_provider_cls, mock_client_cls)
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "ENHANCED"))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        image = GeneratedImage.objects.get(product=self.product)
        self.assertEqual(image.workflow_version, "flux_img_edit@v1")
        self.assertEqual(image.source_image_id, product_image.id)
        client.upload_image.assert_called_once()

    @patch("apps.content.views.generate_image_task")
    def test_image_studio_endpoint(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="x")
        resp = self.client.post(
            f"/api/v1/products/{self.product.id}/image-studio/",
            {"kind": "POSTER", "style": "مینیمال"},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        resp = self.client.post(
            f"/api/v1/products/{self.product.id}/image-studio/", {"kind": "WRONG"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        # ENHANCED without any product image → 400
        resp = self.client.post(
            f"/api/v1/products/{self.product.id}/image-studio/", {"kind": "ENHANCED"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    # ---------------- voice ----------------
    @patch("apps.content.tasks.mix_audio")
    @patch("apps.content.tasks.concat_audio")
    @patch("services.audio.narration.probe_duration", return_value=4.0)
    @patch("services.audio.narration.make_silence")
    @patch("services.audio.narration.fit_audio")
    @patch("apps.content.tasks.probe_duration")
    @patch("apps.content.tasks.get_tts_provider")
    def test_voice_task_mixes_narration(
        self, mock_get_tts, mock_probe, mock_fit, mock_silence, mock_narration_probe,
        mock_concat, mock_mix,
    ):
        script = self._make_script_with_image()
        video_dir = Path(TEMP_MEDIA) / "generated" / "videos" / f"script_{script.id}"
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "final.mp4").write_bytes(b"video")
        script.final_video.name = f"generated/videos/script_{script.id}/final.mp4"
        script.save()

        def write_file(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"x")
            return Path(path)

        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, out: write_file(out)
        mock_get_tts.return_value = tts
        mock_probe.return_value = 4.0
        mock_fit.side_effect = lambda src, out, dur, **kw: write_file(out)
        mock_silence.side_effect = lambda dur, out, **kw: write_file(out)
        mock_concat.side_effect = lambda paths, out: write_file(out)
        mock_mix.side_effect = lambda video, audio, out: write_file(out)

        job = Job.objects.create(store=self.store, type=Job.Type.VOICE_GENERATION)
        generate_voice_task.apply(args=(job.id, script.id))

        job.refresh_from_db()
        script.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertTrue(script.final_video_voiced.name.endswith("final_voiced.mp4"))
        self.assertEqual(tts.synthesize.call_count, 2)  # both scenes have narration

    def test_voice_endpoint_requires_final_video(self):
        script = VideoScript.objects.create(store=self.store, product=self.product)
        resp = self.client.post(f"/api/v1/video-scripts/{script.id}/voice/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "no_final_video")

    @patch("apps.content.tasks.mix_audio")
    @patch("apps.content.tasks.concat_audio")
    @patch("services.audio.narration.probe_duration", return_value=4.0)
    @patch("services.audio.narration.make_silence")
    @patch("services.audio.narration.fit_audio")
    @patch("apps.content.tasks.probe_duration")
    @patch("apps.content.tasks.get_tts_provider")
    def test_voice_task_uses_script_language_voice(
        self, mock_get_tts, mock_probe, mock_fit, mock_silence, mock_narration_probe,
        mock_concat, mock_mix,
    ):
        script = self._make_script_with_image()
        script.narration_language = "en"
        video_dir = Path(TEMP_MEDIA) / "generated" / "videos" / f"script_{script.id}"
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "final.mp4").write_bytes(b"video")
        script.final_video.name = f"generated/videos/script_{script.id}/final.mp4"
        script.save()

        def write_file(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"x")
            return Path(path)

        tts = MagicMock()
        tts.synthesize.side_effect = lambda text, out: write_file(out)
        mock_get_tts.return_value = tts
        mock_probe.return_value = 4.0
        mock_fit.side_effect = lambda src, out, dur, **kw: write_file(out)
        mock_silence.side_effect = lambda dur, out, **kw: write_file(out)
        mock_concat.side_effect = lambda paths, out: write_file(out)
        mock_mix.side_effect = lambda video, audio, out: write_file(out)

        job = Job.objects.create(store=self.store, type=Job.Type.VOICE_GENERATION)
        generate_voice_task.apply(args=(job.id, script.id))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        # the store travels with the request: narration text is about to leave
        # the building, and only the store knows whether that is allowed
        mock_get_tts.assert_called_once_with(language="en", store=self.store)

    def test_script_endpoint_accepts_language(self):
        with patch("apps.content.views.generate_video_script_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="x")
            resp = self.client.post(
                f"/api/v1/products/{self.product.id}/video-script/",
                {"duration": 15, "language": "en"},
                format="json",
            )
            self.assertEqual(resp.status_code, 202, resp.content)
            # language is forwarded to the task and stored in the job context
            self.assertEqual(mock_task.delay.call_args.args[-1], "en")
        job = Job.objects.get(id=resp.data["job_id"])
        self.assertEqual(job.context["language"], "en")

    def test_video_generate_blocked_while_running(self):
        script = self._make_script_with_image()
        Job.objects.create(
            store=self.store,
            type=Job.Type.VIDEO_GENERATION,
            state=Job.State.RUNNING,
            context={"script_id": script.id},
        )
        resp = self.client.post(f"/api/v1/video-scripts/{script.id}/generate/")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["error"]["code"], "already_running")

    def test_voice_generate_blocked_while_running(self):
        script = self._make_script_with_image()
        script.final_video.name = "generated/videos/x.mp4"
        script.save()
        Job.objects.create(
            store=self.store,
            type=Job.Type.VOICE_GENERATION,
            state=Job.State.QUEUED,
            context={"script_id": script.id},
        )
        resp = self.client.post(f"/api/v1/video-scripts/{script.id}/voice/")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["error"]["code"], "already_running")

    def test_tenancy_on_content_endpoints(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        foreign = Product.objects.create(store=bob_store, name="B1")
        self.assertEqual(
            self.client.post(f"/api/v1/products/{foreign.id}/captions/").status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/api/v1/products/{foreign.id}/video-script/").status_code, 404
        )
