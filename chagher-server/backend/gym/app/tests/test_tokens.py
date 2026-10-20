# -*- coding: utf-8 -*-
"""تست‌های خرید توکن، کد تخفیف، کال‌بک پرداخت، مشتریان باشگاه و درخواست توکن"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.utils import timezone
from rest_framework import status

from app.models import (
    CustomUser, DiscountCode, GymClient, PlatformSettings, TokenPackage, TokenPurchase,
    TokenRequest,
)
from .utils import BaseAPITestCase, create_user


def _mock_gateway(verify_success=True, ref_id='REF123'):
    """درگاه پرداخت ساختگی برای تست verify"""
    gateway = MagicMock()
    gateway.create_payment.return_value = {
        'success': True, 'authority': 'AUTH123', 'payment_url': 'https://gateway.test/pay/AUTH123',
    }
    if verify_success:
        gateway.verify_payment.return_value = {'success': True, 'ref_id': ref_id}
    else:
        gateway.verify_payment.return_value = {'success': False, 'error': 'تراکنش ناموفق'}
    return gateway


class PurchaseTokenAPITests(BaseAPITestCase):
    url = '/api/purchase-token/'

    def setUp(self):
        self.user = create_user(phone='09121234567')
        self.package = TokenPackage.objects.create(
            name='پایه', token_amount=50, price_per_50_tokens=Decimal('100000')
        )
        self.auth(self.user)

    def test_purchase_creates_pending_order(self):
        response = self.client.post(self.url, {'token_amount': 100})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['final_price'], 200000.0)

        purchase = TokenPurchase.objects.get()
        self.assertEqual(purchase.status, 'pending')
        self.assertEqual(purchase.token_amount, 100)
        # توکن قبل از پرداخت اضافه نمی‌شود
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_amount_must_be_multiple_of_50(self):
        response = self.client.post(self.url, {'token_amount': 70})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_purchase_with_discount_code(self):
        creator = create_user(phone='09122222222')
        DiscountCode.objects.create(code='OFF10', discount_percent=10, creator=creator)
        response = self.client.post(self.url, {'token_amount': 100, 'discount_code': 'OFF10'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['discount_amount'], 20000.0)
        self.assertEqual(response.data['final_price'], 180000.0)

    def test_purchase_with_invalid_code(self):
        response = self.client.post(self.url, {'token_amount': 100, 'discount_code': 'NOPE'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_active_package(self):
        self.package.is_active = False
        self.package.save()
        response = self.client.post(self.url, {'token_amount': 100})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_gateway_returns_null_payment_url(self):
        """بدون درگاه فعال، لینک پرداخت ساختگی برنمی‌گردد"""
        response = self.client.post(self.url, {'token_amount': 100})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['payment_url'])

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_active_gateway_returns_payment_url_and_stores_authority(self, mock_get):
        mock_get.return_value = _mock_gateway()
        response = self.client.post(self.url, {'token_amount': 100})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['payment_url'], 'https://gateway.test/pay/AUTH123')

        purchase = TokenPurchase.objects.get()
        self.assertEqual(purchase.payment_authority, 'AUTH123')
        self.assertEqual(purchase.status, 'pending')

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_gateway_create_failure_marks_failed(self, mock_get):
        gateway = _mock_gateway()
        gateway.create_payment.return_value = {'success': False, 'error': 'خطا'}
        mock_get.return_value = gateway
        response = self.client.post(self.url, {'token_amount': 100})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(TokenPurchase.objects.get().status, 'failed')


class ValidateDiscountCodeAPITests(BaseAPITestCase):
    url = '/api/validate-discount-code/'

    def setUp(self):
        self.user = create_user(phone='09121234567')
        creator = create_user(phone='09122222222')
        DiscountCode.objects.create(code='OFF20', discount_percent=20, creator=creator)
        self.auth(self.user)

    def test_valid_code(self):
        response = self.client.post(self.url, {'code': 'OFF20', 'purchase_amount': '100000.00'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['valid'])
        self.assertEqual(response.data['final_price'], 80000.0)

    def test_unknown_code(self):
        response = self.client.post(self.url, {'code': 'NOPE', 'purchase_amount': '100000.00'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class PaymentCallbackAPITests(BaseAPITestCase):
    """کال‌بک پرداخت — بدون verify واقعی با درگاه هیچ توکنی شارژ نمی‌شود"""
    url = '/api/payment-callback/'

    def setUp(self):
        self.user = create_user(phone='09121234567')
        self.purchase = TokenPurchase.objects.create(
            user=self.user, token_amount=100,
            original_price=Decimal('200000'), final_price=Decimal('200000'),
            payment_authority='AUTH123',
        )

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_verified_success_marks_paid_and_adds_tokens(self, mock_get):
        mock_get.return_value = gateway = _mock_gateway()
        response = self.client.post(self.url, {'authority': 'AUTH123', 'status': 'OK'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.purchase.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.purchase.status, 'paid')
        self.assertEqual(self.purchase.payment_ref_id, 'REF123')
        self.assertEqual(self.user.token_balance, 100)
        gateway.verify_payment.assert_called_once_with(
            'AUTH123', amount=self.purchase.final_price, order_id=str(self.purchase.id)
        )

    def test_forged_callback_without_gateway_does_not_credit(self):
        """جعل کال‌بک با بدنه ساختگی (رفتار ناامن قبلی) دیگر توکن نمی‌دهد"""
        response = self.client.post(self.url, {
            'purchase_id': self.purchase.id, 'ref_id': 'FAKE', 'status': 'success',
        })
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.purchase.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.purchase.status, 'pending')
        self.assertEqual(self.user.token_balance, 0)

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_forged_status_still_requires_verify(self, mock_get):
        """حتی با status=success، بدون تایید درگاه شارژی انجام نمی‌شود"""
        mock_get.return_value = _mock_gateway(verify_success=False)
        response = self.client.post(self.url, {
            'purchase_id': self.purchase.id, 'status': 'success',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, 'failed')

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_callback_is_idempotent(self, mock_get):
        mock_get.return_value = _mock_gateway()
        for _ in range(2):
            self.client.post(self.url, {'authority': 'AUTH123'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100)  # فقط یکبار شارژ

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_gateway_declared_cancel_marks_failed_without_verify(self, mock_get):
        mock_get.return_value = gateway = _mock_gateway()
        response = self.client.get(self.url + '?Authority=AUTH123&Status=NOK')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, 'failed')
        gateway.verify_payment.assert_not_called()

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_mismatched_authority_rejected(self, mock_get):
        mock_get.return_value = _mock_gateway()
        response = self.client.post(self.url, {
            'purchase_id': self.purchase.id, 'authority': 'WRONG-AUTH',
        })
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_unknown_purchase(self):
        response = self.client.post(self.url, {'purchase_id': 9999, 'status': 'success'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class GymClientAPITests(BaseAPITestCase):
    def setUp(self):
        self.coach = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.coach.token_balance = 200
        self.coach.save()
        self.auth(self.coach)

    def test_create_client_generates_access_code(self):
        response = self.client.post('/api/gym-clients/', {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['access_code'])

    def test_client_access_activates_code(self):
        gym_client = GymClient.objects.create(gym_owner=self.coach)
        self.unauth()
        response = self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

        gym_client.refresh_from_db()
        self.assertTrue(gym_client.is_used)
        self.assertIsNotNone(gym_client.client_user)

    def test_client_access_reentry(self):
        gym_client = GymClient.objects.create(gym_owner=self.coach)
        self.unauth()
        self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        response = self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # کاربر جدیدی ساخته نشده
        self.assertEqual(CustomUser.objects.filter(client_profile__isnull=False).count(), 1)

    def test_client_access_invalid_code(self):
        self.unauth()
        response = self.client.post('/api/client-access/', {'access_code': '999999999999'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_adjust_tokens_reserves_pending_before_activation(self):
        gym_client = GymClient.objects.create(gym_owner=self.coach)
        url = f'/api/gym-clients/{gym_client.id}/adjust-tokens/'
        response = self.client.post(url, {'amount': 50})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        gym_client.refresh_from_db()
        self.coach.refresh_from_db()
        self.assertEqual(gym_client.pending_tokens, 50)
        self.assertEqual(self.coach.token_balance, 150)

        # فعال‌سازی کد → انتقال توکن‌های رزروشده
        self.unauth()
        self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        gym_client.refresh_from_db()
        self.assertEqual(gym_client.pending_tokens, 0)
        self.assertEqual(gym_client.client_user.token_balance, 50)

    def test_adjust_tokens_insufficient_coach_balance(self):
        gym_client = GymClient.objects.create(gym_owner=self.coach)
        url = f'/api/gym-clients/{gym_client.id}/adjust-tokens/'
        response = self.client.post(url, {'amount': 500})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_clients_scoped_to_owner(self):
        GymClient.objects.create(gym_owner=self.coach)
        other = create_user(phone='09127654321')
        self.auth(other)
        response = self.client.get('/api/gym-clients/')
        self.assertEqual(len(response.data), 0)


class AccessCodeExpiryTests(BaseAPITestCase):
    """کد دسترسی دوحالته: دائمی (پیش‌فرض) یا زمان‌دار با انقضای تعیین‌شده توسط مربی"""

    def setUp(self):
        self.coach = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.auth(self.coach)

    def test_default_code_is_permanent(self):
        response = self.client.post('/api/gym-clients/', {})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['access_code_expires_at'])
        self.assertFalse(response.data['access_code_is_expired'])

    def test_coach_sets_validity_days(self):
        response = self.client.post('/api/gym-clients/', {'access_code_validity_days': 7})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.data['access_code_expires_at'])

        gym_client = GymClient.objects.get()
        expected = timezone.now() + timedelta(days=7)
        self.assertAlmostEqual(
            gym_client.access_code_expires_at.timestamp(), expected.timestamp(), delta=60,
        )

    def test_valid_timed_code_activates(self):
        self.client.post('/api/gym-clients/', {'access_code_validity_days': 7})
        gym_client = GymClient.objects.get()
        self.unauth()
        response = self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expired_code_cannot_activate(self):
        gym_client = GymClient.objects.create(
            gym_owner=self.coach,
            access_code_expires_at=timezone.now() - timedelta(hours=1),
        )
        self.unauth()
        response = self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        gym_client.refresh_from_db()
        self.assertFalse(gym_client.is_used)

    def test_expired_code_blocks_reentry(self):
        gym_client = GymClient.objects.create(gym_owner=self.coach)
        self.unauth()
        self.client.post('/api/client-access/', {'access_code': gym_client.access_code})

        GymClient.objects.filter(pk=gym_client.pk).update(
            access_code_expires_at=timezone.now() - timedelta(hours=1)
        )
        response = self.client.post('/api/client-access/', {'access_code': gym_client.access_code})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_can_extend_validity(self):
        response = self.client.post('/api/gym-clients/', {'access_code_validity_days': 1})
        client_id = response.data['id']
        response = self.client.patch(f'/api/gym-clients/{client_id}/', {'access_code_validity_days': 30})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        gym_client = GymClient.objects.get(pk=client_id)
        expected = timezone.now() + timedelta(days=30)
        self.assertAlmostEqual(
            gym_client.access_code_expires_at.timestamp(), expected.timestamp(), delta=60,
        )

    def test_coach_can_make_code_permanent_with_zero(self):
        response = self.client.post('/api/gym-clients/', {'access_code_validity_days': 1})
        client_id = response.data['id']
        response = self.client.patch(f'/api/gym-clients/{client_id}/', {'access_code_validity_days': 0})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(GymClient.objects.get(pk=client_id).access_code_expires_at)

    def test_new_codes_use_configured_length(self):
        """پیش‌فرض ۴ رقم؛ با تغییر تنظیمات سامانه طول کد عوض می‌شود"""
        response = self.client.post('/api/gym-clients/', {})
        self.assertEqual(len(response.data['access_code']), 4)

        settings_obj = PlatformSettings.get_solo()
        settings_obj.access_code_length = 7
        settings_obj.save()

        response = self.client.post('/api/gym-clients/', {})
        self.assertEqual(len(response.data['access_code']), 7)


class TokenRequestAPITests(BaseAPITestCase):
    def setUp(self):
        self.coach = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.coach.token_balance = 200
        self.coach.save()
        self.gym_client = GymClient.objects.create(gym_owner=self.coach)

        # فعال‌سازی مشتری از طریق کد دسترسی
        response = self.client.post('/api/client-access/', {'access_code': self.gym_client.access_code})
        self.client_token = response.data['token']
        self.gym_client.refresh_from_db()
        self.client_user = self.gym_client.client_user

    def _auth_client(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.client_token}')

    def test_client_creates_request(self):
        self._auth_client()
        response = self.client.post('/api/token-requests/', {'requested_tokens': 50, 'message': 'لطفا'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TokenRequest.objects.get().status, 'pending')

    def test_request_more_than_coach_balance_rejected(self):
        self._auth_client()
        response = self.client.post('/api/token-requests/', {'requested_tokens': 500})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_cannot_be_patched_after_creation(self):
        """مشتری نمی‌تواند بعد از ثبت، تعداد توکن را با PATCH دور بزند"""
        self._auth_client()
        response = self.client.post('/api/token-requests/', {'requested_tokens': 50})
        request_id = response.data['id']

        response = self.client.patch(f'/api/token-requests/{request_id}/', {'requested_tokens': 5000})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(TokenRequest.objects.get().requested_tokens, 50)

        response = self.client.delete(f'/api/token-requests/{request_id}/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_coach_approves_request(self):
        self._auth_client()
        response = self.client.post('/api/token-requests/', {'requested_tokens': 50})
        request_id = response.data['id']

        self.auth(self.coach)
        response = self.client.post(f'/api/token-requests/{request_id}/respond/', {'action': 'approve'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.coach.refresh_from_db()
        self.client_user.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 150)
        self.assertEqual(self.client_user.token_balance, 50)

    def test_client_cannot_respond_to_own_request(self):
        self._auth_client()
        response = self.client.post('/api/token-requests/', {'requested_tokens': 50})
        request_id = response.data['id']

        response = self.client.post(f'/api/token-requests/{request_id}/respond/', {'action': 'approve'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_rejects_request(self):
        self._auth_client()
        response = self.client.post('/api/token-requests/', {'requested_tokens': 50})
        request_id = response.data['id']

        self.auth(self.coach)
        response = self.client.post(f'/api/token-requests/{request_id}/respond/', {
            'action': 'reject', 'response_message': 'فعلا نه',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(TokenRequest.objects.get().status, 'rejected')
        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 200)


class AccessCodeCountdownTests(BaseAPITestCase):
    """فرانت باید بداند کد دائمی است یا موقت، و برای موقت شمارش معکوس بگیرد."""

    def setUp(self):
        self.coach = create_user(phone='09121234567', gym_name='باشگاه تست')
        self.auth(self.coach)

    def _client_access(self, code):
        self.unauth()
        response = self.client.post('/api/client-access/', {'access_code': code})
        self.auth(self.coach)
        return response

    def test_permanent_code_has_no_countdown(self):
        response = self.client.post('/api/gym-clients/', {})
        self.assertTrue(response.data['access_code_is_permanent'])
        self.assertIsNone(response.data['access_code_remaining_seconds'])

    def test_timed_code_reports_remaining_seconds(self):
        response = self.client.post('/api/gym-clients/', {'access_code_validity_minutes': 10})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data['access_code_is_permanent'])
        remaining = response.data['access_code_remaining_seconds']
        self.assertGreater(remaining, 10 * 60 - 30)
        self.assertLessEqual(remaining, 10 * 60)

    def test_days_and_minutes_add_up(self):
        self.client.post('/api/gym-clients/', {
            'access_code_validity_days': 1, 'access_code_validity_minutes': 30,
        })
        gym_client = GymClient.objects.get()
        expected = timezone.now() + timedelta(days=1, minutes=30)
        self.assertAlmostEqual(
            gym_client.access_code_expires_at.timestamp(), expected.timestamp(), delta=60,
        )

    def test_countdown_shrinks_over_time(self):
        gym_client = GymClient.objects.create(
            gym_owner=self.coach,
            access_code_expires_at=timezone.now() + timedelta(minutes=10),
        )
        first = gym_client.access_code_remaining_seconds
        gym_client.access_code_expires_at -= timedelta(minutes=4)
        self.assertLess(gym_client.access_code_remaining_seconds, first)

    def test_expired_code_countdown_is_zero_not_negative(self):
        gym_client = GymClient.objects.create(
            gym_owner=self.coach,
            access_code_expires_at=timezone.now() - timedelta(hours=2),
        )
        self.assertEqual(gym_client.access_code_remaining_seconds, 0)
        self.assertFalse(gym_client.access_code_is_permanent)

    def test_client_access_response_carries_countdown(self):
        """ورزشکار هنگام وارد کردن کد، وضعیت و شمارش معکوس را می‌گیرد"""
        response = self.client.post('/api/gym-clients/', {'access_code_validity_minutes': 10})
        code = response.data['access_code']

        access = self._client_access(code)
        self.assertEqual(access.status_code, status.HTTP_200_OK)
        client_data = access.data['client']
        self.assertFalse(client_data['access_code_is_permanent'])
        self.assertGreater(client_data['access_code_remaining_seconds'], 0)

    def test_client_access_response_marks_permanent_code(self):
        response = self.client.post('/api/gym-clients/', {})
        access = self._client_access(response.data['access_code'])
        self.assertTrue(access.data['client']['access_code_is_permanent'])
        self.assertIsNone(access.data['client']['access_code_remaining_seconds'])

    def test_countdown_is_read_only(self):
        """فرانت نمی‌تواند تایمر را دستکاری کند"""
        response = self.client.post('/api/gym-clients/', {
            'access_code_validity_minutes': 10,
            'access_code_remaining_seconds': 999999,
            'access_code_is_permanent': True,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data['access_code_is_permanent'])
        self.assertLessEqual(response.data['access_code_remaining_seconds'], 10 * 60)
