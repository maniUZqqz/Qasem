import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("upmarket")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# لاگِ worker و beat هم UTC با «Z» (مثلِ لاگ‌های جنگو)؛ قبلاً به وقتِ تهران و بی‌نشانه بود (nm_ops)
from celery.signals import after_setup_logger, after_setup_task_logger  # noqa: E402

from config.logging_utils import utc_celery_handlers  # noqa: E402


@after_setup_logger.connect
@after_setup_task_logger.connect
def _utc_celery_logs(logger=None, **_kwargs):
    utc_celery_handlers(logger)
