# -*- coding: utf-8 -*-
"""تست‌های دستورالعمل مربی و بازگشت خودکار توکن رزروشده"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone
from rest_framework import status

from app.models import (
    ClientProgram, CustomUser, GymBrand, GymClient, PlatformSettings, TokenRequest,
)
from .utils import BaseAPITestCase, create_user


def create_personal(phone='09150000001'):
    return CustomUser.objects.create_user(
        phone_number=phone, password='StrongPass123',
        account_type=CustomUser.ACCOUNT_TYPE_PERSONAL,
    )


class CoachInstructionAPITests(BaseAPITestCase):
    url = '/api/coach-instructions/'

    def setUp(self):
        self.coach = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.auth(self.coach)

    def test_empty_when_not_set(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['program_instructions'], '')

    def test_save_creates_brand_if_missing(self):
        """مربی بدون برند هم باید بتواند دستورالعمل ثبت کند"""
        self.assertFalse(GymBrand.objects.filter(user=self.coach).exists())

        response = self.client.put(self.url, {
            'program_instructions': 'روز اول هر هفته سبک باشد.',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        brand = GymBrand.objects.get(user=self.coach)
        self.assertEqual(brand.program_instructions, 'روز اول هر هفته سبک باشد.')
        self.assertEqual(brand.gym_name, 'باشگاه تست')

    def test_update_existing(self):
        GymBrand.objects.create(user=self.coach, gym_name='باشگاه تست',
                                program_instructions='قدیمی')
        self.client.put(self.url, {'program_instructions': 'جدید'})
        self.assertEqual(GymBrand.objects.get(user=self.coach).program_instructions, 'جدید')

    def test_clear_instructions(self):
        GymBrand.objects.create(user=self.coach, gym_name='ب', program_instructions='چیزی')
        response = self.client.put(self.url, {'program_instructions': ''})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(GymBrand.objects.get(user=self.coach).program_instructions, '')

    def test_personal_user_forbidden(self):
        self.auth(create_personal())
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)


class CoachInstructionInPromptTests(BaseAPITestCase):
    """دستورالعمل باید به موتور AI برسد"""

    def test_coach_own_program_uses_instructions(self):
        from ai_engine.ai_generator import get_coach_instructions
        coach = create_user(phone='09121234567')
        GymBrand.objects.create(user=coach, gym_name='ب',
                                program_instructions='هیچ حرکت پرشی نده.')
        program = ClientProgram.objects.create(user=coach, name='علی')
        self.assertIn('پرشی', get_coach_instructions(program))

    def test_gym_client_inherits_coach_instructions(self):
        """ورزشکار باشگاه باید دستورالعمل مربی خودش را بگیرد"""
        from ai_engine.ai_generator import get_coach_instructions
        coach = create_user(phone='09121234567', gym_name='باشگاه')
        GymBrand.objects.create(user=coach, gym_name='باشگاه',
                                program_instructions='تمرکز روی تکنیک.')
        gym_client = GymClient.objects.create(gym_owner=coach)
        response = self.client.post('/api/client-access/',
                                    {'access_code': gym_client.access_code})
        gym_client.refresh_from_db()
        program = ClientProgram.objects.create(user=gym_client.client_user, name='رضا')
        self.assertIn('تکنیک', get_coach_instructions(program))

    def test_personal_user_has_no_coach_instructions(self):
        from ai_engine.ai_generator import get_coach_instructions
        personal = create_personal()
        program = ClientProgram.objects.create(user=personal, name='رضا')
        self.assertEqual(get_coach_instructions(program), 'ندارد')


class PendingTokenExpiryTests(BaseAPITestCase):
    """بازگشت خودکار توکن رزروشده روی کد استفاده‌نشده"""

    def setUp(self):
        self.coach = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.coach.token_balance = 200
        self.coach.save()
        self.gym_client = GymClient.objects.create(gym_owner=self.coach)
        self.auth(self.coach)

    def _reserve(self, amount=50):
        response = self.client.post(
            f'/api/gym-clients/{self.gym_client.id}/adjust-tokens/', {'amount': amount})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.gym_client.refresh_from_db()

    def _age_reservation(self, days):
        GymClient.objects.filter(pk=self.gym_client.pk).update(
            tokens_reserved_at=timezone.now() - timedelta(days=days))
        self.gym_client.refresh_from_db()

    def test_reservation_stamps_time(self):
        self._reserve(50)
        self.assertEqual(self.gym_client.pending_tokens, 50)
        self.assertIsNotNone(self.gym_client.tokens_reserved_at)

    def test_not_expired_before_deadline(self):
        self._reserve(50)
        self._age_reservation(10)
        self.assertFalse(self.gym_client.pending_tokens_expired(30))

    def test_expired_after_deadline(self):
        self._reserve(50)
        self._age_reservation(31)
        self.assertTrue(self.gym_client.pending_tokens_expired(30))

    def test_reclaim_returns_tokens_to_coach(self):
        self._reserve(50)
        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 150)

        returned = self.gym_client.reclaim_pending_tokens()
        self.assertEqual(returned, 50)

        self.coach.refresh_from_db()
        self.gym_client.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 200)
        self.assertEqual(self.gym_client.pending_tokens, 0)
        self.assertIsNone(self.gym_client.tokens_reserved_at)

    def test_reclaim_is_idempotent(self):
        self._reserve(50)
        self.gym_client.reclaim_pending_tokens()
        again = self.gym_client.reclaim_pending_tokens()
        self.assertEqual(again, 0)
        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 200)  # دوباره شارژ نشد

    def test_used_code_never_expires(self):
        """کدی که مشتری فعالش کرده، رزروش منقضی نمی‌شود"""
        self._reserve(50)
        self._age_reservation(90)
        GymClient.objects.filter(pk=self.gym_client.pk).update(is_used=True)
        self.gym_client.refresh_from_db()
        self.assertFalse(self.gym_client.pending_tokens_expired(30))

    def test_zero_days_disables_expiry(self):
        self._reserve(50)
        self._age_reservation(365)
        self.assertFalse(self.gym_client.pending_tokens_expired(0))

    def test_activation_clears_reservation_timestamp(self):
        self._reserve(50)
        self.unauth()
        self.client.post('/api/client-access/', {'access_code': self.gym_client.access_code})
        self.gym_client.refresh_from_db()
        self.assertEqual(self.gym_client.pending_tokens, 0)
        self.assertIsNone(self.gym_client.tokens_reserved_at)
        self.assertEqual(self.gym_client.client_user.token_balance, 50)

    def test_token_request_approval_stamps_time(self):
        """رزرو از مسیر تایید درخواست توکن هم باید زمان بخورد"""
        req = TokenRequest.objects.create(
            client=self.gym_client, gym_owner=self.coach, requested_tokens=50)
        success, _ = req.approve()
        self.assertTrue(success)
        self.gym_client.refresh_from_db()
        self.assertEqual(self.gym_client.pending_tokens, 50)
        self.assertIsNotNone(self.gym_client.tokens_reserved_at)


class ReclaimCommandTests(BaseAPITestCase):
    """دستور مدیریتی بازگشت توکن"""

    def setUp(self):
        self.coach = create_user(phone='09121234567')
        self.coach.token_balance = 200
        self.coach.save()

    def _expired_client(self, amount=50, days=40):
        client = GymClient.objects.create(gym_owner=self.coach, pending_tokens=amount)
        GymClient.objects.filter(pk=client.pk).update(
            tokens_reserved_at=timezone.now() - timedelta(days=days))
        client.refresh_from_db()
        return client

    def _run(self, *args):
        out = StringIO()
        call_command('reclaim_expired_tokens', *args, stdout=out)
        return out.getvalue()

    def test_command_reclaims_expired(self):
        client = self._expired_client()
        self._run()
        client.refresh_from_db()
        self.coach.refresh_from_db()
        self.assertEqual(client.pending_tokens, 0)
        self.assertEqual(self.coach.token_balance, 250)

    def test_dry_run_changes_nothing(self):
        client = self._expired_client()
        output = self._run('--dry-run')
        client.refresh_from_db()
        self.assertEqual(client.pending_tokens, 50)
        self.assertIn('آزمایشی', output)

    def test_fresh_reservation_untouched(self):
        client = GymClient.objects.create(gym_owner=self.coach, pending_tokens=50)
        GymClient.objects.filter(pk=client.pk).update(tokens_reserved_at=timezone.now())
        self._run()
        client.refresh_from_db()
        self.assertEqual(client.pending_tokens, 50)

    def test_custom_days_argument(self):
        client = self._expired_client(days=10)
        self._run('--days', '5')
        client.refresh_from_db()
        self.assertEqual(client.pending_tokens, 0)

    def test_zero_expiry_disables(self):
        settings_obj = PlatformSettings.get_solo()
        settings_obj.pending_token_expiry_days = 0
        settings_obj.save()

        client = self._expired_client(days=100)
        output = self._run()
        client.refresh_from_db()
        self.assertEqual(client.pending_tokens, 50)
        self.assertIn('غیرفعال', output)

    def test_settings_default_is_30_days(self):
        self.assertEqual(PlatformSettings.get_solo().pending_token_expiry_days, 30)

    def test_only_one_active_settings(self):
        PlatformSettings.get_solo()
        PlatformSettings.objects.create(name='دوم', is_active=True)
        self.assertEqual(PlatformSettings.objects.filter(is_active=True).count(), 1)
