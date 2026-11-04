from datetime import date

from django.test import TestCase

from apps.growth_engine.analytics import registry
from apps.growth_engine.compliance.models import AuditEntry, GrowthSettings, SuppressionEntry
from apps.growth_engine.compliance.services import limits, suppression
from apps.growth_engine.compliance.services import settings as settings_service
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.leads.models import Lead, LeadActivity
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import SourceProvider

API = "/api/v1/growth"
IDENTITY = {
    "sender_name": "علی رضایی", "sender_company": "آپ‌مارکت", "sender_phone": "0912 123 4567", "sender_email": "Ali@UpMarket.ir",
}


def make_lead(**raw):
    raw.setdefault("business_name", "فروشگاه")
    d, errors = build_draft(raw)
    assert not errors, errors
    return intake.create_from_draft(d, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


class SettingsServiceTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()

    def test_defaults_are_safe(self):
        s = settings_service.get_settings()
        self.assertEqual((s.sending_enabled, s.emergency_stop, s.daily_cap, s.spacing_min_seconds, s.spacing_max_seconds), (False, False, 40, 60, 120))
        self.assertIn("لغو", s.opt_out_line)
        self.assertFalse(s.readiness()["ok"])
        self.assertEqual(len(s.identity_problems()), 4)

    def test_it_is_a_singleton(self):
        GrowthSettings.load()
        GrowthSettings(sender_name="x").save()
        self.assertEqual(GrowthSettings.objects.count(), 1)

    def test_identity_is_validated_and_normalised_and_audited(self):
        s = settings_service.update_settings(IDENTITY, self.staff)
        self.assertEqual((s.sender_email, s.sender_name), ("ali@upmarket.ir", "علی رضایی"))
        self.assertTrue(s.readiness()["ok"])
        entry = AuditEntry.objects.get(kind="settings_changed")
        self.assertIn("sender_name", entry.data["changes"])
        self.assertEqual(entry.actor_id, self.staff.pk)

    def test_bad_values_save_nothing(self):
        with self.assertRaises(settings_service.SettingsInvalid) as ctx:
            settings_service.update_settings({"sender_name": "x", "sender_phone": "12", "sender_email": "bad", "daily_cap": 0, "spacing_min_seconds": 5, "sender_website": "not a url"}, self.staff)
        self.assertEqual(sorted(e["field"] for e in ctx.exception.errors), ["daily_cap", "sender_email", "sender_phone", "sender_website", "spacing_min_seconds"])
        self.assertEqual(settings_service.get_settings().sender_name, "")
        self.assertEqual(AuditEntry.objects.count(), 0)

    def test_spacing_range(self):
        with self.assertRaises(settings_service.SettingsInvalid):
            settings_service.update_settings({"spacing_min_seconds": 200, "spacing_max_seconds": 100}, self.staff)
        settings_service.update_settings({"spacing_min_seconds": 30, "spacing_max_seconds": 45, "daily_cap": 25}, self.staff)
        s = settings_service.get_settings()
        self.assertEqual((s.spacing_min_seconds, s.spacing_max_seconds, s.daily_cap), (30, 45, 25))

    def test_the_opt_out_line_cannot_be_empty(self):
        with self.assertRaises(settings_service.SettingsInvalid):
            settings_service.update_settings({"opt_out_line": "  "}, self.staff)

    def test_sending_cannot_be_enabled_while_the_identity_is_incomplete(self):
        with self.assertRaises(settings_service.SettingsInvalid) as ctx:
            settings_service.update_settings({"sending_enabled": True}, self.staff)
        self.assertEqual(ctx.exception.errors[0]["code"], "identity_incomplete")
        self.assertFalse(settings_service.get_settings().sending_enabled)
        settings_service.update_settings({**IDENTITY, "sending_enabled": True}, self.staff)
        self.assertTrue(settings_service.get_settings().sending_enabled)

    def test_emergency_stop_toggles_and_is_audited(self):
        settings_service.set_emergency_stop(True, self.staff)
        self.assertTrue(settings_service.get_settings().emergency_stop)
        self.assertFalse(settings_service.get_settings().readiness()["ok"])
        settings_service.set_emergency_stop(True, self.staff)  # no change, no second entry
        settings_service.set_emergency_stop(False, self.staff)
        self.assertEqual(list(AuditEntry.objects.order_by("id").values_list("kind", flat=True)), ["emergency_stop", "emergency_resume"])

    def test_audit_entries_are_append_only(self):
        settings_service.set_emergency_stop(True, self.staff)
        entry = AuditEntry.objects.get()
        entry.summary = "tampered"
        with self.assertRaises(ValueError):
            entry.save()


class LimitsTests(NoNetworkMixin, TestCase):
    def test_cap_remaining_uses_registered_counters(self):
        calls = []

        def counter(day: date) -> int:
            calls.append(day)
            return 15

        limits.register_counter(counter)
        limits.register_counter(counter)  # twice is a no-op
        try:
            self.assertEqual(limits.sent_today(), 15)
            self.assertEqual(limits.cap_remaining(), 25)
            GrowthSettings.load().__class__.objects.filter(pk=1).update(daily_cap=10)
            self.assertEqual(limits.cap_remaining(), 0)
        finally:
            limits._COUNTERS.remove(counter)


class SuppressionServiceTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()

    def test_classify_what_people_paste(self):
        cases = [
            ("0912 123 4567", ("phone", "09121234567")), ("۰۹۱۲۱۲۳۴۵۶۷", ("phone", "09121234567")), ("+98 21 1234 5678", ("phone", "02112345678")),
            ("Info@Shop.IR", ("email", "info@shop.ir")), ("@my.shop", ("instagram", "my.shop")), ("https://instagram.com/My.Shop/", ("instagram", "my.shop")),
            ("https://www.shop.ir/about", ("website", "shop.ir")), ("shop.ir", ("website", "shop.ir")),
        ]
        for raw, (kind, key) in cases:
            with self.subTest(raw=raw):
                got = suppression.classify(raw)
                self.assertEqual((got[0], got[1]), (kind, key))
        for bad in ["", "   ", "12", "not valid @@"]:
            with self.subTest(bad=bad), self.assertRaises(nz.NormalizationError):
                suppression.classify(bad)

    def test_suppressing_a_lead_covers_every_identifier_and_follows_the_business(self):
        lead = make_lead(website="shop.ir", instagram="@shop", phone="09121234567", email="a@shop.ir")
        created = suppression.suppress_lead(lead, "opt_out", "گفت لغو", self.staff)
        self.assertEqual(sorted(e.kind for e in created), ["email", "instagram", "phone", "website"])
        self.assertEqual(len(suppression.matches_for_lead(lead)), 4)
        self.assertTrue(LeadActivity.objects.filter(lead=lead, kind="suppressed").exists())
        self.assertTrue(AuditEntry.objects.filter(kind="suppress_added").exists())
        self.assertEqual(suppression.suppressed_lead_ids([lead.pk]), {lead.pk})

    def test_a_different_lead_sharing_one_identifier_is_blocked_too(self):
        a = make_lead(business_name="الف", phone="09121234567")
        suppression.suppress_lead(a, "opt_out", "", self.staff)
        b = make_lead(business_name="ب", email="b@b.ir")
        self.assertEqual(suppression.suppressed_lead_ids([a.pk, b.pk]), {a.pk})
        suppression.add_entries([("email", "b@b.ir", "b@b.ir")], "other", "", self.staff)
        self.assertEqual(suppression.suppressed_lead_ids([a.pk, b.pk]), {a.pk, b.pk})

    def test_a_lead_with_nothing_to_list_says_so(self):
        lead = make_lead(business_name="فقط نام")
        with self.assertRaises(suppression.NothingToSuppress):
            suppression.suppress_lead(lead, "opt_out", "", self.staff)

    def test_unsuppress_removes_only_that_leads_identifiers(self):
        a = make_lead(business_name="الف", phone="09121234567")
        b = make_lead(business_name="ب", phone="09350000000")
        suppression.suppress_lead(a, "opt_out", "", self.staff)
        suppression.suppress_lead(b, "opt_out", "", self.staff)
        self.assertEqual(suppression.unsuppress_lead(a, self.staff), 1)
        self.assertEqual(suppression.suppressed_lead_ids([a.pk, b.pk]), {b.pk})
        self.assertTrue(LeadActivity.objects.filter(lead=a, kind="unsuppressed").exists())

    def test_adding_twice_does_not_duplicate(self):
        suppression.add_entries([("phone", "09121234567", "09121234567")], "other", "", self.staff)
        self.assertEqual(suppression.add_entries([("phone", "09121234567", "09121234567")], "other", "", self.staff), [])
        self.assertEqual(SuppressionEntry.objects.count(), 1)

    def test_bulk_lookup_is_one_query(self):
        leads = [make_lead(business_name=f"n{i}", phone=f"091200000{i:02d}") for i in range(20)]
        suppression.suppress_lead(leads[3], "opt_out", "", self.staff)
        with self.assertNumQueries(1):
            found = suppression.suppressed_lead_ids([lead.pk for lead in leads])
        self.assertEqual(found, {leads[3].pk})


class ComplianceApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def test_every_endpoint_is_staff_only(self):
        lead = make_lead(phone="09121234567")
        entry = SuppressionEntry.objects.create(kind="phone", normalized="09350000000", value="09350000000")
        endpoints = [
            ("get", "/settings/"), ("patch", "/settings/"), ("post", "/settings/emergency-stop/"), ("get", "/settings/audit/"),
            ("get", "/compliance/suppression/"), ("post", "/compliance/suppression/"), ("delete", f"/compliance/suppression/{entry.pk}/"),
            ("post", f"/leads/{lead.pk}/do-not-contact/"), ("delete", f"/leads/{lead.pk}/do-not-contact/"),
        ]
        plain = client_for(make_plain_user())
        for method, path in endpoints:
            with self.subTest(path=path, who="anonymous"):
                self.assertIn(getattr(client_for(), method)(API + path).status_code, (401, 403))
            with self.subTest(path=path, who="user"):
                self.assertEqual(getattr(plain, method)(API + path).status_code, 403)
        self.assertTrue(SuppressionEntry.objects.filter(pk=entry.pk).exists())

    def test_settings_get_and_patch(self):
        data = self.client.get(f"{API}/settings/").json()
        self.assertEqual((data["sending_enabled"], data["daily_cap"], data["sent_today"], data["cap_remaining"]), (False, 40, 0, 40))
        self.assertFalse(data["ready"]["ok"])
        response = self.client.patch(f"{API}/settings/", IDENTITY, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["ready"]["ok"])
        refused = self.client.patch(f"{API}/settings/", {"daily_cap": 9999, "sender_email": "bad"}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(sorted(e["field"] for e in refused.json()["errors"]), ["daily_cap", "sender_email"])

    def test_enabling_sending_is_refused_until_the_identity_is_complete(self):
        refused = self.client.patch(f"{API}/settings/", {"sending_enabled": True}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("مشخصات", refused.json()["detail"])
        self.client.patch(f"{API}/settings/", IDENTITY, format="json")
        self.assertEqual(self.client.patch(f"{API}/settings/", {"sending_enabled": True}, format="json").json()["sending_enabled"], True)

    def test_emergency_stop_and_audit(self):
        stopped = self.client.post(f"{API}/settings/emergency-stop/", {"stop": True}, format="json").json()
        self.assertTrue(stopped["emergency_stop"])
        self.assertFalse(stopped["ready"]["ok"])
        self.assertIn("توقفِ اضطراری", " ".join(stopped["ready"]["problems"]))
        audit = self.client.get(f"{API}/settings/audit/").json()
        self.assertEqual(audit[0]["kind"], "emergency_stop")
        self.assertEqual(audit[0]["actor_name"], self.staff.username)
        self.assertEqual(self.client.post(f"{API}/settings/emergency-stop/", {}, format="json").status_code, 400)

    def test_suppression_list_add_search_remove(self):
        added = self.client.post(f"{API}/compliance/suppression/", {"value": "۰۹۱۲ ۱۲۳ ۴۵۶۷", "reason": "opt_out", "note": "تلفنی گفت"}, format="json")
        self.assertEqual(added.status_code, 201, added.content)
        entry = added.json()["entries"][0]
        self.assertEqual((entry["kind"], entry["value"], entry["reason_label"]), ("phone", "09121234567", "درخواستِ لغو داد"))
        self.assertEqual(self.client.post(f"{API}/compliance/suppression/", {"value": "09121234567"}, format="json").status_code, 400)  # already listed
        self.assertEqual(self.client.post(f"{API}/compliance/suppression/", {"value": "xx"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/compliance/suppression/", {}, format="json").status_code, 400)
        self.client.post(f"{API}/compliance/suppression/", {"value": "info@shop.ir"}, format="json")
        listing = self.client.get(f"{API}/compliance/suppression/").json()
        self.assertEqual(listing["count"], 2)
        self.assertEqual(self.client.get(f"{API}/compliance/suppression/?q=shop").json()["count"], 1)
        self.assertEqual(self.client.delete(f"{API}/compliance/suppression/{entry['id']}/").status_code, 204)
        self.assertEqual(SuppressionEntry.objects.count(), 1)

    def test_lead_do_not_contact_roundtrip_and_flag_on_the_lead(self):
        lead = make_lead(website="shop.ir", phone="09121234567")
        other = make_lead(business_name="دیگری", phone="09350000000")
        self.assertFalse(self.client.get(f"{API}/leads/{lead.pk}/").json()["do_not_contact"])
        response = self.client.post(f"{API}/leads/{lead.pk}/do-not-contact/", {"reason": "complaint", "note": "x"}, format="json")
        self.assertEqual((response.status_code, response.json()["added"]), (201, 2))
        self.assertTrue(self.client.get(f"{API}/leads/{lead.pk}/").json()["do_not_contact"])
        rows = {r["id"]: r["do_not_contact"] for r in self.client.get(f"{API}/leads/").json()["results"]}
        self.assertEqual(rows, {lead.pk: True, other.pk: False})
        undone = self.client.delete(f"{API}/leads/{lead.pk}/do-not-contact/").json()
        self.assertEqual((undone["do_not_contact"], undone["removed"]), (False, 2))
        self.assertFalse(self.client.get(f"{API}/leads/{lead.pk}/").json()["do_not_contact"])

    def test_a_lead_with_nothing_to_list_is_a_clear_400(self):
        lead = make_lead(business_name="فقط نام")
        response = self.client.post(f"{API}/leads/{lead.pk}/do-not-contact/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ندارد", response.json()["detail"])

    def test_dashboard_block(self):
        suppression.add_entries([("phone", "09121234567", "09121234567")], "other", "", self.staff)
        block = self.client.get(f"{API}/dashboard/").json()["extra"]["compliance"]
        self.assertEqual(block, {"suppressed": 1, "emergency_stop": False, "sending_enabled": False})
        self.assertIn("compliance", registry._PROVIDERS)
