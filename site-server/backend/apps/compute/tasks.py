from celery import shared_task


@shared_task(name="apps.compute.tasks.maintenance")
def maintenance():
    """کارهای گره‌های خاموش‌شده را دوباره در صف می‌گذارد (هر دقیقه از beat)."""
    from . import services

    return {"requeued": services.requeue_stale()}
