# -*- coding: utf-8 -*-
"""آزمونِ اسکنِ دستگاه با دوربین.

مدلِ بینایی در آزمون فراخوانی نمی‌شود (هم پول دارد هم کند است و هم به اینترنت
وابسته)؛ فقط لایهٔ تشخیص جعل می‌شود. چیزی که این‌جا سنجیده می‌شود، همان قاعدهٔ
اصلی است: تا کاربر تأیید نکند هیچ دستگاهی ساخته نشود، و تکراری ساخته نشود.
"""
import io
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import (Equipment, EquipmentScan, EquipmentScanItem,
                        CustomUser, LedgerEntry, PlatformSettings)


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def a_photo(name='g.jpg'):
    """یک JPEGِ کوچکِ واقعی تا ImageField قبولش کند."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (120, 120, 120)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


# (تشخیص‌ها، متنِ خام، نامِ مدل، (توکنِ ورودی، توکنِ خروجی)، تنظیماتِ ارائه‌دهنده)
FAKE_OK = (
    [{'name': 'دستگاه پرس پا', 'muscle_group': 'پا', 'confidence': 0.95, 'new': False},
     {'name': 'دستگاه زیربغل (لت)', 'muscle_group': 'زیربغل', 'confidence': 0.9, 'new': False},
     {'name': 'دستگاه عجیبِ تازه', 'muscle_group': 'شکم', 'confidence': 0.4, 'new': True}],
    '{"items":[...]}', 'fake-vision', (100, 50), {'model_name': 'fake-vision'},
)


class EquipmentScanTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(phone_number='09120000010', password='x')
        self.user.token_balance = 50
        self.user.save(update_fields=['token_balance'])
        self.client.force_authenticate(user=self.user)
        PlatformSettings.objects.all().delete()
        self.settings_obj = PlatformSettings.objects.create(
            equipment_scan_token_cost=0, equipment_scan_max_photos=3
        )

    def _scan(self, photos=2):
        with mock.patch('app.equipment_scan.recognize_photo', return_value=FAKE_OK):
            return self.client.post(
                url('equipment-scan'),
                {'photos': [a_photo('a.jpg'), a_photo('b.jpg')][:photos],
                 'gym_name': 'باشگاهِ آزمون'},
                format='multipart',
            )

    # ------------------------------------------------------------------
    def test_scan_detects_but_adds_nothing(self):
        """قاعدهٔ اصلی: اسکن فقط پیشنهاد می‌دهد، ثبت نمی‌کند."""
        res = self._scan()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['detected'], 3)
        self.assertEqual(res.data['scan']['status'], EquipmentScan.STATUS_DONE)
        self.assertEqual(Equipment.objects.count(), 0, 'بدونِ تأیید نباید دستگاهی ساخته شود')
        self.assertEqual(len(res.data['scan']['photos']), 2)
        names = {i['name'] for i in res.data['scan']['items']}
        self.assertIn('دستگاه پرس پا', names)
        # نامِ تازه علامت می‌خورد تا کاربر بداند از فهرستِ دیتابیس نیامده
        new_item = next(i for i in res.data['scan']['items'] if i['name'] == 'دستگاه عجیبِ تازه')
        self.assertFalse(new_item['in_library'])

    def test_confirm_selected_only(self):
        scan_res = self._scan()
        items = scan_res.data['scan']['items']
        keep = [i['id'] for i in items if i['name'] == 'دستگاه پرس پا']
        res = self.client.post(url('equipment-scan-confirm', scan_res.data['scan']['id']),
                               {'accept': keep}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Equipment.objects.count(), 1)
        eq = Equipment.objects.get()
        self.assertEqual(eq.name, 'دستگاه پرس پا')
        self.assertEqual(eq.muscle_group, 'پا')
        self.assertEqual(eq.user, self.user)
        self.assertEqual(EquipmentScanItem.objects.filter(is_rejected=True).count(), 2)

    def test_confirm_all(self):
        scan_res = self._scan()
        res = self.client.post(url('equipment-scan-confirm', scan_res.data['scan']['id']),
                               {'accept_all': True}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Equipment.objects.count(), 3)
        self.assertEqual(res.data['scan']['status'], EquipmentScan.STATUS_CONFIRMED)

    def test_existing_equipment_not_duplicated(self):
        Equipment.objects.create(user=self.user, name='پرس پا دستگاه')
        scan_res = self._scan()
        item = next(i for i in scan_res.data['scan']['items'] if i['name'] == 'دستگاه پرس پا')
        self.assertTrue(item['already_exists'], 'نامِ هم‌معنی باید «از قبل بود» شود')
        self.client.post(url('equipment-scan-confirm', scan_res.data['scan']['id']),
                         {'accept_all': True}, format='json')
        self.assertEqual(Equipment.objects.filter(user=self.user).count(), 3,
                         'یکی از قبل بود + دو تای تازه = ۳، نه ۴')

    def test_token_cost_and_ledger(self):
        self.settings_obj.equipment_scan_token_cost = 5
        self.settings_obj.save()
        res = self._scan()
        self.assertEqual(res.data['charged_tokens'], 5)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 45)
        self.assertTrue(LedgerEntry.objects.filter(
            entry_type=LedgerEntry.TYPE_TOKEN_SPEND,
            reference='scan#%s' % res.data['scan']['id']).exists())

    def test_no_tokens(self):
        self.settings_obj.equipment_scan_token_cost = 5
        self.settings_obj.save()
        self.user.token_balance = 2
        self.user.save(update_fields=['token_balance'])
        res = self._scan()
        self.assertEqual(res.status_code, 402, res.data)
        self.assertEqual(EquipmentScan.objects.count(), 0)

    def test_photo_limit(self):
        self.settings_obj.equipment_scan_max_photos = 1
        self.settings_obj.save()
        res = self._scan(photos=2)
        self.assertEqual(res.status_code, 400, res.data)

    def test_refund_when_vision_fails(self):
        """همهٔ عکس‌ها خطا دادند: اسکن ناموفق و توکن برمی‌گردد."""
        self.settings_obj.equipment_scan_token_cost = 5
        self.settings_obj.save()
        with mock.patch('app.equipment_scan.recognize_photo', side_effect=RuntimeError('قطعِ درگاه')):
            res = self.client.post(url('equipment-scan'),
                                   {'photos': [a_photo()]}, format='multipart')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['detected'], 0)
        self.assertEqual(res.data['charged_tokens'], 0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 50)
        self.assertEqual(res.data['scan']['status'], EquipmentScan.STATUS_FAILED)

    def test_candidates_list(self):
        res = self.client.get(url('equipment-scan-candidates'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('تردمیل', res.data['equipment'])
        self.assertEqual(res.data['max_photos'], 3)

    def test_other_users_scan_is_hidden(self):
        scan_res = self._scan()
        other = CustomUser.objects.create_user(phone_number='09120000011', password='x')
        self.client.force_authenticate(user=other)
        res = self.client.get(url('equipment-scan-detail', scan_res.data['scan']['id']))
        self.assertEqual(res.status_code, 404)
