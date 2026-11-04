"""Compliance endpoints: Growth Settings, emergency stop, audit, the do-not-contact list."""
from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.pagination import GrowthPagination
from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.leads.api_utils import validation_response
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services.editing import ValidationFailed

from .models import AuditEntry, SuppressionEntry, SuppressionReason
from .services import settings as settings_service
from .services import suppression


class GrowthView(APIView):
    permission_classes = [IsGrowthStaff]


# --------------------------------------------------------------------------- settings


class SettingsView(GrowthView):
    def get(self, request):
        return Response(settings_service.snapshot())

    def patch(self, request):
        try:
            obj = settings_service.update_settings(request.data, request.user)
        except settings_service.SettingsInvalid as exc:
            return validation_response(ValidationFailed(exc.errors))
        return Response(settings_service.snapshot(obj))


class EmergencyStopSerializer(serializers.Serializer):
    stop = serializers.BooleanField()


class EmergencyStopView(GrowthView):
    def post(self, request):
        serializer = EmergencyStopSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = settings_service.set_emergency_stop(serializer.validated_data["stop"], request.user)
        return Response(settings_service.snapshot(obj))


class AuditView(GrowthView):
    def get(self, request):
        rows = AuditEntry.objects.select_related("actor")[:100]
        return Response(
            [
                {
                    "id": r.pk, "kind": r.kind, "kind_label": r.get_kind_display(), "summary": r.summary, "data": r.data,
                    "actor_name": r.actor.username if r.actor_id else "", "created_at": r.created_at,
                }
                for r in rows
            ]
        )


# --------------------------------------------------------------------------- suppression list


def _entry_json(entry: SuppressionEntry) -> dict:
    return {
        "id": entry.pk, "kind": entry.kind, "kind_label": entry.get_kind_display(), "value": entry.value,
        "reason": entry.reason, "reason_label": entry.get_reason_display(), "note": entry.note,
        "created_by_name": entry.created_by.username if entry.created_by_id else "", "created_at": entry.created_at,
    }


class SuppressionInputSerializer(serializers.Serializer):
    value = serializers.CharField(required=False, allow_blank=True, max_length=600)
    lead_id = serializers.IntegerField(required=False, min_value=1)
    reason = serializers.ChoiceField(choices=SuppressionReason.choices, required=False, default=SuppressionReason.OTHER)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class SuppressionListView(GrowthView):
    def get(self, request):
        queryset = SuppressionEntry.objects.select_related("created_by")
        q = nz.normalize_text(request.query_params.get("q", ""))
        if q:
            queryset = queryset.filter(Q(value__icontains=q) | Q(normalized__icontains=nz.search_key(q)) | Q(note__icontains=q))
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([_entry_json(e) for e in page])

    def post(self, request):
        serializer = SuppressionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("lead_id"):
            lead = get_object_or_404(Lead, pk=data["lead_id"])
            try:
                created = suppression.suppress_lead(lead, data["reason"], data.get("note", ""), request.user)
            except suppression.NothingToSuppress:
                return validation_response(ValidationFailed([{"field": "lead_id", "code": "nothing_to_suppress", "message": "این لید تلفن، ایمیل، وب‌سایت یا اینستاگرامی ندارد که بشود در فهرست گذاشت."}]))
            return Response({"added": len(created), "entries": [_entry_json(e) for e in created]}, status=status.HTTP_201_CREATED)
        if not data.get("value", "").strip():
            return validation_response(ValidationFailed([{"field": "value", "code": "required", "message": "شماره، ایمیل، آدرس سایت یا @اینستاگرام را بنویسید."}]))
        try:
            kind, key, value = suppression.classify(data["value"])
        except nz.NormalizationError as exc:
            return validation_response(ValidationFailed([{"field": "value", "code": exc.code, "message": exc.message}]))
        created = suppression.add_entries([(kind, key, value)], data["reason"], data.get("note", ""), request.user)
        if not created:
            return validation_response(ValidationFailed([{"field": "value", "code": "already_listed", "message": "این مورد از قبل در فهرست هست."}]))
        return Response({"added": 1, "entries": [_entry_json(e) for e in created]}, status=status.HTTP_201_CREATED)


class SuppressionDetailView(GrowthView):
    def delete(self, request, pk):
        entry = get_object_or_404(SuppressionEntry, pk=pk)
        suppression.remove_entry(entry, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeadDoNotContactView(GrowthView):
    """POST puts every identifier of the lead on the list; DELETE takes them off."""

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        serializer = SuppressionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            created = suppression.suppress_lead(lead, data["reason"], data.get("note", ""), request.user)
        except suppression.NothingToSuppress:
            return validation_response(ValidationFailed([{"field": "lead", "code": "nothing_to_suppress", "message": "این لید تلفن، ایمیل، وب‌سایت یا اینستاگرامی ندارد که بشود در فهرست گذاشت."}]))
        return Response({"do_not_contact": True, "added": len(created)}, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        removed = suppression.unsuppress_lead(lead, request.user)
        return Response({"do_not_contact": bool(suppression.matches_for_lead(lead)), "removed": removed})
