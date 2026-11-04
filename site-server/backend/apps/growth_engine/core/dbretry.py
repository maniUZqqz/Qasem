"""Retrying a short database transaction that SQLite refused with «database is locked».

With SQLite in WAL mode, ``busy_timeout`` absorbs ordinary lock waits, but NOT a *snapshot conflict*: a transaction
that started by reading and then tries to write fails at once when another connection committed in between. Django
opens its transactions deferred, so two workers writing at nearly the same moment can trigger it (seen live: the web
process updating a job row while the Celery worker began its first row). Each background-job step here is a short,
self-contained transaction, so the right answer is to run it again.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from django.db.utils import OperationalError

logger = logging.getLogger(__name__)
T = TypeVar("T")


def is_locked_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database table is locked" in text or "database is busy" in text


def retry_locked(fn: Callable[[], T], *, attempts: int = 6, base: float = 0.15, sleep: Callable[[float], None] = time.sleep) -> T:
    """Call ``fn`` (one whole transaction, safe to repeat) and repeat it while SQLite reports a lock conflict."""
    for attempt in range(attempts):
        try:
            return fn()
        except OperationalError as exc:
            if not is_locked_error(exc) or attempt == attempts - 1:
                raise
            logger.info("growth: database locked, retrying (%s/%s)", attempt + 1, attempts - 1)
            sleep(base * (2**attempt) * (0.5 + random.random()))
    raise AssertionError("unreachable")  # pragma: no cover
