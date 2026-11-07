"""The «دستی» workspace, pro part: the catalogue (looks, fonts, transitions, export presets), media analysis (waveform,
filmstrip, beats, speech), the exact range preview, auto-captions and the render queue. §23.4

    GET    stores/<id>/editor/catalogue/                          everything the panel needs to draw its choosers
    GET    stores/<id>/editor/analysis/?ref=&kind=                waveform | filmstrip | beats | speech (cached, size-limited)
    POST   stores/<id>/editor/projects/<pk>/preview/             {t0, t1, height?, data?} → job → mp4 of that range
    GET    stores/<id>/editor/captions/status/                   can auto-captions run right now (node online?)
    POST   stores/<id>/editor/captions/                          {ref, start, end, at, speed?} → job → caption clips
    GET    stores/<id>/editor/projects/<pk>/renders/             the queue: active and recent exports of the project
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.editing import audiofx, captions, color, export, media_cache, noderender, safezones, shapes, stickers, titles, transitions
from services.editing import keyframes
from services.editing import timeline as tl

from . import editor_project
from .models import VideoProject
from .tasks_editing import captions_task, preview_range_task, translate_captions_task

logger = logging.getLogger(__name__)

MAX_PREVIEW_SECONDS = 20.0
MAX_QUEUED_PER_PROJECT = 3


def _err(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def snapshot_path(project: VideoProject, name: str, data: dict) -> str:
    """Write the project JSON the job should use (the editor keeps autosaving while a job runs) → path relative to MEDIA_ROOT."""
    folder = Path(settings.MEDIA_ROOT) / "generated" / "editing" / f"project_{project.pk}" / "snap"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(target.relative_to(settings.MEDIA_ROOT)).replace("\\", "/")


def _data_from(request, project: VideoProject) -> dict:
    data = request.data.get("data")
    if isinstance(data, dict) and data.get("tracks"):
        if len(json.dumps(data, ensure_ascii=False)) > 600_000:
            raise tl.TimelineError("پروژه بیش از اندازه بزرگ شد.")
        return data
    return project.data or {}


class EditorCatalogueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({
            "color": color.catalogue(),
            "titles": titles.catalogue(),
            "transitions": transitions.catalogue(),
            "export": export.catalogue(),
            "easings": [{"key": k, "title": keyframes.EASING_TITLES[k]} for k in keyframes.EASINGS],
            "blends": [{"key": k, "title": t} for k, t in (
                ("normal", "عادی"), ("multiply", "ضرب (تیره‌تر)"), ("screen", "روشن‌کننده (Screen)"), ("overlay", "همپوشانی"),
                ("add", "جمع (نورانی)"), ("softlight", "نورِ نرم"), ("lighten", "روشن‌ترین"), ("darken", "تیره‌ترین"),
                ("difference", "تفاوت"))],
            "eq": [{"key": k, "title": audiofx.EQ_TITLES[k]} for k in tl.EQ_PRESETS],
            "ramp_presets": [
                {"key": "montage", "title": "مونتاژ (تند و کند)", "ramp": [{"p": 0, "v": 1}, {"p": 0.35, "v": 3.5}, {"p": 0.65, "v": 0.4}, {"p": 1, "v": 1}]},
                {"key": "hero", "title": "قهرمان (کندِ وسط)", "ramp": [{"p": 0, "v": 1.6}, {"p": 0.4, "v": 0.3}, {"p": 0.7, "v": 0.3}, {"p": 1, "v": 1.8}]},
                {"key": "flash_in", "title": "ورودِ تند", "ramp": [{"p": 0, "v": 4}, {"p": 0.3, "v": 1}, {"p": 1, "v": 1}]},
                {"key": "flash_out", "title": "خروجِ تند", "ramp": [{"p": 0, "v": 1}, {"p": 0.7, "v": 1}, {"p": 1, "v": 4}]},
                {"key": "bullet", "title": "گلوله (کند‌ـ‌تند‌ـ‌کند)", "ramp": [{"p": 0, "v": 0.5}, {"p": 0.5, "v": 3}, {"p": 1, "v": 0.5}]},
            ],
            "captions": captions.status(),
            "shapes": shapes.catalogue()["shapes"],
            "stickers": stickers.available(),
            "render_where": noderender.status(),
            "safe_zones": safezones.catalogue(),
            "limits": {"max_preview_seconds": MAX_PREVIEW_SECONDS, "max_tracks": tl.MAX_TRACKS, "max_clips": tl.MAX_CLIPS,
                       "ramp_steps": tl.RAMP_STEPS},
        })


class EditorAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        ref = str(request.query_params.get("ref") or "")
        kind = str(request.query_params.get("kind") or "")
        try:
            item = editor_project.describe(store, ref)
        except tl.TimelineError as exc:
            return _err("bad_ref", str(exc), status.HTTP_404_NOT_FOUND)
        path = Path(item["path"])
        try:
            if kind == "waveform":
                if item["kind"] == "image":
                    return _err("no_audio", "عکس صدا ندارد.")
                if not item["has_audio"]:
                    return Response({"peaks": [], "per_second": 0, "duration": item["duration"], "silent": True})
                return Response(media_cache.waveform(path))
            if kind == "filmstrip":
                if item["kind"] != "video":
                    return _err("not_video", "نوارِ تصویر فقط برای ویدیو ساخته می‌شود.")
                info = media_cache.filmstrip(path)
                return Response({**{k: v for k, v in info.items() if k != "file"}, "url": editor_project._rel_url(info["file"])})
            if kind == "beats":
                if not item["has_audio"]:
                    return _err("no_audio", "این فایل صدا ندارد.")
                return Response(media_cache.beats(path))
            if kind == "speech":
                if not item["has_audio"]:
                    return Response({"spans": []})
                return Response({"spans": media_cache.speech_spans(path)})
        except tl.TimelineError as exc:
            return _err("analysis_failed", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
        return _err("bad_kind", "نوعِ تحلیل نامعتبر است (waveform | filmstrip | beats | speech).")


class ProjectPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        try:
            t0 = max(0.0, float(request.data.get("t0")))
            t1 = float(request.data.get("t1"))
            data = _data_from(request, project)
        except (TypeError, ValueError):
            return _err("bad_range", "بازهٔ پیش‌نمایش درست نیست.")
        except tl.TimelineError as exc:
            return _err("bad_project", str(exc))
        if t1 <= t0 + 0.1:
            return _err("bad_range", "بازهٔ پیش‌نمایش خیلی کوتاه است.")
        t1 = min(t1, t0 + MAX_PREVIEW_SECONDS)
        verdict = editor_project.check(store, data)
        if not verdict["ok"]:
            return _err("bad_project", verdict["error"])
        height = max(240, min(540, int(request.data.get("height") or 360)))
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "preview", "project_id": project.pk})
        snap = snapshot_path(project, f"preview_{job.id}.json", data)
        failed = dispatch_job(job, preview_range_task, job.id, project.pk, snap, t0, t1, height)
        if failed is not None:
            return failed
        return Response({"job_id": job.id, "t0": t0, "t1": t1}, status=status.HTTP_202_ACCEPTED)


class CaptionsTranslateView(APIView):
    """«ترجمهٔ زیرنویس»: [{id, text}] + زبان → job؛ نتیجه {lang, items: [{id, text}]}."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        from services.editing import translate

        store = access.get_store(request.user, store_id, access.CONTENT)
        lang = str(request.data.get("lang") or "")
        if lang not in translate.LANGS:
            return _err("bad_lang", "زبانِ مقصد درست نیست.")
        try:
            items = translate.clean_items(request.data.get("clips"))
        except ValueError as exc:
            return _err("bad_clips", str(exc))
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "translate", "lang": lang, "count": len(items)})
        failed = dispatch_job(job, translate_captions_task, job.id, lang, items)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class CaptionsStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(captions.status())


class CaptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ref = str(request.data.get("ref") or "")
        try:
            start, end = float(request.data.get("start")), float(request.data.get("end"))
            at = float(request.data.get("at") or 0)
            speed = float(request.data.get("speed") or 1)
            item = editor_project.describe(store, ref)
        except (TypeError, ValueError):
            return _err("bad_range", "بازهٔ زیرنویس درست نیست.")
        except tl.TimelineError as exc:
            return _err("bad_ref", str(exc), status.HTTP_404_NOT_FOUND)
        if item["kind"] == "image" or not item["has_audio"]:
            return _err("no_audio", "این قطعه صدا ندارد، پس چیزی برای زیرنویس‌کردن نیست.")
        if end <= start + 0.2:
            return _err("bad_range", "بازهٔ زیرنویس خیلی کوتاه است.")
        if end - start > captions.MAX_SECONDS:
            return _err("too_long", f"زیرنویسِ خودکار تا {captions.MAX_SECONDS // 60} دقیقه در هر بار.")
        state = captions.status()
        if not state["ok"] and not state.get("waiting"):
            return _err("captions_unavailable", state["message"], status.HTTP_503_SERVICE_UNAVAILABLE)
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "captions", "ref": ref})
        failed = dispatch_job(job, captions_task, job.id, ref, start, end, at, speed)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class ProjectRendersView(APIView):
    """The render queue of a project: every export job still running or waiting, plus the finished files kept on disk."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        jobs = Job.objects.filter(store=store, type=Job.Type.VIDEO_EDIT, context__what="project", context__project_id=project.pk).order_by("-id")[:10]
        rows = []
        for job in jobs:
            rows.append({
                "id": job.id, "state": job.state, "percent": int(job.progress_step or 0) if job.total_steps == 100 else 0,
                "label": job.current_step_label, "error": job.error if job.state == Job.State.FAILED else "",
                "preset": (job.context or {}).get("preset", ""), "quality": (job.context or {}).get("quality", ""),
                "where": (job.context or {}).get("where", ""),
                "created_at": job.created_at, "active": job.state not in (Job.State.COMPLETED, Job.State.FAILED, Job.State.CANCELLED),
            })
        return Response({"jobs": rows, "exports": (project.render_info or {}).get("exports", []), "replaced": (project.render_info or {}).get("replaced", {})})
