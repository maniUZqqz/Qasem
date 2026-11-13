# -*- coding: utf-8 -*-
"""«آزمونِ خودکارِ سرورِ پردازش» و خودکارهای گره (۱۴۰۵/۰۸/۲۱) — فقط کارکنان.

    GET  /api/v1/compute/selftests/                   همهٔ گره‌ها: آخرین اجرا + فهرستِ آزمون‌ها + خودکارها + پیشرفتِ کلی
    POST /api/v1/compute/selftests/run/               {node, deep?, only?}  ⇒ اجرای تازه («آزمونِ کامل»)
    GET  /api/v1/compute/selftests/<id>/              یک اجرا با همهٔ نتیجه‌ها
    POST /api/v1/compute/selftests/<id>/rerun/        {key}  ⇒ «دوباره» برای یک آزمون
    GET  /api/v1/compute/selftests/history/?node=     اجراهای اخیر
    GET  /api/v1/compute/progress/                    پیشرفتِ کلیِ صف به تفکیکِ نوعِ کار
    POST /api/v1/compute/nodes/<pk>/bootstrap/        «تلاش دوباره» برای نصبِ نیازمندی‌ها (دستورِ bootstrap)
    POST /api/v1/compute/nodes/<pk>/autostart/        {enabled}  ⇒ شروعِ خودکارِ برنامه هنگامِ روشن شدنِ کامپیوتر
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import autopilot, sched
from . import commands as C
from .models import ComputeNode, ComputeSettings, SelfTestRun
from .selftests import REGISTRY, load_all, runner, tests


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def catalog() -> list[dict]:
    return [{"key": t.key, "label": t.label, "group": t.group, "kind": t.kind, "deep": t.deep, "optional": t.optional,
             "final": t.final, "describe": t.describe, "after": list(t.after)} for t in tests(deep=True)]


def node_block(node: ComputeNode) -> dict:
    run = runner.latest_run(node)
    caps = node.capabilities or {}
    boot = caps.get("bootstrap") or {}
    return {"id": node.pk, "name": node.name, "online": node.online, "enabled": node.enabled, "agent": caps.get("agent"),
            "gpu": caps.get("gpu") or "", "gpu_info": caps.get("gpu_info") or {}, "last_seen": node.last_seen,
            "run": runner.run_json(run) if run else None, "running": bool(run and run.state == SelfTestRun.State.RUNNING),
            "auto": autopilot.status_of(node), "bootstrap": boot, "autostart": caps.get("autostart") or {},
            "autostart_wanted": (node.desired or {}).get("autostart", True) is not False, "outbox": caps.get("outbox") or {},
            "net": caps.get("net") or {}, "lanes": caps.get("lanes") or {}, "can_bootstrap": "bootstrap" in (caps.get("commands") or [])}


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def overview(request):
    load_all()
    cfg = ComputeSettings.get()
    return Response({
        "nodes": [node_block(n) for n in ComputeNode.objects.filter(enabled=True)], "catalog": catalog(),
        "settings": {"auto_update": cfg.auto_update, "auto_selftest": cfg.auto_selftest, "nightly_selftest": cfg.nightly_selftest,
                     "nightly_time": cfg.nightly_time, "requeue_after_pass": cfg.requeue_after_pass, "short_burst": cfg.short_burst},
        "progress": sched.progress_by_kind()})


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def run_detail(request, pk):
    run = get_object_or_404(SelfTestRun, pk=pk)
    return Response(runner.run_json(run))


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def history(request):
    qs = SelfTestRun.objects.select_related("node").order_by("-created_at")
    node = request.query_params.get("node")
    if node and node.isdigit():
        qs = qs.filter(node_id=int(node))
    return Response({"runs": [runner.run_json(r, with_results=False) for r in qs[:30]]})


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def start(request):
    d = _data(request)
    node = get_object_or_404(ComputeNode, pk=d.get("node"))
    if not node.online:
        return Response({"error": "سرورِ پردازش خاموش است؛ آزمون فقط روی سرورِ روشن اجرا می‌شود."}, status=status.HTTP_409_CONFLICT)
    existing = runner.active_run(node)
    only = [str(k) for k in d.get("only") or [] if str(k) in REGISTRY] or None
    run = runner.start_run(node, "deep" if d.get("deep") else "manual", getattr(request.user, "username", "") or "", deep=bool(d.get("deep")), only=only)
    return Response({**runner.run_json(run), "already_running": existing is not None}, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def rerun(request, pk):
    run = get_object_or_404(SelfTestRun, pk=pk)
    key = str(_data(request).get("key") or "")
    if not run.node.online:
        return Response({"error": "سرورِ پردازش خاموش است."}, status=status.HTTP_409_CONFLICT)
    if runner.rerun(run, key) is None:
        raise exceptions.NotFound("آزمونی با این کلید در این اجرا نیست.")
    run.refresh_from_db()
    return Response(runner.run_json(run))


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def progress(request):
    return Response(sched.progress_by_kind())


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_bootstrap_retry(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    try:
        last = C.request(node, "bootstrap", getattr(request.user, "username", "") or "")
    except C.CommandError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"queued": True, "last": last}, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_autostart(request, pk):
    node = get_object_or_404(ComputeNode, pk=pk)
    enabled = bool(_data(request).get("enabled", True))
    desired = dict(node.desired or {})
    desired["autostart"] = enabled
    node.desired = desired
    node.save(update_fields=["desired"])
    return Response({"autostart_wanted": enabled})
