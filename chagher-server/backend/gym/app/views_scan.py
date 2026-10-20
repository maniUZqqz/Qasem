# -*- coding: utf-8 -*-
"""اسکنِ دستگاه‌های باشگاه با دوربین.

جریانِ کار (همان چیزی که کاربر خواسته است):
    ۱) کاربر دکمهٔ اسکن را می‌زند و در باشگاه می‌چرخد و چند عکس می‌گیرد.
    ۲) عکس‌ها با هم به این مسیر فرستاده می‌شوند و سامانه دستگاه‌ها را تشخیص می‌دهد.
    ۳) فهرستِ تشخیص‌ها برمی‌گردد — **هیچ چیز ثبت نشده است**.
    ۴) کاربر تأیید می‌کند و فقط آن وقت دستگاه‌ها به باشگاهش اضافه می‌شوند.

مسیرها:
    GET  api/equipment-scan/candidates/   فهرستِ نام‌های شناخته‌شده و تنظیم‌ها
    POST api/equipment-scan/              فرستادنِ عکس‌ها و گرفتنِ تشخیص
    GET  api/equipment-scan/              اسکن‌های اخیرِ خودم
    GET  api/equipment-scan/<id>/         نتیجهٔ یک اسکن
    POST api/equipment-scan/<id>/confirm/ تأیید/ردِ تشخیص‌ها → ساختِ دستگاه
"""
import logging

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import equipment_scan as es
from .models import (EquipmentScan, EquipmentScanPhoto, LedgerEntry,
                     PlatformSettings)

logger = logging.getLogger(__name__)


def _item_payload(item):
    return {
        'id': item.pk,
        'name': item.name,
        'muscle_group': item.muscle_group,
        'confidence': round(item.confidence, 2),
        'in_library': item.in_library,
        'already_exists': item.already_exists,
        'is_confirmed': item.is_confirmed,
        'is_rejected': item.is_rejected,
        'equipment_id': item.equipment_id,
        'photo_id': item.photo_id,
        'catalog_id': item.catalog_id,
        # عکسِ واضحِ همان دستگاه از کاتالوگ — کاربر ببیند سامانه چه فهمیده است
        'catalog_image': (item.catalog.display_image_url()
                          if item.catalog_id and item.catalog else None),
    }


def _scan_payload(scan, request=None):
    photos = []
    for photo in scan.photos.all():
        url = photo.image.url if photo.image else None
        if url and request is not None:
            url = request.build_absolute_uri(url)
        photos.append({'id': photo.pk, 'url': url})
    return {
        'id': scan.pk,
        'status': scan.status,
        'status_label': scan.get_status_display(),
        'gym_name': scan.gym_name,
        'model_name': scan.model_name,
        'tokens_charged': scan.tokens_charged,
        'error': scan.error,
        'created_at': scan.created_at,
        'confirmed_at': scan.confirmed_at,
        'photos': photos,
        'items': [_item_payload(i) for i in scan.items.all()],
    }


class EquipmentScanCandidatesView(APIView):
    """نام‌هایی که سامانه می‌شناسد — برای افزودنِ دستی و یکدست‌ماندنِ نام‌ها."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        names, _ = es.candidate_names(request.user)
        settings_obj = PlatformSettings.get_solo()
        return Response({
            'equipment': names,
            'muscle_groups': es.MUSCLE_GROUPS,
            'max_photos': settings_obj.equipment_scan_max_photos,
            'token_cost': settings_obj.equipment_scan_token_cost,
            'balance': request.user.get_effective_token_balance(),
        })


class EquipmentScanView(APIView):
    """فرستادنِ عکس‌های اسکن و گرفتنِ فهرستِ تشخیص (بدونِ ثبت)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        scans = EquipmentScan.objects.filter(user=request.user)[:20]
        return Response({'count': len(scans),
                         'scans': [_scan_payload(s, request) for s in scans]})

    def post(self, request):
        files = request.FILES.getlist('photos') or request.FILES.getlist('photo')
        if not files:
            return Response({'error': 'حداقل یک عکس بفرستید (کلیدِ photos).'},
                            status=status.HTTP_400_BAD_REQUEST)

        settings_obj = PlatformSettings.get_solo()
        if len(files) > settings_obj.equipment_scan_max_photos:
            return Response({
                'error': 'در هر اسکن حداکثر %d عکس می‌شود فرستاد.'
                         % settings_obj.equipment_scan_max_photos,
            }, status=status.HTTP_400_BAD_REQUEST)

        cost = settings_obj.equipment_scan_token_cost
        charged = 0
        if cost:
            if not request.user.deduct_tokens(cost):
                return Response({'error': 'توکنِ کافی برای اسکن ندارید.',
                                 'required_tokens': cost},
                                status=status.HTTP_402_PAYMENT_REQUIRED)
            charged = cost

        scan = EquipmentScan.objects.create(
            user=request.user,
            gym_name=(request.data.get('gym_name') or '').strip() or None,
            tokens_charged=charged,
        )

        photo_files = []
        for f in files:
            blob = f.read()
            f.seek(0)
            photo = EquipmentScanPhoto.objects.create(scan=scan, image=f)
            photo_files.append((photo, blob))

        try:
            count, ai_cost, errors = es.run_scan(scan, photo_files)
        except Exception as exc:
            logger.exception('اسکنِ #%s شکست خورد', scan.pk)
            scan.status = EquipmentScan.STATUS_FAILED
            scan.error = str(exc)
            scan.save(update_fields=['status', 'error'])
            if charged:
                request.user.add_tokens(charged)
                scan.tokens_charged = 0
                scan.save(update_fields=['tokens_charged'])
            return Response({'error': 'تشخیصِ عکس‌ها ناموفق بود؛ توکنی کم نشد.',
                             'detail': str(exc), 'scan': _scan_payload(scan, request)},
                            status=status.HTTP_502_BAD_GATEWAY)

        if count == 0 and errors:
            # هیچ تشخیصی نشد و خطا هم داشتیم: پولِ کاری که انجام نشد برمی‌گردد
            scan.status = EquipmentScan.STATUS_FAILED
            if charged:
                request.user.add_tokens(charged)
                LedgerEntry.record(
                    LedgerEntry.TYPE_TOKEN_REFUND, user=request.user, tokens=charged,
                    reference='scan#%s' % scan.pk,
                    description='بازگشت توکن — اسکنِ دستگاه ناموفق',
                )
                scan.tokens_charged = 0
                charged = 0
        else:
            scan.status = EquipmentScan.STATUS_DONE
        scan.save()

        if charged:
            LedgerEntry.record(
                LedgerEntry.TYPE_TOKEN_SPEND, user=request.user, tokens=-charged,
                reference='scan#%s' % scan.pk, description='اسکنِ دستگاه‌های باشگاه',
            )
        if ai_cost:
            LedgerEntry.record(
                LedgerEntry.TYPE_AI_COST, user=request.user, amount=-ai_cost,
                reference='scan#%s' % scan.pk,
                description='هزینهٔ مدلِ بینایی (%s)' % (scan.model_name or '-'),
            )

        return Response({
            'scan': _scan_payload(scan, request),
            'detected': count,
            'message': ('%d وسیله تشخیص داده شد. تأیید کنید تا به باشگاه اضافه شوند.' % count)
                       if count else 'هیچ وسیله‌ای تشخیص داده نشد؛ عکسِ نزدیک‌تر بگیرید.',
            'charged_tokens': charged,
            'remaining_tokens': request.user.get_effective_token_balance(),
        }, status=status.HTTP_201_CREATED)


class EquipmentScanStartView(APIView):
    """شروعِ یک دورِ اسکنِ زنده (ویدیو). هزینهٔ توکن همین‌جا **یک بار** کم می‌شود."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        settings_obj = PlatformSettings.get_solo()
        cost = settings_obj.equipment_scan_token_cost
        charged = 0
        if cost:
            if not request.user.deduct_tokens(cost):
                return Response({'error': 'توکنِ کافی برای اسکن ندارید.',
                                 'required_tokens': cost},
                                status=status.HTTP_402_PAYMENT_REQUIRED)
            charged = cost

        scan = EquipmentScan.objects.create(
            user=request.user,
            gym_name=(request.data.get('gym_name') or '').strip() or None,
            tokens_charged=charged,
        )
        if charged:
            LedgerEntry.record(
                LedgerEntry.TYPE_TOKEN_SPEND, user=request.user, tokens=-charged,
                reference='scan#%s' % scan.pk, description='اسکنِ زندهٔ دستگاه‌ها',
            )
        return Response({
            'scan_id': scan.pk,
            'max_frames': settings_obj.equipment_scan_max_photos,
            'frame_interval_ms': 2500,
            'charged_tokens': charged,
            'remaining_tokens': request.user.get_effective_token_balance(),
            'cameras': [{'value': 'back', 'label': 'دوربینِ عقب'},
                        {'value': 'front', 'label': 'دوربینِ جلو'}],
        }, status=status.HTTP_201_CREATED)


class EquipmentScanFrameView(APIView):
    """یک فریمِ دوربین → فقط تشخیص‌های **تازه**.

    کاربر در باشگاه می‌چرخد و هر چند ثانیه یک فریم می‌آید. چیزی که قبلاً در
    همین دور پیدا شده باشد دوباره برنمی‌گردد، تا فهرست تکراری نشود.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, scan_id):
        settings_obj = PlatformSettings.get_solo()
        scan = EquipmentScan.objects.filter(pk=scan_id, user=request.user).first()
        if scan is None:
            return Response({'error': 'اسکن پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        if scan.status == EquipmentScan.STATUS_CONFIRMED:
            return Response({'error': 'این اسکن قبلاً تأیید شده است.'},
                            status=status.HTTP_400_BAD_REQUEST)

        used = scan.photos.count()
        if used >= settings_obj.equipment_scan_max_photos:
            return Response({
                'limit_reached': True,
                'message': 'سقفِ فریم‌های این اسکن پر شد؛ تأیید کن یا دورِ تازه بزن.',
                'items': [_item_payload(i) for i in scan.items.all()],
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        upload = request.FILES.get('frame') or request.FILES.get('photo')
        if upload is None:
            return Response({'error': 'فریمی نفرستادی (کلیدِ frame).'},
                            status=status.HTTP_400_BAD_REQUEST)

        blob = upload.read()
        upload.seek(0)
        photo = EquipmentScanPhoto.objects.create(scan=scan, image=upload)

        before = set(scan.items.values_list('name', flat=True))
        try:
            count, ai_cost, errors = es.run_scan(scan, [(photo, blob)])
        except Exception as exc:
            logger.exception('فریمِ اسکنِ #%s شکست خورد', scan.pk)
            return Response({'error': 'تشخیص ممکن نشد؛ فریمِ بعدی را بفرست.',
                             'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        scan.status = EquipmentScan.STATUS_DONE
        scan.save()
        if ai_cost:
            LedgerEntry.record(
                LedgerEntry.TYPE_AI_COST, user=request.user, amount=-ai_cost,
                reference='scan#%s' % scan.pk,
                description='هزینهٔ مدلِ بینایی (اسکنِ زنده)',
            )

        fresh = [i for i in scan.items.all() if i.name not in before]
        return Response({
            'new_items': [_item_payload(i) for i in fresh],
            'items': [_item_payload(i) for i in scan.items.all()],
            'frames_used': used + 1,
            'frames_left': max(0, settings_obj.equipment_scan_max_photos - used - 1),
            'errors': errors,
        })


class EquipmentScanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, scan_id):
        scan = EquipmentScan.objects.filter(pk=scan_id, user=request.user).first()
        if scan is None:
            return Response({'error': 'اسکن پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_scan_payload(scan, request))


class EquipmentScanConfirmView(APIView):
    """تأییدِ نهایی — تنها جایی که دستگاه واقعاً به باشگاه اضافه می‌شود."""
    permission_classes = [IsAuthenticated]

    def post(self, request, scan_id):
        scan = EquipmentScan.objects.filter(pk=scan_id, user=request.user).first()
        if scan is None:
            return Response({'error': 'اسکن پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
        if scan.status == EquipmentScan.STATUS_CONFIRMED:
            return Response({'error': 'این اسکن قبلاً تأیید شده است.',
                             'scan': _scan_payload(scan, request)},
                            status=status.HTTP_400_BAD_REQUEST)

        accept = request.data.get('accept')
        if request.data.get('accept_all'):
            accept = None                      # None = همه
        elif accept is None:
            accept = []                        # نه «همه»، نه فهرست → چیزی تأیید نشده
        reject = request.data.get('reject') or []
        if accept is not None and not isinstance(accept, list):
            return Response({'error': 'accept باید فهرستِ شناسه‌ها باشد.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            created, skipped = es.confirm_items(scan, accept, reject)
        except (TypeError, ValueError):
            return Response({'error': 'شناسه‌ها درست نیستند.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # ورزشکارِ شخصی (B2C) که باشگاهش را اسکن کرده: نامِ باشگاه روی پروفایل و
        # حسابش می‌نشیند تا برنامهٔ بعدی بداند کجا تمرین می‌کند.
        if scan.gym_name and request.user.is_personal:
            from .models import AthleteProfile
            profile, _ = AthleteProfile.objects.get_or_create(user=request.user)
            if not profile.gym_name:
                profile.gym_name = scan.gym_name
                profile.save(update_fields=['gym_name'])
            if not request.user.gym_name:
                request.user.gym_name = scan.gym_name
                request.user.save(update_fields=['gym_name'])

        return Response({
            'scan': _scan_payload(scan, request),
            'added': [{'id': i.equipment_id, 'name': i.name} for i in created],
            'already_had': [{'id': i.equipment_id, 'name': i.name} for i in skipped],
            'message': '%d دستگاه اضافه شد، %d تا از قبل بود.' % (len(created), len(skipped)),
        })
