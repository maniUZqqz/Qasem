"""
Detecting and reaping DEAD jobs.

A Job row is the only thing the frontend polls. If a worker (or the Django
process running the job synchronously) dies mid-task, the row stays
QUEUED/RUNNING forever and every panel that re-attaches to it shows an
infinite spinner and blocks its own button (beter.md v2 #1/#2 — a 33-hour-old
"در حال تحلیل…" that the user never started).

Nothing can rescue such a row, so it is marked FAILED as soon as anyone looks
at it. Two different clocks are used:

* RUNNING — the task reported progress at least once; it is dead only after
  longer than the slowest possible single AI call could take.
* QUEUED  — nobody ever picked it up. A worker takes a job in milliseconds, so
  a long QUEUED age means the queue is not being consumed at all.
"""
import logging
import os

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import Job

logger = logging.getLogger(__name__)

RUNNING_STALE_MESSAGE = (
    "این کار نیمه‌کاره رها شد (سرور یا worker وسط کار بسته شد). "
    "دوباره اجرا کنید."
)
QUEUED_STALE_MESSAGE = (
    "این کار در صف ماند و هیچ workerی آن را برنداشت "
    "(Redis/Celery خاموش بود). دوباره اجرا کنید."
)
RESTART_MESSAGE = (
    "سرور ری‌استارت شد و این کار از بین رفت. دوباره اجرا کنید."
)

#: Still in flight from the panel's point of view — `?active=true` uses this so
#: a refreshed page re-attaches its progress view.
ACTIVE_STATES = [
    Job.State.QUEUED,
    Job.State.RUNNING,
    Job.State.PROCESSING,
    Job.State.PREVIEW,
    Job.State.WAITING_APPROVAL,
    Job.State.APPROVED,
    Job.State.RENDERING,
    Job.State.QC,
]

#: States where the job is waiting for a **person**, not for a worker.
#:
#: These must never be reaped. A job parked for approval will legitimately sit
#: there overnight, and failing it while the owner is asleep would throw away
#: five seconds of finished GPU work and leave them with "این کار نیمه‌کاره رها
#: شد" for something they were about to approve.
HUMAN_STATES = [Job.State.PREVIEW, Job.State.WAITING_APPROVAL]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def running_stale_seconds() -> int:
    """How long a RUNNING job may go without an update before it is dead."""
    conf = settings.UPMARKET_AI
    # worst legitimate case = one AI call that uses the whole timeout on every
    # retry, or one ComfyUI render — plus a margin for slow disk model loads
    slowest_call = conf["OLLAMA_TIMEOUT"] * (conf["OLLAMA_RETRIES"] + 1)
    default = max(slowest_call, conf["COMFYUI_TIMEOUT"]) + 600
    return _int_env("JOB_RUNNING_STALE_SECONDS", default)


# Jobs routed to the `gpu` Celery queue (settings.CELERY_TASK_ROUTES). One
# render can take many minutes, so the next one may legitimately wait a long
# time behind it; everything else is picked up by a free worker in milliseconds.
GPU_QUEUE_TYPES = {
    Job.Type.VIDEO_GENERATION,
    Job.Type.VIDEO_SEGMENT,
    Job.Type.VIDEO_CONCAT,
    Job.Type.IMAGE_GENERATION,
}


def queued_stale_seconds() -> int:
    """How long a job may sit QUEUED before the queue is declared dead.

    Deliberately generous. The `ai` worker runs one job at a time (--pool=solo),
    so a second analysis really does wait behind a ten-minute first one; killing
    it early would break a working setup, which is far worse than a spinner that
    the Cancel button can always end. The genuinely dead cases are caught
    earlier and precisely: dispatch refuses when Redis is down, and synchronous
    mode clears its leftovers at startup.
    """
    return _int_env("JOB_QUEUED_STALE_SECONDS", running_stale_seconds())


def gpu_queued_stale_seconds() -> int:
    """Same, for render jobs that can legitimately wait behind another render."""
    return _int_env("JOB_GPU_QUEUED_STALE_SECONDS", max(2700, running_stale_seconds()))


def stale_filter() -> Q:
    """Q object matching every job row that can no longer make progress."""
    now = timezone.now()
    # The parentheses are explicit on purpose: `&` binds tighter than `|`, so
    # the three clauses below only mean what they should as long as the middle
    # one stays grouped. Dropping them would silently make EVERY queued job
    # subject to the short non-GPU deadline.
    running_too_long = Q(
        state__in=[Job.State.RUNNING, Job.State.PROCESSING, Job.State.RENDERING, Job.State.QC],
        updated_at__lt=now - timedelta(seconds=running_stale_seconds()),
    )
    queued_too_long = Q(
        state=Job.State.QUEUED,
        created_at__lt=now - timedelta(seconds=queued_stale_seconds()),
    ) & ~Q(type__in=GPU_QUEUE_TYPES)
    render_queued_too_long = Q(
        state=Job.State.QUEUED,
        type__in=GPU_QUEUE_TYPES,
        created_at__lt=now - timedelta(seconds=gpu_queued_stale_seconds()),
    )
    # APPROVED is in neither clause on purpose: the owner has answered and a
    # worker is about to pick it up, so it is measured by the running clock
    # once it moves on rather than being failed in the handover.
    return running_too_long | queued_too_long | render_queued_too_long


def reap(queryset=None) -> int:
    """Mark every dead job in `queryset` (default: all jobs) as FAILED.

    Returns the number of rows reaped. Never raises — reaping is housekeeping
    and must not break the request that triggered it.
    """
    qs = Job.objects.all() if queryset is None else queryset
    try:
        dead = list(
            qs.filter(state__in=ACTIVE_STATES)
            .exclude(state__in=HUMAN_STATES)
            .filter(stale_filter())
        )
    except Exception as exc:  # noqa: BLE001 — e.g. table missing during migrate
        logger.debug("Job reaping skipped: %s", exc)
        return 0

    for job in dead:
        message = (
            QUEUED_STALE_MESSAGE if job.state == Job.State.QUEUED else RUNNING_STALE_MESSAGE
        )
        try:
            job.mark_failed(message)
            logger.info("Reaped dead job %s (%s, last update %s)", job.id, job.type, job.updated_at)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not reap job %s: %s", job.id, exc)
    return len(dead)


def reap_on_start() -> int:
    """Fail every non-terminal job left over from a previous process.

    Only correct when jobs run *inside* this process (CELERY_TASK_ALWAYS_EAGER):
    with a real queue the rows belong to Celery workers that outlive Django.

    **Jobs waiting for a person are spared**, and that exclusion is not an
    optimisation — without it, restarting the dev server throws away a finished
    five-second segment and the approval its owner was about to give.

    The earlier reasoning here was that a parked job's worker dies with the
    process, so approving it would resume nothing. That is wrong in exactly
    this mode: a parked job has no worker *by design* — it is waiting for a
    human — and approving it dispatches fresh work. Nothing is orphaned.
    """
    if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return 0
    try:
        orphans = Job.objects.filter(state__in=ACTIVE_STATES).exclude(
            state__in=HUMAN_STATES
        )
        count = orphans.count()
        if count:
            orphans.update(state=Job.State.FAILED, error=RESTART_MESSAGE, updated_at=timezone.now())
            logger.info("Reaped %s orphaned job(s) left over from a previous run", count)
        return count
    except Exception as exc:  # noqa: BLE001 — DB may not exist yet (first migrate)
        logger.debug("Startup job reaping skipped: %s", exc)
        return 0
