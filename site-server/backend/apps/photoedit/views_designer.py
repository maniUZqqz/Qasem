"""API ِ «طراحِ خودکار» (نیمه‌خودکار با دستور) — کنارِ API ِ ادیتورِ عکس.

    GET    stores/<id>/photo-editor/designer/                    الگوها، قاب‌ها، حال‌وهواها، کاتالوگِ ابزارها، وضعیتِ هوش مصنوعی
    POST   stores/<id>/photo-editor/designer/analyze/            {asset} ⇐ تحلیلِ قطعی (پالت، سوژه، جاهای آرام) — فوری
    GET    stores/<id>/photo-editor/designer/designs/?asset=ID   طراحی‌های اخیرِ این عکس
    POST   stores/<id>/photo-editor/designer/designs/            {asset, prompt?, recipe?, format?, mood?, quality?, copy?, variants?, use_ai?} ⇐ 201 {design}
    GET|DELETE  stores/<id>/photo-editor/designer/designs/<pk>/  وضعیت و پیشنهادها / حذف
    POST   stores/<id>/photo-editor/designer/designs/<pk>/rerender/   {variant, plan} ⇐ ساختِ دوبارهٔ یک پیشنهاد با مرحله‌های ویرایش‌شده (بی هوش مصنوعی)
    POST   stores/<id>/photo-editor/designer/designs/<pk>/apply/      {variant} ⇐ پروژهٔ قابل‌ویرایش + نسخهٔ ساخته‌شده
"""
from __future__ import annotations

import logging
import shutil
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import fontreg, services, smart
from .designer import analyze, colorx, engine, grid, recipes, render, toolspec
from .models import PhotoAsset, PhotoDesign
from .tasks import run_design_task, start_edit_task
from .views import _dispatch, _err, _not_found

logger = logging.getLogger(__name__)

STALE_QUEUED = timedelta(seconds=90)
STALE_RUNNING = timedelta(minutes=25)


def ai_status(store) -> dict:
    """«هوش مصنوعی از کجا صدا زده می‌شود» (راست و کوتاه؛ برای نوارِ بالای پنل). جواب‌دادنش را فقط خودِ اجرا نشان می‌دهد."""
    try:
        dec = smart.decide_path(store)
    except Exception:  # noqa: BLE001
        dec = {"path": "site", "first": "local", "node_online": False, "reason": ""}
    return {"path": dec["path"], "first": dec["first"], "node_online": bool(dec["node_online"]), "reason": dec.get("reason", "")}


def _nudge(d: PhotoDesign) -> None:
    try:
        now = timezone.now()
        if d.state == PhotoDesign.State.QUEUED and d.updated_at < now - STALE_QUEUED:
            d.save(update_fields=["updated_at"])
            _dispatch(run_design_task, d.pk)
        elif d.state == PhotoDesign.State.RUNNING and d.updated_at < now - STALE_RUNNING:
            d.state = PhotoDesign.State.FAILED
            d.error = "طراحی نیمه‌کاره ماند (قطعِ سرور). دوباره امتحان کنید."
            d.message = "ناموفق"
            d.save(update_fields=["state", "error", "message", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.exception("photoedit.designer: nudge of design %s failed", d.pk)


class DesignerInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({
            "recipes": recipes.ui_list(),
            "formats": [{"key": k, "title": grid.FORMAT_FA[k]} for k in grid.FORMAT_KEYS],
            "moods": [{"key": k, "title": colorx.MOOD_FA[k]} for k in colorx.MOODS],
            "quality": [{"key": "fast", "title": "سریع", "help": "بدونِ نقدِ هوش مصنوعی"}, {"key": "normal", "title": "معمولی", "help": "یک دورِ نقد و اصلاح"},
                        {"key": "best", "title": "دقیق", "help": "تا دو دورِ نقد و اصلاح (کندتر)"}],
            "tools": toolspec.ui_catalog(),
            "slots": [{"key": k, "title": grid.SLOT_FA.get(k, k)} for k in toolspec.SLOTS],
            "fonts": services.fonts_list(),
            "ai": ai_status(store),
            "has_logo": services._store_logo(store) is not None,
            "limits": {"variants": 3, "prompt": 600},
        })


class DesignerAnalyzeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        a = PhotoAsset.objects.filter(pk=request.data.get("asset") or 0, store=store).select_related("store").first()
        if a is None:
            return _not_found()
        try:
            an = analyze.analyze(render.source_image(a), fmt="orig", facts=a.facts, findings=a.findings)
        except services.PhotoError as exc:
            return _err(str(exc))
        pub = analyze.public(an)
        pub["description"] = analyze.describe_fa(an)
        pub["suggested_recipe"] = recipes.infer_recipe(request.data.get("prompt") or "") or ("product_ad" if pub["background"]["plain"] else "caption")
        return Response({"analysis": pub})


class DesignListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        qs = PhotoDesign.objects.filter(store=store).select_related("asset")
        aid = request.query_params.get("asset")
        if aid and str(aid).isdigit():
            qs = qs.filter(asset_id=int(aid))
        out = []
        for d in qs[:12]:
            _nudge(d)
            out.append(engine.design_dict(d, full=False))
        return Response({"designs": out})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        a = PhotoAsset.objects.filter(pk=request.data.get("asset") or 0, store=store).select_related("store").first()
        if a is None:
            return _not_found()
        try:
            d = engine.create(store, request.user, a, request.data if hasattr(request.data, "get") else {})
        except engine.DesignError as exc:
            return _err(str(exc))
        _dispatch(run_design_task, d.pk)
        d.refresh_from_db()
        return Response({"design": engine.design_dict(d)}, status=status.HTTP_201_CREATED)


class DesignView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return PhotoDesign.objects.filter(pk=pk, store=store).select_related("asset", "asset__store", "store").first()

    def get(self, request, store_id, pk):
        d = self._get(request, store_id, pk)
        if d is None:
            return _not_found()
        _nudge(d)
        d.refresh_from_db()
        return Response({"design": engine.design_dict(d)})

    def delete(self, request, store_id, pk):
        d = self._get(request, store_id, pk, write=True)
        if d is None:
            return _not_found()
        shutil.rmtree(services.abs_path(d.dir_rel), ignore_errors=True)
        d.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DesignRerenderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        d = PhotoDesign.objects.filter(pk=pk, store=store).select_related("asset", "asset__store", "store").first()
        if d is None:
            return _not_found()
        if d.state != PhotoDesign.State.READY:
            return _err("طراحی هنوز آماده نیست.")
        try:
            idx = int(request.data.get("variant"))
        except (TypeError, ValueError):
            return _err("شمارهٔ پیشنهاد را بدهید.")
        try:
            nv = engine.rerender(d, idx, request.data.get("plan"), request.user)
        except (engine.DesignError, toolspec.PlanError) as exc:
            return _err(str(exc))
        except services.PhotoError as exc:
            return _err(str(exc))
        return Response({"variant": engine.variant_dict(nv)})


class DesignApplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        d = PhotoDesign.objects.filter(pk=pk, store=store).select_related("asset", "asset__store", "store").first()
        if d is None:
            return _not_found()
        try:
            idx = int(request.data.get("variant"))
        except (TypeError, ValueError):
            return _err("شمارهٔ پیشنهاد را بدهید.")
        try:
            project, edit = engine.apply(d, idx, request.user)
        except (engine.DesignError, services.PhotoError) as exc:
            return _err(str(exc))
        _dispatch(start_edit_task, edit.pk)
        edit.refresh_from_db()
        return Response({"project": project.pk, "edit": services.edit_dict(edit), "design": engine.design_dict(d, full=False)},
                        status=status.HTTP_201_CREATED)
