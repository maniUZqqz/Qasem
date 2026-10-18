"""Tests for job listing, dead-job reaping, cancelling and queue dispatch."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.stores.models import Store

from . import services, staleness
from .models import Job


class JobListFilterTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.client.force_authenticate(user=self.user)
        self.running = Job.objects.create(
            store=self.store,
            type=Job.Type.PRODUCT_ANALYSIS,
            state=Job.State.RUNNING,
            context={"product_id": 7},
        )
        Job.objects.create(
            store=self.store,
            type=Job.Type.PRODUCT_ANALYSIS,
            state=Job.State.COMPLETED,
            context={"product_id": 7},
        )
        Job.objects.create(
            store=self.store,
            type=Job.Type.CAPTION_GENERATION,
            state=Job.State.QUEUED,
            context={"product_id": 8},
        )

    def test_active_type_and_product_filters(self):
        resp = self.client.get(
            "/api/v1/jobs/?active=true&type=product_analysis&product_id=7"
        )
        self.assertEqual(resp.status_code, 200)
        ids = [row["id"] for row in resp.data["results"]]
        self.assertEqual(ids, [self.running.id])

    def test_bad_product_id_returns_empty_not_500(self):
        resp = self.client.get("/api/v1/jobs/?product_id=abc")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"], [])

    def test_other_users_jobs_invisible(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        self.client.force_authenticate(user=bob)
        resp = self.client.get("/api/v1/jobs/?active=true")
        self.assertEqual(resp.data["results"], [])


class StaleJobReapingTests(APITestCase):
    """A job whose worker died must never keep a panel spinning (beter.md v2 #1/#2)."""

    def setUp(self):
        self.user = User.objects.create_user("carol", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Carol Shop")
        self.client.force_authenticate(user=self.user)

    def _job(self, state, age_seconds, job_type=Job.Type.PRODUCT_ANALYSIS):
        job = Job.objects.create(
            store=self.store, type=job_type, state=state, context={"product_id": 3}
        )
        moment = timezone.now() - timedelta(seconds=age_seconds)
        # auto_now/auto_now_add fields have to be written straight to the row
        Job.objects.filter(pk=job.pk).update(created_at=moment, updated_at=moment)
        job.refresh_from_db()
        return job

    def test_abandoned_running_job_is_failed_and_not_returned_as_active(self):
        dead = self._job(Job.State.RUNNING, staleness.running_stale_seconds() + 60)
        resp = self.client.get("/api/v1/jobs/?active=true&type=product_analysis&product_id=3")
        self.assertEqual(resp.data["results"], [])
        dead.refresh_from_db()
        self.assertEqual(dead.state, Job.State.FAILED)
        self.assertIn("نیمه‌کاره", dead.error)

    def test_queued_job_nobody_picked_up_is_failed(self):
        dead = self._job(Job.State.QUEUED, staleness.queued_stale_seconds() + 60)
        self.client.get("/api/v1/jobs/?active=true")
        dead.refresh_from_db()
        self.assertEqual(dead.state, Job.State.FAILED)

    def test_recent_job_is_left_alone(self):
        alive = self._job(Job.State.RUNNING, 30)
        resp = self.client.get("/api/v1/jobs/?active=true&type=product_analysis&product_id=3")
        self.assertEqual([row["id"] for row in resp.data["results"]], [alive.id])
        alive.refresh_from_db()
        self.assertEqual(alive.state, Job.State.RUNNING)

    def test_detail_poll_of_a_dead_job_reports_failed_so_polling_stops(self):
        dead = self._job(Job.State.RUNNING, staleness.running_stale_seconds() + 60)
        resp = self.client.get(f"/api/v1/jobs/{dead.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["state"], Job.State.FAILED)


class JobCancelTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("dave", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Dave Shop")
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(
            store=self.store, type=Job.Type.CAPTION_GENERATION, state=Job.State.RUNNING
        )

    def test_cancel_moves_job_to_terminal_state(self):
        resp = self.client.post(f"/api/v1/jobs/{self.job.id}/cancel/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["state"], Job.State.CANCELLED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, Job.State.CANCELLED)

    def test_cancel_is_idempotent_on_finished_jobs(self):
        self.job.mark_completed({"ok": True})
        resp = self.client.post(f"/api/v1/jobs/{self.job.id}/cancel/")
        self.assertEqual(resp.data["state"], Job.State.COMPLETED)

    def test_cannot_cancel_another_users_job(self):
        eve = User.objects.create_user("eve", password="Str0ngPass!x")
        self.client.force_authenticate(user=eve)
        resp = self.client.post(f"/api/v1/jobs/{self.job.id}/cancel/")
        self.assertEqual(resp.status_code, 404)


class DispatchWithoutBrokerTests(APITestCase):
    """Queue mode with a dead Redis must fail fast, not queue forever."""

    def setUp(self):
        self.user = User.objects.create_user("frank", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Frank Shop")

    def test_dispatch_fails_the_job_instead_of_leaving_it_queued(self):
        job = Job.objects.create(store=self.store, type=Job.Type.PRODUCT_ANALYSIS)
        task = MagicMock()
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False):
            with patch("apps.jobs.services.broker_reachable", return_value=False):
                response = services.dispatch_job(job, task, job.id)
        self.assertEqual(response.status_code, 503)
        task.delay.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        # The hint used to send the owner to install-redis.bat, which installs
        # Redis and then starts nothing — they ran it, nothing changed, and
        # the error said the same thing again. start.bat brings up the broker
        # AND the worker, and doctor.bat says which one is missing.
        self.assertIn("start.bat", job.error)
        self.assertIn("doctor.bat", job.error)

    def test_the_queue_needs_a_worker_too_not_just_a_broker(self):
        """Redis answering is not the same as work getting done.

        A running Redis with no worker behind it was the exact shape of "I
        press generate and nothing happens": the job queued cleanly and sat
        there for ever.
        """
        with override_settings(CELERY_TASK_ALWAYS_EAGER=True):
            self.assertFalse(services.queue_is_available())

        with override_settings(CELERY_TASK_ALWAYS_EAGER=False):
            with patch("apps.jobs.services.broker_reachable", return_value=True):
                with patch("apps.jobs.services.workers_online", return_value=True):
                    self.assertTrue(services.queue_is_available())
                with patch("apps.jobs.services.workers_online", return_value=False):
                    self.assertFalse(services.queue_is_available())
            with patch("apps.jobs.services.broker_reachable", return_value=False):
                self.assertFalse(services.queue_is_available())


class QueueSpecificStalenessTests(APITestCase):
    """A render can legitimately wait behind another render; a caption cannot."""

    def setUp(self):
        self.user = User.objects.create_user("hana", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Hana Shop")
        self.client.force_authenticate(user=self.user)

    def _queued(self, job_type, age_seconds):
        job = Job.objects.create(store=self.store, type=job_type, state=Job.State.QUEUED)
        moment = timezone.now() - timedelta(seconds=age_seconds)
        Job.objects.filter(pk=job.pk).update(created_at=moment, updated_at=moment)
        return job

    def test_caption_queued_too_long_is_reaped(self):
        job = self._queued(Job.Type.CAPTION_GENERATION, staleness.queued_stale_seconds() + 60)
        self.client.get("/api/v1/jobs/?active=true")
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)

    def test_video_job_gets_the_longer_gpu_grace_period(self):
        waiting = self._queued(
            Job.Type.VIDEO_GENERATION, staleness.queued_stale_seconds() + 60
        )
        self.client.get("/api/v1/jobs/?active=true")
        waiting.refresh_from_db()
        self.assertEqual(waiting.state, Job.State.QUEUED)

    def test_video_job_is_still_reaped_once_even_a_render_queue_makes_no_sense(self):
        abandoned = self._queued(
            Job.Type.VIDEO_GENERATION, staleness.gpu_queued_stale_seconds() + 60
        )
        self.client.get("/api/v1/jobs/?active=true")
        abandoned.refresh_from_db()
        self.assertEqual(abandoned.state, Job.State.FAILED)
