"""
API گیت‌وی پیامک (گوشیِ اندرویدیِ ارسال‌کننده) — همان قراردادِ نمونهٔ فلسک:

    GET  /api/next-otp    →  [{"id": "...", "phone": "0912...", "code": "1234"}, ...]
    POST /api/mark-sent   {"id": "..."}  →  {"status": "ok"}
                                          یا 404 {"error": "id not found"}

گوشی مرتب next-otp را می‌خواند، هر کد را پیامک می‌کند و بعد mark-sent می‌زند.
فقط کدهای ارسال‌نشده و منقضی‌نشده برگردانده می‌شوند.
"""
import json
import logging
import time

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import SMSOutbox

logger = logging.getLogger(__name__)

# آخرین تماسِ گوشی — در «صف پیامک» ِ ادمین نشان داده می‌شود (sms_gateway_status). هر پروسه حداکثر هر ۱۵ ثانیه
# یک بار در کش (دیتابیس) می‌نویسد تا نظرسنجیِ دوثانیه‌ایِ گوشی بارِ نوشتن نسازد.
SEEN_KEY = 'sms_gateway_seen'
_last_write = {}


def _remember(request, what, extra=None):
    ua = request.META.get('HTTP_USER_AGENT', '')
    who = 'phone' if 'dart' in ua.lower() else 'other'
    now = time.time()
    if what == 'poll' and now - _last_write.get((what, who), 0) < 15:
        return
    _last_write[(what, who)] = now
    try:
        seen = cache.get(SEEN_KEY) or {}
        seen['%s_%s' % (what, who)] = {
            'at': timezone.now().isoformat(),
            'ip': request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', ''),
            'ua': ua[:120],
            **(extra or {}),
        }
        cache.set(SEEN_KEY, seen, None)
    except Exception:  # noqa: BLE001 — وضعیت فقط برای نمایش است؛ نباید جوابِ گوشی را خراب کند
        logger.exception('ثبتِ آخرین تماسِ گیت‌وی پیامک نشد')


def gateway_status():
    """برای ادمین: آخرین تماسِ گوشی و دیگران با next-otp / mark-sent."""
    return cache.get(SEEN_KEY) or {}


@require_GET
def next_otp(request):
    result = [
        {'id': str(item.id), 'phone': item.phone, 'code': item.code}
        for item in SMSOutbox.pending()
    ]
    _remember(request, 'poll', {'pending': len(result)})
    return JsonResponse(result, safe=False)


@csrf_exempt
@require_POST
def mark_sent(request):
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    item_id = data.get('id') or request.POST.get('id')
    if not item_id:
        return JsonResponse({'error': 'id is required'}, status=400)

    try:
        updated = SMSOutbox.objects.filter(pk=item_id).update(sent=True, sent_at=timezone.now())
    except (ValidationError, ValueError):
        updated = 0
    _remember(request, 'mark', {'ok': bool(updated)})
    if not updated:
        return JsonResponse({'error': 'id not found'}, status=404)

    logger.info(f'گیت‌وی پیامک: {item_id} ارسال شد')
    return JsonResponse({'status': 'ok'})
