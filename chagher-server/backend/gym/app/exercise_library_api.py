# -*- coding: utf-8 -*-
"""APIهای کتابخانهٔ حرکت‌ها.

ورودِ داده (فقط مدیر، با توکن):
    POST /api/exercise-library/import/            بسته‌ای از حرکت‌ها (JSON)
    POST /api/exercise-library/<ext_id>/media/    آپلودِ گیف و عکس (multipart)
    GET  /api/exercise-library/status/            چه چیزی قبلاً رفته (برای ادامهٔ آپلود)
خواندن برای اپ (کاربرِ واردشده):
    GET  /api/exercise-library/?search=&equipment=&body_part=&page=
"""
from django.db.models import Q
from django.utils import timezone

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from .models import ExerciseLibrary


class ExerciseLibrarySerializer(serializers.ModelSerializer):
    gif_url = serializers.SerializerMethodField()
    thumb_url = serializers.SerializerMethodField()

    class Meta:
        model = ExerciseLibrary
        fields = [
            'id', 'external_id', 'name', 'name_fa', 'category', 'category_fa',
            'body_part', 'body_part_fa', 'equipment', 'equipment_fa',
            'target', 'target_fa', 'muscle_group', 'muscle_group_fa',
            'secondary_muscles', 'secondary_muscles_fa',
            'instructions_en', 'instructions_fa', 'steps_en', 'steps_fa',
            'gif_url', 'thumb_url', 'source', 'brand', 'attribution', 'is_active',
        ]

    def _abs(self, f):
        if not f:
            return None
        request = self.context.get('request')
        try:
            url = f.url
        except Exception:
            return None
        return request.build_absolute_uri(url) if request else url

    def get_gif_url(self, obj):
        return self._abs(obj.gif)

    def get_thumb_url(self, obj):
        return self._abs(obj.thumb)


IMPORT_FIELDS = [
    'name', 'name_fa', 'category', 'category_fa', 'body_part', 'body_part_fa',
    'equipment', 'equipment_fa', 'target', 'target_fa', 'muscle_group', 'muscle_group_fa',
    'secondary_muscles', 'secondary_muscles_fa', 'instructions_en', 'instructions_fa',
    'steps_en', 'steps_fa', 'source', 'brand', 'attribution',
]


@api_view(['POST'])
@permission_classes([IsAdminUser])
def import_exercises(request):
    """بسته‌ای از حرکت‌ها را بر اساس external_id می‌سازد یا به‌روز می‌کند (idempotent)."""
    payload = request.data
    items = payload.get('exercises') if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return Response({'detail': 'بدنه باید آرایه‌ای از حرکت‌ها باشد.'},
                        status=status.HTTP_400_BAD_REQUEST)

    created = updated = 0
    errors = []
    for it in items:
        ext = str(it.get('external_id') or it.get('id') or '').strip()
        if not ext:
            errors.append('رکورد بدون شناسه رد شد')
            continue
        data = {k: it.get(k) for k in IMPORT_FIELDS if it.get(k) is not None}
        try:
            _, is_new = ExerciseLibrary.objects.update_or_create(external_id=ext, defaults=data)
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
        except Exception as e:
            errors.append('%s: %s' % (ext, e))

    return Response({'created': created, 'updated': updated, 'errors': errors})


@api_view(['POST'])
@permission_classes([IsAdminUser])
@parser_classes([MultiPartParser, FormParser])
def upload_media(request, external_id):
    """آپلودِ گیف و عکسِ یک حرکت (فیلدهای فرم: gif, thumb)."""
    try:
        obj = ExerciseLibrary.objects.get(external_id=external_id)
    except ExerciseLibrary.DoesNotExist:
        return Response({'detail': 'حرکت پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)

    saved = []
    if 'gif' in request.FILES:
        obj.gif.save('%s.gif' % external_id, request.FILES['gif'], save=False)
        saved.append('gif')
    if 'thumb' in request.FILES:
        obj.thumb.save('%s.jpg' % external_id, request.FILES['thumb'], save=False)
        saved.append('thumb')
    if not saved:
        return Response({'detail': 'فایلی فرستاده نشد.'}, status=status.HTTP_400_BAD_REQUEST)
    obj.updated_at = timezone.now()
    obj.save()
    return Response({'external_id': external_id, 'saved': saved})


@api_view(['GET'])
@permission_classes([IsAdminUser])
def import_status(request):
    """چه حرکت‌هایی هستند و کدام‌ها گیف دارند — تا آپلود از همان‌جا ادامه بگیرد."""
    qs = ExerciseLibrary.objects.all()
    with_gif = [e for e in qs.exclude(gif='').exclude(gif__isnull=True)
                .values_list('external_id', flat=True)]
    return Response({
        'total': qs.count(),
        'with_gif': len(with_gif),
        'ids': sorted(qs.values_list('external_id', flat=True)),
        'ids_with_gif': sorted(with_gif),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_exercises(request):
    """فهرستِ حرکت‌ها برای اپ — جست‌وجو، فیلتر، صفحه‌بندی."""
    # کتابخانهٔ سراسری + حرکت‌های خودِ همین کاربر (مورد ۵ گزارشِ مالک).
    # حرکتِ یک مربی نباید در کتابخانهٔ مربیِ دیگر دیده شود.
    qs = ExerciseLibrary.objects.filter(is_active=True)
    if request.user.is_authenticated:
        qs = qs.filter(Q(owner__isnull=True) | Q(owner=request.user))
    else:
        qs = qs.filter(owner__isnull=True)
    search = (request.GET.get('search') or '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(name_fa__icontains=search) |
                       Q(equipment_fa__icontains=search) | Q(target_fa__icontains=search))
    for field in ('equipment', 'body_part', 'category', 'target'):
        val = (request.GET.get(field) or '').strip()
        if val:
            qs = qs.filter(**{'%s__iexact' % field: val})

    try:
        page = max(1, int(request.GET.get('page', 1)))
        size = min(200, max(1, int(request.GET.get('page_size', 50))))
    except ValueError:
        page, size = 1, 50

    total = qs.count()
    rows = qs[(page - 1) * size: page * size]
    ser = ExerciseLibrarySerializer(rows, many=True, context={'request': request})
    return Response({'count': total, 'page': page, 'page_size': size, 'results': ser.data})
