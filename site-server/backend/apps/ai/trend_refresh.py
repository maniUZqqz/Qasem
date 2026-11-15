"""Keeping the market-trends tab filled without anybody pressing a button.

Before this module the tab was fed only by the button «به‌روزرسانی از منبع». The
sources say «روزانه», the page hides anything older than 36 hours, and nobody
pressed the button for days — so the tab showed «ترند تازه‌ای نداریم» most of the
time (newest row: 1 Nov; the page said so on 14 Nov).

Three triggers share one code path (:func:`run`):

* **beat** — a daily job (``market-trends-refresh`` in settings): every country
  plus the indirect Instagram source, so the tab is full before the first visit.
* **page** — opening the tab with data older than :data:`STALE_AFTER` queues ONE
  background refresh (not more often than :data:`RETRY_AFTER`, and never while one
  is already running). The page shows «در حال به‌روزرسانی…» and fills itself.
* **manual** — the existing button; synchronous, as before.

State lives in one DB row (:class:`~apps.ai.trend_models.TrendRefreshState`), so the
web process, the Celery worker and the tests all see the same truth, and the
"is one already running?" question is answered by an atomic UPDATE rather than a
lock file.

Nothing here needs an AI model. When a source does not answer, the problem is
stored with the run and shown on the page («منبع … جواب نداد»); an exception never
escapes a background run.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Max, Q
from django.utils import timezone

from services.research import trends as source

from .trend_models import Trend, TrendRefreshState

logger = logging.getLogger(__name__)

#: Every country the page offers, plus the indirect Instagram source. Seven small
#: RSS requests and a few news searches a day — nothing worth saving by guessing
#: which shop will look at which country.
DEFAULT_REGIONS = list(source.REGIONS) + [source.INSTAGRAM]

#: The page asks for a refresh when the newest successful one is older than this.
STALE_AFTER = timedelta(hours=12)

#: After an attempt (any trigger) the page does not start another for this long,
#: so a dead source is retried twice an hour, not on every page view.
RETRY_AFTER = timedelta(minutes=30)

#: A run that has not finished by now is assumed dead (worker killed mid-way).
RUNNING_TIMEOUT = timedelta(minutes=10)

TRIGGERS = ("beat", "page", "manual")


def state() -> TrendRefreshState:
    row, _ = TrendRefreshState.objects.get_or_create(pk=1)
    return row


def last_refresh_at():
    """When the tab was last really filled: the last successful run, else — for a
    database that predates this module — the newest trend row."""
    row = state()
    if row.last_success_at:
        return row.last_success_at
    return Trend.objects.aggregate(m=Max("created_at"))["m"]


def is_running(row: TrendRefreshState | None = None) -> bool:
    row = row or state()
    return bool(row.running_since and timezone.now() - row.running_since < RUNNING_TIMEOUT)


def needs_refresh(now=None) -> bool:
    last = last_refresh_at()
    now = now or timezone.now()
    return last is None or now - last > STALE_AFTER


def _acquire(trigger: str, *, force: bool = False) -> bool:
    """Atomically mark a run as started. ``False`` = another one is in progress."""
    state()  # make sure the row exists
    now = timezone.now()
    rows = TrendRefreshState.objects.filter(pk=1)
    if not force:
        rows = rows.filter(Q(running_since__isnull=True) | Q(running_since__lt=now - RUNNING_TIMEOUT))
    return bool(rows.update(running_since=now, last_attempt_at=now, last_trigger=trigger))


def _release(*, ok: bool, result: dict) -> None:
    now = timezone.now()
    fields = {"running_since": None, "last_result": result}
    if ok:
        fields["last_success_at"] = now
    TrendRefreshState.objects.filter(pk=1).update(**fields)


def run(regions: list[str] | None = None, *, trigger: str = "beat", force: bool = False) -> dict:
    """Fetch the trends and record what happened.

    Returns the :func:`apps.ai.trends.refresh` payload (``fetched``, ``new``,
    ``problems``, ``sources``), or ``{"skipped": "already_running"}``. For the
    background triggers an unexpected exception is stored and swallowed; the
    ``manual`` trigger re-raises so the button can show the error.
    """
    from . import trends as engine

    if not _acquire(trigger, force=force or trigger == "manual"):
        return {"skipped": "already_running"}
    try:
        result = engine.refresh(regions or DEFAULT_REGIONS)
    except Exception as exc:  # noqa: BLE001 — a broken source must not kill the worker
        logger.warning("Market trends refresh (%s) failed: %s", trigger, exc)
        _release(ok=False, result={"fetched": 0, "new": 0, "problems": [str(exc)[:300]],
                                   "trigger": trigger, "at": timezone.now().isoformat()})
        if trigger == "manual":
            raise
        return {"fetched": 0, "new": 0, "problems": [str(exc)[:300]], "sources": []}
    stored = {
        "fetched": result["fetched"], "new": result["new"],
        "problems": list(result.get("problems") or [])[:12],
        "regions": list(regions or DEFAULT_REGIONS),
        "trigger": trigger, "at": timezone.now().isoformat(),
    }
    _release(ok=result["fetched"] > 0, result=stored)
    return result


def ensure_fresh(*, queue_available: bool | None = None) -> str:
    """Called when the page is opened. Returns what it did, for the page to show:

    ``fresh``      nothing to do;
    ``running``    a refresh is already in progress;
    ``started``    a background refresh was just queued;
    ``recent``     data is old but an attempt was made a moment ago (retry later);
    ``queue_off``  data is old but there is no background queue to run it on
                   (Celery is in in-process mode) — the button still works;
    ``error``      the queue refused the job.
    """
    if not needs_refresh():
        return "fresh"
    if is_running():
        return "running"
    if queue_available is None:
        queue_available = not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
    if not queue_available:
        return "queue_off"
    now = timezone.now()
    won = TrendRefreshState.objects.filter(pk=1).filter(
        Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lt=now - RETRY_AFTER),
    ).update(last_attempt_at=now, last_trigger="page")
    if not won:
        return "recent"
    from .tasks import refresh_market_trends

    try:
        refresh_market_trends.apply_async(kwargs={"trigger": "page"}, expires=900)
    except Exception as exc:  # noqa: BLE001 — broker down: the page must still open
        logger.info("Could not queue the market-trends refresh: %s", exc)
        return "error"
    return "started"


def freshness(auto: str = "") -> dict:
    """What the page shows next to the list: how old it is, whether a refresh is
    under way, and the last run's source problems."""
    row = state()
    last = last_refresh_at()
    now = timezone.now()
    age_hours = None if last is None else round((now - last).total_seconds() / 3600, 1)
    result = row.last_result or {}
    return {
        "last_refresh_at": last.isoformat() if last else None,
        "age_hours": age_hours,
        "stale": last is None or now - last > STALE_AFTER,
        "refreshing": is_running(row),
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "last_trigger": row.last_trigger,
        "problems": list(result.get("problems") or []),
        "auto": auto,
        "schedule": "هر روز، خودکار",
    }
