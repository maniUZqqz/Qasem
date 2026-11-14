"""The product API says which products are services, so the panel stops
printing «۹۹۹۹ قابل فروش» for a service that has no stock."""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.products.digital import UNLIMITED_STOCK
from apps.products.models import Product
from apps.stores.models import Store, StoreProfile


class IsDigitalFieldTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("digi-owner", password="x")
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _rows(self, store):
        data = self.api.get(f"/api/v1/products/?store={store.pk}").data
        rows = data["results"] if isinstance(data, dict) else data
        return {r["name"]: r for r in rows}

    def test_unlimited_stock_is_a_service(self):
        store = Store.objects.create(owner=self.owner, name="چغر")
        Product.objects.create(store=store, name="سرویس", price=1, stock_quantity=UNLIMITED_STOCK)
        Product.objects.create(store=store, name="کفش", price=1, stock_quantity=7)
        rows = self._rows(store)
        self.assertTrue(rows["سرویس"]["is_digital"])
        self.assertFalse(rows["کفش"]["is_digital"])

    def test_a_digital_shop_marks_every_product(self):
        store = Store.objects.create(owner=self.owner, name="چغر دو")
        StoreProfile.objects.update_or_create(store=store, defaults={"shipping_policy": "سرویس دیجیتال؛ ارسال فیزیکی ندارد"})
        Product.objects.create(store=store, name="اشتراک", price=1, stock_quantity=5)
        self.assertTrue(self._rows(store)["اشتراک"]["is_digital"])

    def test_the_field_is_read_only(self):
        store = Store.objects.create(owner=self.owner, name="چغر سه")
        p = Product.objects.create(store=store, name="کفش", price=1, stock_quantity=3)
        r = self.api.patch(f"/api/v1/products/{p.pk}/", {"is_digital": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["is_digital"])
