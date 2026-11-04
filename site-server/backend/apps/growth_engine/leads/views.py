"""Lead endpoints: list, detail, edit, contacts, notes, history, bulk, export, tags.

Views only parse the request, call a service and shape the response.
"""
from __future__ import annotations

import logging
from datetime import date

from django.db.models import Count
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.core.pagination import GrowthPagination
from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.core.throttles import GrowthBulkThrottle, GrowthExportThrottle

from .api_utils import duplicate_response, validation_response
from .models import ContactPoint, Lead, LeadActivity, LeadNote, LeadTag
from .serializers import (
    ActivitySerializer,
    BulkInputSerializer,
    ContactInputSerializer,
    ContactSerializer,
    ContactUpdateSerializer,
    LeadDetailSerializer,
    LeadListSerializer,
    LeadUpdateSerializer,
    NoteInputSerializer,
    NoteSerializer,
    TagSerializer,
)
from .services import bulk, editing, export, queries
from .services.editing import ValidationFailed
from .services.intake import DuplicateError

logger = logging.getLogger(__name__)


class GrowthView(APIView):
    permission_classes = [IsGrowthStaff]


def suppressed_ids(lead_ids) -> set[int]:
    """Leads blocked by the do-not-contact list (empty when the compliance module is not installed)."""
    from django.apps import apps

    if not apps.is_installed("apps.growth_engine.compliance"):
        return set()
    from apps.growth_engine.compliance.services.suppression import suppressed_lead_ids

    return suppressed_lead_ids(list(lead_ids))


def _detail_queryset():
    return Lead.objects.select_related("profile", "created_by").prefetch_related(
        "tags", "contacts", "sources__created_by"
    )


class LeadListView(GrowthView):
    """GET /growth/leads/  - search, filters, sorting, pagination."""

    def get(self, request):
        queryset = queries.filter_leads(Lead.objects.all(), request.query_params)
        queryset = queries.with_list_prefetch(queries.apply_ordering(queryset, request.query_params.get("ordering")))
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        context = {"suppressed_ids": suppressed_ids(lead.pk for lead in page)}
        return paginator.get_paginated_response(LeadListSerializer(page, many=True, context=context).data)


class LeadDetailView(GrowthView):
    def get(self, request, pk):
        lead = get_object_or_404(_detail_queryset(), pk=pk)
        return Response(LeadDetailSerializer(lead, context={"suppressed_ids": suppressed_ids([lead.pk])}).data)

    def patch(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        serializer = LeadUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            changed = editing.update_lead(lead, serializer.validated_data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        except DuplicateError as exc:
            return duplicate_response(exc)
        lead = get_object_or_404(_detail_queryset(), pk=pk)
        return Response({**LeadDetailSerializer(lead, context={"suppressed_ids": suppressed_ids([lead.pk])}).data, "changed": changed})

    def delete(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        if request.query_params.get("confirm") != "1":
            return validation_response(ValidationFailed([{"field": "confirm", "code": "confirm_required", "message": "حذف باید تأیید شود."}]))
        logger.info("growth lead deleted id=%s by user=%s", lead.pk, request.user.pk)
        lead.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeadActivityView(GrowthView):
    def get(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        queryset = LeadActivity.objects.filter(lead=lead).select_related("actor")
        kind = request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(ActivitySerializer(page, many=True).data)


class LeadNotesView(GrowthView):
    def get(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        notes = LeadNote.objects.filter(lead=lead).select_related("author")
        return Response(NoteSerializer(notes, many=True).data)

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        serializer = NoteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            note = editing.add_note(lead, serializer.validated_data["body"], request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)


class LeadNoteDetailView(GrowthView):
    def patch(self, request, pk, note_id):
        note = get_object_or_404(LeadNote.objects.select_related("lead", "author"), pk=note_id, lead_id=pk)
        serializer = NoteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            note = editing.edit_note(note, serializer.validated_data["body"], request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(NoteSerializer(note).data)

    def delete(self, request, pk, note_id):
        note = get_object_or_404(LeadNote.objects.select_related("lead"), pk=note_id, lead_id=pk)
        editing.delete_note(note, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeadContactsView(GrowthView):
    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        serializer = ContactInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            contact = editing.add_contact(lead, data["kind"], data["value"], label=data.get("label", ""), actor=request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        except DuplicateError as exc:
            return duplicate_response(exc)
        return Response(ContactSerializer(contact).data, status=status.HTTP_201_CREATED)


class LeadContactDetailView(GrowthView):
    def patch(self, request, pk, contact_id):
        contact = get_object_or_404(ContactPoint.objects.select_related("lead"), pk=contact_id, lead_id=pk)
        serializer = ContactUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            contact = editing.update_contact(contact, serializer.validated_data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        except DuplicateError as exc:
            return duplicate_response(exc)
        return Response(ContactSerializer(contact).data)

    def delete(self, request, pk, contact_id):
        contact = get_object_or_404(ContactPoint.objects.select_related("lead"), pk=contact_id, lead_id=pk)
        editing.remove_contact(contact, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeadBulkView(GrowthView):
    """POST /growth/leads/bulk/  {ids: [...], action, status?, tag?, confirm?}"""

    throttle_classes = [GrowthBulkThrottle]

    def post(self, request):
        serializer = BulkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = bulk.bulk_action(
                data["ids"], data["action"],
                {"status": data.get("status"), "tag": data.get("tag"), "confirm": data.get("confirm")}, request.user,
            )
        except ValidationFailed as exc:
            return validation_response(exc)
        logger.info("growth bulk %s by user=%s: %s", data["action"], request.user.pk, result)
        return Response(result)


class LeadExportView(GrowthView):
    """GET /growth/leads/export/  - the same filters as the list (or ``?ids=1,2,3``), as UTF-8-BOM CSV."""

    throttle_classes = [GrowthExportThrottle]

    def get(self, request):
        queryset = queries.filter_leads(Lead.objects.all(), request.query_params)
        ids = [int(i) for i in (request.query_params.get("ids") or "").split(",") if i.strip().isdigit()]
        if ids:
            queryset = queryset.filter(pk__in=ids[:5000])
        queryset = queries.apply_ordering(queryset, request.query_params.get("ordering"))
        logger.info("growth export by user=%s ids=%s params=%s", request.user.pk, len(ids), dict(request.query_params))
        response = StreamingHttpResponse(export.stream_export(queryset), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="growth-leads-{date.today().isoformat()}.csv"'
        response["Cache-Control"] = "no-store"
        return response


class TagListView(GrowthView):
    def get(self, request):
        tags = LeadTag.objects.annotate(lead_count=Count("leads")).order_by("name")
        data = [{**TagSerializer(t).data, "lead_count": t.lead_count} for t in tags]
        return Response(data)
