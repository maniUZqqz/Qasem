from django.contrib import admin

from .models import IgAccount, IgAudio, IgHashtag, IgPost, IgScanRun, IgSeed, IgSettings, IgStoreConfig, IgTrendCluster


@admin.register(IgSeed)
class IgSeedAdmin(admin.ModelAdmin):
    list_display = ("store", "kind", "value", "enabled", "scrape", "last_status", "last_read_at")
    list_filter = ("kind", "enabled", "source")
    search_fields = ("value",)


@admin.register(IgAccount)
class IgAccountAdmin(admin.ModelAdmin):
    list_display = ("username", "followers", "baseline", "last_read_at")
    search_fields = ("username",)


@admin.register(IgPost)
class IgPostAdmin(admin.ModelAdmin):
    list_display = ("account", "code", "fmt", "taken_at", "likes", "comments", "views", "score")
    list_filter = ("fmt",)
    search_fields = ("code", "caption")


@admin.register(IgTrendCluster)
class IgTrendClusterAdmin(admin.ModelAdmin):
    list_display = ("store", "label", "kind", "score", "size", "accounts_count", "active", "computed_at")


@admin.register(IgScanRun)
class IgScanRunAdmin(admin.ModelAdmin):
    list_display = ("store", "source", "state", "accounts_read", "posts_new", "stop_code", "created_at")
    list_filter = ("source", "state")


admin.site.register(IgHashtag)
admin.site.register(IgAudio)
admin.site.register(IgStoreConfig)
admin.site.register(IgSettings)
