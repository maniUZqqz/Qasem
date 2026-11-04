"""The product knowledge (CRUD, defaults that are true, the empty price) and the default templates."""
from __future__ import annotations

import re

from django.test import TestCase

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.knowledge.models import KnowledgeItem
from apps.growth_engine.knowledge.services import kb, seed, seed_data
from apps.growth_engine.outreach.channels import sms
from apps.growth_engine.outreach.models import Channel, MessageTemplate
from apps.growth_engine.outreach.services import generators, rendering, templates

from apps.growth_engine.outreach.tests.helpers import configure, make_lead

G = "/api/v1/growth"


class DefaultsTests(NoNetworkMixin, TestCase):
    def test_the_test_database_starts_without_defaults_and_seeding_is_explicit(self):
        self.assertEqual(KnowledgeItem.objects.count(), 0)
        self.assertEqual(MessageTemplate.objects.count(), 0)
        seed.seed_after_migrate()  # under IS_TEST this must not seed (tests seed on purpose)
        self.assertEqual(KnowledgeItem.objects.count(), 0)

    def test_seeding_is_idempotent_and_never_touches_what_was_edited_or_deleted(self):
        first = seed.restore_defaults()
        self.assertEqual((first["knowledge"], first["templates"]), (len(seed_data.KNOWLEDGE), len(seed_data.TEMPLATES)))
        self.assertEqual(seed.restore_defaults(), {"knowledge": 0, "templates": 0})
        edited = KnowledgeItem.objects.get(seed_key="trial")
        edited.body = "متنِ ویرایش‌شدهٔ من"
        edited.save()
        KnowledgeItem.objects.filter(seed_key="poster").delete()
        MessageTemplate.objects.filter(seed_key="sms").update(body="ویرایش")
        again = seed.restore_defaults()
        self.assertEqual(again, {"knowledge": 1, "templates": 0})
        self.assertEqual(KnowledgeItem.objects.get(seed_key="trial").body, "متنِ ویرایش‌شدهٔ من")
        self.assertEqual(MessageTemplate.objects.get(seed_key="sms").body, "ویرایش")

    def test_the_price_is_empty_until_a_person_types_it(self):
        seed.restore_defaults()
        price = KnowledgeItem.objects.get(section="price")
        self.assertEqual(price.body, "")
        self.assertTrue(price.needs_value)
        self.assertEqual(kb.item_json(price)["needs_value_hint"], "قیمت را وارد کنید")
        self.assertIn("قیمت را وارد کنید", price.note)

    def test_nothing_invented_no_currency_no_percentages_no_customer_counts_no_testimonials(self):
        seed.restore_defaults()
        every_text = " ".join(f"{k.title} {k.body}" for k in KnowledgeItem.objects.exclude(section="price")) + " " + " ".join(f"{t.subject} {t.body}" for t in MessageTemplate.objects.all())
        for forbidden in ("تومان", "ریال", "%", "٪", "تخفیف", "مشتری راضی", "هزار مشتری", "رتبه", "جایزه", "تضمین"):
            self.assertNotIn(forbidden, every_text, forbidden)
        # the only numbers: "5 seconds" per shot, "24 hours" of support, "2 weeks" of trial (all on the public pages)
        digits = {re.sub(r"[^0-9]", "", d) for d in re.findall(r"[0-9۰-۹]+", every_text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))}
        self.assertLessEqual(digits - {""}, {"5", "24", "2"})

    def test_internal_tools_are_seeded_inactive_for_the_owner_to_decide(self):
        seed.restore_defaults()
        for key in ("site_builder", "video3d"):
            item = KnowledgeItem.objects.get(seed_key=key)
            self.assertFalse(item.is_active)
            self.assertTrue(item.note)
        self.assertTrue(KnowledgeItem.objects.get(seed_key="trial").is_active)

    def test_limitations_are_there_and_say_so_plainly(self):
        seed.restore_defaults()
        limits = KnowledgeItem.objects.filter(section="limitation", is_active=True)
        self.assertGreaterEqual(limits.count(), 3)
        self.assertTrue(any("آزمایشی" in k.body for k in limits))
        self.assertTrue(any("صفِ رندر" in k.body for k in limits))

    def test_one_default_template_per_channel_each_tied_to_its_channel(self):
        seed.restore_defaults()
        self.assertEqual({t.channel for t in MessageTemplate.objects.all()}, {c.value for c in Channel})
        for template in MessageTemplate.objects.all():
            self.assertTrue(template.seed_key)
            self.assertEqual(template.seed_key, template.channel)
            self.assertEqual(template.language, "fa")

    def test_every_default_template_passes_the_template_rules(self):
        seed.restore_defaults()
        for template in MessageTemplate.objects.all():
            templates.validate({"name": template.name, "body": template.body, "subject": template.subject, "channel": template.channel})

    def test_every_default_template_renders_for_a_real_lead_in_its_channel_form(self):
        configure()
        seed.restore_defaults()
        lead = make_lead("def.ir", email="info@def.ir", name="فروشگاه رها", city="همدان", category="پوشاک")
        settings_obj = GrowthSettings.load()
        for template in MessageTemplate.objects.all():
            built = generators.build_message(template, lead, settings_obj, template.channel)
            self.assertNotIn("{", built.text, template.seed_key)
            self.assertNotIn("}", built.text)
            if template.channel not in ("phone_call",):
                self.assertIn("اگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو».", built.text, template.seed_key)
            if template.channel in ("contact_form", "email"):
                self.assertTrue(built.subject)
                self.assertNotIn("{", built.subject)
        email = generators.build_message(MessageTemplate.objects.get(seed_key="email"), lead, settings_obj, "email")
        self.assertIn("فروشگاه رها", email.text)
        self.assertIn("آپ‌مارکت", email.text)  # {company} from Growth Settings
        call = generators.build_message(MessageTemplate.objects.get(seed_key="phone_call"), lead, settings_obj, "phone_call")
        self.assertIn("همدان", call.text)
        self.assertIn("پوشاک می‌فروشد", call.text)

    def test_the_default_sms_fits_two_parts_with_the_short_closing_block(self):
        configure()
        seed.restore_defaults()
        lead = make_lead("sms.ir", phone="09125550099")
        built = generators.build_message(MessageTemplate.objects.get(seed_key="sms"), lead, GrowthSettings.load(), "sms")
        seg = sms.segments(built.text)
        self.assertLessEqual(seg["parts"], 2, (seg, built.text))
        self.assertTrue(built.text.endswith("«لغو»."))

    def test_placeholders_company_and_sender_name_come_from_growth_settings(self):
        configure(sender_company="شرکتِ نمونه", sender_name="علی رضایی")
        lead = make_lead("ph.ir")
        template = MessageTemplate.objects.create(name="ت", body="از {company}، {sender_name}")
        self.assertEqual(generators.build_message(template, lead, GrowthSettings.load()).text.splitlines()[0], "از شرکتِ نمونه، علی رضایی")
        keys = [p["key"] for p in client_for(make_staff()).get(f"{G}/outreach/placeholders/").json()]
        self.assertIn("company", keys)
        self.assertIn("sender_name", keys)

    def test_the_default_templates_are_not_deleted_by_accident(self):
        seed.restore_defaults()
        template = MessageTemplate.objects.get(seed_key="email")
        from apps.growth_engine.outreach.services import campaigns

        campaigns.create_campaign(name="ک", template=template, mode="auto", channel="email")
        with self.assertRaises(Exception):
            templates.delete(template)


class KnowledgeApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        seed.restore_defaults()

    def test_listing_is_grouped_and_summarised(self):
        data = self.client.get(f"{G}/knowledge/").json()
        self.assertEqual({s["key"] for s in data["sections"]}, {"feature", "benefit", "limitation", "audience", "demo", "offer", "price", "note"})
        self.assertEqual(data["summary"]["total"], len(seed_data.KNOWLEDGE))
        self.assertEqual(data["summary"]["prices_missing"], 1)
        self.assertEqual(data["summary"]["defaults_missing"], 0)
        first_sections = [i["section"] for i in data["items"]]
        self.assertEqual(first_sections, sorted(first_sections, key=seed_data.SECTION_ORDER.index))

    def test_create_edit_delete(self):
        created = self.client.post(f"{G}/knowledge/", {"section": "offer", "title": "پیشنهادِ تازه", "body": "متنِ پیشنهاد", "url": "https://example.test/offer"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        pk = created.json()["id"]
        patched = self.client.patch(f"{G}/knowledge/{pk}/", {"body": "متنِ تازه‌تر", "is_active": False}, format="json").json()
        self.assertEqual((patched["body"], patched["is_active"], patched["is_default"]), ("متنِ تازه‌تر", False, False))
        self.assertEqual(self.client.delete(f"{G}/knowledge/{pk}/").status_code, 204)
        self.assertFalse(KnowledgeItem.objects.filter(pk=pk).exists())

    def test_validation(self):
        for body in (
            {"section": "nope", "title": "x", "body": "y"}, {"section": "feature", "title": "", "body": "y"}, {"section": "feature", "title": "x", "body": ""},
            {"section": "feature", "title": "x", "body": "y", "url": "javascript:alert(1)"}, {"section": "feature", "title": "x" * 201, "body": "y"},
            {"section": "feature", "title": "x", "body": "y" * 3001},
        ):
            self.assertEqual(self.client.post(f"{G}/knowledge/", body, format="json").status_code, 400, body)

    def test_a_price_may_be_created_empty_and_gets_its_value_later(self):
        created = self.client.post(f"{G}/knowledge/", {"section": "price", "title": "سایت‌ساز"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertTrue(created.json()["needs_value"])
        filled = self.client.patch(f"{G}/knowledge/{created.json()['id']}/", {"body": "هزینه را مالک نوشت"}, format="json").json()
        self.assertFalse(filled["needs_value"])

    def test_the_section_of_a_default_item_cannot_change_but_its_text_can_be_reset(self):
        item = KnowledgeItem.objects.get(seed_key="trial")
        self.assertEqual(self.client.patch(f"{G}/knowledge/{item.pk}/", {"section": "feature"}, format="json").status_code, 400)
        self.client.patch(f"{G}/knowledge/{item.pk}/", {"body": "ویرایش"}, format="json")
        reset = self.client.post(f"{G}/knowledge/{item.pk}/reset/").json()
        self.assertIn("دو هفته", reset["body"])
        custom = KnowledgeItem.objects.create(section="note", title="ت", body="ب")
        self.assertEqual(self.client.post(f"{G}/knowledge/{custom.pk}/reset/").status_code, 400)

    def test_restore_defaults_puts_back_what_was_deleted(self):
        KnowledgeItem.objects.filter(seed_key__in=["poster", "video"]).delete()
        MessageTemplate.objects.filter(seed_key="whatsapp").delete()
        response = self.client.post(f"{G}/knowledge/restore-defaults/").json()
        self.assertEqual(response, {"knowledge": 2, "templates": 1})
        self.assertEqual(self.client.get(f"{G}/knowledge/").json()["summary"]["defaults_missing"], 0)

    def test_staff_only(self):
        self.assertEqual(client_for().get(f"{G}/knowledge/").status_code, 401)
        plain = client_for(make_plain_user("ge-plain-kb"))
        self.assertEqual(plain.get(f"{G}/knowledge/").status_code, 403)
        self.assertEqual(plain.post(f"{G}/knowledge/", {"section": "note", "title": "x", "body": "y"}, format="json").status_code, 403)
        self.assertEqual(plain.post(f"{G}/knowledge/restore-defaults/").status_code, 403)
