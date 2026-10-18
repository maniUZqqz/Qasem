"""Cancelling a job for real, not just hiding its spinner.

The old cancel flipped the row to CANCELLED and stopped the polling. From the
panel that looks identical to this one; from the shop's side it is not. Four
things have to happen, and the old version did the first only:

1. the UI stops waiting,
2. half-written files stop occupying disk,
3. the GPU stops being held by a task nobody is waiting for,
4. **the credit comes back** — a render the owner abandoned after five seconds
   must not be billed as a finished video.

Point 4 is new because `apps.billing.credits` now exists. Before it, cancelling
quietly charged for nothing, which is the kind of thing a customer discovers on
their invoice rather than in a changelog.

Ordering matters: the credit is returned **before** the row goes terminal. If
the process dies between the two, a job stuck in a non-terminal state is
visible and fixable, whereas a CANCELLED job whose credit was never returned
looks finished and is silently wrong.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction

from .models import Job

logger = logging.getLogger(__name__)


def _refund_credit(job: Job, *, actor=None) -> int:
    """Hand back every credit this job charged. Returns how much came back."""
    from apps.billing import credits, services as billing
    from apps.billing.models import Usage

    given_back = 0
    for row in Usage.objects.filter(job=job):
        if row.state == Usage.State.RESERVED:
            # Never charged in the first place — release, do not refund, or the
            # ledger claims we gave back something we never took.
            billing.release(row, reason="کار لغو شد")
        elif row.state == Usage.State.COMMITTED:
            try:
                credits.refund(
                    row, reason="کار پیش از تمام شدن لغو شد",
                    source=credits.CUSTOMER, actor=actor,
                )
            except credits.NotRefundable:
                continue
            given_back += row.quantity
    return given_back


def _partial_files(job: Job) -> list[Path]:
    """Files this job wrote that are of no use now.

    Only the segments that never finished. A cancelled job may have three good
    five-second clips, and deleting those would throw away work the owner can
    still look at and may still want stitched.
    """
    script_id = (job.context or {}).get("script_id")
    if not script_id:
        return []

    from apps.content.models import VideoSegment

    doomed = []
    unfinished = VideoSegment.objects.filter(
        script_id=script_id,
        status__in=[VideoSegment.Status.PENDING, VideoSegment.Status.GENERATING],
    )
    for segment in unfinished:
        for field in (segment.video, segment.last_frame):
            if field:
                path = Path(settings.MEDIA_ROOT) / field.name
                if path.exists():
                    doomed.append(path)
    return doomed


def _release_gpu() -> None:
    """Let go of VRAM a cancelled job may still be holding.

    Best effort by design: the point of cancelling is to free the card for the
    next job, and failing to do so must not turn a cancellation into an error.
    """
    try:
        from services import gpu

        gpu.unload_ollama_models()
    except Exception as exc:  # noqa: BLE001 — cancellation must still succeed
        logger.info("GPU release after cancel did not complete: %s", exc)


def cancel(job: Job, *, actor=None, reason: str = "توسط کاربر لغو شد.") -> dict:
    """Stop the job and undo what can be undone.

    Safe to call twice: an already-terminal job reports what it is and changes
    nothing, because the second call is usually a double-clicked button.
    """
    from . import machine

    if job.state in machine.TERMINAL:
        return {
            "cancelled": False,
            "state": job.state,
            "refunded": 0,
            "files_removed": 0,
            "message": "این کار از قبل تمام شده بود.",
        }

    # 1. Tell a live worker to stop at its next checkpoint. A Celery task
    #    cannot be killed reliably, so it has to be asked.
    job.request_cancel(reason)

    # 2. Credit first, terminal state second — see the module docstring.
    with transaction.atomic():
        refunded = _refund_credit(job, actor=actor)

    # 3. Throw away only the pieces that are of no use.
    removed = 0
    for path in _partial_files(job):
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            logger.info("Could not remove partial file %s: %s", path, exc)

    _release_gpu()

    job.mark_cancelled(reason)

    logger.info(
        "job %s cancelled: %s credits back, %s partial files removed",
        job.pk, refunded, removed,
    )
    return {
        "cancelled": True,
        "state": job.state,
        "refunded": refunded,
        "files_removed": removed,
        "message": (
            f"کار لغو شد و {refunded} اعتبار برگشت." if refunded
            else "کار لغو شد. اعتباری مصرف نشده بود."
        ),
    }
