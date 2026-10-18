"""Competitors, real profit, and suggestions a shop can audit.

The rule running through all of it: **a missing cost price is "unknown", never
"free"**. Treating it as zero reports the whole selling price as margin, which
makes the worst product in the shop look like the best one — the exact opposite
of the decision §5 exists to support.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, Order, OrderItem
from apps.products.models import Product
from apps.stores.models import Store

from . import opportunities
from .competitor_models import Competitor, CompetitorProduct, Opportunity


class ProfitMathTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("profit-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه سود")

    def test_profit_is_none_when_the_cost_is_unknown(self):
        """Not zero. "This makes nothing" and "nobody told us what it cost"
        are different answers."""
        product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self.assertIsNone(product.unit_profit)
        self.assertIsNone(product.margin_percent)

    def test_profit_and_margin_from_real_numbers(self):
        product = Product.objects.create(
            store=self.store, name="کفش", price=1000, cost_price=600,
        )
        self.assertEqual(product.unit_profit, Decimal(400))
        self.assertEqual(product.margin_percent, 40.0)

    def test_a_product_sold_below_cost_reports_a_negative_margin(self):
        product = Product.objects.create(
            store=self.store, name="ضرر", price=500, cost_price=800,
        )
        self.assertLess(product.margin_percent, 0)

    def test_a_free_product_does_not_divide_by_zero(self):
        product = Product.objects.create(
            store=self.store, name="هدیه", price=0, cost_price=100,
        )
        self.assertIsNone(product.margin_percent)


class ProfitReportTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("report-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه گزارش")
        self.customer = Customer.objects.create(store=self.store, name="مشتری")

    def _sell(self, product, quantity):
        order = Order.objects.create(
            store=self.store, customer=self.customer,
            status=Order.Status.CONFIRMED, total=product.price * quantity,
        )
        OrderItem.objects.create(
            order=order, product=product, quantity=quantity,
            unit_price=product.price,
        )
        return order

    def test_revenue_and_profit_are_separate_numbers(self):
        product = Product.objects.create(
            store=self.store, name="کفش", price=1000, cost_price=600,
        )
        self._sell(product, 3)

        report = opportunities.profit_report(self.store)
        row = report["products"][0]

        self.assertEqual(row["revenue"], "3000.00")
        self.assertEqual(row["profit"], "1200.00")

    def test_products_without_a_cost_are_named_not_silently_skipped(self):
        """A report that quietly covers 4 of 30 products, while looking
        complete, is worse than one that says so."""
        Product.objects.create(store=self.store, name="بی‌قیمت", price=500)
        Product.objects.create(
            store=self.store, name="باقیمت", price=1000, cost_price=400,
        )

        report = opportunities.profit_report(self.store)

        self.assertIn("بی‌قیمت", report["missing_cost"])
        self.assertEqual(report["profit_covers_products"], 1)

    def test_total_profit_is_none_when_nothing_has_a_cost(self):
        """A total of zero would read as "you made nothing"."""
        product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self._sell(product, 2)

        report = opportunities.profit_report(self.store)

        self.assertEqual(report["total_revenue"], "2000.00")
        self.assertIsNone(report["total_profit"])

    def test_only_confirmed_orders_count(self):
        product = Product.objects.create(
            store=self.store, name="کفش", price=1000, cost_price=500,
        )
        order = Order.objects.create(
            store=self.store, customer=self.customer,
            status=Order.Status.AWAITING_APPROVAL, total=1000,
        )
        OrderItem.objects.create(order=order, product=product, quantity=1, unit_price=1000)

        report = opportunities.profit_report(self.store)
        self.assertEqual(report["products"][0]["units"], 0)

    def test_the_most_profitable_product_is_not_the_best_seller(self):
        """The whole reason §5 asks for cost price."""
        cheap = Product.objects.create(
            store=self.store, name="پرفروشِ کم‌سود", price=100, cost_price=95,
        )
        rich = Product.objects.create(
            store=self.store, name="کم‌فروشِ پرسود", price=5000, cost_price=1000,
        )
        self._sell(cheap, 20)
        self._sell(rich, 2)

        report = opportunities.profit_report(self.store)

        self.assertEqual(report["best_sellers"][0], "پرفروشِ کم‌سود")
        self.assertEqual(report["most_profitable"][0], "کم‌فروشِ پرسود")


class CompetitorTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("comp-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه رقبا")

    def test_a_competitor_with_no_analysis_is_stale(self):
        rival = Competitor.objects.create(store=self.store, name="رقیب")
        self.assertTrue(rival.is_stale)

    def test_a_month_old_analysis_is_stale(self):
        """A positioning statement from last quarter is history, not
        intelligence."""
        rival = Competitor.objects.create(
            store=self.store, name="رقیب",
            analysed_at=timezone.now() - timedelta(days=40),
        )
        self.assertTrue(rival.is_stale)

    def test_a_fresh_analysis_is_not_stale(self):
        rival = Competitor.objects.create(
            store=self.store, name="رقیب", analysed_at=timezone.now(),
        )
        self.assertFalse(rival.is_stale)

    def test_one_competitor_name_per_store(self):
        from django.db import IntegrityError

        Competitor.objects.create(store=self.store, name="دیجی‌کالا")
        with self.assertRaises(IntegrityError):
            Competitor.objects.create(store=self.store, name="دیجی‌کالا")

    def test_two_shops_may_track_the_same_competitor(self):
        other = Store.objects.create(owner=self.owner, name="فروشگاه دوم")
        Competitor.objects.create(store=self.store, name="دیجی‌کالا")
        Competitor.objects.create(store=other, name="دیجی‌کالا")
        self.assertEqual(Competitor.objects.filter(name="دیجی‌کالا").count(), 2)


class SuggestionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("sugg-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه پیشنهاد")
        self.customer = Customer.objects.create(store=self.store, name="مشتری")

    def _sell(self, product, quantity):
        order = Order.objects.create(
            store=self.store, customer=self.customer,
            status=Order.Status.CONFIRMED, total=product.price * quantity,
        )
        OrderItem.objects.create(
            order=order, product=product, quantity=quantity, unit_price=product.price,
        )

    def _kinds(self):
        return {s["kind"] for s in opportunities.suggest(self.store)}

    def test_a_missing_cost_price_is_the_highest_priority_suggestion(self):
        """Every other profit number depends on it."""
        Product.objects.create(store=self.store, name="کفش", price=1000)
        found = opportunities.suggest(self.store)
        top = max(found, key=lambda s: s["priority"])
        self.assertEqual(top["kind"], Opportunity.Kind.INVENTORY)

    def test_being_priced_above_a_competitor_is_flagged_with_both_numbers(self):
        product = Product.objects.create(
            store=self.store, name="کفش", price=1500, cost_price=500,
        )
        rival = Competitor.objects.create(store=self.store, name="رقیب")
        CompetitorProduct.objects.create(
            competitor=rival, name="کفش مشابه", price_toman=1000, matches=product,
        )

        pricing = [
            s for s in opportunities.suggest(self.store)
            if s["kind"] == Opportunity.Kind.PRICING and "گران‌تر" in s["title"]
        ]
        self.assertEqual(len(pricing), 1)
        self.assertEqual(pricing[0]["evidence"]["competitor_price"], 1000)
        self.assertEqual(pricing[0]["evidence"]["our_price"], 1500)

    def test_a_small_price_gap_is_not_worth_mentioning(self):
        product = Product.objects.create(
            store=self.store, name="کفش", price=1050, cost_price=500,
        )
        rival = Competitor.objects.create(store=self.store, name="رقیب")
        CompetitorProduct.objects.create(
            competitor=rival, name="مشابه", price_toman=1000, matches=product,
        )
        titles = [s["title"] for s in opportunities.suggest(self.store)]
        self.assertFalse(any("گران‌تر" in t for t in titles))

    def test_a_thin_margin_on_a_selling_product_is_flagged_as_a_question(self):
        """A shop may run a loss-leader on purpose; telling them they are wrong
        about their own strategy is how a tool gets ignored."""
        product = Product.objects.create(
            store=self.store, name="کم‌سود", price=1000, cost_price=950,
        )
        self._sell(product, 5)

        thin = [s for s in opportunities.suggest(self.store) if "سود" in s["title"]]
        self.assertTrue(thin)
        self.assertIn("اگر عمدی نیست", thin[0]["action"])

    def test_stock_that_does_not_move_suggests_content_not_a_discount(self):
        Product.objects.create(
            store=self.store, name="خوابیده", price=1000, cost_price=500,
            stock_quantity=20,
        )
        content = [
            s for s in opportunities.suggest(self.store)
            if s["kind"] == Opportunity.Kind.CONTENT
        ]
        self.assertTrue(content)
        self.assertIn("پوستر", content[0]["action"])

    def test_every_suggestion_carries_the_numbers_it_came_from(self):
        """A recommendation a shop owner cannot audit is one they follow once,
        get burned by, and never trust again."""
        Product.objects.create(
            store=self.store, name="کفش", price=1000, cost_price=950, stock_quantity=5,
        )
        for suggestion in opportunities.suggest(self.store):
            self.assertTrue(suggestion["evidence"], suggestion["title"])
            self.assertTrue(suggestion["reason"])
            self.assertTrue(suggestion["action"])


class RefreshTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("refresh-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه بازسازی")

    def test_running_twice_does_not_duplicate(self):
        Product.objects.create(store=self.store, name="کفش", price=1000)
        opportunities.refresh(self.store)
        first = Opportunity.objects.filter(store=self.store).count()
        opportunities.refresh(self.store)
        self.assertEqual(Opportunity.objects.filter(store=self.store).count(), first)

    def test_a_dismissed_suggestion_never_comes_back(self):
        """A suggestion that reappears after being rejected stops being a
        suggestion and becomes noise."""
        Product.objects.create(store=self.store, name="کفش", price=1000)
        opportunities.refresh(self.store)
        row = Opportunity.objects.filter(store=self.store).first()
        row.state = Opportunity.State.DISMISSED
        row.save()

        opportunities.refresh(self.store)

        row.refresh_from_db()
        self.assertEqual(row.state, Opportunity.State.DISMISSED)

    def test_a_fixed_problem_closes_itself(self):
        """Leaving it open would make the list a graveyard."""
        product = Product.objects.create(store=self.store, name="کفش", price=1000)
        opportunities.refresh(self.store)
        self.assertTrue(
            Opportunity.objects.filter(
                store=self.store, kind=Opportunity.Kind.INVENTORY,
                state=Opportunity.State.OPEN,
            ).exists()
        )

        product.cost_price = 600
        product.save()
        opportunities.refresh(self.store)

        self.assertFalse(
            Opportunity.objects.filter(
                store=self.store, kind=Opportunity.Kind.INVENTORY,
                state=Opportunity.State.OPEN,
            ).exists()
        )


class CompetitorAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("capi-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه API رقبا")
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.id}/competitors/"

    def test_add_and_list_a_competitor(self):
        created = self.client.post(
            self.url, {"name": "دیجی‌کالا", "kind": "MARKETPLACE"},
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        listed = self.client.get(self.url).json()
        self.assertEqual(listed[0]["name"], "دیجی‌کالا")

    def test_a_duplicate_name_is_refused_clearly(self):
        self.client.post(self.url, {"name": "ترب"}, content_type="application/json")
        again = self.client.post(self.url, {"name": "ترب"}, content_type="application/json")
        self.assertEqual(again.status_code, 409)

    def test_a_recorded_price_is_stamped_with_a_date(self):
        """A price with no date is a claim, and repricing against one is how a
        shop loses money confidently."""
        created = self.client.post(
            self.url, {"name": "رقیب"}, content_type="application/json",
        ).json()
        response = self.client.post(
            f"{self.url}{created['id']}/products/",
            {"name": "کفش", "price_toman": 900000},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.json()["observed_at"])

    def test_deleting_keeps_the_evidence(self):
        """The observed prices are what pricing suggestions were built on."""
        created = self.client.post(
            self.url, {"name": "رقیب"}, content_type="application/json",
        ).json()
        self.client.delete(f"{self.url}{created['id']}/")
        self.assertTrue(Competitor.objects.filter(pk=created["id"]).exists())
        self.assertFalse(Competitor.objects.get(pk=created["id"]).is_active)

    def test_a_stranger_sees_nothing(self):
        stranger = User.objects.create_user("capi-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class OpportunityAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("oapi-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه فرصت")
        Product.objects.create(store=self.store, name="کفش", price=1000)
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.id}/opportunities/"

    def test_refreshing_produces_suggestions(self):
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["opportunities"])

    def test_dismissing_removes_it_from_the_open_list(self):
        self.client.post(self.url, {}, content_type="application/json")
        row = Opportunity.objects.filter(store=self.store).first()
        self.client.patch(
            f"{self.url}{row.pk}/", {"state": "DISMISSED"},
            content_type="application/json",
        )
        open_rows = self.client.get(self.url).json()
        self.assertNotIn(row.pk, [r["id"] for r in open_rows])

    def test_the_profit_report_is_reachable(self):
        response = self.client.get(f"/api/v1/stores/{self.store.id}/profit/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("missing_cost", response.json())
