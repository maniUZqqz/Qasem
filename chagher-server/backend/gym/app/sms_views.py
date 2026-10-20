from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.conf import settings
from drf_spectacular.utils import extend_schema

from .models import CustomUser
from .serializers import SendRegisterCodeSerializer
from .throttling import SensitiveScopedRateThrottle
from .sms_hook import (
    issue_registration_code,
    queue_registration_code,
    peek_registration_code,
    SMS_CODE_TTL,
)


def _return_code_enabled() -> bool:
    """
    آیا کد در پاسخ API برگردانده شود؟

    این تنظیم از DEBUG جدا شده تا در production هم بتوانی موقتاً
    برای تست روشنش کنی، بدون اینکه کل حالت DEBUG را فعال کنی.
    """
    return bool(getattr(settings, 'SMS_RETURN_CODE_IN_RESPONSE', False))


class SendRegisterCodeView(APIView):
    """
    ارسال کد تایید ۴ رقمی برای ثبت‌نام.

    اگر SMS_RETURN_CODE_IN_RESPONSE=True باشد، خود کد در پاسخ برمی‌گردد
    (فقط برای تست). در production واقعی این مقدار باید False باشد.
    """
    permission_classes = [AllowAny]
    serializer_class = SendRegisterCodeSerializer
    throttle_classes = [SensitiveScopedRateThrottle]
    throttle_scope = 'login'

    @extend_schema(
        request=SendRegisterCodeSerializer,
        responses={200: {'type': 'object', 'properties': {
            'message': {'type': 'string'},
            'expires_in': {'type': 'integer'},
        }}},
        description='ارسال کد تایید ۴ رقمی برای ثبت‌نام.'
    )
    def post(self, request):
        serializer = SendRegisterCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        phone = serializer.validated_data['phone_number'].strip()

        if CustomUser.objects.filter(phone_number=phone).exists():
            return Response(
                {'error': 'این شماره قبلاً ثبت شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ۱. تولید کد (اتمیک، در کش)
        code = issue_registration_code(phone)

        # ۲. گذاشتن در صف گیت‌وی پیامک — گوشی با /api/next-otp برمی‌دارد و پیامک می‌کند
        queue_registration_code(phone, code)

        response_data = {
            'message': 'کد تایید پیامک شد.',
            'expires_in': SMS_CODE_TTL,
        }

        # ⭐ اگر حالت تست روشن است، کد را هم برگردان
        if _return_code_enabled():
            response_data['debug'] = {'code': code}

        return Response(response_data, status=status.HTTP_200_OK)


class PeekRegisterCodeView(APIView):
    """
    ⚠️ فقط برای توسعه — کد فعلی یک شماره را برمی‌گرداند بدون ارسال پیامک.

    اگر SMS_RETURN_CODE_IN_RESPONSE=False باشد، غیرفعال می‌شود.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        if not _return_code_enabled():
            return Response(
                {'error': 'این endpoint فقط در حالت تست فعال است.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        phone = request.query_params.get('phone_number', '').strip()
        if not phone:
            return Response(
                {'error': 'پارامتر phone_number الزامی است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code = peek_registration_code(phone)
        if not code:
            return Response(
                {'error': 'کدی برای این شماره یافت نشد یا منقضی شده است.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'phone_number': phone,
            'code': code,
            'expires_in': SMS_CODE_TTL,
        })