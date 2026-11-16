from django.contrib import admin

from .models import CrawlCandidate, CrawlFinding, CrawlLog, CrawlMission, CrawlRun, CrawlTask, FetchCache, LeadInsight, LeadReminder, OutreachDraft


@admin.register(CrawlMission)
class CrawlMissionAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "preset_key", "product", "schedule_days", "enabled", "next_run_at", "last_run_at", "is_archived")
    list_filter = ("enabled", "is_archived", "product")
    search_fields = ("name",)


@admin.register(CrawlRun)
class CrawlRunAdmin(admin.ModelAdmin):
    list_display = ("id", "mission", "status", "stage", "paused", "found_count", "created_count", "merged_count", "queued_at", "finished_at")
    list_filter = ("status", "stage", "trigger")
    readonly_fields = ("plan", "spec", "usage", "params")


@admin.register(CrawlTask)
class CrawlTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "source", "kind", "status", "attempts", "label")
    list_filter = ("source", "status", "stage")
    search_fields = ("key", "label")


admin.site.register(CrawlLog)
admin.site.register(CrawlCandidate)
admin.site.register(CrawlFinding)
admin.site.register(LeadInsight)
admin.site.register(LeadReminder)
admin.site.register(OutreachDraft)
admin.site.register(FetchCache)
