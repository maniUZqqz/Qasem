"""The «دستی» video workspace's API (timeline, media bin, light preview, render). §23.4

    GET    stores/<id>/editor/bin/                         everything that can go on a timeline (videos, sounds, photos)
    POST   stores/<id>/editor/proxy/                       {ref} → job: a small, browser-playable stand-in for a big clip
    POST   stores/<id>/editor/subtitles/                   {ref} → the SRT lines of a video, to be placed as text clips
    GET    stores/<id>/editor/projects/                    the shop's projects
    POST   stores/<id>/editor/projects/                    {title?, data?}
    GET PUT DELETE stores/<id>/editor/projects/<pk>/       one project; PUT validates and says whether it would render
    POST   stores/<id>/editor/projects/<pk>/render/        {quality: draft|final, export?: {...}, data?: project} → job (queued, one at a time)

A project's JSON never carries a file path — only refs the server resolves for this store (see editor_project.py).
"""
from __future__ import annotations

import json
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.editing import timeline as tl

from . import editor_project
from .models import VideoProject
from .tasks_editing import make_proxy_task, render_project_task

logger = logging.getLogger(__name__)

MAX_PROJECT_BYTES = 600_000
MAX_PROJECTS = 60
MAX_QUEUED_RENDERS = 3


def _err(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def project_dict(project: VideoProject, *, with_data: bool = True) -> dict:
    out = {
        "id": project.pk, "title": project.title, "state": project.state, "error": project.error,
        "render_info": project.render_info or {},
        "output_url": project.output.url if project.output else None,
        "updated_at": project.updated_at, "created_at": project.created_at,
    }
    if with_data:
        out["data"] = project.data or {}
    return out


def _active_renders(project: VideoProject) -> int:
    """Export jobs of this project that are queued or running (a job that died with its worker half an hour ago is not)."""
    from datetime import timedelta

    from django.utils import timezone

    return Job.objects.filter(
        store=project.store, type=Job.Type.VIDEO_EDIT, context__what="project", context__project_id=project.pk,
        state__in=(Job.State.QUEUED, Job.State.RUNNING, Job.State.PROCESSING), updated_at__gt=timezone.now() - timedelta(minutes=45),
    ).count()


def _clean_data(data) -> dict:
    """Keep only the shapes the panel writes; a project can never smuggle a path (refs are resolved server-side)."""
    if not isinstance(data, dict):
        raise tl.TimelineError("پروژه باید یک شیء باشد.")
    if len(json.dumps(data, ensure_ascii=False)) > MAX_PROJECT_BYTES:
        raise tl.TimelineError("پروژه بیش از اندازه بزرگ شد.")
    return data


class EditorBinView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(editor_project.bin_items(store))


class EditorProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ref = str(request.data.get("ref") or "")
        try:
            item = editor_project.describe(store, ref)
            kind, pk = editor_project.parse_ref(ref)
            editor_project.proxy_path(kind, pk)
        except tl.TimelineError as exc:
            return _err("bad_ref", str(exc))
        if item["kind"] != "video":
            return _err("not_video", "پیش‌نمایشِ سبک فقط برای ویدیو ساخته می‌شود.")
        if item["proxy"] == "ready":
            return Response({"proxy": "ready", "proxy_url": item["proxy_url"], "job_id": None})
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "proxy", "ref": ref})
        failed = dispatch_job(job, make_proxy_task, job.id, ref)
        if failed is not None:
            return failed
        return Response({"job_id": job.id, "proxy": "building"}, status=status.HTTP_202_ACCEPTED)


class EditorSubtitlesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        try:
            lines = editor_project.subtitle_lines(store, str(request.data.get("ref") or ""))
        except tl.TimelineError as exc:
            return _err("no_subtitles", str(exc), status.HTTP_404_NOT_FOUND)
        return Response({"lines": lines[:400]})


class ProjectListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"projects": [project_dict(p, with_data=False) for p in store.video_projects.all()[:MAX_PROJECTS]]})

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        if store.video_projects.count() >= MAX_PROJECTS:
            return _err("too_many", f"حداکثر {MAX_PROJECTS} پروژه؛ چندتا را پاک کنید.")
        try:
            data = _clean_data(request.data.get("data") or {})
        except tl.TimelineError as exc:
            return _err("bad_project", str(exc))
        project = VideoProject.objects.create(store=store, title=str(request.data.get("title") or "پروژهٔ تازه")[:200], data=data)
        return Response({"project": project_dict(project), "check": editor_project.check(store, data) if data.get("tracks") else None},
                        status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        return Response({"project": project_dict(project), "check": editor_project.check(store, project.data) if (project.data or {}).get("tracks") else None})

    def put(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        if "title" in request.data:
            project.title = str(request.data.get("title") or "")[:200] or project.title
        check = None
        if "data" in request.data:
            try:
                project.data = _clean_data(request.data.get("data"))
            except tl.TimelineError as exc:
                return _err("bad_project", str(exc))
            check = editor_project.check(store, project.data) if project.data.get("tracks") else None
        project.save()
        return Response({"project": project_dict(project, with_data=False), "check": check})

    def delete(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectRenderView(APIView):
    """Export. The job works on a snapshot of the project, so editing can go on while it renders (and waits in the queue)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        from .views_editor_pro import snapshot_path

        store = access.get_store(request.user, store_id, access.CONTENT)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        if _active_renders(project) >= MAX_QUEUED_RENDERS:
            return _err("queue_full", f"{MAX_QUEUED_RENDERS} رندر در صف است؛ یکی را لغو کنید یا صبر کنید.", status.HTTP_409_CONFLICT)
        quality = "draft" if str(request.data.get("quality")) == "draft" else "final"
        data = request.data.get("data") if isinstance(request.data.get("data"), dict) and request.data["data"].get("tracks") else (project.data or {})
        try:
            data = _clean_data(data)
        except tl.TimelineError as exc:
            return _err("bad_project", str(exc))
        override = request.data.get("export")
        if isinstance(override, dict):
            data = {**data, "export": {**(data.get("export") or {}), **override}}
        verdict = editor_project.check(store, data)
        if not verdict["ok"]:
            return _err("bad_project", verdict["error"])
        export_block = data.get("export") or {}
        if quality == "final":
            from services.editing import export as export_module

            export_block = export_module.default_export(export_block, export_module.preset_hint(data))
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={
            "what": "project", "project_id": project.pk, "quality": quality, "preset": str(export_block.get("preset") or "")})
        project.state = VideoProject.State.RENDERING
        project.error = ""
        project.save(update_fields=["state", "error", "updated_at"])
        failed = dispatch_job(job, render_project_task, job.id, project.pk, quality, snapshot_path(project, f"render_{job.id}.json", data))
        if failed is not None:
            project.state = VideoProject.State.FAILED
            project.error = "رندر شروع نشد."
            project.save(update_fields=["state", "error", "updated_at"])
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)
