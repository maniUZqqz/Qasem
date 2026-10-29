"""به‌روزرسانیِ کدِ سرورهای پردازش از خودِ سایت (بی git و بی GitHub) — توضیح در updates.py.

    GET  /api/v1/compute/update/              فهرستِ بسته (توکنِ گره یا کارمند)
    GET  /api/v1/compute/update/package/      زیپِ بسته (توکنِ گره یا کارمند؛ پنل با blob دانلود می‌کند)
    POST /api/v1/compute/nodes/<pk>/update/   (کارمند) کارِ node.update برای همان گره
"""
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.settings import api_settings

from . import updates as U
from .api import NodeAuth, node_json
from .models import ComputeNode


def _node_or_staff(request):
    if isinstance(request.auth, ComputeNode):
        return
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_staff):
        raise exceptions.NotAuthenticated("فقط سرورِ پردازش (توکنِ گره) یا کارکنان")


def _both(fn):
    return api_view(["GET"])(authentication_classes([NodeAuth] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES))(
        permission_classes([permissions.AllowAny])(throttle_classes([])(fn))))


@_both
def manifest(request):
    _node_or_staff(request)
    try:
        m = U.current_manifest()
    except FileNotFoundError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({k: v for k, v in m.items() if k != "fingerprint"})


@_both
def package(request):
    _node_or_staff(request)
    try:
        path = U.package_path((request.query_params.get("zip") or "").strip().lower() or None)
        m = U.current_manifest()
    except FileNotFoundError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if path is None or not path.is_file():
        return Response({"error": "this build is gone - ask for the manifest again"}, status=status.HTTP_410_GONE)
    resp = FileResponse(open(path, "rb"), as_attachment=True, filename="processing-server-%s.zip" % m.get("version", ""),
                        content_type="application/zip")
    resp["Cache-Control"] = "no-store"
    return resp


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_update(request, pk):
    """«به‌روزرسانی» ِ پنل: کارِ node.update در صفِ همان گره (اگر خاموش است، وقتی روشن شد انجام می‌شود)."""
    from . import services as SV

    node = get_object_or_404(ComputeNode, pk=pk)
    st = U.update_state(node.capabilities or {})
    if (node.capabilities or {}).get("agent") and not st["can_remote_update"]:
        return Response({"error": "عاملِ این سرور (%s) به‌روزرسانی از راهِ دور ندارد (از نسخهٔ ۲٫۰): یک بار بستهٔ تازه را از "
                                  "همین صفحه دانلود کنید، در پوشه‌ای تازه باز کنید و START.bat را بزنید — مدل‌ها خودشان "
                                  "منتقل می‌شوند." % node.capabilities.get("agent")}, status=status.HTTP_409_CONFLICT)
    job = SV.enqueue("node.update", {}, origin="panel", priority=20, timeout_s=900, node=node.name, dedupe=False,
                     require_online=False)
    return Response({"job": str(job.uid), "node": node_json(node)}, status=status.HTTP_202_ACCEPTED)
