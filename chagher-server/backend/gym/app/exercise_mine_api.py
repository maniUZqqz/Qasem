# -*- coding: utf-8 -*-
"""حرکت‌های خودِ مربی — افزودن، ویرایش و حذف.

گزارشِ مالک: «حرکت را که اصلاً خودِ مربی نمی‌تواند اضافه کند.»

قاعده‌ها:
  · حرکتِ مربی **مالک دارد** و فقط در کتابخانهٔ خودش دیده می‌شود؛ کتابخانهٔ
    سراسریِ ۱۳۲۴تایی دست‌نخورده می‌ماند.
  · اگر نامش با یک حرکتِ سراسری یکی باشد، هشدار می‌دهیم ولی جلویش را
    نمی‌گیریم — ممکن است مربی عمداً نسخهٔ خودش را بخواهد.
  · گیف و عکس اختیاری است؛ بی‌آن‌ها هم حرکت در برنامه و PDF کار می‌کند.
  · مدیر می‌تواند از جنگو ادمین حرکتِ خوبِ یک مربی را «سراسری» کند.
"""
import logging
import re

from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .exercise_library_api import ExerciseLibrarySerializer
from .models import ExerciseLibrary
from .permissions import IsCoachOrPersonal

logger = logging.getLogger(__name__)

EDITABLE = [
    'name_fa', 'name', 'equipment_fa', 'target_fa', 'body_part_fa',
    'muscle_group_fa', 'category_fa', 'instructions_fa',
]


def _norm(text):
    s = (text or '').strip().lower().replace('‌', ' ')
    s = re.sub(r'[^0-9a-z؀-ۿ ]', ' ', s)
    return ' '.join(sorted(set(s.split())))


def _next_external_id(user):
    """شناسهٔ یکتا برای حرکت‌های همین کاربر: u<id>-<شماره>."""
    prefix = 'u%s-' % user.pk
    taken = set(ExerciseLibrary.objects
                .filter(external_id__startswith=prefix)
                .values_list('external_id', flat=True))
    index = len(taken) + 1
    while '%s%d' % (prefix, index) in taken:
        index += 1
    return '%s%d' % (prefix, index)


def _steps_list(value):
    """مراحل را از فهرست یا متنِ چندخطی می‌پذیرد."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


@api_view(['GET', 'POST'])
@permission_classes([IsCoachOrPersonal])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def my_exercises(request):
    """GET: حرکت‌های خودم · POST: افزودنِ حرکتِ تازه."""
    if request.method == 'GET':
        rows = ExerciseLibrary.objects.filter(owner=request.user).order_by('-id')
        return Response({
            'count': rows.count(),
            'results': ExerciseLibrarySerializer(rows, many=True,
                                                 context={'request': request}).data,
        })

    data = request.data
    name_fa = (data.get('name_fa') or data.get('name') or '').strip()
    if not name_fa:
        return Response({'error': 'نامِ حرکت را بنویسید.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(name_fa) > 200:
        return Response({'error': 'نامِ حرکت بیش از اندازه بلند است.'},
                        status=status.HTTP_400_BAD_REQUEST)

    # هم‌نامِ سراسری؟ فقط خبر می‌دهیم، جلویش را نمی‌گیریم
    key = _norm(name_fa)
    similar = None
    for row in ExerciseLibrary.objects.filter(owner__isnull=True, is_active=True) \
            .only('external_id', 'name_fa'):
        if _norm(row.name_fa) == key:
            similar = {'external_id': row.external_id, 'name_fa': row.name_fa}
            break

    exercise = ExerciseLibrary(
        external_id=_next_external_id(request.user),
        owner=request.user,
        is_public=False,
        is_active=True,
        name_fa=name_fa,
        name=(data.get('name') or name_fa)[:200],
        source='coach',
        brand='چغر',
    )
    for field in EDITABLE:
        value = data.get(field)
        if value not in (None, '') and field not in ('name_fa', 'name'):
            setattr(exercise, field, str(value)[:200] if field != 'instructions_fa'
                    else str(value))
    exercise.steps_fa = _steps_list(data.get('steps_fa'))
    if 'gif' in request.FILES:
        exercise.gif = request.FILES['gif']
    if 'thumb' in request.FILES:
        exercise.thumb = request.FILES['thumb']
    exercise.save()
    logger.info('حرکتِ تازهٔ مربی %s: %s', request.user.phone_number, exercise.external_id)

    return Response({
        'exercise': ExerciseLibrarySerializer(exercise, context={'request': request}).data,
        'similar_global': similar,
        'message': ('حرکت اضافه شد. توجه: حرکتی با همین نام در کتابخانهٔ سراسری هم هست.'
                    if similar else 'حرکت اضافه شد و در برنامه‌هایت قابلِ انتخاب است.'),
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsCoachOrPersonal])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def my_exercise_detail(request, external_id):
    """خواندن، ویرایش یا حذفِ حرکتِ خودم (حرکتِ سراسری دست‌نخورده می‌ماند)."""
    exercise = ExerciseLibrary.objects.filter(
        external_id=external_id, owner=request.user).first()
    if exercise is None:
        return Response({'error': 'این حرکت مالِ شما نیست یا وجود ندارد.'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(ExerciseLibrarySerializer(
            exercise, context={'request': request}).data)

    if request.method == 'DELETE':
        exercise.delete()
        return Response({'message': 'حرکت حذف شد.'})

    data = request.data
    for field in EDITABLE:
        if field in data:
            value = data.get(field)
            setattr(exercise, field, str(value) if value is not None else '')
    if 'steps_fa' in data:
        exercise.steps_fa = _steps_list(data.get('steps_fa'))
    if 'gif' in request.FILES:
        exercise.gif = request.FILES['gif']
    if 'thumb' in request.FILES:
        exercise.thumb = request.FILES['thumb']
    exercise.save()
    return Response({
        'exercise': ExerciseLibrarySerializer(exercise, context={'request': request}).data,
        'message': 'ویرایش ذخیره شد.',
    })
