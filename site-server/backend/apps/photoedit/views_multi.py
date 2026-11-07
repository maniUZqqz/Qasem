"""کارهای چندعکسی (دورِ ۸) — API. منطق در ``multi``.

    POST stores/<id>/photo-editor/multi/contact-sheet/  {assets, cols, cell, labels, bg} ⇒ {asset}
    POST stores/<id>/photo-editor/multi/merge/          {assets, kind: "hdr"|"panorama"} ⇒ {asset}
    POST stores/<id>/photo-editor/multi/processor/      {assets, sizes:[{w,h}], fmt, quality, fit, no_upscale} ⇒ فایلِ zip
    POST stores/<id>/photo-editor/multi/action/         {preset, asset} ⇒ {asset}   (برای چند عکس: مرورگر عکس‌به‌عکس صدا می‌زند)
"""
from __future__ import annotations

from urllib.parse import quote

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import multi, services
from .models import PhotoPreset
from .views import _asset, _err, _not_found


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class ContactSheetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        d = request.data
        try:
            a = multi.contact_sheet(store, request.user, d.get("assets"), _int(d.get("cols"), 5), _int(d.get("cell"), 300), bool(d.get("labels", True)), str(d.get("bg") or "#ffffff"))
        except services.PhotoError as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است؛ خانه‌ها را کوچک‌تر کنید.")
        return Response({"asset": services.asset_dict(a)}, status=status.HTTP_201_CREATED)


class MergeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        kind = str(request.data.get("kind") or "")
        fn = {"hdr": multi.hdr_merge, "panorama": multi.panorama}.get(kind)
        if fn is None:
            return _err("نوعِ ادغام باید «hdr» یا «panorama» باشد.")
        try:
            a = fn(store, request.user, request.data.get("assets"))
        except services.PhotoError as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است؛ عکس‌های کوچک‌تر یا کمتر بدهید.")
        return Response({"asset": services.asset_dict(a)}, status=status.HTTP_201_CREATED)


class ProcessorView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        d = request.data
        try:
            data, n = multi.processor_zip(store, d.get("assets"), d.get("sizes") or [], str(d.get("fmt") or "jpeg"), _int(d.get("quality"), 90),
                                          str(d.get("fit") or "contain"), bool(d.get("no_upscale", True)))
        except services.PhotoError as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است؛ عکس‌های کمتر بدهید.")
        name = "photos-sizes.zip"
        resp = HttpResponse(data, content_type="application/zip")
        resp["Content-Disposition"] = f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"
        resp["X-File-Count"] = str(n)
        resp["Cache-Control"] = "no-store"
        return resp


class ActionRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        p = PhotoPreset.objects.filter(pk=_int(request.data.get("preset"), 0), store=store, kind="action").first()
        if p is None:
            return _err("این اکشن پیدا نشد (در «ویرایش ‹ اکشن» ساخته و ذخیره می‌شود).")
        try:
            a = multi.run_action(store, request.user, asset, p.data or {}, p.name)
        except services.PhotoError as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است.")
        return Response({"asset": services.asset_dict(a)}, status=status.HTTP_201_CREATED)


# ───────────────────────────── ابزارهای رنگ و انتخابِ خودکار (colortools)

def _float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class SelectAutoView(APIView):
    """POST {asset, kind: "sky"|"focus"} ⇒ ماسکِ PNG (سفید = انتخاب‌شده) هم‌نسبتِ عکس — «انتخابِ آسمان» و «ناحیهٔ تمرکز»."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        from . import colortools

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        try:
            data = colortools.mask_bytes(str(request.data.get("kind") or ""), services.preview_source(asset))
        except (colortools.ColorToolError, services.PhotoError) as exc:
            return _err(str(exc))
        resp = HttpResponse(data, content_type="image/png")
        resp["Cache-Control"] = "no-store"
        return resp


def _full_source(asset):
    from PIL import Image as _I

    from . import ops

    try:
        img = ops.load(services.abs_path(asset.original))
    except ops.OpError as exc:
        raise services.PhotoError(f"«{asset.title}»: {exc}") from exc
    img.thumbnail((4096, 4096), _I.Resampling.LANCZOS)
    return img


class LutApplyView(APIView):
    """POST multipart {asset, lut (.cube), strength?} ⇒ {asset} — عکسِ تازه با LUT."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, store_id):
        from . import colortools, multi

        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        f = request.FILES.get("lut")
        if f is None:
            return _err("فایلِ LUT (.cube) را بدهید.")
        if f.size > colortools.CUBE_MAX_BYTES:
            return _err("فایلِ LUT بزرگ‌تر از ۶ مگابایت است.")
        try:
            lut = colortools.parse_cube(f.read())
            out = colortools.apply_lut(_full_source(asset), lut, _float(request.data.get("strength"), 1.0))
            a = multi._store_image(store, request.user, out, f"{asset.title} — LUT", "png" if out.mode == "RGBA" else "jpeg", 92)
        except (colortools.ColorToolError, services.PhotoError) as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است.")
        return Response({"asset": services.asset_dict(a)}, status=status.HTTP_201_CREATED)


class MatchColorView(APIView):
    """POST {asset, reference, strength?, keep_luma?} ⇒ {asset} — رنگِ عکسِ مرجع روی عکس."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        from . import colortools, multi

        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        ref = _asset(store, request.data.get("reference"))
        if asset is None or ref is None:
            return _not_found()
        if asset.pk == ref.pk:
            return _err("عکسِ مرجع باید غیر از همین عکس باشد.")
        try:
            out = colortools.match_color(_full_source(asset), services.preview_source(ref), _float(request.data.get("strength"), 1.0), _float(request.data.get("keep_luma"), 0.0))
            a = multi._store_image(store, request.user, out, f"{asset.title} — رنگ از «{ref.title}»"[:200], "png" if out.mode == "RGBA" else "jpeg", 92)
        except (colortools.ColorToolError, services.PhotoError) as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است.")
        return Response({"asset": services.asset_dict(a)}, status=status.HTTP_201_CREATED)
