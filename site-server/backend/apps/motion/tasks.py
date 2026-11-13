"""کارهای Celery ِ استودیوی موشن.

  · site_render_task  ⇒ رندرِ سایت (یک‌به‌یک، با قفل)
  · poll_render_task  ⇒ وضعیتِ کارِ گره را دنبال می‌کند و وقتی تمام شد ویدیو را در رسانهٔ فروشگاه می‌گذارد.
    نخِ Celery گرو نمی‌ماند: خودش را دوباره در صف می‌گذارد (۶ ثانیه وقتی گره آنلاین است، ۳۰ ثانیه وقتی نیست، تا ۴۸ ساعت).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import services
from .models import MotionRender

logger = logging.getLogger(__name__)

POLL_ONLINE = 6
POLL_OFFLINE = 30
POLL_HOURS = 48


def _eager() -> bool:
    return bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))


def schedule_poll(render_id: int) -> None:
    if _eager():
        return
    from apps.compute import services as CS

    online = bool(CS.online_nodes(services.CAPABILITY))
    poll_render_task.apply_async((render_id,), countdown=POLL_ONLINE if online else POLL_OFFLINE)


@shared_task(ignore_result=True, name="apps.motion.tasks.poll_render_task")
def poll_render_task(render_id: int) -> None:
    r = MotionRender.objects.filter(pk=render_id).select_related("store").first()
    if r is None or r.state not in MotionRender.ACTIVE or r.target != MotionRender.Target.NODE:
        return
    if services.refresh(r):
        return
    if timezone.now() - r.created_at > timedelta(hours=POLL_HOURS):
        return          # کار در صف می‌ماند؛ با باز شدنِ پنل دوباره وارسی می‌شود
    schedule_poll(render_id)


@shared_task(ignore_result=True, name="apps.motion.tasks.site_render_task", time_limit=services.runner.SITE_TIMEOUT_S + 600)
def site_render_task(render_id: int) -> None:
    r = MotionRender.objects.filter(pk=render_id).select_related("store").first()
    if r is None:
        return
    services.render_on_site(r)


def dispatch(render: MotionRender) -> None:
    """رندرِ تازه‌ساخته را به راه می‌اندازد (گره: ثبت در صف + poll؛ سایت: تسکِ رندر)."""
    try:
        services.start(render)
        render.refresh_from_db()
        if render.state == MotionRender.State.FAILED:
            return
        if render.target == MotionRender.Target.SITE:
            _run(site_render_task, render.pk)
        else:
            schedule_poll(render.pk)
    except Exception as exc:  # noqa: BLE001
        logger.exception("motion: dispatch of %s failed", render.pk)
        services.fail(render, f"شروعِ رندر ناموفق بود: {exc}")


def _run(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:  # noqa: BLE001 — بی‌بروکر: همین‌جا
        logger.warning("motion: celery unavailable, running %s inline", task.name)
        task(*args)
