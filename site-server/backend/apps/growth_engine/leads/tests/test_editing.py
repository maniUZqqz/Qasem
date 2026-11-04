from django.test import TestCase

from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.leads.choices import ActivityKind
from apps.growth_engine.leads.models import Lead, LeadActivity
from apps.growth_engine.leads.services import bulk, editing, intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.sources.models import SourceProvider


def make_lead(**raw):
    raw.setdefault("business_name", "گل‌سرخ")
    d, errors = build_draft(raw)
    assert not errors
    return intake.create_from_draft(d, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)


class UpdateTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.lead = make_lead(website="shop.ir", instagram="@shop", phone="09121234567")

    def test_edit_stamps_provenance_and_logs_the_old_and_new_value(self):
        changed = editing.update_lead(self.lead, {"business_name": "نام تازه", "city": "تبریز", "category": ""}, self.staff)
        self.assertEqual(sorted(changed), ["business_name", "city"])
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual(lead.provenance["city"]["source"], "manual")
        self.assertEqual(lead.name_key, "نامتازه")
        activity = LeadActivity.objects.filter(lead=lead, kind=ActivityKind.UPDATED).get()
        self.assertEqual(activity.data["changes"]["business_name"], {"old": "گل‌سرخ", "new": "نام تازه"})
        self.assertEqual(activity.actor_id, self.staff.pk)

    def test_no_change_no_history(self):
        before = LeadActivity.objects.count()
        self.assertEqual(editing.update_lead(self.lead, {"business_name": "گل‌سرخ", "city": ""}, self.staff), [])
        self.assertEqual(LeadActivity.objects.count(), before)

    def test_status_change_is_logged_separately_and_validated(self):
        editing.update_lead(self.lead, {"status": "contacted"}, self.staff)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).status, "contacted")
        self.assertTrue(LeadActivity.objects.filter(lead=self.lead, kind=ActivityKind.STATUS_CHANGED, data={"old": "new", "new": "contacted"}).exists())
        with self.assertRaises(editing.ValidationFailed):
            editing.update_lead(self.lead, {"status": "nonsense"}, self.staff)

    def test_validation_errors_change_nothing(self):
        with self.assertRaises(editing.ValidationFailed) as ctx:
            editing.update_lead(self.lead, {"business_name": "x", "country": "Atlantis", "website": "not a url"}, self.staff)
        self.assertEqual(sorted(e["field"] for e in ctx.exception.errors), ["country", "website"])
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).business_name, "گل‌سرخ")

    def test_changing_the_website_keeps_the_identifier_registry_in_step(self):
        editing.update_lead(self.lead, {"website": "https://new-shop.ir/x?utm_source=a"}, self.staff)
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual(lead.website, "https://new-shop.ir/x")
        self.assertEqual(lead.contacts.filter(kind="website").count(), 1)
        self.assertEqual(lead.contacts.get(kind="website").normalized, "new-shop.ir")
        # the old address is free again
        other = make_lead(business_name="دیگری", website="shop.ir")
        self.assertEqual(other.website, "https://shop.ir")

    def test_taking_another_leads_identifier_is_refused(self):
        other = make_lead(business_name="دیگری", website="other.ir", instagram="@other")
        with self.assertRaises(intake.DuplicateError) as ctx:
            editing.update_lead(self.lead, {"website": "https://www.other.ir"}, self.staff)
        self.assertEqual(ctx.exception.matches[0].lead.pk, other.pk)
        with self.assertRaises(intake.DuplicateError):
            editing.update_lead(self.lead, {"instagram_url": "instagram.com/other"}, self.staff)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).website, "https://shop.ir")

    def test_clearing_the_website_removes_its_contact(self):
        editing.update_lead(self.lead, {"website": ""}, self.staff)
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual(lead.website, "")
        self.assertFalse(lead.contacts.filter(kind="website").exists())

    def test_profile_and_tags(self):
        editing.update_lead(self.lead, {"profile": {"address": "خیابان ولیعصر", "business_type": "online_store", "product_names": ["a", "b"]}, "tags": ["vip", "گرم"]}, self.staff)
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual((lead.profile.address, lead.profile.business_type, lead.profile.product_names), ("خیابان ولیعصر", "online_store", ["a", "b"]))
        self.assertEqual(lead.profile.provenance["address"]["source"], "manual")
        self.assertEqual(sorted(t.name for t in lead.tags.all()), ["vip", "گرم"])
        editing.update_lead(self.lead, {"tags": ["vip"]}, self.staff)
        self.assertEqual([t.name for t in lead.tags.all()], ["vip"])
        kinds = list(LeadActivity.objects.filter(lead=lead).values_list("kind", flat=True))
        self.assertIn(ActivityKind.TAG_ADDED, kinds)
        self.assertIn(ActivityKind.TAG_REMOVED, kinds)

    def test_archive_toggle(self):
        editing.update_lead(self.lead, {"is_archived": True}, self.staff)
        self.assertTrue(Lead.objects.get(pk=self.lead.pk).is_archived)
        self.assertTrue(LeadActivity.objects.filter(lead=self.lead, kind=ActivityKind.ARCHIVED).exists())


class ContactTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.lead = make_lead(phone="09121234567")

    def test_add_normalises_and_first_of_a_kind_is_primary(self):
        c1 = editing.add_contact(self.lead, "phone", "۰۲۱-۱۲۳۴۵۶۷۸", label="دفتر", actor=self.staff)
        self.assertEqual((c1.value, c1.is_primary, c1.label, c1.source_ref), ("02112345678", False, "دفتر", "manual"))
        email = editing.add_contact(self.lead, "email", "A@Shop.ir", actor=self.staff)
        self.assertTrue(email.is_primary)

    def test_duplicates_are_refused(self):
        other = make_lead(business_name="دیگری", email="x@y.ir")
        with self.assertRaises(intake.DuplicateError):
            editing.add_contact(self.lead, "email", "X@Y.ir", actor=self.staff)
        with self.assertRaises(editing.ValidationFailed):
            editing.add_contact(self.lead, "phone", "0912 123 4567", actor=self.staff)  # already on this lead
        with self.assertRaises(editing.ValidationFailed):
            editing.add_contact(self.lead, "phone", "12", actor=self.staff)
        self.assertEqual(other.contacts.count(), 1)

    def test_website_contact_syncs_lead_field_and_removal_falls_back(self):
        a = editing.add_contact(self.lead, "website", "a.ir", actor=self.staff)
        editing.add_contact(self.lead, "website", "b.ir", actor=self.staff)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).website, "https://a.ir")
        editing.remove_contact(a, self.staff)
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual(lead.website, "https://b.ir")
        self.assertTrue(lead.contacts.get(kind="website").is_primary)

    def test_update_value_label_and_primary(self):
        second = editing.add_contact(self.lead, "phone", "09350000000", actor=self.staff)
        editing.update_contact(second, {"label": "مدیر", "is_primary": True}, self.staff)
        self.assertEqual(self.lead.contacts.filter(kind="phone", is_primary=True).get().pk, second.pk)
        editing.update_contact(second, {"value": "0935 111 2222"}, self.staff)
        second.refresh_from_db()
        self.assertEqual((second.value, second.normalized, second.source_ref), ("09351112222", "09351112222", "manual"))
        with self.assertRaises(editing.ValidationFailed):  # the lead already has this number
            editing.update_contact(second, {"value": "09121234567"}, self.staff)
        other = make_lead(business_name="دیگری", phone="09370000000")
        with self.assertRaises(intake.DuplicateError):  # another lead owns this number
            editing.update_contact(second, {"value": "09370000000"}, self.staff)
        self.assertEqual(other.contacts.count(), 1)

    def test_every_contact_change_is_in_the_history(self):
        c = editing.add_contact(self.lead, "email", "a@b.ir", actor=self.staff)
        editing.update_contact(c, {"label": "x"}, self.staff)
        editing.remove_contact(c, self.staff)
        kinds = set(LeadActivity.objects.filter(lead=self.lead).values_list("kind", flat=True))
        self.assertTrue({ActivityKind.CONTACT_ADDED, ActivityKind.CONTACT_UPDATED, ActivityKind.CONTACT_REMOVED} <= kinds)


class NoteTests(NoNetworkMixin, TestCase):
    def test_notes_add_edit_delete_are_logged(self):
        staff = make_staff()
        lead = make_lead()
        note = editing.add_note(lead, "  اولین تماس  ", staff)
        self.assertEqual(note.body, "اولین تماس")
        editing.edit_note(note, "تماس دوم", staff)
        editing.delete_note(note, staff)
        kinds = list(LeadActivity.objects.filter(lead=lead).order_by("id").values_list("kind", flat=True))
        self.assertEqual(kinds[-3:], [ActivityKind.NOTE_ADDED, ActivityKind.NOTE_EDITED, ActivityKind.NOTE_DELETED])
        with self.assertRaises(editing.ValidationFailed):
            editing.add_note(lead, "   ", staff)


class HistoryTests(NoNetworkMixin, TestCase):
    def test_history_rows_cannot_be_edited(self):
        lead = make_lead()
        activity = LeadActivity.objects.filter(lead=lead).first()
        activity.summary = "tampered"
        with self.assertRaises(ValueError):
            activity.save()


class BulkTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.leads = [make_lead(business_name=f"لید {i}", phone=f"0912000000{i}") for i in range(4)]
        self.ids = [lead.pk for lead in self.leads]

    def test_set_status_only_touches_changing_leads_and_logs_each(self):
        Lead.objects.filter(pk=self.ids[0]).update(status="qualified")
        result = bulk.bulk_action(self.ids, "set_status", {"status": "qualified"}, self.staff)
        self.assertEqual(result["affected"], 3)
        self.assertEqual(Lead.objects.filter(status="qualified").count(), 4)
        self.assertEqual(LeadActivity.objects.filter(kind=ActivityKind.STATUS_CHANGED).count(), 3)

    def test_tag_add_and_remove(self):
        self.assertEqual(bulk.bulk_action(self.ids, "add_tag", {"tag": "کمپین ۱"}, self.staff)["affected"], 4)
        self.assertEqual(bulk.bulk_action(self.ids, "add_tag", {"tag": "کمپین‌۱"}, self.staff)["affected"], 0)  # same tag, different spelling
        self.assertEqual(bulk.bulk_action(self.ids[:2], "remove_tag", {"tag": "کمپین ۱"}, self.staff)["affected"], 2)
        self.assertEqual(Lead.objects.filter(tags__name="کمپین ۱").count(), 2)

    def test_archive_and_delete(self):
        bulk.bulk_action(self.ids[:2], "archive", {}, self.staff)
        self.assertEqual(Lead.objects.filter(is_archived=True).count(), 2)
        bulk.bulk_action(self.ids[:2], "unarchive", {}, self.staff)
        self.assertEqual(Lead.objects.filter(is_archived=True).count(), 0)
        with self.assertRaises(editing.ValidationFailed):
            bulk.bulk_action(self.ids, "delete", {}, self.staff)
        self.assertEqual(bulk.bulk_action(self.ids, "delete", {"confirm": True}, self.staff)["affected"], 4)
        self.assertEqual(Lead.objects.count(), 0)

    def test_guards(self):
        for args in [([], "archive"), (self.ids, "explode"), (list(range(1, 600)), "archive")]:
            with self.subTest(action=args[1]), self.assertRaises(editing.ValidationFailed):
                bulk.bulk_action(args[0], args[1], {}, self.staff)
        self.assertEqual(bulk.bulk_action([self.ids[0], 999999], "archive", {}, self.staff)["missing"], 1)
