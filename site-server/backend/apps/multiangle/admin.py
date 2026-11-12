from django.contrib import admin

from .models import MultiAngleRun


@admin.register(MultiAngleRun)
class MultiAngleRunAdmin(admin.ModelAdmin):
    list_display = ("id", "mode", "state", "title", "store", "created_at")
    list_filter = ("mode", "state")
    search_fields = ("title", "job_uid", "source_ref")
    readonly_fields = ("plan", "files", "params", "warnings", "checks")
