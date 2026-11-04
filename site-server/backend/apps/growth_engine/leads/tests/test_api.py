import csv
import io
from datetime import timedelta

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.leads.models import Lead, LeadActivity
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import SourceProvider

API = "/api/v1/growth"


def make_lead(**raw):
    raw.setdefault("business_name", "فروشگاه")
    d, errors = build_draft(raw)
    assert not errors, errors
    return intake.create_from_draft(d, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


class PermissionTests(NoNetworkMixin, TestCase):
    """Every endpoint is for staff only: anonymous -> 401, ordinary user -> 403."""

    def setUp(self):
        super().setUp()
        self.lead = make_lead(phone="09121234567")
        self.note = self.lead.notes.create(body="x")
        self.contact = self.lead.contacts.first()
        self.endpoints = [
            ("get", "/meta/"), ("get", "/dashboard/"), ("get", "/leads/"), ("get", f"/leads/{self.lead.pk}/"),
            ("patch", f"/leads/{self.lead.pk}/"), ("delete", f"/leads/{self.lead.pk}/?confirm=1"),
            ("get", f"/leads/{self.lead.pk}/activity/"), ("get", f"/leads/{self.lead.pk}/notes/"),
            ("post", f"/leads/{self.lead.pk}/notes/"), ("patch", f"/leads/{self.lead.pk}/notes/{self.note.pk}/"),
            ("delete", f"/leads/{self.lead.pk}/notes/{self.note.pk}/"), ("post", f"/leads/{self.lead.pk}/contacts/"),
            ("patch", f"/leads/{self.lead.pk}/contacts/{self.contact.pk}/"), ("delete", f"/leads/{self.lead.pk}/contacts/{self.contact.pk}/"),
            ("post", "/leads/bulk/"), ("get", "/leads/export/"), ("get", "/tags/"),
            ("post", "/discovery/manual/check/"), ("post", "/discovery/manual/"), ("post", "/discovery/csv/upload/"),
            ("post", "/discovery/csv/check/"), ("post", "/discovery/csv/import/"), ("get", "/discovery/jobs/"),
            ("get", "/discovery/jobs/1/"), ("get", "/discovery/jobs/1/rows/"), ("get", "/discovery/jobs/1/errors.csv"),
            ("post", "/discovery/jobs/1/cancel/"), ("post", "/discovery/jobs/1/resume/"), ("post", "/discovery/jobs/1/resolve/"),
        ]

    def test_anonymous_is_rejected_everywhere(self):
        client = client_for()
        for method, path in self.endpoints:
            with self.subTest(path=path):
                self.assertIn(getattr(client, method)(API + path).status_code, (401, 403))
        self.assertEqual(Lead.objects.count(), 1)

    def test_ordinary_user_is_forbidden_everywhere(self):
        client = client_for(make_plain_user())
        for method, path in self.endpoints:
            with self.subTest(path=path):
                self.assertEqual(getattr(client, method)(API + path).status_code, 403)
        self.assertEqual(Lead.objects.count(), 1)

    def test_inactive_staff_is_rejected(self):
        staff = make_staff("gone")
        staff.is_active = False
        staff.save()
        self.assertIn(client_for(staff).get(API + "/leads/").status_code, (401, 403))

    def test_staff_reaches_them(self):
        client = client_for(make_staff())
        self.assertEqual(client.get(API + "/leads/").status_code, 200)
        self.assertEqual(client.get(API + "/meta/").status_code, 200)


class ListTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_staff())
        self.a = make_lead(business_name="پوشاک آرمان", website="arman.ir", phone="09121111111", city="تهران", category="پوشاک", tags="vip")
        self.b = make_lead(business_name="کسب و کار گل‌سرخ", instagram="@golsorkh", city="شیراز", category="گل", email="g@gol.ir")
        self.c = make_lead(business_name="Blue Shop", website="blue.com", city="تهران", category="آرایشی", country="ترکیه")
        Lead.objects.filter(pk=self.b.pk).update(status="contacted", created_at=timezone.now() - timedelta(days=10))
        Lead.objects.filter(pk=self.c.pk).update(is_archived=True)

    def ids(self, query=""):
        response = self.client.get(f"{API}/leads/?{query}")
        self.assertEqual(response.status_code, 200, response.content)
        return [row["id"] for row in response.json()["results"]]

    def test_default_hides_archived_and_sorts_newest_first(self):
        self.assertEqual(set(self.ids()), {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(), [self.a.pk, self.b.pk])

    def test_archived_filter(self):
        self.assertEqual(self.ids("archived=1"), [self.c.pk])
        self.assertEqual(set(self.ids("archived=all")), {self.a.pk, self.b.pk, self.c.pk})

    def test_search_across_name_zwnj_city_contacts_and_phone_formats(self):
        self.assertEqual(self.ids("q=" + "گلسرخ"), [self.b.pk])  # ZWNJ ignored
        self.assertEqual(self.ids("q=" + "کسب‌وکار"), [self.b.pk])
        self.assertEqual(self.ids("q=" + "پوشاک تهران"), [self.a.pk])  # every word must match somewhere
        self.assertEqual(self.ids("q=arman.ir"), [self.a.pk])
        self.assertEqual(self.ids("q=g@gol.ir"), [self.b.pk])
        self.assertEqual(self.ids("q=" + "۰۹۱۲ ۱۱۱"), [self.a.pk])  # Persian digits + spaces
        self.assertEqual(self.ids("q=912 1111"), [self.a.pk])
        self.assertEqual(self.ids("q=زززز"), [])

    def test_filters(self):
        self.assertEqual(self.ids("status=contacted"), [self.b.pk])
        self.assertEqual(self.ids("status=new,contacted"), [self.a.pk, self.b.pk])
        self.assertEqual(self.ids("city=" + "شیراز"), [self.b.pk])
        self.assertEqual(self.ids("category=" + "گل"), [self.b.pk])
        self.assertEqual(self.ids("tag=vip"), [self.a.pk])
        self.assertEqual(self.ids("has=website"), [self.a.pk])
        self.assertEqual(self.ids("has=instagram"), [self.b.pk])
        self.assertEqual(self.ids("has=phone"), [self.a.pk])
        self.assertEqual(self.ids("has=email"), [self.b.pk])
        self.assertEqual(self.ids("has=website,phone"), [self.a.pk])
        self.assertEqual(self.ids("country=TR&archived=all"), [self.c.pk])
        self.assertEqual(self.ids("origin=manual"), [self.a.pk, self.b.pk])
        recent = (timezone.localdate() - timedelta(days=3)).isoformat()
        self.assertEqual(self.ids(f"created_from={recent}"), [self.a.pk])
        self.assertEqual(self.ids(f"created_to={recent}"), [self.b.pk])

    def test_sorting(self):
        self.assertEqual(self.ids("ordering=created_at"), [self.b.pk, self.a.pk])
        self.assertEqual(self.ids("ordering=-business_name"), [self.b.pk, self.a.pk])
        self.assertEqual(self.ids("ordering=city"), [self.a.pk, self.b.pk])
        self.assertEqual(self.ids("ordering=nonsense"), [self.a.pk, self.b.pk])  # falls back to the default

    def test_pagination(self):
        for i in range(30):
            make_lead(business_name=f"انبوه {i}", phone=f"0935000{i:04d}")
        page1 = self.client.get(f"{API}/leads/?page_size=10").json()
        self.assertEqual((page1["count"], len(page1["results"])), (32, 10))
        page4 = self.client.get(f"{API}/leads/?page_size=10&page=4").json()
        self.assertEqual(len(page4["results"]), 2)
        self.assertEqual(self.client.get(f"{API}/leads/?page_size=1000").json()["results"].__len__(), 32)  # capped at 100, only 32 exist
        seen = []
        for page in range(1, 5):
            seen += [r["id"] for r in self.client.get(f"{API}/leads/?page_size=10&page={page}").json()["results"]]
        self.assertEqual(len(seen), len(set(seen)), "no lead appears on two pages")

    def test_row_shape(self):
        row = self.client.get(f"{API}/leads/?q=arman").json()["results"][0]
        self.assertEqual(row["display_name"], "پوشاک آرمان")
        self.assertEqual((row["phone"], row["email"], row["status_label"], row["country_name"]), ("09121111111", "", "جدید", ""))
        self.assertEqual([t["name"] for t in row["tags"]], ["vip"])

    def test_the_list_costs_a_fixed_number_of_queries(self):
        for i in range(40):
            make_lead(business_name=f"n{i}", phone=f"0936000{i:04d}", email=f"n{i}@x.ir", tags="a,b")
        # count + page + tags + contacts (+1: the do-not-contact lookup when that module is installed), however many rows
        expected = 4 + (1 if apps.is_installed("apps.growth_engine.compliance") else 0)
        with self.assertNumQueries(expected):
            self.client.get(f"{API}/leads/?page_size=100")
        with self.assertNumQueries(expected):
            self.client.get(f"{API}/leads/?page_size=5")


class DetailTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        self.lead = make_lead(business_name="گل‌سرخ", website="shop.ir", phone="09121234567", instagram="@gol", tags="vip", note="n")

    def test_detail_has_everything_the_page_needs(self):
        data = self.client.get(f"{API}/leads/{self.lead.pk}/").json()
        self.assertEqual(data["website"], "https://shop.ir")
        self.assertEqual(data["profile"]["business_type"], "unknown")
        self.assertEqual(sorted(c["kind"] for c in data["contacts"]), ["instagram", "phone", "website"])
        self.assertEqual(data["sources"][0]["provider"], "manual")
        self.assertEqual(data["provenance"]["business_name"]["source"], "manual")
        self.assertEqual(data["notes_count"], 1)
        self.assertEqual(self.client.get(f"{API}/leads/99999/").status_code, 404)

    def test_patch_returns_the_fresh_lead_and_what_changed(self):
        response = self.client.patch(f"{API}/leads/{self.lead.pk}/", {"city": "قم", "status": "interested", "tags": ["x", "y"]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["city"], body["status"]), ("قم", "interested"))
        self.assertEqual(sorted(body["changed"]), ["city", "status", "tags"])
        self.assertEqual(sorted(t["name"] for t in body["tags"]), ["x", "y"])

    def test_patch_validation_error_is_400_with_field_errors(self):
        response = self.client.patch(f"{API}/leads/{self.lead.pk}/", {"website": "http://localhost", "country": "Atlantis"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(sorted(e["field"] for e in response.json()["errors"]), ["country", "website"])

    def test_patch_to_another_leads_identifier_is_409_with_that_lead(self):
        other = make_lead(business_name="دیگری", website="other.ir")
        response = self.client.patch(f"{API}/leads/{self.lead.pk}/", {"website": "other.ir"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["duplicates"][0]["lead"]["id"], other.pk)

    def test_delete_needs_confirmation(self):
        self.assertEqual(self.client.delete(f"{API}/leads/{self.lead.pk}/").status_code, 400)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())
        self.assertEqual(self.client.delete(f"{API}/leads/{self.lead.pk}/?confirm=1").status_code, 204)
        self.assertFalse(Lead.objects.filter(pk=self.lead.pk).exists())
        self.assertEqual(LeadActivity.objects.filter(lead_id=self.lead.pk).count(), 0)

    def test_notes_contacts_and_activity_endpoints(self):
        base = f"{API}/leads/{self.lead.pk}"
        note = self.client.post(f"{base}/notes/", {"body": "یادداشت تازه"}, format="json")
        self.assertEqual(note.status_code, 201)
        note_id = note.json()["id"]
        self.assertEqual(self.client.patch(f"{base}/notes/{note_id}/", {"body": "ویرایش"}, format="json").json()["body"], "ویرایش")
        self.assertEqual(len(self.client.get(f"{base}/notes/").json()), 2)
        self.assertEqual(self.client.delete(f"{base}/notes/{note_id}/").status_code, 204)
        self.assertEqual(self.client.post(f"{base}/notes/", {"body": "  "}, format="json").status_code, 400)

        contact = self.client.post(f"{base}/contacts/", {"kind": "email", "value": "A@B.ir", "label": "مدیر"}, format="json")
        self.assertEqual(contact.status_code, 201, contact.content)
        self.assertEqual(contact.json()["value"], "a@b.ir")
        cid = contact.json()["id"]
        self.assertEqual(self.client.patch(f"{base}/contacts/{cid}/", {"label": "فروش"}, format="json").json()["label"], "فروش")
        self.assertEqual(self.client.post(f"{base}/contacts/", {"kind": "email", "value": "a@b.ir"}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"{base}/contacts/{cid}/").status_code, 204)

        activity = self.client.get(f"{base}/activity/").json()
        self.assertGreaterEqual(activity["count"], 6)
        self.assertEqual(activity["results"][0]["kind"], "contact_removed")
        only_notes = self.client.get(f"{base}/activity/?kind=note_added").json()
        self.assertTrue(all(r["kind"] == "note_added" for r in only_notes["results"]))
        # a note id of another lead is not reachable through this lead
        other = make_lead(business_name="دیگری")
        other_note = other.notes.create(body="y")
        self.assertEqual(self.client.delete(f"{base}/notes/{other_note.pk}/").status_code, 404)


class BulkAndExportTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_staff())
        self.leads = [make_lead(business_name=f"لید {i}", phone=f"0912333000{i}") for i in range(3)]
        self.ids = [lead.pk for lead in self.leads]

    def test_bulk_endpoint(self):
        response = self.client.post(f"{API}/leads/bulk/", {"ids": self.ids, "action": "set_status", "status": "qualified"}, format="json")
        self.assertEqual(response.json()["affected"], 3)
        self.assertEqual(self.client.post(f"{API}/leads/bulk/", {"ids": self.ids, "action": "delete"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/leads/bulk/", {"ids": [], "action": "archive"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/leads/bulk/", {"ids": self.ids, "action": "add_tag", "tag": "کمپین"}, format="json").json()["affected"], 3)
        tags = self.client.get(f"{API}/tags/").json()
        self.assertEqual((tags[0]["name"], tags[0]["lead_count"]), ("کمپین", 3))

    def test_export_is_utf8_bom_csv_with_persian_headers(self):
        response = self.client.get(f"{API}/leads/export/")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content)
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertIn("attachment", response["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:3], ["شناسه", "نام کسب‌وکار", "وب‌سایت"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1][4], "0912 333 0002")  # newest first; leading zero kept as text for Excel

    def test_export_respects_filters_and_ids(self):
        Lead.objects.filter(pk=self.ids[1]).update(status="qualified")
        filtered = list(csv.reader(io.StringIO(b"".join(self.client.get(f"{API}/leads/export/?status=qualified").streaming_content).decode("utf-8-sig"))))
        self.assertEqual([r[0] for r in filtered[1:]], [str(self.ids[1])])
        rows = list(csv.reader(io.StringIO(b"".join(self.client.get(f"{API}/leads/export/?ids={self.ids[0]},{self.ids[2]}").streaming_content).decode("utf-8-sig"))))
        self.assertEqual(sorted(r[0] for r in rows[1:]), sorted([str(self.ids[0]), str(self.ids[2])]))

    def test_export_blocks_formula_injection(self):
        evil = make_lead(business_name="=HYPERLINK(\"http://evil\",\"x\")", city="+SUM(1)", category="@cmd", description="-2+3")
        body = b"".join(self.client.get(f"{API}/leads/export/?ids={evil.pk}").streaming_content).decode("utf-8-sig")
        row = list(csv.reader(io.StringIO(body)))[1]
        self.assertEqual(row[1][0], "'")
        self.assertTrue(row[1].startswith("'=HYPERLINK"))
        self.assertTrue(row[11].startswith("'+SUM"))
        self.assertTrue(row[8].startswith("'@cmd"))
        self.assertTrue(row[9].startswith("'-2"))

    def test_exported_file_is_understood_by_the_importer(self):
        from apps.growth_engine.core import csvio
        from apps.growth_engine.discovery.services import csv_mapping

        body = b"".join(self.client.get(f"{API}/leads/export/").streaming_content).decode("utf-8-sig")
        headers, rows, _ = csvio.read_table(body)
        mapping = csv_mapping.suggest_mapping(headers)
        self.assertEqual(mapping["نام کسب‌وکار"], "business_name")
        self.assertEqual(mapping["تلفن"], "phone")
        self.assertEqual(mapping["وب‌سایت"], "website")
        self.assertEqual(mapping["شناسه"], "")
        self.assertEqual(mapping["وضعیت"], "")
