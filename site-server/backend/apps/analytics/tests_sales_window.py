"""ب۴ — the sales numbers must mean what the page says they mean.

Synthetic data with an answer worked out by hand: one sale inside the window,
one outside it, one cancelled order and one draft. Before the fix the panel
counted all four as conversions, summed revenue over all time next to a
thirty-day chart, and filed money on the day the chat opened.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Order, OrderItem
from apps.products.models import Product
from apps.stores.models import Store

from .services import store_sales


class SalesWindowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=Decimal("100000"), stock_quantity=99
        )
        self.customer = Customer.objects.create(store=self.store, name="مشتری")
        self.now = timezone.now()

    def an_order(self, *, status, created_days_ago=0, confirmed_days_ago=None, quantity=1):
        conversation = Conversation.objects.create(
            store=self.store, customer=self.customer,
            external_id=f"c{Conversation.objects.count()}",
        )
        order = Order.objects.create(
            store=self.store, customer=self.customer, conversation=conversation,
            status=status, total=Decimal("100000") * quantity,
        )
        OrderItem.objects.create(
            order=order, product=self.product, quantity=quantity,
            unit_price=Decimal("100000"),
        )
        when = self.now - timedelta(days=created_days_ago)
        Order.objects.filter(pk=order.pk).update(created_at=when)
        Conversation.objects.filter(pk=conversation.pk).update(created_at=when)
        if confirmed_days_ago is not None:
            Order.objects.filter(pk=order.pk).update(
                confirmed_at=self.now - timedelta(days=confirmed_days_ago)
            )
        return Order.objects.get(pk=order.pk)

    def test_only_confirmed_orders_inside_the_window_are_revenue(self):
        self.an_order(status=Order.Status.CONFIRMED, confirmed_days_ago=2, quantity=2)
        self.an_order(status=Order.Status.CONFIRMED, created_days_ago=40, confirmed_days_ago=40)
        self.an_order(status=Order.Status.CANCELLED)
        self.an_order(status=Order.Status.DRAFT)

        sales = store_sales(self.store, days=30)
        self.assertEqual(Decimal(sales["revenue"]["confirmed_total"]), Decimal("200000"))
        self.assertEqual(sales["revenue"]["confirmed_orders"], 1)
        self.assertEqual(Decimal(sales["revenue"]["avg_order_value"]), Decimal("200000"))

    def test_the_all_time_figures_are_still_there_but_kept_apart(self):
        self.an_order(status=Order.Status.CONFIRMED, confirmed_days_ago=2)
        self.an_order(status=Order.Status.CONFIRMED, created_days_ago=40, confirmed_days_ago=40)

        sales = store_sales(self.store, days=30)
        self.assertEqual(Decimal(sales["lifetime"]["confirmed_total"]), Decimal("200000"))
        self.assertEqual(sales["lifetime"]["confirmed_orders"], 2)

    def test_conversion_counts_sales_not_attempts(self):
        self.an_order(status=Order.Status.CONFIRMED, confirmed_days_ago=1)
        self.an_order(status=Order.Status.DRAFT)
        self.an_order(status=Order.Status.CANCELLED)
        self.an_order(status=Order.Status.AWAITING_RECEIPT)

        sales = store_sales(self.store, days=30)
        self.assertEqual(sales["conversion"]["conversations"], 4)
        self.assertEqual(sales["conversion"]["orders"], 1)
        self.assertEqual(sales["conversion"]["rate_percent"], 25.0)

    def test_revenue_lands_on_the_day_it_was_confirmed(self):
        self.an_order(
            status=Order.Status.CONFIRMED, created_days_ago=5, confirmed_days_ago=0
        )
        sales = store_sales(self.store, days=30)
        by_date = {row["date"]: row for row in sales["series"]}

        today = timezone.localdate().isoformat()
        creation_day = (timezone.localdate() - timedelta(days=5)).isoformat()
        self.assertEqual(Decimal(by_date[today]["revenue"]), Decimal("100000"))
        self.assertEqual(Decimal(by_date[creation_day]["revenue"]), Decimal("0"))
        # the order itself still belongs to the day it was placed
        self.assertEqual(by_date[creation_day]["orders"], 1)

    def test_best_sellers_use_the_same_window_as_the_chart(self):
        self.an_order(status=Order.Status.CONFIRMED, confirmed_days_ago=3, quantity=2)
        self.an_order(
            status=Order.Status.CONFIRMED, created_days_ago=60, confirmed_days_ago=60,
            quantity=7,
        )
        sales = store_sales(self.store, days=30)
        self.assertEqual(sales["top_products"][0]["quantity"], 2)
