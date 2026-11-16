"""The AI bot's gate and handoff: keywords, off hours, low confidence, data policy."""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.utils import timezone

from apps.customers import views_webhook
from apps.customers.models import Conversation, Message, Notification
from apps.customers.turn import Turn
from services.ai.gateway import PolicyBlocked

from . import bot, hours, team
from .models import InboxSettings
from .tests_base import InboxTestCase


def fake_turn(conversation, reply="سلام! بله موجود است.", confidence="HIGH", needs_human=False):
    """What `turn.answer` returns, with the message row it would have stored."""
    message = Message.objects.create(
        conversation=conversation, role=Message.Role.AI, text=reply,
        grounding={"confidence": confidence},
    )
    return Turn(message=message, result={
        "reply": reply, "intent": "PRICE", "action": "ANSWER", "product_ids": [], "order": None,
        "order_error": None, "ticket": None, "confidence": confidence, "needs_human": needs_human,
        "ai_request": None,
    })


class GateTests(InboxTestCase):
    def test_a_normal_question_stays_with_the_bot(self):
        conversation = self.conversation()
        self.customer_says(conversation, "قیمت پروتئین چنده؟")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.AI)

    def test_asking_for_a_person_hands_over_with_the_reason(self):
        conversation = self.conversation()
        self.customer_says(conversation, "می‌خوام با اپراتور صحبت کنم")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.ESCALATED)
        self.assertIn("اپراتور", conversation.inbox_meta.handoff_reason)
        self.assertIsNotNone(conversation.inbox_meta.waiting_since)  # the clock is running
        self.assertTrue(Notification.objects.filter(store=self.store, title__startswith="گفتگو منتظر پاسخ تیم").exists())

    def test_a_store_can_choose_its_own_words(self):
        cfg = team.settings_for(self.store)
        cfg.bot_handoff_keywords = ["مربی"]
        cfg.save()
        a = self.conversation(sender="a")
        self.customer_says(a, "با اپراتور کار دارم")  # a default word, but the store replaced the list
        a.refresh_from_db()
        self.assertEqual(a.state, Conversation.State.AI)
        b = self.conversation(sender="b")
        self.customer_says(b, "مربی کجاست؟")
        b.refresh_from_db()
        self.assertEqual(b.state, Conversation.State.ESCALATED)

    def test_bot_switched_off_means_a_person_from_the_first_message(self):
        cfg = team.settings_for(self.store)
        cfg.bot_enabled = False
        cfg.save()
        conversation = self.conversation()
        self.customer_says(conversation, "سلام")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.ESCALATED)

    def test_a_human_thread_is_not_touched_by_the_gate(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        self.customer_says(conversation, "اپراتور")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.HUMAN)


class OffHoursTests(InboxTestCase):
    CLOSED = datetime(2026, 11, 14, 3, 30, tzinfo=dt_timezone.utc)  # Saturday 07:00 Tehran

    def configure(self, mode):
        cfg = team.settings_for(self.store)
        cfg.working_hours = {"days": [5, 6, 0, 1, 2], "start": "09:00", "end": "18:00"}
        cfg.bot_offhours = mode
        cfg.offhours_message = "ساعت کاری ما ۹ تا ۱۸ است."
        cfg.save()

    def test_bot_mode_keeps_answering_at_night(self):
        self.configure(InboxSettings.OffHours.BOT)
        conversation = self.conversation()
        self.assertEqual(bot.decide(conversation, "سلام", now=self.CLOSED).action, "bot")

    def test_message_mode_hands_over_and_says_when_we_are_back(self):
        self.configure(InboxSettings.OffHours.MESSAGE)
        conversation = self.conversation()
        decision = bot.decide(conversation, "سلام", now=self.CLOSED)
        self.assertEqual(decision.action, "handoff")
        self.assertEqual(decision.notice, "ساعت کاری ما ۹ تا ۱۸ است.")

    def test_queue_mode_hands_over_silently(self):
        self.configure(InboxSettings.OffHours.QUEUE)
        decision = bot.decide(self.conversation(), "سلام", now=self.CLOSED)
        self.assertEqual((decision.action, decision.notice), ("handoff", ""))

    def test_during_working_hours_nothing_changes(self):
        self.configure(InboxSettings.OffHours.QUEUE)
        open_now = datetime(2026, 11, 14, 8, 0, tzinfo=dt_timezone.utc)  # 11:30 Tehran
        self.assertTrue(hours.is_open(team.settings_for(self.store).working_hours, open_now))
        self.assertEqual(bot.decide(self.conversation(), "سلام", now=open_now).action, "bot")

    def test_the_notice_is_delivered_into_the_thread(self):
        self.configure(InboxSettings.OffHours.MESSAGE)
        conversation = self.conversation()
        message = self.customer_says(conversation, "سلام")
        with patch("apps.inbox.bot.hours.is_open", return_value=False), \
                self.captureOnCommitCallbacks(execute=True):
            bot.gate(conversation, message)
        texts = list(conversation.messages.filter(role=Message.Role.AI).values_list("text", flat=True))
        self.assertIn("ساعت کاری ما ۹ تا ۱۸ است.", texts)
        self.assertEqual(self.sent[-1][2], "ساعت کاری ما ۹ تا ۱۸ است.")


class ConfidenceTests(InboxTestCase):
    """`run_agent_for` asks the inbox between «answered» and «sent»."""

    def run_turn(self, conversation, **kw):
        turn = fake_turn(conversation, **kw)
        with patch.object(views_webhook, "answer", return_value=turn):
            result = views_webhook.run_agent_for(conversation.pk, "سؤال")
        return result, turn

    def test_a_confident_answer_is_sent_as_is(self):
        conversation = self.conversation()
        result, _ = self.run_turn(conversation, confidence="HIGH")
        self.assertEqual(result, "answered")
        self.assertEqual(self.sent[-1][2], "سلام! بله موجود است.")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.AI)

    def test_a_low_confidence_answer_is_withheld_and_a_person_takes_over(self):
        conversation = self.conversation()
        _, turn = self.run_turn(conversation, confidence="LOW", reply="شاید ۵۰۰ هزار تومان")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.ESCALATED)
        self.assertEqual(self.sent[-1][2], bot.HANDOFF_TEXT)  # the customer never sees the guess
        self.assertNotIn("۵۰۰", self.sent[-1][2])
        turn.message.refresh_from_db()
        self.assertTrue(turn.message.grounding["withheld"])  # but the team can read it as a draft
        self.assertIn("LOW", conversation.inbox_meta.handoff_reason)
        self.assertEqual(conversation.inbox_meta.bot_confidence, 0.25)
        self.assertIsNotNone(conversation.inbox_meta.waiting_since)

    def test_the_threshold_is_the_stores_to_set(self):
        cfg = team.settings_for(self.store)
        cfg.bot_min_confidence = 0.0
        cfg.save()
        conversation = self.conversation()
        self.run_turn(conversation, confidence="LOW")
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.AI)
        cfg.bot_min_confidence = 0.8
        cfg.save()
        other = self.conversation(sender="u2")
        self.run_turn(other, confidence="MEDIUM")
        other.refresh_from_db()
        self.assertEqual(other.state, Conversation.State.ESCALATED)

    def test_when_the_agent_itself_asked_for_a_person_its_words_stand(self):
        conversation = self.conversation()

        def answer(conv, text):
            conv.state = Conversation.State.ESCALATED  # what turn.answer does for needs_human
            conv.save()
            return fake_turn(conv, confidence="LOW", needs_human=True, reply="همکارم ادامه می‌دهد")

        with patch.object(views_webhook, "answer", side_effect=answer):
            views_webhook.run_agent_for(conversation.pk, "سؤال")
        self.assertEqual(self.sent[-1][2], "همکارم ادامه می‌دهد")

    def test_a_broken_inbox_hook_never_stops_an_answer(self):
        conversation = self.conversation()
        with patch("apps.inbox.bot.after_turn", side_effect=RuntimeError("boom")):
            result, _ = self.run_turn(conversation, confidence="HIGH")
        self.assertEqual(result, "answered")
        self.assertEqual(self.sent[-1][2], "سلام! بله موجود است.")

    def test_the_data_policy_block_still_works_and_nobody_is_answered_with_a_guess(self):
        conversation = self.conversation()
        self.customer_says(conversation, "سلام")
        with patch.object(views_webhook, "answer", side_effect=PolicyBlocked("فقط محلی", "text")):
            result = views_webhook.run_agent_for(conversation.pk, "سلام")
        self.assertEqual(result, "failed")
        conversation.refresh_from_db()
        self.assertTrue(conversation.ai_failed)  # counted as waiting, retried when allowed
        self.assertTrue(Notification.objects.filter(store=self.store, title__contains="سیاست داده").exists())
