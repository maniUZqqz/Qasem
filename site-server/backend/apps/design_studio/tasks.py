"""کارهای Celery ِ استودیوی طراحی: ساختِ خروجی‌ها (PDF چاپی، بسته‌ها…) پشتِ صف تا درخواستِ وب منتظر نماند."""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True, name="apps.design_studio.tasks.run_export_task", time_limit=1500, soft_time_limit=1400)
def run_export_task(export_id: int) -> None:
    from . import services

    services.run_export(export_id)


def dispatch_export(export_id: int) -> None:
    """صفِ Celery؛ بی‌بروکر یا حالتِ eager همان‌جا اجرا می‌شود."""
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        run_export_task(export_id)
        return
    try:
        run_export_task.delay(export_id)
    except Exception:  # noqa: BLE001
        logger.warning("design: celery unavailable, running export %s inline", export_id)
        run_export_task(export_id)
