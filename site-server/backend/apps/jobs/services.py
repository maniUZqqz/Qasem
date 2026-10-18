"""Queueing helpers: dispatch a Celery task, or fail honestly and immediately.

The worst possible outcome for the UI is a job row that stays QUEUED forever
because nothing is consuming the queue — that is exactly what produced the
"infinite spinner" bug. So every dispatch first checks that somebody is
actually listening, and a failed dispatch always leaves the job in a terminal
state with a message the store owner can act on.
"""
import logging
import socket
import time
from urllib.parse import urlparse

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response

from .serializers import JobSerializer

logger = logging.getLogger(__name__)

# Redis presence is probed at most this often; a probe is a TCP connect.
_BROKER_CACHE_SECONDS = 10
_broker_cache = {"at": 0.0, "up": False}

QUEUE_SETUP_HINT = (
    "برای روشن‌کردن صف: پروژه را با start.bat بالا بیاورید — خودش Redis و "
    "کارگر صف را روشن می‌کند (اگر Redis نصب نباشد، نصبش را پیشنهاد می‌دهد). "
    "نیازی به تغییر دستی backend/.env نیست. برای دیدن اینکه دقیقاً کدام سرویس "
    "بالا نیست: doctor.bat را اجرا کنید."
)

WORKER_SETUP_HINT = (
    "Redis روشن است ولی هیچ کارگری کارها را برنمی‌دارد. پنجره‌های «UpMarket — "
    "Worker» را ببندید و پروژه را با start.bat دوباره بالا بیاورید؛ "
    "doctor.bat هم دقیقاً می‌گوید چه چیزی کم است."
)

#: A worker ping is a broker round-trip, so it is cached like the TCP probe.
_WORKER_CACHE_SECONDS = 15
_worker_cache = {"at": 0.0, "up": False}


def broker_host_port() -> tuple[str, int]:
    parsed = urlparse(settings.CELERY_BROKER_URL or "")
    return (parsed.hostname or "localhost", parsed.port or 6379)


def broker_reachable(force: bool = False) -> bool:
    """True when a TCP connection to the Redis broker succeeds (cached ~10s)."""
    now = time.monotonic()
    if not force and now - _broker_cache["at"] < _BROKER_CACHE_SECONDS:
        return _broker_cache["up"]
    host, port = broker_host_port()
    try:
        with socket.create_connection((host, port), timeout=0.6):
            up = True
    except OSError:
        up = False
    _broker_cache.update({"at": now, "up": up})
    return up


def eager_mode() -> bool:
    """Is work run inside the request instead of on the queue, right now?

    `CELERY_TASK_ALWAYS_EAGER` is decided once, when Django starts. In `auto`
    mode that froze the answer to "was Redis up at boot": a shop that started
    Redis afterwards kept being told the queue was down until the whole
    backend was restarted — which is exactly what happened on the main
    machine. So in auto mode the broker is probed live (cached ~10 s);
    `true`/`false` in .env still force the mode.
    """
    if getattr(settings, "CELERY_MODE_SOURCE", "env") == "auto":
        return not broker_reachable()
    return bool(settings.CELERY_TASK_ALWAYS_EAGER)


def workers_online(force: bool = False) -> bool:
    """True when at least one Celery worker answers a ping (cached ~15 s).

    A live Redis with no worker is the worst failure of the three: the job is
    accepted, the panel spins, and nothing ever happens. Better to refuse.
    """
    now = time.monotonic()
    if not force and now - _worker_cache["at"] < _WORKER_CACHE_SECONDS:
        return _worker_cache["up"]
    up = False
    try:
        from config.celery import app as celery_app

        replies = celery_app.control.ping(timeout=1.0)
        up = bool(replies)
    except Exception as exc:  # noqa: BLE001 — no broker, no kombu, no worker
        logger.debug("Worker ping failed: %s", exc)
    _worker_cache.update({"at": now, "up": up})
    return up


def queue_is_available() -> bool:
    """True when jobs are dispatched to real Celery workers over a live broker."""
    if eager_mode():
        return False
    return broker_reachable() and workers_online()


def queue_unavailable_response(job=None, message: str = ""):
    """Uniform 503 for 'this feature needs the queue and the queue is down'."""
    payload = {
        "error": {
            "code": "queue_unavailable",
            "message": message
            or ("صف پردازش (Redis) در دسترس نیست. " + QUEUE_SETUP_HINT),
        }
    }
    if job is not None:
        payload["job"] = JobSerializer(job).data
    return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)


def dispatch_job(job, task, *args):
    """Queue `task(*args)` for `job`. Returns None on success, or a DRF Response.

    In queue mode the broker is probed first: without that check a dead Redis
    turns into a job that is QUEUED forever and a spinner that never stops.
    """
    if not eager_mode():
        if not broker_reachable():
            job.mark_failed(
                "صف پردازش (Redis) در دسترس نیست، پس این کار اجرا نشد. " + QUEUE_SETUP_HINT
            )
            return queue_unavailable_response(job)
        if not workers_online():
            # Queueing here would leave the job QUEUED for ever behind a
            # spinner that never stops.
            job.mark_failed("کارگر صف روشن نیست، پس این کار اجرا نشد. " + WORKER_SETUP_HINT)
            return queue_unavailable_response(job, message=WORKER_SETUP_HINT)

    try:
        async_result = task.delay(*args)
        job.celery_task_id = str(getattr(async_result, "id", "") or "")
        job.save(update_fields=["celery_task_id", "updated_at"])
        return None
    except Exception as exc:  # broker unavailable → honest failure, no fake success
        logger.warning("Dispatch of %s failed: %s", getattr(task, "name", task), exc)
        job.mark_failed(f"اجرای این کار شروع نشد ({exc}). " + QUEUE_SETUP_HINT)
        return queue_unavailable_response(job)
