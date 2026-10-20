# -*- coding: utf-8 -*-
"""آزمونِ مسیرِ ورزشکارِ شخصی (B2C): مشخصات ← اسکنِ باشگاه ← توکن ← برنامه.

مدلِ هوش مصنوعی و مدلِ بینایی هر دو جعل می‌شوند؛ چیزی که سنجیده می‌شود خودِ
زنجیره است، نه کیفیتِ مدل.
"""
import io
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import (AthleteProfile, ClientProgram, CustomUser, Equipment,
                        PlatformSettings)


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def a_photo(name='gym.jpg'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (90, 90, 90)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


FAKE_VISION = (
    [{'name': 'دستگاه پرس پا', 'muscle_group': 'پا', 'confidence': 0.95, 'new': False},
     {'name': 'تردمیل', 'muscle_group': 'هوازی', 'confidence': 0.99, 'new': False}],
    '{"items":[...]}', 'fake-vision', (80, 40), {'model_name': 'fake-vision'},
)


class FakeUsage:
    model_name = 'fake-ai'
    input_tokens = 100
    output_tokens = 200
    provider_config = {'model_name': 'fake-ai'}


class B2CFlowTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            phone_number='09120000020', password='x',
            account_type=CustomUser.ACCOUNT_TYPE_PERSONAL,
        )
        self.client.force_authenticate(user=self.user)
        PlatformSettings.objects.all().delete()
        PlatformSettings.objects.create(equipment_scan_token_cost=0)

    # ------------------------------------------------------------------
    def test_status_shows_steps(self):
        res = self.client.get(url('my-status'))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['account_type'], CustomUser.ACCOUNT_TYPE_PERSONAL)
        self.assertFalse(res.data['profile_complete'])
        self.assertFalse(res.data['can_generate_program'])
        keys = [s['key'] for s in res.data['steps']]
        self.assertEqual(keys, ['profile', 'scan', 'tokens', 'program'])

    def test_profile_save_and_defaults(self):
        res = self.client.patch(url('athlete-profile'), {
            'full_name': 'سعید کریمی', 'age': 28, 'gender': 'M',
            'height': 178, 'weight': 82, 'goal': 'کاهشِ چربی',
            'program_days': 4, 'gym_name': 'باشگاهِ پارس',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data['profile']['is_complete'])
        defaults = res.data['program_defaults']
        self.assertEqual(defaults['name'], 'سعید کریمی')
        self.assertEqual(defaults['program_days'], 4)
        self.assertIn('کاهشِ چربی', defaults['extra_notes'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.gym_name, 'باشگاهِ پارس')

    def test_scan_gym_then_own_equipment(self):
        """ورزشکار باشگاهش را اسکن می‌کند و دستگاه‌ها به حسابِ خودش می‌نشیند."""
        with mock.patch('app.equipment_scan.recognize_photo', return_value=FAKE_VISION):
            scan = self.client.post(url('equipment-scan'),
                                    {'photos': [a_photo()], 'gym_name': 'باشگاهِ پارس'},
                                    format='multipart')
        self.assertEqual(scan.status_code, 201, scan.data)
        self.assertEqual(Equipment.objects.count(), 0, 'بدونِ تأیید چیزی ثبت نمی‌شود')

        res = self.client.post(url('equipment-scan-confirm', scan.data['scan']['id']),
                               {'accept_all': True}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Equipment.objects.filter(user=self.user).count(), 2)
        self.user.refresh_from_db()
        self.assertEqual(self.user.gym_name, 'باشگاهِ پارس')
        self.assertEqual(AthleteProfile.objects.get(user=self.user).gym_name, 'باشگاهِ پارس')

        status_res = self.client.get(url('my-status'))
        self.assertEqual(status_res.data['equipment_count'], 2)

    def test_personal_user_can_edit_own_equipment(self):
        """نتیجهٔ اسکن باید قابلِ ویرایش باشد (قبلاً فقط مربی اجازه داشت)."""
        res = self.client.post('/api/equipments/',
                               {'name': 'دستگاه قفسهٔ سینه', 'muscle_group': 'سینه'},
                               format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Equipment.objects.get().user, self.user)

    def test_program_uses_profile_and_scanned_equipment(self):
        """برنامه با «تجهیزاتِ ثبت‌شده» و مشخصاتِ پروفایل ساخته می‌شود."""
        self.client.patch(url('athlete-profile'), {
            'full_name': 'سعید کریمی', 'age': 28, 'gender': 'M',
            'height': 178, 'weight': 82, 'program_days': 4,
        }, format='json')
        Equipment.objects.create(user=self.user, name='تردمیل')
        self.user.token_balance = 100
        self.user.save(update_fields=['token_balance'])

        with mock.patch('app.views.generate_program',
                        return_value=('## جلسه 1\n1. تردمیل — 20 دقیقه', None, FakeUsage())):
            res = self.client.post(url('generate-program'), {
                'name': 'سعید کریمی',
                'program_type': 'workout',
                'training_place': 'gym_equipment',
            }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        program = ClientProgram.objects.get()
        self.assertEqual(program.training_place, 'gym_equipment')
        self.assertEqual(program.age, 28, 'سن باید از پروفایل پر شود')
        self.assertEqual(program.weight, 82)
        self.assertEqual(program.program_days, 4)

    def test_personal_without_equipment_must_pick_place(self):
        """بی‌دستگاه، «تجهیزاتِ ثبت‌شده» بی‌معناست و باید رد شود."""
        self.user.token_balance = 100
        self.user.save(update_fields=['token_balance'])
        res = self.client.post(url('generate-program'), {
            'name': 'سعید', 'program_type': 'workout', 'training_place': 'gym_equipment',
        }, format='json')
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn('training_place_choices', res.data)

    def test_coach_world_untouched(self):
        """مربی هنوز به مدیریتِ باشگاه دسترسی دارد و ورزشکارِ شخصی ندارد."""
        coach = CustomUser.objects.create_user(phone_number='09120000021', password='x')
        self.client.force_authenticate(user=coach)
        self.assertEqual(self.client.get('/api/gym-clients/').status_code, 200)
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get('/api/gym-clients/').status_code, 403)
