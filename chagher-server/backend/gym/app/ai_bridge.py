# -*- coding: utf-8 -*-
"""حالتِ سومِ هوش مصنوعی — سرورِ محلیِ **بی‌آی‌پیِ ثابت** که شنونده است.

گزارشِ مالک: «دو حالت داریم: API سرویس‌دهنده‌ها، و لوکال با IP. حالتِ سوم را
می‌خواهم: سرورِ هوش مصنوعی آی‌پیِ ثابت ندارد، پس خودش یک URL روی سایت را گوش
می‌دهد؛ اگر روشن باشد کار را برمی‌دارد و جوابش را می‌دهد.»

و دو باگی که صریحاً گفته نباید پیش بیاید:
  ۱) «سرورِ سایت تا ابد منتظرِ سرورِ لوکال نماند و درخواستِ کاربر از بین نرود.»
     → هر کار **مهلت** دارد و پیش از ساختنِ کار، **زنده‌بودنِ شنونده** سنجیده
       می‌شود. شنونده خاموش ⇒ همان لحظه می‌رویم سرِ ارائه‌دهندهٔ بعدی.
  ۲) «به شنونده و یکی دیگر هم‌زمان نگوید و دو هزینه بدهد.»
     → زنجیره ترتیبی است و هر کار با **اجارهٔ یکتا** فقط به یک کارگر می‌رسد؛
       اگر مهلت تمام شد، کار `expired` می‌شود و جوابِ دیررسِ کارگر **دور
       ریخته** می‌شود. پس هیچ‌وقت دو جواب برای یک درخواست حساب نمی‌شود.

جریانِ کار:
    جنگو: AIJob(queued) ─────────────────────────────┐
    کارگرِ محلی: POST claim/  → اجاره می‌گیرد        │ هر ۱ ثانیه
    کارگرِ محلی: POST result/ → جواب را می‌گذارد     │ چک می‌کند
    جنگو: جواب را برمی‌دارد ◀────────────────────────┘
"""
import json
import logging
import secrets
import time

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import AIJob, APIConfig

logger = logging.getLogger(__name__)

# کارگر چند ثانیه برای تحویلِ جواب وقت دارد؛ از آن بیشتر، کار آزاد می‌شود تا
# کارگرِ دیگری (یا دورِ بعد) برش دارد.
LEASE_SECONDS = 120


def _listener_configs(include_inactive=False):
    """ارائه‌دهنده‌های نوعِ «شنونده»، به ترتیبِ اولویت.

    include_inactive فقط برای پیامِ خطاست: اگر کلید درست باشد ولی ردیف خاموش،
    باید بگوییم «فعالش کن»، نه «کلیدت غلط است».
    """
    if include_inactive:
        return list(APIConfig.objects
                    .filter(provider_type=APIConfig.PROVIDER_TYPE_LISTENER)
                    .order_by('priority', 'id'))
    return [p for p in APIConfig.get_chain()
            if p.provider_type == APIConfig.PROVIDER_TYPE_LISTENER]


def _auth_ok(request, config):
    """کلیدِ مشترک در هدر Authorization یا X-Worker-Key."""
    sent = (request.META.get('HTTP_X_WORKER_KEY')
            or (request.META.get('HTTP_AUTHORIZATION') or '').replace('Bearer', '').strip())
    expected = (config.api_key or '').strip()
    return bool(expected) and secrets.compare_digest(sent.strip(), expected)


def _config_for_request(request):
    """(ارائه‌دهنده، پاسخِ خطا) — پاسخِ خطا None یعنی اجازه هست.

    ⚠ چرا تاپل: پیش از این فقط None برمی‌گرداند و هر چهار مسیر «کلید غلط»
    می‌گفتند. وقتی کلید درست بود ولی ردیف در ادمین فعال نشده بود، کارگر ۴۰۱
    می‌گرفت و هیچ‌کس نمی‌فهمید چرا — همان گیری که در راه‌اندازی پیش آمد.
    """
    for config in _listener_configs(include_inactive=True):
        if _auth_ok(request, config):
            if not config.is_active:
                return None, Response(
                    {'error': 'این ارائه‌دهنده در جنگو ادمین «فعال» نیست. '
                              'تیکِ «فعال» را بزنید تا کارگر بتواند کار بگیرد.',
                     'code': 'provider_inactive'},
                    status=status.HTTP_403_FORBIDDEN)
            return config, None
    return None, Response({'error': 'کلیدِ کارگر درست نیست.',
                           'code': 'bad_key'},
                          status=status.HTTP_401_UNAUTHORIZED)


# ═══════════════════════════ سمتِ کارگرِ محلی ═══════════════════════════

@api_view(['POST', 'GET'])
@permission_classes([AllowAny])        # احراز با کلیدِ مشترک، نه کاربرِ جنگو
def claim(request):
    """کارگر می‌پرسد «کاری داری؟». ۲۰۴ یعنی فعلاً نه.

    گرفتنِ کار زیرِ تراکنش و با `select_for_update` است تا دو کارگر یک کار را
    برندارند — همان «دو بار هزینه نده».
    """
    config, denied = _config_for_request(request)
    if denied is not None:
        return denied

    worker = (request.data.get('worker') if request.method == 'POST' else None) or 'worker'
    config.mark_listener_seen(worker)

    now = timezone.now()

    # اجارهٔ سوخته آزاد می‌شود تا کار گم نشود
    AIJob.objects.filter(status=AIJob.STATUS_LEASED,
                         lease_until__lt=now).update(
        status=AIJob.STATUS_QUEUED, worker_name='')

    # «به‌روزرسانیِ شرطی» جای قفلِ ردیف: روی SQLite هم اتمیک است و قفلِ طولانی
    # نمی‌سازد. اگر دو کارگر هم‌زمان بپرسند، فقط یکی‌شان ۱ می‌گیرد.
    job = None
    for candidate in (AIJob.objects
                      .filter(status=AIJob.STATUS_QUEUED, provider_id=config.id)
                      .order_by('created_at')[:5]):
        taken = AIJob.objects.filter(
            pk=candidate.pk, status=AIJob.STATUS_QUEUED).update(
            status=AIJob.STATUS_LEASED,
            worker_name=str(worker)[:80],
            leased_at=now,
            lease_until=now + timezone.timedelta(seconds=LEASE_SECONDS),
            attempts=candidate.attempts + 1,
        )
        if taken:
            job = AIJob.objects.get(pk=candidate.pk)
            break

    if job is None:
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response({
        'job_id': job.id,
        'kind': job.kind,
        'messages': job.payload.get('messages', []),
        'max_tokens': job.payload.get('max_tokens'),
        'model_hint': config.model_name or '',
        'lease_seconds': LEASE_SECONDS,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def result(request, job_id):
    """کارگر جواب را می‌گذارد. کارِ منقضی‌شده **پذیرفته نمی‌شود**."""
    config, denied = _config_for_request(request)
    if denied is not None:
        return denied

    job = AIJob.objects.filter(pk=job_id, provider_id=config.id).first()
    if job is None:
        return Response({'error': 'کار پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)

    if job.status in (AIJob.STATUS_EXPIRED, AIJob.STATUS_DONE, AIJob.STATUS_FAILED):
        # جوابِ دیررس: سایت دیگر سراغِ ارائه‌دهندهٔ بعدی رفته است. دور می‌ریزیم
        # تا دو جواب برای یک درخواست حساب نشود (باگِ دومِ گزارشِ مالک).
        logger.info('جوابِ دیررسِ کارِ #%s (وضعیت %s) دور ریخته شد', job.id, job.status)
        return Response({'accepted': False, 'reason': 'مهلت تمام شده بود.'},
                        status=status.HTTP_409_CONFLICT)

    text = (request.data.get('text') or request.data.get('content') or '').strip()
    if not text:
        return Response({'error': 'متنِ جواب خالی است.'}, status=status.HTTP_400_BAD_REQUEST)

    job.result = text
    job.usage = request.data.get('usage') or {}
    job.status = AIJob.STATUS_DONE
    job.finished_at = timezone.now()
    job.save(update_fields=['result', 'usage', 'status', 'finished_at'])
    config.mark_listener_seen(job.worker_name)
    return Response({'accepted': True})


@api_view(['POST'])
@permission_classes([AllowAny])
def fail(request, job_id):
    """کارگر می‌گوید نتوانستم — سایت فوراً سراغِ ارائه‌دهندهٔ بعدی می‌رود."""
    config, denied = _config_for_request(request)
    if denied is not None:
        return denied
    job = AIJob.objects.filter(pk=job_id, provider_id=config.id).first()
    if job is None:
        return Response({'error': 'کار پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
    if job.status == AIJob.STATUS_LEASED:
        job.status = AIJob.STATUS_FAILED
        job.error = str(request.data.get('error') or '')[:500]
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error', 'finished_at'])
    return Response({'ok': True})


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def heartbeat(request):
    """کارگر فقط می‌گوید «من روشنم».

    سایت پیش از ساختنِ کار همین را می‌سنجد؛ اگر کارگر خواب باشد، اصلاً کار
    ساخته نمی‌شود و کاربر معطل نمی‌ماند (باگِ اولِ گزارشِ مالک).
    """
    config, denied = _config_for_request(request)
    if denied is not None:
        return denied
    worker = request.data.get('worker') if request.method == 'POST' else request.GET.get('worker')
    config.mark_listener_seen(worker or 'worker')
    pending = AIJob.objects.filter(provider_id=config.id,
                                   status=AIJob.STATUS_QUEUED).count()
    return Response({'ok': True, 'queued_jobs': pending,
                     'server_time': timezone.now().isoformat()})


# ═══════════════════════════ سمتِ سایت ═══════════════════════════

def run_via_listener(config, messages, max_tokens, kind='chat'):
    """یک درخواست را به شنونده می‌دهد و منتظرِ جواب می‌ماند — با مهلت.

    خروجی: (متنِ جواب، مصرفِ توکن) یا استثنا. استثنا یعنی «این ارائه‌دهنده
    نشد»، و زنجیرهٔ بالادست سراغِ بعدی می‌رود.
    """
    if not config.listener_is_online():
        raise RuntimeError('سرورِ شنونده روشن نیست (آخرین تماس: %s)'
                           % (config.listener_last_seen_at or 'هرگز'))

    deadline_seconds = max(10, config.timeout_seconds or 90)
    job = AIJob.objects.create(
        provider=config,
        kind=kind,
        payload={'messages': messages, 'max_tokens': max_tokens},
        status=AIJob.STATUS_QUEUED,
    )
    logger.info('کارِ شنونده #%s ساخته شد (مهلت %ss)', job.id, deadline_seconds)

    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        time.sleep(1.0)
        job.refresh_from_db(fields=['status', 'result', 'usage', 'error'])
        if job.status == AIJob.STATUS_DONE:
            return job.result, (job.usage or {})
        if job.status == AIJob.STATUS_FAILED:
            raise RuntimeError('کارگرِ محلی خطا داد: %s' % (job.error or '-'))

    # مهلت تمام شد: کار را می‌بندیم تا جوابِ دیررس دور ریخته شود
    AIJob.objects.filter(pk=job.pk).exclude(
        status__in=[AIJob.STATUS_DONE, AIJob.STATUS_FAILED]).update(
        status=AIJob.STATUS_EXPIRED, finished_at=timezone.now(),
        error='مهلتِ %ss تمام شد' % deadline_seconds)
    raise TimeoutError('سرورِ شنونده در %s ثانیه جواب نداد' % deadline_seconds)
