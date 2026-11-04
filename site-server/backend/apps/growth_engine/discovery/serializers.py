from __future__ import annotations

from rest_framework import serializers

from .models import DiscoveryJob, DiscoveryJobRow


class JobSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    progress = serializers.IntegerField(read_only=True)
    stalled = serializers.BooleanField(source="is_stalled", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    can_resume = serializers.SerializerMethodField()

    class Meta:
        model = DiscoveryJob
        fields = [
            "id", "kind", "kind_label", "status", "status_label", "file_name", "encoding", "total_items",
            "processed_items", "progress", "created_count", "merged_count", "skipped_count", "duplicate_count",
            "error_count", "error", "stalled", "can_resume", "cancel_requested", "attempts", "queued_at",
            "started_at", "finished_at", "created_by_name", "params",
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by_id else ""

    def get_can_resume(self, obj):
        resumable = obj.status == DiscoveryJob.Status.FAILED or obj.is_stalled
        return resumable and (bool(obj.stored_name) or obj.kind == DiscoveryJob.Kind.SEARCH)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # the mapping is useful to see; nothing else in params is secret, but keep the payload small
        params = data.get("params") or {}
        keep = ("mapping", "default_country", "default_city", "tags", "extract_after", "provider", "category", "category_label", "city", "country",
                "max_results", "require_contact", "attribution", "attribution_url", "empty_note")
        data["params"] = {k: params.get(k) for k in keep if k in params}
        data["attribution"] = params.get("attribution", "")
        return data


class JobRowSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    matched_lead_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = DiscoveryJobRow
        fields = ["id", "row_number", "status", "status_label", "raw", "errors", "matches", "matched_lead_id", "resolved_at"]


class CsvCheckSerializer(serializers.Serializer):
    upload_id = serializers.CharField(max_length=64)
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True), allow_empty=False)
    default_country = serializers.CharField(required=False, allow_blank=True, max_length=60)
    default_city = serializers.CharField(required=False, allow_blank=True, max_length=100)


class CsvImportSerializer(CsvCheckSerializer):
    tags = serializers.ListField(child=serializers.CharField(max_length=50), required=False, max_length=20)
    extract_after = serializers.BooleanField(required=False)


class ManualSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["website_url", "instagram_url", "business_name", "manual"])
    business_name = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    website = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    instagram = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    email = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    whatsapp = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    telegram = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    category = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    description = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    city = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    note = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    tags = serializers.ListField(child=serializers.CharField(allow_blank=True, max_length=200), required=False, max_length=100)
    language = serializers.CharField(required=False, allow_blank=True, max_length=20)
    business_type = serializers.CharField(required=False, allow_blank=True, max_length=60)
    address = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    resolution = serializers.DictField(required=False)


class ResolveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["merge", "skip"])
    rows = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=5000)
    all = serializers.BooleanField(required=False)
    target_lead = serializers.IntegerField(required=False, min_value=1)
    overwrite_fields = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=20)


class SearchRequestSerializer(serializers.Serializer):
    """The panel's «کشف خودکار» form. Validation of the values themselves is in ``services/search.validate_request``."""

    provider = serializers.CharField(max_length=24)
    category = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    city = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    country = serializers.CharField(max_length=60, allow_blank=True, required=False, default="")
    max_results = serializers.IntegerField(required=False, min_value=1, max_value=5000, default=100)
    require_contact = serializers.BooleanField(required=False, default=True)
    extract_after = serializers.BooleanField(required=False, default=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=50, allow_blank=True), required=False, max_length=20)


class ProviderUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    settings = serializers.DictField(required=False)
    secrets = serializers.DictField(child=serializers.CharField(allow_blank=True, max_length=400), required=False)
    clear_secrets = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=10)
