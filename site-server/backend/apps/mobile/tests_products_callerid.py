from decimal import Decimal

from django.contrib.auth.models import User

from apps.customers.models import Customer
from apps.customers.outreach import Prospect
from apps.marketing.models import Lead
from apps.products.models import Product, ProductVariant
from apps.stores.models import Store

from . import callerid, products
from .models import MobileContact, ProductPricing, SmsMessage
from .tests_base import BASE, MobileTestCase


class ProductTests(MobileTestCase):
    def make(self, **kw):
        base = dict(store=self.store, name="کفش ورزشی نایکی", sku="NK-1", brand="Nike", price=Decimal("1200000"), stock_quantity=9, reserved_quantity=2)
        base.update(kw)
        return Product.objects.create(**base)

    def search(self, q, client=None):
        return (client or self.device_client()).get(BASE + "products/search/", {"q": q})

    def test_nothing_is_invented_when_cost_is_unknown(self):
        self.make()
        p = self.search("نایکی").data["results"][0]
        self.assertEqual((p["price"], p["stock"]["available"], p["stock"]["on_hand"], p["stock"]["reserved"]), (1200000, 7, 9, 2))
        for field in ("cost", "unit_profit", "margin_percent", "floor_price", "max_discount_percent", "max_discount_amount"):
            self.assertIsNone(p[field], field)            # null => «ثبت نشده», never 0
        self.assertEqual(p["floor_basis"], "unknown")

    def test_floor_is_cost_plus_extra_and_margin(self):
        prod = self.make(cost_price=Decimal("800000"))
        p = self.search("NK-1").data["results"][0]
        self.assertEqual((p["cost"], p["unit_profit"], p["floor_price"], p["floor_basis"]), (800000, 400000, 800000, "cost_plus"))
        self.assertEqual((p["max_discount_amount"], p["max_discount_percent"]), (400000, 33.3))
        ProductPricing.objects.create(product=prod, extra_unit_cost=Decimal("50000"), min_margin_percent=Decimal("10"))
        p = self.search("NK-1").data["results"][0]
        self.assertEqual(p["floor_price"], 935000)                   # (800000+50000)*1.10
        self.assertEqual(p["max_discount_amount"], 265000)

    def test_owner_override_wins_and_discount_never_negative(self):
        prod = self.make(cost_price=Decimal("800000"))
        ProductPricing.objects.create(product=prod, floor_price_override=Decimal("1300000"))
        p = self.search("نایکی").data["results"][0]
        self.assertEqual((p["floor_price"], p["floor_basis"], p["max_discount_amount"], p["max_discount_percent"]), (1300000, "owner_override", 0, 0.0))

    def test_search_normalizes_persian_and_arabic_letters_and_digits(self):
        self.make(name="گوشی موبایل ۱۲۸ گیگ")
        self.assertEqual(self.search("گوشي 128").data["count"], 1)
        self.assertEqual(self.search("").data["count"], 0)
        self.assertEqual(self.search("ناموجود-xyz").data["count"], 0)

    def test_variants_attributes_and_stock_status(self):
        prod = self.make(stock_status="OUT_OF_STOCK")
        ProductVariant.objects.create(product=prod, name="سایز ۴۲", stock_quantity=3, reserved_quantity=1, price_override=Decimal("1250000"))
        prod.attributes.create(key="رنگ", value="سیاه")
        p = self.search("نایکی").data["results"][0]
        self.assertEqual(p["variants"], [{"name": "سایز ۴۲", "price": 1250000, "available": 2}])
        self.assertEqual(p["attributes"], [{"key": "رنگ", "value": "سیاه"}])
        self.assertEqual(p["stock"]["status_label"], "ناموجود")

    def test_staff_only_and_store_scope(self):
        self.make()
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(BASE + "products/search/?q=x").status_code, 401)
        self.assertEqual(self.panel_client(self.plain).get(BASE + "products/search/?q=x").status_code, 403)
        other_owner = User.objects.create_user("o2", "o2@x.com", "pw12345678", is_staff=True)
        Store.objects.create(owner=other_owner, name="فروشگاه دیگر")
        self.make(store=Store.objects.get(owner=other_owner), name="کفش مخفی")
        # a non-superuser staff member only sees stores he belongs to; the owner (superuser) sees all
        self.assertEqual(self.search("مخفی", self.panel_client(other_owner)).data["count"], 1)
        self.assertEqual(self.search("مخفی", self.panel_client(self.staff)).data["count"], 0)
        self.assertEqual(self.search("مخفی", self.panel_client(self.boss)).data["count"], 1)

    def test_panel_can_edit_cost_stock_and_floor_inputs(self):
        prod = self.make()
        panel = self.panel_client()
        r = panel.patch(BASE + f"admin/products/{prod.pk}/pricing/", {"cost_price": "700,000", "stock_quantity": "12", "extra_unit_cost": "۲۰۰۰۰",
                                                                    "min_margin_percent": "5", "note": "با کارمزد"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["cost"], r.data["stock"]["on_hand"], r.data["floor_price"]), (700000, 12, 756000))
        prod.refresh_from_db()
        self.assertEqual((prod.cost_price, prod.stock_quantity), (Decimal("700000"), 12))
        r = panel.patch(BASE + f"admin/products/{prod.pk}/pricing/", {"cost_price": "", "floor_price_override": "900000"}, format="json")
        self.assertEqual((r.data["cost"], r.data["floor_price"]), (None, 900000))     # clearing really clears
        self.assertEqual(panel.patch(BASE + f"admin/products/{prod.pk}/pricing/", {"cost_price": "abc"}, format="json").status_code, 400)
        self.assertEqual(panel.patch(BASE + f"admin/products/{prod.pk}/pricing/", {"stock_quantity": "-3"}, format="json").status_code, 400)
        self.assertEqual(panel.get(BASE + "admin/products/").data["count"], 1)
        self.assertEqual(self.device_client().patch(BASE + f"admin/products/{prod.pk}/pricing/", {}, format="json").status_code, 403)


class CallerIdTests(MobileTestCase):
    def who(self, number, client=None):
        return (client or self.device_client()).get(BASE + "callerid/", {"number": number}).data

    def test_unknown_number(self):
        d = self.who("09125550000")
        self.assertEqual((d["display"], d["known"], d["matches"], d["profiles"]), (None, False, [], []))
        self.assertEqual(d["history"]["calls"], 0)

    def test_matches_every_spelling_across_nm_sources(self):
        Customer.objects.create(store=self.store, name="مشتری یک", phone="0912 123 4567")
        Prospect.objects.create(store=self.store, company="شرکت پارس", person="خانم رضایی", phone="+98 912 123 4567")
        Lead.objects.create(name="سرنخ وب", email="l@x.com", phone="۰۹۱۲۱۲۳۴۵۶۷", message="سلام")
        d = self.who("+989121234567")
        self.assertEqual(d["display"], "مشتری یک")                 # customers outrank prospects and website leads
        self.assertEqual({m["source"] for m in d["matches"]}, {"customer", "prospect", "lead"})
        self.assertTrue(d["known"])
        self.assertEqual(self.who("09121239999")["known"], False)       # same prefix, other number

    def test_history_and_synced_contacts(self):
        c = self.device_client()
        c.post(BASE + "contacts/sync/", {"contacts": [{"name": "داداش مهدی", "numbers": ["0912 000 1111", "09120002222"]}, {"name": "", "numbers": ["09123"]}]}, format="json")
        self.assertEqual(MobileContact.objects.count(), 2)
        d = self.who("09120001111", c)
        self.assertEqual(d["display"], "داداش مهدی")
        c.post(BASE + "calls/live/", {"number": "09120001111", "direction": "in"}, format="json")
        SmsMessage.objects.create(to_number="989120001111", body="x")
        d = self.who("09120001111", c)
        self.assertEqual((d["history"]["calls"], d["history"]["sms_out"]), (1, 1))
        self.assertIn("previous_call", {m["source"] for m in d["matches"]})
        # a re-sync replaces, DELETE clears
        self.assertEqual(c.post(BASE + "contacts/sync/", {"contacts": [{"name": "فقط یک", "numbers": ["09127778888"]}], "replace": True}, format="json").data["count"], 1)
        self.assertEqual(c.delete(BASE + "contacts/sync/").data["count"], 0)
        self.assertFalse(self.who("09120001111", c)["matches"] and self.who("09120001111", c)["display"])

    def test_synced_contacts_are_private_to_the_user_who_synced(self):
        a, b = self.device_client("marketer", "a"), self.device_client("boss", "b")
        a.post(BASE + "contacts/sync/", {"contacts": [{"name": "شخصی", "numbers": ["09127776666"]}]}, format="json")
        self.assertEqual(self.who("09127776666", b)["display"], None)
        self.assertEqual(self.who("09127776666", a)["display"], "شخصی")

    def test_growth_engine_leads_are_found_read_only(self):
        try:
            from apps.growth_engine.leads.models import ContactPoint, Lead as GLead
        except Exception:
            self.skipTest("growth engine not installed")
        lead = GLead.objects.create(business_name="کافه آزمون")
        ContactPoint.objects.create(lead=lead, kind="phone", value="09124443333", normalized="09124443333")
        before = (GLead.objects.count(), ContactPoint.objects.count())
        d = self.who("+98 912 444 3333")
        self.assertEqual((d["display"], d["matches"][0]["source"]), ("کافه آزمون", "growth_lead"))
        self.assertEqual((GLead.objects.count(), ContactPoint.objects.count()), before)

    def test_extra_source_can_be_registered_by_other_apps(self):
        def fake(user, norm, key):
            return [{"source": "custom", "name": "منبع سوم", "detail": "x", "store": "", "id": 1, "last_contact_at": None}] if key == "9121112222" else []

        callerid.register_source(fake)
        try:
            self.assertEqual(self.who("09121112222")["display"], "منبع سوم")
        finally:
            callerid._EXTRA_SOURCES.remove(fake)

    def test_bad_number_and_auth(self):
        self.assertEqual(self.device_client().get(BASE + "callerid/", {"number": "1"}).status_code, 400)
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(BASE + "callerid/", {"number": "09121234567"}).status_code, 401)
