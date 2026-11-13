"""GET /api/v1/compute/models/ — «مدل‌های سرورِ پردازش»: همهٔ بسته‌های دانلودیِ هر گره با وضعیتِ نصب (apps.compute.model_packages)
و مدل‌های Ollama کنارشان؛ GET|POST /api/v1/compute/models/auto/ — «دانلودِ خودکار» (apps.compute.auto_models).

دانلود از همان مسیرِ همیشگی: POST /api/v1/compute/nodes/<id>/models/download/ {packages, when}.
"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import auto_models, model_packages


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def models_listing(request):
    return Response(model_packages.listing())


@api_view(["GET", "POST"])
@permission_classes([permissions.IsAdminUser])
def models_auto(request):
    """GET ⇒ تنظیمِ «دانلودِ خودکار»؛ POST {enabled?, reserve_gb?, features?: {کلید: bool}} ⇒ ذخیره و همان نما."""
    if request.method == "POST":
        try:
            auto_models.save(request.data if isinstance(request.data, dict) else {})
        except auto_models.AutoError as exc:
            return Response({"error": str(exc)}, status=400)
    return Response(auto_models.view())
