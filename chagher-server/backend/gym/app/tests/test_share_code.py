# -*- coding: utf-8 -*-
"""کد یکبارمصرف دانلود برنامه‌ای که مربی از قبل ساخته است.

قاعده‌ی اصلی که این تست‌ها نگه می‌دارند:

* از سمت ورزشکار، هر کد **فقط یک بار** کار می‌کند.
* دسترسی خود مربی از تاریخچه **همیشگی** است و کد هیچ اثری بر آن ندارد.
* این کد با «کد دسترسی پنل» (که زمان‌دار/دائمی است و ورود مجدد می‌دهد)
  قاطی نمی‌شود.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from app.models import ClientProgram, GymClient, ProgramShareCode
from .utils import BaseAPITestCase, create_user


class ShareCodeCreationTests(BaseAPITestCase):
    def setUp(self):
        self.coach = create_user(phone='09121234567')
        self.program = ClientProgram.objects.create(
            user=self.coach, name='علی',
            generated_workout='## برنامه ورزشی\n### جلسه ۱\n1. اسکات — ۳×۱۰',
            generated_meal_plan='## برنامه غذایی\n### روز ۱\n**صبحانه:** نان و پنیر',
        )
        self.auth(self.coach)

    def test_coach_can_create_share_code(self):
        response = self.client.post(
            f'/api/programs/{self.program.id}/share-code/', {}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('code', response.data)
        self.assertFalse(response.data['is_used'])
        self.assertTrue(response.data['is_redeemable'])

    def test_code_is_numeric_and_matches_access_code_length(self):
        response = self.client.post(
            f'/api/programs/{self.program.id}/share-code/', {}
        )
        code = response.data['code']
        self.assertTrue(code.isdigit())
        self.assertEqual(len(code), GymClient.access_code_length())

    def test_creating_code_costs_no_tokens(self):
        """هزینه هنگام تولید برنامه کسر شده؛ تحویل نباید دوباره پول بگیرد."""
        self.coach.token_balance = 100
        self.coach.save()

        self.client.post(f'/api/programs/{self.program.id}/share-code/', {})

        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 100)

    def test_section_can_be_limited(self):
        response = self.client.post(
            f'/api/programs/{self.program.id}/share-code/', {'section': 'workout'}
        )
        self.assertEqual(response.data['section'], 'workout')

    def test_section_falls_back_for_single_part_program(self):
        """برنامه فقط-ورزشی: کد «هردو» باید به ورزشی محدود شود."""
        program = ClientProgram.objects.create(
            user=self.coach, name='رضا', generated_workout='## برنامه ورزشی\nتست',
        )
        response = self.client.post(
            f'/api/programs/{program.id}/share-code/', {'section': 'both'}
        )
        self.assertEqual(response.data['section'], 'workout')

    def test_cannot_request_missing_section(self):
        program = ClientProgram.objects.create(
            user=self.coach, name='رضا', generated_workout='## برنامه ورزشی\nتست',
        )
        response = self.client.post(
            f'/api/programs/{program.id}/share-code/', {'section': 'meal'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_share_empty_program(self):
        program = ClientProgram.objects.create(user=self.coach, name='خالی')
        response = self.client.post(f'/api/programs/{program.id}/share-code/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_other_coach_cannot_create_code(self):
        stranger = create_user(phone='09129999999')
        self.auth(stranger)
        response = self.client.post(
            f'/api/programs/{self.program.id}/share-code/', {}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_coach_can_list_codes_of_a_program(self):
        self.client.post(f'/api/programs/{self.program.id}/share-code/', {})
        self.client.post(f'/api/programs/{self.program.id}/share-code/', {})

        response = self.client.get(f'/api/programs/{self.program.id}/share-code/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_expiry_can_be_set(self):
        response = self.client.post(
            f'/api/programs/{self.program.id}/share-code/', {'expires_in_hours': 24}
        )
        self.assertIsNotNone(response.data['expires_at'])


class ShareCodeRedeemTests(BaseAPITestCase):
    def setUp(self):
        self.coach = create_user(phone='09121234567')
        self.program = ClientProgram.objects.create(
            user=self.coach, name='علی',
            generated_workout='## برنامه ورزشی\n### جلسه ۱\n1. اسکات — ۳×۱۰',
            generated_meal_plan='## برنامه غذایی\n### روز ۱\n**صبحانه:** نان و پنیر',
        )
        self.share = ProgramShareCode.objects.create(
            program=self.program, created_by=self.coach, section='both',
        )

    def test_athlete_gets_pdf_without_any_account(self):
        """ورزشکار فقط کد دارد؛ نباید مجبور به ساخت حساب شود."""
        self.unauth()
        response = self.client.post(
            '/api/programs/redeem-code/', {'code': self.share.code}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_code_works_only_once(self):
        self.unauth()
        first = self.client.post(
            '/api/programs/redeem-code/', {'code': self.share.code}
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.post(
            '/api/programs/redeem-code/', {'code': self.share.code}
        )
        self.assertEqual(second.status_code, status.HTTP_410_GONE)
        self.assertIn('قبلاً استفاده شده', second.data['error'])

    def test_redeem_marks_code_used(self):
        self.unauth()
        self.client.post('/api/programs/redeem-code/', {'code': self.share.code})

        self.share.refresh_from_db()
        self.assertTrue(self.share.is_used)
        self.assertIsNotNone(self.share.used_at)

    def test_unknown_code_is_rejected(self):
        self.unauth()
        response = self.client.post('/api/programs/redeem-code/', {'code': '000000'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_expired_code_is_rejected(self):
        self.share.expires_at = timezone.now() - timedelta(hours=1)
        self.share.save(update_fields=['expires_at'])

        self.unauth()
        response = self.client.post(
            '/api/programs/redeem-code/', {'code': self.share.code}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.share.refresh_from_db()
        self.assertFalse(self.share.is_used)

    def test_workout_only_code_returns_workout_pdf(self):
        share = ProgramShareCode.objects.create(
            program=self.program, created_by=self.coach, section='workout',
        )
        self.unauth()
        response = self.client.post('/api/programs/redeem-code/', {'code': share.code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('workout', response['Content-Disposition'])

    def test_concurrent_redeem_only_succeeds_once(self):
        """مصرف باید اتمیک باشد — دو درخواست هم‌زمان، یک دانلود."""
        first = self.share.redeem()
        second = self.share.redeem()
        self.assertTrue(first)
        self.assertFalse(second)


class CoachKeepsAccessTests(BaseAPITestCase):
    """مصرف‌شدن کد نباید دسترسی مربی را محدود کند."""

    def setUp(self):
        self.coach = create_user(phone='09121234567')
        self.program = ClientProgram.objects.create(
            user=self.coach, name='علی',
            generated_workout='## برنامه ورزشی\n### جلسه ۱\n1. اسکات — ۳×۱۰',
        )
        self.share = ProgramShareCode.objects.create(
            program=self.program, created_by=self.coach, section='workout',
        )

    def test_coach_can_still_download_after_code_is_used(self):
        self.unauth()
        self.client.post('/api/programs/redeem-code/', {'code': self.share.code})

        self.auth(self.coach)
        response = self.client.get(f'/api/programs/{self.program.id}/pdf-workout/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_program_stays_in_coach_history(self):
        self.unauth()
        self.client.post('/api/programs/redeem-code/', {'code': self.share.code})

        self.auth(self.coach)
        response = self.client.get('/api/programs/history/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data
        if isinstance(payload, dict):
            payload = payload.get('programs', payload.get('results', []))
        ids = [item['id'] for item in payload]
        self.assertIn(self.program.id, ids)

    def test_coach_can_issue_a_new_code_after_the_first_is_used(self):
        self.unauth()
        self.client.post('/api/programs/redeem-code/', {'code': self.share.code})

        self.auth(self.coach)
        response = self.client.post(
            f'/api/programs/{self.program.id}/share-code/', {'section': 'workout'}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data['code'], self.share.code)


class CodeNamespaceTests(BaseAPITestCase):
    """دو نوع کد در یک فیلد وارد می‌شوند؛ نباید با هم تداخل کنند."""

    def setUp(self):
        self.coach = create_user(phone='09121234567')
        self.program = ClientProgram.objects.create(
            user=self.coach, name='علی', generated_workout='## برنامه ورزشی\nتست',
        )

    def test_share_code_never_collides_with_access_code(self):
        existing = {
            GymClient.objects.create(gym_owner=self.coach).access_code
            for _ in range(25)
        }
        shares = {
            ProgramShareCode.objects.create(
                program=self.program, created_by=self.coach
            ).code
            for _ in range(25)
        }
        self.assertEqual(existing & shares, set())

    def test_download_code_in_login_field_gets_helpful_message(self):
        """اگر ورزشکار کد دانلود را در فیلد ورود بزند، باید راهنمایی شود."""
        share = ProgramShareCode.objects.create(
            program=self.program, created_by=self.coach
        )
        self.unauth()
        response = self.client.post('/api/client-access/', {'access_code': share.code})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code_kind'], 'program_download')
        self.assertIn('redeem_endpoint', response.data)

    def test_access_code_still_works_for_panel_login(self):
        """کد دسترسی پنل نباید تحت تأثیر قابلیت جدید قرار بگیرد."""
        gym_client = GymClient.objects.create(gym_owner=self.coach, name='رضا')
        self.unauth()
        response = self.client.post(
            '/api/client-access/', {'access_code': gym_client.access_code}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
