from django.contrib import admin
from django.utils import timezone

from .calls import CallConsent, Recording
from .outreach import Prospect
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


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ["role", "text", "intent", "grounding", "created_at"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    name_en = "Conversations"
    description = (
        "گفتگوهای چت فروش. هر گفتگو وضعیتی دارد: دست هوش مصنوعی است، دست آدم، "
        "یا بسته شده. وقتی ایجنت کاری از دستش برنمی‌آید، همین‌جا به آدم ارجاع می‌دهد."
    )
    list_display = ["id", "store", "customer", "state", "updated_at"]
    list_filter = ["state"]
    inlines = [MessageInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    name_en = "Customers"
    description = (
        "مشتری‌های نهاییِ هر فروشگاه — کسانی که در چت پیام داده‌اند یا سفارش ثبت "
        "کرده‌اند. این‌ها کاربران پنل نیستند."
    )
    list_display = ["id", "name", "store", "channel", "created_at"]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class PaymentReceiptInline(admin.TabularInline):
    model = PaymentReceipt
    extra = 0
    readonly_fields = ["image", "note", "status", "review_note", "reviewed_at", "created_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    name_en = "Orders"
    description = (
        "سفارش‌ها. فقط از داده‌ی واقعی ساخته می‌شوند، نه از ادعای هوش مصنوعی. چرخه: "
        "پیش‌نویس ← منتظر رسید ← منتظر تأیید ← تأییدشده."
    )
    list_display = ["id", "store", "customer", "status", "total", "created_at"]
    list_filter = ["status", "stock_state"]
    readonly_fields = ["confirmed_at", "stock_state", "reserved_until"]
    inlines = [OrderItemInline, PaymentReceiptInline]

    def save_model(self, request, obj, form, change):
        """Keep the warehouse honest when the status is changed here.

        The panel goes through `OrderDecisionView`, but an owner who flips the
        status in this form would otherwise confirm a sale that never left the
        shelf. Same helpers, same guards — `stock.apply` and `stock.release`
        refuse to run twice.
        """
        from . import stock

        if obj.status == Order.Status.CONFIRMED and obj.confirmed_at is None:
            obj.confirmed_at = timezone.now()
        super().save_model(request, obj, form, change)
        if obj.status == Order.Status.CONFIRMED:
            stock.apply(obj)
        elif obj.status == Order.Status.CANCELLED:
            stock.release(obj)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    name_en = "Support tickets"
    description = (
        "شکایت یا مشکلی که پیگیری می‌شود؛ معمولاً وقتی ساخته می‌شود که ایجنت فروش "
        "نتوانسته خودش حلش کند."
    )
    list_display = ["id", "store", "subject", "status", "priority", "created_at"]
    list_filter = ["status", "priority"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    name_en = "Notifications"
    description = (
        "اعلان‌های داخل پنل برای صاحب فروشگاه — هر وقت هوش مصنوعی به آدم نیاز پیدا کند: "
        "ارجاع، بررسی رسید، تأیید سفارش، یا شکست یک کار."
    )
    list_display = ["id", "store", "type", "title", "is_read", "created_at"]
    list_filter = ["type", "is_read"]


# ---------------------------------------------------------------------------
#  صفحه ۷ — تماس‌ها. اینجا بودنشان برای پشتیبانی است: «چرا فایل ذخیره نشد؟»
#  را باید بشود بدون پرسیدن از صاحب فروشگاه جواب داد.
# ---------------------------------------------------------------------------


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    name_en = "Prospects"
    description = (
        "کسب‌وکارهایی که این فروشگاه می‌خواهد به آن‌ها بفروشد، و اینکه کار به کجا "
        "رسیده."
    )
    list_display = ["company", "person", "stage", "next_action_at", "is_due"]
    list_filter = ["stage", "store"]
    search_fields = ["company", "person", "phone", "notes"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="سررسید گذشته", boolean=True)
    def is_due(self, obj):
        return obj.is_due


@admin.register(CallConsent)
class CallConsentAdmin(admin.ModelAdmin):
    name_en = "Call consent"
    description = (
        "اجازه‌ی ضبط تماس، ثبت‌شده. یک ردیف به ازای هر سرنخ. «چطور گرفته شد» متن آزاد و "
        "اجباری است، چون جواب صادقانه‌اش در هر مورد فرق می‌کند."
    )
    list_display = ["prospect", "granted", "how", "obtained_at", "revoked_at"]
    list_filter = ["granted", "how"]
    search_fields = ["prospect__company", "obtained_how"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Recording)
class RecordingAdmin(admin.ModelAdmin):
    name_en = "Call recordings"
    description = (
        "تماس‌های ضبط‌شده و آنچه از دلشان درآمده."
    )
    list_display = ["prospect", "happened_at", "seconds", "status", "error"]
    list_filter = ["status"]
    search_fields = ["prospect__company", "transcript", "summary"]
    readonly_fields = [
        "transcript", "summary", "objections", "commitments",
        "suggested_next", "error", "created_at", "updated_at",
    ]

    def has_add_permission(self, request):
        # Adding one here would skip nothing — `save` still checks consent —
        # but an admin form for uploading somebody's call recording is not a
        # thing this product should make convenient.
        return False
