from django.contrib import admin

from .models import AuditEntry, GrowthSettings, SuppressionEntry


@admin.register(GrowthSettings)
class GrowthSettingsAdmin(admin.ModelAdmin):
    name_en = "Growth settings"
    description = "هویتِ فرستندهٔ پیام‌ها، سقفِ روزانه، فاصلهٔ ارسال و کلیدهای توقف. برای کارِ روزمره از صفحهٔ «تنظیماتِ جذب مشتری» در پنل استفاده کنید."
    list_display = ("__str__", "sending_enabled", "emergency_stop", "daily_cap", "updated_at")
    readonly_fields = ("updated_by", "updated_at")

    def has_add_permission(self, request):
        return not GrowthSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SuppressionEntry)
class SuppressionEntryAdmin(admin.ModelAdmin):
    name_en = "Do-not-contact list"
    description = "تلفن، ایمیل، سایت یا اینستاگرامی که هیچ پیامی نباید برایش برود."
    list_display = ("value", "kind", "reason", "created_by", "created_at")
    list_filter = ("kind", "reason")
    search_fields = ("value", "note")
    readonly_fields = ("normalized", "created_by", "created_at")


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    name_en = "Growth audit log"
    description = "ردِ فقط‌خواندنیِ کارهای مهمِ پیام‌رسانی: تغییرِ تنظیمات، توقف، تأیید، ارسال."
    list_display = ("created_at", "kind", "summary", "actor")
    list_filter = ("kind",)
    readonly_fields = [f.name for f in AuditEntry._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
