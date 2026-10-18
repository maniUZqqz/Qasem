from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from . import services
from .models import ComputeJob, ComputeNode, ComputeNodeLog, ComputeSettings, new_token


@admin.register(ComputeNode)
class ComputeNodeAdmin(admin.ModelAdmin):
    name_en = "Compute nodes"
    description = (
        "کامپیوترهای گرافیکی (بی‌IP ثابت) که با توکنِ خودشان به سایت وصل می‌شوند و کارِ تصویر/ویدیو/صدا "
        "می‌گیرند. توکن را از پنل («سرورهای پردازش» ⇐ فایلِ راه‌اندازی) به سرور می‌دهید."
    )
    list_display = ("name", "online_badge", "enabled", "capability_list", "jobs_done", "last_seen")
    list_filter = ("enabled",)
    search_fields = ("name", "notes")
    readonly_fields = ("token", "capabilities", "stats", "last_seen", "jobs_done", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "enabled", "notes", "token")}),
        ("گزارشِ خودِ سرور", {"fields": ("capabilities", "stats", "last_seen", "jobs_done"), "classes": ("collapse",)}),
        ("زمان‌ها", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    actions = ("rotate_token", "enable_nodes", "disable_nodes")

    @admin.display(description="وضعیت")
    def online_badge(self, obj):
        if not obj.enabled:
            return format_html('<span style="color:#888">غیرفعال</span>')
        if obj.online:
            return format_html('<span style="color:#0a0">● آنلاین</span>')
        return format_html('<span style="color:#c00">● خاموش</span>')

    @admin.display(description="توانایی‌ها")
    def capability_list(self, obj):
        skip = {"hostname", "version", "agent", "platform", "comfy_nodes", "gpu", "slots", "ollama_models", "comfy_profiles"}
        caps = [k for k, v in (obj.capabilities or {}).items() if v is True and k not in skip]
        gpu = (obj.capabilities or {}).get("gpu")
        text = "، ".join(caps) or "—"
        return f"{text} ({gpu})" if gpu else text

    @admin.action(description="توکنِ تازه بساز (سرور باید با فایلِ راه‌اندازیِ جدید اجرا شود)")
    def rotate_token(self, request, queryset):
        for node in queryset:
            node.token = new_token()
            node.save(update_fields=["token"])
        self.message_user(request, f"{queryset.count()} توکن عوض شد.", messages.SUCCESS)

    @admin.action(description="فعال کن")
    def enable_nodes(self, request, queryset):
        queryset.update(enabled=True)

    @admin.action(description="غیرفعال کن (دیگر کار نمی‌گیرد)")
    def disable_nodes(self, request, queryset):
        queryset.update(enabled=False)


@admin.register(ComputeJob)
class ComputeJobAdmin(admin.ModelAdmin):
    name_en = "Compute jobs"
    description = (
        "کارهایی که به سرورهای پردازش سپرده شده‌اند (گرافِ ComfyUI، پروفایلِ FLUX/Wan، ویرایشِ عکس/ویدیو، صدا، متن). "
        "هر کار فقط به یک سرور می‌رسد؛ درخواستِ یکسان (همان پارامترها و فایل‌ها) تا ۷۲ ساعت دوباره ساخته نمی‌شود."
    )
    list_display = ("short_uid", "kind", "state", "progress_pct", "node", "origin", "attempts", "created_at", "finished_at")
    list_filter = ("state", "kind", "origin", "node")
    search_fields = ("uid", "kind", "origin", "message", "error")
    date_hierarchy = "created_at"
    readonly_fields = ("uid", "request_hash", "result", "inputs", "payload", "claimed_at", "heartbeat_at", "finished_at",
                       "attempts", "progress", "message", "error", "created_at", "updated_at", "dedupe_of")
    fieldsets = (
        (None, {"fields": ("uid", "kind", "state", "node", "node_wanted", "priority", "origin", "store")}),
        ("پیشرفت", {"fields": ("progress", "message", "error", "attempts", "max_attempts", "cancel_requested")}),
        ("داده", {"fields": ("payload", "inputs", "result", "request_hash", "dedupe_of"), "classes": ("collapse",)}),
        ("مهلت و زمان‌ها", {"fields": ("timeout_s", "lease_s", "claimed_at", "heartbeat_at", "finished_at", "created_at",
                                       "updated_at"), "classes": ("collapse",)}),
    )
    actions = ("cancel_jobs", "requeue_jobs")

    @admin.display(description="کار", ordering="uid")
    def short_uid(self, obj):
        return str(obj.uid)[:8]

    @admin.display(description="پیشرفت", ordering="progress")
    def progress_pct(self, obj):
        return f"{int(obj.progress * 100)}٪"

    @admin.action(description="لغو کن")
    def cancel_jobs(self, request, queryset):
        n = 0
        for job in queryset:
            if not job.final:
                services.cancel(job)
                n += 1
        self.message_user(request, f"{n} کار لغو شد.", messages.SUCCESS)

    @admin.action(description="دوباره در صف بگذار (برای کارِ ناموفق)")
    def requeue_jobs(self, request, queryset):
        n = 0
        for job in queryset.filter(state__in=["FAILED", "CANCELLED"]):
            job.state = ComputeJob.State.QUEUED
            job.node = None
            job.attempts = 0
            job.error = ""
            job.cancel_requested = False
            job.finished_at = None
            job.claimed_at = None
            job.message = "دوباره در صف (از ادمین)"
            job.save()
            n += 1
        self.message_user(request, f"{n} کار دوباره در صف رفت.", messages.SUCCESS)

    def has_add_permission(self, request):
        return False  # کارها از پنل/برنامه ساخته می‌شوند، نه با دست


@admin.register(ComputeNodeLog)
class ComputeNodeLogAdmin(admin.ModelAdmin):
    name_en = "Compute node logs"
    description = "خطاها و هشدارهایی که خودِ سرورهای پردازش به سایت فرستاده‌اند (۵۰۰ خطِ آخرِ هر سرور)."
    list_display = ("created_at", "node", "level", "short_message")
    list_filter = ("node", "level")
    search_fields = ("message",)
    readonly_fields = ("node", "level", "message", "logged_at", "created_at")

    @admin.display(description="پیام")
    def short_message(self, obj):
        return obj.message[:140]

    def has_add_permission(self, request):
        return False


@admin.register(ComputeSettings)
class ComputeSettingsAdmin(admin.ModelAdmin):
    name_en = "Compute routing"
    description = "تصویر/ویدیو روی کدام سرورِ پردازش ساخته شود (خالی = هر سرورِ ComfyUI‌دار). از پنل هم عوض می‌شود."
    list_display = ("__str__", "image_video_node", "updated_at")

    def has_add_permission(self, request):
        return not ComputeSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
