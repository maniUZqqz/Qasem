"""Counters and flags that must be the same in every worker process.

The site runs several gunicorn workers, and Django's default cache (`LocMemCache`)
is **per process**: a rate limit kept there is multiplied by the number of workers
(a «10 new chats per hour» rule really allowed 20) and forgotten at every reload.
The public widget's flood limits and the «can this server reach Telegram?» probe
therefore live here, in the Redis the site already runs for Celery, with the
process-local cache as the fallback when Redis is not there (tests, a dev
machine, a Redis hiccup) - a limit that is a little looser is better than a chat
widget that errors.

Keys are namespaced (`nm:inbox:`), expire on their own, and hold nothing but
numbers and short flags - no customer data ever goes in here.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

PREFIX = "nm:inbox:"
_client = None
_failed_at = 0.0
#: After a Redis error, use the local cache for this long before trying again.
RETRY_AFTER = 30.0


def _redis():
    """A Redis client, or None when this process should use the local cache."""
    global _client, _failed_at
    if getattr(settings, "IS_TEST", False):
        return None  # tests never depend on a Redis being up
    if _client is not None:
        return _client
    if time.time() - _failed_at < RETRY_AFTER:
        return None
    url = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
    if not url.startswith(("redis://", "rediss://")):
        return None
    try:
        import redis

        _client = redis.Redis.from_url(url, socket_connect_timeout=0.4, socket_timeout=0.4)
    except Exception:  # noqa: BLE001 - the limit must never take the widget down
        logger.warning("inbox: no Redis for shared counters, using the local cache", exc_info=True)
        _failed_at = time.time()
        _client = None
    return _client


def _drop() -> None:
    global _client, _failed_at
    _client = None
    _failed_at = time.time()


def hit(bucket: str, window: int = 60) -> int:
    """Count one event in `bucket` for the current `window`-second slot; returns the count so far."""
    key = f"{PREFIX}{bucket}:{int(time.time() // window)}"
    client = _redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window + 30)
            return int(pipe.execute()[0])
        except Exception:  # noqa: BLE001
            logger.warning("inbox: shared counter failed, falling back to the local cache", exc_info=True)
            _drop()
    cache.add(key, 0, window + 30)
    try:
        return int(cache.incr(key))
    except ValueError:
        return 1


def get_flag(name: str) -> str | None:
    key = PREFIX + name
    client = _redis()
    if client is not None:
        try:
            raw = client.get(key)
            return raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except Exception:  # noqa: BLE001
            _drop()
    return cache.get(key)


def set_flag(name: str, value: str, ttl: int) -> None:
    key = PREFIX + name
    client = _redis()
    if client is not None:
        try:
            client.set(key, value, ex=ttl)
            return
        except Exception:  # noqa: BLE001
            _drop()
    cache.set(key, value, ttl)
