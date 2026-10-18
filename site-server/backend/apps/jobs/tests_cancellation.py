"""Cancelling has to give the credit back.

The old cancel flipped a row and stopped the spinner. From the panel that is
indistinguishable from this; on the invoice it is not, and the invoice is where
the customer finds out.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import Plan, Subscription, Usage
from apps.billing.payment_models import BillingEvent
from apps.stores.models import Store

from . import cancellation
from .models import Job


class CancellationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("cancel-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه لغو")
        plan = Plan.objects.create(
            name="آزمون", slug="cancel-plan", price_toman=1, video_seconds=100, images=10,
        )
        Subscription.objects.update_or_create(
            store=self.store,
            defaults={
                "plan": plan,
                "status": Subscription.Status.ACTIVE,
                "period_end": timezone.now() + timedelta(days=30),
            },
        )
        self.job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION,
            state=Job.State.PROCESSING,
        )

    def test_committed_credit_comes_back(self):
        row = billing.reserve(self.store, Usage.Metric.VIDEO_SECONDS, 5, job=self.job)
        billing.commit(row)

        outcome = cancellation.cancel(self.job, actor=self.owner)

        self.assertTrue(outcome["cancelled"])
        self.assertEqual(outcome["refunded"], 5)
        row.refresh_from_db()
        self.assertEqual(row.state, Usage.State.REFUNDED)

    def test_a_reservation_that_was_never_charged_is_released_not_refunded(self):
        """Refunding it would claim we gave back something we never took."""
        row = billing.reserve(self.store, Usage.Metric.VIDEO_SECONDS, 5, job=self.job)

        outcome = cancellation.cancel(self.job)

        row.refresh_from_db()
        self.assertEqual(row.state, Usage.State.RELEASED)
        self.assertEqual(outcome["refunded"], 0)

    def test_the_allowance_is_really_free_again(self):
        row = billing.reserve(self.store, Usage.Metric.VIDEO_SECONDS, 40, job=self.job)
        billing.commit(row)
        cancellation.cancel(self.job)

        used = billing.used(billing.subscription_for(self.store), Usage.Metric.VIDEO_SECONDS)
        self.assertEqual(used, 0)

    def test_the_decision_is_written_to_the_billing_history(self):
        row = billing.reserve(self.store, Usage.Metric.VIDEO_SECONDS, 5, job=self.job)
        billing.commit(row)
        cancellation.cancel(self.job, actor=self.owner)

        event = BillingEvent.objects.get(kind=BillingEvent.Kind.CREDIT_REFUNDED)
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.context["job_id"], self.job.pk)

    def test_cancelling_twice_refunds_once(self):
        """The second call is usually a double-clicked button."""
        row = billing.reserve(self.store, Usage.Metric.VIDEO_SECONDS, 5, job=self.job)
        billing.commit(row)

        first = cancellation.cancel(self.job)
        second = cancellation.cancel(self.job)

        self.assertTrue(first["cancelled"])
        self.assertFalse(second["cancelled"])
        self.assertEqual(
            Usage.objects.filter(job=self.job, state=Usage.State.REFUNDED).count(), 1
        )

    def test_a_finished_job_is_left_alone(self):
        self.job.state = Job.State.COMPLETED
        self.job.save()
        outcome = cancellation.cancel(self.job)
        self.assertFalse(outcome["cancelled"])
        self.assertEqual(outcome["state"], Job.State.COMPLETED)

    def test_the_worker_is_asked_to_stop(self):
        cancellation.cancel(self.job)
        self.job.refresh_from_db()
        self.assertTrue(self.job.cancel_requested)
        self.assertEqual(self.job.state, Job.State.CANCELLED)

    def test_finished_segments_are_not_deleted(self):
        """A cancelled job may have three good clips. Throwing those away
        discards work the owner can still watch and may still want stitched."""
        from apps.content.models import VideoScript, VideoSegment
        from apps.products.models import Product

        product = Product.objects.create(store=self.store, name="کفش", price=1)
        script = VideoScript.objects.create(store=self.store, product=product)
        done = VideoSegment.objects.create(
            script=script, index=1, status=VideoSegment.Status.DONE,
        )
        VideoSegment.objects.create(
            script=script, index=2, status=VideoSegment.Status.GENERATING,
        )
        self.job.context = {"script_id": script.pk}
        self.job.save()

        cancellation.cancel(self.job)

        done.refresh_from_db()
        self.assertEqual(done.status, VideoSegment.Status.DONE)

    def test_the_message_says_what_happened_to_the_credit(self):
        row = billing.reserve(self.store, Usage.Metric.VIDEO_SECONDS, 5, job=self.job)
        billing.commit(row)
        outcome = cancellation.cancel(self.job)
        self.assertIn("اعتبار", outcome["message"])

    def test_a_job_that_spent_nothing_says_so(self):
        outcome = cancellation.cancel(self.job)
        self.assertIn("مصرف نشده", outcome["message"])


class CancelAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("cancel-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه لغو API")
        self.job = Job.objects.create(
            store=self.store, type=Job.Type.VIDEO_GENERATION,
            state=Job.State.PROCESSING,
        )
        self.client.force_login(self.owner)

    def test_cancel_reports_the_cleanup(self):
        response = self.client.post(f"/api/v1/jobs/{self.job.pk}/cancel/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], Job.State.CANCELLED)
        self.assertIn("cancellation", body)

    def test_another_users_job_is_invisible(self):
        stranger = User.objects.create_user("cancel-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(
            self.client.post(f"/api/v1/jobs/{self.job.pk}/cancel/").status_code, 404
        )
