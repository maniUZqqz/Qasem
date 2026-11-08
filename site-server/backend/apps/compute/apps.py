from django.apps import AppConfig
from django.db.models.signals import pre_save


def _link_job(sender, instance, **_kwargs):
    """کارِ تازهٔ سرورِ پردازش که درونِ تسکِ یک Job ساخته می‌شود، شناسهٔ همان Job را می‌گیرد («پردازشِ دوباره» در صف)."""
    if not instance._state.adding or instance.job_ref:
        return
    try:
        from apps.jobs.retry import current_job_id

        jid = current_job_id()
    except Exception:  # noqa: BLE001
        jid = None
    if jid:
        instance.job_ref = jid


class ComputeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.compute"
    verbose_name = "سرورهای پردازش"

    def ready(self):
        from .models import ComputeJob

        pre_save.connect(_link_job, sender=ComputeJob, weak=False, dispatch_uid="compute.link_job")
