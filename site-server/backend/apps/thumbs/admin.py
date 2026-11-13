from django.contrib import admin

from .models import IdeaSet, Thumbnail


@admin.register(Thumbnail)
class ThumbnailAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "store", "format", "style", "variant", "state", "created_at")
    list_filter = ("format", "style", "state")
    search_fields = ("title", "batch", "bg_job")
    raw_id_fields = ("store", "created_by", "asset")


@admin.register(IdeaSet)
class IdeaSetAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "store", "via", "created_at")
    list_filter = ("via",)
    raw_id_fields = ("store", "created_by", "product")
