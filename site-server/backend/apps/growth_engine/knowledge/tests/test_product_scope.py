"""Growth engine for more than one product: every knowledge item and every campaign belongs to a product (NM or Chagher); the AI writer only sees the
knowledge of the campaign's product; Chagher's defaults hold ONLY facts that chagher.ir itself publishes; unconfirmed claims wait, inactive, for the owner."""
from __future__ import annotations

import re
from unittest import mock

from django.test import TestCase

from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_staff
from apps.growth_engine.knowledge import products
from apps.growth_engine.knowledge.models import KnowledgeItem
from apps.growth_engine.knowledge.services import ai, context, kb, seed, seed_data, versions
from apps.growth_engine.outreach.models import Campaign, MessageTemplate
from apps.growth_engine.outreach.services import campaigns, rendering, templates
from apps.growth_engine.outreach.tests.helpers import configure, make_lead

G = "/api/v1/growth"
ROUTE = {"via": "local", "model": "m", "attempts": [{"via": "local", "ok": True}]}


class ProductRegistryTests(TestCase):
    def test_normalize_and_valid(self):
        self.assertEqual(products.normalize("CHAGHER"), "chagher")
        self.assertEqual(products.normalize("zzz"), "nm")
        self.assertEqual(products.normalize(None), "nm")
        self.assertTrue(products.valid("nm") and products.valid("chagher") and not products.valid("x"))
        self.assertEqual({p["key"] for p in products.public()}, {"nm", "chagher"})


class ChagherDefaultsTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def test_nm_defaults_are_untouched_and_chagher_is_seeded_separately(self):
        first = seed.restore_defaults()
        self.assertEqual((first["knowledge"], first["templates"]), (len(seed_data.KNOWLEDGE), len(seed_data.TEMPLATES)))
        self.assertEqual(KnowledgeItem.objects.filter(product="chagher").count(), 0, "a plain restore must not add another product")
        got = seed.seed_product("chagher")
        self.assertEqual(got, {"knowledge": len(seed_data.CHAGHER_KNOWLEDGE), "templates": len(seed_data.CHAGHER_TEMPLATES)})
        self.assertEqual(seed.seed_product("chagher"), {"knowledge": 0, "templates": 0}, "idempotent")
        self.assertEqual(KnowledgeItem.objects.filter(product="nm").count(), len(seed_data.KNOWLEDGE))

    def test_seed_keys_are_prefixed_and_unique(self):
        keys = [k[0] for k in seed_data.CHAGHER_KNOWLEDGE] + [t[0] for t in seed_data.CHAGHER_TEMPLATES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(k.startswith("chagher_") for k in keys))
        self.assertFalse(set(keys) & {k[0] for k in seed_data.KNOWLEDGE} | set(keys) & {t[0] for t in seed_data.TEMPLATES})
        self.assertTrue(all(products.of_seed_key(k) == "chagher" for k in keys))

    def test_only_published_facts_are_active_and_unconfirmed_claims_wait(self):
        seed.seed_product("chagher")
        active = " ".join(f"{k.title} {k.body}" for k in KnowledgeItem.objects.filter(product="chagher", is_active=True).exclude(section="price"))
        for forbidden in ("۹۸", "۵۰۰", "٪", "%", "۲۴/۷", "امنیت ۱۰۰", "تضمین نتیجه", "cheg_her", "Chagherg", "chaghergym"):
            self.assertNotIn(forbidden, active, "an unconfirmed claim reached an ACTIVE item: " + forbidden)
        self.assertFalse(re.search(r"[0-9۰-۹]+\s*(تومان|ریال)", active), "no price may be active")
        for key in ("chagher_claims", "chagher_social"):
            item = KnowledgeItem.objects.get(seed_key=key)
            self.assertFalse(item.is_active, key)
            self.assertTrue(item.note, "the owner must be told what to confirm")
        price = KnowledgeItem.objects.get(seed_key="chagher_price")
        self.assertTrue(price.needs_value, "the price stays empty until the owner confirms the unit and the number")
        what = KnowledgeItem.objects.get(seed_key="chagher_what")
        self.assertIn("جایگزینِ مربی نیست", what.body)
        self.assertIn("پیش‌نویس", what.body)

    def test_chagher_texts_never_mention_nm_things_and_vice_versa(self):
        seed.restore_defaults()
        seed.seed_product("chagher")
        chag = " ".join(f"{k.title} {k.body}" for k in KnowledgeItem.objects.filter(product="chagher"))
        for nm_word in ("پوستر", "ویدیوی تبلیغاتی", "آپ‌مارکت", "NMarketing"):
            self.assertNotIn(nm_word, chag)
        tmpl = MessageTemplate.objects.get(seed_key="chagher_intro")
        self.assertNotIn("پوستر", tmpl.body)
        nm = " ".join(f"{k.title} {k.body}" for k in KnowledgeItem.objects.filter(product="nm"))
        self.assertNotIn("چغر", nm)

    def test_the_chagher_template_renders_with_the_leads_own_facts_and_no_unknown_placeholders(self):
        seed.seed_product("chagher")
        tmpl = MessageTemplate.objects.get(seed_key="chagher_intro")
        self.assertEqual(rendering.unknown_placeholders(tmpl.body, tmpl.subject), [])
        configure()
        lead = make_lead("gym1.ir", name="باشگاه آرمان", city="همدان", category="باشگاه ورزشی")
        out = templates.preview(tmpl.body, tmpl.subject, lead=lead, channel="whatsapp")
        self.assertEqual(out["unknown_placeholders"], [])
        for want in ("باشگاه آرمان", "همدان", "چغر"):
            self.assertIn(want, out["text"] + out["subject"])
        self.assertNotIn("{", out["text"])


class ProductScopedApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        seed.restore_defaults()

    def test_listing_is_per_product_and_first_open_seeds_chagher(self):
        nm = self.client.get(f"{G}/knowledge/").json()
        self.assertEqual(nm["product"], "nm")
        self.assertEqual(nm["summary"]["total"], len(seed_data.KNOWLEDGE))
        self.assertEqual({p["key"] for p in nm["products"]}, {"nm", "chagher"})
        self.assertEqual(KnowledgeItem.objects.filter(product="chagher").count(), 0)
        ch = self.client.get(f"{G}/knowledge/?product=chagher").json()
        self.assertEqual(ch["product"], "chagher")
        self.assertEqual(ch["summary"]["total"], len(seed_data.CHAGHER_KNOWLEDGE))
        self.assertTrue(all(i["product"] == "chagher" for i in ch["items"]))
        self.assertEqual(ch["summary"]["prices_missing"], 1)
        self.assertEqual(ch["summary"]["defaults_missing"], 0)
        again = self.client.get(f"{G}/knowledge/?product=chagher").json()
        self.assertEqual(again["summary"]["total"], ch["summary"]["total"], "opening twice must not duplicate")
        self.assertEqual(self.client.get(f"{G}/knowledge/?product=bogus").json()["product"], "nm")

    def test_new_item_goes_to_the_chosen_product(self):
        r = self.client.post(f"{G}/knowledge/", {"section": "note", "title": "نکتهٔ چغر", "body": "متن", "product": "chagher"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["product"], "chagher")
        plain = self.client.post(f"{G}/knowledge/", {"section": "note", "title": "نکتهٔ NM", "body": "متن"}, format="json").json()
        self.assertEqual(plain["product"], "nm")
        self.assertEqual(self.client.post(f"{G}/knowledge/", {"section": "note", "title": "x", "body": "y", "product": "zzz"}, format="json").status_code, 400)

    def test_restore_defaults_can_bring_chagher_back(self):
        self.client.get(f"{G}/knowledge/?product=chagher")
        KnowledgeItem.objects.filter(seed_key="chagher_pdf").delete()
        out = self.client.post(f"{G}/knowledge/restore-defaults/", {"product": "chagher"}, format="json").json()
        self.assertEqual(out["knowledge"], 1)
        self.assertTrue(KnowledgeItem.objects.filter(seed_key="chagher_pdf").exists())

    def test_reset_a_chagher_default_item(self):
        self.client.get(f"{G}/knowledge/?product=chagher")
        item = KnowledgeItem.objects.get(seed_key="chagher_what")
        self.client.patch(f"{G}/knowledge/{item.pk}/", {"body": "ویرایش"}, format="json")
        back = self.client.post(f"{G}/knowledge/{item.pk}/reset/").json()
        self.assertIn("دستیار هوش مصنوعیِ مربی‌ها", back["body"])

    def test_campaign_carries_its_product(self):
        seed.seed_product("chagher")
        t = MessageTemplate.objects.get(seed_key="chagher_intro")
        r = self.client.post(f"{G}/outreach/campaigns/", {"name": "چغر — باشگاه‌های همدان", "template_id": t.pk, "mode": "manual", "channel": "whatsapp", "product": "chagher"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()["product"], r.json()["product_label"]), ("chagher", "چغر"))
        default = self.client.post(f"{G}/outreach/campaigns/", {"name": "NM", "template_id": MessageTemplate.objects.get(seed_key="contact_form").pk, "mode": "auto", "channel": "contact_form"}, format="json").json()
        self.assertEqual(default["product"], "nm")
        with self.assertRaises(campaigns.CampaignError):
            campaigns.create_campaign(name="x", template=t, mode="manual", channel="whatsapp", product="nope")


class WriterOnlySeesItsProductTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        seed.restore_defaults()
        seed.seed_product("chagher")
        self.lead = make_lead("gym2.ir", name="باشگاه فرزین", city="همدان", category="باشگاه ورزشی")

    def item_for(self, product):
        t = MessageTemplate.objects.get(seed_key="chagher_intro" if product == "chagher" else "contact_form")
        ch = "whatsapp" if product == "chagher" else "contact_form"
        mode = Campaign.Mode.MANUAL if product == "chagher" else Campaign.Mode.AUTO
        c = campaigns.create_campaign(name=f"c-{product}", template=t, mode=mode, user=self.staff, channel=ch, product=product)
        item = campaigns.add_leads(c, [make_lead(f"{product}-x.ir", name="طرف", city="همدان").pk]).added[0]
        item.refresh_from_db()
        return item

    def test_context_has_only_the_campaigns_product_knowledge(self):
        chag = context.build(self.item_for("chagher"))
        texts = " ".join(f.text for f in chag.facts if f.kind == "kb")
        self.assertIn("دستیار هوش مصنوعیِ مربی‌ها", texts)
        self.assertNotIn("پوستر", texts)
        self.assertNotIn("۹۸", texts, "the inactive unconfirmed claim must not be a fact")
        self.assertFalse(chag.price_known, "the Chagher price is empty: nothing is known")
        nm = context.build(self.item_for("nm"))
        nm_texts = " ".join(f.text for f in nm.facts if f.kind == "kb")
        self.assertIn("پوستر", nm_texts)
        self.assertNotIn("چغر", nm_texts)

    def test_the_prompt_of_a_chagher_item_carries_chagher_facts_only(self):
        item = self.item_for("chagher")
        version, _ = versions.request_version(item, self.staff, "")
        seen = {}

        def fake(system, prompt):
            seen["prompt"] = prompt
            return ({"subject": "", "message": "سلام؛ چغر پیش‌نویسِ برنامه می‌دهد و تصمیمِ نهایی با مربی است.", "personalization_reason": "شهرِ شما را دیدم.",
                     "evidence_references": [], "warnings": []}, ROUTE)

        with mock.patch.object(ai, "complete_json", side_effect=fake):
            from apps.growth_engine.knowledge.services import writer

            writer.run(version.pk)
        self.assertIn("چغر", seen["prompt"])
        self.assertNotIn("پوستر", seen["prompt"])
