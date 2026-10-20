# -*- coding: utf-8 -*-
"""برنامهٔ دستیِ مربی — ساخت، ویرایش و وضعیتِ سهمِ رایگان.

چرا جدا از views.py نوشته شد: آن‌جا همه‌چیز حولِ هوش مصنوعی است (هزینهٔ مدل،
لاگِ مصرف، بازگشتِ توکن پس از خطای مدل). این‌جا هیچ مدلی اجرا نمی‌شود؛ قاعده
فقط این است: چند برنامهٔ اولِ هر ورزشکار رایگان است و بعد از آن توکن کم می‌شود.
هر دو عدد از تنظیماتِ جنگو ادمین خوانده می‌شوند.

مسیرها:
    GET  api/programs/manual/quota/     سهمِ رایگانِ این ورزشکار و هزینهٔ بعدی
    POST api/programs/manual/           ساختِ برنامه
    GET  api/programs/manual/<id>/      ساختارِ برنامه برای ویرایش
    PATCH api/programs/manual/<id>/     ویرایش (رایگان — نوشتهٔ خودِ مربی است)
"""
import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import manual_program as mp
from .models import ClientProgram, ExerciseLibrary, GymClient, LedgerEntry
from .serializers import ClientProgramSerializer

logger = logging.getLogger(__name__)

# فیلدهای اختیاریِ مشخصاتِ ورزشکار که مربی می‌تواند با برنامه بفرستد
_PROFILE_FIELDS = [
    'age', 'gender', 'height', 'weight', 'injuries', 'food_allergies',
    'body_issues', 'chronic_diseases', 'extra_notes', 'exercise_history',
    'training_place',
]


def _resolve_athlete(user, src):
    """(ورزشکارِ باشگاه یا None، نام) — خطا را به‌صورت ValueError برمی‌گرداند."""
    gc_id = src.get('gym_client')
    gym_client = None
    if gc_id:
        gym_client = GymClient.objects.filter(pk=gc_id, gym_owner=user).first()
        if gym_client is None:
            raise ValueError('این ورزشکار در باشگاهِ شما ثبت نشده است.')
    name = mp.norm_name(src.get('name'))
    if not name and gym_client is not None:
        name = mp.norm_name(gym_client.name) or 'ورزشکار'
    if not name:
        raise ValueError('نامِ ورزشکار را بنویسید.')
    return gym_client, name


def _profile_payload(src):
    """فیلدهای مشخصات را برمی‌دارد و اعتبارِ گزینه‌ای‌ها را چک می‌کند."""
    out = {}
    for f in _PROFILE_FIELDS:
        if f in src and src.get(f) not in (None, ''):
            out[f] = src.get(f)
    gender = out.get('gender')
    if gender and gender not in dict(ClientProgram.GENDER_CHOICES):
        raise ValueError('جنسیت باید M یا F باشد.')
    place = out.get('training_place')
    if place and place not in dict(ClientProgram.TRAINING_PLACE_CHOICES):
        raise ValueError('محیطِ تمرین درست نیست.')
    for f in ('age',):
        if f in out:
            try:
                out[f] = int(out[f])
            except (TypeError, ValueError):
                raise ValueError('سن باید عدد باشد.')
    for f in ('height', 'weight'):
        if f in out:
            try:
                out[f] = float(out[f])
            except (TypeError, ValueError):
                raise ValueError('قد و وزن باید عدد باشند.')
    return out


def _program_type(plan):
    """نوعِ برنامه از روی چیزی که مربی واقعاً نوشته است.

    برنامه می‌تواند فقط تمرینی، فقط غذایی، یا هر دو باشد — پیش از این همیشه
    «ورزشی» ثبت می‌شد و بخشِ غذایی در PDF گم می‌شد.
    """
    has_workout = bool(plan.get('days'))
    has_meal = bool(mp.render_meal_text(plan))
    if has_workout and has_meal:
        return 'both'
    return 'meal' if has_meal else 'workout'


def _library_names():
    return dict(
        ExerciseLibrary.objects.filter(is_active=True).values_list('external_id', 'name_fa')
    )


def _note_manual_unmatched(plan):
    """حرکت‌های دست‌نوشتهٔ بی‌تطبیق را برای تصمیمِ ادمین ثبت می‌کند.

    عمداً بی‌صداست: اگر ثبت نشد، ساختِ برنامه نباید بشکند.
    """
    try:
        from .exercise_match import find_exercise, note_unmatched
    except Exception:
        return
    for day in plan.get('days') or []:
        for ex in day.get('exercises') or []:
            if ex.get('exercise_id'):
                continue            # از کتابخانه انتخاب شده
            nm = (ex.get('name') or '').strip()
            if not nm:
                continue
            try:
                if find_exercise(nm) is None:
                    note_unmatched(nm, nm, source='manual')
            except Exception:
                pass


def _apply_rule_to_quota(user, quota, gym_client, name):
    """اگر قاعدهٔ قیمت هست، عددی که به پنل نشان می‌دهیم همان قاعده باشد."""
    try:
        from .pricing import resolve as _r, free_runs_left, F_MANUAL
    except Exception:
        return quota
    key = gym_client.id if gym_client else name
    d = _r(user, F_MANUAL, key)
    if d is None:
        # قاعده‌ای نیست ⇒ حالتی که مالک در تنظیمات انتخاب کرده
        from .models import PlatformSettings as _PS
        st = _PS.get_solo()
        if st.manual_billing_mode == _PS.MANUAL_BILL_FREE:
            return dict(quota, access='always_free', next_cost=0, next_is_free=True)
        if st.manual_billing_mode == _PS.MANUAL_BILL_TOKENS:
            return dict(quota, access='tokens')
        return quota
    left = free_runs_left(user, F_MANUAL, key)
    return dict(quota,
                source='rule', rule=d.rule.title, access='rule',
                next_cost=d.cost, next_is_free=(d.mode == 'free'),
                blocked=(d.mode == 'blocked'),
                blocked_message=d.rule.blocked_message or '',
                free_remaining=(left if left is not None else quota.get('free_remaining')))


class ManualProgramQuotaView(APIView):
    """«برای این ورزشکار چند برنامهٔ رایگان مانده و بعدی چند توکن است؟»"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            gym_client, name = _resolve_athlete(request.user, request.query_params)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        q = mp.quota_state(request.user, gym_client, name)
        return Response(_apply_rule_to_quota(request.user, q, gym_client, name))


class ManualProgramView(APIView):
    """ساختِ برنامهٔ دستی (بدونِ هوش مصنوعی)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        try:
            gym_client, name = _resolve_athlete(request.user, data)
            profile = _profile_payload(data)
            plan = mp.clean_plan(data, library_names=_library_names())
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # نامِ حرکتی که مربی دستی نوشته و در کتابخانه نیست، همان‌جا در
        # «نام‌های بی‌تطبیق» ثبت می‌شود. پیش از این فقط مسیرِ ساختِ PDF ثبت
        # می‌کرد، یعنی عملاً فقط برنامه‌های هوش مصنوعی دیده می‌شدند.
        _note_manual_unmatched(plan)

        quota = mp.quota_state(request.user, gym_client, name)
        cost = quota['next_cost']

        # قاعده‌های قیمتِ ادمین، اگر نوشته شده باشند، بر همه‌چیز مقدم‌اند.
        from .pricing import resolve as _price, F_MANUAL
        _athlete_key = gym_client.id if gym_client else name
        _d = _price(request.user, F_MANUAL, _athlete_key)
        if _d is not None:
            if _d.mode == 'blocked':
                return Response({
                    'error': _d.rule.blocked_message or 'برنامهٔ دستی الان در دسترس نیست.',
                    'rule': _d.rule.title,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)
            cost, allowed, reason, days_left = _d.cost, True, 'rule', 0
            quota = dict(quota, access='rule', rule=_d.rule.title,
                         next_cost=cost, next_is_free=cost == 0)
        else:
            allowed = None

        # حالتِ محاسبه را مالک در «تنظیمات سامانه» انتخاب می‌کند:
        #   · «با توکن»      ⇒ تا سهمِ رایگان مجانی، بعدش توکن. دورهٔ آزمایشی
        #                      و اشتراک دخالت نمی‌کنند. (چیزی که مالک می‌خواست)
        #   · «همیشه رایگان» ⇒ هیچ‌وقت توکن کم نمی‌شود.
        #   · «آزمایشی…»     ⇒ رفتارِ قبلی.
        # قاعده‌های قیمت، اگر نوشته شده باشند، بر همهٔ این‌ها مقدم‌اند.
        from .models import PlatformSettings as _PS
        _mode = _PS.get_solo().manual_billing_mode
        if allowed is None and _mode == _PS.MANUAL_BILL_TOKENS:
            # cost همان quota['next_cost'] است: ۰ تا پایانِ سهم، بعدش نرخِ ادمین
            allowed, reason, days_left = (cost == 0), 'tokens', 0
            quota = dict(quota, access='tokens', next_cost=cost,
                         next_is_free=cost == 0)
            _d = _d or False          # تا شاخهٔ «اشتراک لازم است» اجرا نشود
        elif allowed is None and _mode == _PS.MANUAL_BILL_FREE:
            cost, allowed, reason, days_left = 0, True, 'always_free', 0
            quota = dict(quota, access='always_free', next_cost=0, next_is_free=True)
            _d = _d or False

        if allowed is None:
            allowed, reason, days_left = request.user.manual_plan_status()
        if _d:
            pass            # حکمِ قاعده قطعی است؛ دورهٔ آزمایشی دیگر دخالت نمی‌کند
        elif _d is False:
            pass            # حالتِ انتخابیِ مالک؛ cost همان است که بالا حساب شد
        elif allowed:
            cost = 0
            quota = dict(quota, access=reason, days_left=days_left,
                         next_cost=0, next_is_free=True)
        elif not cost:
            from .models import PlatformSettings
            price = PlatformSettings.get_solo().manual_plan_annual_price
            return Response({
                'error': 'دورهٔ رایگانِ برنامهٔ دستی تمام شده است.',
                'need_subscription': True,
                'annual_price': int(price),
                'message': 'برای ادامه، اشتراکِ سالانهٔ برنامهٔ دستی (%s تومان) '
                           'را فعال کنید.' % '{:,}'.format(int(price)),
            }, status=status.HTTP_402_PAYMENT_REQUIRED)

        # کسرِ توکن قبل از ساختِ رکورد انجام می‌شود تا دو درخواستِ همزمان نتوانند
        # با یک موجودی دو برنامه بسازند؛ اگر ساخت شکست خورد، توکن برمی‌گردد.
        charged = 0
        if cost:
            if not request.user.deduct_tokens(cost):
                return Response({
                    'error': 'سهمِ رایگانِ این ورزشکار تمام شده و توکنِ کافی ندارید.',
                    'required_tokens': cost,
                    'quota': quota,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)
            charged = cost

        try:
            with transaction.atomic():
                program = ClientProgram.objects.create(
                    user=request.user,
                    gym_client=gym_client,
                    name=name,
                    source=ClientProgram.SOURCE_MANUAL,
                    program_type=_program_type(plan),
                    program_days=len(plan['days']),
                    generated_workout=mp.render_workout_text(plan),
                    generated_meal_plan=mp.render_meal_text(plan),
                    manual_plan=plan,
                    tokens_consumed=charged,
                    **profile
                )
        except Exception:
            logger.exception('ساختِ برنامهٔ دستی شکست خورد (کاربر %s)', request.user.phone_number)
            if charged:
                request.user.add_tokens(charged)
                LedgerEntry.record(
                    LedgerEntry.TYPE_TOKEN_REFUND,
                    user=request.user,
                    tokens=charged,
                    description='بازگشت توکن پس از خطای ساختِ برنامهٔ دستی',
                )
            return Response(
                {'error': 'ذخیرهٔ برنامه ناموفق بود؛ توکنی کم نشد. دوباره تلاش کنید.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if charged:
            LedgerEntry.record(
                LedgerEntry.TYPE_TOKEN_SPEND,
                user=request.user,
                tokens=-charged,
                reference='program#%s' % program.id,
                description='برنامهٔ دستیِ مربی (%s)' % name,
            )

        logger.info(
            'برنامهٔ دستی #%s برای %s ساخته شد (%s توکن)',
            program.id, name, charged,
        )
        return Response({
            'program': ClientProgramSerializer(program).data,
            'manual_plan': program.manual_plan,
            'charged_tokens': charged,
            'was_free': charged == 0,
            'remaining_tokens': request.user.get_effective_token_balance(),
            'quota': dict(mp.quota_state(request.user, gym_client, name),
                          access=reason, days_left=days_left),
        }, status=status.HTTP_201_CREATED)


class ManualProgramDetailView(APIView):
    """خواندن و ویرایشِ برنامهٔ دستی. ویرایش رایگان است."""
    permission_classes = [IsAuthenticated]

    def _get(self, request, program_id):
        return ClientProgram.objects.filter(
            pk=program_id, user=request.user, source=ClientProgram.SOURCE_MANUAL
        ).first()

    def get(self, request, program_id):
        program = self._get(request, program_id)
        if program is None:
            return Response({'error': 'برنامهٔ دستی پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'program': ClientProgramSerializer(program).data,
            'manual_plan': program.manual_plan,
        })

    def patch(self, request, program_id):
        program = self._get(request, program_id)
        if program is None:
            return Response({'error': 'برنامهٔ دستی پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        stored = program.manual_plan or {}
        payload = dict(data)
        if 'days' not in payload:
            # ویرایشِ جزئی: جلسه‌های قبلی سرِ جایشان می‌مانند
            payload['days'] = stored.get('days')
        if 'notes' not in payload:
            payload['notes'] = stored.get('notes')
        if 'meal_text' not in payload:
            payload['meal_text'] = stored.get('meal_text')

        try:
            profile = _profile_payload(data)
            plan = mp.clean_plan(payload, library_names=_library_names())
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        new_name = mp.norm_name(data.get('name'))
        if new_name:
            program.name = new_name
        for field, value in profile.items():
            setattr(program, field, value)
        program.manual_plan = plan
        program.program_days = len(plan['days'])
        program.program_type = _program_type(plan)
        program.generated_workout = mp.render_workout_text(plan)
        program.generated_meal_plan = mp.render_meal_text(plan)
        program.save()

        return Response({
            'program': ClientProgramSerializer(program).data,
            'manual_plan': program.manual_plan,
            'charged_tokens': 0,
            'message': 'ویرایش ذخیره شد (رایگان — چیزی از توکن کم نشد).',
        })
