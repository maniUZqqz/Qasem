"""ماسکوت — API پنل (همه زیرِ ``stores/<id>/mascot/``).

    GET    /                       ⇐ نقش‌ها، گزینه‌ها (۲۹ ژست، ۸ حالت، ۱۷ پس‌زمینه، ۴ اندازه)، جمله‌های پیشنهادی، ماسکوت‌های فروشگاه
    POST   /                       ⇐ {role، name، use_logo، brand_colours} ⇒ ماسکوتِ تازه (رنگ‌ها و لوگو از برندِ فروشگاه)
    GET · PATCH · DELETE <id>/     ⇐ ظاهر (spec)، نام، نقش، رنگِ برند؛ PATCH فقط وقتی قفل نیست
    POST   <id>/lock/ · unlock/    ⇐ تأییدِ ظاهر (نسخه +۱) / بازکردنِ قفل
    POST   <id>/preview/           ⇐ {pose، expression، background، size، bubble، caption، spec?} ⇒ پیش‌نمایشِ سریعِ ذخیره‌نشده
    POST   <id>/render/            ⇐ همان گزینه‌ها ⇒ پست/استوریِ کامل (کَش‌دار؛ در کتابخانهٔ ادیتورِ عکس هم هست)
    POST   <id>/sticker/           ⇐ {pose، expression، prop، crop} ⇒ استیکرِ PNG شفاف
    POST   <id>/sheet/             ⇐ برگهٔ مدل
    POST   <id>/check/             ⇐ بررسیِ ثباتِ همهٔ ژست‌ها × ۴ اندازه
    GET    <id>/shots/?kind=       ⇐ خروجی‌های ساخته‌شده · GET/DELETE shots/<rid>/ · GET shots/<rid>/download/
"""
from __future__ import annotations

import logging

from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.photoedit import services as photo
from apps.stores import access

from . import services
from .models import Mascot, MascotRender

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "mascot", http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http)


def _store(request, store_id, write: bool = True):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


def _mascot(store, pk) -> Mascot | None:
    return Mascot.objects.filter(store=store, pk=pk).select_related("store").first()


def _not_found():
    return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _run(fn, *args):
    """MascotError ⇒ ۴۰۰؛ ادعا ⇒ ۴۲۲ با فهرستِ ادعاها (تا صفحه «این ادعا را خودم تأیید کرده‌ام» را نشان بدهد)."""
    try:
        return fn(*args), None
    except services.ClaimsError as exc:
        return None, _err(str(exc), "claims", status.HTTP_422_UNPROCESSABLE_ENTITY, found=exc.found)
    except (services.MascotError, photo.PhotoError) as exc:
        return None, _err(str(exc))


def _render_response(out):
    row, cached = out
    return Response(services.render_dict(row, cached=cached), status=status.HTTP_200_OK if cached else status.HTTP_201_CREATED)


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response(services.overview(store))

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        brand = d.get("brand_colours") if isinstance(d.get("brand_colours"), list) else None
        m, err = _run(lambda: services.create(store, request.user, role=str(d.get("role") or "coach"), name=str(d.get("name") or ""),
                                              use_logo=bool(d.get("use_logo", True)), brand=brand))
        return err or Response(services.mascot_dict(m), status=status.HTTP_201_CREATED)


class MascotView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        m = _mascot(store, pk)
        return Response(services.mascot_dict(m)) if m else _not_found()

    def patch(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        out, err = _run(services.update, m, _body(request))
        return err or Response(services.mascot_dict(out))

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        m.delete()                                    # عکس‌های کتابخانه می‌مانند (مالکِ فروشگاه خودش پاک می‌کند)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LockView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        return Response(services.mascot_dict(services.lock(m))) if m else _not_found()


class UnlockView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        return Response(services.mascot_dict(services.unlock(m))) if m else _not_found()


class PreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        out, err = _run(services.preview, m, _body(request))
        return err or Response(out)


class RenderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        out, err = _run(services.render_shot, m, request.user, _body(request))
        return err or _render_response(out)


class StickerView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        out, err = _run(services.render_sticker, m, request.user, _body(request))
        return err or _render_response(out)


class SheetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        out, err = _run(services.render_sheet, m, request.user)
        return err or _render_response(out)


class CheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        out, err = _run(services.run_check, m)
        return err or Response(out)


class ShotListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        m = _mascot(store, pk)
        if m is None:
            return _not_found()
        qs = m.renders.select_related("asset")
        kind = request.query_params.get("kind")
        if kind in ("shot", "sticker", "sheet"):
            qs = qs.filter(kind=kind)
        try:
            limit = max(1, min(100, int(request.query_params.get("limit") or 40)))
        except ValueError:
            limit = 40
        return Response({"items": [services.render_dict(r) for r in qs[:limit]]})


def _render(store, pk, rid) -> MascotRender | None:
    return MascotRender.objects.filter(store=store, mascot_id=pk, pk=rid).select_related("asset", "mascot").first()


class ShotView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, rid):
        store = _store(request, store_id, write=False)
        r = _render(store, pk, rid)
        return Response(services.render_dict(r)) if r else _not_found()

    def delete(self, request, store_id, pk, rid):
        store = _store(request, store_id)
        r = _render(store, pk, rid)
        if r is None:
            return _not_found()
        r.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShotDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, rid):
        store = _store(request, store_id, write=False)
        r = _render(store, pk, rid)
        if r is None or r.asset is None:
            raise Http404()
        p = photo.abs_path(r.asset.original)
        if not p.is_file():
            raise Http404()
        return FileResponse(open(p, "rb"), content_type="image/png", as_attachment=True, filename=f"mascot-{r.kind}-{r.pk}.png")
