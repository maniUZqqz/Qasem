from celery import shared_task


@shared_task(name="apps.compute.tasks.maintenance")
def maintenance():
    """کارهای گره‌های خاموش‌شده را دوباره در صف می‌گذارد (هر دقیقه از beat)."""
    from . import park, services

    out = {"requeued": services.requeue_stale()}
    try:
        out["woken"] = park.wake_parked()      # کارهای Celeryِ منتظرِ سرورِ پردازش (صفِ ماندگار)
    except Exception as exc:  # noqa: BLE001 — یک خطا نباید requeue را بخواباند
        out["wake_error"] = str(exc)[:200]
    return out
