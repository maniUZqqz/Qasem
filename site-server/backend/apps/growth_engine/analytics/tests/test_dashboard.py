from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.growth_engine.analytics import registry
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.discovery.models import DiscoveryJob
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import SourceProvider

URL = "/api/v1/growth/dashboard/"


def make_lead(**raw):
    d, errors = build_draft(raw)
    assert not errors
    return intake.create_from_draft(d, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


class DashboardTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_staff())

    def test_empty_database_reads_zero_not_a_placeholder(self):
        data = self.client.get(URL).json()
        self.assertEqual(data["totals"]["leads"], 0)
        self.assertEqual(sum(s["count"] for s in data["by_status"]), 0)
        self.assertEqual(len(data["by_status"]), 12)
        self.assertEqual(len(data["daily"]), 14)
        self.assertEqual(sum(d["value"] for d in data["daily"]), 0)
        self.assertEqual((data["recent_jobs"], data["recent_activity"], data["top_cities"], data["pending_duplicates"]), ([], [], [], 0))
        self.assertTrue(data["coming_soon"])

    def test_numbers_are_the_database_truth(self):
        a = make_lead(business_name="الف", website="a.ir", phone="09121111111", city="تهران")
        make_lead(business_name="ب", instagram="@b", email="b@b.ir", city="تهران")
        c = make_lead(business_name="ج", city="شیراز")
        make_lead(business_name="بایگانی", phone="09122222222")
        Lead.objects.filter(business_name="بایگانی").update(is_archived=True)
        Lead.objects.filter(pk=a.pk).update(status="contacted")
        Lead.objects.filter(pk=c.pk).update(created_at=timezone.now() - timedelta(days=9))
        DiscoveryJob.objects.create(file_name="x.csv", status="completed", duplicate_count=3, total_items=5)
        DiscoveryJob.objects.create(file_name="y.csv", status="completed", duplicate_count=2, total_items=5)
        data = self.client.get(URL).json()
        totals = data["totals"]
        self.assertEqual(
            (totals["leads"], totals["archived"], totals["new_7d"], totals["with_website"], totals["with_instagram"], totals["with_phone"], totals["with_email"]),
            (3, 1, 2, 1, 1, 1, 1),
        )
        status = {s["status"]: s["count"] for s in data["by_status"]}
        self.assertEqual((status["new"], status["contacted"]), (2, 1))
        self.assertEqual(data["top_cities"][0], {"city": "تهران", "count": 2})
        self.assertEqual(data["pending_duplicates"], 5)
        self.assertEqual(sum(d["value"] for d in data["daily"]), 3)  # the 9-day-old lead is inside the 14-day window
        self.assertEqual(data["daily"][-1]["value"], 3 - 1)
        self.assertEqual(len(data["recent_jobs"]), 2)
        self.assertEqual(data["recent_activity"][0]["kind"], "created")
        self.assertTrue(data["recent_activity"][0]["lead_name"])

    def test_extra_blocks_come_from_registered_providers_and_a_broken_one_does_not_blank_the_page(self):
        registry.register("t_good", lambda: {"n": 7})
        registry.register("t_bad", lambda: 1 / 0)
        try:
            extra = self.client.get(URL).json()["extra"]
        finally:
            registry._PROVIDERS.pop("t_good", None)
            registry._PROVIDERS.pop("t_bad", None)
        self.assertEqual(extra["t_good"], {"n": 7})
        self.assertEqual(extra["t_bad"], {"error": True})

    def test_staff_only(self):
        self.assertEqual(client_for().get(URL).status_code in (401, 403), True)
        self.assertEqual(client_for(make_plain_user()).get(URL).status_code, 403)

    def test_meta_endpoint_is_the_single_vocabulary(self):
        meta = self.client.get("/api/v1/growth/meta/").json()
        self.assertEqual(len(meta["statuses"]), 12)
        self.assertIn("IR", [c["code"] for c in meta["countries"]])
        self.assertEqual(meta["csv"]["max_rows"], 10000)
        self.assertIn("phone", [t["key"] for t in meta["csv"]["targets"]])
