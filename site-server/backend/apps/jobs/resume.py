"""Picking a parked job back up after a person answered.

Kept apart from the approval endpoint on purpose. The endpoint knows that a
human said yes; only the pipeline knows what "carry on" means for this
particular job type, and wiring that knowledge into the view would make every
new job type a change to the HTTP layer.

A job type with no entry here parks and stays parked. That is the honest
behaviour: a state machine that silently completes jobs it does not know how to
resume would report success for work that never ran.
"""
from __future__ import annotations

import logging

from .models import Job

logger = logging.getLogger(__name__)


def _resume_video(job: Job) -> bool:
    """Continue a segment-by-segment video render from where it stopped."""
    script_id = (job.context or {}).get("script_id")
    if not script_id:
        logger.warning("Job %s has no script_id to resume", job.pk)
        return False

    from apps.content.tasks import generate_video_task

    from .services import dispatch_job

    # dispatch_job returns None on success and a DRF error Response when the
    # queue is down (and marks the job FAILED itself), so None means started.
    return dispatch_job(job, generate_video_task, job.id, script_id) is None


#: Job type → how to continue it. Anything absent parks permanently, visibly.
RESUMERS = {
    Job.Type.VIDEO_GENERATION: _resume_video,
    Job.Type.VIDEO_SEGMENT: _resume_video,
}


def can_resume(job: Job) -> bool:
    return job.type in RESUMERS


def resume(job: Job) -> bool:
    """Hand the job back to its pipeline. Returns whether anything was started.

    Never raises: an approval that 500s would leave the owner unable to say yes
    to work that is already finished and waiting.
    """
    handler = RESUMERS.get(job.type)
    if handler is None:
        logger.info(
            "Job %s (%s) approved but has no resumer — it stays APPROVED",
            job.pk, job.type,
        )
        return False
    try:
        return bool(handler(job))
    except Exception as exc:  # noqa: BLE001 — the approval itself must survive
        logger.exception("Could not resume job %s", job.pk)
        job.mark_failed(f"ادامه‌ی کار ممکن نشد: {exc}")
        return False
