"""Incremental video generation — the DoD of phase 20.

"کاربر ۵ ثانیه‌ی اول را زیر یک دقیقه‌ی مفید می‌بیند و می‌تواند رد کند — بدون
اینکه GPU برای ۴۰ ثانیه‌ی بعدی مصرف شده باشد."

The measurable half of that claim is the last clause, and it is what most of
this file asserts: after the first segment, the render client must not have
been called again. Everything else — the approval loop, the billing, the
continuity state — follows from the job being able to stop.
"""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import Plan, Subscription, Usage
from apps.content.models import VideoScene, VideoScript, VideoSegment
from apps.content.tests import anchor_via
from apps.content.tasks import generate_video_task
from apps.jobs.models import Job
from apps.products.models import Product, ProductImage
from apps.stores.models import Store

TEMP_MEDIA = tempfile.mkdtemp()

SCENES = [
    {"index": 1, "duration": 5, "visual_prompt": "shot A", "transition": "NEW_SCENE"},
    {"index": 2, "duration": 5, "visual_prompt": "shot B", "transition": "CONTINUE"},
    {"index": 3, "duration": 5, "visual_prompt": "shot C", "transition": "CONTINUE"},
]


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class IncrementalGenerationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.owner = User.objects.create_user("inc-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه تدریجی")
        plan = Plan.objects.create(
            name="آزمون", slug="inc-plan", price_toman=1, video_seconds=100, images=10,
        )
        Subscription.objects.update_or_create(
            store=self.store,
            defaults={
                "plan": plan,
                "status": Subscription.Status.ACTIVE,
                "period_end": timezone.now() + timedelta(days=30),
            },
        )
        self.product = Product.objects.create(store=self.store, name="کفش", price=1000)

        image_dir = Path(TEMP_MEDIA) / "products" / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / "anchor.png").write_bytes(b"fakepng")
        product_image = ProductImage(product=self.product)
        product_image.image.name = "products/images/anchor.png"
        product_image.save()

        self.script = VideoScript.objects.create(
            store=self.store, product=self.product, total_duration=15,
        )
        for scene in SCENES:
            VideoScene.objects.create(script=self.script, **scene)

    # ---- fakes -----------------------------------------------------------

    def _wire(self, mock_client_cls, mock_extract, mock_concat):
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
            Path(out).write_bytes(b"finalmp4")
            return Path(out)

        client = mock_client_cls.return_value
        client.upload_image.return_value = "uploaded.png"
        client.generate.side_effect = fake_generate
        mock_extract.side_effect = fake_extract
        mock_concat.side_effect = fake_concat
        anchor = patch("apps.content.tasks.video_anchor.apply", side_effect=anchor_via(mock_extract))
        anchor.start()
        self.addCleanup(anchor.stop)
        return client

    def _job(self, mode=Job.Mode.SAFE):
        return Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, mode=mode,
            context={"script_id": self.script.pk},
        )

    def _run(self, job):
        generate_video_task.apply(args=(job.id, self.script.id))
        job.refresh_from_db()
        return job

    # ---- the DoD ---------------------------------------------------------

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_safe_mode_stops_after_the_first_segment(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """The measurable half of the DoD: the next forty seconds of GPU were
        never spent."""
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())

        self.assertEqual(job.state, Job.State.WAITING_APPROVAL, job.error)
        self.assertEqual(client.generate.call_count, 1)
        mock_concat.assert_not_called()

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_the_preview_says_what_to_look_at(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())

        self.assertEqual(job.preview["segment_index"], 1)
        self.assertEqual(job.preview["segments_total"], 3)
        self.assertTrue(job.preview["video"])

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_only_the_rendered_seconds_are_billed(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """A shop that watches five seconds and walks away pays for five, not
        for the forty it never saw."""
        self._wire(mock_client_cls, mock_extract, mock_concat)
        self._run(self._job())

        used = billing.used(billing.subscription_for(self.store), Usage.Metric.VIDEO_SECONDS)
        self.assertEqual(used, 5)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_approving_continues_and_bills_the_next_segment_only(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())

        self.client.force_login(self.owner)
        response = self.client.post(f"/api/v1/jobs/{job.pk}/approve/")
        self.assertEqual(response.status_code, 200)

        job.refresh_from_db()
        # it rendered segment 2 and parked again
        self.assertEqual(job.state, Job.State.WAITING_APPROVAL)
        self.assertEqual(job.preview["segment_index"], 2)
        self.assertEqual(client.generate.call_count, 2)
        used = billing.used(billing.subscription_for(self.store), Usage.Metric.VIDEO_SECONDS)
        self.assertEqual(used, 10)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_approving_to_the_end_finishes_the_video(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())
        self.client.force_login(self.owner)

        for _ in range(3):
            job.refresh_from_db()
            if job.state != Job.State.WAITING_APPROVAL:
                break
            self.client.post(f"/api/v1/jobs/{job.pk}/approve/")

        job.refresh_from_db()
        self.script.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(client.generate.call_count, 3)
        self.assertEqual(self.script.status, VideoScript.Status.READY)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_auto_mode_runs_straight_through(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """No quality score exists yet, so Auto never pauses — which is
        "nobody looked", not "it passed"."""
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job(Job.Mode.AUTO))

        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(client.generate.call_count, 3)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_auto_mode_pauses_on_a_low_score(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """When phase 21 starts writing scores, Auto has to act on them.

        The threshold is overridden by merging, not replacing: swapping the
        whole UPMARKET_AI dict removes COMFYUI_BASE_URL and the job fails for
        the wrong reason.
        """
        from django.conf import settings

        self._wire(mock_client_cls, mock_extract, mock_concat)
        merged = {**settings.UPMARKET_AI, "QUALITY_PAUSE_THRESHOLD": 0.6}

        original = VideoSegment.save

        def save_with_score(self_seg, *args, **kwargs):
            if self_seg.status == VideoSegment.Status.DONE:
                # A judged, otherwise-good report: only the score may pause it.
                judged = {"axes": [{"name": "نوردهی", "score": 90.0, "note": ""}],
                          "verdict": "GOOD", "vision_checked": True, "error": ""}
                self_seg.metadata = {**(self_seg.metadata or {}), "qc": judged,
                                     "quality_score": 0.2}
            return original(self_seg, *args, **kwargs)

        with override_settings(UPMARKET_AI=merged):
            with patch.object(VideoSegment, "save", save_with_score):
                job = self._run(self._job(Job.Mode.AUTO))

        self.assertEqual(job.state, Job.State.WAITING_APPROVAL, job.error)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_rejecting_a_preview_refunds_and_stops(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())

        self.client.force_login(self.owner)
        response = self.client.post(
            f"/api/v1/jobs/{job.pk}/reject/", {"reason": "محصول عوض شده"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.CANCELLED)
        self.assertEqual(client.generate.call_count, 1)
        used = billing.used(billing.subscription_for(self.store), Usage.Metric.VIDEO_SECONDS)
        self.assertEqual(used, 0)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_a_cancel_flag_stops_the_next_segment(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """The checkpoint a running worker reads, since it cannot be killed."""
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._job(Job.Mode.AUTO)
        job.cancel_requested = True
        job.save()

        self._run(job)

        self.assertEqual(client.generate.call_count, 0)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_mode_can_be_switched_mid_flight(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """The first approval prompt is what tells the owner whether they care
        to see the rest."""
        client = self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())
        self.client.force_login(self.owner)

        response = self.client.patch(
            f"/api/v1/jobs/{job.pk}/mode/", {"mode": "AUTO"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.client.post(f"/api/v1/jobs/{job.pk}/approve/")

        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(client.generate.call_count, 3)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_approving_something_that_is_not_waiting_is_refused(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job(Job.Mode.AUTO))
        self.client.force_login(self.owner)

        response = self.client.post(f"/api/v1/jobs/{job.pk}/approve/")
        self.assertEqual(response.status_code, 409)

    @patch("apps.content.tasks.concat_videos")
    @patch("apps.content.tasks.extract_last_frame")
    @patch("apps.content.tasks.ComfyUIClient")
    def test_a_parked_job_is_never_reaped_as_stale(
        self, mock_client_cls, mock_extract, mock_concat
    ):
        """It will sit there overnight on purpose. Failing it while the owner
        sleeps throws away finished GPU work."""
        from apps.jobs import staleness

        self._wire(mock_client_cls, mock_extract, mock_concat)
        job = self._run(self._job())

        Job.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(days=3),
            created_at=timezone.now() - timedelta(days=3),
        )
        staleness.reap()

        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.WAITING_APPROVAL)
