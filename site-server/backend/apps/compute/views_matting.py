"""«جداسازیِ پس‌زمینه» برای کارکنان: وضعیتِ سه مدل روی گره‌ها، دانلود (با زمان‌بندی) و تست. ادیتورِ عکس از خودِ ماژولِ
`apps.compute.matting` استفاده می‌کند؛ این‌ها همان‌ها را برای پنلِ سرورهای پردازش باز می‌کنند."""
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import matting, queue as QV
from .models import ComputeJob


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def matting_status(request):
    return Response(matting.status())


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def matting_download(request):
    """POST {models: ["u2netp", ...], node?: "gpu-1", when?: {mode: "default|now|at|window", time: "03:30"}} ⇒ کارِ دانلود (در صف)."""
    data = request.data if isinstance(request.data, dict) else {}
    try:
        job = matting.start_download(data.get("models") or ([data["model"]] if data.get("model") else []),
                                     node=str(data.get("node") or ""), when=data.get("when"))
    except matting.MattingError as exc:
        return Response({"error": str(exc)}, status=exc.status)
    return Response({"job": QV.one(job), **matting.status()}, status=202)


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def matting_test(request):
    """POST {model, node?} ⇒ گره مدل را روی یک عکسِ آزمایشی می‌سنجد (کارِ photo.matting با bench)؛ تا نصب شدنِ مدل در صف می‌ماند."""
    data = request.data if isinstance(request.data, dict) else {}
    try:
        job = matting.start_test(str(data.get("model") or ""), node=str(data.get("node") or ""))
    except matting.MattingError as exc:
        return Response({"error": str(exc)}, status=exc.status)
    return Response({"job": QV.one(job)}, status=202)
