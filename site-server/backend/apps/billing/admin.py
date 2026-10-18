from django.contrib import admin
from django.utils.html import format_html

from . import services
from .models import Plan, Subscription, Usage
from .payment_models import BillingEvent, Payment
from .payment_services import confirm_manual
from .payments import PaymentError


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    name_en = "Plans"
    description = (
        "پلن‌های فروختنی و سهمیه‌ی هرکدام. با دیتا/1-داده/data.json هم‌خوان نگه داشته "
        "می‌شود."
    )
    list_display = ["name", "slug", "price_toman", "video_seconds", "images",
                    "captions", "is_public", "is_trial", "sort_order"]
    list_editable = ["price_toman", "sort_order", "is_public"]
    prepopulated_fields = {"slug": ["name"]}
    fieldsets = [
        ("معرفی", {"fields": ["name", "slug", "description", "price_toman",
                              "sort_order", "is_public"]}),
        ("سهمیه‌ی ماهانه", {
            "fields": ["video_seconds", "images", "captions"],
            "description": "این اعداد باید با دیتا/1-داده/data.json یکی بمانند.",
        }),
        ("محدودیت‌ها", {"fields": ["max_products", "max_stores",
                                   "allows_publishing", "allows_sales_agent"]}),
        ("دوره آزمایشی", {"fields": ["is_trial", "trial_days"]}),
    ]


class UsageInline(admin.TabularInline):
    model = Usage
    extra = 0
    fields = ["metric", "quantity", "state", "external", "detail", "created_at"]
    readonly_fields = fields
    can_delete = False
    max_num = 0
    ordering = ["-created_at"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    name_en = "Subscriptions"
    description = (
        "هر فروشگاه الان روی چه پلنی است و دوره‌اش کی تمام می‌شود. یک ردیف به ازای هر "
        "فروشگاه."
    )
    list_display = ["store", "plan", "status", "usage_bars", "days_left", "period_end"]
    list_filter = ["status", "plan"]
    search_fields = ["store__name"]
    autocomplete_fields = ["store"]
    inlines = [UsageInline]
    actions = ["roll_period", "mark_active"]
    fieldsets = [
        (None, {"fields": ["store", "plan", "status", "note"]}),
        ("دوره", {"fields": ["period_start", "period_end", "cancel_at_period_end"]}),
        ("سهمیه‌ی اضافی دستی", {
            "fields": ["bonus_video_seconds", "bonus_images", "bonus_captions"],
            "description": "برای جبران یک رندر خراب، بدون تغییر پلن.",
        }),
    ]

    @admin.display(description="مصرف این دوره")
    def usage_bars(self, obj):
        parts = []
        for row in services.snapshot(obj.store)["metrics"]:
            color = "#c00" if row["percent"] >= 90 else "#e8a" if row["percent"] >= 70 else "#0a0"
            parts.append(
                f'<div style="font-size:11px">{row["label"]}: '
                f'<b style="color:{color}">{row["used"]}</b>/{row["allowed"]}</div>'
            )
        return format_html("".join(parts) or "—")

    @admin.display(description="روز مانده")
    def days_left(self, obj):
        return obj.days_left

    @admin.action(description="شروع دوره‌ی بعد")
    def roll_period(self, request, queryset):
        for sub in queryset:
            sub.roll_period()
        self.message_user(request, f"{queryset.count()} اشتراک به دوره‌ی بعد رفت.")

    @admin.action(description="فعال کردن")
    def mark_active(self, request, queryset):
        n = queryset.update(status=Subscription.Status.ACTIVE)
        self.message_user(request, f"{n} اشتراک فعال شد.")


@admin.register(Usage)
class UsageAdmin(admin.ModelAdmin):
    name_en = "Usage"
    description = (
        "دفتر مصرف سهمیه: هر کپشن، تصویر و ویدیو یک ردیف. ردیف‌ها بعداً دست‌کاری "
        "نمی‌شوند، پس جمعِ ردیف‌های یک دوره *همان* مصرف آن دوره است و قابل حسابرسی."
    )
    list_display = ["created_at", "store", "metric", "quantity", "state", "external", "detail"]
    list_filter = ["metric", "state", "external"]
    search_fields = ["store__name", "detail"]
    readonly_fields = [f.name for f in Usage._meta.fields]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    name_en = "Payments"
    description = (
        "هر تلاش برای پرداخت یک پلن، موفق یا ناموفق."
    )
    """Invoices, and the one place a bank transfer gets confirmed.

    Payments are never created here — they come from the site. The admin exists
    to answer "did this person pay" and to confirm the transfers a gateway
    cannot see.
    """

    list_display = (
        "invoice_number", "created_at", "store", "plan",
        "amount_toman", "provider", "status",
    )
    list_filter = ("status", "provider", "created_at")
    search_fields = ("invoice_number", "reference", "token", "store__name")
    date_hierarchy = "created_at"
    readonly_fields = (
        "invoice_number", "store", "plan", "amount_toman", "provider", "token",
        "reference", "paid_at", "refunded_at", "confirmed_by", "subscription",
        "gateway_response", "error", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # An invoice is a financial record. Correct it with a refund, not a
        # delete.
        return False

    @admin.action(description="تأیید واریز بانکی (فقط پرداخت دستی)")
    def confirm_transfer(self, request, queryset):
        done = failed = 0
        for payment in queryset:
            try:
                confirm_manual(payment, actor=request.user)
                done += 1
            except PaymentError as exc:
                failed += 1
                self.message_user(request, f"{payment.invoice_number}: {exc}", level="error")
        if done:
            self.message_user(request, f"{done} واریز تأیید و اشتراک فعال شد.")

    actions = ["confirm_transfer"]


@admin.register(BillingEvent)
class BillingEventAdmin(admin.ModelAdmin):
    name_en = "Billing events"
    description = (
        "تاریخچه‌ی تغییرات اشتراک، فقط-افزودنی. وقتی مشتری می‌گوید «من هیچ‌وقت ارتقا "
        "ندادم»، جوابِ مفید یک ردیف است که می‌گوید کِی، توسط چه کسی و چرا."
    )
    """Append-only history. Read here, never written here."""

    list_display = ("created_at", "store", "kind", "summary", "actor")
    list_filter = ("kind", "created_at")
    search_fields = ("summary", "store__name")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in BillingEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
