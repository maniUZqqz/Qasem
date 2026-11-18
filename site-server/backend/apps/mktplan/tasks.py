"""کارهای پس‌زمینهٔ برنامهٔ بازاریابی (Celery)."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.mktplan.tasks.run_plan_task")
def run_plan_task(plan_id: int, user_id: int | None = None, keys: list[str] | None = None) -> dict:
    from django.contrib.auth.models import User

    from . import runner
    from .models import MarketingPlan

    plan = MarketingPlan.objects.select_related("store").filter(pk=plan_id).first()
    if plan is None:
        return {"error": "plan not found"}
    user = User.objects.filter(pk=user_id).first() if user_id else None
    res = runner.run_plan(plan, user=user, keys=set(keys) if keys else None)
    return {k: v for k, v in res.items() if k != "log"}


@shared_task(name="apps.mktplan.tasks.tick")
def tick() -> dict:
    """هر ۱۰ دقیقه: وضعیتِ کارها را از چیزهای ساخته‌شده تازه می‌کند و کارهای منتظرِ سرورِ پردازش/هوش مصنوعی را پیش می‌برد."""
    from . import runner

    return runner.tick()
