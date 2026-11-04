from django.contrib import admin

from .models import BusinessProfile, ContactPoint, Lead, LeadActivity, LeadNote, LeadTag


class ContactInline(admin.TabularInline):
    model = ContactPoint
    extra = 0
    fields = ("kind", "value", "label", "is_primary", "source_ref", "source_url", "confidence")
    readonly_fields = ("normalized",)


class ProfileInline(admin.StackedInline):
    model = BusinessProfile
    extra = 0


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    name_en = "Growth leads"
    description = "کسب‌وکارهایی که می‌خواهیم به آن‌ها آپ‌مارکت را بفروشیم (بخشِ «جذب مشتری» در پنل). برای کارِ روزمره از خودِ پنل استفاده کنید."
    list_display = ("display_name", "website", "city", "status", "origin", "is_archived", "created_at")
    list_filter = ("status", "origin", "is_archived", "country")
    search_fields = ("business_name", "website", "instagram_url", "city", "contacts__value")
    readonly_fields = ("name_key", "provenance", "created_by", "created_at", "updated_at")
    inlines = [ProfileInline, ContactInline]
    raw_id_fields = ("created_by",)


@admin.register(LeadTag)
class LeadTagAdmin(admin.ModelAdmin):
    name_en = "Lead tags"
    description = "برچسب‌هایی که روی لیدها می‌گذارید."
    list_display = ("name", "color")
    readonly_fields = ("name_key",)


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    name_en = "Lead notes"
    description = "یادداشت‌های تیم روی لیدها."
    list_display = ("lead", "author", "created_at")
    raw_id_fields = ("lead", "author")


@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):
    name_en = "Lead history"
    description = "تاریخچهٔ هر لید. فقط‌خواندنی است: ویرایش نمی‌شود و فقط همراهِ حذفِ خودِ لید پاک می‌شود."
    list_display = ("lead", "kind", "summary", "actor", "created_at")
    list_filter = ("kind",)
    readonly_fields = [f.name for f in LeadActivity._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # needed so that deleting a whole lead (which cascades to its history) works; history rows are
        # never edited, and the panel has no way to delete them one by one
        return request.user.is_superuser
