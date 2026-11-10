# -*- coding: utf-8 -*-
"""«دستورها» ِ سرورِ پردازش (۱۴۰۵/۰۸/۱۹) — منطق در commands.py.

    GET  /api/v1/compute/nodes/<pk>/commands/   (کارمند) وضعیت: پشتیبانی، آخرین دستور و خروجی
    POST /api/v1/compute/nodes/<pk>/commands/   (کارمند) {action: status|update|restart|build|logs}
    POST /api/v1/compute/commands/<id>/         (توکنِ گره) {state: running|done, ok, output}
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response

from . import commands as C
from .api import NodeAuth
from .models import ComputeNode


@api_view(["GET", "POST"])
@permission_classes([permissions.IsAdminUser])
def node_commands(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    if request.method == "GET":
        return Response(C.state(node))
    action = str((request.data or {}).get("action") or "").strip()
    try:
        last = C.request(node, action, getattr(request.user, "username", "") or "")
    except C.CommandError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"queued": True, "last": last}, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@authentication_classes([NodeAuth])
@permission_classes([permissions.AllowAny])
@throttle_classes([])
def command_report(request, cid):
    if not isinstance(request.auth, ComputeNode):
        raise exceptions.NotAuthenticated("فقط با توکنِ سرورِ پردازش")
    d = request.data or {}
    ok = C.report(request.auth, cid, str(d.get("state") or ""), ok=d.get("ok"), output=str(d.get("output") or ""))
    return Response({"ok": ok})
