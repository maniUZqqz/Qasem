"""Draft building, duplicate detection and merging - the heart of the lead database."""
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.leads.choices import ActivityKind, ContactKind
from apps.growth_engine.leads.models import ContactPoint, Lead, LeadActivity
from apps.growth_engine.leads.services import dedupe, intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import LeadSource, SourceProvider

MANUAL = intake.SourceInfo(provider=SourceProvider.MANUAL, source_ref="manual")


def draft(**raw):
    d, errors = build_draft(raw, source_ref="manual")
    assert not errors, errors
    return d


def make_lead(**raw):
    raw.setdefault("business_name", "فروشگاه گل‌سرخ")
    return intake.create_from_draft(draft(**raw), MANUAL, None)


class BuildDraftTests(NoNetworkMixin, TestCase):
    def test_everything_is_normalised(self):
        d = draft(
            business_name="  فروشگاه  كتاب ", website="WWW.Shop.ir/?utm_source=x", instagram="@My.Shop",
            phone="۰۹۱۲ ۱۲۳ ۴۵۶۷ | 021-12345678", email="Info@Shop.IR", country="ایران", city=" تهران ",
            tags="vip, گل", category="پوشاک",
        )
        self.assertEqual(d.business_name, "فروشگاه کتاب")
        self.assertEqual(d.website.value, "https://shop.ir")
        self.assertEqual(d.instagram.normalized, "my.shop")
        self.assertEqual([c.value for c in d.contacts_of("phone")], ["09121234567", "02112345678"])
        self.assertEqual(d.contacts_of("email")[0].value, "info@shop.ir")
        self.assertEqual((d.country, d.city), ("IR", "تهران"))
        self.assertEqual(d.tags, ["vip", "گل"])

    def test_errors_are_collected_per_field(self):
        _, errors = build_draft({"business_name": "x", "phone": "123", "email": "bad", "instagram": "https://instagram.com/p/AAA/", "country": "Atlantis"})
        fields = sorted(e["field"] for e in errors)
        self.assertEqual(fields, ["country", "email", "instagram", "phone"])
        self.assertTrue(all(e["message"] for e in errors))

    def test_empty_row_is_an_error(self):
        _, errors = build_draft({"category": "x", "city": "y"})
        self.assertEqual([e["code"] for e in errors], ["empty_row"])

    def test_instagram_pasted_into_website_is_filed_as_instagram(self):
        d = draft(website="https://www.instagram.com/shop.ir/")
        self.assertIsNone(d.website)
        self.assertEqual(d.instagram.normalized, "shop.ir")

    def test_same_value_twice_in_one_row_is_kept_once(self):
        d = draft(phone="0912 123 4567, +98 912 123 4567")
        self.assertEqual(len(d.contacts_of("phone")), 1)

    def test_defaults_apply_only_when_the_cell_is_empty(self):
        d, errors = build_draft({"business_name": "a", "country": "ترکیه"}, default_country="IR", default_city="تهران")
        self.assertEqual((d.country, d.city), ("TR", "تهران"))
        d2, _ = build_draft({"business_name": "a"}, default_country="IR")
        self.assertEqual(d2.country, "IR")

    def test_too_long_values_are_reported(self):
        _, errors = build_draft({"business_name": "x" * 201})
        self.assertEqual(errors[0]["code"], "too_long")

    def test_payload_round_trip(self):
        d = draft(business_name="a", website="shop.ir", phone="09121234567", tags="t", address="خیابان ولیعصر")
        again = type(d).from_payload(d.to_payload())
        self.assertEqual(again.to_payload(), d.to_payload())


class CreateTests(NoNetworkMixin, TestCase):
    def test_create_records_fields_contacts_source_provenance_and_history(self):
        staff = make_staff()
        d, errors = build_draft(
            {"business_name": "گل‌سرخ", "website": "shop.ir", "phone": "09121234567", "email": "a@shop.ir", "tags": "vip", "note": "تماس اول", "city": "شیراز"},
            source_ref="csv:leads.csv:7",
        )
        self.assertFalse(errors)
        lead = intake.create_from_draft(d, intake.SourceInfo(SourceProvider.CSV_IMPORT, "csv:leads.csv:7", raw_data={"x": "y"}), staff)
        lead = Lead.objects.get(pk=lead.pk)
        self.assertEqual((lead.website, lead.origin, lead.status, lead.created_by_id), ("https://shop.ir", "csv_import", "new", staff.pk))
        self.assertEqual(lead.provenance["business_name"]["source"], "csv:leads.csv:7")
        self.assertEqual(lead.provenance["website"]["by"], staff.pk)
        self.assertEqual(sorted(lead.contacts.values_list("kind", flat=True)), ["email", "phone", "website"])
        self.assertTrue(all(c.is_primary for c in lead.contacts.all()))
        self.assertEqual(lead.contacts.get(kind="phone").source_ref, "csv:leads.csv:7")
        self.assertEqual([t.name for t in lead.tags.all()], ["vip"])
        self.assertEqual(lead.notes.get().body, "تماس اول")
        source = LeadSource.objects.get(lead=lead)
        self.assertEqual((source.provider, source.source_ref, source.raw_data), ("csv_import", "csv:leads.csv:7", {"x": "y"}))
        kinds = list(lead.activities.values_list("kind", flat=True))
        self.assertIn(ActivityKind.CREATED, kinds)
        self.assertIn(ActivityKind.NOTE_ADDED, kinds)

    def test_a_name_only_lead_is_valid(self):
        lead = make_lead(business_name="فقط نام")
        self.assertEqual(lead.contacts.count(), 0)
        self.assertEqual(lead.display_name, "فقط نام")

    def test_display_name_falls_back_to_host_or_handle_without_storing_it(self):
        lead = make_lead(business_name="", website="https://www.shop.ir/a")
        self.assertEqual((lead.business_name, lead.display_name), ("", "shop.ir"))
        lead2 = make_lead(business_name="", instagram="@abc")
        self.assertEqual(lead2.display_name, "@abc")


class DuplicateDetectionTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        super_setup = make_lead(
            business_name="فروشگاه الف", website="https://www.shop.ir/", instagram="https://instagram.com/shop.ir",
            phone="09121234567", email="info@shop.ir",
        )
        self.lead = super_setup

    def assertDuplicate(self, kind, **raw):
        other = draft(business_name="کسب‌وکار دیگر", **raw)
        with self.assertRaises(intake.DuplicateError) as ctx:
            intake.create_from_draft(other, MANUAL, None)
        match = ctx.exception.matches[0]
        self.assertEqual(match.lead.pk, self.lead.pk)
        self.assertIn(kind, [m["kind"] for m in match.matched_on])
        self.assertEqual(Lead.objects.count(), 1, "nothing may be written for a duplicate")

    def test_website_in_every_form(self):
        for url in ["http://shop.ir", "SHOP.IR/products?utm_campaign=x", "https://shop.ir:443/", "//www.shop.ir/about"]:
            with self.subTest(url=url):
                self.assertDuplicate("website", website=url)

    def test_instagram_in_every_form(self):
        for ig in ["@Shop.IR", "shop.ir", "https://www.instagram.com/shop.ir/?hl=fa", "instagram.com/_u/shop.ir"]:
            with self.subTest(ig=ig):
                self.assertDuplicate("instagram", instagram=ig)

    def test_phone_in_every_notation(self):
        for phone in ["9121234567", "+98 912 123 4567", "۰۹۱۲۱۲۳۴۵۶۷", "0912-123-4567", "00989121234567"]:
            with self.subTest(phone=phone):
                self.assertDuplicate("phone", phone=phone)

    def test_email_case_insensitive(self):
        self.assertDuplicate("email", email="INFO@Shop.IR")

    def test_same_name_alone_is_not_a_duplicate_but_is_reported_as_similar(self):
        new = make_lead(business_name="فروشگاه  الف")  # same name, different spacing, no identifiers
        self.assertEqual(Lead.objects.count(), 2)
        self.assertEqual([lead.pk for lead in dedupe.find_similar_by_name("فروشگاه الف", exclude_ids=(new.pk,))], [self.lead.pk])

    def test_archived_leads_still_own_their_identifiers(self):
        Lead.objects.filter(pk=self.lead.pk).update(is_archived=True)
        self.assertDuplicate("phone", phone="09121234567")

    def test_matches_are_ordered_best_first(self):
        second = make_lead(business_name="دوم", phone="09350000000")
        d = draft(phone="09350000000", website="shop.ir")
        matches = dedupe.find_duplicates_for_draft(d)
        self.assertEqual([m.lead.pk for m in matches], [self.lead.pk, second.pk][: len(matches)])
        self.assertEqual(len(matches), 2)

    def test_database_constraint_is_the_last_line_of_defence(self):
        other = make_lead(business_name="دیگری")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContactPoint.objects.create(lead=other, kind=ContactKind.PHONE, value="09121234567", normalized="09121234567")
        # non-identifier kinds may repeat
        ContactPoint.objects.create(lead=other, kind=ContactKind.TELEGRAM, value="https://t.me/x", normalized="x")
        ContactPoint.objects.create(lead=self.lead, kind=ContactKind.TELEGRAM, value="https://t.me/x", normalized="x")

    def test_a_lost_race_is_reported_as_a_duplicate_not_a_crash(self):
        d = draft(business_name="رقابت", phone="09121234567")
        with mock.patch.object(intake, "find_duplicates_for_draft", side_effect=[[], dedupe.find_duplicates_for_draft(d)]):
            with self.assertRaises(intake.DuplicateError):
                intake.create_from_draft(d, MANUAL, None)
        self.assertEqual(Lead.objects.count(), 1)


class MergeTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.lead = make_lead(business_name="گل‌سرخ", website="shop.ir", phone="09121234567", city="تهران")
        self.src = intake.SourceInfo(SourceProvider.CSV_IMPORT, "csv:f.csv:3", raw_data={"a": 1})

    def test_empty_fields_are_filled_conflicts_are_kept(self):
        d = draft(business_name="گل سرخ تهران", website="shop.ir", category="گل", city="اصفهان", email="a@shop.ir", instagram="@gol")
        result = intake.merge_draft_into(self.lead, d, self.src, self.staff)
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual((lead.category, lead.city, lead.business_name), ("گل", "تهران", "گل‌سرخ"))
        self.assertIn("category", result.filled)
        self.assertEqual([c["field"] for c in result.conflicts], ["business_name", "city"])
        self.assertEqual(result.conflicts[1]["existing"], "تهران")
        self.assertEqual(lead.provenance["category"]["source"], "csv:f.csv:3")
        self.assertEqual(lead.provenance["business_name"]["source"], "manual")  # untouched
        self.assertEqual(lead.instagram_url, "https://www.instagram.com/gol/")
        self.assertEqual(sorted(c["kind"] for c in result.added_contacts), ["email", "instagram"])

    def test_nothing_is_overwritten_unless_the_user_names_the_field(self):
        d = draft(business_name="نام تازه", city="اصفهان", phone="09121234567")
        result = intake.merge_draft_into(self.lead, d, self.src, self.staff, overwrite_fields=["city", "bogus"])
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual((lead.city, lead.business_name), ("اصفهان", "گل‌سرخ"))
        self.assertEqual(result.overwritten, ["city"])
        self.assertEqual(lead.provenance["city"]["source"], "csv:f.csv:3")

    def test_known_contacts_are_not_duplicated_and_foreign_ones_are_not_stolen(self):
        other = make_lead(business_name="دیگری", email="x@other.ir")
        d = draft(phone="09121234567", email="x@other.ir", whatsapp="09121234567")
        result = intake.merge_draft_into(self.lead, d, self.src, self.staff)
        self.assertEqual(self.lead.contacts.filter(kind="phone").count(), 1)
        self.assertEqual([c["kind"] for c in result.skipped_contacts], ["email"])
        self.assertEqual(result.skipped_contacts[0]["lead_id"], other.pk)
        self.assertEqual(other.contacts.filter(kind="email").count(), 1)
        self.assertEqual([c["kind"] for c in result.added_contacts], ["whatsapp"])

    def test_source_history_and_tags_and_note(self):
        d = draft(phone="09121234567", tags="جدید, vip", note="یادداشت ادغام")
        intake.merge_draft_into(self.lead, d, self.src, self.staff)
        self.assertEqual(LeadSource.objects.filter(lead=self.lead).count(), 2)
        self.assertEqual(sorted(t.name for t in self.lead.tags.all()), ["vip", "جدید"])
        self.assertEqual(self.lead.notes.count(), 1)
        activity = LeadActivity.objects.filter(lead=self.lead, kind=ActivityKind.MERGED).get()
        self.assertEqual(activity.source_ref, "csv:f.csv:3")
        self.assertEqual(activity.actor_id, self.staff.pk)

    def test_plan_is_read_only(self):
        d = draft(business_name="گل‌سرخ", category="گل", email="n@shop.ir")
        before = (Lead.objects.count(), ContactPoint.objects.count(), LeadSource.objects.count())
        plan = intake.plan_merge(self.lead, d)
        self.assertEqual(before, (Lead.objects.count(), ContactPoint.objects.count(), LeadSource.objects.count()))
        states = {x.field: x.state for x in plan.decisions}
        self.assertEqual(states, {"business_name": "same", "category": "fill"})
        self.assertEqual([c.kind for c in plan.new_contacts], ["email"])

    def test_profile_fields_fill_only(self):
        first = draft(phone="09121234567", address="خیابان اول", language="fa", product_categories="گل, گلدان")
        intake.merge_draft_into(self.lead, first, self.src, self.staff)
        second = draft(phone="09121234567", address="خیابان دوم", product_categories="گلدان, کاکتوس")
        result = intake.merge_draft_into(self.lead, second, self.src, self.staff)
        profile = Lead.objects.get(pk=self.lead.pk).profile
        self.assertEqual(profile.address, "خیابان اول")
        self.assertEqual(profile.product_categories, ["گل", "گلدان", "کاکتوس"])
        self.assertIn("address", [c["field"] for c in result.conflicts])
