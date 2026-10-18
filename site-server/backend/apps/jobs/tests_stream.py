"""Live job progress, and the limit that keeps it from taking the site down.

The limit is the part worth testing hardest. Gunicorn runs twelve threads for
the whole product; an open stream holds one for its life. A feature that
silently eats that pool turns "several customers watching renders" into "the
API is down for everyone", with nothing in the logs to say why.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.stores.models import Store

from . import stream
from .models import Job


class StreamFrameTests(TestCase):
    """The generator, driven directly — no HTTP, no sockets."""

    def setUp(self):
        owner = User.objects.create_user("sse-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه استریم")
        self.user = owner

    def _job(self, state=Job.State.PROCESSING):
        return Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, state=state,
        )

    def _drain(self, job, limit=8):
        frames = []
        for chunk in stream.job_events(job.pk, self.user):
            frames.append(chunk)
            if len(frames) >= limit:
                break
        return frames

    def test_a_finished_job_sends_progress_then_done_and_stops(self):
        job = self._job(Job.State.COMPLETED)
        frames = self._drain(job)
        self.assertIn("event: progress", frames[0])
        self.assertIn("event: done", frames[1])
        self.assertEqual(len(frames), 2)

    def test_a_parked_job_ends_the_stream_rather_than_waiting_on_a_human(self):
        """Holding a worker thread open until someone comes back from lunch is
        exactly the resource leak this cap exists to prevent."""
        job = self._job(Job.State.WAITING_APPROVAL)
        frames = self._drain(job)
        self.assertTrue(any("event: waiting" in f for f in frames))

    def test_a_deleted_job_says_so_instead_of_just_closing(self):
        """A client that only sees the socket drop cannot tell "finished" from
        "the server died"."""
        job = self._job()
        job_id = job.pk
        job.delete()
        frames = list(stream.job_events(job_id, self.user))
        self.assertIn("event: gone", frames[0])

    def test_the_payload_carries_what_the_panel_draws(self):
        job = self._job(Job.State.WAITING_APPROVAL)
        job.preview = {"segment_index": 2, "segments_total": 3}
        job.save()
        frames = self._drain(job)
        body = "".join(frames)
        self.assertIn("segment_index", body)
        self.assertIn("awaiting_human", body)
        self.assertIn("state_label", body)

    def test_the_slot_is_released_when_the_stream_ends(self):
        """A leaked counter means the product stops offering live progress
        until the next restart."""
        job = self._job(Job.State.COMPLETED)
        before = stream.open_stream_count()
        list(stream.job_events(job.pk, self.user))
        self.assertEqual(stream.open_stream_count(), max(0, before - 1))


class StreamBudgetTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("budget-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه ظرفیت")
        self.job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION,
            state=Job.State.COMPLETED,
        )
        self.client.force_login(self.owner)
        stream._open_streams = 0

    def tearDown(self):
        stream._open_streams = 0

    def test_a_stream_opens_normally(self):
        response = self.client.get(f"/api/v1/jobs/{self.job.pk}/stream/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        # Consume it so the slot is returned.
        b"".join(response.streaming_content)

    def test_buffering_is_disabled_or_nginx_delivers_it_all_at_once(self):
        """A buffered stream arrives at the end, which is worse than polling."""
        response = self.client.get(f"/api/v1/jobs/{self.job.pk}/stream/")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        b"".join(response.streaming_content)

    def test_over_the_budget_it_refuses_instead_of_accepting(self):
        """Twelve threads for the whole product. Accepting a connection we
        cannot afford is how a progress bar takes the API down."""
        merged = {**self.settings_ai(), "MAX_SSE_STREAMS": 0}
        with override_settings(UPMARKET_AI=merged):
            response = self.client.get(f"/api/v1/jobs/{self.job.pk}/stream/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "stream_unavailable")

    def test_a_refusal_does_not_consume_a_slot(self):
        merged = {**self.settings_ai(), "MAX_SSE_STREAMS": 0}
        with override_settings(UPMARKET_AI=merged):
            self.client.get(f"/api/v1/jobs/{self.job.pk}/stream/")
        self.assertEqual(stream.open_stream_count(), 0)

    def test_another_users_job_cannot_be_streamed(self):
        stranger = User.objects.create_user("sse-stranger", password="x")
        self.client.force_login(stranger)
        response = self.client.get(f"/api/v1/jobs/{self.job.pk}/stream/")
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_rejected(self):
        self.client.logout()
        response = self.client.get(f"/api/v1/jobs/{self.job.pk}/stream/")
        self.assertIn(response.status_code, (401, 403))

    def settings_ai(self):
        from django.conf import settings

        return dict(settings.UPMARKET_AI)


class StreamTimingTests(TestCase):
    def test_the_cap_is_below_the_proxy_timeout(self):
        """nginx gives the stream 360s; the backend must be the one that
        decides when it ends, or the connection dies mid-render with no frame
        explaining why."""
        self.assertLess(stream.MAX_STREAM_SECONDS, 360)

    def test_the_heartbeat_is_frequent_enough_for_mobile_networks(self):
        """Carriers drop idle connections well before a minute."""
        self.assertLessEqual(stream.HEARTBEAT_SECONDS, 30)

    def test_the_budget_stays_below_the_thread_count(self):
        """3 workers x 4 threads = 12. Ordinary requests need somewhere to run."""
        self.assertLess(stream.max_streams(), 12)
