"""کارهای Celery ِ بازسازیِ تکه. هیچ‌کدام منتظرِ سرورِ پردازش نمی‌ماند (نخِ Celery گرو نمی‌رود):
poll خودش را هر چند ثانیه دوباره در صف می‌گذارد تا کارِ گره تمام شود."""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from . import services
from .models import RegenSession, RegenVersion

logger = logging.getLogger(__name__)

POLL_SECONDS = 8
#: بیش از این، نسخه منتظرِ گره نمی‌ماند (گره خاموش) — همان لحظه هم در پنل دیده می‌شود و قابلِ لغو است
MAX_POLLS = 6 * 3600 // POLL_SECONDS


def _eager() -> bool:
    return bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))


@shared_task(ignore_result=True)
def prepare_session_task(session_id: int) -> None:
    session = RegenSession.objects.filter(pk=session_id).first()
    if session and session.state == RegenSession.State.PREPARING:
        services.prepare_session(session)


@shared_task(ignore_result=True)
def start_version_task(version_id: int) -> None:
    version = RegenVersion.objects.filter(pk=version_id).select_related("session").first()
    if version is None:
        return
    services.start_version(version)
    if version.state == RegenVersion.State.GENERATING and not _eager():
        poll_version_task.apply_async((version_id, 0), countdown=POLL_SECONDS)


@shared_task(ignore_result=True)
def poll_version_task(version_id: int, n: int = 0) -> None:
    version = RegenVersion.objects.filter(pk=version_id).select_related("session").first()
    if version is None or version.state != RegenVersion.State.GENERATING:
        return
    if services.refresh(version):
        stitch_version_task.delay(version_id)
        return
    version.refresh_from_db()
    if version.state != RegenVersion.State.GENERATING or _eager():
        return
    if n >= MAX_POLLS:
        services.cancel(version)
        RegenVersion.objects.filter(pk=version_id).update(message="سرورِ پردازش در ۶ ساعت کار را تمام نکرد؛ لغو شد.")
        return
    poll_version_task.apply_async((version_id, n + 1), countdown=POLL_SECONDS)


@shared_task(ignore_result=True, soft_time_limit=4 * 3600)
def stitch_version_task(version_id: int) -> None:
    version = RegenVersion.objects.filter(pk=version_id).select_related("session").first()
    if version is not None:
        services.stitch_version(version)
