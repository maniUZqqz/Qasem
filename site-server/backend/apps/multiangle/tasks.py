"""کارِ دوره‌ای (beat هر دو دقیقه): هر سرورِ پردازشِ روشنِ چندزاویه‌دار را آماده می‌کند (نصبِ خودکارِ محیط و مدل‌ها) و آزمونِ خودکارش را می‌زند —
بی‌آن‌که کسی چیزی را بزند."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.multiangle.tasks.autocheck", ignore_result=True)
def autocheck():
    from . import services

    try:
        return services.autocheck()
    except Exception as exc:  # noqa: BLE001 — یک خطا نباید beat را بخواباند
        logger.warning("multiangle autocheck failed: %s", exc)
        return {"error": str(exc)[:200]}
