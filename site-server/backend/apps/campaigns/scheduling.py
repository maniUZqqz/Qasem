"""Publishing at a time nobody has to be awake for. Phase 24.

The DoD is blunt about what counts: "یک پست زمان‌بندی‌شده در ساعت مقرر **بدون
دخالت انسان** منتشر شود." Everything here follows from that sentence.

**Why a due-scan and not a per-post timer.** Celery can schedule a task for a
future moment, and it is the wrong tool: a worker restart loses every pending
eta, and this product restarts workers routinely because they share one GPU.
A beat that asks "what is due?" every minute survives anything that can be
restarted, and the answer comes from rows that outlive any process.

**Why a post can be late but never early.** Publishing before the scheduled
time is a bug the shop cannot undo — the post is out. Publishing a few minutes
late is invisible. So the scan takes everything whose time has passed, and a
missed window simply publishes on the next tick.

**Why there is a grace limit.** A post scheduled for Friday's sale that goes
out on Monday is worse than one that never goes out: the shop discovers it
after customers did. Anything overdue by more than `LATE_LIMIT` is marked
missed, with the reason, rather than published into a changed world.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: How late is too late to publish. Six hours covers a worker outage or a
#: night the queue was down, and stops a Friday post landing on Monday.
LATE_LIMIT = timedelta(hours=6)

#: How many due posts one scan takes. Keeps a backlog from monopolising the
#: worker, and the next tick is a minute away.
BATCH = 20


def due(now=None):
    """Scheduled publishes whose time has come and which nobody has taken."""
    from .models import PublishJob

    now = now or timezone.now()
    return (
        PublishJob.objects
        .filter(
            status=PublishJob.Status.PENDING,
            scheduled_for__isnull=False,
            scheduled_for__lte=now,
        )
        .select_related("campaign", "store")
        .order_by("scheduled_for")[:BATCH]
    )


def too_late(job, now=None) -> bool:
    now = now or timezone.now()
    return bool(job.scheduled_for and (now - job.scheduled_for) > LATE_LIMIT)


@transaction.atomic
def claim(job) -> bool:
    """Take this job, or report that someone else already did.

    Two workers scanning the same minute is normal, and both publishing the
    same post is a duplicate the shop's followers see. The claim is a
    conditional update: exactly one of them changes a row.
    """
    from .models import PublishJob

    updated = PublishJob.objects.filter(
        pk=job.pk, status=PublishJob.Status.PENDING,
    ).update(status=PublishJob.Status.RUNNING, updated_at=timezone.now())
    return updated == 1


def run_due(now=None) -> dict:
    """Publish everything that is due. Called by the beat, and by hand.

    Returns a summary rather than raising: one broken post must not stop the
    other nineteen, and the scan runs again in a minute either way.
    """
    from .models import PublishJob
    from .tasks import publish_scheduled_job

    now = now or timezone.now()
    published = 0
    missed = 0
    skipped = 0

    for job in list(due(now)):
        if too_late(job, now):
            job.status = PublishJob.Status.FAILED
            job.last_error = (
                f"زمان انتشار {LATE_LIMIT.total_seconds() // 3600:.0f} ساعت گذشته بود "
                "و منتشر نشد — پست دیرهنگام از پست منتشرنشده بدتر است. "
                "اگر هنوز می‌خواهیدش، دوباره زمان‌بندی کنید."
            )
            job.save(update_fields=["status", "last_error", "updated_at"])
            missed += 1
            logger.info("Scheduled publish %s missed its window", job.pk)
            continue

        if not claim(job):
            skipped += 1
            continue

        try:
            publish_scheduled_job.delay(job.pk)
            published += 1
        except Exception as exc:  # noqa: BLE001 — broker down; try again next tick
            PublishJob.objects.filter(pk=job.pk).update(
                status=PublishJob.Status.PENDING, updated_at=timezone.now(),
            )
            logger.warning("Could not dispatch scheduled publish %s: %s", job.pk, exc)

    return {"published": published, "missed": missed, "already_taken": skipped}


def schedule(campaign, platform: str, when, payload: dict | None = None):
    """Queue a publish for a moment in the future.

    Refuses a time in the past rather than publishing immediately: someone who
    typed yesterday's date meant a different date, and honouring it literally
    posts to their followers right now.
    """
    from .models import PublishJob

    if when <= timezone.now():
        raise ValueError("زمان انتشار باید در آینده باشد.")

    return PublishJob.objects.create(
        store=campaign.store,
        campaign=campaign,
        platform=platform,
        scheduled_for=when,
        payload=payload or {},
    )
