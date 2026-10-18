"""Scheduled publishing and the learning loop — phases 24 and 25.

The DoD for scheduling is blunt: "یک پست زمان‌بندی‌شده در ساعت مقرر **بدون
دخالت انسان** منتشر شود." So the tests drive the beat's own function, not a
view, because that is what runs at 9am when nobody is awake.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.products.models import Product
from apps.stores.models import Store

from . import learning, scheduling
from .models import Campaign, PublishJob


class ScheduleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("sched-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه زمان‌بندی")
        product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self.campaign = Campaign.objects.create(
            store=self.store, product=product, name="کمپین بهار",
        )

    def _queue(self, minutes_from_now):
        return PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram",
            scheduled_for=timezone.now() + timedelta(minutes=minutes_from_now),
        )

    def test_a_time_in_the_past_is_refused(self):
        """Someone who typed yesterday's date meant a different date; honouring
        it literally posts to their followers this second."""
        with self.assertRaises(ValueError):
            scheduling.schedule(
                self.campaign, "instagram", timezone.now() - timedelta(hours=1),
            )

    def test_a_future_post_is_not_due_yet(self):
        self._queue(60)
        self.assertEqual(list(scheduling.due()), [])

    def test_a_post_whose_time_has_passed_is_due(self):
        job = self._queue(-1)
        self.assertIn(job, list(scheduling.due()))

    def test_publishing_happens_without_a_person(self):
        """The DoD, exercised through the function the beat calls."""
        self._queue(-1)
        with patch("apps.campaigns.tasks.publish_scheduled_job.delay") as dispatched:
            result = scheduling.run_due()

        self.assertEqual(result["published"], 1)
        dispatched.assert_called_once()

    def test_a_post_can_be_late_but_never_early(self):
        """Publishing before the scheduled time is a bug the shop cannot undo."""
        self._queue(5)
        with patch("apps.campaigns.tasks.publish_scheduled_job.delay") as dispatched:
            scheduling.run_due()
        dispatched.assert_not_called()

    def test_a_badly_overdue_post_is_missed_rather_than_published(self):
        """A Friday sale post landing on Monday is worse than one that never
        went out: the shop finds out after its customers did."""
        job = self._queue(0)
        PublishJob.objects.filter(pk=job.pk).update(
            scheduled_for=timezone.now() - scheduling.LATE_LIMIT - timedelta(minutes=1)
        )

        with patch("apps.campaigns.tasks.publish_scheduled_job.delay") as dispatched:
            result = scheduling.run_due()

        dispatched.assert_not_called()
        self.assertEqual(result["missed"], 1)
        job.refresh_from_db()
        self.assertEqual(job.status, PublishJob.Status.FAILED)
        self.assertIn("دوباره زمان‌بندی", job.last_error)

    def test_two_workers_cannot_both_publish_the_same_post(self):
        """A duplicate is something the shop's followers see."""
        job = self._queue(-1)
        self.assertTrue(scheduling.claim(job))
        self.assertFalse(scheduling.claim(job))

    def test_a_dead_broker_puts_the_post_back_in_the_queue(self):
        """It publishes on the next tick rather than being silently lost."""
        job = self._queue(-1)
        with patch(
            "apps.campaigns.tasks.publish_scheduled_job.delay",
            side_effect=RuntimeError("broker down"),
        ):
            scheduling.run_due()

        job.refresh_from_db()
        self.assertEqual(job.status, PublishJob.Status.PENDING)

    def test_an_unscheduled_publish_is_never_picked_up(self):
        """Publishing by hand and publishing on a timer are separate paths."""
        PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram",
        )
        self.assertEqual(list(scheduling.due()), [])


class ScheduleAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("sapi-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه API زمان")
        product = Product.objects.create(store=self.store, name="کفش", price=1)
        self.campaign = Campaign.objects.create(
            store=self.store, product=product, name="کمپین",
        )
        self.client.force_login(self.owner)

    def test_scheduling_from_the_panel(self):
        when = (timezone.now() + timedelta(days=1)).isoformat()
        response = self.client.post(
            f"/api/v1/campaigns/{self.campaign.pk}/schedule/",
            {"when": when, "platforms": ["instagram"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["scheduled"]), 1)

    def test_a_past_time_is_refused_with_a_readable_reason(self):
        when = (timezone.now() - timedelta(days=1)).isoformat()
        response = self.client.post(
            f"/api/v1/campaigns/{self.campaign.pk}/schedule/",
            {"when": when}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "past_time")

    def test_an_unreadable_time_is_refused(self):
        response = self.client.post(
            f"/api/v1/campaigns/{self.campaign.pk}/schedule/",
            {"when": "فردا صبح"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_the_queue_is_visible(self):
        self.client.post(
            f"/api/v1/campaigns/{self.campaign.pk}/schedule/",
            {"when": (timezone.now() + timedelta(days=1)).isoformat()},
            content_type="application/json",
        )
        rows = self.client.get(f"/api/v1/stores/{self.store.pk}/scheduled/").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "PENDING")

    def test_a_queued_post_can_be_cancelled(self):
        created = self.client.post(
            f"/api/v1/campaigns/{self.campaign.pk}/schedule/",
            {"when": (timezone.now() + timedelta(days=1)).isoformat()},
            content_type="application/json",
        ).json()["scheduled"][0]

        response = self.client.delete(
            f"/api/v1/stores/{self.store.pk}/scheduled/?id={created['id']}"
        )
        self.assertEqual(response.status_code, 204)

    def test_cancelling_something_already_sent_is_refused(self):
        job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram",
            scheduled_for=timezone.now() + timedelta(days=1),
            status=PublishJob.Status.SENT,
        )
        response = self.client.delete(
            f"/api/v1/stores/{self.store.pk}/scheduled/?id={job.pk}"
        )
        self.assertEqual(response.status_code, 409)


class LearningTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("learn-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه یادگیری")
        self.product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self.campaign = Campaign.objects.create(
            store=self.store, product=self.product, name="کمپین",
        )

    def _published(self, platform="instagram", days_ago=1):
        return PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform=platform,
            status=PublishJob.Status.SENT,
            published_at=timezone.now() - timedelta(days=days_ago),
            response={"post_id": "abc"},
        )

    def _performance(self, **numbers):
        job = self._published()
        return learning.PostPerformance.objects.create(
            publish_job=job, store=self.store, platform=job.platform, **numbers,
        )

    def test_engagement_is_none_when_nothing_was_reported(self):
        """Zero would claim the post was seen and ignored — different, and much
        worse, news."""
        row = self._performance()
        self.assertIsNone(row.engagement)

    def test_engagement_adds_up_what_is_known(self):
        row = self._performance(likes=10, comments=3, saves=2)
        self.assertEqual(row.engagement, 15)

    def test_the_rate_needs_views(self):
        self.assertIsNone(self._performance(likes=5).engagement_rate)
        self.assertEqual(self._performance(likes=5, views=100).engagement_rate, 5.0)

    def test_a_channel_that_reports_nothing_says_so(self):
        """An empty row with no explanation reads as failure; "this channel
        does not report back" reads as a fact about the channel."""
        job = self._published(platform="telegram")
        row = learning.collect_one(job)
        self.assertTrue(row.unavailable_reason)
        self.assertIn("آماری برنمی‌گرداند", row.unavailable_reason)

    def test_numbers_are_not_refetched_within_the_window(self):
        """Asking again this soon spends the platform's rate limit on nothing."""
        job = self._published()
        learning.collect_one(job)
        with patch.object(learning, "FETCHERS", {}) as _:
            row = learning.collect_one(job)
        self.assertIsNotNone(row.fetched_at)

    def test_old_posts_stop_being_tracked(self):
        self._published(days_ago=30)
        self.assertEqual(list(learning.due_for_refresh()), [])

    def test_too_few_posts_is_said_plainly_not_dressed_as_a_pattern(self):
        """Three posts is not a pattern, and presenting it as one is how a shop
        chases noise."""
        for _ in range(2):
            self._performance(likes=10, views=100)

        report = learning.what_worked(self.store)
        self.assertFalse(report["enough_data"])
        self.assertIn("الگو نیست", report["message"])

    def test_a_real_difference_between_platforms_is_reported(self):
        for _ in range(4):
            job = self._published(platform="instagram")
            learning.PostPerformance.objects.create(
                publish_job=job, store=self.store, platform="instagram",
                likes=100, views=1000,
            )
        for _ in range(3):
            job = self._published(platform="telegram")
            learning.PostPerformance.objects.create(
                publish_job=job, store=self.store, platform="telegram",
                likes=5, views=1000,
            )

        report = learning.what_worked(self.store)
        self.assertTrue(report["enough_data"])
        platform_patterns = [p for p in report["patterns"] if p["kind"] == "platform"]
        self.assertTrue(platform_patterns)
        self.assertIn("instagram", platform_patterns[0]["text"])

    def test_linked_orders_are_named_as_correlation_not_attribution(self):
        """The sentence must not claim more than the number knows.

        It used to say the link came from the customer's own conversation.
        Nothing has ever measured that (ب۵): what is counted is orders of the
        same product in the post's own window, which is a coincidence in time
        and has to read as one.
        """
        for index in range(5):
            job = self._published()
            learning.PostPerformance.objects.create(
                publish_job=job, store=self.store, platform="instagram",
                likes=10, views=100, linked_orders=1 if index < 2 else 0,
            )

        report = learning.what_worked(self.store)
        order_patterns = [p for p in report["patterns"] if p["kind"] == "orders"]
        self.assertTrue(order_patterns)
        text = order_patterns[0]["text"]
        self.assertIn("هم‌زمانی", text)
        self.assertNotIn("گفتگوی خود مشتری", text)
