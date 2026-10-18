from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from apps.ai.models import AIRequest
from apps.common.models import TimeStampedModel
from apps.products.models import Product, ProductVariant
from apps.stores.models import Store


class Customer(TimeStampedModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    external_id = models.CharField(max_length=100, blank=True)
    channel = models.CharField(max_length=32, default="web")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "مشتری"
        verbose_name_plural = "مشتریان"

    def __str__(self):
        return self.name or f"Customer #{self.id}"


class Conversation(TimeStampedModel):
    class State(models.TextChoices):
        AI = "AI", "دست هوش مصنوعی"
        HUMAN = "HUMAN", "دست آدم"
        ESCALATED = "ESCALATED", "ارجاع‌شده به آدم"
        RESOLVED = "RESOLVED", "بسته‌شده"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="conversations")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="conversations")
    state = models.CharField(max_length=12, choices=State.choices, default=State.AI)

    # ---- unified inbox (§9.7) --------------------------------------------
    #: Which channel this thread lives on. A plain string, not a foreign key:
    #: the adapters in services.publishing.channels own the behaviour, and the
    #: inbox should not need a migration to gain a channel.
    channel = models.CharField(max_length=16, default="WEB")
    #: The thread's id on that platform, so a reply reaches the right person.
    external_id = models.CharField(max_length=120, blank=True)
    #: Who on the shop's team owns this conversation. Null means nobody has
    #: picked it up — which is a real state worth seeing in a shared inbox,
    #: not a gap to be filled with the owner by default.
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_conversations",
    )
    tags = models.JSONField(default=list, blank=True)
    #: When the customer last wrote. Sorted on, because "waiting longest" is
    #: the only ordering an inbox can justify: `updated_at` moves when *we*
    #: reply, which pushes the people we already answered to the top.
    last_customer_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "گفتگو"
        verbose_name_plural = "گفتگوها"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["store", "state", "-last_customer_at"]),
            models.Index(fields=["store", "channel"]),
        ]

    @property
    def waiting_minutes(self) -> int | None:
        """How long the customer has been waiting for a human.

        None while the AI is handling it — that is not waiting, that is working.
        """
        if self.state not in (self.State.HUMAN, self.State.ESCALATED):
            return None
        if not self.last_customer_at:
            return None
        from django.utils import timezone

        return int((timezone.now() - self.last_customer_at).total_seconds() // 60)

    def __str__(self):
        return f"Conversation #{self.id} ({self.store.name})"


class Message(TimeStampedModel):
    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        AI = "AI", "AI agent"
        HUMAN = "HUMAN", "Human agent"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    text = models.TextField()
    intent = models.CharField(max_length=32, blank=True)
    #: The platform's own id for this message, when it came from one.
    #:
    #: A real column rather than a key inside `grounding`, because this is what
    #: makes a retried webhook delivery idempotent — and `grounding__contains`
    #: is a JSON lookup SQLite does not support, so the check would have worked
    #: in production and raised on the machine it was written on. Same trap
    #: `apps.common.utils.with_tag` exists for.
    external_id = models.CharField(max_length=120, blank=True, db_index=True)
    grounding = models.JSONField(default=dict, blank=True)
    ai_request = models.ForeignKey(
        AIRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # Blank is the common case (panel chat, AI replies), so the
            # constraint only covers messages that carry a platform id.
            models.UniqueConstraint(
                fields=["conversation", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_platform_message",
            ),
        ]

    def __str__(self):
        return f"{self.role}: {self.text[:40]}"


class Order(TimeStampedModel):
    """Order foundation. Created ONLY from real database data, never AI claims.

    Lifecycle: DRAFT (AI creates from chat) → AWAITING_RECEIPT (payment info
    shared, customer must send the receipt) → AWAITING_APPROVAL (receipt
    uploaded, human must verify) → CONFIRMED / CANCELLED (human decision).
    Pay-on-delivery skips the receipt through COD, which is a decision the
    owner takes on purpose rather than a gap in the checks.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        AWAITING_RECEIPT = "AWAITING_RECEIPT", "منتظر رسید پرداخت"
        AWAITING_APPROVAL = "AWAITING_APPROVAL", "منتظر تأیید شما"
        #: Pay on delivery. A deliberate "no receipt is coming" — an order
        #: could always be confirmed without one, which made "پرداخت تأیید شد"
        #: mean nothing; now that path has its own name and its own button.
        CASH_ON_DELIVERY = "COD", "پرداخت در محل"
        CONFIRMED = "CONFIRMED", "تأییدشده"
        CANCELLED = "CANCELLED", "لغوشده"

    class StockState(models.TextChoices):
        """Where this order stands with the warehouse (apps/customers/stock.py)."""

        NONE = "NONE", "بدون اثر روی موجودی"
        RESERVED = "RESERVED", "موجودی رزرو شده"
        APPLIED = "APPLIED", "از موجودی کم شد"
        RELEASED = "RELEASED", "رزرو آزاد شد"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="orders")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    #: When the human confirmed it. Revenue belongs to the day the money was
    #: accepted, not the day the chat happened — `created_at` put an order
    #: opened on the 1st and paid on the 9th in the wrong month's chart.
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان تأیید")
    stock_state = models.CharField(
        max_length=10, choices=StockState.choices, default=StockState.NONE,
        verbose_name="وضعیت موجودی",
    )
    reserved_until = models.DateTimeField(
        null=True, blank=True, verbose_name="مهلت رزرو",
        help_text="بعد از این زمان، کالای رزروشده دوباره قابل فروش می‌شود.",
    )

    class Meta:
        verbose_name = "سفارش"
        verbose_name_plural = "سفارش‌ها"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        """A confirmed order always has a confirmation date.

        Every sales figure is now grouped by `confirmed_at`, so an order that
        reaches CONFIRMED without one does not appear in any report — it is
        sold and invisible. Rather than trust every present and future path
        (the panel, Django admin, a shell, an import) to remember, the rule
        lives here once.
        """
        if self.status == self.Status.CONFIRMED and self.confirmed_at is None:
            self.confirmed_at = timezone.now()
            fields = kwargs.get("update_fields")
            if fields is not None and "confirmed_at" not in fields:
                kwargs["update_fields"] = [*fields, "confirmed_at"]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.id} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}× {self.product.name}"


class PaymentReceipt(TimeStampedModel):
    """A payment receipt image the customer sends for an order.

    The AI only COLLECTS the receipt; approving it (and the order) is always a
    human decision — the model never confirms payments.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="receipts")
    image = models.ImageField(upload_to="receipts/%Y/%m/")
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    review_note = models.CharField(max_length=300, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Receipt #{self.id} for order #{self.order_id} [{self.status}]"


class SupportTicket(TimeStampedModel):
    """A tracked support issue/complaint, usually opened by the AI agent."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "باز"
        IN_PROGRESS = "IN_PROGRESS", "در حال پیگیری"
        RESOLVED = "RESOLVED", "حل‌شده"

    class Priority(models.TextChoices):
        NORMAL = "NORMAL", "عادی"
        URGENT = "URGENT", "فوری"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="tickets")
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets"
    )
    subject = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.NORMAL)
    resolution_note = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "تیکت پشتیبانی"
        verbose_name_plural = "تیکت‌های پشتیبانی"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Ticket #{self.id} ({self.status}): {self.subject[:40]}"


class Notification(TimeStampedModel):
    """In-app notification for the store owner — fired whenever the AI needs a
    human (escalation, receipt review, order approval, ticket, AI failure)."""

    class Type(models.TextChoices):
        ESCALATION = "ESCALATION", "ارجاع گفتگو"
        ORDER = "ORDER", "سفارش جدید"
        RECEIPT = "RECEIPT", "رسید پرداخت رسید"
        TICKET = "TICKET", "تیکت پشتیبانی"
        AI_ERROR = "AI_ERROR", "شکست هوش مصنوعی"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=16, choices=Type.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    # frontend route the bell links to, e.g. /stores/3/sales
    link = models.CharField(max_length=200, blank=True)
    context = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "اعلان"
        verbose_name_plural = "اعلان‌ها"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "is_read"])]

    def __str__(self):
        return f"[{self.type}] {self.title}"


def notify(store, type, title, body="", link="", context=None):
    """Create an owner notification. Never raises — a notification failure must
    not break the customer-facing flow it accompanies."""
    try:
        return Notification.objects.create(
            store=store, type=type, title=title, body=body, link=link, context=context or {}
        )
    except Exception:  # pragma: no cover - defensive
        import logging

        logging.getLogger(__name__).exception("Failed to create notification for store %s", store)
        return None


# Outbound sales lives in its own module for size; Django only
# discovers models imported from here.
from .outreach import Prospect  # noqa: E402,F401
from .calls import CallConsent, Recording  # noqa: E402,F401
