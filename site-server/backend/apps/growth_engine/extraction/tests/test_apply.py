"""Saving findings: provenance, fill-only fields, no duplicates, never stealing another lead's identifier."""
from django.test import TestCase

from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.extraction.models import ExtractionRun
from apps.growth_engine.extraction.services import apply
from apps.growth_engine.extraction.services.parser import Finding
from apps.growth_engine.leads.choices import ActivityKind
from apps.growth_engine.leads.models import ContactPoint, Lead, LeadActivity
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import LeadSource, SourceProvider


def make_lead(**raw):
    raw.setdefault("business_name", "گل‌سرخ")
    raw.setdefault("website", "golsorkh.ir")
    draft, errors = build_draft(raw)
    assert not errors, errors
    return intake.create_from_draft(draft, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


def finding(field, value, key="", confidence=75, evidence="شاهد", url="https://golsorkh.ir/contact-us", label=""):
    return Finding(field=field, value=value, key=key or value, source_url=url, evidence=evidence, confidence=confidence, label=label)


class ApplyTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.lead = make_lead()
        self.run = ExtractionRun.objects.create(lead=self.lead)

    def apply(self, *findings, lead=None):
        return apply.apply_findings(lead or self.lead, self.run, list(findings), actor=self.staff, home_url="https://golsorkh.ir/", pages=["https://golsorkh.ir/"])

    def reasons(self, result):
        return [(r["field"], r["reason"], r["applied"]) for r in result.records]

    def test_contacts_are_saved_with_source_page_evidence_confidence_and_run_provenance(self):
        result = self.apply(
            finding("phone", "02112345678", confidence=90, evidence="لینک tel:", url="https://golsorkh.ir/"),
            finding("email", "info@golsorkh.ir", confidence=80),
            finding("telegram", "https://t.me/golsorkh_shop", key="golsorkh_shop", confidence=85),
            finding("contact_form", "https://golsorkh.ir/contact-us", confidence=85, label="فرم تماس"),
        )
        self.assertEqual(result.contacts_added, 4)
        self.assertEqual(self.reasons(result), [("phone", "added", True), ("email", "added", True), ("telegram", "added", True), ("contact_form", "added", True)])
        phone = ContactPoint.objects.get(lead=self.lead, kind="phone")
        self.assertEqual((phone.value, phone.source_ref, phone.source_url, phone.evidence, phone.confidence, phone.is_primary), ("02112345678", f"extract:{self.run.pk}", "https://golsorkh.ir/", "لینک tel:", 90, True))
        form = ContactPoint.objects.get(lead=self.lead, kind="contact_form")
        self.assertEqual((form.label, form.normalized, form.value), ("فرم تماس", "https://golsorkh.ir/contact-us", "https://golsorkh.ir/contact-us"))
        self.assertEqual(result.records[0]["source_url"], "https://golsorkh.ir/")

    def test_a_source_and_a_history_row_are_written(self):
        self.apply(finding("phone", "02112345678"))
        source = LeadSource.objects.get(lead=self.lead, provider=SourceProvider.CONTACT_EXTRACTION)
        self.assertEqual((source.source_ref, source.source_url, source.created_by_id), (f"extract:{self.run.pk}", "https://golsorkh.ir/", self.staff.pk))
        self.assertEqual(source.raw_data["contacts_added"], 1)
        self.assertEqual(source.job_id, None)

    def test_nothing_new_writes_no_source(self):
        self.apply(finding("phone", "02112345678"))
        before = LeadSource.objects.filter(lead=self.lead).count()
        self.apply(finding("phone", "02112345678"))
        self.assertEqual(LeadSource.objects.filter(lead=self.lead).count(), before)

    def test_a_value_the_lead_already_has_is_not_duplicated(self):
        lead = make_lead(business_name="دارای شماره", website="has-phone.ir", phone="0912 111 2233", email="a@has-phone.ir")
        result = self.apply(finding("phone", "09121112233"), finding("email", "A@Has-Phone.IR", key="a@has-phone.ir"), lead=lead)
        self.assertEqual(self.reasons(result), [("phone", "already_known", False), ("email", "already_known", False)])
        self.assertEqual(lead.contacts.filter(kind="phone").count(), 1)
        self.assertEqual(result.contacts_added, 0)
        # a second run over the same findings adds nothing either
        again = self.apply(finding("phone", "02112345678"), finding("phone", "02112345678"))
        self.assertEqual(ContactPoint.objects.filter(lead=self.lead, kind="phone").count(), 1)
        self.assertEqual([r["reason"] for r in again.records], ["added", "already_known"])

    def test_an_identifier_of_another_lead_is_never_taken(self):
        other = make_lead(business_name="دیگری", website="other.ir", phone="09125556677", email="x@other.ir", instagram="@other_shop")
        result = self.apply(
            finding("phone", "09125556677"), finding("email", "x@other.ir"),
            finding("instagram", "https://www.instagram.com/other_shop/", key="other_shop"), finding("phone", "02100000001"),
        )
        self.assertEqual(self.reasons(result), [("phone", "owned_by_other_lead", False), ("email", "owned_by_other_lead", False), ("instagram", "owned_by_other_lead", False), ("phone", "added", True)])
        self.assertEqual(other.contacts.filter(kind="phone").count(), 1)
        self.assertEqual(self.lead.contacts.filter(kind__in=["email", "instagram"]).count(), 0)
        self.assertEqual(self.lead.instagram_url, "")

    def test_a_race_for_an_identifier_is_reported_not_raised(self):
        from unittest import mock

        real_create = ContactPoint.objects.create

        def lose_the_race(**kwargs):
            if kwargs.get("kind") == "email":
                from django.db import IntegrityError

                raise IntegrityError("unique")
            return real_create(**kwargs)

        with mock.patch.object(ContactPoint.objects, "create", side_effect=lose_the_race):
            result = self.apply(finding("email", "late@golsorkh.ir"), finding("phone", "02112345678"))
        self.assertEqual(self.reasons(result), [("email", "owned_by_other_lead", False), ("phone", "added", True)])

    def test_values_that_do_not_normalise_are_marked_invalid(self):
        result = self.apply(finding("phone", "12"), finding("email", "nope"), finding("instagram", "https://instagram.com/p/AAA/", key="p"), finding("bogus", "x"))
        self.assertEqual([r["reason"] for r in result.records], ["invalid"] * 4)
        self.assertEqual(self.lead.contacts.exclude(kind="website").count(), 0)

    def test_the_first_contact_of_a_kind_is_primary_later_ones_are_not(self):
        self.apply(finding("phone", "02112345678"), finding("phone", "09123456789"))
        phones = list(ContactPoint.objects.filter(lead=self.lead, kind="phone").order_by("id"))
        self.assertEqual([p.is_primary for p in phones], [True, False])

    def test_instagram_fills_the_lead_field_only_when_it_is_empty(self):
        self.apply(finding("instagram", "https://www.instagram.com/golsorkh.shop/", key="golsorkh.shop", confidence=85))
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual(lead.instagram_url, "https://www.instagram.com/golsorkh.shop/")
        self.assertEqual(lead.provenance["instagram_url"]["source"], f"extract:{self.run.pk}")
        self.apply(finding("instagram", "https://www.instagram.com/another.handle/", key="another.handle"))
        lead.refresh_from_db()
        self.assertEqual(lead.instagram_url, "https://www.instagram.com/golsorkh.shop/")  # kept
        self.assertTrue(ContactPoint.objects.filter(lead=lead, kind="instagram", normalized="another.handle").exists())  # the page does show it

    def test_lead_fields_are_fill_only_with_provenance(self):
        lead = make_lead(business_name="", website="bare.ir")
        result = self.apply(
            finding("business_name", "فروشگاه گل‌سرخ", confidence=80), finding("description", "توضیح کوتاه فروشگاه", confidence=60),
            finding("city", "تهران", confidence=80), finding("address", "تهران، خیابان ولیعصر، پلاک ۱۲", confidence=90), finding("language", "fa", confidence=70),
            lead=lead,
        )
        self.assertEqual([r["reason"] for r in result.records], ["fill_empty"] * 5)
        self.assertEqual(sorted(result.fields_filled), ["address", "business_name", "city", "description", "language"])
        lead.refresh_from_db()
        self.assertEqual((lead.business_name, lead.city, lead.description), ("فروشگاه گل‌سرخ", "تهران", "توضیح کوتاه فروشگاه"))
        self.assertEqual(lead.name_key, "فروشگاهگلسرخ")  # the search key follows the name
        for name in ("business_name", "city", "description"):
            self.assertEqual(lead.provenance[name]["source"], f"extract:{self.run.pk}", name)
        profile = lead.profile
        self.assertEqual((profile.address, profile.language), ("تهران، خیابان ولیعصر، پلاک ۱۲", "fa"))
        self.assertEqual(profile.provenance["address"]["source"], f"extract:{self.run.pk}")
        source = LeadSource.objects.get(lead=lead, provider=SourceProvider.CONTACT_EXTRACTION)
        self.assertEqual(source.raw_data["fields_filled"], result.fields_filled)

    def test_existing_values_are_kept_and_reported(self):
        lead = make_lead(business_name="نام ما", website="mine.ir", city="شیراز", description="توضیحِ خودمان")
        profile_lead = lead
        from apps.growth_engine.leads.services import editing

        editing.update_lead(profile_lead, {"profile": {"address": "نشانی ما", "language": "fa"}}, self.staff)
        result = self.apply(
            finding("business_name", "نام سایت"), finding("city", "تهران"), finding("description", "توضیحِ خودمان"),
            finding("address", "نشانی سایت"), finding("language", "fa"), lead=lead,
        )
        self.assertEqual([r["reason"] for r in result.records], ["kept_existing", "kept_existing", "already_known", "kept_existing", "already_known"])
        lead.refresh_from_db()
        self.assertEqual((lead.business_name, lead.city, lead.profile.address), ("نام ما", "شیراز", "نشانی ما"))
        self.assertEqual(result.fields_filled, [])
        self.assertEqual(lead.provenance["business_name"]["source"], "manual")
        self.assertFalse(LeadSource.objects.filter(lead=lead, provider=SourceProvider.CONTACT_EXTRACTION).exists())

    def test_the_website_of_the_lead_is_never_changed(self):
        self.apply(finding("business_name", "x y"), finding("phone", "02112345678"))
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).website, "https://golsorkh.ir")
        self.assertEqual(ContactPoint.objects.filter(lead=self.lead, kind="website").count(), 1)

    def test_the_run_activity_is_logged_with_the_run_as_source(self):
        apply.log_run_activity(self.lead, self.run, "استخراج از سایت: ۱ راهِ تماسِ تازه", {"run_id": self.run.pk}, actor=self.staff)
        activity = LeadActivity.objects.get(lead=self.lead, kind=ActivityKind.EXTRACTION)
        self.assertEqual((activity.source_ref, activity.actor_id, activity.data["run_id"]), (f"extract:{self.run.pk}", self.staff.pk, self.run.pk))

    def test_a_failure_inside_rolls_the_whole_apply_back(self):
        from unittest import mock

        with mock.patch.object(apply, "_fill_lead_field", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
            self.apply(finding("phone", "02112345678"), finding("city", "تهران"))
        self.assertFalse(ContactPoint.objects.filter(lead=self.lead, kind="phone").exists())
