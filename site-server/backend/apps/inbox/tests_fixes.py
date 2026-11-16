"""The second round: what the review of the live inbox found, each with the test that would have caught it.

Widget flooding and the forged address, a survey answer that reopened the thread, `{name}`
that reached customers as braces, a waiting clock that never stopped, a demo that was half
invisible, silence after «آدم می‌خواهم», English codes in the Persian panel, and the small
inconsistencies around them.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message

from . import (
    adapters, bot, contacts, demo, dispatch, followups, ingest, replies, segments, serializers,
    signals, surveys, team, views_widget,
)
from .adapters.base import Incoming
from .fakes import FakePlatform
from .models import (
    Broadcast, BroadcastRecipient, CannedReply, ChannelConnection, Contact, ContactLink, ConversationMeta,
    InboxSettings, SatisfactionSurvey, WebhookDelivery, WebhookEndpoint, WidgetSession,
)
from .tests_base import InboxTestCase


# ------------------------------------------------------------------ the widget


@patch("apps.customers.views_webhook._respond_later")
class WidgetFloodTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.row = self.connect("WEBCHAT", token="", config={})
        self.base = f"/api/v1/widget/{self.row.secret}"
        self.http = Client()

    def post(self, path, body=None, **extra):
        return self.http.post(f"{self.base}/{path}/", data=json.dumps(body or {}), content_type="application/json", **extra)

    def rows(self):
        return (Customer.objects.count(), Conversation.objects.count(), Contact.objects.count(), WidgetSession.objects.count())

    def test_a_forged_forwarded_for_does_not_buy_more_sessions(self, _):
        # nginx *appends* to X-Forwarded-For, so its first entry belongs to the caller: it must never count.
        codes = [self.post("session", HTTP_X_FORWARDED_FOR=f"203.0.113.{i}").status_code for i in range(1, 31)]
        self.assertEqual(codes.count(200), views_widget.SESSIONS_PER_HOUR_IP)
        self.assertEqual(codes.count(429), 30 - views_widget.SESSIONS_PER_HOUR_IP)

    def test_the_proxys_real_ip_separates_visitors(self, _):
        # our nginx overwrites X-Real-IP with the socket address: behind it, visitors really are different people
        codes = [self.post("session", HTTP_X_REAL_IP=f"198.51.100.{i}").status_code for i in range(1, 31)]
        self.assertEqual(codes.count(429), 0)

    def test_x_real_ip_is_ignored_when_the_caller_is_not_our_proxy(self, _):
        codes = [
            self.post("session", HTTP_X_REAL_IP=f"198.51.100.{i}", REMOTE_ADDR="8.8.8.8").status_code
            for i in range(1, 31)
        ]
        self.assertEqual(codes.count(200), views_widget.SESSIONS_PER_HOUR_IP)

    def test_client_ip_rules(self, _):
        from django.test import RequestFactory

        rf = RequestFactory()
        local = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="203.0.113.7", HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.7")
        self.assertEqual(views_widget.client_ip(local), "203.0.113.7")
        no_real = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="9.9.9.9")
        self.assertEqual(views_widget.client_ip(no_real), "127.0.0.1")
        junk = rf.get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_REAL_IP="not-an-ip")
        self.assertEqual(views_widget.client_ip(junk), "10.0.0.5")
        public = rf.get("/", REMOTE_ADDR="8.8.4.4", HTTP_X_REAL_IP="203.0.113.7")
        self.assertEqual(views_widget.client_ip(public), "8.8.4.4")

    def test_opening_a_session_writes_nothing(self, _):
        token = self.post("session", {"name": "مریم", "phone": "09121234567"}).json()["token"]
        self.assertTrue(token.startswith("w_"))
        self.assertLessEqual(len(token), 64)
        self.assertEqual(self.rows(), (0, 0, 0, 0))  # no customer, no conversation, no CRM contact
        inbox = self.api(self.sara).get(self.url("v2/")).json()
        self.assertEqual(inbox["conversations"], [])
        # the page can still ask for history with it: empty, not an error
        got = self.http.get(f"{self.base}/messages/", {"token": token, "after": 0})
        self.assertEqual((got.status_code, got.json()["messages"]), (200, []))

    def test_the_first_message_is_what_creates_the_chat_and_only_once(self, respond):
        token = self.post("session").json()["token"]
        first = self.post("send", {"token": token, "text": "سلام", "name": "مریم", "phone": "۰۹۱۲۱۲۳۴۵۶۷"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.rows(), (1, 1, 1, 1))
        contact = Contact.objects.get()
        self.assertEqual((contact.name, contact.phone, contact.source), ("مریم", "09121234567", "webchat"))
        self.post("send", {"token": token, "text": "یک پیام دیگر"})
        self.assertEqual(self.rows(), (1, 1, 1, 1))  # the same visitor, the same chat
        self.assertEqual(Conversation.objects.get().messages.count(), 2)
        respond.assert_called()

    def test_a_forged_or_foreign_ticket_is_not_a_session(self, _):
        forged = "w_" + "a" * 20 + "_" + "b" * 24
        self.assertEqual(self.post("send", {"token": forged, "text": "سلام"}).status_code, 404)
        self.assertEqual(self.http.get(f"{self.base}/messages/", {"token": forged, "after": 0}).status_code, 404)
        other = ChannelConnection.objects.create(store=self.other_store, kind="WEBCHAT", enabled=True)
        theirs = views_widget.new_ticket(other)
        self.assertEqual(self.post("send", {"token": theirs, "text": "سلام"}).status_code, 404)
        self.assertEqual(self.rows(), (0, 0, 0, 0))

    def test_new_chats_per_address_are_limited(self, _):
        codes = []
        for i in range(views_widget.NEW_CHATS_PER_HOUR_IP + 3):
            token = self.post("session").json()["token"]
            codes.append(self.post("send", {"token": token, "text": f"پیام {i}"}).status_code)
        self.assertEqual(codes.count(200), views_widget.NEW_CHATS_PER_HOUR_IP)
        self.assertEqual(codes.count(429), 3)
        self.assertEqual(Conversation.objects.count(), views_widget.NEW_CHATS_PER_HOUR_IP)

    def test_a_visitor_with_a_chat_is_not_a_new_chat(self, _):
        token = self.post("session").json()["token"]
        for i in range(views_widget.SEND_PER_MINUTE):
            self.assertEqual(self.post("send", {"token": token, "text": f"پیام {i}"}).status_code, 200)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_a_session_from_before_the_change_keeps_working(self, _):
        customer = Customer.objects.create(store=self.store, channel="webchat", external_id="v_old", name="قدیمی")
        conversation = Conversation.objects.create(
            store=self.store, customer=customer, channel="WEBCHAT", external_id="v_old", state=Conversation.State.AI,
        )
        WidgetSession.objects.create(connection=self.row, token="legacy-token-" + "x" * 30, customer=customer, conversation=conversation)
        sent = self.post("send", {"token": "legacy-token-" + "x" * 30, "text": "سلام دوباره"})
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(conversation.messages.count(), 1)
        self.assertEqual(Customer.objects.count(), 1)

    def test_the_widget_promises_nothing_the_store_did_not_say(self, _):
        data = self.http.get(f"{self.base}/config/").json()
        self.assertEqual(data["subtitle"], "پیامتان را بنویسید")
        self.assertNotIn("دقیقه", data["subtitle"])
        source = (views_widget.SCRIPT).read_text(encoding="utf-8")
        self.assertNotIn("در چند دقیقه", source)


# ------------------------------------------------- relationship messages (survey, opt-out)


class RelationshipMessageTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cfg = team.settings_for(self.store)
        cfg.survey_enabled = True
        cfg.survey_delay_min = 0
        cfg.save()
        self.conn = self.connect("TELEGRAM")
        WebhookEndpoint.objects.create(store=self.store, url="https://hooks.example.com/x", events=[])
        self._n = 0

    def incoming(self, text):
        self._n += 1
        return Incoming(external_id=f"m{self._n}", thread_id="500", sender_id="500", name="مریم", text=text)

    def closed_and_surveyed(self):
        out = ingest.receive(self.conn, self.incoming("مشکل دارم"))
        conversation = out.conversation
        replies.reply(conversation, self.sara, "حل شد")
        replies.close(conversation, self.sara)
        followups.run_due()
        self.assertEqual(SatisfactionSurvey.objects.filter(conversation=conversation).count(), 1)
        replies.mark_read(conversation)
        WebhookDelivery.objects.all().delete()
        return conversation

    def events(self):
        return set(WebhookDelivery.objects.values_list("event", flat=True))

    def test_a_survey_answer_does_not_reopen_the_closed_conversation(self):
        conversation = self.closed_and_surveyed()
        out = ingest.receive(self.conn, self.incoming("۵"))
        self.assertEqual(out.handled, "survey")
        conversation.refresh_from_db()
        meta = ConversationMeta.objects.get(conversation=conversation)
        self.assertEqual(conversation.state, Conversation.State.RESOLVED)
        self.assertEqual((meta.unread_count, meta.reopened_count), (0, 0))
        self.assertIsNotNone(meta.resolved_at)
        self.assertIsNone(meta.waiting_since)
        survey = SatisfactionSurvey.objects.get(conversation=conversation)
        self.assertEqual(survey.score, 5)
        events = self.events()
        self.assertIn("survey.answered", events)
        self.assertNotIn("conversation.reopened", events)
        self.assertNotIn("message.received", events)
        self.assertIn("ممنون", self.sent[-1][2])

    def test_it_stays_out_of_the_resolved_numbers_and_the_open_list(self):
        conversation = self.closed_and_surveyed()
        ingest.receive(self.conn, self.incoming("۴ ممنون"))
        data = self.api(self.sara).get(self.url("v2/")).json()
        row = next(c for c in data["conversations"] if c["id"] == conversation.pk)
        self.assertEqual((row["state"], row["unread"]), ("RESOLVED", 0))
        self.assertEqual(data["counts"]["unread"], 0)
        stats = self.api(self.sara).get(self.url("stats/")).json()
        self.assertEqual((stats["open"], stats["resolved"]), (0, 1))

    def test_a_real_message_after_the_survey_still_reopens_it(self):
        conversation = self.closed_and_surveyed()
        ingest.receive(self.conn, self.incoming("۵"))
        out = ingest.receive(self.conn, self.incoming("ولی یک سؤال دیگر دارم"))
        self.assertEqual(out.handled, "")
        conversation.refresh_from_db()
        self.assertNotEqual(conversation.state, Conversation.State.RESOLVED)
        self.assertIn("conversation.reopened", self.events())

    def test_the_opt_out_word_does_not_reopen_it_either(self):
        conversation = self.closed_and_surveyed()
        SatisfactionSurvey.objects.all().delete()
        out = ingest.receive(self.conn, self.incoming("لغو"))
        self.assertEqual(out.handled, "opt_out")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.RESOLVED)
        self.assertTrue(Contact.objects.get(store=self.store).opted_out_of("TELEGRAM"))
        self.assertNotIn("conversation.reopened", self.events())

    def test_a_message_from_a_door_that_skips_ingest_is_handled_too(self):
        """The old Telegram/Instagram webhook stores the message without `ingest.receive`."""
        conversation = self.closed_and_surveyed()
        with self.captureOnCommitCallbacks(execute=True):
            self.customer_says(conversation, "۳")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.RESOLVED)
        self.assertEqual(SatisfactionSurvey.objects.get(conversation=conversation).score, 3)
        self.assertEqual(ConversationMeta.objects.get(conversation=conversation).unread_count, 0)

    def test_the_peek_changes_nothing(self):
        conversation = self.closed_and_surveyed()
        message = Message.objects.create(conversation=conversation, role=Message.Role.CUSTOMER, text="5")
        self.assertTrue(surveys.is_answer(conversation, message))
        self.assertIsNone(SatisfactionSurvey.objects.get(conversation=conversation).answered_at)


# ------------------------------------------------------------------ {name}


class PlaceholderTests(InboxTestCase):
    def say(self, conversation, text, **extra):
        return self.api(self.sara).post(self.url(f"v2/{conversation.pk}/reply/"), {"text": text, **extra}, format="json").json()

    def test_a_canned_reply_with_name_reaches_the_customer_filled_in(self):
        canned = CannedReply.objects.create(store=self.store, title="سلام", shortcut="hi", text="سلام {name}، ممنون که پیام دادید.")
        conversation = self.conversation(name="مریم رضایی", sender="u9")
        out = self.say(conversation, canned.text, canned_id=canned.pk)
        self.assertEqual(self.sent[-1][2], "سلام مریم، ممنون که پیام دادید.")  # what the platform got
        self.assertEqual(out["message"]["text"], "سلام مریم، ممنون که پیام دادید.")  # and what the thread shows
        self.assertEqual(conversation.messages.get().text, "سلام مریم، ممنون که پیام دادید.")
        self.assertNotIn("{", self.sent[-1][2])

    def test_an_unknown_name_is_a_friendly_word_never_braces_or_a_label(self):
        for index, name in enumerate(["", "مشتری", "بازدیدکنندهٔ سایت", "09121234567"]):
            conversation = self.conversation(name=name, sender=f"x{index}")
            self.say(conversation, "سلام {name}، چه کمکی از ما برمی‌آید؟")
            self.assertEqual(self.sent[-1][2], "سلام دوست عزیز، چه کمکی از ما برمی‌آید؟", name)

    def test_the_persian_spelling_and_spaces_work_too(self):
        conversation = self.conversation(name="علی", sender="u1")
        self.say(conversation, "درود { نام }!")
        self.assertEqual(self.sent[-1][2], "درود علی!")

    def test_a_text_without_braces_is_untouched(self):
        conversation = self.conversation(name="علی", sender="u1")
        self.say(conversation, "سلام؛ {این} یک متن عادی است")
        self.assertEqual(self.sent[-1][2], "سلام؛ {این} یک متن عادی است")

    def test_system_messages_get_the_name_too(self):
        conversation = self.conversation(name="سارا", sender="u2")
        replies.system_reply(conversation, "{name} عزیز، یادآوری!")
        self.assertEqual(self.sent[-1][2], "سارا عزیز، یادآوری!")

    def test_it_uses_the_contact_name_when_the_customer_has_none(self):
        conversation = self.conversation(name="", sender="u3")
        contacts.identify(conversation.customer, name="نیلوفر احمدی")
        conversation.customer.refresh_from_db()
        conversation = Conversation.objects.get(pk=conversation.pk)
        self.assertEqual(replies.first_name_of(conversation), "نیلوفر")


# --------------------------------------------------------- the waiting clock


class WaitingClockTests(InboxTestCase):
    def row(self, conversation):
        conversation = Conversation.objects.select_related("customer", "assigned_to", "store").get(pk=conversation.pk)
        return serializers.conversation_row(conversation)

    def test_the_clock_stops_when_the_team_answers(self):
        conversation = self.conversation()
        self.customer_says(conversation, "اپراتور")
        self.assertIsNotNone(self.row(conversation)["waiting_minutes"])
        replies.reply(conversation, self.sara, "بفرمایید")
        row = self.row(conversation)
        self.assertEqual(row["state"], "HUMAN")
        self.assertIsNone(row["waiting_minutes"])
        data = self.api(self.sara).get(self.url("v2/")).json()["conversations"]
        self.assertIsNone(data[0]["waiting_minutes"])

    def test_a_thread_without_a_clock_is_judged_by_who_spoke_last(self):
        with signals.suppressed():  # an old thread, or a demo one: the SLA clock never ran
            conversation = self.conversation(state=Conversation.State.HUMAN)
            Message.objects.create(conversation=conversation, role=Message.Role.CUSTOMER, text="سلام")
            Message.objects.create(conversation=conversation, role=Message.Role.HUMAN, text="جواب")
        Conversation.objects.filter(pk=conversation.pk).update(last_customer_at=timezone.now() - timedelta(hours=2))
        self.assertIsNone(self.row(conversation)["waiting_minutes"])
        with signals.suppressed():
            Message.objects.create(conversation=conversation, role=Message.Role.CUSTOMER, text="ببخشید؟")
        self.assertGreaterEqual(self.row(conversation)["waiting_minutes"], 119)

    def test_the_demo_thread_the_owner_saw_no_longer_counts(self):
        demo.seed(self.store, owner=self.owner)
        rows = self.api(self.sara).get(self.url("v2/?test=only")).json()["conversations"]
        by_name = {r["customer"]["name"]: r for r in rows}
        self.assertIsNone(by_name["مربی نمونه ۳"]["waiting_minutes"])  # SMS: the team spoke last
        self.assertIsNotNone(by_name["مربی نمونه ۲"]["waiting_minutes"])  # Telegram: still owed an answer

    def test_the_unassigned_tab_count_is_the_list_it_opens(self):
        for i in range(2):
            self.customer_says(self.conversation(sender=f"p{i}"), "اپراتور")
        failed = self.conversation(sender="f1")
        Conversation.objects.filter(pk=failed.pk).update(ai_failed_at=timezone.now())
        data = self.api(self.sara).get(self.url("v2/")).json()
        listed = self.api(self.sara).get(self.url("v2/?assigned=nobody&state=waiting")).json()["conversations"]
        self.assertEqual(data["counts"]["unassigned"], len(listed))
        self.assertEqual(len(listed), 3)
        team_page = self.api(self.sara).get(self.url("team/")).json()
        self.assertEqual(team_page["unassigned_open"], 3)


# ---------------------------------------------------- the Chagher demo, fully visible


class DemoVisibilityTests(InboxTestCase):
    def test_a_test_chat_does_not_put_a_real_looking_contact_in_the_crm(self):
        customer = Customer.objects.create(store=self.store, channel="web-test", external_id="t1", name="مشتری آزمایشی")
        conversation = Conversation.objects.create(store=self.store, customer=customer, channel="WEB", external_id="t1")
        r = self.api(self.sara).get(self.url(f"v2/{conversation.pk}/contact/"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Contact.objects.get(store=self.store).is_test)
        shown = self.api(self.sara).get(self.url("contacts/")).json()
        self.assertEqual((shown["total"], shown["test_total"]), (0, 1))
        with_tests = self.api(self.sara).get(self.url("contacts/?test=1")).json()
        self.assertEqual(with_tests["total"], 1)
        self.assertTrue(with_tests["contacts"][0]["is_test"])
        self.assertEqual(segments.count_in(self.store, {"rules": []}), 0)  # never in an audience

    def test_the_demo_contacts_and_followup_can_be_looked_at(self):
        demo.seed(self.store, owner=self.owner)
        c = self.api(self.owner)
        plain = c.get(self.url("contacts/")).json()
        self.assertEqual((plain["total"], plain["test_total"]), (0, len(demo.CONVERSATIONS)))
        self.assertEqual(c.get(self.url("contacts/?test=1")).json()["total"], len(demo.CONVERSATIONS))
        follow = c.get(self.url("followups/?status=")).json()
        self.assertEqual((follow["followups"], follow["test_total"]), ([], 1))
        shown = c.get(self.url("followups/?status=&test=1")).json()["followups"]
        self.assertEqual(len(shown), 1)
        self.assertTrue(shown[0]["is_test"])

    def test_a_followup_made_from_a_test_conversation_is_found_under_show_test(self):
        customer = Customer.objects.create(store=self.store, channel="web-test", external_id="t2", name="آزمون")
        conversation = Conversation.objects.create(store=self.store, customer=customer, channel="WEB", external_id="t2")
        made = self.api(self.sara).post(self.url(f"v2/{conversation.pk}/followup/"), {"text": "فردا", "in_hours": 24}, format="json")
        self.assertEqual(made.status_code, 201)
        self.assertEqual(self.api(self.sara).get(self.url("followups/")).json()["followups"], [])
        self.assertEqual(self.api(self.sara).get(self.url("followups/")).json()["test_total"], 1)
        self.assertEqual(len(self.api(self.sara).get(self.url("followups/?test=1")).json()["followups"]), 1)

    def test_seeding_again_never_overwrites_what_the_owner_changed(self):
        demo.seed(self.store, owner=self.owner)
        cfg = team.settings_for(self.store)
        cfg.survey_enabled = False
        cfg.working_hours = {"days": [5], "start": "10:00", "end": "14:00"}
        cfg.widget = {**cfg.widget, "color": "#000000"}
        cfg.save()
        demo.seed(self.store, owner=self.owner)
        cfg.refresh_from_db()
        self.assertFalse(cfg.survey_enabled)
        self.assertEqual(cfg.working_hours["start"], "10:00")
        self.assertEqual(cfg.widget["color"], "#000000")

    def test_the_draft_invents_no_hours_and_promises_no_minutes(self):
        demo.seed(self.store, owner=self.owner)
        cfg = team.settings_for(self.store)
        self.assertEqual(cfg.working_hours, {})
        self.assertEqual(cfg.offhours_message, "")
        self.assertNotIn("دقیقه", cfg.widget["subtitle"])
        self.assertTrue(inbox_open_always(cfg))

    def test_no_demo_text_uses_the_phrase_the_brand_forbids(self):
        texts = [t for _, _, t in demo.CANNED] + [t for t, _, _ in demo.CANNED]
        for _, _, _, _, lines, _, _ in demo.CONVERSATIONS:
            texts += [t for _, t in lines]
        for text in texts:
            self.assertNotIn("جایگزین مربی", text)
            self.assertNotIn("جایگزینِ مربی", text)

    def test_the_data_migration_fixes_what_the_first_release_left_and_only_that(self):
        fix = importlib.import_module("apps.inbox.migrations.0003_fix_test_data_and_demo_wording").fix
        stale = importlib.import_module("apps.inbox.migrations.0003_fix_test_data_and_demo_wording")
        # a contact that only a test chat ever created
        customer = Customer.objects.create(store=self.store, channel="web-test", external_id="t9", name="مشتری آزمایشی")
        ghost = Contact.objects.create(store=self.store, name="مشتری آزمایشی", source="web-test")
        ContactLink.objects.create(contact=ghost, customer=customer, matched_by="new")
        real = Contact.objects.create(store=self.store, name="واقعی")
        ContactLink.objects.create(
            contact=real, customer=Customer.objects.create(store=self.store, channel="telegram", external_id="r1"), matched_by="new",
        )
        # the wording the first release seeded, plus one line the owner rewrote
        CannedReply.objects.create(store=self.store, shortcut="coach", title=stale.CANNED["coach"][0][0], text=stale.CANNED["coach"][0][1])
        CannedReply.objects.create(store=self.store, shortcut="hours", title="ساعت پاسخ‌گویی", text="متن خودِ مالک")
        cfg = team.settings_for(self.store)
        cfg.widget = {"subtitle": stale.OLD_SUBTITLE, "color": "#126F85"}
        cfg.working_hours = stale.OLD_HOURS
        cfg.offhours_message = stale.OLD_OFFHOURS
        cfg.bot_offhours = InboxSettings.OffHours.MESSAGE
        cfg.save()
        other_store_cfg = team.settings_for(self.other_store)
        other_store_cfg.working_hours = stale.OLD_HOURS  # same hours, but the owner's own text: left alone
        other_store_cfg.offhours_message = "ساعت کاری ما ۹ تا ۱۸"
        other_store_cfg.save()

        fix(django_apps, None)
        fix(django_apps, None)  # idempotent

        ghost.refresh_from_db()
        real.refresh_from_db()
        self.assertTrue(ghost.is_test)
        self.assertFalse(real.is_test)
        self.assertEqual(CannedReply.objects.get(shortcut="coach").title, "آیا مربی لازم است؟")
        self.assertEqual(CannedReply.objects.get(shortcut="hours").text, "متن خودِ مالک")
        cfg.refresh_from_db()
        self.assertEqual(cfg.widget, {"subtitle": "پیامتان را بنویسید", "color": "#126F85"})
        self.assertEqual((cfg.working_hours, cfg.offhours_message, cfg.bot_offhours), ({}, "", "BOT"))
        other_store_cfg.refresh_from_db()
        self.assertEqual(other_store_cfg.working_hours, stale.OLD_HOURS)
        self.assertEqual(other_store_cfg.offhours_message, "ساعت کاری ما ۹ تا ۱۸")

    def test_the_data_migration_repairs_the_demo_threads_the_first_seed_made(self):
        mig = importlib.import_module("apps.inbox.migrations.0003_fix_test_data_and_demo_wording")
        demo.seed(self.store, owner=self.owner)
        sms = Conversation.objects.get(store=self.store, external_id="989120000003")
        spoke_last = sms.messages.filter(role=Message.Role.HUMAN).first()
        customer_wrote = sms.messages.filter(role=Message.Role.CUSTOMER).first()
        # the first seed stamped «the customer last wrote» *after* the team's answer
        Conversation.objects.filter(pk=sms.pk).update(last_customer_at=spoke_last.created_at + timedelta(minutes=2))
        old_customer_line, new_customer_line = list(mig.LINES.items())[0]
        old_bot_line, new_bot_line = list(mig.LINES.items())[1]
        Message.objects.filter(text=new_customer_line).update(text=old_customer_line)
        Message.objects.filter(text=new_bot_line).update(text=old_bot_line)
        # a real customer who happens to have typed the same words is not a demo row
        real = self.conversation("TELEGRAM", sender="real1")
        real_message = Message.objects.create(conversation=real, role=Message.Role.CUSTOMER, text=old_customer_line)

        mig.fix(django_apps, None)

        sms.refresh_from_db()
        self.assertEqual(sms.last_customer_at, customer_wrote.created_at)
        self.assertEqual(Message.objects.filter(text=old_customer_line).exclude(pk=real_message.pk).count(), 0)
        self.assertEqual(Message.objects.filter(text=old_bot_line).count(), 0)
        self.assertTrue(Message.objects.filter(text=new_customer_line).exists())
        real_message.refresh_from_db()
        self.assertEqual(real_message.text, old_customer_line)

    def test_the_data_migration_clears_a_stale_channel_error_only_when_a_later_check_passed(self):
        fix = importlib.import_module("apps.inbox.migrations.0003_fix_test_data_and_demo_wording").fix
        now = timezone.now()
        ok = self.connect("BALE", enabled=True)
        ChannelConnection.objects.filter(pk=ok.pk).update(
            health_ok=True, health_checked_at=now, last_error="توکن اشتباه", last_error_at=now - timedelta(hours=1),
        )
        recent = self.connect("EITAA", enabled=True)
        ChannelConnection.objects.filter(pk=recent.pk).update(
            health_ok=True, health_checked_at=now - timedelta(hours=2), last_error="تازه‌تر از بررسی", last_error_at=now,
        )
        fix(django_apps, None)
        ok.refresh_from_db()
        recent.refresh_from_db()
        self.assertEqual((ok.last_error, ok.last_error_at), ("", None))
        self.assertEqual(recent.last_error, "تازه‌تر از بررسی")


def inbox_open_always(cfg) -> bool:
    from . import hours

    return hours.is_open(cfg.working_hours)


# ------------------------------------------------------- «آدم می‌خواهم» gets an answer


class HandoffNoticeTests(InboxTestCase):
    def say(self, conversation, text):
        with self.captureOnCommitCallbacks(execute=True):
            return self.customer_says(conversation, text)

    def test_asking_for_a_person_is_acknowledged_once(self):
        conversation = self.conversation()
        self.say(conversation, "می‌خواهم با اپراتور صحبت کنم")
        self.assertEqual(self.sent[-1][2], bot.DEFAULT_HANDOFF_NOTICE)
        self.say(conversation, "هنوز هستید؟ اپراتور")
        self.assertEqual([s for s in self.sent if s[2] == bot.DEFAULT_HANDOFF_NOTICE].__len__(), 1)
        notice = conversation.messages.get(text=bot.DEFAULT_HANDOFF_NOTICE)
        self.assertEqual(notice.role, Message.Role.AI)  # the bot's own line, not a customer message

    def test_the_bot_being_off_is_acknowledged_too(self):
        cfg = team.settings_for(self.store)
        cfg.bot_enabled = False
        cfg.save()
        conversation = self.conversation()
        self.say(conversation, "سلام، قیمت؟")
        self.assertEqual(self.sent[-1][2], bot.DEFAULT_RECEIVED_NOTICE)

    def test_the_store_can_say_it_in_its_own_words(self):
        cfg = team.settings_for(self.store)
        cfg.handoff_message = "پیامتان را به همکارمان دادم."
        cfg.save()
        conversation = self.conversation()
        self.say(conversation, "اپراتور")
        self.assertEqual(self.sent[-1][2], "پیامتان را به همکارمان دادم.")
        response = self.api(self.owner).get(self.url("settings/")).json()
        self.assertEqual(response["handoff_message"], "پیامتان را به همکارمان دادم.")
        self.assertEqual(response["handoff_default_message"], bot.DEFAULT_HANDOFF_NOTICE)
        saved = self.api(self.owner).patch(self.url("settings/"), {"handoff_message": "   "}, format="json").json()
        self.assertEqual(saved["handoff_message"], "")

    def test_a_test_chat_is_never_answered_on_a_real_channel(self):
        customer = Customer.objects.create(store=self.store, channel="web-test", external_id="t5", name="آزمون")
        conversation = Conversation.objects.create(store=self.store, customer=customer, channel="WEB", external_id="t5")
        before = list(self.sent)
        self.say(conversation, "اپراتور")
        self.assertEqual(self.sent, before)

    def test_the_demo_line_is_what_the_real_code_says(self):
        demo_lines = [t for _, _, _, _, lines, _, _ in demo.CONVERSATIONS for _, t in lines]
        self.assertIn(bot.DEFAULT_HANDOFF_NOTICE, demo_lines)

    def test_off_hours_queue_stays_silent_by_design(self):
        cfg = team.settings_for(self.store)
        cfg.working_hours = {"days": [5], "start": "09:00", "end": "10:00"}
        cfg.bot_offhours = InboxSettings.OffHours.QUEUE
        cfg.save()
        conversation = self.conversation()
        before = list(self.sent)
        with patch("apps.inbox.bot.hours.is_open", return_value=False):
            self.say(conversation, "سلام")
        self.assertEqual(self.sent, before)
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.ESCALATED)




# ------------------------------------------- Persian words, never the English codes


class PersianLabelTests(InboxTestCase):
    def test_the_team_table_has_role_titles(self):
        members = self.api(self.sara).get(self.url("team/")).json()["members"]
        titles = {m["username"]: m["role_title"] for m in members}
        self.assertEqual(titles["boss"], "مالک")
        self.assertEqual(titles["admin1"], "مدیر")
        self.assertEqual(titles["sara"], "پشتیبانی")
        for member in members:
            self.assertFalse(member["role_title"].isascii(), member)

    def test_broadcast_recipients_come_with_words(self):
        self.connect("BALE")
        broadcast = Broadcast.objects.create(
            store=self.store, name="ب", text="سلام", created_by=self.sara, status=Broadcast.Status.SENT, channels=["BALE"],
        )
        for i, (status, reason) in enumerate([("SENT", ""), ("SKIPPED", "opted_out"), ("SKIPPED", "cancelled"), ("FAILED", "")]):
            contact = Contact.objects.create(store=self.store, name=f"مخاطب {i}")
            customer = Customer.objects.create(store=self.store, channel="bale", external_id=f"b{i}")
            BroadcastRecipient.objects.create(
                broadcast=broadcast, contact=contact, customer=customer, channel="BALE", to=f"b{i}",
                status=status, skip_reason=reason,
            )
        sample = self.api(self.sara).get(self.url(f"broadcasts/{broadcast.pk}/")).json()["recipients_sample"]
        titles = [(r["status_title"], r["skip_reason_title"]) for r in sample]
        self.assertEqual(titles, [
            ("فرستاده شد", ""), ("رد شد", "پیام تبلیغاتی را لغو کرده است"), ("رد شد", "ارسال لغو شد"), ("ناموفق", ""),
        ])
        for status_title, reason_title in titles:
            self.assertFalse(status_title.isascii())
            self.assertFalse(reason_title and reason_title.isascii())


# ----------------------------------------------- the approve button tells the truth


class ApproveButtonTests(InboxTestCase):
    def test_an_admin_is_not_offered_the_approval_of_their_own_broadcast(self):
        self.connect("BALE")
        for i in range(2):
            contact = Contact.objects.create(store=self.store, name=f"م{i}", phone=f"0912111111{i}")
            customer = Customer.objects.create(store=self.store, channel="bale", external_id=f"x{i}", name=contact.name)
            ContactLink.objects.create(contact=contact, customer=customer, matched_by="new")
        made = self.api(self.admin).post(self.url("broadcasts/"), {"name": "من ساختم", "text": "سلام {name}", "channels": ["BALE"]}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        pk = made.json()["id"]
        self.assertEqual(self.api(self.admin).post(self.url(f"broadcasts/{pk}/submit/")).status_code, 200)

        as_admin = self.api(self.admin).get(self.url("broadcasts/")).json()
        row = as_admin["broadcasts"][0]
        self.assertTrue(as_admin["can_approve"])  # admins may approve *others'* broadcasts
        self.assertFalse(row["can_approve"])  # ... but not this one
        self.assertIn("شخص دیگری", row["cannot_approve_reason"])
        self.assertFalse(self.api(self.admin).get(self.url(f"broadcasts/{pk}/")).json()["can_approve"])

        as_owner = self.api(self.owner).get(self.url("broadcasts/")).json()["broadcasts"][0]
        self.assertTrue(as_owner["can_approve"])
        self.assertEqual(as_owner["cannot_approve_reason"], "")

        as_support = self.api(self.sara).get(self.url("broadcasts/")).json()["broadcasts"][0]
        self.assertFalse(as_support["can_approve"])

    def test_the_scheduled_time_survives_a_round_trip_with_its_offset(self):
        """The panel now edits in local time and sends an ISO instant: 09:00 Tehran stays 09:00 Tehran."""
        made = self.api(self.sara).post(self.url("broadcasts/"), {
            "name": "زمان‌بندی", "text": "سلام", "scheduled_at": "2026-11-20T09:00:00+03:30",
        }, format="json").json()
        stored = Broadcast.objects.get(pk=made["id"]).scheduled_at
        self.assertEqual(stored.utcoffset(), timedelta(0))
        self.assertEqual((stored.hour, stored.minute), (5, 30))
        patched = self.api(self.sara).patch(self.url(f"broadcasts/{made['id']}/"), {"scheduled_at": "2026-11-20T05:30:00.000Z"}, format="json")
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(Broadcast.objects.get(pk=made["id"]).scheduled_at, stored)


# --------------------------------------------------- the small inconsistencies


class LittleThingsTests(InboxTestCase):
    def test_a_manual_contact_is_new_not_also_dormant(self):
        segments.ensure_builtin(self.store)
        contact = Contact.objects.create(store=self.store, name="دستی", source="manual")
        facts = segments.facts_for([contact])[contact.pk]
        from .models import Segment

        names = [
            s.name for s in Segment.objects.filter(store=self.store)
            if segments.matches(segments.validate(s.rules), facts)
        ]
        self.assertIn("تازه‌وارد", names)
        self.assertNotIn("غیرفعال", names)

    def test_a_contact_that_stayed_quiet_for_two_months_is_dormant(self):
        contact = Contact.objects.create(
            store=self.store, name="قدیمی", source="manual", first_seen_at=timezone.now() - timedelta(days=90),
        )
        facts = segments.facts_for([contact])[contact.pk]
        self.assertGreaterEqual(facts["last_activity_days"], 60)

    def test_unlinking_takes_the_phone_that_came_with_it(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, username="same_handle", name="الف")
        two = contacts.identify(b.customer, username="same_handle", phone="۰۹۱۲۱۲۳۴۵۶۷", name="ب")
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(Contact.objects.get(pk=one.pk).phone, "09121234567")
        fresh = contacts.unlink(b.customer)
        one.refresh_from_db()
        self.assertEqual(one.phone, "")  # the number was never theirs
        self.assertEqual(fresh.phone, "09121234567")
        # the next message from that number is the wrong person's, not merged back into the old contact
        again = self.conversation("RUBIKA", sender="r1")
        self.assertEqual(contacts.identify(again.customer, phone="09121234567").pk, fresh.pk)

    def test_unlinking_leaves_a_phone_both_identities_share(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, phone="09121234567")
        contacts.identify(b.customer, phone="09121234567")
        contacts.unlink(b.customer)
        one.refresh_from_db()
        self.assertEqual(one.phone, "09121234567")

    def test_unlinking_takes_a_handle_only_this_identity_had(self):
        a = self.conversation("TELEGRAM", sender="t1")
        b = self.conversation("BALE", sender="b1")
        one = contacts.identify(a.customer, phone="09121234567", name="الف")
        contacts.identify(b.customer, phone="09121234567", username="only_mine")
        one.refresh_from_db()
        self.assertEqual(one.usernames, ["only_mine"])
        fresh = contacts.unlink(b.customer)
        one.refresh_from_db()
        self.assertEqual(one.usernames, [])
        self.assertEqual(fresh.usernames, ["only_mine"])

    def test_a_channel_error_is_cleared_by_a_later_success(self):
        row = self.connect("TELEGRAM")
        ChannelConnection.objects.filter(pk=row.pk).update(last_error="خطای قدیمی", last_error_at=timezone.now())

        class Healthy:
            def health(self):
                return adapters.Health(True, "سالم است", "@bot")

        with patch.object(dispatch, "adapter_for", return_value=Healthy()):
            self.assertTrue(dispatch.check_health(row)["ok"])
        row.refresh_from_db()
        self.assertEqual((row.last_error, row.last_error_at), ("", None))

        ChannelConnection.objects.filter(pk=row.pk).update(last_error="خطای دوم", last_error_at=timezone.now())
        conversation = self.conversation("TELEGRAM", sender="t1")
        with patch.object(dispatch, "adapter_for") as fake:
            fake.return_value.send.return_value = adapters.SendResult(True, "", "5")
            self.assertTrue(dispatch.send("TELEGRAM", self.store, to=conversation.external_id, text="سلام")["sent"])
        row.refresh_from_db()
        self.assertEqual(row.last_error, "")

    def test_a_failed_check_still_records_the_error(self):
        row = self.connect("TELEGRAM")

        class Broken:
            def health(self):
                return adapters.Health(False, "توکن پذیرفته نشد", "")

        with patch.object(dispatch, "adapter_for", return_value=Broken()):
            dispatch.check_health(row)
        row.refresh_from_db()
        self.assertEqual(row.last_error, "توکن پذیرفته نشد")
        self.assertIsNotNone(row.last_error_at)

    def test_a_good_poll_clears_the_error(self):
        row = self.connect("BALE")
        ChannelConnection.objects.filter(pk=row.pk).update(last_error="قدیمی", last_error_at=timezone.now())
        row.refresh_from_db()
        with FakePlatform({"getUpdates": {"ok": True, "result": []}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            self.assertTrue(ingest.poll_connection(row)["polled"])
        row.refresh_from_db()
        self.assertEqual((row.last_error, row.last_error_at), ("", None))

    def test_the_dead_api_key_module_is_gone(self):
        self.assertIsNone(importlib.util.find_spec("apps.inbox.apikeys"))

