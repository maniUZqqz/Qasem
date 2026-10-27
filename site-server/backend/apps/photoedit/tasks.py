"""کارهای Celery ِ ادیتورِ عکس. هیچ‌کدام منتظرِ سرورِ پردازش نمی‌ماند (نخِ Celery گرو نمی‌رود): poll خودش را
دوباره در صف می‌گذارد — هر ۶ ثانیه وقتی گره آنلاین است، هر ۳۰ ثانیه وقتی نیست. بعد از ۲۴ ساعت poll می‌ایستد ولی
کار در صف می‌ماند و هر بار که پنل باز شود دوباره وارسی می‌شود (views._nudge)."""
from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import services
from .models import PhotoEdit

logger = logging.getLogger(__name__)

POLL_ONLINE = 6
POLL_OFFLINE = 30
POLL_HOURS = 24


def _eager() -> bool:
    return bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))


def _edit(edit_id: int) -> PhotoEdit | None:
    return PhotoEdit.objects.filter(pk=edit_id).select_related("asset", "asset__store").first()


def _schedule_poll(edit_id: int, started: str | None = None) -> None:
    if _eager():
        return
    online = services.node_status()["online"]
    poll_edit_task.apply_async((edit_id, started or timezone.now().isoformat()),
                               countdown=POLL_ONLINE if online else POLL_OFFLINE)


@shared_task(ignore_result=True)
def start_edit_task(edit_id: int) -> None:
    edit = _edit(edit_id)
    if edit is None:
        return
    services.start(edit)
    if edit.state == PhotoEdit.State.NODE:
        if services.refresh(edit):          # همان ویرایش قبلاً ساخته شده بود ⇐ همین حالا
            edit.refresh_from_db()
            services.run_server_stage(edit)
            return
        _schedule_poll(edit_id)


@shared_task(ignore_result=True)
def poll_edit_task(edit_id: int, started: str | None = None) -> None:
    edit = _edit(edit_id)
    if edit is None or edit.state != PhotoEdit.State.NODE:
        return
    if services.refresh(edit):
        finish_edit_task.delay(edit_id)
        return
    edit.refresh_from_db()
    if edit.state != PhotoEdit.State.NODE:
        return
    try:
        begun = datetime.fromisoformat(started) if started else edit.created_at
    except ValueError:
        begun = edit.created_at
    if (timezone.now() - begun).total_seconds() > POLL_HOURS * 3600:
        logger.info("photoedit: edit %s still waits for a processing server; polling stops (panel nudges it)", edit_id)
        return
    _schedule_poll(edit_id, started)


@shared_task(ignore_result=True, soft_time_limit=900)
def finish_edit_task(edit_id: int) -> None:
    edit = _edit(edit_id)
    if edit is not None and edit.state == PhotoEdit.State.SERVER:
        services.run_server_stage(edit)
