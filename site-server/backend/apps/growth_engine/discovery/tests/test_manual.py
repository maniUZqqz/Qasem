from django.test import TestCase

from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_staff
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.sources.models import LeadSource

API = "/api/v1/growth/discovery/manual"


class ManualDiscoveryTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def post(self, payload, check=False):
        return self.client.post(API + ("/check/" if check else "/"), payload, format="json")

    def test_each_mode_creates_a_lead_with_its_own_source(self):
        cases = [
            ({"mode": "website_url", "website": "https://www.Shop-A.ir/?utm_source=x"}, "website_url"),
            ({"mode": "instagram_url", "instagram": "https://instagram.com/shop_b/"}, "instagram_url"),
            ({"mode": "business_name", "business_name": "فروشگاه ج"}, "business_name"),
            ({"mode": "manual", "business_name": "فروشگاه د", "phone": "0912 000 1111", "city": "یزد", "country": "ایران"}, "manual"),
        ]
        for payload, origin in cases:
            with self.subTest(mode=payload["mode"]):
                response = self.post(payload)
                self.assertEqual(response.status_code, 201, response.content)
                lead = Lead.objects.get(pk=response.json()["lead"]["id"])
                self.assertEqual(lead.origin, origin)
                source = LeadSource.objects.get(lead=lead)
                self.assertEqual((source.provider, source.source_ref, source.created_by_id), (origin, "manual", self.staff.pk))
        self.assertEqual(Lead.objects.get(business_name="فروشگاه د").country, "IR")
        self.assertEqual(LeadSource.objects.get(lead__website="https://shop-a.ir").source_url, "https://shop-a.ir")

    def test_each_mode_requires_its_own_field(self):
        for payload in [{"mode": "website_url"}, {"mode": "instagram_url", "business_name": "x"}, {"mode": "business_name", "website": "a.ir"}, {"mode": "manual"}]:
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Lead.objects.count(), 0)

    def test_instagram_is_stored_as_given_and_never_fetched(self):
        # NoNetworkMixin fails the test if anything tried to connect
        response = self.post({"mode": "instagram_url", "instagram": "@Some.Shop"})
        lead = Lead.objects.get(pk=response.json()["lead"]["id"])
        self.assertEqual(lead.instagram_url, "https://www.instagram.com/some.shop/")
        self.assertEqual(lead.business_name, "")

    def test_a_post_link_is_rejected_with_a_clear_message(self):
        response = self.post({"mode": "instagram_url", "instagram": "https://www.instagram.com/p/ABC/"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("پست", response.json()["detail"])

    def test_check_reports_errors_duplicates_and_similar_names_without_writing(self):
        self.post({"mode": "manual", "business_name": "گل‌سرخ", "website": "shop.ir", "phone": "09121234567"})
        count = Lead.objects.count()
        dup = self.post({"mode": "website_url", "website": "http://www.shop.ir/about"}, check=True).json()
        self.assertTrue(dup["valid"])
        self.assertEqual(len(dup["duplicates"]), 1)
        self.assertEqual(dup["duplicates"][0]["matched_on"][0]["kind"], "website")
        self.assertIn("merge_preview", dup["duplicates"][0])
        similar = self.post({"mode": "business_name", "business_name": "گل سرخ"}, check=True).json()
        self.assertEqual((similar["duplicates"], len(similar["similar"])), ([], 1))
        bad = self.post({"mode": "manual", "business_name": "x", "phone": "12"}, check=True).json()
        self.assertEqual((bad["valid"], bad["errors"][0]["field"]), (False, "phone"))
        self.assertEqual(Lead.objects.count(), count)

    def test_duplicate_returns_409_and_writes_nothing(self):
        self.post({"mode": "manual", "business_name": "گل‌سرخ", "instagram": "@gol", "category": "گل"})
        response = self.post({"mode": "manual", "business_name": "نام دیگر", "instagram": "https://instagram.com/gol", "category": "پوشاک"})
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "duplicate")
        preview = body["duplicates"][0]["merge_preview"]
        states = {f["field"]: f["state"] for f in preview["fields"]}
        self.assertEqual(states["business_name"], "conflict")
        self.assertEqual(states["category"], "conflict")
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Lead.objects.get().business_name, "گل‌سرخ")

    def test_merge_decision_fills_blanks_and_keeps_conflicts(self):
        first = self.post({"mode": "manual", "business_name": "گل‌سرخ", "instagram": "@gol"}).json()["lead"]["id"]
        response = self.post({
            "mode": "manual", "business_name": "نام دیگر", "instagram": "@gol", "city": "قم", "phone": "09121234567",
            "resolution": {"action": "merge", "target_lead": first},
        })
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["result"], "merged")
        self.assertIn("city", body["filled"])
        self.assertEqual([c["field"] for c in body["conflicts"]], ["business_name"])
        lead = Lead.objects.get(pk=first)
        self.assertEqual((lead.business_name, lead.city), ("گل‌سرخ", "قم"))
        self.assertEqual(LeadSource.objects.filter(lead=lead).count(), 2)

    def test_merge_with_an_explicit_overwrite(self):
        first = self.post({"mode": "manual", "business_name": "قدیمی", "instagram": "@gol"}).json()["lead"]["id"]
        response = self.post({
            "mode": "manual", "business_name": "جدید", "instagram": "@gol",
            "resolution": {"action": "merge", "overwrite_fields": ["business_name"]},
        })
        self.assertEqual(response.json()["overwritten"], ["business_name"])
        self.assertEqual(Lead.objects.get(pk=first).business_name, "جدید")

    def test_skip_decision_writes_nothing(self):
        self.post({"mode": "manual", "business_name": "الف", "instagram": "@gol"})
        response = self.post({"mode": "manual", "business_name": "ب", "instagram": "@gol", "resolution": {"action": "skip"}})
        self.assertEqual(response.json(), {"result": "skipped"})
        self.assertEqual((Lead.objects.count(), LeadSource.objects.count()), (1, 1))

    def test_unknown_mode_is_rejected(self):
        self.assertEqual(self.post({"mode": "scrape", "website": "a.ir"}).status_code, 400)
