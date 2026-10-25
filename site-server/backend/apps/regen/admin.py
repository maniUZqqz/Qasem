from django.contrib import admin

from .models import RegenSession, RegenVersion


class VersionInline(admin.TabularInline):
    model = RegenVersion
    extra = 0
    fields = ("number", "state", "start_frame", "end_frame", "engine", "quality", "seed", "progress", "message")
    readonly_fields = fields
    show_change_link = True


@admin.register(RegenSession)
class RegenSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "store", "source_kind", "state", "created_at")
    list_filter = ("state", "source_kind")
    search_fields = ("title", "source_ref")
    readonly_fields = ("info", "filmstrip", "original", "created_at", "updated_at")
    inlines = [VersionInline]


@admin.register(RegenVersion)
class RegenVersionAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "number", "state", "engine", "quality", "start_frame", "end_frame", "created_at")
    list_filter = ("state", "engine", "quality")
    readonly_fields = ("plan", "files", "seams", "stats", "compute_job", "created_at", "updated_at")
