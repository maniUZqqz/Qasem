"""The outbound sales list (صفحه ۷).

What is worth testing here is the one thing that makes it a tool instead of a
table: **what is due**. Everything else is a form.

A closed deal is never due, however old its follow-up date, because a list that
nags about deals already won is a list nobody opens — and then the one call
that mattered is the one that gets missed.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.stores.models import Store

from .outreach import Prospect, counts, due


class DueTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("out-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.past = timezone.now() - timedelta(days=1)
        self.future = timezone.now() + timedelta(days=3)

    def make(self, **kwargs) -> Prospect:
        return Prospect.objects.create(
            store=self.store, company=kwargs.pop("company", "شرکت"), **kwargs,
        )

    def test_a_past_date_is_due(self):
        row = self.make(next_action_at=self.past)
        self.assertTrue(row.is_due)
        self.assertIn(row, due(self.store))

    def test_a_future_date_is_not(self):
        self.assertFalse(self.make(next_action_at=self.future).is_due)

    def test_no_date_is_not_due(self):
        self.assertFalse(self.make().is_due)

    def test_a_won_deal_never_nags(self):
        row = self.make(next_action_at=self.past, stage=Prospect.Stage.WON)
        self.assertFalse(row.is_due)
        self.assertNotIn(row, due(self.store))

    def test_a_lost_deal_never_nags(self):
        row = self.make(next_action_at=self.past, stage=Prospect.Stage.LOST)
        self.assertNotIn(row, due(self.store))

    def test_oldest_owed_call_comes_first(self):
        older = self.make(company="الف", next_action_at=self.past - timedelta(days=5))
        newer = self.make(company="ب", next_action_at=self.past)
        self.assertEqual(list(due(self.store)), [older, newer])

    def test_counts_separate_open_from_closed(self):
        self.make(next_action_at=self.past)
        self.make(stage=Prospect.Stage.WON)
        summary = counts(self.store)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["due"], 1)
        self.assertEqual(summary["by_stage"]["WON"], 1)


class ApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("out-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.url = f"/api/v1/stores/{self.store.pk}/prospects/"
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_create_and_list(self):
        res = self.client.post(self.url, {"company": "شرکت الف"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        body = self.client.get(self.url).json()
        self.assertEqual([p["company"] for p in body["prospects"]], ["شرکت الف"])
        self.assertEqual(body["counts"]["total"], 1)

    def test_a_nameless_row_is_refused(self):
        res = self.client.post(self.url, {"company": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_the_payload_says_what_is_deliberately_missing(self):
        """A reader of the spec looks for phone lookup. Silence reads as
        unfinished; the reason reads as a decision."""
        held = self.client.get(self.url).json()["held"]
        self.assertTrue(held)
        self.assertTrue(all(h["why"] for h in held))

    def test_call_recording_is_no_longer_on_the_held_list(self):
        """It came off by building the consent record that was missing, not by
        deciding the constraint did not matter."""
        body = self.client.get(self.url).json()
        self.assertNotIn("ضبط", " ".join(h["title"] for h in body["held"]))
        self.assertIn("ضبط", " ".join(b["title"] for b in body["built_since"]))

    def test_patch_moves_the_stage(self):
        pk = self.client.post(self.url, {"company": "ب"}, format="json").json()["id"]
        res = self.client.patch(
            f"{self.url}{pk}/", {"stage": "WON"}, format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["is_closed"])

    def test_delete(self):
        pk = self.client.post(self.url, {"company": "ج"}, format="json").json()["id"]
        self.assertEqual(self.client.delete(f"{self.url}{pk}/").status_code, 204)
        self.assertEqual(Prospect.objects.count(), 0)

    def test_another_shop_cannot_see_the_list(self):
        stranger = User.objects.create_user("stranger-out", password="x")
        client = APIClient()
        client.force_authenticate(stranger)
        self.assertIn(client.get(self.url).status_code, (403, 404))

    def test_due_filter(self):
        self.client.post(
            self.url,
            {
                "company": "دیر",
                "next_action_at": (timezone.now() - timedelta(days=2)).isoformat(),
            },
            format="json",
        )
        self.client.post(self.url, {"company": "بعداً"}, format="json")
        rows = self.client.get(self.url, {"due": "1"}).json()["prospects"]
        self.assertEqual([p["company"] for p in rows], ["دیر"])
