"""Admin for AI providers — the one screen where local ↔ API is switched."""
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from services.ai import factory, providers

from .models import ModelProvider, StoreAIPolicy


@admin.register(ModelProvider)
class ModelProviderAdmin(admin.ModelAdmin):
    name_en = "AI providers"
    description = (
        "هر توانایی هوش مصنوعی از کجا سرو می‌شود — کارت گرافیک خودمان یا API کسی دیگر. "
        "عوض کردنش تصمیم مدیر است، نه تغییر کد: قابلیت را انتخاب کن، آدرس و کلید را "
        "بگذار."
    )
    list_display = [
        "capability", "name", "kind", "model_name",
        "where", "priority", "is_active", "health_badge",
    ]
    list_filter = ["capability", "kind", "is_active", "is_approved", "data_location"]
    list_editable = ["priority", "is_active"]
    search_fields = ["name", "model_name", "base_url"]
    actions = ["test_connection", "activate", "deactivate"]
    readonly_fields = ["checked_at", "is_healthy", "last_error", "created_at", "updated_at"]

    fieldsets = [
        ("چه کاری", {
            "fields": ["capability", "kind", "name", "is_active", "priority"],
            "description": "«اولویت» کمتر یعنی زودتر امتحان می‌شود. "
                           "می‌توانی سرور خودت را اول بگذاری و API را پشتش، "
                           "تا وقتی GPU مشغول یا خاموش بود کار نخوابد.",
        }),
        ("اتصال", {
            "fields": ["base_url", "api_key", "model_name", "timeout_s"],
            "description": "برای Ollama و ComfyUI اگر آدرس را خالی بگذاری، "
                           "مقدار .env استفاده می‌شود و کلید API لازم نیست.",
        }),
        ("تنظیمات پیشرفته", {
            "fields": ["options"],
            "classes": ["collapse"],
            "description": "JSON. برای سرویس‌های تصویر و ویدیو مسیر خروجی و "
                           "حالت sync/async اینجا تنظیم می‌شود.",
        }),
        ("حریم داده", {
            "fields": [
                "is_approved", "data_location", "allowed_data",
                "data_retention", "privacy_policy_url",
            ],
            "description": "این بخش تزئینی نیست: فروشگاهی که «فقط سرویس‌های تأییدشده» "
                           "را انتخاب کرده، سرویس بدون تیکِ «تأییدشده» را اصلاً "
                           "نمی‌بیند و کارش با پیام روشن fail می‌شود. "
                           "«مجاز برای کدام داده» را خالی بگذاری، سرویس بیرونی "
                           "فقط محصول و برند می‌گیرد و پیام مشتری هرگز نمی‌رود.",
        }),
        ("سلامت", {"fields": ["checked_at", "is_healthy", "last_error"]}),
    ]

    @admin.display(description="اجرا روی")
    def where(self, obj):
        return "🖥️ سخت‌افزار ما" if obj.is_local else "☁️ سرویس بیرونی"

    @admin.display(description="وضعیت")
    def health_badge(self, obj):
        if obj.is_healthy is None:
            return format_html('<span style="color:#888">آزمایش نشده</span>')
        if obj.is_healthy:
            return format_html('<span style="color:#0a0">● سالم</span>')
        return format_html(
            '<span style="color:#c00" title="{}">● خطا</span>', obj.last_error[:200]
        )

    @admin.action(description="تست اتصال")
    def test_connection(self, request, queryset):
        for row in queryset:
            resolved = providers._from_row(row)
            ok, detail = factory.health(resolved)
            row.is_healthy = ok
            row.last_error = "" if ok else detail
            row.checked_at = timezone.now()
            row.save(update_fields=["is_healthy", "last_error", "checked_at"])
            self.message_user(
                request, f"{row.name}: {detail}",
                messages.SUCCESS if ok else messages.ERROR,
            )

    @admin.action(description="فعال کردن")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} مورد فعال شد.")

    @admin.action(description="غیرفعال کردن")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} مورد غیرفعال شد.")


@admin.register(StoreAIPolicy)
class StoreAIPolicyAdmin(admin.ModelAdmin):
    name_en = "AI data policy"
    description = (
        "چه مقدار از داده‌ی یک فروشگاه اجازه دارد از سرور ما بیرون برود. بدون این، یک "
        "تنظیم سراسری می‌توانست پیام خصوصی مشتریانِ همه‌ی فروشگاه‌ها را به یک سرویس "
        "خارجی بفرستد."
    )
    """Per-store answer to "may this shop's data leave our servers?".

    Kept as its own screen rather than an inline on Store, because this is the
    one setting an operator must be able to audit across every shop at once —
    "who is on Local Only" has to be a single list, not thirty clicks.
    """

    list_display = ["store", "mode", "allow_customer_data_external", "acknowledged_at"]
    list_filter = ["mode", "allow_customer_data_external"]
    search_fields = ["store__name", "store__slug"]
    autocomplete_fields = ["store"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        ("فروشگاه", {"fields": ["store"]}),
        ("سیاست", {
            "fields": ["mode", "allow_customer_data_external"],
            "description": "«فقط لوکال» یعنی اگر مدل محلی نبود، کار fail می‌شود — "
                           "نه اینکه بی‌سروصدا به API بیرونی برود. "
                           "صداگذاری هم بیرونی است، پس در این حالت کار نمی‌کند.",
        }),
        ("رضایت", {
            "fields": ["acknowledged_at", "acknowledged_by"],
            "description": "چه کسی و کِی این سیاست را تأیید کرده.",
        }),
        ("زمان", {"fields": ["created_at", "updated_at"], "classes": ["collapse"]}),
    ]
