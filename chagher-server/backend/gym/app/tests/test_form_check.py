# -*- coding: utf-8 -*-
"""آزمونِ «بررسیِ درستیِ حرکت با دوربین».

مهم‌ترین چیزی که این‌جا سنجیده می‌شود، همان خواستهٔ صریحِ مالک است: وقتی قابلیت
از جنگو ادمین خاموش است، **هیچ نشانی از آن نباشد** — نه دکمه، نه صفحه، نه API.
"""
import io
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import (CustomUser, ExerciseLibrary, FormCheckFrame,
                        FormCheckSession, LedgerEntry, PlatformSettings)


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def a_frame(name='f.jpg'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (60, 80), (70, 90, 110)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


FAKE_BAD = {
    'verdict': 'bad', 'message': 'کمرت گرد شده؛ سینه را بده جلو.', 'confidence': 0.9,
    'box': {'x': 0.1, 'y': 0.1, 'w': 0.7, 'h': 0.8},
    'raw': '{}', 'model_name': 'fake-vision', 'usage': (90, 40),
    'config': {'model_name': 'fake-vision'},
}
FAKE_OK = dict(FAKE_BAD, verdict='ok', message='خوب است، همین‌طور ادامه بده.')


class FormCheckTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(phone_number='09120000030', password='x')
        self.user.token_balance = 30
        self.user.save(update_fields=['token_balance'])
        self.client.force_authenticate(user=self.user)
        PlatformSettings.objects.all().delete()
        self.cfg = PlatformSettings.objects.create(
            form_check_enabled=True, form_check_token_cost=0,
            form_check_max_frames=3, form_check_store_frames=False,
        )
        self.ex = ExerciseLibrary.objects.create(
            external_id='9100', name='Barbell Squat', name_fa='اسکوات با هالتر',
            equipment_fa='هالتر', target_fa='پا',
            steps_fa=['کمر را صاف نگه دار.', 'زانو از پنجهٔ پا جلوتر نرود.'],
            is_active=True,
        )

    # ---------------- خاموش بودن ----------------
    def test_everything_hidden_when_disabled(self):
        self.cfg.form_check_enabled = False
        self.cfg.save()
        self.assertEqual(self.client.get(url('form-check-info', '9100')).status_code, 404)
        self.assertEqual(self.client.post(url('form-check-start', '9100')).status_code, 404)
        # صفحهٔ وب هم نباید باز شود
        web = self.client.get(url('form-check-page', '9100'))
        self.assertIn(web.status_code, (302, 404))
        # و دکمه‌اش در صفحهٔ آموزش نباشد
        page = self.client.get(url('exercise-detail', '9100'))
        self.assertNotContains(page, 'بررسیِ درستیِ حرکت با دوربین')

    def test_button_shows_when_enabled(self):
        page = self.client.get(url('exercise-detail', '9100'))
        self.assertContains(page, 'بررسیِ درستیِ حرکت با دوربین')

    # ---------------- کارِ اصلی ----------------
    def test_info(self):
        res = self.client.get(url('form-check-info', '9100'))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data['enabled'])
        self.assertEqual(res.data['exercise']['name_fa'], 'اسکوات با هالتر')
        self.assertEqual(len(res.data['exercise']['steps_fa']), 2)
        self.assertEqual([c['value'] for c in res.data['cameras']], ['front', 'back'])

    def test_frame_verdicts_and_counters(self):
        start = self.client.post(url('form-check-start', '9100'), {'camera': 'front'}, format='json')
        self.assertEqual(start.status_code, 201, start.data)
        sid = start.data['session_id']
        self.assertEqual(FormCheckSession.objects.get(pk=sid).camera, 'front')

        with mock.patch('app.form_check.check_frame', return_value=FAKE_BAD):
            res = self.client.post(url('form-check-frame', sid), {'frame': a_frame()},
                                   format='multipart')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['verdict'], 'bad')
        self.assertEqual(res.data['color'], 'red')
        self.assertIn('کمرت', res.data['message'])
        self.assertEqual(res.data['box']['w'], 0.7)
        self.assertEqual(res.data['frames_left'], 2)

        with mock.patch('app.form_check.check_frame', return_value=FAKE_OK):
            res = self.client.post(url('form-check-frame', sid), {'frame': a_frame()},
                                   format='multipart')
        self.assertEqual(res.data['color'], 'green')

        session = FormCheckSession.objects.get(pk=sid)
        self.assertEqual((session.frames_checked, session.ok_count, session.bad_count), (2, 1, 1))
        self.assertEqual(FormCheckFrame.objects.filter(session=session).count(), 2)
        self.assertFalse(any(f.image for f in FormCheckFrame.objects.all()),
                         'پیش‌فرض نباید عکسِ ورزشکار ذخیره شود')

    def test_frame_limit(self):
        sid = self.client.post(url('form-check-start', '9100')).data['session_id']
        with mock.patch('app.form_check.check_frame', return_value=FAKE_OK):
            for _ in range(3):
                self.client.post(url('form-check-frame', sid), {'frame': a_frame()},
                                 format='multipart')
            res = self.client.post(url('form-check-frame', sid), {'frame': a_frame()},
                                   format='multipart')
        self.assertEqual(res.status_code, 429, res.data)
        self.assertTrue(res.data['limit_reached'])

    def test_store_frames_flag(self):
        self.cfg.form_check_store_frames = True
        self.cfg.save()
        sid = self.client.post(url('form-check-start', '9100')).data['session_id']
        with mock.patch('app.form_check.check_frame', return_value=FAKE_OK):
            self.client.post(url('form-check-frame', sid), {'frame': a_frame()}, format='multipart')
        self.assertTrue(FormCheckFrame.objects.get().image)

    def test_token_cost_and_finish_ledger(self):
        self.cfg.form_check_token_cost = 5
        self.cfg.save()
        start = self.client.post(url('form-check-start', '9100'))
        self.assertEqual(start.data['charged_tokens'], 5)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 25)
        sid = start.data['session_id']
        self.assertTrue(LedgerEntry.objects.filter(
            entry_type=LedgerEntry.TYPE_TOKEN_SPEND, reference='formcheck#%s' % sid).exists())

        with mock.patch('app.form_check.check_frame', return_value=FAKE_OK):
            self.client.post(url('form-check-frame', sid), {'frame': a_frame()}, format='multipart')
        res = self.client.post(url('form-check-finish', sid))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['ok_count'], 1)
        self.assertEqual(res.data['ok_percent'], 100)
        self.assertIn('مربی', res.data['note'])

    def test_no_tokens(self):
        self.cfg.form_check_token_cost = 50
        self.cfg.save()
        res = self.client.post(url('form-check-start', '9100'))
        self.assertEqual(res.status_code, 402, res.data)
        self.assertEqual(FormCheckSession.objects.count(), 0)

    def test_other_users_session(self):
        sid = self.client.post(url('form-check-start', '9100')).data['session_id']
        other = CustomUser.objects.create_user(phone_number='09120000031', password='x')
        self.client.force_authenticate(user=other)
        res = self.client.post(url('form-check-frame', sid), {'frame': a_frame()}, format='multipart')
        self.assertEqual(res.status_code, 404)

    def test_missing_frame(self):
        sid = self.client.post(url('form-check-start', '9100')).data['session_id']
        res = self.client.post(url('form-check-frame', sid), {}, format='multipart')
        self.assertEqual(res.status_code, 400)

    def test_unknown_exercise(self):
        self.assertEqual(self.client.get(url('form-check-info', '0000')).status_code, 404)
