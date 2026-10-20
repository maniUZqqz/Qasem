# -*- coding: utf-8 -*-
"""محدودسازی نرخ درخواست برای endpoint های حساس (ضد brute-force).

نرخ هر scope در settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] تنظیم می‌شود.
"""
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


class SensitiveScopedRateThrottle(ScopedRateThrottle):
    """ScopedRateThrottle که در تست‌ها با DISABLE_API_THROTTLING=True خاموش می‌شود."""

    def allow_request(self, request, view):
        if getattr(settings, 'DISABLE_API_THROTTLING', False):
            return True
        return super().allow_request(request, view)
