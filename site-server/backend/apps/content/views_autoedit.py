"""The automatic edit's endpoints: ask the owner about doubtful pauses, make one project into every network's size, run the polish for an upload.

    GET   stores/<id>/autoedit/silences/?ref=video:22       the pauses of one source: what we decided, what we ask → {silences[], questions[], counts, …}
    POST  stores/<id>/autoedit/silences/                    {ref, answers:[{start,end,action:keep|shorten|cut}], default?} → the same, with the answers applied and remembered
    GET   stores/<id>/autoedit/look-preview/?ref=&t=         before/after stills of the automatic light + colour correction of one video
    GET   stores/<id>/autoedit/sizes/                       the networks and their sizes
    POST  stores/<id>/editor/projects/<pk>/sizes/           {sizes:[key…]} → one project + one render job per size
    POST  stores/<id>/videos/<pk>/autoedit/                 {platform?, prompt?} → the director's «polish» run on an uploaded video (job)
"""
from __future__ import annotations

import base64
import logging
import subprocess

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.editing import autolook, captions, color, silence_intel, social_sizes
from services.editing import timeline as tl
from services.editing.director.ctx import store_ctx

from . import editor_project
from .models import UploadedVideo, VideoProject

logger = logging.getLogger(__name__)

MAX_ANSWERS = 200


def _err(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code, "message": message}, status=http)


def review_payload(store, ref: str) -> dict:
    """The review of one source for the panel: raises `editor_project.RefError` / `TimelineError` when the ref is not the store's."""
    item = editor_project.describe(store, ref)
    if item["kind"] != "video" or not item.get("has_audio"):
        raise tl.TimelineError("این ویدیو صدا ندارد؛ مکثی برای بررسی نیست.")
    report = silence_intel.review(item["path"], float(item["duration"]), store_id=store.pk, ref=ref)
    state = captions.status()
    words = "ready" if report["has_words"] else ("waiting" if state.get("waiting") else "off" if not state.get("ok") else "later")
    return {
        "ref": ref, "title": item["title"], "duration": item["duration"], "url": item.get("url"), "auth": item.get("auth", False),
        "silences": report["silences"], "questions": report["questions"], "counts": report["counts"], "removed_seconds": report["removed_seconds"],
        "answered": report["answered"], "pending": report["pending"], "words": words, "note": report["note"],
        "has_picture": report["has_picture"],
    }


class SilenceReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        ref = str(request.query_params.get("ref") or "")
        if not ref:
            return _err("no_ref", "ویدیو مشخص نشده است.")
        try:
            return Response(review_payload(store, ref))
        except (editor_project.RefError, tl.TimelineError) as exc:
            return _err("bad_ref", str(exc))

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)
        ref = str(request.data.get("ref") or "")
        answers = request.data.get("answers")
        if not ref or not isinstance(answers, list):
            return _err("bad_request", "ویدیو یا پاسخ‌ها فرستاده نشد.")
        try:
            editor_project.describe(store, ref)                     # the ref must be this store's own
        except (editor_project.RefError, tl.TimelineError) as exc:
            return _err("bad_ref", str(exc))
        rule = {}
        if request.data.get("default") in (*silence_intel.ACTIONS, "suggest"):
            rule["ask_default"] = request.data["default"]
        silence_intel.save_answers(store.pk, ref, answers[:MAX_ANSWERS], rule)
        try:
            return Response(review_payload(store, ref))
        except (editor_project.RefError, tl.TimelineError) as exc:
            return _err("bad_ref", str(exc))


class SizesCatalogueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({"sizes": social_sizes.catalogue(), "default": list(social_sizes.DEFAULT_SET)})


def dispatch_sizes(store, source: VideoProject, keys: list[str], data: dict, ctx, *, origin: str = "", parent: int | None = None) -> tuple[list[dict], list[dict]]:
    """One edit → one editable project + one final render job per size (`keys` are `social_sizes` keys).  Returns (made, skipped).  Shared by the
    panel's «چند سایز» button and the automatic edit's own delivery, so both go through the normal export (site or processing node)."""
    from services.editing import export as export_module

    from .tasks_editing import render_project_task
    from .views_editor_pro import snapshot_path

    made, skipped = [], []
    for key in keys:
        derived = social_sizes.derive(data, key, ctx)
        verdict = editor_project.check(store, derived.project)
        if not verdict["ok"]:
            skipped.append({"size": key, "title": derived.title, "reason": verdict["error"]})
            continue
        title = f"{source.title} — {derived.title}"[:200]
        project = VideoProject.objects.create(store=store, title=title, data=derived.project, state=VideoProject.State.RENDERING)
        export_block = export_module.default_export(derived.project.get("export") or {}, "")
        context = {"what": "project", "project_id": project.pk, "quality": "final", "preset": str(export_block.get("preset") or ""), "size": key, "of": source.pk}
        if origin:
            context["origin"] = origin
        if parent:
            context["parent_job"] = parent
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context=context)
        failed = dispatch_job(job, render_project_task, job.id, project.pk, "final", snapshot_path(project, f"render_{job.id}.json", derived.project))
        if failed is not None:
            project.state = VideoProject.State.FAILED
            project.error = "رندر شروع نشد."
            project.save(update_fields=["state", "error", "updated_at"])
            skipped.append({"size": key, "title": derived.title, "reason": "صفِ پردازش در دسترس نیست."})
            continue
        made.append({"size": key, "title": derived.title, "project_id": project.pk, "job_id": job.id, "notes": derived.notes})
    return made, skipped


class ProjectSizesView(APIView):
    """One edit → every network.  Each size becomes its own project (editable) with its own export job, so progress, cancel, the node render and
    the audio check all work exactly as for a normal export."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        source = get_object_or_404(VideoProject, pk=pk, store=store)
        keys = social_sizes.clean_keys(request.data.get("sizes"))
        if not keys:
            return _err("no_sizes", "حداقل یک اندازه (مثلاً ریلز یا یوتیوب) را انتخاب کنید.")
        data = request.data.get("data") if isinstance(request.data.get("data"), dict) and request.data["data"].get("tracks") else (source.data or {})
        if request.data.get("captions") in ("burn", "soft"):
            data = {**data, "export": {**(data.get("export") or {}), "captions": request.data["captions"]}}
        made, skipped = dispatch_sizes(store, source, keys, data, store_ctx(store, user=request.user, asr=False))
        if not made:
            return Response({"jobs": [], "skipped": skipped}, status=status.HTTP_409_CONFLICT)
        return Response({"jobs": made, "skipped": skipped}, status=status.HTTP_202_ACCEPTED)


def autoedit_payload(upload_id: int, *, platform: str = "", prompt: str = "", require_words: bool = False, deliver: bool = True, sizes=None, captions: str = "") -> dict:
    """The director job payload of the polish run for one upload (shared by the endpoint and the `queue_autoedit_rerun` command).

    `deliver` (default on): the run does not stop at a draft - when the draft is complete (captions filled in once the processing server is on)
    it becomes a project and is rendered (final quality, NVENC on the node), so there is always an OUTPUT to watch; `sizes` (social_sizes keys)
    makes one rendered project per network instead of the single one in the platform's own size."""
    override = {"recipe": "polish"}
    if platform:
        override["platform"] = platform
    options = {"variants": 1, "rounds": 1, "use_ai": False, "preview": False, "override": override, "require_words": require_words, "deliver": bool(deliver)}
    keys = social_sizes.clean_keys(sizes)
    if keys:
        options["sizes"] = keys
    if captions in ("burn", "soft"):
        options["captions"] = captions            # «زیرنویس: داخلِ تصویر / فایلِ جدا (.srt)»
    return {"kind": "run", "prompt": prompt[:600], "refs": [f"video:{upload_id}"], "options": options}


class UploadAutoEditView(APIView):
    """«تدوینِ خودکارِ حرفه‌ای» for an uploaded video: the director's polish recipe as a job; the result is a draft in the usual drafts list."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        from .tasks_director import director_task

        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)
        if upload.state not in (UploadedVideo.State.READY, UploadedVideo.State.EDITED):
            return _err("not_ready", "ویدیو هنوز بررسی نشده است؛ چند لحظه بعد دوباره امتحان کنید.", status.HTTP_409_CONFLICT)
        payload = autoedit_payload(upload.pk, platform=str(request.data.get("platform") or "")[:12], prompt=str(request.data.get("prompt") or ""),
                                   require_words=bool(request.data.get("wait_for_words")), deliver=request.data.get("deliver", True) is not False,
                                   sizes=request.data.get("sizes") if isinstance(request.data.get("sizes"), list) else None,
                                   captions=str(request.data.get("captions") or ""))
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "director", "kind": "run", "origin": "autoedit", "upload_id": upload.pk})
        failed = dispatch_job(job, director_task, job.id, payload)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


STILL_SIDE = 640


def _still(path, t: float, filters: list[str] | None = None) -> str:
    """One JPEG of the video at second `t` (optionally through colour filters) as a data URL, STILL_SIDE px wide."""
    from services.video.ffmpeg import FFMPEG

    chain = [f"scale={STILL_SIDE}:-2"] + list(filters or [])
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1", "-vf", ",".join(chain), "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=60, stdin=subprocess.DEVNULL).stdout
    if not raw:
        raise tl.TimelineError("از این لحظهٔ ویدیو تصویری گرفته نشد.")
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


#: where the preview looks first when no moment is asked for (fractions of the video): the middle, then around it, then the edges
LOOK_PROBES = (0.5, 0.15, 0.3, 0.7, 0.85, 0.05)


def default_look_time(path, duration: float) -> float:
    """The moment the light preview opens on: the first probe with a PERSON in it - the face is what the owner judges light by, and a recorded app
    screen (what the middle of his own video was) says «نیازی به اصلاح نبود» about a video whose face part does need it - else the middle."""
    middle = max(0.0, duration / 2)
    try:
        import tempfile
        from pathlib import Path as _P

        from services.video import faces
        from services.video.ffmpeg import FFMPEG

        ok, _why = faces.available()
        if not ok or duration < 2.0:
            return middle
        with tempfile.TemporaryDirectory(prefix="nm-lookt-") as work:
            for f in LOOK_PROBES:
                t = max(0.0, min(duration - 0.3, duration * f))
                jpg = _P(work) / f"p{int(f * 100)}.jpg"
                subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=512:-2", str(jpg)],
                               capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
                if jpg.is_file() and faces.in_image(jpg):
                    return round(t * 2) / 2
    except Exception as exc:  # noqa: BLE001 - the default frame is a courtesy: the middle is always a valid answer
        logger.info("look preview: default moment not chosen (%s)", exc)
    return middle


class LookPreviewView(APIView):
    """«قبل / بعد» of the automatic light and colour: the frame as shot and the same frame with the correction `auto_look` would apply to its shot.
    Nothing is saved; a correct shot comes back with `changed: false` and a sentence saying so."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        ref = str(request.query_params.get("ref") or "")
        try:
            item = editor_project.describe(store, ref)
            if item["kind"] != "video":
                raise tl.TimelineError("نورِ خودکار فقط برای ویدیو نشان داده می‌شود.")
            duration = float(item.get("duration") or 0.0)
            auto_t = False
            try:
                t = float(request.query_params.get("t"))
            except (TypeError, ValueError):
                t = default_look_time(item["path"], duration)
                auto_t = True
            t = max(0.0, min(max(0.0, duration - 0.2), t))
            ctx = store_ctx(store, asr=False)
            stats = ctx.look_stats(ref, max(0.0, t - 1.5), min(duration, t + 1.5)) or {}
            box = ctx.content_box(ref) or {}
            if box.get("found") and not stats.get("faces"):
                # a recorded phone/app screen: the director's `auto_look` leaves it alone (its whites are the interface, not a burnt sky) - so does the preview,
                # otherwise the panel would promise a correction the finished video never gets
                res = {"color": {}, "report": [], "changed": False, "skipped": "ضبطِ صفحهٔ برنامه است؛ نور و رنگ دست نخورد تا سفیدیِ صفحه و نوشته‌ها خراب نشود."}
            else:
                res = autolook.plan(stats, has_face=bool(stats.get("faces")), height=int(stats.get("height") or item.get("height") or 0))
            filters = color.build_filters(res["color"]) if res["changed"] else []
            before = _still(item["path"], t)
            after = _still(item["path"], t, filters) if filters else before
        except (editor_project.RefError, tl.TimelineError) as exc:
            return _err("bad_ref", str(exc))
        note = autolook.summary_fa(res["report"]) if res["changed"] else (res.get("skipped") or "نور و رنگِ این نما درست است؛ دست نمی‌خورد.")
        return Response({"ref": ref, "t": round(t, 2), "duration": round(duration, 2), "auto_t": auto_t, "changed": bool(res["changed"]), "before": before, "after": after, "note": note,
                         "report": [{k: r.get(k) for k in ("what", "from", "to", "note")} for r in res["report"]]})
