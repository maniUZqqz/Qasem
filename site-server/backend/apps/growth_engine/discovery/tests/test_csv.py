"""CSV upload -> check -> import job -> row report -> resolve duplicates."""
import csv
import io
import json
from datetime import timedelta
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.testing import NoNetworkMixin, TempMediaMixin, client_for, make_staff
from apps.growth_engine.discovery.models import DiscoveryJob, DiscoveryJobRow
from apps.growth_engine.discovery.services import csv_import, csv_mapping, csv_upload
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import LeadSource, SourceProvider

API = "/api/v1/growth/discovery"

SAMPLE = (
    "نام کسب‌وکار,وب‌سایت,اینستاگرام,تلفن,ایمیل,شهر,دسته,برچسب‌ها\n"
    "پوشاک آرمان,https://www.arman.ir/?utm_source=x,@arman_shop,۰۹۱۲۱۱۱۱۱۱۱ | 021-12345678,info@arman.ir,تهران,پوشاک,vip; گرم\n"
    "گل‌سرخ,golsorkh.com,,0912 222 2222,,شیراز,گل,\n"
    "بدون راه تماس معتبر,,,123,not-an-email,,,\n"
    ",,,,,,,\n"
    "تکراری آرمان,http://arman.ir,,,,اصفهان,,\n"
    "فقط نام,,,,,,,\n"
)


def upload(client, data, name="leads.csv"):
    return client.post(f"{API}/csv/upload/", {"file": SimpleUploadedFile(name, data, content_type="text/csv")}, format="multipart")


class UploadTests(TempMediaMixin, NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def test_upload_returns_preview_and_a_good_first_mapping(self):
        response = upload(self.client, SAMPLE.encode("utf-8-sig"))
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data["encoding"], data["delimiter"], data["total_rows"]), ("utf-8-sig", ",", 5))
        self.assertEqual(data["headers"][:3], ["نام کسب‌وکار", "وب‌سایت", "اینستاگرام"])
        self.assertEqual(data["sample_rows"][0]["row"], 2)
        self.assertEqual(data["sample_rows"][-1]["row"], 7)
        self.assertEqual(
            data["suggested_mapping"],
            {"نام کسب‌وکار": "business_name", "وب‌سایت": "website", "اینستاگرام": "instagram", "تلفن": "phone", "ایمیل": "email", "شهر": "city", "دسته": "category", "برچسب‌ها": "tags"},
        )
        self.assertTrue(data["upload_id"])
        self.assertEqual(Lead.objects.count(), 0, "uploading must not create leads")

    def test_encodings(self):
        text = "نام,شهر\nفروشگاه چاپی,گرگان\nپوشاک ژاله,تهران\n"
        for encoding in ["utf-8", "utf-8-sig", "cp1256", "utf-16"]:
            with self.subTest(encoding=encoding):
                # Excel's cp1256 has no Persian yeh/kaf: it writes the Arabic letters, like real files do
                data = text.replace("ی", "ي").replace("ک", "ك").encode(encoding) if encoding == "cp1256" else text.encode(encoding)
                response = upload(self.client, data)
                self.assertEqual(response.status_code, 201, response.content)
                first = response.json()["sample_rows"][0]["cells"][0]
                self.assertEqual(nz.normalize_text(first), "فروشگاه چاپی")

    def test_english_headers_and_semicolon_delimiter(self):
        response = upload(self.client, b"Business Name;Website;Mobile;E-mail;City\nShop;shop.ir;09121234567;a@shop.ir;Tehran\n")
        data = response.json()
        self.assertEqual(data["delimiter"], ";")
        self.assertEqual(
            data["suggested_mapping"], {"Business Name": "business_name", "Website": "website", "Mobile": "phone", "E-mail": "email", "City": "city"}
        )

    def test_rejections(self):
        self.assertEqual(upload(self.client, b"a,b\n1,2\n", name="leads.exe").status_code, 400)
        self.assertEqual(upload(self.client, b"").status_code, 400)
        self.assertEqual(upload(self.client, b"PK\x03\x04\x00\x00binary").status_code, 400)
        self.assertEqual(upload(self.client, b"only,a,header\n").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/csv/upload/", {}, format="multipart").status_code, 400)

    @override_settings(GROWTH_ENGINE={"CSV_MAX_BYTES": 200})
    def test_size_limit(self):
        response = upload(self.client, b"a,b\n" + b"x,y\n" * 200)
        self.assertEqual(response.status_code, 400)
        self.assertIn("مگابایت", response.json()["detail"])

    @override_settings(GROWTH_ENGINE={"CSV_MAX_ROWS": 5})
    def test_row_limit(self):
        response = upload(self.client, b"a\n" + b"1\n2\n3\n4\n5\n6\n")
        self.assertEqual(response.status_code, 400)
        self.assertIn("5", response.json()["detail"])

    def test_the_stored_name_is_random_and_a_hostile_file_name_is_harmless(self):
        response = upload(self.client, b"name\nx\n", name="../../etc/passwd\x00.csv")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["file_name"], "passwd.csv")
        self.assertRegex(response.json()["upload_id"], r"^[0-9a-f]{32}$")

    def test_another_users_upload_is_not_reachable(self):
        token = upload(self.client, b"name\nx\n").json()["upload_id"]
        other = client_for(make_staff("someone-else"))
        response = other.post(f"{API}/csv/import/", {"upload_id": token, "mapping": {"name": "business_name"}}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"{API}/csv/import/", {"upload_id": "../../x", "mapping": {"name": "business_name"}}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_stale_uploads_are_cleaned(self):
        old = "growth_engine/uploads/u1-" + "a" * 32 + ".csv"
        default_storage.save(old, ContentFile(b"x"))
        path = default_storage.path(old)
        import os

        stale = (timezone.now() - timedelta(days=3)).timestamp()
        os.utime(path, (stale, stale))
        self.assertGreaterEqual(csv_upload.cleanup_stale_uploads(), 1)
        self.assertFalse(default_storage.exists(old))


class MappingTests(NoNetworkMixin, TestCase):
    def test_validation(self):
        headers = ["a", "b", "c"]
        self.assertEqual(csv_mapping.validate_mapping({"a": "business_name", "b": ""}, headers), {"a": "business_name"})
        for bad in [{"a": "business_name", "b": "business_name"}, {"zzz": "website"}, {"a": "bogus"}, {"a": "city"}, {}]:
            with self.subTest(mapping=bad), self.assertRaises(csv_mapping.MappingError):
                csv_mapping.validate_mapping(bad, headers)
        # several columns may feed a multi field
        self.assertEqual(csv_mapping.validate_mapping({"a": "phone", "b": "phone"}, headers), {"a": "phone", "b": "phone"})

    def test_numbered_columns_join_the_same_multi_target(self):
        suggestion = csv_mapping.suggest_mapping(["name", "phone", "phone2", "تلفن 3", "email"])
        self.assertEqual((suggestion["phone"], suggestion["phone2"], suggestion["تلفن 3"]), ("phone", "phone", "phone"))

    def test_row_to_raw_collects_lists(self):
        raw = csv_mapping.row_to_raw(["n", "p1", "p2"], ["x", "0912", " 0935 "], {"n": "business_name", "p1": "phone", "p2": "phone"})
        self.assertEqual(raw, {"business_name": "x", "phone": ["0912", "0935"]})


class CheckTests(TempMediaMixin, NoNetworkMixin, TestCase):
    def test_dry_run_counts_row_errors_without_touching_the_database(self):
        client = client_for(make_staff())
        up = upload(client, SAMPLE.encode("utf-8")).json()
        response = client.post(f"{API}/csv/check/", {"upload_id": up["upload_id"], "mapping": up["suggested_mapping"], "default_country": "ایران"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["total_rows"], data["valid_rows"], data["error_rows"]), (5, 4, 1))
        self.assertEqual(data["errors"][0]["row"], 4)
        self.assertEqual(sorted(e["field"] for e in data["errors"][0]["errors"]), ["email", "phone"])
        first = data["sample"][0]["summary"]
        self.assertEqual((first["website"], first["phones"], first["country"]), ("https://arman.ir", ["09121111111", "02112345678"], "IR"))
        self.assertEqual(Lead.objects.count(), 0)
        bad = client.post(f"{API}/csv/check/", {"upload_id": up["upload_id"], "mapping": {"شهر": "city"}}, format="json")
        self.assertEqual(bad.status_code, 400)


class ImportJobTests(TempMediaMixin, NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def start(self, data=SAMPLE.encode("utf-8"), **extra):
        up = upload(self.client, data).json()
        payload = {"upload_id": up["upload_id"], "mapping": up["suggested_mapping"], "default_country": "IR", **extra}
        with self.captureOnCommitCallbacks(execute=True):  # the task is queued once the request commits
            response = self.client.post(f"{API}/csv/import/", payload, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()

    def job(self, job_id):
        return self.client.get(f"{API}/jobs/{job_id}/").json()

    def test_import_runs_in_the_background_and_reports_row_level_results(self):
        job = self.start(tags=["ورودی ۱"])
        self.assertEqual(job["status"], "queued")  # the response is the queued job; celery (eager in tests) already ran it
        done = self.job(job["id"])
        self.assertEqual(done["status"], "completed", done)
        self.assertEqual((done["total_items"], done["processed_items"], done["progress"]), (5, 5, 100))
        self.assertEqual((done["created_count"], done["duplicate_count"], done["error_count"]), (3, 1, 1))
        self.assertEqual(Lead.objects.count(), 3)
        arman = Lead.objects.get(website="https://arman.ir")
        self.assertEqual((arman.country, arman.origin, arman.city), ("IR", "csv_import", "تهران"))
        self.assertEqual(sorted(t.name for t in arman.tags.all()), ["vip", "ورودی ۱", "گرم"])
        self.assertEqual(sorted(arman.contacts.filter(kind="phone").values_list("value", flat=True)), ["02112345678", "09121111111"])
        self.assertEqual(arman.provenance["website"]["source"], "csv:leads.csv:2")
        source = LeadSource.objects.get(lead=arman)
        self.assertEqual((source.provider, source.source_ref, source.job_id), ("csv_import", "csv:leads.csv:2", job["id"]))
        self.assertEqual(source.raw_data["نام کسب‌وکار"], "پوشاک آرمان")

        rows = self.client.get(f"{API}/jobs/{job['id']}/rows/").json()["results"]
        self.assertEqual([(r["row_number"], r["status"]) for r in rows], [(4, "error"), (6, "duplicate")])
        self.assertEqual(sorted(e["field"] for e in rows[0]["errors"]), ["email", "phone"])
        self.assertEqual(rows[1]["matches"][0]["lead_id"], arman.pk)
        only_errors = self.client.get(f"{API}/jobs/{job['id']}/rows/?status=error").json()
        self.assertEqual(only_errors["count"], 1)

    def test_the_uploaded_file_is_deleted_when_the_job_ends(self):
        up = upload(self.client, SAMPLE.encode("utf-8")).json()
        self.assertEqual(len(default_storage.listdir(csv_upload.UPLOAD_DIR)[1]), 2)  # the data file and its sidecar
        payload = {"upload_id": up["upload_id"], "mapping": up["suggested_mapping"]}
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"{API}/csv/import/", payload, format="json")
        self.assertEqual(default_storage.listdir(csv_upload.UPLOAD_DIR)[1], [])
        self.assertEqual(DiscoveryJob.objects.get().stored_name, "")

    def test_error_report_csv_can_be_fixed_and_reimported(self):
        job = self.start()
        response = self.client.get(f"{API}/jobs/{job['id']}/errors.csv")
        body = b"".join(response.streaming_content)
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
        self.assertEqual(rows[0][-2:], ["ردیف در فایل", "خطا"])
        self.assertEqual(rows[1][-2], "4")
        self.assertIn("تلفن", rows[1][-1])
        self.assertEqual(rows[1][0], "بدون راه تماس معتبر")

    def test_duplicates_are_parked_for_a_decision_never_auto_merged(self):
        job = self.start()
        arman = Lead.objects.get(website="https://arman.ir")
        self.assertEqual(arman.city, "تهران")  # the duplicate row said Isfahan: not applied
        self.assertEqual(LeadSource.objects.filter(lead=arman).count(), 1)

    def test_resolve_merge_then_skip(self):
        job = self.start()
        dup = DiscoveryJobRow.objects.get(job_id=job["id"], status="duplicate")
        arman = Lead.objects.get(website="https://arman.ir")
        preview = self.client.get(f"{API}/jobs/{job['id']}/rows/?status=duplicate&with_merge_preview=1").json()["results"][0]
        self.assertEqual({f["field"]: f["state"] for f in preview["merge_preview"]["fields"]}["city"], "conflict")
        response = self.client.post(f"{API}/jobs/{job['id']}/resolve/", {"action": "merge", "rows": [dup.pk]}, format="json")
        self.assertEqual(response.json(), {"resolved": 1, "merged": 1, "skipped": 0, "created": 0, "remaining": 0})
        arman.refresh_from_db()
        self.assertEqual(arman.city, "تهران")
        self.assertEqual(LeadSource.objects.filter(lead=arman).count(), 2)
        self.assertEqual(self.job(job["id"])["merged_count"], 1)
        self.assertEqual(self.job(job["id"])["duplicate_count"], 0)
        dup.refresh_from_db()
        self.assertEqual((dup.status, dup.resolved_by_id), ("merged", self.staff.pk))

    def test_resolve_skip_and_overwrite(self):
        job = self.start()
        dup = DiscoveryJobRow.objects.get(job_id=job["id"], status="duplicate")
        arman = Lead.objects.get(website="https://arman.ir")
        self.client.post(f"{API}/jobs/{job['id']}/resolve/", {"action": "merge", "all": True, "overwrite_fields": ["city"]}, format="json")
        arman.refresh_from_db()
        self.assertEqual(arman.city, "اصفهان")
        # a second call finds nothing pending
        again = self.client.post(f"{API}/jobs/{job['id']}/resolve/", {"action": "skip", "all": True}, format="json").json()
        self.assertEqual(again["resolved"], 0)

    def test_skip_all(self):
        job = self.start()
        result = self.client.post(f"{API}/jobs/{job['id']}/resolve/", {"action": "skip", "all": True}, format="json").json()
        self.assertEqual((result["skipped"], result["remaining"]), (1, 0))
        self.assertEqual(self.job(job["id"])["skipped_count"], 1)
        self.assertEqual(Lead.objects.count(), 3)

    def test_rows_of_the_same_file_that_repeat_each_other_are_duplicates_too(self):
        job = self.start(b"name,website\nA,a.ir\nB,https://www.a.ir/x\nC,c.ir\n")
        done = self.job(job["id"])
        self.assertEqual((done["created_count"], done["duplicate_count"]), (2, 1))

    def test_cancel_before_it_starts(self):
        up = upload(self.client, SAMPLE.encode()).json()
        job = csv_import.create_import_job(self.staff, up["upload_id"], up["suggested_mapping"])
        response = self.client.post(f"{API}/jobs/{job.pk}/cancel/")
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(csv_import.run_import(job.pk), "cancelled")
        self.assertEqual(Lead.objects.count(), 0)

    def test_cancel_while_running_keeps_the_rows_already_done(self):
        up = upload(self.client, SAMPLE.encode()).json()
        job = csv_import.create_import_job(self.staff, up["upload_id"], up["suggested_mapping"])
        calls = {"n": 0}
        real = csv_import._process_row

        def cancel_after_two(*args, **kwargs):
            real(*args, **kwargs)
            calls["n"] += 1
            if calls["n"] == 2:
                DiscoveryJob.objects.filter(pk=job.pk).update(cancel_requested=True)

        with mock.patch.object(csv_import, "CANCEL_POLL_EVERY", 1), mock.patch.object(csv_import, "_process_row", cancel_after_two):
            self.assertEqual(csv_import.run_import(job.pk), "cancelled")
        job.refresh_from_db()
        self.assertEqual((job.processed_items, job.status, job.stored_name), (2, "cancelled", ""))
        self.assertEqual(Lead.objects.count(), 2)

    def test_resume_continues_after_the_cursor_without_duplicating_work(self):
        up = upload(self.client, SAMPLE.encode()).json()
        job = csv_import.create_import_job(self.staff, up["upload_id"], up["suggested_mapping"])
        real = csv_import._process_row
        calls = {"n": 0}

        class WorkerKilled(BaseException):
            pass

        def die_on_third(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise WorkerKilled()
            real(*args, **kwargs)

        with mock.patch.object(csv_import, "_process_row", die_on_third), self.assertRaises(WorkerKilled):
            csv_import.run_import(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.processed_items, job.cursor), ("running", 2, 3))
        self.assertEqual(Lead.objects.count(), 2)
        # nothing happens until it looks stalled
        self.assertFalse(csv_import.prepare_resume(job))
        DiscoveryJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(minutes=10))
        job.refresh_from_db()
        self.assertTrue(job.is_stalled)
        self.assertTrue(self.job(job.pk)["can_resume"])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(f"{API}/jobs/{job.pk}/resume/").status_code, 202)
        done = self.job(job.pk)
        self.assertEqual((done["status"], done["processed_items"], done["created_count"], done["error_count"], done["duplicate_count"]), ("completed", 5, 3, 1, 1))
        self.assertEqual(Lead.objects.count(), 3)

    def test_missing_file_fails_the_job_clearly(self):
        up = upload(self.client, SAMPLE.encode()).json()
        job = csv_import.create_import_job(self.staff, up["upload_id"], up["suggested_mapping"])
        default_storage.delete(job.stored_name)
        self.assertEqual(csv_import.run_import(job.pk), "failed")
        job.refresh_from_db()
        self.assertIn("آپلود", job.error)
        self.assertFalse(csv_import.prepare_resume(job), "a failed job whose file is gone cannot resume")

    def test_infrastructure_failure_marks_failed_and_is_resumable(self):
        up = upload(self.client, SAMPLE.encode()).json()
        job = csv_import.create_import_job(self.staff, up["upload_id"], up["suggested_mapping"])
        with mock.patch.object(csv_import, "_process_row", side_effect=RuntimeError("db gone")):
            self.assertEqual(csv_import.run_import(job.pk), "failed")
        job.refresh_from_db()
        self.assertIn("RuntimeError", job.error)
        self.assertNotIn("db gone", job.error)
        self.assertTrue(csv_import.prepare_resume(job))
        self.assertEqual(csv_import.run_import(job.pk), "completed")
        self.assertEqual(Lead.objects.count(), 3)

    def test_one_broken_row_does_not_stop_the_file(self):
        real = intake.create_from_draft
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("boom")
            return real(*args, **kwargs)

        with mock.patch.object(csv_import, "create_from_draft", flaky):
            job = self.start()
        done = self.job(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual((done["created_count"], done["error_count"]), (2, 2))
        broken = DiscoveryJobRow.objects.get(job_id=job["id"], row_number=3)
        self.assertEqual(broken.errors[0]["code"], "internal_error")

    def test_a_sqlite_lock_conflict_is_retried_and_never_recorded_as_a_bad_row(self):
        from django.db.utils import OperationalError

        real = intake.create_from_draft
        calls = {"n": 0}

        def locked_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError("database is locked")
            return real(*args, **kwargs)

        with mock.patch.object(csv_import, "create_from_draft", locked_once), mock.patch("apps.growth_engine.core.dbretry.time.sleep"):
            job = self.start()
        done = self.job(job["id"])
        self.assertEqual((done["status"], done["created_count"], done["error_count"]), ("completed", 3, 1))  # the real bad row only
        self.assertFalse(DiscoveryJobRow.objects.filter(job_id=job["id"], errors__0__code="internal_error").exists())

    def test_job_list_and_unknown_job(self):
        self.start()
        self.assertEqual(self.client.get(f"{API}/jobs/").json()["count"], 1)
        self.assertEqual(self.client.get(f"{API}/jobs/9999/").status_code, 404)

    def test_finished_jobs_cannot_be_resumed_or_cancelled(self):
        job = self.start()
        self.assertEqual(self.client.post(f"{API}/jobs/{job['id']}/resume/").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/jobs/{job['id']}/cancel/").json()["status"], "completed")

    def test_export_then_import_round_trip(self):
        job = self.start()
        exported = b"".join(self.client.get("/api/v1/growth/leads/export/").streaming_content)
        up = upload(self.client, exported, name="export.csv").json()
        check = self.client.post(f"{API}/csv/check/", {"upload_id": up["upload_id"], "mapping": up["suggested_mapping"]}, format="json").json()
        self.assertEqual((check["total_rows"], check["error_rows"]), (3, 0))
        self.assertEqual(job["id"], 1)
