"""Celery tasks of the finder: run a crawl, and the once-in-a-while ``tick`` that keeps everything moving by itself.

``tick`` (Celery beat, every 5 minutes) does five small things, so that nothing depends on a person clicking:
  1. starts the missions whose schedule says it is time (weekly, daily ...),
  2. wakes the runs that went to sleep because a public service was busy,
  3. restarts a run whose worker died (running, but nothing moved for a while),
  4. hands waiting work to the processing node as soon as a node that can do it has reported in, and takes the node's answers back
     (this is how «the node was off» becomes «the node came on and the leads got their Instagram data» with nobody doing anything),
  5. once a day, trims the page cache.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)


@shared_task(name="apps.growth_engine.crawler.tasks.run_crawl_task", ignore_result=True)
def run_crawl_task(run_id: int) -> str:
    """Run (or resume) one crawl. Safe to enqueue twice: a finished run is left alone and a run another worker has is skipped."""
    from .engine import runner

    return runner.run_crawl(run_id)


def enqueue_run(run_id: int) -> None:
    """Queue a run once the surrounding transaction has committed (so the worker can see the row)."""
    from apps.growth_engine.core.dispatch import dispatch

    from .models import CrawlRun

    transaction.on_commit(lambda: dispatch(run_crawl_task, CrawlRun, run_id))


@shared_task(name="apps.growth_engine.crawler.tasks.tick", ignore_result=True)
def tick() -> dict:
    from django.conf import settings

    from .engine import fetch, runner
    from .models import CrawlRun, CrawlTask
    from .services import missions

    out = {"scheduled": [], "woken": [], "restarted": [], "node": 0}
    try:
        out["scheduled"] = missions.tick_schedule()
    except Exception:  # noqa: BLE001
        logger.exception("crawler tick: schedule failed")
    now = timezone.now()
    for run in CrawlRun.objects.filter(status=CrawlRun.Status.QUEUED, paused=False, cancel_requested=False).exclude(usage__parked_until__isnull=True)[:20]:
        until = parse_datetime(str((run.usage or {}).get("parked_until") or ""))
        if until is not None and until <= now:
            CrawlRun.objects.filter(pk=run.pk).update(usage={**(run.usage or {}), "parked_until": ""})
            enqueue_run(run.pk)
            out["woken"].append(run.pk)
    stale = now - timedelta(seconds=int(getattr(settings, "GROWTH_CRAWL_STALL_S", 300)))
    for run in CrawlRun.objects.filter(status=CrawlRun.Status.RUNNING, heartbeat_at__lt=stale)[:10]:
        enqueue_run(run.pk)
        out["restarted"].append(run.pk)
    for run in CrawlRun.objects.filter(tasks_waiting__gt=0).order_by("-id")[:15]:
        res = runner.sync_node(run)
        out["node"] += res["ingested"] + res["queued"]
    # a run that has no counter yet but has waiting tasks (an interrupted run) is found through its tasks
    for run_id in CrawlTask.objects.filter(status=CrawlTask.Status.WAITING_NODE).values_list("run_id", flat=True).distinct()[:15]:
        run = CrawlRun.objects.filter(pk=run_id, tasks_waiting=0).first()
        if run is not None:
            out["node"] += runner.sync_node(run)["ingested"]
    if now.hour == 3 and now.minute < 5:
        fetch.purge_cache()
    return out
