from django.contrib import admin

from .models import MotionAsset, MotionRender


@admin.register(MotionRender)
class MotionRenderAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "store", "mode", "style", "state", "target", "created_at")
    list_filter = ("state", "mode", "target")
    search_fields = ("title", "style")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MotionAsset)
class MotionAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "store", "width", "height", "created_at")
