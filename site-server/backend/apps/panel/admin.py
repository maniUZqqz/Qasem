from django.contrib import admin

from .models import PanelFeature, PanelPage, PanelSection


class PageInline(admin.TabularInline):
    model = PanelPage
    extra = 0
    fields = ("key", "title", "path", "order", "enabled", "staff_only")
    readonly_fields = ("key", "path")
    show_change_link = True


class FeatureInline(admin.TabularInline):
    model = PanelFeature
    extra = 0
    fields = ("key", "title", "enabled", "description")
    readonly_fields = ("key",)


@admin.register(PanelSection)
class PanelSectionAdmin(admin.ModelAdmin):
    name_en = "Panel sections"
    description = ("دسته‌های منوی پنل (فروشگاه، بازار، فروش و پشتیبانی، …). تیکِ «فعال» را بردارید، کلِ دسته با "
                   "همهٔ صفحه‌هایش از پنل پنهان می‌شود؛ دوباره بزنید، برمی‌گردد.")
    list_display = ("title", "key", "order", "enabled", "staff_only", "page_count")
    list_editable = ("order", "enabled")
    search_fields = ("key", "title")
    inlines = [PageInline]

    @admin.display(description="صفحه‌ها")
    def page_count(self, obj):
        return obj.pages.count()


@admin.register(PanelPage)
class PanelPageAdmin(admin.ModelAdmin):
    name_en = "Panel pages"
    description = ("هر صفحهٔ پنل (محصولات، آمار، کمپین‌ها، …). تیکِ «فعال» را بردارید، صفحه از منو می‌رود و "
                   "بازکردنِ مسیرش پیامِ «این صفحه فعلاً غیرفعال است» می‌دهد.")
    list_display = ("title", "section", "key", "path", "order", "enabled", "staff_only", "feature_count")
    list_editable = ("enabled",)
    list_filter = ("section", "enabled", "staff_only")
    search_fields = ("key", "title", "path")
    inlines = [FeatureInline]

    @admin.display(description="قابلیت‌ها")
    def feature_count(self, obj):
        return obj.features.count()


@admin.register(PanelFeature)
class PanelFeatureAdmin(admin.ModelAdmin):
    name_en = "Panel features"
    description = "قابلیت‌های داخلِ یک صفحه (یک زبانه، یک کارت، یک دکمه). تیکِ «فعال» را بردارید، همان بخش از صفحه حذف می‌شود."
    list_display = ("title", "page", "key", "enabled")
    list_editable = ("enabled",)
    list_filter = ("page__section", "enabled")
    search_fields = ("key", "title")
