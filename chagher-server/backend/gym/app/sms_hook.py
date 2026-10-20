"""
کد تایید ثبت‌نام و صفِ ارسالِ آن به گیت‌وی پیامک.

کد در کش (DatabaseCache، مشترک بین workerها) نگه داشته می‌شود و یک ردیف در
SMSOutbox می‌گیرد؛ گوشیِ گیت‌وی با GET /api/next-otp آن را برمی‌دارد، پیامک
می‌کند و با POST /api/mark-sent «ارسال شد» می‌زند (sms_gateway.py).

اگر پیامک نرسید، کاربر می‌تواند کد اضطراری (SMS_EMERGENCY_CODE) را وارد کند.
"""
import secrets
import logging
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SMS_CODE_TTL = getattr(settings, 'SMS_CODE_TTL', 300)

_CACHE_KEY = 'reg_otp:{phone}'


def _generate_code() -> str:
    return str(secrets.randbelow(9000) + 1000)


def issue_registration_code(phone_number: str) -> str:
    key = _CACHE_KEY.format(phone=phone_number)

    existing = cache.get(key)
    if existing:
        return existing

    for _ in range(5):
        code = _generate_code()
        if cache.add(key, code, timeout=SMS_CODE_TTL):
            return code
        existing = cache.get(key)
        if existing:
            return existing

    raise RuntimeError('عدم توانایی در تولید کد یکتا')


def is_emergency_code(code: str) -> bool:
    """کد اضطراری — وقتی پیامک نرسیده به‌جای کدِ پیامکی پذیرفته می‌شود."""
    emergency = str(getattr(settings, 'SMS_EMERGENCY_CODE', '') or '').strip()
    return bool(emergency) and secrets.compare_digest(emergency, str(code).strip())


def verify_registration_code(phone_number: str, code: str) -> bool:
    if not code:
        return False
    key = _CACHE_KEY.format(phone=phone_number)
    if is_emergency_code(code):
        logger.warning(f'ثبت‌نام {phone_number} با کد اضطراری تایید شد')
        cache.delete(key)
        return True
    stored = cache.get(key)
    if not stored:
        return False
    if not secrets.compare_digest(str(stored), str(code)):
        return False
    cache.delete(key)
    return True


def peek_registration_code(phone_number: str) -> str:
    """فقط برای دیباگ — کد فعلی را برمی‌گرداند بدون حذف کردن."""
    return cache.get(_CACHE_KEY.format(phone=phone_number))


def queue_registration_code(phone_number: str, code: str):
    """کد را در صفِ گیت‌وی پیامک می‌گذارد (تکراریِ ارسال‌نشده ساخته نمی‌شود)."""
    from .models import SMSOutbox
    item = SMSOutbox.enqueue(phone_number, code, purpose=SMSOutbox.PURPOSE_REGISTER, ttl_seconds=SMS_CODE_TTL)
    logger.info(f'کد ثبت‌نام {phone_number} در صف گیت‌وی پیامک: {item.id}')
    return item
