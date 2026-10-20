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

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import SMSOutbox

logger = logging.getLogger(__name__)


@require_GET
def next_otp(request):
    result = [
        {'id': str(item.id), 'phone': item.phone, 'code': item.code}
        for item in SMSOutbox.pending()
    ]
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
    if not updated:
        return JsonResponse({'error': 'id not found'}, status=404)

    logger.info(f'گیت‌وی پیامک: {item_id} ارسال شد')
    return JsonResponse({'status': 'ok'})
