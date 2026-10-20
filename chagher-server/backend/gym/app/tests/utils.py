# -*- coding: utf-8 -*-
"""ابزارهای مشترک تست‌ها"""
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from app.models import CustomUser


def create_user(phone='09120000001', password='StrongPass123', **kwargs):
    """ساخت کاربر تستی"""
    return CustomUser.objects.create_user(phone_number=phone, password=password, **kwargs)


# محدودسازی نرخ در تست‌ها خاموش می‌شود تا تست‌های پرتکرار خطای 429 نگیرند
# (تست‌های اختصاصی throttle خودشان آن را روشن می‌کنند)
@override_settings(DISABLE_API_THROTTLING=True)
class BaseAPITestCase(APITestCase):
    """کلاس پایه تست‌های API — احراز هویت با توکن DRF"""

    def auth(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def unauth(self):
        self.client.credentials()
