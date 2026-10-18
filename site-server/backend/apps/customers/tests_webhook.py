"""Messages arriving from a platform.

This endpoint is unauthenticated by necessity — the caller is Telegram, not a
person — so most of this file is about the four ways that goes wrong:

**Anyone who finds the URL could run the shop's AI.** So the secret is checked,
and so is the platform's own signature.

**Platforms retry.** A duplicate delivery must not produce a second answer to
the same question, or the customer sees the shop reply twice and the shop pays
for both.

**Platforms send things that are not messages.** Receipts, reactions, edits,
echoes of our own replies. Erroring on those makes the platform back off and
eventually disable the webhook, losing the messages that *were* understood.

**A human who took the conversation must keep it.** An AI reply landing under a
person's is the customer getting two answers from one shop.
"""
import hashlib
import hmac
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.stores.models import Store, StoreProfile

from . import webhooks
from .models import Conversation, Customer, Message

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

TELEGRAM_MESSAGE = {
    "update_id": 1,
    "message": {
        "message_id": 77,
        "chat": {"id": 4242},
        "from": {"id": 4242, "first_name": "مهدی"},
        "text": "این موجوده؟",
    },
}


class SecretTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("hook-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")

    def test_a_secret_is_created_once_and_reused(self):
        first = webhooks.secret_for(self.store)
        self.assertGreaterEqual(len(first), 16)
        self.assertEqual(first, webhooks.secret_for(self.store))

    def test_the_secret_finds_its_store(self):
        secret = webhooks.secret_for(self.store)
        self.assertEqual(webhooks.store_for(secret), self.store)

    def test_a_wrong_or_short_secret_is_refused(self):
        webhooks.secret_for(self.store)
        for bad in ("", "short", "x" * 40):
            with self.assertRaises(webhooks.WebhookRefused):
                webhooks.store_for(bad)

    def test_two_stores_do_not_share_one(self):
        other_owner = User.objects.create_user("hook-owner-2", password="x")
        other = Store.objects.create(owner=other_owner, name="دیگری")
        self.assertNotEqual(webhooks.secret_for(self.store), webhooks.secret_for(other))


class TelegramTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("tg-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")
        self.secret = webhooks.secret_for(self.store)
        self.url = reverse("inbound-webhook", args=["telegram", self.secret])

    def post(self, payload=None, *, header=True):
        headers = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": self.secret} if header else {}
        return self.client.post(
            self.url,
            data=json.dumps(payload if payload is not None else TELEGRAM_MESSAGE),
            content_type="application/json",
            **headers,
        )

    @patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY))
    @patch("apps.customers.views_webhook._send")
    def test_a_message_becomes_a_conversation_and_gets_answered(self, send, agent):
        res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["accepted"], 1)

        conversation = Conversation.objects.get(store=self.store)
        self.assertEqual(conversation.channel, "TELEGRAM")
        self.assertEqual(conversation.external_id, "4242")
        self.assertEqual(
            [m.text for m in conversation.messages.all()],
            ["این موجوده؟", AI_REPLY["reply"]],
        )
        self.assertEqual(Customer.objects.get(store=self.store).name, "مهدی")
        send.assert_called_once()

    @patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY))
    @patch("apps.customers.views_webhook._send")
    def test_a_retried_delivery_does_not_answer_twice(self, send, agent):
        self.post()
        res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["accepted"], 0)
        self.assertEqual(Message.objects.filter(role=Message.Role.CUSTOMER).count(), 1)
        self.assertEqual(agent.call_count, 1)

    def test_a_missing_secret_header_is_refused(self):
        self.assertEqual(self.post(header=False).status_code, 403)

    def test_a_wrong_url_secret_is_refused(self):
        url = reverse("inbound-webhook", args=["telegram", "y" * 30])
        res = self.client.post(url, data="{}", content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_an_unknown_channel_is_404_not_500(self):
        url = reverse("inbound-webhook", args=["fax", self.secret])
        self.assertEqual(
            self.client.post(url, data="{}", content_type="application/json").status_code,
            404,
        )

    @patch("apps.customers.turn.run_sales_agent")
    def test_a_payload_that_is_not_a_message_is_accepted_and_ignored(self, agent):
        """Receipts and reactions come down the same pipe. Erroring makes the
        platform back off and eventually disable the webhook."""
        for payload in ({"update_id": 2}, {"message": {"chat": {"id": 1}}}, {}):
            res = self.post(payload)
            self.assertEqual(res.status_code, 200, payload)
            self.assertEqual(res.json()["accepted"], 0)
        agent.assert_not_called()

    def test_unparseable_json_is_accepted_not_retried(self):
        res = self.client.post(
            self.url, data=b"{not json", content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=self.secret,
        )
        self.assertEqual(res.status_code, 200)

    @patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY))
    @patch("apps.customers.views_webhook._send")
    def test_a_conversation_a_human_took_over_gets_no_ai_reply(self, send, agent):
        self.post()
        conversation = Conversation.objects.get(store=self.store)
        conversation.state = Conversation.State.HUMAN
        conversation.save()

        second = dict(TELEGRAM_MESSAGE)
        second["message"] = {**TELEGRAM_MESSAGE["message"], "message_id": 78,
                             "text": "هنوز منتظرم"}
        self.post(second)

        self.assertEqual(agent.call_count, 1)  # only the first one
        self.assertIn("هنوز منتظرم", [m.text for m in conversation.messages.all()])

    @patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY))
    @patch("apps.customers.views_webhook._send")
    def test_the_same_person_writing_again_stays_one_thread(self, send, agent):
        self.post()
        second = dict(TELEGRAM_MESSAGE)
        second["message"] = {**TELEGRAM_MESSAGE["message"], "message_id": 79,
                             "text": "قیمتش چنده؟"}
        self.post(second)
        self.assertEqual(Conversation.objects.filter(store=self.store).count(), 1)
        self.assertEqual(Customer.objects.filter(store=self.store).count(), 1)

    def test_get_is_not_a_handshake_on_telegram(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)


@override_settings(UPMARKET_AI={"META_APP_SECRET": "app-secret", "META_VERIFY_TOKEN": "vt"})
class MetaTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("ig-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")
        self.secret = webhooks.secret_for(self.store)
        self.url = reverse("inbound-webhook", args=["instagram", self.secret])

    def signed(self, payload: dict):
        body = json.dumps(payload).encode()
        digest = hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
        return self.client.post(
            self.url, data=body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
        )

    def message(self, text="سلام", mid="m1", echo=False):
        return {
            "entry": [{
                "messaging": [{
                    "sender": {"id": "ig-999"},
                    "message": {"mid": mid, "text": text, **({"is_echo": True} if echo else {})},
                }]
            }]
        }

    @patch("apps.customers.turn.run_sales_agent", return_value=dict(AI_REPLY))
    @patch("apps.customers.views_webhook._send")
    def test_a_signed_message_is_accepted(self, send, agent):
        res = self.signed(self.message())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["accepted"], 1)
        self.assertEqual(Conversation.objects.get(store=self.store).channel, "INSTAGRAM")

    def test_a_wrong_signature_is_refused(self):
        body = json.dumps(self.message()).encode()
        res = self.client.post(
            self.url, data=body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64,
        )
        self.assertEqual(res.status_code, 403)

    def test_no_signature_is_refused(self):
        res = self.client.post(
            self.url, data=json.dumps(self.message()), content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    @patch("apps.customers.turn.run_sales_agent")
    def test_our_own_reply_echoed_back_is_not_answered(self, agent):
        """Meta delivers the shop's own replies down the same webhook. Feeding
        those to the agent makes it answer itself until the quota runs out."""
        res = self.signed(self.message(echo=True))
        self.assertEqual(res.json()["accepted"], 0)
        agent.assert_not_called()

    def test_the_verification_handshake_answers_the_challenge(self):
        res = self.client.get(
            self.url, {"hub.verify_token": "vt", "hub.challenge": "12345"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content.decode(), "12345")

    def test_the_handshake_refuses_a_wrong_token(self):
        res = self.client.get(
            self.url, {"hub.verify_token": "nope", "hub.challenge": "12345"},
        )
        self.assertEqual(res.status_code, 403)


@override_settings(UPMARKET_AI={})
class MetaWithoutCredentialsTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("ig-owner-2", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه")
        self.secret = webhooks.secret_for(self.store)

    def test_an_unconfigured_integration_refuses_rather_than_trusting(self):
        url = reverse("inbound-webhook", args=["instagram", self.secret])
        res = self.client.post(url, data="{}", content_type="application/json")
        self.assertEqual(res.status_code, 403)


class ProfileTests(TestCase):
    def test_the_secret_lives_on_the_profile(self):
        owner = User.objects.create_user("prof-owner", password="x")
        store = Store.objects.create(owner=owner, name="فروشگاه")
        secret = webhooks.secret_for(store)
        self.assertEqual(StoreProfile.objects.get(store=store).webhook_secret, secret)
