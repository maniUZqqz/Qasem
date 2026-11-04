"""The rule-based reachability score: every point has a reason, the list and the detail agree, no extra queries per row."""
from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_staff
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.models import ContactPoint
from apps.growth_engine.leads.services import scoring
from apps.growth_engine.outreach.tests.helpers import make_lead

G = "/api/v1/growth"


def contact(lead, kind, value):
    return ContactPoint.objects.create(lead=lead, kind=kind, value=value, normalized=value)


class ScoreTests(NoNetworkMixin, TestCase):
    def test_the_points_add_up_to_exactly_one_hundred(self):
        self.assertEqual(sum(points for points, _ in scoring.POINTS.values()), 100)

    def test_a_complete_lead_scores_the_maximum_and_each_point_is_explained(self):
        lead = make_lead("full.ir", email="info@full.ir", phone="09125550001", instagram="@fullshop", name="کامل", city="تهران")
        contact(lead, ContactKind.TELEGRAM, "https://t.me/fullshop")
        result = scoring.score(lead, lead.contacts.all())
        self.assertEqual((result["value"], result["level"], result["label"]), (100, "high", "بالا"))
        self.assertEqual(sum(r["points"] for r in result["reasons"]), 100)
        self.assertTrue(all(r["text"] for r in result["reasons"]))

    def test_an_empty_lead_scores_zero_with_a_reason(self):
        lead = make_lead(None, phone="02188112233", name="", form=False, city="")
        lead.contacts.all().delete()
        lead.business_name = ""
        result = scoring.score(lead, [])
        self.assertEqual((result["value"], result["level"]), (0, "low"))
        self.assertEqual(result["reasons"][0]["text"], "هیچ راهِ تماسی ثبت نشده")

    def test_a_landline_is_not_a_mobile_and_a_placeholder_email_is_nothing(self):
        lead = make_lead(None, phone="02188112233", email="name@example.com", name="الف", city="", form=False)
        result = scoring.score(lead, lead.contacts.all())
        self.assertNotIn("شمارهٔ موبایل دارد (پیامک، واتساپ و تماس ممکن است)", [r["text"] for r in result["reasons"]])
        self.assertEqual(result["value"], 3)  # only the name

    def test_levels(self):
        self.assertEqual([scoring.level(v) for v in (0, 39, 40, 69, 70, 100)], ["low", "low", "medium", "medium", "high", "high"])

    def test_do_not_contact_and_archived_leads_score_zero_for_that_reason(self):
        lead = make_lead("dnc.ir", email="a@dnc.ir")
        self.assertEqual(scoring.score(lead, lead.contacts.all(), suppressed=True)["value"], 0)
        self.assertIn("تماس نگیر", scoring.score(lead, lead.contacts.all(), suppressed=True)["reasons"][0]["text"])
        lead.is_archived = True
        self.assertEqual(scoring.score(lead, lead.contacts.all())["reasons"][0]["text"], "بایگانی شده است")


class ApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def test_the_list_and_the_detail_agree(self):
        lead = make_lead("same.ir", email="info@same.ir", phone="09125550002", name="مشترک", city="شیراز")
        listed = next(r for r in self.client.get(f"{G}/leads/").json()["results"] if r["id"] == lead.pk)
        detail = self.client.get(f"{G}/leads/{lead.pk}/").json()
        self.assertEqual(listed["reach"], detail["reach"])
        self.assertEqual(listed["reach"]["value"], 25 + 25 + 20 + 10 + 3 + 2)  # mobile, e-mail, website, contact form, name, city

    def test_a_lead_on_the_do_not_contact_list_shows_zero(self):
        lead = make_lead("dnc2.ir", email="b@dnc2.ir")
        suppression.suppress_lead(lead, "opt_out", "", self.staff)
        listed = next(r for r in self.client.get(f"{G}/leads/").json()["results"] if r["id"] == lead.pk)
        self.assertEqual((listed["do_not_contact"], listed["reach"]["value"]), (True, 0))

    def test_a_page_of_leads_costs_a_fixed_number_of_queries(self):
        for n in range(3):
            make_lead(f"q{n}.ir", email=f"x@q{n}.ir")
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"{G}/leads/")
        for n in range(3, 12):
            make_lead(f"q{n}.ir", email=f"x@q{n}.ir")
        with CaptureQueriesContext(connection) as large:
            self.client.get(f"{G}/leads/")
        self.assertEqual(len(small), len(large))
