# -*- coding: utf-8 -*-
"""آزمونِ برنامهٔ دستیِ مربی: سهمِ رایگان، کسرِ توکن و لینکِ حرکت در PDF."""
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APITestCase


def url(name, *args):
    """آدرسِ آزمون.

    سایت زیرِ /chagher بالا می‌آید و همان را FORCE_SCRIPT_NAME به reverse اضافه
    می‌کند؛ ولی کلاینتِ آزمون این پیشوند را نمی‌شناسد، پس برداشته می‌شود.
    """
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path

from app.models import (ClientProgram, CustomUser, ExerciseLibrary, GymClient,
                        LedgerEntry, PlatformSettings)


class ManualProgramTests(APITestCase):
    def setUp(self):
        self.coach = CustomUser.objects.create_user(
            phone_number='09120000001', password='x', gym_name='باشگاهِ آزمون'
        )
        self.coach.token_balance = 100
        self.coach.save(update_fields=['token_balance'])
        self.client.force_authenticate(user=self.coach)

        PlatformSettings.objects.all().delete()
        PlatformSettings.objects.create(
            manual_program_free_quota=2, manual_program_token_cost=10,
            manual_trial_days=10, ai_free_programs=5,
        )

        ExerciseLibrary.objects.create(
            external_id='9001', name='Barbell Bench Press',
            name_fa='پرس سینه با هالتر', is_active=True
        )
        from app.exercise_match import reset_cache
        reset_cache()

    def _payload(self, name='رضا احمدی', **extra):
        data = {
            'name': name,
            'days': [{
                'title': 'سینه',
                'exercises': [
                    {'exercise_id': '9001', 'sets': 4, 'reps': 10, 'rest': 90},
                    {'name': 'شنا سوئدی', 'sets': 3, 'reps': '12-15'},
                ],
            }],
            'notes': 'ده دقیقه گرم‌کردن',
        }
        data.update(extra)
        return data

    def _create(self, **kw):
        return self.client.post(url('manual-program'), self._payload(**kw), format='json')

    # ------------------------------------------------------------------
    def test_free_during_trial_then_tokens(self):
        """در دورهٔ آزمایشی رایگان؛ پس از پایانش با توکن."""
        for _ in range(3):
            res = self._create()
            self.assertEqual(res.status_code, 201, res.data)
            self.assertTrue(res.data['was_free'], 'در دورهٔ آزمایشی باید رایگان باشد')
        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 100, 'توکنی نباید کم شود')

        settings_obj = PlatformSettings.get_solo()
        settings_obj.manual_trial_days = 0
        settings_obj.save()
        res = self._create()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['charged_tokens'], 10)
        self.assertTrue(LedgerEntry.objects.filter(
            entry_type=LedgerEntry.TYPE_TOKEN_SPEND,
            reference='program#%s' % res.data['program']['id'],
        ).exists())

    def test_subscription_makes_it_free(self):
        """اشتراکِ سالانه ⇒ دوباره رایگان."""
        from django.utils import timezone
        settings_obj = PlatformSettings.get_solo()
        settings_obj.manual_trial_days = 0
        settings_obj.save()
        self.coach.manual_plan_expires_at = timezone.now() + timezone.timedelta(days=365)
        self.coach.save(update_fields=['manual_plan_expires_at'])
        res = self._create()
        self.assertTrue(res.data['was_free'])
        self.assertEqual(res.data['quota']['access'], 'subscription')

    def test_quota_is_per_athlete(self):
        """سهمِ رایگان برای هر ورزشکار جدا شمرده می‌شود."""
        self._create(name='رضا احمدی')
        self._create(name='رضا احمدی')
        res = self._create(name='سعید کریمی')
        self.assertEqual(res.data['charged_tokens'], 0, 'ورزشکارِ تازه باید رایگان باشد')

    def test_arabic_spelling_counts_as_same_athlete(self):
        """«احمدي» با «احمدی» یک نفر شمرده می‌شود."""
        self._create(name='رضا احمدی')
        self._create(name='رضا  احمدي')
        res = self.client.get(url('manual-program-quota'), {'name': 'رضا احمدی'})
        self.assertEqual(res.data['used'], 2, 'ي عربی نباید نفرِ تازه بسازد')

    def test_needs_subscription_when_trial_over(self):
        """دورهٔ آزمایشی تمام، توکن صفر ⇒ ۴۰۲ با قیمتِ اشتراکِ سالانه."""
        settings_obj = PlatformSettings.get_solo()
        settings_obj.manual_trial_days = 0
        settings_obj.manual_program_token_cost = 0
        settings_obj.save()
        self.coach.token_balance = 0
        self.coach.save(update_fields=['token_balance'])
        res = self._create()
        self.assertEqual(res.status_code, 402, res.data)
        self.assertTrue(res.data['need_subscription'])
        self.assertEqual(res.data['annual_price'], 2000000)
        self.assertEqual(ClientProgram.objects.count(), 0)

    def test_meal_sections_and_supplements(self):
        """برنامهٔ غذاییِ دستی: تیترهای آزاد + جایگاهِ جدای مکمل."""
        res = self.client.post(url('manual-program'), {
            'name': 'رضا احمدی',
            'meal_sections': [
                {'title': 'صبحانه', 'content': 'تخم‌مرغ و نان'},
                {'title': 'شام', 'content': 'ماهی و سالاد'},
            ],
            'supplements': [{'title': 'کراتین', 'content': 'روزی ۵ گرم'}],
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        meal = res.data['program']['generated_meal_plan']
        self.assertIn('## صبحانه', meal)
        self.assertIn('## شام', meal)
        self.assertIn('## مکمل‌ها و ویتامین‌ها', meal)
        self.assertIn('کراتین: روزی ۵ گرم', meal)
        self.assertEqual(res.data['program']['program_type'], 'meal')

    def test_free_text_exercise_is_accepted(self):
        """حرکتی که در کتابخانهٔ ما نیست هم باید پذیرفته شود."""
        res = self.client.post(url('manual-program'), {
            'name': 'رضا احمدی',
            'days': [{'title': 'سینه', 'exercises': [
                {'name': 'حرکتِ اختصاصیِ خودم', 'sets': 3, 'reps': 10}]}],
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn('حرکتِ اختصاصیِ خودم', res.data['program']['generated_workout'])

    def test_library_name_and_pdf_link(self):
        """نامِ حرکت از کتابخانه می‌آید و در PDF لینک می‌خورد."""
        res = self._create()
        text = res.data['program']['generated_workout']
        self.assertIn('## جلسه 1', text)
        self.assertIn('1. پرس سینه با هالتر — 4×10 · استراحت 90 ثانیه', text)

        from pdf_generator.pdf_gen import _exercise_link
        self.assertIn('/exercise/9001/', _exercise_link('پرس سینه با هالتر — 4×10') or '')

    def test_quota_endpoint(self):
        res = self.client.get(url('manual-program-quota'), {'name': 'رضا احمدی'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['free_remaining'], 2)
        self.assertTrue(res.data['next_is_free'])
        self._create()
        res = self.client.get(url('manual-program-quota'), {'name': 'رضا احمدی'})
        self.assertEqual(res.data['free_remaining'], 1)

    def test_edit_is_free(self):
        created = self._create()
        pid = created.data['program']['id']
        res = self.client.patch(
            url('manual-program-detail', pid),
            {'days': [{'title': 'پا', 'exercises': [{'name': 'اسکوات', 'sets': 5, 'reps': 5}]}]},
            format='json',
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['charged_tokens'], 0)
        self.assertIn('اسکوات', res.data['program']['generated_workout'])
        self.assertNotIn('پرس سینه', res.data['program']['generated_workout'])

    def test_gym_client_must_belong_to_coach(self):
        other = CustomUser.objects.create_user(phone_number='09120000002', password='x')
        gc = GymClient.objects.create(gym_owner=other, access_code='7777', name='غریبه')
        res = self.client.post(url('manual-program'),
                               self._payload(gym_client=gc.id), format='json')
        self.assertEqual(res.status_code, 400)

    def test_bad_payload(self):
        res = self.client.post(url('manual-program'),
                               {'name': 'رضا', 'days': []}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.post(url('manual-program'),
                               {'name': 'رضا', 'days': [{'exercises': [{'exercise_id': 'نیست'}]}]},
                               format='json')
        self.assertEqual(res.status_code, 400)
