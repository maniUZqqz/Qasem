"""A payment slip photo sent on Bale / Rubika / WhatsApp reaches the receipt flow."""
from __future__ import annotations

import io

from django.test import override_settings
from PIL import Image

from apps.customers import receipts
from apps.customers.models import Conversation, Customer, Message, Order

from . import files
from .adapters import eitaa, rubika, tgcompat, whatsapp
from .fakes import FakePlatform
from .tests_adapters import Conn
from .tests_base import InboxTestCase


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 120, 90)).save(buffer, "PNG")
    return buffer.getvalue()


class DescriptorTests(InboxTestCase):
    def test_each_platform_names_itself_in_the_descriptor(self):
        photo = {"message": {"message_id": 1, "chat": {"id": 5}, "from": {"id": 9}, "photo": [{"file_id": "f1"}]}}
        self.assertEqual(tgcompat.TelegramAdapter(Conn()).parse(photo)[0].image["kind"], "telegram_file")
        self.assertEqual(tgcompat.BaleAdapter(Conn()).parse(photo)[0].image["kind"], "bale_file")
        self.assertEqual(eitaa.EitaaAdapter(Conn()).parse(photo)[0].image["kind"], "eitaa_file")
        update = {"update": {"type": "NewMessage", "chat_id": "b0x", "new_message": {
            "message_id": "m", "sender_type": "User", "sender_id": "u0", "file": {"file_id": "rf", "type": "Image"}}}}
        self.assertEqual(rubika.RubikaAdapter(Conn()).parse(update)[0].image["kind"], "rubika_file")


class ResolveTests(InboxTestCase):
    def test_bale_file_id_becomes_a_download_address(self):
        self.connect("BALE")
        with FakePlatform({"getFile": {"ok": True, "result": {"file_path": "photos/slip.png"}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            url, headers = files.resolve(self.store, {"kind": "bale_file", "file_id": "f1"})
        self.assertTrue(url.endswith("/file/bot123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ/photos/slip.png"))
        self.assertEqual(headers, {})

    def test_rubika_and_whatsapp(self):
        self.connect("RUBIKA", token="R" * 30)
        with FakePlatform({"getFile": {"status": "OK", "data": {"download_url": "https://cdn.example/x.png"}}}) as fake, \
                override_settings(INBOX_API_BASES={"RUBIKA": fake.url}):
            self.assertEqual(files.resolve(self.store, {"kind": "rubika_file", "file_id": "f"}), ("https://cdn.example/x.png", {}))
        self.connect("WHATSAPP", token="T" * 30, config={"phone_number_id": "1", "app_secret": "s", "verify_token": "v"})
        with FakePlatform({"/m-1": {"url": "https://lookaside.example/m-1"}}) as fake, \
                override_settings(INBOX_API_BASES={"WHATSAPP": fake.url}):
            url, headers = files.resolve(self.store, {"kind": "whatsapp_media", "id": "m-1"})
        self.assertEqual(url, "https://lookaside.example/m-1")
        self.assertTrue(headers["Authorization"].startswith("Bearer "))  # the media server wants the token too

    def test_eitaa_unknown_kinds_and_switched_off_channels_resolve_to_nothing(self):
        self.connect("EITAA")
        self.assertIsNone(files.resolve(self.store, {"kind": "eitaa_file", "file_id": "f"}))
        self.assertIsNone(files.resolve(self.store, {"kind": "mystery", "file_id": "f"}))
        self.connect("BALE", enabled=False)
        self.assertIsNone(files.resolve(self.store, {"kind": "bale_file", "file_id": "f"}))


class ReceiptFlowTests(InboxTestCase):
    def test_a_bale_slip_is_attached_to_the_open_order(self):
        self.connect("BALE")
        conversation = self.conversation("BALE", sender="900")
        order = Order.objects.create(store=self.store, customer=conversation.customer, conversation=conversation,
                                     status=Order.Status.AWAITING_RECEIPT, total=1000)
        message = Message.objects.create(
            conversation=conversation, role=Message.Role.CUSTOMER, text="[تصویر]",
            grounding={"image": {"kind": "bale_file", "file_id": "f1"}},
        )
        answers = {
            "getFile": {"ok": True, "result": {"file_path": "photos/slip.png"}},
            "photos/slip.png": png_bytes(),
        }
        with FakePlatform(answers) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            receipt = receipts.absorb(message)
        self.assertIsNotNone(receipt)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.AWAITING_APPROVAL)  # a person still approves the money

    def test_a_slip_that_cannot_be_resolved_tells_the_owner_instead_of_vanishing(self):
        from apps.customers.models import Notification

        self.connect("EITAA")
        conversation = self.conversation("EITAA", sender="55")
        Order.objects.create(store=self.store, customer=conversation.customer, conversation=conversation,
                             status=Order.Status.AWAITING_RECEIPT, total=1000)
        message = Message.objects.create(
            conversation=conversation, role=Message.Role.CUSTOMER, text="[تصویر]",
            grounding={"image": {"kind": "eitaa_file", "file_id": "f"}},
        )
        self.assertIsNone(receipts.absorb(message))
        self.assertTrue(Notification.objects.filter(store=self.store, type="RECEIPT").exists())

    def test_telegram_and_url_photos_still_take_their_old_road(self):
        self.assertIsNone(receipts.fetch(self.store, {"kind": "mystery"}))
        with FakePlatform({"/slip.png": png_bytes()}) as fake:
            data, content_type = receipts.fetch(self.store, {"kind": "url", "url": fake.url + "/slip.png"})
        self.assertEqual(content_type, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))
