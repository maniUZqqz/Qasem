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
    try:
        from . import report
        out["report"] = report.maintain()     # بستنِ نوبت‌های ساکت، فشرده‌سازی و پاکسازیِ آمارِ گزارش (هر ۱۰ دقیقه، کران‌دار)
    except Exception as exc:  # noqa: BLE001 — آمار نباید requeue را بخواباند
        out["report_error"] = str(exc)[:200]
    return out


@shared_task(name="apps.compute.tasks.remote_control")
def remote_control(node_pk, action, by=""):
    """«کنترل از راهِ دور»: یک دستورِ ثابت روی سرورِ پردازش از راهِ تونلش (remote.py)؛ نتیجه در پنل و لاگِ همان سرور."""
    from . import remote
    from .models import ComputeNode

    node = ComputeNode.objects.filter(pk=node_pk).first()
    if node is None:
        return {"error": "node gone"}
    row = remote.control(node, action, by)
    return {"action": action, "exit_code": row.get("exit_code")}
