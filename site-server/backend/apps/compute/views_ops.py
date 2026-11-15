"""«عملیاتِ سرور» برای پنل (فقط کارکنان): آخرین بکاپ + آزمون‌های شبانهٔ سایت. GET /api/v1/compute/ops/"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import ops_status


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def ops(request):
    return Response(ops_status.ops_status())
