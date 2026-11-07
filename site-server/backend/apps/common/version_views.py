# -*- coding: utf-8 -*-
"""GET /api/v1/version/ و GET /api/v1/version/changelog/ — عمومی، بی‌ورود، سبک.

چرا بی‌احراز و بی‌محدودکننده
===========================

نشانِ نسخه روی صفحهٔ ورود هم دیده می‌شود، یعنی پیش از آنکه توکنی در کار باشد؛ و
اگر توکنِ منقضی در هدر مانده باشد، احرازِ پیش‌فرض (JWT) حتی روی یک `AllowAny`
هم ۴۰۱ می‌دهد. پس `authentication_classes = []`.

محدودکنندهٔ «anon» هم این‌جا نیست: پاسخ از حافظه می‌آید (ماژولِ versioning)، هزینه‌ای
ندارد، و نباید سهمِ ۳۰ درخواست در دقیقهٔ همان IP را — که ورود و ثبت‌نام هم از آن
می‌خورند — کم کند.
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import versioning


class _PublicView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []


class VersionView(_PublicView):
    @extend_schema(tags=["version"], responses={200: OpenApiTypes.OBJECT}, summary="نسخهٔ نرم‌افزار")
    def get(self, request):
        response = Response(versioning.read_build())
        # کوتاه: بعد از bump-version.sh نشان تا نیم دقیقه بعد تازه می‌شود
        response["Cache-Control"] = "public, max-age=30"
        return response


class ChangelogView(_PublicView):
    @extend_schema(tags=["version"], responses={200: OpenApiTypes.OBJECT}, summary="چه چیزی تازه است")
    def get(self, request):
        response = Response(
            {
                "name": versioning.NAME,
                "current": versioning.read_version(),
                "entries": versioning.read_changelog(),
            }
        )
        response["Cache-Control"] = "public, max-age=30"
        return response
