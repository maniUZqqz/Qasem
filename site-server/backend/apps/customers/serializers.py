from rest_framework import serializers

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


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "phone", "channel", "created_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "text", "intent", "grounding", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "state", "customer", "last_message", "created_at", "updated_at"]

    def get_last_message(self, obj):
        message = obj.messages.order_by("-created_at").first()
        return message.text[:120] if message else ""


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True, default=None)

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "variant", "variant_name", "quantity", "unit_price"]


class PaymentReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentReceipt
        fields = ["id", "image", "note", "status", "review_note", "reviewed_at", "created_at"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer = CustomerSerializer(read_only=True)
    receipts = PaymentReceiptSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "status",
            "total",
            "items",
            "customer",
            "conversation",
            "receipts",
            "confirmed_at",
            "stock_state",
            "reserved_until",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["confirmed_at", "stock_state", "reserved_until"]


class SupportTicketSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "subject",
            "description",
            "status",
            "priority",
            "customer",
            "conversation",
            "resolution_note",
            "resolved_at",
            "created_at",
        ]


class NotificationSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "store",
            "store_name",
            "type",
            "title",
            "body",
            "link",
            "context",
            "is_read",
            "created_at",
        ]
