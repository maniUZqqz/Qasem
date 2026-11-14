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

#: Where a post may be sent from. Same list the interactive «انتشار حالا» accepts
#: (views.SUPPORTED_PLATFORMS is this very set) — a fake platform name used to be
#: queued and then fail at the minute it was due.
SUPPORTED_PLATFORMS = frozenset({"instagram", "telegram", "linkedin"})

#: A claimed post that has not finished after this long was lost with its worker
#: (restart, OOM kill). Nothing else ever moves RUNNING on, so the beat does.
RUNNING_LIMIT = timedelta(minutes=15)


class ScheduleError(ValueError):
    """A schedule request that must be refused, with a machine-readable `code`.

    A `ValueError` subclass on purpose: callers (and older tests) that catch the
    "time in the past" `ValueError` keep working.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def publishable(campaign) -> bool:
    """Whether the owner's approval still stands for this campaign.

    APPROVED is the rule. PUBLISHED counts too, exactly as in the interactive
    publish: the first scheduled platform that goes out flips the campaign to
    PUBLISHED, and the other platforms queued for the same morning must not
    fail because of that.
    """
    from .models import Campaign

    return campaign.approval_state in (
        Campaign.ApprovalState.APPROVED, Campaign.ApprovalState.PUBLISHED,
    )


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
    stuck = fail_stuck(now)

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

    return {
        "published": published, "missed": missed, "already_taken": skipped,
        "stuck": stuck,
    }


def fail_stuck(now=None) -> int:
    """Fail scheduled posts that were claimed and then never finished.

    `claim()` sets RUNNING and only the task that was dispatched moves it on. If
    that worker died, the row stays RUNNING for ever: the queue page shows
    «در حال انتشار» for a post nobody is publishing, and the shop never learns
    it did not go out. Whatever is still running after `RUNNING_LIMIT` is
    marked failed with the reason, and the shop is told.
    """
    from .models import PublishJob

    now = now or timezone.now()
    rows = list(
        PublishJob.objects
        .filter(
            status=PublishJob.Status.RUNNING,
            scheduled_for__isnull=False,
            updated_at__lt=now - RUNNING_LIMIT,
        )
        .select_related("campaign", "store")[:BATCH]
    )
    failed = 0
    for job in rows:
        reason = (
            "انتشار شروع شد ولی بعد از "
            f"{int(RUNNING_LIMIT.total_seconds() // 60)} دقیقه تمام نشد "
            "(احتمالاً سرویس در همان لحظه خاموش شد). "
            "مطمئن نیستیم پست رفته یا نه؛ صفحهٔ شبکه را ببینید و در صورت نیاز دوباره زمان‌بندی کنید."
        )
        # conditional update: the worker may have finished in the meantime
        changed = PublishJob.objects.filter(
            pk=job.pk, status=PublishJob.Status.RUNNING,
        ).update(
            status=PublishJob.Status.FAILED, last_error=reason, updated_at=timezone.now(),
        )
        if not changed:
            continue
        failed += 1
        logger.warning("Scheduled publish %s was stuck RUNNING; marked failed", job.pk)
        notify_failure(job, reason)
    return failed


def notify_failure(job, reason: str) -> None:
    """Tell the shop a scheduled post did not go out. Never raises."""
    try:
        from apps.customers.models import Notification, notify

        notify(
            job.campaign.store,
            Notification.Type.AI_ERROR,
            "انتشار زمان‌بندی‌شده ناموفق بود",
            body=f"کمپین «{job.campaign.name}» روی {job.platform}: {reason}"[:500],
            link=f"/stores/{job.campaign.store_id}/campaigns",
        )
    except Exception:  # noqa: BLE001 — a failed notification must not hide the failure itself
        logger.exception("Could not notify about failed scheduled publish %s", job.pk)


def cancel_pending(campaign) -> int:
    """Drop the campaign's queued posts that have not started. Returns how many.

    Called when the campaign is rejected or its content changes: the owner's
    approval was for the old state, so a post that would go out at 9 a.m. with
    content nobody approved must not stay queued. A post already RUNNING is in
    flight and is left alone (the fire-time check in `publish_scheduled_job`
    catches a rejected campaign before it delivers).
    """
    from .models import PublishJob

    deleted, _ = PublishJob.objects.filter(
        campaign=campaign,
        status=PublishJob.Status.PENDING,
        scheduled_for__isnull=False,
    ).delete()
    return deleted


def schedule_get_or_create(campaign, platform: str, when, payload: dict | None = None):
    """Queue a publish for a moment in the future. Returns `(job, created)`.

    Refuses what must never reach the queue:
    - a campaign the owner has not approved (or has since rejected): scheduling
      it would hand the decision to the clock;
    - a platform nobody can publish to («myspace», or text where a list was meant);
    - a time in the past: someone who typed yesterday's date meant a different
      date, and honouring it literally posts to their followers right now.

    The same campaign + platform + moment is one row: pressing the button twice
    (or a retried request) must not post the same thing twice.
    """
    from .models import PublishJob

    if not publishable(campaign):
        raise ScheduleError(
            "not_approved",
            "قبل از زمان‌بندی، کمپین باید تأیید شود (کمپینِ پیش‌نویس یا ردشده زمان‌بندی نمی‌شود).",
        )
    platform = str(platform or "").strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ScheduleError(
            "bad_platform",
            f"پلتفرم «{platform}» پشتیبانی نمی‌شود؛ یکی از "
            f"{', '.join(sorted(SUPPORTED_PLATFORMS))} را انتخاب کنید.",
        )
    if when <= timezone.now():
        raise ScheduleError("past_time", "زمان انتشار باید در آینده باشد.")

    # whole seconds: the same request repeated a moment later carries the same
    # minute but not the same microsecond
    when = when.replace(microsecond=0)
    with transaction.atomic():
        return PublishJob.objects.get_or_create(
            campaign=campaign,
            platform=platform,
            scheduled_for=when,
            defaults={"store": campaign.store, "payload": payload or {}},
        )


def schedule(campaign, platform: str, when, payload: dict | None = None):
    """`schedule_get_or_create` for callers that only want the row."""
    job, _created = schedule_get_or_create(campaign, platform, when, payload)
    return job
