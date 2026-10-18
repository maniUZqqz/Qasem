import io
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from apps.ai.models import AIRequest
from apps.products.models import Product, ProductVariant
from apps.stores.models import Store

from .agent import run_sales_agent
from .models import (
    Conversation,
    Customer,
    Message,
    Notification,
    Order,
    OrderItem,
    PaymentReceipt,
    SupportTicket,
)

VALID_AGENT_OUTPUT = {
    "reply": "بله، این کفش برای دویدن شهری عالیه!",
    "intent": "PRODUCT_QUESTION",
    "action": "ANSWER",
    "product_ids": [],
    "order": None,
    "ticket": None,
    "confidence": "HIGH",
    "needs_human": False,
}


def make_agent_result(**overrides):
    result = {
        "reply": "پاسخ آزمایشی",
        "intent": "PRODUCT_QUESTION",
        "action": "ANSWER",
        "product_ids": [],
        "order": None,
        "order_error": None,
        "payment_request": None,
        "ticket": None,
        "confidence": "HIGH",
        "needs_human": False,
        "ai_request": None,
    }
    result.update(overrides)
    return result


def make_test_image(name="receipt.png"):
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(30, 120, 30)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class ChatEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش اسپرت", price=Decimal("1250000"), stock_quantity=5
        )
        self.client.force_authenticate(user=self.user)

    @patch("apps.customers.turn.run_sales_agent")
    def test_chat_creates_conversation_and_messages(self, mock_agent):
        mock_agent.return_value = make_agent_result(reply="سلام! چطور می‌تونم کمک کنم؟")
        resp = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "سلام"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        conversation = Conversation.objects.get(id=resp.data["conversation_id"])
        roles = list(conversation.messages.values_list("role", flat=True))
        self.assertEqual(roles, [Message.Role.CUSTOMER, Message.Role.AI])
        self.assertEqual(resp.data["message"]["text"], "سلام! چطور می‌تونم کمک کنم؟")

    @patch("apps.customers.turn.run_sales_agent")
    def test_chat_continues_existing_conversation(self, mock_agent):
        mock_agent.return_value = make_agent_result()
        first = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "سلام"}, format="json"
        )
        conversation_id = first.data["conversation_id"]
        second = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/",
            {"message": "قیمت کفش؟", "conversation_id": conversation_id},
            format="json",
        )
        self.assertEqual(second.data["conversation_id"], conversation_id)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 4)

    @patch("apps.customers.turn.run_sales_agent")
    def test_escalation_changes_state_and_stops_ai(self, mock_agent):
        mock_agent.return_value = make_agent_result(action="ESCALATE", needs_human=True)
        resp = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "شکایت دارم"}, format="json"
        )
        self.assertEqual(resp.data["state"], Conversation.State.ESCALATED)
        conversation_id = resp.data["conversation_id"]
        # next message must NOT trigger the agent
        mock_agent.reset_mock()
        resp = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/",
            {"message": "هستید؟", "conversation_id": conversation_id},
            format="json",
        )
        self.assertIsNone(resp.data["message"])
        mock_agent.assert_not_called()

    def test_chat_foreign_store_404(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        resp = self.client.post(
            f"/api/v1/stores/{bob_store.id}/chat/", {"message": "سلام"}, format="json"
        )
        self.assertEqual(resp.status_code, 404)

    def test_empty_message_rejected(self):
        resp = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "  "}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    @patch("apps.customers.turn.run_sales_agent")
    def test_handoff_and_lists(self, mock_agent):
        mock_agent.return_value = make_agent_result()
        resp = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "سلام"}, format="json"
        )
        conversation_id = resp.data["conversation_id"]

        resp = self.client.post(
            f"/api/v1/conversations/{conversation_id}/handoff/", {"state": "HUMAN"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["state"], "HUMAN")

        resp = self.client.get(f"/api/v1/stores/{self.store.id}/conversations/")
        self.assertEqual(resp.data["count"], 1)
        resp = self.client.get(f"/api/v1/conversations/{conversation_id}/messages/")
        self.assertEqual(len(resp.data), 2)


class SalesAgentGroundingTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store,
            name="کفش اسپرت",
            description="کفش سبک مناسب دویدن",
            price=Decimal("1250000"),
            stock_quantity=5,
        )
        customer = Customer.objects.create(store=self.store, name="مشتری")
        self.conversation = Conversation.objects.create(store=self.store, customer=customer)

    def _mock_provider(self, mock_provider_cls, output):
        provider = mock_provider_cls.return_value
        provider.generate_json.return_value = (dict(output), "{}")
        return provider

    @patch("apps.customers.agent.text_provider")
    def test_answer_records_ai_request(self, mock_provider_cls):
        self._mock_provider(mock_provider_cls, VALID_AGENT_OUTPUT)
        result = run_sales_agent(self.conversation, "این کفش برای دویدن خوبه؟")
        self.assertEqual(result["action"], "ANSWER")
        self.assertIsNotNone(result["ai_request"])
        self.assertEqual(AIRequest.objects.count(), 1)

    @patch("apps.customers.agent.text_provider")
    def test_unknown_product_ids_dropped(self, mock_provider_cls):
        output = dict(VALID_AGENT_OUTPUT, product_ids=[self.product.id, 9999])
        self._mock_provider(mock_provider_cls, output)
        result = run_sales_agent(self.conversation, "کفش دارید؟")
        self.assertEqual(result["product_ids"], [self.product.id])

    @patch("apps.customers.agent.text_provider")
    def test_order_created_with_db_price(self, mock_provider_cls):
        output = dict(
            VALID_AGENT_OUTPUT,
            action="CREATE_ORDER",
            order={"product_id": self.product.id, "variant_id": None, "quantity": 2},
        )
        self._mock_provider(mock_provider_cls, output)
        result = run_sales_agent(self.conversation, "دو تا می‌خوام")
        self.assertIsNone(result["order_error"])
        order = result["order"]
        self.assertIsInstance(order, Order)
        self.assertEqual(order.total, Decimal("2500000"))
        item = order.items.get()
        self.assertEqual(item.unit_price, Decimal("1250000"))  # from DB, never the model

    @patch("apps.customers.agent.text_provider")
    def test_order_rejected_when_stock_insufficient(self, mock_provider_cls):
        output = dict(
            VALID_AGENT_OUTPUT,
            action="CREATE_ORDER",
            order={"product_id": self.product.id, "variant_id": None, "quantity": 100},
        )
        self._mock_provider(mock_provider_cls, output)
        result = run_sales_agent(self.conversation, "صد تا می‌خوام")
        self.assertIsNone(result["order"])
        self.assertIsNotNone(result["order_error"])
        self.assertEqual(result["action"], "ANSWER")
        self.assertEqual(Order.objects.count(), 0)

    @patch("apps.customers.agent.text_provider")
    def test_order_with_variant_uses_variant_stock_and_price(self, mock_provider_cls):
        variant = ProductVariant.objects.create(
            product=self.product,
            name="سایز ۴۲",
            stock_quantity=1,
            price_override=Decimal("1300000"),
        )
        output = dict(
            VALID_AGENT_OUTPUT,
            action="CREATE_ORDER",
            order={"product_id": self.product.id, "variant_id": variant.id, "quantity": 1},
        )
        self._mock_provider(mock_provider_cls, output)
        result = run_sales_agent(self.conversation, "سایز ۴۲ می‌خوام")
        self.assertIsNone(result["order_error"])
        self.assertEqual(result["order"].total, Decimal("1300000"))

    @patch("apps.customers.agent.text_provider")
    def test_invalid_output_marks_validation_failed(self, mock_provider_cls):
        self._mock_provider(mock_provider_cls, {"reply": ""})
        from services.ai.ollama import OllamaMalformedOutput

        with self.assertRaises(OllamaMalformedOutput):
            run_sales_agent(self.conversation, "سلام")
        # every installed model is tried before giving up, and each attempt is
        # audited — all of them failed validation here
        rows = list(AIRequest.objects.all())
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row.status, AIRequest.Status.VALIDATION_FAILED)

    @patch("apps.customers.agent.text_provider")
    def test_a_later_model_can_rescue_an_invalid_first_answer(self, mock_provider_cls):
        """An incomplete reply must fall through to the next model, not fail."""
        provider = mock_provider_cls.return_value
        provider.generate_json.side_effect = [
            ({"reply": ""}, "{}"),  # first model: valid JSON, missing keys
            (dict(VALID_AGENT_OUTPUT), "{}"),  # second model: good answer
        ]
        result = run_sales_agent(self.conversation, "سلام")
        self.assertEqual(result["reply"], VALID_AGENT_OUTPUT["reply"])
        statuses = list(AIRequest.objects.order_by("id").values_list("status", flat=True))
        self.assertEqual(
            statuses[:2],
            [AIRequest.Status.VALIDATION_FAILED, AIRequest.Status.OK],
        )


class PaymentAndTicketAgentTests(APITestCase):
    """Grounding of the new REQUEST_PAYMENT / CREATE_TICKET actions."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش اسپرت", price=Decimal("1250000"), stock_quantity=5
        )
        customer = Customer.objects.create(store=self.store, name="مشتری")
        self.conversation = Conversation.objects.create(store=self.store, customer=customer)

    def _mock_provider(self, mock_provider_cls, output):
        provider = mock_provider_cls.return_value
        provider.generate_json.return_value = (dict(output), "{}")
        return provider

    def _make_order(self):
        order = Order.objects.create(
            store=self.store,
            customer=self.conversation.customer,
            conversation=self.conversation,
            total=Decimal("1250000"),
        )
        OrderItem.objects.create(
            order=order, product=self.product, quantity=1, unit_price=self.product.price
        )
        return order

    @patch("apps.customers.agent.text_provider")
    def test_request_payment_moves_order_to_awaiting_receipt(self, mock_provider_cls):
        self.store.profile.payment_info = "کارت 6037-XXXX به نام آپ‌مارکت"
        self.store.profile.save()
        order = self._make_order()
        self._mock_provider(
            mock_provider_cls, dict(VALID_AGENT_OUTPUT, action="REQUEST_PAYMENT")
        )
        result = run_sales_agent(self.conversation, "می‌خوام پرداخت کنم")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.AWAITING_RECEIPT)
        self.assertEqual(result["payment_request"]["order_id"], order.id)
        self.assertIn("6037", result["payment_request"]["payment_info"])

    @patch("apps.customers.agent.text_provider")
    def test_request_payment_without_payment_info_escalates(self, mock_provider_cls):
        self._make_order()
        self._mock_provider(
            mock_provider_cls, dict(VALID_AGENT_OUTPUT, action="REQUEST_PAYMENT")
        )
        result = run_sales_agent(self.conversation, "می‌خوام پرداخت کنم")
        self.assertEqual(result["action"], "ESCALATE")
        self.assertTrue(result["needs_human"])
        self.assertIsNone(result["payment_request"])

    @patch("apps.customers.agent.text_provider")
    def test_request_payment_without_order_degrades(self, mock_provider_cls):
        self.store.profile.payment_info = "کارت"
        self.store.profile.save()
        self._mock_provider(
            mock_provider_cls, dict(VALID_AGENT_OUTPUT, action="REQUEST_PAYMENT")
        )
        result = run_sales_agent(self.conversation, "پرداخت")
        self.assertEqual(result["action"], "ANSWER")
        self.assertIsNotNone(result["order_error"])

    @patch("apps.customers.agent.text_provider")
    def test_create_ticket_creates_row(self, mock_provider_cls):
        self._mock_provider(
            mock_provider_cls,
            dict(
                VALID_AGENT_OUTPUT,
                action="CREATE_TICKET",
                ticket={
                    "subject": "کفش پاره رسیده",
                    "description": "مشتری عصبانی است",
                    "urgent": True,
                },
            ),
        )
        result = run_sales_agent(self.conversation, "کفشی که فرستادید پاره است!")
        ticket = result["ticket"]
        self.assertIsInstance(ticket, SupportTicket)
        self.assertEqual(ticket.priority, SupportTicket.Priority.URGENT)
        self.assertEqual(ticket.conversation, self.conversation)
        self.assertEqual(SupportTicket.objects.count(), 1)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="upmarket-receipts-test-"))
class ReceiptAndOrderDecisionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=Decimal("100"), stock_quantity=5
        )
        customer = Customer.objects.create(store=self.store, name="مشتری")
        self.conversation = Conversation.objects.create(store=self.store, customer=customer)
        self.order = Order.objects.create(
            store=self.store,
            customer=customer,
            conversation=self.conversation,
            total=Decimal("100"),
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

    def _upload_receipt(self):
        return self.client.post(
            f"/api/v1/orders/{self.order.id}/receipt/",
            {"image": make_test_image(), "note": "کارت به کارت شد"},
            format="multipart",
        )

    def test_receipt_upload_moves_order_and_notifies(self):
        resp = self._upload_receipt()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_APPROVAL)
        receipt = self.order.receipts.get()
        self.assertEqual(receipt.status, PaymentReceipt.Status.PENDING)
        notification = Notification.objects.get(type=Notification.Type.RECEIPT)
        self.assertIn(str(self.order.id), notification.title)

    def test_receipt_rejected_for_cancelled_order(self):
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        resp = self._upload_receipt()
        self.assertEqual(resp.status_code, 400)

    def test_receipt_requires_valid_image(self):
        fake = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        resp = self.client.post(
            f"/api/v1/orders/{self.order.id}/receipt/", {"image": fake}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)

    def test_confirm_approves_receipt_and_order(self):
        self._upload_receipt()
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/confirm/", {"note": "اوکی"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        receipt = self.order.receipts.get()
        self.assertEqual(receipt.status, PaymentReceipt.Status.APPROVED)
        self.assertIsNotNone(receipt.reviewed_at)

    def test_reject_receipt_returns_to_awaiting_receipt(self):
        self._upload_receipt()
        resp = self.client.post(
            f"/api/v1/orders/{self.order.id}/reject/", {"note": "مبلغ اشتباه است"}
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_RECEIPT)
        receipt = self.order.receipts.get()
        self.assertEqual(receipt.status, PaymentReceipt.Status.REJECTED)
        self.assertIn("اشتباه", receipt.review_note)

    def test_confirmed_order_cannot_be_cancelled(self):
        self.order.status = Order.Status.CONFIRMED
        self.order.save()
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/cancel/")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_draft_order(self):
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/cancel/")
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)

    def test_foreign_order_404(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        self.client.force_authenticate(user=bob)
        resp = self.client.post(f"/api/v1/orders/{self.order.id}/confirm/")
        self.assertEqual(resp.status_code, 404)


class NotificationAndTicketAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.client.force_authenticate(user=self.user)

    @patch("apps.customers.turn.run_sales_agent")
    def test_escalation_creates_notification(self, mock_agent):
        mock_agent.return_value = make_agent_result(action="ESCALATE", needs_human=True)
        self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "شکایت دارم"}, format="json"
        )
        self.assertTrue(
            Notification.objects.filter(
                store=self.store, type=Notification.Type.ESCALATION
            ).exists()
        )

    @patch("apps.customers.turn.run_sales_agent")
    def test_ai_error_creates_notification(self, mock_agent):
        from services.ai.ollama import OllamaError

        mock_agent.side_effect = OllamaError("connection refused")
        resp = self.client.post(
            f"/api/v1/stores/{self.store.id}/chat/", {"message": "سلام"}, format="json"
        )
        self.assertEqual(resp.status_code, 503)
        self.assertTrue(
            Notification.objects.filter(
                store=self.store, type=Notification.Type.AI_ERROR
            ).exists()
        )

    def test_notification_list_read_and_tenancy(self):
        n1 = Notification.objects.create(
            store=self.store, type=Notification.Type.ORDER, title="سفارش جدید"
        )
        Notification.objects.create(
            store=self.store, type=Notification.Type.TICKET, title="تیکت"
        )
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        Notification.objects.create(
            store=bob_store, type=Notification.Type.ORDER, title="سفارش باب"
        )

        resp = self.client.get("/api/v1/notifications/?unread=true")
        self.assertEqual(resp.data["count"], 2)  # bob's is invisible
        self.assertEqual(resp.data["unread_count"], 2)

        resp = self.client.post(f"/api/v1/notifications/{n1.id}/read/")
        self.assertEqual(resp.data["marked_read"], 1)
        resp = self.client.get("/api/v1/notifications/?unread=true")
        self.assertEqual(resp.data["count"], 1)

        resp = self.client.post("/api/v1/notifications/read-all/")
        self.assertEqual(resp.data["marked_read"], 1)
        self.assertEqual(
            Notification.objects.filter(store=self.store, is_read=False).count(), 0
        )

    def test_ticket_list_and_resolve(self):
        ticket = SupportTicket.objects.create(store=self.store, subject="مشکل ارسال")
        resp = self.client.get(f"/api/v1/stores/{self.store.id}/tickets/?status=open")
        self.assertEqual(resp.data["count"], 1)
        resp = self.client.post(
            f"/api/v1/tickets/{ticket.id}/resolve/", {"note": "با مشتری تماس گرفتم"}
        )
        self.assertEqual(resp.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, SupportTicket.Status.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)
