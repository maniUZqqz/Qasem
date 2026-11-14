"""A digital service (Chagher) must not be asked for «other angles» or sent to
Digikala to find «competitors»: the product tabs «حالت پیشرفته» and
«تحلیل بازار» said exactly that."""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.products.digital import UNLIMITED_STOCK
from apps.products.models import Product
from apps.stores.models import Store
from services.content import readiness
from services.research import web


class DigitalReadinessTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("dig-ready", password="x")
        self.store = Store.objects.create(owner=owner, name="چغر")

    def _keys(self, **kw):
        product = Product.objects.create(store=self.store, name="سرویس", price=1, **kw)
        return {r.key: r for r in readiness.check(product, readiness.VIDEO)}

    def test_a_service_is_asked_for_real_screens_not_other_angles(self):
        keys = self._keys(stock_quantity=UNLIMITED_STOCK)
        self.assertIn("more_screens", keys)
        self.assertNotIn("more_angles", keys)
        self.assertIn("اسکرین‌شات", keys["more_screens"].title)
        self.assertNotIn("زاویه", keys["more_screens"].title + keys["more_screens"].why)

    def test_a_physical_product_is_still_asked_for_angles(self):
        keys = self._keys(stock_quantity=12)
        self.assertIn("more_angles", keys)
        self.assertNotIn("more_screens", keys)


class MarketplaceSkipTests(SimpleTestCase):
    def test_a_digital_service_does_not_query_the_marketplaces(self):
        fetch = MagicMock(return_value=[{"title": "کتابخانهٔ چوبی"}])
        with patch.dict(web.SOURCES, {"digikala": fetch}, clear=True), \
                patch.object(web, "web_search_configured", return_value=False):
            out = web.research_product("چغر", skip_marketplaces=True)
        fetch.assert_not_called()
        self.assertEqual(out["items"], [])
        first = out["sources"][0]
        self.assertTrue(first.get("skipped"))
        self.assertIn("سرویسِ دیجیتال", first["error"])

    def test_a_physical_product_still_does_(self):
        fetch = MagicMock(return_value=[{"title": "کفش"}])
        with patch.dict(web.SOURCES, {"digikala": fetch}, clear=True), \
                patch.object(web, "web_search_configured", return_value=False):
            out = web.research_product("کفش")
        fetch.assert_called_once()
        self.assertEqual(out["items"], [{"title": "کفش"}])
