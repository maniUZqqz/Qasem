from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores.models import Store
from services.ai.gateway import PolicyBlocked
from services.ai.ollama import OllamaError

from . import stock
from .agent import OPEN_ORDER_STATES, open_orders_payload
from .turn import answer
from .models import (
    Conversation,
    Customer,
    Message,
    Notification,
    Order,
    PaymentReceipt,
    SupportTicket,
    notify,
)
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    NotificationSerializer,
    OrderSerializer,
    SupportTicketSerializer,
)
from apps.stores import access


def _owned_store(request, store_id) -> Store:
    return access.get_store(request.user, store_id, access.CONVERSATIONS)


class ChatView(APIView):
    """POST /api/v1/stores/{store_id}/chat/ — one grounded sales-agent turn.

    Body: {"message": "...", "conversation_id"?: int, "customer_name"?: "..."}
    Runs synchronously (an LLM chat turn); returns the AI reply plus any
    validated side effects (order created, escalation).
    """

    def post(self, request, store_id):
        store = _owned_store(request, store_id)
        text = str(request.data.get("message", "") or "").strip()
        if not text:
            return Response(
                {"error": {"code": "empty_message", "message": "Field 'message' is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation_id = request.data.get("conversation_id")
        if conversation_id:
            conversation = get_object_or_404(
                Conversation.objects.filter(store=store), pk=conversation_id
            )
        else:
            customer = Customer.objects.create(
                store=store,
                name=str(request.data.get("customer_name", "") or "مشتری آزمایشی"),
                channel="web-test",
            )
            conversation = Conversation.objects.create(store=store, customer=customer)

        Message.objects.create(
            conversation=conversation, role=Message.Role.CUSTOMER, text=text
        )

        # The inbox sorts by longest-waiting, measured from when the CUSTOMER
        # last wrote. Without this stamp that ordering is meaningless and the
        # person waiting since morning sits below the one we just answered.
        from django.utils import timezone

        conversation.last_customer_at = timezone.now()
        conversation.save(update_fields=["last_customer_at", "updated_at"])
        if conversation.state != Conversation.State.AI:
            conversation.save(update_fields=["updated_at"])
            return Response(
                {
                    "conversation_id": conversation.id,
                    "state": conversation.state,
                    "message": None,
                    "note": "این گفتگو در حالت پاسخ‌گویی انسانی است؛ AI پاسخ نمی‌دهد.",
                }
            )

        try:
            # The recording, the notifications and the escalation live in
            # `turn.answer` so the webhook path cannot drift from this one.
            turn = answer(conversation, text)
            result = turn.result
        except PolicyBlocked as exc:
            # Not an outage: the shop's own data policy forbids the only
            # provider that could answer. Saying "AI unavailable" here would
            # send the owner hunting a fault that does not exist.
            notify(
                store,
                Notification.Type.AI_ERROR,
                "سیاست داده‌ی فروشگاه جلوی پاسخ AI را گرفت",
                body=f"گفتگو #{conversation.id}: {exc}",
                link=f"/stores/{store.id}/settings",
                context={"conversation_id": conversation.id, "policy": True},
            )
            return Response(
                {
                    "error": {
                        "code": "ai_policy_blocked",
                        "message": str(exc),
                    },
                    "conversation_id": conversation.id,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except OllamaError as exc:
            # the one moment the AI can do nothing — tell the owner immediately
            notify(
                store,
                Notification.Type.AI_ERROR,
                "AI پاسخ نداد — مشتری منتظر است",
                body=f"گفتگو #{conversation.id}: {exc}",
                link=f"/stores/{store.id}/chat",
                context={"conversation_id": conversation.id},
            )
            return Response(
                {
                    "error": {
                        "code": "ai_unavailable",
                        "message": f"پاسخ AI در دسترس نیست: {exc}",
                    },
                    "conversation_id": conversation.id,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        ai_message = turn.message

        products = store.products.filter(id__in=result["product_ids"]).prefetch_related("images")
        product_cards = [
            {
                "id": p.id,
                "name": p.name,
                "price": str(p.price),
                "currency": p.currency,
                # Sellable, like the catalogue the agent was given — the card
                # next to the reply must not say 3 left when 3 are promised.
                "stock_quantity": p.available_quantity,
                "image": (
                    request.build_absolute_uri(p.images.first().image.url)
                    if p.images.first()
                    else None
                ),
            }
            for p in products
        ]

        return Response(
            {
                "conversation_id": conversation.id,
                "state": conversation.state,
                "message": MessageSerializer(ai_message).data,
                "action": result["action"],
                "products": product_cards,
                "order": OrderSerializer(result["order"]).data if result["order"] else None,
                "order_error": result["order_error"],
                "payment_request": result.get("payment_request"),
                "ticket": SupportTicketSerializer(result["ticket"]).data
                if result.get("ticket")
                else None,
                # orders of this conversation the customer can still pay for —
                # drives the receipt-upload button in the chat UI
                "open_orders": open_orders_payload(conversation),
            }
        )


class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationSerializer

    def get_queryset(self):
        store = _owned_store(self.request, self.kwargs["store_id"])
        return Conversation.objects.filter(store=store)


class MessageListView(generics.ListAPIView):
    serializer_class = MessageSerializer
    pagination_class = None

    def get_queryset(self):
        conversation = get_object_or_404(
            Conversation.objects.filter(store__in=access.stores_for(self.request.user)), pk=self.kwargs["pk"]
        )
        return conversation.messages.all()[:500]


class HandoffView(APIView):
    """POST /api/v1/conversations/{id}/handoff/ {"state": "HUMAN"|"AI"|"RESOLVED"}"""

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation.objects.filter(store__in=access.stores_for(request.user)), pk=pk
        )
        new_state = str(request.data.get("state", "") or "").upper()
        allowed = {
            Conversation.State.AI,
            Conversation.State.HUMAN,
            Conversation.State.RESOLVED,
        }
        if new_state not in allowed:
            return Response(
                {"error": {"code": "invalid_state", "message": f"state must be one of {sorted(allowed)}"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        conversation.state = new_state
        conversation.save(update_fields=["state", "updated_at"])
        return Response(ConversationSerializer(conversation).data)


class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer

    def get_queryset(self):
        store = _owned_store(self.request, self.kwargs["store_id"])
        qs = Order.objects.filter(store=store).prefetch_related("items__product", "receipts")
        order_status = self.request.query_params.get("status")
        if order_status:
            qs = qs.filter(status=str(order_status).upper())
        return qs


def _owned_order(request, pk) -> Order:
    return get_object_or_404(
        Order.objects.filter(store__in=access.stores_for(request.user)).select_related("store"), pk=pk
    )


class OrderReceiptView(APIView):
    """POST /api/v1/orders/{id}/receipt/ — the customer sends a payment receipt
    image in the chat; the order then waits for HUMAN approval (never AI)."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        order = _owned_order(request, pk)
        if order.status not in {
            Order.Status.DRAFT,
            Order.Status.AWAITING_RECEIPT,
            Order.Status.AWAITING_APPROVAL,
        }:
            return Response(
                {
                    "error": {
                        "code": "invalid_state",
                        "message": f"برای سفارش در وضعیت «{order.status}» رسید پذیرفته نمی‌شود.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        upload = request.FILES.get("image")
        if upload is None:
            return Response(
                {"error": {"code": "missing_file", "message": "Field 'image' (file) is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            return Response(
                {
                    "error": {
                        "code": "file_too_large",
                        "message": f"حداکثر حجم مجاز {settings.MAX_UPLOAD_MB} مگابایت است.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        if (upload.content_type or "") not in allowed_types:
            return Response(
                {"error": {"code": "invalid_type", "message": "فقط تصویر JPEG/PNG/WebP مجاز است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from PIL import Image as PILImage

        try:
            PILImage.open(upload).verify()
            upload.seek(0)
        except Exception:
            return Response(
                {"error": {"code": "invalid_type", "message": "فایل تصویر معتبر نیست."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        receipt = PaymentReceipt.objects.create(
            order=order, image=upload, note=str(request.data.get("note", "") or "")[:300]
        )
        order.status = Order.Status.AWAITING_APPROVAL
        order.save(update_fields=["status", "updated_at"])
        notify(
            order.store,
            Notification.Type.RECEIPT,
            f"رسید پرداخت برای سفارش #{order.id} رسید",
            body=f"مبلغ سفارش: {order.total} — منتظر بررسی و تأیید شماست.",
            link=f"/stores/{order.store_id}/sales",
            context={"order_id": order.id, "receipt_id": receipt.id},
        )
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDecisionView(APIView):
    """Human decision on an order:
    POST /api/v1/orders/{id}/confirm/ — approve latest receipt + CONFIRMED
    POST /api/v1/orders/{id}/reject/  — reject latest receipt → AWAITING_RECEIPT
    POST /api/v1/orders/{id}/cod/     — pay on delivery, no receipt expected
    POST /api/v1/orders/{id}/cancel/  — CANCELLED

    "Confirm" means *the money is in*. It used to be allowed on any order that
    was not already cancelled, so a draft nobody had paid a rial for could be
    booked as revenue with one click — and since that was also the only way to
    close a pay-on-delivery sale, owners had to do it. Both needs are real, so
    they now have separate buttons: `confirm` requires a receipt waiting (or
    an order already marked pay-on-delivery), and `cod` is the deliberate
    "there will be no receipt".
    """

    def post(self, request, pk, decision):
        order = _owned_order(request, pk)
        note = str(request.data.get("note", "") or "")[:300]
        latest_receipt = order.receipts.filter(status=PaymentReceipt.Status.PENDING).first()
        extra_fields: list[str] = []

        if decision == "confirm":
            if order.status == Order.Status.CANCELLED:
                return Response(
                    {"error": {"code": "invalid_state", "message": "سفارش لغوشده قابل تأیید نیست."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if order.status == Order.Status.CONFIRMED:
                return Response(OrderSerializer(order).data)
            if latest_receipt is None and order.status != Order.Status.CASH_ON_DELIVERY:
                return Response(
                    {
                        "error": {
                            "code": "no_receipt",
                            "message": (
                                "رسیدی برای این سفارش نرسیده. تا وقتی مشتری رسید نفرستاده "
                                "تأیید یعنی ثبت پولی که نگرفته‌اید؛ اگر قرار است پول را موقع "
                                "تحویل بگیرید، «پرداخت در محل» را بزنید."
                            ),
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if latest_receipt is not None:
                latest_receipt.status = PaymentReceipt.Status.APPROVED
                latest_receipt.review_note = note
                latest_receipt.reviewed_at = timezone.now()
                latest_receipt.save()
            order.status = Order.Status.CONFIRMED
            order.confirmed_at = timezone.now()
            extra_fields = ["confirmed_at"]
        elif decision == "cod":
            if order.status in (Order.Status.CONFIRMED, Order.Status.CANCELLED):
                return Response(
                    {
                        "error": {
                            "code": "invalid_state",
                            "message": "این سفارش بسته شده و دیگر نمی‌شود نوعش را عوض کرد.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            order.status = Order.Status.CASH_ON_DELIVERY
            # The goods are going out of the door: hold them like a paid one.
            stock.reserve(order)
        elif decision == "reject":
            if latest_receipt is None:
                return Response(
                    {
                        "error": {
                            "code": "no_receipt",
                            "message": "رسید در انتظاری برای رد کردن وجود ندارد.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            latest_receipt.status = PaymentReceipt.Status.REJECTED
            latest_receipt.review_note = note
            latest_receipt.reviewed_at = timezone.now()
            latest_receipt.save()
            order.status = Order.Status.AWAITING_RECEIPT
        elif decision == "cancel":
            if order.status == Order.Status.CONFIRMED:
                return Response(
                    {
                        "error": {
                            "code": "invalid_state",
                            "message": "سفارش تأییدشده را نمی‌توان لغو کرد.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            order.status = Order.Status.CANCELLED
        else:  # pragma: no cover - routed decisions only
            return Response(status=status.HTTP_404_NOT_FOUND)

        order.save(update_fields=["status", "updated_at", *extra_fields])
        # After the status is saved, so a failure here cannot leave the order
        # confirmed in the customer's eyes and unsold in the warehouse's.
        if order.status == Order.Status.CONFIRMED:
            stock.apply(order)
        elif order.status == Order.Status.CANCELLED:
            stock.release(order)
        return Response(OrderSerializer(order).data)


class TicketListView(generics.ListAPIView):
    serializer_class = SupportTicketSerializer

    def get_queryset(self):
        store = _owned_store(self.request, self.kwargs["store_id"])
        qs = SupportTicket.objects.filter(store=store).select_related("customer")
        ticket_status = self.request.query_params.get("status")
        if ticket_status:
            qs = qs.filter(status=str(ticket_status).upper())
        return qs


class TicketResolveView(APIView):
    """POST /api/v1/tickets/{id}/resolve/ {"note"?: "..."}"""

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket.objects.filter(store__in=access.stores_for(request.user)), pk=pk)
        ticket.status = SupportTicket.Status.RESOLVED
        ticket.resolution_note = str(request.data.get("note", "") or "")
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolution_note", "resolved_at", "updated_at"])
        return Response(SupportTicketSerializer(ticket).data)


class NotificationListView(generics.ListAPIView):
    """GET /api/v1/notifications/?store=&unread=true — across the user's stores."""

    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(store__in=access.stores_for(self.request.user)).select_related("store")
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        if str(self.request.query_params.get("unread", "")).lower() in {"1", "true", "yes"}:
            qs = qs.filter(is_read=False)
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["unread_count"] = self.get_queryset().model.objects.filter(
            store__in=access.stores_for(request.user), is_read=False
        ).count()
        return response


class NotificationReadView(APIView):
    """POST /api/v1/notifications/{id}/read/ — or /notifications/read-all/."""

    def post(self, request, pk=None):
        qs = Notification.objects.filter(store__in=access.stores_for(request.user))
        if pk is not None:
            get_object_or_404(qs, pk=pk)
            qs = qs.filter(pk=pk)
        updated = qs.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return Response({"marked_read": updated})
