# -*- coding: utf-8 -*-
"""کارهای پس‌زمینهٔ «تصویر به کد»: اجرای یک تبدیل (یکی‌یکی؛ اگر قفل دست دیگری بود صبر در صف، بدونِ نگه‌داشتنِ نخِ worker) و رُفتن‌های دوره‌ای."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="apps.img2code.tasks.run_conversion", ignore_result=True, max_retries=900, soft_time_limit=900, time_limit=960)
def run_conversion(self, conv_id):
    from . import services
    from .models import Conversion

    conv = Conversion.objects.filter(pk=conv_id).first()
    if conv is None or conv.state not in (Conversion.State.QUEUED, Conversion.State.RUNNING):
        return {"skipped": True}
    # «اولین وارد، اولین خارج»: اگر تبدیلِ قدیمی‌تری هنوز منتظر است نوبت با آن است (این‌جا قفل را امتحان هم نمی‌کنیم)
    lock = services.RunLock()
    if not services.is_my_turn(conv) or not lock.acquire():
        pos = services.queue_position(conv)
        from django.utils import timezone
        Conversion.objects.filter(pk=conv_id, state=Conversion.State.QUEUED).update(
            message="در صف؛ %s (نوبتِ %s)" % ("تبدیلِ قدیمی‌تری پیش از این است" if pos > 1 else "یک تبدیلِ دیگر در حال اجراست", services._fa_digits(str(pos))), updated_at=timezone.now())
        raise self.retry(countdown=5)
    try:
        conv = services.run(conv)
        return {"state": conv.state}
    finally:
        lock.release()


@shared_task(name="apps.img2code.tasks.sweep", ignore_result=True)
def sweep():
    from . import services
    try:
        return services.sweep()
    except Exception as exc:  # noqa: BLE001 — یک خطا beat را نخواباند
        logger.warning("img2code sweep failed: %s", exc)
        return {"error": str(exc)[:200]}
