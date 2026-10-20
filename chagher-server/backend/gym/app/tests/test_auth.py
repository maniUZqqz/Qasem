# -*- coding: utf-8 -*-
"""تست‌های API احراز هویت و پروفایل کاربر"""
from datetime import timedelta

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from app.models import CustomUser, PasswordResetOTP
from .utils import BaseAPITestCase, create_user


class RegisterAPITests(BaseAPITestCase):
    url = '/api/auth/register/'

    def test_register_success(self):
        # ثبت‌نام از زمانی که کدِ پیامکی اجباری شد، بدونِ کد رد می‌شود؛
        # کد را همان‌جایی می‌گیریم که خودِ سامانه می‌سازد.
        from app.sms_hook import issue_registration_code
        code = issue_registration_code('09121234567')
        response = self.client.post(self.url, {
            'phone_number': '09121234567',
            'password': 'StrongPass123',
            'password_confirm': 'StrongPass123',
            'gym_name': 'باشگاه تست',
            'verification_code': code,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertTrue(CustomUser.objects.filter(phone_number='09121234567').exists())

    def test_register_duplicate_phone(self):
        create_user(phone='09121234567')
        response = self.client.post(self.url, {
            'phone_number': '09121234567',
            'password': 'StrongPass123',
            'password_confirm': 'StrongPass123',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_password_mismatch(self):
        response = self.client.post(self.url, {
            'phone_number': '09121234567',
            'password': 'StrongPass123',
            'password_confirm': 'DifferentPass123',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password(self):
        response = self.client.post(self.url, {
            'phone_number': '09121234567',
            'password': 'short',
            'password_confirm': 'short',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginAPITests(BaseAPITestCase):
    url = '/api/auth/login/'

    def setUp(self):
        self.user = create_user(phone='09121234567', password='StrongPass123')

    def test_login_success(self):
        response = self.client.post(self.url, {
            'phone_number': '09121234567',
            'password': 'StrongPass123',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

    def test_login_wrong_password(self):
        response = self.client.post(self.url, {
            'phone_number': '09121234567',
            'password': 'WrongPass123',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_deletes_token(self):
        self.auth(self.user)
        response = self.client.post('/api/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Token.objects.filter(user=self.user).exists())

    def test_logout_requires_auth(self):
        response = self.client.post('/api/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PasswordResetAPITests(BaseAPITestCase):
    """بازیابی رمز فقط با کد OTP پیامکی — بدون کد معتبر هیچ رمزی عوض نمی‌شود"""
    request_url = '/api/auth/password-reset/'
    confirm_url = '/api/auth/password-reset/confirm/'

    def setUp(self):
        self.user = create_user(phone='09121234567', password='OldPass1234')

    def _request_code(self, phone='09121234567'):
        return self.client.post(self.request_url, {'phone_number': phone})

    def test_full_reset_flow_with_otp(self):
        response = self._request_code()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        otp = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        response = self.client.post(self.confirm_url, {
            'phone_number': '09121234567',
            'code': otp.code,
            'new_password': 'NewPass1234',
            'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass1234'))

    def test_code_is_single_use(self):
        self._request_code()
        otp = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        payload = {
            'phone_number': '09121234567',
            'code': otp.code,
            'new_password': 'NewPass1234',
            'new_password_confirm': 'NewPass1234',
        }
        self.client.post(self.confirm_url, payload)
        response = self.client.post(self.confirm_url, {**payload, 'new_password': 'OtherPass1234',
                                                       'new_password_confirm': 'OtherPass1234'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_wrong_code_rejected_and_password_unchanged(self):
        self._request_code()
        response = self.client.post(self.confirm_url, {
            'phone_number': '09121234567',
            'code': '0000',
            'new_password': 'NewPass1234',
            'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass1234'))

    def test_code_blocked_after_max_attempts(self):
        self._request_code()
        otp = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        wrong = '0000' if otp.code != '0000' else '1111'
        for _ in range(PasswordResetOTP.MAX_ATTEMPTS):
            self.client.post(self.confirm_url, {
                'phone_number': '09121234567', 'code': wrong,
                'new_password': 'NewPass1234', 'new_password_confirm': 'NewPass1234',
            })
        # حتی کد درست هم بعد از سقف تلاش پذیرفته نمی‌شود
        response = self.client.post(self.confirm_url, {
            'phone_number': '09121234567', 'code': otp.code,
            'new_password': 'NewPass1234', 'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass1234'))

    def test_expired_code_rejected(self):
        self._request_code()
        otp = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        expired_time = timezone.now() - timedelta(minutes=PasswordResetOTP.OTP_EXPIRY_MINUTES + 1)
        PasswordResetOTP.objects.filter(pk=otp.pk).update(created_at=expired_time)
        response = self.client.post(self.confirm_url, {
            'phone_number': '09121234567', 'code': otp.code,
            'new_password': 'NewPass1234', 'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_phone_gets_generic_success(self):
        """پاسخ برای شماره ناموجود هم 200 است تا وجود حساب افشا نشود"""
        response = self._request_code(phone='09999999999')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(PasswordResetOTP.objects.count(), 0)

    def test_direct_reset_without_code_is_impossible(self):
        """قرارداد ناامن قبلی (تغییر رمز بدون کد) دیگر کار نمی‌کند"""
        response = self.client.post(self.request_url, {
            'phone_number': '09121234567',
            'new_password': 'HackedPass1234',
            'new_password_confirm': 'HackedPass1234',
        })
        # مرحله اول فقط کد می‌فرستد؛ رمز دست‌نخورده می‌ماند
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass1234'))

    def test_reset_invalidates_existing_tokens(self):
        token = Token.objects.create(user=self.user)
        self._request_code()
        otp = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        self.client.post(self.confirm_url, {
            'phone_number': '09121234567', 'code': otp.code,
            'new_password': 'NewPass1234', 'new_password_confirm': 'NewPass1234',
        })
        self.assertFalse(Token.objects.filter(key=token.key).exists())

    def test_new_request_invalidates_previous_code(self):
        self._request_code()
        first = PasswordResetOTP.objects.get(user=self.user, is_used=False)
        self._request_code()
        first.refresh_from_db()
        self.assertTrue(first.is_used)
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user, is_used=False).count(), 1)


@override_settings(DISABLE_API_THROTTLING=False)
class AuthThrottleTests(APITestCase):
    """محدودسازی نرخ روی endpoint های حساس (ضد brute-force)"""

    def setUp(self):
        cache.clear()
        create_user(phone='09121234567', password='StrongPass123')

    def tearDown(self):
        cache.clear()

    def test_login_throttled_after_limit(self):
        # نرخ login: 10/min — درخواست یازدهم باید 429 بگیرد
        for _ in range(10):
            response = self.client.post('/api/auth/login/', {
                'phone_number': '09121234567', 'password': 'WrongPass',
            })
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post('/api/auth/login/', {
            'phone_number': '09121234567', 'password': 'WrongPass',
        })
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_client_access_throttled(self):
        # نرخ client-access: 30/hour — جلوی حدس زدن کد را می‌گیرد
        for _ in range(30):
            self.client.post('/api/client-access/', {'access_code': '123456'})
        response = self.client.post('/api/client-access/', {'access_code': '123456'})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class ChangePasswordAPITests(BaseAPITestCase):
    url = '/api/auth/change-password/'

    def setUp(self):
        self.user = create_user(phone='09121234567', password='OldPass1234')

    def test_requires_auth(self):
        response = self.client.post(self.url, {
            'old_password': 'OldPass1234',
            'new_password': 'NewPass1234',
            'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_success_rotates_token(self):
        self.auth(self.user)
        old_token = Token.objects.get(user=self.user).key

        response = self.client.post(self.url, {
            'old_password': 'OldPass1234',
            'new_password': 'NewPass1234',
            'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertNotEqual(response.data['token'], old_token)

        # رمز جدید اعمال شده
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass1234'))

        # توکن قبلی باطل شده و توکن جدید کار می‌کند
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {old_token}')
        self.assertEqual(
            self.client.get('/api/user/profile/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        self.assertEqual(
            self.client.get('/api/user/profile/').status_code,
            status.HTTP_200_OK,
        )

    def test_wrong_old_password(self):
        self.auth(self.user)
        response = self.client.post(self.url, {
            'old_password': 'WrongPass1234',
            'new_password': 'NewPass1234',
            'new_password_confirm': 'NewPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('old_password', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass1234'))

    def test_new_password_mismatch(self):
        self.auth(self.user)
        response = self.client.post(self.url, {
            'old_password': 'OldPass1234',
            'new_password': 'NewPass1234',
            'new_password_confirm': 'DifferentPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_new_password_same_as_old(self):
        self.auth(self.user)
        response = self.client.post(self.url, {
            'old_password': 'OldPass1234',
            'new_password': 'OldPass1234',
            'new_password_confirm': 'OldPass1234',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_new_password_too_short(self):
        self.auth(self.user)
        response = self.client.post(self.url, {
            'old_password': 'OldPass1234',
            'new_password': 'short',
            'new_password_confirm': 'short',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserProfileAPITests(BaseAPITestCase):
    url = '/api/user/profile/'

    def setUp(self):
        self.user = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.user.token_balance = 75
        self.user.save()

    def test_profile_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_profile(self):
        self.auth(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['phone_number'], '09121234567')
        self.assertEqual(response.data['token_balance'], 75)

    def test_patch_profile(self):
        self.auth(self.user)
        response = self.client.patch(self.url, {'gym_name': 'باشگاه جدید'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.gym_name, 'باشگاه جدید')
