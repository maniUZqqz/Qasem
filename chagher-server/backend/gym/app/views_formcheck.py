# -*- coding: utf-8 -*-
"""مسیرهای «بررسیِ درستیِ حرکت با دوربین».

جریانِ کار:
    ۱) ورزشکار در صفحهٔ آموزشِ حرکت دکمه را می‌زند.
    ۲) `start/` یک دور می‌سازد (و اگر تنظیم شده باشد، توکن کم می‌کند).
    ۳) صفحه هر چند ثانیه یک فریم به `frame/` می‌فرستد و حکم را روی تصویر نشان می‌دهد.
    ۴) `finish/` خلاصه را برمی‌گرداند و هزینهٔ مدل را در دفتر ثبت می‌کند.

**کلیدِ خاموش/روشن:** اگر مدیر در جنگو ادمین «بررسیِ درستیِ حرکت فعال باشد» را
بردارد، همهٔ این مسیرها ۴۰۴ می‌دهند و دکمه‌اش هم در صفحه‌ها دیده نمی‌شود — یعنی
کاربر اصلاً نمی‌فهمد چنین چیزی وجود دارد.
"""
import logging
from decimal import Decimal

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import form_check as fc
from .models import (APIConfig, ExerciseLibrary, FormCheckFrame,
                     FormCheckSession, LedgerEntry, PlatformSettings)

logger = logging.getLogger(__name__)

# فاصلهٔ فرستادنِ فریم‌ها. کمتر از این، هم مدل عقب می‌افتد و هم بی‌فایده است
# چون یک تکرارِ حرکت چند ثانیه طول می‌کشد.
FRAME_INTERVAL_MS = 2500


def _settings_or_none():
    """تنظیمات را می‌دهد، یا None اگر قابلیت خاموش است."""
    settings_obj = PlatformSettings.get_solo()
    return settings_obj if settings_obj.form_check_enabled else None


def _flush_ledger(session):
    """هزینهٔ مدلِ یک دورِ تمام‌شده را یک‌بار در دفتر می‌نویسد."""
    if session.ledger_written or not session.ai_cost:
        return
    LedgerEntry.record(
        LedgerEntry.TYPE_AI_COST,
        user=session.user,
        amount=-session.ai_cost,
        reference='formcheck#%s' % session.pk,
        description='هزینهٔ مدلِ بررسیِ درستیِ حرکت (%s)' % (session.model_name or '-'),
    )
    session.ledger_written = True
    session.save(update_fields=['ledger_written'])


class FormCheckInfoView(APIView):
    """«این حرکت را می‌شود با دوربین بررسی کرد؟» + آموزشِ گام‌به‌گام."""
    permission_classes = [IsAuthenticated]

    def get(self, request, external_id):
        settings_obj = _settings_or_none()
        if settings_obj is None:
            return Response({'detail': 'یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)
        exercise = ExerciseLibrary.objects.filter(external_id=external_id, is_active=True).first()
        if exercise is None:
            return Response({'detail': 'حرکت پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'enabled': True,
            'exercise': {
                'external_id': exercise.external_id,
                'name_fa': exercise.name_fa,
                'equipment_fa': exercise.equipment_fa,
                'target_fa': exercise.target_fa,
                'gif': exercise.gif.url if exercise.gif else None,
                'steps_fa': exercise.steps_fa or [],
            },
            'token_cost': settings_obj.form_check_token_cost,
            'max_frames': settings_obj.form_check_max_frames,
            'frame_interval_ms': FRAME_INTERVAL_MS,
            'balance': request.user.get_effective_token_balance(),
            'cameras': [{'value': c, 'label': l} for c, l in FormCheckSession.CAMERA_CHOICES],
        })


class FormCheckStartView(APIView):
    """شروعِ یک دورِ بررسی."""
    permission_classes = [IsAuthenticated]

    def post(self, request, external_id):
        settings_obj = _settings_or_none()
        if settings_obj is None:
            return Response({'detail': 'یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)
        exercise = ExerciseLibrary.objects.filter(external_id=external_id, is_active=True).first()
        if exercise is None:
            return Response({'detail': 'حرکت پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)

        camera = (request.data.get('camera') or FormCheckSession.CAMERA_BACK).strip()
        if camera not in dict(FormCheckSession.CAMERA_CHOICES):
            camera = FormCheckSession.CAMERA_BACK

        # دورهای رهاشدهٔ قبلی را تسویه کن (کاربر صفحه را بسته بوده)
        for old in FormCheckSession.objects.filter(
                user=request.user, ledger_written=False).exclude(ai_cost=0)[:5]:
            _flush_ledger(old)

        cost = settings_obj.form_check_token_cost
        charged = 0
        if cost:
            if not request.user.deduct_tokens(cost):
                return Response({'error': 'توکنِ کافی برای بررسیِ حرکت ندارید.',
                                 'required_tokens': cost},
                                status=status.HTTP_402_PAYMENT_REQUIRED)
            charged = cost

        session = FormCheckSession.objects.create(
            user=request.user, exercise=exercise, camera=camera, tokens_charged=charged
        )
        if charged:
            LedgerEntry.record(
                LedgerEntry.TYPE_TOKEN_SPEND, user=request.user, tokens=-charged,
                reference='formcheck#%s' % session.pk,
                description='بررسیِ درستیِ حرکت (%s)' % (exercise.name_fa or exercise.name),
            )
        return Response({
            'session_id': session.pk,
            'max_frames': settings_obj.form_check_max_frames,
            'frame_interval_ms': FRAME_INTERVAL_MS,
            'charged_tokens': charged,
            'remaining_tokens': request.user.get_effective_token_balance(),
        }, status=status.HTTP_201_CREATED)


class FormCheckFrameView(APIView):
    """یک فریمِ دوربین → حکمِ سبز/قرمز + راهنماییِ زرد."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, session_id):
        settings_obj = _settings_or_none()
        if settings_obj is None:
            return Response({'detail': 'یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)
        session = FormCheckSession.objects.filter(pk=session_id, user=request.user).first()
        if session is None or session.exercise_id is None:
            return Response({'detail': 'دورِ بررسی پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)

        if session.frames_checked >= settings_obj.form_check_max_frames:
            return Response({
                'limit_reached': True,
                'message': 'سقفِ بررسیِ این دور پر شد؛ دوباره شروع کن.',
                'summary': _summary(session),
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        upload = request.FILES.get('frame') or request.FILES.get('photo')
        if upload is None:
            return Response({'error': 'فریمی نفرستادی (کلیدِ frame).'},
                            status=status.HTTP_400_BAD_REQUEST)
        blob = upload.read()

        try:
            result = fc.check_frame(session.exercise, blob)
        except Exception as exc:
            logger.exception('بررسیِ فریم شکست خورد (دور #%s)', session.pk)
            return Response({'error': 'تشخیص ممکن نشد؛ چند لحظه بعد دوباره.',
                             'detail': str(exc)},
                            status=status.HTTP_502_BAD_GATEWAY)

        frame = FormCheckFrame(
            session=session,
            verdict=result['verdict'],
            message=result['message'],
            confidence=result['confidence'],
            raw_answer=result['raw'][:4000],
        )
        if settings_obj.form_check_store_frames:
            upload.seek(0)
            frame.image = upload
        frame.save()

        session.frames_checked += 1
        if result['verdict'] == 'ok':
            session.ok_count += 1
        elif result['verdict'] == 'bad':
            session.bad_count += 1
        session.model_name = result['model_name'] or session.model_name
        try:
            cost = APIConfig.estimate_cost(result['usage'][0], result['usage'][1],
                                           result['config']) or Decimal('0')
        except Exception:
            cost = Decimal('0')
        session.ai_cost = (session.ai_cost or Decimal('0')) + cost
        session.save(update_fields=['frames_checked', 'ok_count', 'bad_count',
                                    'model_name', 'ai_cost', 'updated_at'])

        return Response({
            'verdict': result['verdict'],
            # رنگ‌ها عمداً از سرور می‌آیند تا اپِ فلاتر و صفحهٔ وب یک رفتار داشته باشند
            'color': {'ok': 'green', 'bad': 'red', 'unsure': 'none'}[result['verdict']],
            'message': result['message'],
            'confidence': round(result['confidence'], 2),
            'box': result['box'],
            'frames_checked': session.frames_checked,
            'frames_left': max(0, settings_obj.form_check_max_frames - session.frames_checked),
        })


def _summary(session):
    total = session.frames_checked or 1
    return {
        'session_id': session.pk,
        'exercise': session.exercise.name_fa if session.exercise else None,
        'frames_checked': session.frames_checked,
        'ok_count': session.ok_count,
        'bad_count': session.bad_count,
        'ok_percent': round(100.0 * session.ok_count / total),
        'tokens_charged': session.tokens_charged,
    }


class FormCheckFinishView(APIView):
    """پایانِ دور: خلاصه + ثبتِ هزینهٔ مدل در دفتر."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = FormCheckSession.objects.filter(pk=session_id, user=request.user).first()
        if session is None:
            return Response({'detail': 'دورِ بررسی پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        _flush_ledger(session)
        data = _summary(session)
        data['note'] = ('این تشخیص از روی تصویر است و جای چشمِ مربی را نمی‌گیرد؛ '
                        'اگر جایی درد گرفت، حرکت را قطع کن.')
        return Response(data)
