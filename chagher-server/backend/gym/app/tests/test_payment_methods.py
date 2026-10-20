# -*- coding: utf-8 -*-
"""روشن/خاموش بودن روش‌های پرداخت باید یک تصمیم پیکربندی باشد، نه کد کلاینت."""
from app.models import CardPaymentAccount, PaymentGatewayConfig
from app.tests.utils import BaseAPITestCase, create_user


class PaymentMethodsViewTests(BaseAPITestCase):
    url = '/api/payment-methods/'

    def setUp(self):
        self.user = create_user(phone='09121234567')
        self.auth(self.user)

    def _card(self):
        return CardPaymentAccount.objects.create(
            title='حساب اصلی',
            card_number='6037991234567890',
            card_holder='محمد اکبری',
            is_active=True,
        )

    def _gateway(self, gateway_type='zarinpal', active=True):
        return PaymentGatewayConfig.objects.create(
            gateway_type=gateway_type,
            merchant_id='m' * 36,
            callback_url='https://example.com/api/payment-callback/',
            is_active=active,
        )

    def test_requires_authentication(self):
        self.unauth()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_nothing_available_by_default(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['card']['available'])
        self.assertIsNone(response.data['card']['account'])
        self.assertFalse(response.data['gateway']['available'])
        self.assertFalse(response.data['gateway']['is_mock'])

    def test_card_becomes_available_once_configured(self):
        self._card()
        response = self.client.get(self.url)
        self.assertTrue(response.data['card']['available'])
        self.assertEqual(
            response.data['card']['account']['card_holder'], 'محمد اکبری'
        )

    def test_real_gateway_becomes_available_without_client_changes(self):
        """همان چیزی که باید روزی که درگاه واقعی ثبت شود اتفاق بیفتد."""
        self._gateway('zarinpal')
        response = self.client.get(self.url)
        self.assertTrue(response.data['gateway']['available'])
        self.assertFalse(response.data['gateway']['is_mock'])
        self.assertIn('زرین', response.data['gateway']['name'])

    def test_mock_gateway_is_never_offered_to_users(self):
        """درگاه تستی یک شبیه‌ساز است؛ نباید به کاربر نهایی پیشنهاد شود."""
        self._gateway('mock')
        response = self.client.get(self.url)
        self.assertFalse(response.data['gateway']['available'])
        self.assertTrue(response.data['gateway']['is_mock'])

    def test_deactivated_gateway_disappears(self):
        gateway = self._gateway('zarinpal')
        gateway.is_active = False
        gateway.save()
        response = self.client.get(self.url)
        self.assertFalse(response.data['gateway']['available'])

    def test_both_methods_can_be_offered_together(self):
        self._card()
        self._gateway('zarinpal')
        response = self.client.get(self.url)
        self.assertTrue(response.data['card']['available'])
        self.assertTrue(response.data['gateway']['available'])
