from django.contrib import admin

from .models import EvalRun, LexiconEntry, ProblemWord, PronSettings


@admin.register(LexiconEntry)
class LexiconEntryAdmin(admin.ModelAdmin):
    list_display = ("word", "respelling", "pn", "store", "enabled", "updated_at")
    search_fields = ("word", "respelling")
    list_filter = ("enabled",)


@admin.register(ProblemWord)
class ProblemWordAdmin(admin.ModelAdmin):
    list_display = ("word", "source", "status", "count", "store", "updated_at")
    list_filter = ("source", "status")


@admin.register(EvalRun)
class EvalRunAdmin(admin.ModelAdmin):
    list_display = ("id", "engine", "voice", "sample", "state", "baseline", "created_at")
    list_filter = ("engine", "state", "baseline")
    exclude = ("rows",)


admin.site.register(PronSettings)
