from django.contrib import admin

from .models import ApprovalRecord, Campaign, MessageTemplate, OutreachItem, OutreachJob, SendAttempt


class ReadOnlyAdmin(admin.ModelAdmin):
    """Rows that record what happened: viewable, never edited from here."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    name_en = "Message templates"
    description = "متنِ پیام‌ها با جاگذارهایی مثل {business_name}. برای کارِ روزمره از صفحهٔ «قالب‌های پیام» در پنل استفاده کنید."
    list_display = ("name", "language", "is_active", "created_at")
    list_filter = ("language", "is_active")
    search_fields = ("name", "body")


@admin.register(Campaign)
class CampaignAdmin(ReadOnlyAdmin):
    name_en = "Outreach campaigns"
    description = "کمپین‌های پیام. فقط‌خواندنی: شروع، توقف و لغو از صفحهٔ «پیام‌رسانی» در پنل انجام می‌شود."
    list_display = ("name", "template", "mode", "status", "started_at", "created_at")
    list_filter = ("mode", "status")


@admin.register(OutreachItem)
class OutreachItemAdmin(ReadOnlyAdmin):
    name_en = "Campaign items"
    description = "یک پیام به یک کسب‌وکار در یک کمپین، با وضعیت و دلیلِ ردّ شدن. فقط‌خواندنی."
    list_display = ("campaign", "lead", "status", "skip_reason", "domain", "updated_at")
    list_filter = ("status", "skip_reason")
    search_fields = ("domain", "rendered_text")
    raw_id_fields = ("campaign", "lead", "approved_record")


@admin.register(ApprovalRecord)
class ApprovalRecordAdmin(ReadOnlyAdmin):
    name_en = "Approvals"
    description = "ردِ تغییرناپذیرِ تأییدها: چه کسی، چه زمانی، چه متنی را برای کدام فرم تأیید کرد."
    list_display = ("item", "approved_by", "approved_at", "fingerprint")
    raw_id_fields = ("item",)


@admin.register(SendAttempt)
class SendAttemptAdmin(ReadOnlyAdmin):
    name_en = "Send attempts"
    description = "هر ارسالِ خودکار دقیقاً یک بار: آدرس، دادهٔ فرستاده‌شده، کدِ HTTP و بخشی از پاسخ. فقط‌خواندنی."
    list_display = ("item", "attempted_at", "status_code", "success_guess", "outcome")
    list_filter = ("success_guess", "outcome")
    raw_id_fields = ("item",)


@admin.register(OutreachJob)
class OutreachJobAdmin(ReadOnlyAdmin):
    name_en = "Outreach jobs"
    description = "کارهای پس‌زمینهٔ پیام‌رسانی (آماده‌سازیِ فرم‌ها و ارسال) با وضعیت و شمارنده‌ها."
    list_display = ("id", "campaign", "kind", "status", "total_items", "processed_items", "items_sent", "items_failed", "queued_at")
    list_filter = ("kind", "status")
