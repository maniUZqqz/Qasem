from django.contrib import admin

from .models import PhotoAsset, PhotoEdit, PhotoPreset, PhotoProject


@admin.register(PhotoAsset)
class PhotoAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "store", "source_kind", "width", "height", "created_at")
    list_filter = ("source_kind",)
    search_fields = ("title", "source_ref")
    raw_id_fields = ("store", "product", "created_by")


@admin.register(PhotoEdit)
class PhotoEditAdmin(admin.ModelAdmin):
    list_display = ("id", "asset", "number", "recipe", "state", "progress", "created_at")
    list_filter = ("state", "recipe")
    search_fields = ("batch", "compute_job")
    raw_id_fields = ("asset", "created_by")


@admin.register(PhotoProject)
class PhotoProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "asset", "store", "rev", "updated_at")
    search_fields = ("title",)
    raw_id_fields = ("store", "asset")


@admin.register(PhotoPreset)
class PhotoPresetAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "store", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("name",)
    raw_id_fields = ("store", "created_by")
