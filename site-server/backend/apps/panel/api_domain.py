"""GET /api/v1/panel/domain/ و POST /api/v1/panel/domain/check/ — کارتِ ادمینِ «دامنه و SSL» (فقط کارکنان، فقط خواندنی)."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from . import domain_core, domain_status


@api_view(["GET"])
@permission_classes([IsAdminUser])
def domain_state(request):
    """وضعیتِ فعلی: فقط IP، یا دامنه + گواهی (انقضا) + DNS + هشدارها."""
    return Response(domain_status.status())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def domain_check(request):
    """{"domain": "example.ir", "www": true} ⇒ DNS را می‌سنجد (فقط resolve؛ هیچ تغییری نمی‌دهد) و می‌گوید چه رکوردی بسازید."""
    raw = str(request.data.get("domain") or "")
    www = request.data.get("www", True) not in (False, "false", "0", 0)
    try:
        return Response(domain_status.check_dns(raw, www))
    except domain_core.DomainError as exc:
        return Response({"detail": str(exc), "code": "bad_domain"}, status=400)
