"""کارِ Celery ِ «تلفظ»: هر ۵ دقیقه (beat) سنجش‌های در جریان را یک گام جلو می‌برد و آزمونِ خودکارِ گره را نگه می‌دارد."""
from __future__ import annotations

import logging
import time

from celery import shared_task

logger = logging.getLogger(__name__)

_LAST_CLEAN = [0.0]
CLEAN_EVERY_S = 3600


@shared_task(name="apps.pronunciation.tasks.step", ignore_result=True, soft_time_limit=120)
def step() -> dict:
    out: dict = {}
    try:
        from . import evalrun

        out["eval"] = evalrun.advance()
    except Exception as exc:  # noqa: BLE001 — کارِ پس‌زمینه هرگز چیزِ دیگری را خراب نکند
        logger.warning("pronunciation: advance failed: %s", exc)
        out["eval"] = {"error": str(exc)[:200]}
    # test-box recordings and eval-run files do not pile up (at most once an hour)
    if time.monotonic() - _LAST_CLEAN[0] > CLEAN_EVERY_S:
        _LAST_CLEAN[0] = time.monotonic()
        try:
            from . import services

            out["cleanup"] = services.cleanup_media()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pronunciation: cleanup failed: %s", exc)
    return out
