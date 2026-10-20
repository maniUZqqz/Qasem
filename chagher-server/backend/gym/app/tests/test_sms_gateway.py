# -*- coding: utf-8 -*-
"""تست‌های صف پیامک، API گیت‌وی (next-otp / mark-sent) و کد اضطراری ثبت‌نام"""
from datetime import timedelta

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from app.models import CustomUser, PasswordResetOTP, SMSOutbox
from .utils import BaseAPITestCase, create_user


@override_settings(SMS_RETURN_CODE_IN_RESPONSE=False, SMS_EMERGENCY_CODE='6985')
class SMSGatewayTests(BaseAPITestCase):
    phone = '09121234567'

    def setUp(self):
        cache.clear()

    def _register(self, code):
        return self.client.post('/api/auth/register/', {
            'phone_number': self.phone,
            'password': 'StrongPass123',
            'password_confirm': 'StrongPass123',
            'verification_code': code,
        })

    def test_send_code_queues_for_gateway(self):
        response = self.client.post('/api/auth/send-register-code/', {'phone_number': self.phone})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('debug', response.data)

        items = self.client.get('/api/next-otp').json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['phone'], self.phone)
        self.assertEqual(set(items[0]), {'id', 'phone', 'code'})

        # درخواستِ دوباره پیش از ارسال، ردیفِ تکراری نمی‌سازد
        self.client.post('/api/auth/send-register-code/', {'phone_number': self.phone})
        self.assertEqual(len(self.client.get('/api/next-otp').json()), 1)

        # کدِ گیت‌وی همان کدی است که ثبت‌نام را تایید می‌کند
        self.assertEqual(self._register(items[0]['code']).status_code, status.HTTP_201_CREATED)

    def test_mark_sent_removes_from_queue(self):
        item = SMSOutbox.enqueue(self.phone, '1234')
        response = self.client.post('/api/mark-sent', {'id': str(item.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(self.client.get('/api/next-otp').json(), [])
        item.refresh_from_db()
        self.assertTrue(item.sent)
        self.assertIsNotNone(item.sent_at)

    def test_mark_sent_errors(self):
        self.assertEqual(self.client.post('/api/mark-sent', {}, format='json').status_code, 400)
        self.assertEqual(
            self.client.post('/api/mark-sent', {'id': 'not-a-uuid'}, format='json').status_code, 404
        )
        self.assertEqual(
            self.client.post('/api/mark-sent', {'id': '00000000-0000-0000-0000-000000000000'},
                             format='json').status_code, 404
        )

    def test_trailing_slash_also_works(self):
        item = SMSOutbox.enqueue(self.phone, '1234')
        self.assertEqual(len(self.client.get('/api/next-otp/').json()), 1)
        response = self.client.post('/api/mark-sent/', {'id': str(item.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expired_items_not_given_to_gateway(self):
        item = SMSOutbox.enqueue(self.phone, '1234')
        SMSOutbox.objects.filter(pk=item.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/next-otp').json(), [])

    def test_emergency_code_registers(self):
        self.client.post('/api/auth/send-register-code/', {'phone_number': self.phone})
        self.assertEqual(self._register('6985').status_code, status.HTTP_201_CREATED)
        self.assertTrue(CustomUser.objects.filter(phone_number=self.phone).exists())

    def test_wrong_code_rejected(self):
        self.client.post('/api/auth/send-register-code/', {'phone_number': self.phone})
        real = self.client.get('/api/next-otp').json()[0]['code']
        wrong = '1111' if real != '1111' else '2222'
        self.assertEqual(self._register(wrong).status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(SMS_EMERGENCY_CODE='')
    def test_emergency_code_can_be_disabled(self):
        self.client.post('/api/auth/send-register-code/', {'phone_number': self.phone})
        self.assertEqual(self._register('6985').status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_code_queued(self):
        user = create_user(phone=self.phone)
        self.client.post('/api/auth/password-reset/', {'phone_number': self.phone})
        otp = PasswordResetOTP.objects.get(user=user, is_used=False)
        items = self.client.get('/api/next-otp').json()
        self.assertEqual([(i['phone'], i['code']) for i in items], [(self.phone, otp.code)])
