from django.apps import AppConfig


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        # ثبت بررسی‌های زمان راه‌اندازی (فونت PDF، فضای خصوصی، درگاه تستی)
        from . import checks  # noqa: F401


# ─────────────────────── تنظیمِ SQLite برای سایتِ زنده ───────────────────────
# چرا لازم است: سایت دو کارگرِ gunicorn با چهار نخ دارد. در حالتِ پیش‌فرضِ
# SQLite، یک نوشتن همهٔ خواندن‌ها را می‌خواباند و کاربر «کندی» حس می‌کند؛ و
# زیرِ هم‌زمانی خطای «database is locked» می‌دهد.
#   WAL          → خواندن و نوشتن هم‌زمان می‌شوند
#   busy_timeout → به‌جای خطا، تا ۲۰ ثانیه صبر می‌کند
#   synchronous=NORMAL → نوشتن سریع‌تر، با WAL همچنان بی‌خطر
from django.db.backends.signals import connection_created  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(connection_created)
def _tune_sqlite(sender, connection, **kwargs):
    if connection.vendor != 'sqlite':
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA busy_timeout=20000;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
    except Exception:
        import logging
        logging.getLogger(__name__).warning('تنظیمِ SQLite انجام نشد', exc_info=True)
