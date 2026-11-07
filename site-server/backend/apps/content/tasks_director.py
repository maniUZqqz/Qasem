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
        job.mark_completed(final)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Director job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}
