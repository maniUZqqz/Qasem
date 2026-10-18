"""ب۵ — two posts of one product must not both count the same orders.

The existing performance tests set `linked_orders` by hand, so the function
that computes it had never been run by a test at all. This runs it.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, Order, OrderItem
from apps.products.models import Product
from apps.stores.models import Store

from .learning import _count_linked_orders
from .models import Campaign, PublishJob


class LinkedOrderCountingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=Decimal("100000"), stock_quantity=99
        )
        self.customer = Customer.objects.create(store=self.store, name="مشتری")
        self.campaign = Campaign.objects.create(
            store=self.store, name="کمپین", product=self.product
        )
        self.now = timezone.now()

    def a_post(self, days_ago):
        job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="INSTAGRAM",
            status=PublishJob.Status.SENT,
        )
        PublishJob.objects.filter(pk=job.pk).update(
            published_at=self.now - timedelta(days=days_ago)
        )
        return PublishJob.objects.select_related("campaign", "store").get(pk=job.pk)

    def an_order(self, days_ago):
        order = Order.objects.create(
            store=self.store, customer=self.customer,
            status=Order.Status.CONFIRMED, total=Decimal("100000"),
        )
        OrderItem.objects.create(
            order=order, product=self.product, quantity=1, unit_price=Decimal("100000")
        )
        Order.objects.filter(pk=order.pk).update(
            created_at=self.now - timedelta(days=days_ago)
        )
        return order

    def test_each_order_belongs_to_exactly_one_post(self):
        first = self.a_post(days_ago=10)
        second = self.a_post(days_ago=4)
        self.an_order(days_ago=8)
        self.an_order(days_ago=6)
        self.an_order(days_ago=2)

        before = _count_linked_orders(first)
        after = _count_linked_orders(second)
        self.assertEqual(before, 2)
        self.assertEqual(after, 1)
        self.assertEqual(before + after, 3, "three orders, counted three times in total")

    def test_orders_outside_the_fourteen_day_window_do_not_count(self):
        post = self.a_post(days_ago=40)
        self.an_order(days_ago=39)  # inside
        self.an_order(days_ago=20)  # the window closed on day 26
        self.assertEqual(_count_linked_orders(post), 1)

    def test_a_post_that_never_went_out_counts_nothing(self):
        job = PublishJob.objects.create(
            store=self.store, campaign=self.campaign, platform="INSTAGRAM",
            status=PublishJob.Status.PENDING,
        )
        self.an_order(days_ago=1)
        self.assertEqual(_count_linked_orders(job), 0)
