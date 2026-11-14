"""Prices and stock typed the way a Persian keyboard produces them.

Live, on a copy of the database: `price: "-5000"` -> 201 stored; `"۳۰۰٬۰۰۰"`
-> 400 with a generic English sentence; `compare_at_price: 500` with
`price: 1000` -> 201 (a «was» price below the selling price). In the panel the
`<input type=number>` dropped Persian digits silently and left an empty box.

The browser half is `frontend/tests/number-input.test.ts`; this is the
server's, so a script, the mobile app or a paste that bypassed the field gets
the same forgiveness and the same Persian sentence about *that* field.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.common.numbers import fa_money, normalize_number_text, parse_decimal
from apps.stores.models import Store

from .models import Product, ProductVariant


class NormalizeTests(SimpleTestCase):
    def test_persian_arabic_and_latin_are_the_same_number(self):
        for typed in ("۳۰۰۰۰۰", "٣٠٠٠٠٠", "300000", "۳۰۰٬۰۰۰", "300,000", "۳۰۰،۰۰۰", " ۳۰۰ ۰۰۰ ", "3_00_000"):
            self.assertEqual(parse_decimal(typed), Decimal("300000"), typed)

    def test_decimals_and_signs(self):
        self.assertEqual(parse_decimal("۱٫۵"), Decimal("1.5"))
        self.assertEqual(parse_decimal("−۵"), Decimal("-5"))

    def test_words_and_garbage_are_not_numbers(self):
        for typed in ("سی هزار", "abc", "", "  ", None, True, "NaN", "Infinity", "۳x"):
            self.assertIsNone(parse_decimal(typed), repr(typed))

    def test_only_digit_like_characters_are_touched(self):
        self.assertEqual(normalize_number_text("سلام ۱۲"), "سلام12")

    def test_fa_money(self):
        self.assertEqual(fa_money(Decimal("300000.00")), "۳۰۰٬۰۰۰")
        self.assertEqual(fa_money("1200"), "۱٬۲۰۰")
        self.assertEqual(fa_money("x"), "")


class ProductNumberApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("num-owner", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه")
        self.client.force_authenticate(self.user)

    def post(self, **fields):
        return self.client.post(
            "/api/v1/products/", {"store": self.store.pk, "name": "کفش", **fields}, format="json",
        )

    def error(self, response, field):
        self.assertEqual(response.status_code, 400, response.content)
        message = response.json()[field][0]
        self.assertRegex(message, r"[؀-ۿ]", f"{field}: the message is not Persian: {message}")
        return message

    # ---- Persian digits -------------------------------------------------
    def test_persian_digits_and_separators_are_accepted(self):
        response = self.post(price="۳۰۰٬۰۰۰", stock_quantity="۱۲", cost_price="٢٠٠٬٠٠٠")
        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get(pk=response.json()["id"])
        self.assertEqual(product.price, Decimal("300000"))
        self.assertEqual(product.stock_quantity, 12)
        self.assertEqual(product.cost_price, Decimal("200000"))

    def test_latin_numbers_and_json_numbers_still_work(self):
        self.assertEqual(self.post(price="300000", stock_quantity=5).status_code, 201)
        self.assertEqual(self.post(price=1500.5, stock_quantity="7").status_code, 201)

    # ---- never negative -------------------------------------------------
    def test_a_negative_price_is_refused_in_persian(self):
        self.assertIn("منفی", self.error(self.post(price="-5000"), "price"))
        self.assertIn("منفی", self.error(self.post(price="-۵۰۰۰"), "price"))
        self.assertEqual(Product.objects.count(), 0)

    def test_a_negative_cost_or_stock_is_refused(self):
        self.assertIn("منفی", self.error(self.post(price="10", cost_price="-1"), "cost_price"))
        self.assertIn("منفی", self.error(self.post(stock_quantity="-3"), "stock_quantity"))

    def test_zero_is_fine(self):
        self.assertEqual(self.post(price="0", stock_quantity="0", cost_price="0").status_code, 201)

    # ---- non-numeric ----------------------------------------------------
    def test_a_non_number_says_which_field_and_what_to_type(self):
        message = self.error(self.post(price="سی هزار"), "price")
        self.assertIn("قیمت", message)
        self.assertIn("عدد", message)
        self.assertIn("موجودی", self.error(self.post(stock_quantity="دوازده"), "stock_quantity"))
        self.assertIn("عدد", self.error(self.post(price="12x"), "price"))

    def test_too_big_and_too_precise_say_so(self):
        self.assertIn("بزرگ", self.error(self.post(price="1" + "0" * 20), "price"))
        self.assertIn("اعشار", self.error(self.post(price="1.234"), "price"))

    # ---- compare-at price ----------------------------------------------
    def test_a_compare_at_price_must_be_above_the_selling_price(self):
        message = self.error(self.post(price="1000", compare_at_price="500"), "compare_at_price")
        self.assertIn("بیشتر", message)
        self.assertIn("۱٬۰۰۰", message)                       # says what it is being compared with
        self.error(self.post(price="1000", compare_at_price="1000"), "compare_at_price")
        self.assertEqual(self.post(price="1000", compare_at_price="۱٬۵۰۰").status_code, 201)

    def test_an_empty_compare_at_price_means_not_set(self):
        for empty in (None, "", "  "):
            self.assertEqual(self.post(price="1000", compare_at_price=empty).status_code, 201, repr(empty))

    def test_raising_the_price_over_an_existing_compare_at_price_is_refused_on_price(self):
        product = Product.objects.get(pk=self.post(price="1000", compare_at_price="1500").json()["id"])
        response = self.client.patch(f"/api/v1/products/{product.pk}/", {"price": "۲٬۰۰۰"}, format="json")
        message = self.error(response, "price")
        self.assertIn("قبل از تخفیف", message)

    def test_resending_an_unchanged_price_never_fails_old_data(self):
        """A product whose stored values already disagree (imported that way)
        must stay editable: the details form re-sends the price every time."""
        product = Product.objects.create(
            store=self.store, name="قدیمی", price=Decimal("1000"), compare_at_price=Decimal("900"),
        )
        response = self.client.patch(
            f"/api/v1/products/{product.pk}/", {"name": "قدیمیِ ویرایش‌شده", "price": "1000.00"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    # ---- variants -------------------------------------------------------
    def test_variants_get_the_same_treatment(self):
        product = Product.objects.get(pk=self.post(price="1000").json()["id"])
        url = f"/api/v1/products/{product.pk}/variants/"
        ok = self.client.post(url, {"name": "قرمز", "price_override": "۲٬۰۰۰", "stock_quantity": "۴"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(ProductVariant.objects.get(pk=ok.json()["id"]).price_override, Decimal("2000"))
        bad = self.client.post(url, {"name": "آبی", "price_override": "-1"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("منفی", bad.json()["price_override"][0])


class ModelValidatorTests(APITestCase):
    def test_the_model_itself_refuses_a_negative_price(self):
        """Admin forms and `full_clean` go through the model, not the API."""
        owner = User.objects.create_user("mv-owner", password="x")
        store = Store.objects.create(owner=owner, name="ف")
        product = Product(store=store, name="ن", price=Decimal("-1"))
        with self.assertRaises(ValidationError) as caught:
            product.full_clean()
        self.assertIn("price", caught.exception.message_dict)
