"""Extraction API: permissions on every endpoint, request validation, response shapes."""
from django.test import TestCase

from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.extraction.models import ExtractionJob, ExtractionRun
from apps.growth_engine.extraction.services import runner
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import SourceProvider

API = "/api/v1/growth"


def make_lead(**raw):
    raw.setdefault("business_name", "فروشگاه")
    draft, errors = build_draft(raw)
    assert not errors, errors
    return intake.create_from_draft(draft, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


class PermissionTests(NoNetworkMixin, TestCase):
    """Staff only: anonymous -> 401, an ordinary user -> 403, on every extraction endpoint."""

    def setUp(self):
        super().setUp()
        self.lead = make_lead(website="shop.ir")
        self.job = runner.create_jobs(make_staff("owner"), lead_ids=[self.lead.pk])[0]
        self.endpoints = [
            ("get", "/extraction/jobs/"), ("post", "/extraction/jobs/"), ("get", f"/extraction/jobs/{self.job.pk}/"),
            ("post", f"/extraction/jobs/{self.job.pk}/cancel/"), ("post", f"/extraction/jobs/{self.job.pk}/resume/"),
            ("get", f"/leads/{self.lead.pk}/extraction/"),
        ]

    def test_anonymous_is_rejected_everywhere(self):
        client = client_for()
        for method, path in self.endpoints:
            with self.subTest(path=path):
                self.assertEqual(getattr(client, method)(API + path).status_code, 401)
        self.assertEqual(ExtractionJob.objects.count(), 1)

    def test_an_ordinary_user_is_forbidden_everywhere(self):
        client = client_for(make_plain_user())
        for method, path in self.endpoints:
            with self.subTest(path=path):
                self.assertEqual(getattr(client, method)(API + path).status_code, 403)
        self.job.refresh_from_db()
        self.assertEqual((ExtractionJob.objects.count(), self.job.status, self.job.cancel_requested), (1, "queued", False))

    def test_staff_reaches_them(self):
        client = client_for(make_staff())
        self.assertEqual(client.get(API + "/extraction/jobs/").status_code, 200)
        self.assertEqual(client.get(f"{API}/extraction/jobs/{self.job.pk}/").status_code, 200)
        self.assertEqual(client.get(f"{API}/leads/{self.lead.pk}/extraction/").status_code, 200)

    def test_inactive_staff_is_rejected(self):
        staff = make_staff("gone")
        staff.is_active = False
        staff.save()
        self.assertIn(client_for(staff).get(API + "/extraction/jobs/").status_code, (401, 403))


class RequestTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        self.with_site = make_lead(business_name="الف", website="a.ir")
        self.no_site = make_lead(business_name="ب", phone="09121112233")

    def post(self, payload):
        return self.client.post(f"{API}/extraction/jobs/", payload, format="json")

    def test_exactly_one_of_lead_ids_or_a_csv_import(self):
        for payload in ({}, {"lead_ids": []}, {"lead_ids": [self.with_site.pk], "discovery_job_id": 1}, {"force": True}):
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "validation")
        self.assertEqual(ExtractionJob.objects.count(), 0)

    def test_unknown_leads_unknown_imports_and_nothing_readable(self):
        self.assertEqual(self.post({"lead_ids": [99999]}).status_code, 400)
        self.assertEqual(self.post({"discovery_job_id": 99999}).status_code, 400)
        response = self.post({"lead_ids": [self.no_site.pk]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("وب‌سایت ندارد", response.json()["detail"])
        self.assertEqual(ExtractionJob.objects.count(), 0)

    def test_bad_types_are_rejected_by_the_serializer(self):
        self.assertEqual(self.post({"lead_ids": ["x"]}).status_code, 400)
        self.assertEqual(self.post({"lead_ids": [0]}).status_code, 400)

    def test_a_valid_request_creates_a_queued_job_with_a_run_per_lead(self):
        with self.captureOnCommitCallbacks(execute=False):
            response = self.post({"lead_ids": [self.with_site.pk, self.no_site.pk, self.with_site.pk]})  # duplicates are folded
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual((body["scope"], body["status"], body["total_items"], body["progress"]), ("selected", "queued", 2, 0))
        self.assertEqual(body["created_by_name"], self.staff.username)
        self.assertFalse(body["stalled"])
        self.assertEqual(sorted(ExtractionRun.objects.filter(job_id=body["id"]).values_list("lead_id", flat=True)), sorted([self.with_site.pk, self.no_site.pk]))
        self.assertEqual(list(ExtractionRun.objects.filter(job_id=body["id"]).values_list("status", flat=True)), ["queued", "queued"])

    def test_listing_and_detail_shapes(self):
        job = runner.create_jobs(self.staff, lead_ids=[self.with_site.pk])[0]
        listing = self.client.get(f"{API}/extraction/jobs/").json()
        self.assertEqual((listing["count"], listing["results"][0]["id"]), (1, job.pk))
        detail = self.client.get(f"{API}/extraction/jobs/{job.pk}/").json()
        for key in ("id", "status", "status_label", "scope", "progress", "total_items", "processed_items", "runs_done", "runs_failed", "runs_skipped", "pages_fetched", "contacts_added", "error", "stalled", "can_resume", "queued_at", "finished_at", "created_by_name", "runs"):
            self.assertIn(key, detail)
        self.assertEqual(detail["runs"][0]["lead_name"], "الف")
        self.assertEqual(self.client.get(f"{API}/extraction/jobs/9999/").status_code, 404)

    def test_the_lead_endpoint_hides_queued_runs_and_404s_for_an_unknown_lead(self):
        runner.create_jobs(self.staff, lead_ids=[self.with_site.pk])
        self.assertEqual(self.client.get(f"{API}/leads/{self.with_site.pk}/extraction/").json(), {"runs": []})
        self.assertEqual(self.client.get(f"{API}/leads/99999/extraction/").status_code, 404)
        ExtractionRun.objects.filter(lead=self.with_site).update(status="skipped", reason="recent")
        runs = self.client.get(f"{API}/leads/{self.with_site.pk}/extraction/").json()["runs"]
        self.assertEqual((runs[0]["status"], runs[0]["reason_label"]), ("skipped", "به‌تازگی استخراج شده (برای دوباره‌خوانی «اجبار» را بزنید)"))

    def test_the_lead_endpoint_returns_only_the_latest_five_runs(self):
        for _ in range(7):
            ExtractionRun.objects.create(lead=self.with_site, status="done")
        self.assertEqual(len(self.client.get(f"{API}/leads/{self.with_site.pk}/extraction/").json()["runs"]), 5)
