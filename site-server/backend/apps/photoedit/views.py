"""API ِ «ادیتور عکس» (پنل › فروشگاه › محتوا).

    GET    stores/<id>/photo-editor/                          کتابخانه + ابزارها + دستورها + کیت + وضعیتِ سرورِ پردازش
    GET    stores/<id>/photo-editor/sources/                  عکس‌های محصول‌ها و تصویرهای ساخته‌شده
    POST   stores/<id>/photo-editor/assets/                   multipart: files (چندتا) — یا {refs: ["product_image:12", …]}
    GET    stores/<id>/photo-editor/assets/<pk>/              عکس + همهٔ نسخه‌ها
    PATCH  stores/<id>/photo-editor/assets/<pk>/              {title?, product?}
    DELETE stores/<id>/photo-editor/assets/<pk>/
    POST   stores/<id>/photo-editor/assets/<pk>/analyze/      تحلیلِ کیت روی سرورِ پردازش (photo.analyze)
    POST   stores/<id>/photo-editor/plan/                     {asset, recipe} ⇐ کارها با دلیل و تیکِ پیش‌فرض
    POST   stores/<id>/photo-editor/preview/                  {asset, operations} ⇐ JPEG ِ پیش‌نمایشِ دقیقِ کارهای سرورِ سایت
    POST   stores/<id>/photo-editor/edits/                    {assets: [...], recipe, operations?} ⇐ یک نسخه برای هر عکس
    GET    stores/<id>/photo-editor/edits/?ids=1,2            وضعیت (کارِ گره را هم وارسی می‌کند)
    GET|DELETE stores/<id>/photo-editor/edits/<pk>/
    POST   stores/<id>/photo-editor/edits/<pk>/<cancel|retry|product|content|library>/
    GET    stores/<id>/photo-editor/batches/<batch>/zip/      همهٔ نتیجه‌های آمادهٔ یک «اعمال» در یک zip

    ─── ادیتورِ حرفه‌ای (لایه‌ها، ماسک، پیش‌تنظیم، پیش‌نمایشِ دقیق) ───
    GET|POST  stores/<id>/photo-editor/projects/                 ?asset=ID ⇐ {projects}؛ POST {asset, title?, data?} ⇐ 201 {project}
    GET|PUT|PATCH|DELETE  stores/<id>/photo-editor/projects/<pid>/   {data?, title?, rev?} ⇐ {project}؛ rev کهنه ⇐ 409
    PUT|GET|DELETE  stores/<id>/photo-editor/projects/<pid>/masks/<mid>/   بدنهٔ خامِ عکس یا multipart file ⇐ {id, url, w, h}
    GET|PUT|DELETE  stores/<id>/photo-editor/projects/<pid>/liquify/   نقشهٔ مایع‌سازی (LQF1، ≤ ۲MB) ⇐ PUT {rev, gw, gh}
    POST   stores/<id>/photo-editor/exact/                       {asset, operations, side?} ⇐ {online, state, job?} (کیت روی کپیِ کوچک)
    GET|DELETE  stores/<id>/photo-editor/exact/<uid>/            وضعیت + نشانیِ نتیجه / لغوِ درخواستِ کهنه
    POST   stores/<id>/photo-editor/subject/                     {asset, rect?} ⇐ ماسکِ سوژه (گره یا grabCut)
    GET    stores/<id>/photo-editor/subject/<uid>/
    GET|POST  stores/<id>/photo-editor/presets/                  پیش‌تنظیم‌های شخصی
    PATCH|DELETE  stores/<id>/photo-editor/presets/<id>/         تغییرِ نام/داده، حذف
    POST   stores/<id>/photo-editor/presets/<id>/apply/          {assets: [...]} ⇐ نسخه برای هر عکس (مثلِ edits/)
    GET    stores/<id>/photo-editor/fonts/                       فونت‌های فارسیِ موجود روی سرور
    POST   stores/<id>/photo-editor/genfill/                     multipart {image, mask, asset, prompt?, seed?} ⇐ «پرکردنِ هوشمند» (FLUX) در صف
    GET|DELETE  stores/<id>/photo-editor/genfill/<uid>/          وضعیت (READY ⇐ asset + layer) / لغو
    POST   stores/<id>/photo-editor/genfill/translate/           {prompt} ⇐ ترجمهٔ پیش‌نمایشِ توضیحِ فارسی (state: none|ok|pending|unavailable|failed)
    POST   stores/<id>/photo-editor/genfill/<uid>/prompt/        {prompt_en} ⇐ انگلیسیِ نوشتهٔ کاربر برای کارِ منتظرِ ترجمه (آزادش می‌کند)
"""
from __future__ import annotations

import io
import logging
import zipfile

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import BaseParser, FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import catalog, services
from . import blend as blendmod
from . import layers as layers_mod
from .models import PhotoAsset, PhotoEdit, PhotoPreset, PhotoProject
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
                    "presets": [{k: p[k] for k in ("key", "title", "help", "kind", "recipe") if k in p} for p in catalog.kit()["presets"]]},
            "node": services.node_status(),
            "store_logo": services.media_url(store.logo.name) if getattr(store, "logo", None) else None,
            "limits": {"max_upload_mb": services.MAX_UPLOAD_MB, "max_batch": services.MAX_BATCH},
            "pro": {"blend_modes": list(blendmod.BLEND_MODES), "layer_types": list(layers_mod.LAYER_TYPES),
                    "fonts": services.fonts_list(), "max_layers": layers_mod.MAX_LAYERS},
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


class PreviewView(APIView):
    """POST {asset, operations} ⇐ JPEG ِ پیش‌نمایشِ دقیقِ کارهای سرورِ سایت (کارهای کیت در هدر «skipped» می‌آیند)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        import json
        from urllib.parse import quote

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        a = PhotoAsset.objects.filter(pk=request.data.get("asset") or 0, store=store).select_related("store").first()
        if a is None:
            return _not_found()
        try:
            data, info = services.preview(a, request.data.get("operations") or [])
        except services.PhotoError as exc:
            return _err(str(exc))
        resp = HttpResponse(data, content_type="image/jpeg")
        resp["X-Preview-Info"] = quote(json.dumps(info, ensure_ascii=False))
        resp["Cache-Control"] = "no-store"
        return resp


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
                # «ویرایش با دستور» روی سرورِ سایت: کارها بازنویسی شده‌اند؛ تلاشِ دوباره از اصلِ کارها (دوباره از هوش مصنوعی می‌پرسد).
                # نسخهٔ قدیمی (stats.order نیست ⇒ ۱) عیناً با همان ترتیبِ قدیمی ساخته می‌شود؛ نسخهٔ تازه با ترتیبِ خودش
                again = services.create_edits(e.asset.store, request.user, [e.asset_id], e.recipe,
                                              (e.stats or {}).get("original_operations") or e.operations,
                                              order=int((e.stats or {}).get("order") or 1))
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


# ═════════════════════════════ ادیتورِ حرفه‌ای

class RawParser(BaseParser):
    """بدنهٔ خامِ عکس (image/png …) برای ماسک‌ها."""
    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read(31 * 1024 * 1024) if stream is not None else b""


def _asset(store, pk):
    try:
        return PhotoAsset.objects.filter(pk=int(pk or 0), store=store).select_related("store").first()
    except (TypeError, ValueError):
        return None


class ProjectListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        qs = PhotoProject.objects.filter(store=store).select_related("asset")
        aid = request.query_params.get("asset")
        if aid:
            qs = qs.filter(asset_id=int(aid) if str(aid).isdigit() else 0)
        return Response({"projects": [services.project_dict(p, full=False) for p in qs[:200]]})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        try:
            p = services.create_project(store, asset, str(request.data.get("title") or ""), request.data.get("data"))
        except services.PhotoError as exc:
            return _err(str(exc))
        return Response({"project": services.project_dict(p, migrate=False)}, status=status.HTTP_201_CREATED)


class ProjectView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return PhotoProject.objects.filter(pk=pk, store=store).select_related("asset", "store").first()

    def get(self, request, store_id, pk):
        p = self._get(request, store_id, pk)
        return _not_found() if p is None else Response({"project": services.project_dict(p)})

    def put(self, request, store_id, pk):
        p = self._get(request, store_id, pk, write=True)
        if p is None:
            return _not_found()
        rev = request.data.get("rev")
        try:
            saved = services.save_project(p, data=request.data.get("data") if "data" in request.data else None,
                                          title=request.data.get("title") if "title" in request.data else None,
                                          rev=None if rev in (None, "") else int(rev))
        except services.ProjectConflict as exc:
            p.refresh_from_db()
            return Response({"error": {"code": "conflict", "message": str(exc)},
                             "project": services.project_dict(p, migrate=False)},
                            status=status.HTTP_409_CONFLICT)
        except PhotoProject.DoesNotExist:   # پروژه همین لحظه از تبِ دیگری پاک شد
            return _not_found()
        except (services.PhotoError, ValueError) as exc:
            return _err(str(exc))
        return Response({"project": services.project_dict(saved, migrate=False)})

    patch = put

    def delete(self, request, store_id, pk):
        p = self._get(request, store_id, pk, write=True)
        if p is None:
            return _not_found()
        services.delete_project(p)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MaskView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, RawParser]

    def _project(self, request, store_id, pk, write):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return PhotoProject.objects.filter(pk=pk, store=store).select_related("asset", "store").first()

    def put(self, request, store_id, pk, mid):
        p = self._project(request, store_id, pk, True)
        if p is None:
            return _not_found()
        raw = request.FILES["file"].read() if "file" in request.FILES else (
            request.data if isinstance(request.data, (bytes, bytearray)) else b"")
        try:
            path, w, h = services.save_mask(p, mid, bytes(raw))
        except services.PhotoError as exc:
            return _err(str(exc))
        rel = f"{p.dir_rel}/{path.name}"
        return Response({"id": mid, "url": f"{services.media_url(rel)}?v={int(path.stat().st_mtime)}", "w": w, "h": h})

    def get(self, request, store_id, pk, mid):
        p = self._project(request, store_id, pk, False)
        if p is None:
            return _not_found()
        try:
            path = services.mask_file(p, mid)
        except services.PhotoError as exc:
            return _err(str(exc))
        if not path.is_file():
            return _not_found()
        resp = HttpResponse(path.read_bytes(), content_type="image/png")
        resp["Cache-Control"] = "no-store"
        return resp

    def delete(self, request, store_id, pk, mid):
        p = self._project(request, store_id, pk, True)
        if p is None:
            return _not_found()
        try:
            services.mask_file(p, mid).unlink(missing_ok=True)
        except services.PhotoError as exc:
            return _err(str(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExactView(APIView):
    """POST {asset, operations, side?} ⇐ کارهای کیتِ لغزنده‌ها روی کپیِ کوچک، روی سرورِ پردازش (آنلاین)؛ خاموش ⇐ online:false."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        try:
            return Response(services.exact_request(asset, request.data.get("operations") or [],
                                                   request.data.get("side") or 1280))
        except services.PhotoError as exc:
            return _err(str(exc))


class ExactStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        out = services.exact_status(store, uid)
        return _not_found() if out is None else Response(out)

    def delete(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(status=status.HTTP_204_NO_CONTENT) if services.exact_cancel(store, uid) else _not_found()


class SubjectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        try:
            return Response(services.subject_request(asset, request.data.get("rect")))
        except services.PhotoError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("photoedit: subject selection failed")
            return _err(f"انتخابِ سوژه انجام نشد: {exc}")


class SubjectStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        out = services.subject_status(store, uid)
        return _not_found() if out is None else Response(out)

    def delete(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        ok = services.exact_cancel(store, uid, "photosubject")
        return Response(status=status.HTTP_204_NO_CONTENT) if ok else _not_found()


class FontsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"fonts": services.fonts_list()})


MAX_PRESETS = 200


class PresetListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"presets": [services.preset_dict(p) for p in PhotoPreset.objects.filter(store=store)[:MAX_PRESETS]]})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        name = str(request.data.get("name") or "").strip()[:80]
        if not name:
            return _err("برای پیش‌تنظیم یک نام بنویسید.")
        if PhotoPreset.objects.filter(store=store).count() >= MAX_PRESETS:
            return _err(f"بیشتر از {MAX_PRESETS} پیش‌تنظیم نمی‌شود.")
        try:
            raw = request.data.get("data")
            data = services.normalize_preset_data(raw if raw is not None else {})
        except services.PhotoError as exc:
            return _err(str(exc))
        kind = str(request.data.get("kind") or "develop")[:20]
        p = PhotoPreset.objects.create(store=store, created_by=request.user, name=name, kind=kind, data=data)
        return Response({"preset": services.preset_dict(p)}, status=status.HTTP_201_CREATED)


class PresetView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=True):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return store, PhotoPreset.objects.filter(pk=pk, store=store).first()

    def patch(self, request, store_id, pk):
        _store, p = self._get(request, store_id, pk)
        if p is None:
            return _not_found()
        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()[:80]
            if not name:
                return _err("نامِ پیش‌تنظیم خالی است.")
            p.name = name
        if "data" in request.data:
            try:
                p.data = services.normalize_preset_data(request.data.get("data"))
            except services.PhotoError as exc:
                return _err(str(exc))
        p.save()
        return Response({"preset": services.preset_dict(p)})

    put = patch

    def delete(self, request, store_id, pk):
        _store, p = self._get(request, store_id, pk)
        if p is None:
            return _not_found()
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PresetApplyView(APIView):
    """POST {assets: [...]} ⇐ پیش‌تنظیم روی چند عکس (مثلِ CapCut): برای هر عکس یک نسخه."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        p = PhotoPreset.objects.filter(pk=pk, store=store).first()
        if p is None:
            return _not_found()
        try:
            operations = services.preset_operations(p.data, services.node_status()["online"])
            edits = services.create_edits(store, request.user, request.data.get("assets") or [], "manual", operations)
        except services.PhotoError as exc:
            return _err(str(exc))
        for e in edits:
            _dispatch(start_edit_task, e.pk)
        for e in edits:
            e.refresh_from_db()
        return Response({"batch": edits[0].batch, "edits": [services.edit_dict(e) for e in edits],
                         "node": services.node_status(), "preset": p.pk}, status=status.HTTP_201_CREATED)


# ═════════════════════════════ «پرکردنِ هوشمند» (FLUX inpaint)

class GenFillView(APIView):
    """POST multipart {image, mask, asset, prompt?, seed?} ⇐ کارِ FLUX در صف (حتی با گرهٔ خاموش) ⇐ {job, state, online, message}."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        image, mask = request.FILES.get("image"), request.FILES.get("mask")
        if image is None or mask is None:
            return _err("تصویر و ماسک را بفرستید (فیلدهای image و mask).")
        try:
            out = services.genfill_request(store, request.user, asset, image.read(), mask.read(),
                                           str(request.data.get("prompt") or ""), request.data.get("seed"),
                                           str(request.data.get("prompt_en") or ""))
        except services.PhotoError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("photoedit: genfill request failed")
            return _err(f"«پرکردنِ هوشمند» ثبت نشد: {exc}")
        return Response(out, status=status.HTTP_201_CREATED)


class GenFillTranslateView(APIView):
    """POST {prompt} ⇐ ترجمهٔ پیش‌نمایشِ توضیحِ فارسی به انگلیسی (برای نمایش و ویرایش پیش از «اجرا»). همیشه ۲۰۰ و بی‌انتظار:
    ``state`` = none (فارسی نیست) | ok (+en, label) | pending (دوباره بپرسید) | unavailable / failed (+message فارسی)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request, store_id):
        from . import tasks, translate

        store = access.get_store(request.user, store_id, access.CONTENT)
        text = str(request.data.get("prompt") or "")
        out = translate.preview_request(store, text, lambda sid, fa: _dispatch(tasks.genfill_preview_task, sid, fa))
        return Response(out)


class GenFillPromptView(APIView):
    """POST {prompt_en} ⇐ کاربر برای «پرکردنِ» منتظرِ ترجمه خودش انگلیسی نوشت ⇒ کار همین حالا آزاد می‌شود ⇒ وضعیت."""
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT)
        try:
            out = services.genfill_set_english(store, uid, request.data.get("prompt_en"))
        except services.PhotoError as exc:
            return _err(str(exc))
        return _not_found() if out is None else Response(out)


class GenFillStatusView(APIView):
    """GET ⇐ وضعیت؛ وقتی تمام شد ⇐ {state:"READY", asset, layer:{cx,cy,w}}. DELETE ⇐ لغو."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT)
        out = services.genfill_status(store, uid)
        return _not_found() if out is None else Response(out)

    def delete(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT)
        return Response(status=status.HTTP_204_NO_CONTENT) if services.genfill_cancel(store, uid) else _not_found()


# ─── پایانِ «پرکردنِ هوشمند» ───


class LiquifyRawParser(BaseParser):
    """بدنهٔ خامِ نقشهٔ مایع‌سازی؛ بیش از سقف + ۱ بایت نمی‌خواند (بزرگ‌تر ⇐ ۴۱۳ در view)."""
    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None):
        from .liquify import MAX_BYTES

        return stream.read(MAX_BYTES + 1) if stream is not None else b""


class LiquifyView(APIView):
    """GET|PUT|DELETE stores/<id>/photo-editor/projects/<pid>/liquify/ — نقشهٔ جابه‌جاییِ liquify.bin (فرمتِ LQF1، حداکثر ۲ مگابایت).

    PUT: بدنهٔ خامِ octet-stream ⇐ ``{rev, gw, gh}`` (rev = int(mtime)، همیشه صعودی)؛ هدر/اندازهٔ نادرست ⇐ ۴۰۰، بزرگ‌تر از ۲ مگابایت ⇐ ۴۱۳.
    GET: بایت‌های فایل (۴۰۴ اگر نیست)؛ DELETE: حذف (۲۰۴، تکرارپذیر)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [LiquifyRawParser]

    def _project(self, request, store_id, pk, write):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return PhotoProject.objects.filter(pk=pk, store=store).select_related("asset", "store").first()

    def put(self, request, store_id, pk):
        from .liquify import MAX_BYTES

        p = self._project(request, store_id, pk, True)
        if p is None:
            return _not_found()
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        too_big = _err("نقشهٔ مایع‌سازی بزرگ‌تر از ۲ مگابایت است.", "too_large", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        if declared > MAX_BYTES:
            return too_big
        raw = request.data if isinstance(request.data, (bytes, bytearray)) else b""
        if len(raw) > MAX_BYTES:
            return too_big
        try:
            info = services.save_liquify(p, bytes(raw))
        except services.PhotoError as exc:
            return _err(str(exc))
        return Response(info)

    def get(self, request, store_id, pk):
        p = self._project(request, store_id, pk, False)
        if p is None:
            return _not_found()
        path = services.liquify_file(p)
        if not path.is_file():
            return _not_found()
        resp = HttpResponse(path.read_bytes(), content_type="application/octet-stream")
        resp["Cache-Control"] = "no-store"
        info = services.liquify_info(p)
        if info:
            resp["X-Liquify-Rev"] = str(info["rev"])
        return resp

    def delete(self, request, store_id, pk):
        p = self._project(request, store_id, pk, True)
        if p is None:
            return _not_found()
        services.delete_liquify(p)
        return Response(status=status.HTTP_204_NO_CONTENT)
