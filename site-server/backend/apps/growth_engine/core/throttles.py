"""Scoped throttles for the expensive Growth Engine endpoints.

Honours the project-wide "no throttling in tests" switch, like the other apps do.
Rates come from ``REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`` (see settings).
"""
from django.conf import settings
from rest_framework.throttling import UserRateThrottle


class _GrowthThrottle(UserRateThrottle):
    def allow_request(self, request, view):
        if getattr(settings, "IS_TEST", False) and not getattr(settings, "GROWTH_THROTTLE_IN_TESTS", False):
            return True
        return super().allow_request(request, view)


class GrowthUploadThrottle(_GrowthThrottle):
    scope = "growth_upload"


class GrowthExportThrottle(_GrowthThrottle):
    scope = "growth_export"


class GrowthBulkThrottle(_GrowthThrottle):
    scope = "growth_bulk"
