"""
Webhook دریافت JSON کد تایید.
این endpoint همان چیزی است که SMS_HOOK_URL به آن POST می‌کند.
"""
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def sms_webhook(request):
    """
    دریافت JSON به فرمت: {"09225674948": "1234"}
    فعلاً کد را در لاگ ثبت می‌کند.
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"SMS webhook: invalid JSON - {exc}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    logger.info(f"📱 SMS WEBHOOK دریافت کرد: {payload}")

    # اینجا می‌تونی به سرویس پیامک واقعی وصل کنی
    # مثلاً کاوه‌نگار، ملی‌پیامک، فراز اس‌ام‌اس و ...

    # برای تست: کد را در فایل هم ذخیره می‌کنیم که راحت‌تر ببینی
    try:
        with open('/tmp/sms_webhook.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception as exc:
        logger.warning(f"Could not write sms_webhook.log: {exc}")

    return JsonResponse({'success': True, 'received': payload}, status=200)