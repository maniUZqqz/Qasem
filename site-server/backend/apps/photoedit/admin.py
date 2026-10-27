from django.contrib import admin

from .models import PhotoAsset, PhotoEdit


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
