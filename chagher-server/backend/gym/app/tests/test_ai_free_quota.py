# -*- coding: utf-8 -*-
"""سهمیهٔ رایگانِ هوش مصنوعی (خواستهٔ مالک: ۵ برنامهٔ اولِ هر مربی)."""
from unittest import mock

from django.conf import settings
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import ClientProgram, CustomUser, PlatformSettings


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


class FakeUsage:
    model_name = 'fake-ai'
    input_tokens = 10
    output_tokens = 20
    provider_config = {'model_name': 'fake-ai'}


class AIFreeQuotaTests(APITestCase):
    def setUp(self):
        self.coach = CustomUser.objects.create_user(phone_number='09120000050', password='x')
        self.coach.token_balance = 0          # عمداً صفر: سهمیهٔ رایگان باید کار کند
        self.coach.save(update_fields=['token_balance'])
        self.client.force_authenticate(user=self.coach)
        PlatformSettings.objects.all().delete()
        self.cfg = PlatformSettings.objects.create(ai_free_programs=2)

    def _generate(self):
        with mock.patch('app.views.generate_program',
                        return_value=('## جلسه 1\n1. اسکوات', None, FakeUsage())):
            return self.client.post(url('generate-program'), {
                'name': 'رضا', 'program_type': 'workout',
                'training_place': 'public_gym',
            }, format='json')

    def test_free_programs_need_no_tokens(self):
        """با موجودیِ صفر، دو برنامهٔ اول باید ساخته شود."""
        for i in range(2):
            res = self._generate()
            self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(ClientProgram.objects.count(), 2)
        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 0, 'توکنی نباید کم شود')

    def test_after_quota_tokens_are_required(self):
        """سومی دیگر رایگان نیست و بی‌توکن ۴۰۲ می‌دهد."""
        self._generate()
        self._generate()
        res = self._generate()
        self.assertEqual(res.status_code, 402, res.data)

    def test_quota_is_reported(self):
        self.assertEqual(self.coach.ai_free_left(), 2)
        self._generate()
        self.assertEqual(self.coach.ai_free_left(), 1)

    def test_admin_can_disable_quota(self):
        self.cfg.ai_free_programs = 0
        self.cfg.save()
        res = self._generate()
        self.assertEqual(res.status_code, 402, 'با سهمیهٔ صفر باید توکن لازم باشد')
