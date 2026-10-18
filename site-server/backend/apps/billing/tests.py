from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.products.models import Product
from apps.stores.models import Store

from . import guards, services
from .models import Plan, Subscription, Usage


def make_plans():
    trial = Plan.objects.create(
        slug="trial", name="آزمایشی", price_toman=0, is_trial=True, trial_days=14,
        video_seconds=15, images=5, captions=5, is_public=False,
        allows_publishing=False, max_products=10,
    )
    pro = Plan.objects.create(
        slug="pro", name="حرفه‌ای", price_toman=1_490_000,
        video_seconds=45, images=15, captions=15, sort_order=2,
    )
    return trial, pro


class QuotaTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner", password="x")
        self.trial, self.pro = make_plans()   # before the store: the trial
        self.store = Store.objects.create(owner=self.user, name="فروشگاه")  # signal starts it

    # ---------------------------------------------------------- allocation

    def test_first_use_starts_a_trial(self):
        sub = services.subscription_for(self.store)
        self.assertEqual(sub.plan, self.trial)
        self.assertEqual(sub.status, Subscription.Status.TRIALING)
        self.assertEqual(services.remaining(sub, Usage.Metric.IMAGES), 5)

    def test_no_trial_plan_blocks_instead_of_letting_through(self):
        # a store that somehow has no subscription, on an install with no
        # trial plan configured, must be blocked — never silently allowed
        Subscription.objects.filter(store=self.store).delete()
        Plan.objects.filter(is_trial=True).delete()
        with self.assertRaises(services.NoSubscription):
            services.subscription_for(self.store)

    # ------------------------------------------------------------ counting

    def test_reserve_reduces_remaining(self):
        services.reserve(self.store, Usage.Metric.IMAGES, 2)
        sub = services.subscription_for(self.store)
        self.assertEqual(services.remaining(sub, Usage.Metric.IMAGES), 3)

    def test_reserve_beyond_allowance_raises(self):
        services.reserve(self.store, Usage.Metric.IMAGES, 5)
        with self.assertRaises(services.QuotaExceeded):
            services.reserve(self.store, Usage.Metric.IMAGES, 1)

    def test_released_reservation_returns_the_allowance(self):
        row = services.reserve(self.store, Usage.Metric.IMAGES, 5)
        services.release(row, "رندر شکست خورد")
        sub = services.subscription_for(self.store)
        self.assertEqual(services.remaining(sub, Usage.Metric.IMAGES), 5)

    def test_committed_usage_stays_spent(self):
        row = services.reserve(self.store, Usage.Metric.IMAGES, 3)
        services.commit(row)
        services.release(row, "دیر رسید")  # must not undo a committed row
        sub = services.subscription_for(self.store)
        self.assertEqual(services.remaining(sub, Usage.Metric.IMAGES), 2)

    def test_context_manager_commits_on_success(self):
        with services.reserved(self.store, Usage.Metric.CAPTIONS, 2):
            pass
        sub = services.subscription_for(self.store)
        self.assertEqual(services.remaining(sub, Usage.Metric.CAPTIONS), 3)

    def test_context_manager_releases_on_failure(self):
        with self.assertRaises(ValueError):
            with services.reserved(self.store, Usage.Metric.CAPTIONS, 2):
                raise ValueError("boom")
        sub = services.subscription_for(self.store)
        self.assertEqual(services.remaining(sub, Usage.Metric.CAPTIONS), 5)

    # -------------------------------------------------------------- period

    def test_usage_is_scoped_to_its_period(self):
        services.reserve(self.store, Usage.Metric.IMAGES, 5)
        sub = services.subscription_for(self.store)
        sub.status = Subscription.Status.ACTIVE
        sub.save(update_fields=["status"])
        sub.roll_period()
        sub.status = Subscription.Status.ACTIVE  # roll_period only demotes trials
        sub.save(update_fields=["status"])
        self.assertEqual(services.remaining(sub, Usage.Metric.IMAGES), 5)

    def test_bonus_adds_to_the_allowance(self):
        sub = services.subscription_for(self.store)
        sub.bonus_images = 3
        sub.save(update_fields=["bonus_images"])
        self.assertEqual(services.remaining(sub, Usage.Metric.IMAGES), 8)

    def test_expired_subscription_is_not_usable(self):
        sub = services.subscription_for(self.store)
        sub.status = Subscription.Status.EXPIRED
        sub.period_end = timezone.now() - timedelta(days=1)
        sub.save(update_fields=["status", "period_end"])
        with self.assertRaises(services.NoSubscription):
            services.subscription_for(self.store)

    # --------------------------------------------------------------- gates

    def test_guard_allows_within_quota(self):
        self.assertIsNone(guards.check(self.store, guards.IMAGES, 5))

    def test_guard_returns_402_over_quota(self):
        response = guards.check(self.store, guards.IMAGES, 6)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["error"]["code"], "quota_exceeded")
        self.assertEqual(response.data["error"]["remaining"], 5)

    def test_feature_gate_follows_the_plan(self):
        self.assertIsNotNone(
            guards.check_feature(self.store, "publishing", "انتشار در پلن شما نیست.")
        )
        sub = services.subscription_for(self.store)
        sub.plan = self.pro
        sub.save(update_fields=["plan"])
        self.assertIsNone(
            guards.check_feature(self.store, "publishing", "انتشار در پلن شما نیست.")
        )

    def test_product_limit_is_enforced(self):
        for i in range(10):
            Product.objects.create(store=self.store, name=f"کالا {i}")
        with self.assertRaises(services.QuotaExceeded):
            services.check_product_limit(self.store)


class BillingAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner", password="x")
        self.other = get_user_model().objects.create_user("other", password="x")
        self.trial, self.pro = make_plans()   # before the store: the trial
        self.store = Store.objects.create(owner=self.user, name="فروشگاه")  # signal starts it

    def test_plans_are_public(self):
        response = self.client.get("/api/v1/plans/")
        self.assertEqual(response.status_code, 200)
        slugs = {row["slug"] for row in response.data}
        self.assertIn("pro", slugs)
        self.assertNotIn("trial", slugs)  # is_public=False

    def test_usage_snapshot_shows_every_meter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/v1/stores/{self.store.id}/usage/")
        self.assertEqual(response.status_code, 200)
        metrics = {row["metric"]: row for row in response.data["metrics"]}
        self.assertEqual(metrics["IMAGES"]["allowed"], 5)
        self.assertEqual(metrics["IMAGES"]["used"], 0)

    def test_another_owner_cannot_read_usage(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.get(f"/api/v1/stores/{self.store.id}/usage/")
        self.assertEqual(response.status_code, 404)

    def test_choosing_a_paid_plan_does_not_grant_it_for_free(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/v1/stores/{self.store.id}/subscription/", {"plan": "pro"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Subscription.Status.PAST_DUE)
        # and the gate stays shut until a payment moves it to ACTIVE
        with self.assertRaises(services.NoSubscription):
            services.subscription_for(self.store)
