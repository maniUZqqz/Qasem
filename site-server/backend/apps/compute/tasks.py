from celery import shared_task


@shared_task(name="apps.compute.tasks.maintenance")
def maintenance():
    """کارهای گره‌های خاموش‌شده را دوباره در صف می‌گذارد (هر دقیقه از beat)."""
    from . import park, services

    out = {"requeued": services.requeue_stale()}
    try:
        from . import autopilot
        out["autopilot"] = autopilot.tick()   # به‌روزرسانیِ خودکارِ گره‌های بی‌کار، آزمونِ شبانه، جلو بردنِ آزمون‌های در جریان
    except Exception as exc:  # noqa: BLE001 — خودکارها نباید requeue را بخواباند
        out["autopilot_error"] = str(exc)[:200]
    try:
        out["woken"] = park.wake_parked()      # کارهای Celeryِ منتظرِ سرورِ پردازش (صفِ ماندگار)
    except Exception as exc:  # noqa: BLE001 — یک خطا نباید requeue را بخواباند
        out["wake_error"] = str(exc)[:200]
    try:
        from . import report
        out["report"] = report.maintain()     # بستنِ نوبت‌های ساکت، فشرده‌سازی و پاکسازیِ آمارِ گزارش (هر ۱۰ دقیقه، کران‌دار)
    except Exception as exc:  # noqa: BLE001 — آمار نباید requeue را بخواباند
        out["report_error"] = str(exc)[:200]
    return out

