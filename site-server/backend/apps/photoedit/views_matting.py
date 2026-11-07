"""حذفِ پس‌زمینه با چند مدل (دورِ ۸) — API پنل. منطق در ``matting_nodes``.

    GET  stores/<id>/photo-editor/matting/                       ⇐ وضعیتِ مدل‌ها (روی سایت / روی سرورِ پردازش)
    POST stores/<id>/photo-editor/matting/run/                   {asset, models:[…]} ⇐ {jobs:[…], skipped:[…]}
    GET  stores/<id>/photo-editor/matting/jobs/?uids=a,b         ⇐ وضعیتِ کارها
    GET  stores/<id>/photo-editor/matting/jobs/<uid>/cutout.png  ⇐ تصویرِ بریده (فقط مالکِ فروشگاه)
    GET  stores/<id>/photo-editor/matting/site/<asset>/          ⇐ نتیجهٔ RVM ِ سایت
    POST stores/<id>/photo-editor/matting/apply/                 {asset, model, uid?} ⇐ عکسِ تازه در کتابخانه
"""
from __future__ import annotations

from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import matting_nodes as mn
from . import services
from .models import PhotoAsset
from .views import _asset, _err, _not_found


def _jobs(store, uids):
    from apps.compute.models import ComputeJob

    return list(ComputeJob.objects.filter(uid__in=uids, store=store, kind=mn.JOB_KIND).select_related("node"))


class MattingStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(mn.status(store))


class MattingRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        models = request.data.get("models")
        if models is None and request.data.get("model"):
            models = [request.data.get("model")]
        if not isinstance(models, list) or not models or len(models) > 4:
            return _err("دست‌کم یک مدل را انتخاب کنید.")
        return Response(mn.request(store, request.user, asset, [str(m) for m in models]), status=status.HTTP_201_CREATED)


class MattingJobsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        uids = [u for u in str(request.query_params.get("uids") or "").split(",") if u.strip()][:8]
        try:
            rows = _jobs(store, uids)
        except Exception:  # noqa: BLE001 — uid نامعتبر
            rows = []
        return Response({"jobs": [{"uid": str(j.uid)} | mn.job_state(j) for j in rows], "node_online": mn.status(store)["node_online"]})


class MattingCutoutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, uid):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        try:
            jobs = _jobs(store, [str(uid)])
        except Exception:  # noqa: BLE001
            jobs = []
        p = mn.result_file(jobs[0]) if jobs else None
        if p is None:
            raise Http404()
        resp = FileResponse(open(p, "rb"), content_type="image/png")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp


class MattingSiteResultView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, asset_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        asset = _asset(store, asset_id)
        p = mn._site_path(asset) if asset else None
        if p is None or not p.is_file():
            raise Http404()
        resp = FileResponse(open(p, "rb"), content_type="image/png")
        resp["Cache-Control"] = "private, no-cache"
        return resp


class MattingApplyView(APIView):
    """نتیجهٔ یک مدل را به‌عنوانِ عکسِ تازه (پس‌زمینهٔ شفاف) در کتابخانه می‌گذارد."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        asset = _asset(store, request.data.get("asset"))
        if asset is None:
            return _not_found()
        model = str(request.data.get("model") or "")
        if model == "rvm":
            path = mn._site_path(asset)
        else:
            jobs = _jobs(store, [str(request.data.get("uid") or "")]) if request.data.get("uid") else []
            path = mn.result_file(jobs[0]) if jobs else None
        if path is None or not path.is_file():
            return _err("این نتیجه هنوز آماده نیست.")
        try:
            new: PhotoAsset = mn.import_result(store, request.user, asset, path, model or "؟")
        except services.PhotoError as exc:
            return _err(str(exc))
        return Response({"asset": services.asset_dict(new)}, status=status.HTTP_201_CREATED)


class PsdImportView(APIView):
    """POST stores/<id>/photo-editor/psd/import/ (multipart: file) ⇐ {asset, project, layers, notes} — «بازکردنِ فایلِ لایه‌دار (PSD)» (دورِ ۸)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, store_id):
        from . import psd_import
        from .psd_read import PsdReadError

        store = access.get_store(request.user, store_id, access.CONTENT)
        f = request.FILES.get("file")
        if f is None:
            return _err("فایلِ PSD را بفرستید (فیلدِ file).")
        if f.size > 150 * 1024 * 1024:
            return _err("فایلِ PSD بیشتر از ۱۵۰ مگابایت است.")
        try:
            out = psd_import.import_psd(store, request.user, f.read(), (f.name or "").rsplit(".", 1)[0])
        except PsdReadError as exc:
            return _err(str(exc))
        except services.PhotoError as exc:
            return _err(str(exc))
        proj = out["project"]
        return Response({"asset": services.asset_dict(out["asset"]), "project": proj.pk if proj else None, "layers": out["layers"], "notes": out["notes"]},
                        status=status.HTTP_201_CREATED)
