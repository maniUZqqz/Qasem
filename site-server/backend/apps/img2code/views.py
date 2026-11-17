# -*- coding: utf-8 -*-
"""API ِ «تصویر به کد» (پنل › ابزارها).

    GET    stores/<id>/image-to-code/                       گزینه‌ها + وضعیتِ موتور + تاریخچهٔ فروشگاه (تبدیل‌های در جریان تازه می‌شوند)
    POST   stores/<id>/image-to-code/                       بارگذاری (multipart: image) یا نشانی (json: url) ⇒ ساختنِ کارِ پس‌زمینه
    GET    stores/<id>/image-to-code/<pk>/                  یک تبدیل (+ امتیازهای فارسی)
    DELETE stores/<id>/image-to-code/<pk>/                  حذفِ تبدیل و فایل‌هایش
    POST   stores/<id>/image-to-code/<pk>/cancel/           لغو
    POST   stores/<id>/image-to-code/<pk>/again/            همان تصویر با حالت/زبانِ دیگر
    GET    stores/<id>/image-to-code/<pk>/code/             {html, css, tree} برای نمایشِ کد
    GET    stores/<id>/image-to-code/<pk>/files/<name>      original.png، rendered.png، index.html، tree.json، result.zip …
    GET    stores/<id>/image-to-code/<pk>/site-targets/     (کارکنان) پروژه‌های سایت‌ساز که به فروشگاه وصل‌اند
    POST   stores/<id>/image-to-code/<pk>/site-draft/       (کارکنان) {project?: slug} ⇒ ساختِ پیش‌نویسِ صفحه در سایت‌ساز
    POST   stores/<id>/image-to-code/<pk>/ui-design/        سندِ UI/UX در استودیوی طراحی (اگر روشن باشد) ⇒ {doc_id, url}

مجوز: دیدن = دسترسیِ خواندنِ «محتوا» در فروشگاه؛ ساختن/حذف/لغو = دسترسیِ نوشتنِ «محتوا»؛ پیش‌نویسِ سایت‌ساز فقط کارکنان (سایت‌ساز ابزارِ کارکنان است).
"""
from __future__ import annotations

import logging

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import services, sitedraft, uidesign
from .models import Conversion

log = logging.getLogger(__name__)


def _err(message: str, code: str = "img2code", http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _store(request, store_id, write=False):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, store_id):
        store = _store(request, store_id)
        rows = list(Conversion.objects.filter(store=store).order_by("-created_at", "-id")[:60])
        return Response({"items": [services.item_dict(c) for c in rows], "options": services.options(), "engine": services.engine_status(),
                         "can_draft": bool(getattr(request.user, "is_staff", False)), "steps": [{"key": k, "label": l} for k, l in services.STEPS]})

    def post(self, request, store_id):
        store = _store(request, store_id, write=True)
        data = request.data
        mode = data.get("mode") or "responsive"
        lang = data.get("lang") or "auto"
        title = str(data.get("title") or "")[:160]
        eng = services.engine_status()
        if not eng["ready"]:
            return _err("موتورِ «تصویر به کد» روی این سرور هنوز نصب نیست؛ " + (eng["messages"][0] if eng["messages"] else ""), "engine_missing", status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            upload = request.FILES.get("image")
            if upload is not None:
                conv = services.create_upload(store, request.user, upload, mode, lang, title)
            elif str(data.get("url") or "").strip():
                if not eng["url_ok"]:
                    return _err("مرورگرِ بی‌سرِ سرور آماده نیست؛ تصویرِ صفحه را خودتان بارگذاری کنید.", "browser_missing", status.HTTP_503_SERVICE_UNAVAILABLE)
                dom = str(data.get("dom_text", "1")).lower() not in ("0", "false", "no", "off", "")
                conv = services.create_url(store, request.user, data.get("url"), mode, lang, data.get("width") or 1280, dom, title)
            else:
                return _err("تصویر را بارگذاری کنید یا نشانیِ صفحه را بنویسید.", "no_input")
        except services.Img2CodeError as exc:
            return _err(exc.message, exc.code, exc.status)
        conv.refresh_from_db()
        return Response({"item": services.item_dict(conv)}, status=status.HTTP_201_CREATED)


class ItemView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        return Response({"item": services.item_dict(conv, detail=True)})

    def delete(self, request, store_id, pk):
        store = _store(request, store_id, write=True)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        services.delete(conv)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id, write=True)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        services.cancel(conv)
        return Response({"item": services.item_dict(conv)})


class AgainView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id, write=True)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        try:
            new = services.create_again(conv, request.user, request.data.get("mode"), request.data.get("lang"))
        except services.Img2CodeError as exc:
            return _err(exc.message, exc.code, exc.status)
        new.refresh_from_db()
        return Response({"item": services.item_dict(new)}, status=status.HTTP_201_CREATED)


class CodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        if conv.state != Conversion.State.READY:
            return _err("هنوز نتیجه‌ای نیست.", "not_ready", status.HTTP_409_CONFLICT)
        return Response(services.code_payload(conv))


class FileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, name):
        store = _store(request, store_id)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        if name == "result.zip":
            try:
                data = services.zip_bytes(conv)
            except services.Img2CodeError as exc:
                return _err(exc.message, exc.code, exc.status)
            resp = HttpResponse(data, content_type="application/zip")
            resp["Content-Disposition"] = 'attachment; filename="img2code-%d.zip"' % conv.pk
            resp["X-Content-Type-Options"] = "nosniff"
            return resp
        path = services.file_path(conv, name)
        if path is None:
            return _err("این فایل نیست.", "no_file", status.HTTP_404_NOT_FOUND)
        ctype = services.FILES[name][1]
        resp = FileResponse(open(path, "rb"), content_type=ctype)
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "private, max-age=120"
        if not ctype.startswith("image/"):
            # صفحهٔ ساخته‌شده هرگز روی مبدأِ پنل اجرا نمی‌شود؛ فقط دانلود می‌شود
            resp["Content-Disposition"] = 'attachment; filename="%s"' % name
            resp["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return resp


class SiteTargetsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id)
        if not getattr(request.user, "is_staff", False):
            return _err("سایت‌ساز ابزارِ کارکنان است.", "staff_only", status.HTTP_403_FORBIDDEN)
        get_object_or_404(Conversion, pk=pk, store=store)
        return Response({"targets": sitedraft.targets(store)})


class UiDesignView(APIView):
    """«باز کردن در طراحیِ UI»: سندِ UI/UX در استودیوی طراحی می‌سازد (یا همانِ قبلی را برمی‌گرداند)؛ هر عضوی که «محتوا» را می‌نویسد (مثلِ خودِ استودیو)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id, write=True)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        try:
            out = uidesign.create_doc(conv, request.user, force_new=str(request.data.get("new", "")).lower() in ("1", "true", "yes"))
        except services.Img2CodeError as exc:
            return _err(exc.message, exc.code, exc.status)
        conv.refresh_from_db()
        return Response({**out, "item": services.item_dict(conv)}, status=status.HTTP_201_CREATED if out["created"] else status.HTTP_200_OK)


class SiteDraftView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id, write=True)
        if not getattr(request.user, "is_staff", False):
            return _err("سایت‌ساز ابزارِ کارکنان است؛ ساختِ صفحه در آن فقط برای کارکنان باز است.", "staff_only", status.HTTP_403_FORBIDDEN)
        conv = get_object_or_404(Conversion, pk=pk, store=store)
        try:
            out = sitedraft.create_draft(conv, request.user, str(request.data.get("project") or "").strip(), str(request.data.get("title") or "").strip())
        except services.Img2CodeError as exc:
            return _err(exc.message, exc.code, exc.status)
        conv.refresh_from_db()
        return Response({**out, "item": services.item_dict(conv)}, status=status.HTTP_201_CREATED)
