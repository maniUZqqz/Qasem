from __future__ import annotations

from rest_framework import serializers

from apps.growth_engine.integrations import safe_http

from .models import ExtractionJob, ExtractionPageLog, ExtractionRun
from .services import runner

#: outcome strings of a page log -> Persian (fetch outcomes, robots.txt states, and two crawler-only notes)
OUTCOME_LABELS = {
    **safe_http.OUTCOME_LABELS,
    "ok": "دریافت شد",
    "none": "robots.txt ندارد (همه‌چیز مجاز)",
    "disallow_all": "robots.txt دسترسی را بسته است",
    "unavailable": "robots.txt خوانده نشد؛ برای احتیاط رد شد",
    "off": "بررسیِ robots.txt خاموش است",
}


class PageLogSerializer(serializers.ModelSerializer):
    outcome_label = serializers.SerializerMethodField()

    class Meta:
        model = ExtractionPageLog
        fields = ["url", "kind", "status", "outcome", "outcome_label", "elapsed_ms", "bytes", "note"]

    def get_outcome_label(self, obj):
        # a robots.txt row says "ok" for a file that was read; everything else uses the shared labels
        if obj.kind == "robots" and obj.outcome == "ok":
            return "robots.txt خوانده شد"
        return OUTCOME_LABELS.get(obj.outcome, obj.outcome)


class RunSerializer(serializers.ModelSerializer):
    """``ExtractionRunInfo`` of the front end (with the page log)."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reason_label = serializers.CharField(read_only=True)
    job_id = serializers.IntegerField(allow_null=True, read_only=True)
    pages = PageLogSerializer(many=True, read_only=True)

    class Meta:
        model = ExtractionRun
        fields = [
            "id", "job_id", "status", "status_label", "reason", "reason_label", "started_at", "finished_at",
            "pages_fetched", "robots_state", "contacts_added", "findings", "pages",
        ]


class RunBriefSerializer(serializers.ModelSerializer):
    lead_name = serializers.CharField(source="lead.display_name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reason_label = serializers.CharField(read_only=True)

    class Meta:
        model = ExtractionRun
        fields = ["id", "lead_id", "lead_name", "status", "status_label", "reason", "reason_label", "pages_fetched", "contacts_added"]


class JobSerializer(serializers.ModelSerializer):
    """``ExtractionJobInfo`` of the front end."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    scope_label = serializers.CharField(source="get_scope_display", read_only=True)
    progress = serializers.IntegerField(read_only=True)
    stalled = serializers.BooleanField(source="is_stalled", read_only=True)
    can_resume = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    discovery_job_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = ExtractionJob
        fields = [
            "id", "status", "status_label", "scope", "scope_label", "discovery_job_id", "progress", "total_items", "processed_items",
            "runs_done", "runs_failed", "runs_skipped", "pages_fetched", "contacts_added", "error", "stalled", "can_resume",
            "cancel_requested", "attempts", "queued_at", "started_at", "finished_at", "created_by_name",
        ]

    def get_can_resume(self, obj):
        return runner.can_resume(obj)

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by_id else ""


class JobDetailSerializer(JobSerializer):
    runs = serializers.SerializerMethodField()

    class Meta(JobSerializer.Meta):
        fields = JobSerializer.Meta.fields + ["runs"]

    def get_runs(self, obj):
        queryset = obj.runs.select_related("lead").order_by("id")[:300]
        return RunBriefSerializer(queryset, many=True).data


class JobCreateSerializer(serializers.Serializer):
    lead_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True, max_length=5000)
    discovery_job_id = serializers.IntegerField(required=False, min_value=1)
    force = serializers.BooleanField(required=False, default=False)
