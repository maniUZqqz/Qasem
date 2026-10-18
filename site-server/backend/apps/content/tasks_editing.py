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
import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings

from apps.jobs.models import Job
from services.editing import agent, analysis, edl, preferences
from services.media import files as media
from services.video import subtitles

from .models import UploadedVideo

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
