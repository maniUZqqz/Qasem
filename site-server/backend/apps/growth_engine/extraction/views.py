"""Extraction endpoints (``/api/v1/growth/extraction/...`` and ``/api/v1/growth/leads/<id>/extraction/``).

Views only read the request, call the runner / a query and shape the response.
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.core.pagination import GrowthPagination
from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.core.throttles import GrowthBulkThrottle
from apps.growth_engine.leads.api_utils import validation_response
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services.editing import ValidationFailed

from .models import ExtractionJob, ExtractionRun
from .serializers import JobCreateSerializer, JobDetailSerializer, JobSerializer, RunSerializer
from .services import runner
from .tasks import enqueue_extraction

logger = logging.getLogger(__name__)


class GrowthView(APIView):
    permission_classes = [IsGrowthStaff]


class JobListCreateView(GrowthView):
    """GET: the jobs, newest first.  POST ``{lead_ids | discovery_job_id, force?}``: start an extraction (202)."""

    def get_throttles(self):
        throttles = super().get_throttles()
        return throttles + [GrowthBulkThrottle()] if self.request.method == "POST" else throttles

    def get(self, request):
        queryset = ExtractionJob.objects.select_related("created_by")
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(JobSerializer(page, many=True).data)

    def post(self, request):
        serializer = JobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            jobs = runner.create_jobs(
                request.user, lead_ids=data.get("lead_ids"), discovery_job_id=data.get("discovery_job_id"), force=data.get("force", False)
            )
        except runner.JobRequestError as exc:
            return validation_response(ValidationFailed([{"field": "lead_ids", "code": "nothing_to_do", "message": str(exc)}]))
        for job in jobs:
            enqueue_extraction(job.pk)
        logger.info("growth extraction jobs %s queued by user=%s", [j.pk for j in jobs], request.user.pk)
        body = JobSerializer(jobs[0]).data
        if len(jobs) > 1:
            body["extra_job_ids"] = [j.pk for j in jobs[1:]]
        return Response(body, status=status.HTTP_202_ACCEPTED)


class JobDetailView(GrowthView):
    def get(self, request, pk):
        job = get_object_or_404(ExtractionJob.objects.select_related("created_by"), pk=pk)
        return Response(JobDetailSerializer(job).data)


class JobCancelView(GrowthView):
    def post(self, request, pk):
        job = runner.request_cancel(get_object_or_404(ExtractionJob, pk=pk))
        return Response(JobSerializer(job).data)


class JobResumeView(GrowthView):
    def post(self, request, pk):
        job = get_object_or_404(ExtractionJob, pk=pk)
        if not runner.prepare_resume(job):
            return validation_response(
                ValidationFailed([{"field": "job", "code": "not_resumable", "message": "این کار قابل ادامه نیست (یا تمام شده یا هنوز در حال اجراست)."}])
            )
        enqueue_extraction(job.pk)
        job.refresh_from_db()
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class LeadExtractionView(GrowthView):
    """The latest runs of one lead: findings (with source page, evidence, confidence) and the page log."""

    def get(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        runs = ExtractionRun.objects.filter(lead=lead).exclude(status=ExtractionRun.Status.QUEUED).prefetch_related("pages").order_by("-id")[:5]
        return Response({"runs": RunSerializer(runs, many=True).data})
