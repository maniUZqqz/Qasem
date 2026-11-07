"""«کارگردان» and the one-click tools of the manual workspace.

    GET   stores/<id>/editor/director/catalogue/    tools, recipes, variants, platforms, safe zones, caption looks, AI/ASR status
    POST  stores/<id>/editor/director/run/          {prompt, refs[], options{variants,rounds,use_ai,preview,music_ref}} → job (result: plan + variants)
    POST  stores/<id>/editor/director/rerun/        {brief, steps[], refs[], variant?, draft_id?} → job: an EDITED plan run again, no model
    GET   stores/<id>/editor/director/drafts/       unopened drafts (lightweight results of earlier «بساز»), newest first, with days left
    POST  stores/<id>/editor/director/drafts/<pk>/open/   → {project_id}: the draft becomes a real project (idempotent)
    DELETE stores/<id>/editor/director/drafts/<pk>/       throw one draft away
    GET/PUT stores/<id>/editor/settings/            {ai_default, draft_days} — what the «کمکِ هوش مصنوعی» tick starts from, and how long drafts live
    POST  stores/<id>/editor/director/apply/        {data: project, steps[]} → {data, results[], notes[]}  (sync; the one-click sound tools)
    POST  stores/<id>/editor/reframe/               {ref, start, end, aspect, follow?, zoom?, speed?} → {reframe, engine, samples, notes}
    POST  stores/<id>/editor/scenes/                {ref, start?, end?, sensitivity?(low|normal|high)} → {cuts[] (source seconds), threshold, scanned}
    GET   stores/<id>/editor/projects/<pk>/versions/            saved snapshots of a project
    POST  stores/<id>/editor/projects/<pk>/versions/            {label?, data?} → snapshot now
    POST  stores/<id>/editor/projects/<pk>/versions/<name>/     restore (the current state is snapshotted first)
"""
from __future__ import annotations

import json
import logging
import re
import time
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
from services.editing import captions, reframe, safezones, scenes
from services.editing import timeline as tl
from services.editing.director import drafts as drafts_mod
from services.editing.director import projectops as ops
from services.editing.director.brief import PLATFORMS, RECIPES
from services.editing.director.ctx import store_ctx
from services.editing.director.recipes import VARIANTS
from services.editing.director.runner import apply_steps, validate_plan
from services.editing.director.tools import CAPTION_STYLES, catalogue_for_ui

from . import editor_project
from .models import DirectorDraft, VideoProject
from .tasks_director import director_task

logger = logging.getLogger(__name__)

MAX_PROJECT_BYTES = 600_000
MAX_VERSIONS = 20


def _err(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def ai_status(store) -> dict:
    """What the panel can say BEFORE the owner presses the button: which AI parts are available right now."""
    out: dict = {"node": False, "node_message": ""}
    try:
        from apps.compute import services as compute

        out["node"] = bool(compute.online_nodes("voice"))
    except Exception:  # noqa: BLE001
        out["node"] = False
    if not out["node"]:
        out["node_message"] = "سرورِ پردازش خاموش است؛ هوش مصنوعیِ محلی و گویندگی با آن کار نمی‌کند. قالب‌های آماده بدون آن هم کار می‌کنند."
    return out


class DirectorCatalogueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({
            "tools": catalogue_for_ui(),
            "recipes": [{"key": k, **v} for k, v in RECIPES.items()],
            "variants": [{"key": k, "title": v["title"]} for k, v in VARIANTS.items()],
            "platforms": [{"key": k, "title": v["title"], "preset": v["preset"], "target": v["target"], "max": v["max"]} for k, v in PLATFORMS.items()],
            "safe_zones": safezones.catalogue(),
            "caption_styles": [{"key": k, "title": v["title"]} for k, v in CAPTION_STYLES.items()],
            "captions": captions.status(),
            "ai": ai_status(store),
            "settings": drafts_mod.public_settings(store),
        })


def _refs(raw) -> list[str]:
    return [str(r)[:60] for r in (raw if isinstance(raw, list) else [])][:24]


def _busy(store) -> bool:
    from datetime import timedelta

    from django.utils import timezone

    return Job.objects.filter(store=store, type=Job.Type.VIDEO_EDIT, context__what="director",
                              state__in=(Job.State.QUEUED, Job.State.RUNNING, Job.State.PROCESSING), updated_at__gt=timezone.now() - timedelta(minutes=30)).exists()


class DirectorRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        refs = _refs(request.data.get("refs"))
        prompt = str(request.data.get("prompt") or "").strip()[:600]
        if not refs:
            return _err("no_refs", "اول ویدیو یا عکس‌هایی را که می‌خواهید در ویدیو باشند انتخاب کنید.")
        if _busy(store):
            return _err("busy", "یک کارگردانِ دیگر هنوز در حال کار است؛ تمام شدنش را صبر کنید.", status.HTTP_409_CONFLICT)
        opts = dict(request.data.get("options")) if isinstance(request.data.get("options"), dict) else {}
        # the «کمکِ هوش مصنوعی» tick starts from the store's own default; the panel can still override it for one run
        if "use_ai" not in opts:
            opts["use_ai"] = drafts_mod.get_settings(store)["ai_default"]
        drafts_mod.purge(store)
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "director", "kind": "run"})
        failed = dispatch_job(job, director_task, job.id, {"kind": "run", "prompt": prompt, "refs": refs, "options": opts})
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class DirectorRerunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        refs = _refs(request.data.get("refs"))
        steps = request.data.get("steps")
        if not refs or not isinstance(steps, list) or not steps:
            return _err("bad_request", "مرحله‌ها یا منبع‌ها نیامده است.")
        if _busy(store):
            return _err("busy", "یک کارگردانِ دیگر هنوز در حال کار است.", status.HTTP_409_CONFLICT)
        brief = request.data.get("brief") if isinstance(request.data.get("brief"), dict) else {}
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "director", "kind": "rerun"})
        payload = {"kind": "rerun", "refs": refs, "steps": steps[:80], "brief": brief, "variant": str(request.data.get("variant") or "a")[:2],
                   "replace_draft": request.data.get("draft_id")}
        failed = dispatch_job(job, director_task, job.id, payload)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class DirectorDraftsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"drafts": drafts_mod.drafts_of(store), "draft_days": drafts_mod.get_settings(store)["draft_days"], "max_drafts": drafts_mod.MAX_DRAFTS})


class DirectorDraftOpenView(APIView):
    """Open a draft in the manual editor: this is the moment it becomes a real project."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        draft = get_object_or_404(DirectorDraft, pk=pk, store=store)
        project = drafts_mod.promote(draft)
        return Response({"project_id": project.pk, "title": project.title})


class DirectorDraftDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        draft = get_object_or_404(DirectorDraft, pk=pk, store=store, project__isnull=True, promoted_at__isnull=True)
        run, job_id, sid = draft.run, draft.job_id, draft.store_id
        draft.delete()
        drafts_mod._drop_previews([(run, job_id, sid)])
        return Response(status=status.HTTP_204_NO_CONTENT)


class EditorSettingsView(APIView):
    """Store-level editor settings: the default of the «هوش مصنوعی کمک کند» tick and the lifetime of unopened drafts."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response(drafts_mod.public_settings(store))

    def put(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ai = request.data.get("ai_default")
        days = request.data.get("draft_days")
        if ai is not None and not isinstance(ai, bool):
            return _err("bad_request", "مقدارِ «کمکِ هوش مصنوعی» باید روشن یا خاموش باشد.")
        if days is not None:
            try:
                int(days)
            except (TypeError, ValueError):
                return _err("bad_request", "مدتِ نگهداریِ پیش‌نویس باید یک عدد (روز) باشد.")
        drafts_mod.save_settings(store, ai_default=ai, draft_days=days)
        return Response(drafts_mod.public_settings(store))


class DirectorApplyView(APIView):
    """The manual workspace's one-click tools (music, silence removal, loudness, clean voice, mix, voice-over)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        data = request.data.get("data")
        steps = request.data.get("steps")
        if not isinstance(data, dict) or not data.get("tracks"):
            return _err("bad_project", "پروژه نیامده است.")
        if len(json.dumps(data, ensure_ascii=False)) > MAX_PROJECT_BYTES:
            return _err("bad_project", "پروژه بیش از اندازه بزرگ شد.")
        if not isinstance(steps, list) or not steps:
            return _err("bad_request", "مرحله‌ای فرستاده نشده است.")
        clean, problems = validate_plan(steps[:12])
        # speech recognition may run only for the tools that cannot work without it (it can take a while; the others answer at once)
        needs_asr = any(s["tool"] in ("remove_fillers", "add_captions") for s in clean)
        ctx = store_ctx(store, user=request.user, asr=needs_asr, tts_wait=20.0)
        try:
            new, results = apply_steps(data, clean, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.exception("director apply failed")
            return _err("apply_failed", f"انجامش ممکن نشد: {str(exc)[:120]}", status.HTTP_500_INTERNAL_SERVER_ERROR)
        if "director" in data:                          # the plan metadata rides along untouched
            new["director"] = data["director"]
        verdict = editor_project.check(store, new) if new.get("tracks") else None
        return Response({"data": new, "results": results, "notes": problems, "check": verdict})


class EditorReframeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        ref = str(request.data.get("ref") or "")
        try:
            item = editor_project.describe(store, ref)
        except tl.TimelineError as exc:
            return _err("bad_ref", str(exc), status.HTTP_404_NOT_FOUND)
        try:
            asp = reframe.aspect_value(request.data.get("aspect") or "9:16")
            start = max(0.0, float(request.data.get("start") or 0))
            end = float(request.data.get("end") if request.data.get("end") is not None else start + 1)
            zoom = float(request.data.get("zoom") or 1.0)
            speed = float(request.data.get("speed") or 1.0)
        except (TypeError, ValueError):
            return _err("bad_request", "مقدارها درست نیست.")
        except tl.TimelineError as exc:
            return _err("bad_aspect", str(exc))
        if item["kind"] not in ("video", "image") or not (item.get("width") and item.get("height")):
            return _err("not_visual", "این منبع تصویر ندارد.")
        follow = "center" if str(request.data.get("follow")) == "center" else "auto"
        try:
            if item["kind"] == "image":
                res = {"reframe": reframe.centred(item["width"], item["height"], asp, zoom), "engine": "center", "samples": 0, "notes": []}
            else:
                res = reframe.plan(item["path"], start, max(end, start + 0.3), asp, follow=follow, zoom=zoom, speed=speed, size=(item["width"], item["height"]))
        except tl.TimelineError as exc:
            return _err("reframe_failed", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(res)


class EditorScenesView(APIView):
    """Where does this video change shot? (the manual editor's «تشخیصِ برش‌ها»); the panel splits the clip at those times."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        ref = str(request.data.get("ref") or "")
        try:
            item = editor_project.describe(store, ref)
        except tl.TimelineError as exc:
            return _err("bad_ref", str(exc), status.HTTP_404_NOT_FOUND)
        if item["kind"] != "video":
            return _err("not_video", "تشخیصِ برش فقط روی ویدیو شدنی است.")
        try:
            start = max(0.0, float(request.data.get("start") or 0))
            end = float(request.data.get("end") if request.data.get("end") is not None else item.get("duration") or 0)
        except (TypeError, ValueError):
            return _err("bad_request", "مقدارها درست نیست.")
        if end <= start + 0.5:
            return _err("bad_range", "بازهٔ ویدیو خیلی کوتاه است.")
        sens = str(request.data.get("sensitivity") or "normal")
        return Response(scenes.detect_cuts(item["path"], start, end, sens if sens in scenes.SENSITIVITY else "normal"))


# ------------------------------------------------------------------ versions (snapshots on disk; no migration)


def _version_dir(project: VideoProject) -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / f"project_{project.pk}" / "versions"


def snapshot(project: VideoProject, label: str = "") -> str | None:
    """Write the project's current JSON as a version (keeps the newest MAX_VERSIONS). Returns the version name."""
    data = project.data or {}
    if not data.get("tracks"):
        return None
    folder = _version_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}.json"
    n = 1
    while (folder / name).exists():                       # two snapshots in the same second
        n += 1
        name = f"{stamp}-{n}.json"
    payload = {"label": re.sub(r"\s+", " ", label)[:60], "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "title": project.title, "data": data}
    (folder / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for old in sorted(folder.glob("*.json"))[:-MAX_VERSIONS]:
        old.unlink(missing_ok=True)
    return name


def _row(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        data = d.get("data") or {}
        clips = sum(len(t.get("clips", [])) for t in data.get("tracks", []))
        return {"name": path.name, "label": d.get("label", ""), "saved_at": d.get("saved_at", ""), "clips": clips,
                "length": round(ops.project_length(data), 1) if data.get("tracks") else 0}
    except (OSError, ValueError):
        return None


class ProjectVersionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        folder = _version_dir(project)
        rows = [r for r in (_row(p) for p in sorted(folder.glob("*.json"), reverse=True)) if r] if folder.is_dir() else []
        return Response({"versions": rows})

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        data = request.data.get("data")
        if isinstance(data, dict) and data.get("tracks") and len(json.dumps(data, ensure_ascii=False)) <= MAX_PROJECT_BYTES:
            project.data = data
            project.save(update_fields=["data", "updated_at"])
        name = snapshot(project, str(request.data.get("label") or "نقطهٔ ذخیره"))
        if not name:
            return _err("empty", "پروژه هنوز چیزی ندارد که ذخیره شود.")
        return Response({"name": name}, status=status.HTTP_201_CREATED)


class ProjectVersionRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk, name):
        store = access.get_store(request.user, store_id, access.CONTENT)
        project = get_object_or_404(VideoProject, pk=pk, store=store)
        if not re.fullmatch(r"\d{8}-\d{6}(-\d+)?\.json", name):
            return _err("bad_name", "نامِ نسخه درست نیست.")
        path = _version_dir(project) / name
        if not path.is_file():
            return _err("not_found", "این نسخه پیدا نشد.", status.HTTP_404_NOT_FOUND)
        snapshot(project, "پیش از بازگرداندن")
        saved = json.loads(path.read_text(encoding="utf-8"))
        project.data = saved.get("data") or {}
        project.save(update_fields=["data", "updated_at"])
        return Response({"project": {"id": project.pk, "title": project.title, "data": project.data}})
