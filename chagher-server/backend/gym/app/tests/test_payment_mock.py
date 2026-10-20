# -*- coding: utf-8 -*-
"""تست‌های درگاه پرداخت تستی (mock) — فلوی کامل خرید → درگاه → کال‌بک → شارژ"""
from decimal import Decimal

from django.test import override_settings
from rest_framework import status

from app.models import PaymentGatewayConfig, TokenPackage, TokenPurchase
from app.payment_gateway import MockGateway, PaymentGateway
from .utils import BaseAPITestCase, create_user

CALLBACK = 'http://testserver/api/payment-callback/'


def create_mock_config(**kwargs):
    """درگاه تستی فعال"""
    defaults = {
        'gateway_type': 'mock',
        'merchant_id': '',
        'callback_url': CALLBACK,
        'is_sandbox': True,
        'is_active': True,
    }
    defaults.update(kwargs)
    return PaymentGatewayConfig.objects.create(**defaults)


@override_settings(ALLOW_MOCK_PAYMENT_GATEWAY=True)
class MockGatewayUnitTests(BaseAPITestCase):
    """رفتار خود کلاس MockGateway"""

    def setUp(self):
        self.gateway = MockGateway(create_mock_config())

    def test_factory_returns_mock_gateway(self):
        self.assertIsInstance(PaymentGateway.get_active_gateway(), MockGateway)

    def test_create_payment_returns_local_simulator_url(self):
        result = self.gateway.create_payment(Decimal('200000'), 'تست')
        self.assertTrue(result['success'])
        self.assertTrue(result['authority'].startswith('MOCK-'))
        self.assertIn('/api/mock-payment/?Authority=', result['payment_url'])
        self.assertIn(result['authority'], result['payment_url'])

    def test_verify_accepts_own_authority_only(self):
        own = self.gateway.create_payment(Decimal('1000'), 'تست')['authority']
        self.assertTrue(self.gateway.verify_payment(own, amount=Decimal('1000'))['success'])
        self.assertFalse(self.gateway.verify_payment('AUTH-FROM-ELSEWHERE')['success'])

    def test_create_payment_needs_callback_url(self):
        gateway = MockGateway(create_mock_config(callback_url='', is_active=False))
        self.assertFalse(gateway.create_payment(Decimal('1000'), 'تست')['success'])

    @override_settings(ALLOW_MOCK_PAYMENT_GATEWAY=False)
    def test_disabled_when_flag_is_off(self):
        """روی production بدون فلگ صریح، درگاه تستی توکن رایگان نمی‌دهد"""
        self.assertFalse(self.gateway.create_payment(Decimal('1000'), 'تست')['success'])
        self.assertFalse(self.gateway.verify_payment('MOCK-ABC')['success'])


@override_settings(ALLOW_MOCK_PAYMENT_GATEWAY=True)
class MockPaymentEndToEndTests(BaseAPITestCase):
    """فلوی کاملی که کاربر در محیط تست طی می‌کند"""

    def setUp(self):
        create_mock_config()
        self.user = create_user(phone='09121234567')
        TokenPackage.objects.create(
            name='پایه', token_amount=50, price_per_50_tokens=Decimal('100000')
        )
        self.auth(self.user)

    def _purchase(self, token_amount=100):
        response = self.client.post('/api/purchase-token/', {'token_amount': token_amount})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def test_successful_test_payment_credits_tokens(self):
        response = self._purchase()
        purchase_id = response.data['purchase_id']
        self.assertIn('/api/mock-payment/', response.data['payment_url'])

        authority = TokenPurchase.objects.get(pk=purchase_id).payment_authority

        # صفحه شبیه‌ساز درگاه بالا می‌آید
        page = self.client.get('/api/mock-payment/', {'Authority': authority})
        self.assertEqual(page.status_code, status.HTTP_200_OK)
        self.assertContains(page, authority)

        # کاربر «پرداخت موفق» را می‌زند → بازگشت به کال‌بک با Status=OK
        callback = self.client.get('/api/payment-callback/', {'Authority': authority, 'Status': 'OK'})
        self.assertEqual(callback.status_code, status.HTTP_200_OK)
        self.assertEqual(callback.data['tokens_added'], 100)

        self.user.refresh_from_db()
        purchase = TokenPurchase.objects.get(pk=purchase_id)
        self.assertEqual(self.user.token_balance, 100)
        self.assertEqual(purchase.status, 'paid')
        self.assertTrue(purchase.payment_ref_id.startswith('MOCKREF'))

    def test_cancelled_test_payment_does_not_credit(self):
        purchase_id = self._purchase().data['purchase_id']
        authority = TokenPurchase.objects.get(pk=purchase_id).payment_authority

        callback = self.client.get('/api/payment-callback/', {'Authority': authority, 'Status': 'NOK'})
        self.assertEqual(callback.status_code, status.HTTP_400_BAD_REQUEST)

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)
        self.assertEqual(TokenPurchase.objects.get(pk=purchase_id).status, 'failed')

    def test_repeated_callback_credits_once(self):
        purchase_id = self._purchase().data['purchase_id']
        authority = TokenPurchase.objects.get(pk=purchase_id).payment_authority

        for _ in range(3):
            self.client.get('/api/payment-callback/', {'Authority': authority, 'Status': 'OK'})

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100)

    def test_browser_gets_html_result_page_api_client_gets_json(self):
        """درگاه واقعی مرورگر کاربر را برمی‌گرداند — نباید صفحه دیباگ DRF ببیند"""
        purchase_id = self._purchase().data['purchase_id']
        authority = TokenPurchase.objects.get(pk=purchase_id).payment_authority

        browser = self.client.get(
            '/api/payment-callback/', {'Authority': authority, 'Status': 'OK'},
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        )
        self.assertEqual(browser.status_code, status.HTTP_200_OK)
        self.assertEqual(browser['Content-Type'].split(';')[0], 'text/html')
        self.assertContains(browser, 'نتیجه پرداخت')
        self.assertNotContains(browser, 'Django REST framework')

        # کلاینت API همچنان JSON می‌گیرد
        api = self.client.get('/api/payment-callback/', {'Authority': authority, 'Status': 'OK'})
        self.assertEqual(api['Content-Type'].split(';')[0], 'application/json')

    def test_browser_gets_html_page_for_failed_payment(self):
        purchase_id = self._purchase().data['purchase_id']
        authority = TokenPurchase.objects.get(pk=purchase_id).payment_authority

        response = self.client.get(
            '/api/payment-callback/', {'Authority': authority, 'Status': 'NOK'},
            HTTP_ACCEPT='text/html,*/*;q=0.8',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response['Content-Type'].split(';')[0], 'text/html')
        self.assertContains(response, 'پرداخت ناموفق بود یا لغو شد.', status_code=400)

    def test_simulator_page_rejects_unknown_authority(self):
        self.assertEqual(
            self.client.get('/api/mock-payment/', {'Authority': 'MOCK-DOESNOTEXIST'}).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get('/api/mock-payment/', {'Authority': 'NOT-A-MOCK-CODE'}).status_code,
            status.HTTP_404_NOT_FOUND,
        )


@override_settings(ALLOW_MOCK_PAYMENT_GATEWAY=True)
class MockSimulatorAvailabilityTests(BaseAPITestCase):
    """صفحه شبیه‌ساز فقط وقتی درگاه تستی فعال است در دسترس است"""

    def test_hidden_when_no_gateway_active(self):
        self.assertEqual(
            self.client.get('/api/mock-payment/', {'Authority': 'MOCK-ABC'}).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_hidden_when_real_gateway_active(self):
        PaymentGatewayConfig.objects.create(
            gateway_type='zarinpal', merchant_id='xxxx', callback_url=CALLBACK, is_active=True
        )
        self.assertEqual(
            self.client.get('/api/mock-payment/', {'Authority': 'MOCK-ABC'}).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    @override_settings(ALLOW_MOCK_PAYMENT_GATEWAY=False)
    def test_hidden_when_flag_is_off(self):
        create_mock_config()
        self.assertEqual(
            self.client.get('/api/mock-payment/', {'Authority': 'MOCK-ABC'}).status_code,
            status.HTTP_404_NOT_FOUND,
        )
