"""Channels: the settings API (secrets stay secret), targets, deep links, SMS sizes, campaign rules, manual channels."""
from __future__ import annotations

import json

from django.test import SimpleTestCase, TestCase

from apps.growth_engine.compliance.models import AuditEntry
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.models import ContactPoint
from apps.growth_engine.outreach import models
from apps.growth_engine.outreach.channels import deeplinks, sms, targets
from apps.growth_engine.outreach.models import AUTO, Campaign, Channel, ChannelConfig, ItemStatus, MessageTemplate, OutreachItem
from apps.growth_engine.outreach.services import campaigns, channel_config, manual

from .helpers import configure, make_campaign, make_lead, make_template

G = "/api/v1/growth"
SMTP_PASSWORD = "smtp-PASSWORD-s3cret!"


def add_contact(lead, kind, value, **kw):
    return ContactPoint.objects.create(lead=lead, kind=kind, value=value, normalized=kw.pop("normalized", value), **kw)


class SmsSizeTests(SimpleTestCase):
    def test_persian_text_is_counted_in_ucs2_parts(self):
        self.assertEqual(sms.segments("س" * 70)["parts"], 1)
        self.assertEqual(sms.segments("س" * 71)["parts"], 2)  # 71 > 70: now 67 per part
        self.assertEqual(sms.segments("س" * 134)["parts"], 2)
        self.assertEqual(sms.segments("س" * 135)["parts"], 3)
        self.assertEqual(sms.segments("س" * 70)["encoding"], "ucs2")

    def test_latin_text_is_gsm7(self):
        self.assertEqual(sms.segments("a" * 160)["parts"], 1)
        self.assertEqual(sms.segments("a" * 161)["parts"], 2)
        self.assertEqual(sms.segments("a" * 306)["parts"], 2)
        self.assertEqual(sms.segments("a" * 307)["parts"], 3)
        self.assertEqual(sms.segments("€" * 80)["parts"], 1)  # an extension character takes two units
        self.assertEqual(sms.segments("€" * 81)["parts"], 2)

    def test_one_persian_letter_turns_the_whole_message_to_ucs2(self):
        seg = sms.segments("a" * 69 + "ب")
        self.assertEqual((seg["encoding"], seg["parts"]), ("ucs2", 1))
        self.assertEqual(sms.segments("a" * 70 + "ب")["parts"], 2)

    def test_empty(self):
        self.assertEqual(sms.segments("")["parts"], 0)


class DeepLinkTests(SimpleTestCase):
    def test_whatsapp_link_carries_the_encoded_text(self):
        data = deeplinks.build(Channel.WHATSAPP, "09121234567", "سلام & خوش آمدید؟")
        self.assertTrue(data["link"].startswith("https://wa.me/989121234567?text="))
        self.assertNotIn(" ", data["link"])
        self.assertNotIn("&", data["link"].split("?text=")[1])
        self.assertEqual(data["link_kind"], "https")

    def test_messenger_links_are_the_pages_themselves(self):
        self.assertEqual(deeplinks.build(Channel.TELEGRAM, "https://t.me/rahashop", "x")["link"], "https://t.me/rahashop")
        self.assertEqual(deeplinks.build(Channel.EITAA, "https://eitaa.com/raha", "x")["link"], "https://eitaa.com/raha")
        self.assertEqual(deeplinks.build(Channel.BALE, "https://ble.ir/raha", "x")["link"], "https://ble.ir/raha")
        self.assertEqual(deeplinks.build(Channel.RUBIKA, "https://rubika.ir/raha", "x")["link"], "https://rubika.ir/raha")

    def test_a_link_to_another_host_or_scheme_is_never_made(self):
        self.assertEqual(deeplinks.build(Channel.TELEGRAM, "https://evil.example/rahashop", "x")["link"], "")
        self.assertEqual(deeplinks.build(Channel.TELEGRAM, "javascript:alert(1)", "x")["link"], "")
        self.assertEqual(deeplinks.build(Channel.TELEGRAM, "http://t.me/raha", "x")["link"], "")
        self.assertEqual(deeplinks.build(Channel.WHATSAPP, "not a number", "x")["link"], "")

    def test_a_call_is_a_tel_link(self):
        data = deeplinks.build(Channel.PHONE_CALL, "02112345678", "script")
        self.assertEqual((data["link"], data["link_kind"]), ("tel:+982112345678", "tel"))

    def test_the_contact_form_and_email_have_no_manual_link(self):
        self.assertEqual(deeplinks.build(Channel.EMAIL, "a@b.ir", "x")["link"], "")


class TargetTests(TestCase):
    def test_each_channel_picks_its_own_contact_point(self):
        lead = make_lead("t1.ir", phone="09125550001; 02188112233", email="info@t1.ir")
        add_contact(lead, ContactKind.TELEGRAM, "https://t.me/t1shop")
        add_contact(lead, ContactKind.WHATSAPP, "09125550002")
        self.assertEqual(targets.resolve(lead, Channel.EMAIL).recipient, "info@t1.ir")
        self.assertEqual(targets.resolve(lead, Channel.SMS).recipient, "09125550001")  # the mobile, not the landline
        self.assertEqual(targets.resolve(lead, Channel.WHATSAPP).recipient, "09125550002")
        self.assertEqual(targets.resolve(lead, Channel.TELEGRAM).recipient, "https://t.me/t1shop")
        self.assertEqual(targets.resolve(lead, Channel.CONTACT_FORM).recipient, "https://t1.ir/contact")
        self.assertIsNone(targets.resolve(lead, Channel.EITAA))
        self.assertIsNotNone(targets.resolve(lead, Channel.PHONE_CALL))

    def test_a_landline_cannot_receive_an_sms(self):
        lead = make_lead("t2.ir", phone="02188112233")
        self.assertIsNone(targets.resolve(lead, Channel.SMS))
        self.assertEqual(targets.no_target(Channel.SMS)[0], "no_mobile")

    def test_whatsapp_falls_back_to_the_mobile_with_a_caution(self):
        lead = make_lead("t3.ir", phone="09125550003")
        target = targets.resolve(lead, Channel.WHATSAPP)
        self.assertEqual(target.recipient, "09125550003")
        self.assertIn("ممکن است واتساپ نداشته باشد", target.note)

    def test_placeholder_emails_are_not_targets(self):
        lead = make_lead("t4.ir", email="user@example.com")
        self.assertIsNone(targets.resolve(lead, Channel.EMAIL))

    def test_the_primary_contact_wins_then_the_more_confident_one(self):
        lead = make_lead("t5.ir", email="first@t5.ir")
        add_contact(lead, ContactKind.EMAIL, "better@t5.ir", confidence=95)
        self.assertEqual(targets.resolve(lead, Channel.EMAIL).recipient, "first@t5.ir")  # the first one entered is the primary
        lead.contacts.filter(value="first@t5.ir").update(is_primary=False)
        self.assertEqual(targets.resolve(lead, Channel.EMAIL).recipient, "better@t5.ir")

    def test_auto_choice_follows_the_given_order(self):
        lead = make_lead("t6.ir", phone="09125550006", email="x@t6.ir")
        self.assertEqual(targets.choose_for_auto(lead, [Channel.SMS, Channel.EMAIL]).channel, Channel.SMS)
        self.assertEqual(targets.choose_for_auto(lead, [Channel.EMAIL, Channel.SMS]).channel, Channel.EMAIL)
        self.assertEqual(targets.choose_for_auto(lead, [Channel.TELEGRAM, Channel.EMAIL]).channel, Channel.EMAIL)
        self.assertIsNone(targets.choose_for_auto(lead, [Channel.TELEGRAM, Channel.EITAA]))


class ChannelConfigApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def smtp(self, **extra):
        return {"config": {"host": "smtp.example.test", "port": 587, "security": "starttls", "from_email": "no-reply@upmarket.ir", "username": "mailer"},
                "secrets": {"smtp_password": SMTP_PASSWORD}, **extra}

    def test_listing_has_every_channel_in_priority_order(self):
        data = self.client.get(f"{G}/outreach/channels/").json()["channels"]
        self.assertEqual([c["key"] for c in data], ["contact_form", "email", "sms", "whatsapp", "telegram", "eitaa", "bale", "rubika", "phone_call"])
        by = {c["key"]: c for c in data}
        self.assertTrue(by["contact_form"]["enabled"])
        self.assertFalse(by["email"]["enabled"])
        self.assertFalse(by["sms"]["enabled"])
        self.assertTrue(by["whatsapp"]["enabled"])  # a manual channel is on: it is only a link
        self.assertEqual(by["whatsapp"]["kind"], "manual")
        self.assertFalse(by["email"]["ready"])
        self.assertIn("سرورِ ایمیل", by["email"]["not_ready_reason"])
        self.assertIn("NM-Mobile", by["sms"]["not_ready_reason"])
        self.assertTrue(by["sms"]["needs_app"])

    def test_email_cannot_be_turned_on_while_incomplete(self):
        response = self.client.patch(f"{G}/outreach/channels/email/", {"enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "not_ready")
        self.assertFalse(ChannelConfig.objects.filter(channel="email", enabled=True).exists())

    def test_the_smtp_password_is_stored_but_never_returned_or_audited(self):
        response = self.client.patch(f"{G}/outreach/channels/email/", {**self.smtp(), "enabled": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.content.decode()
        self.assertNotIn(SMTP_PASSWORD, body)
        self.assertTrue(response.json()["secrets"]["smtp_password"]["is_set"])
        self.assertTrue(response.json()["enabled"])
        self.assertTrue(response.json()["ready"])
        self.assertNotIn(SMTP_PASSWORD, self.client.get(f"{G}/outreach/channels/").content.decode())
        self.assertNotIn(SMTP_PASSWORD, self.client.get(f"{G}/outreach/channels/email/").content.decode())
        self.assertEqual(ChannelConfig.objects.get(channel="email").secrets["smtp_password"], SMTP_PASSWORD)
        trail = json.dumps(list(AuditEntry.objects.values("summary", "data")), ensure_ascii=False)
        self.assertNotIn(SMTP_PASSWORD, trail)
        self.assertIn("secrets.smtp_password", trail)

    def test_an_empty_password_box_keeps_the_stored_password_and_clearing_is_explicit(self):
        self.client.patch(f"{G}/outreach/channels/email/", self.smtp(), format="json")
        self.client.patch(f"{G}/outreach/channels/email/", {"secrets": {"smtp_password": ""}, "daily_cap": 5}, format="json")
        self.assertEqual(ChannelConfig.objects.get(channel="email").secrets["smtp_password"], SMTP_PASSWORD)
        response = self.client.patch(f"{G}/outreach/channels/email/", {"clear_secrets": ["smtp_password"]}, format="json")
        self.assertFalse(response.json()["secrets"]["smtp_password"]["is_set"])
        self.assertEqual(ChannelConfig.objects.get(channel="email").secrets, {})

    def test_the_effective_account_shows_what_comes_from_the_server_but_not_the_password(self):
        response = self.client.patch(f"{G}/outreach/channels/email/", {"config": {"host": "smtp.example.test", "from_email": "a@upmarket.ir"}}, format="json")
        config = response.json()["config"]
        self.assertEqual(config["in_force"]["host"], "smtp.example.test")
        self.assertNotIn("password", config["in_force"])
        self.assertIn("port", config["from_server"])
        self.assertEqual(config["in_force"]["reply_to"], "ali@upmarket.ir")  # the sender's own address from Growth Settings

    def test_validation(self):
        bad = [
            {"priority": 0}, {"priority": "x"}, {"daily_cap": 0}, {"daily_cap": 501}, {"spacing_min_seconds": 5}, {"spacing_min_seconds": 30},  # min without max
            {"spacing_min_seconds": 90, "spacing_max_seconds": 30}, {"config": {"host": "not a host!"}}, {"config": {"port": 70000}},
            {"config": {"security": "plain"}}, {"config": {"from_email": "nope"}}, {"config": {"nonsense": 1}}, {"secrets": {"api_key": "x"}},
            {"secrets": {"smtp_password": "a\nb"}}, {"default_template_id": 999999},
        ]
        for body in bad:
            response = self.client.patch(f"{G}/outreach/channels/email/", body, format="json")
            self.assertEqual(response.status_code, 400, body)
        self.assertFalse(ChannelConfig.objects.filter(channel="email").exists())

    def test_a_manual_channel_has_no_caps_or_spacing(self):
        for body in ({"daily_cap": 5}, {"spacing_min_seconds": 20, "spacing_max_seconds": 40}):
            self.assertEqual(self.client.patch(f"{G}/outreach/channels/whatsapp/", body, format="json").status_code, 400)

    def test_caps_spacing_and_priority_are_saved_and_used(self):
        self.client.patch(f"{G}/outreach/channels/email/", {**self.smtp(), "enabled": True, "daily_cap": 3, "spacing_min_seconds": 20, "spacing_max_seconds": 30}, format="json")
        self.assertEqual(channel_config.cap_remaining(Channel.EMAIL), 3)
        self.assertEqual(channel_config.spacing_for(Channel.EMAIL), (20, 30))
        self.assertEqual(channel_config.spacing_for(Channel.CONTACT_FORM), (60, 120))  # the global setting
        self.assertIsNone(channel_config.cap_remaining(Channel.CONTACT_FORM))
        self.client.patch(f"{G}/outreach/channels/email/", {"daily_cap": None, "spacing_min_seconds": None, "spacing_max_seconds": None}, format="json")
        self.assertIsNone(channel_config.cap_remaining(Channel.EMAIL))
        self.assertEqual(channel_config.spacing_for(Channel.EMAIL), (60, 120))

    def test_reorder_sets_the_priority_and_the_listing_follows_it(self):
        self.client.patch(f"{G}/outreach/channels/email/", {**self.smtp(), "enabled": True}, format="json")
        response = self.client.post(f"{G}/outreach/channels/reorder/", {"order": ["email", "telegram", "contact_form"]}, format="json")
        keys = [c["key"] for c in response.json()["channels"]]
        self.assertEqual(keys[:3], ["email", "telegram", "contact_form"])
        self.assertEqual(channel_config.ordered_enabled()[:2], ["email", "telegram"])
        self.assertEqual(self.client.post(f"{G}/outreach/channels/reorder/", {"order": ["email", "email"]}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{G}/outreach/channels/reorder/", {"order": ["fax"]}, format="json").status_code, 400)

    def test_the_default_template_must_suit_the_channel(self):
        email_tpl = make_template("ایمیل", channel="email")
        sms_tpl = make_template("پیامک", channel="sms")
        any_tpl = make_template("عمومی")
        ok = self.client.patch(f"{G}/outreach/channels/whatsapp/", {"default_template_id": any_tpl.pk}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["default_template"]["id"], any_tpl.pk)
        self.assertEqual(self.client.patch(f"{G}/outreach/channels/whatsapp/", {"default_template_id": sms_tpl.pk}, format="json").status_code, 400)
        self.assertEqual(channel_config.default_template(Channel.EMAIL).pk, email_tpl.pk)  # falls back to a template written for the channel

    def test_staff_only_and_unknown_channels(self):
        self.assertEqual(client_for().get(f"{G}/outreach/channels/").status_code, 401)
        plain = client_for(make_plain_user("ge-plain-ch"))
        self.assertEqual(plain.get(f"{G}/outreach/channels/").status_code, 403)
        self.assertEqual(plain.patch(f"{G}/outreach/channels/email/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.get(f"{G}/outreach/channels/fax/").status_code, 404)
        self.assertEqual(self.client.patch(f"{G}/outreach/channels/fax/", {}, format="json").status_code, 404)

    def test_template_channel_and_the_campaign_channel_are_in_the_api(self):
        response = self.client.post(f"{G}/outreach/templates/", {"name": "پیامک کوتاه", "body": "سلام", "channel": "sms"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()["channel"], response.json()["channel_label"]), ("sms", "پیامک (از گوشیِ شما)"))
        bad = self.client.post(f"{G}/outreach/templates/", {"name": "x", "body": "y", "channel": "fax"}, format="json")
        self.assertEqual(bad.status_code, 400)
        campaign = self.client.post(f"{G}/outreach/campaigns/", {"name": "ک", "template_id": response.json()["id"], "mode": "auto", "channel": "sms"}, format="json")
        self.assertEqual(campaign.status_code, 201, campaign.content)
        self.assertEqual(campaign.json()["channel"], "sms")


class CampaignChannelRuleTests(TestCase):
    def setUp(self):
        configure()

    def test_a_messenger_or_call_campaign_must_be_a_manual_queue(self):
        for channel in (Channel.WHATSAPP, Channel.TELEGRAM, Channel.EITAA, Channel.BALE, Channel.RUBIKA, Channel.PHONE_CALL):
            with self.assertRaises(campaigns.CampaignError) as cm:
                campaigns.create_campaign(name="x", template=make_template(), mode=Campaign.Mode.AUTO, channel=channel)
            self.assertEqual(cm.exception.code, "manual_channel_mode")
            ok = campaigns.create_campaign(name="x", template=make_template(), mode=Campaign.Mode.MANUAL, channel=channel)
            self.assertEqual(ok.channel, channel)

    def test_the_template_must_be_for_the_channel_or_for_all(self):
        sms_tpl = make_template("س", channel="sms")
        with self.assertRaises(campaigns.CampaignError) as cm:
            campaigns.create_campaign(name="x", template=sms_tpl, mode=Campaign.Mode.AUTO, channel=Channel.EMAIL)
        self.assertEqual(cm.exception.code, "template_channel")
        campaigns.create_campaign(name="x", template=sms_tpl, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        campaigns.create_campaign(name="y", template=make_template("همه"), mode=Campaign.Mode.AUTO, channel=Channel.EMAIL)
        campaigns.create_campaign(name="z", template=sms_tpl, mode=Campaign.Mode.AUTO, channel=AUTO)  # an auto campaign takes any as the fallback
        with self.assertRaises(campaigns.CampaignError):
            campaigns.create_campaign(name="w", template=make_template("ن"), mode=Campaign.Mode.AUTO, channel="fax")

    def test_a_lead_without_the_campaigns_contact_point_is_refused_with_the_reason(self):
        campaign = campaigns.create_campaign(name="ایمیل", template=make_template("ا", channel="email"), mode=Campaign.Mode.AUTO, channel=Channel.EMAIL)
        with_mail = make_lead("c1.ir", email="a@c1.ir")
        no_mail = make_lead("c2.ir")
        result = campaigns.add_leads(campaign, [with_mail.pk, no_mail.pk])
        self.assertEqual(len(result.added), 1)
        self.assertEqual(result.added[0].channel, Channel.EMAIL)
        self.assertEqual(result.added[0].recipient, "a@c1.ir")
        self.assertEqual([(s["lead_id"], s["reason"]) for s in result.skipped], [(no_mail.pk, "no_email")])
        self.assertIn("ایمیل", result.skipped[0]["reason_text"])

    def test_items_remember_their_channel_recipient_and_template(self):
        template = make_template("پیامک", channel="sms")
        campaign = campaigns.create_campaign(name="س", template=template, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        lead = make_lead("c3.ir", phone="09125550010")
        item = campaigns.add_leads(campaign, [lead.pk]).added[0]
        item.refresh_from_db()
        self.assertEqual((item.channel, item.recipient, item.template_id, item.target_url), (Channel.SMS, "09125550010", template.pk, ""))
        # an SMS carries the short closing block: the company and the opt-out line only
        self.assertTrue(item.rendered_text.endswith("آپ‌مارکت\nاگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو»."))
        self.assertNotIn("ali@upmarket.ir", item.rendered_text)

    def test_a_form_item_is_unchanged_by_all_this(self):
        campaign = make_campaign()
        lead = make_lead("c4.ir")
        item = campaigns.add_leads(campaign, [lead.pk]).added[0]
        item.refresh_from_db()
        self.assertEqual((item.channel, item.target_url, item.recipient), (Channel.CONTACT_FORM, "https://c4.ir/contact", "https://c4.ir/contact"))
        self.assertIn("ali@upmarket.ir", item.rendered_text)  # the full closing block

    def test_auto_campaign_picks_the_first_enabled_channel_that_reaches_each_lead(self):
        staff = make_staff()
        channel_config.update("email", {"config": {"host": "smtp.example.test", "from_email": "n@upmarket.ir"}, "enabled": True}, staff)
        channel_config.update("contact_form", {"enabled": False}, staff)
        channel_config.reorder(["email", "telegram", "whatsapp"], staff)
        campaign = campaigns.create_campaign(name="خودکار", template=make_template("پایه"), mode=Campaign.Mode.AUTO, channel=AUTO)
        both = make_lead("c5.ir", email="a@c5.ir", phone="09125550011")
        only_phone = make_lead("c6.ir", phone="09125550012")
        nothing = make_lead(None, phone="02188112233", form=False)  # no website, a landline only
        added = {i.lead_id: i for i in campaigns.add_leads(campaign, [both.pk, only_phone.pk, nothing.pk]).added}
        self.assertEqual(added[both.pk].channel, Channel.EMAIL)
        self.assertEqual(added[only_phone.pk].channel, Channel.WHATSAPP)  # whatsapp is the next enabled one that can reach a mobile
        self.assertEqual(added[nothing.pk].channel, Channel.PHONE_CALL)  # every enabled channel before it failed

    def test_auto_campaign_uses_the_default_template_of_the_chosen_channel(self):
        staff = make_staff()
        email_tpl = make_template("ایمیلِ پیش‌فرض", channel="email")
        channel_config.update("email", {"config": {"host": "smtp.example.test", "from_email": "n@upmarket.ir"}, "enabled": True, "default_template_id": email_tpl.pk}, staff)
        channel_config.reorder(["email"], staff)
        campaign = campaigns.create_campaign(name="خودکار", template=make_template("پایه"), mode=Campaign.Mode.AUTO, channel=AUTO)
        item = campaigns.add_leads(campaign, [make_lead("c7.ir", email="a@c7.ir").pk]).added[0]
        item.refresh_from_db()
        self.assertEqual((item.channel, item.template_id), (Channel.EMAIL, email_tpl.pk))

    def test_a_lead_with_no_reachable_enabled_channel_is_refused_in_an_auto_campaign(self):
        staff = make_staff()
        for key in ("contact_form", "whatsapp", "telegram", "eitaa", "bale", "rubika", "phone_call"):
            channel_config.update(key, {"enabled": False}, staff)
        campaign = campaigns.create_campaign(name="خودکار", template=make_template("پایه"), mode=Campaign.Mode.AUTO, channel=AUTO)
        result = campaigns.add_leads(campaign, [make_lead("c8.ir").pk])
        self.assertEqual([s["reason"] for s in result.skipped], ["no_channel"])

    def test_the_same_lead_can_get_a_different_template_but_never_the_same_twice(self):
        t1, t2 = make_template("الف", channel="sms"), make_template("ب", channel="sms")
        lead = make_lead("c9.ir", phone="09125550013")
        c1 = campaigns.create_campaign(name="1", template=t1, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        item = campaigns.add_leads(c1, [lead.pk]).added[0]
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.SENT)
        c2 = campaigns.create_campaign(name="2", template=t1, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        self.assertEqual(campaigns.add_leads(c2, [lead.pk]).skipped[0]["reason"], "already_contacted")
        c3 = campaigns.create_campaign(name="3", template=t2, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        self.assertEqual(len(campaigns.add_leads(c3, [lead.pk]).added), 1)


class ManualChannelTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def queue(self, channel, lead):
        campaign = campaigns.create_campaign(name="دستی", template=make_template("دستی", channel=channel), mode=Campaign.Mode.MANUAL, channel=channel, user=self.staff)
        result = campaigns.add_leads(campaign, [lead.pk])
        self.assertEqual(len(result.added), 1, result.skipped)
        return campaign, result.added[0]

    def item_api(self, campaign, item):
        return self.client.get(f"{G}/outreach/campaigns/{campaign.pk}/items/{item.pk}/").json()

    def test_whatsapp_item_carries_the_ready_link_and_the_text(self):
        lead = make_lead("m1.ir", phone="09125550020")
        campaign, item = self.queue(Channel.WHATSAPP, lead)
        data = self.item_api(campaign, item)
        self.assertEqual((data["channel"], data["channel_label"]), ("whatsapp", "واتساپ"))
        manual_block = data["manual"]
        self.assertTrue(manual_block["link"].startswith("https://wa.me/989125550020?text="))
        self.assertTrue(manual_block["copy_text"])
        self.assertIn("ممکن است واتساپ نداشته باشد", manual_block["note"])
        self.assertEqual(data["rendered_text"].count("آپ‌مارکت"), data["rendered_text"].count("آپ‌مارکت"))

    def test_other_channels_links(self):
        lead = make_lead("m2.ir", phone="02188112233")
        add_contact(lead, ContactKind.TELEGRAM, "https://t.me/m2shop")
        add_contact(lead, ContactKind.BALE, "https://ble.ir/m2shop")
        for channel, link in ((Channel.TELEGRAM, "https://t.me/m2shop"), (Channel.BALE, "https://ble.ir/m2shop"), (Channel.PHONE_CALL, "tel:+982188112233")):
            campaign, item = self.queue(channel, lead)
            self.assertEqual(self.item_api(campaign, item)["manual"]["link"], link, channel)

    def test_a_call_has_no_sender_block_and_no_opt_out_requirement(self):
        lead = make_lead("m3.ir", phone="02188112233")
        campaign, item = self.queue(Channel.PHONE_CALL, lead)
        item.refresh_from_db()
        self.assertNotIn("ali@upmarket.ir", item.rendered_text)
        self.assertNotIn("لغو", item.rendered_text)
        from apps.growth_engine.outreach.services import items as item_service

        item_service.edit_item(item, text="سلام، من علی از آپ‌مارکت هستم.", actor=self.staff)  # no opt-out line needed in a spoken script
        item.refresh_from_db()
        self.assertEqual(item.rendered_text, "سلام، من علی از آپ‌مارکت هستم.")

    def test_a_manual_channel_item_can_never_be_approved_or_sent_by_the_system(self):
        lead = make_lead("m4.ir", phone="09125550021")
        campaign, item = self.queue(Channel.WHATSAPP, lead)
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.READY)
        response = self.client.post(f"{G}/outreach/campaigns/{campaign.pk}/approve/", {"item_ids": [item.pk]}, format="json").json()
        self.assertEqual(response["approved"], 0)
        self.assertEqual(response["refused"][0]["code"], "manual_channel")

    def test_the_outcome_unreachable_is_recorded_with_the_channel(self):
        lead = make_lead("m5.ir", phone="09125550022")
        campaign, item = self.queue(Channel.WHATSAPP, lead)
        response = self.client.post(f"{G}/outreach/campaigns/{campaign.pk}/items/{item.pk}/outcome/", {"outcome": "unreachable", "note": "حساب نداشت"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.UNREACHABLE)
        activity = lead.activities.filter(kind="queue_outcome").first()
        self.assertEqual((activity.data["via"], activity.data["outcome"], activity.data["channel"]), ("whatsapp", "unreachable", "manual"))
        self.assertIn("واتساپ", activity.summary)
        self.assertEqual(campaigns.counts([campaign.pk])[campaign.pk], {"unreachable": 1})

    def test_a_sent_message_is_recorded_and_moves_the_lead(self):
        lead = make_lead("m6.ir", phone="09125550023")
        campaign, item = self.queue(Channel.WHATSAPP, lead)
        manual.record_outcome(item, "sent", "رفت", self.staff)
        item.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual((item.status, lead.status), (ItemStatus.MANUAL_SENT, "contacted"))
        # the one-per-lead-and-template rule holds across channels
        again = campaigns.create_campaign(name="دوباره", template=item.template, mode=Campaign.Mode.MANUAL, channel=Channel.WHATSAPP)
        self.assertEqual(campaigns.add_leads(again, [lead.pk]).skipped[0]["reason"], "already_contacted")

    def test_do_not_contact_blocks_a_manual_record_too(self):
        from apps.growth_engine.compliance.services import suppression

        lead = make_lead("m7.ir", phone="09125550024")
        campaign, item = self.queue(Channel.WHATSAPP, lead)
        suppression.suppress_lead(lead, "opt_out", "", self.staff)
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed):
            manual.record_outcome(item, "sent", "", self.staff)
