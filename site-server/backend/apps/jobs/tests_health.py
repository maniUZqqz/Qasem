"""Monitoring. Phase 18.

The property worth defending: **a monitor that reports healthy when it could
not check is worse than no monitor.** It tells you everything is fine while the
thing it was meant to watch is down, and you believe it. Several tests below
break a dependency on purpose and check the endpoint says so rather than
shrugging.

The second: **parked is not stuck.** A job waiting for its owner to press
approve is perfectly healthy. Counting it as a problem makes a working feature
look like an outage every single day.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.stores.models import Store

from .models import Job


class LivenessTests(TestCase):
    def test_healthz_needs_no_account(self):
        """A load balancer has no credentials."""
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_healthz_touches_nothing(self):
        """It is asked every second. It must never be the thing that falls over
        under its own monitoring."""
        with self.assertNumQueries(0):
            self.client.get("/healthz")


class ReadinessTests(TestCase):
    def test_readyz_reports_the_checks_it_ran(self):
        body = self.client.get("/readyz").json()
        self.assertTrue(body["ready"])
        self.assertIn("database", body["checks"])
        self.assertIn("queue", body["checks"])

    def test_a_dead_database_makes_it_not_ready(self):
        with patch("apps.jobs.health._database", side_effect=RuntimeError("gone")):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ready"])

    def test_a_check_that_crashed_is_a_check_that_failed(self):
        """Not an exception reaching the client, and not a pass."""
        with patch("apps.jobs.health._queue", side_effect=RuntimeError("boom")):
            body = self.client.get("/readyz").json()
        self.assertFalse(body["checks"]["queue"]["ok"])
        self.assertIn("boom", body["checks"]["queue"]["detail"])

    def test_eager_mode_is_not_reported_as_a_broken_queue(self):
        """There is deliberately no broker in eager mode, and confusing the two
        sends someone to debug a Redis that was never meant to be running."""
        body = self.client.get("/readyz").json()
        self.assertTrue(body["checks"]["queue"]["ok"])
        self.assertIn("eager", body["checks"]["queue"]["detail"])

    def test_a_local_volume_is_reported_as_single_machine(self):
        """Correct in development, wrong on more than one box. The honest
        answer is to say which this is."""
        detail = self.client.get("/readyz").json()["checks"]["storage"]["detail"]
        self.assertIn("single machine", detail)


class MetricsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("metrics-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه سلامت")
        self.staff = User.objects.create_user("metrics-staff", password="x", is_staff=True)

    def _job(self, state, **kwargs):
        return Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION, state=state, **kwargs
        )

    def test_metrics_are_staff_only(self):
        """Queue depth and failure rates are a map of how to overload us, and
        the rows name customers' work."""
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/metrics").status_code, 403)

    def test_an_anonymous_request_gets_nothing(self):
        self.assertIn(self.client.get("/metrics").status_code, (401, 403))

    def test_a_staff_user_sees_the_numbers(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/metrics").status_code, 200)

    def test_a_job_parked_for_approval_is_not_counted_as_stuck(self):
        """It is perfectly healthy. Counting it as a problem makes a working
        feature look like an outage every day."""
        self._job(Job.State.WAITING_APPROVAL)
        self.client.force_login(self.staff)
        jobs = self.client.get("/metrics").json()["jobs"]
        self.assertEqual(jobs["stuck"], 0)
        self.assertEqual(jobs["waiting_for_a_person"], 1)

    def test_a_job_running_far_too_long_is(self):
        job = self._job(Job.State.PROCESSING)
        Job.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(hours=5),
        )
        self.client.force_login(self.staff)
        jobs = self.client.get("/metrics").json()["jobs"]
        self.assertEqual(jobs["stuck"], 1)
        self.assertEqual(jobs["stuck_ids"], [job.pk])

    def test_a_quiet_night_is_not_a_perfect_success_rate(self):
        """None, not 0.0. Dividing by nothing and reporting 100% is a number
        someone will quote."""
        self.client.force_login(self.staff)
        day = self.client.get("/metrics").json()["last_24h"]
        self.assertEqual(day["total"], 0)
        self.assertIsNone(day["failure_rate"])
        self.assertFalse(day["alarming"])

    def test_a_bad_night_is_flagged(self):
        for _ in range(3):
            self._job(Job.State.FAILED)
        self._job(Job.State.COMPLETED)
        self.client.force_login(self.staff)
        day = self.client.get("/metrics").json()["last_24h"]
        self.assertEqual(day["failure_rate"], 0.75)
        self.assertTrue(day["alarming"])

    def test_it_says_how_long_someone_has_been_waiting(self):
        job = self._job(Job.State.WAITING_APPROVAL)
        Job.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(hours=30),
        )
        self.client.force_login(self.staff)
        self.assertGreater(
            self.client.get("/metrics").json()["jobs"]["longest_wait_hours"], 29,
        )

    def test_the_ai_engines_never_fail_readiness(self):
        """A shop can log in, see their products and read their inbox with the
        GPU box switched off."""
        with patch("apps.jobs.health._ai_engines", side_effect=RuntimeError("no gpu")):
            self.assertEqual(self.client.get("/readyz").status_code, 200)
