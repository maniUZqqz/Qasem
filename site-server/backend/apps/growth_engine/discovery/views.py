"""Discovery endpoints: manual entry and the CSV import (upload -> check -> import -> job)."""
from __future__ import annotations

import logging

from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.pagination import GrowthPagination
from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.core.throttles import GrowthUploadThrottle
from apps.growth_engine.leads.api_utils import describe_plan, duplicate_payload, duplicate_response, validation_response
from apps.growth_engine.leads.serializers import LeadDetailSerializer, LeadListSerializer
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.leads.services.intake import DuplicateError, plan_merge

from .models import DiscoveryJob, DiscoveryJobRow
from .serializers import (
    CsvCheckSerializer,
    CsvImportSerializer,
    JobRowSerializer,
    JobSerializer,
    ManualSerializer,
    ResolveSerializer,
)
from .services import csv_import, csv_mapping, csv_upload, manual
from .tasks import enqueue_import

logger = logging.getLogger(__name__)


class GrowthView(APIView):
    permission_classes = [IsGrowthStaff]


# --------------------------------------------------------------------------- manual


def _manual_input(serializer: ManualSerializer) -> tuple[str, dict, dict | None]:
    data = dict(serializer.validated_data)
    mode = data.pop("mode")
    resolution = data.pop("resolution", None)
    return mode, data, resolution


class ManualCheckView(GrowthView):
    """POST /growth/discovery/manual/check/ - validation + duplicates, writes nothing."""

    def post(self, request):
        serializer = ManualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mode, raw, _ = _manual_input(serializer)
        result = manual.check(raw, mode)
        if not result["valid"]:
            return Response({"valid": False, "errors": result["errors"], "duplicates": [], "similar": []})
        draft = result["draft"]
        return Response({
            "valid": True, "errors": [],
            "duplicates": duplicate_payload(result["matches"], draft),
            "similar": LeadListSerializer(result["similar"], many=True).data,
        })


class ManualSubmitView(GrowthView):
    """POST /growth/discovery/manual/ - create the lead, or apply the user's merge/skip decision."""

    def post(self, request):
        serializer = ManualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mode, raw, resolution = _manual_input(serializer)
        try:
            outcome = manual.submit(raw, mode, request.user, resolution=resolution)
        except DuplicateError as exc:
            draft, _, _ = manual.prepare(raw, mode)
            return duplicate_response(exc, draft)
        if outcome["result"] == "invalid":
            return validation_response(ValidationFailed(outcome["errors"]))
        if outcome["result"] == "created":
            return Response({"result": "created", "lead": LeadListSerializer(outcome["lead"]).data}, status=status.HTTP_201_CREATED)
        if outcome["result"] == "merged":
            merged = outcome["merge"]
            return Response({
                "result": "merged", "lead": LeadListSerializer(merged.lead).data, "filled": merged.filled,
                "overwritten": merged.overwritten, "conflicts": merged.conflicts,
                "contacts_added": merged.added_contacts, "contacts_skipped": merged.skipped_contacts,
            })
        return Response({"result": "skipped"})


# --------------------------------------------------------------------------- csv


class CsvUploadView(GrowthView):
    """POST multipart ``file`` -> upload id, headers, samples and a first guess of the mapping."""

    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [GrowthUploadThrottle]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return validation_response(ValidationFailed([{"field": "file", "code": "required", "message": "فایلی فرستاده نشد."}]))
        try:
            payload = csv_upload.save_upload(request.user, uploaded)
        except csv_upload.UploadError as exc:
            return validation_response(ValidationFailed([{"field": "file", "code": exc.code, "message": exc.message}]))
        logger.info("growth csv uploaded by user=%s name=%s rows=%s", request.user.pk, payload["file_name"], payload["total_rows"])
        return Response(payload, status=status.HTTP_201_CREATED)


def _load(request, data: dict) -> tuple[bytes, str]:
    return csv_upload.load_upload(request.user.pk, data["upload_id"])


class CsvCheckView(GrowthView):
    """POST {upload_id, mapping, default_country?, default_city?} -> row-level dry run (no database writes)."""

    parser_classes = [JSONParser]

    def post(self, request):
        serializer = CsvCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            country = nz.normalize_country(data.get("default_country", ""))
            blob, file_name = _load(request, data)
            result = csv_import.check_mapping(
                blob, file_name, data["mapping"], default_country=country, default_city=nz.normalize_text(data.get("default_city", "")),
            )
        except nz.NormalizationError as exc:
            return validation_response(ValidationFailed([{"field": "default_country", "code": exc.code, "message": exc.message}]))
        except (csv_upload.UploadError, csv_mapping.MappingError) as exc:
            code = getattr(exc, "code", "mapping")
            return validation_response(ValidationFailed([{"field": "mapping", "code": code, "message": getattr(exc, "message", str(exc))}]))
        return Response(result)


class CsvImportView(GrowthView):
    """POST {upload_id, mapping, ...} -> 202 + the queued job."""

    parser_classes = [JSONParser]
    throttle_classes = [GrowthUploadThrottle]

    def post(self, request):
        serializer = CsvImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            country = nz.normalize_country(data.get("default_country", ""))
            job = csv_import.create_import_job(
                request.user, data["upload_id"], data["mapping"], default_country=country,
                default_city=nz.normalize_text(data.get("default_city", "")), tags=data.get("tags"),
                extract_after=data.get("extract_after", False),
            )
        except nz.NormalizationError as exc:
            return validation_response(ValidationFailed([{"field": "default_country", "code": exc.code, "message": exc.message}]))
        except (csv_upload.UploadError, csv_mapping.MappingError) as exc:
            return validation_response(
                ValidationFailed([{"field": "mapping", "code": getattr(exc, "code", "mapping"), "message": getattr(exc, "message", str(exc))}])
            )
        enqueue_import(job.pk)
        logger.info("growth csv import job %s queued by user=%s rows=%s", job.pk, request.user.pk, job.total_items)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


# --------------------------------------------------------------------------- jobs


class JobListView(GrowthView):
    def get(self, request):
        queryset = DiscoveryJob.objects.select_related("created_by")
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(JobSerializer(page, many=True).data)


class JobDetailView(GrowthView):
    def get(self, request, pk):
        job = get_object_or_404(DiscoveryJob.objects.select_related("created_by"), pk=pk)
        return Response(JobSerializer(job).data)


class JobRowsView(GrowthView):
    """GET ?status=error|duplicate|merged|skipped|created - the row-level report."""

    def get(self, request, pk):
        job = get_object_or_404(DiscoveryJob, pk=pk)
        queryset = job.rows.all()
        wanted = request.query_params.get("status")
        if wanted:
            queryset = queryset.filter(status__in=[s for s in wanted.split(",") if s])
        paginator = GrowthPagination()
        paginator.page_size = 50
        page = paginator.paginate_queryset(queryset.order_by("row_number"), request, view=self)
        data = JobRowSerializer(page, many=True).data
        if request.query_params.get("with_merge_preview") == "1":
            ids = {m["lead_id"] for row in data for m in row["matches"][:1]}
            by_id = {}
            from apps.growth_engine.leads.models import Lead

            for lead in Lead.objects.filter(pk__in=ids):
                by_id[lead.pk] = lead
            from apps.growth_engine.leads.services.drafts import LeadDraft

            rows_by_id = {r.pk: r for r in page}
            for item in data:
                row = rows_by_id[item["id"]]
                first = item["matches"][0]["lead_id"] if item["matches"] else None
                if row.status == DiscoveryJobRow.Status.DUPLICATE and first in by_id and row.payload:
                    item["merge_preview"] = describe_plan(plan_merge(by_id[first], LeadDraft.from_payload(row.payload)))
        return paginator.get_paginated_response(data)


class JobErrorsCsvView(GrowthView):
    def get(self, request, pk):
        job = get_object_or_404(DiscoveryJob, pk=pk)
        response = StreamingHttpResponse(csv_import.errors_csv_stream(job), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="import-{job.pk}-errors.csv"'
        response["Cache-Control"] = "no-store"
        return response


class JobCancelView(GrowthView):
    def post(self, request, pk):
        job = get_object_or_404(DiscoveryJob, pk=pk)
        job = csv_import.request_cancel(job)
        return Response(JobSerializer(job).data)


class JobResumeView(GrowthView):
    def post(self, request, pk):
        job = get_object_or_404(DiscoveryJob, pk=pk)
        if not csv_import.prepare_resume(job):
            return validation_response(
                ValidationFailed([{"field": "job", "code": "not_resumable", "message": "این کار قابل ادامه نیست (یا تمام شده یا فایلش پاک شده)."}])
            )
        enqueue_import(job.pk)
        job.refresh_from_db()
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class JobResolveView(GrowthView):
    """POST {action: merge|skip, rows: [ids] | all: true, target_lead?, overwrite_fields?} on duplicate rows."""

    parser_classes = [JSONParser]

    def post(self, request, pk):
        job = get_object_or_404(DiscoveryJob, pk=pk)
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rows = job.rows.all()
        if not data.get("all"):
            ids = data.get("rows") or []
            if not ids:
                return validation_response(ValidationFailed([{"field": "rows", "code": "empty", "message": "ردیفی انتخاب نشده است."}]))
            rows = rows.filter(Q(pk__in=ids))
        result = csv_import.resolve_rows(
            job, rows, data["action"], request.user, target_lead_id=data.get("target_lead"),
            overwrite_fields=data.get("overwrite_fields", []),
        )
        return Response(result)
