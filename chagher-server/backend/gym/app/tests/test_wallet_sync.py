# -*- coding: utf-8 -*-
"""تست‌های هماهنگی کیف پول توکن — سناریوهای دستکاری همزمان (ادمین + API)

قانون: برای مالک باشگاه، کیف پول برند (GymBrand.token_balance) مرجع واحد است
و CustomUser.token_balance فقط آینه آن است.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase
from rest_framework import status

from app.admin import CustomUserAdmin
from app.models import ClientProgram, CustomUser, GymBrand
from .utils import BaseAPITestCase, create_user


class WalletSourceOfTruthTests(TestCase):
    """کیف پول برند مرجع است و مقدار کهنه‌ی در حافظه نباید آن را خراب کند"""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user()
        self.user.token_balance = 100
        self.user.save()
        self.brand = GymBrand.objects.create(user=self.user, gym_name='باشگاه تست')

    def test_stale_full_save_does_not_clobber_wallet(self):
        """سناریوی اصلی گیج‌زدن: ادمین کیف پول را عوض می‌کند، بعد مربی
        (با نمونه‌ی کهنه در حافظه) پروفایلش را ذخیره می‌کند — کیف پول نباید برگردد."""
        stale_user = CustomUser.objects.get(pk=self.user.pk)  # در حافظه: 100

        # ادمین کیف پول برند را به 500 تغییر می‌دهد
        self.brand.token_balance = 500
        self.brand.save()

        # مربی پروفایلش را ذخیره می‌کند (ذخیره کامل با مقدار کهنه 100)
        stale_user.gym_name = 'باشگاه ویرایش‌شده'
        stale_user.save()

        self.brand.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 500)  # کیف پول دست‌نخورده
        self.assertEqual(self.user.token_balance, 500)   # آینه هماهنگ

    def test_explicit_token_change_pushes_to_wallet(self):
        """تغییر عمدی موجودی کاربر (update_fields) باید کیف پول را هم به‌روز کند"""
        self.user.token_balance = 300
        self.user.save(update_fields=['token_balance'])

        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 300)

    def test_brand_save_mirrors_user(self):
        """ذخیره برند (مثلاً از ادمین) باید آینه‌ی کاربر را به‌روز کند"""
        self.brand.token_balance = 250
        self.brand.save()

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 250)

    def test_deduct_reads_fresh_wallet_not_stale_cache(self):
        """کسر توکن باید موجودی تازه را ببیند، نه مقدار کهنه در حافظه را"""
        stale_user = CustomUser.objects.get(pk=self.user.pk)  # در حافظه: 100

        # در این فاصله کیف پول به 30 کاهش یافته
        self.brand.token_balance = 30
        self.brand.save()

        # کسر 50 باید رد شود چون موجودی واقعی 30 است
        self.assertFalse(stale_user.deduct_tokens(50))
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 30)

        # کسر 20 مجاز است
        self.assertTrue(stale_user.deduct_tokens(20))
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 10)

    def test_deduct_invalid_amounts(self):
        self.assertFalse(self.user.deduct_tokens(0))
        self.assertFalse(self.user.deduct_tokens(-10))
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 100)


class UserWithoutBrandConcurrencyTests(TestCase):
    """کاربر بدون برند (ورزشکار): کسر شرطی باید در برابر نمونه‌های کهنه امن باشد"""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user()
        self.user.token_balance = 100
        self.user.save()

    def test_two_stale_instances_cannot_overdraw(self):
        instance_a = CustomUser.objects.get(pk=self.user.pk)
        instance_b = CustomUser.objects.get(pk=self.user.pk)

        self.assertTrue(instance_a.deduct_tokens(80))
        # نمونه‌ی دوم هنوز فکر می‌کند 100 دارد ولی دیتابیس 20 دارد
        self.assertFalse(instance_b.deduct_tokens(80))

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 20)

    def test_add_tokens_uses_db_value(self):
        stale = CustomUser.objects.get(pk=self.user.pk)
        self.user.deduct_tokens(50)  # دیتابیس: 50

        stale.add_tokens(10)  # باید 50+10 شود، نه 100+10
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 60)


class AdminWalletEditTests(TestCase):
    """ویرایش موجودی از پنل ادمین باید به کیف پول برند (مرجع) منتقل شود"""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user()
        self.user.token_balance = 100
        self.user.save()
        self.brand = GymBrand.objects.create(user=self.user, gym_name='باشگاه تست')
        self.model_admin = CustomUserAdmin(CustomUser, admin.site)

    def _admin_save(self, obj, changed_fields):
        fake_form = SimpleNamespace(changed_data=changed_fields)
        self.model_admin.save_model(request=None, obj=obj, form=fake_form, change=True)

    def test_admin_token_edit_updates_wallet(self):
        admin_instance = CustomUser.objects.get(pk=self.user.pk)
        admin_instance.token_balance = 700
        self._admin_save(admin_instance, ['token_balance'])

        self.brand.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 700)
        self.assertEqual(self.user.token_balance, 700)

    def test_admin_edit_other_fields_keeps_wallet(self):
        """ادمین فقط نام باشگاه را عوض می‌کند — موجودی نباید تغییر کند"""
        self.brand.token_balance = 400
        self.brand.save()

        admin_instance = CustomUser.objects.get(pk=self.user.pk)
        admin_instance.gym_name = 'نام جدید'
        self._admin_save(admin_instance, ['gym_name'])

        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 400)

    def test_admin_token_edit_user_without_brand(self):
        """برای کاربر بدون برند، ویرایش ادمین مستقیم روی خود کاربر می‌نشیند"""
        athlete = create_user(phone='09990000009')
        admin_instance = CustomUser.objects.get(pk=athlete.pk)
        admin_instance.token_balance = 55
        self._admin_save(admin_instance, ['token_balance'])

        athlete.refresh_from_db()
        self.assertEqual(athlete.token_balance, 55)


class DeductRespectedByViewsTests(BaseAPITestCase):
    """اگر کسر توکن شکست بخورد، ویو نباید برنامه‌ی مجانی تولید کند"""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user()
        self.user.token_balance = 100
        self.user.save()
        self.auth(self.user)

    @patch.object(CustomUser, 'deduct_tokens', return_value=False)
    def test_generate_returns_402_when_deduct_fails(self, mock_deduct):
        response = self.client.post('/api/programs/generate/', {'name': 'علی'})
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(ClientProgram.objects.count(), 0)

    @patch.object(CustomUser, 'deduct_tokens', return_value=False)
    def test_edit_returns_402_when_deduct_fails(self, mock_deduct):
        program = ClientProgram.objects.create(
            user=self.user, name='علی',
            generated_workout='ورزشی', generated_meal_plan='غذایی',
        )
        response = self.client.post(
            f'/api/programs/{program.id}/edit/', {'feedback': 'تست'}
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
