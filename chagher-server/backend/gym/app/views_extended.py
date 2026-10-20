from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets, serializers, mixins
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authentication import (
    SessionAuthentication, TokenAuthentication)
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.authtoken.models import Token
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema, extend_schema_view, OpenApiParameter,
)
import logging
from urllib.parse import urlencode

import mimetypes
import os

from django.http import FileResponse, Http404

from .models import (
    CustomUser, TokenPackage, DiscountCode, DiscountCodeUsage, TokenPurchase,
    GymBrand, GymClient, TokenRequest, HomePage, BlogPost, ContactMessage,
    TeamMember, Feature, CardPaymentAccount, LedgerEntry, ProgramShareCode
)
from .payment_gateway import PaymentGateway, MockGateway, mock_gateway_allowed
from .models import PaymentGatewayConfig
from .permissions import IsCoach, IsGymClient
from .throttling import SensitiveScopedRateThrottle
from .serializers import (
    TokenPackageSerializer, PurchaseTokenSerializer, DiscountCodeSerializer,
    ValidateDiscountCodeSerializer, GymBrandSerializer, GymClientSerializer,
    ClientAccessCodeSerializer, ClientUpdateInfoSerializer, CoachInstructionSerializer,
    TokenRequestSerializer, TokenRequestResponseSerializer, AdjustClientTokensSerializer,
    HomePageSerializer, BlogPostSerializer, ContactMessageSerializer,
    TeamMemberSerializer, FeatureSerializer,
    CardPaymentAccountSerializer, UploadReceiptSerializer, TokenPurchaseStatusSerializer, PaymentCallbackSerializer
)

logger = logging.getLogger(__name__)


def _generate_unique_client_phone(client_id):
    """
    تولید شماره سیستماتیک و قابل‌ردیابی برای حساب مشتری:
    099 + شناسه مشتری (تا 8 رقم).
    """
    base = f"099{str(client_id).zfill(8)}"[-11:]
    if not CustomUser.objects.filter(phone_number=base).exists():
        return base

    # fallback نهایی در صورت برخورد نادر
    for i in range(1, 1000):
        candidate = f"099{str((client_id + i) % 100000000).zfill(8)}"[-11:]
        if not CustomUser.objects.filter(phone_number=candidate).exists():
            return candidate
    raise ValueError('امکان تولید شماره مشتری یکتا وجود ندارد')


def _complete_purchase(purchase, ref_id=None):
    """تکمیل idempotent خرید: paid + شارژ توکن + ثبت استفاده کد تخفیف.

    زیر قفل ردیف انجام می‌شود تا کال‌بک همزمان/تکراری دوبار شارژ نکند.
    خروجی: True اگر همین فراخوانی خرید را تکمیل کرد، False اگر قبلاً paid بود.
    """
    with transaction.atomic():
        locked = TokenPurchase.objects.select_for_update().get(pk=purchase.pk)
        if locked.status == 'paid':
            return False

        locked.status = 'paid'
        if ref_id:
            locked.payment_ref_id = ref_id
        locked.save(update_fields=['status', 'payment_ref_id', 'updated_at'])

        locked.user.add_tokens(locked.token_amount)

        if locked.discount_code:
            commission = (locked.final_price * locked.discount_code.commission_percent) / 100
            usage, created = DiscountCodeUsage.objects.get_or_create(
                discount_code=locked.discount_code,
                user=locked.user,
                defaults={
                    'purchase_amount': locked.final_price,
                    'discount_amount': locked.discount_amount,
                    'commission_amount': commission,
                }
            )
            if created:
                locked.discount_code.used_count += 1
                locked.discount_code.save(update_fields=['used_count', 'updated_at'])

    _record_purchase_ledger(locked)

    purchase.refresh_from_db()
    return True


def _record_purchase_ledger(purchase):
    """سه سطر دفتر حساب برای یک خرید نهایی‌شده: درآمد، شارژ توکن، کمیسیون.

    عمداً بعد از پایان تراکنش صدا زده می‌شود تا نوشتن دفتر (که گزارش است،
    نه منبع حقیقت) نتواند شارژ توکن را به عقب برگرداند.
    """
    LedgerEntry.record(
        LedgerEntry.TYPE_PURCHASE,
        user=purchase.user,
        amount=purchase.final_price,
        reference=f'purchase#{purchase.id}',
        description=(
            f'{purchase.get_payment_method_display()} — {purchase.token_amount} توکن'
        ),
    )
    LedgerEntry.record(
        LedgerEntry.TYPE_TOKEN_GRANT,
        user=purchase.user,
        tokens=purchase.token_amount,
        reference=f'purchase#{purchase.id}',
        description='شارژ توکن پس از تایید پرداخت',
    )

    if purchase.discount_code:
        usage = DiscountCodeUsage.objects.filter(
            discount_code=purchase.discount_code, user=purchase.user
        ).first()
        if usage and usage.commission_amount:
            LedgerEntry.record(
                LedgerEntry.TYPE_COMMISSION,
                user=purchase.user,
                counterparty=purchase.discount_code.creator,
                amount=-usage.commission_amount,
                reference=f'purchase#{purchase.id}',
                description=(
                    f'کمیسیون کد {purchase.discount_code.code} '
                    f'({purchase.discount_code.commission_percent}%)'
                ),
            )


# ==================== Token Package Views ====================

@extend_schema(tags=['Token Package'])
@extend_schema_view(
    list=extend_schema(description="دریافت لیست بسته‌های توکن فعال"),
)
class TokenPackageViewSet(viewsets.ReadOnlyModelViewSet):
    """لیست و جزئیات بسته‌های توکن"""
    queryset = TokenPackage.objects.filter(is_active=True)
    serializer_class = TokenPackageSerializer
    permission_classes = [AllowAny]


@extend_schema(tags=['Token Purchase'])
class PurchaseTokenView(APIView):
    """خرید توکن با قابلیت اعمال کد تخفیف"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PurchaseTokenSerializer,
        responses={201: {'type': 'object'}},
        description="""خرید توکن:
        - تعداد توکن باید حداقل 50 و مضربی از 50 باشد
        - می‌توانید کد تخفیف اعمال کنید
        - قیمت بر اساس تعرفه محاسبه می‌شود
        - در صورت موفقیت، لینک درگاه پرداخت برگردانده می‌شود
        """
    )
    def post(self, request):
        serializer = PurchaseTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        token_amount = serializer.validated_data['token_amount']
        package_id = serializer.validated_data.get('package_id')
        discount_code_str = serializer.validated_data.get('discount_code', '').strip()
        payment_method = serializer.validated_data.get(
            'payment_method', TokenPurchase.METHOD_GATEWAY
        )

        # کارت‌به‌کارت فقط وقتی قابل انتخاب است که مدیر یک کارت فعال ثبت کرده باشد
        card_account = None
        if payment_method == TokenPurchase.METHOD_CARD:
            card_account = CardPaymentAccount.get_active()
            if not card_account:
                return Response({
                    'error': 'پرداخت کارت‌به‌کارت در حال حاضر فعال نیست. '
                             'لطفاً از درگاه آنلاین استفاده کنید.'
                }, status=status.HTTP_400_BAD_REQUEST)

        # بررسی تعرفه موجود
        if package_id:
            package = TokenPackage.objects.filter(id=package_id, is_active=True).first()
        else:
            package = TokenPackage.objects.filter(is_active=True).first()
        if not package:
            return Response({
                'error': 'تعرفه انتخابی معتبر نیست یا هیچ تعرفه فعالی تعریف نشده است.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # محاسبه قیمت اصلی
        original_price = package.calculate_price(token_amount)
        discount_code = None
        discount_amount = 0
        final_price = original_price

        # اعمال کد تخفیف (در صورت وجود)
        if discount_code_str:
            try:
                discount_code = DiscountCode.objects.get(code=discount_code_str)
                can_use, message = discount_code.can_use(request.user)

                if not can_use:
                    return Response({
                        'error': message
                    }, status=status.HTTP_400_BAD_REQUEST)

                final_price, discount_amount = discount_code.apply_discount(original_price)

            except DiscountCode.DoesNotExist:
                return Response({
                    'error': 'کد تخفیف معتبر نیست.'
                }, status=status.HTTP_400_BAD_REQUEST)

        try:
            purchase = TokenPurchase.objects.create(
                user=request.user,
                token_amount=token_amount,
                original_price=original_price,
                discount_code=discount_code,
                discount_amount=discount_amount,
                final_price=final_price,
                status='pending',
                payment_method=payment_method,
                card_account=card_account,
            )

            base_response = {
                'purchase_id': purchase.id,
                'package_id': package.id,
                'package_name': package.name,
                'token_amount': token_amount,
                'original_price': float(original_price),
                'discount_amount': float(discount_amount),
                'final_price': float(final_price),
            }

            # تخفیف 100٪ (قیمت صفر): بدون درگاه، مستقیم تکمیل می‌شود
            if final_price <= 0:
                _complete_purchase(purchase, ref_id=f'FREE-{purchase.id}')
                request.user.refresh_from_db()
                logger.info(f"Token purchase #{purchase.id} completed free of charge (100% discount)")
                return Response({
                    **base_response,
                    'payment_url': None,
                    'status': 'paid',
                    'tokens_added': purchase.token_amount,
                    'message': 'خرید با تخفیف کامل انجام و توکن‌ها به حساب شما اضافه شد.'
                }, status=status.HTTP_201_CREATED)

            # کارت‌به‌کارت: کاربر شماره کارت را می‌بیند، واریز می‌کند و رسید
            # را بارگذاری می‌کند. توکن فقط پس از تایید مدیر آزاد می‌شود.
            if payment_method == TokenPurchase.METHOD_CARD:
                purchase.status = 'awaiting_receipt'
                purchase.save(update_fields=['status', 'updated_at'])
                logger.info(
                    f"Card purchase #{purchase.id} created for "
                    f"{request.user.phone_number} ({token_amount} tokens, {final_price})"
                )
                return Response({
                    **base_response,
                    'payment_method': TokenPurchase.METHOD_CARD,
                    'payment_url': None,
                    'status': 'awaiting_receipt',
                    'tokens_added': 0,
                    'card_account': CardPaymentAccountSerializer(card_account).data,
                    'upload_receipt_url': f'/api/purchase-token/{purchase.id}/receipt/',
                    'message': (
                        'سفارش ثبت شد. مبلغ را به شماره کارت اعلام‌شده واریز کنید و '
                        'سپس تصویر رسید را بارگذاری کنید. توکن‌ها پس از تایید مدیر '
                        'به حساب شما اضافه می‌شوند.'
                    )
                }, status=status.HTTP_201_CREATED)

            # اتصال به درگاه پرداخت فعال (در صورت تنظیم در پنل ادمین)
            gateway = PaymentGateway.get_active_gateway()
            payment_url = None
            # درگاه تستی نباید مثل درگاه واقعی به کلاینت معرفی شود: کلاینت
            # با دیدن این پرچم کاربر را به صفحه شبیه‌ساز نمی‌فرستد و مسیر
            # کارت‌به‌کارت را پیشنهاد می‌دهد.
            is_mock_gateway = False
            if gateway:
                result = gateway.create_payment(
                    amount=final_price,
                    description=f'خرید {token_amount} توکن - سفارش #{purchase.id}',
                    metadata={'order_id': str(purchase.id)},
                )
                if not result.get('success'):
                    purchase.status = 'failed'
                    purchase.save(update_fields=['status', 'updated_at'])
                    logger.error(
                        f"Gateway create_payment failed for purchase #{purchase.id}: {result.get('error')}"
                    )
                    return Response({
                        'error': 'اتصال به درگاه پرداخت ناموفق بود. لطفاً بعداً دوباره تلاش کنید.'
                    }, status=status.HTTP_502_BAD_GATEWAY)

                purchase.payment_authority = str(result['authority'])
                purchase.save(update_fields=['payment_authority', 'updated_at'])
                payment_url = result['payment_url']
                is_mock_gateway = bool(result.get('is_mock'))
            else:
                logger.warning(
                    f"Token purchase #{purchase.id} created but no active payment gateway is configured"
                )

            logger.info(
                f"Token purchase #{purchase.id} created: {request.user.phone_number} "
                f"- {token_amount} tokens - final price: {final_price}"
            )

            card_available = CardPaymentAccount.get_active() is not None

            return Response({
                **base_response,
                'payment_method': TokenPurchase.METHOD_GATEWAY,
                'payment_url': payment_url,
                'is_mock_gateway': is_mock_gateway,
                'card_payment_available': card_available,
                'status': 'pending',
                'tokens_added': 0,
                'message': (
                    'سفارش ثبت شد. برای پرداخت به درگاه هدایت شوید؛ '
                    'توکن‌ها پس از تایید پرداخت اضافه می‌شوند.'
                    if payment_url else
                    'سفارش ثبت شد اما درگاه پرداخت فعالی تنظیم نشده است. '
                    'توکن‌ها پس از تایید مدیر به حساب شما اضافه می‌شوند.'
                )
            }, status=status.HTTP_201_CREATED)

        except Exception:
            logger.exception("Error in token purchase")
            return Response({
                'error': 'خطا در ثبت سفارش. لطفاً دوباره تلاش کنید.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaymentResultRenderer(TemplateHTMLRenderer):
    """نتیجه پرداخت به‌صورت صفحه قابل خواندن برای کاربر.

    درگاه واقعی مرورگرِ کاربر را به کال‌بک برمی‌گرداند؛ بدون این رندرر،
    کاربر صفحه دیباگ Browsable API را می‌دید نه نتیجه پرداخت را.
    """
    template_name = 'app/payment_result.html'


@extend_schema(tags=['Token Purchase'])
class PaymentCallbackView(APIView):
    """کال‌بک درگاه پرداخت.

    هیچ پرداختی بدون verify واقعی با درگاه تایید نمی‌شود — محتوای درخواستِ
    کال‌بک به‌تنهایی قابل اعتماد نیست (هر کسی می‌تواند آن را جعل کند).

    پاسخ بر اساس هدر Accept انتخاب می‌شود: مرورگر (text/html) صفحه نتیجه
    می‌گیرد و کلاینت API همان JSON قبلی را — قرارداد API تغییر نکرده است.
    """
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, PaymentResultRenderer]

    @extend_schema(
        parameters=[
            OpenApiParameter('Authority', str, OpenApiParameter.QUERY,
                             description='شناسه تراکنش درگاه'),
            OpenApiParameter('Status', str, OpenApiParameter.QUERY,
                             description='OK یا NOK'),
        ],
        responses={200: {'type': 'object'}},
        description="""کال‌بک بازگشت از درگاه پرداخت (GET برای درگاه‌هایی مثل زرین‌پال).
        پرداخت با verify مستقیم از خود درگاه تایید می‌شود.
        """
    )
    def get(self, request):
        # درگاه‌هایی مثل زرین‌پال کاربر را با GET (Authority و Status) برمی‌گردانند
        return self._handle(request.query_params)

    @extend_schema(
        request=PaymentCallbackSerializer,
        responses={200: {'type': 'object'}},
        description="""کال‌بک از درگاه پرداخت برای تایید تراکنش.
        شناسه تراکنش (Authority) با رکورد خرید تطبیق داده شده و سپس با
        درگاه verify می‌شود؛ فقط در صورت تایید درگاه، توکن‌ها شارژ می‌شوند.
        """
    )
    def post(self, request):
        return self._handle(request.data)

    def _handle(self, params):
        authority = str(
            params.get('Authority') or params.get('authority')
            or params.get('trans_id') or params.get('id') or ''
        ).strip()
        order_id = params.get('order_id') or params.get('purchase_id')
        gateway_status = str(params.get('Status') or params.get('status') or '').strip().lower()

        try:
            # یافتن سفارش: اول با شناسه تراکنش درگاه، بعد با شماره سفارش
            purchase = None
            if authority:
                purchase = TokenPurchase.objects.filter(payment_authority=authority).first()
            if purchase is None and order_id:
                purchase = TokenPurchase.objects.filter(id=order_id).first()
                # جلوگیری از جعل: authority ارسالی باید با ثبت‌شده بخواند
                if purchase and authority and purchase.payment_authority and purchase.payment_authority != authority:
                    purchase = None

            if purchase is None:
                return Response({'error': 'سفارش یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

            # idempotent: پرداخت قبلاً تایید شده
            if purchase.status == 'paid':
                return Response({
                    'message': 'این پرداخت قبلاً ثبت شده است.',
                    'tokens_added': 0,
                    'new_balance': purchase.user.token_balance,
                    'already_paid': True
                })

            # انصراف/شکست اعلام‌شده توسط درگاه (مثلاً زرین‌پال: Status=NOK)
            if gateway_status in ('nok', 'failed', 'cancel', 'canceled', 'cancelled'):
                purchase.status = 'failed'
                purchase.save(update_fields=['status', 'updated_at'])
                logger.warning(f"Payment callback: purchase #{purchase.id} cancelled/failed by gateway")
                return Response({'error': 'پرداخت ناموفق بود یا لغو شد.'},
                                status=status.HTTP_400_BAD_REQUEST)

            gateway = PaymentGateway.get_active_gateway()
            if gateway is None:
                logger.error(
                    f"Payment callback received for purchase #{purchase.id} "
                    f"but no active payment gateway is configured"
                )
                return Response({
                    'error': 'درگاه پرداخت فعالی تنظیم نشده است؛ امکان تایید پرداخت وجود ندارد.'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            # سفارش کارت‌به‌کارت هرگز از مسیر کال‌بک درگاه تایید نمی‌شود؛
            # تنها راهش بارگذاری رسید و تایید دستی مدیر است.
            if purchase.payment_method == TokenPurchase.METHOD_CARD:
                logger.warning(
                    f"Gateway callback attempted on card purchase #{purchase.id}"
                )
                return Response({
                    'error': 'این سفارش کارت‌به‌کارت است و از مسیر درگاه تایید نمی‌شود.'
                }, status=status.HTTP_400_BAD_REQUEST)

            if not purchase.payment_authority:
                return Response({
                    'error': 'برای این سفارش تراکنش درگاهی ثبت نشده است.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # تایید قطعی با خود درگاه — تنها مرجع قابل اعتماد
            result = gateway.verify_payment(
                purchase.payment_authority,
                amount=purchase.final_price,
                order_id=str(purchase.id),
            )
            if not result.get('success'):
                purchase.status = 'failed'
                purchase.save(update_fields=['status', 'updated_at'])
                logger.warning(
                    f"Payment verify failed for purchase #{purchase.id}: {result.get('error')}"
                )
                return Response({'error': 'تایید پرداخت توسط درگاه ناموفق بود.'},
                                status=status.HTTP_400_BAD_REQUEST)

            _complete_purchase(purchase, ref_id=str(result.get('ref_id') or ''))

            logger.info(
                f"Payment callback: purchase #{purchase.id} verified & paid "
                f"({purchase.token_amount} tokens added to {purchase.user.phone_number})"
            )
            return Response({
                'message': 'پرداخت با موفقیت تایید شد و توکن‌ها به حساب شما اضافه شدند.',
                'tokens_added': purchase.token_amount,
                'new_balance': purchase.user.token_balance
            })

        except Exception:
            logger.exception("Error in payment callback")
            return Response({
                'error': 'خطا در پردازش پرداخت. لطفاً با پشتیبانی تماس بگیرید.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def mock_payment_page(request):
    """صفحه شبیه‌ساز درگاه پرداخت (فقط وقتی درگاه فعال از نوع «تستی» است).

    نقش صفحه درگاه واقعی را بازی می‌کند: مبلغ را نشان می‌دهد و با دو دکمه،
    کاربر را با Status=OK یا Status=NOK به همان callback_url برمی‌گرداند.
    """
    config = PaymentGatewayConfig.get_active_gateway()
    if config is None or config.gateway_type != 'mock' or not mock_gateway_allowed():
        raise Http404('درگاه تستی فعال نیست.')

    authority = str(request.GET.get('Authority') or request.GET.get('authority') or '').strip()
    if not MockGateway.owns_authority(authority):
        raise Http404('شناسه تراکنش تستی معتبر نیست.')

    purchase = TokenPurchase.objects.filter(payment_authority=authority).select_related('user').first()
    if purchase is None:
        raise Http404('سفارشی با این شناسه تراکنش یافت نشد.')

    def callback(status_value):
        return f"{config.callback_url}?{urlencode({'Authority': authority, 'Status': status_value})}"

    return render(request, 'app/mock_payment.html', {
        'purchase': purchase,
        'authority': authority,
        'success_url': callback('OK'),
        'failure_url': callback('NOK'),
        'already_paid': purchase.status == 'paid',
    })


# ==================== Card Payment Views ====================

@extend_schema(tags=['Token Purchase'])
class PaymentMethodsView(APIView):
    """روش‌های پرداختی که همین حالا واقعاً قابل استفاده‌اند.

    کلاینت نباید خودش حدس بزند چه چیزی فعال است. اگر مدیر فردا یک درگاه
    واقعی ثبت کند، همین پاسخ عوض می‌شود و گزینه‌ی درگاه بدون هیچ تغییری در
    کد کلاینت ظاهر می‌شود؛ و اگر درگاه را خاموش کند، خودش محو می‌شود.

    درگاه تستی عمداً `available=false` گزارش می‌شود: یک شبیه‌ساز است و
    فرستادن کاربر واقعی به آن، یک پرداخت جعلی و یک انتظار غلط می‌سازد.
    نشانه‌اش (`is_mock`) جدا برمی‌گردد تا در محیط توسعه قابل تشخیص باشد.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: {'type': 'object'}},
        description='وضعیت روش‌های پرداخت: کارت‌به‌کارت و درگاه آنلاین.',
    )
    def get(self, request):
        account = CardPaymentAccount.get_active()
        config = PaymentGatewayConfig.get_active_gateway()

        is_mock = bool(config and config.gateway_type == 'mock')
        gateway_available = bool(config) and not is_mock

        return Response({
            'card': {
                'available': account is not None,
                'account': (
                    CardPaymentAccountSerializer(account).data if account else None
                ),
            },
            'gateway': {
                'available': gateway_available,
                'is_mock': is_mock,
                'name': config.get_gateway_type_display() if config else None,
            },
        })


@extend_schema(tags=['Token Purchase'])
class CardPaymentInfoView(APIView):
    """اطلاعات کارت مقصد برای پرداخت کارت‌به‌کارت."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CardPaymentAccountSerializer},
        description="شماره کارت فعال برای واریز. اگر مدیر کارتی ثبت نکرده باشد، "
                    "enabled=false برمی‌گردد و کلاینت باید گزینه کارت‌به‌کارت را نشان ندهد."
    )
    def get(self, request):
        account = CardPaymentAccount.get_active()
        if not account:
            return Response({'enabled': False, 'card_account': None})
        return Response({
            'enabled': True,
            'card_account': CardPaymentAccountSerializer(account).data,
        })


@extend_schema(tags=['Token Purchase'])
class UploadPaymentReceiptView(APIView):
    """بارگذاری رسید پرداخت کارت‌به‌کارت برای یک سفارش."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        request=UploadReceiptSerializer,
        responses={200: TokenPurchaseStatusSerializer},
        description="""بارگذاری تصویر رسید برای سفارش کارت‌به‌کارت.

        - فقط صاحب همان سفارش می‌تواند رسید بگذارد.
        - سفارشی که قبلاً تایید (paid) شده دیگر رسید نمی‌پذیرد.
        - پس از بارگذاری، وضعیت به «در انتظار تایید مدیر» می‌رود و توکن
          فقط با تایید مدیر در پنل ادمین آزاد می‌شود.
        """
    )
    def post(self, request, purchase_id):
        purchase = TokenPurchase.objects.filter(
            id=purchase_id, user=request.user
        ).first()
        if not purchase:
            return Response(
                {'error': 'سفارش یافت نشد.'}, status=status.HTTP_404_NOT_FOUND
            )

        if purchase.payment_method != TokenPurchase.METHOD_CARD:
            return Response(
                {'error': 'این سفارش از نوع کارت‌به‌کارت نیست.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if purchase.status == 'paid':
            return Response(
                {'error': 'این سفارش قبلاً تایید و شارژ شده است.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if purchase.status in ('cancelled', 'failed'):
            return Response(
                {'error': 'این سفارش بسته شده است. لطفاً سفارش جدیدی ثبت کنید.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UploadReceiptSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        purchase.receipt_image = serializer.validated_data['receipt_image']
        purchase.receipt_reference = serializer.validated_data.get('receipt_reference') or None
        purchase.receipt_note = serializer.validated_data.get('receipt_note') or None
        purchase.receipt_uploaded_at = timezone.now()
        purchase.status = 'under_review'
        # رسید جدید یعنی بررسی قبلی باطل است
        purchase.review_note = None
        purchase.reviewed_by = None
        purchase.reviewed_at = None
        purchase.save(update_fields=[
            'receipt_image', 'receipt_reference', 'receipt_note',
            'receipt_uploaded_at', 'status', 'review_note',
            'reviewed_by', 'reviewed_at', 'updated_at',
        ])

        logger.info(
            f"Receipt uploaded for purchase #{purchase.id} by {request.user.phone_number}"
        )

        return Response({
            'purchase': TokenPurchaseStatusSerializer(purchase).data,
            'message': 'رسید دریافت شد. پس از تایید مدیر، توکن‌ها به حساب شما اضافه می‌شود.',
        })


@extend_schema(tags=['Token Purchase'])
class PaymentReceiptFileView(APIView):
    """سرو محافظت‌شده‌ی تصویر رسید پرداخت.

    رسید بانکی داده‌ی حساس است و در فضای خصوصی (بیرون از MEDIA_ROOT) ذخیره
    می‌شود، پس وب‌سرور مستقیماً سروش نمی‌کند. تنها صاحب همان سفارش یا کاربر
    staff می‌تواند ببیندش.
    """
    # ⚠ احرازِ پیش‌فرضِ پروژه فقط TokenAuthentication است. مدیر رسید را از
    #   **جنگو ادمین** باز می‌کند، یعنی با کوکیِ نشست و بی‌هدرِ Token — و ۴۰۱
    #   می‌گرفت. با این خط هر دو راه کار می‌کند (فقط GET است، CSRF موضوعیت ندارد).
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: {'type': 'string', 'format': 'binary'}},
        description="دریافت تصویر رسید یک سفارش — فقط برای صاحب سفارش یا مدیر."
    )
    def get(self, request, purchase_id):
        purchase = TokenPurchase.objects.filter(id=purchase_id).first()
        if not purchase or not purchase.receipt_image:
            raise Http404('رسیدی برای این سفارش وجود ندارد.')

        is_owner = purchase.user_id == request.user.id
        if not (is_owner or request.user.is_staff):
            # عمداً ۴۰۴ و نه ۴۰۳ — تا وجود/نبود سفارش دیگران لو نرود
            logger.warning(
                f"Unauthorized receipt access attempt on purchase #{purchase_id} "
                f"by {request.user.phone_number}"
            )
            raise Http404('رسیدی برای این سفارش وجود ندارد.')

        try:
            handle = purchase.receipt_image.open('rb')
        except (FileNotFoundError, OSError):
            logger.error(f"Receipt file missing on disk for purchase #{purchase_id}")
            raise Http404('فایل رسید یافت نشد.')

        content_type, _ = mimetypes.guess_type(purchase.receipt_image.name)
        response = FileResponse(handle, content_type=content_type or 'application/octet-stream')
        response['Content-Disposition'] = (
            f'inline; filename="receipt-{purchase.id}{os.path.splitext(purchase.receipt_image.name)[1]}"'
        )
        # رسید نباید در کش واسط یا مرورگر مشترک بماند
        response['Cache-Control'] = 'private, no-store'
        return response


@extend_schema(tags=['Token Purchase'])
class MyPurchasesView(APIView):
    """فهرست سفارش‌های خرید توکن کاربر و وضعیت هرکدام."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: TokenPurchaseStatusSerializer(many=True)},
        description="سفارش‌های کاربر — برای نمایش وضعیت رسید و تایید در پنل."
    )
    def get(self, request):
        purchases = (
            TokenPurchase.objects
            .filter(user=request.user)
            .select_related('card_account')
            .order_by('-created_at')[:50]
        )
        return Response({
            'purchases': TokenPurchaseStatusSerializer(purchases, many=True).data,
        })


# ==================== Discount Code Views ====================

@extend_schema(tags=['Discount Codes'])
class ValidateDiscountCodeView(APIView):
    """اعتبارسنجی کد تخفیف"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ValidateDiscountCodeSerializer,
        responses={200: {'type': 'object'}},
        description="بررسی اعتبار کد تخفیف و محاسبه قیمت نهایی"
    )
    def post(self, request):
        serializer = ValidateDiscountCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data['code']
        purchase_amount = serializer.validated_data['purchase_amount']

        try:
            discount_code = DiscountCode.objects.get(code=code)
            can_use, message = discount_code.can_use(request.user)

            if not can_use:
                return Response({
                    'valid': False,
                    'message': message
                }, status=status.HTTP_400_BAD_REQUEST)

            final_price, discount_amount = discount_code.apply_discount(purchase_amount)

            return Response({
                'valid': True,
                'discount_percent': discount_code.discount_percent,
                'original_price': float(purchase_amount),
                'discount_amount': float(discount_amount),
                'final_price': float(final_price),
                'message': f'کد تخفیف {discount_code.discount_percent}% اعمال شد.'
            })

        except DiscountCode.DoesNotExist:
            return Response({
                'valid': False,
                'message': 'کد تخفیف معتبر نیست.'
            }, status=status.HTTP_404_NOT_FOUND)


# ==================== Gym Brand Views ====================

@extend_schema(tags=['Gym Brand'])
class GymBrandView(APIView):
    """مدیریت برندسازی باشگاه"""
    permission_classes = [IsCoach]

    @extend_schema(
        responses={200: GymBrandSerializer},
        description="دریافت اطلاعات برند باشگاه کاربر"
    )
    def get(self, request):
        """دریافت اطلاعات برند (مشتریان باشگاه برند را از client-profile می‌گیرند)"""
        brand = GymBrand.objects.filter(user=request.user).first()
        if brand:
            return Response(GymBrandSerializer(brand).data)
        return Response({
            'message': 'برند باشگاه هنوز ایجاد نشده است.'
        }, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(
        request=GymBrandSerializer,
        responses={200: GymBrandSerializer},
        description="ایجاد یا ویرایش برند باشگاه"
    )
    def post(self, request):
        """ایجاد یا ویرایش برند"""
        try:
            brand = request.user.gym_brand
            serializer = GymBrandSerializer(brand, data=request.data, partial=True)
        except GymBrand.DoesNotExist:
            serializer = GymBrandSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Gym Brand'])
class CoachInstructionView(APIView):
    """دستورالعمل ثابت مربی برای تولید برنامه‌ها"""
    permission_classes = [IsCoach]
    # drf_spectacular برای APIView سریالایزر را حدس می‌زند؛ اعلام صریح
    # باعث می‌شود مستندات Swagger شکل واقعی داده را نشان بدهد نه حدس.
    serializer_class = CoachInstructionSerializer

    @extend_schema(
        responses={200: CoachInstructionSerializer},
        description='دریافت دستورالعمل فعلی مربی (اگر ثبت نشده باشد، رشته خالی برمی‌گردد).'
    )
    def get(self, request):
        brand = GymBrand.objects.filter(user=request.user).first()
        return Response({
            'program_instructions': (brand.program_instructions if brand else '') or ''
        })

    @extend_schema(
        request=CoachInstructionSerializer,
        responses={200: CoachInstructionSerializer},
        description="""ثبت یا ویرایش دستورالعمل مربی.

        این متن در تولید **هر** برنامه‌ای که برای مشتریان این باشگاه ساخته می‌شود،
        با اولویت بالا به هوش مصنوعی داده می‌شود.
        نمونه: «روز اول هر هفته سبک باشد» یا «برای بانوان از پرس سرشانه بالای سر استفاده نشود».
        اگر هنوز برند باشگاه نساخته باشید، به‌صورت خودکار ساخته می‌شود.
        """
    )
    def put(self, request):
        serializer = CoachInstructionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        text = serializer.validated_data['program_instructions'].strip()
        brand, _ = GymBrand.objects.get_or_create(
            user=request.user,
            defaults={'gym_name': request.user.gym_name or 'باشگاه من'},
        )
        brand.program_instructions = text
        brand.save(update_fields=['program_instructions', 'updated_at'])

        logger.info(f"Coach instructions updated by {request.user.phone_number} ({len(text)} chars)")
        return Response({
            'program_instructions': brand.program_instructions or '',
            'message': 'دستورالعمل ذخیره شد.' if text else 'دستورالعمل پاک شد.',
        })

    def post(self, request):
        return self.put(request)


# ==================== Gym Client Views ====================

@extend_schema(tags=['Gym Clients'])
@extend_schema_view(
    list=extend_schema(description="لیست مشتریان باشگاه"),
    create=extend_schema(description="ایجاد مشتری جدید با کد دسترسی یکبار مصرف"),
    retrieve=extend_schema(description="جزئیات یک مشتری"),
    destroy=extend_schema(description="حذف مشتری"),
)
class GymClientViewSet(viewsets.ModelViewSet):
    """مدیریت مشتریان باشگاه"""
    serializer_class = GymClientSerializer
    # فقط برای مستندسازی: get_queryset واقعی بر اساس کاربر فیلتر می‌کند
    # و هنگام ساخت schema (بدون request) قابل فراخوانی نیست.
    queryset = GymClient.objects.none()
    permission_classes = [IsCoach]

    def get_queryset(self):
        return GymClient.objects.filter(gym_owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(gym_owner=self.request.user)

    @extend_schema(
        request=AdjustClientTokensSerializer,
        responses={200: {'type': 'object'}},
        description='تنظیم دستی توکن مشتری توسط مربی. مقدار مثبت: انتقال از مربی به مشتری، مقدار منفی: بازگشت از مشتری به مربی.'
    )
    @action(detail=True, methods=['post'], url_path='adjust-tokens')
    def adjust_tokens(self, request, pk=None):
        client = self.get_object()
        serializer = AdjustClientTokensSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']

        coach = request.user
        with transaction.atomic():
            if client.client_user:
                client_user = client.client_user
                if amount > 0:
                    # چک قطعی موجودی داخل deduct_tokens زیر قفل انجام می‌شود
                    if not coach.deduct_tokens(amount):
                        return Response({
                            'error': 'موجودی توکن مربی کافی نیست.',
                            'coach_balance': coach.get_effective_token_balance()
                        }, status=status.HTTP_400_BAD_REQUEST)
                    client_user.add_tokens(amount)
                    message = f'{amount} توکن به مشتری اضافه شد.'
                else:
                    transfer_back = abs(amount)
                    if not client_user.deduct_tokens(transfer_back):
                        return Response({
                            'error': 'موجودی توکن مشتری کافی نیست.',
                            'client_balance': client_user.get_effective_token_balance()
                        }, status=status.HTTP_400_BAD_REQUEST)
                    coach.add_tokens(transfer_back)
                    message = f'{transfer_back} توکن از مشتری کسر و به مربی بازگردانده شد.'
            else:
                # مشتری هنوز کد را فعال نکرده: توکن‌ها به صورت رزروشده روی کد ذخیره می‌شوند
                if amount > 0:
                    if not coach.deduct_tokens(amount):
                        return Response({
                            'error': 'موجودی توکن مربی کافی نیست.',
                            'coach_balance': coach.get_effective_token_balance()
                        }, status=status.HTTP_400_BAD_REQUEST)
                    client.pending_tokens += amount
                    client.tokens_reserved_at = timezone.now()
                    client.save(update_fields=['pending_tokens', 'tokens_reserved_at', 'updated_at'])
                    message = f'{amount} توکن روی این کد رزرو شد و بعد از فعال‌سازی به مشتری منتقل می‌شود.'
                else:
                    transfer_back = abs(amount)
                    if client.pending_tokens < transfer_back:
                        return Response({
                            'error': 'توکن رزروشده روی این کد کافی نیست.',
                            'pending_tokens': client.pending_tokens
                        }, status=status.HTTP_400_BAD_REQUEST)
                    client.pending_tokens -= transfer_back
                    if client.pending_tokens == 0:
                        client.tokens_reserved_at = None
                    client.save(update_fields=['pending_tokens', 'tokens_reserved_at', 'updated_at'])
                    coach.add_tokens(transfer_back)
                    message = f'{transfer_back} توکن رزروشده از این کد کسر و به مربی بازگردانده شد.'

        if client.client_user:
            client_balance = client.client_user.token_balance
        else:
            client_balance = client.pending_tokens

        return Response({
            'message': message,
            'coach_balance': coach.token_balance,
            'client_balance': client_balance,
            'pending_tokens': client.pending_tokens,
            'client_id': client.id
        })









@extend_schema(tags=['Client Access'])
class ClientAccessView(APIView):
    """ورود مشتری با کد دسترسی"""
    permission_classes = [AllowAny]
    throttle_classes = [SensitiveScopedRateThrottle]
    throttle_scope = 'client_access'

    @extend_schema(
        request=ClientAccessCodeSerializer,
        responses={200: GymClientSerializer},
        description="""ورود مشتری با کد دسترسی یکبار مصرف.
        پس از ورود موفق، کد غیرفعال می‌شود و مشتری به باشگاه متصل می‌شود.
        کد زمان‌دار پس از انقضا نه فعال می‌شود و نه ورود مجدد می‌دهد (پاسخ 403).

        پاسخ برای نمایش وضعیت اعتبار کد در فرانت دو فیلد دارد (داخل `client`):
        - `access_code_is_permanent`: کد دائمی است یا زمان‌دار
        - `access_code_remaining_seconds`: شمارش معکوس به ثانیه برای کد زمان‌دار
          (null برای کد دائمی، 0 برای منقضی) — فرانت مثل تایمر کد پیامکی
          هر ثانیه از همین عدد کم می‌کند.
        """
    )
    def post(self, request):
        serializer = ClientAccessCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        access_code = serializer.validated_data['access_code'].strip()

        try:
            client = GymClient.objects.select_related('client_user', 'gym_owner').get(access_code=access_code)

            # کد زمان‌دار منقضی‌شده: نه فعال‌سازی، نه ورود مجدد
            if client.access_code_is_expired:
                logger.warning(f"Expired access code used (client #{client.id})")
                return Response({
                    'error': 'کد دسترسی منقضی شده است. از مربی خود کد جدید بگیرید.'
                }, status=status.HTTP_403_FORBIDDEN)

            # اگر قبلا کد فعال شده، اجازه ورود مجدد به همان مشتری بده
            if client.is_used and client.client_user:
                token, _ = Token.objects.get_or_create(user=client.client_user)
                logger.info(f"Client re-entry with access code (client #{client.id})")
                return Response({
                    'message': 'ورود مجدد با موفقیت انجام شد.',
                    'token': token.key,
                    'client': GymClientSerializer(client).data
                })

            # فعال‌سازی اولیه کد
            if not client.client_user:
                temp_phone = _generate_unique_client_phone(client.id)
                client_user = CustomUser.objects.create_user(
                    phone_number=temp_phone,
                    password=None,
                    gym_name=client.gym_owner.gym_name or 'مشتری',
                    account_type=CustomUser.ACCOUNT_TYPE_GYM_CLIENT,
                )
                client_user.set_unusable_password()
                client_user.save(update_fields=['password'])
                client.client_user = client_user

            client.is_used = True
            client.save(update_fields=['is_used', 'client_user', 'updated_at'])

            # انتقال خودکار توکن‌های رزروشده (اگر قبلاً مربی شارژ کرده باشد)
            # اتمیک: یا هر دو (شارژ + صفرشدن رزرو) انجام می‌شود یا هیچ‌کدام
            if client.pending_tokens > 0:
                with transaction.atomic():
                    client.client_user.add_tokens(client.pending_tokens)
                    client.pending_tokens = 0
                    client.tokens_reserved_at = None
                    client.save(update_fields=['pending_tokens', 'tokens_reserved_at', 'updated_at'])

            token, _ = Token.objects.get_or_create(user=client.client_user)

            logger.info(
                f"Access code activated: client #{client.id} of gym "
                f"{client.gym_owner.phone_number} (user: {client.client_user.phone_number})"
            )

            return Response({
                'message': 'با موفقیت به باشگاه متصل شدید.',
                'token': token.key,
                'client': GymClientSerializer(client).data
            })

        except GymClient.DoesNotExist:
            # ورزشکار دو نوع کد می‌گیرد و هر دو را در همین یک فیلد وارد
            # می‌کند. اگر این کد از نوع «دانلود برنامه آماده» باشد، به‌جای
            # پیام «کد معتبر نیست» باید مسیر درستش نشان داده شود.
            share = ProgramShareCode.objects.filter(code=access_code).first()
            if share:
                return Response({
                    'error': 'این کد برای دریافت برنامه آماده است، نه ورود به پنل.',
                    'code_kind': 'program_download',
                    'hint': 'از بخش «دریافت برنامه با کد» همین کد را وارد کنید.',
                    'redeem_endpoint': '/api/programs/redeem-code/',
                }, status=status.HTTP_409_CONFLICT)

            return Response({
                'error': 'کد دسترسی معتبر نیست.'
            }, status=status.HTTP_404_NOT_FOUND)


@extend_schema(tags=['Client Profile'])
class ClientProfileView(APIView):
    """پروفایل مشتری"""
    permission_classes = [IsGymClient]
    # drf_spectacular برای APIView سریالایزر را حدس می‌زند؛ اعلام صریح
    # باعث می‌شود مستندات Swagger شکل واقعی داده را نشان بدهد نه حدس.
    serializer_class = ClientUpdateInfoSerializer

    @extend_schema(
        responses={200: GymClientSerializer},
        description="دریافت اطلاعات پروفایل مشتری"
    )
    def get(self, request):
        """دریافت پروفایل"""
        try:
            client = request.user.client_profile.first()
            if not client:
                return Response({
                    'message': 'شما هنوز به هیچ باشگاهی متصل نیستید.'
                }, status=status.HTTP_404_NOT_FOUND)
            return Response(GymClientSerializer(client).data)
        except Exception:
            logger.exception("Error fetching client profile")
            return Response({
                'error': 'خطا در دریافت پروفایل.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        request=ClientUpdateInfoSerializer,
        responses={200: GymClientSerializer},
        description="ویرایش اطلاعات پروفایل مشتری"
    )
    def patch(self, request):
        """ویرایش اطلاعات"""
        try:
            client = request.user.client_profile.first()
            if not client:
                return Response({
                    'error': 'پروفایل مشتری یافت نشد.'
                }, status=status.HTTP_404_NOT_FOUND)

            serializer = ClientUpdateInfoSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            for key, value in serializer.validated_data.items():
                setattr(client, key, value)
            client.save()

            return Response(GymClientSerializer(client).data)

        except Exception:
            logger.exception("Error updating client profile")
            return Response({
                'error': 'خطا در ویرایش پروفایل.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request):
        return self.patch(request)


# ==================== Token Request Views ====================

@extend_schema(tags=['Token Requests'])
@extend_schema_view(
    list=extend_schema(description="لیست درخواست‌های توکن"),
    create=extend_schema(description="ایجاد درخواست توکن جدید (توسط مشتری)"),
    retrieve=extend_schema(description="جزئیات یک درخواست"),
)
class TokenRequestViewSet(mixins.CreateModelMixin,
                          mixins.RetrieveModelMixin,
                          mixins.ListModelMixin,
                          viewsets.GenericViewSet):
    """مدیریت درخواست‌های توکن.

    عمداً ویرایش/حذف ندارد: درخواست پس از ثبت فقط از مسیر respond تعیین
    تکلیف می‌شود (وگرنه مشتری می‌توانست با PATCH چک موجودی را دور بزند).
    """
    serializer_class = TokenRequestSerializer
    # فقط برای مستندسازی: get_queryset واقعی بر اساس کاربر فیلتر می‌کند
    # و هنگام ساخت schema (بدون request) قابل فراخوانی نیست.
    queryset = TokenRequest.objects.none()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # مربی می‌تواند درخواست‌های مشتریان خود را ببیند
        # مشتری می‌تواند درخواست‌های خودش را ببیند
        user = self.request.user
        return TokenRequest.objects.filter(
            Q(gym_owner=user) | Q(client__client_user=user)
        ).distinct()

    def perform_create(self, serializer):
        # مشتری درخواست می‌دهد
        client = self.request.user.client_profile.first()
        if not client:
            raise serializers.ValidationError('شما به هیچ باشگاهی متصل نیستید.')

        requested_tokens = serializer.validated_data.get('requested_tokens', 0)
        if requested_tokens < 50 or requested_tokens % 50 != 0:
            raise serializers.ValidationError('تعداد توکن درخواستی باید حداقل 50 و مضربی از 50 باشد.')

        coach_balance = client.gym_owner.get_effective_token_balance()
        if requested_tokens > coach_balance:
            raise serializers.ValidationError(
                f'درخواست شما بیشتر از موجودی مربی است. حداکثر قابل درخواست: {coach_balance}'
            )

        serializer.save(
            client=client,
            gym_owner=client.gym_owner
        )

    @extend_schema(
        request=TokenRequestResponseSerializer,
        responses={200: TokenRequestSerializer},
        description="پاسخ به درخواست توکن (تایید یا رد)"
    )
    @action(detail=True, methods=['post'])
    def respond(self, request, pk=None):
        """تایید یا رد درخواست توسط مربی"""
        token_request = self.get_object()

        # بررسی اینکه فقط مربی مربوطه بتواند پاسخ دهد
        if token_request.gym_owner != request.user:
            return Response({
                'error': 'شما مجاز به پاسخ به این درخواست نیستید.'
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = TokenRequestResponseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        action_type = serializer.validated_data['action']
        response_message = serializer.validated_data.get('response_message', '')

        if action_type == 'approve':
            success, message = token_request.approve(response_message)
        else:
            success, message = token_request.reject(response_message)

        if not success:
            return Response({
                'error': message
            }, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            f"Token request #{token_request.id} "
            f"{'approved' if action_type == 'approve' else 'rejected'} "
            f"by {request.user.phone_number} ({token_request.requested_tokens} tokens)"
        )

        return Response({
            'message': message,
            'token_request': TokenRequestSerializer(token_request).data
        })


# ==================== Content Pages Views ====================

@extend_schema(tags=['Homepage'])
class HomePageView(APIView):
    """صفحه اصلی"""
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: HomePageSerializer},
        description="دریافت محتوای صفحه اصلی"
    )
    def get(self, request):
        homepage = HomePage.objects.filter(is_active=True).first()
        if not homepage:
            return Response({
                'message': 'محتوای صفحه اصلی هنوز تنظیم نشده است.'
            }, status=status.HTTP_404_NOT_FOUND)
        return Response(HomePageSerializer(homepage).data)


@extend_schema(tags=['Blog'])
@extend_schema_view(
    list=extend_schema(description="لیست پست‌های منتشر شده وبلاگ"),
    retrieve=extend_schema(description="جزئیات یک پست وبلاگ"),
)
class BlogPostViewSet(viewsets.ReadOnlyModelViewSet):
    """وبلاگ"""
    queryset = BlogPost.objects.filter(is_published=True)
    serializer_class = BlogPostSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'


@extend_schema(tags=['Contact'])
class ContactMessageView(APIView):
    """تماس با ما"""
    permission_classes = [AllowAny]

    @extend_schema(
        request=ContactMessageSerializer,
        responses={201: ContactMessageSerializer},
        description="ارسال پیام تماس با ما"
    )
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'message': 'پیام شما با موفقیت ارسال شد.'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Team'])
class TeamMemberListView(APIView):
    """لیست اعضای تیم"""
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: TeamMemberSerializer(many=True)},
        description="دریافت لیست اعضای تیم"
    )
    def get(self, request):
        members = TeamMember.objects.all()
        return Response(TeamMemberSerializer(members, many=True).data)


@extend_schema(tags=['Features'])
class FeatureListView(APIView):
    """لیست امکانات"""
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: FeatureSerializer(many=True)},
        description="دریافت لیست امکانات فعال"
    )
    def get(self, request):
        features = Feature.objects.filter(is_active=True)
        return Response(FeatureSerializer(features, many=True).data)
