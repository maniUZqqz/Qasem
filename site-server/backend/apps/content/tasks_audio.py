"""Background sound for a finished social video: the shop's music and an ambience bed, ducked under the voice.

The voiced cut is never touched: the result goes to `final_video_music`, like the music-only mix
(`tasks_editing.add_music_task`), so «صداگذاری دوباره» and this mix can be run in any order.
"""
import contextlib
import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings

from apps.jobs.models import Job
from services.media import files as media

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def mix_sound_task(self, job_id, script_id, duck=True):
    from apps.content.models import VideoScript
    from services.audio import music as music_engine

    job = Job.objects.get(id=job_id)
    try:
        script = VideoScript.objects.select_related("store").get(id=script_id)
        source = script.final_video_real or script.final_video_voiced or script.final_video
        if not source:
            raise RuntimeError("اول باید ویدیو ساخته شده باشد.")
        bed = (script.finishing or {}).get("ambience_bed") or {}
        job.total_steps = 1
        job.mark_running("در حالِ گذاشتنِ موسیقی و صدای محیط زیرِ صدا")
        out = Path(settings.MEDIA_ROOT) / "generated" / "videos" / f"script_{script.pk}" / "final_music.mp4"
        with contextlib.ExitStack() as stack:
            video_path = stack.enter_context(media.reading(source))
            layers = []
            if script.music:
                layers.append((music_engine.Track(path=stack.enter_context(media.reading(script.music)),
                                                  level_db=script.music_level_db), "music"))
            if bed.get("file"):
                path = Path(settings.MEDIA_ROOT) / bed["file"]
                layers.append((music_engine.Track(path=path, level_db=float(bed.get("level_db", music_engine.AMBIENCE_DB))),
                               "ambience"))
            music_engine.under_narration_layers(video_path, layers, out, duck=duck)
        media.store(script.final_video_music, out)
        script.save(update_fields=["final_video_music", "updated_at"])
        job.mark_progress(1, "")
        result = {"script_id": script.pk, "video": script.final_video_music.url, "music": bool(script.music),
                  "ambience": bool(bed.get("file")), "ducked": duck}
        job.mark_completed(result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sound mix job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


#: the one failure that is known to be the node's old bug, not the shop's input: MOSS on a half-precision GPU
#: («expected mat1 and mat2 to have the same dtype … BFloat16»). The node code that fixed it reaches the PC with the
#: next update; the takes that failed before it stay «ناموفق» until someone presses «دوباره بساز». This remakes them
#: by itself, once each, as soon as a node that can run MOSS is online.
STALE_ERRORS = ("BFloat16",)
STALE_DAYS = 45


def sync_waiting_audio(limit: int = 50) -> int:
    """Rows that wait for a node job are brought up to date here, not only when somebody opens the library.

    `studio.sync` is what every read of the library does; without a reader a take whose job the node had already
    finished stayed «در صف» for ever (the shop's takes 31-35 were in exactly that state). Returns how many rows
    changed state. One bad row never stops the others."""
    from apps.ai.models import AudioAsset
    from services.audio import studio

    rows = (AudioAsset.objects
            .filter(status__in=[AudioAsset.Status.PENDING, AudioAsset.Status.RUNNING], job_uid__isnull=False)
            .order_by("updated_at")[:limit])
    changed = 0
    for asset in rows:
        before = asset.status
        try:
            studio.sync(asset)
        except Exception:  # noqa: BLE001 - a periodic task must not die on one row
            logger.exception("audio %s: sync failed", asset.pk)
            continue
        if asset.status != before:
            changed += 1
    if changed:
        logger.info("audio: %d waiting takes were brought up to date", changed)
    return changed


@shared_task
def retry_stale_failed_audio(limit: int = 5) -> int:
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from apps.ai.models import AudioAsset
    from services.audio import node_audio, studio

    sync_waiting_audio()          # first: whatever the node has finished since the last round
    try:
        if not node_audio.status()["engines"]["moss"]["ready"]:
            return 0
    except Exception:  # noqa: BLE001 - a status read must never fail a periodic task
        return 0
    stale = Q()
    for needle in STALE_ERRORS:
        stale |= Q(error__contains=needle)
    rows = (AudioAsset.objects
            .filter(stale, status=AudioAsset.Status.FAILED, kind=AudioAsset.Kind.SPEECH, engine="moss-fa",
                    created_at__gt=timezone.now() - timedelta(days=STALE_DAYS))
            .select_related("store").order_by("created_at"))
    done = 0
    for asset in rows:
        if done >= limit:
            break
        if (asset.params or {}).get("auto_retried"):
            continue       # once: a take that fails the same way again is not an old bug any more
        try:
            studio.retry(asset, asset.created_by)
        except (studio.StudioError, node_audio.NodeAudioError) as exc:
            logger.info("audio %s: auto-retry skipped (%s)", asset.pk, exc)
            continue
        asset.params = {**(asset.params or {}), "auto_retried": True}
        asset.save(update_fields=["params", "updated_at"])
        done += 1
    if done:
        logger.info("audio: %d takes that failed on the old MOSS bug were queued again", done)
    return done
