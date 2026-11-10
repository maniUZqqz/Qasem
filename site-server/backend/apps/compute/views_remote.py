# -*- coding: utf-8 -*-
"""دسترسیِ راه‌دور به سرورهای پردازش — نماها (۱۴۰۵/۰۸/۱۹). منطق در remote.py.

    POST /api/v1/compute/remote/enroll/        (توکنِ گره) Setup-Remote.bat: کلیدِ تونل ⇒ پورت، کلیدِ مدیر، known_hosts
    GET  /api/v1/compute/remote/check/         (توکنِ گره) «سایت از تونل به من می‌رسد؟»
    GET  /api/v1/compute/nodes/<pk>/remote/    (کارمند)    وضعیتِ تونل + آخرین دستور
    POST /api/v1/compute/nodes/<pk>/control/   (کارمند)    {action: status|stop|start|restart|update|build|logs}
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response

from . import remote as R
from .api import NodeAuth
from .models import ComputeNode


def _node(request) -> ComputeNode:
    if not isinstance(request.auth, ComputeNode):
        raise exceptions.NotAuthenticated("فقط با توکنِ سرورِ پردازش")
    return request.auth


@api_view(["POST"])
@authentication_classes([NodeAuth])
@permission_classes([permissions.AllowAny])
@throttle_classes([])
def remote_enroll(request):
    node = _node(request)
    d = request.data or {}
    try:
        out = R.enroll(node, d.get("pubkey", ""), d.get("user", ""), home=d.get("home", ""),
                       python=d.get("python", ""), windows=d.get("windows", ""))
    except R.RemoteError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(out)


@api_view(["GET"])
@authentication_classes([NodeAuth])
@permission_classes([permissions.AllowAny])
@throttle_classes([])
def remote_check(request):
    return Response(R.check(_node(request)))


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def node_remote(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    return Response(R.state(node))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_control(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    action = str((request.data or {}).get("action") or "").strip()
    by = getattr(request.user, "username", "") or ""
    try:
        row = R.mark_started(node, action, by)
    except R.RemoteError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
    from .tasks import remote_control

    remote_control.apply_async(args=[node.pk, action, by], queue="ai")   # کارگرِ گره‌ها (nm-celery-node)؛ دقیقه‌ای‌ها را نگه ندارد
    return Response({"queued": True, "last": row}, status=status.HTTP_202_ACCEPTED)
