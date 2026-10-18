"""Lead inbox.

This is where follow-up actually happens, so the list view is built for
triage: who, when, what they want, and whether anyone has touched it.
"""
from django.contrib import admin

from .events import Event
from .funnel import by_channel, funnel, top_pages
from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    name_en = "Leads"
    description = (
        "کسانی که فرم تماس سایت عمومی را پر کرده‌اند."
    )
    list_display = ("created_at", "name", "email", "business", "subject", "status")
    list_filter = ("status", "subject", "created_at")
    search_fields = ("name", "email", "phone", "business", "message")
    list_editable = ("status",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "created_at", "updated_at", "ip", "user_agent",
        "source_path", "referrer", "utm",
    )
    fieldsets = (
        ("پیام", {"fields": ("name", "email", "phone", "business", "subject", "message")}),
        ("پیگیری", {"fields": ("status", "notes")}),
        (
            "از کجا آمده",
            {
                "classes": ("collapse",),
                "fields": ("source_path", "referrer", "utm", "ip", "user_agent"),
            },
        ),
        ("زمان", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    @admin.action(description="علامت‌گذاری به‌عنوان اسپم")
    def mark_spam(self, request, queryset):
        updated = queryset.update(status=Lead.Status.SPAM)
        self.message_user(request, f"{updated} لید اسپم شد.")

    actions = ["mark_spam"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    name_en = "Events"
    description = (
        "هر کاری که یک بازدیدکننده در سایت عمومی کرده — بازدید صفحه، کلیک روی دکمه، "
        "انتخاب پلن. قیف فروش از روی همین ساخته می‌شود."
    )
    """Raw events. The funnel view below is what you actually read."""

    list_display = ("created_at", "name", "path", "locale", "session")
    list_filter = ("name", "locale", "created_at")
    search_fields = ("path", "session")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in Event._meta.fields)

    def has_add_permission(self, request):
        return False  # events come from the site, never typed in

    def changelist_view(self, request, extra_context=None):
        """Show the funnel above the raw list, so the numbers are unavoidable."""
        extra_context = extra_context or {}
        extra_context["funnel"] = funnel(30)
        extra_context["channels"] = by_channel(30)
        extra_context["pages"] = top_pages(30)
        return super().changelist_view(request, extra_context)
