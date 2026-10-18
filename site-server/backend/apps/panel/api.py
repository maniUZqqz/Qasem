"""GET /api/v1/panel/flags/ — وضعیتِ دسته‌ها/صفحه‌ها/قابلیت‌های پنل برای کاربرِ واردشده.

پاسخ هم درختی است (برای منو) و هم تخت (برای گِیت‌ها):
  {"sections": [...], "pages": {"analytics": true, ...}, "features": {"studio.video": false, ...}}
چیزی که در دیتابیس نیست در این فهرست هم نیست ⇒ فرانت آن را فعال فرض می‌کند.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PanelSection


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def flags(request):
    staff = bool(request.user.is_staff)
    sections, pages, features = [], {}, {}
    qs = PanelSection.objects.prefetch_related("pages__features").order_by("order", "key")
    for s in qs:
        s_on = s.enabled and (staff or not s.staff_only)
        node = {"key": s.key, "title": s.title, "enabled": s_on, "pages": []}
        for p in s.pages.all():
            p_on = s_on and p.enabled and (staff or not p.staff_only)
            pages[p.key] = p_on
            pnode = {"key": p.key, "title": p.title, "path": p.path, "enabled": p_on, "features": []}
            for f in p.features.all():
                f_on = p_on and f.enabled
                features[f.key] = f_on
                pnode["features"].append({"key": f.key, "title": f.title, "enabled": f_on})
            node["pages"].append(pnode)
        sections.append(node)
    return Response({"sections": sections, "pages": pages, "features": features})
