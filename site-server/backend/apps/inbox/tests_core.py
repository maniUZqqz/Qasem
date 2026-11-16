"""The inbox's core rules: doors, contacts, assignment, presence, SLA, reopening."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message, Notification, Order

from . import contacts, hours, replies, sla, team
from .models import (
    AgentProfile, ChannelConnection, Contact, ContactLink, ConversationMeta, InboxSettings, InternalNote, MessageMeta,
)
from .tests_base import InboxTestCase

BALE_MESSAGE = {"update_id": 1, "message": {
    "message_id": 41, "from": {"id": 900, "first_name": "مینا", "username": "Mina_Fit"},
    "chat": {"id": 900, "type": "private"}, "text": "سلام، ساعت کاری شما؟"}}


def post_hook(client, slug, secret, payload, **headers):
    return client.post(f"/api/v1/inbox/hook/{slug}/{secret}/", data=json.dumps(payload),
                       content_type="application/json", **headers)


@patch("apps.customers.views_webhook._respond_later")
class HookTests(InboxTestCase):
    def test_a_bale_message_becomes_a_conversation_contact_and_unread(self, respond):
        from django.test import Client

        row = self.connect("BALE")
        response = post_hook(Client(), "bale", row.secret, BALE_MESSAGE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 1)
        conversation = Conversation.objects.get(store=self.store, channel="BALE")
        self.assertEqual(conversation.external_id, "900")
        self.assertEqual(conversation.customer.name, "مینا")
        meta = conversation.inbox_meta
        self.assertEqual(meta.unread_count, 1)
        contact = conversation.customer.inbox_link.contact
        self.assertEqual(contact.usernames, ["mina_fit"])
        row.refresh_from_db()
        self.assertEqual(row.inbound_count, 1)
        self.assertIsNotNone(row.last_inbound_at)
        respond.assert_called_once()  # the bot owns the thread, so the AI is asked

    def test_a_retried_delivery_is_not_answered_twice(self, respond):
        from django.test import Client

        row = self.connect("BALE")
        client = Client()
        post_hook(client, "bale", row.secret, BALE_MESSAGE)
        again = post_hook(client, "bale", row.secret, BALE_MESSAGE)
        self.assertEqual(again.json()["accepted"], 0)
        self.assertEqual(Message.objects.filter(conversation__channel="BALE").count(), 1)
        respond.assert_called_once()

    def test_wrong_secret_disabled_channel_and_unknown_platform_are_404(self, respond):
        from django.test import Client

        row = self.connect("BALE")
        client = Client()
        self.assertEqual(post_hook(client, "bale", "x" * 24, BALE_MESSAGE).status_code, 404)
        self.assertEqual(post_hook(client, "nowhere", row.secret, BALE_MESSAGE).status_code, 404)
        row.enabled = False
        row.save()
        self.assertEqual(post_hook(client, "bale", row.secret, BALE_MESSAGE).status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_the_url_secret_of_one_channel_does_not_open_another(self, respond):
        from django.test import Client

        bale = self.connect("BALE")
        self.connect("RUBIKA", token="R" * 30)
        self.assertEqual(post_hook(Client(), "rubika", bale.secret, BALE_MESSAGE).status_code, 404)

    def test_garbage_is_a_200_not_a_500(self, respond):
        from django.test import Client

        row = self.connect("BALE")
        response = Client().post(f"/api/v1/inbox/hook/bale/{row.secret}/", data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        reaction = {"update_id": 5, "message_reaction": {"x": 1}}
        self.assertEqual(post_hook(Client(), "bale", row.secret, reaction).json()["accepted"], 0)

    def test_whatsapp_needs_a_valid_signature(self, respond):
        from django.test import Client

        row = self.connect("WHATSAPP", token="T" * 30, config={
            "phone_number_id": "555", "app_secret": "appsec", "verify_token": "vt"})
        payload = {"entry": [{"changes": [{"value": {"messages": [
            {"from": "989121234567", "id": "w1", "type": "text", "text": {"body": "سلام"}}]}}]}]}
        self.assertEqual(post_hook(Client(), "whatsapp", row.secret, payload).status_code, 403)
        import hashlib
        import hmac

        body = json.dumps(payload)
        sig = "sha256=" + hmac.new(b"appsec", body.encode(), hashlib.sha256).hexdigest()
        ok = Client().post(f"/api/v1/inbox/hook/whatsapp/{row.secret}/", data=body, content_type="application/json",
                           HTTP_X_HUB_SIGNATURE_256=sig)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(Conversation.objects.filter(channel="WHATSAPP").count(), 1)
        handshake = Client().get(f"/api/v1/inbox/hook/whatsapp/{row.secret}/",
                                 {"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "777"})
        self.assertEqual(handshake.content.decode(), "777")

    def test_opt_out_word_is_not_a_question_for_the_bot(self, respond):
        from django.test import Client

        row = self.connect("BALE")
        payload = json.loads(json.dumps(BALE_MESSAGE))
        payload["message"]["text"] = "لغو"
        post_hook(Client(), "bale", row.secret, payload)
        contact = Contact.objects.get(store=self.store)
        self.assertTrue(contact.opted_out_of("BALE"))
        respond.assert_not_called()
        # the confirmation is in the thread, attributed to the system, not to a person
        self.assertTrue(MessageMeta.objects.filter(kind="SYSTEM").exists())

    def test_a_long_sentence_with_lagv_in_it_is_not_an_opt_out(self, respond):
        self.assertEqual(contacts.opt_word("می‌خواهم سفارشم را لغو کنم"), "")
        self.assertEqual(contacts.opt_word("لغو"), "out")
        self.assertEqual(contacts.opt_word("  STOP! "), "out")
        self.assertEqual(contacts.opt_word("عضویت"), "in")


class ContactTests(InboxTestCase):
    def test_same_phone_on_two_channels_is_one_person(self):
        a = self.conversation("TELEGRAM", sender="t1", name="سارا")
        b = self.conversation("SMS", sender="989121234567", name="")
        first = contacts.identify(a.customer, phone="+98 912 123 4567", name="سارا")
        second = contacts.identify(b.customer, phone="09121234567")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.phone, "09121234567")
        self.assertEqual(Contact.objects.filter(store=self.store).count(), 1)
        self.assertEqual(ContactLink.objects.filter(contact=first).count(), 2)

    def test_persian_digits_match_too(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, phone="۰۹۱۲۱۲۳۴۵۶۷")
        two = contacts.identify(b.customer, phone="0912 123 4567")
        self.assertEqual(one.pk, two.pk)

    def test_same_username_merges_by_default_and_can_be_turned_off(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("RUBIKA", sender="r1")
        one = contacts.identify(a.customer, username="@Ali_Fit")
        two = contacts.identify(b.customer, username="ali_fit")
        self.assertEqual(one.pk, two.pk)
        cfg = team.settings_for(self.store)
        cfg.merge_by_username = False
        cfg.save()
        c = self.conversation("BALE", sender="b9")
        three = contacts.identify(c.customer, username="ali_fit")
        self.assertNotEqual(three.pk, one.pk)

    def test_never_merges_across_stores(self):
        a = self.conversation("TELEGRAM", sender="t1")
        other = self.conversation("TELEGRAM", sender="t1", store=self.other_store)
        one = contacts.identify(a.customer, phone="09121234567")
        two = contacts.identify(other.customer, phone="09121234567")
        self.assertNotEqual(one.pk, two.pk)
        with self.assertRaises(ValueError):
            contacts.merge(one, two)

    def test_a_late_phone_merges_two_existing_contacts(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, phone="09121234567")
        two = contacts.identify(b.customer, name="بدون شماره")
        self.assertNotEqual(one.pk, two.pk)
        merged = contacts.identify(b.customer, phone="09121234567")
        self.assertEqual(merged.pk, one.pk)
        self.assertEqual(Contact.objects.filter(store=self.store).count(), 1)

    def test_unlink_undoes_a_wrong_merge(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, username="same_handle")
        contacts.identify(b.customer, username="same_handle")
        fresh = contacts.unlink(b.customer)
        self.assertNotEqual(fresh.pk, one.pk)
        self.assertEqual(ContactLink.objects.get(customer=b.customer).contact_id, fresh.pk)
        self.assertEqual(ContactLink.objects.filter(contact=one).count(), 1)

    def test_merge_keeps_the_strictest_opt_out_and_unions_tags(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer)
        two = contacts.identify(b.customer)
        one.tags = ["vip"]
        one.save()
        contacts.set_opt_out(two, "BALE", True)
        two.tags = ["gym"]
        two.save()
        merged = contacts.merge(one, two)
        self.assertEqual(merged.tags, ["gym", "vip"])
        self.assertTrue(merged.opted_out_of("BALE"))
        self.assertFalse(merged.opted_out_of("TELEGRAM"))

    def test_stats_count_only_paid_orders(self):
        a = self.conversation("TELEGRAM", sender="t1")
        contact = contacts.identify(a.customer)
        Order.objects.create(store=self.store, customer=a.customer, status=Order.Status.DRAFT, total=900)
        Order.objects.create(store=self.store, customer=a.customer, status=Order.Status.CONFIRMED, total=500)
        Order.objects.create(store=self.store, customer=a.customer, status=Order.Status.CASH_ON_DELIVERY, total=300)
        contacts.refresh_stats(contact)
        self.assertEqual(contact.orders_count, 2)
        self.assertEqual(float(contact.total_spent), 800.0)
        self.assertIsNotNone(contact.last_purchase_at)

    def test_history_merges_every_channel_in_time_order(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("SMS", sender="989121234567")
        contact = contacts.identify(a.customer, phone="09121234567")
        contacts.identify(b.customer, phone="09121234567")
        self.customer_says(a, "از تلگرام")
        self.customer_says(b, "از پیامک")
        history = contacts.history(contact)
        self.assertEqual([h["channel"] for h in history], ["TELEGRAM", "SMS"])


class SignalTests(InboxTestCase):
    def test_a_customer_message_counts_unread_and_reading_clears_it(self):
        conversation = self.conversation()
        self.customer_says(conversation, "یک")
        self.customer_says(conversation, "دو")
        self.assertEqual(conversation.inbox_meta.unread_count, 2)
        replies.mark_read(conversation)
        conversation.inbox_meta.refresh_from_db()
        self.assertEqual(conversation.inbox_meta.unread_count, 0)

    def test_a_closed_thread_reopens_when_the_customer_writes_again(self):
        conversation = self.conversation(state=Conversation.State.RESOLVED)
        self.customer_says(conversation, "هنوز مشکل دارم")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.AI)
        self.assertEqual(conversation.inbox_meta.reopened_count, 1)

    def test_with_the_bot_off_a_reopened_thread_goes_to_a_person(self):
        cfg = team.settings_for(self.store)
        cfg.bot_enabled = False
        cfg.save()
        conversation = self.conversation(state=Conversation.State.RESOLVED)
        self.customer_says(conversation, "سلام")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.ESCALATED)
        self.assertIsNotNone(conversation.inbox_meta.waiting_since)

    def test_notes_never_reach_the_ai_history(self):
        """Internal notes are a different table - no prompt built from messages can see them."""
        conversation = self.conversation(state=Conversation.State.HUMAN)
        replies.add_note(conversation, self.sara, "این مشتری بدحساب است")
        self.assertEqual(conversation.messages.count(), 0)
        self.assertEqual(InternalNote.objects.filter(conversation=conversation).count(), 1)

    def test_mentions_notify_the_colleague_and_ignore_strangers(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        note = replies.add_note(conversation, self.sara, "@reza لطفاً پیگیری کن، @ghost و @sara هم")
        self.assertEqual(note.mentions, ["reza", "sara"])
        alerts = Notification.objects.filter(store=self.store, context__mention=True)
        self.assertEqual([a.context["for_user"] for a in alerts], ["reza"])  # not yourself, not a stranger


class AssignmentTests(InboxTestCase):
    def set_mode(self, mode, **extra):
        cfg = team.settings_for(self.store)
        cfg.assignment_mode = mode
        for key, value in extra.items():
            setattr(cfg, key, value)
        cfg.save()

    def escalate(self, **kw):
        conversation = self.conversation(**kw)
        conversation.state = Conversation.State.ESCALATED
        conversation.save()
        conversation.refresh_from_db()
        return conversation

    def test_manual_leaves_it_unassigned_but_the_clock_starts(self):
        self.online(self.sara)
        conversation = self.escalate()
        self.assertIsNone(conversation.assigned_to)
        self.assertIsNotNone(conversation.inbox_meta.waiting_since)
        self.assertIsNotNone(conversation.inbox_meta.sla_due_at)

    def test_round_robin_alternates_between_online_agents(self):
        self.set_mode(InboxSettings.Assignment.ROUND_ROBIN)
        self.online(self.sara, self.reza)
        got = [self.escalate(sender=f"u{i}").assigned_to.username for i in range(4)]
        self.assertEqual(sorted(set(got)), ["reza", "sara"])
        self.assertEqual(got[0], got[2])
        self.assertEqual(got[1], got[3])
        self.assertNotEqual(got[0], got[1])

    def test_offline_agents_are_skipped_and_nobody_online_means_the_queue(self):
        self.set_mode(InboxSettings.Assignment.ROUND_ROBIN)
        self.online(self.sara)
        self.assertEqual(self.escalate(sender="a").assigned_to, self.sara)
        team.set_status(self.store, self.sara, AgentProfile.Status.BUSY)
        self.assertIsNone(self.escalate(sender="b").assigned_to)  # busy is not available
        self.set_mode(InboxSettings.Assignment.ROUND_ROBIN, assign_only_online=False)
        self.assertIsNotNone(self.escalate(sender="c").assigned_to)

    def test_presence_expires_when_the_panel_goes_quiet(self):
        self.online(self.sara)
        profile = AgentProfile.objects.get(user=self.sara)
        self.assertEqual(profile.effective_status, AgentProfile.Status.ONLINE)
        profile.last_seen_at = timezone.now() - timedelta(minutes=10)
        profile.save()
        self.assertEqual(profile.effective_status, AgentProfile.Status.OFFLINE)

    def test_the_busy_choice_survives_a_heartbeat_but_offline_wakes_up(self):
        team.set_status(self.store, self.sara, AgentProfile.Status.BUSY)
        team.heartbeat(self.store, self.sara)
        self.assertEqual(AgentProfile.objects.get(user=self.sara).status, AgentProfile.Status.BUSY)
        team.set_status(self.store, self.reza, AgentProfile.Status.OFFLINE)
        team.heartbeat(self.store, self.reza)
        self.assertEqual(AgentProfile.objects.get(user=self.reza).status, AgentProfile.Status.ONLINE)

    def test_by_channel_prefers_the_person_who_named_the_channel(self):
        self.set_mode(InboxSettings.Assignment.BY_CHANNEL)
        self.online(self.sara, self.reza)
        profile = team.profile_for(self.store, self.reza)
        profile.channels = ["RUBIKA"]
        profile.save()
        self.assertEqual(self.escalate(channel="RUBIKA", sender="r1").assigned_to, self.reza)
        # a channel nobody named falls back to everyone who covers all channels
        self.assertEqual(self.escalate(channel="BALE", sender="b1").assigned_to, self.sara)

    def test_by_skill_matches_tags_and_falls_back(self):
        self.set_mode(InboxSettings.Assignment.BY_SKILL)
        self.online(self.sara, self.reza)
        profile = team.profile_for(self.store, self.reza)
        profile.skills = ["پرداخت"]
        profile.save()
        conversation = self.conversation(sender="s1")
        conversation.tags = ["پرداخت"]
        conversation.state = Conversation.State.ESCALATED
        conversation.save()
        conversation.refresh_from_db()
        self.assertEqual(conversation.assigned_to, self.reza)
        self.assertIsNotNone(self.escalate(sender="s2").assigned_to)  # no skill match: still someone

    def test_max_open_is_respected(self):
        self.set_mode(InboxSettings.Assignment.ROUND_ROBIN)
        self.online(self.sara)
        profile = team.profile_for(self.store, self.sara)
        profile.max_open = 1
        profile.save()
        self.assertEqual(self.escalate(sender="a").assigned_to, self.sara)
        self.assertIsNone(self.escalate(sender="b").assigned_to)

    def test_a_person_is_never_overridden(self):
        self.set_mode(InboxSettings.Assignment.ROUND_ROBIN)
        self.online(self.sara, self.reza)
        conversation = self.conversation()
        conversation.assigned_to = self.admin
        conversation.state = Conversation.State.ESCALATED
        conversation.save()
        conversation.refresh_from_db()
        self.assertEqual(conversation.assigned_to, self.admin)

    def test_a_viewer_is_never_offered_a_conversation(self):
        self.assertNotIn(self.viewer, team.members(self.store))
        self.assertIn(self.sara, team.members(self.store))
        self.assertIn(self.owner, team.members(self.store))

    def test_assign_from_the_first_message_when_the_store_asks(self):
        self.set_mode(InboxSettings.Assignment.ROUND_ROBIN, assign_when=InboxSettings.AssignWhen.ALWAYS)
        self.online(self.sara)
        conversation = self.conversation()
        self.customer_says(conversation)
        conversation.refresh_from_db()
        self.assertEqual(conversation.assigned_to, self.sara)

    def test_transfer_leaves_a_note_the_receiver_sees(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        team.transfer(conversation, self.reza, by=self.sara, note="پرداخت دارد")
        conversation.refresh_from_db()
        self.assertEqual(conversation.assigned_to, self.reza)
        note = InternalNote.objects.get(conversation=conversation)
        self.assertIn("reza", note.text)
        self.assertEqual(note.mentions, ["reza"])


class SlaTests(InboxTestCase):
    def escalated(self, minutes_ago=0):
        conversation = self.conversation()
        self.customer_says(conversation)
        conversation.state = Conversation.State.ESCALATED
        conversation.save()
        meta = conversation.inbox_meta
        meta.refresh_from_db()
        if minutes_ago:
            shift = timedelta(minutes=minutes_ago)
            meta.waiting_since -= shift
            meta.sla_due_at -= shift
            meta.save()
        return conversation

    def test_due_time_follows_the_store_setting(self):
        cfg = team.settings_for(self.store)
        cfg.sla_first_response_min = 20
        cfg.save()
        conversation = self.escalated()
        meta = conversation.inbox_meta
        meta.refresh_from_db()
        self.assertAlmostEqual((meta.sla_due_at - meta.waiting_since).total_seconds(), 20 * 60, delta=2)

    def test_warning_at_eighty_percent_then_breach_each_exactly_once(self):
        conversation = self.escalated(minutes_ago=13)  # 13 of 15 minutes = 87 percent
        self.assertEqual(sla.status_of(conversation.inbox_meta), "warning")
        first = sla.tick()
        self.assertEqual(first, {"warned": 1, "breached": 0})
        self.assertEqual(sla.tick(), {"warned": 0, "breached": 0})  # not twice
        meta = conversation.inbox_meta
        meta.refresh_from_db()
        meta.waiting_since -= timedelta(minutes=10)
        meta.sla_due_at -= timedelta(minutes=10)
        meta.save()
        self.assertEqual(sla.tick(), {"warned": 0, "breached": 1})
        self.assertEqual(sla.tick(), {"warned": 0, "breached": 0})
        titles = list(Notification.objects.filter(store=self.store).values_list("title", flat=True))
        self.assertEqual(sum("SLA" in t for t in titles), 2)

    def test_a_reply_stops_the_clock_and_records_how_long_it_took(self):
        self.online(self.sara)
        conversation = self.escalated(minutes_ago=7)
        result = replies.reply(conversation, self.sara, "سلام، در خدمتم")
        self.assertGreaterEqual(result["response_seconds"], 7 * 60 - 2)
        meta = conversation.inbox_meta
        meta.refresh_from_db()
        self.assertIsNone(meta.waiting_since)
        self.assertEqual(sla.status_of(meta), "none")
        self.assertGreaterEqual(meta.first_response_seconds, 7 * 60 - 2)
        self.assertEqual(sla.tick(), {"warned": 0, "breached": 0})
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.HUMAN)
        self.assertEqual(conversation.assigned_to, self.sara)  # answering takes ownership

    def test_the_first_response_is_the_first_not_the_latest(self):
        conversation = self.escalated(minutes_ago=5)
        replies.reply(conversation, self.sara, "اول")
        self.customer_says(conversation, "دوباره")
        meta = conversation.inbox_meta
        meta.refresh_from_db()
        meta.waiting_since -= timedelta(minutes=30)
        meta.save()
        replies.reply(conversation, self.sara, "دوم")
        meta.refresh_from_db()
        self.assertLess(meta.first_response_seconds, 10 * 60)

    def test_off_hours_pause_the_clock_until_the_shop_opens(self):
        cfg = team.settings_for(self.store)
        cfg.working_hours = {"days": [5, 6, 0, 1, 2], "start": "09:00", "end": "18:00"}
        cfg.sla_first_response_min = 15
        cfg.save()
        conversation = self.conversation()
        saturday_7am_tehran = datetime(2026, 11, 14, 3, 30, tzinfo=dt_timezone.utc)
        meta = sla.start(conversation, now=saturday_7am_tehran)
        opens = datetime(2026, 11, 14, 5, 30, tzinfo=dt_timezone.utc)  # 09:00 Tehran
        self.assertEqual(meta.sla_due_at, opens + timedelta(minutes=15))

    def test_thursday_night_waits_for_saturday(self):
        cfg = team.settings_for(self.store)
        cfg.working_hours = {"days": [5, 6, 0, 1, 2], "start": "09:00", "end": "18:00"}
        cfg.save()
        thursday_noon = datetime(2026, 11, 12, 8, 30, tzinfo=dt_timezone.utc)
        self.assertFalse(hours.is_open(cfg.working_hours, thursday_noon))
        nxt = hours.next_open(cfg.working_hours, thursday_noon)
        self.assertEqual(nxt.astimezone(hours.TEHRAN).strftime("%a %H:%M"), "Sat 09:00")

    def test_test_conversations_never_run_the_clock(self):
        conversation = self.conversation(channel="TELEGRAM")
        meta, _ = ConversationMeta.objects.get_or_create(conversation=conversation, defaults={"store": self.store})
        meta.is_test = True
        meta.save()
        self.customer_says(conversation)
        conversation.state = Conversation.State.ESCALATED
        conversation.save()
        meta.refresh_from_db()
        self.assertIsNone(meta.waiting_since)
        self.assertEqual(sla.tick(), {"warned": 0, "breached": 0})

    def test_team_performance_is_per_member_and_ignores_tests(self):
        self.online(self.sara, self.reza)
        for minutes in (4, 8):
            replies.reply(self.escalated(minutes_ago=minutes), self.sara, "پاسخ")
        replies.reply(self.escalated(minutes_ago=30), self.reza, "دیر")
        rows = {r["username"]: r for r in team.performance(self.store)}
        self.assertEqual(rows["sara"]["replies"], 2)
        self.assertAlmostEqual(rows["sara"]["avg_response_seconds"], 6 * 60, delta=10)
        self.assertGreater(rows["reza"]["avg_response_seconds"], 25 * 60)
        self.assertEqual(rows["admin1"]["replies"], 0)
        self.assertIsNone(rows["admin1"]["avg_response_seconds"])
        # a test thread's reply is not in anyone's average
        test = self.escalated(minutes_ago=60)
        meta = test.inbox_meta
        meta.is_test = True
        meta.save()
        replies.reply(test, self.sara, "آزمایشی")
        again = {r["username"]: r for r in team.performance(self.store)}
        self.assertEqual(again["sara"]["replies"], 2)
