"""کارِ Celery ِ «تلفظ»: هر ۵ دقیقه (beat) سنجش‌های در جریان را یک گام جلو می‌برد و آزمونِ خودکارِ گره را نگه می‌دارد."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.pronunciation.tasks.step", ignore_result=True, soft_time_limit=120)
def step() -> dict:
    out: dict = {}
    try:
        from . import evalrun

        out["eval"] = evalrun.advance()
    except Exception as exc:  # noqa: BLE001 — کارِ پس‌زمینه هرگز چیزِ دیگری را خراب نکند
        logger.warning("pronunciation: advance failed: %s", exc)
        out["eval"] = {"error": str(exc)[:200]}
    return out
