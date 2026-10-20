# -*- coding: utf-8 -*-
"""تست‌های مدل‌ها: کاربر، کیف پول توکن، کد تخفیف، بسته توکن، مشتری باشگاه، درخواست توکن"""
from decimal import Decimal

from django.test import TestCase

from app.models import (
    APIConfig, CustomUser, DiscountCode, DiscountCodeUsage,
    GymBrand, GymClient, PlatformSettings, TokenPackage, TokenRequest,
)
from .utils import create_user


class CustomUserManagerTests(TestCase):
    def test_create_user_requires_phone(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_user(phone_number='', password='x')

    def test_create_superuser_sets_flags(self):
        admin = CustomUser.objects.create_superuser(phone_number='09121111111', password='AdminPass123')
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_active)

    def test_str_contains_phone(self):
        user = create_user(gym_name='باشگاه تست')
        self.assertIn(user.phone_number, str(user))


class TokenWalletTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.user.token_balance = 100
        self.user.save()

    def test_has_enough_tokens(self):
        self.assertTrue(self.user.has_enough_tokens(100))
        self.assertFalse(self.user.has_enough_tokens(101))

    def test_deduct_tokens_success(self):
        self.assertTrue(self.user.deduct_tokens(40))
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 60)

    def test_deduct_tokens_insufficient(self):
        self.assertFalse(self.user.deduct_tokens(150))
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100)

    def test_add_tokens(self):
        self.user.add_tokens(50)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 150)

    def test_gym_brand_copies_initial_balance(self):
        brand = GymBrand.objects.create(user=self.user, gym_name='باشگاه تست')
        self.assertEqual(brand.token_balance, 100)

    def test_deduct_syncs_user_and_brand(self):
        brand = GymBrand.objects.create(user=self.user, gym_name='باشگاه تست')
        self.assertTrue(self.user.deduct_tokens(30))
        brand.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(brand.token_balance, 70)
        self.assertEqual(self.user.token_balance, 70)

    def test_add_syncs_user_and_brand(self):
        brand = GymBrand.objects.create(user=self.user, gym_name='باشگاه تست')
        self.user.add_tokens(25)
        brand.refresh_from_db()
        self.assertEqual(brand.token_balance, 125)

    def test_effective_balance_uses_brand_wallet(self):
        brand = GymBrand.objects.create(user=self.user, gym_name='باشگاه تست')
        brand.token_balance = 500
        brand.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_effective_token_balance(), 500)
        self.assertEqual(self.user.token_balance, 500)  # سینک معکوس


class DiscountCodeTests(TestCase):
    def setUp(self):
        self.creator = create_user(phone='09122222222')
        self.buyer = create_user(phone='09123333333')
        self.code = DiscountCode.objects.create(
            code='OFF20', discount_percent=20, creator=self.creator
        )

    def test_apply_discount_math(self):
        final_price, discount = self.code.apply_discount(Decimal('1000'))
        self.assertEqual(final_price, Decimal('800'))
        self.assertEqual(discount, Decimal('200'))

    def test_inactive_code_rejected(self):
        self.code.is_active = False
        self.code.save()
        can_use, _ = self.code.can_use(self.buyer)
        self.assertFalse(can_use)

    def test_single_use_per_user(self):
        DiscountCodeUsage.objects.create(
            discount_code=self.code, user=self.buyer,
            purchase_amount=Decimal('1000'), discount_amount=Decimal('200'),
            commission_amount=Decimal('80'),
        )
        can_use, _ = self.code.can_use(self.buyer)
        self.assertFalse(can_use)
        # کاربر دیگر همچنان می‌تواند استفاده کند
        other = create_user(phone='09124444444')
        can_use_other, _ = self.code.can_use(other)
        self.assertTrue(can_use_other)


class TokenPackageTests(TestCase):
    def test_calculate_price(self):
        package = TokenPackage.objects.create(
            name='پایه', token_amount=100, price_per_50_tokens=Decimal('50000')
        )
        self.assertEqual(package.calculate_price(), Decimal('100000'))
        self.assertEqual(package.calculate_price(150), Decimal('150000'))


class GymClientModelTests(TestCase):
    def setUp(self):
        self.owner = create_user(gym_name='باشگاه تست')

    def test_access_code_generated_automatically(self):
        """طول پیش‌فرض کد ۴ رقم است"""
        client = GymClient.objects.create(gym_owner=self.owner)
        self.assertTrue(client.access_code)
        self.assertEqual(len(client.access_code), 4)
        self.assertTrue(client.access_code.isdigit())

    def test_access_code_length_follows_platform_settings(self):
        """مدیر می‌تواند طول کد را از تنظیمات سامانه تغییر دهد"""
        settings_obj = PlatformSettings.get_solo()
        settings_obj.access_code_length = 8
        settings_obj.save()

        client = GymClient.objects.create(gym_owner=self.owner)
        self.assertEqual(len(client.access_code), 8)

    def test_access_codes_are_unique(self):
        codes = {GymClient.objects.create(gym_owner=self.owner).access_code for _ in range(20)}
        self.assertEqual(len(codes), 20)

    def test_code_grows_when_shorter_space_is_exhausted(self):
        """اگر همه ترکیب‌های طول تنظیم‌شده مصرف شده باشد، یک رقم اضافه می‌شود"""
        settings_obj = PlatformSettings.get_solo()
        settings_obj.access_code_length = 1
        settings_obj.save()

        for digit in '0123456789':
            GymClient.objects.create(gym_owner=self.owner, access_code=digit)

        client = GymClient.objects.create(gym_owner=self.owner)
        self.assertEqual(len(client.access_code), 2)


class TokenRequestTests(TestCase):
    def setUp(self):
        self.owner = create_user(gym_name='باشگاه تست')
        self.owner.token_balance = 200
        self.owner.save()
        self.gym_client = GymClient.objects.create(gym_owner=self.owner, name='مشتری تست')

    def _make_request(self, tokens=50):
        return TokenRequest.objects.create(
            client=self.gym_client, gym_owner=self.owner, requested_tokens=tokens
        )

    def test_approve_without_client_user_reserves_pending(self):
        req = self._make_request(50)
        success, _ = req.approve('تایید شد')
        self.assertTrue(success)
        self.owner.refresh_from_db()
        self.gym_client.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(self.owner.token_balance, 150)
        self.assertEqual(self.gym_client.pending_tokens, 50)

    def test_approve_with_client_user_adds_directly(self):
        client_user = create_user(phone='09990000001')
        self.gym_client.client_user = client_user
        self.gym_client.save()
        req = self._make_request(50)
        success, _ = req.approve()
        self.assertTrue(success)
        client_user.refresh_from_db()
        self.assertEqual(client_user.token_balance, 50)

    def test_approve_insufficient_owner_balance(self):
        self.owner.token_balance = 10
        self.owner.save()
        req = self._make_request(50)
        success, _ = req.approve()
        self.assertFalse(success)
        self.assertEqual(req.status, 'pending')

    def test_double_approve_blocked(self):
        req = self._make_request(50)
        req.approve()
        success, _ = req.approve()
        self.assertFalse(success)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.token_balance, 150)  # فقط یکبار کسر شده

    def test_reject(self):
        req = self._make_request(50)
        success, _ = req.reject('رد شد')
        self.assertTrue(success)
        self.assertEqual(req.status, 'rejected')
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.token_balance, 200)


class APIConfigTests(TestCase):
    """ارائه‌دهنده‌ها یک زنجیره‌ی اولویت‌دار هستند، نه یک رکورد یکتا.

    رفتار قبلی «فقط یکی می‌تواند فعال باشد» عمداً حذف شد: بدون چند
    ارائه‌دهنده‌ی هم‌زمان فعال، جایگزینی خودکار هنگام قطعی ممکن نیست.
    """

    def test_multiple_providers_can_be_active(self):
        APIConfig.objects.create(name='اول', api_key='k1', priority=1, is_active=True)
        APIConfig.objects.create(name='دوم', api_key='k2', priority=2, is_active=True)
        self.assertEqual(APIConfig.objects.filter(is_active=True).count(), 2)

    def test_chain_is_ordered_by_priority(self):
        APIConfig.objects.create(name='سوم', api_key='k3', priority=3, is_active=True)
        APIConfig.objects.create(name='اول', api_key='k1', priority=1, is_active=True)
        APIConfig.objects.create(name='دوم', api_key='k2', priority=2, is_active=True)

        self.assertEqual(
            [p.name for p in APIConfig.get_chain()], ['اول', 'دوم', 'سوم']
        )

    def test_chain_excludes_inactive(self):
        APIConfig.objects.create(name='فعال', api_key='k1', priority=1, is_active=True)
        APIConfig.objects.create(name='خاموش', api_key='k2', priority=2, is_active=False)

        self.assertEqual([p.name for p in APIConfig.get_chain()], ['فعال'])

    def test_equal_priority_breaks_by_id_deterministically(self):
        """دو ارائه‌دهنده با اولویت یکسان نباید هر بار جای هم را بگیرند."""
        first = APIConfig.objects.create(name='الف', api_key='k1', priority=1, is_active=True)
        second = APIConfig.objects.create(name='ب', api_key='k2', priority=1, is_active=True)

        for _ in range(3):
            self.assertEqual(
                [p.pk for p in APIConfig.get_chain()], [first.pk, second.pk]
            )

    def test_get_active_config_default_when_empty(self):
        config = APIConfig.get_active_config()
        self.assertEqual(config['api_key'], '')
        self.assertIn('base_url', config)

    def test_get_active_config_returns_highest_priority(self):
        APIConfig.objects.create(
            name='پشتیبان', api_key='backup', priority=5, is_active=True
        )
        APIConfig.objects.create(
            name='اصلی', api_key='secret', model_name='gpt-4o-mini',
            priority=1, is_active=True,
        )
        config = APIConfig.get_active_config()
        self.assertEqual(config['api_key'], 'secret')


class LocalProviderTests(TestCase):
    """مدل محلی (اولاما و مشابه) بدون کلید API باید کار کند."""

    def test_local_provider_needs_no_api_key(self):
        provider = APIConfig.objects.create(
            name='اولامای سرور خودم',
            provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://192.168.1.50:11434/v1',
            model_name='llama3.2',
            api_key='',
            priority=1,
        )
        self.assertTrue(provider.is_local)
        # کتابخانه OpenAI بدون کلید کلاینت نمی‌سازد، پس مقدار جانشین می‌گیرد
        self.assertEqual(provider.resolved_api_key, 'local')
        self.assertEqual(provider.as_config()['api_key'], 'local')

    def test_local_provider_keeps_explicit_key_if_given(self):
        provider = APIConfig.objects.create(
            name='سرور با کلید',
            provider_type=APIConfig.TYPE_LOCAL,
            base_url='https://ai.example.com/v1',
            model_name='llama3.2',
            api_key='my-secret',
        )
        self.assertEqual(provider.resolved_api_key, 'my-secret')

    def test_cloud_provider_without_key_stays_empty(self):
        """سرویس ابری بدون کلید نباید کلید ساختگی بگیرد — باید خطا بدهد."""
        provider = APIConfig.objects.create(
            name='ابری ناقص',
            provider_type=APIConfig.TYPE_API,
            api_key='',
        )
        self.assertEqual(provider.resolved_api_key, '')

    def test_config_carries_timeout(self):
        provider = APIConfig.objects.create(
            name='کند', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434/v1', model_name='llama3.2',
            timeout_seconds=300,
        )
        self.assertEqual(provider.as_config()['timeout_seconds'], 300)
