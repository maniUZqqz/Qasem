from django.contrib import admin

from .models import GeneratedMessage, KnowledgeItem


@admin.register(KnowledgeItem)
class KnowledgeItemAdmin(admin.ModelAdmin):
    name_en = "Product knowledge"
    description = "آنچه نویسندهٔ هوشمند می‌تواند دربارهٔ NM بگوید. برای کارِ روزمره از صفحهٔ «دانشِ محصول» در پنل استفاده کنید."
    list_display = ("title", "section", "is_active", "sort_order", "seed_key")
    list_filter = ("section", "is_active")
    search_fields = ("title", "body")


@admin.register(GeneratedMessage)
class GeneratedMessageAdmin(admin.ModelAdmin):
    name_en = "AI message versions"
    description = "نسخه‌های پیامی که هوش مصنوعی نوشته؛ فقط برای دیدن."
    list_display = ("item", "version", "status", "created_at")
    list_filter = ("status",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
