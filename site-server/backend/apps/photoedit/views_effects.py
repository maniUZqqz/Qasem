"""API ِ «جعبهٔ فیلترها» (نوبت ۴) — کنارِ API ِ ادیتورِ عکس.

    GET   stores/<id>/photo-editor/effects/            فهرستِ فیلترها با مشخصاتِ پارامترها (برای ساختنِ فرم)
    POST  stores/<id>/photo-editor/effects/preview/    multipart {effect, params(JSON), image, mask?} ⇒ PNG ِ کوچک (حداکثر ۹۰۰ پیکسل)
    POST  stores/<id>/photo-editor/effects/apply/      multipart {effect, params, image, mask?, title?} ⇒ عکسِ تازهٔ کتابخانه + مشخصاتِ لایه

هیچ‌چیزِ هوش مصنوعی یا سرورِ پردازش در کار نیست؛ همه روی همین سرور و با کتابخانه‌های نصب‌شده.
"""
from __future__ import annotations

import io
import json
import logging
import threading

from django.http import HttpResponse
from PIL import Image
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import effects, services
from .views import _err

logger = logging.getLogger(__name__)

PREVIEW_SIDE = 900
MAX_UPLOAD = 24 * 1024 * 1024
_slots = threading.BoundedSemaphore(2)          # هر پردازه حداکثر دو فیلترِ هم‌زمان (CPU ِ سرور کم است)


def _read_image(f) -> Image.Image:
    if f is None:
        raise effects.EffectError("تصویر فرستاده نشد.")
    if getattr(f, "size", 0) > MAX_UPLOAD:
        raise effects.EffectError("تصویر خیلی بزرگ است.")
    try:
        im = Image.open(io.BytesIO(f.read()))
        im.load()
    except Exception as exc:  # noqa: BLE001
        raise effects.EffectError("تصویر خوانده نشد.") from exc
    return im.convert("RGBA")


def _params(request) -> dict:
    raw = request.data.get("params") or "{}"
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise effects.EffectError("پارامترها نامعتبر است.") from exc
    return v if isinstance(v, dict) else {}


class EffectsCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"effects": effects.catalog(), "max_side": effects.MAX_SIDE})


class _Base(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def run(self, request, preview: bool):
        eid = str(request.data.get("effect") or "")
        img = _read_image(request.FILES.get("image"))
        mask = None
        if request.FILES.get("mask") is not None:
            mask = _read_image(request.FILES.get("mask")).convert("L")
        p = _params(request)
        if preview and max(img.size) > PREVIEW_SIDE:
            k = PREVIEW_SIDE / max(img.size)
            img = img.resize((max(4, round(img.width * k)), max(4, round(img.height * k))), Image.Resampling.LANCZOS)
        if not _slots.acquire(timeout=60):
            raise effects.EffectError("سرور الان مشغول است؛ چند لحظه بعد دوباره امتحان کنید.")
        try:
            return effects.run(eid, img, p, mask)
        finally:
            _slots.release()


class EffectPreviewView(_Base):
    def post(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        try:
            out, e = self.run(request, True)
        except effects.EffectError as exc:
            return _err(str(exc))
        if out.width * out.height > 1200 * 1200:
            k = 1200 / max(out.size)
            out = out.resize((max(4, round(out.width * k)), max(4, round(out.height * k))), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "PNG", compress_level=2)
        resp = HttpResponse(buf.getvalue(), content_type="image/png")
        resp["Cache-Control"] = "no-store"
        resp["X-Result-Size"] = f"{out.width}x{out.height}"
        return resp


class EffectApplyView(_Base):
    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        try:
            out, e = self.run(request, False)
        except effects.EffectError as exc:
            return _err(str(exc))
        except MemoryError:
            return _err("حافظهٔ سرور برای این اندازه کم است؛ عکس کوچک‌تری بدهید.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("photoedit.effects: %s failed", request.data.get("effect"))
            return _err(f"فیلتر اجرا نشد: {exc}")
        buf = io.BytesIO()
        out.save(buf, "PNG", compress_level=3)
        title = str(request.data.get("title") or e.title)[:120]
        try:
            asset = services._asset_from_bytes(store, request.user, buf.getvalue(), title=title, source_ref=f"fx:{e.id}")
        except services.PhotoError as exc:
            return _err(str(exc))
        return Response({"asset": services.asset_dict(asset), "effect": e.id, "kind": e.kind, "blend": e.blend, "title": e.title,
                         "size": [out.width, out.height]}, status=status.HTTP_201_CREATED)
