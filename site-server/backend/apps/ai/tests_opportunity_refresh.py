"""A deploy that fixes the wording must fix the screen too.

After the digital-service fix the opportunities page kept showing
«۹۹۹۹ عدد موجودی دارد و … موجود است ولی نمی‌فروشد» until the owner pressed
«بازمحاسبه»: stored rows were never rewritten. Rows now carry the version of
the rules that wrote them and the list recomputes older ones before showing.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from apps.products.digital import UNLIMITED_STOCK
from apps.products.models import Product
from apps.stores.models import Store, StoreProfile

from . import opportunities
from .competitor_models import Opportunity


class StaleSuggestionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("opp-refresh-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")
        StoreProfile.objects.update_or_create(
            store=self.store, defaults={"shipping_policy": "سرویسِ دیجیتال؛ ارسالِ فیزیکی ندارد"},
        )
        self.product = Product.objects.create(
            store=self.store, name="برنامه‌ساز", price=1, stock_quantity=UNLIMITED_STOCK,
        )
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.id}/opportunities/"

    def _old_row(self):
        # what the pre-fix code stored: Latin digits, the wrong «unlimited» sentence, no rules version
        return Opportunity.objects.create(
            store=self.store, product=self.product, kind=Opportunity.Kind.CONTENT,
            title=f"«{self.product.name}» در ۳۰ روز گذشته فروشی نداشته",
            reason="9999 عدد موجودی دارد و در 30 روز گذشته 0 عدد فروخته.",
            action="یک پوستر بسازید", evidence={"stock": 9999, "units": 0}, priority=55,
        )

    def test_new_suggestions_carry_the_rules_version_and_persian_digits(self):
        found = opportunities.suggest(self.store)
        self.assertTrue(found)
        for item in found:
            self.assertEqual(item["evidence"]["rules"], opportunities.RULES_VERSION)
            self.assertNotRegex(item["reason"] + item["action"], r"[0-9]")

    def test_an_old_row_is_noticed_a_current_one_is_not(self):
        self._old_row()
        self.assertTrue(opportunities.needs_refresh(self.store))
        opportunities.refresh(self.store)
        self.assertFalse(opportunities.needs_refresh(self.store))

    def test_a_marketplace_row_alone_never_asks_for_a_refresh(self):
        Opportunity.objects.create(
            store=self.store, product=self.product, kind=Opportunity.Kind.CHANNEL,
            title="کجا بفروشم", reason="r", action="a", evidence={"channel": "basalam"}, priority=40,
        )
        self.assertFalse(opportunities.needs_refresh(self.store))

    def test_listing_shows_fixed_text_without_pressing_recompute(self):
        row = self._old_row()
        data = self.client.get(self.url).json()
        self.assertIn(row.pk, [r["id"] for r in data])
        text = " ".join(r["reason"] for r in data)
        self.assertNotIn("9999", text)
        self.assertNotIn("۹۹۹۹", text)
        self.assertIn("سرویسِ دیجیتال", text)
        # and a second listing does not recompute again
        self.assertFalse(opportunities.needs_refresh(self.store))

    def test_a_dismissed_row_is_not_brought_back_by_the_auto_refresh(self):
        row = self._old_row()
        row.state = Opportunity.State.DISMISSED
        row.save(update_fields=["state"])
        data = self.client.get(self.url).json()
        self.assertNotIn(row.pk, [r["id"] for r in data])
        self.assertEqual(Opportunity.objects.get(pk=row.pk).state, Opportunity.State.DISMISSED)

    def test_the_last_marketplace_check_is_written_as_shamsi_tehran_time(self):
        from unittest.mock import patch

        fake = {"checked_at": "2026-11-14T02:30:00+00:00", "products": [1], "problems": []}
        with patch.object(opportunities, "last_channel_check", return_value=fake):
            items = opportunities.readiness(self.store)["items"]
        detail = next(i["detail"] for i in items if i["key"] == "channels")
        self.assertIn("۱۴۰۵/۰۸/۲۳ ۰۶:۰۰", detail)
        self.assertNotIn("2026", detail)
        self.assertNotIn("۲۰۲۶", detail)

    def test_readiness_titles_use_persian_digits(self):
        titles = [i["title"] for i in opportunities.readiness(self.store)["items"]]
        self.assertIn("فروشِ ۳۰ روزِ اخیر", titles)
