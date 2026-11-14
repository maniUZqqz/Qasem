"""GET /api/v1/compute/readiness/ — «اگر همین حالا گره را روشن کنند چه می‌شود؟» (کارکنان؛ فقط‌خواندنی). نگاه کنید به readiness.py."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import readiness
from .models import ComputeNode


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def readiness_report(request):
    """?node=<pk> فقط همان گره؛ بی آن همهٔ گره‌های فعال."""
    pk = request.query_params.get("node")
    node = get_object_or_404(ComputeNode, pk=int(pk)) if pk and pk.isdigit() else None
    return Response(readiness.report(node))
