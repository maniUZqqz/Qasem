"""API ِ «بازسازیِ یک تکه» (پنل › فروشگاه › محتوا).

    GET  stores/<id>/regen/                         جلسه‌ها + منبع‌ها + موتورها
    POST stores/<id>/regen/sessions/                {source: "script:12"} یا فایل (multipart: file, title)
    GET  stores/<id>/regen/sessions/<pk>/           جلسه + نسخه‌ها
    GET  stores/<id>/regen/sessions/<pk>/frame/     ?n=<فریم>&w=<عرض>  ⇐ JPEG ِ همان فریم (از پایهٔ فعلی)
    GET  stores/<id>/regen/sessions/<pk>/estimate/  ?start&end&engine&quality&context ⇐ نقشه و زمانِ تقریبی
    POST stores/<id>/regen/sessions/<pk>/versions/  {start, end, prompt, engine, quality, seed?, context?, blend?}
    GET  stores/<id>/regen/versions/<pk>/           یک نسخه (وضعیتِ کارِ گره را هم تازه می‌کند)
    POST stores/<id>/regen/versions/<pk>/<accept|discard|cancel|editor>/
"""
from __future__ import annotations

import logging

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access
from services.video.regen import media
from services.video.regen import plan as planmod

from . import services
from .models import RegenSession, RegenVersion
from .tasks import prepare_session_task, start_version_task, stitch_version_task

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "regen", http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _dispatch(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:  # noqa: BLE001 — بی‌بروکر (محیطِ آزمایشی): همین‌جا
        logger.warning("regen: celery unavailable, running %s inline", task.name)
        task(*args)


def version_dict(v: RegenVersion) -> dict:
    f = v.files or {}
    st = v.stats or {}
    plan = v.plan or {}
    fps = plan.get("fps") or (v.session.info or {}).get("fps") or 30
    return {
        "id": v.id, "number": v.number, "state": v.state, "state_label": v.get_state_display(),
        "active": v.active, "progress": round(v.progress, 3), "message": v.message, "error": v.error,
        "start": v.start_frame, "end": v.end_frame, "seconds": round((v.end_frame - v.start_frame + 1) / fps, 3),
        "prompt": v.prompt, "model_prompt": v.model_prompt, "engine": v.engine, "quality": v.quality,
        "seed": v.seed, "context": v.context, "blend": v.blend, "base": v.base_id,
        "plan": plan, "seams": v.seams or {},
        "urls": {k: services.media_url(f.get(k)) for k in ("result", "after", "before", "piece", "frame_before",
                                                            "frame_after")},
        "accepted": bool(v.accepted_at), "discarded": v.discarded,
        "assemble": {k: (st.get("assemble") or {}).get(k) for k in ("method", "reencoded_frames", "seconds",
                                                                     "smart_skipped", "checks")},
        "stitch": st.get("stitch") or {}, "warnings": st.get("warnings") or [],
        "gen_seconds": st.get("gen_seconds"), "node": st.get("node"), "prompt_source": st.get("prompt_source"),
        "result_pruned": bool(st.get("result_pruned")), "editor_upload": st.get("editor_upload"),
        "mode": v.mode, "mode_label": v.get_mode_display(), "audio": v.audio or {},
        "audio_report": st.get("audio") or {}, "audio_edges_db": st.get("audio_edges_db") or {},
        "removed_frames": (st.get("assemble") or {}).get("removed_frames") or 0,
        "created_at": v.created_at,
    }


def session_dict(s: RegenSession, *, versions: bool = True) -> dict:
    cur = s.current
    base_url = services.media_url(cur.files.get("result")) if cur and cur.files.get("result") else \
        services.media_url(s.original)
    # پایهٔ فعلی (اصل، یا نسخهٔ قبول‌شده — بعد از برش تعدادِ فریم‌ها فرق دارد)
    info = (cur.stats or {}).get("result_info") if cur and (cur.stats or {}).get("result_info") else (s.info or {})
    out = {
        "id": s.id, "title": s.title, "state": s.state, "error": s.error, "source_kind": s.source_kind,
        "source_label": services.KIND_LABELS.get(s.source_kind, s.source_kind), "source_ref": s.source_ref,
        "original_url": services.media_url(s.original), "base_url": base_url, "current": s.current_id,
        "current_number": cur.number if cur else None,
        "info": {k: info.get(k) for k in ("width", "height", "fps", "fps_num", "fps_den", "n_frames", "duration",
                                          "codec", "pix_fmt", "vfr", "hdr", "rotation", "audio", "bit_rate")},
        "smart_splice": not services.asm.smart_possible(info | {"keyframes": [1]}) if info else False,
        "filmstrip": {"url": services.media_url((s.filmstrip or {}).get("path")),
                      "frames": (s.filmstrip or {}).get("frames") or []},
        "max_seconds": services.max_seconds(),
        "created_at": s.created_at,
    }
    if versions:
        out["versions"] = [version_dict(v) for v in s.versions.select_related("session").order_by("-number")]
    return out


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        sessions = RegenSession.objects.filter(store=store).order_by("-updated_at")[:30]
        return Response({
            "sessions": [session_dict(s, versions=False) | {
                "versions_count": s.versions.count(),
                "ready_count": s.versions.filter(state=RegenVersion.State.READY).count()} for s in sessions],
            "sources": services.list_sources(store, request.user),
            "engines": services.engines_status(),
            "max_seconds": services.max_seconds(),
        })


class SessionListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        try:
            session = services.create_session(store, request.user, ref=str(request.data.get("source") or ""),
                                              upload=request.FILES.get("file"),
                                              title=str(request.data.get("title") or "").strip())
        except services.RegenError as exc:
            return _err(str(exc))
        if session.state == RegenSession.State.PREPARING and not session.info:
            _dispatch(prepare_session_task, session.pk)
            session.refresh_from_db()
        return Response({"session": session_dict(session)}, status=status.HTTP_201_CREATED)


class SessionView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return RegenSession.objects.filter(pk=pk, store=store).select_related("current").first()

    def get(self, request, store_id, pk):
        s = self._get(request, store_id, pk)
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        for v in s.versions.filter(state__in=RegenVersion.ACTIVE):
            _nudge(v)
        return Response({"session": session_dict(s), "engines": services.engines_status()})

    def delete(self, request, store_id, pk):
        s = self._get(request, store_id, pk, write=True)
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        for v in s.versions.filter(state__in=RegenVersion.ACTIVE):
            services.cancel(v)
        import shutil

        shutil.rmtree(services.abs_path(s.dir_rel), ignore_errors=True)
        s.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _nudge(v: RegenVersion) -> None:
    """هر بار که پنل می‌پرسد: وضعیتِ کارِ گره را بخوان (اگر poll ِ Celery از دست رفته باشد هم کار جلو می‌رود)."""
    try:
        if v.state == RegenVersion.State.GENERATING and services.refresh(v):
            _dispatch(stitch_version_task, v.pk)
        elif services.recover_stale(v):
            _dispatch(stitch_version_task, v.pk)
    except Exception:  # noqa: BLE001
        logger.exception("regen: nudge of version %s failed", v.pk)


class FrameView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        s = RegenSession.objects.filter(pk=pk, store=store, state=RegenSession.State.READY).first()
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            n = int(request.query_params.get("n", 0))
            w = max(64, min(1280, int(request.query_params.get("w", 480))))
        except ValueError:
            return _err("n و w باید عدد باشند.")
        version_id = request.query_params.get("version")
        if version_id:
            v = s.versions.filter(pk=version_id).first()
            if v is None or not v.files.get("result"):
                return _err("نسخه ویدیوی کامل ندارد.", "not_found", status.HTTP_404_NOT_FOUND)
            path, info = services.abs_path(v.files["result"]), media.load_index(
                v.stats["result_info"], services.abs_path(v.dir_rel) / "index.json")
        else:
            _cur, path, info = services.current_base(s)
        n = max(0, min(info["n_frames"] - 1, n))
        h = max(2, int(round(w * info["height"] / info["width"] / 2)) * 2)
        try:
            data = media.jpeg(media.read_frame(path, info, n, width=w, height=h))
        except media.MediaError as exc:
            return _err(str(exc))
        resp = HttpResponse(data, content_type="image/jpeg")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp


class EstimateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        s = RegenSession.objects.filter(pk=pk, store=store, state=RegenSession.State.READY).first()
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        q = request.query_params
        _cur, _path, info = services.current_base(s)
        try:
            plan = planmod.make_plan(info, int(q.get("start")), int(q.get("end")),
                                     engine=q.get("engine") or "wan22_flf", quality=q.get("quality") or "480p",
                                     context=int(q.get("context") or 1), max_seconds=services.max_seconds())
        except (TypeError, ValueError) as exc:
            return _err(str(exc) if isinstance(exc, planmod.PlanError) else "start و end لازم است.")
        return Response({"plan": services.plan_summary(plan), "estimate": services.estimate(plan, info)})


class VersionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        s = RegenSession.objects.filter(pk=pk, store=store).first()
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            v = services.create_version(s, request.user, request.data)
        except services.RegenError as exc:
            return _err(str(exc))
        _dispatch(start_version_task, v.pk)
        v.refresh_from_db()
        return Response({"version": version_dict(v)}, status=status.HTTP_201_CREATED)


class VersionView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = access.get_store(request.user, store_id, access.CONTENT, write=write)
        return RegenVersion.objects.filter(pk=pk, session__store=store).select_related("session").first()

    def get(self, request, store_id, pk):
        v = self._get(request, store_id, pk)
        if v is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        if v.active:
            _nudge(v)
            v.refresh_from_db()
        return Response({"version": version_dict(v)})

    def post(self, request, store_id, pk, action):
        v = self._get(request, store_id, pk, write=True)
        if v is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            if action == "accept":
                services.accept(v)
            elif action == "discard":
                services.discard(v)
            elif action == "cancel":
                services.cancel(v)
            elif action == "editor":
                upload = services.send_to_editor(v)
                v.refresh_from_db()
                return Response({"version": version_dict(v), "upload_id": upload.pk})
            else:
                return _err("کارِ ناشناخته.", "bad_action", status.HTTP_404_NOT_FOUND)
        except services.RegenError as exc:
            return _err(str(exc))
        v.refresh_from_db()
        return Response({"version": version_dict(v), "session": session_dict(v.session, versions=False)})


class AudioUploadView(APIView):
    """یک فایلِ صدا برای «صدای تازه» ِ همین جلسه (multipart: file) ⇐ {source: "upload:…", duration, url}."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        s = RegenSession.objects.filter(pk=pk, store=store).first()
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        upload = request.FILES.get("file")
        if upload is None:
            return _err("فایلی فرستاده نشد.")
        try:
            return Response(services.save_audio_upload(s, upload), status=status.HTTP_201_CREATED)
        except services.RegenError as exc:
            return _err(str(exc))


class WaveformView(APIView):
    """شکلِ موجِ صدای پایهٔ فعلی: ?from&to (ثانیه، خالی = کلِ ویدیو)&n (تعدادِ ستون)&version"""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        s = RegenSession.objects.filter(pk=pk, store=store, state=RegenSession.State.READY).first()
        if s is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        q = request.query_params
        try:
            t_from = float(q["from"]) if q.get("from") not in (None, "") else None
            t_to = float(q["to"]) if q.get("to") not in (None, "") else None
            n = max(10, min(4000, int(q.get("n") or 800)))
        except ValueError:
            return _err("from/to/n باید عدد باشند.")
        version = s.versions.filter(pk=q.get("version")).first() if q.get("version") else None
        return Response(services.waveform(s, t_from, t_to, n, version=version))
