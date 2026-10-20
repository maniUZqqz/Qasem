"""تاییدِ خرید در پنل ادمین باید توکن را شارژ کند (باگِ ۱۴۰۵/۰۷/۰۹)."""
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.test import TestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage

from app.admin import TokenPurchaseAdmin
from app.models import CustomUser, GymBrand, TokenPurchase, LedgerEntry


def _request(user):
    req = RequestFactory().post('/admin/')
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


class AdminChargeTests(TestCase):
    def setUp(self):
        self.admin_user = CustomUser.objects.create_superuser(
            phone_number='09120000000', password='AdminPass123')
        self.owner = CustomUser.objects.create_user(
            phone_number='09121111111', password='OwnerPass123', account_type='coach')
        self.brand = GymBrand.objects.create(user=self.owner, gym_name='باشگاه تست', token_balance=0)
        self.purchase = TokenPurchase.objects.create(
            user=self.owner, token_amount=500, original_price=Decimal('1000000'),
            final_price=Decimal('1000000'), status='under_review',
            payment_method=TokenPurchase.METHOD_CARD)
        self.site = TokenPurchaseAdmin(TokenPurchase, AdminSite())

    def test_status_change_in_form_charges_wallet(self):
        """وضعیت را در فرم روی «پرداخت شده» بگذار ⇒ کیف پول پر شود."""
        self.purchase.status = 'paid'
        self.site.save_model(_request(self.admin_user), self.purchase, None, True)

        self.brand.refresh_from_db()
        self.purchase.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 500)
        self.assertEqual(self.owner.get_effective_token_balance(), 500)
        self.assertEqual(self.purchase.status, 'paid')
        self.assertEqual(self.purchase.reviewed_by_id, self.admin_user.id)
        self.assertTrue(LedgerEntry.objects.filter(
            entry_type=LedgerEntry.TYPE_TOKEN_GRANT,
            reference=f'purchase#{self.purchase.id}').exists())

    def test_second_save_does_not_double_charge(self):
        self.purchase.status = 'paid'
        self.site.save_model(_request(self.admin_user), self.purchase, None, True)
        self.site.save_model(_request(self.admin_user), self.purchase, None, True)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 500)

    def test_repair_action_charges_old_paid_purchase(self):
        """خریدی که قبلاً دستی paid شده بود و شارژ نشده، با اکشنِ جبران شارژ شود."""
        TokenPurchase.objects.filter(pk=self.purchase.pk).update(status='paid')
        self.purchase.refresh_from_db()
        qs = TokenPurchase.objects.filter(pk=self.purchase.pk)
        self.site.charge_missing_tokens(_request(self.admin_user), qs)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 500)
        # بار دوم نباید دوباره شارژ کند
        self.site.charge_missing_tokens(_request(self.admin_user), qs)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.token_balance, 500)

    def test_user_without_brand_gets_tokens_on_own_account(self):
        solo = CustomUser.objects.create_user(
            phone_number='09122222222', password='SoloPass123', account_type='personal')
        purchase = TokenPurchase.objects.create(
            user=solo, token_amount=50, original_price=Decimal('100000'),
            final_price=Decimal('100000'), status='under_review')
        purchase.status = 'paid'
        self.site.save_model(_request(self.admin_user), purchase, None, True)
        solo.refresh_from_db()
        self.assertEqual(solo.token_balance, 50)
