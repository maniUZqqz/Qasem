"""
سیستم درگاه پرداخت با Factory Pattern
پشتیبانی از درگاه‌های مختلف ایرانی + یک درگاه تستی داخلی (mock)
"""
import secrets
import requests
import logging
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings

from .models import PaymentGatewayConfig

logger = logging.getLogger(__name__)


def mock_gateway_allowed():
    """آیا اجازه استفاده از درگاه تستی وجود دارد؟

    مقدارش از settings.ALLOW_MOCK_PAYMENT_GATEWAY می‌آید: در توسعه روشن،
    در production فقط با DJANGO_ALLOW_MOCK_GATEWAY=1 — تا سروری که اشتباهاً
    روی درگاه تستی مانده، توکن رایگان تحویل ندهد.
    """
    return bool(getattr(settings, 'ALLOW_MOCK_PAYMENT_GATEWAY', getattr(settings, 'DEBUG', False)))


class PaymentGateway:
    """Factory برای ایجاد درگاه پرداخت مناسب"""

    @staticmethod
    def get_active_gateway():
        """دریافت درگاه فعال از دیتابیس"""
        config = PaymentGatewayConfig.get_active_gateway()
        if not config:
            logger.warning("No active payment gateway configured")
            return None

        gateway_map = {
            'mock': MockGateway,
            'zarinpal': ZarinpalGateway,
            'idpay': IDPayGateway,
            'nextpay': NextPayGateway,
            'zibal': ZibalGateway,
            'mellat': MellatGateway,
            'saman': SamanGateway,
        }

        gateway_class = gateway_map.get(config.gateway_type)
        if gateway_class:
            return gateway_class(config)

        logger.error(f"Unknown gateway type: {config.gateway_type}")
        return None


def _result_data(result):
    """بخش data پاسخ درگاه را همیشه به شکل dict برمی‌گرداند.

    زرین‌پال در پاسخ‌های خطا "data": [] می‌فرستد؛ فراخوانی .get روی list
    باعث AttributeError می‌شد و خطای واقعی درگاه پشت پیام «خطا در اتصال» گم می‌شد.
    """
    data = result.get('data') if isinstance(result, dict) else None
    return data if isinstance(data, dict) else {}


def _error_message(errors, default='خطای ناشناخته'):
    """پیام خطای درگاه را از ساختارهای مختلف بیرون می‌کشد.

    زرین‌پال بسته به نوع خطا، errors را dict یا list of dict برمی‌گرداند؛
    خواندن مستقیم .get روی list باعث AttributeError و پیام گمراه‌کننده
    «خطا در اتصال به درگاه» می‌شد.
    """
    if isinstance(errors, dict):
        return errors.get('message') or default
    if isinstance(errors, (list, tuple)) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return first.get('message') or default
        return str(first)
    return default


class BaseGateway:
    """کلاس پایه برای تمام درگاه‌ها"""

    def __init__(self, config):
        self.config = config
        self.merchant_id = config.merchant_id
        self.api_key = config.api_key
        self.callback_url = config.callback_url
        self.is_sandbox = config.is_sandbox

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش پرداخت - باید در کلاس‌های فرزند پیاده‌سازی شود"""
        raise NotImplementedError

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت - باید در کلاس‌های فرزند پیاده‌سازی شود.

        order_id شماره سفارش خودمان است؛ بعضی درگاه‌ها (مثل آیدی‌پی)
        برای verify هم شناسه تراکنش و هم شماره سفارش را لازم دارند.
        """
        raise NotImplementedError

    def _convert_to_rials(self, tomans):
        """تبدیل تومان به ریال"""
        return int(tomans * 10)


class MockGateway(BaseGateway):
    """درگاه تستی داخلی (شبیه‌ساز).

    هیچ تماسی با سرویس خارجی ندارد و هیچ پولی جابه‌جا نمی‌شود؛ فقط برای
    تست کامل فلوی خرید → درگاه → کال‌بک → شارژ توکن روی محیط توسعه.
    برای رفتن به حالت واقعی کافی است در پنل ادمین درگاه واقعی را فعال کنید.
    """

    AUTHORITY_PREFIX = 'MOCK-'
    # صفحه شبیه‌ساز پرداخت که کاربر به آن هدایت می‌شود
    PAY_PAGE_PATH = 'mock-payment/'

    @classmethod
    def owns_authority(cls, authority):
        """آیا این شناسه تراکنش متعلق به درگاه تستی است؟"""
        return bool(authority) and str(authority).startswith(cls.AUTHORITY_PREFIX)

    def _pay_page_url(self, authority):
        """آدرس صفحه شبیه‌ساز، کنار همان callback_url ثبت‌شده.

        مثال: http://host/api/payment-callback/  →  http://host/api/mock-payment/
        """
        parts = urlsplit(self.callback_url)
        parent = parts.path.rstrip('/').rsplit('/', 1)[0]
        return urlunsplit((
            parts.scheme, parts.netloc, f'{parent}/{self.PAY_PAGE_PATH}',
            urlencode({'Authority': authority}), '',
        ))

    def create_payment(self, amount, description, metadata=None):
        """ساخت تراکنش تستی — بدون تماس شبکه‌ای"""
        if not mock_gateway_allowed():
            logger.error("Mock payment gateway is active but ALLOW_MOCK_PAYMENT_GATEWAY is off")
            return {
                'success': False,
                'error': 'درگاه تستی در حالت production غیرفعال است. '
                         'یک درگاه واقعی را در پنل ادمین فعال کنید یا '
                         'متغیر محیطی DJANGO_ALLOW_MOCK_GATEWAY=1 را تنظیم کنید.',
            }

        if not self.callback_url:
            return {
                'success': False,
                'error': 'برای درگاه تستی باید Callback URL در پنل ادمین تنظیم شود '
                         '(مثلاً http://localhost:8000/api/payment-callback/).',
            }

        authority = f"{self.AUTHORITY_PREFIX}{secrets.token_hex(12).upper()}"
        logger.info(
            f"MockGateway create_payment: authority={authority} amount={amount} desc={description}"
        )
        return {
            'success': True,
            'authority': authority,
            'payment_url': self._pay_page_url(authority),
            'is_mock': True,
        }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید تراکنش تستی.

        شناسه‌ای که خود ما ساخته‌ایم را می‌پذیریم؛ لغو/شکست پرداخت از مسیر
        Status=NOK در کال‌بک مدیریت می‌شود (دقیقاً مثل زرین‌پال).
        """
        if not mock_gateway_allowed():
            return {'success': False, 'error': 'درگاه تستی در حالت production غیرفعال است.'}

        if not self.owns_authority(authority):
            return {'success': False, 'error': 'شناسه تراکنش متعلق به درگاه تستی نیست.'}

        ref_id = f"MOCKREF{secrets.randbelow(10 ** 9):09d}"
        logger.info(f"MockGateway verify_payment OK: authority={authority} ref_id={ref_id} amount={amount}")
        return {
            'success': True,
            'ref_id': ref_id,
            'card_pan': '6037******1234',
            'is_mock': True,
        }


class ZarinpalGateway(BaseGateway):
    """درگاه زرین پال"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://sandbox.zarinpal.com/pg/v4/payment/' if self.is_sandbox else 'https://api.zarinpal.com/pg/v4/payment/'
        self.payment_url = 'https://sandbox.zarinpal.com/pg/StartPay/' if self.is_sandbox else 'https://www.zarinpal.com/pg/StartPay/'

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش در زرین پال"""
        try:
            # مبلغ به ریال
            amount_rials = self._convert_to_rials(amount)

            payload = {
                'merchant_id': self.merchant_id,
                'amount': amount_rials,
                'description': description,
                'callback_url': self.callback_url,
            }

            if metadata:
                payload['metadata'] = metadata

            response = requests.post(
                f'{self.base_url}request.json',
                json=payload,
                timeout=10
            )

            result = response.json()

            data = _result_data(result)
            if data.get('code') == 100:
                authority = data['authority']
                payment_url = f"{self.payment_url}{authority}"
                return {
                    'success': True,
                    'authority': authority,
                    'payment_url': payment_url,
                }
            else:
                return {
                    'success': False,
                    'error': _error_message(result.get('errors')),
                }

        except Exception as e:
            logger.error(f"ZarinPal create_payment error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در اتصال به درگاه: {str(e)}',
            }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت در زرین پال"""
        try:
            amount_rials = self._convert_to_rials(amount) if amount else 0

            payload = {
                'merchant_id': self.merchant_id,
                'amount': amount_rials,
                'authority': authority,
            }

            response = requests.post(
                f'{self.base_url}verify.json',
                json=payload,
                timeout=10
            )

            result = response.json()

            data = _result_data(result)
            if data.get('code') == 100:
                return {
                    'success': True,
                    'ref_id': data['ref_id'],
                    'card_pan': data.get('card_pan'),
                }
            else:
                return {
                    'success': False,
                    'error': _error_message(result.get('errors'), 'تراکنش ناموفق'),
                }

        except Exception as e:
            logger.error(f"ZarinPal verify_payment error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در تایید پرداخت: {str(e)}',
            }


class IDPayGateway(BaseGateway):
    """درگاه آیدی پی"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://api.idpay.ir/v1.1/'

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش در آیدی پی"""
        try:
            # مبلغ به ریال
            amount_rials = self._convert_to_rials(amount)

            headers = {
                'X-API-KEY': self.api_key,
                'Content-Type': 'application/json',
            }

            order_id = (metadata or {}).get('order_id')
            if not order_id:
                return {
                    'success': False,
                    'error': 'آیدی‌پی برای ایجاد تراکنش به order_id نیاز دارد.',
                }

            payload = {
                'order_id': str(order_id),
                'amount': amount_rials,
                'desc': description,
                'callback': self.callback_url,
            }

            response = requests.post(
                f'{self.base_url}payment',
                json=payload,
                headers=headers,
                timeout=10
            )

            result = response.json()

            if response.status_code == 201:
                return {
                    'success': True,
                    'authority': result['id'],
                    'payment_url': result['link'],
                    'order_id': str(order_id),
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error_message', 'خطای ناشناخته'),
                }

        except Exception as e:
            logger.error(f"IDPay create_payment error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در اتصال به درگاه: {str(e)}',
            }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت در آیدی پی"""
        try:
            headers = {
                'X-API-KEY': self.api_key,
                'Content-Type': 'application/json',
            }

            if not order_id:
                return {
                    'success': False,
                    'error': 'برای تایید تراکنش آیدی‌پی، شماره سفارش (order_id) لازم است.',
                }

            payload = {
                'id': authority,
                'order_id': str(order_id),
            }

            response = requests.post(
                f'{self.base_url}payment/verify',
                json=payload,
                headers=headers,
                timeout=10
            )

            result = response.json()

            if response.status_code == 200:
                return {
                    'success': True,
                    'ref_id': result['track_id'],
                    'card_pan': result.get('payment', {}).get('card_no'),
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error_message', 'تراکنش ناموفق'),
                }

        except Exception as e:
            logger.error(f"IDPay verify_payment error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در تایید پرداخت: {str(e)}',
            }


class NextPayGateway(BaseGateway):
    """درگاه نکست پی"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://nextpay.org/nx/gateway/'

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش در نکست پی"""
        try:
            amount_rials = self._convert_to_rials(amount)

            order_id = (metadata or {}).get('order_id')
            if not order_id:
                return {
                    'success': False,
                    'error': 'نکست‌پی برای ایجاد تراکنش به order_id نیاز دارد.',
                }

            payload = {
                'api_key': self.api_key,
                'amount': amount_rials,
                'order_id': str(order_id),
                'callback_uri': self.callback_url,
            }

            response = requests.post(
                f'{self.base_url}token',
                data=payload,
                timeout=10
            )

            result = response.json()

            if result.get('code') == -1:
                trans_id = result['trans_id']
                payment_url = f"https://nextpay.org/nx/gateway/payment/{trans_id}"
                return {
                    'success': True,
                    'authority': trans_id,
                    'payment_url': payment_url,
                }
            else:
                return {
                    'success': False,
                    'error': f"خطا: {result.get('code')}",
                }

        except Exception as e:
            logger.error(f"NextPay create_payment error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در اتصال به درگاه: {str(e)}',
            }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت در نکست پی"""
        try:
            amount_rials = self._convert_to_rials(amount) if amount else 0

            payload = {
                'api_key': self.api_key,
                'amount': amount_rials,
                'trans_id': authority,
            }

            response = requests.post(
                f'{self.base_url}verify',
                data=payload,
                timeout=10
            )

            result = response.json()

            if result.get('code') == 0:
                return {
                    'success': True,
                    'ref_id': result.get('Shaparak_Ref_Id'),
                    'card_pan': result.get('card_holder'),
                }
            else:
                return {
                    'success': False,
                    'error': f"خطا: {result.get('code')}",
                }

        except Exception as e:
            logger.error(f"NextPay verify_payment error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در تایید پرداخت: {str(e)}',
            }


class ZibalGateway(BaseGateway):
    """درگاه زیبال"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://gateway.zibal.ir/v1/'

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش در زیبال"""
        # پیاده‌سازی مشابه سایر درگاه‌ها
        return {
            'success': False,
            'error': 'درگاه زیبال هنوز پیاده‌سازی نشده است. لطفاً از درگاه دیگری استفاده کنید.',
        }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت در زیبال"""
        return {
            'success': False,
            'error': 'درگاه زیبال هنوز پیاده‌سازی نشده است.',
        }


class MellatGateway(BaseGateway):
    """درگاه بانک ملت"""

    def __init__(self, config):
        super().__init__(config)
        # پیاده‌سازی SOAP برای ملت نیاز به کتابخانه zeep دارد

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش در بانک ملت"""
        return {
            'success': False,
            'error': 'درگاه ملت هنوز پیاده‌سازی نشده است. لطفاً از درگاه دیگری استفاده کنید.',
        }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت در بانک ملت"""
        return {
            'success': False,
            'error': 'درگاه ملت هنوز پیاده‌سازی نشده است.',
        }


class SamanGateway(BaseGateway):
    """درگاه بانک سامان"""

    def __init__(self, config):
        super().__init__(config)

    def create_payment(self, amount, description, metadata=None):
        """ایجاد تراکنش در بانک سامان"""
        return {
            'success': False,
            'error': 'درگاه سامان هنوز پیاده‌سازی نشده است. لطفاً از درگاه دیگری استفاده کنید.',
        }

    def verify_payment(self, authority, amount=None, order_id=None):
        """تایید پرداخت در بانک سامان"""
        return {
            'success': False,
            'error': 'درگاه سامان هنوز پیاده‌سازی نشده است.',
        }
