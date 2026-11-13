"""کارِ Celery ِ تامنیل‌ساز: تامنیلِ منتظرِ «پس‌زمینهٔ هوش مصنوعی» را تا رسیدنِ تصویر پیگیری می‌کند (بدونِ باز بودنِ پنل).

مثلِ ادیتورِ عکس: نخِ Celery گرو نمی‌ماند؛ poll خودش را دوباره در صف می‌گذارد — هر چند ثانیه وقتی گره آنلاین است، هر چند ده ثانیه وقتی
نیست؛ بعد از ۲۴ ساعت می‌ایستد ولی کار در صف می‌ماند و هر بار که پنل باز شود دوباره وارسی می‌شود (``services.nudge_waiting``).
"""
from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import services
from .models import Thumbnail

logger = logging.getLogger(__name__)


@shared_task(name="apps.thumbs.tasks.selftest_when_online", ignore_result=True, soft_time_limit=60)
def selftest_when_online() -> dict:
    """هر ۵ دقیقه (beat): آزمونِ پس‌زمینهٔ هوش مصنوعی را بدونِ دخالتِ کسی در صفِ سرورِ پردازش نگه می‌دارد (``selftest.auto_step``)."""
    from . import selftest

    try:
        return selftest.auto_step()
    except Exception as exc:  # noqa: BLE001 — آزمونِ خودکار هرگز چیزِ دیگری را خراب نکند
        logger.warning("thumbs: selftest step failed: %s", exc)
        return {"action": "error", "why": str(exc)[:200]}


@shared_task(ignore_result=True, soft_time_limit=900)
def poll_thumb_task(thumb_id: int, started: str | None = None) -> None:
    t = Thumbnail.objects.filter(pk=thumb_id).select_related("store").first()
    if t is None or t.state != Thumbnail.State.WAITING_BG:
        return
    if services.refresh(t):
        return
    try:
        begun = datetime.fromisoformat(started) if started else t.created_at
    except ValueError:
        begun = t.created_at
    if (timezone.now() - begun).total_seconds() > services.POLL_HOURS * 3600:
        logger.info("thumbs: thumbnail %s still waits for a processing server; polling stops (panel nudges it)", thumb_id)
        return
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return
    services.kick_poll(t, started=started)
