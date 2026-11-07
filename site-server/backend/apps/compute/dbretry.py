"""SQLite «database is locked» یک خطای واقعی نیست؛ فقط یعنی همین لحظه یک نویسندهٔ دیگر کارش را تمام نکرده.

سایت روی SQLite کار می‌کند (gunicorn ۲×۸ نخ + celery ۴ نخ + beat + گره‌ها)؛ تنها یک نفر هم‌زمان می‌تواند بنویسد. اگر یکی
(مثلاً ورودِ دسته‌جمعیِ CSV، یک تسکِ سنگین) چند ثانیه قفل را نگه دارد، بقیه تا `busy_timeout` صبر می‌کنند و بعد خطا می‌گیرند.
در صفِ پردازش این خطا هرگز نباید کاری را «ناموفق» یا نیمه‌ساخته رها کند. سه لایه:

  1. تنظیماتِ پایگاه‌داده (config/settings.py): busy_timeout سی‌ثانیه‌ای، WAL، و تراکنشِ IMMEDIATE (قفلِ نوشتن از همان BEGIN
     گرفته می‌شود و صبر می‌کند، نه اینکه وسطِ «خواندن ⇐ نوشتن» فوراً خطا بدهد).
  2. این ماژول: نوشتن‌های کوتاهِ صف با عقب‌نشینیِ نمایی و تکرار می‌شوند (`retry_on_lock` / `call_with_retry`).
  3. نماهای گره (`node_api`): اگر پس از همهٔ تکرارها هم قفل بود، «۵۰۳ + Retry-After» برمی‌گردد — گره (عامل) آن را «تکرارپذیر»
     می‌داند و دوباره می‌فرستد؛ هیچ کاری به‌خاطر قفل ناموفق ثبت نمی‌شود.

داخلِ `transaction.atomic()` نمی‌شود تکرار کرد (تراکنش شکسته است)؛ آن‌جا خطا به بیرونی‌ترین لایه می‌رسد که خودش تکرار می‌کند.
"""
from __future__ import annotations

import functools
import logging
import random
import time

from django.conf import settings
from django.db import OperationalError, connection

logger = logging.getLogger(__name__)

_MARKS = ("database is locked", "database table is locked", "database schema is locked", "database is busy", "sqlite_busy")
#: تعدادِ تلاش (هر تلاش خودش تا busy_timeout صبر می‌کند) و عقب‌نشینی (ثانیه)
TRIES = int(getattr(settings, "NM_DB_LOCK_TRIES", 6))
BASE_DELAY = 0.25
MAX_DELAY = 4.0


def is_lock_error(exc: BaseException) -> bool:
    """خطای قفلِ SQLite (نه هر OperationalError ِ دیگر مثل «no such table»)."""
    if not isinstance(exc, OperationalError):
        return False
    text = str(exc).lower()
    return any(mark in text for mark in _MARKS)


def call_with_retry(fn, *args, _tries: int | None = None, _what: str = "", **kwargs):
    """fn را اجرا می‌کند؛ روی قفلِ SQLite با عقب‌نشینی و جیتر دوباره. خطای دیگر یا تمام‌شدنِ تلاش‌ها ⇒ همان خطا."""
    tries = _tries or TRIES
    delay = BASE_DELAY
    for attempt in range(1, tries + 1):
        try:
            return fn(*args, **kwargs)
        except OperationalError as exc:
            if not is_lock_error(exc):
                raise
            if connection.in_atomic_block or attempt >= tries:
                if attempt >= tries:
                    logger.warning("compute: database stayed locked after %s tries (%s)", attempt, _what or getattr(fn, "__name__", "?"))
                raise
            logger.info("compute: database is locked (%s), retry %s/%s", _what or getattr(fn, "__name__", "?"), attempt, tries)
            time.sleep(delay * (0.6 + random.random() * 0.8))
            delay = min(MAX_DELAY, delay * 2)
    raise AssertionError("unreachable")        # pragma: no cover


def retry_on_lock(fn=None, *, tries: int | None = None):
    """دکوراتور: همان call_with_retry برای یک تابعِ کوتاه و idempotent (فقط یک نوشتن یا چند نوشتنِ بی‌اثرِ تکراری)."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return call_with_retry(f, *args, _tries=tries, _what=f.__name__, **kwargs)
        return wrapper
    return deco(fn) if fn else deco
