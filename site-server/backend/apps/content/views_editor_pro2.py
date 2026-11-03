"""The «دستی» workspace, pro part 2: colour LUTs, motion tracking, multicam sync, background-removal mattes, node-render status. §23.4

    GET  POST   stores/<id>/editor/luts/                    the shop's .cube LUTs / import one (multipart `file`, `title`)
    DELETE      stores/<id>/editor/luts/<key>/              remove one
    GET         stores/<id>/editor/luts/<key>/file/         the .cube text (the browser previews with it)
    POST        stores/<id>/editor/track/                   {ref, s0, s1, region{x,y,w,h}, fps?} → job → the path (samples)
    POST        stores/<id>/editor/multicam/sync/           {refs: [...]} → job → offsets in seconds
    GET         stores/<id>/editor/matte/status/            can background removal run right now (and what is missing)
    GET  POST   stores/<id>/editor/mattes/                  the shop's mattes / {ref, s0, s1, fps?} → job → a matte
    DELETE      stores/<id>/editor/mattes/<key>/            remove one
    GET         stores/<id>/editor/render-where/            is a processing node ready for the final render (and NVENC?)
"""
from __future__ import annotations

import logging

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.editing import luts, mattes, multicam, noderender, tracking
from services.editing import timeline as tl

from . import editor_project
from .tasks_editing import MATTE_NEEDS, MAX_MATTE_SECONDS, matte_status, matte_task, sync_task, track_task

logger = logging.getLogger(__name__)


def _err(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _num(value, name):
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise tl.TimelineError(f"«{name}» عدد نیست.") from None
    if x != x or abs(x) > 1e7:
        raise tl.TimelineError(f"«{name}» درست نیست.")
    return x


class EditorLutsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"luts": luts.listing(store.pk)})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = request.FILES.get("file")
        if upload is None:
            return _err("no_file", "فایلِ .cube را انتخاب کنید.")
        if upload.size > luts.MAX_BYTES:
            return _err("too_big", "فایلِ LUT بزرگ‌تر از ۱۲ مگابایت است.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            row = luts.store(store.pk, upload.read(), str(request.data.get("title") or "")[:60] or upload.name.rsplit(".", 1)[0][:60])
        except tl.TimelineError as exc:
            return _err("bad_lut", str(exc))
        return Response({"lut": row}, status=status.HTTP_201_CREATED)


class EditorLutDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, key):
        store = access.get_store(request.user, store_id, access.CONTENT)
        if not luts.remove(store.pk, key):
            return _err("not_found", "LUT پیدا نشد.", status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EditorLutFileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, key):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        path = luts.path_of(store.pk, key)
        if path is None:
            return _err("not_found", "LUT پیدا نشد.", status.HTTP_404_NOT_FOUND)
        return HttpResponse(path.read_bytes(), content_type="text/plain; charset=utf-8")


class EditorTrackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ref = str(request.data.get("ref") or "")
        try:
            s0, s1 = _num(request.data.get("s0"), "شروع"), _num(request.data.get("s1"), "پایان")
            region = request.data.get("region") if isinstance(request.data.get("region"), dict) else {}
            region = {k: _num(region.get(k), k) for k in ("x", "y", "w", "h")}
            fps = _num(request.data.get("fps") or tracking.DEFAULT_FPS, "نرخ")
            item = editor_project.describe(store, ref)
        except tl.TimelineError as exc:
            return _err("bad_request", str(exc))
        if item["kind"] != "video":
            return _err("not_video", "ردیابی فقط روی ویدیو ممکن است.")
        if s1 <= s0 + 0.2 or s0 < 0:
            return _err("bad_range", "بازهٔ ردیابی درست نیست.")
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "track", "ref": ref})
        failed = dispatch_job(job, track_task, job.id, ref, s0, s1, region, fps)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class EditorSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        refs = request.data.get("refs")
        if not isinstance(refs, list) or not 2 <= len(refs) <= 8 or not all(isinstance(r, str) for r in refs):
            return _err("bad_refs", "برای هم‌زمان‌سازی ۲ تا ۸ ویدیو لازم است.")
        try:
            for ref in refs:
                item = editor_project.describe(store, ref)
                if item["kind"] == "image" or not item["has_audio"]:
                    return _err("no_audio", f"«{item['title']}» صدا ندارد؛ هم‌زمان‌سازی با صدا ممکن نیست.")
        except tl.TimelineError as exc:
            return _err("bad_ref", str(exc), status.HTTP_404_NOT_FOUND)
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "sync", "refs": refs})
        failed = dispatch_job(job, sync_task, job.id, refs)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class MatteStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({**matte_status(), "max_seconds": MAX_MATTE_SECONDS})


class EditorMattesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        rows = []
        for row in mattes.listing(store.pk):
            path = mattes.path_of(store.pk, row["key"])
            rows.append({**row, "url": editor_project._rel_url(path) if path else ""})
        return Response({"mattes": rows})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ref = str(request.data.get("ref") or "")
        try:
            s0, s1 = _num(request.data.get("s0"), "شروع"), _num(request.data.get("s1"), "پایان")
            fps = _num(request.data.get("fps") or 6, "نرخ")
            item = editor_project.describe(store, ref)
        except tl.TimelineError as exc:
            return _err("bad_request", str(exc))
        if item["kind"] != "video":
            return _err("not_video", "حذفِ پس‌زمینه فقط روی ویدیو ممکن است.")
        if s1 <= s0 + 0.3 or s0 < 0:
            return _err("bad_range", "بازه درست نیست.")
        state = matte_status()
        if not state["ok"]:
            return _err("matte_unavailable", state["message"], status.HTTP_503_SERVICE_UNAVAILABLE)
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "matte", "ref": ref})
        failed = dispatch_job(job, matte_task, job.id, ref, s0, min(s1, s0 + MAX_MATTE_SECONDS), fps)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class EditorMatteDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, key):
        store = access.get_store(request.user, store_id, access.CONTENT)
        if not mattes.remove(store.pk, key):
            return _err("not_found", "مات پیدا نشد.", status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RenderWhereView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(noderender.status())
