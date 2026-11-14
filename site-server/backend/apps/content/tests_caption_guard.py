"""The caption quality gate: banned claims, broken numbers, repeats."""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.products.models import Product
from apps.stores.models import SalesAgentSettings, Store

from . import caption_guard
from .models import Caption


class _Cap:
    """The few fields the guard reads - the check needs no database row."""

    def __init__(self, short="", medium="", long="", cta="", hashtags=None):
        self.short_text, self.medium_text, self.long_text = short, medium, long
        self.cta, self.hashtags = cta, hashtags or []


def codes(cap, banned=None):
    return [w["code"] for w in caption_guard.check(cap, banned)]


class GuardRuleTests(SimpleTestCase):
    def test_a_clean_caption_has_no_warnings(self):
        cap = _Cap(medium="چغر پیش‌نویس برنامه را در کمتر از یک دقیقه می‌دهد؛ بازبینی با مربی است.",
                   hashtags=["#چغر", "#مربی"])
        self.assertEqual(caption_guard.check(cap, ["۹۸٪ رضایت"]), [])

    def test_banned_phrase_is_found_however_the_digits_are_typed(self):
        banned = ["۹۸٪ رضایت", "جایگزین مربی"]
        self.assertIn("banned", codes(_Cap(medium="با ۹۸٪ رضایتِ مربیان"), banned))
        self.assertIn("banned", codes(_Cap(medium="98% رضایت مربی‌ها"), banned))
        self.assertIn("banned", codes(_Cap(short="چغر جایگزينِ مربی است"), banned))

    def test_the_owners_own_sentence_is_not_a_false_alarm(self):
        # «جایگزین‌کردنِ مربی نیست» is the brand line; it is not «جایگزین مربی»
        cap = _Cap(medium="هدفِ ما جایگزین‌کردنِ مربی نیست.")
        self.assertNotIn("banned", codes(cap, ["جایگزین مربی"]))

    def test_a_price_that_lost_its_zeros_is_flagged(self):
        self.assertIn("broken_number", codes(_Cap(medium="۵۰ توکن = ۶۰۰٬۰۰ تومان")))
        self.assertIn("broken_number", codes(_Cap(medium="50 tokens = 600,00 toman")))
        self.assertNotIn("broken_number", codes(_Cap(medium="۵۰ توکن = ۶۰۰٬۰۰۰ تومان")))
        self.assertNotIn("broken_number", codes(_Cap(medium="ساعت ۱۹:۳۰ و نسخهٔ ۲.۵")))

    def test_a_sentence_printed_twice_in_a_row_is_flagged(self):
        self.assertIn("repeated", codes(_Cap(medium="شروع رایگان. لینک در بایو. لینک در بایو")))
        self.assertNotIn("repeated", codes(_Cap(medium="شروع رایگان. لینک در بایو. بازبینی با توست")))

    def test_emoji_is_flagged_but_plain_word_hashtags_are_not(self):
        self.assertIn("emoji", codes(_Cap(medium="😀" * 8)))
        self.assertNotIn("emoji", codes(_Cap(medium="😀" * 6)))
        # the model stores hashtags without «#»; the panel adds it when showing and copying
        self.assertEqual(codes(_Cap(hashtags=["چغر", "هوش مصنوعی", "#مربی"])), [])

    def test_each_warning_is_reported_once(self):
        cap = _Cap(short="۹۸٪ رضایت", medium="۹۸٪ رضایت", long="۹۸٪ رضایت")
        self.assertEqual(codes(cap, ["۹۸٪ رضایت"]).count("banned"), 1)


class CaptionApiWarningsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("cap-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغرِ آزمون")
        SalesAgentSettings.objects.create(store=self.store, never_say="۹۸٪ رضایت\nتضمین")
        self.product = Product.objects.create(store=self.store, name="سرویس", price=1)
        Caption.objects.create(
            store=self.store, product=self.product, platform="INSTAGRAM",
            medium_text="تضمینِ نتیجه! ۵۰ توکن = ۶۰۰٬۰۰ تومان",
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_the_list_carries_warnings_next_to_each_caption(self):
        r = self.api.get(f"/api/v1/products/{self.product.pk}/captions/")
        self.assertEqual(r.status_code, 200)
        got = {w["code"] for w in r.data[0]["warnings"]}
        # a price in the text also earns the «confirm the price» reminder
        self.assertEqual(got, {"banned", "broken_number", "price_check"})

    def test_more_than_thirty_captions_are_reachable(self):
        for i in range(34):
            Caption.objects.create(store=self.store, product=self.product, platform="INSTAGRAM", short_text=f"n{i}")
        r = self.api.get(f"/api/v1/products/{self.product.pk}/captions/")
        self.assertEqual(len(r.data), 35)
