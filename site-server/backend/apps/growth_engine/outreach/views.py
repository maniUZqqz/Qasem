"""Outreach endpoints (``/api/v1/growth/outreach/...``). Views read the request, call a service, shape the answer."""
from __future__ import annotations

import logging

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import limits
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.core.pagination import GrowthPagination
from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.core.throttles import GrowthBulkThrottle
from apps.growth_engine.leads.api_utils import validation_response
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services.editing import ValidationFailed

from .models import Campaign, MessageTemplate, OutreachItem, OutreachJob
from .serializers import (
    AddLeadsSerializer,
    CampaignCreateSerializer,
    ChannelReorderSerializer,
    ChannelUpdateSerializer,
    CampaignPatchSerializer,
    ItemIdsSerializer,
    ItemPatchSerializer,
    OutcomeSerializer,
    PreviewSerializer,
    TemplateInputSerializer,
    campaign_json,
    item_json,
    job_json,
    template_json,
)
from .channels import email as email_channel
from .channels import sms as sms_channel
from .services import approval, campaigns, channel_config, items, manual, preparing, rendering, sending, templates
from .tasks import enqueue

logger = logging.getLogger(__name__)


class GrowthView(APIView):
    permission_classes = [IsGrowthStaff]


class ThrottledPost(GrowthView):
    """Views whose POST starts real work share the bulk throttle."""

    def get_throttles(self):
        throttles = super().get_throttles()
        return throttles + [GrowthBulkThrottle()] if self.request.method == "POST" else throttles


def _problem(exc: campaigns.CampaignError | ValidationFailed) -> Response:
    if isinstance(exc, campaigns.CampaignError):
        return validation_response(ValidationFailed([{"field": "campaign", "code": exc.code, "message": exc.message}]))
    return validation_response(exc)


def _campaign_or_404(pk: int) -> Campaign:
    return get_object_or_404(Campaign.objects.select_related("template", "created_by"), pk=pk)


def _item_queryset():
    return OutreachItem.objects.select_related("lead", "campaign", "campaign__template", "approved_record", "approved_record__approved_by", "attempt")


# --------------------------------------------------------------------------- templates


class PlaceholdersView(GrowthView):
    def get(self, request):
        return Response([{"key": k, "label": label, "example_source": source} for k, label, source in rendering.PLACEHOLDERS])


class TemplateListView(GrowthView):
    def get(self, request):
        queryset = MessageTemplate.objects.select_related("created_by").annotate(n_campaigns=Count("campaigns")).order_by("-id")
        if request.query_params.get("active") == "1":
            queryset = queryset.filter(is_active=True)
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([template_json(t, t.n_campaigns) for t in page])

    def post(self, request):
        serializer = TemplateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            template = templates.create(serializer.validated_data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(template_json(template, 0), status=status.HTTP_201_CREATED)


class TemplateDetailView(GrowthView):
    def get(self, request, pk):
        return Response(template_json(get_object_or_404(MessageTemplate.objects.select_related("created_by"), pk=pk)))

    def patch(self, request, pk):
        template = get_object_or_404(MessageTemplate, pk=pk)
        serializer = TemplateInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            template = templates.update(template, serializer.validated_data)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(template_json(template))

    def delete(self, request, pk):
        template = get_object_or_404(MessageTemplate, pk=pk)
        try:
            templates.delete(template)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TemplatePreviewView(GrowthView):
    def post(self, request):
        serializer = PreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lead = get_object_or_404(Lead, pk=data["lead_id"]) if data.get("lead_id") else None
        return Response(templates.preview(data["body"], data.get("subject", ""), lead, data.get("channel") or None))


# --------------------------------------------------------------------------- campaigns


class CampaignListView(GrowthView):
    def get(self, request):
        queryset = Campaign.objects.select_related("template", "created_by")
        wanted = [s for s in (request.query_params.get("status") or "").split(",") if s]
        if wanted:
            queryset = queryset.filter(status__in=wanted)
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        counted = campaigns.counts([c.pk for c in page])
        return paginator.get_paginated_response([campaign_json(c, counted[c.pk]) for c in page])

    def post(self, request):
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        template = MessageTemplate.objects.filter(pk=data["template_id"]).first()
        if template is None:
            return validation_response(ValidationFailed([{"field": "template_id", "code": "not_found", "message": "این قالب پیدا نشد."}]))
        try:
            campaign = campaigns.create_campaign(name=data["name"], template=template, mode=data["mode"], user=request.user, channel=data["channel"])
        except campaigns.CampaignError as exc:
            return _problem(exc)
        body = campaign_json(campaign)
        if data.get("lead_ids"):
            result = campaigns.add_leads(campaign, data["lead_ids"], user=request.user, force=data.get("force", False))
            body = campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk])
            body["add_result"] = {"added": len(result.added), "skipped": result.skipped}
        return Response(body, status=status.HTTP_201_CREATED)


class CampaignDetailView(GrowthView):
    def get(self, request, pk):
        campaign = _campaign_or_404(pk)
        return Response(campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk]))

    def patch(self, request, pk):
        campaign = _campaign_or_404(pk)
        serializer = CampaignPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = nz.normalize_text(serializer.validated_data["name"])
        if not name or len(name) > 150:
            return validation_response(ValidationFailed([{"field": "name", "code": "invalid", "message": "نامِ کمپین باید بین ۱ تا ۱۵۰ نویسه باشد."}]))
        campaign.name = name
        campaign.save(update_fields=["name", "updated_at"])
        return Response(campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk]))


class AddLeadsView(GrowthView):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        serializer = AddLeadsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = campaigns.add_leads(campaign, data["lead_ids"], user=request.user, force=data.get("force", False))
        except campaigns.CampaignError as exc:
            return _problem(exc)
        return Response({"added": len(result.added), "skipped": result.skipped})


class RemoveItemsView(GrowthView):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        serializer = ItemIdsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(campaigns.remove_items(campaign, serializer.validated_data.get("item_ids", []), request.user))


class PrepareView(ThrottledPost):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        try:
            job = preparing.create_prepare_job(campaign, request.user)
        except campaigns.CampaignError as exc:
            return _problem(exc)
        if job.status == OutreachJob.Status.QUEUED and not job.celery_task_id:
            enqueue(job)
        return Response(job_json(job), status=status.HTTP_202_ACCEPTED)


class ApproveView(ThrottledPost):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        serializer = ItemIdsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not data.get("all_ready") and not data.get("item_ids"):
            return validation_response(ValidationFailed([{"field": "item_ids", "code": "empty", "message": "موردی انتخاب نشده است."}]))
        return Response(approval.approve_items(campaign, item_ids=data.get("item_ids"), all_ready=data.get("all_ready", False), actor=request.user))


class RevokeView(GrowthView):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        serializer = ItemIdsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"revoked": approval.revoke_items(campaign, serializer.validated_data.get("item_ids", []), request.user)})


class StartView(ThrottledPost):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        try:
            campaign, job, created = campaigns.start(campaign, request.user)
        except campaigns.CampaignError as exc:
            return _problem(exc)
        if created and job is not None:
            enqueue(job)
        body = campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk])
        body["job"] = job_json(job)
        return Response(body, status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


class PauseView(GrowthView):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        try:
            campaign = campaigns.pause(campaign, request.user)
        except campaigns.CampaignError as exc:
            return _problem(exc)
        return Response(campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk]))


class CancelView(GrowthView):
    def post(self, request, pk):
        campaign = _campaign_or_404(pk)
        try:
            campaign = campaigns.cancel(campaign, request.user)
        except campaigns.CampaignError as exc:
            return _problem(exc)
        return Response(campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk]))


class StatusView(GrowthView):
    """Everything the campaign page polls: counters, the latest job, today's allowance, readiness."""

    def get(self, request, pk):
        campaign = _campaign_or_404(pk)
        sms_channel.reconcile(campaign.pk)  # what the phone has sent / failed since the last look
        settings_obj = GrowthSettings.load()
        readiness = settings_obj.readiness()
        job = campaign.jobs.first()
        return Response(
            {
                "campaign": campaign_json(campaign, campaigns.counts([campaign.pk])[campaign.pk]),
                "counts": campaigns.counts([campaign.pk])[campaign.pk],
                "job": job_json(job),
                "sent_today": limits.sent_today(),
                "daily_cap": settings_obj.daily_cap,
                "cap_remaining": limits.cap_remaining(settings_obj),
                "readiness": readiness,
                "emergency_stop": settings_obj.emergency_stop,
                "channels": {c["key"]: {"label": c["label"], "enabled": c["enabled"], "sent_today": c["sent_today"], "cap_remaining": c["cap_remaining"],
                                        "ready": c["ready"], "not_ready_reason": c["not_ready_reason"]}
                             for c in channel_config.snapshot_all() if c["kind"] == "auto"},
                "settings": {"sending_enabled": settings_obj.sending_enabled, "emergency_stop": settings_obj.emergency_stop, "ready": readiness},
            }
        )


# --------------------------------------------------------------------------- items


class ItemListView(GrowthView):
    def get(self, request, pk):
        campaign = _campaign_or_404(pk)
        sms_channel.reconcile(campaign.pk)
        queryset = _item_queryset().filter(campaign=campaign)
        channel = request.query_params.get("channel")
        if channel:
            queryset = queryset.filter(channel=channel)
        wanted = [s for s in (request.query_params.get("status") or "").split(",") if s]
        if wanted:
            queryset = queryset.filter(status__in=wanted)
        q = nz.normalize_text(request.query_params.get("q", ""))
        if q:
            queryset = queryset.filter(
                Q(lead__name_key__contains=nz.search_key(q)) | Q(lead__website__icontains=q) | Q(domain__icontains=q) | Q(lead__city__icontains=q)
            )
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(queryset.order_by("id"), request, view=self)
        return paginator.get_paginated_response([item_json(i) for i in page])


class ItemDetailView(GrowthView):
    def get(self, request, pk, item_id):
        return Response(item_json(get_object_or_404(_item_queryset(), pk=item_id, campaign_id=pk)))

    def patch(self, request, pk, item_id):
        item = get_object_or_404(_item_queryset(), pk=item_id, campaign_id=pk)
        serializer = ItemPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            items.edit_item(item, text=data.get("rendered_text"), subject=data.get("subject"), actor=request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(item_json(get_object_or_404(_item_queryset(), pk=item_id)))


class ItemRerenderView(GrowthView):
    def post(self, request, pk, item_id):
        item = get_object_or_404(_item_queryset(), pk=item_id, campaign_id=pk)
        try:
            items.rerender_item(item, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(item_json(get_object_or_404(_item_queryset(), pk=item_id)))


class ItemOutcomeView(GrowthView):
    def post(self, request, pk, item_id):
        item = get_object_or_404(_item_queryset(), pk=item_id, campaign_id=pk)
        serializer = OutcomeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            manual.record_outcome(item, data["outcome"], data.get("note", ""), request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(item_json(get_object_or_404(_item_queryset(), pk=item_id)))


# --------------------------------------------------------------------------- jobs


class JobDetailView(GrowthView):
    def get(self, request, pk):
        return Response(job_json(get_object_or_404(OutreachJob, pk=pk)))


class JobCancelView(GrowthView):
    def post(self, request, pk):
        return Response(job_json(sending.request_cancel(get_object_or_404(OutreachJob, pk=pk))))


class JobResumeView(GrowthView):
    def post(self, request, pk):
        job = get_object_or_404(OutreachJob, pk=pk)
        if not sending.prepare_resume(job):
            return validation_response(
                ValidationFailed([{"field": "job", "code": "not_resumable", "message": "این کار قابل ادامه نیست (یا تمام شده یا هنوز در حال اجراست)."}])
            )
        enqueue(job)
        job.refresh_from_db()
        return Response(job_json(job), status=status.HTTP_202_ACCEPTED)


# --------------------------------------------------------------------------- channels (settings; secrets are never returned)


class ChannelListView(GrowthView):
    """GET - every channel in priority order: on / off, readiness, caps, spacing, default template, which secrets are SET."""

    def get(self, request):
        return Response({"channels": channel_config.snapshot_all()})


class ChannelReorderView(GrowthView):
    def post(self, request):
        serializer = ChannelReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            channel_config.reorder(serializer.validated_data["order"], request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response({"channels": channel_config.snapshot_all()})


class ChannelDetailView(GrowthView):
    def get(self, request, key):
        try:
            channel_config.spec_or_404(key)
        except channel_config.UnknownChannel:
            return Response({"code": "not_found", "detail": "این کانال وجود ندارد."}, status=status.HTTP_404_NOT_FOUND)
        return Response(channel_config.snapshot(key))

    def patch(self, request, key):
        try:
            channel_config.spec_or_404(key)
        except channel_config.UnknownChannel:
            return Response({"code": "not_found", "detail": "این کانال وجود ندارد."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ChannelUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            channel_config.update(key, serializer.validated_data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(channel_config.snapshot(key))


class EmailVerifyView(ThrottledPost):
    """POST - open a session on the mail server and log in. Sends NOTHING."""

    def post(self, request):
        ok, message = email_channel.verify()
        return Response({"ok": ok, "message": message})
