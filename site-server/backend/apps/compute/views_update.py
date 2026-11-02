"""به‌روزرسانیِ کدِ سرورهای پردازش از خودِ سایت (بی git و بی GitHub) — توضیح در updates.py.

    GET  /api/v1/compute/update/              فهرستِ بسته (توکنِ گره یا کارمند)
    GET  /api/v1/compute/update/package/      زیپِ بسته (توکنِ گره یا کارمند؛ پنل با blob دانلود می‌کند)؛ با Range ادامه‌پذیر
    GET  /api/v1/compute/update/Update.bat    فایلِ Update.bat (همگانی، بی راز): پوشهٔ هر نسخه را با یک دابل‌کلیک به‌روز می‌کند
    GET  /api/v1/compute/update/bootstrap/    زیپِ کوچکِ ابزارِ به‌روزرسانی که Update.bat هر بار می‌گیرد (همگانی، بی راز)؛
                                              ?info=1 فقط {sha256, size, version}
    GET  /api/v1/compute/downloads/?name=...  اندازه و sha256 ِ فایلِ بزرگِ سایت (توکنِ گره یا کارمند) برای سنجشِ دانلود
    POST /api/v1/compute/nodes/<pk>/update/   (کارمند) کارِ node.update برای همان گره
"""
import re

from django.http import HttpResponse, StreamingHttpResponse
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


def _public(fn):
    """بی ورود: فقط چیزهایی که راز ندارند (خودِ Update.bat و سه فایلِ کوچکِ ابزار)."""
    return api_view(["GET"])(authentication_classes([])(permission_classes([permissions.AllowAny])(throttle_classes([])(fn))))


def _iter_file(path, start, end, chunk=256 * 1024):
    with open(path, "rb") as fh:
        fh.seek(start)
        left = end - start + 1
        while left > 0:
            b = fh.read(min(chunk, left))
            if not b:
                break
            left -= len(b)
            yield b


def ranged_file(request, path, content_type, filename):
    """فایل را با پشتیبانی از «Range: bytes=a-b» می‌دهد (۲۰۶ + Content-Range) تا دانلودِ قطع‌شده از همان‌جا ادامه پیدا کند؛
    Range نامعتبر ⇒ کلِ فایل، Range بیرون از فایل ⇒ ۴۱۶."""
    size = path.stat().st_size
    start, end, code = 0, size - 1, 200
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (request.META.get("HTTP_RANGE") or "").strip())
    if m and (m.group(1) or m.group(2)):
        a, b = m.groups()
        if a == "":
            start, end = max(0, size - int(b)), size - 1
        else:
            start = int(a)
            end = min(size - 1, int(b)) if b else size - 1
        if size == 0 or start >= size or start > end:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = "bytes */%d" % size
            return resp
        code = 206
    resp = StreamingHttpResponse(_iter_file(path, start, end), status=code, content_type=content_type)
    resp["Content-Length"] = str(end - start + 1)
    resp["Accept-Ranges"] = "bytes"
    resp["Content-Disposition"] = 'attachment; filename="%s"' % filename
    if code == 206:
        resp["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    resp["Cache-Control"] = "no-store"
    return resp


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
    return ranged_file(request, path, "application/zip", "processing-server-%s.zip" % m.get("version", ""))


@_public
def update_bat(request):
    """Update.bat برای دانلود (همگانی): خودش هیچ توکنی ندارد؛ نشانیِ سایت را از node.json/site.json می‌خواند و بسته را با
    توکنِ همان کامپیوتر می‌گیرد."""
    try:
        body = U.update_bat_bytes()
    except FileNotFoundError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    resp = HttpResponse(body, content_type="application/octet-stream")
    resp["Content-Disposition"] = 'attachment; filename="Update.bat"'
    resp["Cache-Control"] = "no-store"
    return resp


@_public
def bootstrap(request):
    try:
        info = U.bootstrap()
    except FileNotFoundError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if request.query_params.get("info"):
        return Response({k: v for k, v in info.items() if k != "path"})
    from pathlib import Path
    resp = ranged_file(request, Path(info["path"]), "application/zip", "nm-update-tool.zip")
    resp["X-NM-SHA256"] = info["sha256"]
    return resp


@_both
def downloads(request):
    """?name=blender-windows.zip ⇒ {name, size, sha256}؛ بی name ⇒ فهرستِ فایل‌ها با اندازه."""
    _node_or_staff(request)
    name = (request.query_params.get("name") or "").strip()
    if not name:
        return Response({"files": U.list_downloads()})
    info = U.download_info(name)
    if info is None:
        return Response({"error": "no such file"}, status=status.HTTP_404_NOT_FOUND)
    return Response(info)


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def node_update(request, pk):
    """«به‌روزرسانی» ِ پنل: کارِ node.update در صفِ همان گره (اگر خاموش است، وقتی روشن شد انجام می‌شود)."""
    from . import services as SV

    node = get_object_or_404(ComputeNode, pk=pk)
    st = U.update_state(node.capabilities or {})
    if (node.capabilities or {}).get("agent") and not st["can_remote_update"]:
        return Response({"error": "عاملِ این سرور (%s) به‌روزرسانی از راهِ دور ندارد (از نسخهٔ ۲٫۰): فایلِ Update.bat را از "
                                  "پنل (ثبتِ سرورِ تازه ← «دانلودِ Update.bat») بگیرید، کنارِ START.bat همان پوشه بگذارید و دو بار "
                                  "کلیک کنید — مدل‌ها دوباره دانلود نمی‌شوند و شناسنامهٔ سرور می‌ماند."
                         % node.capabilities.get("agent")}, status=status.HTTP_409_CONFLICT)
    job = SV.enqueue("node.update", {}, origin="panel", priority=20, timeout_s=900, node=node.name, dedupe=False,
                     require_online=False)
    return Response({"job": str(job.uid), "node": node_json(node)}, status=status.HTTP_202_ACCEPTED)
