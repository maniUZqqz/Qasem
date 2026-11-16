"""Channel adapters against fake platform servers (real HTTP on localhost).

What each platform really does is encoded in the fake: Bale answers a bad token
with HTTP 401, Eitaa Yar answers HTTP 200 with the error inside the body, Rubika
answers a bad token on `getMe` with `{"status": "INVALID_INPUT"}` - all three
observed against the live services. A test that passed against an idealised fake
would prove nothing about the day a real token is pasted in.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from django.test import override_settings

from apps.customers.models import Conversation
from services.publishing import channels

from . import adapters, dispatch
from .adapters import eitaa, rubika, tgcompat, whatsapp
from .fakes import FakePlatform
from .models import ChannelConnection
from .tests_base import InboxTestCase

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class Conn:
    """A connection stand-in for adapters that only read token/config/secret."""

    def __init__(self, token=TOKEN, config=None, secret="s3cret"):
        self.token, self.config, self.secret = token, config or {}, secret
        self.store = None


UPDATE = {"ok": True, "result": [{"update_id": 10, "message": {
    "message_id": 5, "from": {"id": 77, "first_name": "علی", "last_name": "رضایی", "username": "Ali_Fit"},
    "chat": {"id": 77, "type": "private"}, "text": "سلام، قیمت؟"}}]}


class BaleTests(InboxTestCase):
    def test_health_send_and_poll(self):
        with FakePlatform({
            "getMe": {"ok": True, "result": {"username": "shop_bot"}},
            "sendMessage": {"ok": True, "result": {"message_id": 9}},
            "getUpdates": UPDATE,
        }) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            adapter = tgcompat.BaleAdapter(Conn())
            health = adapter.health()
            self.assertTrue(health.ok)
            self.assertEqual(health.account, "@shop_bot")
            sent = adapter.send("77", "درود")
            self.assertTrue(sent.ok)
            self.assertEqual(sent.external_id, "9")
            polled = adapter.poll("")
            self.assertEqual(len(polled.messages), 1)
            self.assertEqual(polled.cursor, "11")  # last update id + 1: nothing is delivered twice
            message = polled.messages[0]
            self.assertEqual((message.text, message.thread_id, message.username), ("سلام، قیمت؟", "77", "Ali_Fit"))
            self.assertEqual(message.name, "علی رضایی")
            # the token is part of the URL path (Telegram-shaped), and nothing else
            self.assertTrue(fake.requests[0]["path"].startswith(f"/bot{TOKEN}/"))
            adapter.poll("11")
            self.assertEqual(fake.requests[-1]["body"]["offset"], 11)

    def test_a_bad_token_is_said_in_words_without_leaking_the_token(self):
        with FakePlatform({"getMe": (401, {"ok": False, "error_code": 401, "description": "Unauthorized"})}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            health = tgcompat.BaleAdapter(Conn()).health()
        self.assertFalse(health.ok)
        self.assertIn("پذیرفته نشد", health.detail)
        self.assertNotIn("ABCDEFG", health.detail)

    def test_an_unreachable_platform_never_quotes_the_token(self):
        with override_settings(INBOX_API_BASES={"BALE": "http://127.0.0.1:1"}):
            result = tgcompat.BaleAdapter(Conn()).send("77", "x")
        self.assertFalse(result.ok)
        self.assertNotIn("ABCDEFG", result.reason)
        self.assertNotIn("127.0.0.1", result.reason)

    def test_groups_bots_and_empty_updates_are_not_customers(self):
        adapter = tgcompat.BaleAdapter(Conn())
        group = {"message": {"message_id": 1, "chat": {"id": 5, "type": "group"}, "from": {"id": 9}, "text": "hi"}}
        bot = {"message": {"message_id": 2, "chat": {"id": 5, "type": "private"}, "from": {"id": 9, "is_bot": True}, "text": "hi"}}
        sticker = {"message": {"message_id": 3, "chat": {"id": 5, "type": "private"}, "from": {"id": 9}}}
        self.assertEqual(adapter.parse(group), [])
        self.assertEqual(adapter.parse(bot), [])
        self.assertEqual(adapter.parse(sticker), [])

    def test_photo_and_contact_card_are_understood(self):
        adapter = tgcompat.BaleAdapter(Conn())
        photo = {"message": {"message_id": 1, "chat": {"id": 5}, "from": {"id": 9}, "photo": [
            {"file_id": "small"}, {"file_id": "big"}]}}
        parsed = adapter.parse(photo)[0]
        self.assertEqual(parsed.image, {"kind": "bale_file", "file_id": "big"})  # names Bale, so the receipt flow asks Bale for the file
        card = {"message": {"message_id": 2, "chat": {"id": 5}, "from": {"id": 9},
                            "contact": {"phone_number": "+98 912 345 6789"}}}
        self.assertEqual(adapter.parse(card)[0].phone, "+98 912 345 6789")

    def test_too_long_is_refused_before_the_network(self):
        result = tgcompat.BaleAdapter(Conn()).send("1", "x" * 5000)
        self.assertFalse(result.ok)
        self.assertIn("بلندتر", result.reason)


class EitaaTests(InboxTestCase):
    def test_error_comes_back_inside_a_200(self):
        with FakePlatform({"getMe": (200, {"ok": False, "error_code": 401, "description": "Unauthorized"})}) as fake, \
                override_settings(INBOX_API_BASES={"EITAA": fake.url}):
            health = eitaa.EitaaAdapter(Conn()).health()
        self.assertFalse(health.ok)
        self.assertIn("پذیرفته نشد", health.detail)

    def test_send_carries_the_title_eitaa_shows_and_no_bot_prefix(self):
        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 3}}}) as fake, \
                override_settings(INBOX_API_BASES={"EITAA": fake.url}):
            result = eitaa.EitaaAdapter(Conn(config={"message_title": "پشتیبانی چغر"})).send("55", "سلام")
        self.assertTrue(result.ok)
        request = fake.requests[0]
        self.assertTrue(request["path"].startswith(f"/{TOKEN}/sendMessage"))
        self.assertEqual(request["body"]["title"], "پشتیبانی چغر")

    def test_a_bot_that_cannot_receive_is_reported_as_send_only_not_green(self):
        with FakePlatform({
            "getMe": {"ok": True, "result": {"username": "eb"}},
            "getUpdates": (200, {"ok": False, "error_code": 400, "description": "not enabled"}),
        }) as fake, override_settings(INBOX_API_BASES={"EITAA": fake.url}):
            health = eitaa.EitaaAdapter(Conn()).health()
            self.assertTrue(health.ok)
            self.assertIn("دریافت پیام", health.detail)
            self.assertFalse(eitaa.probe_receive(eitaa.EitaaAdapter(Conn())))

    def test_a_bot_that_can_receive_says_so(self):
        with FakePlatform({
            "getMe": {"ok": True, "result": {"username": "eb"}},
            "getUpdates": {"ok": True, "result": []},
        }) as fake, override_settings(INBOX_API_BASES={"EITAA": fake.url}):
            health = eitaa.EitaaAdapter(Conn()).health()
        self.assertIn("ارسال و دریافت فعال", health.detail)


RUBIKA_UPDATES = {"status": "OK", "data": {"updates": [
    {"type": "NewMessage", "chat_id": "b0abc", "new_message": {
        "message_id": "m1", "text": "ساعت کاری؟", "sender_type": "User", "sender_id": "u0xyz"}},
    {"type": "NewMessage", "chat_id": "b0bot", "new_message": {
        "message_id": "m2", "text": "echo", "sender_type": "Bot", "sender_id": "b0bot"}},
], "next_offset_id": "nx9"}}


class RubikaTests(InboxTestCase):
    def test_poll_send_health_and_webhook_registration(self):
        with FakePlatform({
            "getMe": {"status": "OK", "data": {"bot": {"username": "my_bot"}}},
            "sendMessage": {"status": "OK", "data": {"message_id": "r1"}},
            "getUpdates": RUBIKA_UPDATES,
            "updateBotEndpoints": {"status": "OK", "data": {}},
        }) as fake, override_settings(INBOX_API_BASES={"RUBIKA": fake.url}):
            adapter = rubika.RubikaAdapter(Conn(token="TOKTOKTOKTOKTOKTOKTOK"))
            self.assertTrue(adapter.health().ok)
            self.assertEqual(adapter.send("b0abc", "سلام").external_id, "r1")
            polled = adapter.poll("")
            self.assertEqual(polled.cursor, "nx9")
            self.assertEqual([m.thread_id for m in polled.messages], ["b0abc"])  # the bot's own echo is dropped
            adapter.register_webhook("https://nm.example/api/v1/inbox/hook/rubika/xyz/")
            hook = [r for r in fake.requests if r["path"].endswith("updateBotEndpoints")][0]
            self.assertEqual(hook["body"]["type"], "ReceiveUpdate")

    def test_wrong_token_is_input_error_on_getme(self):
        with FakePlatform({"getMe": (200, {"status": "INVALID_INPUT"})}) as fake, \
                override_settings(INBOX_API_BASES={"RUBIKA": fake.url}):
            health = rubika.RubikaAdapter(Conn(token="BADTOKENBADTOKENBADTOK")).health()
        self.assertFalse(health.ok)
        self.assertIn("پذیرفته نشد", health.detail)

    def test_webhook_body_and_inline_buttons(self):
        adapter = rubika.RubikaAdapter(Conn())
        body = {"update": {"type": "NewMessage", "chat_id": "b0q", "new_message": {
            "message_id": "z", "text": "hey", "sender_type": "User", "sender_id": "u0q"}}}
        self.assertEqual(adapter.parse(body)[0].text, "hey")
        self.assertEqual(adapter.parse({"inline_message": {"x": 1}}), [])


class WhatsAppTests(InboxTestCase):
    PAYLOAD = {"entry": [{"changes": [{"value": {
        "contacts": [{"profile": {"name": "سارا"}, "wa_id": "989121234567"}],
        "messages": [{"from": "989121234567", "id": "wamid.1", "type": "text", "text": {"body": "سلام"}}]}}]}]}

    def adapter(self):
        return whatsapp.WhatsAppAdapter(Conn(token="T" * 30, config={
            "phone_number_id": "555", "app_secret": "appsec", "verify_token": "vt"}))

    def test_parse_uses_the_cloud_api_envelope(self):
        message = self.adapter().parse(self.PAYLOAD)[0]
        self.assertEqual((message.text, message.name, message.phone), ("سلام", "سارا", "989121234567"))

    def test_signature_is_required_and_checked(self):
        body = json.dumps(self.PAYLOAD).encode()
        good = "sha256=" + hmac.new(b"appsec", body, hashlib.sha256).hexdigest()
        adapter = self.adapter()
        self.assertTrue(adapter.verify(body, {"X-Hub-Signature-256": good}))
        self.assertFalse(adapter.verify(body, {"X-Hub-Signature-256": "sha256=00"}))
        self.assertFalse(adapter.verify(body, {}))
        no_secret = whatsapp.WhatsAppAdapter(Conn(config={"phone_number_id": "1"}))
        self.assertFalse(no_secret.verify(body, {"X-Hub-Signature-256": good}))  # unconfigured = refuse

    def test_handshake(self):
        adapter = self.adapter()
        self.assertEqual(adapter.handshake({"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}), "42")
        self.assertIsNone(adapter.handshake({"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "42"}))

    def test_send_uses_bearer_and_phone_number_id(self):
        with FakePlatform({"messages": {"messages": [{"id": "wamid.out"}]}}) as fake, \
                override_settings(INBOX_API_BASES={"WHATSAPP": fake.url}):
            result = self.adapter().send("989121234567", "سلام")
        self.assertEqual(result.external_id, "wamid.out")
        self.assertTrue(fake.requests[0]["path"].endswith("/555/messages"))
        self.assertTrue(fake.requests[0]["headers"]["Authorization"].startswith("Bearer "))

    def test_whatsapp_is_off_by_default_and_refuses_to_send(self):
        """No account, no sending: the channel exists but nothing leaves."""
        conversation = self.conversation("WHATSAPP", sender="989121234567")
        outcome = channels.send("WHATSAPP", self.store, to=conversation.external_id, text="hi")
        self.assertFalse(outcome["sent"])
        self.assertIn("وصل نشده", outcome["reason"])


class DispatchTests(InboxTestCase):
    def test_send_counts_and_records_failure(self):
        self.connect("BALE")
        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 1}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            outcome = dispatch.send("BALE", self.store, to="77", text="سلام")
        self.assertTrue(outcome["sent"])
        row = ChannelConnection.objects.get(store=self.store, kind="BALE")
        self.assertEqual(row.outbound_count, 1)
        self.assertIsNotNone(row.last_outbound_at)
        with FakePlatform({"sendMessage": (500, {})}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            bad = dispatch.send("BALE", self.store, to="77", text="سلام")
        self.assertFalse(bad["sent"])
        row.refresh_from_db()
        self.assertTrue(row.last_error)
        self.assertEqual(row.outbound_count, 1)

    def test_a_switched_off_or_missing_channel_refuses_with_words(self):
        self.assertIn("وصل نشده", dispatch.send("RUBIKA", self.store, to="x", text="y")["reason"])
        self.connect("RUBIKA", enabled=False)
        self.assertIn("خاموش", dispatch.send("RUBIKA", self.store, to="x", text="y")["reason"])

    def test_the_shared_send_call_delivers_on_new_channels(self):
        """`channels.send` is what the sales agent and the old inbox already call."""
        self.connect("BALE")
        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 1}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            outcome = channels.send("BALE", self.store, to="77", text="سلام")
        self.assertTrue(outcome["sent"])
        self.assertEqual(len(fake.requests), 1)

    def test_status_for_lists_every_new_channel_with_a_reason(self):
        rows = {r["key"]: r for r in channels.status_for(self.store)}
        for key in ("BALE", "EITAA", "RUBIKA", "WEBCHAT", "SMS", "WHATSAPP"):
            self.assertIn(key, rows)
            self.assertFalse(rows[key]["configured"], key)
            self.assertIn("صفحهٔ «کانال‌ها»", rows[key]["reason"])

    def test_registry_covers_every_connect_page_channel(self):
        from . import guides

        for kind in guides.CHANNEL_ORDER:
            if kind in ("INSTAGRAM",):
                continue
            self.assertIsNotNone(adapters.adapter_class(kind), kind)

    def test_token_for_telegram_falls_back_to_the_store_profile(self):
        from apps.stores.models import StoreProfile

        profile, _ = StoreProfile.objects.get_or_create(store=self.store)
        profile.telegram_bot_token = "999:LEGACYTOKENLEGACYTOKEN"
        profile.save()
        self.store.refresh_from_db()
        row = ChannelConnection.objects.create(store=self.store, kind="TELEGRAM", token="")
        self.assertEqual(dispatch.token_for(row), "999:LEGACYTOKENLEGACYTOKEN")


class ConversationStateUntouched(InboxTestCase):
    def test_new_channel_conversations_use_the_same_state_machine(self):
        conversation = self.conversation("BALE", sender="9")
        self.assertEqual(conversation.state, Conversation.State.AI)
