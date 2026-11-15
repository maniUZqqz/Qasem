"""لاگِ NMarketing: قالبِ یکدست، زمانِ UTC، خطاها با نشانی و کاربر، و کم‌کردنِ نویزِ تسک‌های هر‌دقیقه.

چرا (۱۴۰۵/۰۸/۲۳، ممیزیِ کیفیت):
* ~۸۵٪ خط‌های celery.log فقط «Task … received / succeeded» برای تسک‌های هر دقیقه بود (maintenance، run_scheduled_publishes، poll_thumb_task…)
  و ۱۲۲ traceback زیرِ آن‌ها گم بود.
* زمانِ لاگ‌ها در سه منطقهٔ زمانی بود (celery/gunicorn-access = تهران بدونِ نشانه؛ gunicorn-error/nginx/journal = UTC).
  حالا لاگ‌های پایتون همه UTC با «Z» هستند؛ لاگِ gunicorn-access و nginx خودشان offset را می‌نویسند.
* ردِ خطاهای HTTP 500 فقط ~۲۷ ساعت در journal می‌ماند. حالا WARNING به بالا (با نشانی و شناسهٔ کاربر) در logs/django-errors.log هم می‌رود.
"""
from __future__ import annotations

import logging
import time


class UtcFormatter(logging.Formatter):
    """زمان را UTC و با «Z» می‌نویسد: «2026-11-14 10:27:01Z»."""

    converter = time.gmtime

    def formatTime(self, record, datefmt=None):  # noqa: N802 (API of logging)
        text = time.strftime("%Y-%m-%d %H:%M:%S", self.converter(record.created))
        return f"{text}Z"


class RequestInfoFilter(logging.Filter):
    """به هر رکورد `path` و `user_id` و `method` می‌افزاید (از `record.request` که django.request می‌گذارد؛ وگرنه «-»)."""

    def filter(self, record: logging.LogRecord) -> bool:
        request = getattr(record, "request", None)
        record.path = getattr(request, "path", None) or "-"
        record.method = getattr(request, "method", None) or "-"
        record.user_id = "-"
        if request is not None:
            try:
                user = getattr(request, "user", None)
                if user is not None and getattr(user, "is_authenticated", False):
                    record.user_id = str(getattr(user, "pk", "-"))
            except Exception:  # noqa: BLE001 — لاگ‌کردن هرگز نباید خودش خطا بدهد
                pass
        return True


def _task_name(record: logging.LogRecord) -> str:
    """نامِ تسک را از رکوردِ celery.worker.strategy («Task %s[%s] received») یا celery.app.trace (args دیکشنری) درمی‌آورد."""
    args = record.args
    if isinstance(args, dict):
        return str(args.get("name", ""))
    if isinstance(args, tuple) and args:
        return str(args[0])
    return ""


class QuietPeriodicTasksFilter(logging.Filter):
    """رکوردهای INFO ِ «Task X received/succeeded» را برای تسک‌های هر‌چند‌دقیقه‌یک‌بار حذف می‌کند (WARNING و بالاتر همیشه می‌ماند).

    فهرستِ تسک‌ها از CELERY_BEAT_SCHEDULE می‌آید: هر ورودی‌ای که بازه‌اش ≤ `max_interval` ثانیه باشد؛ به‌علاوهٔ «پولرها»
    (تسک‌هایی که نامشان با poll_ شروع می‌شود، مثلِ poll_thumb_task و poll_render_task که هر چند ثانیه خودشان را دوباره صف می‌کنند).
    اگر تسکی دیرتر هم اجرا شود (ساعتی/روزانه) لاگ‌اش می‌ماند. فیلتر روی خودِ لاگرها نصب می‌شود (settings.LOGGING)،
    پس به celery.log و journal هر دو اثر دارد.
    """

    def __init__(self, names: frozenset[str] | set[str] | None = None, max_interval: float = 1800.0):
        super().__init__()
        self._names = frozenset(names) if names is not None else None
        self.max_interval = max_interval

    @property
    def names(self) -> frozenset[str]:
        if self._names is None:
            self._names = frozenset(noisy_task_names(self.max_interval))
        return self._names

    def is_noisy(self, task: str) -> bool:
        return task in self.names or task.rsplit(".", 1)[-1].startswith("poll_")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.INFO:
            return True
        task = _task_name(record)
        return not (task and self.is_noisy(task))


def _interval_seconds(schedule) -> float | None:
    """ثانیهٔ بازهٔ یک schedule (عدد، timedelta، celery.schedules.schedule)؛ crontab ⇒ None (کم‌تکرار فرض می‌شود)."""
    if isinstance(schedule, (int, float)):
        return float(schedule)
    run_every = getattr(schedule, "run_every", None)
    if run_every is not None and hasattr(run_every, "total_seconds"):
        return float(run_every.total_seconds())
    if hasattr(schedule, "total_seconds"):
        return float(schedule.total_seconds())
    return None


def noisy_task_names(max_interval: float = 1800.0) -> set[str]:
    from django.conf import settings

    names: set[str] = set()
    for entry in (getattr(settings, "CELERY_BEAT_SCHEDULE", None) or {}).values():
        seconds = _interval_seconds(entry.get("schedule"))
        if seconds is not None and 0 < seconds <= max_interval and entry.get("task"):
            names.add(str(entry["task"]))
    return names


def utc_celery_handlers(logger) -> None:
    """هندلرهای لاگرِ celery (worker/beat) را روی زمانِ UTC می‌گذارد؛ «Z» در CELERY_WORKER_LOG_FORMAT است (settings)."""
    for handler in getattr(logger, "handlers", None) or []:
        formatter = getattr(handler, "formatter", None)
        if formatter is not None:
            formatter.converter = time.gmtime
