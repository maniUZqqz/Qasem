"""Knowledge endpoints (``/api/v1/growth/knowledge/...``) and the AI-writer endpoints on an outreach item (``.../items/<id>/ai|versions``)."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.core.throttles import GrowthBulkThrottle
from apps.growth_engine.leads.api_utils import validation_response
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.outreach.models import OutreachItem

from .models import GeneratedMessage, KnowledgeItem
from .services import ai, kb, seed, versions
from .tasks import enqueue

MAX_BULK = 30


class GrowthView(APIView):
    permission_classes = [IsGrowthStaff]


class KnowledgeInputSerializer(serializers.Serializer):
    section = serializers.CharField(required=False, max_length=12)
    title = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    body = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    sort_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)


class WriteSerializer(serializers.Serializer):
    instructions = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class BulkWriteSerializer(WriteSerializer):
    item_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=MAX_BULK)


class ApproveSerializer(serializers.Serializer):
    acknowledge_warnings = serializers.BooleanField(required=False, default=False)


# --------------------------------------------------------------------------- knowledge


class KnowledgeListView(GrowthView):
    def get(self, request):
        return Response(kb.listing())

    def post(self, request):
        serializer = KnowledgeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = kb.create(serializer.validated_data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(kb.item_json(item), status=status.HTTP_201_CREATED)


class KnowledgeDetailView(GrowthView):
    def patch(self, request, pk):
        item = get_object_or_404(KnowledgeItem, pk=pk)
        serializer = KnowledgeInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            item = kb.update(item, serializer.validated_data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(kb.item_json(item))

    def delete(self, request, pk):
        get_object_or_404(KnowledgeItem, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class KnowledgeResetView(GrowthView):
    def post(self, request, pk):
        item = get_object_or_404(KnowledgeItem, pk=pk)
        try:
            return Response(kb.item_json(kb.reset_to_default(item, request.user)))
        except ValidationFailed as exc:
            return validation_response(exc)


class RestoreDefaultsView(GrowthView):
    """POST - put back the default knowledge items and default templates that were deleted (nothing edited is touched)."""

    def post(self, request):
        return Response(seed.restore_defaults())


class WriterStatusView(GrowthView):
    """GET - what the AI routing looks like right now (best effort)."""

    def get(self, request):
        return Response(ai.status())


# --------------------------------------------------------------------------- the writer on an item


def _item(pk: int, item_id: int) -> OutreachItem:
    return get_object_or_404(
        OutreachItem.objects.select_related("lead", "campaign", "campaign__template", "template"), pk=item_id, campaign_id=pk
    )


def _version(pk: int, item_id: int, vid: int) -> GeneratedMessage:
    return get_object_or_404(GeneratedMessage.objects.select_related("item", "created_by", "decided_by"), pk=vid, item_id=item_id, item__campaign_id=pk)


class WriteView(GrowthView):
    """POST - ask the AI for a new version of this item's message (202; poll the versions)."""

    def get_throttles(self):
        return super().get_throttles() + [GrowthBulkThrottle()]

    def post(self, request, pk, item_id):
        item = _item(pk, item_id)
        serializer = WriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            version, created = versions.request_version(item, request.user, serializer.validated_data["instructions"])
        except ValidationFailed as exc:
            return validation_response(exc)
        if created:
            enqueue(version.pk)
        return Response({**versions.version_json(version, current_text=item.rendered_text), "created": created}, status=status.HTTP_202_ACCEPTED)


class BulkWriteView(GrowthView):
    """POST {item_ids, instructions?} - ask for a version for several items (at most 30); items that cannot be written are listed."""

    def get_throttles(self):
        return super().get_throttles() + [GrowthBulkThrottle()]

    def post(self, request, pk):
        serializer = BulkWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        started, refused = [], []
        for item in OutreachItem.objects.select_related("lead", "campaign", "campaign__template", "template").filter(campaign_id=pk, pk__in=data["item_ids"]):
            try:
                version, created = versions.request_version(item, request.user, data["instructions"])
            except ValidationFailed as exc:
                refused.append({"item_id": item.pk, "text": exc.errors[0]["message"]})
                continue
            if created:
                enqueue(version.pk)
            started.append({"item_id": item.pk, "version_id": version.pk})
        return Response({"started": started, "refused": refused}, status=status.HTTP_202_ACCEPTED)


class VersionListView(GrowthView):
    def get(self, request, pk, item_id):
        item = _item(pk, item_id)
        rows = item.versions.select_related("created_by", "decided_by")
        return Response({"versions": [versions.version_json(v, current_text=item.rendered_text) for v in rows], "current_text": item.rendered_text, "current_subject": item.subject})


class VersionCompareView(GrowthView):
    """GET ?a=<version id | current>&b=<version id | current> - a word-level difference (old side ``a``, new side ``b``)."""

    def get(self, request, pk, item_id):
        item = _item(pk, item_id)

        def side(token: str) -> tuple[str, str]:
            if token in ("current", "", None):
                return "متنِ فعلیِ پیام", item.rendered_text
            if not str(token).isdigit():
                raise ValidationFailed([{"field": "compare", "code": "invalid", "message": "نسخه درست انتخاب نشده است."}])
            version = get_object_or_404(GeneratedMessage, pk=int(token), item=item)
            return f"نسخهٔ {version.version}", version.text

        try:
            (a_label, a_text), (b_label, b_text) = side(request.query_params.get("a", "current")), side(request.query_params.get("b", "current"))
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response({"a": {"label": a_label, "text": a_text}, "b": {"label": b_label, "text": b_text}, "ops": versions.compare(a_text, b_text)})


class VersionApproveView(GrowthView):
    def post(self, request, pk, item_id, vid):
        version = _version(pk, item_id, vid)
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            versions.approve(version, request.user, acknowledge_warnings=serializer.validated_data["acknowledge_warnings"])
        except ValidationFailed as exc:
            return validation_response(exc)
        item = _item(pk, item_id)
        return Response({"version": versions.version_json(version, current_text=item.rendered_text), "item": {"id": item.pk, "status": item.status, "rendered_text": item.rendered_text, "subject": item.subject}})


class VersionRejectView(GrowthView):
    def post(self, request, pk, item_id, vid):
        version = _version(pk, item_id, vid)
        try:
            versions.reject(version, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(versions.version_json(version))
