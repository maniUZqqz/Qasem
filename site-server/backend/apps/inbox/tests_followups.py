"""Follow-ups, payment reminders and the satisfaction survey."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message, Notification, Order

from . import followups, replies, sla, surveys, team
from .models import FollowUp, SatisfactionSurvey
from .tests_base import InboxTestCase


class FollowUpTests(InboxTestCase):
    def test_a_due_followup_is_sent_once_in_the_customers_thread(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        row = followups.create(
            self.store, conversation=conversation, text="سلام، سفارشتان آماده شد؟",
            due_at=timezone.now() - timedelta(minutes=1), by=self.sara,
        )
        self.assertEqual(followups.run_due(), {"sent": 1, "failed": 0, "skipped": 0})
        self.assertEqual(followups.run_due(), {"sent": 0, "failed": 0, "skipped": 0})  # not twice
        row.refresh_from_db()
        self.assertEqual(row.status, FollowUp.Status.SENT)
        self.assertEqual(self.sent[-1][2], "سلام، سفارشتان آماده شد؟")
        self.assertTrue(conversation.messages.filter(inbox_meta__kind="FOLLOWUP").exists())

    def test_not_due_yet_waits(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        followups.create(self.store, conversation=conversation, text="x", due_at=timezone.now() + timedelta(hours=3), by=self.sara)
        self.assertEqual(followups.run_due()["sent"], 0)
        self.assertEqual(self.sent, [])

    def test_a_reminder_to_a_colleague_notifies_instead_of_messaging_the_customer(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        followups.create(
            self.store, conversation=conversation, text="زنگ بزن", due_at=timezone.now(), by=self.sara,
            target=FollowUp.Target.AGENT, assigned_to=self.reza,
        )
        followups.run_due()
        self.assertEqual(self.sent, [])
        alert = Notification.objects.get(store=self.store, title="یادآوری پیگیری")
        self.assertEqual(alert.context["for_user"], "reza")

    def test_a_test_conversation_is_never_messaged(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        meta = sla.meta_for(conversation)
        meta.is_test = True
        meta.save()
        row = followups.create(self.store, conversation=conversation, text="x", due_at=timezone.now(), by=self.sara)
        self.assertTrue(row.is_test)
        followups.run_due()
        row.refresh_from_db()
        self.assertEqual(row.status, FollowUp.Status.CANCELLED)
        self.assertEqual(self.sent, [])

    def test_a_channel_that_cannot_send_fails_with_the_reason(self):
        conversation = self.conversation("BALE", sender="9", state=Conversation.State.HUMAN)  # not connected
        row = followups.create(self.store, conversation=conversation, text="x", due_at=timezone.now(), by=self.sara)
        self.assertEqual(followups.run_due()["failed"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, FollowUp.Status.FAILED)
        self.assertIn("وصل نشده", row.error)

    def test_cancelled_ones_do_not_run(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        row = followups.create(self.store, conversation=conversation, text="x", due_at=timezone.now(), by=self.sara)
        followups.cancel(row)
        self.assertEqual(followups.run_due()["sent"], 0)


class PaymentReminderTests(InboxTestCase):
    def order(self, hours_old, status=Order.Status.AWAITING_RECEIPT):
        conversation = self.conversation(state=Conversation.State.AI)
        order = Order.objects.create(
            store=self.store, customer=conversation.customer, conversation=conversation, status=status, total=1000,
        )
        Order.objects.filter(pk=order.pk).update(updated_at=timezone.now() - timedelta(hours=hours_old))
        return order

    def enable(self, **kw):
        cfg = team.settings_for(self.store)
        cfg.payment_reminder_enabled = True
        for key, value in kw.items():
            setattr(cfg, key, value)
        cfg.save()

    def test_off_by_default(self):
        self.order(48)
        self.assertEqual(followups.scan_payment_reminders(), 0)

    def test_an_order_waiting_too_long_gets_one_reminder_per_interval(self):
        self.enable()
        order = self.order(30)
        self.assertEqual(followups.scan_payment_reminders(), 1)
        self.assertEqual(followups.scan_payment_reminders(), 0)  # same interval: not again
        followups.run_due()
        self.assertIn("منتظر پرداخت", self.sent[-1][2])
        self.assertEqual(FollowUp.objects.filter(order=order, kind="PAYMENT", status="SENT").count(), 1)

    def test_a_fresh_order_is_left_alone(self):
        self.enable()
        self.order(2)
        self.assertEqual(followups.scan_payment_reminders(), 0)

    def test_a_paid_order_cancels_its_pending_reminder(self):
        self.enable()
        order = self.order(30)
        followups.scan_payment_reminders()
        Order.objects.filter(pk=order.pk).update(status=Order.Status.CONFIRMED)
        followups.run_due()
        row = FollowUp.objects.get(order=order)
        self.assertEqual(row.status, FollowUp.Status.CANCELLED)
        self.assertEqual(self.sent, [])

    def test_at_most_the_stores_maximum(self):
        self.enable(payment_reminder_max=1, payment_reminder_hours=1)
        order = self.order(30)
        followups.scan_payment_reminders()
        followups.run_due()
        FollowUp.objects.filter(order=order).update(due_at=timezone.now() - timedelta(hours=5))
        self.assertEqual(followups.scan_payment_reminders(), 0)

    def test_the_stores_own_text_is_used(self):
        self.enable(payment_reminder_text="لطفاً رسید را بفرستید")
        self.order(30)
        followups.scan_payment_reminders()
        followups.run_due()
        self.assertEqual(self.sent[-1][2], "لطفاً رسید را بفرستید")


class SurveyTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cfg = team.settings_for(self.store)
        cfg.survey_enabled = True
        cfg.survey_delay_min = 0
        cfg.save()

    def answered_conversation(self):
        conversation = self.conversation(state=Conversation.State.ESCALATED)
        self.customer_says(conversation, "مشکل دارم")
        replies.reply(conversation, self.sara, "حل شد")
        return conversation

    def test_closing_a_helped_conversation_schedules_a_survey_that_goes_out(self):
        conversation = self.answered_conversation()
        replies.close(conversation, self.sara)
        self.assertEqual(FollowUp.objects.filter(conversation=conversation, kind="SURVEY").count(), 1)
        followups.run_due()
        self.assertIn("۱ (ضعیف) تا ۵ (عالی)", self.sent[-1][2])
        survey = SatisfactionSurvey.objects.get(conversation=conversation)
        self.assertEqual(survey.agent, self.sara)  # it is about the person who helped

    def test_a_digit_is_the_answer_and_is_not_a_question_for_the_bot(self):
        conversation = self.answered_conversation()
        replies.close(conversation, self.sara)
        followups.run_due()
        message = self.customer_says(conversation, "۵ عالی بود")
        self.assertTrue(surveys.try_answer(conversation, message))
        survey = SatisfactionSurvey.objects.get(conversation=conversation)
        self.assertEqual((survey.score, survey.comment), (5, "عالی بود"))
        self.assertIn("ممنون", self.sent[-1][2])
        self.assertFalse(surveys.try_answer(conversation, self.customer_says(conversation, "5")))  # answered once

    def test_a_digit_with_no_survey_open_is_just_a_message(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        self.assertFalse(surveys.try_answer(conversation, self.customer_says(conversation, "3")))

    def test_no_survey_when_nobody_helped_or_the_store_has_it_off(self):
        bot_only = self.conversation(state=Conversation.State.AI, sender="b")
        self.assertIsNone(surveys.schedule(bot_only))
        helped = self.answered_conversation()
        cfg = team.settings_for(self.store)
        cfg.survey_enabled = False
        cfg.save()
        self.assertIsNone(surveys.schedule(helped))

    def test_test_conversations_are_never_surveyed(self):
        conversation = self.answered_conversation()
        from .sla import meta_for

        meta = meta_for(conversation)
        meta.is_test = True
        meta.save()
        self.assertIsNone(surveys.schedule(conversation))

    def test_summary_averages_by_agent_and_ignores_tests(self):
        for score, agent in ((5, self.sara), (3, self.sara), (4, self.reza)):
            conversation = self.conversation(sender=f"c{score}", state=Conversation.State.HUMAN)
            SatisfactionSurvey.objects.create(
                conversation=conversation, store=self.store, sent_at=timezone.now(),
                answered_at=timezone.now(), score=score, agent=agent,
            )
        summary = surveys.summary(self.store)
        self.assertEqual(summary["answered"], 3)
        self.assertEqual(summary["average"], 4.0)
        self.assertEqual(summary["by_agent"]["sara"], {"average": 4.0, "count": 2})
        self.assertEqual(summary["distribution"]["5"], 1)
