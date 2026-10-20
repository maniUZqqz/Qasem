"""
سیستم ارسال SMS با Factory Pattern
پشتیبانی از سرویس‌های مختلف ایرانی
"""
import requests
import logging
from .models import SMSConfig

logger = logging.getLogger(__name__)


class SMSService:
    """Factory برای ایجاد سرویس SMS مناسب"""

    @staticmethod
    def get_active_service():
        """دریافت سرویس فعال از دیتابیس"""
        config = SMSConfig.get_active_service()
        if not config:
            logger.warning("No active SMS service configured")
            return None

        service_map = {
            'farazsms': FarazSMSService,
            'kavenegar': KavenegarService,
            'ghasedak': GhasedakService,
            'melipayamak': MelipayamakService,
        }

        service_class = service_map.get(config.provider)
        if service_class:
            return service_class(config)

        logger.error(f"Unknown SMS provider: {config.provider}")
        return None


class BaseSMSService:
    """کلاس پایه برای تمام سرویس‌های SMS"""

    def __init__(self, config):
        self.config = config
        self.api_key = config.api_key
        self.sender_number = config.sender_number
        self.access_code_template = config.access_code_template
        self.token_approved_template = config.token_approved_template
        self.token_rejected_template = config.token_rejected_template

    def send_sms(self, phone_number, message):
        """ارسال پیامک - باید در کلاس‌های فرزند پیاده‌سازی شود"""
        raise NotImplementedError

    def send_access_code(self, phone_number, code, gym_name):
        """ارسال کد دسترسی"""
        message = self.access_code_template.format(code=code, gym_name=gym_name)
        return self.send_sms(phone_number, message)

    def send_token_approved(self, phone_number, tokens):
        """ارسال پیام تایید توکن"""
        message = self.token_approved_template.format(tokens=tokens)
        return self.send_sms(phone_number, message)

    def send_token_rejected(self, phone_number, reason):
        """ارسال پیام رد توکن"""
        message = self.token_rejected_template.format(reason=reason)
        return self.send_sms(phone_number, message)

    def send_password_reset_code(self, phone_number, code):
        """ارسال کد یکبارمصرف بازیابی رمز عبور"""
        template = getattr(self.config, 'password_reset_template', None) or 'کد بازیابی رمز عبور شما: {code}'
        return self.send_sms(phone_number, template.format(code=code))

    def _normalize_phone(self, phone_number):
        """نرمال‌سازی شماره تلفن"""
        # حذف کاراکترهای اضافی
        phone = phone_number.replace('+98', '0').replace(' ', '').replace('-', '')
        # اطمینان از شروع با 09
        if not phone.startswith('09'):
            if phone.startswith('9'):
                phone = '0' + phone
        return phone


class FarazSMSService(BaseSMSService):
    """سرویس فراز اس ام اس"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://api.ippanel.com/v1/'

    def send_sms(self, phone_number, message):
        """ارسال پیامک با فراز اس ام اس"""
        try:
            phone = self._normalize_phone(phone_number)

            headers = {
                'Authorization': f'AccessKey {self.api_key}',
                'Content-Type': 'application/json',
            }

            payload = {
                'recipient': phone,
                'sender': self.sender_number,
                'message': message,
            }

            response = requests.post(
                f'{self.base_url}sms/send/single',
                json=payload,
                headers=headers,
                timeout=10
            )

            result = response.json()

            if response.status_code == 200:
                logger.info(f"SMS sent successfully to {phone}")
                return {
                    'success': True,
                    'message_id': result.get('message_id'),
                }
            else:
                logger.error(f"FarazSMS error: {result}")
                return {
                    'success': False,
                    'error': result.get('error', 'خطای ناشناخته'),
                }

        except Exception as e:
            logger.error(f"FarazSMS send_sms error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در ارسال پیامک: {str(e)}',
            }


class KavenegarService(BaseSMSService):
    """سرویس کاوه نگار"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = f'https://api.kavenegar.com/v1/{self.api_key}/'

    def send_sms(self, phone_number, message):
        """ارسال پیامک با کاوه نگار"""
        try:
            phone = self._normalize_phone(phone_number)

            params = {
                'sender': self.sender_number,
                'receptor': phone,
                'message': message,
            }

            response = requests.get(
                f'{self.base_url}sms/send.json',
                params=params,
                timeout=10
            )

            result = response.json()

            if result.get('return', {}).get('status') == 200:
                logger.info(f"SMS sent successfully to {phone}")
                return {
                    'success': True,
                    'message_id': result['entries'][0]['messageid'],
                }
            else:
                logger.error(f"Kavenegar error: {result}")
                return {
                    'success': False,
                    'error': result.get('return', {}).get('message', 'خطای ناشناخته'),
                }

        except Exception as e:
            logger.error(f"Kavenegar send_sms error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در ارسال پیامک: {str(e)}',
            }


class GhasedakService(BaseSMSService):
    """سرویس قاصدک"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://api.ghasedak.me/v2/'

    def send_sms(self, phone_number, message):
        """ارسال پیامک با قاصدک"""
        try:
            phone = self._normalize_phone(phone_number)

            headers = {
                'ApiKey': self.api_key,
                'Content-Type': 'application/json',
            }

            payload = {
                'message': message,
                'receptor': phone,
                'linenumber': self.sender_number,
            }

            response = requests.post(
                f'{self.base_url}sms/send/simple',
                json=payload,
                headers=headers,
                timeout=10
            )

            result = response.json()

            if result.get('result', {}).get('code') == 200:
                logger.info(f"SMS sent successfully to {phone}")
                return {
                    'success': True,
                    'message_id': result['result']['items'][0]['messageid'],
                }
            else:
                logger.error(f"Ghasedak error: {result}")
                return {
                    'success': False,
                    'error': result.get('result', {}).get('message', 'خطای ناشناخته'),
                }

        except Exception as e:
            logger.error(f"Ghasedak send_sms error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در ارسال پیامک: {str(e)}',
            }


class MelipayamakService(BaseSMSService):
    """سرویس ملی پیامک"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = 'https://rest.payamak-panel.com/api/SendSMS/'

    def send_sms(self, phone_number, message):
        """ارسال پیامک با ملی پیامک"""
        try:
            phone = self._normalize_phone(phone_number)

            # ملی پیامک نیاز به username و password دارد
            # فعلاً از api_key به عنوان username:password استفاده می‌کنیم
            # فرمت: username:password
            if ':' in self.api_key:
                username, password = self.api_key.split(':', 1)
            else:
                return {
                    'success': False,
                    'error': 'API Key باید به فرمت username:password باشد',
                }

            payload = {
                'username': username,
                'password': password,
                'from': self.sender_number,
                'to': phone,
                'text': message,
                'isflash': False,
            }

            response = requests.post(
                f'{self.base_url}SendSMS',
                json=payload,
                timeout=10
            )

            result = response.json()

            if result.get('RetStatus') == 1:
                logger.info(f"SMS sent successfully to {phone}")
                return {
                    'success': True,
                    'message_id': result.get('Value'),
                }
            else:
                logger.error(f"Melipayamak error: {result}")
                return {
                    'success': False,
                    'error': result.get('StrRetStatus', 'خطای ناشناخته'),
                }

        except Exception as e:
            logger.error(f"Melipayamak send_sms error: {str(e)}")
            return {
                'success': False,
                'error': f'خطا در ارسال پیامک: {str(e)}',
            }
