"""A software/service shop must not be advised like a shop with boxes."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.products.digital import UNLIMITED_STOCK, is_digital, store_is_digital
from apps.products.models import Product
from apps.stores.models import Store, StoreProfile

from . import competitor_research, opportunities
from .competitor_models import Opportunity


def _store(name, shipping=""):
    owner = User.objects.create_user("own-" + name, password="x")
    store = Store.objects.create(owner=owner, name=name)
    StoreProfile.objects.update_or_create(store=store, defaults={"shipping_policy": shipping})
    return store


class DigitalDetectionTests(TestCase):
    def test_unlimited_stock_marker_means_digital(self):
        store = _store("a")
        p = Product.objects.create(store=store, name="سرویس", price=1, stock_quantity=UNLIMITED_STOCK)
        self.assertTrue(is_digital(p))

    def test_the_shops_own_shipping_policy_can_say_it_is_digital(self):
        store = _store("b", "چغر یک سرویسِ دیجیتال است؛ ارسالِ فیزیکی ندارد.")
        p = Product.objects.create(store=store, name="سرویس", price=1, stock_quantity=5)
        self.assertTrue(store_is_digital(store))
        self.assertTrue(is_digital(p))

    def test_a_shop_with_boxes_is_not_digital(self):
        store = _store("c", "ارسال با پست")
        p = Product.objects.create(store=store, name="کفش", price=1, stock_quantity=20)
        self.assertFalse(is_digital(p))


class DigitalOpportunityTests(TestCase):
    def test_a_service_gets_an_honest_idle_message_not_nine_thousand_boxes(self):
        store = _store("d", "ارسالِ فیزیکی ندارد")
        Product.objects.create(store=store, name="برنامه‌ساز", price=1, stock_quantity=UNLIMITED_STOCK)
        content = [s for s in opportunities.suggest(store) if s["kind"] == Opportunity.Kind.CONTENT]
        self.assertTrue(content)
        text = content[0]["title"] + content[0]["reason"]
        self.assertNotIn("9999", text)
        self.assertNotIn("۹۹۹۹", text)
        self.assertIn("سرویسِ دیجیتال", content[0]["reason"])
        self.assertEqual(content[0]["evidence"]["digital"], True)

    def test_physical_stock_wording_is_unchanged_and_uses_persian_digits(self):
        store = _store("e", "ارسال با پست")
        Product.objects.create(store=store, name="خوابیده", price=1000, cost_price=500, stock_quantity=20)
        content = [s for s in opportunities.suggest(store) if s["kind"] == Opportunity.Kind.CONTENT]
        self.assertIn("پوستر", content[0]["action"])
        self.assertIn("۲۰ عدد موجودی", content[0]["reason"])

    def test_readiness_details_use_persian_digits(self):
        store = _store("f", "ارسال با پست")
        Product.objects.create(store=store, name="x", price=1, stock_quantity=1)
        items = opportunities.readiness(store)["items"]
        self.assertIn("۱ محصول ثبت شده.", [i["detail"] for i in items])


class DigitalCompetitorDiscoveryTests(TestCase):
    def test_discovery_skips_digital_services_and_says_why(self):
        store = _store("g", "سرویسِ دیجیتال")
        Product.objects.create(store=store, name="کتابخانهٔ حرکت‌ها", price=1, stock_quantity=UNLIMITED_STOCK)
        called = []
        fake = {"digikala": lambda q, n: called.append(q) or [], "basalam": lambda q, n: called.append(q) or []}
        with patch.dict(competitor_research.web.SOURCES, fake):
            result = competitor_research.discover(store)
        self.assertEqual(called, [])  # no marketplace was searched
        self.assertEqual(result["suggestions"], [])
        self.assertIn("سرویسِ دیجیتال", result["note"])

    def test_a_physical_product_is_still_searched(self):
        store = _store("h", "ارسال با پست")
        Product.objects.create(store=store, name="قهوه ترک", price=1, stock_quantity=10)
        called = []
        fake = {"digikala": lambda q, n: called.append(q) or [], "basalam": lambda q, n: called.append(q) or []}
        with patch.dict(competitor_research.web.SOURCES, fake):
            competitor_research.discover(store)
        self.assertEqual(len(called), 2)
