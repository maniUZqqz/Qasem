from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.content.models import Caption, VideoScript
from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store
from services.publishing.n8n import PublishError

from .models import Campaign, PublishJob
from .tasks import build_payload, publish_campaign_task


class CampaignAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش اسپرت", price=100)
        self.caption = Caption.objects.create(
            store=self.store,
            product=self.product,
            platform="INSTAGRAM",
            short_text="کوتاه",
            medium_text="متوسط",
            long_text="بلند",
            hashtags=["#کفش"],
            cta="بخر",
        )
        self.client.force_authenticate(user=self.user)

    def test_create_campaign_with_linked_caption(self):
        resp = self.client.post(
            "/api/v1/campaigns/",
            {
                "product": self.product.id,
                "name": "کمپین پاییزه",
                "goal": "فروش",
                "caption": self.caption.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        campaign = Campaign.objects.get(id=resp.data["id"])
        self.assertEqual(campaign.store, self.store)
        self.assertEqual(campaign.approval_state, Campaign.ApprovalState.DRAFT)
        self.assertEqual(resp.data["caption_detail"]["short_text"], "کوتاه")

    def test_cannot_link_foreign_product_content(self):
        other_product = Product.objects.create(store=self.store, name="کیف")
        resp = self.client.post(
            "/api/v1/campaigns/",
            {"product": other_product.id, "name": "x", "caption": self.caption.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_tenancy(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        bob_product = Product.objects.create(store=bob_store, name="B1")
        bob_campaign = Campaign.objects.create(
            store=bob_store, product=bob_product, name="bob camp"
        )
        resp = self.client.get(f"/api/v1/campaigns/{bob_campaign.id}/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(
            "/api/v1/campaigns/", {"product": bob_product.id, "name": "hack"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_approve_reject_flow(self):
        campaign = Campaign.objects.create(store=self.store, product=self.product, name="c1")
        resp = self.client.post(f"/api/v1/campaigns/{campaign.id}/approve/")
        self.assertEqual(resp.data["approval_state"], "APPROVED")
        resp = self.client.post(
            f"/api/v1/campaigns/{campaign.id}/reject/", {"note": "رنگ پوستر بد است"}
        )
        self.assertEqual(resp.data["approval_state"], "REJECTED")
        campaign.refresh_from_db()
        self.assertIn("رنگ پوستر", campaign.notes)

    def test_publish_requires_approval(self):
        campaign = Campaign.objects.create(store=self.store, product=self.product, name="c1")
        resp = self.client.post(
            f"/api/v1/campaigns/{campaign.id}/publish/",
            {"platforms": ["instagram"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "not_approved")

    @patch("apps.campaigns.views.publish_campaign_task")
    def test_publish_creates_jobs(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="x")
        campaign = Campaign.objects.create(
            store=self.store,
            product=self.product,
            name="c1",
            approval_state=Campaign.ApprovalState.APPROVED,
        )
        resp = self.client.post(
            f"/api/v1/campaigns/{campaign.id}/publish/",
            {"platforms": ["instagram", "telegram", "bogus"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        self.assertEqual(campaign.publish_jobs.count(), 2)  # bogus filtered out
        self.assertEqual(Job.objects.get(id=resp.data["job_id"]).type, Job.Type.PUBLISHING)


class PublishTaskTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش", price=100)
        self.caption = Caption.objects.create(
            store=self.store,
            product=self.product,
            platform="INSTAGRAM",
            short_text="کوتاه",
            medium_text="متوسط",
            long_text="بلند",
            hashtags=["#x"],
            cta="بخر",
        )
        self.campaign = Campaign.objects.create(
            store=self.store,
            product=self.product,
            name="کمپین",
            caption=self.caption,
            approval_state=Campaign.ApprovalState.APPROVED,
        )

    def test_build_payload_contains_real_data(self):
        script = VideoScript.objects.create(store=self.store, product=self.product)
        script.final_video.name = "generated/videos/final.mp4"
        script.save()
        self.campaign.video_script = script
        self.campaign.save()
        payload = build_payload(self.campaign, "instagram")
        self.assertEqual(payload["platform"], "instagram")
        self.assertEqual(payload["content"]["caption"]["short"], "کوتاه")
        self.assertTrue(payload["content"]["video_url"].startswith("http://localhost:8000/media/"))
        self.assertIsNone(payload["content"]["poster_url"])

    @patch("apps.campaigns.tasks.send_to_n8n")
    def test_publish_success_marks_published(self, mock_send):
        mock_send.return_value = {"status_code": 200, "body": {"ok": True}}
        publish_job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram"
        )
        job = Job.objects.create(store=self.store, type=Job.Type.PUBLISHING)
        publish_campaign_task.apply(args=(job.id, self.campaign.id, [publish_job.id]))

        job.refresh_from_db()
        publish_job.refresh_from_db()
        self.campaign.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(publish_job.status, PublishJob.Status.SENT)
        self.assertIsNotNone(publish_job.published_at)
        self.assertEqual(self.campaign.approval_state, Campaign.ApprovalState.PUBLISHED)

    @patch("apps.campaigns.tasks.send_to_n8n")
    def test_publish_failure_recorded(self, mock_send):
        mock_send.side_effect = PublishError("connection refused")
        publish_job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram"
        )
        job = Job.objects.create(store=self.store, type=Job.Type.PUBLISHING)
        publish_campaign_task.apply(args=(job.id, self.campaign.id, [publish_job.id]))

        job.refresh_from_db()
        publish_job.refresh_from_db()
        self.campaign.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertEqual(publish_job.status, PublishJob.Status.FAILED)
        self.assertIn("connection refused", publish_job.last_error)
        # not published on failure
        self.assertEqual(self.campaign.approval_state, Campaign.ApprovalState.APPROVED)


class PublishDeadlockTests(APITestCase):
    """Stale PENDING rows must never block publishing forever."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش", price=100)
        self.campaign = Campaign.objects.create(
            store=self.store,
            product=self.product,
            name="کمپین",
            approval_state=Campaign.ApprovalState.APPROVED,
        )
        self.client.force_authenticate(user=self.user)

    @patch("apps.campaigns.views.publish_campaign_task")
    def test_stale_pending_is_reset_and_publish_proceeds(self, mock_task):
        # leftover PENDING row with NO live publishing job (dead worker / failed dispatch)
        stale = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram"
        )
        mock_task.delay.return_value = MagicMock(id="x")
        resp = self.client.post(
            f"/api/v1/campaigns/{self.campaign.id}/publish/",
            {"platforms": ["instagram"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        stale.refresh_from_db()
        self.assertEqual(stale.status, PublishJob.Status.FAILED)

    @patch("apps.campaigns.views.publish_campaign_task")
    def test_live_pending_still_blocks(self, mock_task):
        PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram"
        )
        Job.objects.create(
            store=self.store,
            type=Job.Type.PUBLISHING,
            state=Job.State.RUNNING,
            context={"campaign_id": self.campaign.id},
        )
        resp = self.client.post(
            f"/api/v1/campaigns/{self.campaign.id}/publish/",
            {"platforms": ["instagram"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "publish_in_progress")

    @patch("apps.campaigns.views.publish_campaign_task")
    def test_sent_platform_not_resent_without_flag(self, mock_task):
        PublishJob.objects.create(
            store=self.store,
            campaign=self.campaign,
            platform="instagram",
            status=PublishJob.Status.SENT,
        )
        resp = self.client.post(
            f"/api/v1/campaigns/{self.campaign.id}/publish/",
            {"platforms": ["instagram"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "already_published")
        # resend flag allows an explicit repost
        mock_task.delay.return_value = MagicMock(id="x")
        resp = self.client.post(
            f"/api/v1/campaigns/{self.campaign.id}/publish/",
            {"platforms": ["instagram"], "resend": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)

    @patch("apps.campaigns.tasks.send_to_n8n")
    def test_partial_failure_marks_sent_and_failed_separately(self, mock_send):
        def send(payload):
            if payload["platform"] == "telegram":
                raise PublishError("boom")
            return {"status_code": 200, "body": {"ok": True}}

        mock_send.side_effect = send
        ok_job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="instagram"
        )
        bad_job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="telegram"
        )
        job = Job.objects.create(store=self.store, type=Job.Type.PUBLISHING)
        publish_campaign_task.apply(args=(job.id, self.campaign.id, [ok_job.id, bad_job.id]))

        job.refresh_from_db()
        ok_job.refresh_from_db()
        bad_job.refresh_from_db()
        self.campaign.refresh_from_db()
        self.assertEqual(ok_job.status, PublishJob.Status.SENT)
        self.assertEqual(bad_job.status, PublishJob.Status.FAILED)
        # something went out → campaign is published; the job reports the failure
        self.assertEqual(self.campaign.approval_state, Campaign.ApprovalState.PUBLISHED)
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("telegram", job.error)


class N8NServiceTests(APITestCase):
    @patch("services.publishing.n8n.requests.post")
    def test_send_to_n8n_posts_payload(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"ok": True}, raise_for_status=lambda: None
        )
        from services.publishing.n8n import send_to_n8n

        result = send_to_n8n({"a": 1}, url="http://n8n.local/webhook", token="secret")
        self.assertEqual(result["body"], {"ok": True})
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["json"], {"a": 1})
        self.assertEqual(kwargs["headers"]["X-Upmarket-Token"], "secret")

    def test_send_without_url_raises(self):
        from services.publishing.n8n import send_to_n8n

        with self.assertRaises(PublishError):
            send_to_n8n({"a": 1}, url="")
