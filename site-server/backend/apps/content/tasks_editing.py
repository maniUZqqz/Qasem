"""Celery tasks for the editing engine. §8–§10.

Three jobs, in the order a shop meets them: look at what they uploaded, edit it,
then cut it into every format they publish to.

The analysis job exists separately from the editing job for a reason worth
stating: measuring a video costs an ffmpeg pass per thing measured, and a shop
opening the editor should not wait for that before seeing anything. So the
measurements are taken once on upload and cached on the row, and every later
screen reads them instantly.
"""
import contextlib
import json
import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings

from apps.jobs.models import Job
from services.editing import agent, analysis, edl, preferences
from services.media import files as media
from services.video import subtitles

from .models import UploadedVideo, VideoProject

logger = logging.getLogger(__name__)


def _work_dir(upload: UploadedVideo) -> Path:
    path = Path(settings.MEDIA_ROOT) / "generated" / "editing" / f"upload_{upload.pk}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _media_rel(path: Path) -> str:
    return media.media_rel(path)


#: The measurements worth putting next to each other. Face boxes and forty
#: silence spans are for the code; these are for a person.
COMPARABLE = (
    "duration", "silence_count", "silence_seconds", "longest_silence",
    "brightness", "p5", "p50", "p95", "clip_hi", "cast_rb", "cast_measurable",
    "flicker", "shake", "motion", "faces", "width", "height", "fps",
    "noise_floor_db", "snr_db",
)


def _comparable(facts: dict) -> dict:
    return {k: facts[k] for k in COMPARABLE if facts and facts.get(k) is not None}


@shared_task(bind=True)
def analyze_upload_task(self, job_id, upload_id):
    """Measure one uploaded video, once. §8"""
    job = Job.objects.get(id=job_id)
    try:
        upload = UploadedVideo.objects.select_related("store").get(id=upload_id)
        upload.state = UploadedVideo.State.ANALYZING
        upload.save(update_fields=["state", "updated_at"])

        job.total_steps = 1
        job.mark_running("در حال بررسی ویدیو")

        with media.reading(upload.video) as source:
            facts = analysis.describe(source, _work_dir(upload))
        if not facts.get("readable"):
            upload.state = UploadedVideo.State.FAILED
            upload.error = facts.get("reason", "ویدیو خوانده نشد")
            upload.save(update_fields=["state", "error", "updated_at"])
            raise RuntimeError(upload.error)

        upload.facts = facts
        upload.duration = facts["duration"]
        upload.has_audio = facts["has_audio"]
        upload.state = UploadedVideo.State.READY
        upload.error = ""
        upload.save(update_fields=[
            "facts", "duration", "has_audio", "state", "error", "updated_at",
        ])

        job.mark_progress(1, "")
        result = {
            "upload_id": upload.pk,
            "facts": facts,
            "findings": analysis.obvious_problems(facts),
        }
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Video analysis job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def edit_video_task(self, job_id, upload_id, mode, operations=None, instruction=""):
    """Plan, render, look again. §9's loop, as a job.

    The shop's decisions are recorded whatever the outcome — that is what makes
    «مثل همیشه ادیت کن» possible later, and a run that failed still says
    something about what they were willing to try.
    """
    job = Job.objects.get(id=job_id)
    try:
        upload = UploadedVideo.objects.select_related("store").get(id=upload_id)
        job.total_steps = 3
        job.mark_running("در حال بررسی ویدیو")

        work = _work_dir(upload)
        operations = list(operations or [])
        with contextlib.ExitStack() as stack:
            source = stack.enter_context(media.reading(upload.video))
            # A subtitle file the shop asked to have burnt in rides along with
            # the edit: one render instead of two, and the caption is placed
            # after the zoom so it cannot be cropped off. Only when the shop's
            # setting says "burn", and only if the plan does not already carry
            # a subtitle operation of its own.
            subtitle_file = None
            if upload.subtitles and subtitles.subtitles_burned(upload, upload.store):
                subtitle_file = stack.enter_context(media.reading(upload.subtitles))
                if not any(str(o.get("tool")) == "subtitle" for o in operations if isinstance(o, dict)):
                    operations.append({
                        "tool": "subtitle",
                        "params": {
                            "position": preferences.habits(upload.store).get(
                                "subtitle_position", "bottom",
                            ),
                        },
                        "reason": "زیرنویس طبق تنظیم فروشگاه روی تصویر می‌سوزد",
                    })
            outcome = agent.run(
                source,
                work / "edited.mp4",
                work,
                mode=mode,
                operations=operations,
                instruction=instruction,
                store=upload.store,
                job=job,
                subtitle_file=subtitle_file,
            )

        job.mark_progress(2, "در حال تدوین")

        # A decision is "accepted" when a person chose it and the render was
        # kept. AUTO and DIRECTED rows are still recorded — they are the audit
        # trail — but `preferences.learn` reads habits from human decisions
        # only, so four Auto runs cannot teach the system its own defaults.
        kept = outcome.output is not None
        for operation in outcome.plan.edl.operations:
            preferences.record(
                upload.store,
                tool=operation.tool,
                params=operation.params,
                accepted=kept if mode == agent.MANUAL else mode != agent.SUGGEST,
                source=mode,
            )
        if mode != agent.SUGGEST:
            preferences.refresh(upload.store)

        if outcome.output is not None:
            final = work / "edited.mp4"
            if Path(outcome.output) != final:
                final.write_bytes(Path(outcome.output).read_bytes())
            media.store(upload.edited, final)
            upload.state = UploadedVideo.State.EDITED

        # Before/after, kept on the row: the panel shows the original and the
        # edited cut side by side with the numbers that changed, and a shop
        # deciding whether the edit helped should not need the job that made it.
        upload.edit_outcome = {
            "mode": mode,
            "instruction": instruction,
            "kept": outcome.output is not None,
            "improved": outcome.improved,
            "note": outcome.note,
            "rounds": outcome.rounds,
            "summary": outcome.plan.edl.summary(),
            "operations": [o.as_dict() for o in outcome.plan.edl.operations],
            "refusals": outcome.plan.edl.refusals,
            "before": _comparable(outcome.before),
            "after": _comparable(outcome.after),
            "effects": outcome.effects,
            # Which noise remover ran and what it measured, when one did — the
            # before/after SNR rows say THAT it helped; this says with what.
            "denoise": dict(outcome.denoise) or None,
        }
        upload.save(update_fields=["edited", "state", "edit_outcome", "updated_at"])

        job.mark_progress(3, "")
        result = {
            "upload_id": upload.pk,
            "edited": upload.edited.url if upload.edited else None,
            "original": upload.video.url if upload.video else None,
            **outcome.as_dict(),
        }
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Video edit job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def repurpose_upload_task(self, job_id, upload_id, formats=None):
    """One video, every format the shop publishes to. §10"""
    job = Job.objects.get(id=job_id)
    try:
        from services.video import repurpose

        upload = UploadedVideo.objects.select_related("store").get(id=upload_id)
        # The edited cut when there is one: a shop that just fixed the colour
        # does not want five copies of the version they fixed.
        newest = upload.edited if upload.edited else upload.video
        wanted = [
            key for key in (formats or []) if key in repurpose.FORMATS_BY_KEY
        ] or list(repurpose.FORMATS_BY_KEY)
        job.total_steps = len(wanted)
        job.mark_running("در حال ساخت نسخه‌های مختلف")

        with media.reading(newest) as source:
            cuts = repurpose.make_all(source, _work_dir(upload) / "cuts", wanted)
        made = []
        for cut in cuts:
            if cut["ok"]:
                cut["url"] = f"{settings.MEDIA_URL}{_media_rel(Path(cut.pop('path')))}"
            made.append(cut)

        # One format failing is not all of them failing; a shop with four
        # publishable cuts and a message about the fifth is better served than
        # one with an exception.
        if not any(cut["ok"] for cut in made):
            raise RuntimeError("هیچ‌کدام از قالب‌ها ساخته نشد.")

        result = {"upload_id": upload.pk, "formats": made}
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Repurpose job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def append_real_photo_task(self, job_id, script_id, prefer="owner"):
    """Put the shop's real photo at the end of a finished video. §26

    Runs on the newest cut that exists — voiced if there is one, otherwise the
    plain one. Appending to the wrong version is the obvious bug here: a shop
    that just paid for narration would get a silent video back.
    """
    from apps.content.models import VideoScript
    from services.content import trust

    job = Job.objects.get(id=job_id)
    try:
        script = VideoScript.objects.select_related("product", "store").get(id=script_id)
        source = script.final_video_voiced or script.final_video
        if not source:
            raise RuntimeError("اول باید ویدیو ساخته شده باشد.")

        job.total_steps = 1
        job.mark_running("در حال اضافه‌کردن عکس واقعی")

        out = (
            Path(settings.MEDIA_ROOT) / "generated" / "videos"
            / f"script_{script.pk}" / "final_real.mp4"
        )
        with trust.open_real_photo(script.store, script.product, prefer=prefer) as photo:
            with media.reading(source) as video_path:
                trust.append_to_video(video_path, photo, out)
            described = photo.as_dict()

        media.store(script.final_video_real, out)
        script.save(update_fields=["final_video_real", "updated_at"])

        job.mark_progress(1, "")
        result = {
            "script_id": script.pk,
            "video": script.final_video_real.url,
            "photo": described,
        }
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Real-photo job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def build_subtitles_task(self, job_id, script_id):
    """Subtitles for a video we made ourselves. §8

    No speech-to-text: the narration is a column in our own database. What is
    unknown is *when* each line falls, and that comes from the pauses in the
    narration audio we already rendered.
    """
    from apps.content.models import VideoScript, VideoSegment
    from services.video import subtitles
    from services.video.ffmpeg import probe_duration

    job = Job.objects.get(id=job_id)
    try:
        script = VideoScript.objects.select_related("store").get(id=script_id)
        scenes = list(script.scenes.all())
        if not any((s.narration or "").strip() for s in scenes):
            raise RuntimeError("هیچ‌کدام از صحنه‌ها نریشن ندارند.")

        job.total_steps = 1
        job.mark_running("در حال ساخت زیرنویس")

        work = Path(settings.MEDIA_ROOT) / "generated" / "subtitles" / f"script_{script.pk}"
        work.mkdir(parents=True, exist_ok=True)

        # The per-scene narration clips the voice job wrote. Real audio means
        # real pause detection; without them the timing falls back to
        # proportional and the result says so.
        audio_dir = Path(settings.MEDIA_ROOT) / "generated" / "audio" / f"script_{script.pk}"
        done = {
            s.index: s for s in script.segments.filter(status=VideoSegment.Status.DONE)
        }

        def clip_for(scene):
            clip = audio_dir / f"scene_{scene.index}.m4a"
            return clip if clip.exists() else None

        def duration_for(scene):
            segment = done.get(scene.index)
            if segment is None or not segment.video:
                return scene.duration
            try:
                with media.reading(segment.video) as path:
                    return probe_duration(path)
            except Exception:  # noqa: BLE001 — the planned length is a fine fallback
                return scene.duration

        built = subtitles.build_for_scenes(
            scenes, work, clip_for=clip_for, duration_for=duration_for,
        )
        if not built["cues"]:
            raise RuntimeError("متنی برای زیرنویس پیدا نشد.")

        path = subtitles.write_srt(built["cues"], work / "subtitles.srt")
        media.store(script.subtitles, path)
        script.save(update_fields=["subtitles", "updated_at"])

        job.mark_progress(1, "")
        result = {
            "script_id": script.pk,
            "url": script.subtitles.url,
            "count": built["count"],
            "measured": built["measured"],
            "word_level": built["word_level"],
            "note": built["note"],
        }
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Subtitle job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def add_music_task(self, job_id, script_id, level_db=None, duck=True):
    """Lay the shop's own music under the narration. §7 (phase 22)"""
    from apps.content.models import VideoScript
    from services.audio import music as music_engine

    job = Job.objects.get(id=job_id)
    try:
        script = VideoScript.objects.select_related("store").get(id=script_id)
        if not script.music:
            raise RuntimeError(music_engine.LICENCE_NOTE)

        # The newest cut, so a shop that just added their photo does not get
        # music on the version from two steps ago.
        source = (
            script.final_video_real
            or script.final_video_voiced
            or script.final_video
        )
        if not source:
            raise RuntimeError("اول باید ویدیو ساخته شده باشد.")

        job.total_steps = 1
        job.mark_running("در حال گذاشتن موسیقی")

        out = (
            Path(settings.MEDIA_ROOT) / "generated" / "videos"
            / f"script_{script.pk}" / "final_music.mp4"
        )
        with media.reading(source) as video_path, \
                media.reading(script.music) as music_path:
            track = music_engine.Track(
                path=music_path,
                level_db=(
                    script.music_level_db if level_db is None else float(level_db)
                ),
            )
            music_engine.under_narration(video_path, track, out, duck=duck)

        media.store(script.final_video_music, out)
        script.save(update_fields=["final_video_music", "updated_at"])

        job.mark_progress(1, "")
        result = {
            "script_id": script.pk,
            "video": script.final_video_music.url,
            "level_db": track.safe_level(),
            "ducked": duck,
        }
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Music job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def transcribe_upload_task(self, job_id, upload_id):
    """Subtitles for video the shop filmed themselves. §8

    Needs Whisper, because here we genuinely do not know what was said. Every
    uncertain line is marked rather than shown in the same typeface as a
    confident one — a shop can fix a word we got wrong, and cannot fix a line
    we quietly deleted.
    """
    from services.audio import transcribe
    from services.video import subtitles

    job = Job.objects.get(id=job_id)
    try:
        upload = UploadedVideo.objects.select_related("store").get(id=upload_id)
        if not upload.has_audio:
            raise RuntimeError(
                "این ویدیو صدا ندارد، پس چیزی برای زیرنویس کردن نیست."
            )

        ok, why = transcribe.available()
        if not ok:
            raise RuntimeError(why)

        job.total_steps = 2
        job.mark_running("در حال گوش دادن به ویدیو")

        work = _work_dir(upload)
        with media.reading(upload.video) as source:
            heard = transcribe.transcribe(source)

        job.mark_progress(1, "در حال ساخت زیرنویس")
        built = subtitles.from_transcript(heard)
        if not built["cues"]:
            raise RuntimeError("حرفی در این ویدیو شنیده نشد.")

        path = subtitles.write_srt(built["cues"], work / "subtitles.srt")
        media.store(upload.subtitles, path)
        upload.transcript = [s.as_dict() for s in heard.segments]
        upload.save(update_fields=["subtitles", "transcript", "updated_at"])

        job.mark_progress(2, "")
        result = {
            "upload_id": upload.pk,
            "url": upload.subtitles.url,
            "count": built["count"],
            "word_level": built["word_level"],
            "uncertain_lines": built["uncertain_lines"],
            "note": built["note"],
            "model": heard.model,
        }
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Transcription job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def make_proxy_task(self, job_id, ref):
    """A small, browser-playable copy of a big (or browser-unfriendly) clip, for scrubbing in the «دستی» workspace.
    The export always uses the original — the proxy keeps the frame rate so a cut lands on the same frame."""
    from services.editing import timeline as tl

    from . import editor_project

    job = Job.objects.get(id=job_id)
    try:
        job.total_steps = 1
        job.mark_running("در حال ساختنِ پیش‌نمایشِ سبک")
        kind, pk = editor_project.parse_ref(ref)
        found = editor_project.locate(job.store, ref)
        out = editor_project.proxy_path(kind, pk)
        with media.reading(found["field"]) as source:
            if not (out.is_file() and out.stat().st_size > 0):
                tl.make_proxy(source, out, force=True)
            result = {"ref": ref, "proxy_url": editor_project._rel_url(out), "savings": tl.proxy_savings(source, out)}
        job.mark_progress(1, "")
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Proxy job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


# ------------------------------------------------------------ the render queue

#: Only one render at a time on this small server: the others wait their turn («در صف») and can be cancelled.
RENDER_LOCK = "render.lock"
KEEP_EXPORTS = 4
KEEP_PREVIEWS = 3


class _Cancelled(Exception):
    pass


def _editing_root() -> Path:
    path = Path(settings.MEDIA_ROOT) / "generated" / "editing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cancelled(job_id) -> bool:
    return Job.objects.filter(pk=job_id, state=Job.State.CANCELLED).exists()


@contextlib.contextmanager
def _render_slot(job: Job):
    """Wait for the single render slot (polling, so a cancel while queued is noticed), hold it, release it."""
    import fcntl
    import time

    handle = open(_editing_root() / RENDER_LOCK, "a+")
    waited = False
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if _cancelled(job.id):
                    raise _Cancelled() from None
                if not waited:
                    waited = True
                    job.mark_progress(0, "در صفِ رندر — یک رندرِ دیگر در حال اجراست")
                time.sleep(1.0)
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def _percent(job: Job, lo: int, hi: int, label: str):
    """A progress callback that maps ffmpeg's 0..1 onto [lo, hi] percent of the job (a save every ~0.7 s at most)."""
    import time

    state = {"t": 0.0, "p": -1}

    def report(fraction: float) -> None:
        now = time.monotonic()
        p = int(lo + (hi - lo) * max(0.0, min(1.0, fraction)))
        if p != state["p"] and now - state["t"] > 0.7:
            state["t"], state["p"] = now, p
            job.mark_progress(p, f"{label} — {p}٪")

    return report


def _percent_labelled(job: Job, lo: int, hi: int):
    """Like `_percent` for a producer that brings its own label: `report(fraction, label)`."""
    import time

    state = {"t": 0.0, "p": -1, "label": ""}

    def report(fraction: float, label: str) -> None:
        now = time.monotonic()
        p = int(lo + (hi - lo) * max(0.0, min(1.0, fraction)))
        if (p != state["p"] or label != state["label"]) and now - state["t"] > 0.7:
            state.update(t=now, p=p, label=label)
            job.mark_progress(p, f"{label} — {p}٪")

    return report


def _set_where(job: Job, where: str) -> None:
    job.context = {**(job.context or {}), "where": where}
    job.save(update_fields=["context", "updated_at"])


def _note_placement(job: Job, decision) -> None:
    """Keep what `placement.decide` said (where, why, the two estimates) in the job's context — for whoever wonders why a draft
    stayed on the site."""
    job.context = {**(job.context or {}), "placement": {
        "where": decision.where, "reason": decision.reason, "site_s": round(decision.site_seconds, 1),
        "node_s": None if decision.node_seconds is None else round(decision.node_seconds, 1), "uncached_bytes": decision.uncached_bytes}}
    job.save(update_fields=["context", "updated_at"])


def _snapshot_data(project: VideoProject, snapshot: str) -> dict:
    import json

    if snapshot:
        snap = Path(settings.MEDIA_ROOT) / snapshot
        if snap.is_file():
            return json.loads(snap.read_text(encoding="utf-8"))
    return project.data or {}


def _finish_replace(job, project, dest, rel, notes):
    """«رندر و جایگزینی» done: the rendered range becomes a media file of the shop (a ref the panel can put on the timeline)."""
    from services.video.ffmpeg import probe
    from services.video.ffmpeg import probe_duration

    from .models import UploadedVideo

    seconds = round(probe_duration(dest), 2)
    has_audio = False
    try:
        has_audio = any(s.get("codec_type") == "audio" for s in probe(dest).get("streams", []))
    except Exception:  # noqa: BLE001 — a probe failure only costs the audio flag
        pass
    title = f"رندرِ جایگزین · {project.title or project.pk}"[:200]
    up = UploadedVideo.objects.create(store=project.store, title=title, video=rel, state=UploadedVideo.State.READY, duration=seconds, has_audio=has_audio)
    project = VideoProject.objects.get(pk=project.pk)
    info = dict(project.render_info or {})
    replaced = dict(info.get("replaced") or {})
    replaced[str(job.id)] = {"ref": f"video:{up.pk}", "seconds": seconds, "has_audio": has_audio, "title": title, "note": " ".join(notes)}
    for stale in sorted(replaced, key=int)[:-20]:
        replaced.pop(stale, None)
    info["replaced"] = replaced
    project.render_info = info
    project.state = VideoProject.State.READY if project.output else VideoProject.State.DRAFT
    project.error = ""
    project.save(update_fields=["state", "error", "render_info", "updated_at"])
    job.mark_progress(100, "")
    result = {"project_id": project.pk, "replace_ref": f"video:{up.pk}", "seconds": seconds}
    job.mark_completed(result)
    return result


@shared_task(bind=True)
def render_project_task(self, job_id, project_id, quality="final", snapshot=""):
    """The «دستی» workspace's Export: timeline → one ffmpeg graph (stage one), then the program-wide tools through the
    single-source EDL pipeline (stage two) — so every one of the 21 tools has a place, per clip or on the whole video.

    Works on a SNAPSHOT of the project taken when Export was pressed (the editor keeps autosaving meanwhile), reads the
    ORIGINAL files (never proxies), waits for the single render slot, reports percent and honours cancel."""
    import shutil

    from django.utils import timezone

    from services.editing import export as export_module
    from services.editing import timeline as tl
    from services.video.ffmpeg import probe_duration

    from . import editor_project

    job = Job.objects.get(id=job_id)
    project = None
    work = None
    try:
        if job.state == Job.State.CANCELLED:             # cancelled before the worker even picked it up
            raise _Cancelled()
        project = VideoProject.objects.select_related("store").get(pk=project_id)
        data = _snapshot_data(project, snapshot)
        lowmem_notes: list[str] = []
        job.total_steps = 100
        job.mark_running("در حال چیدنِ تایم‌لاین")
        work = _editing_root() / f"project_{project.pk}"
        (work / "exports").mkdir(parents=True, exist_ok=True)
        # «رندر و جایگزینی»: only the in–out range is rendered (the clips' own effects, no whole-video tools) and kept as a new media file
        replace = bool((data.get("export") or {}).get("replace") is True and isinstance(data.get("inout"), dict))
        program_ops = [] if replace else tl.program_operations(data)
        job.mark_progress(1, "در حال چیدنِ تایم‌لاین")
        stage1 = work / f"program_{job.id}.mp4"
        where = {"where": "server", "node": "", "encoder": "libx264", "fallback": ""}
        with editor_project.sources(project.store) as resolve:
            timeline = tl.from_project(data, resolve)
            if replace:
                if not timeline.inout:
                    raise RuntimeError("بازهٔ جایگزینی نامعتبر است.")
                timeline = tl.window(timeline, timeline.inout["in"], timeline.inout["out"])
            # a final render always has settings: what the shop set, completed with defaults and the Director's platform preset
            spec_export = export_module.default_export(dict(timeline.export or {}), export_module.preset_hint(data)) if quality != "draft" else None
            spec = export_module.resolve(spec_export or {}, timeline) if quality != "draft" else None
            hi = 85 if program_ops else 98
            on_node = False
            # the final render goes to the processing node when one is online (and the shop did not pick «فقط سرورِ سایت»);
            # a quick draft only when placement.py finds it heavy and cheap to move (otherwise the site, quietly); offline,
            # failing or silent ⇒ the site renders it itself, and says so
            bundle, budget, grace = None, None, None
            send = quality == "final" and (timeline.export or {}).get("where") != "server"
            if quality == "draft" and (timeline.export or {}).get("where") != "server":
                from services.editing import noderender, placement

                try:
                    decision, bundle = noderender.plan_draft(timeline)
                except Exception:  # noqa: BLE001 — never let the placement guess cost the shop their draft
                    logger.exception("draft placement failed for job %s", job.id)
                    decision = placement.Decision("server", "error")
                _note_placement(job, decision)
                send = decision.on_node
                budget, grace = decision.budget, placement.DRAFT_QUEUE_GRACE
            if send:
                from services.editing import noderender

                try:
                    _set_where(job, "node")
                    got = noderender.render_on_node(job, timeline, spec_export or {}, stage1, progress=_percent_labelled(job, 2, hi),
                                                    cancel=lambda: _cancelled(job.id), store=project.store, profile=quality, bundle=bundle,
                                                    budget=budget, queue_grace=grace)
                    where = {"where": "node", "node": got["node"], "encoder": got.get("encoder", ""), "fallback": ""}
                    on_node = True
                except (noderender.NodeUnavailable, noderender.NodeFailed) as exc:
                    quiet = isinstance(exc, noderender.NodeUnavailable) and "روشن نیست" in str(exc)
                    where["fallback"] = "" if quiet else f"رندر روی سرورِ پردازش ممکن نشد ({exc}) و روی سرورِ سایت ساخته شد."
                    logger.info("Node render of job %s not used: %s", job.id, exc)
                    _set_where(job, "server")
            if not on_node:
                with _render_slot(job):
                    job.mark_progress(2, "در حال رندر روی سرورِ سایت")
                    tl.render(timeline, stage1, quality=quality, export=spec_export or None,
                              progress=_percent(job, 2, hi, "رندرِ تایم‌لاین"), cancel=lambda: _cancelled(job.id), notes=lowmem_notes)
        job.mark_progress(hi, "افکت‌های کلِ ویدیو" if program_ops else "ذخیرهٔ خروجی")

        final = stage1
        refusals: list[str] = []
        with _render_slot(job) if program_ops else contextlib.nullcontext():
            if program_ops:
                final = work / f"final_{job.id}.mp4"
                stage2 = work / f"stage2_{job.id}"
                plan = agent.plan(stage1, stage2, mode=agent.MANUAL, operations=program_ops, store=project.store, job=job)
                plan.edl.store = project.store
                if not plan.facts.get("readable", True):
                    raise RuntimeError(plan.edl.refusals[0] if plan.edl.refusals else "خروجیِ مرحلهٔ اول خوانده نشد")
                if edl.needs_stabilization_pass(plan.edl):
                    try:
                        edl.detect_stabilization(stage1, stage2, plan.edl)
                    except Exception as exc:  # noqa: BLE001
                        logger.info("Stabilisation detect failed: %s", exc)
                        plan.edl.stabilize = ""
                        plan.edl.refusals.append("ثابت‌کردن تصویر روی این ویدیو ممکن نشد و از تدوین حذف شد")
                edl.render(plan.edl, final)
                refusals = list(plan.edl.refusals)
                shutil.rmtree(stage2, ignore_errors=True)
                stage1.unlink(missing_ok=True)

        preset = str((spec_export or timeline.export or {}).get("preset") or "")
        fmt = str((timeline.export or {}).get("format") or "mp4")
        use_range = (timeline.export or {}).get("range") == "inout" and bool(timeline.inout)
        convert_note = " ".join(lowmem_notes)
        if replace:
            dest = work / "exports" / f"{job.id}_replace.mp4"
            Path(final).replace(dest)
        elif fmt != "mp4" or use_range:
            # one-shot outputs (GIF, still frame, sound only, only the in–out range) are cut from the finished render
            ext = export_module.FORMATS.get(fmt, ("mp4", ""))[0]
            dest = work / "exports" / f"{job.id}_{fmt if fmt != 'mp4' else (preset or quality) + '_range'}.{ext}"
            job.mark_progress(95, "ساختنِ خروجیِ خواسته‌شده")
            t0 = float(timeline.inout["in"]) if use_range else None
            t1 = float(timeline.inout["out"]) if use_range else None
            done = export_module.convert(final, dest, fmt, t0=t0, t1=t1, frame_t=float((timeline.export or {}).get("frame_t") or 0.0), spec=spec,
                                         cancel=lambda: _cancelled(job.id))
            convert_note = " ".join(x for x in (convert_note, done["note"]) if x)
            Path(final).unlink(missing_ok=True)
        else:
            dest = work / "exports" / f"{job.id}_{preset or quality}.mp4"
            Path(final).replace(dest)
        rel = media.media_rel(dest)
        if replace:
            return _finish_replace(job, project, dest, rel, lowmem_notes)
        w, h = export_module.size_for(timeline, spec.short_side if spec else None)
        project = VideoProject.objects.get(pk=project.pk)          # fresh: the editor may have saved meanwhile
        old = [e for e in (project.render_info or {}).get("exports", []) if isinstance(e, dict)]
        entry = {
            "job_id": job.id, "url": settings.MEDIA_URL.rstrip("/") + "/" + rel, "rel": rel, "preset": preset, "quality": quality,
            "seconds": 0.0 if fmt == "frame" else round(probe_duration(dest), 2), "bytes": dest.stat().st_size, "size": f"{w}x{h}",
            "format": fmt, "range": "inout" if use_range else "all",
            "codec": spec.codec if spec else "h264", "note": " ".join(x for x in (spec.note if spec else "", convert_note) if x),
            "rendered_at": timezone.now().isoformat(),
            "where": where["where"], "node": where["node"], "encoder": where["encoder"], "fallback": where["fallback"],
        }
        keep = [entry] + [e for e in old if e.get("job_id") != job.id][: KEEP_EXPORTS - 1]
        for gone in [e for e in old if e not in keep]:
            try:
                (Path(settings.MEDIA_ROOT) / gone.get("rel", "")).unlink(missing_ok=True)
            except OSError:
                pass
        if fmt == "mp4" and not use_range:
            project.output.name = rel                  # «آخرین خروجیِ پروژه» = یک ویدیوی کامل؛ GIF و عکس و فقط‌صدا و بازهٔ برش‌خورده فقط در فهرستِ خروجی‌ها می‌آیند
        project.state = VideoProject.State.READY if project.output else VideoProject.State.DRAFT
        project.error = ""
        project.render_info = {**entry, "refusals": refusals, "program_tools": [o["tool"] for o in program_ops], "exports": keep}
        project.save(update_fields=["output", "state", "error", "render_info", "updated_at"])
        _set_where(job, where["where"] + (f":{where['node']}" if where["node"] else ""))
        job.mark_progress(100, "")
        result = {"project_id": project.pk, "output": entry["url"], **{k: v for k, v in project.render_info.items() if k != "exports"}}
        job.mark_completed(result)
        return result
    except (_Cancelled, export_module.RenderCancelled):
        logger.info("Project render job %s cancelled", job_id)
        if project is not None:
            project = VideoProject.objects.get(pk=project.pk)
            project.state = VideoProject.State.READY if project.output else VideoProject.State.DRAFT
            project.save(update_fields=["state", "updated_at"])
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Project render job %s failed", job_id)
        if project is not None:
            project = VideoProject.objects.get(pk=project.pk)
            project.state = VideoProject.State.FAILED
            project.error = str(exc)[:1500]
            project.save(update_fields=["state", "error", "updated_at"])
        job.mark_failed(exc)
        return {"error": str(exc)}
    finally:
        if work is not None:
            (work / f"program_{job_id}.mp4").unlink(missing_ok=True)
        if snapshot:
            (Path(settings.MEDIA_ROOT) / snapshot).unlink(missing_ok=True)


@shared_task(bind=True)
def preview_range_task(self, job_id, project_id, snapshot, t0, t1, height=360):
    """«پیش‌نمایشِ دقیقِ این بازه»: the real graph for a few seconds at low resolution (waits for the render slot too)."""
    from services.editing import export as export_module
    from services.editing import timeline as tl

    from . import editor_project

    job = Job.objects.get(id=job_id)
    try:
        if job.state == Job.State.CANCELLED:
            raise _Cancelled()
        project = VideoProject.objects.select_related("store").get(pk=project_id)
        data = _snapshot_data(project, snapshot)
        job.total_steps = 100
        job.mark_running("در حال ساختنِ پیش‌نمایشِ دقیق")
        work = _editing_root() / f"project_{project.pk}" / "previews"
        work.mkdir(parents=True, exist_ok=True)
        out = work / f"preview_{job.id}.mp4"
        with _render_slot(job):
            with editor_project.sources(project.store) as resolve:
                timeline = tl.from_project(data, resolve)
                info = export_module.render_preview(timeline, out, float(t0), float(t1), height=int(height),
                                                    progress=_percent(job, 5, 98, "پیش‌نمایشِ دقیق"),
                                                    cancel=lambda: _cancelled(job.id))
        for old in sorted(work.glob("preview_*.mp4"), key=lambda p: p.stat().st_mtime)[:-KEEP_PREVIEWS]:
            old.unlink(missing_ok=True)
        result = {"url": settings.MEDIA_URL.rstrip("/") + "/" + media.media_rel(out), "t0": info["t0"], "t1": info["t1"],
                  "size": info["size"], "seconds": info["seconds"], "notes": info["notes"]}
        job.mark_progress(100, "")
        job.mark_completed(result)
        return result
    except (_Cancelled, export_module.RenderCancelled):
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Preview job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}
    finally:
        if snapshot:
            (Path(settings.MEDIA_ROOT) / snapshot).unlink(missing_ok=True)


@shared_task(bind=True)
def translate_captions_task(self, job_id, lang, items):
    """Caption translation: the lines go to the shop's text model in batches (the processing server's Qwen when online, else the API) and come
    back in the same order. A failure says WHY (no credit, server off, bad answer) instead of a blank error."""
    from services.editing import agent, translate

    job = Job.objects.get(id=job_id)
    try:
        if job.state == Job.State.CANCELLED:
            return {"cancelled": True}
        job.total_steps = max(1, -(-len(items) // translate.BATCH))
        job.mark_running("در حال ترجمهٔ زیرنویس")
        out = translate.translate(items, lang, store=job.store, job=job, progress=lambda done, total: job.mark_progress(done, f"ترجمهٔ بخش {done} از {total}"))
        result = {"lang": lang, "items": out, "count": len(out)}
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.info("Caption translation job %s: %s", job_id, exc)
        try:
            from apps.compute import park

            if park.maybe_park(job, exc):                    # no AI right now but a processing server is on record: wait for it
                return {"waiting": "node"}
        except Exception:  # noqa: BLE001 — parking is a courtesy; a failure keeps the old behaviour
            pass
        message = str(exc) if isinstance(exc, (translate.TranslateError, ValueError)) else agent.explain_failure(exc)[1]
        job.mark_failed(RuntimeError(message))
        return {"error": message}


@shared_task(bind=True)
def captions_task(self, job_id, ref, start, end, at, speed=1.0):
    """Auto-captions for a stretch of a clip: speech → words (the node's `voice.asr`, else a clear message) →
    caption lines with per-word timing, placed on the timeline at `at` (the clip's speed followed)."""
    import tempfile

    from services.editing import captions

    from . import editor_project

    job = Job.objects.get(id=job_id)
    wav = None
    try:
        from apps.compute import park

        if captions.status().get("waiting") and park.gate(job, "voice"):          # the server is off: wait in the queue, do not fail
            return {"waiting": "node"}
        job.total_steps = 3
        job.mark_running("در حال آماده‌کردنِ صدا")
        item = editor_project.describe(job.store, ref)
        if not item.get("has_audio"):
            raise captions.CaptionsUnavailable("این قطعه صدا ندارد، پس چیزی برای زیرنویس‌کردن نیست.")
        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        wav = Path(handle.name)
        captions.extract_audio(item["path"], float(start), float(end), wav)
        job.mark_progress(1, "در حال گوش‌دادن به گفتار (سرورِ پردازش)")
        heard = captions.transcribe_wav(wav, store=job.store, on_tick=lambda j: job.mark_progress(1, "در حال گوش‌دادن به گفتار"))
        words = heard.get("words") or []
        if not words:
            raise captions.CaptionsUnavailable("حرفی در این بخش شنیده نشد.")
        k = 1.0 / max(0.25, float(speed or 1.0))
        scaled = [{"w": w["w"], "s": w["s"] * k, "e": w["e"] * k} for w in words]
        groups = captions.group_words(scaled)
        clips = captions.caption_clips(groups, offset=float(at))
        job.mark_progress(2, "")
        result = {"clips": clips, "text": heard.get("text", ""), "engine": heard.get("engine", ""), "count": len(clips)}
        job.mark_progress(3, "")
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.info("Captions job %s: %s", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}
    finally:
        if wav is not None:
            wav.unlink(missing_ok=True)


# ------------------------------------------------------------ motion tracking, matting, multicam sync (pro 2)

TRACK_PROXY_SIDE = 480
MATTE_PROXY_SIDE = 720
MAX_MATTE_SECONDS = 20.0


def _segment_file(path, s0: float, s1: float, side: int) -> tuple[Path, int, int]:
    """A small, video-only copy of source seconds s0..s1 (the tracker and the matting model both work on small frames, and the
    node should not have to download the original) → (file, width, height)."""
    import subprocess
    import tempfile

    from services.editing.compose import _source_size
    from services.video.ffmpeg import FFMPEG

    sw, sh = _source_size(str(path))
    k = min(1.0, side / max(sw, sh))
    w, h = max(16, int(round(sw * k / 2)) * 2), max(16, int(round(sh * k / 2)) * 2)
    folder = Path(tempfile.mkdtemp(prefix="nm-seg-"))
    out = folder / "clip.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", str(path), "-an", "-vf", f"scale={w}:{h}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", str(out)],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
    return out, w, h


def _node_with(flag: str):
    """An online node whose `capabilities.edit[flag]` is true, or None."""
    try:
        from apps.compute import services as compute

        for node in compute.online_nodes("ffmpeg"):
            if ((node.capabilities or {}).get("edit") or {}).get(flag):
                return node
    except Exception:  # noqa: BLE001
        return None
    return None


def _wait_node(job: Job, cjob, lo: int, hi: int, label: str, timeout_s: int):
    """Wait for a compute job, mirroring its progress into `job` and passing a cancel on."""
    from apps.compute import services as compute

    def tick(j):
        if _cancelled(job.id):
            compute.cancel(j)
        job.mark_progress(int(lo + (hi - lo) * max(0.0, min(1.0, j.progress))), f"{label} — {int(j.progress * 100)}٪")

    return compute.wait(cjob, timeout_s, on_tick=tick, poll=1.5)


@shared_task(bind=True)
def track_task(self, job_id, ref, s0, s1, region, fps=15.0):
    """Follow a point/region of a clip through source seconds s0..s1: on the processing node when it can (OpenCV there),
    else here. The path (source seconds, centre as fractions of the frame, scale, rotation) is the job's result."""
    import shutil

    from apps.compute import services as compute
    from services.editing import tracking
    from services.video.ffmpeg import FFMPEG

    from . import editor_project

    job = Job.objects.get(id=job_id)
    folder = None
    try:
        job.total_steps = 100
        job.mark_running("در حال آماده‌کردنِ ویدیو برای ردیابی")
        item = editor_project.describe(job.store, ref)
        if item["kind"] != "video":
            raise tracking.TrackError("ردیابی فقط روی ویدیو ممکن است.")
        s0 = max(0.0, float(s0))
        s1 = min(float(s1), s0 + tracking.MAX_SECONDS)
        if s1 <= s0 + 0.2:
            raise tracking.TrackError("بازهٔ ردیابی خیلی کوتاه است.")
        seg, w, h = _segment_file(item["path"], s0, s1, TRACK_PROXY_SIDE)
        folder = seg.parent
        job.mark_progress(8, "")
        result, engine = None, "server"
        node = _node_with("track")
        if node is not None:
            try:
                cjob = compute.enqueue("edit.track", {"video": "clip.mp4", "region": region, "fps": float(fps), "size": [w, h], "duration": s1 - s0},
                                       {"clip.mp4": seg}, store=job.store, origin="video-editor-track", timeout_s=300, node=node.name, dedupe=False)
                cjob = _wait_node(job, cjob, 10, 95, "ردیابی روی سرورِ پردازش", 300)
                result = json.loads(Path(compute.output_path(cjob, "track.json")).read_text(encoding="utf-8"))
                engine = f"node:{node.name}"
            except compute.ComputeCancelled:
                raise _Cancelled() from None
            except (compute.ComputeError, OSError, ValueError) as exc:
                logger.info("node tracking not used for job %s: %s", job_id, exc)
                job.mark_progress(10, "ردیابی روی سرورِ سایت")
        if result is None:
            result = tracking.track(seg, 0.0, s1 - s0, region, src_size=(w, h), fps=float(fps), ffmpeg=FFMPEG,
                                    progress=lambda f: job.mark_progress(int(10 + 85 * f), f"ردیابی — {int(f * 100)}٪"), cancel=lambda: _cancelled(job.id))
        for sample in result["samples"]:
            sample["s"] = round(sample["s"] + s0, 3)
        if result.get("lost_at") is not None:
            result["lost_at"] = round(result["lost_at"] + s0, 3)
        result.update({"engine": engine, "ref": ref, "s0": s0, "s1": s1})
        job.mark_progress(100, "")
        job.mark_completed(result)
        return result
    except (_Cancelled, tracking.TrackCancelled):
        job.mark_cancelled()
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001
        logger.info("Track job %s: %s", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}
    finally:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)


MATTE_NEEDS = (
    "حذفِ پس‌زمینهٔ ویدیو روی کامپیوترِ گرافیکی (سرورِ پردازش) انجام می‌شود و به این‌ها نیاز دارد: ۱) سرورِ پردازش روشن باشد (و با Update.bat به نسخهٔ ۲٫۵ رسیده باشد)؛ "
    "۲) یکی از این دو: مدلِ ویدیوییِ Robust Video Matting (RVM، حدود ۱۴ مگابایت، مجوز GPL-3.0 برای استفادهٔ داخلی؛ خودکار از همین سایت گرفته می‌شود و به numpy و onnxruntime "
    "در پایتونِ آن کامپیوتر نیاز دارد) که سریع است و لبه‌ها نمی‌پرند؛ یا بستهٔ مدلِ «photo-background» (BiRefNet-lite، حدود ۲۲۴ مگابایت، مجوز MIT) با Download-Models.bat "
    "یا از پنلِ «سرورهای پردازش» و سرویسِ عکس (PersianAiKit Photo) که بتواند روشن شود — که فریم‌به‌فریم و کندتر است."
)
#: with Robust Video Matting the node cuts every frame in one pass, so the matte can follow the source's frame rate and a longer stretch
RVM_FPS = 24.0
MAX_MATTE_SECONDS_RVM = 60.0


def matte_engine(node) -> str:
    """"rvm" (the video model, fast and steady) | "birefnet" (frame by frame through the photo kit) | "rvm-pending" (the runtime is
    there, the model is fetched by the first job) — what the node's heartbeat says."""
    return str((((node.capabilities or {}).get("edit") or {}).get("matte_engine")) or "birefnet")


def matte_status() -> dict:
    node = _node_with("matte")
    if node is not None:
        engine = matte_engine(node)
        return {"ok": True, "node": node.name, "message": "", "engine": engine,
                "max_seconds": MAX_MATTE_SECONDS_RVM if engine == "rvm" else MAX_MATTE_SECONDS}
    try:
        from apps.compute import services as compute

        online = compute.online_nodes("ffmpeg")
    except Exception:  # noqa: BLE001
        online = []
    if not online:
        return {"ok": False, "node": "", "message": "هیچ سرورِ پردازشی روشن نیست (START.bat را روی کامپیوترِ گرافیکی اجرا کنید). " + MATTE_NEEDS}
    return {"ok": False, "node": online[0].name, "message": "سرورِ پردازشِ روشن مدلِ حذفِ پس‌زمینه را آماده ندارد. " + MATTE_NEEDS}


@shared_task(bind=True)
def matte_task(self, job_id, ref, s0, s1, fps=6.0):
    """Background removal of source seconds s0..s1 of a clip: the node cuts a mask per frame (BiRefNet through the photo kit),
    the result is a grey video kept for the shop (`mattes.py`); a clip then points at it (`clip.matte`)."""
    import shutil

    from apps.compute import services as compute
    from services.editing import mattes

    from . import editor_project

    job = Job.objects.get(id=job_id)
    folder = None
    try:
        job.total_steps = 100
        job.mark_running("در حال آماده‌کردنِ ویدیو برای حذفِ پس‌زمینه")
        state = matte_status()
        if not state["ok"]:
            raise RuntimeError(state["message"])
        node = _node_with("matte")
        item = editor_project.describe(job.store, ref)
        if item["kind"] != "video":
            raise RuntimeError("حذفِ پس‌زمینه فقط روی ویدیو ممکن است.")
        fast = matte_engine(node) == "rvm"
        s0 = max(0.0, float(s0))
        s1 = min(float(s1), s0 + (MAX_MATTE_SECONDS_RVM if fast else MAX_MATTE_SECONDS))
        if s1 <= s0 + 0.3:
            raise RuntimeError("بازهٔ حذفِ پس‌زمینه خیلی کوتاه است.")
        fps = RVM_FPS if fast else max(2.0, min(12.0, float(fps)))
        seg, w, h = _segment_file(item["path"], s0, s1, MATTE_PROXY_SIDE)
        folder = seg.parent
        frames = int((s1 - s0) * fps) + 1
        budget = int(300 + frames * (3 if fast else 40))
        job.mark_progress(6, "")
        cjob = compute.enqueue("edit.matte", {"video": "clip.mp4", "fps": fps, "duration": s1 - s0, "size": [w, h]}, {"clip.mp4": seg}, store=job.store,
                               origin="video-editor-matte", timeout_s=budget, node=node.name, dedupe=False)
        cjob = _wait_node(job, cjob, 8, 94, "حذفِ پس‌زمینه روی سرورِ پردازش", budget)
        out = compute.output_path(cjob, "matte.mp4")
        if not out.is_file() or out.stat().st_size <= 0:
            raise RuntimeError("سرورِ پردازش ماتی نفرستاد.")
        meta = (cjob.result or {}).get("meta") or {}                 # which model the node really used (it may have fallen back)
        model = str(meta.get("model") or ("rvm-mobilenetv3" if fast else "birefnet-lite"))
        fps = float(meta.get("fps") or fps)
        row = mattes.store_file(job.store.pk, out, {"ref": ref, "s0": s0, "s1": s1, "fps": fps, "node": node.name, "engine": model})
        job.mark_progress(100, "")
        result = {**row, "engine": row["engine"], "frames": int(meta.get("frames") or frames)}
        job.mark_completed(result)
        shutil.rmtree(compute.job_root(cjob), ignore_errors=True)
        return result
    except (_Cancelled, compute.ComputeCancelled):
        job.mark_cancelled()
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001
        logger.info("Matte job %s: %s", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}
    finally:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)


@shared_task(bind=True)
def sync_task(self, job_id, refs):
    """Offsets (seconds) of several recordings of the same event relative to the first, from their sound (multicam)."""
    from services.editing import multicam

    from . import editor_project

    job = Job.objects.get(id=job_id)
    try:
        job.total_steps = 100
        job.mark_running("در حال هم‌زمان‌سازی با صدا")
        paths = []
        for ref in refs:
            item = editor_project.describe(job.store, ref)
            if item["kind"] == "image" or not item["has_audio"]:
                raise multicam.TimelineError(f"«{item['title']}» صدا ندارد؛ هم‌زمان‌سازی با صدا ممکن نیست.")
            paths.append(item["path"])
        rows = multicam.sync(paths, progress=lambda f: job.mark_progress(int(5 + 90 * f), "در حال هم‌زمان‌سازی با صدا"))
        result = {"offsets": [{"ref": r, **row} for r, row in zip(refs, rows)]}
        job.mark_progress(100, "")
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.info("Sync job %s: %s", job_id, exc)
        job.mark_failed(exc)
        return {"error": str(exc)}
