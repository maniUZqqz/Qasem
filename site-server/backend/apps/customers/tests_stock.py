"""Stock reservation, the confirmation rules, and receipts from a chat.

Covers ب۶ (stock was never decremented), ب۱۲ (any order could be "confirmed"
without a rial arriving) and ب۷ (a customer could not send a receipt on the
one channel a shop actually uses). Each test fails on the code as it was
before those fixes.
"""
import io
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from apps.products.models import Product, ProductVariant
from apps.stores.models import Store, StoreProfile

from . import stock, webhooks
from .models import (
    Conversation,
    Customer,
    Notification,
    Order,
    OrderItem,
    PaymentReceipt,
)


def an_image() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


class StockLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=Decimal("100"), stock_quantity=3
        )
        self.customer = Customer.objects.create(store=self.store, name="مشتری")

    def an_order(self, quantity=1, variant=None):
        order = Order.objects.create(
            store=self.store, customer=self.customer, total=Decimal("100") * quantity
        )
        OrderItem.objects.create(
            order=order, product=self.product, variant=variant,
            quantity=quantity, unit_price=Decimal("100"),
        )
        return order

    def test_reserving_holds_the_goods_without_emptying_the_shelf(self):
        stock.reserve(self.an_order(quantity=2))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3, "the shelf did not change")
        self.assertEqual(self.product.reserved_quantity, 2)
        self.assertEqual(self.product.available_quantity, 1)

    def test_confirming_takes_the_goods_off_the_shelf_once(self):
        order = self.an_order(quantity=2)
        stock.reserve(order)
        stock.apply(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)
        self.assertEqual(self.product.reserved_quantity, 0)

        # a retried confirmation must not sell the same two items again
        self.assertFalse(stock.apply(Order.objects.get(pk=order.pk)))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)

    def test_cancelling_frees_the_reservation_but_invents_no_stock(self):
        order = self.an_order()
        stock.reserve(order)
        stock.release(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 3)

        sold = self.an_order()
        stock.reserve(sold)
        stock.apply(sold)
        self.assertFalse(stock.release(Order.objects.get(pk=sold.pk)))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)

    def test_two_customers_cannot_both_buy_the_last_one(self):
        self.product.stock_quantity = 1
        self.product.save()
        stock.reserve(self.an_order())
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 0)

    def test_an_expired_reservation_goes_back_on_the_shelf(self):
        order = self.an_order()
        stock.reserve(order)
        Order.objects.filter(pk=order.pk).update(
            reserved_until=timezone.now() - timedelta(hours=1)
        )
        self.assertEqual(stock.release_expired(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 3)

    def test_a_variant_holds_its_own_stock(self):
        variant = ProductVariant.objects.create(
            product=self.product, name="سایز ۴۲", stock_quantity=2
        )
        stock.reserve(self.an_order(variant=variant))
        variant.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(variant.available_quantity, 1)
        self.assertEqual(self.product.reserved_quantity, 0, "the parent was not touched")

    def test_the_catalogue_the_agent_sees_quotes_what_is_sellable(self):
        from .agent import catalog_payload

        stock.reserve(self.an_order(quantity=2))
        row = catalog_payload(Product.objects.filter(pk=self.product.pk))[0]
        self.assertEqual(row["stock_quantity"], 1)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="upmarket-stock-test-"))
class OrderDecisionRuleTests(APITestCase):
    """ب۱۲ — "confirmed" must mean the money arrived."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=Decimal("100"), stock_quantity=5
        )
        self.customer = Customer.objects.create(store=self.store, name="مشتری")
        self.order = Order.objects.create(
            store=self.store, customer=self.customer, total=Decimal("100")
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=1, unit_price=Decimal("100")
        )
        self.client.force_authenticate(user=self.user)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.conf import settings as dj_settings

        shutil.rmtree(dj_settings.MEDIA_ROOT, ignore_errors=True)

    def test_a_draft_with_no_receipt_cannot_be_confirmed(self):
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/confirm/")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["error"]["code"], "no_receipt")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DRAFT)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_pay_on_delivery_is_its_own_decision_and_holds_the_goods(self):
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/cod/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], Order.Status.CASH_ON_DELIVERY)
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_quantity, 1)
        self.assertEqual(self.product.stock_quantity, 5)

    def test_confirming_a_pay_on_delivery_order_sells_it(self):
        self.client.post(f"/api/v1/orders/{self.order.id}/cod/")
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/confirm/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["confirmed_at"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 4)
        self.assertEqual(self.product.reserved_quantity, 0)

    def test_cancelling_releases_what_was_held(self):
        self.client.post(f"/api/v1/orders/{self.order.id}/cod/")
        self.client.post(f"/api/v1/orders/{self.order.id}/cancel/")
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 5)

    def test_a_confirmed_order_always_carries_its_confirmation_date(self):
        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=["status", "updated_at"])
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.confirmed_at)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="upmarket-receipt-test-"))
class ReceiptFromChatTests(APITestCase):
    """ب۷ — a caption-less photo in Telegram is how a receipt really arrives."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.profile, _ = StoreProfile.objects.get_or_create(store=self.store)
        self.profile.telegram_bot_token = "111:AAA-own-bot"
        self.profile.save()
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=Decimal("100"), stock_quantity=5
        )
        self.customer = Customer.objects.create(
            store=self.store, name="مشتری", external_id="9001", channel="telegram"
        )
        self.conversation = Conversation.objects.create(
            store=self.store, customer=self.customer,
            channel="TELEGRAM", external_id="9001",
        )
        self.order = Order.objects.create(
            store=self.store, customer=self.customer, conversation=self.conversation,
            status=Order.Status.AWAITING_RECEIPT, total=Decimal("100"),
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=1, unit_price=Decimal("100")
        )
        self.payload = {
            "message": {
                "message_id": 555,
                "chat": {"id": 9001},
                "from": {"id": 9001, "first_name": "مشتری"},
                "photo": [
                    {"file_id": "small"},
                    {"file_id": "BIGGEST"},
                ],
            }
        }

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.conf import settings as dj_settings

        shutil.rmtree(dj_settings.MEDIA_ROOT, ignore_errors=True)

    def test_the_parser_keeps_a_photo_that_has_no_caption(self):
        parsed = webhooks.parse("telegram", self.payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].text, "")
        self.assertEqual(parsed[0].image, {"kind": "telegram_file", "file_id": "BIGGEST"})

    def test_a_meta_image_attachment_is_kept_too(self):
        parsed = webhooks.parse("instagram", {
            "entry": [{"messaging": [{
                "sender": {"id": "77"},
                "message": {
                    "mid": "m1",
                    "attachments": [
                        {"type": "image", "payload": {"url": "https://x/y.jpg"}}
                    ],
                },
            }]}],
        })
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].image, {"kind": "url", "url": "https://x/y.jpg"})

    def _post_the_photo(self, message_id=555):
        from unittest.mock import patch

        secret = webhooks.secret_for(self.store)
        payload = {"message": {**self.payload["message"], "message_id": message_id}}
        with patch(
            "apps.customers.receipts.fetch", return_value=(an_image(), "image/png")
        ), patch("apps.customers.receipts.acknowledge"):
            return self.client.post(
                f"/api/v1/webhooks/telegram/{secret}/",
                payload, format="json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret,
            )

    def test_the_photo_becomes_a_receipt_waiting_for_a_human(self):
        resp = self._post_the_photo()
        self.assertEqual(resp.status_code, 200, resp.content)

        receipt = PaymentReceipt.objects.get(order=self.order)
        self.assertTrue(receipt.image.name)
        self.assertGreater(receipt.image.size, 0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_APPROVAL)
        self.assertEqual(
            Notification.objects.filter(
                store=self.store, type=Notification.Type.RECEIPT
            ).count(),
            1,
        )
        # the bot never decides about money
        self.assertNotEqual(self.order.status, Order.Status.CONFIRMED)

    def test_a_retried_delivery_does_not_file_the_receipt_twice(self):
        self._post_the_photo()
        self._post_the_photo()
        self.assertEqual(PaymentReceipt.objects.filter(order=self.order).count(), 1)

    def test_a_photo_with_no_open_order_is_not_an_error(self):
        self.order.status = Order.Status.CONFIRMED
        self.order.save()
        resp = self._post_the_photo(message_id=556)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PaymentReceipt.objects.filter(order=self.order).count(), 0)


class PerStoreTelegramTokenTests(TestCase):
    """ب۱۱ — two shops must be able to each have their own bot."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.first = Store.objects.create(owner=self.user, name="First")
        self.second = Store.objects.create(owner=self.user, name="Second")

    def test_each_store_answers_from_its_own_bot(self):
        from services.publishing import channels

        for store, token in ((self.first, "111:AAA"), (self.second, "222:BBB")):
            profile, _ = StoreProfile.objects.get_or_create(store=store)
            profile.telegram_bot_token = token
            profile.save()

        self.assertEqual(
            channels.telegram_token(Store.objects.get(pk=self.first.pk)), "111:AAA"
        )
        self.assertEqual(
            channels.telegram_token(Store.objects.get(pk=self.second.pk)), "222:BBB"
        )

    @override_settings(UPMARKET_AI={"TELEGRAM_BOT_TOKEN": "shared-token"})
    def test_an_empty_token_falls_back_to_the_shared_bot(self):
        from services.publishing import channels

        self.assertEqual(channels.telegram_token(self.first), "shared-token")
