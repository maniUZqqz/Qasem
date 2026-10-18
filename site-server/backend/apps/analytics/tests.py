from decimal import Decimal

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.campaigns.models import Campaign
from apps.customers.models import Conversation, Customer, Message, Order
from apps.products.models import Product
from apps.stores.models import Store


class AnalyticsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="Alice Shop")
        self.product = Product.objects.create(store=self.store, name="کفش", price=100)
        customer = Customer.objects.create(store=self.store, name="مشتری")
        conversation = Conversation.objects.create(store=self.store, customer=customer)
        Message.objects.create(conversation=conversation, role=Message.Role.CUSTOMER, text="سلام")
        Message.objects.create(conversation=conversation, role=Message.Role.AI, text="درود")
        Order.objects.create(
            store=self.store,
            customer=customer,
            status=Order.Status.CONFIRMED,
            total=Decimal("250000"),
        )
        Order.objects.create(
            store=self.store, customer=customer, status=Order.Status.DRAFT, total=Decimal("100000")
        )
        Campaign.objects.create(store=self.store, product=self.product, name="c1")
        self.client.force_authenticate(user=self.user)

    def test_overview_returns_real_counts(self):
        resp = self.client.get(f"/api/v1/stores/{self.store.id}/analytics/")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data
        self.assertEqual(data["products"]["total"], 1)
        self.assertEqual(data["conversations"]["total"], 1)
        self.assertEqual(data["conversations"]["messages"], 2)
        self.assertEqual(data["orders"]["total"], 2)
        self.assertEqual(data["orders"]["confirmed_revenue"], "250000")
        self.assertEqual(data["orders"]["draft_value"], "100000")
        self.assertEqual(data["campaigns"]["total"], 1)
        self.assertEqual(data["ai"]["requests"], 0)

    def test_timeseries_covers_every_day(self):
        resp = self.client.get(f"/api/v1/stores/{self.store.id}/analytics/timeseries/?days=7")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["days"], 7)
        self.assertEqual(len(resp.data["series"]), 7)
        today = resp.data["series"][-1]
        self.assertEqual(today["conversations"], 1)
        self.assertEqual(today["orders"], 2)

    def test_tenancy(self):
        bob = User.objects.create_user("bob", password="Str0ngPass!x")
        bob_store = Store.objects.create(owner=bob, name="Bob Shop")
        resp = self.client.get(f"/api/v1/stores/{bob_store.id}/analytics/")
        self.assertEqual(resp.status_code, 404)

    def test_sales_dashboard_returns_real_numbers(self):
        from apps.customers.models import OrderItem, SupportTicket

        confirmed = Order.objects.filter(
            store=self.store, status=Order.Status.CONFIRMED
        ).first()
        OrderItem.objects.create(
            order=confirmed, product=self.product, quantity=2, unit_price=Decimal("125000")
        )
        SupportTicket.objects.create(store=self.store, subject="مشکل ارسال")

        resp = self.client.get(f"/api/v1/stores/{self.store.id}/analytics/sales/?days=7")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data
        self.assertEqual(data["orders"]["total"], 2)
        self.assertEqual(data["orders"]["by_status"]["CONFIRMED"], 1)
        self.assertTrue(data["revenue"]["confirmed_total"].startswith("250000"))
        self.assertEqual(data["pending"]["open_tickets"], 1)
        self.assertEqual(data["conversion"]["conversations"], 1)
        self.assertEqual(len(data["series"]), 7)
        today = data["series"][-1]
        self.assertEqual(today["orders"], 2)
        self.assertEqual(today["confirmed_orders"], 1)
        self.assertTrue(today["revenue"].startswith("250000"))
        top = data["top_products"][0]
        self.assertEqual(top["name"], "کفش")
        self.assertEqual(top["quantity"], 2)
        self.assertTrue(str(top["revenue"]).startswith("250000"))
