"""Provider settings API (secrets stay secret) and the search job: fetch -> candidates -> leads / duplicates -> resume / cancel."""
from __future__ import annotations

import json
from unittest import mock

import httpx
from django.test import TestCase

from apps.growth_engine.compliance.models import AuditEntry
from apps.growth_engine.core.testing import NoNetworkMixin, TempMediaMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.discovery.models import DiscoveryJob, DiscoveryJobRow, ProviderConfig
from apps.growth_engine.discovery.services import search
from apps.growth_engine.extraction.models import ExtractionJob
from apps.growth_engine.leads.models import ContactPoint, Lead
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import LeadSource, SourceProvider

from .helpers import HAMEDAN, NOMINATIM, OVERPASS, FakeApis, make_fetcher, overpass_payload, shop

API = "/api/v1/growth/discovery"
BRAVE_KEY = "BRAVE-SECRET-KEY-98765"
GOOGLE_KEY, GOOGLE_CX = "GOOGLE-SECRET-KEY-5555", "ENGINE-CX-7777"


def elements(n=3):
    return [shop(i, f"فروشگاه {i}", website=f"https://shop{i}.example/", phone=f"0912333{i:04d}") for i in range(1, n + 1)]


def world(*els, status=200):
    apis = FakeApis().json(NOMINATIM, HAMEDAN)
    apis.json(OVERPASS, overpass_payload(*els), status=status)
    return apis


class Base(TempMediaMixin, NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        self.apis = world(*elements())

    def patch_world(self, apis=None):
        apis = apis or self.apis
        fetcher, clock = make_fetcher(apis)
        self.clock = clock
        patcher = mock.patch.object(search, "make_fetcher", lambda: fetcher)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fetcher

    def start(self, **data):
        body = {"provider": "osm", "category": "clothes", "city": "همدان", "max_results": 50, **data}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{API}/search/", body, format="json")
        return response

    def job(self, response):
        self.assertEqual(response.status_code, 202, response.content)
        job = DiscoveryJob.objects.get(pk=response.json()["id"])
        return job


class ProviderConfigApiTests(Base):
    def test_listing_shows_the_free_map_ready_and_the_keyed_ones_off(self):
        data = self.client.get(f"{API}/providers/").json()["providers"]
        by_key = {p["key"]: p for p in data}
        self.assertEqual(set(by_key), {"osm", "brave", "google_cse"})
        self.assertTrue(by_key["osm"]["ready"])
        self.assertEqual(by_key["osm"]["attribution"], "© OpenStreetMap contributors (ODbL)")
        self.assertGreaterEqual(len(by_key["osm"]["categories"]), 12)
        self.assertFalse(by_key["brave"]["ready"])
        self.assertIn("وارد نشده", by_key["brave"]["not_ready_reason"])
        self.assertFalse(by_key["brave"]["secrets"]["api_key"]["is_set"])
        self.assertEqual(by_key["google_cse"]["secrets"].keys(), {"api_key", "cx"})

    def test_a_key_is_stored_but_never_returned(self):
        response = self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": BRAVE_KEY}, "enabled": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["secrets"]["api_key"]["is_set"])
        self.assertTrue(response.json()["ready"])
        self.assertNotIn(BRAVE_KEY, response.content.decode())
        self.assertNotIn(BRAVE_KEY[-4:], response.content.decode())
        listing = self.client.get(f"{API}/providers/")
        self.assertNotIn(BRAVE_KEY, listing.content.decode())
        self.assertNotIn(BRAVE_KEY, self.client.get(f"{API}/providers/brave/").content.decode())
        self.assertEqual(ProviderConfig.objects.get(provider="brave").secrets["api_key"], BRAVE_KEY)  # the database has it
        # not in the audit trail either: the names of the changed fields only
        trail = json.dumps(list(AuditEntry.objects.values("summary", "data")), ensure_ascii=False)
        self.assertNotIn(BRAVE_KEY, trail)
        self.assertIn("secrets.api_key", trail)

    def test_enabling_a_keyed_provider_without_its_key_is_refused(self):
        response = self.client.patch(f"{API}/providers/brave/", {"enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "key_required")
        google = self.client.patch(f"{API}/providers/google_cse/", {"enabled": True, "secrets": {"api_key": GOOGLE_KEY}}, format="json")
        self.assertEqual(google.status_code, 400)  # the engine id is missing
        self.assertFalse(ProviderConfig.objects.filter(provider="google_cse", enabled=True).exists())

    def test_clearing_a_key_makes_the_provider_not_ready_again(self):
        self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": BRAVE_KEY}, "enabled": True}, format="json")
        response = self.client.patch(f"{API}/providers/brave/", {"clear_secrets": ["api_key"]}, format="json")
        self.assertFalse(response.json()["secrets"]["api_key"]["is_set"])
        self.assertFalse(response.json()["ready"])
        self.assertEqual(ProviderConfig.objects.get(provider="brave").secrets, {})

    def test_removing_the_key_while_the_panel_still_sends_enabled_true_switches_it_off(self):
        self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": BRAVE_KEY}, "enabled": True}, format="json")
        response = self.client.patch(f"{API}/providers/brave/", {"enabled": True, "clear_secrets": ["api_key"]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["enabled"], response.json()["secrets"]["api_key"]["is_set"]), (False, False))
        # but switching it ON while there is no key is still refused
        self.assertEqual(self.client.patch(f"{API}/providers/brave/", {"enabled": True}, format="json").status_code, 400)

    def test_an_empty_secret_box_keeps_the_stored_key(self):
        self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": BRAVE_KEY}}, format="json")
        self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": ""}, "settings": {"daily_cap": 5}}, format="json")
        row = ProviderConfig.objects.get(provider="brave")
        self.assertEqual((row.secrets["api_key"], row.config["daily_cap"]), (BRAVE_KEY, 5))

    def test_bad_secret_values_and_names_are_refused(self):
        for value in ("short", "has space in it 1234", "کلید-فارسی-۱۲۳۴۵۶۷۸", "x" * 301):
            response = self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": value}}, format="json")
            self.assertEqual(response.status_code, 400, value)
        self.assertEqual(self.client.patch(f"{API}/providers/brave/", {"secrets": {"password": "abcdefgh123"}}, format="json").status_code, 400)
        self.assertFalse(ProviderConfig.objects.filter(provider="brave").exists())

    def test_settings_are_validated(self):
        ok = self.client.patch(f"{API}/providers/osm/", {"settings": {"overpass_endpoints": ["https://overpass.example.org/api/interpreter", "https://overpass-api.de/api/interpreter"]}}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(len(ok.json()["settings"]["overpass_endpoints"]), 2)
        for bad in ({"overpass_endpoints": ["javascript:alert(1)"]}, {"overpass_endpoints": []}, {"nominatim_url": "not a url"}, {"unknown": 1}):
            self.assertEqual(self.client.patch(f"{API}/providers/osm/", {"settings": bad}, format="json").status_code, 400, bad)
        self.assertEqual(self.client.patch(f"{API}/providers/brave/", {"settings": {"daily_cap": 0}}, format="json").status_code, 400)

    def test_only_staff_and_only_known_providers(self):
        self.assertEqual(client_for().get(f"{API}/providers/").status_code, 401)
        plain = make_plain_user("ge-plain-a")
        self.assertEqual(client_for(plain).get(f"{API}/providers/").status_code, 403)
        self.assertEqual(client_for(plain).patch(f"{API}/providers/brave/", {"enabled": False}, format="json").status_code, 403)
        self.assertEqual(self.client.get(f"{API}/providers/nope/").status_code, 404)
        self.assertEqual(self.client.patch(f"{API}/providers/nope/", {}, format="json").status_code, 404)


class CheckAndValidationTests(Base):
    def test_check_resolves_the_city_once_and_shows_the_licence_line(self):
        self.patch_world()
        body = {"provider": "osm", "category": "clothes", "city": "همدان"}
        first = self.client.post(f"{API}/search/check/", body, format="json").json()
        self.assertTrue(first["ok"])
        self.assertIn("همدان", first["place"]["name"])
        self.assertFalse(first["place"]["cached"])
        self.assertEqual(first["attribution"], "© OpenStreetMap contributors (ODbL)")
        second = self.client.post(f"{API}/search/check/", body, format="json").json()
        self.assertTrue(second["place"]["cached"])
        self.assertEqual(len(self.apis.to(NOMINATIM)), 1)
        self.assertEqual(self.apis.to(OVERPASS), [])  # a check never runs the search

    def test_unknown_city_is_a_field_error(self):
        apis = FakeApis().json(NOMINATIM, [])
        self.patch_world(apis)
        response = self.client.post(f"{API}/search/check/", {"provider": "osm", "category": "clothes", "city": "ناکجاآباد"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["field"], "city")

    def test_request_validation(self):
        cases = [
            ({"provider": "nope"}, "provider"),
            ({"provider": "osm", "category": "not-a-preset", "city": "همدان"}, "category"),
            ({"provider": "osm", "category": "clothes", "city": ""}, "city"),
            ({"provider": "osm", "category": "clothes", "city": "همدان", "max_results": 501}, "max_results"),
            ({"provider": "brave", "category": "لباس زنانه", "city": "همدان"}, "provider"),  # no key yet
        ]
        for body, field in cases:
            response = self.client.post(f"{API}/search/", body, format="json")
            self.assertEqual(response.status_code, 400, body)
            self.assertIn(field, [e["field"] for e in response.json()["errors"]], body)
        self.assertEqual(DiscoveryJob.objects.count(), 0)

    def test_only_staff_may_start_a_search(self):
        self.assertEqual(client_for(make_plain_user("ge-plain-b")).post(f"{API}/search/", {"provider": "osm"}, format="json").status_code, 403)
        self.assertEqual(client_for().post(f"{API}/search/check/", {"provider": "osm"}, format="json").status_code, 401)


class SearchJobTests(Base):
    def test_a_map_search_creates_leads_with_provenance_and_the_licence_line(self):
        self.patch_world()
        job = self.job(self.start(tags=["نقشه"]))
        job.refresh_from_db()
        self.assertEqual((job.status, job.kind, job.total_items, job.processed_items, job.created_count), ("completed", "search", 3, 3, 3))
        self.assertEqual(Lead.objects.count(), 3)
        lead = Lead.objects.get(contacts__value="https://shop1.example")
        self.assertEqual((lead.origin, lead.city, lead.category), ("search", "همدان", "پوشاک و لباس"))
        self.assertTrue(lead.tags.filter(name="نقشه").exists())
        source = LeadSource.objects.get(lead=lead)
        self.assertEqual((source.provider, source.source_ref), (SourceProvider.OSM_OVERPASS, "osm:node/1"))
        self.assertEqual(source.source_url, "https://www.openstreetmap.org/node/1")
        self.assertEqual(source.raw_data["attribution"], "© OpenStreetMap contributors (ODbL)")
        self.assertEqual(source.job_id, job.pk)
        phone = ContactPoint.objects.get(lead=lead, kind="phone")
        self.assertEqual(phone.source_ref, "osm:node/1")
        self.assertEqual(lead.provenance["business_name"]["source"], "osm:node/1")
        self.assertEqual(job.params["attribution"], "© OpenStreetMap contributors (ODbL)")
        self.assertFalse(job.stored_name)  # the temporary candidate file is gone
        api = self.client.get(f"{API}/jobs/{job.pk}/").json()
        self.assertEqual((api["kind_label"], api["attribution"]), ("کشفِ خودکار (نقشه / جست‌وجو)", "© OpenStreetMap contributors (ODbL)"))
        self.assertEqual(api["params"]["category_label"], "پوشاک و لباس")

    def test_a_business_we_already_have_waits_for_a_decision_and_merges_with_its_osm_source(self):
        self.patch_world()
        draft, _ = build_draft({"business_name": "فروشگاه قدیمی", "website": "https://shop2.example/"})
        existing = intake.create_from_draft(draft, intake.SourceInfo(provider=SourceProvider.MANUAL), self.staff)
        job = self.job(self.start())
        job.refresh_from_db()
        self.assertEqual((job.created_count, job.duplicate_count), (2, 1))
        row = DiscoveryJobRow.objects.get(job=job)
        self.assertEqual((row.status, row.matched_lead_id), ("duplicate", existing.pk))
        self.assertEqual(Lead.objects.count(), 3)
        result = self.client.post(f"{API}/jobs/{job.pk}/resolve/", {"action": "merge", "all": True}, format="json").json()
        self.assertEqual((result["merged"], result["remaining"]), (1, 0))
        merged = LeadSource.objects.filter(lead=existing, provider=SourceProvider.OSM_OVERPASS).get()
        self.assertEqual(merged.source_ref, "osm:node/2")
        self.assertTrue(ContactPoint.objects.filter(lead=existing, kind="phone", source_ref="osm:node/2").exists())

    def test_nothing_found_is_a_completed_job_with_a_plain_note(self):
        self.patch_world(world())
        job = self.job(self.start())
        job.refresh_from_db()
        self.assertEqual((job.status, job.total_items, Lead.objects.count()), ("completed", 0, 0))
        self.assertIn("هیچ موردی", self.client.get(f"{API}/jobs/{job.pk}/").json()["params"]["empty_note"])

    def test_a_busy_map_server_fails_the_job_plainly_and_resume_asks_again(self):
        busy = world(status=502)
        self.patch_world(busy)
        job = self.job(self.start())
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("شلوغ", job.error)
        self.assertEqual(Lead.objects.count(), 0)
        data = self.client.get(f"{API}/jobs/{job.pk}/").json()
        self.assertTrue(data["can_resume"])
        # the server recovers
        self.patch_world(world(*elements(2)))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{API}/jobs/{job.pk}/resume/")
        self.assertEqual(response.status_code, 202, response.content)
        job.refresh_from_db()
        self.assertEqual((job.status, job.created_count, Lead.objects.count()), ("completed", 2, 2))

    def test_resume_after_an_internal_failure_continues_after_the_cursor_without_asking_again(self):
        self.patch_world()
        real = search.rowops.process_draft
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("boom")  # an infrastructure failure on the third candidate
            return real(*args, **kwargs)

        with mock.patch.object(search.rowops, "process_draft", flaky):
            job = self.job(self.start())
        job.refresh_from_db()
        self.assertEqual((job.status, job.cursor, job.created_count), ("failed", 2, 2))
        self.assertTrue(job.stored_name)
        overpass_calls = len(self.apis.to(OVERPASS))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"{API}/jobs/{job.pk}/resume/")
        job.refresh_from_db()
        self.assertEqual((job.status, job.created_count, Lead.objects.count()), ("completed", 3, 3))
        self.assertEqual(len(self.apis.to(OVERPASS)), overpass_calls)  # the stored answer was used

    def test_cancel_stops_between_candidates_and_keeps_what_was_filed(self):
        self.apis = world(*elements(12))
        self.patch_world()
        polls = {"n": 0}

        def cancel_on_second_poll(job):
            polls["n"] += 1
            return polls["n"] >= 3  # poll 1 = the fetch phase, poll 2 = before the first candidate, poll 3 = before the 11th

        with mock.patch.object(search.rowops, "should_cancel", cancel_on_second_poll):
            job = self.job(self.start())
        job.refresh_from_db()
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(Lead.objects.count(), 10)

    def test_extract_after_starts_contact_extraction_for_the_new_leads(self):
        self.patch_world()
        with mock.patch("apps.growth_engine.extraction.receivers.enqueue_extraction") as enqueue:
            job = self.job(self.start(extract_after=True))
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertTrue(ExtractionJob.objects.filter(discovery_job=job).exists())
        self.assertTrue(enqueue.called)

    def test_without_the_option_nothing_is_extracted(self):
        self.patch_world()
        with mock.patch("apps.growth_engine.extraction.receivers.enqueue_extraction") as enqueue:
            self.job(self.start())
        self.assertFalse(enqueue.called)
        self.assertEqual(ExtractionJob.objects.count(), 0)

    def test_the_report_rows_of_a_provider_job_carry_their_source(self):
        self.patch_world()
        draft, _ = build_draft({"business_name": "قدیمی", "website": "https://shop1.example/"})
        intake.create_from_draft(draft, intake.SourceInfo(provider=SourceProvider.MANUAL), self.staff)
        job = self.job(self.start())
        rows = self.client.get(f"{API}/jobs/{job.pk}/rows/?status=duplicate").json()["results"]
        self.assertEqual(rows[0]["raw"]["_source"]["ref"], "osm:node/1")
        self.assertEqual(rows[0]["raw"]["business_name"], "فروشگاه 1")


class KeyedSearchJobTests(Base):
    def enable_brave(self, **settings):
        response = self.client.patch(f"{API}/providers/brave/", {"secrets": {"api_key": BRAVE_KEY}, "enabled": True, "settings": settings}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def brave_world(self, n=3):
        apis = FakeApis()
        apis.json("api.search.brave.com", {"web": {"results": [
            {"title": f"فروشگاه {i} | لباس", "url": f"https://shop{i}.example/page", "description": "d"} for i in range(1, n + 1)
        ] + [{"title": "اینستا", "url": "https://instagram.com/x", "description": "d"}]}})
        return apis

    def test_a_brave_search_files_websites_as_leads_under_the_search_origin(self):
        self.enable_brave()
        self.patch_world(self.brave_world())
        job = self.job(self.start(provider="brave", category="فروشگاه لباس زنانه", city="همدان", max_results=10))
        job.refresh_from_db()
        self.assertEqual((job.status, job.created_count), ("completed", 3))
        lead = Lead.objects.get(contacts__value="https://shop1.example")
        self.assertEqual((lead.origin, lead.business_name), ("search", "فروشگاه 1"))
        source = LeadSource.objects.get(lead=lead)
        self.assertEqual((source.provider, source.source_ref), (SourceProvider.BRAVE_SEARCH, "search:brave:shop1.example"))
        self.assertEqual(source.source_url, "https://shop1.example/page")
        self.assertFalse(Lead.objects.filter(contacts__value__contains="instagram").exists())

    def test_the_key_never_reaches_a_job_a_lead_a_row_or_a_response(self):
        self.enable_brave()
        self.patch_world(self.brave_world())
        job = self.job(self.start(provider="brave", category="فروشگاه لباس", city="همدان", max_results=10))
        blobs = [
            json.dumps(self.client.get(f"{API}/jobs/{job.pk}/").json(), ensure_ascii=False),
            json.dumps(list(DiscoveryJob.objects.values("params", "error", "file_name")), ensure_ascii=False),
            json.dumps(list(LeadSource.objects.values("raw_data", "source_url", "source_ref")), ensure_ascii=False),
            json.dumps(list(AuditEntry.objects.values("summary", "data")), ensure_ascii=False),
            self.client.get(f"{API}/providers/").content.decode(),
        ]
        for blob in blobs:
            self.assertNotIn(BRAVE_KEY, blob)

    def test_the_daily_cap_protects_the_free_quota(self):
        self.enable_brave(daily_cap=1)
        self.patch_world(self.brave_world())
        job = self.job(self.start(provider="brave", category="فروشگاه لباس", city="همدان", max_results=30))  # two pages
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("سقفِ درخواستِ امروز", job.error)
        listing = {p["key"]: p for p in self.client.get(f"{API}/providers/").json()["providers"]}
        self.assertEqual((listing["brave"]["usage_today"], listing["brave"]["daily_cap"]), (1, 1))

    def test_a_rejected_key_says_so_in_plain_words(self):
        self.enable_brave()
        apis = FakeApis().on("api.search.brave.com", lambda r: httpx.Response(403, json={"error": "x"}))
        self.patch_world(apis)
        job = self.job(self.start(provider="brave", category="فروشگاه لباس", city="", max_results=10))
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("کلیدِ API برِیو پذیرفته نشد", job.error)
        self.assertNotIn(BRAVE_KEY, job.error)
