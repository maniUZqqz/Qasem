from django.contrib import admin

from .models import Campaign, PublishJob


class PublishJobInline(admin.TabularInline):
    model = PublishJob
    extra = 0
    readonly_fields = ["platform", "status", "attempts", "last_error", "published_at"]


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    name_en = "Campaigns"
    description = (
        "بسته‌ی محتوای تأییدشده‌ی یک محصول: پوستر، کپشن، سناریو، همه زیر یک نام. چیزی "
        "که منتشر می‌شود این است."
    )
    list_display = ["id", "name", "store", "product", "approval_state", "created_at"]
    list_filter = ["approval_state"]
    inlines = [PublishJobInline]


@admin.register(PublishJob)
class PublishJobAdmin(admin.ModelAdmin):
    name_en = "Publish jobs"
    description = (
        "هر تلاش برای تحویل یک کمپین به یک پلتفرم. اگر پستی منتشر نشد، دلیلش در ستون "
        "خطای همین‌جاست."
    )
    list_display = ["id", "campaign", "platform", "status", "attempts", "published_at"]
    list_filter = ["status", "platform"]
