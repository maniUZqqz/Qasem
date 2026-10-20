# -*- coding: utf-8 -*-
"""تست‌های پرداخت کارت‌به‌کارت، دفتر حساب و محاسبه هزینه هوش مصنوعی.

محور اصلی این تست‌ها یک چیز است: هیچ توکنی نباید بدون تایید صریح مدیر آزاد
شود. هر مسیری که بتواند توکن بدهد اینجا بسته شده و آزمایش می‌شود.
"""
import io
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib import admin as django_admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status

from app.admin import TokenPurchaseAdmin
from app.models import (
    APIConfig, CardPaymentAccount, ClientProgram, DiscountCode, LedgerEntry,
    TokenPackage, TokenPurchase,
)
from .utils import BaseAPITestCase, create_user


def _png_bytes():
    """کوچک‌ترین PNG معتبر — Pillow باید بتواند بازش کند."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new('RGB', (4, 4), (219, 230, 255)).save(buf, format='PNG')
    return buf.getvalue()


def _receipt_file(name='receipt.png'):
    return SimpleUploadedFile(name, _png_bytes(), content_type='image/png')


class MediaIsolatedTestCase(BaseAPITestCase):
    """رسیدهای تست در یک پوشه موقت نوشته و بعد پاک می‌شوند.

    بدون این، هر اجرای تست فایل‌های واقعی داخل media/ پروژه جا می‌گذاشت.
    """

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='gym-test-media-')
        cls._private_root = tempfile.mkdtemp(prefix='gym-test-private-')
        cls._media_override = override_settings(
            MEDIA_ROOT=cls._media_root,
            PRIVATE_MEDIA_ROOT=cls._private_root,
        )
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        shutil.rmtree(cls._private_root, ignore_errors=True)


class CardPaymentFlowTests(MediaIsolatedTestCase):
    """جریان کامل: ثبت سفارش → نمایش کارت → بارگذاری رسید → تایید مدیر"""

    purchase_url = '/api/purchase-token/'
    card_url = '/api/payment-card/'

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.package = TokenPackage.objects.create(
            name='پایه', token_amount=50, price_per_50_tokens=Decimal('100000')
        )
        self.card = CardPaymentAccount.objects.create(
            title='کارت شریک اول',
            card_number='6037991122334455',
            card_holder='مهدی رنجبران',
            bank_name='ملی',
            is_active=True,
        )
        self.auth(self.user)

    # ---------------- اطلاعات کارت ----------------

    def test_card_info_returned_when_active(self):
        response = self.client.get(self.card_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['enabled'])
        self.assertEqual(
            response.data['card_account']['card_number'], '6037991122334455'
        )
        self.assertEqual(
            response.data['card_account']['formatted_card_number'],
            '6037-9911-2233-4455',
        )

    def test_card_info_disabled_when_no_active_account(self):
        CardPaymentAccount.objects.update(is_active=False)
        response = self.client.get(self.card_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['enabled'])
        self.assertIsNone(response.data['card_account'])

    def test_only_one_card_stays_active(self):
        second = CardPaymentAccount.objects.create(
            title='کارت شریک دوم', card_number='5022291122334455',
            card_holder='شریک دوم', is_active=True,
        )
        self.card.refresh_from_db()
        self.assertTrue(second.is_active)
        self.assertFalse(self.card.is_active)

    # ---------------- ثبت سفارش ----------------

    def test_card_purchase_creates_awaiting_receipt_order(self):
        response = self.client.post(self.purchase_url, {
            'token_amount': 100, 'payment_method': 'card',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'awaiting_receipt')
        self.assertIsNone(response.data['payment_url'])
        self.assertEqual(response.data['tokens_added'], 0)
        self.assertEqual(
            response.data['card_account']['card_number'], '6037991122334455'
        )

        purchase = TokenPurchase.objects.get()
        self.assertEqual(purchase.payment_method, TokenPurchase.METHOD_CARD)
        self.assertEqual(purchase.status, 'awaiting_receipt')
        self.assertEqual(purchase.card_account_id, self.card.id)

        # مهم‌ترین ادعا: هنوز هیچ توکنی داده نشده است
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_card_purchase_rejected_without_active_card(self):
        CardPaymentAccount.objects.update(is_active=False)
        response = self.client.post(self.purchase_url, {
            'token_amount': 100, 'payment_method': 'card',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(TokenPurchase.objects.count(), 0)

    # ---------------- بارگذاری رسید ----------------

    def _create_card_purchase(self):
        self.client.post(self.purchase_url, {
            'token_amount': 100, 'payment_method': 'card',
        })
        return TokenPurchase.objects.get()

    def test_receipt_upload_moves_to_review_without_granting_tokens(self):
        purchase = self._create_card_purchase()

        response = self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file(), 'receipt_reference': '123456'},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'under_review')
        self.assertTrue(purchase.receipt_image)
        self.assertEqual(purchase.receipt_reference, '123456')
        self.assertIsNotNone(purchase.receipt_uploaded_at)

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_other_user_cannot_upload_receipt(self):
        purchase = self._create_card_purchase()
        intruder = create_user(phone='09129999999')
        self.auth(intruder)

        response = self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'awaiting_receipt')

    def test_receipt_rejected_for_gateway_purchase(self):
        purchase = TokenPurchase.objects.create(
            user=self.user, token_amount=100,
            original_price=Decimal('200000'), final_price=Decimal('200000'),
            status='pending', payment_method=TokenPurchase.METHOD_GATEWAY,
        )
        response = self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_receipt_rejected_after_paid(self):
        purchase = self._create_card_purchase()
        purchase.status = 'paid'
        purchase.save(update_fields=['status'])

        response = self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ---------------- تایید مدیر ----------------

    def _approve(self, purchase, actor):
        model_admin = TokenPurchaseAdmin(TokenPurchase, django_admin.site)
        request = MagicMock()
        request.user = actor
        queryset = TokenPurchase.objects.filter(pk=purchase.pk)
        model_admin.approve_card_receipts(request, queryset)

    def test_admin_approval_grants_tokens_once(self):
        purchase = self._create_card_purchase()
        self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        staff = create_user(phone='09120000777', is_staff=True)

        self._approve(purchase, staff)

        purchase.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(purchase.status, 'paid')
        self.assertEqual(purchase.reviewed_by_id, staff.id)
        self.assertEqual(self.user.token_balance, 100)

        # اجرای دوباره نباید دوباره شارژ کند
        self._approve(purchase, staff)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100)

    def test_admin_approval_refuses_order_without_receipt(self):
        purchase = self._create_card_purchase()
        staff = create_user(phone='09120000777', is_staff=True)

        self._approve(purchase, staff)

        purchase.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(purchase.status, 'awaiting_receipt')
        self.assertEqual(self.user.token_balance, 0)

    def test_admin_rejection_lets_user_retry(self):
        purchase = self._create_card_purchase()
        self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        staff = create_user(phone='09120000777', is_staff=True)

        model_admin = TokenPurchaseAdmin(TokenPurchase, django_admin.site)
        request = MagicMock()
        request.user = staff
        model_admin.reject_card_receipts(
            request, TokenPurchase.objects.filter(pk=purchase.pk)
        )

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'rejected')
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

        # کاربر می‌تواند رسید تازه بگذارد و دوباره به صف بررسی برود
        response = self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file('again.png')},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'under_review')

    # ---------------- مرز درگاه و کارت ----------------

    @patch('app.views_extended.PaymentGateway.get_active_gateway')
    def test_gateway_callback_cannot_settle_card_purchase(self, mock_gateway):
        gateway = MagicMock()
        gateway.verify_payment.return_value = {'success': True, 'ref_id': 'FAKE'}
        mock_gateway.return_value = gateway

        purchase = self._create_card_purchase()
        self.unauth()

        response = self.client.get(
            f'/api/payment-callback/?order_id={purchase.id}&Status=OK'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        purchase.refresh_from_db()
        self.user.refresh_from_db()
        self.assertNotEqual(purchase.status, 'paid')
        self.assertEqual(self.user.token_balance, 0)
        gateway.verify_payment.assert_not_called()

    def test_my_purchases_lists_only_own_orders(self):
        self._create_card_purchase()
        other = create_user(phone='09128888888')
        TokenPurchase.objects.create(
            user=other, token_amount=50,
            original_price=Decimal('100000'), final_price=Decimal('100000'),
            status='pending',
        )

        response = self.client.get('/api/my-purchases/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['purchases']), 1)
        self.assertEqual(response.data['purchases'][0]['payment_method'], 'card')


class ReceiptPrivacyTests(MediaIsolatedTestCase):
    """رسید بانکی داده‌ی حساس است و نباید عمومی سرو شود."""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        TokenPackage.objects.create(
            name='پایه', token_amount=50, price_per_50_tokens=Decimal('100000')
        )
        CardPaymentAccount.objects.create(
            title='کارت', card_number='6037991122334455',
            card_holder='مالک', is_active=True,
        )
        self.auth(self.user)
        self.client.post('/api/purchase-token/', {
            'token_amount': 100, 'payment_method': 'card',
        })
        self.purchase = TokenPurchase.objects.get()
        self.client.post(
            f'/api/purchase-token/{self.purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        self.purchase.refresh_from_db()

    def test_receipt_is_stored_outside_public_media(self):
        from django.conf import settings

        path = self.purchase.receipt_image.path
        self.assertTrue(path.startswith(settings.PRIVATE_MEDIA_ROOT))
        self.assertFalse(path.startswith(settings.MEDIA_ROOT))

    def test_owner_can_fetch_receipt(self):
        response = self.client.get(
            f'/api/purchase-token/{self.purchase.id}/receipt/file/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_staff_can_fetch_receipt(self):
        staff = create_user(phone='09120000777', is_staff=True)
        self.auth(staff)
        response = self.client.get(
            f'/api/purchase-token/{self.purchase.id}/receipt/file/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_other_user_cannot_fetch_receipt(self):
        intruder = create_user(phone='09129999999')
        self.auth(intruder)
        response = self.client.get(
            f'/api/purchase-token/{self.purchase.id}/receipt/file/'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_cannot_fetch_receipt(self):
        self.unauth()
        response = self.client.get(
            f'/api/purchase-token/{self.purchase.id}/receipt/file/'
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_receipt_url_points_at_protected_route(self):
        self.assertEqual(
            self.purchase.receipt_url,
            f'/api/purchase-token/{self.purchase.id}/receipt/file/',
        )


class AdminReceiptPageTests(MediaIsolatedTestCase):
    """صفحه‌ی ادمین سفارش دارای رسید باید بدون خطا باز شود.

    رسید در فضای خصوصی بدون base_url ذخیره می‌شود؛ اگر فیلد فایل در ادمین
    قابل ویرایش بماند، ویجت آپلود جنگو برای ساختن لینک .url را صدا می‌زند و
    صفحه با ValueError می‌شکند. این تست دقیقاً همان را می‌گیرد.
    """

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        TokenPackage.objects.create(
            name='پایه', token_amount=50, price_per_50_tokens=Decimal('100000')
        )
        CardPaymentAccount.objects.create(
            title='کارت', card_number='6037991122334455',
            card_holder='مالک', is_active=True,
        )
        self.auth(self.user)
        self.client.post('/api/purchase-token/', {
            'token_amount': 100, 'payment_method': 'card',
        })
        self.purchase = TokenPurchase.objects.get()
        self.client.post(
            f'/api/purchase-token/{self.purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )
        self.unauth()

    def test_admin_change_page_renders_with_receipt(self):
        admin_user = create_user(
            phone='09120000555', is_staff=True, is_superuser=True
        )
        self.client.force_login(admin_user)

        response = self.client.get(
            f'/admin/app/tokenpurchase/{self.purchase.id}/change/'
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        # پیش‌نمایش باید به مسیر محافظت‌شده اشاره کند، نه به /media/
        self.assertIn(f'/api/purchase-token/{self.purchase.id}/receipt/file/', body)
        self.assertNotIn('/media/payment_receipts/', body)

    def test_admin_changelist_renders(self):
        admin_user = create_user(
            phone='09120000556', is_staff=True, is_superuser=True
        )
        self.client.force_login(admin_user)
        response = self.client.get('/admin/app/tokenpurchase/')
        self.assertEqual(response.status_code, 200)

    def test_ledger_admin_is_read_only(self):
        admin_user = create_user(
            phone='09120000557', is_staff=True, is_superuser=True
        )
        self.client.force_login(admin_user)

        # صفحه افزودن سطر دفتر حساب نباید در دسترس باشد
        response = self.client.get('/admin/app/ledgerentry/add/')
        self.assertIn(response.status_code, (403, 302))

        response = self.client.get('/admin/app/ledgerentry/')
        self.assertEqual(response.status_code, 200)


class LedgerTests(MediaIsolatedTestCase):
    """دفتر حساب باید فقط افزودنی باشد و هر رویداد مالی را ثبت کند."""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        TokenPackage.objects.create(
            name='پایه', token_amount=50, price_per_50_tokens=Decimal('100000')
        )
        CardPaymentAccount.objects.create(
            title='کارت', card_number='6037991122334455',
            card_holder='مالک', is_active=True,
        )
        self.auth(self.user)

    def test_entry_cannot_be_edited_or_deleted(self):
        entry = LedgerEntry.record(
            LedgerEntry.TYPE_TOKEN_GRANT, user=self.user, tokens=50,
            reference='test#1',
        )
        self.assertIsNotNone(entry)

        entry.tokens = 5000
        with self.assertRaises(ValueError):
            entry.save()

        with self.assertRaises(ValueError):
            entry.delete()

        entry.refresh_from_db()
        self.assertEqual(entry.tokens, 50)

    def test_approved_card_purchase_writes_income_and_grant(self):
        self.client.post('/api/purchase-token/', {
            'token_amount': 100, 'payment_method': 'card',
        })
        purchase = TokenPurchase.objects.get()
        self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )

        staff = create_user(phone='09120000777', is_staff=True)
        model_admin = TokenPurchaseAdmin(TokenPurchase, django_admin.site)
        request = MagicMock()
        request.user = staff
        model_admin.approve_card_receipts(
            request, TokenPurchase.objects.filter(pk=purchase.pk)
        )

        entries = LedgerEntry.objects.filter(reference=f'purchase#{purchase.id}')
        types = set(entries.values_list('entry_type', flat=True))
        self.assertIn(LedgerEntry.TYPE_PURCHASE, types)
        self.assertIn(LedgerEntry.TYPE_TOKEN_GRANT, types)

        income = entries.get(entry_type=LedgerEntry.TYPE_PURCHASE)
        self.assertEqual(income.amount, purchase.final_price)

        grant = entries.get(entry_type=LedgerEntry.TYPE_TOKEN_GRANT)
        self.assertEqual(grant.tokens, 100)

    def test_discount_commission_recorded_as_platform_cost(self):
        partner = create_user(phone='09127777777')
        DiscountCode.objects.create(
            code='PARTNER20', discount_percent=20, creator=partner,
            commission_percent=10,
        )

        self.client.post('/api/purchase-token/', {
            'token_amount': 100, 'payment_method': 'card',
            'discount_code': 'PARTNER20',
        })
        purchase = TokenPurchase.objects.get()
        self.client.post(
            f'/api/purchase-token/{purchase.id}/receipt/',
            {'receipt_image': _receipt_file()},
            format='multipart',
        )

        staff = create_user(phone='09120000777', is_staff=True)
        model_admin = TokenPurchaseAdmin(TokenPurchase, django_admin.site)
        request = MagicMock()
        request.user = staff
        model_admin.approve_card_receipts(
            request, TokenPurchase.objects.filter(pk=purchase.pk)
        )

        commission = LedgerEntry.objects.get(
            entry_type=LedgerEntry.TYPE_COMMISSION,
            reference=f'purchase#{purchase.id}',
        )
        # سهم شریک برای پلتفرم هزینه است، پس منفی ثبت می‌شود
        self.assertLess(commission.amount, 0)
        self.assertEqual(commission.counterparty_id, partner.id)


class AICostTests(BaseAPITestCase):
    """هزینه واقعی مدل باید بر اساس تعرفه ثبت‌شده روی هر برنامه بنشیند."""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.user.token_balance = 500
        self.user.save()
        self.auth(self.user)

    def test_cost_is_zero_when_no_pricing_configured(self):
        self.assertEqual(
            APIConfig.estimate_cost(1_000_000, 1_000_000), Decimal('0.0000')
        )

    def test_cost_uses_configured_model_pricing(self):
        APIConfig.objects.create(
            name='متیس', api_key='k', model_name='gpt-4o-mini',
            input_price_per_million=Decimal('30000'),
            output_price_per_million=Decimal('120000'),
            is_active=True,
        )
        # نیم میلیون ورودی + ربع میلیون خروجی
        cost = APIConfig.estimate_cost(500_000, 250_000)
        self.assertEqual(cost, Decimal('45000.0000'))

    @patch('app.views.generate_program')
    def test_generated_program_stores_model_usage_and_cost(self, mock_generate):
        from ai_engine.ai_generator import AIUsage

        APIConfig.objects.create(
            name='متیس', api_key='k', model_name='gpt-4o-mini',
            input_price_per_million=Decimal('30000'),
            output_price_per_million=Decimal('120000'),
            is_active=True,
        )
        mock_generate.return_value = (
            'برنامه ورزشی', 'برنامه غذایی',
            AIUsage(model_name='gpt-4o-mini', input_tokens=10_000, output_tokens=5_000),
        )

        response = self.client.post('/api/programs/generate/', {
            'name': 'علی', 'program_days': 3, 'program_type': 'both',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        program = ClientProgram.objects.get()
        self.assertEqual(program.ai_model_name, 'gpt-4o-mini')
        self.assertEqual(program.ai_input_tokens, 10_000)
        self.assertEqual(program.ai_output_tokens, 5_000)
        # 10k*30000/1M + 5k*120000/1M = 300 + 600
        self.assertEqual(program.ai_cost, Decimal('900.0000'))

        cost_entry = LedgerEntry.objects.get(
            entry_type=LedgerEntry.TYPE_AI_COST,
            reference=f'program#{program.id}',
        )
        self.assertEqual(cost_entry.amount, Decimal('-900.0000'))

        spend_entry = LedgerEntry.objects.get(
            entry_type=LedgerEntry.TYPE_TOKEN_SPEND,
            reference=f'program#{program.id}',
        )
        self.assertEqual(spend_entry.tokens, -50)
