from django.contrib import admin

from .models import Conversion


@admin.register(Conversion)
class ConversionAdmin(admin.ModelAdmin):
    list_display = ("id", "store", "title", "source_kind", "mode", "state", "created_at")
    list_filter = ("state", "mode", "source_kind")
    search_fields = ("title", "source_url")
    readonly_fields = ("scores", "raw_scores", "report", "warnings")
