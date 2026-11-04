from django.contrib import admin

from .models import ExtractionJob, ExtractionPageLog, ExtractionRun


class PageInline(admin.TabularInline):
    model = ExtractionPageLog
    extra = 0
    fields = ("kind", "url", "status", "outcome", "elapsed_ms", "bytes", "note")
    readonly_fields = fields
    can_delete = False
    max_num = 0


class RunInline(admin.TabularInline):
    model = ExtractionRun
    extra = 0
    fields = ("lead", "status", "reason", "pages_fetched", "contacts_added")
    readonly_fields = fields
    can_delete = False
    max_num = 0
    show_change_link = True


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    name_en = "Extraction jobs"
    description = "کارهای «خواندنِ اطلاعاتِ تماس از سایتِ خودِ کسب‌وکار». وضعیت، شمارنده‌ها و اجرای هر لید اینجا دیده می‌شود (فقط‌خواندنی)."
    list_display = ("id", "scope", "status", "total_items", "runs_done", "runs_failed", "runs_skipped", "contacts_added", "queued_at")
    list_filter = ("status", "scope")
    readonly_fields = [f.name for f in ExtractionJob._meta.fields]
    inlines = [RunInline]

    def has_add_permission(self, request):
        return False


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    name_en = "Extraction runs"
    description = "نتیجهٔ خواندنِ سایتِ یک لید: چه چیزی پیدا شد، از کدام صفحه، با چه اطمینانی، و چرا ذخیره شد یا نشد. گزارشِ هر صفحه (از جمله رد شدن به‌خاطر robots.txt) پایین است."
    list_display = ("id", "lead", "status", "reason", "pages_fetched", "contacts_added", "finished_at")
    list_filter = ("status", "reason")
    search_fields = ("lead__business_name", "lead__website")
    readonly_fields = [f.name for f in ExtractionRun._meta.fields]
    raw_id_fields = ("lead", "job")
    inlines = [PageInline]

    def has_add_permission(self, request):
        return False
