"""SMS through the owner's phones: sending, receiving, and the privacy rules."""
from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from apps.customers.models import Conversation
from apps.mobile.models import MobileDevice, MobileSettings, SmsInbound, SmsMessage, SmsOptOut, hash_token
from services.publishing import channels

from . import sms_gateway
from .models import ChannelConnection, Contact
from .tests_base import InboxTestCase


class SmsTests(InboxTestCase):
    def phone(self, user=None, *, online=True):
        return MobileDevice.objects.create(
            user=user or self.sara, name="گوشی دفتر", install_id=uuid.uuid4().hex, token_hash=hash_token(uuid.uuid4().hex),
            last_seen_at=timezone.now() if online else timezone.now() - timedelta(hours=2), sms_enabled=True,
        )

    def inbound(self, device, number, body, n=1):
        return SmsInbound.objects.create(device=device, dedupe_key=f"k{uuid.uuid4().hex[:8]}", from_number=number, body=body)

    def sms(self, **config):
        row = self.connect("SMS", token="", config=config)
        return row

    def test_a_reply_is_queued_on_the_phone_gateway(self):
        self.sms()
        conversation = self.conversation("SMS", sender="989121234567", state=Conversation.State.HUMAN)
        out = channels.send("SMS", self.store, to=conversation.external_id, text="سلام، سفارش شما ارسال شد")
        self.assertTrue(out["sent"])
        message = SmsMessage.objects.get()
        self.assertEqual((message.to_number, message.kind, message.state), ("989121234567", "transactional", "QUEUED"))

    def test_a_number_that_said_stop_is_refused_by_the_gateway_and_we_say_why(self):
        from apps.mobile import sms as gateway

        self.sms()
        gateway.add_opt_out("09121234567")
        out = channels.send("SMS", self.store, to="989121234567", text="سلام")
        self.assertFalse(out["sent"])
        self.assertIn("لغو", out["reason"])

    def test_too_long_for_sms_is_refused_before_the_gateway(self):
        self.sms()
        out = channels.send("SMS", self.store, to="989121234567", text="ا" * 600)
        self.assertFalse(out["sent"])
        self.assertEqual(SmsMessage.objects.count(), 0)

    def test_availability_needs_an_online_phone_and_a_running_queue(self):
        self.assertFalse(sms_gateway.available(self.store))
        device = self.phone(online=False)
        self.assertFalse(sms_gateway.available(self.store))
        device.last_seen_at = timezone.now()
        device.save()
        self.assertTrue(sms_gateway.available(self.store))
        settings = MobileSettings.get()
        settings.sms_enabled = False
        settings.save()
        self.assertFalse(sms_gateway.available(self.store))

    def test_a_phone_of_another_store_never_counts(self):
        self.phone(user=self.other_owner)
        self.assertFalse(sms_gateway.available(self.store))

    def test_only_new_messages_are_ever_imported(self):
        device = self.phone()
        MobileSettings.objects.update_or_create(pk=1, defaults={"forward_incoming_sms": True})
        self.inbound(device, "989121234567", "پیامک قدیمی و خصوصی")
        row = self.sms(accept_unknown=True)
        sms_gateway.start(row)  # switching on: the cursor jumps to now
        row.refresh_from_db()
        self.assertEqual(sms_gateway.pull(row)["received"], 0)
        self.assertEqual(Conversation.objects.filter(channel="SMS").count(), 0)
        self.inbound(device, "989121234567", "پیامک تازه")
        with patch("apps.customers.views_webhook._respond_later"):
            result = sms_gateway.pull(row)
        self.assertEqual(result["accepted"], 1)

    def test_unknown_senders_banks_and_short_codes_stay_out_by_default(self):
        device = self.phone()
        MobileSettings.objects.update_or_create(pk=1, defaults={"forward_incoming_sms": True})
        row = self.sms()
        sms_gateway.start(row)
        self.inbound(device, "989129998877", "غریبه")
        self.inbound(device, "30001234", "کد بانک ۱۲۳۴۵")
        self.inbound(device, "BANKMELLI", "موجودی")
        Contact.objects.create(store=self.store, name="مشتری", phone="09121112233")
        self.inbound(device, "989121112233", "از مشتری شناخته‌شده")
        with patch("apps.customers.views_webhook._respond_later"):
            result = sms_gateway.pull(row)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["skipped"], 3)
        conversation = Conversation.objects.get(channel="SMS")
        self.assertEqual(conversation.messages.get().text, "از مشتری شناخته‌شده")
        self.assertEqual(conversation.customer.inbox_link.contact.phone, "09121112233")  # merged with the known contact

    def test_a_store_that_runs_a_public_number_can_accept_everyone_with_a_real_mobile(self):
        device = self.phone()
        MobileSettings.objects.update_or_create(pk=1, defaults={"forward_incoming_sms": True})
        row = self.sms(accept_unknown=True)
        sms_gateway.start(row)
        self.inbound(device, "989129998877", "سلام، عضویت؟")
        self.inbound(device, "30001234", "کد بانک")  # still never
        with patch("apps.customers.views_webhook._respond_later"):
            result = sms_gateway.pull(row)
        self.assertEqual((result["accepted"], result["skipped"]), (1, 1))

    def test_pulling_twice_does_not_double_deliver(self):
        device = self.phone()
        MobileSettings.objects.update_or_create(pk=1, defaults={"forward_incoming_sms": True})
        row = self.sms(accept_unknown=True)
        sms_gateway.start(row)
        self.inbound(device, "989129998877", "یک")
        with patch("apps.customers.views_webhook._respond_later"):
            sms_gateway.pull(row)
            second = sms_gateway.pull(row)
        self.assertEqual(second["received"], 0)
        self.assertEqual(Conversation.objects.filter(channel="SMS").count(), 1)

    def test_a_replied_to_number_counts_as_known(self):
        device = self.phone()
        MobileSettings.objects.update_or_create(pk=1, defaults={"forward_incoming_sms": True})
        row = self.sms()
        sms_gateway.start(row)
        channels.send("SMS", self.store, to="989125556677", text="سلام")  # we wrote to them first
        self.inbound(device, "989125556677", "جواب")
        with patch("apps.customers.views_webhook._respond_later"):
            self.assertEqual(sms_gateway.pull(row)["accepted"], 1)

    def test_the_forwarding_switch_is_staff_only(self):
        c = self.api(self.admin)
        self.assertEqual(c.post(self.url("channels/sms/forwarding/"), {"on": True}, format="json").status_code, 403)
        staff = self.api(self.owner)
        self.owner.is_staff = True
        self.owner.save()
        self.assertTrue(self.api(self.owner).post(self.url("channels/sms/forwarding/"), {"on": True}, format="json").json()["forwarding"])
        self.assertTrue(MobileSettings.get().forward_incoming_sms)

    def test_enabling_sms_needs_a_phone_and_then_starts_at_now(self):
        c = self.api(self.admin)
        refused = c.put(self.url("channels/SMS/"), {"enabled": True}, format="json").json()
        self.assertFalse(refused["channel"]["enabled"])
        self.assertIn("گوشی", refused["enabled_refused"])
        device = self.phone()
        self.inbound(device, "989121234567", "قدیمی")
        ok = c.put(self.url("channels/SMS/"), {"enabled": True}, format="json").json()
        self.assertTrue(ok["channel"]["enabled"])
        row = ChannelConnection.objects.get(store=self.store, kind="SMS")
        self.assertEqual(int(row.poll_cursor), SmsInbound.objects.latest("id").pk)
        listing = c.get(self.url("channels/")).json()["channels"]
        sms = next(x for x in listing if x["kind"] == "SMS")
        self.assertEqual(sms["sms"]["online"], 1)
