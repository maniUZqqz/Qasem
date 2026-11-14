"""The AI failing to answer a customer is a state, not a notification.

Live, before this: two customers' messages stayed unanswered because the model
was unreachable; the inbox said «۰ نفر منتظر جواب» (the conversation stayed
`AI`, `waiting_minutes` was None) and nothing asked the AI again when it came
back. What is pinned here, in the order a thread goes through it:

* a failed turn is **recorded on the conversation** (panel test chat and the
  webhook path alike) and the inbox **counts it, sorts it with the longest waits
  and badges it**;
* a real customer gets **one** neutral «پیام شما رسید» — never a test chat;
* the beat **does nothing while no AI path is usable** and **answers once** when
  one is (with a fake node going from off to on, not a mocked flag);
* an attempt that fails again is quiet (no second notification) and respects the
  gap; too many failures, or too long a wait, **hand the thread to a person**;
* a worker that died mid-turn (nothing recorded at all) is found and flagged;
* a person answering, or closing the thread, clears it — nothing is retried on
  top of a human.
"""
import importlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.compute.models import ComputeNode
from apps.stores.models import Store
from services.ai.gateway import PolicyBlocked
from services.ai.ollama import OllamaUnavailable

from . import ai_retry
from .models import Conversation, Customer, Message, Notification
from .views_webhook import run_agent_for

AI_REPLY = {
    "reply": "سلام! بله موجود است.",
    "intent": "PRICE",
    "action": "ANSWER",
    "product_ids": [],
    "order": None,
    "order_error": None,
    "ticket": None,
    "confidence": "HIGH",
    "needs_human": False,
    "ai_request": None,
}
DOWN = OllamaUnavailable("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — سرورِ پردازش خاموش است.")


class Base(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("aif-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه آزمایشی")
        self.client.force_login(self.owner)
        self.inbox = f"/api/v1/stores/{self.store.pk}/inbox/"

    def thread(self, *, minutes_ago=30, test=False, text="این موجوده؟", flagged=True,
               state=Conversation.State.AI):
        customer = Customer.objects.create(
            store=self.store, name="مهدی", channel="web-test" if test else "telegram",
        )
        conversation = Conversation.objects.create(
            store=self.store, customer=customer, state=state,
            channel="WEB" if test else "TELEGRAM", external_id="4242",
            last_customer_at=timezone.now() - timedelta(minutes=minutes_ago),
        )
        message = Message.objects.create(
            conversation=conversation, role=Message.Role.CUSTOMER, text=text,
        )
        if flagged:
            conversation.ai_failed_at = conversation.last_customer_at
            conversation.ai_failed_reason = "هوش مصنوعی در دسترس نبود."
            conversation.save(update_fields=["ai_failed_at", "ai_failed_reason"])
        return conversation, message

    def rows(self, suffix=""):
        body = self.client.get(self.inbox + suffix).json()
        return body, {r["id"]: r for r in body["conversations"]}

    def ai_messages(self, conversation):
        return list(
            conversation.messages.filter(role=Message.Role.AI)
            .exclude(intent="ack").values_list("text", flat=True)
        )


# --------------------------------------------------------------------------
class RecordingTests(Base):
    def test_a_failed_test_chat_turn_is_recorded_counted_and_linked(self):
        with patch("apps.customers.turn.run_sales_agent", side_effect=DOWN):
            response = self.client.post(
                f"/api/v1/stores/{self.store.pk}/chat/", {"message": "سلام"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 503)
        conversation = Conversation.objects.get(pk=response.json()["conversation_id"])
        self.assertTrue(conversation.ai_failed)
        self.assertIn("سرورِ پردازش خاموش", conversation.ai_failed_reason)

        body, rows = self.rows()
        self.assertEqual(body["counts"]["waiting"], 1)
        self.assertEqual(body["counts"]["ai_failed"], 1)
        row = rows[conversation.pk]
        self.assertTrue(row["ai_failed"])
        self.assertTrue(row["is_test"])
        self.assertIsNotNone(row["waiting_minutes"])

        note = Notification.objects.get(store=self.store, type=Notification.Type.AI_ERROR)
        self.assertEqual(note.link, f"/stores/{self.store.pk}/chat?c={conversation.pk}")

    def test_a_policy_block_links_to_the_data_policy_page_not_a_blank_route(self):
        blocked = PolicyBlocked("سیاست داده", "text", ["r"])
        with patch("apps.customers.turn.run_sales_agent", side_effect=blocked):
            response = self.client.post(
                f"/api/v1/stores/{self.store.pk}/chat/", {"message": "سلام"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 409)
        note = Notification.objects.get(store=self.store)
        self.assertEqual(note.link, f"/stores/{self.store.pk}/data")
        self.assertTrue(Conversation.objects.get(pk=response.json()["conversation_id"]).ai_failed)

    @patch("services.publishing.channels.send", return_value={"sent": True, "reason": ""})
    def test_the_webhook_path_records_notifies_with_a_conversation_link_and_acks_once(self, send):
        conversation, message = self.thread(flagged=False)
        with patch("apps.customers.turn.run_sales_agent", side_effect=DOWN):
            outcome = run_agent_for(conversation.pk, message.text, message.pk)
        self.assertEqual(outcome, "failed")
        conversation.refresh_from_db()
        self.assertTrue(conversation.ai_failed)
        note = Notification.objects.get(store=self.store, type=Notification.Type.AI_ERROR)
        self.assertEqual(note.link, f"/stores/{self.store.pk}/inbox?c={conversation.pk}")

        # one neutral acknowledgement, delivered on the channel and kept in the thread
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["text"], ai_retry.ACK_TEXT)
        self.assertIsNotNone(conversation.ai_ack_at)
        self.assertEqual(conversation.messages.filter(intent="ack").count(), 1)

        # the customer writes again and the AI is still down: no second «پیام شما رسید»
        again = Message.objects.create(conversation=conversation, role=Message.Role.CUSTOMER, text="؟")
        with patch("apps.customers.turn.run_sales_agent", side_effect=DOWN):
            run_agent_for(conversation.pk, again.text, again.pk)
        self.assertEqual(send.call_count, 1)

    @patch("services.publishing.channels.send", return_value={"sent": True, "reason": ""})
    def test_a_test_chat_never_gets_the_acknowledgement(self, send):
        conversation, message = self.thread(test=True, flagged=False)
        with patch("apps.customers.turn.run_sales_agent", side_effect=DOWN):
            run_agent_for(conversation.pk, message.text, message.pk)
        send.assert_not_called()
        self.assertFalse(conversation.messages.filter(intent="ack").exists())

    @patch("services.publishing.channels.send", return_value={"sent": False, "reason": "تنظیم نشده"})
    def test_an_acknowledgement_that_was_not_delivered_is_not_pretended(self, send):
        conversation, message = self.thread(flagged=False)
        with patch("apps.customers.turn.run_sales_agent", side_effect=DOWN):
            run_agent_for(conversation.pk, message.text, message.pk)
        conversation.refresh_from_db()
        self.assertIsNone(conversation.ai_ack_at)
        self.assertFalse(conversation.messages.filter(intent="ack").exists())

    @patch("services.publishing.channels.send", return_value={"sent": True, "reason": ""})
    def test_a_crash_that_is_not_an_ai_error_is_still_recorded(self, send):
        conversation, message = self.thread(flagged=False)
        with patch("apps.customers.turn.run_sales_agent", side_effect=RuntimeError("boom")):
            outcome = run_agent_for(conversation.pk, message.text, message.pk)
        self.assertEqual(outcome, "failed")
        conversation.refresh_from_db()
        self.assertTrue(conversation.ai_failed)
        # never a traceback or exception text in what the owner reads
        self.assertNotIn("boom", conversation.ai_failed_reason)

    @patch("apps.customers.views_webhook._send")
    def test_an_answer_clears_the_flag(self, _send):
        conversation, message = self.thread()
        with patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY)):
            self.assertEqual(run_agent_for(conversation.pk, message.text, message.pk), "answered")
        conversation.refresh_from_db()
        self.assertFalse(conversation.ai_failed)
        self.assertEqual(conversation.ai_failed_reason, "")
        self.assertEqual(conversation.ai_retries, 0)
        body, _ = self.rows()
        self.assertEqual(body["counts"]["waiting"], 0)


# --------------------------------------------------------------------------
class InboxTests(Base):
    def test_the_counter_counts_the_ai_failed_customers_and_they_sort_with_the_longest_waits(self):
        failed, _ = self.thread(minutes_ago=300)
        human, _ = self.thread(minutes_ago=10, flagged=False, state=Conversation.State.HUMAN)
        fine, _ = self.thread(minutes_ago=5, flagged=False)       # AI turn in progress / answered
        body, rows = self.rows()
        self.assertEqual(body["counts"]["waiting"], 2)
        self.assertEqual(body["counts"]["ai_failed"], 1)
        order = [r["id"] for r in body["conversations"]]
        self.assertEqual(order[:2], [failed.pk, human.pk])          # longest wait first
        self.assertEqual(order[2], fine.pk)
        self.assertTrue(rows[failed.pk]["ai_failed"])
        self.assertFalse(rows[fine.pk]["ai_failed"])
        self.assertIsNone(rows[fine.pk]["waiting_minutes"])
        self.assertGreaterEqual(rows[failed.pk]["waiting_minutes"], 299)

    def test_a_filter_shows_only_the_ai_failed_ones_and_counts_ignore_the_filter(self):
        failed, _ = self.thread()
        self.thread(flagged=False, state=Conversation.State.HUMAN)
        body, rows = self.rows("?ai_failed=1")
        self.assertEqual(list(rows), [failed.pk])
        # the numbers belong to the whole inbox, not to the filtered view
        self.assertEqual(body["counts"]["waiting"], 2)

    def test_the_preview_looks_through_our_own_acknowledgement(self):
        conversation, _ = self.thread(text="قیمت این چنده؟")
        Message.objects.create(
            conversation=conversation, role=Message.Role.AI, text=ai_retry.ACK_TEXT,
            intent="ack", grounding={ai_retry.ACK_MARK: True},
        )
        _, rows = self.rows()
        self.assertEqual(rows[conversation.pk]["last_message"]["text"], "قیمت این چنده؟")

    def test_a_human_reply_clears_it(self):
        conversation, _ = self.thread()
        with patch("services.publishing.channels.send", return_value={"sent": True, "reason": ""}):
            self.client.post(
                f"{self.inbox}{conversation.pk}/reply/", {"text": "فردا می‌رسد"},
                content_type="application/json",
            )
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.HUMAN)
        self.assertFalse(conversation.ai_failed)
        self.assertIsNone(conversation.ai_failed_at)

    def test_closing_or_handing_the_thread_to_a_person_clears_it(self):
        one, _ = self.thread()
        two, _ = self.thread()
        three, _ = self.thread()
        self.client.post(f"{self.inbox}{one.pk}/resolve/")
        for conversation, state in ((two, "HUMAN"), (three, "RESOLVED")):
            self.client.post(
                f"/api/v1/conversations/{conversation.pk}/handoff/", {"state": state},
                content_type="application/json",
            )
        for conversation in (one, two, three):
            conversation.refresh_from_db()
            self.assertIsNone(conversation.ai_failed_at, conversation.pk)
        one.refresh_from_db()
        self.assertEqual(one.state, Conversation.State.RESOLVED)

    def test_handing_it_back_to_the_ai_keeps_what_is_owed(self):
        conversation, _ = self.thread()
        self.client.post(
            f"/api/v1/conversations/{conversation.pk}/handoff/", {"state": "AI"},
            content_type="application/json",
        )
        conversation.refresh_from_db()
        self.assertTrue(conversation.ai_failed)


# --------------------------------------------------------------------------
class RetryCycleTests(Base):
    def test_nothing_happens_while_no_ai_path_is_usable_and_one_answer_when_it_is_back(self):
        """Node off -> counted as waiting, left alone. Node on -> answered, once."""
        conversation, message = self.thread()
        # The router is real here (AI_ROUTE_FORCE) and so is the node row; only the
        # cloud path is taken out of the picture (a developer's .env may configure
        # Metis), so "no node" really means "no AI path".
        with override_settings(AI_ROUTE_FORCE=True), \
                patch("services.ai.gateway._external_allowed", return_value=None), \
                patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY)) as agent, \
                patch("apps.customers.views_webhook._send") as send:
            # no node at all: the router says so, the beat does not call the agent
            out = ai_retry.run_cycle()
            self.assertEqual((out["retried"], out["waiting_for_ai"]), (0, 1))
            agent.assert_not_called()
            body, _ = self.rows()
            self.assertEqual(body["counts"]["waiting"], 1)

            # a node that stopped heartbeating two hours ago is not online either
            node = ComputeNode.objects.create(
                name="gpu-fake", token="t-fake", capabilities={"ollama": True},
                last_seen=timezone.now() - timedelta(hours=2),
            )
            self.assertEqual(ai_retry.run_cycle()["retried"], 0)
            agent.assert_not_called()

            # the node comes back
            node.last_seen = timezone.now()
            node.save(update_fields=["last_seen"])
            out = ai_retry.run_cycle()
            self.assertEqual((out["retried"], out["answered"]), (1, 1))
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(send.call_count, 1)

            # and the next tick has nothing left to do
            out = ai_retry.run_cycle()
            self.assertEqual((out["retried"], out["answered"]), (0, 0))
            self.assertEqual(agent.call_count, 1)

        conversation.refresh_from_db()
        self.assertFalse(conversation.ai_failed)
        self.assertEqual(self.ai_messages(conversation), [AI_REPLY["reply"]])
        # the agent was given the customer's own words
        self.assertEqual(agent.call_args.args[1], message.text)

    @patch("apps.customers.ai_retry.ai_available", return_value=(True, ""))
    @patch("apps.customers.views_webhook._send")
    def test_a_test_conversation_is_never_retried_automatically(self, _send, _ok):
        conversation, _ = self.thread(test=True)
        with patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY)) as agent:
            out = ai_retry.run_cycle()
        self.assertEqual(out["retried"], 0)
        agent.assert_not_called()
        conversation.refresh_from_db()
        self.assertTrue(conversation.ai_failed)

    @patch("apps.customers.ai_retry.ai_available", return_value=(True, ""))
    def test_a_failing_retry_is_quiet_and_respects_the_gap(self, _ok):
        conversation, _ = self.thread()
        before = Notification.objects.count()
        first_failure = conversation.ai_failed_at
        with patch("apps.customers.turn.run_sales_agent", side_effect=DOWN) as agent:
            out = ai_retry.run_cycle()
            self.assertEqual((out["retried"], out["failed"]), (1, 1))
            conversation.refresh_from_db()
            self.assertEqual(conversation.ai_retries, 1)
            self.assertEqual(conversation.ai_failed_at, first_failure)     # still waiting since then
            self.assertEqual(Notification.objects.count(), before)         # the owner is not told again

            self.assertEqual(ai_retry.run_cycle()["retried"], 0)           # inside the gap
            Conversation.objects.filter(pk=conversation.pk).update(
                ai_retry_at=timezone.now() - timedelta(minutes=10),
            )
            self.assertEqual(ai_retry.run_cycle()["retried"], 1)
            self.assertEqual(agent.call_count, 2)

    @patch("apps.customers.ai_retry.ai_available", return_value=(True, ""))
    def test_too_many_failed_attempts_hand_the_thread_to_a_person(self, _ok):
        conversation, _ = self.thread()
        Conversation.objects.filter(pk=conversation.pk).update(ai_retries=6)
        with patch("apps.customers.turn.run_sales_agent") as agent:
            out = ai_retry.run_cycle()
        agent.assert_not_called()
        self.assertEqual(out["escalated"], 1)
        conversation.refresh_from_db()
        self.assertEqual(conversation.state, Conversation.State.ESCALATED)
        self.assertFalse(conversation.ai_failed)
        note = Notification.objects.get(store=self.store, type=Notification.Type.ESCALATION)
        self.assertEqual(note.link, f"/stores/{self.store.pk}/inbox?c={conversation.pk}")
        # it is still counted as waiting — now for a person
        body, rows = self.rows()
        self.assertEqual(body["counts"]["waiting"], 1)
        self.assertIsNotNone(rows[conversation.pk]["waiting_minutes"])

    @patch("apps.customers.ai_retry.ai_available", return_value=(False, "خاموش"))
    def test_a_thread_older_than_the_window_is_handed_over_even_with_the_ai_down(self, _down):
        old, _ = self.thread(minutes_ago=13 * 60)
        fresh, _ = self.thread(minutes_ago=30)
        out = ai_retry.run_cycle()
        self.assertEqual(out["escalated"], 1)
        old.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(old.state, Conversation.State.ESCALATED)
        self.assertEqual(fresh.state, Conversation.State.AI)

    @patch("services.publishing.channels.send", return_value={"sent": True, "reason": ""})
    def test_a_turn_a_dead_worker_never_recorded_is_found_and_flagged(self, send):
        lost, _ = self.thread(minutes_ago=20, flagged=False)
        too_fresh, _ = self.thread(minutes_ago=3, flagged=False)       # may still be running
        answered, _ = self.thread(minutes_ago=20, flagged=False)
        Message.objects.create(conversation=answered, role=Message.Role.AI, text="جواب")
        lost_test, _ = self.thread(minutes_ago=20, flagged=False, test=True)
        with patch("apps.customers.ai_retry.ai_available", return_value=(False, "خاموش")):
            out = ai_retry.run_cycle()
        self.assertEqual(out["flagged"], 2)
        for conversation in (lost, too_fresh, answered, lost_test):
            conversation.refresh_from_db()
        self.assertTrue(lost.ai_failed)
        self.assertTrue(lost_test.ai_failed)                           # shown in the inbox ...
        self.assertFalse(too_fresh.ai_failed)
        self.assertFalse(answered.ai_failed)
        self.assertEqual(send.call_count, 1)                           # «پیام شما رسید», once, real customer only
        notes = Notification.objects.filter(store=self.store)
        self.assertEqual(notes.count(), 1)                             # ... but only the real one is announced
        self.assertEqual(notes.get().context["conversation_id"], lost.pk)

    @patch("services.publishing.channels.send", return_value={"sent": True, "reason": ""})
    def test_a_payment_slip_photo_is_not_an_unanswered_message(self, send):
        """The slip is filed and acknowledged and no reply message is written —
        ten minutes later it must not look like a customer the AI ignored."""
        conversation, message = self.thread(minutes_ago=30, text="[تصویر]", flagged=False)
        message.grounding = {"image": {"id": "x"}}
        message.save(update_fields=["grounding"])
        with patch("apps.customers.views_webhook._file_receipt", return_value=object()):
            self.assertEqual(run_agent_for(conversation.pk, "", message.pk), "skipped")
        message.refresh_from_db()
        self.assertTrue(message.grounding[ai_retry.RECEIPT_MARK])
        with patch("apps.customers.ai_retry.ai_available", return_value=(False, "خاموش")):
            out = ai_retry.run_cycle()
        self.assertEqual(out["flagged"], 0)
        conversation.refresh_from_db()
        self.assertFalse(conversation.ai_failed)
        send.assert_not_called()
        self.assertIsNone(ai_retry.pending_customer_message(conversation))

    @patch("apps.customers.ai_retry.ai_available", return_value=(True, ""))
    @patch("apps.customers.views_webhook._send")
    def test_it_never_answers_on_top_of_a_message_that_was_already_answered(self, _send, _ok):
        conversation, _ = self.thread()
        Message.objects.create(conversation=conversation, role=Message.Role.HUMAN, text="جواب دستی")
        with patch("apps.customers.turn.run_sales_agent") as agent:
            out = ai_retry.run_cycle()
        agent.assert_not_called()
        self.assertEqual(out["retried"], 1)
        conversation.refresh_from_db()
        self.assertFalse(conversation.ai_failed)                       # nothing is owed after all

    @patch("apps.customers.ai_retry.ai_available", return_value=(True, ""))
    def test_a_person_who_took_the_thread_is_never_retried(self, _ok):
        conversation, _ = self.thread(state=Conversation.State.HUMAN)
        conversation.ai_failed_at = timezone.now()
        conversation.save(update_fields=["ai_failed_at"])
        with patch("apps.customers.turn.run_sales_agent") as agent:
            self.assertEqual(ai_retry.run_cycle()["retried"], 0)
        agent.assert_not_called()

    @patch("apps.customers.ai_retry.ai_available", return_value=(True, ""))
    @patch("apps.customers.views_webhook._send")
    def test_two_workers_cannot_take_the_same_thread(self, _send, _ok):
        conversation, _ = self.thread()
        now = timezone.now()
        stale = Conversation.objects.get(pk=conversation.pk)            # a second worker's copy
        self.assertTrue(ai_retry._claim(conversation, now))
        self.assertFalse(ai_retry._claim(stale, now))

    def test_the_beat_entry_is_registered(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["retry-failed-ai-replies"]
        self.assertEqual(entry["task"], "apps.customers.tasks.retry_failed_ai_replies")
        self.assertLessEqual(entry["schedule"], 600)


class ManualRetryTests(Base):
    @patch("apps.customers.views_webhook._send")
    def test_the_retry_button_asks_the_ai_again(self, _send):
        conversation, _ = self.thread(test=True)
        url = f"{self.inbox}{conversation.pk}/retry/"
        with patch("apps.customers.ai_retry.ai_available", return_value=(False, "سرورِ پردازش خاموش است")):
            down = self.client.post(url)
        self.assertEqual(down.status_code, 503)
        self.assertIn("سرورِ پردازش خاموش", down.json()["error"]["message"])

        with patch("apps.customers.ai_retry.ai_available", return_value=(True, "")), \
                patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY)):
            ok = self.client.post(url)
        self.assertEqual(ok.status_code, 202)
        conversation.refresh_from_db()
        self.assertFalse(conversation.ai_failed)                       # eager Celery ran it
        self.assertEqual(self.ai_messages(conversation), [AI_REPLY["reply"]])

    def test_retrying_a_thread_that_is_not_waiting_for_the_ai_is_refused(self):
        conversation, _ = self.thread(flagged=False)
        self.assertEqual(self.client.post(f"{self.inbox}{conversation.pk}/retry/").status_code, 409)


class BackfillTests(Base):
    def test_the_migration_flags_recent_unanswered_threads_only(self):
        backfill = importlib.import_module(
            "apps.customers.migrations.0013_backfill_ai_failure"
        ).flag_unanswered
        from django.apps import apps

        recent, _ = self.thread(minutes_ago=60 * 24 * 2, flagged=False)
        ancient, _ = self.thread(minutes_ago=60 * 24 * 40, flagged=False)
        answered, _ = self.thread(minutes_ago=60, flagged=False)
        Message.objects.create(conversation=answered, role=Message.Role.AI, text="جواب")
        slip, slip_message = self.thread(minutes_ago=60, text="[تصویر]", flagged=False)
        slip_message.grounding = {"image": {"id": "x"}}
        slip_message.save(update_fields=["grounding"])
        backfill(apps, None)
        for conversation in (recent, ancient, answered, slip):
            conversation.refresh_from_db()
        self.assertTrue(recent.ai_failed)
        self.assertFalse(ancient.ai_failed)
        self.assertFalse(answered.ai_failed)
        self.assertFalse(slip.ai_failed)
        body, _ = self.rows()
        self.assertEqual(body["counts"]["ai_failed"], 1)

    def test_the_migration_repairs_the_links_already_in_the_bell(self):
        repair = importlib.import_module(
            "apps.customers.migrations.0013_backfill_ai_failure"
        ).repair_notification_links
        from django.apps import apps

        sid = self.store.pk
        test_chat, _ = self.thread(test=True, flagged=False)
        real, _ = self.thread(flagged=False)
        T = Notification.Type

        def note(kind, link, **context):
            return Notification.objects.create(
                store=self.store, type=kind, title="x", link=link, context=context,
            )

        policy = note(T.AI_ERROR, f"/stores/{sid}/settings", conversation_id=test_chat.pk, policy=True)
        in_chat = note(T.AI_ERROR, f"/stores/{sid}/chat", conversation_id=test_chat.pk)
        in_inbox = note(T.AI_ERROR, f"/stores/{sid}/inbox", conversation_id=real.pk)
        order = note(T.ORDER, f"/stores/{sid}/sales", order_id=1)
        ticket = note(T.TICKET, f"/stores/{sid}/sales", ticket_id=1)
        receipt = note(T.RECEIPT, f"/stores/{sid}/sales", order_id=1)
        untouched = note(T.AI_ERROR, f"/stores/{sid}/chat")          # no conversation to point at
        repair(apps, None)
        for n in (policy, in_chat, in_inbox, order, ticket, receipt, untouched):
            n.refresh_from_db()
        self.assertEqual(policy.link, f"/stores/{sid}/data")
        self.assertEqual(in_chat.link, f"/stores/{sid}/chat?c={test_chat.pk}")
        self.assertEqual(in_inbox.link, f"/stores/{sid}/inbox?c={real.pk}")
        self.assertEqual(order.link, f"/stores/{sid}/sales/orders")
        self.assertEqual(ticket.link, f"/stores/{sid}/sales/tickets")
        self.assertEqual(receipt.link, f"/stores/{sid}/sales/receipts")
        self.assertEqual(untouched.link, f"/stores/{sid}/chat")
