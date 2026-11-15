"""کارِ Celery ِ «سبک تصویر»: هر ۵ دقیقه (beat) بدونِ دخالتِ کسی

* تصویرهای نمونهٔ ساخته‌شده را برمی‌دارد و دستهٔ ۱۲تاییِ بعدی را در صفِ ماندگارِ سرورِ پردازش می‌گذارد (``samples.auto_step``)؛
* آزمونِ کوچکِ «یک تصویرِ ۵۱۲×۵۱۲» را نگه می‌دارد و می‌سنجد (``selftest.auto_step``).

گره خاموش باشد کارها در صف می‌مانند و با روشن‌شدنش خودکار انجام می‌شوند.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.looks.tasks.step", ignore_result=True, soft_time_limit=120)
def step() -> dict:
    out: dict = {}
    for name in ("samples", "selftest"):
        try:
            if name == "samples":
                from . import samples

                out[name] = samples.auto_step()
            else:
                from . import selftest

                out[name] = selftest.auto_step()
        except Exception as exc:  # noqa: BLE001 — کارِ پس‌زمینه هرگز چیزِ دیگری را خراب نکند
            logger.warning("looks: %s step failed: %s", name, exc)
            out[name] = {"action": "error", "why": str(exc)[:200]}
    return out
