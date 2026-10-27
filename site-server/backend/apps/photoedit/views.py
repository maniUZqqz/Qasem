"""API ِ «ادیتور عکس» (پنل › فروشگاه › محتوا).

    GET    stores/<id>/photo-editor/                          کتابخانه + ابزارها + دستورها + کیت + وضعیتِ سرورِ پردازش
    GET    stores/<id>/photo-editor/sources/                  عکس‌های محصول‌ها و تصویرهای ساخته‌شده
    POST   stores/<id>/photo-editor/assets/                   multipart: files (چندتا) — یا {refs: ["product_image:12", …]}
    GET    stores/<id>/photo-editor/assets/<pk>/              عکس + همهٔ نسخه‌ها
    PATCH  stores/<id>/photo-editor/assets/<pk>/              {title?, product?}
    DELETE stores/<id>/photo-editor/assets/<pk>/
    POST   stores/<id>/photo-editor/assets/<pk>/analyze/      تحلیلِ کیت روی سرورِ پردازش (photo.analyze)
    POST   stores/<id>/photo-editor/plan/                     {asset, recipe} ⇐ کارها با دلیل و تیکِ پیش‌فرض
    POST   stores/<id>/photo-editor/edits/                    {assets: [...], recipe, operations?} ⇐ یک نسخه برای هر عکس
    GET    stores/<id>/photo-editor/edits/?ids=1,2            وضعیت (کارِ گره را هم وارسی می‌کند)
    GET|DELETE stores/<id>/photo-editor/edits/<pk>/
    POST   stores/<id>/photo-editor/edits/<pk>/<cancel|retry|product|content|library>/
    GET    stores/<id>/photo-editor/batches/<batch>/zip/      همهٔ نتیجه‌های آمادهٔ یک «اعمال» در یک zip
"""
from __future__ import annotations

import io
import logging
import zipfile

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import catalog, services
from .models import PhotoAsset, PhotoEdit
from .tasks import finish_edit_task, start_edit_task

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "photoedit", http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _not_found():
    return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)


def _dispatch(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:  # noqa: BLE001 — بی‌بروکر: همین‌جا
        logger.warning("photoedit: celery unavailable, running %s inline", task.name)
        task(*args)


def _nudge(edit: PhotoEdit) -> None:
    """هر بار که پنل می‌پرسد: وضعیتِ کارِ گره را بخوان (اگر poll ِ Celery از دست رفته یا ایستاده باشد هم کار جلو می‌رود)."""
    try:
        if edit.state == PhotoEdit.State.NODE and services.refresh(edit):
            _dispatch(finish_edit_task, edit.pk)
        elif services.recover_stale(edit):
            _dispatch(start_edit_task if edit.state == PhotoEdit.State.QUEUED else finish_edit_task, edit.pk)
    except Exception:  # noqa: BLE001
        logger.exception("photoedit: nudge of edit %s failed", edit.pk)


def _nudge_asset(asset: PhotoAsset) -> None:
    try:
        services.refresh_analysis(asset)
    except Exception:  # noqa: BLE001
        logger.exception("photoedit: analysis refresh of %s failed", asset.pk)


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        for e in PhotoEdit.objects.filter(asset__store=store, state__in=PhotoEdit.ACTIVE).select_related(
                "asset", "asset__store")[:100]:
            _nudge(e)
        assets = PhotoAsset.objects.filter(store=store).select_related("product").order_by("-created_at")[:200]
        active = PhotoEdit.objects.filter(asset__store=store, state__in=PhotoEdit.ACTIVE).select_related("asset")
        return Response({
            "assets": [services.asset_dict(a) for a in assets],
            "active": [services.edit_dict(e) for e in active[:100]],
            "tools": catalog.tool_list(),
            "recipes": catalog.recipe_list(),
            "kit": {"groups": catalog.kit()["groups"], "params": catalog.kit()["params"],
                    "presets": [{k: p[k] for k in ("key", "title", "help", "kind")} for p in catalog.kit()["presets"]]},
            "node": services.node_status(),
            "store_logo": services.media_url(store.logo.name) if getattr(store, "logo", None) else None,
            "limits": {"max_upload_mb": services.MAX_UPLOAD_MB, "max_batch": services.MAX_BATCH},
        })


class SourcesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(services.list_sources(store))


class AssetListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        made, errors = [], []
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if len(files) > services.MAX_BATCH:
            return _err(f"در هر بار حداکثر {services.MAX_BATCH} عکس.")
        for f in files:
            try:
                made.append(services.add_upload(store, request.user, f))
            except services.PhotoError as exc:
                errors.append(str(exc))
        refs = request.data.get("refs") if not files else None
        if isinstance(refs, str):
            refs = [r for r in refs.split(",") if r]
        for ref in (refs or [])[: services.MAX_BATCH]:
            try:
                made.append(services.add_ref(store, request.user, str(ref))[0])
            except services.PhotoError as exc:
                errors.append(str(exc))
        if not made and not errors:
            return _err("عکسی نیامد (فیلدِ files یا refs).")
        code = status.HTTP_201_CREATED if made else status.HTTP_400_BAD_REQUEST
        return Response({"assets": [services.asset_dict(a) for a in made], "errors": errors}, status=code)


class AssetView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return PhotoAsset.objects.filter(pk=pk, store=store).select_related("product", "store").first()

    def get(self, request, store_id, pk):
        a = self._get(request, store_id, pk)
        if a is None:
            return _not_found()
        for e in a.edits.filter(state__in=PhotoEdit.ACTIVE).select_related("asset", "asset__store"):
            _nudge(e)
        _nudge_asset(a)
        return Response({"asset": services.asset_dict(a, edits=True)})

    def patch(self, request, store_id, pk):
        a = self._get(request, store_id, pk, write=True)
        if a is None:
            return _not_found()
        if "title" in request.data:
            a.title = str(request.data.get("title") or "").strip()[:200] or a.title
        if "product" in request.data:
            pid = request.data.get("product")
            try:
                a.product = services._product(a.store, pid) if pid else None
            except services.PhotoError as exc:
                return _err(str(exc))
        a.save()
        return Response({"asset": services.asset_dict(a)})

    def delete(self, request, store_id, pk):
        a = self._get(request, store_id, pk, write=True)
        if a is None:
            return _not_found()
        services.delete_asset(a)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssetAnalyzeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        a = PhotoAsset.objects.filter(pk=pk, store=store).first()
        if a is None:
            return _not_found()
        try:
            services.request_analysis(a)
        except Exception as exc:  # noqa: BLE001
            logger.exception("photoedit: analysis request failed")
            return _err(f"ثبتِ تحلیل نشد: {exc}")
        return Response({"asset": services.asset_dict(a)})


class PlanView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        a = PhotoAsset.objects.filter(pk=request.data.get("asset") or 0, store=store).first()
        if a is None:
            return _not_found()
        try:
            return Response(services.plan(a, str(request.data.get("recipe") or "suggest")))
        except services.PhotoError as exc:
            return _err(str(exc))


class EditListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        qs = PhotoEdit.objects.filter(asset__store=store).select_related("asset", "asset__store")
        ids = [int(x) for x in str(request.query_params.get("ids") or "").split(",") if x.strip().isdigit()][:200]
        if ids:
            qs = qs.filter(pk__in=ids)
        elif request.query_params.get("batch"):
            qs = qs.filter(batch=request.query_params["batch"])
        else:
            qs = qs.filter(state__in=PhotoEdit.ACTIVE)
        edits = list(qs[:200])
        for e in edits:
            if e.active:
                _nudge(e)
                e.refresh_from_db()
        return Response({"edits": [services.edit_dict(e) for e in edits], "node": services.node_status()})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ops = request.data.get("operations")
        try:
            edits = services.create_edits(store, request.user, request.data.get("assets") or [],
                                          str(request.data.get("recipe") or ""), ops if ops is not None else None)
        except services.PhotoError as exc:
            return _err(str(exc))
        for e in edits:
            _dispatch(start_edit_task, e.pk)
        for e in edits:
            e.refresh_from_db()
        return Response({"batch": edits[0].batch, "edits": [services.edit_dict(e) for e in edits],
                         "node": services.node_status()}, status=status.HTTP_201_CREATED)


class EditView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return PhotoEdit.objects.filter(pk=pk, asset__store=store).select_related("asset", "asset__store").first()

    def get(self, request, store_id, pk):
        e = self._get(request, store_id, pk)
        if e is None:
            return _not_found()
        if e.active:
            _nudge(e)
            e.refresh_from_db()
        return Response({"edit": services.edit_dict(e)})

    def delete(self, request, store_id, pk):
        e = self._get(request, store_id, pk, write=True)
        if e is None:
            return _not_found()
        services.delete_edit(e)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def post(self, request, store_id, pk, action):
        e = self._get(request, store_id, pk, write=True)
        if e is None:
            return _not_found()
        extra = {}
        try:
            if action == "cancel":
                services.cancel(e)
            elif action == "retry":
                again = services.create_edits(e.asset.store, request.user, [e.asset_id], e.recipe, e.operations)
                _dispatch(start_edit_task, again[0].pk)
                again[0].refresh_from_db()
                extra["new"] = services.edit_dict(again[0])
            elif action == "product":
                img = services.save_to_product(e, request.data.get("product"), main=bool(request.data.get("main")))
                extra["product_image"] = {"id": img.pk, "product": img.product_id, "url": img.image.url}
            elif action == "content":
                gi = services.use_in_content(e, request.data.get("product"))
                extra["generated_image"] = {"id": gi.pk, "product": gi.product_id, "url": gi.image.url}
            elif action == "library":
                extra["asset"] = services.asset_dict(services.save_to_library(e, request.user))
            else:
                return _err("کارِ ناشناخته.", "bad_action", status.HTTP_404_NOT_FOUND)
        except services.PhotoError as exc:
            return _err(str(exc))
        e.refresh_from_db()
        return Response({"edit": services.edit_dict(e)} | extra)


class BatchZipView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, batch):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        edits = PhotoEdit.objects.filter(asset__store=store, batch=batch, state=PhotoEdit.State.READY).select_related("asset")
        buf = io.BytesIO()
        n = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for e in edits:
                p = services.abs_path(e.files.get("result") or "-")
                if p.is_file():
                    safe = "".join(ch for ch in (e.asset.title or f"photo-{e.asset_id}") if ch not in '\\/:*?"<>|')[:60]
                    z.write(p, f"{n + 1:02d}-{safe}-v{e.number}{p.suffix}")
                    n += 1
        if not n:
            return _err("هنوز نتیجهٔ آماده‌ای نیست.", "empty", status.HTTP_404_NOT_FOUND)
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="photos-{batch[:8]}.zip"'
        return resp
