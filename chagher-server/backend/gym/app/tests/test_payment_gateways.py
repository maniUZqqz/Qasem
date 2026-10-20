# -*- coding: utf-8 -*-
"""تست‌های واحد درگاه‌های واقعی — بدون تماس شبکه‌ای"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from app.models import PaymentGatewayConfig
from app.payment_gateway import IDPayGateway, NextPayGateway, ZarinpalGateway, _error_message


def config(gateway_type, **kwargs):
    defaults = {
        'gateway_type': gateway_type,
        'merchant_id': 'MERCHANT-TEST',
        'api_key': 'KEY-TEST',
        'callback_url': 'http://testserver/api/payment-callback/',
        'is_sandbox': True,
    }
    defaults.update(kwargs)
    return PaymentGatewayConfig(**defaults)


class ErrorMessageTests(TestCase):
    """زرین‌پال errors را گاهی dict و گاهی list برمی‌گرداند"""

    def test_dict_shape(self):
        self.assertEqual(_error_message({'message': 'مبلغ نامعتبر'}), 'مبلغ نامعتبر')

    def test_list_shape(self):
        self.assertEqual(_error_message([{'message': 'مرچنت نامعتبر'}]), 'مرچنت نامعتبر')

    def test_empty_falls_back_to_default(self):
        self.assertEqual(_error_message(None, 'تراکنش ناموفق'), 'تراکنش ناموفق')
        self.assertEqual(_error_message([], 'تراکنش ناموفق'), 'تراکنش ناموفق')


class ZarinpalErrorReportingTests(TestCase):
    def test_list_errors_reported_not_swallowed_as_connection_error(self):
        """قبلاً errorهای list باعث AttributeError و پیام گمراه‌کننده اتصال می‌شد"""
        gateway = ZarinpalGateway(config('zarinpal'))
        with patch('app.payment_gateway.requests.post') as post:
            post.return_value.json.return_value = {
                'data': [], 'errors': [{'code': -9, 'message': 'مرچنت نامعتبر است'}],
            }
            result = gateway.create_payment(Decimal('1000'), 'تست')

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'مرچنت نامعتبر است')


class OrderIdRequirementTests(TestCase):
    """آیدی‌پی/نکست‌پی بدون شماره سفارش کار نمی‌کنند"""

    def test_idpay_create_requires_order_id(self):
        result = IDPayGateway(config('idpay')).create_payment(Decimal('1000'), 'تست')
        self.assertFalse(result['success'])
        self.assertIn('order_id', result['error'])

    def test_idpay_verify_sends_real_order_id(self):
        gateway = IDPayGateway(config('idpay'))
        with patch('app.payment_gateway.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'track_id': 'TRK1', 'payment': {'card_no': '6037'}}
            result = gateway.verify_payment('IDPAY-ID', amount=Decimal('1000'), order_id='42')

        self.assertTrue(result['success'])
        self.assertEqual(post.call_args.kwargs['json']['order_id'], '42')
        self.assertEqual(post.call_args.kwargs['json']['id'], 'IDPAY-ID')

    def test_idpay_verify_without_order_id_fails_clearly(self):
        result = IDPayGateway(config('idpay')).verify_payment('IDPAY-ID', amount=Decimal('1000'))
        self.assertFalse(result['success'])
        self.assertIn('order_id', result['error'])

    def test_nextpay_create_requires_order_id(self):
        result = NextPayGateway(config('nextpay')).create_payment(Decimal('1000'), 'تست')
        self.assertFalse(result['success'])
        self.assertIn('order_id', result['error'])

    def test_nextpay_create_sends_order_id_from_metadata(self):
        gateway = NextPayGateway(config('nextpay'))
        with patch('app.payment_gateway.requests.post') as post:
            post.return_value.json.return_value = {'code': -1, 'trans_id': 'T1'}
            result = gateway.create_payment(Decimal('1000'), 'تست', metadata={'order_id': 7})

        self.assertTrue(result['success'])
        self.assertEqual(post.call_args.kwargs['data']['order_id'], '7')
