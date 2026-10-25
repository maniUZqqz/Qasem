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
