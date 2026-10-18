"""One inbox for every channel. §9.7.

The sort order is what most of this tests, because it is the design decision:
**longest-waiting first, measured from when the customer last wrote**. Sorting
by `updated_at` puts the threads we just answered on top and buries the person
waiting since morning — exactly backwards for a queue whose job is "who needs
us next".
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.stores.models import Membership, Store
from services.publishing import channels

from .models import Conversation, Customer, Message


class ChannelTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("chan-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه کانال")

    def test_instagram_can_send_but_not_receive_until_meta_approves(self):
        """The shop should learn this from the inbox, not by noticing replies
        never arrive.

        The inbound code path exists now, so what decides this is the Meta
        credentials rather than a hard-coded flag — and the shop is told which
        ones are missing, not just that something is.
        """
        from django.test import override_settings

        with override_settings(UPMARKET_AI={"NOVINHUB_TOKEN": "t"}):
            row = next(
                r for r in channels.status_for(self.store) if r["key"] == "INSTAGRAM"
            )
        self.assertTrue(row["can_send"])
        self.assertFalse(row["can_receive"])
        self.assertIn("META_APP_SECRET", row["reason"])

    def test_instagram_receives_once_meta_credentials_are_set(self):
        from django.test import override_settings

        with override_settings(UPMARKET_AI={
            "NOVINHUB_TOKEN": "t",
            "META_APP_SECRET": "s",
            "META_VERIFY_TOKEN": "v",
        }):
            row = next(
                r for r in channels.status_for(self.store) if r["key"] == "INSTAGRAM"
            )
        self.assertTrue(row["can_receive"])

    def test_telegram_receiving_is_no_longer_a_claim_with_nothing_behind_it(self):
        """It said `can_receive=True` for months with no inbound endpoint at
        all — a bot that could answer and never heard anything."""
        from django.urls import reverse

        self.assertTrue(channels.TELEGRAM.can_receive)
        self.assertTrue(
            reverse("inbound-webhook", args=["telegram", "x" * 24]),
        )

    def test_an_unknown_channel_falls_back_instead_of_raising(self):
        """An old row or a typo must not break an inbox where a customer is
        waiting."""
        self.assertEqual(channels.get("CARRIER_PIGEON").key, "WEB")
        self.assertEqual(channels.get("").key, "WEB")

    def test_a_channel_with_no_requirements_is_always_configured(self):
        self.assertTrue(channels.configured(channels.WEBSITE, self.store))

    def test_a_channel_missing_its_token_is_not_configured(self):
        from django.test import override_settings

        from django.conf import settings

        merged = {**settings.UPMARKET_AI, "TELEGRAM_BOT_TOKEN": ""}
        with override_settings(UPMARKET_AI=merged):
            self.assertFalse(channels.configured(channels.TELEGRAM, self.store))

    def test_a_store_token_beats_the_shared_one(self):
        """A shop with its own NovinHub account should not be sharing ours."""
        self.store.profile.novinhub_token = "own-token"
        self.store.profile.save()
        self.store.refresh_from_db()
        self.assertTrue(channels.configured(channels.INSTAGRAM, self.store))

    def test_status_separates_unconfigured_from_one_way(self):
        """A single "unavailable" badge conflates two problems with different
        fixes."""
        rows = {r["key"]: r for r in channels.status_for(self.store)}
        self.assertTrue(rows["WEB"]["can_receive"])
        self.assertFalse(rows["SMS"]["can_receive"])
        self.assertTrue(rows["SMS"]["reason"])

    def test_an_unconfigured_channel_says_what_is_missing(self):
        """Checked before the message itself: "SMS_API_KEY is not set" is a
        fix, "your message is too long" on a channel that cannot send anything
        is a red herring."""
        outcome = channels.send("SMS", self.store, to="0912", text="سلام")
        self.assertFalse(outcome["sent"])
        self.assertIn("SMS_API_KEY", outcome["reason"])

    def test_a_message_over_the_channel_limit_is_refused(self):
        from django.conf import settings
        from django.test import override_settings

        merged = {**settings.UPMARKET_AI, "SMS_API_KEY": "configured"}
        with override_settings(UPMARKET_AI=merged):
            outcome = channels.send("SMS", self.store, to="0912", text="x" * 600)

        self.assertFalse(outcome["sent"])
        self.assertIn("کاراکتر", outcome["reason"])

    def test_the_website_channel_needs_no_delivery(self):
        """The message row IS the delivery — the customer reads the same thread."""
        outcome = channels.send("WEB", self.store, to="1", text="سلام")
        self.assertTrue(outcome["sent"])


class InboxOrderTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("inbox-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه صندوق")
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.pk}/inbox/"

    def _thread(self, *, minutes_waiting, state=Conversation.State.HUMAN, channel="WEB"):
        customer = Customer.objects.create(store=self.store, name=f"م{minutes_waiting}")
        conversation = Conversation.objects.create(
            store=self.store, customer=customer, state=state, channel=channel,
            last_customer_at=timezone.now() - timedelta(minutes=minutes_waiting),
        )
        Message.objects.create(
            conversation=conversation, role=Message.Role.CUSTOMER, text="سلام",
        )
        return conversation

    def test_the_longest_wait_comes_first(self):
        recent = self._thread(minutes_waiting=2)
        old = self._thread(minutes_waiting=180)

        rows = self.client.get(self.url).json()["conversations"]
        self.assertEqual(rows[0]["id"], old.pk)
        self.assertEqual(rows[1]["id"], recent.pk)

    def test_answering_someone_does_not_push_them_back_to_the_top(self):
        """`updated_at` moves when we reply; `last_customer_at` does not."""
        old = self._thread(minutes_waiting=180)
        self._thread(minutes_waiting=5)

        # We reply to the older one — it should stay first, because the
        # customer has still been waiting longest overall.
        Message.objects.create(
            conversation=old, role=Message.Role.HUMAN, text="جواب",
        )
        old.save()

        rows = self.client.get(self.url).json()["conversations"]
        self.assertEqual(rows[0]["id"], old.pk)

    def test_waiting_minutes_is_none_while_the_ai_is_handling_it(self):
        """That is not waiting, that is working."""
        self._thread(minutes_waiting=60, state=Conversation.State.AI)
        rows = self.client.get(self.url).json()["conversations"]
        self.assertIsNone(rows[0]["waiting_minutes"])

    def test_waiting_minutes_is_counted_once_a_person_owes_an_answer(self):
        self._thread(minutes_waiting=45)
        rows = self.client.get(self.url).json()["conversations"]
        self.assertGreaterEqual(rows[0]["waiting_minutes"], 44)

    def test_filtering_by_channel(self):
        self._thread(minutes_waiting=5, channel="WEB")
        self._thread(minutes_waiting=5, channel="TELEGRAM")
        rows = self.client.get(f"{self.url}?channel=telegram").json()["conversations"]
        self.assertEqual(len(rows), 1)

    def test_unassigned_is_a_real_state_worth_filtering_for(self):
        self._thread(minutes_waiting=5)
        rows = self.client.get(f"{self.url}?assigned=nobody").json()["conversations"]
        self.assertEqual(len(rows), 1)

    def test_the_channel_list_travels_with_the_inbox(self):
        body = self.client.get(self.url).json()
        self.assertTrue(body["channels"])
        self.assertIn("counts", body)


class AssignAndTagTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("assign-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه واگذاری")
        customer = Customer.objects.create(store=self.store, name="مشتری")
        self.conversation = Conversation.objects.create(
            store=self.store, customer=customer, state=Conversation.State.HUMAN,
        )
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/inbox/{self.conversation.pk}"

    def test_taking_a_conversation(self):
        response = self.client.post(
            f"{self.base}/assign/", {"username": "me"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.assigned_to, self.owner)

    def test_handing_it_to_a_colleague(self):
        colleague = User.objects.create_user("colleague", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.SUPPORT,
        )
        response = self.client.post(
            f"{self.base}/assign/", {"username": "colleague"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_assigning_to_someone_outside_the_shop_is_refused(self):
        User.objects.create_user("outsider", password="x")
        response = self.client.post(
            f"{self.base}/assign/", {"username": "outsider"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "not_a_member")

    def test_putting_it_back(self):
        self.conversation.assigned_to = self.owner
        self.conversation.save()
        self.client.post(f"{self.base}/assign/", {}, content_type="application/json")
        self.conversation.refresh_from_db()
        self.assertIsNone(self.conversation.assigned_to)

    def test_tags_are_deduplicated_and_capped(self):
        response = self.client.post(
            f"{self.base}/tags/",
            {"tags": ["فوری", "فوری", "  ", "پیگیری"]},
            content_type="application/json",
        )
        self.assertEqual(response.json()["tags"], ["فوری", "پیگیری"])

    def test_tags_must_be_a_list(self):
        response = self.client.post(
            f"{self.base}/tags/", {"tags": "فوری"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class ReplyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("reply-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه پاسخ")
        customer = Customer.objects.create(store=self.store, name="مشتری")
        self.conversation = Conversation.objects.create(
            store=self.store, customer=customer, channel="WEB",
        )
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.pk}/inbox/{self.conversation.pk}/reply/"

    def test_a_reply_is_recorded_and_delivered(self):
        response = self.client.post(
            self.url, {"text": "سلام، فردا ارسال می‌شود"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["delivered"])

    def test_a_failed_delivery_still_records_the_message(self):
        """A reply that failed to send is still something a colleague wrote —
        losing it means two people write the same answer."""
        with patch.object(
            channels, "send",
            return_value={"sent": False, "reason": "تلگرام در دسترس نبود"},
        ):
            response = self.client.post(
                self.url, {"text": "جواب"}, content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["delivered"])
        self.assertTrue(response.json()["reason"])
        self.assertEqual(
            Message.objects.filter(
                conversation=self.conversation, role=Message.Role.HUMAN,
            ).count(),
            1,
        )

    def test_replying_takes_the_conversation_off_the_ai(self):
        """The AI must not answer on top of a person."""
        self.client.post(self.url, {"text": "جواب"}, content_type="application/json")
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.state, Conversation.State.HUMAN)
        self.assertEqual(self.conversation.assigned_to, self.owner)

    def test_an_empty_reply_is_refused(self):
        response = self.client.post(
            self.url, {"text": "   "}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_a_stranger_cannot_reply(self):
        stranger = User.objects.create_user("reply-stranger", password="x")
        self.client.force_login(stranger)
        response = self.client.post(
            self.url, {"text": "x"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
