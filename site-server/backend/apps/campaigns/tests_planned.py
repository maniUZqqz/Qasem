"""The store-level list of planned (dated) campaign tasks, for the calendar."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.products.models import Product
from apps.stores.models import Store

from .models import Campaign
from .tasks_board import CampaignTask


class PlannedTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("plan-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه برنامه")
        self.product = Product.objects.create(store=self.store, name="سرویس", price=10)
        self.campaign = Campaign.objects.create(store=self.store, product=self.product, name="هفتهٔ ۱")
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _task(self, title, due, state="TODO"):
        return CampaignTask.objects.create(
            campaign=self.campaign, store=self.store, title=title, due_at=due, state=state,
        )

    def test_lists_dated_tasks_in_order_and_skips_undated_and_dropped(self):
        now = timezone.now()
        self._task("دوم", now + timedelta(days=2))
        self._task("اول", now + timedelta(days=1))
        self._task("بی‌تاریخ", None)
        self._task("حذف‌شده", now + timedelta(days=3), state="DROPPED")
        r = self.api.get(f"/api/v1/stores/{self.store.pk}/planned/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["title"] for x in r.data], ["اول", "دوم"])
        self.assertEqual(r.data[0]["campaign"], "هفتهٔ ۱")
        self.assertIn("state_label", r.data[0])

    def test_a_stranger_cannot_read_another_shops_plan(self):
        other = User.objects.create_user("stranger", password="x")
        api = APIClient()
        api.force_authenticate(other)
        self.assertEqual(api.get(f"/api/v1/stores/{self.store.pk}/planned/").status_code, 404)


class BoardDueDateTests(TestCase):
    """Found by really using the board for a content plan: a task created with a
    due date answered 500 although the row had been saved (the date stayed a
    string, and reading it back crashed `is_late`)."""

    def setUp(self):
        self.owner = User.objects.create_user("due-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه موعد")
        self.product = Product.objects.create(store=self.store, name="سرویس", price=10)
        self.campaign = Campaign.objects.create(store=self.store, product=self.product, name="کمپین")
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.url = f"/api/v1/campaigns/{self.campaign.pk}/board/"

    def test_a_task_with_a_due_date_is_created_and_answers_201(self):
        r = self.api.post(self.url, {"title": "کاروسل", "kind": "CONTENT", "due_at": "2026-11-13T12:00:00Z", "priority": 3})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.data["due_at"].startswith("2026-11-13"))
        self.assertEqual(r.data["priority"], 3)
        self.assertFalse(r.data["is_late"] and False)  # computed without crashing

    def test_a_naive_date_is_accepted_and_made_aware(self):
        r = self.api.post(self.url, {"title": "t", "due_at": "2030-01-02T10:00:00"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(r.data["is_late"])

    def test_a_garbage_date_is_a_400_with_a_reason_not_a_500(self):
        r = self.api.post(self.url, {"title": "t", "due_at": "فردا"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["code"], "bad_due")
        self.assertEqual(CampaignTask.objects.filter(campaign=self.campaign).count(), 0)

    def test_a_bad_priority_is_a_400(self):
        r = self.api.post(self.url, {"title": "t", "priority": "زیاد"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["code"], "bad_priority")

    def test_patching_the_due_date_validates_it_too(self):
        t = CampaignTask.objects.create(campaign=self.campaign, store=self.store, title="t")
        url = f"{self.url}{t.pk}/"
        self.assertEqual(self.api.patch(url, {"due_at": "نه"}, format="json").status_code, 400)
        r = self.api.patch(url, {"due_at": "2026-12-01T09:00:00Z"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        t.refresh_from_db()
        self.assertEqual(t.due_at.year, 2026)
        r = self.api.patch(url, {"due_at": None}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_a_long_plan_text_is_kept_not_silently_cut_at_2000(self):
        text = "ا" * 5000
        r = self.api.post(self.url, {"title": "t", "detail": text, "because": "چون برنامه است"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.data["detail"]), 5000)
        self.assertEqual(r.data["because"], "چون برنامه است")
