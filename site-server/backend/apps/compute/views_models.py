"""GET /api/v1/compute/models/ — «مدل‌های سرورِ پردازش»: همهٔ بسته‌های دانلودیِ هر گره با وضعیتِ نصب (apps.compute.model_packages).

دانلود از همان مسیرِ همیشگی: POST /api/v1/compute/nodes/<id>/models/download/ {packages, when}.
"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import model_packages


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def models_listing(request):
    return Response(model_packages.listing())
