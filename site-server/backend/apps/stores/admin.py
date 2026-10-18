from django.contrib import admin

from .content_automation import ContentAutomation
from .models import Store, StoreProfile


class StoreProfileInline(admin.StackedInline):
    model = StoreProfile
    extra = 0


class ContentAutomationInline(admin.StackedInline):
    """Visible here because support needs to answer "why did nothing post?"
    without asking the owner to read their own settings page back."""

    model = ContentAutomation
    extra = 0
    readonly_fields = ["last_run_at", "summary"]

    @admin.display(description="یعنی")
    def summary(self, obj):
        return obj.summary() if obj.pk else "—"


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    name_en = "Stores"
    description = (
        "مرز مستأجرها: هر چیزی در این سیستم به یک فروشگاه تعلق دارد. حذف یک فروشگاه "
        "یعنی حذف محصول‌ها، سفارش‌ها و محتوایش."
    )
    list_display = ["name", "owner", "business_type", "is_active", "created_at"]
    search_fields = ["name", "owner__username"]
    inlines = [StoreProfileInline, ContentAutomationInline]
