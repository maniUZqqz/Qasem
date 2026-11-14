"""The director's background job: analyse → plan → build the variants → (maybe) preview + vision critique.

The job result carries everything the panel shows (brief, AI notes, what was degraded, per-variant Persian plan + critique). Each variant
is saved as a lightweight `DirectorDraft` (the project JSON + plan + critique; the media stay where they are). It becomes an ordinary
`VideoProject` only when the owner opens it in the manual workspace; unopened drafts expire (`services.editing.director.drafts`).
"""
from __future__ import annotations

import base64
import logging
import subprocess
import uuid
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from services.editing import timeline as tl
from services.editing.director import loop as director_loop
from services.editing.director import drafts as drafts_mod
from services.editing.director import projectops as ops
from services.editing.director.ctx import store_ctx
from services.editing.director.runner import validate_plan
from services.media import files as media

from .models import DirectorDraft

logger = logging.getLogger(__name__)


def _editing_root() -> Path:
    path = Path(settings.MEDIA_ROOT) / "generated" / "editing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slim_plan(views: list[dict]) -> list[dict]:
    keys = ("id", "tool", "title", "text", "group", "why", "params", "on", "round", "ok", "skipped", "message", "notes")
    return [{k: v.get(k) for k in keys if k in v} for v in views]


def slim_critique(report: dict) -> dict:
    return {"score": report["score"], "summary": report["summary"], "vision": report.get("vision"),
            "items": [{k: i.get(k) for k in ("key", "title", "ok", "severity", "detail")} for i in report["items"]]}


#: steps that need the processing server (speech recognition, text-to-speech). When it is only OFF the Director still builds every variant at once and
#: these steps are filled in later (`director_fill_task`), instead of the whole job failing or the owner getting variants without captions for good.
NODE_STEPS = ("add_captions", "remove_fillers", "remove_retakes", "background", "add_voiceover")
STEP_KEYS = ("id", "tool", "params", "on", "why")


def node_pending(variants: list[dict]) -> list[dict]:
    """[{draft, steps}] — plan steps that failed ONLY because the processing server is off (their message says «در صف …»)."""
    out = []
    for v in variants:
        steps = [s for s in v.get("plan", []) if s.get("tool") in NODE_STEPS and s.get("ok") is False and s.get("on", True) and str(s.get("message") or "").startswith("در صف")]
        if steps and v.get("draft_id"):
            out.append({"draft": v["draft_id"], "steps": [{k: s[k] for k in STEP_KEYS if k in s} for s in steps]})
    return out


def _log_failure(log, what: str, job_id, exc) -> None:
    """A run that stops because the processing server is OFF is not a failure: `Job.mark_failed` parks it in the durable queue and it goes on by
    itself when the server is on.  It is logged as one line at INFO (not as an ERROR with a traceback) so a person watching celery.log is not
    told the owner's run failed when it is waiting by design."""
    from apps.compute import park

    if park._flag_of(exc):
        log.info("%s %s waits for the processing server (parked): %s", what, job_id, exc)
    else:
        log.exception("%s %s failed", what, job_id)


def deliver_draft(store, spec: dict) -> dict:
    """THE OUTPUT of the automatic edit: the finished draft becomes an ordinary project and is rendered at final quality - on the processing
    node (NVENC) as soon as it is online, parked in the durable queue until then - so the owner has a video to watch, not only a draft.
    `spec` = {draft, parent, sizes?}: one render of the project as it is, or (`sizes`) one project + render per network.  A draft the owner
    already opened (or that expired) is theirs now and is never rendered behind their back.  Never raises: the draft is already saved."""
    from services.editing import export as export_module
    from services.editing import social_sizes

    from .tasks_editing import render_project_task
    from .views_autoedit import dispatch_sizes
    from .views_editor_pro import snapshot_path
    from .models import VideoProject

    try:
        draft = DirectorDraft.objects.filter(pk=spec.get("draft"), store=store, promoted_at__isnull=True).first()
        if draft is None:
            return {"skipped": "پیش‌نویس باز شده یا پاک شده؛ خروجیِ خودکار ساخته نشد."}
        project = drafts_mod.promote(draft)
        if spec.get("captions") in ("burn", "soft"):
            data0 = dict(project.data or {})
            data0["export"] = {**(data0.get("export") or {}), "captions": spec["captions"]}
            project.data = data0
            project.save(update_fields=["data", "updated_at"])
        parent = spec.get("parent")
        keys = social_sizes.clean_keys(spec.get("sizes"))
        if keys:
            made, skipped = dispatch_sizes(store, project, keys, project.data or {}, store_ctx(store, user=None, asr=False), origin="autoedit", parent=parent)
            return {"project_id": project.pk, "renders": made, "skipped": skipped}
        data = project.data or {}
        block = export_module.default_export(data.get("export") or {}, export_module.preset_hint(data))
        job = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={
            "what": "project", "project_id": project.pk, "quality": "final", "preset": str(block.get("preset") or ""), "origin": "autoedit", "parent_job": parent})
        project.state = VideoProject.State.RENDERING
        project.error = ""
        project.save(update_fields=["state", "error", "updated_at"])
        failed = dispatch_job(job, render_project_task, job.id, project.pk, "final", snapshot_path(project, f"render_{job.id}.json", data))
        if failed is not None:
            project.state = VideoProject.State.FAILED
            project.error = "رندر شروع نشد."
            project.save(update_fields=["state", "error", "updated_at"])
            return {"project_id": project.pk, "renders": [], "skipped": [{"size": "", "title": project.title, "reason": "صفِ پردازش در دسترس نیست."}]}
        return {"project_id": project.pk, "renders": [{"size": "", "title": project.title, "project_id": project.pk, "job_id": job.id, "notes": []}], "skipped": []}
    except Exception as exc:  # noqa: BLE001 — the draft is saved; a failed hand-over must not fail the whole run
        logger.exception("could not hand the automatic edit over to the renderer")
        return {"skipped": f"رندرِ خودکار شروع نشد ({exc}); پیش‌نویس سر جایش است."}


def _queue_fill(job: Job, store, payload: dict, result: dict, final: dict, deliver: dict | None = None) -> None:
    """After a run: queue the node-only steps (and the vision critique) as durable follow-up jobs; they park themselves while the server is off."""
    try:
        pending = node_pending(result["variants"]) if payload.get("asr", True) else []
        if pending:
            count = sum(len(p["steps"]) for p in pending)
            fill = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "director_fill", "of": job.id, "count": count})
            if dispatch_job(fill, director_fill_task, fill.id, {"items": pending, **({"deliver": deliver} if deliver else {})}) is None:
                final["waiting_node"] = {"job_id": fill.id, "steps": count, "then_render": bool(deliver)}
                final.setdefault("degraded", []).append(f"{count} مرحله (زیرنویس، حذفِ «اِم و اوم» یا گویندگی) به سرورِ پردازش نیاز دارد که الان روشن نیست؛ در صفِ پردازش ماند و با روشن شدنش خودکار به پیش‌نویس‌ها اضافه می‌شود.")
        opts = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        primary = next((v for v in result["variants"] if v["key"] == result.get("primary")), None)
        if opts.get("use_ai") and opts.get("preview", True) and primary and primary.get("draft_id") and not (primary.get("critique") or {}).get("vision"):
            vis = Job.objects.create(store=store, type=Job.Type.VIDEO_EDIT, context={"what": "director_vision", "of": job.id})
            body = {"draft": primary["draft_id"], "request": str(payload.get("prompt") or "")[:600], "brief": result.get("brief") or {}}
            if dispatch_job(vis, director_vision_task, vis.id, body) is None:
                final["waiting_vision"] = {"job_id": vis.id}
    except Exception:  # noqa: BLE001 — the follow-ups are a courtesy; the variants are already saved
        logger.exception("could not queue the Director follow-ups of job %s", job.id)


def _frames_of(video: Path, total: float, n: int = 6) -> list[str]:
    from services.video.ffmpeg import FFMPEG

    out = []
    for i in range(n):
        t = max(0.0, min(total - 0.1, total * (i + 0.5) / n))
        jpg = video.with_name(f"{video.stem}_f{i}.jpg")
        subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2", str(jpg)],
                       check=False, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        if jpg.is_file() and jpg.stat().st_size > 0:
            out.append(base64.b64encode(jpg.read_bytes()).decode("ascii"))
        jpg.unlink(missing_ok=True)
    return out


def preview_reviewer(job: Job, store, holder: dict):
    """`review_preview(project) -> [b64 jpg]`: renders the project small (the real graph at 360 p) and returns 6 evenly spaced frames."""
    from services.editing import export as export_module

    from . import editor_project
    from .tasks_editing import _render_slot

    def review(project: dict) -> list[str]:
        folder = _editing_root() / f"director_{job.id}"
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / "preview.mp4"
        with _render_slot(job):
            with editor_project.sources(store) as resolve:
                timeline = tl.from_project(project, resolve)
                export_module.render(timeline, out, quality="draft", export={"height": 360, "quality": "small", "fps": 15, "audio_kbps": 64})
        holder["url"] = settings.MEDIA_URL.rstrip("/") + "/" + media.media_rel(out)
        holder["seconds"] = round(timeline.length, 1)
        return _frames_of(out, timeline.length)

    return review


def _options(raw: dict) -> director_loop.Options:
    raw = raw if isinstance(raw, dict) else {}
    return director_loop.Options(
        variants=max(1, min(3, int(raw.get("variants") or 3))),
        rounds=max(0, min(3, int(raw.get("rounds", 2)))),
        use_ai=bool(raw.get("use_ai", True)),
        preview=bool(raw.get("preview", True)),
        music_ref=str(raw.get("music_ref") or ""),
        require_words=bool(raw.get("require_words")),
        override=raw.get("override") if isinstance(raw.get("override"), dict) else {})


@shared_task(bind=True)
def director_task(self, job_id, payload):
    job = Job.objects.get(id=job_id)
    store = job.store
    try:
        job.total_steps = 100
        job.mark_running("آغازِ کارگردان")
        kind = payload.get("kind", "run")
        refs = [str(r) for r in (payload.get("refs") or [])][:24]
        ctx = store_ctx(store, user=None, asr=bool(payload.get("asr", True)))
        assets, missing = [], []
        for ref in refs:
            item = ctx.describe(ref)
            if item:
                assets.append(item)
            else:
                missing.append(ref)

        def report(fraction, label=""):
            job.mark_progress(int(100 * max(0.0, min(0.99, fraction))), label)

        holder: dict = {}
        if kind == "rerun":
            raw_steps = payload.get("steps") or []
            steps, problems = validate_plan(raw_steps)
            # validate_plan drops invalid steps; keep the owner's on/off switches for the ones that stayed
            kept = [s for s in raw_steps if isinstance(s, dict)]
            for i, st in enumerate(steps):
                st["on"] = bool(kept[i].get("on", True)) if i < len(kept) else True
            v = director_loop.rerun(payload.get("brief") or {}, steps, assets, ctx, key=str(payload.get("variant") or "a"))
            result = {"brief": payload.get("brief") or {}, "ai": {"asked": False, "ok": False, "enabled": False, "needed_for": []},
                      "degraded": list(problems), "variants": [v], "primary": v["key"], "analysis": {}}
        else:
            opts = _options(payload.get("options"))
            reviewer = preview_reviewer(job, store, holder) if opts.preview else None
            result = director_loop.run(str(payload.get("prompt") or ""), assets, ctx, store=store, options=opts, review_preview=reviewer,
                                       progress=report, job=job)
        if result.get("error"):
            raise ValueError(result["error"])
        if missing:
            result.setdefault("degraded", []).append(f"{len(missing)} منبع پیدا نشد و کنار گذاشته شد.")

        drafts_mod.purge(store)
        run_id = uuid.uuid4().hex[:10]
        title_base = (result.get("brief") or {}).get("title") or "ویدیو"
        rows = []
        replace_id = payload.get("replace_draft")
        for v in result["variants"]:
            data = dict(v["project"])
            data["director"] = {"run": run_id, "variant": v["key"], "variant_title": v["title"], "brief": result.get("brief"), "plan": slim_plan(v["plan"]),
                                "critique": slim_critique(v["critique"]), "refs": refs, "prompt": str(payload.get("prompt") or "")[:600],
                                "made_at": timezone.now().isoformat()}
            title = f"{title_base} — {v['title']}"[:200]
            length = ops.project_length(v["project"])
            draft = None
            if replace_id and kind == "rerun":
                # only an UNOPENED draft is replaced in place; a project the owner opened is never touched by a re-run
                draft = DirectorDraft.objects.filter(pk=replace_id, store=store, promoted_at__isnull=True).first()
            if draft is not None:
                drafts_mod.replace(draft, title=title, data=data, score=v["score"], length=length)
            else:
                draft = drafts_mod.create(store, run=run_id, job_id=job.id, key=v["key"], title=title, data=data, score=v["score"], length=length)
            rows.append({"key": v["key"], "id": draft.pk, "title": draft.title, "score": v["score"], "length": round(length, 1)})
            v["draft_id"] = draft.pk
        job.mark_progress(99, "ذخیرهٔ پیش‌نویس‌ها")
        final = {
            "run": run_id, "kind": kind, "brief": result.get("brief"), "platform": result.get("platform"), "recipe_title": result.get("recipe_title"),
            "ai": result.get("ai"), "degraded": result.get("degraded", []), "primary": result.get("primary"), "analysis": result.get("analysis"),
            "drafts": rows, "preview": holder or None, "draft_days": drafts_mod.get_settings(store)["draft_days"],
            "variants": [{"key": v["key"], "title": v["title"], "draft_id": v.get("draft_id"), "project_id": None, "score": v["score"], "rounds": v.get("rounds", 0),
                          "ai_steps": v.get("ai_steps", 0), "plan": slim_plan(v["plan"]), "critique": slim_critique(v["critique"]), "problems": v.get("problems", [])}
                         for v in result["variants"]],
        }
        if kind == "run":
            raw_opts = payload.get("options") if isinstance(payload.get("options"), dict) else {}
            spec = None
            if raw_opts.get("deliver"):
                primary = next((v for v in result["variants"] if v["key"] == result.get("primary")), None)
                if primary and primary.get("draft_id"):
                    spec = {"draft": primary["draft_id"], "parent": job.id, "sizes": raw_opts.get("sizes") or [],
                            "captions": raw_opts.get("captions") if raw_opts.get("captions") in ("burn", "soft") else ""}
            _queue_fill(job, store, payload, result, final, deliver=spec)
            if spec and not final.get("waiting_node"):
                job.mark_progress(99, "ساختِ خروجی")
                final["delivered"] = deliver_draft(store, spec)
        job.mark_completed(final)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        _log_failure(logger, "Director job", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def director_fill_task(self, job_id, payload):
    """Run, later, the steps of the drafts that needed the processing server (captions, filler removal, voice-over). The job waits in the
    durable queue while the server is off (`park.gate`) and is started again by the queue when it comes online."""
    from apps.compute import park
    from services.editing.director.brief import PLATFORMS
    from services.editing.director.runner import apply_steps

    job = Job.objects.get(id=job_id)
    store = job.store
    try:
        if park.gate(job, "voice"):
            return {"waiting": "node"}
        job.total_steps = max(1, len(payload.get("items") or []))
        job.mark_running("سرورِ پردازش روشن شد؛ تکمیلِ زیرنویس‌ها")
        ctx = store_ctx(store, user=None, asr=True)
        done = still = 0
        for n, item in enumerate(payload.get("items") or [], start=1):
            draft = DirectorDraft.objects.filter(pk=item.get("draft"), store=store, promoted_at__isnull=True).first()   # an opened draft is the owner's: never touched
            if draft is None:
                continue
            meta = dict((draft.data or {}).get("director") or {})
            platform = ((meta.get("brief") or {}).get("platform")) or "reels"
            zone = (PLATFORMS.get(platform) or PLATFORMS["reels"])["zone"]
            new, results = apply_steps(draft.data, item.get("steps") or [], ctx, platform=zone)
            by_id = {r["id"]: r for r in results}
            for p in meta.get("plan") or []:
                r = by_id.get(p.get("id"))
                if r:
                    p.update(ok=r["ok"], skipped=r["skipped"], message=r["message"], notes=r["notes"])
            ok_now = sum(1 for r in results if r["ok"])
            done += ok_now
            still += len(results) - ok_now
            if ok_now:
                new["director"] = {**meta, "filled_at": timezone.now().isoformat()}
                drafts_mod.replace(draft, title=draft.title, data=new, score=draft.score, length=ops.project_length(new))
            job.mark_progress(n, "")
        result = {"filled": done, "still_missing": still}
        if payload.get("deliver"):
            job.mark_progress(len(payload.get("items") or []), "ساختِ خروجی")
            result["delivered"] = deliver_draft(store, payload["deliver"])
        job.mark_completed(result)
        return {"ok": True, "filled": done}
    except Exception as exc:  # noqa: BLE001
        _log_failure(logger, "Director fill job", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def director_vision_task(self, job_id, payload):
    """The vision critique of the primary draft's preview, done later when a model that can look at pictures is available (it needs the
    processing server's Ollama or the paid API). The Director itself never waits for it."""
    from apps.compute import park
    from services.editing.director import ai as ai_mod

    job = Job.objects.get(id=job_id)
    store = job.store
    try:
        if park.gate(job, "ollama"):
            return {"waiting": "node"}
        job.total_steps = 3
        job.mark_running("نقدِ تصویریِ پیش‌نمایش")
        draft = DirectorDraft.objects.filter(pk=payload.get("draft"), store=store, promoted_at__isnull=True).first()
        if draft is None:
            job.mark_completed({"skipped": "draft gone or opened"})
            return {"ok": True}
        frames = preview_reviewer(job, store, {})(draft.data) or []
        job.mark_progress(2, "")
        if not frames:
            job.mark_completed({"ok": False, "reason": "پیش‌نمایش ساخته نشد"})
            return {"ok": False}
        parsed, info = ai_mod.vision_review(store, str(payload.get("request") or ""), payload.get("brief") or {}, frames, job=job)
        if not parsed:
            job.mark_completed({"ok": False, "reason": info.get("error") or "مدلِ بینایی جواب نداد"})
            return {"ok": False}
        data = dict(draft.data)
        meta = dict(data.get("director") or {})
        critique = dict(meta.get("critique") or {})
        critique["vision"] = {"scores": parsed.get("scores"), "issues": (parsed.get("issues") or [])[:5], "verdict": parsed.get("verdict", ""), "via": info.get("via", "")}
        meta["critique"] = critique
        data["director"] = meta
        draft.data = data
        draft.save(update_fields=["data", "updated_at"])
        job.mark_completed({"ok": True})
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        _log_failure(logger, "Director vision job", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}
