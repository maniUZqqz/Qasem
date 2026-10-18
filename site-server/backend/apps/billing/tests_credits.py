"""Credit is charged for usable output, not for attempts.

The rule under test: a store that regenerates the same poster four times must
not pay four times for one poster. Everything else here follows from that.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.jobs.models import Job
from apps.stores.models import Store

from . import credits, services
from .models import Plan, Subscription, Usage
from .payment_models import BillingEvent


class CreditTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("credit-owner", password="x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه اعتبار")
        self.plan = Plan.objects.create(
            name="پایه", slug="base-credit", price_toman=1_000_000,
            is_public=True, images=20, video_seconds=100, captions=50,
        )
        Subscription.objects.update_or_create(
            store=self.store,
            defaults={
                "plan": self.plan,
                "status": Subscription.Status.ACTIVE,
                "period_end": timezone.now() + timedelta(days=30),
            },
        )

    def spend(self, quantity=1, metric=Usage.Metric.IMAGES):
        """One completed generation: reserved then committed."""
        row = services.reserve(self.store, metric, quantity)
        services.commit(row)
        row.refresh_from_db()
        return row


class RefundTests(CreditTestBase):
    def test_rejecting_output_returns_the_credit(self):
        row = self.spend()
        before = services.used(services.subscription_for(self.store), Usage.Metric.IMAGES)

        credits.refund(row, reason="محصول توی تصویر عوض شده", actor=self.user)

        after = services.used(services.subscription_for(self.store), Usage.Metric.IMAGES)
        self.assertEqual(after, before - 1)

    def test_refund_is_a_distinct_state_from_a_crashed_job(self):
        """Released and refunded must not be the same row state.

        "How much are we giving back for bad output?" is the number that says
        whether the product works; a crashed render must not inflate it.
        """
        crashed = services.reserve(self.store, Usage.Metric.IMAGES, 1)
        services.release(crashed, reason="GPU برگشت")
        rejected = self.spend()
        credits.refund(rejected, reason="بد بود")

        crashed.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual(crashed.state, Usage.State.RELEASED)
        self.assertEqual(rejected.state, Usage.State.REFUNDED)

    def test_refunding_twice_gives_back_one_credit(self):
        """A double-clicked button is not a second complaint."""
        row = self.spend()
        credits.refund(row, reason="یک‌بار")
        credits.refund(row, reason="دوباره")

        self.assertEqual(
            Usage.objects.filter(store=self.store, state=Usage.State.REFUNDED).count(), 1
        )

    def test_a_crashed_job_cannot_be_refunded(self):
        """Nothing was charged, so there is nothing to hand back."""
        row = services.reserve(self.store, Usage.Metric.IMAGES, 1)
        services.release(row, reason="شکست")
        with self.assertRaises(credits.NotRefundable):
            credits.refund(row)

    def test_an_unfinished_job_cannot_be_refunded(self):
        row = services.reserve(self.store, Usage.Metric.IMAGES, 1)
        with self.assertRaises(credits.NotRefundable):
            credits.refund(row)

    def test_the_decision_is_recorded_with_who_and_why(self):
        """A refund with no stated reason is indistinguishable from a bug."""
        row = self.spend()
        credits.refund(row, reason="نور تصویر خیلی تیره بود", actor=self.user)

        event = BillingEvent.objects.get(kind=BillingEvent.Kind.CREDIT_REFUNDED)
        self.assertEqual(event.actor, self.user)
        self.assertIn("تیره", event.summary)
        self.assertEqual(event.context["usage_id"], row.pk)

    def test_a_refund_without_a_reason_still_says_something(self):
        row = self.spend()
        refunded = credits.refund(row)
        self.assertTrue(refunded.quality_reason)

    def test_refunded_credit_can_be_spent_again(self):
        """The point of the refund: the allowance really is back."""
        small = Plan.objects.create(
            name="تک", slug="one-image", price_toman=1, images=1,
        )
        Subscription.objects.filter(store=self.store).update(plan=small)

        first = self.spend()
        with self.assertRaises(services.QuotaExceeded):
            services.reserve(self.store, Usage.Metric.IMAGES, 1)

        credits.refund(first, reason="بد بود")
        again = services.reserve(self.store, Usage.Metric.IMAGES, 1)
        self.assertIsNotNone(again)


class GuaranteeTests(CreditTestBase):
    @override_settings(UPMARKET_AI={"QUALITY_MAX_ATTEMPTS": 3})
    def test_a_retry_costs_a_credit_while_attempts_remain(self):
        first = self.spend()
        credits.refund(first, reason="بد")
        reservation, status = credits.reserve_retry(first)

        self.assertIsNotNone(reservation)
        self.assertFalse(status["free"])
        self.assertEqual(reservation.attempt, 2)
        self.assertEqual(reservation.retry_of, first)

    @override_settings(UPMARKET_AI={"QUALITY_MAX_ATTEMPTS": 3})
    def test_after_the_limit_the_work_is_free_and_the_credit_comes_back(self):
        """ROADMAP §9.9 row C — a promise, so it lives in code not in copy."""
        row = self.spend()
        for _ in range(2):
            credits.refund(row, reason="بد")
            row, _status = credits.reserve_retry(row)
            services.commit(row)
            row.refresh_from_db()

        self.assertEqual(row.attempt, 3)
        reservation, status = credits.reserve_retry(row)

        self.assertIsNone(reservation)
        self.assertTrue(status["free"])
        self.assertIn("رایگان", status["message"])

        row.refresh_from_db()
        self.assertEqual(row.state, Usage.State.REFUNDED)

    @override_settings(UPMARKET_AI={"QUALITY_MAX_ATTEMPTS": 3})
    def test_the_guarantee_returns_every_attempt_not_only_the_last(self):
        """Handing back one credit out of three is a discount on failure, not
        a guarantee. This is the assertion that caught exactly that."""
        row = self.spend()
        for _ in range(2):
            row, _ = credits.reserve_retry(row)
            services.commit(row)
            row.refresh_from_db()

        _, status = credits.reserve_retry(row)
        self.assertEqual(status["refunded"], 3)
        self.assertEqual(
            Usage.objects.filter(
                store=self.store, state=Usage.State.REFUNDED,
            ).count(),
            3,
        )

    @override_settings(UPMARKET_AI={"QUALITY_MAX_ATTEMPTS": 3})
    def test_the_whole_chain_costs_nothing_once_the_guarantee_fires(self):
        """The number that matters to the shop owner: what did I pay for a
        thing that never worked?"""
        row = self.spend()
        for _ in range(2):
            row, _ = credits.reserve_retry(row)
            services.commit(row)
            row.refresh_from_db()
        credits.reserve_retry(row)  # guarantee fires

        charged = Usage.objects.filter(
            store=self.store, state__in=services.COUNTED,
        ).count()
        self.assertEqual(charged, 0)

    @override_settings(UPMARKET_AI={"QUALITY_MAX_ATTEMPTS": 3})
    def test_status_counts_down_so_the_panel_can_warn_first(self):
        row = self.spend()
        self.assertEqual(credits.guarantee_status(row)["attempts_left"], 2)

        row, _ = credits.reserve_retry(row)
        self.assertEqual(credits.guarantee_status(row)["attempts_left"], 1)

    @override_settings(UPMARKET_AI={"QUALITY_MAX_ATTEMPTS": 2})
    def test_the_limit_is_configurable(self):
        row = self.spend()
        row, _ = credits.reserve_retry(row)
        services.commit(row)
        row.refresh_from_db()
        _, status = credits.reserve_retry(row)
        self.assertTrue(status["free"])

    def test_attempt_chain_is_walkable_in_order(self):
        first = self.spend()
        second, _ = credits.reserve_retry(first)
        services.commit(second)
        second.refresh_from_db()
        third, _ = credits.reserve_retry(second)

        chain = credits.attempt_chain(third)
        self.assertEqual([row.attempt for row in chain], [1, 2, 3])


class SnapshotTests(CreditTestBase):
    def test_refunds_are_shown_next_to_usage(self):
        """A store that got credits back should see it, not merely notice its
        allowance lasting longer than expected."""
        row = self.spend(quantity=2)
        credits.refund(row, reason="بد")

        snapshot = services.snapshot(self.store)
        images = next(m for m in snapshot["metrics"] if m["metric"] == "IMAGES")
        self.assertEqual(images["refunded"], 2)
        self.assertEqual(images["used"], 0)


class QualityAPITests(CreditTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def _reject_url(self, usage_id):
        return f"/api/v1/stores/{self.store.id}/usage/{usage_id}/reject/"

    def test_owner_rejects_an_output_and_the_credit_returns(self):
        row = self.spend()
        response = self.client.post(
            self._reject_url(row.pk),
            {"reason": "متن روی تصویر ناخواناست"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["usage"]["state"], "REFUNDED")
        self.assertEqual(body["guarantee"]["attempts_left"], 2)

    def test_rejecting_a_crashed_job_is_refused_with_a_reason(self):
        row = services.reserve(self.store, Usage.Metric.IMAGES, 1)
        services.release(row, reason="شکست")
        response = self.client.post(self._reject_url(row.pk))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "not_refundable")

    def test_another_users_usage_is_invisible(self):
        row = self.spend()
        stranger = User.objects.create_user("stranger-credit", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(self._reject_url(row.pk)).status_code, 404)

    def test_usage_from_another_store_cannot_be_rejected_through_mine(self):
        """Same owner, different store — the id in the path must still match."""
        other = Store.objects.create(owner=self.user, name="فروشگاه دوم")
        Subscription.objects.update_or_create(
            store=other,
            defaults={
                "plan": self.plan,
                "status": Subscription.Status.ACTIVE,
                "period_end": timezone.now() + timedelta(days=30),
            },
        )
        foreign = services.reserve(other, Usage.Metric.IMAGES, 1)
        services.commit(foreign)
        self.assertEqual(self.client.post(self._reject_url(foreign.pk)).status_code, 404)

    def test_the_job_link_survives_a_refund(self):
        """The audit trail has to keep pointing at what was generated."""
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        row = services.reserve(self.store, Usage.Metric.IMAGES, 1, job=job)
        services.commit(row)
        self.client.post(self._reject_url(row.pk))
        row.refresh_from_db()
        self.assertEqual(row.job_id, job.pk)
