# -*- coding: utf-8 -*-
"""«امشب: روشن کردنِ سرورِ پردازش» + «درخواست‌های هوش مصنوعیِ صف‌دار».

    GET  /api/v1/compute/tonight/?node=            گزارشِ زنده (tonight.py)؛ فقط کارکنان
    POST /api/v1/compute/tonight/retry/            {what: update|bootstrap|selftest|requeue|kick, node?}
    GET  /api/v1/compute/deferred/<uid>/           وضعیت/نتیجهٔ یک درخواستِ صف‌دار (صاحبِ فروشگاه یا کارمند)
    POST /api/v1/compute/deferred/<uid>/cancel/    لغو
"""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import deferred, tonight


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def tonight_report(request):
    pk = request.query_params.get("node")
    return Response(tonight.build(int(pk) if pk and pk.isdigit() else None))


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def tonight_retry(request):
    d = request.data if isinstance(request.data, dict) else {}
    pk = d.get("node")
    what = str(d.get("what") or "")
    if what not in tonight.RETRY:
        return Response({"ok": False, "message": "کارِ ناشناخته."}, status=status.HTTP_400_BAD_REQUEST)
    out = tonight.retry(what, int(pk) if str(pk or "").isdigit() else None, getattr(request.user, "username", "") or "")
    return Response(out, status=status.HTTP_200_OK)             # {ok: false, message} هم ۲۰۰ است: پیامِ فارسی را صفحه نشان می‌دهد


def _allowed(request, uid) -> bool:
    found, sid = deferred.owner_of(uid)
    if not found:
        return False
    if request.user.is_staff:
        return True
    if sid is None:
        return False                       # درخواستِ سطحِ پلتفرم: فقط کارکنان
    try:
        from apps.stores import access

        access.get_store(request.user, sid, access.CONTENT, write=False)
        return True
    except Exception:  # noqa: BLE001 - not a member of this store
        return False


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def deferred_status(request, uid):
    if not _allowed(request, uid):
        return Response({"error": {"code": "not_found", "message": "پیدا نشد."}}, status=status.HTTP_404_NOT_FOUND)
    doc = deferred.status(uid)
    if doc is None:
        return Response({"error": {"code": "not_found", "message": "این درخواست دیگر در صف نیست."}}, status=status.HTTP_404_NOT_FOUND)
    return Response(doc)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def deferred_cancel(request, uid):
    if not _allowed(request, uid):
        return Response({"error": {"code": "not_found", "message": "پیدا نشد."}}, status=status.HTTP_404_NOT_FOUND)
    return Response({"cancelled": deferred.cancel(uid)})
