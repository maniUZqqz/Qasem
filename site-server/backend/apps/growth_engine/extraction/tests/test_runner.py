"""Extraction jobs end to end (one lead, selected leads, a whole CSV import), skip rules, cancel, resume, stalled."""
import json
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.growth_engine.core.testing import NoNetworkMixin, TempMediaMixin, client_for, make_staff
from apps.growth_engine.discovery.models import DiscoveryJob
from apps.growth_engine.extraction.models import ExtractionJob, ExtractionPageLog, ExtractionRun
from apps.growth_engine.extraction.services import crawler, runner
from apps.growth_engine.leads.choices import ActivityKind
from apps.growth_engine.leads.models import ContactPoint, Lead, LeadActivity
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import LeadSource, SourceProvider

from .helpers import Site, add_mini_shop, add_shop, golsorkh_site, make_fetcher

API = "/api/v1/growth"


def make_lead(**raw):
    raw.setdefault("business_name", "فروشگاه")
    draft, errors = build_draft(raw)
    assert not errors, errors
    return intake.create_from_draft(draft, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


class RunnerCase(TempMediaMixin, NoNetworkMixin, TestCase):
    """The fetcher the runner builds is replaced by one wired to a fake web (``self.site``)."""

    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        self.site = golsorkh_site()
        patcher = mock.patch.object(runner, "make_fetcher", lambda: make_fetcher(self.site)[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, payload):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{API}/extraction/jobs/", payload, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()

    def job(self, job_id):
        return self.client.get(f"{API}/extraction/jobs/{job_id}/").json()


class SingleLeadJobTests(RunnerCase):
    def test_one_lead_end_to_end(self):
        lead = make_lead(business_name="", website="https://golsorkh.ir/")
        queued = self.start({"lead_ids": [lead.pk]})
        self.assertEqual((queued["scope"], queued["total_items"]), ("single", 1))
        done = self.job(queued["id"])
        self.assertEqual((done["status"], done["progress"], done["processed_items"]), ("completed", 100, 1))
        self.assertEqual((done["runs_done"], done["runs_failed"], done["runs_skipped"], done["pages_fetched"]), (1, 0, 0, 4))
        self.assertGreater(done["contacts_added"], 8)

        run = ExtractionRun.objects.get(lead=lead)
        self.assertEqual((run.status, run.reason, run.robots_state, run.pages_fetched), ("done", "", "ok", 4))
        lead.refresh_from_db()
        # contacts, each with its source page, evidence, confidence and the run as provenance
        phone = lead.contacts.get(kind="phone", normalized="02112345678")
        self.assertEqual((phone.source_ref, phone.source_url, phone.confidence), (f"extract:{run.pk}", "https://golsorkh.ir", 90))
        form = lead.contacts.get(kind="contact_form", normalized="https://golsorkh.ir/contact-us")
        self.assertEqual((form.label, form.confidence, form.source_url), ("فرم تماس", 85, "https://golsorkh.ir/contact-us"))
        self.assertTrue(lead.contacts.filter(kind="instagram", normalized="golsorkh.shop").exists())
        self.assertEqual(lead.instagram_url, "https://www.instagram.com/golsorkh.shop/")
        # empty lead fields were filled; the website itself is untouched
        self.assertEqual((lead.business_name, lead.city), ("فروشگاه گل‌سرخ", "تهران"))
        self.assertEqual(lead.provenance["business_name"]["source"], f"extract:{run.pk}")
        self.assertEqual(lead.website, "https://golsorkh.ir")
        self.assertIn("خیابان ولیعصر", lead.profile.address)
        self.assertEqual(lead.profile.language, "fa")
        # source, history, page log, findings
        self.assertEqual(LeadSource.objects.filter(lead=lead, provider=SourceProvider.CONTACT_EXTRACTION).count(), 1)
        activity = LeadActivity.objects.get(lead=lead, kind=ActivityKind.EXTRACTION)
        self.assertEqual((activity.source_ref, activity.actor_id, activity.data["job_id"]), (f"extract:{run.pk}", self.staff.pk, queued["id"]))
        self.assertEqual(list(run.pages.values_list("kind", flat=True)), ["robots", "home", "contact", "about", "support"])
        self.assertTrue(all(f["applied"] or f["reason"] in ("already_known", "kept_existing", "owned_by_other_lead", "invalid") for f in run.findings))
        self.assertEqual(self.site.methods(), {"GET"})

    def test_the_detail_and_the_lead_endpoint_show_runs_findings_and_the_page_log(self):
        lead = make_lead(business_name="", website="golsorkh.ir")
        job_id = self.start({"lead_ids": [lead.pk]})["id"]
        detail = self.job(job_id)
        self.assertEqual([(r["lead_id"], r["status"], r["reason"]) for r in detail["runs"]], [(lead.pk, "done", "")])
        data = self.client.get(f"{API}/leads/{lead.pk}/extraction/").json()
        run = data["runs"][0]
        self.assertEqual((run["job_id"], run["status"], run["status_label"], run["robots_state"], run["pages_fetched"]), (job_id, "done", "انجام شد", "ok", 4))
        finding = next(f for f in run["findings"] if f["field"] == "phone" and f["value"] == "02112345678")
        self.assertEqual((finding["source_url"], finding["evidence"], finding["confidence"], finding["applied"], finding["reason"]), ("https://golsorkh.ir", "لینک tel:", 90, True, "added"))
        self.assertEqual([p["kind"] for p in run["pages"]], ["robots", "home", "contact", "about", "support"])
        self.assertEqual(run["pages"][1]["outcome_label"], "دریافت شد")
        self.assertEqual(run["pages"][0]["outcome_label"], "robots.txt خوانده شد")

    def test_a_second_pass_never_duplicates_a_contact(self):
        lead = make_lead(business_name="", website="golsorkh.ir")
        self.start({"lead_ids": [lead.pk]})
        count = ContactPoint.objects.filter(lead=lead).count()
        self.start({"lead_ids": [lead.pk], "force": True})
        self.assertEqual(ContactPoint.objects.filter(lead=lead).count(), count)
        second = ExtractionRun.objects.filter(lead=lead).order_by("-id").first()
        self.assertEqual(second.contacts_added, 0)
        self.assertTrue(all(not f["applied"] for f in second.findings))
        pairs = list(ContactPoint.objects.filter(lead=lead).values_list("kind", "normalized"))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_a_robots_refusal_is_a_failed_run_with_the_log_and_nothing_fetched(self):
        self.site = golsorkh_site(robots=False).robots("golsorkh.ir", "User-agent: *\nDisallow: /\n")
        lead = make_lead(website="golsorkh.ir")
        job_id = self.start({"lead_ids": [lead.pk]})["id"]
        done = self.job(job_id)
        self.assertEqual((done["status"], done["runs_done"], done["runs_failed"], done["contacts_added"]), ("completed", 0, 1, 0))
        run = ExtractionRun.objects.get(lead=lead)
        self.assertEqual((run.status, run.reason, run.reason_label), ("failed", "robots_blocked", "robots.txt سایت اجازه نداد"))
        self.assertEqual([(p.kind, p.outcome) for p in run.pages.all()], [("robots", "ok"), ("home", "robots_blocked")])
        self.assertEqual(self.site.page_paths(), [])
        activity = LeadActivity.objects.get(lead=lead, kind=ActivityKind.EXTRACTION)
        self.assertIn("انجام نشد", activity.summary)
        self.assertFalse(ContactPoint.objects.filter(lead=lead, source_ref__startswith="extract:").exists())

    def test_a_timed_out_site_is_a_failed_run_not_a_crashed_job(self):
        import httpx

        self.site = Site().robots("golsorkh.ir").add("golsorkh.ir", "/", error=httpx.ReadTimeout("slow"))
        lead = make_lead(website="golsorkh.ir")
        done = self.job(self.start({"lead_ids": [lead.pk]})["id"])
        self.assertEqual((done["status"], done["runs_failed"]), ("completed", 1))
        run = ExtractionRun.objects.get(lead=lead)
        self.assertEqual((run.reason, [p.outcome for p in run.pages.all()]), ("fetch_failed", ["ok", "timeout"]))


class SelectedLeadsJobTests(RunnerCase):
    def setUp(self):
        super().setUp()
        self.leads = []
        for n in range(1, 4):
            host = f"shop{n}.ir"
            add_mini_shop(self.site, host, n)
            self.leads.append(make_lead(business_name=f"فروشگاه {n}", website=host))

    def test_every_selected_lead_is_processed_in_order(self):
        queued = self.start({"lead_ids": [lead.pk for lead in self.leads]})
        self.assertEqual((queued["scope"], queued["total_items"]), ("selected", 3))
        done = self.job(queued["id"])
        self.assertEqual((done["status"], done["processed_items"], done["runs_done"], done["contacts_added"]), ("completed", 3, 3, 9))
        self.assertEqual(ExtractionJob.objects.get(pk=queued["id"]).cursor, 3)
        for n, lead in enumerate(self.leads, 1):
            phones = list(lead.contacts.filter(kind="phone").values_list("value", flat=True))
            self.assertEqual(phones, [f"0912000{n:04d}"])
        self.assertEqual([r["lead_id"] for r in self.job(queued["id"])["runs"]], [lead.pk for lead in self.leads])

    def test_skip_rules_no_website_recent_and_force(self):
        no_site = make_lead(business_name="بدون سایت", phone="09129998877")
        leads = [no_site, *self.leads]
        first = self.job(self.start({"lead_ids": [lead.pk for lead in leads]})["id"])
        self.assertEqual((first["runs_done"], first["runs_skipped"]), (3, 1))
        skipped = ExtractionRun.objects.get(lead=no_site)
        self.assertEqual((skipped.status, skipped.reason, skipped.reason_label), ("skipped", "no_website", "لید وب‌سایت ندارد"))
        # a second job right away: the three read ones are "recent", only the website-less one is left (and skipped again)
        fetched_before = len(self.site.requests)
        response = self.client.post(f"{API}/extraction/jobs/", {"lead_ids": [lead.pk for lead in self.leads]}, format="json")
        self.assertEqual(response.status_code, 400)  # nothing would be read at all
        self.assertIn("به‌تازگی", response.json()["detail"])
        self.assertEqual(len(self.site.requests), fetched_before)
        mixed = self.job(self.start({"lead_ids": [lead.pk for lead in leads], "force": True})["id"])
        self.assertEqual((mixed["runs_done"], mixed["runs_skipped"]), (3, 1))
        # without force a job that has something new to read skips the recent ones visibly
        fresh = make_lead(business_name="تازه", website="shop9.ir")
        add_mini_shop(self.site, "shop9.ir", 9)
        third = self.job(self.start({"lead_ids": [self.leads[0].pk, fresh.pk]})["id"])
        self.assertEqual((third["runs_done"], third["runs_skipped"]), (1, 1))
        recent = ExtractionRun.objects.filter(lead=self.leads[0]).order_by("-id").first()
        self.assertEqual((recent.status, recent.reason), ("skipped", "recent"))

    def test_an_old_extraction_is_not_recent(self):
        self.start({"lead_ids": [self.leads[0].pk]})
        ExtractionRun.objects.update(finished_at=timezone.now() - timedelta(days=45))
        done = self.job(self.start({"lead_ids": [self.leads[0].pk]})["id"])
        self.assertEqual((done["runs_done"], done["runs_skipped"]), (1, 0))

    def test_a_failed_earlier_run_does_not_make_a_lead_recent(self):
        ExtractionRun.objects.create(lead=self.leads[0], status=ExtractionRun.Status.FAILED, finished_at=timezone.now())
        done = self.job(self.start({"lead_ids": [self.leads[0].pk]})["id"])
        self.assertEqual(done["runs_done"], 1)

    def test_a_lead_deleted_after_the_job_was_created_is_skipped(self):
        jobs = runner.create_jobs(self.staff, lead_ids=[lead.pk for lead in self.leads])
        self.leads[1].delete()
        self.assertEqual(runner.run_extraction(jobs[0].pk), "completed")
        job = ExtractionJob.objects.get(pk=jobs[0].pk)
        self.assertEqual((job.processed_items, job.runs_done, job.runs_skipped), (3, 2, 1))

    def test_one_broken_lead_does_not_stop_the_job_and_leaves_nothing_half_written(self):
        real = runner.apply.apply_findings
        calls = {"n": 0}

        def flaky(lead, run, findings, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                # write something, then blow up: the transaction must take it back
                ContactPoint.objects.create(lead=lead, kind="phone", value="09350000000", normalized="09350000000", source_ref="x")
                raise ValueError("boom")
            return real(lead, run, findings, **kwargs)

        with mock.patch.object(runner.apply, "apply_findings", flaky):
            done = self.job(self.start({"lead_ids": [lead.pk for lead in self.leads]})["id"])
        self.assertEqual((done["status"], done["runs_done"], done["runs_failed"], done["processed_items"]), ("completed", 2, 1, 3))
        broken = ExtractionRun.objects.get(lead=self.leads[1])
        self.assertEqual((broken.status, broken.reason), ("failed", "internal_error"))
        self.assertFalse(ContactPoint.objects.filter(lead=self.leads[1], kind="phone").exists())
        self.assertFalse(ExtractionPageLog.objects.filter(run=broken).exists())

    def test_chunking_and_limits(self):
        with override_settings(GROWTH_ENGINE={"EXTRACT_MAX_LEADS_PER_JOB": 2}):
            response = self.client.post(f"{API}/extraction/jobs/", {"lead_ids": [lead.pk for lead in self.leads]}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("حداکثر 2", response.json()["detail"])


class CancelResumeStalledTests(RunnerCase):
    def setUp(self):
        super().setUp()
        self.leads = []
        for n in range(1, 5):
            host = f"shop{n}.ir"
            add_mini_shop(self.site, host, n)
            self.leads.append(make_lead(business_name=f"فروشگاه {n}", website=host))

    def create(self):
        return runner.create_jobs(self.staff, lead_ids=[lead.pk for lead in self.leads])[0]

    def test_cancel_before_it_starts(self):
        job = self.create()
        response = self.client.post(f"{API}/extraction/jobs/{job.pk}/cancel/")
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(runner.run_extraction(job.pk), "cancelled")
        self.assertEqual(self.site.requests, [])
        self.assertFalse(ContactPoint.objects.filter(source_ref__startswith="extract:").exists())

    def test_cancel_while_running_keeps_the_leads_already_read(self):
        job = self.create()
        real = runner._process_lead
        seen = {"n": 0}

        def cancel_after_two(*args, **kwargs):
            outcome = real(*args, **kwargs)
            seen["n"] += 1
            if seen["n"] == 2:
                ExtractionJob.objects.filter(pk=job.pk).update(cancel_requested=True)
            return outcome

        with mock.patch.object(runner, "_process_lead", cancel_after_two):
            self.assertEqual(runner.run_extraction(job.pk), "cancelled")
        job.refresh_from_db()
        self.assertEqual((job.processed_items, job.runs_done, job.status), (2, 2, "cancelled"))
        self.assertEqual(ExtractionRun.objects.filter(status="queued").count(), 2)
        self.assertGreater(ContactPoint.objects.filter(lead=self.leads[0], source_ref__startswith="extract:").count(), 0)
        self.assertEqual(ContactPoint.objects.filter(lead=self.leads[3], source_ref__startswith="extract:").count(), 0)

    def test_a_cancel_in_the_middle_of_a_crawl_discards_that_leads_partial_result(self):
        job = self.create()
        calls = {"n": 0}
        real = crawler.crawl_site

        def crawl_then_cancel(website, fetcher, **kwargs):
            calls["n"] += 1
            result = real(website, fetcher, **kwargs)
            if calls["n"] == 3:
                ExtractionJob.objects.filter(pk=job.pk).update(cancel_requested=True)
            return result

        with mock.patch.object(crawler, "crawl_site", crawl_then_cancel):
            self.assertEqual(runner.run_extraction(job.pk), "cancelled")
        job.refresh_from_db()
        self.assertEqual(job.processed_items, 2)
        third = ExtractionRun.objects.get(job=job, lead=self.leads[2])
        self.assertEqual(third.status, "queued")
        self.assertFalse(ContactPoint.objects.filter(lead=self.leads[2], source_ref__startswith="extract:").exists())
        self.assertFalse(ExtractionPageLog.objects.filter(run=third).exists())

    def test_resume_continues_after_the_cursor_without_reading_anything_twice(self):
        job = self.create()
        real = runner._process_lead
        calls = {"n": 0}

        class WorkerKilled(BaseException):
            pass

        def die_on_third(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise WorkerKilled()
            return real(*args, **kwargs)

        with mock.patch.object(runner, "_process_lead", die_on_third), self.assertRaises(WorkerKilled):
            runner.run_extraction(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.processed_items, job.cursor, job.runs_done), ("running", 2, 2, 2))
        self.assertFalse(runner.prepare_resume(job), "still looks alive")
        requests_before = len(self.site.requests)
        ExtractionJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=10))
        job.refresh_from_db()
        self.assertTrue(job.is_stalled)
        self.assertTrue(self.job(job.pk)["stalled"])
        self.assertTrue(self.job(job.pk)["can_resume"])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(f"{API}/extraction/jobs/{job.pk}/resume/").status_code, 202)
        done = self.job(job.pk)
        self.assertEqual((done["status"], done["processed_items"], done["runs_done"], done["contacts_added"]), ("completed", 4, 4, 12))
        hosts_fetched = {r.headers["host"] for r in self.site.requests[requests_before:]}
        self.assertEqual(hosts_fetched, {"shop3.ir", "shop4.ir"}, "the two leads before the cursor were not read again")

    def test_an_infrastructure_failure_marks_the_job_failed_and_it_can_be_resumed(self):
        job = self.create()
        with mock.patch.object(runner, "_process_lead", side_effect=RuntimeError("db gone")):
            self.assertEqual(runner.run_extraction(job.pk), "failed")
        job.refresh_from_db()
        self.assertIn("RuntimeError", job.error)
        self.assertNotIn("db gone", job.error)
        self.assertTrue(self.job(job.pk)["can_resume"])
        self.assertTrue(runner.prepare_resume(job))
        self.assertEqual(runner.run_extraction(job.pk), "completed")
        self.assertEqual(ExtractionJob.objects.get(pk=job.pk).runs_done, 4)

    def test_finished_jobs_cannot_be_resumed_or_cancelled_into_something_else(self):
        job = self.create()
        runner.run_extraction(job.pk)
        self.assertEqual(self.client.post(f"{API}/extraction/jobs/{job.pk}/resume/").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/extraction/jobs/{job.pk}/cancel/").json()["status"], "completed")
        self.assertEqual(runner.run_extraction(job.pk), "completed")  # a duplicate task does no harm
        self.assertEqual(ExtractionJob.objects.get(pk=job.pk).runs_done, 4)

    def test_a_job_that_is_not_stalled_cannot_be_resumed(self):
        job = self.create()
        ExtractionJob.objects.filter(pk=job.pk).update(status="running", heartbeat_at=timezone.now())
        self.assertEqual(self.client.post(f"{API}/extraction/jobs/{job.pk}/resume/").status_code, 400)


class CsvImportExtractionTests(RunnerCase):
    """"Extract after import": a whole CSV import becomes extraction jobs through the discovery signal."""

    CSV = (
        "نام,وب‌سایت\n"
        "فروشگاه یک,shop1.ir\n"
        "فروشگاه دو,shop2.ir\n"
        "فقط نام,\n"
    )

    def setUp(self):
        super().setUp()
        add_mini_shop(self.site, "shop1.ir", 1)
        add_mini_shop(self.site, "shop2.ir", 2)

    def import_csv(self, extract_after, data=None):
        up = self.client.post(
            f"{API}/discovery/csv/upload/", {"file": SimpleUploadedFile("leads.csv", (data or self.CSV).encode("utf-8"), content_type="text/csv")}, format="multipart"
        ).json()
        payload = {"upload_id": up["upload_id"], "mapping": up["suggested_mapping"], "extract_after": extract_after}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{API}/discovery/csv/import/", payload, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()["id"]

    def test_extract_after_reads_the_websites_of_the_imported_leads(self):
        import_id = self.import_csv(True)
        self.assertEqual(DiscoveryJob.objects.get(pk=import_id).status, "completed")
        job = ExtractionJob.objects.get()
        self.assertEqual((job.scope, job.discovery_job_id, job.status, job.total_items, job.runs_done), ("csv_import", import_id, "completed", 2, 2))
        self.assertEqual(job.created_by_id, self.staff.pk)
        for n in (1, 2):
            lead = Lead.objects.get(website=f"https://shop{n}.ir")
            self.assertEqual(lead.contacts.get(kind="phone").value, f"0912000{n:04d}")
            self.assertEqual(lead.contacts.get(kind="email").value, f"shop{n}@shop{n}.ir")
        self.assertFalse(ExtractionRun.objects.filter(lead__business_name="فقط نام").exists())

    def test_without_extract_after_nothing_is_read(self):
        self.import_csv(False)
        self.assertEqual(ExtractionJob.objects.count(), 0)
        self.assertEqual(self.site.requests, [])

    def test_a_failed_or_cancelled_import_starts_no_extraction(self):
        from apps.growth_engine.discovery.signals import discovery_job_finished

        job = DiscoveryJob.objects.create(file_name="x.csv", status="failed", params={"extract_after": True})
        with self.captureOnCommitCallbacks(execute=True):
            discovery_job_finished.send(sender=DiscoveryJob, job=job)
        self.assertEqual(ExtractionJob.objects.count(), 0)

    def test_an_import_without_any_website_is_not_an_error_and_starts_nothing(self):
        self.import_csv(True, "نام,تلفن\nفقط نام,09121112233\n")
        self.assertEqual(ExtractionJob.objects.count(), 0)

    def test_a_problem_in_the_receiver_never_breaks_the_import(self):
        with mock.patch.object(runner, "create_jobs", side_effect=RuntimeError("boom")):
            import_id = self.import_csv(True)
        self.assertEqual(DiscoveryJob.objects.get(pk=import_id).status, "completed")
        self.assertEqual(Lead.objects.count(), 3)

    def test_the_csv_api_path_and_chunking_of_big_imports(self):
        import_id = self.import_csv(False)
        with override_settings(GROWTH_ENGINE={"EXTRACT_MAX_LEADS_PER_JOB": 1}):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"{API}/extraction/jobs/", {"discovery_job_id": import_id}, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual((body["scope"], body["discovery_job_id"], len(body["extra_job_ids"])), ("csv_import", import_id, 1))
        jobs = ExtractionJob.objects.order_by("id")
        self.assertEqual([(j.total_items, j.status, j.runs_done) for j in jobs], [(1, "completed", 1), (1, "completed", 1)])


class DashboardBlockTests(RunnerCase):
    def test_the_dashboard_block_is_counted_from_the_database(self):
        empty = self.client.get(f"{API}/dashboard/").json()["extra"]["extraction"]
        self.assertEqual(empty, {"leads_extracted": 0, "runs_total": 0, "contacts_found": 0, "last_job": None})
        lead = make_lead(business_name="", website="golsorkh.ir")
        failing = make_lead(business_name="ب", website="down.ir")
        self.site.add("down.ir", "/", "x", status=404)
        job_id = self.start({"lead_ids": [lead.pk, failing.pk]})["id"]
        block = self.client.get(f"{API}/dashboard/").json()["extra"]["extraction"]
        self.assertEqual((block["leads_extracted"], block["runs_total"]), (1, 2))
        self.assertEqual(block["contacts_found"], ContactPoint.objects.filter(source_ref__startswith="extract:").count())
        self.assertGreater(block["contacts_found"], 0)
        self.assertEqual((block["last_job"]["id"], block["last_job"]["status"], block["last_job"]["total_items"]), (job_id, "completed", 2))
        json.dumps(block, default=str)
