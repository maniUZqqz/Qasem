"""The panel API: list/thread/reply, permissions, channels, CRM, broadcasts, stats."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message, Order

from . import contacts, guides, replies, team
from .fakes import FakePlatform
from .models import (
    AgentProfile, Broadcast, CannedReply, ChannelConnection, Contact, ContactLink, InboxSettings, InternalNote,
)
from .tests_base import InboxTestCase


class ListAndThreadTests(InboxTestCase):
    def test_longest_waiting_first_then_the_rest_by_recency(self):
        old = self.conversation(sender="old", name="قدیمی", state=Conversation.State.ESCALATED)
        new = self.conversation(sender="new", name="تازه", state=Conversation.State.ESCALATED)
        quiet = self.conversation(sender="q", name="آرام", state=Conversation.State.AI)
        Conversation.objects.filter(pk=old.pk).update(last_customer_at=timezone.now() - timedelta(hours=5))
        Conversation.objects.filter(pk=new.pk).update(last_customer_at=timezone.now() - timedelta(minutes=2))
        data = self.api().get(self.url("v2/")).json()
        names = [c["customer"]["name"] for c in data["conversations"]]
        self.assertEqual(names[:2], ["قدیمی", "تازه"])
        self.assertEqual(names[2], "آرام")
        self.assertEqual(data["counts"]["waiting"], 2)

    def test_filters_channel_assignee_unread_state_search_and_sla(self):
        a = self.conversation("TELEGRAM", sender="a", name="سارا", state=Conversation.State.ESCALATED)
        b = self.conversation("BALE", sender="b", name="بهار", state=Conversation.State.HUMAN)
        b.assigned_to = self.sara
        b.save()
        self.customer_says(a, "سلام درباره پروتئین")
        c = self.api()
        get = lambda q: [x["id"] for x in c.get(self.url("v2/") + q).json()["conversations"]]  # noqa: E731
        self.assertEqual(get("?channel=bale"), [b.id])
        self.assertEqual(get("?channel=BALE,TELEGRAM").__len__(), 2)
        self.assertEqual(get("?assigned=sara"), [b.id])
        self.assertEqual(get("?assigned=nobody"), [a.id])
        self.assertEqual(get("?unread=1"), [a.id])
        self.assertEqual(get("?q=پروتئین"), [a.id])
        self.assertEqual(get("?q=بهار"), [b.id])
        self.assertEqual(get("?state=HUMAN"), [b.id])
        self.assertEqual(get("?sla=breached"), [])
        meta = a.inbox_meta
        meta.sla_breached_at = timezone.now()
        meta.save()
        self.assertEqual(get("?sla=breached"), [a.id])

    def test_test_conversations_are_hidden_by_default_and_marked_when_shown(self):
        real = self.conversation(sender="r", name="واقعی")
        test = self.conversation(sender="t", name="آزمایشی")
        from .sla import meta_for

        meta = meta_for(test)
        meta.is_test = True
        meta.save()
        c = self.api()
        shown = c.get(self.url("v2/")).json()["conversations"]
        self.assertEqual([x["id"] for x in shown], [real.id])
        only = c.get(self.url("v2/?test=only")).json()["conversations"]
        self.assertEqual([(x["id"], x["is_test"]) for x in only], [(test.id, True)])

    def test_other_stores_are_invisible_and_a_viewer_can_read_but_not_write(self):
        mine = self.conversation(sender="m")
        theirs = self.conversation(sender="t", store=self.other_store)
        self.assertEqual(self.api().get(self.url("v2/", self.other_store)).status_code, 404)
        c = self.api(self.viewer)
        self.assertEqual(c.get(self.url("v2/")).status_code, 200)
        self.assertEqual(c.post(self.url(f"v2/{mine.pk}/reply/"), {"text": "x"}, format="json").status_code, 403)
        self.assertEqual(self.api().get(self.url(f"v2/{theirs.pk}/")).status_code, 404)  # id of another store

    def test_the_thread_merges_messages_and_notes_and_reading_clears_unread(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        self.customer_says(conversation, "سلام")
        replies.reply(conversation, self.sara, "درود")
        replies.add_note(conversation, self.sara, "حواست باشد")
        data = self.api(self.sara).get(self.url(f"v2/{conversation.pk}/")).json()
        self.assertEqual([t["type"] for t in data["thread"]], ["message", "message", "note"])
        self.assertEqual(data["thread"][1]["author"], "sara")
        conversation.inbox_meta.refresh_from_db()
        self.assertEqual(conversation.inbox_meta.unread_count, 0)

    def test_viewing_with_read_zero_does_not_mark_read(self):
        conversation = self.conversation()
        self.customer_says(conversation)
        self.api().get(self.url(f"v2/{conversation.pk}/?read=0"))
        conversation.inbox_meta.refresh_from_db()
        self.assertEqual(conversation.inbox_meta.unread_count, 1)


class ActionTests(InboxTestCase):
    def test_reply_delivers_records_the_author_and_takes_the_thread(self):
        conversation = self.conversation(state=Conversation.State.ESCALATED)
        self.customer_says(conversation)
        response = self.api(self.sara).post(self.url(f"v2/{conversation.pk}/reply/"), {"text": "سلام"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["delivered"])
        self.assertEqual(self.sent[-1][2], "سلام")
        conversation.refresh_from_db()
        self.assertEqual((conversation.state, conversation.assigned_to), (Conversation.State.HUMAN, self.sara))

    def test_a_failed_delivery_is_still_recorded_and_said_out_loud(self):
        conversation = self.conversation("BALE", sender="9", state=Conversation.State.HUMAN)  # not connected
        response = self.api(self.sara).post(self.url(f"v2/{conversation.pk}/reply/"), {"text": "سلام"}, format="json")
        body = response.json()
        self.assertFalse(body["delivered"])
        self.assertIn("وصل نشده", body["reason"])
        self.assertEqual(conversation.messages.count(), 1)
        self.assertFalse(conversation.messages.first().inbox_meta.delivered)

    def test_canned_reply_use_is_counted(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        canned = CannedReply.objects.create(store=self.store, title="سلام", text="درود", created_by=self.sara)
        self.api(self.sara).post(self.url(f"v2/{conversation.pk}/reply/"),
                                    {"text": "درود", "canned_id": canned.pk}, format="json")
        canned.refresh_from_db()
        self.assertEqual(canned.use_count, 1)

    def test_empty_and_huge_replies_are_refused(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        c = self.api(self.sara)
        self.assertEqual(c.post(self.url(f"v2/{conversation.pk}/reply/"), {"text": "  "}, format="json").status_code, 400)
        self.assertEqual(c.post(self.url(f"v2/{conversation.pk}/reply/"), {"text": "x" * 5000}, format="json").status_code, 400)

    def test_note_is_internal_only(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        self.api(self.sara).post(self.url(f"v2/{conversation.pk}/note/"), {"text": "@reza نگاه کن"}, format="json")
        self.assertEqual(self.sent, [])
        self.assertEqual(conversation.messages.count(), 0)
        self.assertEqual(InternalNote.objects.get().mentions, ["reza"])
        mine = self.api(self.reza).get(self.url("mentions/")).json()["mentions"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(self.api(self.sara).get(self.url("mentions/")).json()["mentions"], [])

    def test_transfer_and_putting_it_back(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        c = self.api(self.sara)
        out = c.post(self.url(f"v2/{conversation.pk}/assign/"), {"username": "reza", "note": "پرداخت"}, format="json").json()
        self.assertEqual(out["assigned_to"]["username"], "reza")
        out = c.post(self.url(f"v2/{conversation.pk}/assign/"), {"username": "nobody"}, format="json").json()
        self.assertIsNone(out["assigned_to"])
        bad = c.post(self.url(f"v2/{conversation.pk}/assign/"), {"username": "viewer"}, format="json")
        self.assertEqual(bad.status_code, 400)
        mine = c.post(self.url(f"v2/{conversation.pk}/assign/"), {"username": "me"}, format="json").json()
        self.assertEqual(mine["assigned_to"]["username"], "sara")

    def test_close_reopen_take_and_give_back(self):
        conversation = self.conversation(state=Conversation.State.ESCALATED)
        self.customer_says(conversation)
        c = self.api(self.sara)
        post = lambda action: c.post(self.url(f"v2/{conversation.pk}/state/"), {"action": action}, format="json")  # noqa: E731
        self.assertEqual(post("close").json()["state"], "RESOLVED")
        conversation.inbox_meta.refresh_from_db()
        self.assertIsNone(conversation.inbox_meta.waiting_since)
        self.assertEqual(post("reopen").json()["state"], "HUMAN")
        self.assertEqual(post("give_to_ai").json()["state"], "AI")
        self.assertEqual(post("take_from_ai").json()["state"], "HUMAN")
        self.assertEqual(post("explode").status_code, 400)

    def test_tags_are_cleaned_and_capped(self):
        conversation = self.conversation()
        out = self.api(self.sara).post(
            self.url(f"v2/{conversation.pk}/tags/"), {"tags": ["پرداخت", "پرداخت", "  ", "x" * 80] + list("abcdefghijklm")},
            format="json").json()
        self.assertEqual(out["tags"][0], "پرداخت")
        self.assertEqual(len(out["tags"]), 12)
        self.assertEqual(len(out["tags"][1]), 40)

    def test_followup_from_a_conversation(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        c = self.api(self.sara)
        ok = c.post(self.url(f"v2/{conversation.pk}/followup/"), {"text": "پیگیری سفارش", "in_hours": 24}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(c.post(self.url(f"v2/{conversation.pk}/followup/"), {"text": "x"}, format="json").status_code, 400)
        thread = c.get(self.url(f"v2/{conversation.pk}/")).json()
        self.assertEqual(len(thread["followups"]), 1)

    def test_canned_replies_crud_and_channel_filter(self):
        c = self.api(self.sara)
        made = c.post(self.url("canned/"), {"title": "ساعت کاری", "text": "۹ تا ۱۸", "shortcut": "/hours",
                                            "channels": ["bale"]}, format="json")
        self.assertEqual(made.status_code, 201)
        self.assertEqual(made.json()["shortcut"], "hours")
        self.assertEqual(len(c.get(self.url("canned/?channel=bale")).json()["replies"]), 1)
        self.assertEqual(len(c.get(self.url("canned/?channel=telegram")).json()["replies"]), 0)
        pk = made.json()["id"]
        c.patch(self.url(f"canned/{pk}/"), {"text": "۹ تا ۲۰"}, format="json")
        self.assertEqual(CannedReply.objects.get(pk=pk).text, "۹ تا ۲۰")
        self.assertEqual(c.delete(self.url(f"canned/{pk}/")).status_code, 204)


class SettingsAndTeamTests(InboxTestCase):
    def test_only_admins_change_settings_and_values_are_validated(self):
        self.assertEqual(self.api(self.sara).patch(self.url("settings/"), {"assignment_mode": "ROUND_ROBIN"}, format="json").status_code, 403)
        c = self.api(self.admin)
        ok = c.patch(self.url("settings/"), {
            "assignment_mode": "ROUND_ROBIN", "sla_first_response_min": 10, "bot_min_confidence": 0.8,
            "working_hours": {"days": [5, 6, 0], "start": "08:30", "end": "17:00"},
            "rate_limits": {"bale": 200, "telegram": 5, "nonsense": 9},
            "widget": {"color": "red-ish", "title": "گفتگو با چغر", "position": "right"},
        }, format="json")
        self.assertEqual(ok.status_code, 200)
        cfg = InboxSettings.objects.get(store=self.store)
        self.assertEqual(cfg.assignment_mode, "ROUND_ROBIN")
        self.assertEqual(cfg.rate_limits, {"BALE": 120, "TELEGRAM": 5})  # capped, junk dropped
        self.assertEqual(cfg.widget["color"], "#2563eb")  # a bad colour never reaches a page
        self.assertEqual(cfg.widget["position"], "right")
        for bad in ({"assignment_mode": "RANDOM"}, {"sla_first_response_min": 0}, {"bot_min_confidence": 3},
                    {"working_hours": {"days": [1], "start": "18:00", "end": "09:00"}}):
            self.assertEqual(c.patch(self.url("settings/"), bad, format="json").status_code, 400, bad)

    def test_settings_come_back_with_the_effective_keywords(self):
        data = self.api().get(self.url("settings/")).json()
        self.assertIn("اپراتور", data["bot_handoff_keywords_effective"])
        self.assertEqual(data["default_working_hours"]["start"], "09:00")

    def test_presence_endpoint_and_team_view(self):
        c = self.api(self.sara)
        self.assertEqual(c.post(self.url("presence/"), {"status": "BUSY", "note": "جلسه"}, format="json").json()["status"], "BUSY")
        data = self.api().get(self.url("team/")).json()
        rows = {m["username"]: m for m in data["members"]}
        self.assertEqual(rows["sara"]["status"], "BUSY")
        self.assertEqual(rows["sara"]["status_note"], "جلسه")
        self.assertEqual(rows["reza"]["status"], "OFFLINE")
        self.assertNotIn("viewer", rows)

    def test_member_settings_need_settings_permission(self):
        body = {"channels": ["bale", "bogus"], "skills": ["پرداخت"], "max_open": 5, "accepts_chats": False}
        self.assertEqual(self.api(self.sara).patch(self.url("team/reza/"), body, format="json").status_code, 403)
        self.assertEqual(self.api(self.admin).patch(self.url("team/reza/"), body, format="json").status_code, 200)
        profile = AgentProfile.objects.get(user=self.reza)
        self.assertEqual((profile.channels, profile.skills, profile.max_open, profile.accepts_chats),
                         (["BALE"], ["پرداخت"], 5, False))
        self.assertEqual(self.api(self.admin).patch(self.url("team/viewer/"), body, format="json").status_code, 400)

    def test_stats_summarise_the_queue(self):
        self.conversation(state=Conversation.State.ESCALATED, sender="a")
        self.conversation(state=Conversation.State.AI, sender="b")
        data = self.api().get(self.url("stats/")).json()
        self.assertEqual((data["open"], data["waiting_for_person"], data["unassigned"]), (2, 1, 1))
        self.assertIn("survey", data)


class ChannelPageTests(InboxTestCase):
    def test_every_channel_has_a_guide_with_steps_fields_and_a_health_story(self):
        rows = {c["kind"]: c for c in self.api().get(self.url("channels/")).json()["channels"]}
        self.assertEqual(list(rows), guides.CHANNEL_ORDER)
        for kind, row in rows.items():
            self.assertGreaterEqual(len(row["steps"]), 3, kind)
            self.assertTrue(row["summary"] and row["limits"], kind)
            self.assertIn("health", row)
        for kind in ("TELEGRAM", "BALE", "EITAA", "RUBIKA", "WHATSAPP"):
            self.assertTrue(any(f["key"] == "token" and f["secret"] for f in rows[kind]["fields"]), kind)
        self.assertTrue(rows["BALE"]["hook_url"].endswith("/"))
        self.assertIn("/api/v1/inbox/hook/bale/", rows["BALE"]["hook_url"])
        self.assertIn("<script src=", rows["WEBCHAT"]["snippet"])
        self.assertTrue(rows["WHATSAPP"]["needs_owner_account"])
        self.assertFalse(rows["WHATSAPP"]["enabled"])  # off by default

    def test_connecting_bale_checks_the_token_then_turns_it_on(self):
        c = self.api(self.admin)
        with FakePlatform({"getMe": {"ok": True, "result": {"username": "my_bot"}},
                           "getUpdates": {"ok": True, "result": []}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            response = c.put(self.url("channels/BALE/"), {"token": "123:GOODTOKENGOODTOKENGOODTOKEN", "enabled": True}, format="json")
        body = response.json()
        self.assertTrue(body["channel"]["enabled"])
        self.assertTrue(body["channel"]["health"]["ok"])
        self.assertEqual(body["channel"]["health"]["account"], "@my_bot")
        self.assertEqual(body["channel"]["masked_token"], "••••OKEN")
        self.assertNotIn("GOODTOKEN", response.content.decode())  # the token never comes back
        self.assertIn("پرسش دوره‌ای", body["message"])  # plain http test host: polling, not webhook

    def test_a_bad_token_cannot_be_switched_on(self):
        c = self.api(self.admin)
        with FakePlatform({"getMe": (401, {"ok": False, "error_code": 401, "description": "Unauthorized"})}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            body = c.put(self.url("channels/BALE/"), {"token": "123:BADBADBADBADBADBADBADBAD", "enabled": True}, format="json").json()
        self.assertFalse(body["channel"]["enabled"])
        self.assertIn("پذیرفته نشد", body["enabled_refused"])

    def test_support_staff_cannot_touch_credentials(self):
        r = self.api(self.sara).put(self.url("channels/BALE/"), {"token": "x" * 30}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_masked_or_blank_secret_keeps_the_stored_one(self):
        self.connect("WHATSAPP", token="T" * 30, enabled=False, config={"app_secret": "keepme", "phone_number_id": "1"})
        self.api(self.admin).put(self.url("channels/WHATSAPP/"), {"token": "••••TTTT", "app_secret": "", "phone_number_id": "2"}, format="json")
        row = ChannelConnection.objects.get(store=self.store, kind="WHATSAPP")
        self.assertEqual(row.token, "T" * 30)
        self.assertEqual(row.config["app_secret"], "keepme")
        self.assertEqual(row.config["phone_number_id"], "2")

    def test_whatsapp_cannot_be_enabled_without_its_account_details(self):
        body = self.api(self.admin).put(self.url("channels/WHATSAPP/"), {"token": "T" * 30, "enabled": True}, format="json").json()
        self.assertFalse(body["channel"]["enabled"])
        self.assertIn("App Secret", body["enabled_refused"])

    def test_telegram_token_is_stored_where_the_old_sender_reads_it(self):
        with FakePlatform({"getMe": {"ok": True, "result": {"username": "tg"}}}) as fake, \
                override_settings(INBOX_API_BASES={"TELEGRAM": fake.url}):
            self.api(self.admin).put(self.url("channels/TELEGRAM/"), {"token": "777:NEWTELEGRAMTOKENNEWTELEGRAM"}, format="json")
        self.store.profile.refresh_from_db()
        self.assertEqual(self.store.profile.telegram_bot_token, "777:NEWTELEGRAMTOKENNEWTELEGRAM")
        self.assertIn("/api/v1/webhooks/telegram/", self.api().get(self.url("channels/")).json()["channels"][0]["hook_url"])

    def test_check_poll_and_webhook_registration_endpoints(self):
        self.connect("RUBIKA", token="R" * 30)
        c = self.api(self.admin)
        updates = {"status": "OK", "data": {"updates": [{"type": "NewMessage", "chat_id": "b0z", "new_message": {
            "message_id": "m1", "text": "سلام", "sender_type": "User", "sender_id": "u0z"}}], "next_offset_id": "n1"}}
        with FakePlatform({"getMe": {"status": "OK", "data": {"bot": {"username": "rb"}}}, "getUpdates": updates,
                           "updateBotEndpoints": {"status": "OK", "data": {}}}) as fake, \
                override_settings(INBOX_API_BASES={"RUBIKA": fake.url}), \
                patch("apps.customers.views_webhook._respond_later"):
            self.assertTrue(c.post(self.url("channels/RUBIKA/check/")).json()["ok"])
            polled = c.post(self.url("channels/RUBIKA/poll/")).json()
            self.assertEqual(polled["accepted"], 1)
            again = c.post(self.url("channels/RUBIKA/poll/")).json()
            self.assertEqual(again["polled"], True)
            self.assertTrue(c.post(self.url("channels/RUBIKA/webhook/")).json()["ok"])
        self.assertEqual(Conversation.objects.filter(channel="RUBIKA").count(), 1)
        row = ChannelConnection.objects.get(store=self.store, kind="RUBIKA")
        self.assertEqual(row.poll_cursor, "n1")
        self.assertTrue(row.config["webhook_registered"])

    def test_polling_never_double_delivers_the_same_message(self):
        from . import ingest

        row = self.connect("BALE")
        upd = {"ok": True, "result": [{"update_id": 3, "message": {
            "message_id": 8, "from": {"id": 5, "first_name": "ع"}, "chat": {"id": 5, "type": "private"}, "text": "یک"}}]}
        with FakePlatform({"getUpdates": upd}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}), \
                patch("apps.customers.views_webhook._respond_later") as respond:
            ingest.poll_connection(row)
            row.poll_cursor = ""  # even if the cursor were lost, the platform id makes it idempotent
            ingest.poll_connection(row)
        self.assertEqual(Message.objects.filter(conversation__channel="BALE").count(), 1)
        self.assertEqual(respond.call_count, 1)

    def test_a_polling_error_is_recorded_on_the_connection_not_raised(self):
        from . import ingest

        row = self.connect("BALE")
        with FakePlatform({"getUpdates": (401, {"ok": False, "error_code": 401})}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            result = ingest.poll_connection(row)
        self.assertFalse(result["polled"])
        row.refresh_from_db()
        self.assertFalse(row.health_ok)
        self.assertIn("پذیرفته نشد", row.last_error)


class ContactApiTests(InboxTestCase):
    def test_the_customer_panel_has_profile_orders_segments_and_history_across_channels(self):
        a = self.conversation("TELEGRAM", sender="t1", name="سارا", state=Conversation.State.HUMAN)
        b = self.conversation("SMS", sender="989121234567", name="", state=Conversation.State.HUMAN)
        contacts.identify(a.customer, phone="09121234567", name="سارا")
        contacts.identify(b.customer, phone="09121234567")
        self.customer_says(a, "از تلگرام")
        self.customer_says(b, "از پیامک")
        for _ in range(3):
            Order.objects.create(store=self.store, customer=a.customer, status=Order.Status.CONFIRMED, total=100)
        data = self.api(self.sara).get(self.url(f"v2/{a.pk}/contact/")).json()
        self.assertEqual(data["phone"], "09121234567")
        self.assertEqual({c["channel"] for c in data["customers"]}, {"TELEGRAM", "SMS"})
        self.assertEqual(data["orders_count"], 3)
        self.assertEqual(len(data["orders"]), 3)
        self.assertIn("مشتریِ دائمی", data["segments"])
        self.assertEqual([h["channel"] for h in data["history"]], ["TELEGRAM", "SMS"])

    def test_edit_tags_notes_and_opt_out(self):
        contact = Contact.objects.create(store=self.store, name="آ", phone="09120000001")
        c = self.api(self.sara)
        out = c.patch(self.url(f"contacts/{contact.pk}/"), {
            "tags": ["vip", "vip", " "], "notes": "ترجیح می‌دهد صبح", "opt_out": {"ALL": True}}, format="json").json()
        self.assertEqual(out["tags"], ["vip"])
        self.assertEqual(out["opt_out"], {"ALL": True})
        clash = Contact.objects.create(store=self.store, name="ب", phone="09120000002")
        r = c.patch(self.url(f"contacts/{clash.pk}/"), {"phone": "0912 000 0001"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ادغام", r.json()["error"]["message"])

    def test_merge_and_unlink_through_the_api(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, name="یک")
        two = contacts.identify(b.customer, name="دو")
        c = self.api(self.sara)
        merged = c.post(self.url(f"contacts/{one.pk}/merge/"), {"with_contact": two.pk}, format="json").json()
        self.assertEqual(len(merged["customers"]), 2)
        self.assertEqual(Contact.objects.filter(store=self.store).count(), 1)
        split = c.post(self.url(f"customers/{b.customer.pk}/unlink/")).json()
        self.assertEqual(len(split["customers"]), 1)
        self.assertEqual(Contact.objects.filter(store=self.store).count(), 2)

    def test_listing_searching_and_upserting_by_phone(self):
        c = self.api(self.sara)
        self.assertEqual(c.post(self.url("contacts/"), {"name": "علی", "phone": "۰۹۱۲۳۴۵۶۷۸۹", "tags": ["gym"]}, format="json").status_code, 201)
        again = c.post(self.url("contacts/"), {"phone": "+98 912 345 6789"}, format="json")
        self.assertIn(again.status_code, (200, 201))
        found = c.get(self.url("contacts/?q=09123456789")).json()
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["contacts"][0]["tags"], ["gym"])
        self.assertEqual(c.get(self.url("contacts/?tag=GYM")).json()["total"], 1)

    def test_segments_api_lists_counts_previews_and_protects_builtins(self):
        Contact.objects.create(store=self.store, name="دائمی", orders_count=5)
        c = self.api(self.sara)
        listing = c.get(self.url("segments/")).json()
        loyal = next(s for s in listing["segments"] if s["builtin_key"] == "loyal")
        self.assertEqual(loyal["count"], 1)
        self.assertEqual(c.patch(self.url(f"segments/{loyal['id']}/"), {"name": "x"}, format="json").status_code, 400)
        self.assertEqual(c.delete(self.url(f"segments/{loyal['id']}/")).status_code, 400)
        made = c.post(self.url("segments/"), {"name": "خرج‌کرده‌ها", "rules": {"rules": [
            {"field": "total_spent", "op": "gte", "value": 1}]}}, format="json")
        self.assertEqual(made.status_code, 201)
        preview = c.post(self.url("segments/preview/"), {"rules": {"rules": [{"field": "orders_count", "op": "gte", "value": 1}]}}, format="json").json()
        self.assertEqual(preview["count"], 1)
        bad = c.post(self.url("segments/"), {"name": "بد", "rules": {"rules": [{"field": "zzz", "op": "eq"}]}}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(c.delete(self.url(f"segments/{made.json()['id']}/")).status_code, 204)


class BroadcastApiTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        self.connect("BALE")
        for i in range(3):
            contact = Contact.objects.create(store=self.store, name=f"م{i}", phone=f"0912111111{i}")
            customer = Customer.objects.create(store=self.store, name=contact.name, channel="bale", external_id=f"b{i}")
            ContactLink.objects.create(contact=contact, customer=customer, matched_by="new")

    def test_support_drafts_admin_approves_and_it_sends(self):
        support, admin = self.api(self.sara), self.api(self.admin)
        made = support.post(self.url("broadcasts/"), {"name": "آخر هفته", "text": "سلام {name}", "channels": ["bale"]}, format="json")
        self.assertEqual(made.status_code, 201)
        pk = made.json()["id"]
        preview = support.get(self.url(f"broadcasts/{pk}/preview/")).json()
        self.assertEqual(preview["recipients"], 3)
        self.assertEqual(support.post(self.url(f"broadcasts/{pk}/submit/")).json()["status"], "PENDING")
        denied = support.post(self.url(f"broadcasts/{pk}/approve/"))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(Broadcast.objects.get(pk=pk).status, "PENDING")
        self.assertTrue(admin.get(self.url("broadcasts/")).json()["can_approve"])
        self.assertFalse(support.get(self.url("broadcasts/")).json()["can_approve"])
        self.assertEqual(admin.post(self.url(f"broadcasts/{pk}/approve/")).json()["status"], "APPROVED")
        locked = support.patch(self.url(f"broadcasts/{pk}/"), {"text": "عوض شد"}, format="json")
        self.assertEqual(locked.status_code, 400)  # an approved text cannot be swapped under the approver
        from . import broadcast as bc

        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 1}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            self.assertEqual(bc.send_tick()["sent"], 3)
        detail = admin.get(self.url(f"broadcasts/{pk}/")).json()
        self.assertEqual(detail["status"], "SENT")
        self.assertEqual(len(detail["recipients_sample"]), 3)

    def test_a_viewer_cannot_make_one_and_other_stores_cannot_see_it(self):
        self.assertEqual(self.api(self.viewer).post(self.url("broadcasts/"), {"name": "x", "text": "y"}, format="json").status_code, 403)
        made = self.api(self.sara).post(self.url("broadcasts/"), {"name": "a", "text": "b"}, format="json").json()
        self.assertEqual(self.api(self.other_owner).get(self.url(f"broadcasts/{made['id']}/", self.other_store)).status_code, 404)

    def test_marketing_role_can_draft_but_not_approve(self):
        from apps.stores.models import Membership
        from django.contrib.auth.models import User

        marketer = User.objects.create_user("mkt", password="x")
        Membership.objects.create(store=self.store, user=marketer, role=Membership.Role.MARKETING)
        c = self.api(marketer)
        made = c.post(self.url("broadcasts/"), {"name": "a", "text": "b", "channels": ["bale"]}, format="json")
        self.assertEqual(made.status_code, 201)
        pk = made.json()["id"]
        c.post(self.url(f"broadcasts/{pk}/submit/"))
        self.assertEqual(c.post(self.url(f"broadcasts/{pk}/approve/")).status_code, 403)

    def test_followups_list_and_cancel(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        c = self.api(self.sara)
        made = c.post(self.url(f"v2/{conversation.pk}/followup/"), {"text": "پیگیری", "in_hours": 2}, format="json").json()
        self.assertEqual(len(c.get(self.url("followups/?status=pending")).json()["followups"]), 1)
        self.assertEqual(c.delete(self.url(f"followups/{made['id']}/")).json()["status"], "CANCELLED")
