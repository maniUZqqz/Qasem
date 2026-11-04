from django.contrib import admin

from .models import DiscoveryJob, DiscoveryJobRow


class RowInline(admin.TabularInline):
    model = DiscoveryJobRow
    extra = 0
    fields = ("row_number", "status", "errors", "matched_lead")
    readonly_fields = fields
    can_delete = False
    max_num = 0
    show_change_link = False


@admin.register(DiscoveryJob)
class DiscoveryJobAdmin(admin.ModelAdmin):
    name_en = "Discovery jobs"
    description = "ورودِ گروهیِ لیدها از فایل CSV (و بعدها کشفِ خودکار). وضعیت، شمارنده‌ها و ردیف‌های خطادار اینجا دیده می‌شود."
    list_display = ("id", "kind", "file_name", "status", "total_items", "created_count", "duplicate_count", "error_count", "queued_at")
    list_filter = ("status", "kind")
    readonly_fields = [f.name for f in DiscoveryJob._meta.fields]
    inlines = [RowInline]

    def has_add_permission(self, request):
        return False
