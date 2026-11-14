"""Scheduled publishing must obey the owner's approval — audit batch nm_campaigns.

Found on a copy of the database: a DRAFT campaign could be scheduled, the same
request twice queued two posts, `platforms: "abc"` queued three, `["myspace"]`
was accepted, and rejecting a campaign left its six queued posts PENDING — they
would have gone out at the scheduled minute. At that minute nothing re-checked
anything, and a worker that died after claiming a post left it RUNNING for ever.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.content.models import Caption, GeneratedImage
from apps.customers.models import Notification
from apps.products.models import Product
from apps.stores.models import Store
from services.publishing.n8n import PublishError

from . import scheduling, tasks
from .models import Campaign, PublishJob

State = Campaign.ApprovalState


class Base(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("guard-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه نگهبان")
        self.product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self.caption = Caption.objects.create(
            store=self.store, product=self.product, platform="INSTAGRAM",
            short_text="کفش سبک", medium_text="کفش سبک برای هر روز", long_text="کفش سبک برای هر روز و هر مسیر",
        )
        self.campaign = Campaign.objects.create(
            store=self.store, product=self.product, name="کمپین",
            approval_state=State.APPROVED, caption=self.caption,
        )
        self.client.force_login(self.owner)

    def url(self):
        return f"/api/v1/campaigns/{self.campaign.pk}/schedule/"

    def when(self, days=1):
        return (timezone.now() + timedelta(days=days)).isoformat()

    def post(self, **body):
        body.setdefault("when", self.when())
        return self.client.post(self.url(), body, content_type="application/json")

    def queued(self, minutes=-1, **extra):
        return PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram",
            scheduled_for=timezone.now() + timedelta(minutes=minutes), **extra,
        )


class ScheduleRefusalTests(Base):
    def test_a_draft_campaign_cannot_be_scheduled(self):
        for state in (State.DRAFT, State.REJECTED, State.ARCHIVED):
            Campaign.objects.filter(pk=self.campaign.pk).update(approval_state=state)
            response = self.post(platforms=["instagram"])
            self.assertEqual(response.status_code, 400, state)
            self.assertEqual(response.json()["error"]["code"], "not_approved")
        self.assertEqual(PublishJob.objects.count(), 0)

    def test_a_published_campaign_can_still_get_its_other_platforms_scheduled(self):
        """The first platform going out flips the campaign to PUBLISHED."""
        Campaign.objects.filter(pk=self.campaign.pk).update(approval_state=State.PUBLISHED)
        self.assertEqual(self.post(platforms=["telegram"]).status_code, 201)

    def test_the_same_request_twice_queues_one_post(self):
        when = self.when()
        first = self.post(when=when, platforms=["instagram"])
        second = self.post(when=when, platforms=["instagram"])
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PublishJob.objects.count(), 1)
        self.assertEqual(
            first.json()["scheduled"][0]["id"], second.json()["scheduled"][0]["id"],
        )
        self.assertFalse(second.json()["scheduled"][0]["created"])

    def test_a_platform_listed_twice_is_one_post(self):
        response = self.post(platforms=["instagram", "Instagram", " instagram "])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["scheduled"]), 1)
        self.assertEqual(PublishJob.objects.count(), 1)

    def test_text_where_a_list_belongs_is_refused_not_split_into_letters(self):
        """«abc» used to become three posts: a, b and c."""
        response = self.post(platforms="abc")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "bad_platforms")
        self.assertEqual(PublishJob.objects.count(), 0)

    def test_a_platform_that_does_not_exist_is_refused(self):
        response = self.post(platforms=["myspace"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "bad_platform")
        self.assertIn("myspace", response.json()["error"]["message"])

    def test_one_bad_platform_queues_nothing(self):
        response = self.post(platforms=["instagram", "myspace"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PublishJob.objects.count(), 0)

    def test_the_default_platform_is_still_instagram(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["scheduled"][0]["platform"], "instagram")

    def test_an_impossible_date_is_a_readable_400_not_a_crash(self):
        response = self.post(when="2030-13-45T10:00:00Z")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "bad_time")

    def test_a_past_time_queues_nothing_for_any_platform(self):
        response = self.post(
            when=(timezone.now() - timedelta(hours=1)).isoformat(),
            platforms=["instagram", "telegram"],
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "past_time")
        self.assertEqual(PublishJob.objects.count(), 0)

    def test_the_service_refuses_too(self):
        """Not only the view: anything that calls `schedule()` gets the same rules."""
        Campaign.objects.filter(pk=self.campaign.pk).update(approval_state=State.DRAFT)
        self.campaign.refresh_from_db()
        with self.assertRaises(scheduling.ScheduleError) as ctx:
            scheduling.schedule(self.campaign, "instagram", timezone.now() + timedelta(hours=1))
        self.assertEqual(ctx.exception.code, "not_approved")
        self.assertIsInstance(ctx.exception, ValueError)


class RejectCancelsTheQueueTests(Base):
    def test_rejecting_a_campaign_cancels_its_queued_posts(self):
        for platform in ("instagram", "telegram", "linkedin"):
            self.assertEqual(self.post(platforms=[platform]).status_code, 201)
        self.assertEqual(PublishJob.objects.filter(status="PENDING").count(), 3)

        response = self.client.post(f"/api/v1/campaigns/{self.campaign.pk}/reject/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cancelled_scheduled"], 3)
        self.assertEqual(response.json()["approval_state"], "REJECTED")
        self.assertEqual(PublishJob.objects.count(), 0)

    def test_a_post_that_already_went_out_stays_as_history(self):
        sent = self.queued(minutes=-30, status=PublishJob.Status.SENT)
        running = self.queued(minutes=-1, status=PublishJob.Status.RUNNING)
        self.queued(minutes=60)
        response = self.client.post(f"/api/v1/campaigns/{self.campaign.pk}/reject/")
        self.assertEqual(response.json()["cancelled_scheduled"], 1)
        self.assertEqual(
            set(PublishJob.objects.values_list("pk", flat=True)), {sent.pk, running.pk},
        )

    def test_a_post_published_by_hand_is_not_a_scheduled_one(self):
        PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram",
        )
        response = self.client.post(f"/api/v1/campaigns/{self.campaign.pk}/reject/")
        self.assertEqual(response.json()["cancelled_scheduled"], 0)

    def test_other_campaigns_keep_their_queue(self):
        other = Campaign.objects.create(
            store=self.store, product=self.product, name="دیگری",
            approval_state=State.APPROVED, caption=self.caption,
        )
        PublishJob.objects.create(
            store=self.store, campaign=other, platform="instagram",
            scheduled_for=timezone.now() + timedelta(hours=2),
        )
        self.client.post(f"/api/v1/campaigns/{self.campaign.pk}/reject/")
        self.assertEqual(PublishJob.objects.filter(campaign=other).count(), 1)


class EditCancelsTheQueueTests(Base):
    def setUp(self):
        super().setUp()
        self.job = self.queued(minutes=120)

    def patch(self, **body):
        return self.client.patch(
            f"/api/v1/campaigns/{self.campaign.pk}/", body, content_type="application/json",
        )

    def test_changing_what_is_posted_cancels_the_queued_post(self):
        poster = GeneratedImage.objects.create(
            store=self.store, product=self.product, kind="POSTER", concept="پوستر",
        )
        response = self.patch(poster=poster.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["cancelled_scheduled"], 1)
        self.assertFalse(PublishJob.objects.filter(pk=self.job.pk).exists())

    def test_swapping_the_caption_cancels_the_queued_post(self):
        other = Caption.objects.create(
            store=self.store, product=self.product, platform="INSTAGRAM", short_text="متن دیگر",
        )
        self.assertEqual(self.patch(caption=other.pk).status_code, 200)
        self.assertFalse(PublishJob.objects.filter(pk=self.job.pk).exists())

    def test_renaming_does_not_touch_the_queue(self):
        """The name, goal and notes are for the team; followers never see them."""
        response = self.patch(name="اسم تازه", goal="هدف تازه")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("cancelled_scheduled", response.json())
        self.assertTrue(PublishJob.objects.filter(pk=self.job.pk).exists())

    def test_saving_the_same_content_again_keeps_the_queue(self):
        self.assertEqual(self.patch(caption=self.caption.pk).status_code, 200)
        self.assertTrue(PublishJob.objects.filter(pk=self.job.pk).exists())


class FireTimeChecksTests(Base):
    """The minute the post is due, nobody is watching — so re-check."""

    def run_job(self, job, deliver=None):
        with patch("apps.campaigns.tasks._deliver", deliver or (lambda *a, **k: {"ok": True})) as d:
            result = tasks.publish_scheduled_job(job.pk)
        job.refresh_from_db()
        return result, d

    def test_a_campaign_rejected_since_is_not_published(self):
        job = self.queued(status=PublishJob.Status.RUNNING)
        Campaign.objects.filter(pk=self.campaign.pk).update(approval_state=State.REJECTED)
        delivered = []
        result, _ = self.run_job(job, lambda *a, **k: delivered.append(1))
        self.assertEqual(delivered, [])
        self.assertFalse(result["published"])
        self.assertEqual(job.status, PublishJob.Status.FAILED)
        self.assertIn("کمپین دیگر تأیید نیست", job.last_error)

    def test_the_shop_is_told_when_it_does_not_go_out(self):
        job = self.queued(status=PublishJob.Status.RUNNING)
        Campaign.objects.filter(pk=self.campaign.pk).update(approval_state=State.DRAFT)
        self.run_job(job)
        note = Notification.objects.get(store=self.store)
        self.assertEqual(note.title, "انتشار زمان‌بندی‌شده ناموفق بود")
        self.assertIn("کمپین دیگر تأیید نیست", note.body)

    def test_a_campaign_emptied_since_is_not_published(self):
        Campaign.objects.filter(pk=self.campaign.pk).update(caption=None)
        job = self.queued(status=PublishJob.Status.RUNNING)
        delivered = []
        self.run_job(job, lambda *a, **k: delivered.append(1))
        self.assertEqual(delivered, [])
        self.assertEqual(job.status, PublishJob.Status.FAILED)
        self.assertIn("محتوایی برای انتشار ندارد", job.last_error)

    def test_an_unexpected_error_ends_as_failed_not_running_for_ever(self):
        job = self.queued(status=PublishJob.Status.RUNNING)

        def boom(*args, **kwargs):
            raise RuntimeError("n8n returned HTML")

        result, _ = self.run_job(job, boom)
        self.assertFalse(result["published"])
        self.assertEqual(job.status, PublishJob.Status.FAILED)
        self.assertIn("n8n returned HTML", job.last_error)
        self.assertEqual(Notification.objects.filter(store=self.store).count(), 1)

    def test_a_known_publishing_error_is_failed_with_its_message(self):
        job = self.queued(status=PublishJob.Status.RUNNING)

        def refuse(*args, **kwargs):
            raise PublishError("webhook 500")

        self.run_job(job, refuse)
        self.assertEqual(job.status, PublishJob.Status.FAILED)
        self.assertIn("webhook 500", job.last_error)
        self.assertEqual(job.attempts, 1)

    def test_a_good_post_is_sent_and_marks_the_campaign_published(self):
        job = self.queued(status=PublishJob.Status.RUNNING)
        result, _ = self.run_job(job)
        self.assertTrue(result["published"])
        self.assertEqual(job.status, PublishJob.Status.SENT)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.approval_state, State.PUBLISHED)

    def test_the_second_platform_of_the_same_morning_still_goes_out(self):
        """The first one flipped the campaign to PUBLISHED; that is still approval."""
        first = self.queued(status=PublishJob.Status.RUNNING)
        second = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="telegram",
            scheduled_for=timezone.now() - timedelta(minutes=1),
            status=PublishJob.Status.RUNNING,
        )
        self.run_job(first)
        result, _ = self.run_job(second)
        self.assertTrue(result["published"], result)
        self.assertEqual(second.status, PublishJob.Status.SENT)

    def test_a_job_that_is_already_finished_is_not_delivered_again(self):
        job = self.queued(status=PublishJob.Status.SENT)
        delivered = []
        result, _ = self.run_job(job, lambda *a, **k: delivered.append(1))
        self.assertEqual(delivered, [])
        self.assertEqual(result, {"skipped": "SENT"})

    def test_a_vanished_job_is_not_an_error(self):
        self.assertEqual(tasks.publish_scheduled_job(987654), {"error": "not_found"})


class StuckRunningTests(Base):
    def test_a_post_stuck_running_is_failed_and_the_shop_is_told(self):
        job = self.queued(status=PublishJob.Status.RUNNING)
        PublishJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - scheduling.RUNNING_LIMIT - timedelta(minutes=1),
        )
        with patch("apps.campaigns.tasks.publish_scheduled_job.delay"):
            result = scheduling.run_due()
        job.refresh_from_db()
        self.assertEqual(result["stuck"], 1)
        self.assertEqual(job.status, PublishJob.Status.FAILED)
        self.assertIn("تمام نشد", job.last_error)
        self.assertEqual(Notification.objects.filter(store=self.store).count(), 1)

    def test_a_post_that_is_running_right_now_is_left_alone(self):
        job = self.queued(status=PublishJob.Status.RUNNING)
        with patch("apps.campaigns.tasks.publish_scheduled_job.delay"):
            result = scheduling.run_due()
        job.refresh_from_db()
        self.assertEqual(result["stuck"], 0)
        self.assertEqual(job.status, PublishJob.Status.RUNNING)

    def test_a_manual_publish_is_never_swept(self):
        """Only scheduled rows are the beat's business."""
        job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram",
            status=PublishJob.Status.RUNNING,
        )
        PublishJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(hours=3),
        )
        self.assertEqual(scheduling.fail_stuck(), 0)
